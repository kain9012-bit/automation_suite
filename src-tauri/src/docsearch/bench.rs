//! 실제 폴더로 재 보기(개발용, 평소 시험에서는 건너뜀).
//! DS_BENCH_DIR=폴더 DS_BENCH_DB=색인파일 DS_RUNNER=bridge/runner.py [DS_DUMP=글 내보낼 폴더]
//! cargo test --lib docsearch::bench -- --ignored --nocapture

use super::extract::{self, Extracted};
use super::{db, index, search};
use std::path::Path;
use std::time::Instant;

#[test]
#[ignore]
fn bench_folder() {
    let dir = std::env::var("DS_BENCH_DIR").expect("DS_BENCH_DIR");
    let db_path = std::env::var("DS_BENCH_DB").expect("DS_BENCH_DB");
    let runner = std::env::var("DS_RUNNER").expect("DS_RUNNER");
    let _ = std::fs::remove_file(&db_path);
    let mut conn = db::open_at(Path::new(&db_path)).unwrap();
    let t0 = Instant::now();
    let mut pdfs = Vec::new();
    let mut text_bytes = 0usize;
    for entry in std::fs::read_dir(&dir).unwrap().flatten() {
        let path = entry.path();
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        let ext = path.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
        let meta = entry.metadata().unwrap();
        conn.execute(
            "INSERT INTO files(path, folder_id, name, ext, size, mtime, status) VALUES(?1,1,?2,?3,?4,0,'pending')",
            rusqlite::params![path.to_string_lossy(), name, ext, meta.len() as i64],
        )
        .unwrap();
        let id = conn.last_insert_rowid();
        match extract::content_kind(&ext) {
            Some("pdf") => pdfs.push((id, path.to_string_lossy().into_owned())),
            Some(kind) => {
                let r = extract::extract(&path, kind);
                if let Ok(Extracted::Text(t)) = &r {
                    text_bytes += t.len();
                }
                index::save_result(&mut conn, id, r).unwrap();
            }
            None => {}
        }
    }
    let t_other = t0.elapsed();
    let list = format!("{db_path}.pdfs.json");
    std::fs::write(&list, serde_json::to_vec(&pdfs.iter().map(|(_, p)| p.clone()).collect::<Vec<_>>()).unwrap()).unwrap();
    let out = std::process::Command::new("python3").arg(&runner).arg("--pdf-text-list").arg(&list).output().unwrap();
    let t1 = Instant::now();
    for line in String::from_utf8_lossy(&out.stdout).lines() {
        let v: serde_json::Value = match serde_json::from_str(line) { Ok(v) => v, Err(_) => continue };
        let p = v["path"].as_str().unwrap_or("");
        let id = pdfs.iter().find(|(_, q)| q == p).map(|(id, _)| *id).unwrap();
        let r = match v["status"].as_str() {
            Some("ok") | Some("no_text") => {
                let t = v["text"].as_str().unwrap_or("").to_string();
                text_bytes += t.len();
                Ok(Extracted::Text(t))
            }
            Some("encrypted") => Ok(Extracted::Encrypted),
            _ => Err(v["error"].as_str().unwrap_or("").to_string()),
        };
        index::save_result(&mut conn, id, r).unwrap();
    }
    println!("non-pdf {:?}, pdf(index only) {:?}, total {:?}", t_other, t1.elapsed(), t0.elapsed());
    let mut stmt = conn.prepare("SELECT status, count(*) FROM files GROUP BY status").unwrap();
    for row in stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))).unwrap().flatten() {
        println!("status {:?}", row);
    }
    let mut stmt = conn.prepare("SELECT name, detail FROM files WHERE status='error'").unwrap();
    for row in stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))).unwrap().flatten() {
        println!("error {:?}", row);
    }
    conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE); VACUUM;").unwrap();
    let size = std::fs::metadata(&db_path).unwrap().len();
    println!("text bytes {text_bytes}, db bytes {size}, ratio {:.2}", size as f64 / text_bytes.max(1) as f64);
    if let Ok(dump) = std::env::var("DS_DUMP") {
        std::fs::create_dir_all(&dump).unwrap();
        let mut stmt = conn.prepare("SELECT f.name, group_concat(c.text, char(10)) FROM files f JOIN chunks c ON c.file_id=f.id GROUP BY f.id").unwrap();
        for (name, text) in stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))).unwrap().flatten() {
            std::fs::write(Path::new(&dump).join(format!("{name}.txt")), text).unwrap();
        }
    }
    for q in std::env::var("DS_QUERIES").unwrap_or_default().split('|').filter(|q| !q.is_empty()) {
        let t = Instant::now();
        let r = search::search(&conn, q, &search::Filters::default()).unwrap();
        println!("query {q:?}: {} hits in {:?}; top: {:?}", r.total, t.elapsed(), r.hits.iter().take(3).map(|h| &h.name).collect::<Vec<_>>());
    }
}
