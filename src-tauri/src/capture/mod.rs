//! 화면 캡처 도구(1.5.3, 간단 도구 `screen_capture`)의 화면 찍기와 '화면에 고정'.
//!
//! 도구(HTML)는 편집만 한다. 화면은 앱이 직접 찍는다(브라우저는 다른 프로그램 화면을 찍지 못한다).
//! - 영역: 그 순간의 화면을 멈춘 채로 덮고, 끌어서 고른 곳을 자른다. 끌지 않고 누르면 그 자리의 창(없으면 모니터).
//! - 전체 화면: 모니터 전체. 모니터가 둘 이상이면 찍을 모니터를 누르게 한다.
//! - 스크롤: 영역을 고른 뒤, 그 영역 위에서 휠을 한 칸씩 굴리며 찍어 한 장으로 잇는다(stitch.rs).
//! - 캡처 지연: 정한 초만큼 화면 위쪽에 남은 초를 보이고 기다렸다가 찍는다.
//! - 화면에 고정: 그림을 항상 맨 위에 떠 있는 작은 창으로 띄운다(끌어 옮김·휠로 크기·두 번 눌러 닫기·오른쪽 단추 메뉴).
//!
//! 창은 모두 Win32 로 직접 만든다(웹 화면을 새로 띄우지 않는다). 스레드마다 모니터별 배율(PMv2)을 켜서
//! 좌표가 실제 화면 점과 1:1 로 맞는다(배율이 다른 모니터를 함께 써도 고른 곳이 그대로 잘린다).
//! 다른 도구는 이 모듈을 쓰지 않는다.

#[cfg_attr(not(windows), allow(dead_code))]
mod stitch;
#[cfg(windows)]
mod win;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Region,
    Screen,
    Scroll,
}

impl Mode {
    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "region" => Ok(Mode::Region),
            "screen" => Ok(Mode::Screen),
            "scroll" => Ok(Mode::Scroll),
            other => Err(format!("알 수 없는 캡처 방식입니다: {other}")),
        }
    }
}

/// 지연은 0~10초만 받는다.
pub const MAX_DELAY_SECS: u32 = 10;

/// 화면을 찍어 PNG 로 돌려준다. 사용자가 취소하면 None.
/// 창을 띄우고 메시지를 돌려야 해서 따로 스레드를 만들어 그 안에서 한다(부른 스레드는 끝날 때까지 기다린다).
pub fn capture(mode: Mode, delay_secs: u32) -> Result<Option<Vec<u8>>, String> {
    #[cfg(windows)]
    {
        let delay = delay_secs.min(MAX_DELAY_SECS);
        std::thread::Builder::new()
            .name("screen-capture".into())
            .spawn(move || win::capture(mode, delay))
            .map_err(|e| format!("캡처를 시작하지 못했습니다: {e}"))?
            .join()
            .map_err(|_| "캡처 중 오류가 났습니다.".to_string())?
    }
    #[cfg(not(windows))]
    {
        let _ = (mode, delay_secs);
        Err("화면 캡처는 Windows 에서만 됩니다.".to_string())
    }
}

/// 그림(PNG)을 화면에 고정한다. 창을 띄우면 바로 돌아온다(창은 닫을 때까지 따로 돈다).
pub fn pin(png_bytes: Vec<u8>) -> Result<(), String> {
    #[cfg(windows)]
    {
        win::pin(png_bytes)
    }
    #[cfg(not(windows))]
    {
        let _ = png_bytes;
        Err("화면에 고정은 Windows 에서만 됩니다.".to_string())
    }
}

/// 위에서 아래로 쌓은 BGRA 를 PNG(RGB)로. 화면 캡처는 투명이 없어 RGB 로 줄인다.
pub(crate) fn encode_png(width: usize, height: usize, bgra: &[u8]) -> Result<Vec<u8>, String> {
    let mut rgb = Vec::with_capacity(width * height * 3);
    for px in bgra.chunks_exact(4) {
        rgb.extend_from_slice(&[px[2], px[1], px[0]]);
    }
    let mut out = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut out, width as u32, height as u32);
        encoder.set_color(png::ColorType::Rgb);
        encoder.set_depth(png::BitDepth::Eight);
        encoder.set_compression(png::Compression::Fast);
        let mut writer = encoder.write_header().map_err(|e| format!("그림을 만들지 못했습니다: {e}"))?;
        writer.write_image_data(&rgb).map_err(|e| format!("그림을 만들지 못했습니다: {e}"))?;
    }
    Ok(out)
}

/// PNG 를 BGRA 로 푼다. 반투명한 곳은 흰 바탕에 얹은 색으로 바꾼다(고정 창은 투명을 그리지 않는다).
#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn decode_png_bgra(png_bytes: &[u8]) -> Result<(usize, usize, Vec<u8>), String> {
    let bad = |e: &dyn std::fmt::Display| format!("그림을 읽지 못했습니다: {e}");
    let mut decoder = png::Decoder::new(std::io::Cursor::new(png_bytes));
    decoder.set_transformations(png::Transformations::normalize_to_color8());
    let mut reader = decoder.read_info().map_err(|e| bad(&e))?;
    let size = reader.output_buffer_size().ok_or_else(|| "그림이 너무 큽니다.".to_string())?;
    let mut buf = vec![0u8; size];
    let info = reader.next_frame(&mut buf).map_err(|e| bad(&e))?;
    let (w, h) = (info.width as usize, info.height as usize);
    let src = &buf[..info.buffer_size()];
    let over_white = |r: u8, g: u8, b: u8, a: u8| -> [u8; 4] {
        let mix = |c: u8| ((c as u32 * a as u32 + 255 * (255 - a as u32) + 127) / 255) as u8;
        [mix(b), mix(g), mix(r), 255]
    };
    let bgra: Vec<u8> = match info.color_type {
        png::ColorType::Rgba => src.chunks_exact(4).flat_map(|p| over_white(p[0], p[1], p[2], p[3])).collect(),
        png::ColorType::Rgb => src.chunks_exact(3).flat_map(|p| [p[2], p[1], p[0], 255]).collect(),
        png::ColorType::GrayscaleAlpha => src.chunks_exact(2).flat_map(|p| over_white(p[0], p[0], p[0], p[1])).collect(),
        png::ColorType::Grayscale => src.iter().flat_map(|&v| [v, v, v, 255]).collect(),
        png::ColorType::Indexed => return Err("그림 형식을 바꾸지 못했습니다.".to_string()),
    };
    if bgra.len() != w * h * 4 {
        return Err("그림 크기가 맞지 않습니다.".to_string());
    }
    Ok((w, h, bgra))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn png_round_trip() {
        let (w, h) = (3, 2);
        let bgra = vec![
            10, 20, 30, 255, 40, 50, 60, 255, 70, 80, 90, 255, //
            1, 2, 3, 255, 4, 5, 6, 255, 7, 8, 9, 255,
        ];
        let png = encode_png(w, h, &bgra).unwrap();
        let (dw, dh, back) = decode_png_bgra(&png).unwrap();
        assert_eq!((dw, dh), (w, h));
        assert_eq!(back, bgra);
    }

    #[test]
    fn modes() {
        assert_eq!(Mode::parse("scroll").unwrap(), Mode::Scroll);
        assert!(Mode::parse("x").is_err());
    }
}
