mod desktop;
mod macro_deck;
mod updates;

use base64::{engine::general_purpose::STANDARD, Engine as _};
use semver::Version;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
    process::Command,
};
use tauri::{AppHandle, Manager};
use updates::{check_tool_updates, install_tool_updates};
use desktop::{get_app_preferences, handle_window_event, set_app_preferences, setup_desktop};
use macro_deck::run_macro_action;

#[derive(Clone, Debug, Deserialize, Serialize)]
struct ToolManifest {
    id: String,
    name: String,
    top_tab: String,
    #[serde(rename = "type")]
    tool_type: String,
    entry: String,
    #[serde(default)]
    icon: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    submenu_group: String,
    #[serde(default)]
    order: i64,
    #[serde(default = "default_enabled")]
    enabled: bool,
    #[serde(default = "default_version")]
    version: String,
    #[serde(default)]
    keywords: Vec<String>,
    #[serde(skip_deserializing)]
    source: String,
    #[serde(skip_deserializing)]
    has_html: bool,
}

#[derive(Clone, Debug)]
struct ToolRecord {
    manifest: ToolManifest,
    root: PathBuf,
}

fn default_enabled() -> bool {
    true
}

fn default_version() -> String {
    "0.0.0".to_string()
}

fn canonical_if_dir(path: PathBuf) -> Option<PathBuf> {
    if !path.is_dir() {
        return None;
    }
    fs::canonicalize(path).ok()
}

fn tool_roots(app: &AppHandle) -> Vec<(PathBuf, &'static str)> {
    let mut roots = Vec::new();

    if let Ok(data_dir) = app.path().app_data_dir() {
        if let Some(path) = canonical_if_dir(data_dir.join("tools")) {
            roots.push((path, "user"));
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        for candidate in [
            resource_dir.join("tools"),
            resource_dir.join("_up_").join("tools"),
        ] {
            if let Some(path) = canonical_if_dir(candidate) {
                roots.push((path, "builtin"));
            }
        }
    }

    let dev_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("tools");
    if let Some(path) = canonical_if_dir(dev_root) {
        roots.push((path, "builtin"));
    }

    roots
}

fn parsed_version(value: &str) -> Version {
    Version::parse(value.trim_start_matches('v')).unwrap_or_else(|_| Version::new(0, 0, 0))
}

fn read_tool_records(app: &AppHandle) -> Result<Vec<ToolRecord>, String> {
    let mut selected: HashMap<String, ToolRecord> = HashMap::new();

    for (root, source) in tool_roots(app) {
        let entries = fs::read_dir(&root)
            .map_err(|error| format!("도구 폴더를 읽지 못했습니다: {error}"))?;

        for entry in entries.flatten() {
            let tool_root = entry.path();
            if !tool_root.is_dir() {
                continue;
            }
            let manifest_path = tool_root.join("manifest.json");
            if !manifest_path.is_file() {
                continue;
            }

            let raw = match fs::read_to_string(&manifest_path) {
                Ok(raw) => raw,
                Err(_) => continue,
            };
            let mut manifest: ToolManifest = match serde_json::from_str(&raw) {
                Ok(manifest) => manifest,
                Err(_) => continue,
            };
            if !manifest.enabled {
                continue;
            }

            // web/index.html 폴백은 html 도구에만 적용한다. 예전에 HTML이었다가
            // 파이썬으로 옮긴 도구에 옛 index.html이 남아 있으면, 이 폴백이
            // internal_python 도구를 HTML 화면으로 가로채 버린다.
            let declared_html = tool_root.join(&manifest.entry);
            let fallback_html = tool_root.join("web").join("index.html");
            manifest.has_html = manifest.tool_type == "html"
                && (declared_html.is_file() || fallback_html.is_file());
            manifest.source = source.to_string();

            let should_replace = selected
                .get(&manifest.id)
                .map(|current| {
                    parsed_version(&manifest.version) > parsed_version(&current.manifest.version)
                        || (parsed_version(&manifest.version)
                            == parsed_version(&current.manifest.version)
                            && source == "user"
                            && current.manifest.source != "user")
                })
                .unwrap_or(true);

            if should_replace {
                selected.insert(
                    manifest.id.clone(),
                    ToolRecord {
                        manifest,
                        root: tool_root,
                    },
                );
            }
        }
    }

    let mut records: Vec<_> = selected.into_values().collect();
    records.sort_by(|left, right| {
        left.manifest
            .top_tab
            .cmp(&right.manifest.top_tab)
            .then(left.manifest.order.cmp(&right.manifest.order))
            .then(left.manifest.name.cmp(&right.manifest.name))
    });
    Ok(records)
}

fn find_tool(app: &AppHandle, tool_id: &str) -> Result<ToolRecord, String> {
    if tool_id.is_empty()
        || !tool_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        return Err("올바르지 않은 도구 ID입니다.".to_string());
    }

    read_tool_records(app)?
        .into_iter()
        .find(|record| record.manifest.id == tool_id)
        .ok_or_else(|| format!("도구를 찾을 수 없습니다: {tool_id}"))
}

fn checked_child(root: &Path, relative: &Path) -> Result<PathBuf, String> {
    let root = fs::canonicalize(root).map_err(|error| error.to_string())?;
    let candidate =
        fs::canonicalize(root.join(relative)).map_err(|error| format!("파일 없음: {error}"))?;
    if !candidate.starts_with(&root) {
        return Err("도구 폴더 바깥의 파일은 열 수 없습니다.".to_string());
    }
    Ok(candidate)
}

#[tauri::command]
fn list_tools(app: AppHandle) -> Result<Vec<ToolManifest>, String> {
    Ok(read_tool_records(&app)?
        .into_iter()
        .map(|record| record.manifest)
        .collect())
}

#[tauri::command]
fn read_tool_html(app: AppHandle, tool_id: String) -> Result<String, String> {
    let record = find_tool(&app, &tool_id)?;
    let relative = if record.manifest.tool_type == "html" {
        PathBuf::from(&record.manifest.entry)
    } else {
        PathBuf::from("web").join("index.html")
    };
    let html_path = checked_child(&record.root, &relative)?;
    fs::read_to_string(html_path).map_err(|error| format!("HTML 도구를 읽지 못했습니다: {error}"))
}

/// HTML 도구를 기본 브라우저의 별도 창으로 연다.
/// 프런트엔드에서 window.open으로 blob URL을 여는 방식은 WebView2에서 동작하지 않는다.
#[tauri::command]
fn open_tool_in_browser(app: AppHandle, tool_id: String) -> Result<(), String> {
    let record = find_tool(&app, &tool_id)?;
    let relative = if record.manifest.tool_type == "html" {
        PathBuf::from(&record.manifest.entry)
    } else {
        PathBuf::from("web").join("index.html")
    };
    let html_path = checked_child(&record.root, &relative)?;
    if !html_path.is_file() {
        return Err("도구 화면 파일을 찾지 못했습니다.".to_string());
    }
    macro_deck::open_with_default(&html_path.to_string_lossy())
}

fn bridge_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("bridge")
        .join("runner.py");
    if dev_path.is_file() {
        return Ok(dev_path);
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("리소스 폴더를 찾지 못했습니다: {error}"))?;
    for candidate in [
        resource_dir.join("bridge").join("runner.py"),
        resource_dir
            .join("_up_")
            .join("bridge")
            .join("runner.py"),
    ] {
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err("Python 도구 연결 모듈을 찾지 못했습니다.".to_string())
}

#[tauri::command]
fn run_native_tool(
    app: AppHandle,
    tool_id: String,
    payload: Value,
) -> Result<Value, String> {
    let record = find_tool(&app, &tool_id)?;
    if record.manifest.has_html {
        return Err("이 도구는 중앙 HTML 화면에서 실행됩니다.".to_string());
    }

    let runner = bridge_path(&app).ok();
    let payload_json =
        serde_json::to_string(&payload).map_err(|error| format!("입력값 오류: {error}"))?;
    let payload_encoded = STANDARD.encode(payload_json);

    let mut sidecar_candidates = Vec::new();
    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            sidecar_candidates.push(parent.join("bridge-runner.exe"));
        }
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        sidecar_candidates.push(resource_dir.join("bridge-runner.exe"));
        sidecar_candidates.push(resource_dir.join("binaries").join("bridge-runner.exe"));
    }
    let sidecar = sidecar_candidates
        .into_iter()
        .find(|candidate| candidate.is_file());

    let mut command = if let Some(sidecar) = sidecar {
        Command::new(sidecar)
    } else {
        let runner = runner
            .ok_or_else(|| "내장 Python 실행기와 개발용 연결 모듈을 찾지 못했습니다.".to_string())?;
        let mut command = Command::new("python");
        command.arg(runner);
        command
    };
    command
        .arg("--tool")
        .arg(&tool_id)
        .arg("--payload-b64")
        .arg(payload_encoded)
        .env(
            "JBEDU_TOOLS_ROOT",
            record.root.parent().unwrap_or(&record.root),
        )
        .env(
            "JBEDU_PROJECT_ROOT",
            record.root.parent().unwrap_or(&record.root),
        )
        .current_dir(record.root.parent().unwrap_or(&record.root));

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    let output = command
        .output()
        .map_err(|error| format!("Python 도구를 실행하지 못했습니다: {error}"))?;

    if !output.status.success() {
        let message = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if message.is_empty() {
            "도구 실행 중 오류가 발생했습니다.".to_string()
        } else {
            message
        });
    }

    serde_json::from_slice(&output.stdout)
        .or_else(|_| {
            Ok(json!({
                "ok": true,
                "message": String::from_utf8_lossy(&output.stdout).trim()
            }))
        })
        .map_err(|error: serde_json::Error| error.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // 중복 실행 방지: 이미 떠 있으면 새 창을 만들지 않고, 트레이에 숨어 있던
        // 기존 창을 꺼내서 앞으로 가져온다. 반드시 첫 번째 플러그인이어야 한다.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            desktop::focus_main_window(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(setup_desktop)
        .on_window_event(handle_window_event)
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            list_tools,
            read_tool_html,
            open_tool_in_browser,
            run_native_tool,
            check_tool_updates,
            install_tool_updates,
            get_app_preferences,
            set_app_preferences,
            run_macro_action
        ])
        .run(tauri::generate_context!())
        .expect("Tauri 애플리케이션 실행 실패");
}

