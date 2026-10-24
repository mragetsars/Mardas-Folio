use crate::process_tree::{self, ProcessTree};
use serde_json::{json, Value};
use std::{
    collections::{hash_map::Entry, HashMap},
    env,
    io::{self, BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex, Weak,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const CONTROL_TIMEOUT: Duration = Duration::from_secs(15);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(3);
const MAX_REQUEST_BYTES: usize = 64 * 1024 * 1024;
const MAX_RESPONSE_BYTES: usize = 128 * 1024 * 1024;
const MAX_LOG_BYTES: usize = 64 * 1024;
const MAX_PENDING_REQUESTS: usize = 16;
static NEXT_PROCESS_ID: AtomicU64 = AtomicU64::new(1);

type ResponseSender = mpsc::Sender<Value>;
type ManagedProcessSlot = Arc<Mutex<Option<(u64, Arc<SidecarProcess>)>>>;
type WeakManagedProcessSlot = Weak<Mutex<Option<(u64, Arc<SidecarProcess>)>>>;

struct RequestRegistry {
    accepting: bool,
    pending: HashMap<String, ResponseSender>,
}

impl RequestRegistry {
    fn new() -> Self {
        Self {
            accepting: true,
            pending: HashMap::new(),
        }
    }

    fn register(&mut self, key: String, sender: ResponseSender) -> Result<(), String> {
        if !self.accepting {
            return Err("The rendering engine is not running.".into());
        }
        if self.pending.len() >= MAX_PENDING_REQUESTS {
            return Err(
                "Too many rendering requests are already active; try again shortly.".into(),
            );
        }
        match self.pending.entry(key) {
            Entry::Vacant(entry) => {
                entry.insert(sender);
                Ok(())
            }
            Entry::Occupied(_) => {
                Err("A rendering request with the same ID is already active.".into())
            }
        }
    }

    fn remove(&mut self, key: &str) -> Option<ResponseSender> {
        self.pending.remove(key)
    }

    fn stop(&mut self) {
        self.accepting = false;
        self.pending.clear();
    }

    fn fail(&mut self, message: &str) {
        self.accepting = false;
        for (key, sender) in self.pending.drain() {
            let id = serde_json::from_str::<Value>(&key).unwrap_or(Value::Null);
            let _ = sender.send(json!({
                "jsonrpc": "2.0", "id": id,
                "error": {"code": -32010, "message": message,
                    "data": {"code": "MARDAS-SIDECAR-PROTOCOL"}}
            }));
        }
    }
}

pub(crate) struct SidecarProcess {
    instance_id: u64,
    child: Mutex<Child>,
    input: mpsc::SyncSender<Vec<u8>>,
    process_tree: ProcessTree,
    registry: Arc<Mutex<RequestRegistry>>,
}

impl SidecarProcess {
    fn start(app: &AppHandle, managed_slot: WeakManagedProcessSlot) -> Result<Arc<Self>, String> {
        let (program, arguments, working_dir) = resolve_sidecar(app)?;
        let mut command = Command::new(&program);
        command
            .args(arguments)
            .current_dir(&working_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("MARDAS_RUNTIME_ROOT", &working_dir);

        process_tree::configure(&mut command);

        let mut child = command
            .spawn()
            .map_err(|error| format!("Could not start Mardas rendering engine: {error}"))?;
        let process_tree = match ProcessTree::attach(&child) {
            Ok(tree) => tree,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!(
                    "Could not manage rendering engine subprocesses: {error}"
                ));
            }
        };
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "The rendering engine did not expose stdin.".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "The rendering engine did not expose stdout.".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "The rendering engine did not expose stderr.".to_string())?;

        let instance_id = next_process_id();
        let registry = Arc::new(Mutex::new(RequestRegistry::new()));
        let (input, queued_input) = mpsc::sync_channel::<Vec<u8>>(MAX_PENDING_REQUESTS);
        let client = Arc::new(Self {
            instance_id,
            child: Mutex::new(child),
            input,
            process_tree,
            registry: Arc::clone(&registry),
        });

        let writer_registry = Arc::clone(&registry);
        let writer_slot = managed_slot.clone();
        if let Err(error) = thread::Builder::new()
            .name("mardas-sidecar-stdin".into())
            .spawn(move || {
                write_input(stdin, queued_input, || {
                    stop_registry(&writer_registry);
                    invalidate_managed_process(&writer_slot, instance_id);
                });
            })
        {
            client.terminate();
            return Err(format!("Could not send rendering engine requests: {error}"));
        }

        let stdout_app = app.clone();
        let (ready_sender, ready_receiver) = mpsc::sync_channel(1);
        if let Err(error) = thread::Builder::new()
            .name("mardas-sidecar-stdout".into())
            .spawn(move || {
                read_stdout(
                    stdout_app,
                    stdout,
                    registry,
                    managed_slot,
                    instance_id,
                    ready_sender,
                )
            })
        {
            client.terminate();
            return Err(format!("Could not monitor the rendering engine: {error}"));
        }

        let stderr_app = app.clone();
        if let Err(error) = thread::Builder::new()
            .name("mardas-sidecar-stderr".into())
            .spawn(move || {
                read_logs(stderr, |line| {
                    let _ = stderr_app.emit("sidecar-log", json!({"level":"error","message":line}));
                });
            })
        {
            client.terminate();
            return Err(format!("Could not monitor rendering logs: {error}"));
        }

        match ready_receiver.recv_timeout(STARTUP_TIMEOUT) {
            Ok(Ok(())) => {}
            response => {
                client.terminate();
                return Err(match response {
                    Ok(Err(error)) => error,
                    Err(_) => "The rendering engine did not complete its startup handshake.".into(),
                    Ok(Ok(())) => unreachable!(),
                });
            }
        }

        Ok(client)
    }

    fn register_request(&self, key: String, sender: ResponseSender) -> Result<(), String> {
        self.registry
            .lock()
            .map_err(|_| "The rendering request registry is unavailable.".to_string())?
            .register(key, sender)
    }

    fn remove_request(&self, key: &str) {
        if let Ok(mut registry) = self.registry.lock() {
            registry.remove(key);
        }
    }

    fn mark_stopped(&self) {
        stop_registry(&self.registry);
    }

    fn is_alive(&self) -> bool {
        let accepting = self
            .registry
            .lock()
            .map(|registry| registry.accepting)
            .unwrap_or(false);
        if !accepting {
            return false;
        }
        let running = self
            .child
            .lock()
            .map(|mut child| matches!(child.try_wait(), Ok(None)))
            .unwrap_or(false);
        if !running {
            self.mark_stopped();
        }
        running
    }

    fn request(
        &self,
        request_id: Value,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        let key = response_key(&request_id)?;
        let (sender, receiver) = mpsc::channel();
        self.register_request(key.clone(), sender)?;
        let payload = json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        });
        let encoded = match encode_request(&payload) {
            Ok(encoded) => encoded,
            Err(error) => {
                self.remove_request(&key);
                return Err(error);
            }
        };
        // A pipe write can block forever when a failed engine stops reading.
        // The dedicated writer keeps queueing plus writing inside this timeout.
        if let Err(error) = self.input.try_send(encoded) {
            self.remove_request(&key);
            return Err(match error {
                mpsc::TrySendError::Full(_) => "The rendering engine input queue is full.".into(),
                mpsc::TrySendError::Disconnected(_) => {
                    "The rendering engine input is unavailable.".into()
                }
            });
        }

        let response = match receiver.recv_timeout(timeout) {
            Ok(response) => response,
            Err(error) => {
                self.terminate();
                return Err(match error {
                    mpsc::RecvTimeoutError::Timeout => {
                        "The rendering engine did not respond before the request timeout."
                            .to_string()
                    }
                    mpsc::RecvTimeoutError::Disconnected => {
                        "The rendering engine stopped before completing the request.".to_string()
                    }
                });
            }
        };

        if let Some(error) = response.get("error") {
            return Err(serde_json::to_string(error).unwrap_or_else(|_| error.to_string()));
        }
        response
            .get("result")
            .cloned()
            .ok_or_else(|| "The rendering engine returned a response without a result.".to_string())
    }

    pub(crate) fn request_method(
        &self,
        request_id: String,
        method: String,
        params: Value,
    ) -> Result<Value, String> {
        if method == "system.shutdown" || method == "job.cancel" {
            return Err("Control methods must use their dedicated desktop command.".into());
        }
        self.request(Value::String(request_id), &method, params, REQUEST_TIMEOUT)
    }

    pub(crate) fn cancel(&self, request_id: String) -> Result<Value, String> {
        let control_id = format!("desktop-cancel-{}", unique_suffix());
        self.request(
            Value::String(control_id),
            "job.cancel",
            json!({"request_id": request_id}),
            CONTROL_TIMEOUT,
        )
    }

    fn terminate(&self) {
        self.mark_stopped();
        self.process_tree.terminate();
        if let Ok(mut child) = self.child.lock() {
            match child.try_wait() {
                Ok(Some(_)) => {}
                _ => {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    }

    fn shutdown(&self) {
        if self.is_alive() {
            let _ = self.request(
                Value::String(format!("desktop-shutdown-{}", unique_suffix())),
                "system.shutdown",
                json!({"force": true}),
                CONTROL_TIMEOUT,
            );
        }
        if let Ok(mut child) = self.child.lock() {
            wait_for_exit(&mut child, SHUTDOWN_GRACE);
        }
        self.terminate();
    }
}

fn write_input(mut input: impl Write, queue: mpsc::Receiver<Vec<u8>>, on_failure: impl FnOnce()) {
    for encoded in queue {
        if input
            .write_all(&encoded)
            .and_then(|_| input.flush())
            .is_err()
        {
            on_failure();
            break;
        }
    }
}

fn read_stdout(
    app: AppHandle,
    stdout: impl std::io::Read,
    registry: Arc<Mutex<RequestRegistry>>,
    managed_slot: WeakManagedProcessSlot,
    instance_id: u64,
    ready_sender: mpsc::SyncSender<Result<(), String>>,
) {
    let mut ready_sender = Some(ready_sender);
    let outcome = read_protocol(
        stdout,
        || {
            if let Some(sender) = ready_sender.take() {
                let _ = sender.send(Ok(()));
            }
        },
        |payload| {
            if let Some(id) = payload.get("id") {
                if let Ok(key) = response_key(id) {
                    if let Ok(mut requests) = registry.lock() {
                        if let Some(sender) = requests.remove(&key) {
                            let _ = sender.send(payload);
                            return;
                        }
                    }
                }
            }
            match payload.get("method").and_then(Value::as_str) {
                Some("job.progress") => {
                    let _ = app.emit("sidecar-progress", &payload);
                }
                Some("system.ready") => {
                    let _ = app.emit("sidecar-ready", &payload);
                }
                Some(_) => {
                    let _ = app.emit("sidecar-notification", &payload);
                }
                None => {
                    let _ = app.emit(
                        "sidecar-log",
                        json!({"level":"warning","message":"Unmatched engine response"}),
                    );
                }
            }
        },
    );
    let message = outcome
        .err()
        .unwrap_or_else(|| "The rendering engine has stopped.".into());
    if let Some(sender) = ready_sender {
        let _ = sender.send(Err(message.clone()));
    }
    match registry.lock() {
        Ok(mut requests) => requests.fail(&message),
        Err(poisoned) => poisoned.into_inner().fail(&message),
    }
    let _ = app.emit("sidecar-log", json!({"level":"error","message":message}));
    invalidate_managed_process(&managed_slot, instance_id);
}

struct BoundedBuffer {
    bytes: Vec<u8>,
    limit: usize,
}

impl Write for BoundedBuffer {
    fn write(&mut self, value: &[u8]) -> io::Result<usize> {
        if value.len() > self.limit.saturating_sub(self.bytes.len()) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "JSON-RPC request exceeds the 64 MiB size limit.",
            ));
        }
        self.bytes.extend_from_slice(value);
        Ok(value.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn encode_request(payload: &Value) -> Result<Vec<u8>, String> {
    let mut output = BoundedBuffer {
        bytes: Vec::new(),
        limit: MAX_REQUEST_BYTES - 1,
    };
    serde_json::to_writer(&mut output, payload)
        .map_err(|error| format!("Could not encode rendering request: {error}"))?;
    output.bytes.push(b'\n');
    Ok(output.bytes)
}

fn read_frame(reader: &mut impl BufRead, limit: usize) -> Result<Option<Value>, String> {
    let mut bytes = Vec::new();
    reader
        .take((limit + 1) as u64)
        .read_until(b'\n', &mut bytes)
        .map_err(|error| format!("Could not read rendering engine response: {error}"))?;
    if bytes.is_empty() {
        return Ok(None);
    }
    if bytes.len() > limit {
        return Err("Rendering engine response exceeds the 128 MiB size limit.".into());
    }
    if bytes.last() != Some(&b'\n') {
        return Err("The rendering engine returned an incomplete response.".into());
    }
    let payload: Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("Invalid engine response: {error}"))?;
    if payload.get("jsonrpc").and_then(Value::as_str) != Some("2.0") {
        return Err("The rendering engine returned an invalid JSON-RPC envelope.".into());
    }
    if let Some(id) = payload.get("id") {
        response_key(id)?;
        if payload.get("result").is_some() == payload.get("error").is_some() {
            return Err("The rendering engine response must contain one result or error.".into());
        }
    } else if payload.get("method").and_then(Value::as_str).is_none()
        || !payload.get("params").is_some_and(Value::is_object)
    {
        return Err("The rendering engine returned an invalid notification.".into());
    }
    Ok(Some(payload))
}

fn validate_ready(payload: &Value) -> Result<(), String> {
    if payload.get("method").and_then(Value::as_str) != Some("system.ready")
        || payload.get("id").is_some()
        || payload.pointer("/params/protocol").and_then(Value::as_str) != Some("mardas-sidecar")
        || payload
            .pointer("/params/protocol_version")
            .and_then(Value::as_u64)
            != Some(1)
    {
        return Err("The rendering engine uses an incompatible startup protocol.".into());
    }
    Ok(())
}

fn read_protocol(
    input: impl Read,
    mut on_ready: impl FnMut(),
    mut on_payload: impl FnMut(Value),
) -> Result<(), String> {
    let mut reader = BufReader::new(input);
    let ready = read_frame(&mut reader, MAX_RESPONSE_BYTES)?
        .ok_or_else(|| "The rendering engine stopped before its startup handshake.".to_string())?;
    validate_ready(&ready)?;
    on_ready();
    on_payload(ready);
    while let Some(payload) = read_frame(&mut reader, MAX_RESPONSE_BYTES)? {
        on_payload(payload);
    }
    Ok(())
}

fn read_logs(input: impl Read, mut emit: impl FnMut(String)) {
    let mut reader = BufReader::new(input);
    let mut line = Vec::new();
    let mut truncated = false;
    loop {
        let available = match reader.fill_buf() {
            Ok(available) => available,
            Err(_) => break,
        };
        if available.is_empty() {
            if !line.is_empty() || truncated {
                emit(log_text(&line, truncated));
            }
            break;
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let count = newline.map_or(available.len(), |position| position + 1);
        let keep = count.min(MAX_LOG_BYTES.saturating_sub(line.len()));
        line.extend_from_slice(&available[..keep]);
        truncated |= keep < count;
        reader.consume(count);
        if newline.is_some() {
            emit(log_text(&line, truncated));
            line.clear();
            truncated = false;
        }
    }
}

fn log_text(bytes: &[u8], truncated: bool) -> String {
    let mut text = String::from_utf8_lossy(bytes)
        .trim_end_matches(['\r', '\n'])
        .to_string();
    if truncated {
        text.push_str(" [log line truncated]");
    }
    text
}

fn wait_for_exit(child: &mut Child, grace: Duration) -> bool {
    let deadline = Instant::now() + grace;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return true,
            Err(_) => return false,
            Ok(None) if Instant::now() >= deadline => return false,
            Ok(None) => thread::sleep(Duration::from_millis(10)),
        }
    }
}

fn stop_registry(registry: &Arc<Mutex<RequestRegistry>>) {
    match registry.lock() {
        Ok(mut registry) => registry.stop(),
        Err(poisoned) => poisoned.into_inner().stop(),
    }
}

fn take_matching_process<T>(slot: &mut Option<(u64, T)>, instance_id: u64) -> Option<T> {
    if slot
        .as_ref()
        .is_some_and(|(current_id, _)| *current_id == instance_id)
    {
        slot.take().map(|(_, process)| process)
    } else {
        None
    }
}

fn invalidate_managed_process(slot: &WeakManagedProcessSlot, instance_id: u64) {
    let Some(slot) = slot.upgrade() else {
        return;
    };
    let stale = match slot.lock() {
        Ok(mut slot) => take_matching_process(&mut slot, instance_id),
        Err(poisoned) => {
            let mut slot = poisoned.into_inner();
            take_matching_process(&mut slot, instance_id)
        }
    };
    if let Some(process) = stale {
        process.terminate();
    }
}

fn response_key(value: &Value) -> Result<String, String> {
    if value.is_string() || value.is_i64() || value.is_u64() {
        serde_json::to_string(value).map_err(|error| error.to_string())
    } else {
        Err("Request IDs must be strings or numbers.".into())
    }
}

fn next_process_id() -> u64 {
    NEXT_PROCESS_ID.fetch_add(1, Ordering::Relaxed)
}

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default()
}

fn resolve_sidecar(app: &AppHandle) -> Result<(PathBuf, Vec<String>, PathBuf), String> {
    if let Some(path) = env::var_os("MARDAS_SIDECAR_PATH") {
        let executable = PathBuf::from(path);
        return validate_sidecar_path(executable);
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Could not resolve application resources: {error}"))?;
    let bundled = resource_dir.join("sidecar").join(sidecar_filename());
    if bundled.is_file() {
        return validate_sidecar_path(bundled);
    }

    if cfg!(debug_assertions) || env::var_os("MARDAS_ALLOW_DEV_SIDECAR").is_some() {
        let python = env::var_os("MARDAS_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(if cfg!(windows) {
                    "python.exe"
                } else {
                    "python3"
                })
            });
        let cwd = env::current_dir().map_err(|error| error.to_string())?;
        return Ok((
            python,
            vec!["-m".into(), "mardas_folio.sidecar".into()],
            cwd,
        ));
    }

    Err(format!(
        "Bundled rendering engine is missing: {}",
        bundled.display()
    ))
}

fn validate_sidecar_path(executable: PathBuf) -> Result<(PathBuf, Vec<String>, PathBuf), String> {
    if !executable.is_file() {
        return Err(format!(
            "Configured rendering engine does not exist: {}",
            executable.display()
        ));
    }
    let working_dir = executable
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf();
    Ok((executable, Vec::new(), working_dir))
}

fn sidecar_filename() -> &'static str {
    if cfg!(windows) {
        "mardas-sidecar.exe"
    } else {
        "mardas-sidecar"
    }
}

pub struct ManagedSidecar {
    process: ManagedProcessSlot,
}

impl Default for ManagedSidecar {
    fn default() -> Self {
        Self {
            process: Arc::new(Mutex::new(None)),
        }
    }
}

impl ManagedSidecar {
    pub(crate) fn process(&self, app: &AppHandle) -> Result<Arc<SidecarProcess>, String> {
        let mut slot = self
            .process
            .lock()
            .map_err(|_| "The rendering engine state is unavailable.".to_string())?;
        if let Some((_, process)) = slot.as_ref() {
            if process.is_alive() {
                return Ok(Arc::clone(process));
            }
        }
        if let Some((_, stale)) = slot.take() {
            stale.terminate();
        }
        let process = SidecarProcess::start(app, Arc::downgrade(&self.process))?;
        if !process.is_alive() {
            process.terminate();
            return Err("The rendering engine stopped while it was starting.".into());
        }
        *slot = Some((process.instance_id, Arc::clone(&process)));
        Ok(process)
    }

    pub fn cancel(&self, request_id: String) -> Result<Value, String> {
        let process = self
            .process
            .lock()
            .map_err(|_| "The rendering engine state is unavailable.".to_string())?
            .as_ref()
            .map(|(_, process)| Arc::clone(process));
        match process.filter(|process| process.is_alive()) {
            Some(process) => process.cancel(request_id),
            None => Ok(json!({"request_id": request_id, "cancel_requested": false})),
        }
    }

    pub fn shutdown(&self) {
        let process = self
            .process
            .lock()
            .ok()
            .and_then(|mut slot| slot.take().map(|(_, process)| process));
        if let Some(process) = process {
            process.shutdown();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duplicate_request_id_preserves_the_original_waiter() {
        let mut registry = RequestRegistry::new();
        let (first_sender, first_receiver) = mpsc::channel();
        let (duplicate_sender, duplicate_receiver) = mpsc::channel();

        registry
            .register("same-id".into(), first_sender)
            .expect("first request should register");
        let error = registry
            .register("same-id".into(), duplicate_sender)
            .expect_err("duplicate request IDs must be rejected");
        assert!(error.contains("same ID"));

        let response = json!({"jsonrpc":"2.0","id":"same-id","result":{"ok":true}});
        registry
            .remove("same-id")
            .expect("original sender must remain registered")
            .send(response.clone())
            .expect("original receiver should still be connected");
        let received = first_receiver
            .recv_timeout(Duration::from_millis(100))
            .expect("original response should be delivered");
        assert_eq!(received, response);
        assert!(matches!(
            duplicate_receiver.try_recv(),
            Err(mpsc::TryRecvError::Disconnected)
        ));
    }

    #[test]
    fn stopping_registry_disconnects_pending_requests_and_rejects_new_ones() {
        let registry = Arc::new(Mutex::new(RequestRegistry::new()));
        let (sender, receiver) = mpsc::channel();
        registry
            .lock()
            .expect("registry lock")
            .register("pending".into(), sender)
            .expect("request should register");

        stop_registry(&registry);

        assert!(matches!(
            receiver.recv_timeout(Duration::from_millis(100)),
            Err(mpsc::RecvTimeoutError::Disconnected)
        ));
        let (sender, _receiver) = mpsc::channel();
        let error = registry
            .lock()
            .expect("registry lock")
            .register("after-stop".into(), sender)
            .expect_err("a stopped process must not accept requests");
        assert!(error.contains("not running"));
    }

    #[test]
    fn stale_eof_cannot_invalidate_a_replacement_process() {
        let mut slot = Some((2, "replacement"));
        assert_eq!(take_matching_process(&mut slot, 1), None);
        assert_eq!(slot, Some((2, "replacement")));
        assert_eq!(take_matching_process(&mut slot, 2), Some("replacement"));
        assert_eq!(slot, None);
    }

    #[test]
    fn request_timeout_is_bounded_well_below_the_previous_hour() {
        assert_eq!(REQUEST_TIMEOUT, Duration::from_secs(10 * 60));
        assert!(REQUEST_TIMEOUT < Duration::from_secs(60 * 60));
        assert!(CONTROL_TIMEOUT < REQUEST_TIMEOUT);
    }

    #[test]
    fn response_frame_limit_stops_without_reading_an_unbounded_line() {
        let mut reader = io::Cursor::new(vec![b'x'; 1024]);
        assert!(read_frame(&mut reader, 32)
            .unwrap_err()
            .contains("size limit"));
        assert_eq!(reader.position(), 33);
    }

    #[test]
    fn incomplete_wrong_version_and_ambiguous_responses_are_rejected() {
        for frame in [
            "{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":true}",
            "{\"jsonrpc\":\"1.0\",\"id\":1,\"result\":true}\n",
            "{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":true,\"error\":{}}\n",
            "{\"jsonrpc\":\"2.0\",\"id\":0.5,\"result\":true}\n",
        ] {
            assert!(
                read_frame(&mut io::Cursor::new(frame), 1024).is_err(),
                "{frame}"
            );
        }
    }

    #[test]
    fn startup_protocol_must_match_before_any_response_is_delivered() {
        let mut received = Vec::new();
        let mut ready = 0;
        let payload = json!({"jsonrpc":"2.0", "method":"system.ready", "params":{
            "protocol":"mardas-sidecar", "protocol_version": 1}});
        let response = json!({"jsonrpc":"2.0", "id":"health", "result":{}});
        let stream = format!("{payload}\n{response}\n");
        read_protocol(
            stream.as_bytes(),
            || ready += 1,
            |value| received.push(value),
        )
        .unwrap();
        assert_eq!(ready, 1);
        assert_eq!(received, vec![payload.clone(), response]);
        let mut wrong_version = payload.clone();
        wrong_version["params"]["protocol_version"] = json!(2);
        let mut wrong_protocol = payload.clone();
        wrong_protocol["params"]["protocol"] = json!("other-engine");
        let mut wrong_method = payload;
        wrong_method["method"] = json!("job.progress");
        for broken in [wrong_version, wrong_protocol, wrong_method] {
            assert!(read_protocol(
                format!("{broken}\n").as_bytes(),
                || panic!("incompatible handshake"),
                |_| panic!("incompatible response")
            )
            .is_err());
        }
        assert!(read_protocol(b"".as_slice(), || panic!("empty handshake"), |_| {}).is_err());
    }

    #[test]
    fn log_reader_drains_oversized_and_invalid_utf8_lines_then_continues() {
        let mut input = vec![b'x'; MAX_LOG_BYTES + 500];
        input.extend_from_slice(b"\ninvalid \xff\nnext line\n");
        let mut logs = Vec::new();
        read_logs(input.as_slice(), |line| logs.push(line));
        assert_eq!(logs.len(), 3);
        assert!(logs[0].ends_with("[log line truncated]"));
        assert_eq!(logs[0].len(), MAX_LOG_BYTES + " [log line truncated]".len());
        assert_eq!(logs[1], "invalid \u{fffd}");
        assert_eq!(logs[2], "next line");
    }

    #[test]
    fn bounded_serializer_counts_escaped_utf8_bytes() {
        let mut buffer = BoundedBuffer {
            bytes: Vec::new(),
            limit: 10,
        };
        assert!(serde_json::to_writer(&mut buffer, &json!("\0\0")).is_err());
        assert!(buffer.bytes.len() <= 10);
        let output = encode_request(&json!({"content":"متن\n"})).unwrap();
        assert_eq!(output.last(), Some(&b'\n'));
        assert_eq!(
            serde_json::from_slice::<Value>(&output).unwrap()["content"],
            "متن\n"
        );
    }

    #[test]
    fn protocol_failure_returns_a_structured_error_to_every_pending_request() {
        let mut registry = RequestRegistry::new();
        let (sender, receiver) = mpsc::channel();
        registry.register("\"document-1\"".into(), sender).unwrap();
        registry.fail("Rendering engine response exceeds the size limit.");
        let response = receiver.recv_timeout(Duration::from_millis(50)).unwrap();
        assert_eq!(response["id"], "document-1");
        assert_eq!(response["error"]["data"]["code"], "MARDAS-SIDECAR-PROTOCOL");
        assert!(registry.pending.is_empty());
        assert!(!registry.accepting);
    }

    #[test]
    fn too_many_pending_requests_do_not_grow_the_registry() {
        let mut registry = RequestRegistry::new();
        for index in 0..MAX_PENDING_REQUESTS {
            registry
                .register(index.to_string(), mpsc::channel().0)
                .unwrap();
        }
        assert!(registry
            .register("extra".into(), mpsc::channel().0)
            .is_err());
        assert_eq!(registry.pending.len(), MAX_PENDING_REQUESTS);
    }

    #[test]
    fn cancelling_an_absent_engine_does_not_start_a_new_process() {
        let sidecar = ManagedSidecar::default();
        assert_eq!(
            sidecar.cancel("finished".into()).unwrap(),
            json!({"request_id":"finished", "cancel_requested":false})
        );
        assert!(sidecar.process.lock().unwrap().is_none());
    }

    #[cfg(any(unix, windows))]
    #[test]
    fn graceful_shutdown_waits_for_cleanup_before_terminating() {
        // An engine acknowledges shutdown before its worker/browser cleanup ends.
        #[cfg(unix)]
        let mut child = Command::new("sh")
            .args(["-c", "sleep 0.05; exit 0"])
            .spawn()
            .unwrap();
        #[cfg(windows)]
        let mut child = windows_fixture("cleanup").spawn().unwrap();
        #[cfg(windows)]
        let _tree = ProcessTree::attach(&child).unwrap();
        let started = Instant::now();
        assert!(wait_for_exit(&mut child, Duration::from_secs(1)));
        assert!(started.elapsed() >= Duration::from_millis(20));
        assert!(child.try_wait().unwrap().unwrap().success());
    }

    #[cfg(windows)]
    fn windows_fixture(role: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "process_tree::windows_tests::child_fixture",
                "--nocapture",
            ])
            .env("MARDAS_PROCESS_TREE_TEST_ROLE", role)
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        process_tree::configure(&mut command);
        command
    }

    #[cfg(any(unix, windows))]
    #[test]
    fn request_timeout_includes_a_blocked_pipe_write() {
        #[cfg(unix)]
        let mut command = Command::new("sh");
        #[cfg(unix)]
        command.args(["-c", "sleep 30"]).stdin(Stdio::piped());
        #[cfg(windows)]
        let mut command = windows_fixture("leaf");
        command.stdin(Stdio::piped());
        process_tree::configure(&mut command);
        let mut child = command.spawn().unwrap();
        let process_tree = ProcessTree::attach(&child).unwrap();
        let stdin = child.stdin.take().unwrap();
        let (input, queue) = mpsc::sync_channel(MAX_PENDING_REQUESTS);
        let registry = Arc::new(Mutex::new(RequestRegistry::new()));
        let writer_registry = Arc::clone(&registry);
        let writer =
            thread::spawn(move || write_input(stdin, queue, || stop_registry(&writer_registry)));
        let client = SidecarProcess {
            instance_id: 0,
            child: Mutex::new(child),
            input,
            process_tree,
            registry,
        };
        let started = Instant::now();
        let error = client
            .request(
                json!("blocked"),
                "document.save",
                json!({"content":"x".repeat(2 * 1024 * 1024)}),
                Duration::from_millis(40),
            )
            .unwrap_err();
        assert!(error.contains("timeout"), "{error}");
        assert!(started.elapsed() < Duration::from_secs(2));
        writer.join().unwrap();
        assert!(!client.is_alive());
    }
}
