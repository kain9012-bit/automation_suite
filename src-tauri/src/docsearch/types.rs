//! 내용까지 찾을 문서 종류(1.4.5).
//!
//! 사용자가 고른 종류만 글을 꺼내 색인한다. 고르지 않은 종류도 파일 이름으로는 찾는다(상태 'name').
//! 쿼리 결과 엑셀처럼 글자가 많은 표 파일이 첫 색인을 몇 시간씩 끌고 색인을 크게 만드는 것을 막으려는 것이다.
//!
//! - 처음 고를 때 기본: 한글·PDF·워드·텍스트 켬, 엑셀·파워포인트 끔.
//! - 1.4.4 에서 이미 색인을 만든 PC(표시 없음)는 지금처럼 모든 종류를 읽는다. 끄고 싶은 사람만 직접 끈다.
//! - 종류를 바꾸면 다음 목록 대조(sync_list)가 상태를 맞춘다: 끈 종류는 글을 지우고 'name',
//!   켠 종류는 '읽을 차례'.

use super::db;
use rusqlite::Connection;
use std::collections::HashSet;

/// meta 에 저장하는 이름. 값은 "hwp,pdf,word" 처럼 쉼표로 이은 종류 id.
pub const META_KEY: &str = "content_types";

/// (id, 확장자들). 화면의 이름표는 src/lib/docsearch.ts 에 있다.
pub const TYPES: &[(&str, &[&str])] = &[
    ("hwp", &["hwp", "hwpx"]),
    ("pdf", &["pdf"]),
    ("word", &["docx"]),
    ("text", &["txt", "md"]),
    ("excel", &["xlsx", "csv"]),
    ("ppt", &["pptx"]),
];

/// 처음 검색 폴더를 고를 때 켜 두는 종류.
pub const DEFAULT_NEW: &[&str] = &["hwp", "pdf", "word", "text"];

pub fn type_of_ext(ext: &str) -> Option<&'static str> {
    TYPES.iter().find(|(_, exts)| exts.contains(&ext)).map(|(id, _)| *id)
}

/// 알려진 종류 id 만 남기고 순서를 TYPES 에 맞춘다.
pub fn normalize(ids: &[String]) -> Vec<String> {
    TYPES
        .iter()
        .map(|(id, _)| *id)
        .filter(|id| ids.iter().any(|x| x == id))
        .map(str::to_string)
        .collect()
}

/// 지금 켜진 종류. 표시가 없으면(1.4.4 에서 만든 색인) 모든 종류.
pub fn enabled(conn: &Connection) -> Vec<String> {
    match db::get_meta(conn, META_KEY) {
        Some(value) => {
            let ids: Vec<String> = value.split(',').map(|s| s.trim().to_string()).collect();
            normalize(&ids)
        }
        None => TYPES.iter().map(|(id, _)| id.to_string()).collect(),
    }
}

pub fn set(conn: &Connection, ids: &[String]) -> Result<(), String> {
    db::set_meta(conn, META_KEY, &normalize(ids).join(","))
}

/// 내용까지 읽을 확장자들.
pub fn enabled_exts(conn: &Connection) -> HashSet<String> {
    let on = enabled(conn);
    TYPES
        .iter()
        .filter(|(id, _)| on.iter().any(|x| x == id))
        .flat_map(|(_, exts)| exts.iter().map(|e| e.to_string()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_marker_means_all_types() {
        let dir = std::env::temp_dir().join(format!("ds-types-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let conn = db::open_at(&dir.join("i.db")).unwrap();
        assert_eq!(enabled(&conn).len(), TYPES.len(), "1.4.4 색인은 모든 종류");
        set(&conn, &["excel".into(), "hwp".into(), "모름".into()]).unwrap();
        assert_eq!(enabled(&conn), vec!["hwp".to_string(), "excel".to_string()]);
        let exts = enabled_exts(&conn);
        assert!(exts.contains("hwpx") && exts.contains("csv") && !exts.contains("pdf"));
        set(&conn, &[]).unwrap();
        assert!(enabled(&conn).is_empty(), "빈 값은 '아무것도 안 읽음'");
        drop(conn);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn every_content_extension_has_a_type() {
        for ext in ["hwp", "hwpx", "pdf", "docx", "txt", "md", "xlsx", "csv", "pptx"] {
            assert!(super::super::extract::content_kind(ext).is_some(), "{ext}");
            assert!(type_of_ext(ext).is_some(), "{ext}");
        }
    }
}
