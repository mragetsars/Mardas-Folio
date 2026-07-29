use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::Duration,
};
use tauri::{AppHandle, Emitter, Manager};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(60 * 60);
const CONTROL_TIMEOUT: Duration = Duration::from_secs(15);

pub(crate) struct SidecarProcess {
    child: Mutex<Child>,
    stdin: Mutex<ChildStdin>,
    pending: Arc<Mutex<HashMap<String, mpsc::Sender<Value>>>>,
}

impl SidecarProcess {
    fn start(app: &AppHandle) -> Result<Arc<Self>, String> {
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

        let pending = Arc::new(Mutex::new(HashMap::<String, mpsc::Sender<Value>>::new()));
        let client = Arc::new(Self {
            child: Mutex::new(child),
            stdin: Mutex::new(stdin),
            pending: Arc::clone(&pending),
        });

        let stdout_app = app.clone();
        thread::Builder::new()
            .name("mardas-sidecar-stdout".into())
            .spawn(move || read_stdout(stdout_app, stdout, pending))
            .map_err(|error| format!("Could not monitor the rendering engine: {error}"))?;

        let stderr_app = app.clone();
        thread::Builder::new()
            .name("mardas-sidecar-stderr".into())
            .spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    let _ = stderr_app.emit("sidecar-log", json!({"level":"error","message":line}));
                }
            })
            .map_err(|error| format!("Could not monitor rendering logs: {error}"))?;

        Ok(client)
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
        {
            let mut pending = self
                .pending
                .lock()
                .map_err(|_| "The rendering request registry is unavailable.".to_string())?;
            if pending.insert(key.clone(), sender).is_some() {
                return Err("A rendering request with the same ID is already active.".into());
            }
        }

        let payload = json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        });
        let encoded = serde_json::to_string(&payload)
            .map_err(|error| format!("Could not encode rendering request: {error}"))?;
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
            if let Ok(mut pending) = self.pending.lock() {
                pending.remove(&key);
            }
            return Err(error);
        }

        let response = receiver.recv_timeout(timeout).map_err(|error| {
            if let Ok(mut pending) = self.pending.lock() {
                pending.remove(&key);
            }
            match error {
                mpsc::RecvTimeoutError::Timeout => {
                    "The rendering engine did not respond before the request timeout.".to_string()
                }
                mpsc::RecvTimeoutError::Disconnected => {
                    "The rendering engine stopped before completing the request.".to_string()
                }
            }
        })?;

        if let Some(error) = response.get("error") {
            return Err(serde_json::to_string(error).unwrap_or_else(|_| error.to_string()));
        }
        response
            .get("result")
            .cloned()
            .ok_or_else(|| "The rendering engine returned a response without a result.".to_string())
    }

    pub(crate) fn request_method(&self, request_id: String, method: String, params: Value) -> Result<Value, String> {
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

    fn shutdown(&self) {
        let _ = self.request(
            Value::String(format!("desktop-shutdown-{}", unique_suffix())),
            "system.shutdown",
            json!({"force": true}),
            CONTROL_TIMEOUT,
        );
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
}

fn read_stdout(
    app: AppHandle,
    stdout: impl std::io::Read,
    pending: Arc<Mutex<HashMap<String, mpsc::Sender<Value>>>>,
) {
    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
        let payload: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(error) => {
                let _ = app.emit(
                    "sidecar-log",
                    json!({"level":"error","message":format!("Invalid engine response: {error}")}),
                );
                continue;
            }
        };
        if let Some(id) = payload.get("id") {
            if let Ok(key) = response_key(id) {
                if let Ok(mut requests) = pending.lock() {
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
    if let Ok(mut requests) = pending.lock() {
        requests.clear();
    }
    let _ = app.emit(
        "sidecar-log",
        json!({"level":"error","message":"The rendering engine has stopped."}),
    );
}

fn response_key(value: &Value) -> Result<String, String> {
    if value.is_string() || value.is_number() {
        serde_json::to_string(value).map_err(|error| error.to_string())
    } else {
        Err("Request IDs must be strings or numbers.".into())
    }
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
            .unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python.exe" } else { "python3" }));
        let cwd = env::current_dir().map_err(|error| error.to_string())?;
        return Ok((
            python,
            vec!["-m".into(), "mardas_md2pdf.sidecar".into()],
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

#[derive(Default)]
pub struct ManagedSidecar {
    process: Mutex<Option<Arc<SidecarProcess>>>,
}

impl ManagedSidecar {
    pub(crate) fn process(&self, app: &AppHandle) -> Result<Arc<SidecarProcess>, String> {
        let mut slot = self
            .process
            .lock()
            .map_err(|_| "The rendering engine state is unavailable.".to_string())?;
        if let Some(process) = slot.as_ref() {
            return Ok(Arc::clone(process));
        }
        let process = SidecarProcess::start(app)?;
        *slot = Some(Arc::clone(&process));
        Ok(process)
    }

    pub fn request(
        &self,
        app: &AppHandle,
        request_id: String,
        method: String,
        params: Value,
    ) -> Result<Value, String> {
        self.process(app)?.request_method(request_id, method, params)
    }

    pub fn cancel(&self, app: &AppHandle, request_id: String) -> Result<Value, String> {
        self.process(app)?.cancel(request_id)
    }

    pub fn shutdown(&self) {
        if let Ok(mut slot) = self.process.lock() {
            if let Some(process) = slot.take() {
                process.shutdown();
            }
        }
    }
}
