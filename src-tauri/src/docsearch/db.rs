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
    // 같으면 쓰지 않는다. 열 때마다 쓰면 [색인 정리] 중에 검색·상태 보기가 쓰기 차례를 기다리게 된다.
    if version != SCHEMA_VERSION {
        set_meta(conn, "schema", &SCHEMA_VERSION.to_string())?;
    }
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

/// [색인 정리]: 지운 글이 남긴 빈 자리를 비워 파일 크기를 줄인다.
/// 내용 검색 종류를 끄거나 폴더를 빼서 글을 지워도 파일은 그대로라, 사용자가 원할 때 한다.
/// ① FTS 색인을 하나로 합치며 지운 항목을 걷어 내고 ② VACUUM 으로 파일을 새로 쓰고
/// ③ WAL 을 비운다. 실패해도(디스크 공간 부족 등) 색인은 원래대로 남는다(SQLite 가 되돌림).
pub fn compact(conn: &Connection) -> Result<(), String> {
    let friendly = |e: rusqlite::Error| {
        let text = e.to_string();
        if text.contains("full") {
            "디스크 여유 공간이 부족해 정리하지 못했습니다. 색인은 그대로입니다.".to_string()
        } else {
            format!("색인을 정리하지 못했습니다: {text}")
        }
    };
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')", [])
        .map_err(friendly)?;
    conn.execute_batch("VACUUM;").map_err(friendly)?;
    conn.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |_| Ok(()))
        .map_err(friendly)?;
    Ok(())
}

pub fn now_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 글 조각 `files`×`per`개를 넣는다. 조각마다 낱말이 달라 색인이 커진다.
    fn fill(conn: &Connection, files: i64, per: i64) {
        let tx = conn.unchecked_transaction().unwrap();
        for f in 0..files {
            tx.execute(
                "INSERT INTO files(id,path,folder_id,name,ext,size,mtime,status) VALUES(?1,?2,1,'a','txt',1,1,'ok')",
                params![f + 1, format!("C:\\d\\{f}.txt")],
            )
            .unwrap();
            for s in 0..per {
                let id = f * per + s + 1;
                let terms: String = (0..60).map(|k| format!("w{}x{} ", (id * 7 + k) % 50_000, k % 9)).collect();
                tx.execute("INSERT INTO chunks(id,file_id,seq,text) VALUES(?1,?2,?3,?4)", params![id, f + 1, s, terms])
                    .unwrap();
                tx.execute("INSERT INTO chunks_fts(rowid,terms) VALUES(?1,?2)", params![id, terms]).unwrap();
            }
        }
        tx.commit().unwrap();
    }

    fn size(path: &Path) -> u64 {
        ["", "-wal"].iter().filter_map(|s| std::fs::metadata(format!("{}{s}", path.display())).ok()).map(|m| m.len()).sum()
    }

    #[test]
    fn compact_shrinks_after_clearing_content_and_keeps_the_rest() {
        let dir = std::env::temp_dir().join(format!("ds-compact-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("index.db");
        let conn = open_at(&path).unwrap();
        fill(&conn, 300, 20);
        // 3분의 2 파일의 글을 지운다(내용 검색 종류를 끈 것과 같다).
        for f in 1..=300 {
            if f % 3 != 0 {
                clear_content(&conn, f).unwrap();
            }
        }
        conn.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |_| Ok(())).unwrap();
        let before = size(&path);
        let hits = |c: &Connection, term: &str| -> i64 {
            c.query_row("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?1", [term], |r| r.get(0)).unwrap()
        };
        // 남은 파일(3의 배수)의 첫 조각 낱말
        let keep_id = 2 * 20 + 1; // 파일 3의 첫 조각
        let keep_term = format!("w{}x0", (keep_id * 7) % 50_000);
        let kept = hits(&conn, &keep_term);
        assert!(kept >= 1);

        // 정리하는 동안 다른 연결이 열고 읽을 수 있는지(검색·상태 보기).
        let reader_path = path.clone();
        let reader = std::thread::spawn(move || {
            let mut ok = 0;
            for _ in 0..20 {
                let c = open_at(&reader_path).unwrap();
                let n: i64 = c.query_row("SELECT count(*) FROM files", [], |r| r.get(0)).unwrap();
                assert_eq!(n, 300);
                ok += 1;
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            ok
        });
        compact(&conn).unwrap();
        assert_eq!(reader.join().unwrap(), 20);

        let after = size(&path);
        assert!(after * 2 < before, "크기가 줄어야 함: {before} → {after}");
        assert_eq!(hits(&conn, &keep_term), kept, "남은 글은 그대로 찾아짐");
        // 색인 결과가 남은 글 조각과 정확히 맞는지(지운 글은 안 나오고, 남은 글은 다 나옴).
        let in_text = |term: &str| -> i64 {
            conn.query_row("SELECT count(*) FROM chunks WHERE (' ' || text) LIKE '% ' || ?1 || ' %'", [term], |r| r.get(0))
                .unwrap()
        };
        for id in [1i64, 7, 41, 999, 5_999] {
            let term = format!("w{}x0", (id * 7) % 50_000);
            assert_eq!(hits(&conn, &term), in_text(&term), "{term}");
        }
        drop(conn);
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 큰 색인에서 정리에 걸리는 시간(수동 확인용).
    #[test]
    #[ignore]
    fn compact_timing() {
        let dir = std::env::temp_dir().join("ds-compact-timing");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("index.db");
        let conn = open_at(&path).unwrap();
        fill(&conn, 5000, 60);
        for f in 1..=5000 {
            if f % 2 == 0 {
                clear_content(&conn, f).unwrap();
            }
        }
        conn.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |_| Ok(())).unwrap();
        let before = size(&path);
        let t = std::time::Instant::now();
        compact(&conn).unwrap();
        eprintln!("compact {:.1}MB → {:.1}MB in {:?}", before as f64 / 1e6, size(&path) as f64 / 1e6, t.elapsed());
        drop(conn);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
