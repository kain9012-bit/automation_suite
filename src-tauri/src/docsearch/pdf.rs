//! PDF 글자 꺼내기: 이미 설치본에 있는 파이썬 실행기(PyMuPDF)를 한 번 띄워 여러 개를 읽는다.
//! 실행기 찾는 순서는 도구 실행(lib.rs run_native_tool)과 같다.

use super::extract::Extracted;
use serde::Deserialize;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::{AppHandle, Manager};

#[derive(Deserialize)]
struct Line {
    path: String,
    status: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    error: String,
}

fn runner_command(app: &AppHandle) -> Option<Command> {
    // 개발 중에는 소스의 runner.py(설치본에는 없음). 경로가 빌드 때 박히므로 개발 빌드에서만 본다.
    if cfg!(debug_assertions) {
        let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("bridge")
            .join("runner.py");
        if dev.is_file() {
            let mut command = Command::new("python");
            command.arg(dev);
            return Some(command);
        }
    }
    let mut candidates = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.join("bridge-runner.exe"));
        }
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("bridge-runner.exe"));
        candidates.push(resource_dir.join("binaries").join("bridge-runner.exe"));
    }
    candidates.into_iter().find(|p| p.is_file()).map(Command::new)
}

/// PDF 목록을 읽어 하나씩 `on_result` 로 넘긴다. 실행기를 띄우지 못하면 Err.
pub fn read_pdfs(
    app: &AppHandle,
    paths: &[String],
    mut on_result: impl FnMut(&str, Result<Extracted, String>),
) -> Result<(), String> {
    let mut command = runner_command(app).ok_or_else(|| "PDF 읽기 모듈을 찾지 못했습니다".to_string())?;
    let dir = super::db::index_dir(app)?;
    let list = dir.join(format!("pdf-list-{}.json", std::process::id()));
    std::fs::write(&list, serde_json::to_vec(paths).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    command
        .arg("--pdf-text-list")
        .arg(&list)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // 창 없이, 낮은 우선순위로(BELOW_NORMAL_PRIORITY_CLASS) 돌려 업무를 방해하지 않게 한다.
        command.creation_flags(0x08000000 | 0x00004000);
    }
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            let _ = std::fs::remove_file(&list);
            return Err(format!("PDF 읽기 모듈을 실행하지 못했습니다: {error}"));
        }
    };
    if let Some(stdout) = child.stdout.take() {
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
            let text = String::from_utf8_lossy(&raw);
            let Ok(line) = serde_json::from_str::<Line>(text.trim()) else {
                continue; // 라이브러리가 찍은 안내 등
            };
            let result = match line.status.as_str() {
                "ok" | "no_text" => Ok(Extracted::Text(line.text)),
                "encrypted" => Ok(Extracted::Encrypted),
                _ => Err(if line.error.is_empty() { "PDF를 읽지 못했습니다".to_string() } else { line.error }),
            };
            on_result(&line.path, result);
            if super::index::stop_requested() {
                let _ = child.kill(); // [취소]: 남은 PDF 는 다음에 이어 읽는다
                break;
            }
        }
    }
    let _ = child.wait();
    let _ = std::fs::remove_file(&list);
    Ok(())
}
