//! 문서 검색(1.4.4): 내 PC 문서를 파일 이름과 내용으로 찾는다.
//!
//! 도큐파인더의 키워드 검색 방식(SQLite FTS5 + Lindera)을 가볍게 옮겼다.
//! 미리보기·OCR·AI 는 없다. 다른 도구 코드와 섞이지 않게 이 폴더 안에만 둔다.
//! 계획서: Project 문서 claude/1.4.4_문서검색_계획.md

mod db;
mod extract;
mod index;
mod pdf;
mod search;
mod tokenize;
#[cfg(test)]
mod bench;

use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;
use tauri::{AppHandle, Manager};

/// 화면을 열 때 이만큼 지났으면 바뀐 파일을 대조한다.
const SCREEN_RECHECK_SECS: i64 = 10 * 60;
/// 프로그램이 켜지고 이만큼 뒤에 대조한다(켜진 직후 PC가 바쁠 때를 피함).
const STARTUP_DELAY_SECS: u64 = 90;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FolderInfo {
    path: String,
    exists: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    folders: Vec<FolderInfo>,
    /// 목록에 있는 파일 수
    files: i64,
    /// 내용까지 검색되는 문서 수
    documents: i64,
    /// 아직 읽을 차례인 문서 수
    pending: i64,
    /// 마지막 대조 시각(초). 한 번도 안 했으면 0
    last_check: i64,
    running: bool,
    progress: Option<index::Progress>,
    /// 색인 파일 크기(바이트)
    index_bytes: u64,
}

fn status(app: &AppHandle) -> Result<Status, String> {
    let conn = db::open(app)?;
    let count = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap_or(0);
    let folders = db::folders(&conn)?
        .into_iter()
        .map(|(_, path)| FolderInfo { exists: PathBuf::from(&path).is_dir(), path })
        .collect();
    let dir = db::index_dir(app)?;
    let index_bytes = ["index.db", "index.db-wal"]
        .iter()
        .filter_map(|n| std::fs::metadata(dir.join(n)).ok())
        .map(|m| m.len())
        .sum();
    Ok(Status {
        folders,
        files: count("SELECT count(*) FROM files"),
        documents: count("SELECT count(*) FROM files WHERE status='ok'"),
        pending: count("SELECT count(*) FROM files WHERE status='pending'"),
        last_check: db::get_meta(&conn, "last_check").and_then(|v| v.parse().ok()).unwrap_or(0),
        running: index::is_running(),
        progress: index::progress(),
        index_bytes,
    })
}

/// 기본 검색 폴더: 바탕화면 · 문서 · 다운로드
fn default_folders(app: &AppHandle) -> Vec<String> {
    let path = app.path();
    [path.desktop_dir(), path.document_dir(), path.download_dir()]
        .into_iter()
        .filter_map(Result::ok)
        .filter(|p| p.is_dir())
        .map(|p| p.to_string_lossy().into_owned())
        .collect()
}

fn normalize_folder(path: &str) -> String {
    let trimmed = path.trim();
    let stripped = trimmed.trim_end_matches(['\\', '/']);
    // "D:\" 같은 드라이브 맨 위는 끝의 \ 를 남긴다.
    if stripped.ends_with(':') {
        format!("{stripped}\\")
    } else {
        stripped.to_string()
    }
}

async fn blocking<T: Send + 'static>(
    f: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|e| format!("문서 검색 작업을 마치지 못했습니다: {e}"))?
}

/// 문서 검색 화면을 열 때. 처음이면 기본 폴더를 넣고, 마지막 대조 후 10분이 지났으면 뒤에서 대조한다.
/// 검색은 기존 색인으로 바로 된다(대조를 기다리지 않음).
#[tauri::command]
pub async fn docsearch_open_screen(app: AppHandle) -> Result<Status, String> {
    blocking(move || {
        let conn = db::open(&app)?;
        if db::get_meta(&conn, "initialized").is_none() {
            for folder in default_folders(&app) {
                conn.execute(
                    "INSERT OR IGNORE INTO folders(path, added_at) VALUES(?1, ?2)",
                    rusqlite::params![folder, db::now_secs()],
                )
                .map_err(|e| e.to_string())?;
            }
            db::set_meta(&conn, "initialized", "1")?;
        }
        let last: i64 = db::get_meta(&conn, "last_check").and_then(|v| v.parse().ok()).unwrap_or(0);
        if db::now_secs() - last >= SCREEN_RECHECK_SECS {
            index::start(&app);
        }
        status(&app)
    })
    .await
}

#[tauri::command]
pub async fn docsearch_status(app: AppHandle) -> Result<Status, String> {
    blocking(move || status(&app)).await
}

/// [지금 다시 읽기]
#[tauri::command]
pub async fn docsearch_refresh(app: AppHandle) -> Result<Status, String> {
    blocking(move || {
        index::start(&app);
        status(&app)
    })
    .await
}

/// 검색 폴더를 바꾼다. 뺀 폴더의 파일은 다음 대조에서 색인에서 빠지고, 더한 폴더는 바로 대조를 시작한다.
#[tauri::command]
pub async fn docsearch_set_folders(app: AppHandle, folders: Vec<String>) -> Result<Status, String> {
    blocking(move || {
        let mut conn = db::open(&app)?;
        let wanted: Vec<String> = {
            let mut list: Vec<String> = Vec::new();
            for f in folders.iter().map(|f| normalize_folder(f)).filter(|f| !f.is_empty()) {
                if !list.iter().any(|x| x.eq_ignore_ascii_case(&f)) {
                    list.push(f);
                }
            }
            list
        };
        let tx = conn.transaction().map_err(|e| e.to_string())?;
        for (id, path) in db::folders(&tx)? {
            if !wanted.iter().any(|w| w.eq_ignore_ascii_case(&path)) {
                tx.execute("DELETE FROM folders WHERE id=?1", [id]).map_err(|e| e.to_string())?;
            }
        }
        for folder in &wanted {
            tx.execute(
                "INSERT OR IGNORE INTO folders(path, added_at) VALUES(?1, ?2)",
                rusqlite::params![folder, db::now_secs()],
            )
            .map_err(|e| e.to_string())?;
        }
        db::set_meta(&tx, "initialized", "1")?;
        tx.commit().map_err(|e| e.to_string())?;
        drop(conn);
        index::start(&app);
        status(&app)
    })
    .await
}

#[tauri::command]
pub async fn docsearch_search(app: AppHandle, query: String, filters: Option<Value>) -> Result<search::SearchResult, String> {
    blocking(move || {
        let filters: search::Filters = filters
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default();
        let conn = db::open(&app)?;
        search::search(&conn, &query, &filters)
    })
    .await
}

/// 결과의 파일을 연다. 그사이 지워졌으면 알린다.
#[tauri::command]
pub fn docsearch_open_file(path: String) -> Result<(), String> {
    if !PathBuf::from(&path).is_file() {
        return Err("파일이 없습니다. 옮겨졌거나 지워졌을 수 있습니다.".to_string());
    }
    crate::macro_deck::open_with_default(&path)
}

/// 결과의 파일이 든 폴더를 열고 그 파일을 골라 둔다.
#[tauri::command]
pub fn docsearch_reveal_file(path: String) -> Result<(), String> {
    let target = PathBuf::from(&path);
    let mut command = Command::new("explorer.exe");
    if target.is_file() {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.raw_arg(format!("/select,\"{}\"", path));
        }
        #[cfg(not(windows))]
        command.arg(&path);
    } else if let Some(parent) = target.parent().filter(|p| p.is_dir()) {
        command.arg(parent);
    } else {
        return Err("폴더가 없습니다. 옮겨졌거나 지워졌을 수 있습니다.".to_string());
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    // explorer.exe 는 성공해도 0이 아닌 코드를 돌려주므로 결과를 따지지 않는다.
    let _ = command.spawn();
    Ok(())
}

/// 프로그램이 켜질 때: 문서 검색을 한 번이라도 연 PC에서만, 잠시 뒤 바뀐 파일을 대조한다.
pub fn schedule_startup_check(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(STARTUP_DELAY_SECS));
        // 한 번도 안 연 PC 에는 색인 파일을 만들지 않는다.
        let exists = app
            .path()
            .app_local_data_dir()
            .map(|d| d.join("docsearch").join("index.db").is_file())
            .unwrap_or(false);
        let initialized = exists
            && db::open(&app)
                .map(|conn| db::get_meta(&conn, "initialized").is_some())
                .unwrap_or(false);
        if initialized {
            index::start(&app);
        }
    });
}
