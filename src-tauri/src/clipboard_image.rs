//! HTML 도구가 만든 그림(PNG)을 윈도우 클립보드에 넣는다(지역별 수치·학교 위치 지도 시각화의 [지도 복사], 1.5.1).
//!
//! 브라우저(WebView2)의 `navigator.clipboard.write` 로 투명 PNG 를 복사하면 투명한 곳의 색 값이 검정(0,0,0)으로
//! 들어가, 투명을 모르는 프로그램(한글)에 붙이면 바탕이 검게 나온다. 그래서 앱이 직접 두 가지 형식으로 넣는다.
//! - "PNG"      : 받은 PNG 그대로. 투명을 아는 프로그램이 쓴다.
//! - CF_DIBV5   : 32비트 BGRA 그림(알파 포함). 투명한 곳(알파 0)의 색은 흰색으로 채워,
//!                알파를 무시하는 프로그램이나 윈도우가 만들어 주는 CF_DIB 에서는 흰 바탕으로 보이게 한다.
//! 다른 도구는 이 기능을 쓰지 않는다(도구가 직접 부를 때만 동작).

/// BITMAPV5HEADER 크기(바이트)
const V5_HEADER: usize = 124;

/// PNG 를 CF_DIBV5 내용(BITMAPV5HEADER + 아래에서 위로 쌓은 BGRA 줄)으로 바꾼다.
pub fn png_to_dibv5(png_bytes: &[u8]) -> Result<Vec<u8>, String> {
    let (width, height, rgba) = decode_rgba(png_bytes)?;
    let (w, h) = (width as usize, height as usize);
    let mut out = Vec::with_capacity(V5_HEADER + w * h * 4);
    let push32 = |out: &mut Vec<u8>, v: u32| out.extend_from_slice(&v.to_le_bytes());
    push32(&mut out, V5_HEADER as u32); // bV5Size
    push32(&mut out, width); // bV5Width
    push32(&mut out, height); // bV5Height (양수 = 아래 줄부터)
    out.extend_from_slice(&1u16.to_le_bytes()); // bV5Planes
    out.extend_from_slice(&32u16.to_le_bytes()); // bV5BitCount
    push32(&mut out, 3); // bV5Compression = BI_BITFIELDS
    push32(&mut out, (w * h * 4) as u32); // bV5SizeImage
    push32(&mut out, 0); // bV5XPelsPerMeter
    push32(&mut out, 0); // bV5YPelsPerMeter
    push32(&mut out, 0); // bV5ClrUsed
    push32(&mut out, 0); // bV5ClrImportant
    push32(&mut out, 0x00FF_0000); // bV5RedMask
    push32(&mut out, 0x0000_FF00); // bV5GreenMask
    push32(&mut out, 0x0000_00FF); // bV5BlueMask
    push32(&mut out, 0xFF00_0000); // bV5AlphaMask
    push32(&mut out, 0x7352_4742); // bV5CSType = LCS_sRGB('sRGB')
    out.extend_from_slice(&[0u8; 36]); // bV5Endpoints
    push32(&mut out, 0); // bV5GammaRed
    push32(&mut out, 0); // bV5GammaGreen
    push32(&mut out, 0); // bV5GammaBlue
    push32(&mut out, 4); // bV5Intent = LCS_GM_IMAGES
    push32(&mut out, 0); // bV5ProfileData
    push32(&mut out, 0); // bV5ProfileSize
    push32(&mut out, 0); // bV5Reserved
    debug_assert_eq!(out.len(), V5_HEADER);
    for y in (0..h).rev() {
        for x in 0..w {
            let i = (y * w + x) * 4;
            let (r, g, b, a) = (rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]);
            if a == 0 {
                out.extend_from_slice(&[255, 255, 255, 0]);
            } else {
                out.extend_from_slice(&[b, g, r, a]);
            }
        }
    }
    Ok(out)
}

/// PNG 를 8비트 RGBA 로 푼다(흑백·팔레트·16비트도 받는다).
fn decode_rgba(png_bytes: &[u8]) -> Result<(u32, u32, Vec<u8>), String> {
    let bad = |e: &dyn std::fmt::Display| format!("그림을 읽지 못했습니다: {e}");
    let mut decoder = png::Decoder::new(std::io::Cursor::new(png_bytes));
    decoder.set_transformations(png::Transformations::normalize_to_color8());
    let mut reader = decoder.read_info().map_err(|e| bad(&e))?;
    let size = reader
        .output_buffer_size()
        .ok_or_else(|| "그림이 너무 큽니다.".to_string())?;
    let mut buf = vec![0u8; size];
    let info = reader.next_frame(&mut buf).map_err(|e| bad(&e))?;
    let (w, h) = (info.width, info.height);
    let pixels = (w as usize) * (h as usize);
    let src = &buf[..info.buffer_size()];
    let rgba = match info.color_type {
        png::ColorType::Rgba => src.to_vec(),
        png::ColorType::Rgb => src.chunks_exact(3).flat_map(|p| [p[0], p[1], p[2], 255]).collect(),
        png::ColorType::GrayscaleAlpha => src.chunks_exact(2).flat_map(|p| [p[0], p[0], p[0], p[1]]).collect(),
        png::ColorType::Grayscale => src.iter().flat_map(|&v| [v, v, v, 255]).collect(),
        png::ColorType::Indexed => return Err("그림 형식을 바꾸지 못했습니다.".to_string()),
    };
    if rgba.len() != pixels * 4 {
        return Err("그림 크기가 맞지 않습니다.".to_string());
    }
    Ok((w, h, rgba))
}

/// 클립보드를 비우고 "PNG" 와 CF_DIBV5 를 넣는다.
#[cfg(windows)]
pub fn write_png_to_clipboard(png_bytes: &[u8]) -> Result<(), String> {
    use windows_sys::Win32::System::DataExchange::{
        CloseClipboard, EmptyClipboard, OpenClipboard, RegisterClipboardFormatW, SetClipboardData,
    };
    use windows_sys::Win32::Foundation::GlobalFree;
    use windows_sys::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE};

    const CF_DIBV5: u32 = 17;
    let dib = png_to_dibv5(png_bytes)?;
    let png_name: Vec<u16> = "PNG".encode_utf16().chain(std::iter::once(0)).collect();

    // 다른 프로그램이 클립보드를 잠깐 쥐고 있을 수 있어 몇 번 다시 해 본다.
    let mut opened = false;
    for _ in 0..10 {
        if unsafe { OpenClipboard(std::ptr::null_mut()) } != 0 {
            opened = true;
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(30));
    }
    if !opened {
        return Err("다른 프로그램이 클립보드를 쓰고 있습니다. 잠시 뒤 다시 누르세요.".to_string());
    }
    let put = |format: u32, data: &[u8]| -> bool {
        unsafe {
            let mem = GlobalAlloc(GMEM_MOVEABLE, data.len());
            if mem.is_null() {
                return false;
            }
            let ptr = GlobalLock(mem) as *mut u8;
            if ptr.is_null() {
                GlobalFree(mem);
                return false;
            }
            std::ptr::copy_nonoverlapping(data.as_ptr(), ptr, data.len());
            GlobalUnlock(mem);
            if SetClipboardData(format, mem as _).is_null() {
                GlobalFree(mem);
                return false;
            }
            true // 성공하면 그 메모리는 클립보드 것이 된다(놓지 않는다)
        }
    };
    let result = unsafe {
        if EmptyClipboard() == 0 {
            Err("클립보드를 비우지 못했습니다.".to_string())
        } else {
            let png_format = RegisterClipboardFormatW(png_name.as_ptr());
            let png_ok = png_format != 0 && put(png_format, png_bytes);
            let dib_ok = put(CF_DIBV5, &dib);
            if png_ok || dib_ok {
                Ok(())
            } else {
                Err("클립보드에 그림을 넣지 못했습니다.".to_string())
            }
        }
    };
    unsafe { CloseClipboard() };
    result
}

#[cfg(not(windows))]
pub fn write_png_to_clipboard(_png_bytes: &[u8]) -> Result<(), String> {
    Err("그림 복사는 Windows 에서만 됩니다.".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png_of(w: u32, h: u32, rgba: &[u8]) -> Vec<u8> {
        let mut out = Vec::new();
        {
            let mut enc = png::Encoder::new(&mut out, w, h);
            enc.set_color(png::ColorType::Rgba);
            enc.set_depth(png::BitDepth::Eight);
            let mut writer = enc.write_header().unwrap();
            writer.write_image_data(rgba).unwrap();
        }
        out
    }

    #[test]
    fn transparent_pixels_become_white_and_rows_go_bottom_up() {
        // 2×2: 윗줄 [투명, 빨강], 아랫줄 [파랑 반투명, 초록]
        let png = png_of(2, 2, &[0, 0, 0, 0, 255, 0, 0, 255, 0, 0, 255, 128, 0, 255, 0, 255]);
        let dib = png_to_dibv5(&png).unwrap();
        assert_eq!(dib.len(), V5_HEADER + 16);
        assert_eq!(u32::from_le_bytes(dib[0..4].try_into().unwrap()), 124);
        assert_eq!(u32::from_le_bytes(dib[16..20].try_into().unwrap()), 3); // BI_BITFIELDS
        let px = &dib[V5_HEADER..];
        // 첫 줄 = 그림의 아랫줄(BGRA)
        assert_eq!(&px[0..4], &[255, 0, 0, 128]); // 파랑 반투명
        assert_eq!(&px[4..8], &[0, 255, 0, 255]); // 초록
        // 둘째 줄 = 그림의 윗줄
        assert_eq!(&px[8..12], &[255, 255, 255, 0]); // 투명 → 흰색, 알파 0
        assert_eq!(&px[12..16], &[0, 0, 255, 255]); // 빨강
    }

    #[test]
    fn broken_png_is_an_error() {
        assert!(png_to_dibv5(b"not a png").is_err());
    }
}
