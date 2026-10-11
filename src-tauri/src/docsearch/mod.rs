//! 문서 검색(1.4.4): 내 PC 문서를 파일 이름과 내용으로 찾는다.
//!
//! 도큐파인더의 키워드 검색 방식(SQLite FTS5 + Lindera)을 가볍게 옮겼다.
//! 미리보기·OCR·AI 는 없다. 다른 도구 코드와 섞이지 않게 이 폴더 안에만 둔다.
//! 계획서: Project 문서 claude/1.4.4_문서검색_계획.md

mod db;
mod extract;
mod icons;
mod index;
mod pdf;
mod search;
mod tokenize;
mod types;
#[cfg(test)]
mod bench;

use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;
use tauri::{AppHandle, Manager};

/// 사용자가 검색 폴더를 직접 골라 시작했다는 표시. 이것이 있어야 색인을 만든다.
/// (1.4.4 첫 시험판은 바탕화면·문서·다운로드를 알아서 넣고 'initialized' 를 썼다. 그 PC 도 한 번은 고르게 한다.)
const CONFIRMED_KEY: &str = "folders_confirmed";

/// 화면을 열 때 이만큼 지났으면 바뀐 파일을 대조한다.
const SCREEN_RECHECK_SECS: i64 = 10 * 60;
/// 프로그램이 켜지고 이만큼 뒤에 대조한다(켜진 직후 PC가 바쁠 때를 피함).
const STARTUP_DELAY_SECS: u64 = 90;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FolderInfo {
    path: String,
    exists: bool,
    /// 이 폴더 안의 문서 수(겹치는 폴더는 각각 센다)
    documents: i64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    /// 사용자가 검색 폴더를 골라 '시작'을 눌렀는지. 아니면 화면이 먼저 폴더를 고르게 한다.
    confirmed: bool,
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
    /// 내용까지 찾는 문서 종류(types.rs 의 id). 나머지는 이름으로만 찾는다.
    content_types: Vec<String>,
}

fn status(app: &AppHandle) -> Result<Status, String> {
    let conn = db::open(app)?;
    let count = |sql: &str| conn.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap_or(0);
    let folders = db::folders(&conn)?
        .into_iter()
        .map(|(_, path)| {
            let prefix = if path.ends_with(['\\', '/']) { path.clone() } else { format!("{path}\\") };
            let documents = conn
                .query_row(
                    "SELECT count(*) FROM files WHERE status <> 'name'
                     AND lower(substr(path, 1, length(?1))) = lower(?1)",
                    [&prefix],
                    |r| r.get::<_, i64>(0),
                )
                .unwrap_or(0);
            FolderInfo { exists: PathBuf::from(&path).is_dir(), path, documents }
        })
        .collect();
    let index_bytes = index_bytes(app)?;
    Ok(Status {
        confirmed: db::get_meta(&conn, CONFIRMED_KEY).is_some(),
        folders,
        files: count("SELECT count(*) FROM files"),
        documents: count("SELECT count(*) FROM files WHERE status <> 'name'"),
        pending: count("SELECT count(*) FROM files WHERE status='pending'"),
        last_check: db::get_meta(&conn, "last_check").and_then(|v| v.parse().ok()).unwrap_or(0),
        running: index::is_running(),
        progress: index::progress(),
        index_bytes,
        content_types: types::enabled(&conn),
    })
}

/// 색인 파일 크기(index.db + 쓰는 중인 WAL)
fn index_bytes(app: &AppHandle) -> Result<u64, String> {
    let dir = db::index_dir(app)?;
    Ok(["index.db", "index.db-wal"]
        .iter()
        .filter_map(|n| std::fs::metadata(dir.join(n)).ok())
        .map(|m| m.len())
        .sum())
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

/// 문서 검색 화면을 열 때. 검색 폴더를 고르기 전이면 아무것도 읽지 않는다(화면이 먼저 고르게 함).
/// 골라 둔 뒤라면 마지막 대조 후 10분이 지났을 때 뒤에서 대조한다. 검색은 기존 색인으로 바로 된다.
#[tauri::command]
pub async fn docsearch_open_screen(app: AppHandle) -> Result<Status, String> {
    blocking(move || {
        let conn = db::open(&app)?;
        if db::get_meta(&conn, CONFIRMED_KEY).is_some() {
            let last: i64 = db::get_meta(&conn, "last_check").and_then(|v| v.parse().ok()).unwrap_or(0);
            if db::now_secs() - last >= SCREEN_RECHECK_SECS {
                index::start(&app);
            }
        }
        status(&app)
    })
    .await
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FolderChoice {
    label: String,
    path: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FolderChoices {
    /// 바탕화면 · 문서 · 다운로드
    common: Vec<FolderChoice>,
    /// C:\ D:\ … 드라이브 전체
    drives: Vec<FolderChoice>,
}

/// 검색 폴더를 고를 때 보여 줄 후보
#[tauri::command]
pub fn docsearch_folder_choices(app: AppHandle) -> FolderChoices {
    let path = app.path();
    let common = [("바탕화면", path.desktop_dir()), ("문서", path.document_dir()), ("다운로드", path.download_dir())]
        .into_iter()
        .filter_map(|(label, dir)| dir.ok().filter(|d| d.is_dir()).map(|d| (label, d)))
        .map(|(label, dir)| FolderChoice { label: label.to_string(), path: dir.to_string_lossy().into_owned() })
        .collect();
    let drives = if cfg!(windows) {
        (b'C'..=b'Z')
            .map(|letter| format!("{}:\\", letter as char))
            .filter(|root| PathBuf::from(root).is_dir())
            .map(|root| FolderChoice { label: format!("{} 드라이브 전체", &root[..2]), path: root })
            .collect()
    } else {
        Vec::new()
    };
    FolderChoices { common, drives }
}

#[tauri::command]
pub async fn docsearch_status(app: AppHandle) -> Result<Status, String> {
    blocking(move || status(&app)).await
}

/// 진행 중인 대조·읽기를 멈춘다. 못 읽은 문서는 다음에 이어 읽는다.
#[tauri::command]
pub fn docsearch_cancel() {
    index::cancel();
}

/// 결과 목록에 보일 파일 아이콘(그 PC 탐색기의 아이콘). 확장자 → PNG data URL. 못 받은 것은 빠진다.
#[tauri::command]
pub async fn docsearch_file_icons(exts: Vec<String>) -> Result<std::collections::HashMap<String, String>, String> {
    blocking(move || Ok(icons::file_icons(&exts))).await
}

/// 처음 고를 때 켜 두는 내용 검색 종류
#[tauri::command]
pub fn docsearch_default_content_types() -> Vec<String> {
    types::DEFAULT_NEW.iter().map(|s| s.to_string()).collect()
}

/// 내용 검색 종류를 바꾼다. 하던 대조·읽기를 멈추고 다시 돌며, 그 대조에서 끈 종류의 글을 지우고
/// 켠 종류를 읽을 차례로 돌린다(index::sync_list).
#[tauri::command]
pub async fn docsearch_set_content_types(app: AppHandle, content_types: Vec<String>) -> Result<Status, String> {
    blocking(move || {
        let conn = db::open(&app)?;
        types::set(&conn, &content_types)?;
        drop(conn);
        index::restart(&app);
        status(&app)
    })
    .await
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CompactResult {
    before: u64,
    after: u64,
    status: Status,
}

/// [색인 정리]: 하던 대조·읽기를 멈추고 색인 파일의 빈 자리를 비운다. 끝나면 멈췄던 읽기를 이어 한다.
#[tauri::command]
pub async fn docsearch_compact(app: AppHandle) -> Result<CompactResult, String> {
    blocking(move || {
        let before = index_bytes(&app)?;
        index::exclusive(&app, "compact", || {
            let conn = db::open(&app)?;
            db::compact(&conn)
        })?;
        let after = index_bytes(&app)?;
        Ok(CompactResult { before, after, status: status(&app)? })
    })
    .await
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
pub async fn docsearch_set_folders(
    app: AppHandle,
    folders: Vec<String>,
    content_types: Option<Vec<String>>,
) -> Result<Status, String> {
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
        db::set_meta(&tx, CONFIRMED_KEY, "1")?;
        // 처음 고를 때 함께 고른 내용 검색 종류. 나중에 폴더만 바꿀 때는 그대로 둔다.
        if let Some(ids) = &content_types {
            types::set(&tx, ids)?;
        }
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
                .map(|conn| db::get_meta(&conn, CONFIRMED_KEY).is_some())
                .unwrap_or(false);
        if initialized {
            index::start(&app);
        }
    });
}
