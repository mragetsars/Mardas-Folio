use serde_json::{json, Value};
use std::{
    collections::{hash_map::Entry, HashMap},
    env,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex, Weak,
    },
    thread,
    time::Duration,
};
use tauri::{AppHandle, Emitter, Manager};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const CONTROL_TIMEOUT: Duration = Duration::from_secs(15);
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
}

pub(crate) struct SidecarProcess {
    instance_id: u64,
    child: Mutex<Child>,
    stdin: Mutex<ChildStdin>,
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

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let mut child = command
            .spawn()
            .map_err(|error| format!("Could not start Mardas rendering engine: {error}"))?;
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
        let client = Arc::new(Self {
            instance_id,
            child: Mutex::new(child),
            stdin: Mutex::new(stdin),
            registry: Arc::clone(&registry),
        });

        let stdout_app = app.clone();
        if let Err(error) = thread::Builder::new()
            .name("mardas-sidecar-stdout".into())
            .spawn(move || read_stdout(stdout_app, stdout, registry, managed_slot, instance_id))
        {
            client.terminate();
            return Err(format!("Could not monitor the rendering engine: {error}"));
        }

        let stderr_app = app.clone();
        if let Err(error) = thread::Builder::new()
            .name("mardas-sidecar-stderr".into())
            .spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    let _ = stderr_app.emit("sidecar-log", json!({"level":"error","message":line}));
                }
            })
        {
            client.terminate();
            return Err(format!("Could not monitor rendering logs: {error}"));
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
        let encoded = match serde_json::to_string(&payload) {
            Ok(encoded) => encoded,
            Err(error) => {
                self.remove_request(&key);
                return Err(format!("Could not encode rendering request: {error}"));
            }
        };
        let write_result = self
            .stdin
            .lock()
            .map_err(|_| "The rendering engine input is unavailable.".to_string())
            .and_then(|mut input| {
                writeln!(input, "{encoded}")
                    .and_then(|_| input.flush())
                    .map_err(|error| format!("Could not send request to rendering engine: {error}"))
            });
        if let Err(error) = write_result {
            self.terminate();
            return Err(error);
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
        self.terminate();
    }
}

fn read_stdout(
    app: AppHandle,
    stdout: impl std::io::Read,
    registry: Arc<Mutex<RequestRegistry>>,
    managed_slot: WeakManagedProcessSlot,
    instance_id: u64,
) {
    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
        let payload: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(error) => {
                let _ = app.emit(
                    "sidecar-log",
                    json!({"level":"error","message":format!("Invalid engine response: {error}")}),
                );
                break;
            }
        };
        if let Some(id) = payload.get("id") {
            if let Ok(key) = response_key(id) {
                if let Ok(mut requests) = registry.lock() {
                    if let Some(sender) = requests.remove(&key) {
                        let _ = sender.send(payload);
                        continue;
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
    }
    stop_registry(&registry);
    let _ = app.emit(
        "sidecar-log",
        json!({"level":"error","message":"The rendering engine has stopped."}),
    );
    invalidate_managed_process(&managed_slot, instance_id);
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
    if value.is_string() || value.is_number() {
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

    pub fn request(
        &self,
        app: &AppHandle,
        request_id: String,
        method: String,
        params: Value,
    ) -> Result<Value, String> {
        self.process(app)?
            .request_method(request_id, method, params)
    }

    pub fn cancel(&self, app: &AppHandle, request_id: String) -> Result<Value, String> {
        self.process(app)?.cancel(request_id)
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
}
