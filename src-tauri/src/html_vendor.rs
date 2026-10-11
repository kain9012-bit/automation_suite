//! HTML 도구가 인터넷(cdn.jsdelivr.net)에서 받아 쓰던 부품을 설치본에 넣어 둔 사본으로 바꿔 끼운다(1.4.6).
//!
//! 도구 HTML 파일은 고치지 않는다. 앱이 도구 화면을 열 때(read_tool_html)와 브라우저로 열 때
//! (open_tool_in_browser) 아래 표에 있는 주소의 <script src> 를 `tools/_vendor` 의 사본 내용으로
//! 바꾸고, Pretendard 글꼴 CSS <link> 는 사본 글꼴(가변 글꼴 한 파일)을 담은 <style> 로 바꾼다.
//! preconnect <link> 는 뺀다. 그래서 인터넷이 없거나 jsdelivr 가 막힌 PC에서도 도구가 같은 모습으로 동작한다.
//!
//! - 표에 없는 주소, 사본 파일이 없는 경우는 그대로 둔다(인터넷이 되면 예전처럼 받아 온다).
//! - 사본은 npm 에 올라온 그 버전의 배포 파일 그대로다. 주소의 버전과 파일 이름의 버전을 같게 둔다.
//! - 도구에 새 부품을 쓰면 여기 표와 `tools/_vendor`, THIRD_PARTY_NOTICES.txt 에 함께 더한다.
//!   (테스트 every_bundled_html_tool_works_offline 가 빠뜨린 것을 잡는다.)

use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager};

/// (도구가 쓰는 주소, `tools/_vendor` 안의 파일)
pub const SCRIPTS: &[(&str, &str)] = &[
    ("https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js", "xlsx-0.18.5.full.min.js"),
    ("https://cdn.jsdelivr.net/npm/exceljs@4.4.0/dist/exceljs.min.js", "exceljs-4.4.0.min.js"),
    ("https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js", "pdf-lib-1.17.1.min.js"),
    ("https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js", "jszip-3.10.1.min.js"),
    ("https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js", "chart-4.4.1.umd.js"),
    ("https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0", "chartjs-plugin-datalabels-2.2.0.min.js"),
];

/// Pretendard 글꼴 CSS. 사본 글꼴을 담은 <style> 로 바꾼다(사본이 없으면 빼서 윈도우 글꼴로 보인다).
const FONT_CSS: &str = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css";
/// 글꼴 사본(Pretendard 1.3.9 가변 글꼴, SIL OFL 1.1). 굵기 45~920 을 한 파일로 다룬다.
pub const FONT_FILE: &str = "PretendardVariable-1.3.9.woff2";

/// 빼는 <link>(미리 연결).
const DROP_LINKS: &[&str] = &["https://cdn.jsdelivr.net"];

/// 사본이 있는 폴더 후보. 도구를 찾는 곳(lib.rs tool_roots)의 기본 도구 폴더와 같다.
pub fn vendor_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        dirs.push(resource_dir.join("tools").join("_vendor"));
        dirs.push(resource_dir.join("_up_").join("tools").join("_vendor"));
    }
    if cfg!(debug_assertions) {
        dirs.push(dev_vendor_dir());
    }
    dirs
}

fn dev_vendor_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("tools")
        .join("_vendor")
}

fn read_from(dirs: &[PathBuf], file: &str) -> Option<String> {
    dirs.iter().find_map(|dir| std::fs::read_to_string(dir.join(file)).ok())
}

/// 글꼴 사본을 담은 @font-face. 도구 이름표의 'Pretendard' 로 쓰이게 이름을 맞춘다.
fn font_style(dirs: &[PathBuf]) -> Option<String> {
    use base64::Engine;
    let bytes = dirs.iter().find_map(|dir| std::fs::read(dir.join(FONT_FILE)).ok())?;
    let data = base64::engine::general_purpose::STANDARD.encode(bytes);
    Some(format!(
        "<style>/* Pretendard 1.3.9 (c) 2021 Kil Hyung-jin, SIL Open Font License 1.1 */\n\
         @font-face{{font-family:'Pretendard';font-weight:45 920;font-style:normal;font-display:swap;\
         src:url(data:font/woff2;base64,{data}) format('woff2');}}</style>"
    ))
}

/// 글꼴은 2MB 남짓이라 base64 로 바꾼 것을 한 번만 만들어 둔다.
static FONT_STYLE: std::sync::OnceLock<Option<String>> = std::sync::OnceLock::new();

/// 앱에 넣어 둔 사본으로 바꿔 끼운 HTML.
pub fn localize(app: &AppHandle, html: &str) -> String {
    let dirs = vendor_dirs(app);
    let font = FONT_STYLE.get_or_init(|| font_style(&dirs));
    localize_with(html, |file| read_from(&dirs, file), font.as_deref())
}

/// `read` 는 사본 파일 이름을 받아 내용을 돌려준다(없으면 None). `font` 는 글꼴 CSS 자리에 넣을 <style>.
pub fn localize_with(html: &str, read: impl Fn(&str) -> Option<String>, font: Option<&str>) -> String {
    let mut out = String::with_capacity(html.len());
    let mut rest = html;
    loop {
        let script = rest.find("<script");
        let link = rest.find("<link");
        let start = match (script, link) {
            (Some(a), Some(b)) => a.min(b),
            (Some(a), None) => a,
            (None, Some(b)) => b,
            (None, None) => break,
        };
        out.push_str(&rest[..start]);
        rest = &rest[start..];
        let Some(open_end) = rest.find('>') else { break };
        let open_tag = &rest[..=open_end];

        if open_tag.starts_with("<script") {
            // 외부 부품은 <script src="..."></script> 꼴로만 쓴다. 속에 내용이 있으면 손대지 않는다.
            let after = &rest[open_end + 1..];
            let close = "</script>";
            let replaced = attr(open_tag, "src")
                .and_then(|src| SCRIPTS.iter().find(|(url, _)| *url == src))
                .filter(|_| after.trim_start().starts_with(close))
                .and_then(|(_, file)| read(file));
            if let Some(code) = replaced {
                let gap = after.len() - after.trim_start().len();
                out.push_str("<script>");
                // 부품 코드 속의 "</script" 가 태그를 닫지 않게 한다(문자열·정규식 안에서는 같은 뜻).
                out.push_str(&code.replace("</script", "<\\/script"));
                out.push_str("</script>");
                rest = &after[gap + close.len()..];
                continue;
            }
        } else if let Some(href) = attr(open_tag, "href") {
            if href == FONT_CSS {
                out.push_str(font.unwrap_or(""));
                rest = &rest[open_end + 1..];
                continue;
            }
            if DROP_LINKS.contains(&href.as_str()) {
                rest = &rest[open_end + 1..];
                continue;
            }
        }
        out.push_str(open_tag);
        rest = &rest[open_end + 1..];
    }
    out.push_str(rest);
    out
}

/// 태그 안의 속성 값(따옴표 " 또는 '). 없으면 None.
fn attr(tag: &str, name: &str) -> Option<String> {
    let mut search = 0;
    while let Some(found) = tag[search..].find(name) {
        let at = search + found;
        search = at + name.len();
        // 다른 속성 이름의 일부(data-src 등)는 건너뛴다.
        let before = tag[..at].chars().last();
        if !matches!(before, Some(c) if c.is_whitespace()) {
            continue;
        }
        let after = tag[search..].trim_start();
        let Some(after) = after.strip_prefix('=') else { continue };
        let after = after.trim_start();
        let quote = after.chars().next()?;
        if quote != '"' && quote != '\'' {
            continue;
        }
        let body = &after[1..];
        let end = body.find(quote)?;
        return Some(body[..end].to_string());
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake(file: &str) -> Option<String> {
        match file {
            "xlsx-0.18.5.full.min.js" => Some("var XLSX={};/* </script> */".to_string()),
            "exceljs-4.4.0.min.js" => Some("var ExcelJS={};".to_string()),
            _ => None,
        }
    }

    #[test]
    fn swaps_known_scripts_and_drops_font_links() {
        let html = concat!(
            "<head><link rel=\"preconnect\" href=\"https://cdn.jsdelivr.net\" />",
            "<link href=\"https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css\" rel=\"stylesheet\"/>",
            "<link rel=\"stylesheet\" href=\"style.css\">",
            "<script src=\"https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js\"></script>\n",
            "<script src='https://cdn.jsdelivr.net/npm/exceljs@4.4.0/dist/exceljs.min.js'>  </script>",
            "<script src=\"https://example.com/other.js\"></script>",
            "<script data-src=\"https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js\">var a = '<b>';</script>",
            "</head>"
        );
        let out = localize_with(html, fake, Some("<style>/*FONT*/</style>"));
        assert!(!out.contains("pretendard.css"), "글꼴 CSS 주소를 뺌: {out}");
        assert!(out.contains("<head><style>/*FONT*/</style><link rel=\"stylesheet\""), "글꼴 자리에 사본 글꼴: {out}");
        assert!(!out.contains("preconnect"));
        assert!(out.contains("<link rel=\"stylesheet\" href=\"style.css\">"), "다른 link 는 그대로");
        assert!(out.contains("<script>var XLSX={};/* <\\/script> */</script>"), "{out}");
        assert!(out.contains("<script>var ExcelJS={};</script>"));
        assert!(out.contains("<script src=\"https://example.com/other.js\"></script>"), "표에 없는 주소는 그대로");
        assert!(out.contains("data-src=\"https://cdn.jsdelivr.net/npm/xlsx"), "src 가 아닌 속성은 그대로");
        assert!(out.contains("var a = '<b>';</script></head>"));
    }

    #[test]
    fn keeps_tag_when_copy_is_missing() {
        let html = "<script src=\"https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js\"></script>";
        assert_eq!(localize_with(html, |_| None, None), html);
        let font = "<link href=\"https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css\" rel=\"stylesheet\"/>x";
        assert_eq!(localize_with(font, |_| None, None), "x", "글꼴 사본이 없으면 링크만 뺌");
    }

    /// 설치본에 들어가는 모든 HTML 도구가 jsdelivr 없이 열리는지. 도구에 새 부품을 쓰고
    /// 표에 더하지 않으면 여기서 걸린다.
    #[test]
    fn every_bundled_html_tool_works_offline() {
        let dir = dev_vendor_dir();
        for (_, file) in SCRIPTS {
            assert!(dir.join(file).is_file(), "사본이 없습니다: {file}");
        }
        let font = font_style(&[dir.clone()]).expect("글꼴 사본");
        assert!(font.len() > 2_000_000 && font.contains("font-family:'Pretendard'"));
        let tools = dir.parent().unwrap();
        let mut checked = 0;
        for entry in std::fs::read_dir(tools).unwrap().flatten() {
            let web = entry.path().join("web");
            let Ok(files) = std::fs::read_dir(&web) else { continue };
            for file in files.flatten() {
                let path = file.path();
                if path.extension().and_then(|e| e.to_str()) != Some("html") {
                    continue;
                }
                let html = std::fs::read_to_string(&path).unwrap();
                let out = localize_with(&html, |f| read_from(&[dir.clone()], f), Some(&font));
                assert!(!out.contains("cdn.jsdelivr.net"), "인터넷에서 받는 부품이 남음: {}", path.display());
                checked += 1;
            }
        }
        assert!(checked >= 19, "HTML 도구를 {checked}개만 찾음");
    }
}
