//! 색인 파일(SQLite). 도큐파인더와 같은 구성: folders · files · chunks · chunks_fts(FTS5)
//!
//! 위치: %LOCALAPPDATA%\kr.go.jbe.automation-suite\docsearch\index.db
//! WAL 방식으로 열어, 색인을 쓰는 동안에도 검색(읽기)이 막히지 않게 한다.

use rusqlite::{params, Connection, OptionalExtension};
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager};

/// 색인 구조가 바뀌면 올린다. 다르면 색인을 처음부터 다시 만든다(검색 폴더는 남김).
const SCHEMA_VERSION: i64 = 1;

pub fn index_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| format!("색인 폴더를 찾지 못했습니다: {e}"))?
        .join("docsearch");
    std::fs::create_dir_all(&dir).map_err(|e| format!("색인 폴더를 만들지 못했습니다: {e}"))?;
    Ok(dir)
}

pub fn open(app: &AppHandle) -> Result<Connection, String> {
    open_at(&index_dir(app)?.join("index.db"))
}

pub fn open_at(path: &Path) -> Result<Connection, String> {
    let conn = Connection::open(path).map_err(|e| format!("색인 파일을 열지 못했습니다: {e}"))?;
    conn.busy_timeout(std::time::Duration::from_secs(10)).ok();
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA synchronous=NORMAL;
         PRAGMA foreign_keys=ON;",
    )
    .map_err(|e| e.to_string())?;
    migrate(&conn)?;
    Ok(conn)
}

fn migrate(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
         CREATE TABLE IF NOT EXISTS folders(
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            added_at INTEGER NOT NULL DEFAULT 0
         );",
    )
    .map_err(|e| e.to_string())?;
    let version: i64 = get_meta(conn, "schema")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    if version != SCHEMA_VERSION {
        conn.execute_batch(
            "DROP TABLE IF EXISTS chunks_fts;
             DROP TABLE IF EXISTS chunks;
             DROP TABLE IF EXISTS files;",
        )
        .map_err(|e| e.to_string())?;
    }
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS files(
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            folder_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            ext TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime INTEGER NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
         );
         CREATE INDEX IF NOT EXISTS files_folder ON files(folder_id);
         CREATE INDEX IF NOT EXISTS files_status ON files(status);
         CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            text TEXT NOT NULL
         );
         CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
         CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            terms, content='', contentless_delete=1, tokenize='unicode61 remove_diacritics 0'
         );",
    )
    .map_err(|e| e.to_string())?;
    set_meta(conn, "schema", &SCHEMA_VERSION.to_string())?;
    Ok(())
}

pub fn get_meta(conn: &Connection, key: &str) -> Option<String> {
    conn.query_row("SELECT value FROM meta WHERE key=?1", [key], |r| r.get(0))
        .optional()
        .ok()
        .flatten()
}

pub fn set_meta(conn: &Connection, key: &str, value: &str) -> Result<(), String> {
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params![key, value],
    )
    .map(|_| ())
    .map_err(|e| e.to_string())
}

/// 파일의 글 조각과 색인을 지운다(파일 행은 남김).
pub fn clear_content(conn: &Connection, file_id: i64) -> Result<(), String> {
    conn.execute(
        "DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE file_id=?1)",
        [file_id],
    )
    .map_err(|e| e.to_string())?;
    conn.execute("DELETE FROM chunks WHERE file_id=?1", [file_id])
        .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn delete_file(conn: &Connection, file_id: i64) -> Result<(), String> {
    clear_content(conn, file_id)?;
    conn.execute("DELETE FROM files WHERE id=?1", [file_id])
        .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn folders(conn: &Connection) -> Result<Vec<(i64, String)>, String> {
    let mut stmt = conn
        .prepare("SELECT id, path FROM folders ORDER BY id")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .collect();
    Ok(rows)
}

pub fn now_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}
