// A release build is a windowed program, so link it against the Windows GUI
// subsystem. Without this the launcher also owns a console: a terminal opens
// beside the window, and closing that terminal takes the application with it.
// Debug builds keep the console so `cargo run` can still print.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;
mod updates;

use serde_json::{json, Value};
use sidecar::ManagedSidecar;
use std::{
    env,
    ffi::OsString,
    path::{Path, PathBuf},
    process::Command,
    sync::Mutex,
};
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Default)]
struct LaunchFiles(Mutex<Vec<String>>);

fn markdown_paths<I>(arguments: I, cwd: Option<&Path>) -> Vec<String>
where
    I: IntoIterator<Item = OsString>,
{
    arguments
        .into_iter()
        .filter_map(|argument| {
            let path = PathBuf::from(argument);
            let resolved = if path.is_absolute() {
                path
            } else if let Some(root) = cwd {
                root.join(path)
            } else {
                path
            };
            let extension = resolved.extension()?.to_string_lossy().to_ascii_lowercase();
            if extension != "md" && extension != "markdown" {
                return None;
            }
            resolved
                .canonicalize()
                .ok()
                .map(|value| value.to_string_lossy().into_owned())
        })
        .collect()
}

fn queue_launch_files(app: &AppHandle, files: Vec<String>) {
    if files.is_empty() {
        return;
    }
    if let Some(state) = app.try_state::<LaunchFiles>() {
        if let Ok(mut queued) = state.0.lock() {
            for file in &files {
                if !queued.contains(file) {
                    queued.push(file.clone());
                }
            }
        }
    }
    let _ = app.emit("desktop-open-files", &files);
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn desktop_info(app: AppHandle) -> Value {
    json!({
        "name": app.package_info().name,
        "version": app.package_info().version.to_string(),
        "native_shell": true,
        "local_http_server": false,
    })
}

#[tauri::command]
fn take_launch_files(state: State<'_, LaunchFiles>) -> Result<Vec<String>, String> {
    let mut queued = state
        .0
        .lock()
        .map_err(|_| "Could not access files queued for opening.".to_string())?;
    Ok(std::mem::take(&mut *queued))
}

#[tauri::command]
fn pick_markdown_file() -> Option<String> {
    rfd::FileDialog::new()
        .add_filter("Markdown", &["md", "markdown"])
        .pick_file()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn pick_markdown_files() -> Vec<String> {
    rfd::FileDialog::new()
        .add_filter("Markdown", &["md", "markdown"])
        .pick_files()
        .unwrap_or_default()
        .into_iter()
        .map(|path| path.to_string_lossy().into_owned())
        .collect()
}

#[tauri::command(rename_all = "snake_case")]
fn pick_markdown_output(suggested_path: Option<String>) -> Option<String> {
    let mut dialog = rfd::FileDialog::new().add_filter("Markdown", &["md", "markdown"]);
    if let Some(suggested) = suggested_path.filter(|value| !value.trim().is_empty()) {
        let path = PathBuf::from(suggested);
        if let Some(parent) = path.parent().filter(|candidate| candidate.is_dir()) {
            dialog = dialog.set_directory(parent);
        }
        if let Some(name) = path.file_name().and_then(|value| value.to_str()) {
            dialog = dialog.set_file_name(name);
        }
    }
    dialog
        .save_file()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command(rename_all = "snake_case")]
fn pick_text_output(suggested_path: Option<String>) -> Option<String> {
    let mut dialog = rfd::FileDialog::new().add_filter(
        "Editable text",
        &["txt", "toml", "json", "yaml", "yml", "bib"],
    );
    if let Some(suggested) = suggested_path.filter(|value| !value.trim().is_empty()) {
        let path = PathBuf::from(suggested);
        if let Some(parent) = path.parent().filter(|candidate| candidate.is_dir()) {
            dialog = dialog.set_directory(parent);
        }
        if let Some(name) = path.file_name().and_then(|value| value.to_str()) {
            dialog = dialog.set_file_name(name);
        }
    }
    dialog
        .save_file()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn pick_project_directory() -> Option<String> {
    rfd::FileDialog::new()
        .pick_folder()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn pick_document_asset() -> Option<String> {
    rfd::FileDialog::new()
        .add_filter(
            "Images and references",
            &[
                "png", "jpg", "jpeg", "webp", "gif", "svg", "avif", "bmp", "bib", "json", "yaml",
                "yml",
            ],
        )
        .pick_file()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn pick_support_bundle_output() -> Option<String> {
    rfd::FileDialog::new()
        .add_filter("ZIP archive", &["zip"])
        .set_file_name("Mardas-Folio-Support.zip")
        .save_file()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command(rename_all = "snake_case")]
fn pick_pdf_output(suggested_path: Option<String>) -> Option<String> {
    let mut dialog = rfd::FileDialog::new().add_filter("PDF document", &["pdf"]);
    if let Some(suggested) = suggested_path.filter(|value| !value.trim().is_empty()) {
        let path = PathBuf::from(suggested);
        if let Some(parent) = path.parent().filter(|candidate| candidate.is_dir()) {
            dialog = dialog.set_directory(parent);
        }
        if let Some(name) = path.file_name().and_then(|value| value.to_str()) {
            dialog = dialog.set_file_name(name);
        }
    }
    dialog
        .save_file()
        .map(|path| path.to_string_lossy().into_owned())
}

fn existing_path(value: &str) -> Result<PathBuf, String> {
    PathBuf::from(value)
        .canonicalize()
        .map_err(|error| format!("Could not access path: {error}"))
}

fn launch_path(path: &Path, reveal: bool) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("explorer.exe");
        if reveal && path.is_file() {
            command.arg(format!("/select,{}", path.display()));
        } else {
            command.arg(if reveal {
                path.parent().unwrap_or(path)
            } else {
                path
            });
        }
        command
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        if reveal {
            command.arg("-R");
        }
        command.arg(path);
        command
    };

    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(if reveal {
            path.parent().unwrap_or(path)
        } else {
            path
        });
        command
    };

    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not open path: {error}"))
}

#[tauri::command]
fn allow_document_images(app: AppHandle, path: String) -> Result<(), String> {
    // Local images render in the editor through the asset protocol, whose scope
    // starts empty. Only the directory holding the open document is added, and
    // only non-recursively, so opening a file never exposes the tree beneath
    // it — let alone the rest of the filesystem — to the webview.
    let document = PathBuf::from(&path);
    if !document.is_absolute() {
        return Err("Document path must be absolute.".into());
    }
    let directory = document
        .parent()
        .ok_or_else(|| "Document has no parent directory.".to_string())?;
    let directory = directory
        .canonicalize()
        .map_err(|error| format!("Could not resolve document directory: {error}"))?;
    if !directory.is_dir() {
        return Err("Document directory does not exist.".into());
    }
    app.asset_protocol_scope()
        .allow_directory(&directory, false)
        .map_err(|error| format!("Could not allow document images: {error}"))
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    let resolved = existing_path(&path)?;
    launch_path(&resolved, false)
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    let resolved = existing_path(&path)?;
    launch_path(&resolved, true)
}

#[tauri::command(rename_all = "snake_case")]
async fn sidecar_request(
    app: AppHandle,
    state: State<'_, ManagedSidecar>,
    request_id: String,
    method: String,
    params: Value,
) -> Result<Value, String> {
    let process = state.inner().process(&app)?;
    tauri::async_runtime::spawn_blocking(move || process.request_method(request_id, method, params))
        .await
        .map_err(|error| format!("Rendering task failed to join: {error}"))?
}

#[tauri::command(rename_all = "snake_case")]
async fn sidecar_cancel(
    app: AppHandle,
    state: State<'_, ManagedSidecar>,
    request_id: String,
) -> Result<Value, String> {
    let process = state.inner().process(&app)?;
    tauri::async_runtime::spawn_blocking(move || process.cancel(request_id))
        .await
        .map_err(|error| format!("Cancellation task failed to join: {error}"))?
}

fn main() {
    let initial_files = markdown_paths(env::args_os().skip(1), env::current_dir().ok().as_deref());
    let single_instance = tauri_plugin_single_instance::init(|app, argv, cwd| {
        let files = markdown_paths(
            argv.into_iter().skip(1).map(OsString::from),
            Some(Path::new(&cwd)),
        );
        queue_launch_files(app, files);
    });

    let app = tauri::Builder::default()
        // Single-instance must be the first plugin so second launches are intercepted early.
        .plugin(single_instance)
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(LaunchFiles(Mutex::new(initial_files)))
        .manage(ManagedSidecar::default())
        .invoke_handler(tauri::generate_handler![
            desktop_info,
            take_launch_files,
            pick_markdown_file,
            pick_markdown_files,
            pick_markdown_output,
            pick_text_output,
            pick_project_directory,
            pick_document_asset,
            pick_pdf_output,
            pick_support_bundle_output,
            open_path,
            allow_document_images,
            reveal_path,
            sidecar_request,
            sidecar_cancel,
            updates::updater_status,
            updates::updater_check,
            updates::updater_install,
        ])
        .setup(|app| {
            let queued = app
                .state::<LaunchFiles>()
                .0
                .lock()
                .map(|value| value.clone())
                .unwrap_or_default();
            if !queued.is_empty() {
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    queue_launch_files(&handle, queued);
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Mardas Folio");

    app.run(|app, event| match event {
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Opened { urls } => {
            let files = markdown_paths(
                urls.into_iter()
                    .filter_map(|url| url.to_file_path().ok())
                    .map(|path| path.into_os_string()),
                None,
            );
            queue_launch_files(app, files);
        }
        tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. } => {
            app.state::<ManagedSidecar>().shutdown();
        }
        _ => {}
    });
}
