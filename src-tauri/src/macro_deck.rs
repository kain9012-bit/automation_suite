use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::process::Command;

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
        // 1.4.3 에서 명령·단축키·텍스트·대기·매크로를 뺐다. 화면에서 지우지만 혹시 남은 것이 오면 여기서 막는다.
        other => Err(format!("지원하지 않는 빠른 실행 동작입니다: {other}")),
    }
}

/// 탐색기·기본 프로그램을 띄우는 데 시간이 걸릴 수 있다. 동기 명령은 메인 스레드에서 돌아
/// 그동안 창이 멈추므로 다른 스레드로 넘긴다.
#[tauri::command]
pub async fn run_macro_action(action: MacroAction) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let message = run_native(&action)?;
        Ok(serde_json::json!({ "ok": true, "message": message }))
    })
    .await
    .map_err(|error| format!("빠른 실행을 마치지 못했습니다: {error}"))?
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
