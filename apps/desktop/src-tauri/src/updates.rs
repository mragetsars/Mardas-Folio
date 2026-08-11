use serde::Serialize;
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use tauri_plugin_updater::UpdaterExt;
use url::Url;

const DEFAULT_ENDPOINT: &str =
    "https://github.com/mragetsars/Mardas-Folio/releases/latest/download/latest.json";
const UPDATE_TIMEOUT_SECS: u64 = 30;

#[derive(Clone, Serialize)]
pub struct UpdateStatus {
    pub configured: bool,
    pub current_version: String,
    pub channel: &'static str,
    pub endpoint: Option<String>,
    pub reason: Option<&'static str>,
}

#[derive(Clone, Serialize)]
pub struct UpdateCheck {
    pub available: bool,
    pub current_version: String,
    pub version: Option<String>,
    pub notes: Option<String>,
    pub pub_date: Option<String>,
}

#[derive(Clone, Serialize)]
struct UpdateProgress {
    event: &'static str,
    version: String,
    chunk_length: Option<usize>,
    content_length: Option<u64>,
}

fn compile_time_pubkey() -> Option<&'static str> {
    option_env!("MARDAS_UPDATER_PUBKEY")
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

fn compile_time_endpoint() -> &'static str {
    option_env!("MARDAS_UPDATE_ENDPOINT")
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(DEFAULT_ENDPOINT)
}

fn validated_endpoint() -> Result<Url, String> {
    let value = compile_time_endpoint();
    let parsed = Url::parse(value).map_err(|error| format!("Invalid update endpoint: {error}"))?;
    if parsed.scheme() != "https" || parsed.host_str().is_none() {
        return Err("Update endpoint must use HTTPS.".to_string());
    }
    if !parsed.username().is_empty() || parsed.password().is_some() || parsed.fragment().is_some() {
        return Err("Update endpoint must not contain credentials or fragments.".to_string());
    }
    Ok(parsed)
}

fn update_configuration(app: &AppHandle) -> Result<(&'static str, Url), String> {
    let pubkey = compile_time_pubkey()
        .ok_or_else(|| "Automatic updates are not configured for this build.".to_string())?;
    if pubkey.contains('\0') || pubkey.len() > 32 * 1024 {
        return Err("Embedded update public key is invalid.".to_string());
    }
    let endpoint = validated_endpoint()?;
    if app.package_info().version.to_string().trim().is_empty() {
        return Err("Application version is unavailable.".to_string());
    }
    Ok((pubkey, endpoint))
}

pub fn status(app: &AppHandle) -> UpdateStatus {
    let current_version = app.package_info().version.to_string();
    match update_configuration(app) {
        Ok((_, endpoint)) => UpdateStatus {
            configured: true,
            current_version,
            channel: "stable",
            endpoint: Some(endpoint.to_string()),
            reason: None,
        },
        Err(_) => UpdateStatus {
            configured: false,
            current_version,
            channel: "stable",
            endpoint: None,
            reason: Some("not_configured"),
        },
    }
}

async fn check_internal(app: &AppHandle) -> Result<Option<tauri_plugin_updater::Update>, String> {
    let (pubkey, endpoint) = update_configuration(app)?;
    app.updater_builder()
        .pubkey(pubkey)
        .endpoints(vec![endpoint])
        .map_err(|error| format!("Could not configure update endpoint: {error}"))?
        .timeout(Duration::from_secs(UPDATE_TIMEOUT_SECS))
        .build()
        .map_err(|error| format!("Could not initialize updater: {error}"))?
        .check()
        .await
        .map_err(|error| format!("Could not check for updates: {error}"))
}

#[tauri::command]
pub fn updater_status(app: AppHandle) -> UpdateStatus {
    status(&app)
}

#[tauri::command]
pub async fn updater_check(app: AppHandle) -> Result<UpdateCheck, String> {
    let current_version = app.package_info().version.to_string();
    let update = check_internal(&app).await?;
    Ok(match update {
        Some(update) => UpdateCheck {
            available: true,
            current_version,
            version: Some(update.version.to_string()),
            notes: update.body,
            pub_date: update.date.map(|value| value.to_string()),
        },
        None => UpdateCheck {
            available: false,
            current_version,
            version: None,
            notes: None,
            pub_date: None,
        },
    })
}

#[tauri::command]
pub async fn updater_install(app: AppHandle, expected_version: String) -> Result<bool, String> {
    let expected_version = expected_version.trim().to_string();
    if expected_version.is_empty() || expected_version.len() > 128 {
        return Err("Expected update version is invalid.".to_string());
    }

    let update = check_internal(&app)
        .await?
        .ok_or_else(|| "No update is currently available.".to_string())?;

    if update.version.to_string() != expected_version {
        return Err("The available update changed; check for updates again.".to_string());
    }

    let version = update.version.to_string();
    let progress_app = app.clone();
    let finished_app = app.clone();
    update
        .download_and_install(
            move |chunk_length, content_length| {
                let _ = progress_app.emit(
                    "desktop-update-progress",
                    UpdateProgress {
                        event: "progress",
                        version: version.clone(),
                        chunk_length: Some(chunk_length),
                        content_length,
                    },
                );
            },
            move || {
                let _ = finished_app.emit(
                    "desktop-update-progress",
                    UpdateProgress {
                        event: "finished",
                        version: expected_version.clone(),
                        chunk_length: None,
                        content_length: None,
                    },
                );
            },
        )
        .await
        .map_err(|error| format!("Could not install update: {error}"))?;
    Ok(true)
}
