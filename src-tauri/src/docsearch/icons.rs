//! 결과 목록의 파일 아이콘: 그 PC의 윈도우 탐색기가 쓰는 아이콘을 확장자별로 받아 쓴다.
//!
//! 아이콘 그림(한컴·마이크로소프트 등)을 프로그램에 넣어 나눠 주지 않으려고, 실행 중에
//! 윈도우에게 물어본다. 파일을 열지 않고 확장자만으로 묻는다(SHGFI_USEFILEATTRIBUTES).
//! 한 번 받은 아이콘은 프로그램이 켜져 있는 동안 기억한다.
//! 윈도우가 아니거나 받지 못하면 빈 값을 돌려주고, 화면은 원래 아이콘을 쓴다.

use std::collections::HashMap;
use std::sync::Mutex;

static CACHE: Mutex<Option<HashMap<String, Option<String>>>> = Mutex::new(None);

/// 확장자로 쓸 수 있는 값만(영문·숫자 1~16자). 소문자로 맞춘다.
fn clean_ext(ext: &str) -> Option<String> {
    let ext = ext.trim().trim_start_matches('.').to_ascii_lowercase();
    (!ext.is_empty() && ext.len() <= 16 && ext.chars().all(|c| c.is_ascii_alphanumeric())).then_some(ext)
}

/// 확장자 → PNG data URL. 받지 못한 확장자는 빠진다.
pub fn file_icons(exts: &[String]) -> HashMap<String, String> {
    let wanted: Vec<String> = {
        let mut list: Vec<String> = exts.iter().filter_map(|e| clean_ext(e)).collect();
        list.sort();
        list.dedup();
        list
    };
    let mut out = HashMap::new();
    let mut missing = Vec::new();
    if let Ok(cache) = CACHE.lock() {
        for ext in &wanted {
            match cache.as_ref().and_then(|c| c.get(ext)) {
                Some(Some(url)) => {
                    out.insert(ext.clone(), url.clone());
                }
                Some(None) => {}
                None => missing.push(ext.clone()),
            }
        }
    }
    if missing.is_empty() {
        return out;
    }
    let fetched = system::icons(&missing);
    if let Ok(mut cache) = CACHE.lock() {
        let cache = cache.get_or_insert_with(HashMap::new);
        for (ext, url) in missing.into_iter().zip(fetched) {
            if let Some(url) = &url {
                out.insert(ext.clone(), url.clone());
            }
            cache.insert(ext, url);
        }
    }
    out
}

/// BGRA(위에서 아래로) → PNG data URL. 알파가 모두 0인 옛 아이콘은 `mask_bgra`(검정=보임)로 알파를 만든다.
#[cfg_attr(not(windows), allow(dead_code))]
fn to_png_data_url(width: u32, height: u32, bgra: &[u8], mask_bgra: Option<&[u8]>) -> Option<String> {
    use base64::Engine;
    let pixels = (width * height) as usize;
    if width == 0 || height == 0 || bgra.len() < pixels * 4 {
        return None;
    }
    let has_alpha = bgra.chunks_exact(4).take(pixels).any(|p| p[3] != 0);
    let mut rgba = Vec::with_capacity(pixels * 4);
    for i in 0..pixels {
        let p = &bgra[i * 4..i * 4 + 4];
        let alpha = if has_alpha {
            p[3]
        } else {
            match mask_bgra {
                Some(mask) if mask.len() >= pixels * 4 => {
                    if mask[i * 4] == 0 {
                        255
                    } else {
                        0
                    }
                }
                _ => 255,
            }
        };
        rgba.extend_from_slice(&[p[2], p[1], p[0], alpha]);
    }
    if rgba.chunks_exact(4).all(|p| p[3] == 0) {
        return None; // 빈 그림
    }
    let mut png_bytes = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut png_bytes, width, height);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header().ok()?;
        writer.write_image_data(&rgba).ok()?;
        writer.finish().ok()?;
    }
    Some(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(png_bytes)
    ))
}

#[cfg(not(windows))]
mod system {
    pub fn icons(exts: &[String]) -> Vec<Option<String>> {
        vec![None; exts.len()]
    }
}

#[cfg(windows)]
mod system {
    use std::ffi::c_void;
    use std::ptr::{null, null_mut};
    use windows_sys::core::GUID;
    use windows_sys::Win32::Graphics::Gdi::{
        CreateCompatibleDC, DeleteDC, DeleteObject, GetDIBits, GetObjectW, BITMAP, BITMAPINFO,
        BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS, HBITMAP,
    };
    use windows_sys::Win32::System::Com::{CoInitializeEx, CoUninitialize};
    use windows_sys::Win32::UI::Shell::{SHGetFileInfoW, SHGetImageList, SHFILEINFOW};
    use windows_sys::Win32::UI::WindowsAndMessaging::{DestroyIcon, GetIconInfo, HICON, ICONINFO};

    const FILE_ATTRIBUTE_NORMAL: u32 = 0x80;
    const SHGFI_SYSICONINDEX: u32 = 0x4000;
    const SHGFI_USEFILEATTRIBUTES: u32 = 0x10;
    /// 48×48. 화면 배율이 125~150%여도 흐려지지 않게 큰 것을 받아 줄여 보인다.
    const SHIL_EXTRALARGE: i32 = 2;
    const COINIT_APARTMENTTHREADED: u32 = 0x2;
    const COINIT_DISABLE_OLE1DDE: u32 = 0x4;
    const ILD_TRANSPARENT: u32 = 0x1;
    /// IImageList {46EB5926-582E-4017-9FDF-E8998DAA0950}
    const IID_IIMAGELIST: GUID = GUID {
        data1: 0x46eb5926,
        data2: 0x582e,
        data3: 0x4017,
        data4: [0x9f, 0xdf, 0xe8, 0x99, 0x8d, 0xaa, 0x09, 0x50],
    };

    /// IImageList 의 함수 자리(commoncontrols.h 순서): IUnknown 3개 뒤
    /// Add, ReplaceIcon, SetOverlayImage, Replace, AddMasked, Draw, Remove, GetIcon(10번째).
    /// comctl32 판(5·6)과 상관없이 쓰려고 ImageList_GetIcon 대신 인터페이스로 직접 부른다.
    type GetIconFn = unsafe extern "system" fn(*mut c_void, i32, u32, *mut HICON) -> i32;
    type ReleaseFn = unsafe extern "system" fn(*mut c_void) -> u32;

    pub fn icons(exts: &[String]) -> Vec<Option<String>> {
        unsafe {
            let hr = CoInitializeEx(null(), COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
            let mut list: *mut c_void = null_mut();
            let result = if SHGetImageList(SHIL_EXTRALARGE, &IID_IIMAGELIST, &mut list) >= 0 && !list.is_null() {
                let out = exts.iter().map(|ext| icon_for(list, ext)).collect();
                let vtbl = *(list as *const *const usize);
                let release: ReleaseFn = std::mem::transmute(*vtbl.add(2));
                release(list);
                out
            } else {
                vec![None; exts.len()]
            };
            if hr >= 0 {
                CoUninitialize();
            }
            result
        }
    }

    unsafe fn icon_for(list: *mut c_void, ext: &str) -> Option<String> {
        let name: Vec<u16> = format!("x.{ext}").encode_utf16().chain(Some(0)).collect();
        let mut info: SHFILEINFOW = std::mem::zeroed();
        let ok = SHGetFileInfoW(
            name.as_ptr(),
            FILE_ATTRIBUTE_NORMAL,
            &mut info,
            std::mem::size_of::<SHFILEINFOW>() as u32,
            SHGFI_SYSICONINDEX | SHGFI_USEFILEATTRIBUTES,
        );
        if ok == 0 {
            return None;
        }
        let vtbl = *(list as *const *const usize);
        let get_icon: GetIconFn = std::mem::transmute(*vtbl.add(10));
        let mut icon: HICON = null_mut();
        if get_icon(list, info.iIcon, ILD_TRANSPARENT, &mut icon) < 0 || icon.is_null() {
            return None;
        }
        let url = icon_to_png(icon);
        DestroyIcon(icon);
        url
    }

    unsafe fn bitmap_bgra(hdc: windows_sys::Win32::Graphics::Gdi::HDC, bitmap: HBITMAP, width: i32, height: i32) -> Option<Vec<u8>> {
        let mut header: BITMAPINFO = std::mem::zeroed();
        header.bmiHeader = BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width,
            biHeight: -height, // 위에서 아래로
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB,
            biSizeImage: 0,
            biXPelsPerMeter: 0,
            biYPelsPerMeter: 0,
            biClrUsed: 0,
            biClrImportant: 0,
        };
        let mut buffer = vec![0u8; (width * height * 4) as usize];
        let lines = GetDIBits(hdc, bitmap, 0, height as u32, buffer.as_mut_ptr() as *mut c_void, &mut header, DIB_RGB_COLORS);
        (lines == height).then_some(buffer)
    }

    unsafe fn icon_to_png(icon: HICON) -> Option<String> {
        let mut info: ICONINFO = std::mem::zeroed();
        if GetIconInfo(icon, &mut info) == 0 {
            return None;
        }
        let color = info.hbmColor;
        let mask = info.hbmMask;
        let result = (|| {
            if color.is_null() {
                return None; // 흑백 아이콘은 쓰지 않는다
            }
            let mut bm: BITMAP = std::mem::zeroed();
            if GetObjectW(color, std::mem::size_of::<BITMAP>() as i32, &mut bm as *mut _ as *mut c_void) == 0 {
                return None;
            }
            let (width, height) = (bm.bmWidth, bm.bmHeight);
            if width <= 0 || height <= 0 || width > 256 || height > 256 {
                return None;
            }
            let hdc = CreateCompatibleDC(null_mut());
            if hdc.is_null() {
                return None;
            }
            let pixels = bitmap_bgra(hdc, color, width, height);
            let mask_pixels = if mask.is_null() { None } else { bitmap_bgra(hdc, mask, width, height) };
            DeleteDC(hdc);
            super::to_png_data_url(width as u32, height as u32, &pixels?, mask_pixels.as_deref())
        })();
        if !color.is_null() {
            DeleteObject(color);
        }
        if !mask.is_null() {
            DeleteObject(mask);
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ext_is_cleaned() {
        assert_eq!(clean_ext(".HWP"), Some("hwp".to_string()));
        assert_eq!(clean_ext("x/../y"), None);
        assert_eq!(clean_ext(""), None);
    }

    #[test]
    fn png_uses_alpha_or_mask() {
        // 2×1: 알파 있음
        let url = to_png_data_url(2, 1, &[0, 0, 255, 255, 0, 255, 0, 128], None).unwrap();
        assert!(url.starts_with("data:image/png;base64,"));
        // 알파가 모두 0이면 마스크(검정=보임)로
        assert!(to_png_data_url(2, 1, &[0, 0, 255, 0, 0, 255, 0, 0], Some(&[0, 0, 0, 0, 255, 255, 255, 0])).is_some());
        // 모두 투명이면 없음
        assert!(to_png_data_url(1, 1, &[0, 0, 0, 0], Some(&[255, 255, 255, 0])).is_none());
    }
}
