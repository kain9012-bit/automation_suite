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
    /// 이 블록이 있는 도구만 탐색기 우클릭 메뉴에 등록할 수 있다.
    #[serde(default)]
    context_menu: Option<ContextMenuSpec>,
    #[serde(skip_deserializing)]
    source: String,
    #[serde(skip_deserializing)]
    has_html: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct ContextMenuSpec {
    /// 확장자 목록(["pdf", "xlsx"]) 또는 ["folder"]
    targets: Vec<String>,
    label: String,
    #[serde(default)]
    multiple: bool,
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

// ── 탐색기 우클릭 메뉴 ───────────────────────────────────────────────
// HKCU에만 쓰므로 관리자 권한이 필요 없다. 키 이름을 이 접두어로 시작하게 두면
// 프로그램을 제거할 때 한 번에 찾아 지울 수 있다.
const CONTEXT_KEY_PREFIX: &str = "JBEduON.";

#[derive(Clone, Debug, Serialize)]
pub struct ContextMenuEntry {
    id: String,
    name: String,
    label: String,
    targets: Vec<String>,
    enabled: bool,
}

/// 대상 하나에 대응하는 레지스트리 키 경로.
fn context_key(target: &str, tool_id: &str) -> String {
    let leaf = format!("{CONTEXT_KEY_PREFIX}{tool_id}");
    if target.eq_ignore_ascii_case("folder") {
        format!(r"HKCU\Software\Classes\Directory\shell\{leaf}")
    } else {
        let extension = target.trim_start_matches('.').to_lowercase();
        format!(r"HKCU\Software\Classes\SystemFileAssociations\.{extension}\shell\{leaf}")
    }
}

fn reg(args: &[&str]) -> std::io::Result<std::process::Output> {
    let mut command = Command::new("reg");
    command.args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command.output()
}

fn context_registered(target: &str, tool_id: &str) -> bool {
    reg(&["query", &context_key(target, tool_id)])
        .map(|output| output.status.success())
        .unwrap_or(false)
}

/// 우클릭 메뉴에 넣을 수 있는 도구 목록과 현재 등록 상태.
#[tauri::command]
fn list_context_menu(app: AppHandle) -> Result<Vec<ContextMenuEntry>, String> {
    let mut entries = Vec::new();
    for record in read_tool_records(&app)? {
        let Some(spec) = record.manifest.context_menu.clone() else {
            continue;
        };
        let enabled = spec
            .targets
            .iter()
            .all(|target| context_registered(target, &record.manifest.id));
        entries.push(ContextMenuEntry {
            id: record.manifest.id,
            name: record.manifest.name,
            label: spec.label,
            targets: spec.targets,
            enabled,
        });
    }
    Ok(entries)
}

#[tauri::command]
fn set_context_menu(app: AppHandle, tool_id: String, enabled: bool) -> Result<(), String> {
    let record = find_tool(&app, &tool_id)?;
    let spec = record
        .manifest
        .context_menu
        .clone()
        .ok_or_else(|| "이 도구는 우클릭 메뉴를 지원하지 않습니다.".to_string())?;

    let exe = std::env::current_exe()
        .map_err(|error| format!("실행 파일 경로를 찾지 못했습니다: {error}"))?;
    let exe = exe.to_string_lossy().to_string();

    for target in &spec.targets {
        let key = context_key(target, &tool_id);
        if enabled {
            let command_key = format!(r"{key}\command");
            let command_value = format!("\"{exe}\" --open-with {tool_id} --path \"%1\"");
            reg(&["add", &key, "/ve", "/d", &spec.label, "/f"])
                .map_err(|error| format!("메뉴를 등록하지 못했습니다: {error}"))?;
            let _ = reg(&["add", &key, "/v", "Icon", "/d", &exe, "/f"]);
            reg(&["add", &command_key, "/ve", "/d", &command_value, "/f"])
                .map_err(|error| format!("메뉴를 등록하지 못했습니다: {error}"))?;
        } else {
            // 없는 키를 지우려 하면 실패하지만 결과는 같으므로 따지지 않는다.
            let _ = reg(&["delete", &key, "/f"]);
        }
    }
    Ok(())
}

// reg query가 결과를 HKCU가 아니라 이 이름으로 찍어 주므로, 목록을 훑을 때는
// 같은 표기를 써야 앞부분을 잘라낼 수 있다.
const CLASSES_ROOT: &str = r"HKEY_CURRENT_USER\Software\Classes";

/// 주어진 키 바로 아래에 있는 하위 키의 전체 경로. 값과 손자 키는 빼고 본다.
fn reg_subkeys(parent: &str) -> Vec<String> {
    let Ok(output) = reg(&["query", parent]) else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    // 키 이름은 ASCII라서 콘솔 코드 페이지가 무엇이든 이 비교는 안전하다.
    let text = String::from_utf8_lossy(&output.stdout).into_owned();
    let prefix = format!(r"{parent}\");
    text.lines()
        .filter_map(|line| {
            let line = line.trim();
            // 바로 아래 자식만 본다. 더 깊은 경로는 여기서 걸러진다.
            let leaf = line.strip_prefix(prefix.as_str())?;
            if leaf.is_empty() || leaf.contains('\\') {
                return None;
            }
            Some(line.to_string())
        })
        .collect()
}

fn is_context_key(key: &str) -> bool {
    key.rsplit('\\')
        .next()
        .map(|leaf| leaf.starts_with(CONTEXT_KEY_PREFIX))
        .unwrap_or(false)
}

/// 지금 등록되어 있는 우클릭 메뉴 키 전부. 매니페스트에서 도구가 사라진 뒤에도 찾아낸다.
fn registered_context_keys() -> Vec<String> {
    let mut keys: Vec<String> = reg_subkeys(&format!(r"{CLASSES_ROOT}\Directory\shell"))
        .into_iter()
        .filter(|key| is_context_key(key))
        .collect();

    for association in reg_subkeys(&format!(r"{CLASSES_ROOT}\SystemFileAssociations")) {
        keys.extend(
            reg_subkeys(&format!(r"{association}\shell"))
                .into_iter()
                .filter(|key| is_context_key(key)),
        );
    }
    keys
}

/// 등록된 우클릭 메뉴를 전부 지우고 지운 개수를 돌려준다.
/// 설치 제거 훅이 놓친 것이나, 이름이 바뀐 옛 도구가 남긴 것도 함께 정리된다.
#[tauri::command]
fn clear_context_menus() -> Result<usize, String> {
    let mut removed = 0;
    for key in registered_context_keys() {
        if reg(&["delete", &key, "/f"])
            .map(|output| output.status.success())
            .unwrap_or(false)
        {
            removed += 1;
        }
    }
    Ok(removed)
}

// 탐색기에서 파일 여러 개를 골라도 Windows는 명령을 파일 개수만큼 각각 실행한다.
// 그래서 잠깐 모았다가 한 번에 넘긴다.
static CONTEXT_BUFFER: std::sync::Mutex<Option<(String, Vec<String>)>> =
    std::sync::Mutex::new(None);

fn parse_context_args(argv: &[String]) -> Option<(String, String)> {
    let mut tool_id = None;
    let mut path = None;
    let mut index = 0;
    while index + 1 < argv.len() {
        match argv[index].as_str() {
            "--open-with" => tool_id = Some(argv[index + 1].clone()),
            "--path" => path = Some(argv[index + 1].clone()),
            _ => {}
        }
        index += 1;
    }
    match (tool_id, path) {
        (Some(tool_id), Some(path)) if !tool_id.is_empty() && !path.is_empty() => {
            Some((tool_id, path))
        }
        _ => None,
    }
}

/// 우클릭으로 들어온 경로를 모은다. 첫 경로가 들어오면 잠깐 기다렸다 한 번에 알린다.
fn collect_context_request(app: &AppHandle, argv: &[String]) {
    let Some((tool_id, path)) = parse_context_args(argv) else {
        return;
    };

    let first = {
        let Ok(mut buffer) = CONTEXT_BUFFER.lock() else {
            return;
        };
        match buffer.as_mut() {
            // 도구가 다르면 앞의 것은 버리고 새로 시작한다.
            Some((current, paths)) if *current == tool_id => {
                if !paths.contains(&path) {
                    paths.push(path);
                }
                false
            }
            _ => {
                *buffer = Some((tool_id.clone(), vec![path]));
                true
            }
        }
    };

    if !first {
        return;
    }

    let handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(800));
        let taken = CONTEXT_BUFFER.lock().ok().and_then(|mut buffer| buffer.take());
        if let Some((tool_id, paths)) = taken {
            use tauri::Emitter;
            let _ = handle.emit("context-open", json!({ "toolId": tool_id, "paths": paths }));
        }
    });
}

/// 앱이 꺼져 있던 상태에서 우클릭으로 실행됐을 때, 화면이 준비된 뒤 다시 확인한다.
#[tauri::command]
fn take_context_request() -> Option<Value> {
    let taken = CONTEXT_BUFFER.lock().ok().and_then(|mut buffer| buffer.take())?;
    Some(json!({ "toolId": taken.0, "paths": taken.1 }))
}

/// 작업 결과가 저장된 파일이나 폴더를 탐색기로 연다.
/// 파일 경로를 주면 그 파일이 든 폴더를 연다.
#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    let target = PathBuf::from(path.trim());
    if !target.exists() {
        return Err("결과 경로를 찾지 못했습니다.".to_string());
    }
    let folder = if target.is_dir() {
        target
    } else {
        target
            .parent()
            .map(Path::to_path_buf)
            .ok_or_else(|| "결과 폴더를 찾지 못했습니다.".to_string())?
    };
    let mut command = Command::new("explorer.exe");
    command.arg(&folder);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    // explorer.exe는 성공해도 0이 아닌 코드를 돌려주므로 결과를 따지지 않는다.
    let _ = command.spawn();
    Ok(())
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
    // 한 도구가 실행 외에 조회 같은 보조 동작을 가질 수 있다.
    // "excel_split__analyze" 처럼 뒤에 붙여 쓰고, 등록 확인은 앞부분으로 한다.
    let base_id = tool_id.split("__").next().unwrap_or(&tool_id);
    let record = find_tool(&app, base_id)?;
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

    // 개발 중에는 bridge/runner.py를 먼저 쓴다. 미리 빌드해 둔 sidecar exe는
    // 파이썬 코드를 고쳐도 갱신되지 않아 옛 동작이 그대로 돌아간다.
    // 설치본에는 runner.py가 없으므로 자연스럽게 sidecar를 쓴다.
    let mut attempts: Vec<(std::ffi::OsString, Option<PathBuf>)> = Vec::new();
    if let Some(dev_runner) = runner.filter(|path| path.is_file()) {
        attempts.push(("python".into(), Some(dev_runner)));
    }
    if let Some(sidecar) = sidecar {
        attempts.push((sidecar.into_os_string(), None));
    }
    if attempts.is_empty() {
        return Err("내장 Python 실행기와 개발용 연결 모듈을 찾지 못했습니다.".to_string());
    }

    let working_dir = record.root.parent().unwrap_or(&record.root);
    let mut spawn_error = String::new();
    let mut result = None;

    for (program, script) in attempts {
        let mut command = Command::new(&program);
        if let Some(script) = &script {
            command.arg(script);
        }
        command
            .arg("--tool")
            .arg(&tool_id)
            .arg("--payload-b64")
            .arg(&payload_encoded)
            .env("JBEDU_TOOLS_ROOT", working_dir)
            .env("JBEDU_PROJECT_ROOT", working_dir)
            // 한글 오류 메시지가 깨지지 않도록 파이썬 출력을 UTF-8로 고정한다.
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .current_dir(working_dir);

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }

        match command.output() {
            Ok(output) => {
                result = Some(output);
                break;
            }
            Err(error) => spawn_error = error.to_string(),
        }
    }

    let output = result
        .ok_or_else(|| format!("Python 도구를 실행하지 못했습니다: {spawn_error}"))?;

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
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            desktop::focus_main_window(app);
            collect_context_request(app, &argv);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            // 앱이 꺼져 있을 때 우클릭으로 실행되면 인자가 이 첫 실행에 들어온다.
            let argv: Vec<String> = std::env::args().collect();
            collect_context_request(app.handle(), &argv);
            setup_desktop(app)
        })
        .on_window_event(handle_window_event)
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            list_tools,
            read_tool_html,
            open_tool_in_browser,
            reveal_path,
            list_context_menu,
            set_context_menu,
            clear_context_menus,
            take_context_request,
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

