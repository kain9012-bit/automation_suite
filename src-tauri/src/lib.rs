mod board_update;
mod desktop;
mod docsearch;
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

    // 소스의 tools 폴더는 개발 중에만 본다. 이 경로는 빌드할 때 문자열로 박히므로,
    // 설치본이 이걸 보면 그 PC에서만 다른 도구 코드가 돈다. bridge/runner.py 와
    // 같은 함정이고, 실제로 그 때문에 남들에게만 나는 문제를 오래 못 봤다.
    if cfg!(debug_assertions) {
        let dev_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("tools");
        if let Some(path) = canonical_if_dir(dev_root) {
            roots.push((path, "builtin"));
        }
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

/// 도구 실행이 끝났을 때 부른다. 설정이 켜져 있고 앱 창이 가려져 있을 때만 윈도우 알림을 띄운다.
/// status: "done"(완료) · "check"(확인 필요: 일부 실패·중지·목표 미달 등) · "failed"(실패)
#[tauri::command]
fn notify_tool_finished(app: AppHandle, tool_id: String, status: String, message: String) -> bool {
    use tauri_plugin_notification::NotificationExt;
    if !desktop::should_notify_finish(&app) {
        return false;
    }
    let name = find_tool(&app, &tool_id).map(|record| record.manifest.name).unwrap_or(tool_id);
    let title = match status.as_str() {
        "done" => format!("{name} 완료"),
        "failed" => format!("{name} - 작업을 마치지 못했습니다"),
        _ => format!("{name} - 결과를 확인해 주세요"),
    };
    // 알림에는 첫 줄만, 너무 길면 줄인다.
    let first = message.lines().map(str::trim).find(|line| !line.is_empty()).unwrap_or("");
    let mut body: String = first.chars().take(150).collect();
    if first.chars().count() > 150 {
        body.push('…');
    }
    if body.is_empty() {
        body = "JB업무ON 을 열어 결과를 확인해 주세요.".to_string();
    }
    app.notification().builder().title(title).body(body).show().is_ok()
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

// ── 예전 탐색기 우클릭 메뉴 정리 ─────────────────────────────────────
// 우클릭 메뉴 기능은 없앴다. 그러나 예전 버전이 HKCU에 써 둔 키가 남아 있으면
// 탐색기에 눌러도 아무 일이 없는 메뉴가 계속 보인다. 예전 버전이 쓰던 곳은 두 군데다.
//   HKCU\Software\Classes\Directory\shell\JBEduON.<도구ID>
//   HKCU\Software\Classes\SystemFileAssociations\.<확장자>\shell\JBEduON.<도구ID>
// 앱이 뜰 때 따로 돌려 지운다. 실패해도 조용히 넘어가고 다음 실행 때 다시 해 본다.

/// 예전 버전이 키 이름 앞에 붙이던 말.
const LEGACY_CONTEXT_KEY_PREFIX: &str = "JBEduON.";

// reg query가 결과를 HKCU가 아니라 이 이름으로 찍어 주므로, 목록을 훑을 때는
// 같은 표기를 써야 앞부분을 잘라낼 수 있다.
const CLASSES_ROOT: &str = r"HKEY_CURRENT_USER\Software\Classes";

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
            let leaf = line.strip_prefix(prefix.as_str())?;
            if leaf.is_empty() || leaf.contains('\\') {
                return None;
            }
            Some(line.to_string())
        })
        .collect()
}

fn is_legacy_context_key(key: &str) -> bool {
    key.rsplit('\\')
        .next()
        .map(|leaf| leaf.starts_with(LEGACY_CONTEXT_KEY_PREFIX))
        .unwrap_or(false)
}

/// 예전 버전이 남긴 우클릭 메뉴 키 전부.
fn legacy_context_keys() -> Vec<String> {
    let mut keys: Vec<String> = reg_subkeys(&format!(r"{CLASSES_ROOT}\Directory\shell"))
        .into_iter()
        .filter(|key| is_legacy_context_key(key))
        .collect();
    for association in reg_subkeys(&format!(r"{CLASSES_ROOT}\SystemFileAssociations")) {
        keys.extend(
            reg_subkeys(&format!(r"{association}\shell"))
                .into_iter()
                .filter(|key| is_legacy_context_key(key)),
        );
    }
    keys
}

/// 예전 우클릭 메뉴 키를 지운다. 다 지워진 것을 확인하면 표시 파일을 남겨
/// 다음부터는 레지스트리를 훑지 않는다.
fn remove_legacy_context_menus(app: &AppHandle) {
    if !cfg!(windows) {
        return;
    }
    let marker = app
        .path()
        .app_config_dir()
        .ok()
        .map(|dir| dir.join("legacy-context-menu-removed"));
    if marker.as_ref().map(|path| path.is_file()).unwrap_or(false) {
        return;
    }
    for key in legacy_context_keys() {
        // reg delete 는 하위 키(command)까지 함께 지운다.
        let _ = reg(&["delete", &key, "/f"]);
    }
    if legacy_context_keys().is_empty() {
        if let Some(path) = marker {
            if let Some(dir) = path.parent() {
                let _ = fs::create_dir_all(dir);
            }
            let _ = fs::write(path, b"done");
        }
    }
}

/// 넣은 파일들의 크기(바이트). 없는 파일이나 폴더는 None.
/// PDF 용량 압축처럼 크기가 중요한 도구에서 목록 옆에 보여 준다.
#[tauri::command]
fn file_sizes(paths: Vec<String>) -> Vec<Option<u64>> {
    paths
        .iter()
        .map(|path| {
            fs::metadata(path)
                .ok()
                .filter(|meta| meta.is_file())
                .map(|meta| meta.len())
        })
        .collect()
}

/// 넣은 경로가 파일인지 폴더인지. "file", "folder", 없으면 "missing".
/// 끌어다 놓은 것을 도구가 받을 수 있는지 미리 가리는 데 쓴다.
#[tauri::command]
fn path_kinds(paths: Vec<String>) -> Vec<&'static str> {
    paths
        .iter()
        .map(|path| match fs::metadata(path) {
            Ok(meta) if meta.is_dir() => "folder",
            Ok(_) => "file",
            Err(_) => "missing",
        })
        .collect()
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
    // 소스의 runner.py 는 개발 중에만 쓴다. 이 경로는 빌드할 때 문자열로 박히기
    // 때문에, 설치본이 이걸 쓰면 그 PC에서만 다른 코드가 돈다. 그러면 남들에게만
    // 나는 문제를 제작자는 영영 보지 못한다. 실제로 그 일이 있었다.
    if cfg!(debug_assertions) {
        let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("bridge")
            .join("runner.py");
        if dev_path.is_file() {
            return Ok(dev_path);
        }
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

/// 실행 중인 도구에 중지를 알리는 신호 파일의 위치.
///
/// 프로세스를 죽이면 그때까지 모은 결과도 함께 사라진다. 파일 하나를 만들어 두고
/// 도구가 스스로 보게 하면, 하던 항목까지 마치고 결과를 저장한 뒤 멈출 수 있다.
fn cancel_flag_path(app: &AppHandle, tool_id: &str) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_cache_dir()
        .map_err(|error| format!("임시 폴더를 찾지 못했습니다: {error}"))?
        .join("cancel");
    fs::create_dir_all(&dir).map_err(|error| format!("임시 폴더를 만들지 못했습니다: {error}"))?;
    let safe: String = tool_id
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '-')
        .collect();
    Ok(dir.join(format!("{safe}.stop")))
}

/// 실행 중인 도구에 그만두라고 알린다. 도구가 중지를 지원할 때만 효과가 있다.
#[tauri::command]
fn cancel_native_tool(app: AppHandle, tool_id: String) -> Result<(), String> {
    let path = cancel_flag_path(&app, &tool_id)?;
    fs::write(&path, b"stop").map_err(|error| format!("중지 요청을 남기지 못했습니다: {error}"))
}

/// 파이썬 도구가 진행 상황을 알릴 때 줄 앞에 붙이는 표시.
/// 이 표시가 붙은 줄은 결과가 아니라 화면에 그때그때 올릴 안내다.
const PROGRESS_PREFIX: &str = "@@JBEDU_PROGRESS@@";

/// 도구 실행은 오래 걸린다. 동기 명령은 Tauri가 메인 스레드에서 돌리기 때문에
/// 그동안 창이 통째로 멈춘다. 중지 버튼도 안 눌리고 진행 상황도 그려지지 않는다.
/// 그래서 실제 작업은 다른 스레드로 넘기고 여기서는 기다리기만 한다.
#[tauri::command]
async fn run_native_tool(
    app: AppHandle,
    tool_id: String,
    payload: Value,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_native_tool_blocking(app, tool_id, payload))
        .await
        .map_err(|error| format!("도구 실행을 마치지 못했습니다: {error}"))?
}

/// 명령줄로 넘길 입력값(base64)의 최대 길이. 윈도 명령줄 한도(32,767자)에서 경로·다른 인자 몫을 뺐다.
const PAYLOAD_ARG_LIMIT: usize = 24_000;

/// 명령줄에 다 들어가지 않는 입력값을 담은 임시 파일. 도구 실행이 끝나면(오류로 끝나도) 지운다.
struct PayloadFile(PathBuf);

impl PayloadFile {
    fn write(app: &AppHandle, payload_json: &str) -> Result<Self, String> {
        let dir = app
            .path()
            .app_cache_dir()
            .map_err(|error| format!("임시 폴더를 찾지 못했습니다: {error}"))?
            .join("payload");
        fs::create_dir_all(&dir).map_err(|error| format!("임시 폴더를 만들지 못했습니다: {error}"))?;
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or_default();
        let path = dir.join(format!("{}-{stamp}.json", std::process::id()));
        fs::write(&path, payload_json).map_err(|error| format!("입력값을 넘기지 못했습니다: {error}"))?;
        Ok(Self(path))
    }
}

impl Drop for PayloadFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn run_native_tool_blocking(
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
    let payload_encoded = STANDARD.encode(&payload_json);
    // 윈도 명령줄은 32,767자까지만 받는다. 입력값이 길면(문서 개인정보 마스킹의 확인 목록 등)
    // 임시 파일로 넘기고 끝나면 지운다. 짧은 입력은 지금까지처럼 명령줄로 넘긴다.
    let payload_file = if payload_encoded.len() > PAYLOAD_ARG_LIMIT {
        Some(PayloadFile::write(&app, &payload_json)?)
    } else {
        None
    };

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

    // 지난 실행에서 남은 중지 신호를 지우고 시작한다. 남아 있으면 시작하자마자 멈춘다.
    let cancel_flag = cancel_flag_path(&app, &tool_id).ok();
    if let Some(path) = &cancel_flag {
        let _ = fs::remove_file(path);
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
            .arg(&tool_id);
        match &payload_file {
            Some(file) => command.arg("--payload-file").arg(&file.0),
            None => command.arg("--payload-b64").arg(&payload_encoded),
        };
        command
            .env(
                "JBEDU_CANCEL_FILE",
                cancel_flag.as_deref().unwrap_or(Path::new("")),
            )
            .env("JBEDU_TOOLS_ROOT", working_dir)
            .env("JBEDU_PROJECT_ROOT", working_dir)
            // 한글 오류 메시지가 깨지지 않도록 파이썬 출력을 UTF-8로 고정한다.
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .current_dir(working_dir);

        command
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }

        match command.spawn() {
            Ok(child) => {
                result = Some(child);
                break;
            }
            Err(error) => spawn_error = error.to_string(),
        }
    }

    let mut child = result
        .ok_or_else(|| format!("Python 도구를 실행하지 못했습니다: {spawn_error}"))?;

    // 오류 출력은 따로 읽는다. 그냥 두면 출력이 많을 때 파이프가 차서 서로 멈춘다.
    let stderr_reader = child.stderr.take().map(|mut stderr| {
        std::thread::spawn(move || {
            use std::io::Read;
            let mut text = String::new();
            let _ = stderr.read_to_string(&mut text);
            text
        })
    });

    // 도구가 한 줄씩 내보내는 진행 상황을 기다리지 않고 그때그때 화면으로 올린다.
    // 표시가 붙은 줄은 안내, 나머지는 모아서 결과로 읽는다.
    let mut body_lines: Vec<String> = Vec::new();
    if let Some(stdout) = child.stdout.take() {
        use std::io::{BufRead, BufReader};
        use tauri::Emitter;
        // UTF-8이 아닌 줄이 섞여도 읽기를 멈추지 않는다. 멈추면 도구가 파이프가
        // 끊겨 죽는다. 바이트로 읽어 깨진 글자만 바꿔 넣는다.
        let mut reader = BufReader::new(stdout);
        let mut raw = Vec::new();
        loop {
            raw.clear();
            match reader.read_until(b'\n', &mut raw) {
                Ok(0) => break,
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            }
            let line = String::from_utf8_lossy(&raw)
                .trim_end_matches(['\r', '\n'])
                .to_string();
            match line.trim().strip_prefix(PROGRESS_PREFIX) {
                Some(text) => {
                    let _ = app.emit(
                        "tool-progress",
                        json!({ "toolId": tool_id, "text": text.trim() }),
                    );
                }
                None => body_lines.push(line),
            }
        }
    }

    let status = child
        .wait()
        .map_err(|error| format!("도구 실행을 마치지 못했습니다: {error}"))?;
    if let Some(path) = &cancel_flag {
        let _ = fs::remove_file(path);
    }
    let stderr_text = stderr_reader
        .and_then(|handle| handle.join().ok())
        .unwrap_or_default();

    if !status.success() {
        let message = stderr_text.trim().to_string();
        return Err(if message.is_empty() {
            "도구 실행 중 오류가 발생했습니다.".to_string()
        } else {
            message
        });
    }

    parse_tool_output(&body_lines.join("\n"))
}

/// 도구가 낸 출력에서 결과 JSON을 읽는다.
///
/// 전체가 JSON 하나면 그것을, 아니면 마지막 줄을 본다(앞에 라이브러리가 찍은
/// 안내가 섞일 수 있다). 둘 다 아니면 성공으로 치지 않고 오류로 돌려준다.
fn parse_tool_output(body: &str) -> Result<Value, String> {
    let body = body.trim();
    if let Ok(value) = serde_json::from_str::<Value>(body) {
        return Ok(value);
    }
    if let Some(last) = body.lines().rev().map(str::trim).find(|line| !line.is_empty()) {
        if let Ok(value) = serde_json::from_str::<Value>(last) {
            return Ok(value);
        }
    }
    let head: String = body.chars().take(300).collect();
    Err(if head.is_empty() {
        "도구가 결과를 돌려주지 않았습니다.".to_string()
    } else {
        format!("도구 결과를 읽지 못했습니다: {head}")
    })
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
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            // 예전 버전이 남긴 탐색기 우클릭 메뉴를 치운다. reg 조회가 느려
            // 창 띄우는 것을 붙잡지 않도록 따로 돌린다.
            let handle = app.handle().clone();
            std::thread::spawn(move || remove_legacy_context_menus(&handle));
            // 문서 검색: 켜지고 잠시 뒤 바뀐 파일만 대조한다(문서 검색을 연 적 있는 PC만).
            docsearch::schedule_startup_check(app.handle());

            setup_desktop(app)
        })
        .on_window_event(handle_window_event)
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            list_tools,
            read_tool_html,
            open_tool_in_browser,
            reveal_path,
            file_sizes,
            path_kinds,
            run_native_tool,
            cancel_native_tool,
            board_update::check_board_update,
            board_update::download_board_update,
            board_update::apply_board_update,
            check_tool_updates,
            install_tool_updates,
            get_app_preferences,
            set_app_preferences,
            run_macro_action,
            notify_tool_finished,
            docsearch::docsearch_open_screen,
            docsearch::docsearch_status,
            docsearch::docsearch_refresh,
            docsearch::docsearch_set_folders,
            docsearch::docsearch_search,
            docsearch::docsearch_open_file,
            docsearch::docsearch_reveal_file
        ])
        .run(tauri::generate_context!())
        .expect("Tauri 애플리케이션 실행 실패");
}


#[cfg(test)]
mod tests {
    use super::{is_legacy_context_key, parse_tool_output};
    use serde_json::json;

    #[test]
    fn reads_whole_json_body() {
        let value = parse_tool_output("{\n  \"ok\": true,\n  \"count\": 2\n}\n").unwrap();
        assert_eq!(value, json!({ "ok": true, "count": 2 }));
    }

    #[test]
    fn reads_last_line_when_noise_precedes_result() {
        let value = parse_tool_output("경고: 라이브러리 안내\n\n{\"ok\": true}\n\n").unwrap();
        assert_eq!(value, json!({ "ok": true }));
    }

    #[test]
    fn plain_text_is_an_error_not_success() {
        let error = parse_tool_output("Traceback (most recent call last):\n  boom").unwrap_err();
        assert!(error.starts_with("도구 결과를 읽지 못했습니다: Traceback"));
        assert!(parse_tool_output("  \n").is_err());
        let long = "가".repeat(1000);
        assert_eq!(
            parse_tool_output(&long).unwrap_err().chars().count(),
            "도구 결과를 읽지 못했습니다: ".chars().count() + 300
        );
    }

    #[test]
    fn legacy_context_key_match() {
        assert!(is_legacy_context_key(
            r"HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.pdf\shell\JBEduON.pdf_compress"
        ));
        assert!(is_legacy_context_key(r"HKEY_CURRENT_USER\Software\Classes\Directory\shell\JBEduON.file_inventory"));
        assert!(!is_legacy_context_key(r"HKEY_CURRENT_USER\Software\Classes\Directory\shell\Open"));
    }
}
