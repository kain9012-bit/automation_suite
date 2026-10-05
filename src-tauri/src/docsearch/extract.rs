//! 문서에서 검색할 글자를 꺼낸다.
//!
//! 한글(hwp)은 한글 프로그램을 띄우지 않고 파일 안의 문단 글자(BodyText)를 직접 읽는다.
//! hwpx·docx·xlsx·pptx 는 압축을 풀어 본문 XML 의 글자를 읽는다.
//! PDF 는 여기서 읽지 않는다(파이썬 사이드카의 PyMuPDF 로 묶어서 읽는다, mod.rs).
//! 미리보기용이 아니라 검색용이라 서식·표 구조는 버리고 글자만 남긴다.

use std::fs::File;
use std::io::{Read, Seek};
use std::path::Path;

/// 내용을 읽는 파일 크기 상한(100MB). 넘으면 이름으로만 찾는다.
pub const MAX_CONTENT_BYTES: u64 = 100 * 1024 * 1024;
/// 압축 안의 파일 하나를 풀 때 상한. 압축 폭탄으로 메모리가 터지지 않게 한다.
const MAX_ZIP_ENTRY: u64 = 200 * 1024 * 1024;

pub enum Extracted {
    Text(String),
    /// 열 때 암호를 묻는 문서
    Encrypted,
    /// 한글 '배포용 문서'(본문이 암호화돼 있음)
    Distribution,
}

/// 내용을 읽는 확장자인지. 나머지 파일은 이름으로만 찾는다.
pub fn content_kind(ext: &str) -> Option<&'static str> {
    Some(match ext {
        "hwp" => "hwp",
        "hwpx" => "hwpx",
        "docx" => "docx",
        "xlsx" => "xlsx",
        "pptx" => "pptx",
        "txt" | "csv" | "md" => "text",
        "pdf" => "pdf",
        _ => return None,
    })
}

pub fn extract(path: &Path, kind: &str) -> Result<Extracted, String> {
    match kind {
        "hwp" => {
            // 확장자는 hwp 인데 속은 hwpx(압축)인 파일이 있다.
            if starts_with_zip(path) {
                hwpx_text(path)
            } else {
                hwp_text(path)
            }
        }
        // 확장자는 hwpx 인데 속은 hwp(5.0 바이너리)인 파일도 있다(예: 예전 한글 취합 결과).
        "hwpx" => {
            if starts_with_zip(path) {
                hwpx_text(path)
            } else {
                hwp_text(path)
            }
        }
        "docx" => ooxml_text(path, |name| name == "word/document.xml", "docx"),
        // 슬라이드와 발표자 메모
        "pptx" => ooxml_text(
            path,
            |name| {
                (name.starts_with("ppt/slides/slide") || name.starts_with("ppt/notesSlides/notesSlide"))
                    && name.ends_with(".xml")
            },
            "pptx",
        ),
        "xlsx" => ooxml_text(
            path,
            |name| {
                name == "xl/sharedStrings.xml"
                    || (name.starts_with("xl/worksheets/sheet") && name.ends_with(".xml"))
            },
            "xlsx",
        ),
        "text" => plain_text(path).map(Extracted::Text),
        _ => Err("지원하지 않는 형식".to_string()),
    }
}

fn starts_with_zip(path: &Path) -> bool {
    let mut head = [0u8; 2];
    File::open(path)
        .and_then(|mut f| f.read_exact(&mut head))
        .map(|_| &head == b"PK")
        .unwrap_or(false)
}

// ───────────────────────────────────────────── hwp (HWP 5.0 바이너리)

fn hwp_text(path: &Path) -> Result<Extracted, String> {
    let mut comp = cfb::open(path).map_err(|_| "한글 5.0 형식이 아님".to_string())?;
    let mut header = Vec::new();
    comp.open_stream("/FileHeader")
        .map_err(|_| "FileHeader 없음".to_string())?
        .read_to_end(&mut header)
        .map_err(|e| e.to_string())?;
    if header.len() < 40 || !header.starts_with(b"HWP Document File") {
        return Err("한글 문서 머리 정보가 이상함".to_string());
    }
    let flags = u32::from_le_bytes([header[36], header[37], header[38], header[39]]);
    let compressed = flags & 0x1 != 0;
    if flags & 0x2 != 0 {
        return Ok(Extracted::Encrypted);
    }
    if flags & 0x4 != 0 {
        return Ok(Extracted::Distribution);
    }

    // BodyText/Section0, Section1 … 을 번호 순서대로
    let mut sections: Vec<(u32, String)> = comp
        .walk_storage("/BodyText")
        .map_err(|_| "본문이 없음".to_string())?
        .filter(|entry| entry.is_stream())
        .filter_map(|entry| {
            let name = entry.name().to_string();
            name.strip_prefix("Section")
                .and_then(|n| n.parse::<u32>().ok())
                .map(|n| (n, entry.path().to_string_lossy().replace('\\', "/")))
        })
        .collect();
    sections.sort();

    let mut out = String::new();
    for (_, stream_path) in sections {
        let mut raw = Vec::new();
        comp.open_stream(&stream_path)
            .map_err(|e| e.to_string())?
            .read_to_end(&mut raw)
            .map_err(|e| e.to_string())?;
        let data = if compressed {
            let mut inflated = Vec::new();
            flate2::read::DeflateDecoder::new(&raw[..])
                .take(MAX_ZIP_ENTRY)
                .read_to_end(&mut inflated)
                .map_err(|_| "본문 압축을 풀지 못함".to_string())?;
            inflated
        } else {
            raw
        };
        hwp_records_text(&data, &mut out);
    }
    Ok(Extracted::Text(out))
}

/// 레코드를 훑어 문단 글자(HWPTAG_PARA_TEXT = 67)만 모은다. 표·글상자 안 문단도 같은 레코드라 함께 나온다.
fn hwp_records_text(data: &[u8], out: &mut String) {
    const PARA_TEXT: u32 = 67;
    let mut i = 0usize;
    while i + 4 <= data.len() {
        let header = u32::from_le_bytes([data[i], data[i + 1], data[i + 2], data[i + 3]]);
        i += 4;
        let tag = header & 0x3ff;
        let mut size = (header >> 20) as usize;
        if size == 0xfff {
            if i + 4 > data.len() {
                break;
            }
            size = u32::from_le_bytes([data[i], data[i + 1], data[i + 2], data[i + 3]]) as usize;
            i += 4;
        }
        let end = (i + size).min(data.len());
        if tag == PARA_TEXT {
            para_text(&data[i..end], out);
            out.push('\n');
        }
        i = end;
    }
}

/// 문단 글자(UTF-16LE). 0~31 은 제어 문자다. 한글 5.0 규격에 따라
/// 글자형(1칸)은 바꾸거나 버리고, 인라인·확장형(8칸)은 통째로 건너뛴다.
fn para_text(bytes: &[u8], out: &mut String) {
    let units: Vec<u16> = bytes
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]]))
        .collect();
    let mut j = 0usize;
    let mut buf: Vec<u16> = Vec::with_capacity(units.len());
    while j < units.len() {
        let c = units[j];
        if c < 32 {
            match c {
                // 인라인·확장 제어: 8칸(16바이트)
                1..=9 | 11 | 12 | 14..=23 => {
                    if c == 9 {
                        buf.push(b'\t' as u16);
                    }
                    j += 8;
                    continue;
                }
                10 | 13 => buf.push(b'\n' as u16),
                24 => buf.push(b'-' as u16),
                30 | 31 => buf.push(b' ' as u16),
                _ => {}
            }
            j += 1;
            continue;
        }
        buf.push(c);
        j += 1;
    }
    out.push_str(&String::from_utf16_lossy(&buf));
}

// ───────────────────────────────────────────── hwpx·docx·xlsx·pptx (압축 + XML)

fn open_zip(path: &Path) -> Result<zip::ZipArchive<File>, String> {
    let file = File::open(path).map_err(|e| e.to_string())?;
    zip::ZipArchive::new(file).map_err(|_| "압축 형식이 아님".to_string())
}

fn read_entry<R: Read + Seek>(zip: &mut zip::ZipArchive<R>, name: &str) -> Result<Vec<u8>, String> {
    let entry = zip.by_name(name).map_err(|e| e.to_string())?;
    if entry.size() > MAX_ZIP_ENTRY {
        return Err("압축 안의 파일이 너무 큼".to_string());
    }
    let mut buf = Vec::with_capacity(entry.size() as usize);
    entry
        .take(MAX_ZIP_ENTRY)
        .read_to_end(&mut buf)
        .map_err(|e| e.to_string())?;
    Ok(buf)
}

/// 이름 끝의 숫자 순서대로(section2 가 section10 앞에 오게)
fn numbered(names: &mut Vec<String>) {
    names.sort_by_key(|name| {
        let digits: String = name
            .rsplit('/')
            .next()
            .unwrap_or("")
            .chars()
            .filter(|c| c.is_ascii_digit())
            .collect();
        (digits.parse::<u64>().unwrap_or(0), name.clone())
    });
}

fn hwpx_text(path: &Path) -> Result<Extracted, String> {
    let mut zip = open_zip(path)?;
    // 암호를 건 hwpx 는 manifest 에 암호화 정보가 들어 있다.
    if let Ok(manifest) = read_entry(&mut zip, "META-INF/manifest.xml") {
        let text = String::from_utf8_lossy(&manifest);
        if text.contains("encryption-data") || text.contains("EncryptionData") {
            return Ok(Extracted::Encrypted);
        }
    }
    let mut names: Vec<String> = zip
        .file_names()
        .filter(|n| n.starts_with("Contents/section") && n.ends_with(".xml"))
        .map(str::to_string)
        .collect();
    numbered(&mut names);
    let mut out = String::new();
    for name in names {
        let xml = read_entry(&mut zip, &name)?;
        xml_text(&xml, &mut out);
    }
    Ok(Extracted::Text(out))
}

fn ooxml_text(
    path: &Path,
    wanted: impl Fn(&str) -> bool,
    kind: &str,
) -> Result<Extracted, String> {
    let mut zip = match open_zip(path) {
        Ok(zip) => zip,
        // 암호를 건 오피스 문서는 zip 이 아니라 OLE(암호화 패키지)다.
        Err(_) if cfb::open(path).is_ok() => return Ok(Extracted::Encrypted),
        Err(e) => return Err(e),
    };
    let mut names: Vec<String> = zip.file_names().filter(|n| wanted(n)).map(str::to_string).collect();
    numbered(&mut names);
    let mut out = String::new();
    for name in names {
        let xml = read_entry(&mut zip, &name)?;
        // 엑셀 시트의 칸 값(<v>): 숫자·수식 결과·글자(t="str")는 넣고, 공유 문자열 번호(t="s")는 뺀다.
        let cell_values = kind == "xlsx" && name.starts_with("xl/worksheets/");
        xml_text_with(&xml, &mut out, cell_values);
    }
    Ok(Extracted::Text(out))
}

fn xml_text(xml: &[u8], out: &mut String) {
    xml_text_with(xml, out, false);
}

/// 본문 XML 에서 글자만 모은다. 접두어(hp:, w:, a:)는 보지 않는다.
/// t: 글자 · p/si: 문단 끝(줄바꿈) · tab: 탭 · lineBreak/br: 줄바꿈
fn xml_text_with(xml: &[u8], out: &mut String, cell_values: bool) {
    use quick_xml::events::Event;
    let mut reader = quick_xml::Reader::from_reader(xml);
    let mut buf = Vec::new();
    let mut in_t = 0u32;
    let mut shared_cell = false;
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => match e.local_name().as_ref() {
                b"t" => in_t += 1,
                b"c" if cell_values => {
                    shared_cell = e
                        .attributes()
                        .flatten()
                        .any(|a| a.key.local_name().as_ref() == b"t" && a.value.as_ref() == b"s");
                }
                b"v" if cell_values && !shared_cell => in_t += 1,
                _ => {}
            },
            Ok(Event::End(e)) => match e.local_name().as_ref() {
                b"t" => in_t = in_t.saturating_sub(1),
                b"v" if cell_values && !shared_cell => in_t = in_t.saturating_sub(1),
                b"p" | b"si" | b"row" => out.push('\n'),
                b"c" => out.push('\t'),
                _ => {}
            },
            Ok(Event::Empty(e)) => match e.local_name().as_ref() {
                b"tab" => out.push('\t'),
                b"lineBreak" | b"br" => out.push('\n'),
                _ => {}
            },
            Ok(Event::Text(t)) if in_t > 0 => {
                // 0.38 부터 &amp; 같은 참조는 GeneralRef 로 따로 온다. 여기 글자는 그대로 쓴다.
                if let Ok(text) = t.decode() {
                    out.push_str(&text);
                }
            }
            Ok(Event::GeneralRef(r)) if in_t > 0 => {
                // &amp; &lt; 같은 문자 참조
                let name = String::from_utf8_lossy(r.as_ref()).into_owned();
                let ch = match name.as_str() {
                    "amp" => Some('&'),
                    "lt" => Some('<'),
                    "gt" => Some('>'),
                    "quot" => Some('"'),
                    "apos" => Some('\''),
                    _ => r.resolve_char_ref().ok().flatten(),
                };
                if let Some(ch) = ch {
                    out.push(ch);
                }
            }
            Ok(Event::CData(t)) if in_t > 0 => out.push_str(&String::from_utf8_lossy(&t)),
            Ok(Event::Eof) => break,
            Err(_) => break,
            _ => {}
        }
        buf.clear();
    }
}

// ───────────────────────────────────────────── txt·csv·md

fn plain_text(path: &Path) -> Result<String, String> {
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|e| e.to_string())?
        .take(MAX_CONTENT_BYTES)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    Ok(decode_text(&bytes))
}

/// BOM 이 있으면 그대로, 없으면 UTF-8 인지 보고 아니면 한국어 윈도 인코딩(CP949)으로 읽는다.
pub fn decode_text(bytes: &[u8]) -> String {
    if let Some((encoding, bom_len)) = encoding_rs::Encoding::for_bom(bytes) {
        return encoding.decode_without_bom_handling(&bytes[bom_len..]).0.into_owned();
    }
    match std::str::from_utf8(bytes) {
        Ok(text) => text.to_string(),
        Err(_) => encoding_rs::EUC_KR.decode_without_bom_handling(bytes).0.into_owned(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn le16(s: &str) -> Vec<u8> {
        s.encode_utf16().flat_map(|u| u.to_le_bytes()).collect()
    }

    #[test]
    fn para_text_skips_controls() {
        // "가" + 확장 제어(표, 8칸) + "나" + 탭(인라인 8칸) + "다" + 문단 끝
        let mut b = le16("가");
        b.extend([11u8, 0]);
        b.extend(std::iter::repeat(0u8).take(14));
        b.extend(le16("나"));
        b.extend([9u8, 0]);
        b.extend(std::iter::repeat(0u8).take(14));
        b.extend(le16("다"));
        b.extend([13u8, 0]);
        let mut out = String::new();
        para_text(&b, &mut out);
        assert_eq!(out, "가나\t다\n");
    }

    #[test]
    fn records_pick_para_text_only() {
        let mut data = Vec::new();
        let body = le16("예산 편성");
        let header = 67u32 | ((body.len() as u32) << 20);
        data.extend(header.to_le_bytes());
        data.extend(&body);
        let other = 66u32 | (4u32 << 20);
        data.extend(other.to_le_bytes());
        data.extend([1, 2, 3, 4]);
        let mut out = String::new();
        hwp_records_text(&data, &mut out);
        assert_eq!(out, "예산 편성\n");
    }

    #[test]
    fn xml_text_joins_runs_in_paragraph() {
        let xml = r#"<hs:sec xmlns:hp="x" xmlns:hs="y"><hp:p><hp:run><hp:t>비교측량</hp:t></hp:run><hp:run><hp:t>하여 A&amp;B</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>둘째<hp:tab/>칸</hp:t></hp:run></hp:p></hs:sec>"#;
        let mut out = String::new();
        xml_text(xml.as_bytes(), &mut out);
        assert_eq!(out, "비교측량하여 A&B\n둘째\t칸\n");
    }

    #[test]
    fn xlsx_cell_values_skip_shared_index() {
        let xml = r#"<x:worksheet xmlns:x="m"><x:sheetData><x:row><x:c r="A1" t="str"><x:v>성명</x:v></x:c><x:c r="B1" t="s"><x:v>7</x:v></x:c><x:c r="C1"><x:v>2026</x:v></x:c><x:c r="D1" t="inlineStr"><x:is><x:t>예산</x:t></x:is></x:c></x:row></x:sheetData></x:worksheet>"#;
        let mut out = String::new();
        xml_text_with(xml.as_bytes(), &mut out, true);
        assert!(out.contains("성명") && out.contains("2026") && out.contains("예산"), "{out:?}");
        assert!(!out.contains('7'), "{out:?}");
    }

    #[test]
    fn decodes_cp949_and_utf8() {
        let (cp, _, _) = encoding_rs::EUC_KR.encode("학교 예산");
        assert_eq!(decode_text(&cp), "학교 예산");
        assert_eq!(decode_text("학교".as_bytes()), "학교");
        let mut bom = vec![0xEF, 0xBB, 0xBF];
        bom.extend("예산".as_bytes());
        assert_eq!(decode_text(&bom), "예산");
    }
}
