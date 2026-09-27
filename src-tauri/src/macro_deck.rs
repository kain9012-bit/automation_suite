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
    // 개발 중에는 bridge/runner.py를 먼저 쓴다. 미리 빌드해 둔 sidecar exe는
    // 파이썬 코드를 고쳐도 갱신되지 않는다. 설치본에는 runner.py가 없다.
    // 소스 경로는 빌드할 때 문자열로 박히므로 설치본에서는 보지 않는다(lib.rs bridge_path 와 같다).
    let runner = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap_or_else(|| std::path::Path::new(".")).join("bridge").join("runner.py");
    let mut command = if cfg!(debug_assertions) && runner.is_file() {
        let mut command = Command::new("python");
        command.arg(runner);
        command
    } else {
        let mut candidates = Vec::new();
        if let Ok(current_exe) = std::env::current_exe() { if let Some(parent) = current_exe.parent() { candidates.push(parent.join("bridge-runner.exe")); } }
        if let Ok(resource_dir) = app.path().resource_dir() { candidates.push(resource_dir.join("bridge-runner.exe")); candidates.push(resource_dir.join("binaries").join("bridge-runner.exe")); }
        let sidecar = candidates.into_iter().find(|path| path.is_file()).ok_or_else(|| "빠른 실행 모듈을 찾지 못했습니다.".to_string())?;
        Command::new(sidecar)
    };
    command.env("PYTHONUTF8", "1").env("PYTHONIOENCODING", "utf-8");
    Ok(command)
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
pub fn open_with_default(target: &str) -> Result<(), String> {
    let mut command = Command::new("rundll32.exe");
    command.arg("url.dll,FileProtocolHandler").arg(target);
    spawn_detached(command)
}

/// 인수 문자열을 나눈다. 큰따옴표로 묶은 부분은 공백이 있어도 한 덩어리로 본다.
/// ("C:\바탕 화면\a.txt" 처럼 공백이 든 경로를 넘길 수 있어야 한다.)
/// 따옴표 자체는 빼고 넘긴다. 인수를 다시 조립할 때 Rust가 필요한 따옴표를 붙인다.
pub(crate) fn split_arguments(value: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut quoted = false;
    let mut started = false;
    for ch in value.chars() {
        match ch {
            '"' => {
                quoted = !quoted;
                started = true;
            }
            c if c.is_whitespace() && !quoted => {
                if started {
                    parts.push(std::mem::take(&mut current));
                    started = false;
                }
            }
            c => {
                current.push(c);
                started = true;
            }
        }
    }
    if started {
        parts.push(current);
    }
    parts
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
                command.args(split_arguments(arguments));
                spawn_detached(command)?;
            }
            Ok(format!("{}을(를) 실행했습니다.", action.name))
        }
        "command" => {
            if target.is_empty() {
                return Err("실행할 명령을 입력해 주세요.".to_string());
            }
            let mut command = Command::new("cmd");
            // cmd.exe 는 C 런타임식 \" 이스케이프를 모른다. args()로 넘기면 따옴표로
            // 묶은 경로("C:\Program Files\...")가 깨지므로, 적은 그대로 붙여 넘긴다.
            // /S 와 바깥 따옴표 한 겹: cmd 는 이 바깥 따옴표만 벗기고 안쪽은 그대로 둔다.
            // 이렇게 하지 않으면 따옴표로 시작하는 명령에서 cmd 가 첫·끝 따옴표를 떼어 버린다.
            #[cfg(windows)]
            {
                command.raw_arg("/S /C").raw_arg(format!("\"{target}\""));
            }
            #[cfg(not(windows))]
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

/// 대기 단계나 키 입력 흉내는 오래 걸릴 수 있다. 동기 명령은 메인 스레드에서 돌아
/// 그동안 창이 멈추므로 다른 스레드로 넘긴다.
#[tauri::command]
pub async fn run_macro_action(app: AppHandle, action: MacroAction) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_macro_action_blocking(app, action))
        .await
        .map_err(|error| format!("빠른 실행을 마치지 못했습니다: {error}"))?
}

fn run_macro_action_blocking(app: AppHandle, action: MacroAction) -> Result<Value, String> {
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

#[cfg(test)]
mod tests {
    use super::split_arguments;

    #[test]
    fn splits_plain_words() {
        assert_eq!(split_arguments("  -a  b\tc "), vec!["-a", "b", "c"]);
    }

    #[test]
    fn keeps_quoted_paths_with_spaces() {
        assert_eq!(
            split_arguments(r#"/open "C:\Users\me\바탕 화면\a.txt" --x"#),
            vec!["/open", r"C:\Users\me\바탕 화면\a.txt", "--x"]
        );
        assert_eq!(
            split_arguments(r#""C:\Users\me\OneDrive - 기관\b.hwp""#),
            vec![r"C:\Users\me\OneDrive - 기관\b.hwp"]
        );
    }

    #[test]
    fn joins_quoted_part_inside_word_and_keeps_empty_quotes() {
        assert_eq!(split_arguments(r#"--path="a b" """#), vec!["--path=a b", ""]);
        assert!(split_arguments("   ").is_empty());
    }
}
