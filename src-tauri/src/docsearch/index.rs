//! 목록 대조와 색인 만들기.
//!
//! 폴더를 계속 감시하지 않는다. 대조는 세 경우에만 한다(계획서 5번):
//! 프로그램이 켜지고 1~2분 뒤 · 문서 검색 화면을 열 때(마지막 대조 10분 경과) · [지금 다시 읽기].
//! 대조는 파일을 열지 않고 수정 날짜·크기만 비교하고, 바뀐 파일만 다시 읽는다.

use super::db;
use super::extract::{self, Extracted, MAX_CONTENT_BYTES};
use super::tokenize;
use rusqlite::{params, Connection};
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};
use walkdir::WalkDir;

static RUNNING: AtomicBool = AtomicBool::new(false);
static RERUN: AtomicBool = AtomicBool::new(false);
/// [취소]를 눌렀을 때. 하던 파일까지만 하고 멈춘다. 못 읽은 문서는 '읽을 차례'로 남아 다음에 이어 읽는다.
static STOP: AtomicBool = AtomicBool::new(false);

pub fn stop_requested() -> bool {
    STOP.load(Ordering::SeqCst)
}

pub fn cancel() {
    RERUN.store(false, Ordering::SeqCst);
    if RUNNING.load(Ordering::SeqCst) {
        STOP.store(true, Ordering::SeqCst);
    }
}
static PROGRESS: Mutex<Option<Progress>> = Mutex::new(None);

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    /// "scan"(목록 대조) · "read"(문서 읽기)
    pub phase: String,
    pub done: usize,
    pub total: usize,
    pub current: String,
}

pub fn is_running() -> bool {
    RUNNING.load(Ordering::SeqCst)
}

pub fn progress() -> Option<Progress> {
    PROGRESS.lock().ok().and_then(|p| p.clone())
}

fn set_progress(app: &AppHandle, value: Option<Progress>, last_emit: &mut Instant, force: bool) {
    if let Ok(mut p) = PROGRESS.lock() {
        *p = value.clone();
    }
    if force || last_emit.elapsed() > Duration::from_millis(200) {
        *last_emit = Instant::now();
        let _ = app.emit("docsearch-progress", value);
    }
}

/// 뒤에서 대조를 시작한다. 이미 돌고 있으면 끝난 뒤 한 번 더 돌게 표시만 한다.
pub fn start(app: &AppHandle) -> bool {
    if RUNNING.swap(true, Ordering::SeqCst) {
        RERUN.store(true, Ordering::SeqCst);
        return false;
    }
    STOP.store(false, Ordering::SeqCst);
    let app = app.clone();
    std::thread::spawn(move || {
        loop {
            RERUN.store(false, Ordering::SeqCst);
            if let Err(error) = run(&app) {
                let _ = app.emit("docsearch-error", error);
            }
            if !RERUN.load(Ordering::SeqCst) || STOP.load(Ordering::SeqCst) {
                break;
            }
        }
        if let Ok(mut p) = PROGRESS.lock() {
            *p = None;
        }
        STOP.store(false, Ordering::SeqCst);
        RUNNING.store(false, Ordering::SeqCst);
        let _ = app.emit("docsearch-progress", Option::<Progress>::None);
        let _ = app.emit("docsearch-updated", ());
    });
    true
}

struct Seen {
    folder_id: i64,
    name: String,
    ext: String,
    size: i64,
    mtime: i64,
    cloud: bool,
}

struct Known {
    id: i64,
    folder_id: i64,
    size: i64,
    mtime: i64,
}

fn run(app: &AppHandle) -> Result<(), String> {
    let mut conn = db::open(app)?;
    db::set_meta(&conn, "last_check", &db::now_secs().to_string())?;
    let mut last_emit = Instant::now() - Duration::from_secs(1);

    // ① 목록 대조
    let finished = sync_list(&mut conn, |count, name| {
        set_progress(
            app,
            Some(Progress { phase: "scan".into(), done: count, total: 0, current: name.to_string() }),
            &mut last_emit,
            false,
        );
        !stop_requested()
    })?;
    if !finished {
        return Ok(());
    }

    // ② 바뀐 문서 읽기 (최근 것부터)
    let pending: Vec<(i64, String, String)> = {
        let mut stmt = conn
            .prepare("SELECT id, path, ext FROM files WHERE status='pending' ORDER BY mtime DESC")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .collect();
        rows
    };
    let total = pending.len();
    if total == 0 {
        db::set_meta(&conn, "last_done", &db::now_secs().to_string())?;
        return Ok(());
    }
    tokenize::warm_up();
    let (pdfs, others): (Vec<_>, Vec<_>) = pending.into_iter().partition(|(_, _, ext)| ext == "pdf");
    let mut done = 0usize;

    for (id, path, ext) in others {
        if stop_requested() {
            return Ok(());
        }
        let name = file_name(&path);
        set_progress(
            app,
            Some(Progress { phase: "read".into(), done, total, current: name }),
            &mut last_emit,
            false,
        );
        let kind = extract::content_kind(&ext).unwrap_or("");
        let result = extract::extract(Path::new(&path), kind);
        save_result(&mut conn, id, result)?;
        done += 1;
    }

    // PDF 는 파이썬 실행기를 한 번 띄워 여러 개를 읽는다.
    for batch in pdfs.chunks(200) {
        if stop_requested() {
            return Ok(());
        }
        let ids: HashMap<String, i64> = batch.iter().map(|(id, path, _)| (path.clone(), *id)).collect();
        let paths: Vec<String> = batch.iter().map(|(_, path, _)| path.clone()).collect();
        let mut handled: HashSet<i64> = HashSet::new();
        let outcome = super::pdf::read_pdfs(app, &paths, |path, result| {
            if let Some(&id) = ids.get(path) {
                set_progress(
                    app,
                    Some(Progress { phase: "read".into(), done, total, current: file_name(path) }),
                    &mut last_emit,
                    false,
                );
                if save_result(&mut conn, id, result).is_ok() {
                    handled.insert(id);
                }
                done += 1;
            }
        });
        match outcome {
            // 실행기를 띄우지 못했으면 '읽을 차례'로 남겨 다음 대조 때 다시 읽는다.
            Err(_) => done += batch.len() - handled.len(),
            // 실행기가 도중에 끝나 결과가 안 온 PDF 는 오류로 적는다(같은 파일로 매번 멈추지 않게).
            Ok(()) if stop_requested() => return Ok(()),
            Ok(()) => {
                for (id, _, _) in batch {
                    if !handled.contains(id) {
                        let _ = save_result(&mut conn, *id, Err("PDF를 읽지 못했습니다".to_string()));
                        done += 1;
                    }
                }
            }
        }
    }

    set_progress(app, None, &mut last_emit, true);
    db::set_meta(&conn, "last_done", &db::now_secs().to_string())?;
    Ok(())
}

/// 검색 폴더를 훑어 파일 목록을 색인과 맞춘다. 파일은 열지 않고 수정 날짜·크기만 본다.
/// 새 파일은 넣고, 날짜나 크기가 바뀐 파일은 글을 지우고 '읽을 차례'로 돌리고, 사라진 파일은 뺀다.
/// `on_file` 이 false 를 돌려주면(취소) 목록을 고치지 않고 Ok(false).
pub fn sync_list(conn: &mut Connection, mut on_file: impl FnMut(usize, &str) -> bool) -> Result<bool, String> {
    let folders = db::folders(conn)?;
    let mut seen: HashMap<String, Seen> = HashMap::new();
    let mut scanned_folders: HashSet<i64> = HashSet::new();
    for (folder_id, folder) in &folders {
        let root = PathBuf::from(folder);
        if !root.is_dir() {
            continue; // 연결이 끊긴 드라이브 등: 기존 목록을 지우지 않고 둔다
        }
        scanned_folders.insert(*folder_id);
        if !walk(&root, *folder_id, &mut seen, &mut on_file) {
            return Ok(false); // 다 훑지 못한 목록으로 지우면 안 되므로 그대로 둔다
        }
    }

    let known: HashMap<String, Known> = {
        let mut stmt = conn
            .prepare("SELECT id, path, folder_id, size, mtime FROM files")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(1)?,
                    Known { id: r.get(0)?, folder_id: r.get(2)?, size: r.get(3)?, mtime: r.get(4)? },
                ))
            })
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .collect();
        rows
    };

    let tx = conn.transaction().map_err(|e| e.to_string())?;
    for (path, item) in &seen {
        let status = initial_status(item);
        match known.get(path) {
            None => {
                tx.execute(
                    "INSERT INTO files(path, folder_id, name, ext, size, mtime, status) VALUES(?1,?2,?3,?4,?5,?6,?7)",
                    params![path, item.folder_id, item.name, item.ext, item.size, item.mtime, status],
                )
                .map_err(|e| e.to_string())?;
            }
            Some(old) if old.size != item.size || old.mtime != item.mtime => {
                db::clear_content(&tx, old.id)?;
                tx.execute(
                    "UPDATE files SET folder_id=?2, size=?3, mtime=?4, status=?5, detail='' WHERE id=?1",
                    params![old.id, item.folder_id, item.size, item.mtime, status],
                )
                .map_err(|e| e.to_string())?;
            }
            Some(old) if old.folder_id != item.folder_id => {
                // 검색 폴더를 바꿔 다른 폴더 아래로 들어간 파일(예: 바탕화면 → C 드라이브 전체)
                tx.execute("UPDATE files SET folder_id=?2 WHERE id=?1", params![old.id, item.folder_id])
                    .map_err(|e| e.to_string())?;
            }
            Some(_) => {}
        }
    }
    // 대조한 폴더에서 사라진 파일, 검색 폴더에서 뺀 폴더의 파일은 색인에서 뺀다.
    let folder_ids: HashSet<i64> = folders.iter().map(|(id, _)| *id).collect();
    for (path, old) in &known {
        if seen.contains_key(path) {
            continue;
        }
        if !folder_ids.contains(&old.folder_id) || scanned_folders.contains(&old.folder_id) {
            db::delete_file(&tx, old.id)?;
        }
    }
    tx.commit().map_err(|e| e.to_string())?;
    Ok(true)
}

fn file_name(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn initial_status(item: &Seen) -> &'static str {
    if extract::content_kind(&item.ext).is_none() {
        "name"
    } else if item.cloud {
        "cloud"
    } else if item.size as u64 > MAX_CONTENT_BYTES {
        "too_large"
    } else {
        "pending"
    }
}

/// 꺼낸 글을 조각으로 나눠 저장하고 상태를 적는다. 파일 하나를 한 번에 커밋해 바로 검색되게 한다.
pub fn save_result(
    conn: &mut Connection,
    file_id: i64,
    result: Result<Extracted, String>,
) -> Result<(), String> {
    let tx = conn.transaction().map_err(|e| e.to_string())?;
    db::clear_content(&tx, file_id)?;
    let (status, detail) = match result {
        Ok(Extracted::Text(text)) => {
            let pieces = chunk_text(&text);
            if pieces.is_empty() {
                ("no_text", String::new())
            } else {
                for (seq, piece) in pieces.iter().enumerate() {
                    tx.execute(
                        "INSERT INTO chunks(file_id, seq, text) VALUES(?1,?2,?3)",
                        params![file_id, seq as i64, piece],
                    )
                    .map_err(|e| e.to_string())?;
                    let rowid = tx.last_insert_rowid();
                    tx.execute(
                        "INSERT INTO chunks_fts(rowid, terms) VALUES(?1,?2)",
                        params![rowid, tokenize::index_text(piece)],
                    )
                    .map_err(|e| e.to_string())?;
                }
                ("ok", String::new())
            }
        }
        Ok(Extracted::Encrypted) => ("encrypted", String::new()),
        Ok(Extracted::Distribution) => ("distribution", String::new()),
        Err(error) => ("error", error.chars().take(200).collect()),
    };
    tx.execute(
        "UPDATE files SET status=?2, detail=?3 WHERE id=?1",
        params![file_id, status, detail],
    )
    .map_err(|e| e.to_string())?;
    tx.commit().map_err(|e| e.to_string())
}

/// 글을 600자 안팎의 조각으로 나눈다. 줄 단위로 모으고, 너무 긴 줄은 자른다.
/// 빈칸이 여러 개면 하나로 줄인다.
pub fn chunk_text(text: &str) -> Vec<String> {
    const TARGET: usize = 600;
    const MAX_LINE: usize = 1200;
    let mut out = Vec::new();
    let mut current = String::new();
    let mut current_len = 0usize;
    for raw in text.lines() {
        let line: String = raw.split_whitespace().collect::<Vec<_>>().join(" ");
        if line.is_empty() {
            continue;
        }
        let chars: Vec<char> = line.chars().collect();
        for piece in chars.chunks(MAX_LINE) {
            let piece: String = piece.iter().collect();
            let len = piece.chars().count();
            if !current.is_empty() {
                current.push('\n');
            }
            current.push_str(&piece);
            current_len += len;
            if current_len >= TARGET {
                out.push(std::mem::take(&mut current));
                current_len = 0;
            }
        }
    }
    if !current.trim().is_empty() {
        out.push(current);
    }
    out
}

// ───────────────────────────────────────────── 폴더 훑기

/// 시스템·숨김 폴더와 임시 파일은 건너뛴다.
const SKIP_DIRS: &[&str] = &[
    "node_modules",
    "appdata",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "__pycache__",
    "site-packages",
    "$recycle.bin",
];

/// 사용자 폴더 등에 직접 깔린 프로그램 폴더. 폴더 안에 이 흔적이 있으면 통째로 건너뛴다.
/// (예: C:\Users\이름\anaconda3 — 파이썬 배포판의 txt·csv 수천 개가 색인을 차지하고 검색 결과를 흐렸다)
/// 사용자가 검색 폴더로 직접 고른 폴더 자체는 따지지 않는다.
const PROGRAM_MARKERS: &[(&str, bool)] = &[
    ("conda-meta", true),     // 아나콘다·미니콘다 설치 폴더와 그 가상환경
    ("pyvenv.cfg", false),    // 파이썬 가상환경
    ("unins000.exe", false),  // Inno Setup 으로 설치한 프로그램
    ("uninstall.exe", false), // NSIS 로 설치한 프로그램
];

fn is_program_dir(dir: &Path) -> bool {
    PROGRAM_MARKERS.iter().any(|(name, is_dir)| {
        let marker = dir.join(name);
        if *is_dir {
            marker.is_dir()
        } else {
            marker.is_file()
        }
    })
}

fn skip_dir_name(name: &str) -> bool {
    let lower = name.to_lowercase();
    lower.starts_with('.') || lower.starts_with('$') || SKIP_DIRS.contains(&lower.as_str())
}

fn skip_file_name(name: &str) -> bool {
    let lower = name.to_lowercase();
    lower.starts_with("~$")
        || lower.starts_with(".~")
        || lower.starts_with('~') && lower.ends_with(".tmp")
        || lower.ends_with(".tmp")
        || lower.ends_with(".crdownload")
        || lower.ends_with(".part")
        || lower == "desktop.ini"
        || lower == "thumbs.db"
}

#[cfg(windows)]
fn attrs(meta: &std::fs::Metadata) -> u32 {
    use std::os::windows::fs::MetadataExt;
    meta.file_attributes()
}
#[cfg(not(windows))]
fn attrs(_meta: &std::fs::Metadata) -> u32 {
    0
}

const ATTR_HIDDEN: u32 = 0x2;
const ATTR_SYSTEM: u32 = 0x4;
const ATTR_OFFLINE: u32 = 0x1000;
const ATTR_RECALL_ON_OPEN: u32 = 0x40000;
const ATTR_RECALL_ON_DATA_ACCESS: u32 = 0x400000;

/// 다 훑었으면 true, 도중에 멈췄으면 false
fn walk(root: &Path, folder_id: i64, seen: &mut HashMap<String, Seen>, mut on_file: impl FnMut(usize, &str) -> bool) -> bool {
    let iter = WalkDir::new(root).follow_links(false).into_iter().filter_entry(|entry| {
        if entry.depth() == 0 || !entry.file_type().is_dir() {
            return true;
        }
        let name = entry.file_name().to_string_lossy();
        if skip_dir_name(&name) {
            return false;
        }
        match entry.metadata() {
            Ok(meta) if attrs(&meta) & (ATTR_HIDDEN | ATTR_SYSTEM) == 0 => !is_program_dir(entry.path()),
            _ => false,
        }
    });
    for entry in iter.flatten() {
        if !entry.file_type().is_file() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        if skip_file_name(&name) {
            continue;
        }
        let Ok(meta) = entry.metadata() else { continue };
        let a = attrs(&meta);
        if a & (ATTR_HIDDEN | ATTR_SYSTEM) != 0 {
            continue;
        }
        let path = entry.path().to_string_lossy().into_owned();
        if seen.contains_key(&path) {
            continue; // 겹치는 검색 폴더: 먼저 본 폴더에 둔다
        }
        let ext = Path::new(&name)
            .extension()
            .map(|e| e.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        let mtime = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        // 원드라이브의 '온라인 전용' 파일은 내용을 읽으면 내려받기가 시작되므로 이름으로만 찾는다.
        let cloud = a & (ATTR_OFFLINE | ATTR_RECALL_ON_OPEN | ATTR_RECALL_ON_DATA_ACCESS) != 0;
        if !on_file(seen.len() + 1, &name) {
            return false;
        }
        seen.insert(path, Seen { folder_id, name, ext, size: meta.len() as i64, mtime, cloud });
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunks_collapse_spaces_and_split() {
        let text = "가   나\n\n다\t라\n".to_string() + &"마".repeat(1300);
        let pieces = chunk_text(&text);
        assert_eq!(pieces[0].lines().next().unwrap(), "가 나");
        assert!(pieces.iter().all(|p| p.chars().count() <= 1200 + 10));
        let joined: String = pieces.concat();
        assert_eq!(joined.matches('마').count(), 1300);
    }

    /// 읽을 차례인 문서(PDF 제외)를 읽어 색인에 넣는다(시험용).
    fn read_pending(conn: &mut Connection) {
        let pending: Vec<(i64, String, String)> = conn
            .prepare("SELECT id, path, ext FROM files WHERE status='pending'")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap()
            .flatten()
            .collect();
        for (id, path, ext) in pending {
            let kind = extract::content_kind(&ext).unwrap();
            save_result(conn, id, extract::extract(Path::new(&path), kind)).unwrap();
        }
    }

    #[test]
    fn edited_document_is_reread_and_deleted_one_removed() {
        use crate::docsearch::search::{search, Filters};
        let dir = std::env::temp_dir().join(format!("ds-sync-{}", std::process::id()));
        let docs = dir.join("문서");
        std::fs::create_dir_all(&docs).unwrap();
        let mut conn = db::open_at(&dir.join("i.db")).unwrap();
        conn.execute("INSERT INTO folders(path) VALUES(?1)", [docs.to_string_lossy()]).unwrap();
        let a = docs.join("회의록.txt");
        let b = docs.join("지울문서.txt");
        std::fs::write(&a, "바나나 예산 회의").unwrap();
        std::fs::write(&b, "사과 계획").unwrap();
        sync_list(&mut conn, |_, _| true).unwrap();
        read_pending(&mut conn);
        let f = Filters::default();
        assert_eq!(search(&conn, "바나나", &f).unwrap().hits.len(), 1);

        // 내용을 고치고(수정 시각도 바뀜) 하나는 지운 뒤 다시 대조
        std::fs::write(&a, "수박 예산 회의 내용 변경").unwrap();
        let later = std::time::SystemTime::now() + std::time::Duration::from_secs(120);
        std::fs::File::options().write(true).open(&a).unwrap().set_modified(later).unwrap();
        std::fs::remove_file(&b).unwrap();
        sync_list(&mut conn, |_, _| true).unwrap();
        read_pending(&mut conn);
        assert_eq!(search(&conn, "바나나", &f).unwrap().hits.len(), 0, "예전 내용은 빠져야 함");
        assert_eq!(search(&conn, "수박", &f).unwrap().hits.len(), 1, "바뀐 내용으로 찾혀야 함");
        assert_eq!(search(&conn, "사과", &f).unwrap().hits.len(), 0, "지운 파일은 빠져야 함");

        // 검색 폴더를 상위 폴더로 바꿔도 파일이 사라지지 않음
        conn.execute("DELETE FROM folders", []).unwrap();
        conn.execute("INSERT INTO folders(path) VALUES(?1)", [dir.to_string_lossy()]).unwrap();
        sync_list(&mut conn, |_, _| true).unwrap();
        assert_eq!(search(&conn, "수박", &f).unwrap().hits.len(), 1, "상위 폴더로 바꿔도 남아야 함");
        drop(conn);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn skips_temp_and_system() {
        assert!(skip_file_name("~$보고서.hwp"));
        assert!(skip_file_name("abc.TMP"));
        assert!(!skip_file_name("2026 예산서.xlsx"));
        assert!(skip_dir_name("$RECYCLE.BIN"));
        assert!(skip_dir_name(".git"));
        assert!(!skip_dir_name("업무자료"));
    }

    #[test]
    fn program_folders_are_skipped_but_chosen_root_is_not() {
        let dir = std::env::temp_dir().join(format!("ds-prog-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let make = |rel: &str, text: &str| {
            let p = dir.join(rel);
            std::fs::create_dir_all(p.parent().unwrap()).unwrap();
            std::fs::write(p, text).unwrap();
        };
        make("업무/회의록.txt", "회의");
        make("anaconda3/conda-meta/history", "");
        make("anaconda3/pkgs/라이선스.txt", "x");
        make("anaconda3/envs/py311/conda-meta/history", "");
        make("venv/pyvenv.cfg", "home = x");
        make("venv/Lib/notes.txt", "x");
        make("도구/unins000.exe", "");
        make("도구/readme.txt", "x");
        make("설치본/uninstall.exe", "");
        make("설치본/설명.txt", "x");
        make("python/Lib/site-packages/pkg/data.csv", "x");
        // 일반 폴더에 conda-meta '파일'이 있는 것은 프로그램 흔적이 아님
        make("자료/conda-meta", "메모");
        make("자료/보고서.txt", "보고");

        let mut seen = HashMap::new();
        assert!(walk(&dir, 1, &mut seen, |_, _| true));
        let mut names: Vec<&str> = seen.values().map(|s| s.name.as_str()).collect();
        names.sort();
        assert_eq!(names, vec!["conda-meta", "보고서.txt", "회의록.txt"]);

        // 사용자가 프로그램 폴더 자체를 검색 폴더로 고르면 그 안은 읽는다
        let mut seen = HashMap::new();
        assert!(walk(&dir.join("도구"), 1, &mut seen, |_, _| true));
        assert_eq!(seen.len(), 2);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
