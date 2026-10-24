// A release build is a windowed program, so link it against the Windows GUI
// subsystem. Without this the launcher also owns a console: a terminal opens
// beside the window, and closing that terminal takes the application with it.
// Debug builds keep the console so `cargo run` can still print.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod process_tree;
mod sidecar;
mod updates;

use serde_json::{json, Value};
use sidecar::ManagedSidecar;
use std::{
    env,
    ffi::OsString,
    fs,
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

    let child = command
        .spawn()
        .map_err(|error| format!("Could not open path: {error}"))?;
    // Dropping Child does not reap an exited Unix process. Repeated open/reveal
    // actions otherwise accumulate zombie xdg-open/open helper processes.
    reap_launcher(child)
        .map(|_| ())
        .map_err(|error| format!("Could not monitor the file launcher: {error}"))
}

fn reap_launcher(mut child: std::process::Child) -> std::io::Result<std::thread::JoinHandle<()>> {
    std::thread::Builder::new()
        .name("mardas-file-launcher".into())
        .spawn(move || {
            let _ = child.wait();
        })
}

#[tauri::command]
async fn allow_document_images(
    app: AppHandle,
    path: String,
    sources: Option<Vec<String>>,
) -> Result<(), String> {
    let images = tauri::async_runtime::spawn_blocking(move || match sources {
        Some(sources) => referenced_document_images(Path::new(&path), &sources, 4096),
        None => document_image_paths(Path::new(&path), 4096),
    })
    .await
    .map_err(|error| format!("Could not inspect document images: {error}"))??;
    // Grant exact files, never a directory wildcard: imported assets and nested
    // image folders work without exposing document text or sibling secrets.
    let scope = app.asset_protocol_scope();
    for image in images {
        scope
            .allow_file(image)
            .map_err(|error| format!("Could not allow document image: {error}"))?;
    }
    Ok(())
}

fn referenced_document_images(
    document: &Path,
    sources: &[String],
    max_entries: usize,
) -> Result<Vec<PathBuf>, String> {
    use std::path::Component;
    if !document.is_absolute() || document.is_symlink() || !document.is_file() {
        return Err("Document must be an existing absolute regular file.".into());
    }
    if sources.len() > max_entries {
        return Err("Document image references exceed the allowed size.".into());
    }
    let directory = document
        .parent()
        .ok_or("Document has no parent directory.")?
        .canonicalize()
        .map_err(|error| format!("Could not resolve document directory: {error}"))?;
    let mut images = Vec::new();
    for source in sources {
        let normalized = source.replace('\\', "/");
        let relative = Path::new(&normalized);
        if normalized.is_empty()
            || normalized.contains('\0')
            || normalized
                .split('/')
                .next()
                .is_some_and(|part| part.contains(':'))
            || relative
                .components()
                .any(|part| !matches!(part, Component::Normal(_) | Component::CurDir))
        {
            continue;
        }
        let mut image = directory.clone();
        let mut safe = true;
        for component in relative.components() {
            image.push(component);
            if image.is_symlink() {
                safe = false;
                break;
            }
        }
        if !safe || !image.is_file() || !supported_image_path(&image) {
            continue;
        }
        if let Ok(canonical) = image.canonicalize() {
            if canonical.starts_with(&directory) {
                images.push(canonical);
            }
        }
    }
    images.sort();
    images.dedup();
    Ok(images)
}

fn supported_image_path(path: &Path) -> bool {
    path.extension().is_some_and(|extension| {
        matches!(
            extension.to_string_lossy().to_ascii_lowercase().as_str(),
            "png" | "jpg" | "jpeg" | "webp" | "gif" | "svg" | "avif" | "bmp" | "ico"
        )
    })
}

fn document_image_paths(document: &Path, max_entries: usize) -> Result<Vec<PathBuf>, String> {
    if !document.is_absolute() {
        return Err("Document path must be absolute.".into());
    }
    if document.is_symlink() || !document.is_file() {
        return Err("Document must be an existing regular file.".into());
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
    let mut pending = vec![(directory.clone(), 0usize)];
    let mut images = Vec::new();
    let mut inspected = 0usize;
    while let Some((folder, depth)) = pending.pop() {
        let entries = fs::read_dir(&folder)
            .map_err(|error| format!("Could not read image directory: {error}"))?;
        for entry in entries {
            let entry = entry.map_err(|error| format!("Could not read image path: {error}"))?;
            inspected += 1;
            if inspected > max_entries {
                return Err("Document image inventory exceeds the allowed size.".into());
            }
            let path = entry.path();
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.starts_with('.') || matches!(name.as_ref(), "node_modules" | "target" | "build")
            {
                continue;
            }
            let kind = entry
                .file_type()
                .map_err(|error| format!("Could not inspect image path: {error}"))?;
            if kind.is_symlink() {
                continue;
            }
            let canonical = path
                .canonicalize()
                .map_err(|error| format!("Could not resolve image path: {error}"))?;
            if !canonical.starts_with(&directory) {
                continue;
            }
            if kind.is_dir() && depth < 8 {
                pending.push((canonical, depth + 1));
            } else if kind.is_file() {
                if supported_image_path(&path) {
                    images.push(canonical);
                }
            }
        }
    }
    images.sort();
    images.dedup();
    Ok(images)
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
    request_id: String,
    method: String,
    params: Value,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.state::<ManagedSidecar>()
            .process(&app)?
            .request_method(request_id, method, params)
    })
    .await
    .map_err(|error| format!("Rendering task failed to join: {error}"))?
}

#[tauri::command(rename_all = "snake_case")]
async fn sidecar_cancel(app: AppHandle, request_id: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || app.state::<ManagedSidecar>().cancel(request_id))
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

#[cfg(test)]
mod image_scope_tests {
    use super::*;

    struct Fixture(PathBuf);

    impl Fixture {
        fn new() -> Self {
            let suffix = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let path = env::temp_dir().join(format!(
                "mardas-image-scope-{}-{suffix}",
                std::process::id()
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }

        fn file(&self, relative: &str) -> PathBuf {
            let path = self.0.join(relative);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, b"fixture").unwrap();
            path
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn nested_and_imported_images_are_allowed_without_sibling_text() {
        let fixture = Fixture::new();
        let document = fixture.file("book.md");
        let cover = fixture.file("cover.PNG").canonicalize().unwrap();
        let imported = fixture.file("assets/figure.png").canonicalize().unwrap();
        let nested = fixture
            .file("images/chapter/chart.svg")
            .canonicalize()
            .unwrap();
        fixture.file("secret.txt");
        fixture.file("assets/references.bib");
        fixture.file(".private/secret.png");
        fixture.file("node_modules/vendor.png");
        let mut expected = vec![cover, imported, nested];
        expected.sort();
        assert_eq!(document_image_paths(&document, 4096).unwrap(), expected);
    }

    #[test]
    fn oversized_inventory_fails_before_granting_any_paths() {
        let fixture = Fixture::new();
        let document = fixture.file("book.md");
        fixture.file("one.png");
        fixture.file("two.png");
        assert!(document_image_paths(&document, 2)
            .unwrap_err()
            .contains("allowed size"));
    }

    #[test]
    fn image_grants_inspect_only_references_not_unrelated_directory_entries() {
        let fixture = Fixture::new();
        let document = fixture.file("book.md");
        let referenced = fixture.file("assets/شکل یک.PNG").canonicalize().unwrap();
        fixture.file("unrelated/private.png");
        for index in 0..20 {
            fixture.file(&format!("unrelated/{index}.txt"));
        }
        let sources = vec!["assets/شکل یک.PNG".into(), "assets/شکل یک.PNG".into()];
        assert_eq!(
            referenced_document_images(&document, &sources, 2).unwrap(),
            vec![referenced]
        );
        assert!(referenced_document_images(&document, &[], 0)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn image_grants_reject_absolute_parent_uri_text_and_missing_sources() {
        let fixture = Fixture::new();
        let document = fixture.file("book.md");
        let image = fixture.file("cover.png");
        fixture.file("secret.txt");
        let sources = vec![
            "../cover.png".into(),
            "https://example.com/cover.png".into(),
            image.to_string_lossy().into_owned(),
            "C:\\private\\cover.png".into(),
            "secret.txt".into(),
            "missing.png".into(),
        ];
        assert!(referenced_document_images(&document, &sources, 10)
            .unwrap()
            .is_empty());
        assert!(referenced_document_images(&document, &sources, 2)
            .unwrap_err()
            .contains("allowed size"));
    }

    #[cfg(unix)]
    #[test]
    fn image_references_cannot_follow_symlinked_files_or_parent_folders() {
        use std::os::unix::fs::symlink;
        let fixture = Fixture::new();
        let outside = Fixture::new();
        let document = fixture.file("book.md");
        let outside_image = outside.file("secret.png");
        symlink(&outside_image, fixture.0.join("linked.png")).unwrap();
        symlink(&outside.0, fixture.0.join("linked-folder")).unwrap();
        let sources = vec!["linked.png".into(), "linked-folder/secret.png".into()];
        assert!(referenced_document_images(&document, &sources, 2)
            .unwrap()
            .is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn completed_file_launcher_is_reaped_before_the_app_exits() {
        unsafe extern "C" {
            fn waitpid(pid: i32, status: *mut i32, options: i32) -> i32;
        }
        let child = Command::new("sh").args(["-c", "exit 0"]).spawn().unwrap();
        let pid = child.id();
        reap_launcher(child).unwrap().join().unwrap();
        let mut status = 0;
        assert_eq!(unsafe { waitpid(pid as i32, &mut status, 1) }, -1);
        assert_eq!(std::io::Error::last_os_error().raw_os_error(), Some(10)); // ECHILD
    }

    #[cfg(unix)]
    #[test]
    fn symlinked_images_and_image_directories_are_not_allowed() {
        use std::os::unix::fs::symlink;
        let fixture = Fixture::new();
        let document = fixture.file("book.md");
        let outside = Fixture::new();
        let image = outside.file("private.png");
        symlink(&image, fixture.0.join("linked.png")).unwrap();
        symlink(&outside.0, fixture.0.join("linked-assets")).unwrap();
        assert!(document_image_paths(&document, 4096).unwrap().is_empty());
    }
}
