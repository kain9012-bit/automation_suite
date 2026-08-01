use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{path::PathBuf, process::Command};
use tauri::{AppHandle, Manager};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct MacroAction {
    pub id: String,
    pub name: String,
    #[serde(rename = "type")] pub action_type: String,
    #[serde(default)] pub target: String,
    #[serde(default)] pub arguments: String,
    #[serde(default)] pub hotkey: String,
    #[serde(default)] pub color: String,
    #[serde(default)] pub size: String,
    #[serde(default)] pub steps: Vec<MacroAction>,
}

fn command_for_runner(app: &AppHandle) -> Result<Command, String> {
    let mut candidates = Vec::new();
    if let Ok(current_exe) = std::env::current_exe() { if let Some(parent) = current_exe.parent() { candidates.push(parent.join("bridge-runner.exe")); } }
    if let Ok(resource_dir) = app.path().resource_dir() { candidates.push(resource_dir.join("bridge-runner.exe")); candidates.push(resource_dir.join("binaries").join("bridge-runner.exe")); }
    if let Some(sidecar) = candidates.into_iter().find(|path| path.is_file()) { return Ok(Command::new(sidecar)); }
    let runner = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap_or_else(|| std::path::Path::new(".")).join("bridge").join("runner.py");
    if !runner.is_file() { return Err("빠른 실행 모듈을 찾지 못했습니다.".to_string()); }
    let mut command = Command::new("python"); command.arg(runner); Ok(command)
}

/// 키 입력을 흉내 내야 하는 동작만 Python sidecar가 필요하다.
/// 나머지는 Rust에서 바로 실행해야 링크 하나 여는 데 인터프리터가 뜨는 일이 없다.
fn needs_sidecar(action: &MacroAction) -> bool {
    match action.action_type.as_str() {
        "hotkey" | "text" => true,
        "macro" => action.steps.iter().any(needs_sidecar),
        _ => false,
    }
}

fn spawn_detached(mut command: Command) -> Result<(), String> {
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("실행하지 못했습니다: {error}"))
}

/// 확장 프로그램이나 셸 따옴표 해석을 거치지 않고 기본 연결 프로그램으로 연다.
fn open_with_default(target: &str) -> Result<(), String> {
    let mut command = Command::new("rundll32.exe");
    command.arg("url.dll,FileProtocolHandler").arg(target);
    spawn_detached(command)
}

/// `~`와 `%APPDATA%` 같은 표기를 실제 경로로 바꾼다.
fn expand(value: &str) -> String {
    let mut result = String::new();
    let mut rest = value.trim();

    if let Some(stripped) = rest.strip_prefix('~') {
        if let Ok(home) = std::env::var("USERPROFILE") {
            result.push_str(&home);
            rest = stripped;
        }
    }

    loop {
        let Some(start) = rest.find('%') else {
            result.push_str(rest);
            break;
        };
        result.push_str(&rest[..start]);
        let Some(offset) = rest[start + 1..].find('%') else {
            result.push_str(&rest[start..]);
            break;
        };
        let name = &rest[start + 1..start + 1 + offset];
        match std::env::var(name) {
            Ok(found) => result.push_str(&found),
            Err(_) => {
                result.push('%');
                result.push_str(name);
                result.push('%');
            }
        }
        rest = &rest[start + offset + 2..];
    }

    result
}

fn run_native(action: &MacroAction) -> Result<String, String> {
    let target = action.target.trim();
    match action.action_type.as_str() {
        "macro" => {
            if action.steps.is_empty() {
                return Err("매크로 단계를 하나 이상 추가해 주세요.".to_string());
            }
            for step in &action.steps {
                run_native(step)?;
            }
            Ok(format!("{}단계 매크로를 실행했습니다.", action.steps.len()))
        }
        "site" => {
            if target.is_empty() {
                return Err("주소를 입력해 주세요.".to_string());
            }
            let url = if target.contains("://") { target.to_string() } else { format!("https://{target}") };
            open_with_default(&url)?;
            Ok(format!("{}을(를) 열었습니다.", action.name))
        }
        "folder" => {
            let path = expand(target);
            if path.is_empty() {
                return Err("폴더 경로를 입력해 주세요.".to_string());
            }
            if !std::path::Path::new(&path).exists() {
                return Err(format!("경로를 찾을 수 없습니다.\n{path}"));
            }
            let mut command = Command::new("explorer.exe");
            command.arg(&path);
            // explorer.exe는 성공해도 0이 아닌 코드를 돌려주므로 결과를 따지지 않는다.
            let _ = spawn_detached(command);
            Ok(format!("{}을(를) 열었습니다.", action.name))
        }
        "file" => {
            let path = expand(target);
            if !std::path::Path::new(&path).exists() {
                return Err(format!("경로를 찾을 수 없습니다.\n{path}"));
            }
            open_with_default(&path)?;
            Ok(format!("{}을(를) 열었습니다.", action.name))
        }
        "program" => {
            let path = expand(target);
            if !std::path::Path::new(&path).exists() {
                return Err(format!("프로그램을 찾을 수 없습니다.\n{path}"));
            }
            let arguments = action.arguments.trim();
            if arguments.is_empty() {
                open_with_default(&path)?;
            } else {
                let mut command = Command::new(&path);
                command.args(arguments.split_whitespace());
                spawn_detached(command)?;
            }
            Ok(format!("{}을(를) 실행했습니다.", action.name))
        }
        "command" => {
            if target.is_empty() {
                return Err("실행할 명령을 입력해 주세요.".to_string());
            }
            let mut command = Command::new("cmd");
            command.args(["/C", target]);
            spawn_detached(command)?;
            Ok(format!("{} 명령을 실행했습니다.", action.name))
        }
        "wait" => {
            let seconds: f64 = target.parse().map_err(|_| "대기 시간은 숫자로 입력해 주세요.".to_string())?;
            if !(0.0..=3600.0).contains(&seconds) {
                return Err("대기 시간은 0초에서 3600초 사이로 입력해 주세요.".to_string());
            }
            std::thread::sleep(std::time::Duration::from_secs_f64(seconds));
            Ok("대기를 마쳤습니다.".to_string())
        }
        other => Err(format!("지원하지 않는 빠른 실행 동작입니다: {other}")),
    }
}

#[tauri::command]
pub fn run_macro_action(app: AppHandle, action: MacroAction) -> Result<Value, String> {
    if !needs_sidecar(&action) {
        let message = run_native(&action)?;
        return Ok(serde_json::json!({ "ok": true, "message": message }));
    }
    let encoded = STANDARD.encode(serde_json::to_vec(&action).map_err(|error| format!("빠른 실행 입력 오류: {error}"))?);
    let mut command = command_for_runner(&app)?;
    command.arg("--macro-action-b64").arg(encoded);
    #[cfg(windows)] command.creation_flags(0x08000000);
    let output = command.output().map_err(|error| format!("빠른 실행을 시작하지 못했습니다: {error}"))?;
    if !output.status.success() {
        let message = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if message.is_empty() { "빠른 실행 중 오류가 발생했습니다.".to_string() } else { message });
    }
    serde_json::from_slice(&output.stdout).map_err(|error| format!("빠른 실행 결과를 읽지 못했습니다: {error}"))
}
