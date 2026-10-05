//! 검색: 파일 이름과 문서 내용에서 함께 찾는다.
//!
//! 띄어 쓴 낱말마다 "이름에 들어 있음 ∪ 내용에 들어 있음"을 구하고, 모든 낱말을 만족하는 파일만 남긴다.
//! 내용은 Lindera 로 나눈 낱말을 앞부분 일치로 찾는다(FTS5). 사전에 없는 줄임말 등으로
//! 그렇게 하나도 안 나오면 글자 그대로 포함되는지 보조로 찾는다.

use super::tokenize;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

const MAX_RESULTS: usize = 200;
const MAX_CANDIDATES: usize = 5000;

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Filters {
    /// 확장자 묶음: hwp · pdf · excel · word · ppt · text · other. 비어 있으면 전부.
    #[serde(default)]
    pub kinds: Vec<String>,
    /// 이 폴더 안만
    #[serde(default)]
    pub folder: Option<String>,
    /// 이 시각(초) 이후에 고친 것만
    #[serde(default)]
    pub since: Option<i64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Hit {
    pub path: String,
    pub name: String,
    pub folder: String,
    pub ext: String,
    pub size: i64,
    pub mtime: i64,
    pub status: String,
    pub snippet: String,
    pub name_match: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchResult {
    pub hits: Vec<Hit>,
    /// 조건에 맞는 전체 수(보여 주는 것은 최대 200개)
    pub total: usize,
    /// 화면에서 강조할 글자들
    pub highlights: Vec<String>,
}

fn kind_exts(kind: &str) -> &'static [&'static str] {
    match kind {
        "hwp" => &["hwp", "hwpx"],
        "pdf" => &["pdf"],
        "excel" => &["xlsx", "xls", "csv"],
        "word" => &["docx", "doc"],
        "ppt" => &["pptx", "ppt"],
        "text" => &["txt", "md"],
        _ => &[],
    }
}

fn kind_matches(kinds: &[String], ext: &str) -> bool {
    if kinds.is_empty() {
        return true;
    }
    let known = ["hwp", "pdf", "excel", "word", "ppt", "text"];
    kinds.iter().any(|k| {
        if k == "other" {
            !known.iter().any(|kk| kind_exts(kk).contains(&ext))
        } else {
            kind_exts(k).contains(&ext)
        }
    })
}

struct WordMatch {
    /// file_id → (내용 점수: bm25, 작을수록 잘 맞음, 가장 잘 맞는 조각 id)
    content: HashMap<i64, (f64, Option<i64>)>,
    names: HashSet<i64>,
}

fn match_word(conn: &Connection, word: &str) -> Result<WordMatch, String> {
    let mut names = HashSet::new();
    {
        let mut stmt = conn
            .prepare_cached("SELECT id FROM files WHERE instr(lower(name), ?1) > 0 LIMIT 20000")
            .map_err(|e| e.to_string())?;
        for id in stmt.query_map([word], |r| r.get::<_, i64>(0)).map_err(|e| e.to_string())?.flatten() {
            names.insert(id);
        }
    }

    let mut content: HashMap<i64, (f64, Option<i64>)> = HashMap::new();
    let terms = tokenize::terms(word);
    if !terms.is_empty() {
        let query = terms
            .iter()
            .map(|t| format!("\"{}\"*", t.replace('"', "")))
            .collect::<Vec<_>>()
            .join(" AND ");
        let mut stmt = conn
            .prepare_cached(
                "SELECT c.file_id, c.id, bm25(chunks_fts) FROM chunks_fts
                 JOIN chunks c ON c.id = chunks_fts.rowid
                 WHERE chunks_fts MATCH ?1 LIMIT 50000",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([query], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?, r.get::<_, f64>(2)?)))
            .map_err(|e| e.to_string())?;
        for (file_id, chunk_id, rank) in rows.flatten() {
            let entry = content.entry(file_id).or_insert((f64::MAX, None));
            if rank < entry.0 {
                *entry = (rank, Some(chunk_id));
            }
        }
    }
    // 보조 검색: 낱말로 하나도 안 나오면 글자 그대로 들어 있는지
    if content.is_empty() && word.chars().count() >= 2 {
        let mut stmt = conn
            .prepare_cached("SELECT file_id, min(id) FROM chunks WHERE instr(lower(text), ?1) > 0 GROUP BY file_id LIMIT 5000")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([word], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)))
            .map_err(|e| e.to_string())?;
        for (file_id, chunk_id) in rows.flatten() {
            content.insert(file_id, (0.0, Some(chunk_id)));
        }
    }
    Ok(WordMatch { content, names })
}

pub fn search(conn: &Connection, query: &str, filters: &Filters) -> Result<SearchResult, String> {
    let words: Vec<String> = query
        .split_whitespace()
        .map(|w| w.to_lowercase())
        .filter(|w| !w.is_empty())
        .take(8)
        .collect();
    if words.is_empty() {
        return Ok(SearchResult { hits: Vec::new(), total: 0, highlights: Vec::new() });
    }

    let matches: Vec<WordMatch> = words.iter().map(|w| match_word(conn, w)).collect::<Result<_, _>>()?;

    // 모든 낱말을 만족하는 파일
    let mut candidates: Option<HashSet<i64>> = None;
    for m in &matches {
        let set: HashSet<i64> = m.names.iter().copied().chain(m.content.keys().copied()).collect();
        candidates = Some(match candidates {
            None => set,
            Some(prev) => prev.intersection(&set).copied().collect(),
        });
    }
    let candidates = candidates.unwrap_or_default();

    struct Row {
        id: i64,
        path: String,
        name: String,
        ext: String,
        size: i64,
        mtime: i64,
        status: String,
    }
    let folder = filters.folder.as_ref().map(|f| f.trim_end_matches(['\\', '/']).to_lowercase());
    let mut rows: Vec<Row> = Vec::new();
    {
        let mut stmt = conn
            .prepare_cached("SELECT path, name, ext, size, mtime, status FROM files WHERE id=?1")
            .map_err(|e| e.to_string())?;
        for &id in candidates.iter().take(MAX_CANDIDATES * 4) {
            let Ok(row) = stmt.query_row([id], |r| {
                Ok(Row {
                    id,
                    path: r.get(0)?,
                    name: r.get(1)?,
                    ext: r.get(2)?,
                    size: r.get(3)?,
                    mtime: r.get(4)?,
                    status: r.get(5)?,
                })
            }) else {
                continue;
            };
            if !kind_matches(&filters.kinds, &row.ext) {
                continue;
            }
            if let Some(since) = filters.since {
                if row.mtime < since {
                    continue;
                }
            }
            if let Some(folder) = &folder {
                let p = row.path.to_lowercase();
                if !(p.starts_with(&format!("{folder}\\")) || p.starts_with(&format!("{folder}/"))) {
                    continue;
                }
            }
            rows.push(row);
        }
    }
    let total = rows.len();

    // 점수: 이름에 든 낱말 수(많을수록 위) → 내용 점수 합(작을수록 위) → 최근 것
    let score = |id: i64| -> (usize, f64) {
        let name_hits = matches.iter().filter(|m| m.names.contains(&id)).count();
        let content: f64 = matches
            .iter()
            .map(|m| m.content.get(&id).map(|(r, _)| *r).unwrap_or(0.0))
            .sum();
        (name_hits, content)
    };
    rows.sort_by(|a, b| {
        let (an, ac) = score(a.id);
        let (bn, bc) = score(b.id);
        bn.cmp(&an)
            .then(ac.partial_cmp(&bc).unwrap_or(std::cmp::Ordering::Equal))
            .then(b.mtime.cmp(&a.mtime))
    });
    rows.truncate(MAX_RESULTS);

    // 강조할 글자: 검색어 그대로 + 나뉜 낱말
    let mut highlights: Vec<String> = words.clone();
    for w in &words {
        for t in tokenize::terms(w) {
            if t.chars().count() >= 1 && !highlights.contains(&t) {
                highlights.push(t);
            }
        }
    }
    highlights.sort_by_key(|h| std::cmp::Reverse(h.chars().count()));

    let mut chunk_stmt = conn
        .prepare_cached("SELECT text FROM chunks WHERE id=?1")
        .map_err(|e| e.to_string())?;
    let hits = rows
        .into_iter()
        .map(|row| {
            let best_chunk = matches
                .iter()
                .filter_map(|m| m.content.get(&row.id))
                .filter_map(|(rank, chunk)| chunk.map(|c| (*rank, c)))
                .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal))
                .map(|(_, c)| c);
            let snippet = best_chunk
                .and_then(|c| chunk_stmt.query_row(params![c], |r| r.get::<_, String>(0)).ok())
                .map(|text| make_snippet(&text, &highlights))
                .unwrap_or_default();
            let name_match = matches.iter().any(|m| m.names.contains(&row.id));
            let folder = std::path::Path::new(&row.path)
                .parent()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default();
            Hit {
                path: row.path,
                name: row.name,
                folder,
                ext: row.ext,
                size: row.size,
                mtime: row.mtime,
                status: row.status,
                snippet,
                name_match,
            }
        })
        .collect();
    Ok(SearchResult { hits, total, highlights })
}

/// 조각에서 찾은 글자 둘레만 잘라 한 줄로. 못 찾으면 앞부분.
pub fn make_snippet(text: &str, highlights: &[String]) -> String {
    let flat: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let chars: Vec<char> = flat.chars().collect();
    let lower: Vec<char> = flat.to_lowercase().chars().collect();
    let pos = if lower.len() == chars.len() {
        highlights
            .iter()
            .filter_map(|h| {
                let needle: Vec<char> = h.chars().collect();
                if needle.is_empty() || needle.len() > lower.len() {
                    return None;
                }
                (0..=lower.len() - needle.len()).find(|&i| lower[i..i + needle.len()] == needle[..])
            })
            .min()
    } else {
        None
    };
    let start = pos.map(|p| p.saturating_sub(30)).unwrap_or(0);
    let end = (start + 110).min(chars.len());
    let mut out: String = chars[start..end].iter().collect();
    if start > 0 {
        out.insert(0, '…');
    }
    if end < chars.len() {
        out.push('…');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::docsearch::{db, index};
    use crate::docsearch::extract::Extracted;

    fn add(conn: &mut Connection, path: &str, ext: &str, mtime: i64, text: &str) -> i64 {
        let name = path.rsplit('/').next().unwrap();
        conn.execute(
            "INSERT INTO files(path, folder_id, name, ext, size, mtime, status) VALUES(?1,1,?2,?3,10,?4,'pending')",
            params![path, name, ext, mtime],
        )
        .unwrap();
        let id = conn.last_insert_rowid();
        index::save_result(conn, id, Ok(Extracted::Text(text.to_string()))).unwrap();
        id
    }

    #[test]
    fn finds_by_content_name_and_fallback() {
        let dir = std::env::temp_dir().join(format!("dsearch-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("t.db");
        let _ = std::fs::remove_file(&path);
        let mut conn = db::open_at(&path).unwrap();
        add(&mut conn, "/d/2026 학교회계 지침.hwp", "hwp", 3, "학교예산을 편성하여 집행하는 절차를 안내합니다.");
        add(&mut conn, "/d/급식 계획.pdf", "pdf", 2, "학교급식 식재료는 HACCP 기준을 따른다.");
        add(&mut conn, "/d/교데통 회의.hwpx", "hwpx", 1, "교데통 수신그룹 등록 방법");
        let f = Filters::default();

        // 내용: 조사가 붙어 있어도("학교예산을") '예산'으로 찾힘
        let r = search(&conn, "예산", &f).unwrap();
        assert_eq!(r.hits.len(), 1);
        assert!(r.hits[0].snippet.contains("예산"), "{}", r.hits[0].snippet);

        // 두 낱말 모두: 이름(회계) + 내용(편성)
        let r = search(&conn, "회계 편성", &f).unwrap();
        assert_eq!(r.hits.len(), 1);
        assert!(r.hits[0].name_match);

        // 영문 대소문자
        assert_eq!(search(&conn, "haccp", &f).unwrap().hits.len(), 1);

        // 사전에 없는 줄임말
        let r = search(&conn, "교데통", &f).unwrap();
        assert_eq!(r.hits.len(), 1);

        // 종류 거르기
        let f2 = Filters { kinds: vec!["pdf".into()], ..Default::default() };
        assert_eq!(search(&conn, "학교", &f2).unwrap().hits.len(), 1);

        // 지운 파일은 결과에서 빠짐
        let id: i64 = conn.query_row("SELECT id FROM files WHERE ext='pdf'", [], |r| r.get(0)).unwrap();
        db::delete_file(&conn, id).unwrap();
        assert_eq!(search(&conn, "급식", &f).unwrap().hits.len(), 0);
        assert_eq!(search(&conn, "", &f).unwrap().hits.len(), 0);
        drop(conn);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn snippet_cuts_around_match() {
        let text = format!("{}학교예산 편성{}", "가".repeat(100), "나".repeat(100));
        let s = make_snippet(&text, &["예산".to_string()]);
        assert!(s.starts_with('…') && s.ends_with('…'));
        assert!(s.contains("학교예산"));
    }
}
