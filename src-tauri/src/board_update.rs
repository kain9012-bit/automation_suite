//! 데이터도구실 게시글을 읽어 새 버전을 확인하고 설치까지 진행한다.
//!
//! 게시판 첨부는 파일을 다시 올릴 때마다 주소가 바뀌어 고정 주소가 없다.
//! 그래서 Tauri 업데이터처럼 고정 주소의 JSON을 받는 방식을 쓸 수 없고,
//! 주소가 바뀌지 않는 게시글 본문에서 표식을 읽는다.
//!
//! 표식에는 이 앱의 **배포 게시글 주소**를 적는다. 앱은 그 글을 열어 첨부
//! 목록에서 설치본 ZIP을 찾는다. 게시글 주소는 바뀌지 않으므로 한 번 적어 두면
//! 되고, 파일을 다시 올려 첨부 주소가 바뀌어도 손댈 것이 없다.
//!
//! 게시판이 exe 첨부를 받지 않으므로 설치본은 ZIP으로 올린다. ZIP은 운반
//! 수단일 뿐이고, **서명은 압축을 푼 exe에 대해 확인한다.** 그래서 배포
//! 워크플로가 만드는 `.sig` 파일을 그대로 쓸 수 있다.
//!
//! 자세한 배경은 docs/board-update.md.

use base64::{engine::general_purpose::STANDARD, Engine as _};
use minisign_verify::{PublicKey, Signature};
use semver::Version;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    io::{Cursor, Read},
    path::PathBuf,
    process::Command,
    time::Duration,
};
use tauri::{AppHandle, Manager};
use zip::ZipArchive;

/// 게시글 본문에서 이 말로 시작하는 조각을 찾는다.
const MARKER: &str = "[업데이트정보]";

/// 압축을 풀었을 때 이 크기를 넘으면 받지 않는다. 설치본은 100MB 아래다.
const MAX_INSTALLER_BYTES: u64 = 300 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize)]
struct BoardConfigFile {
    app: BoardConfig,
}

#[derive(Clone, Debug, Deserialize)]
struct BoardConfig {
    #[serde(default)]
    enabled: bool,
    /// 게시글에서 이 번호가 붙은 표식만 본다.
    #[serde(default)]
    app_id: String,
    /// 버전 정보 게시글 주소. 첨부와 달리 이 주소는 바뀌지 않는다.
    #[serde(default)]
    post_url: String,
    /// 설치본 서명을 확인할 공개키. GitHub 배포에 쓰는 것과 같은 키다.
    #[serde(default)]
    public_key: String,
}

/// 게시글에서 읽어 온 새 버전 정보.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BoardUpdate {
    version: String,
    download: String,
    signature: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct BoardUpdateCheck {
    /// 게시글 주소와 공개키가 채워져 있는지.
    configured: bool,
    current: String,
    update: Option<BoardUpdate>,
    message: String,
}

fn read_config(app: &AppHandle) -> Result<BoardConfig, String> {
    let raw = fs::read_to_string(crate::updates::config_path(app)?)
        .map_err(|error| format!("업데이트 설정을 읽지 못했습니다: {error}"))?;
    let parsed: BoardConfigFile =
        serde_json::from_str(&raw).map_err(|error| format!("업데이트 설정 형식 오류: {error}"))?;
    Ok(parsed.app)
}

// ── 게시글 읽기 ──────────────────────────────────────────────────────

/// 게시판 편집기가 넣는 문자 참조를 되돌린다. 첨부 주소의 &amp; 때문에 꼭 필요하다.
fn unescape(text: &str) -> String {
    text.replace("&amp;", "&")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
}

/// 게시글 HTML에서 표식 뒤쪽 글자를 모은다.
///
/// 게시판 편집기는 줄 중간에 <span> 같은 서식 태그를 아무렇지 않게 끼워 넣는다.
/// 태그를 만났다고 멈추면 표식이 잘려 읽히므로, 글자를 안 담는 태그는 건너뛰고
/// 줄을 끝내는 태그(br, p, div, td 등)와 줄바꿈에서만 멈춘다.
fn marker_segments(html: &str) -> Vec<String> {
    /// 줄이 여기서 끝난다고 볼 태그 이름.
    fn ends_line(tag: &str) -> bool {
        let name: String = tag
            .trim_start_matches('<')
            .trim_start_matches('/')
            .chars()
            .take_while(|c| c.is_ascii_alphanumeric())
            .collect();
        matches!(
            name.as_str(),
            "br" | "p" | "div" | "td" | "tr" | "li" | "table" | "body" | "h1" | "h2" | "h3"
        )
    }

    let mut found = Vec::new();
    let mut rest = html;
    while let Some(at) = rest.find(MARKER) {
        let mut cursor = &rest[at + MARKER.len()..];
        let mut text = String::new();

        loop {
            let Some(stop) = cursor.find(|c: char| c == '<' || c == '\r' || c == '\n') else {
                text.push_str(cursor);
                cursor = "";
                break;
            };
            text.push_str(&cursor[..stop]);
            let tail = &cursor[stop..];
            if !tail.starts_with('<') {
                cursor = tail;
                break;
            }
            let Some(close) = tail.find('>') else {
                cursor = "";
                break;
            };
            let is_end = ends_line(&tail[..close].to_ascii_lowercase());
            cursor = &tail[close + 1..];
            if is_end {
                break;
            }
        }

        found.push(text);
        rest = cursor;
    }
    found
}

/// `id=..|버전=..|서명=..` 를 표로 만든다. 순서가 달라도 상관없다.
fn parse_fields(segment: &str) -> HashMap<String, String> {
    let mut fields = HashMap::new();
    for part in unescape(segment).split('|') {
        if let Some((key, value)) = part.split_once('=') {
            fields.insert(key.trim().to_string(), value.trim().to_string());
        }
    }
    fields
}

/// 게시글의 첨부 링크를 (주소, 파일 이름)으로 모은다.
///
/// 첨부는 `<a href="/board/download.jbe?..." title="이름.zip" class="ico_file">` 모양이다.
/// 주소만 보고 고르면 본문에 넣은 다른 링크까지 걸리므로 download.jbe 를 함께 본다.
fn attachment_links(html: &str) -> Vec<(String, String)> {
    let mut links = Vec::new();
    let mut rest = html;
    while let Some(at) = rest.find("href=\"") {
        let after = &rest[at + 6..];
        let Some(quote) = after.find('"') else { break };
        let href = &after[..quote];
        let tail = &after[quote..];

        if href.contains("download.jbe") {
            // 같은 태그 안에 있는 title 속성이 파일 이름이다.
            let tag = &tail[..tail.find('>').unwrap_or(0)];
            let name = tag
                .find("title=\"")
                .and_then(|at| {
                    let value = &tag[at + 7..];
                    value.find('"').map(|end| value[..end].to_string())
                })
                .unwrap_or_default();
            links.push((unescape(href), unescape(&name)));
        }
        rest = tail;
    }
    links
}

/// 게시글 주소를 기준으로 상대 주소를 절대 주소로 만든다.
fn absolute(href: &str, post_url: &str) -> String {
    if href.starts_with("http://") || href.starts_with("https://") {
        return href.to_string();
    }
    let origin = post_url
        .split_once("://")
        .map(|(scheme, rest)| {
            let host = rest.split('/').next().unwrap_or(rest);
            format!("{scheme}://{host}")
        })
        .unwrap_or_default();
    if href.starts_with('/') {
        format!("{origin}{href}")
    } else {
        format!("{origin}/{href}")
    }
}

/// 첨부 중에서 설치본 ZIP 하나를 고른다.
///
/// `hint`(표식의 `파일=`)가 있으면 이름에 그 말이 든 것만 본다. 이 글은 다른 앱과
/// 함께 쓰므로, 나중에 첨부가 늘어나도 엉뚱한 것을 받지 않게 하는 장치다.
fn pick_attachment(html: &str, post_url: &str, hint: &str) -> Result<String, String> {
    let zips: Vec<(String, String)> = attachment_links(html)
        .into_iter()
        .filter(|(_, name)| name.to_lowercase().ends_with(".zip"))
        .filter(|(_, name)| hint.is_empty() || name.contains(hint))
        .collect();

    match zips.len() {
        0 if hint.is_empty() => Err("게시글에 첨부된 ZIP 파일이 없습니다.".to_string()),
        0 => Err(format!("이름에 '{hint}'이(가) 든 첨부를 찾지 못했습니다.")),
        1 => Ok(absolute(&zips[0].0, post_url)),
        _ => {
            let names: Vec<&str> = zips.iter().map(|(_, name)| name.as_str()).collect();
            Err(format!(
                "첨부된 ZIP이 여러 개입니다. 표식에 파일=<이름 일부>를 넣어 하나를 고르세요: {}",
                names.join(", ")
            ))
        }
    }
}

fn parsed_version(value: &str) -> Option<Version> {
    Version::parse(value.trim().trim_start_matches(|c| c == 'v' || c == 'V')).ok()
}

fn fetch_post(url: &str) -> Result<String, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(15))
        // 관공서 사이트가 브라우저가 아닌 요청을 거르는 경우가 있다.
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) JBEduON")
        .build()
        .map_err(|error| format!("연결을 준비하지 못했습니다: {error}"))?;
    let response = client
        .get(url)
        .send()
        .map_err(|error| format!("게시글을 열지 못했습니다: {error}"))?;
    if !response.status().is_success() {
        return Err(format!("게시글을 열지 못했습니다: {}", response.status()));
    }
    response
        .text()
        .map_err(|error| format!("게시글을 읽지 못했습니다: {error}"))
}

/// 게시글에서 우리 표식을 찾아 새 버전인지 본다.
#[tauri::command]
pub fn check_board_update(app: AppHandle) -> Result<BoardUpdateCheck, String> {
    let current = app.package_info().version.to_string();
    let config = read_config(&app)?;

    if !config.enabled || config.post_url.trim().is_empty() || config.app_id.trim().is_empty() {
        return Ok(BoardUpdateCheck {
            configured: false,
            current,
            update: None,
            message: "게시판 업데이트 확인이 설정되어 있지 않습니다.".to_string(),
        });
    }

    let post_url = config.post_url.trim();
    let html = fetch_post(post_url)?;
    let target = config.app_id.trim();

    // 우리 번호가 붙은 표식만 모은다. 예전에 넣어 둔 미완성 줄이 남아 있을 수 있어
    // 버전과 서명이 다 있는 것을 먼저 본다.
    let mine: Vec<HashMap<String, String>> = marker_segments(&html)
        .iter()
        .map(|segment| parse_fields(segment))
        .filter(|fields| fields.get("id").map(String::as_str) == Some(target))
        .collect();

    let has_version = |fields: &HashMap<String, String>| {
        fields.contains_key("버전") || fields.contains_key("version")
    };
    let has_signature = |fields: &HashMap<String, String>| {
        fields.contains_key("서명") || fields.contains_key("signature")
    };

    let chosen = mine
        .iter()
        .find(|fields| has_version(fields) && has_signature(fields))
        .or_else(|| mine.first());

    let Some(fields) = chosen else {
        return Ok(BoardUpdateCheck {
            configured: true,
            current,
            update: None,
            message: format!("게시글에서 {target} 표식을 찾지 못했습니다."),
        });
    };

    let (Some(version), Some(signature)) = (
        fields.get("버전").or_else(|| fields.get("version")),
        fields.get("서명").or_else(|| fields.get("signature")),
    ) else {
        // 아직 준비 중인 표식일 뿐이다. 사용자에게 실패라고 알릴 일이 아니다.
        return Ok(BoardUpdateCheck {
            configured: true,
            current,
            update: None,
            message: format!(
                "게시글의 {target} 표식에 버전·서명이 아직 없습니다. (표식 {}개 확인)",
                mine.len()
            ),
        });
    };

    let (Some(latest), Some(installed)) = (parsed_version(version), parsed_version(&current))
    else {
        return Ok(BoardUpdateCheck {
            configured: true,
            current,
            update: None,
            message: format!("게시글의 버전 형식을 읽지 못했습니다: {version}"),
        });
    };

    if latest <= installed {
        return Ok(BoardUpdateCheck {
            configured: true,
            current,
            update: None,
            message: "최신 버전을 사용 중입니다.".to_string(),
        });
    }

    // 어디서 받을지. 표식에 적은 이 앱의 배포 게시글을 열어 첨부를 찾는다.
    let hint = fields.get("파일").map(String::as_str).unwrap_or("").trim();
    let listed = fields
        .get("게시글")
        .or_else(|| fields.get("주소"))
        .or_else(|| fields.get("다운로드"))
        .or_else(|| fields.get("post"))
        .or_else(|| fields.get("download"))
        .map(|value| value.trim())
        .filter(|value| !value.is_empty());

    let download = match listed {
        // 첨부 주소를 그대로 적었으면 그것을 쓴다. 다시 올리면 바뀌는 주소다.
        Some(url) if url.contains("download.jbe") => absolute(url, post_url),
        // 게시글 주소면 그 글을 열어 첨부를 찾는다. 이러면 주소가 바뀌어도 된다.
        Some(url) => {
            let page_url = absolute(url, post_url);
            let page = fetch_post(&page_url)?;
            pick_attachment(&page, &page_url, hint)?
        }
        // 주소를 안 적었으면 표식이 있는 이 글의 첨부를 본다.
        None => pick_attachment(&html, post_url, hint)?,
    };

    return Ok(BoardUpdateCheck {
        configured: true,
        current,
        update: Some(BoardUpdate {
            version: version.trim().to_string(),
            download,
            signature: signature.trim().to_string(),
        }),
        message: format!("새 버전 {}이 있습니다.", version.trim()),
    });
}


// ── 내려받기와 서명 확인 ─────────────────────────────────────────────

/// 공개키와 서명은 둘 다 minisign 원문을 base64로 한 번 더 감싼 것이다.
fn decode_wrapped(value: &str, what: &str) -> Result<String, String> {
    let bytes = STANDARD
        .decode(value.trim())
        .map_err(|_| format!("{what} 형식이 올바르지 않습니다."))?;
    String::from_utf8(bytes).map_err(|_| format!("{what} 형식이 올바르지 않습니다."))
}

fn verify_installer(bytes: &[u8], signature: &str, public_key: &str) -> Result<(), String> {
    let key_text = decode_wrapped(public_key, "공개키")?;
    let key_line = key_text
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .ok_or_else(|| "공개키가 비어 있습니다.".to_string())?;
    let key = PublicKey::from_base64(key_line.trim())
        .map_err(|error| format!("공개키를 읽지 못했습니다: {error}"))?;

    let signature_text = decode_wrapped(signature, "서명")?;
    let signature = Signature::decode(&signature_text)
        .map_err(|error| format!("서명을 읽지 못했습니다: {error}"))?;

    // 세 번째 인자는 서명 방식(미리 해시했는지)이다. 어느 쪽으로 서명됐든
    // 같은 키로 확인되므로 둘 다 시도하고, 둘 다 어긋날 때만 거부한다.
    if key.verify(bytes, &signature, false).is_ok() || key.verify(bytes, &signature, true).is_ok() {
        return Ok(());
    }
    Err("서명이 맞지 않습니다. 받은 파일을 설치하지 않습니다.".to_string())
}

/// ZIP에서 설치본 exe 하나를 꺼낸다. ZIP 안의 경로는 쓰지 않는다.
fn take_installer(bytes: &[u8]) -> Result<Vec<u8>, String> {
    let mut archive = ZipArchive::new(Cursor::new(bytes))
        .map_err(|error| format!("압축을 열지 못했습니다: {error}"))?;

    let mut found: Option<usize> = None;
    for index in 0..archive.len() {
        let file = archive
            .by_index(index)
            .map_err(|error| format!("압축 항목을 읽지 못했습니다: {error}"))?;
        if file.is_dir() {
            continue;
        }
        let is_exe = file
            .enclosed_name()
            .and_then(|path| path.extension().map(|ext| ext.eq_ignore_ascii_case("exe")))
            .unwrap_or(false);
        if !is_exe {
            continue;
        }
        if found.is_some() {
            return Err(
                "압축 안에 실행 파일이 여러 개입니다. 설치본 하나만 넣어 주세요.".to_string(),
            );
        }
        if file.size() > MAX_INSTALLER_BYTES {
            return Err("설치본이 너무 큽니다.".to_string());
        }
        found = Some(index);
    }

    let index = found.ok_or_else(|| "압축 안에 설치본(.exe)이 없습니다.".to_string())?;
    let mut file = archive
        .by_index(index)
        .map_err(|error| format!("압축 항목을 읽지 못했습니다: {error}"))?;
    let mut installer = Vec::with_capacity(file.size() as usize);
    file.read_to_end(&mut installer)
        .map_err(|error| format!("설치본을 꺼내지 못했습니다: {error}"))?;
    Ok(installer)
}

fn download_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_cache_dir()
        .map_err(|error| format!("임시 폴더를 찾지 못했습니다: {error}"))?
        .join("updates");
    fs::create_dir_all(&dir).map_err(|error| format!("임시 폴더를 만들지 못했습니다: {error}"))?;
    Ok(dir)
}

/// 설치본을 받아 서명을 확인하고 저장한다. 저장한 경로를 돌려준다.
/// 서명이 어긋나면 아무것도 남기지 않는다.
#[tauri::command]
pub fn download_board_update(app: AppHandle, update: BoardUpdate) -> Result<String, String> {
    let config = read_config(&app)?;
    if config.public_key.trim().is_empty() {
        return Err("공개키가 설정되어 있지 않아 설치본을 확인할 수 없습니다.".to_string());
    }

    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(600))
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) JBEduON")
        .build()
        .map_err(|error| format!("연결을 준비하지 못했습니다: {error}"))?;
    let mut response = client
        .get(update.download.trim())
        .send()
        .map_err(|error| format!("설치본을 받지 못했습니다: {error}"))?;
    if !response.status().is_success() {
        return Err(format!("설치본을 받지 못했습니다: {}", response.status()));
    }

    let mut archive = Vec::new();
    response
        .read_to_end(&mut archive)
        .map_err(|error| format!("설치본을 읽지 못했습니다: {error}"))?;

    let installer = take_installer(&archive)?;
    verify_installer(&installer, &update.signature, &config.public_key)?;

    let target = download_dir(&app)?.join(format!("JBEduON-{}-setup.exe", update.version.trim()));
    fs::write(&target, &installer)
        .map_err(|error| format!("설치본을 저장하지 못했습니다: {error}"))?;
    Ok(target.to_string_lossy().to_string())
}

/// 받아 둔 설치본을 실행하고 앱을 끝낸다.
///
/// `/UPDATE` 갱신 모드, `/P` 진행 막대만 표시, `/R` 설치 후 앱 다시 실행.
/// 빌드로 나온 installer.nsi에서 확인한 인자다.
#[tauri::command]
pub fn apply_board_update(app: AppHandle, path: String) -> Result<(), String> {
    let installer = PathBuf::from(path.trim());
    if !installer.is_file() {
        return Err("받아 둔 설치본을 찾지 못했습니다.".to_string());
    }
    // 우리가 받아 둔 곳 바깥의 파일은 실행하지 않는다.
    let dir = download_dir(&app)?;
    if installer.parent() != Some(dir.as_path()) {
        return Err("설치본 위치가 올바르지 않습니다.".to_string());
    }

    Command::new(&installer)
        .args(["/UPDATE", "/P", "/R"])
        .spawn()
        .map_err(|error| format!("설치를 시작하지 못했습니다: {error}"))?;

    app.exit(0);
    Ok(())
}
