//! 화면 캡처의 Windows 부분: 화면 읽기(BitBlt), 영역 고르기 덮개 창, 남은 초·진행 표시 창, 스크롤, 화면에 고정 창.
//! 이 파일의 함수는 모두 `capture()` 가 만든 전용 스레드(또는 고정 창마다 만든 스레드)에서 돈다.

use super::stitch::{Push, Stitcher};
use super::Mode;
use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::Once;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, CreateDIBSection, CreateFontW, CreateSolidBrush,
    DeleteDC, DeleteObject, DrawTextW, EndPaint, EnumDisplayMonitors, FillRect, GetDC, GetDIBits, GetMonitorInfoW, InvalidateRect,
    MonitorFromPoint, ReleaseDC, SelectObject, SetBkMode, SetBrushOrgEx, SetStretchBltMode, SetTextColor, StretchBlt,
    BITMAPINFO, BITMAPINFOHEADER, BI_RGB, CAPTUREBLT, DIB_RGB_COLORS, DT_CALCRECT, DT_CENTER, DT_NOPREFIX,
    DT_SINGLELINE, DT_VCENTER, HALFTONE, HBITMAP, HDC, HFONT, HGDIOBJ, HMONITOR, MONITORINFO, MONITOR_DEFAULTTONEAREST,
    PAINTSTRUCT, SRCCOPY, TRANSPARENT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::HiDpi::{
    GetDpiForWindow, SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    GetAsyncKeyState, ReleaseCapture, SendInput, SetCapture, INPUT, INPUT_MOUSE, MOUSEEVENTF_WHEEL, MOUSEINPUT,
    VK_ESCAPE,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu, DestroyWindow, DispatchMessageW,
    EnumChildWindows, EnumWindows, GetAncestor, GetClassNameW, GetClientRect, GetCursorPos, GetMessageW, GetSystemMetrics, GetWindowLongPtrW,
    GetWindowRect, GetWindowThreadProcessId, IsIconic, IsWindowVisible, KillTimer, LoadCursorW, PeekMessageW,
    PostQuitMessage, RegisterClassW, SetCursor, SetCursorPos, SetForegroundWindow, SetTimer, SetWindowDisplayAffinity,
    SetWindowLongPtrW, SetWindowPos, ShowWindow, TrackPopupMenu, TranslateMessage, WindowFromPoint, CS_DBLCLKS,
    CS_DROPSHADOW, GA_ROOT, GWLP_USERDATA, HTCAPTION, IDC_CROSS, IDC_SIZEALL, MA_NOACTIVATE, MF_SEPARATOR,
    MF_STRING, MSG, PM_REMOVE, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN,
    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOZORDER, SW_SHOW, SW_SHOWNOACTIVATE, TPM_RETURNCMD, TPM_RIGHTBUTTON,
    WDA_EXCLUDEFROMCAPTURE, WM_DESTROY, WM_ERASEBKGND, WM_KEYDOWN, WM_LBUTTONDOWN, WM_LBUTTONUP,
    WM_MOUSEACTIVATE, WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_NCHITTEST, WM_NCLBUTTONDBLCLK, WM_NCRBUTTONUP, WM_PAINT,
    WM_RBUTTONUP, WM_SETCURSOR, WM_TIMER, WNDCLASSW, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP,
};

// ── 공통 ───────────────────────────────────────────────────────────

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// RGB → COLORREF(0x00BBGGRR)
const fn rgb(r: u8, g: u8, b: u8) -> u32 {
    r as u32 | (g as u32) << 8 | (b as u32) << 16
}

const ACCENT: u32 = rgb(37, 99, 235);
const PANEL: u32 = rgb(31, 41, 55);
const WHITE: u32 = rgb(255, 255, 255);

fn lo(l: LPARAM) -> i32 {
    (l as u32 & 0xFFFF) as i16 as i32
}
fn hi(l: LPARAM) -> i32 {
    ((l as u32 >> 16) & 0xFFFF) as i16 as i32
}

fn width(r: &RECT) -> i32 {
    r.right - r.left
}
fn height(r: &RECT) -> i32 {
    r.bottom - r.top
}
fn contains(r: &RECT, x: i32, y: i32) -> bool {
    x >= r.left && x < r.right && y >= r.top && y < r.bottom
}
fn intersect(a: &RECT, b: &RECT) -> Option<RECT> {
    let r = RECT { left: a.left.max(b.left), top: a.top.max(b.top), right: a.right.min(b.right), bottom: a.bottom.min(b.bottom) };
    (r.right > r.left && r.bottom > r.top).then_some(r)
}

fn esc_down() -> bool {
    unsafe { (GetAsyncKeyState(VK_ESCAPE as i32) as u16 & 0x8000) != 0 }
}

/// 이 스레드에 쌓인 창 메시지를 다 처리한다.
fn pump() {
    unsafe {
        let mut msg: MSG = zeroed();
        while PeekMessageW(&mut msg, null_mut(), 0, 0, PM_REMOVE) != 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

/// 메시지를 돌리며 기다린다.
fn wait(ms: u64) {
    let until = Instant::now() + Duration::from_millis(ms);
    while Instant::now() < until {
        pump();
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn register_class(once: &'static Once, name: &'static str, proc_: unsafe extern "system" fn(HWND, u32, WPARAM, LPARAM) -> LRESULT, style: u32) {
    once.call_once(|| unsafe {
        let class = wide(name);
        let wc = WNDCLASSW {
            style,
            lpfnWndProc: Some(proc_),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: GetModuleHandleW(null()),
            hIcon: null_mut(),
            hCursor: LoadCursorW(null_mut(), IDC_CROSS),
            hbrBackground: null_mut(),
            lpszMenuName: null(),
            // 클래스 이름은 프로그램이 끝날 때까지 살아 있어야 한다
            lpszClassName: Box::leak(class.into_boxed_slice()).as_ptr(),
        };
        RegisterClassW(&wc);
    });
}

fn font(px: i32, bold: bool) -> HFONT {
    let face = wide("Malgun Gothic");
    unsafe { CreateFontW(-px, 0, 0, 0, if bold { 700 } else { 400 }, 0, 0, 0, 1, 0, 0, 5, 0, face.as_ptr()) }
}

fn scale_of(hwnd: HWND) -> f64 {
    let dpi = unsafe { GetDpiForWindow(hwnd) };
    if dpi == 0 { 1.0 } else { dpi as f64 / 96.0 }
}

/// 마우스가 있는 모니터(전체, 작업 영역)
fn monitor_at_cursor() -> (RECT, RECT) {
    unsafe {
        let mut pt: POINT = zeroed();
        GetCursorPos(&mut pt);
        monitor_at(pt)
    }
}
fn monitor_at(pt: POINT) -> (RECT, RECT) {
    unsafe {
        let mon = MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST);
        let mut info: MONITORINFO = zeroed();
        info.cbSize = size_of::<MONITORINFO>() as u32;
        GetMonitorInfoW(mon, &mut info);
        (info.rcMonitor, info.rcWork)
    }
}

unsafe extern "system" fn collect_monitor(_mon: HMONITOR, _dc: HDC, rect: *mut RECT, lparam: LPARAM) -> windows_sys::core::BOOL {
    let list = &mut *(lparam as *mut Vec<RECT>);
    if !rect.is_null() {
        list.push(*rect);
    }
    1
}

/// 연결된 모니터들(실제 화면 점 좌표)
fn monitors() -> Vec<RECT> {
    let mut list: Vec<RECT> = Vec::new();
    unsafe { EnumDisplayMonitors(null_mut(), null(), Some(collect_monitor), &mut list as *mut _ as LPARAM) };
    list
}

fn virtual_screen() -> RECT {
    unsafe {
        let x = GetSystemMetrics(SM_XVIRTUALSCREEN);
        let y = GetSystemMetrics(SM_YVIRTUALSCREEN);
        RECT { left: x, top: y, right: x + GetSystemMetrics(SM_CXVIRTUALSCREEN), bottom: y + GetSystemMetrics(SM_CYVIRTUALSCREEN) }
    }
}

// ── 화면 읽기 ─────────────────────────────────────────────────────

/// 화면 r(실제 화면 점 좌표)을 위에서 아래로 쌓은 BGRA 로 읽는다.
fn grab(r: &RECT) -> Result<Vec<u8>, String> {
    let (w, h) = (width(r), height(r));
    if w <= 0 || h <= 0 {
        return Err("찍을 영역이 없습니다.".to_string());
    }
    unsafe {
        let screen = GetDC(null_mut());
        if screen.is_null() {
            return Err("화면을 읽지 못했습니다.".to_string());
        }
        let mem = CreateCompatibleDC(screen);
        let bmp = CreateCompatibleBitmap(screen, w, h);
        if mem.is_null() || bmp.is_null() {
            if !bmp.is_null() {
                DeleteObject(bmp as HGDIOBJ);
            }
            if !mem.is_null() {
                DeleteDC(mem);
            }
            ReleaseDC(null_mut(), screen);
            return Err("화면이 너무 커서 읽지 못했습니다.".to_string());
        }
        let old = SelectObject(mem, bmp as HGDIOBJ);
        let ok = BitBlt(mem, 0, 0, w, h, screen, r.left, r.top, SRCCOPY | CAPTUREBLT) != 0;
        SelectObject(mem, old);
        let mut bmi: BITMAPINFO = zeroed();
        bmi.bmiHeader = BITMAPINFOHEADER {
            biSize: size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: w,
            biHeight: -h, // 위에서 아래로
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB,
            ..zeroed()
        };
        let mut buf = vec![0u8; (w as usize) * (h as usize) * 4];
        let lines = GetDIBits(mem, bmp, 0, h as u32, buf.as_mut_ptr() as *mut _, &mut bmi, DIB_RGB_COLORS);
        DeleteObject(bmp as HGDIOBJ);
        DeleteDC(mem);
        ReleaseDC(null_mut(), screen);
        if !ok || lines != h {
            return Err("화면을 읽지 못했습니다.".to_string());
        }
        for px in buf.chunks_exact_mut(4) {
            px[3] = 255;
        }
        Ok(buf)
    }
}

/// 전체 그림(full_w 너비)에서 r 부분만 잘라 낸다.
fn crop(full: &[u8], full_w: i32, r: &RECT) -> Vec<u8> {
    let stride = full_w as usize * 4;
    let mut out = Vec::with_capacity(width(r) as usize * height(r) as usize * 4);
    for y in r.top..r.bottom {
        let start = y as usize * stride + r.left as usize * 4;
        out.extend_from_slice(&full[start..start + width(r) as usize * 4]);
    }
    out
}

/// BGRA 그림을 GDI 그림(DIB)으로 만들어 메모리 DC 에 끼운다. (dc, bmp, old)
unsafe fn dib_dc(w: i32, h: i32, bgra: &[u8]) -> Option<(HDC, HBITMAP, HGDIOBJ)> {
    let screen = GetDC(null_mut());
    let dc = CreateCompatibleDC(screen);
    let mut bmi: BITMAPINFO = zeroed();
    bmi.bmiHeader = BITMAPINFOHEADER {
        biSize: size_of::<BITMAPINFOHEADER>() as u32,
        biWidth: w,
        biHeight: -h,
        biPlanes: 1,
        biBitCount: 32,
        biCompression: BI_RGB,
        ..zeroed()
    };
    let mut bits: *mut core::ffi::c_void = null_mut();
    let bmp = CreateDIBSection(screen, &bmi, DIB_RGB_COLORS, &mut bits, null_mut(), 0);
    ReleaseDC(null_mut(), screen);
    if dc.is_null() || bmp.is_null() || bits.is_null() {
        if !bmp.is_null() {
            DeleteObject(bmp as HGDIOBJ);
        }
        if !dc.is_null() {
            DeleteDC(dc);
        }
        return None;
    }
    std::ptr::copy_nonoverlapping(bgra.as_ptr(), bits as *mut u8, bgra.len());
    let old = SelectObject(dc, bmp as HGDIOBJ);
    Some((dc, bmp, old))
}

unsafe fn free_dc((dc, bmp, old): (HDC, HBITMAP, HGDIOBJ)) {
    SelectObject(dc, old);
    DeleteObject(bmp as HGDIOBJ);
    DeleteDC(dc);
}

// ── 보이는 창 목록(누르기만 하면 그 창을 고른다) ─────────────────────

unsafe extern "system" fn collect_window(hwnd: HWND, lparam: LPARAM) -> windows_sys::core::BOOL {
    let list = &mut *(lparam as *mut Vec<(HWND, RECT)>);
    if IsWindowVisible(hwnd) == 0 || IsIconic(hwnd) != 0 {
        return 1;
    }
    let mut pid = 0u32;
    GetWindowThreadProcessId(hwnd, &mut pid);
    if pid == std::process::id() {
        return 1; // JB업무ON 창·고정 창
    }
    let mut cloaked = 0u32;
    DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED as u32, &mut cloaked as *mut _ as *mut _, 4);
    if cloaked != 0 {
        return 1; // 다른 가상 데스크톱·숨은 앱 창
    }
    let mut r: RECT = zeroed();
    if DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS as u32, &mut r as *mut _ as *mut _, size_of::<RECT>() as u32) != 0 {
        GetWindowRect(hwnd, &mut r);
    }
    if width(&r) >= 40 && height(&r) >= 30 {
        list.push((hwnd, r));
    }
    1
}

unsafe extern "system" fn collect_child(hwnd: HWND, lparam: LPARAM) -> windows_sys::core::BOOL {
    let list = &mut *(lparam as *mut Vec<RECT>);
    if IsWindowVisible(hwnd) != 0 {
        let mut r: RECT = zeroed();
        GetWindowRect(hwnd, &mut r);
        list.push(r);
    }
    1
}

fn class_name(hwnd: HWND) -> String {
    let mut buf = [0u16; 128];
    let n = unsafe { GetClassNameW(hwnd, buf.as_mut_ptr(), buf.len() as i32) };
    String::from_utf16_lossy(&buf[..n.max(0) as usize])
}

/// 창 안의 칸들: 자식 창(한글의 문서 칸 등)과, 자식 창으로 나뉘지 않는 브라우저·엑셀은 UI 자동화로 찾은 칸
/// (엣지·크롬의 웹 페이지 칸 MultiContentsView, 엑셀의 시트 표 XLSpreadsheetGrid — 사용자 PC에서 확인).
fn window_parts(hwnd: HWND, frame: &RECT) -> Vec<RECT> {
    let mut parts: Vec<RECT> = Vec::new();
    unsafe { EnumChildWindows(hwnd, Some(collect_child), &mut parts as *mut _ as LPARAM) };
    let class = class_name(hwnd);
    if class == "Chrome_WidgetWin_1" || class == "XLMAIN" {
        parts.extend(uia_parts(hwnd, &class));
    }
    let frame_area = width(frame) as i64 * height(frame) as i64;
    let mut parts: Vec<RECT> = parts
        .into_iter()
        .filter_map(|r| intersect(&r, frame))
        .filter(|r| width(r) >= 40 && height(r) >= 30 && (width(r) as i64 * height(r) as i64) * 100 < frame_area * 97)
        .collect();
    parts.sort_by_key(|r| width(r) as i64 * height(r) as i64);
    parts.dedup_by(|a, b| a.left == b.left && a.top == b.top && a.right == b.right && a.bottom == b.bottom);
    parts
}

/// UI 자동화로 브라우저의 웹 페이지 칸·엑셀의 시트 표 칸을 찾는다. 응답이 늦은 프로그램에 붙잡히지 않게 0.8초만 기다린다.
fn uia_parts(hwnd: HWND, class: &str) -> Vec<RECT> {
    use windows::core::{Interface, BSTR};
    use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_INPROC_SERVER};
    use windows::Win32::System::Variant::{VariantClear, VARIANT, VT_BSTR};
    use windows::Win32::UI::Accessibility::{
        CUIAutomation, IUIAutomation, IUIAutomation2, TreeScope_Descendants, UIA_ClassNamePropertyId,
    };
    let mut out = Vec::new();
    let Ok(uia) = (unsafe { CoCreateInstance::<_, IUIAutomation>(&CUIAutomation, None, CLSCTX_INPROC_SERVER) }) else {
        return out;
    };
    if let Ok(u2) = uia.cast::<IUIAutomation2>() {
        unsafe {
            let _ = u2.SetConnectionTimeout(800);
            let _ = u2.SetTransactionTimeout(800);
        }
    }
    let Ok(root) = (unsafe { uia.ElementFromHandle(windows::Win32::Foundation::HWND(hwnd)) }) else {
        return out;
    };
    let names: &[&str] = if class == "XLMAIN" { &["XLSpreadsheetGrid"] } else { &["MultiContentsView"] };
    for name in names {
        let mut value = VARIANT::default();
        unsafe {
            (*value.Anonymous.Anonymous).vt = VT_BSTR;
            (*value.Anonymous.Anonymous).Anonymous.bstrVal = std::mem::ManuallyDrop::new(BSTR::from(*name));
        }
        let cond = unsafe { uia.CreatePropertyCondition(UIA_ClassNamePropertyId, &value) };
        unsafe {
            let _ = VariantClear(&mut value);
        }
        let Ok(cond) = cond else {
            continue;
        };
        if let Ok(el) = unsafe { root.FindFirst(TreeScope_Descendants, &cond) } {
            if let Ok(r) = unsafe { el.CurrentBoundingRectangle() } {
                out.push(RECT { left: r.left, top: r.top, right: r.right, bottom: r.bottom });
            }
        }
    }
    out
}

/// 화면에 보이는 창(위에 있는 창부터). 창마다 고를 수 있는 곳을 작은 것부터 담고, 맨 끝은 창 전체.
fn visible_windows() -> Vec<Vec<RECT>> {
    let mut list: Vec<(HWND, RECT)> = Vec::new();
    unsafe { EnumWindows(Some(collect_window), &mut list as *mut _ as LPARAM) };
    list.into_iter()
        .enumerate()
        .map(|(i, (hwnd, frame))| {
            // 맨 위쪽 창 몇 개만 안쪽 칸까지 찾는다(나머지는 거의 가려져 있다)
            let mut parts = if i < 12 { window_parts(hwnd, &frame) } else { Vec::new() };
            parts.push(frame);
            parts
        })
        .collect()
}

// ── 영역 고르기 덮개 창 ───────────────────────────────────────────

struct Overlay {
    w: i32,
    h: i32,
    bright: (HDC, HBITMAP, HGDIOBJ),
    dim: (HDC, HBITMAP, HGDIOBJ),
    back: Option<(HDC, HBITMAP, HGDIOBJ)>,
    /// 덮개 창 좌표(왼쪽 위 = 가상 화면 왼쪽 위). 창마다 고를 수 있는 곳(작은 것부터, 끝은 창 전체)
    windows: Vec<Vec<RECT>>,
    /// 휠로 고른 넓이(0 = 가장 안쪽 칸)
    level: usize,
    /// 마우스 아래 후보가 바뀌면 level 을 0 으로 되돌린다
    level_key: (usize, usize),
    monitors_hint: Vec<u16>,
    /// 끌어서 고르지 않고 누르기만 한다(전체 화면: 모니터 고르기)
    pick_only: bool,
    start: Option<POINT>,
    cur: POINT,
    result: Option<RECT>,
    finished: bool,
    font: HFONT,
}

impl Overlay {
    fn drag_rect(&self) -> Option<RECT> {
        let s = self.start?;
        let (l, r) = (s.x.min(self.cur.x), s.x.max(self.cur.x) + 1);
        let (t, b) = (s.y.min(self.cur.y), s.y.max(self.cur.y) + 1);
        let all = RECT { left: 0, top: 0, right: self.w, bottom: self.h };
        intersect(&RECT { left: l, top: t, right: r, bottom: b }, &all)
    }
    fn dragged(&self) -> bool {
        !self.pick_only && self.start.is_some_and(|s| (s.x - self.cur.x).abs() >= 4 || (s.y - self.cur.y).abs() >= 4)
    }
    /// 마우스 아래 창의 후보들(작은 것부터)과 그 창의 번호
    fn candidates(&self) -> Option<(usize, Vec<RECT>)> {
        let (i, parts) = self
            .windows
            .iter()
            .enumerate()
            .find(|(_, parts)| parts.last().is_some_and(|f| contains(f, self.cur.x, self.cur.y)))?;
        Some((i, parts.iter().filter(|r| contains(r, self.cur.x, self.cur.y)).copied().collect()))
    }
    /// 끌지 않았을 때 고를 곳: 마우스 아래의 가장 안쪽 칸(휠로 넓히기), 창이 없으면 그 모니터
    fn hover_rect(&self, origin: POINT) -> RECT {
        let all = RECT { left: 0, top: 0, right: self.w, bottom: self.h };
        if let Some((_, list)) = self.candidates() {
            if let Some(r) = list.get(self.level.min(list.len().saturating_sub(1))).and_then(|r| intersect(r, &all)) {
                return r;
            }
        }
        let (mon, _) = monitor_at(POINT { x: self.cur.x + origin.x, y: self.cur.y + origin.y });
        let mon = RECT { left: mon.left - origin.x, top: mon.top - origin.y, right: mon.right - origin.x, bottom: mon.bottom - origin.y };
        intersect(&mon, &all).unwrap_or(all)
    }
    fn selection(&self, origin: POINT) -> RECT {
        if self.dragged() {
            if let Some(r) = self.drag_rect() {
                return r;
            }
        }
        self.hover_rect(origin)
    }
}

static OVERLAY_CLASS: Once = Once::new();
const OVERLAY_NAME: &str = "JBEduCaptureOverlay";

thread_local! {
    static ORIGIN: std::cell::Cell<POINT> = const { std::cell::Cell::new(POINT { x: 0, y: 0 }) };
}

unsafe fn fill(dc: HDC, r: &RECT, color: u32) {
    let brush = CreateSolidBrush(color);
    FillRect(dc, r, brush);
    DeleteObject(brush as HGDIOBJ);
}

/// 글을 어두운 띠에 담아 그린다. (x, y) 는 띠의 왼쪽 위. 그린 띠를 돌려준다.
unsafe fn label(dc: HDC, font: HFONT, text: &str, x: i32, y: i32, pad: i32) -> RECT {
    let t = wide(text);
    let old = SelectObject(dc, font as HGDIOBJ);
    let mut m = RECT { left: 0, top: 0, right: 0, bottom: 0 };
    DrawTextW(dc, t.as_ptr(), -1, &mut m, DT_CALCRECT | DT_SINGLELINE | DT_NOPREFIX);
    let r = RECT { left: x, top: y, right: x + width(&m) + pad * 2, bottom: y + height(&m) + pad };
    fill(dc, &r, PANEL);
    SetBkMode(dc, TRANSPARENT as i32);
    SetTextColor(dc, WHITE);
    let mut tr = r;
    DrawTextW(dc, t.as_ptr(), -1, &mut tr, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
    SelectObject(dc, old);
    r
}

unsafe fn measure(dc: HDC, font: HFONT, text: &str, pad: i32) -> (i32, i32) {
    let t = wide(text);
    let old = SelectObject(dc, font as HGDIOBJ);
    let mut m = RECT { left: 0, top: 0, right: 0, bottom: 0 };
    DrawTextW(dc, t.as_ptr(), -1, &mut m, DT_CALCRECT | DT_SINGLELINE | DT_NOPREFIX);
    SelectObject(dc, old);
    (width(&m) + pad * 2, height(&m) + pad)
}

unsafe fn paint_overlay(hwnd: HWND, st: &mut Overlay) {
    let origin = ORIGIN.with(|o| o.get());
    let mut ps: PAINTSTRUCT = zeroed();
    let hdc = BeginPaint(hwnd, &mut ps);
    if st.back.is_none() {
        let dc = CreateCompatibleDC(hdc);
        let bmp = CreateCompatibleBitmap(hdc, st.w, st.h);
        if !dc.is_null() && !bmp.is_null() {
            let old = SelectObject(dc, bmp as HGDIOBJ);
            st.back = Some((dc, bmp, old));
        }
    }
    let target = st.back.map(|b| b.0).unwrap_or(hdc);
    BitBlt(target, 0, 0, st.w, st.h, st.dim.0, 0, 0, SRCCOPY);
    let sel = st.selection(origin);
    BitBlt(target, sel.left, sel.top, width(&sel), height(&sel), st.bright.0, sel.left, sel.top, SRCCOPY);
    let line = (2.0 * scale_of(hwnd)).round().max(1.0) as i32;
    for edge in [
        RECT { left: sel.left, top: sel.top, right: sel.right, bottom: sel.top + line },
        RECT { left: sel.left, top: sel.bottom - line, right: sel.right, bottom: sel.bottom },
        RECT { left: sel.left, top: sel.top, right: sel.left + line, bottom: sel.bottom },
        RECT { left: sel.right - line, top: sel.top, right: sel.right, bottom: sel.bottom },
    ] {
        fill(target, &edge, ACCENT);
    }
    let pad = (6.0 * scale_of(hwnd)) as i32;
    let size_text = format!("{} × {}", width(&sel), height(&sel));
    let (_, lh) = measure(target, st.font, &size_text, pad);
    let ly = if sel.top - lh - 4 >= 0 { sel.top - lh - 4 } else { sel.top + 4 };
    label(target, st.font, &size_text, sel.left + if ly == sel.top + 4 { 4 } else { 0 }, ly, pad);
    // 안내: 마우스가 있는 모니터 위쪽 가운데
    let hint = String::from_utf16_lossy(&st.monitors_hint[..st.monitors_hint.len() - 1]);
    let (mon, _) = monitor_at(POINT { x: st.cur.x + origin.x, y: st.cur.y + origin.y });
    let (hw, _) = measure(target, st.font, &hint, pad * 2);
    let hx = (mon.left - origin.x) + (width(&mon) - hw) / 2;
    let hy = (mon.top - origin.y) + (24.0 * scale_of(hwnd)) as i32;
    if !(st.start.is_some() && contains(&sel, hx + hw / 2, hy)) {
        label(target, st.font, &hint, hx, hy, pad * 2);
    }
    if let Some(back) = st.back {
        BitBlt(hdc, 0, 0, st.w, st.h, back.0, 0, 0, SRCCOPY);
    }
    EndPaint(hwnd, &ps);
}

unsafe extern "system" fn overlay_proc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut Overlay;
    if ptr.is_null() {
        return DefWindowProcW(hwnd, msg, wparam, lparam);
    }
    let st = &mut *ptr;
    match msg {
        WM_PAINT => {
            paint_overlay(hwnd, st);
            0
        }
        WM_ERASEBKGND => 1,
        WM_SETCURSOR => {
            SetCursor(LoadCursorW(null_mut(), IDC_CROSS));
            1
        }
        WM_MOUSEMOVE => {
            st.cur = POINT { x: lo(lparam), y: hi(lparam) };
            let key = st.candidates().map(|(i, list)| (i, list.len())).unwrap_or((usize::MAX, 0));
            if key != st.level_key {
                st.level_key = key;
                st.level = 0;
            }
            InvalidateRect(hwnd, null(), 0);
            0
        }
        WM_MOUSEWHEEL => {
            // 휠 위로: 넓게(안쪽 칸 → 창 전체), 아래로: 좁게
            let delta = ((wparam >> 16) & 0xFFFF) as u16 as i16;
            let count = st.candidates().map(|(_, list)| list.len()).unwrap_or(1);
            if delta > 0 {
                st.level = (st.level + 1).min(count.saturating_sub(1));
            } else if delta < 0 {
                st.level = st.level.saturating_sub(1);
            }
            InvalidateRect(hwnd, null(), 0);
            0
        }
        WM_LBUTTONDOWN => {
            st.cur = POINT { x: lo(lparam), y: hi(lparam) };
            st.start = Some(st.cur);
            SetCapture(hwnd);
            0
        }
        WM_LBUTTONUP => {
            ReleaseCapture();
            st.cur = POINT { x: lo(lparam), y: hi(lparam) };
            let origin = ORIGIN.with(|o| o.get());
            st.result = Some(st.selection(origin));
            st.finished = true;
            0
        }
        WM_RBUTTONUP => {
            st.result = None;
            st.finished = true;
            0
        }
        WM_KEYDOWN if wparam == VK_ESCAPE as usize => {
            st.result = None;
            st.finished = true;
            0
        }
        WM_TIMER => {
            // 덮개 창이 키보드를 받지 못해도(다른 창이 앞에 있을 때) Esc 로 그만둘 수 있게
            if esc_down() {
                st.result = None;
                st.finished = true;
            }
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// 멈춘 화면(frozen, 가상 화면 전체)을 덮어 영역을 고르게 한다. 고른 곳(실제 화면 좌표) 또는 취소면 None.
fn select_region(frozen: &[u8], vs: &RECT, windows: Vec<Vec<RECT>>, hint: &str, pick_only: bool) -> Result<Option<RECT>, String> {
    let (w, h) = (width(vs), height(vs));
    let dimmed: Vec<u8> = frozen
        .chunks_exact(4)
        .flat_map(|p| [(p[0] as u32 * 11 / 20) as u8, (p[1] as u32 * 11 / 20) as u8, (p[2] as u32 * 11 / 20) as u8, 255])
        .collect();
    register_class(&OVERLAY_CLASS, OVERLAY_NAME, overlay_proc, 0);
    unsafe {
        let bright = dib_dc(w, h, frozen).ok_or("화면이 너무 커서 덮개를 만들지 못했습니다.")?;
        let Some(dim) = dib_dc(w, h, &dimmed) else {
            free_dc(bright);
            return Err("화면이 너무 커서 덮개를 만들지 못했습니다.".to_string());
        };
        drop(dimmed);
        let origin = POINT { x: vs.left, y: vs.top };
        ORIGIN.with(|o| o.set(origin));
        let mut pt: POINT = zeroed();
        GetCursorPos(&mut pt);
        let class = wide(OVERLAY_NAME);
        let title = wide("화면 캡처");
        let hwnd = CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            class.as_ptr(),
            title.as_ptr(),
            WS_POPUP,
            vs.left,
            vs.top,
            w,
            h,
            null_mut(),
            null_mut(),
            GetModuleHandleW(null()),
            null(),
        );
        if hwnd.is_null() {
            free_dc(bright);
            free_dc(dim);
            return Err("화면 캡처 창을 만들지 못했습니다.".to_string());
        }
        let font_px = (15.0 * scale_of(hwnd)).round() as i32;
        let mut st = Box::new(Overlay {
            w,
            h,
            bright,
            dim,
            back: None,
            windows: windows
                .into_iter()
                .map(|parts| {
                    parts
                        .into_iter()
                        .map(|r| RECT { left: r.left - origin.x, top: r.top - origin.y, right: r.right - origin.x, bottom: r.bottom - origin.y })
                        .collect()
                })
                .collect(),
            level: 0,
            level_key: (usize::MAX, 0),
            monitors_hint: wide(hint),
            pick_only,
            start: None,
            cur: POINT { x: pt.x - origin.x, y: pt.y - origin.y },
            result: None,
            finished: false,
            font: font(font_px, true),
        });
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, &mut *st as *mut Overlay as isize);
        ShowWindow(hwnd, SW_SHOW);
        SetForegroundWindow(hwnd);
        SetTimer(hwnd, 1, 50, None);
        let mut msg: MSG = zeroed();
        while !st.finished && GetMessageW(&mut msg, null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        KillTimer(hwnd, 1);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        DestroyWindow(hwnd);
        pump();
        if let Some(back) = st.back.take() {
            free_dc(back);
        }
        free_dc(st.bright);
        free_dc(st.dim);
        DeleteObject(st.font as HGDIOBJ);
        Ok(st.result.map(|r| RECT { left: r.left + origin.x, top: r.top + origin.y, right: r.right + origin.x, bottom: r.bottom + origin.y }))
    }
}

// ── 남은 초·진행을 보이는 작은 창 ──────────────────────────────────

struct Badge {
    big: String,
    text: String,
    clicked: bool,
    font_big: HFONT,
    font: HFONT,
}

static BADGE_CLASS: Once = Once::new();
const BADGE_NAME: &str = "JBEduCaptureBadge";

unsafe extern "system" fn badge_proc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut Badge;
    if ptr.is_null() {
        return DefWindowProcW(hwnd, msg, wparam, lparam);
    }
    let st = &mut *ptr;
    match msg {
        WM_PAINT => {
            let mut ps: PAINTSTRUCT = zeroed();
            let hdc = BeginPaint(hwnd, &mut ps);
            let mut rc: RECT = zeroed();
            GetClientRect(hwnd, &mut rc);
            fill(hdc, &rc, PANEL);
            fill(hdc, &RECT { left: 0, top: 0, right: rc.right, bottom: (3.0 * scale_of(hwnd)) as i32 }, ACCENT);
            SetBkMode(hdc, TRANSPARENT as i32);
            SetTextColor(hdc, WHITE);
            let mut text_rc = rc;
            if !st.big.is_empty() {
                let big = wide(&st.big);
                let mut br = RECT { left: 0, top: 0, right: rc.right, bottom: rc.bottom * 3 / 5 };
                let old = SelectObject(hdc, st.font_big as HGDIOBJ);
                DrawTextW(hdc, big.as_ptr(), -1, &mut br, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
                SelectObject(hdc, old);
                text_rc.top = rc.bottom * 3 / 5 - (4.0 * scale_of(hwnd)) as i32;
            }
            let t = wide(&st.text);
            let old = SelectObject(hdc, st.font as HGDIOBJ);
            DrawTextW(hdc, t.as_ptr(), -1, &mut text_rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
            SelectObject(hdc, old);
            EndPaint(hwnd, &ps);
            0
        }
        WM_ERASEBKGND => 1,
        WM_MOUSEACTIVATE => MA_NOACTIVATE as LRESULT,
        WM_LBUTTONDOWN => {
            st.clicked = true;
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

struct BadgeWindow {
    hwnd: HWND,
    st: Box<Badge>,
}

impl BadgeWindow {
    /// place: 창을 둘 곳을 정한다(창 크기 w,h → 왼쪽 위)
    fn show(big: &str, text: &str, place: impl Fn(i32, i32) -> (i32, i32)) -> Option<Self> {
        register_class(&BADGE_CLASS, BADGE_NAME, badge_proc, 0);
        unsafe {
            let class = wide(BADGE_NAME);
            let title = wide("화면 캡처");
            let hwnd = CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                class.as_ptr(),
                title.as_ptr(),
                WS_POPUP,
                0,
                0,
                10,
                10,
                null_mut(),
                null_mut(),
                GetModuleHandleW(null()),
                null(),
            );
            if hwnd.is_null() {
                return None;
            }
            let s = scale_of(hwnd);
            let mut st = Box::new(Badge {
                big: big.to_string(),
                text: text.to_string(),
                clicked: false,
                font_big: font((40.0 * s) as i32, true),
                font: font((14.0 * s) as i32, false),
            });
            let screen = GetDC(null_mut());
            let (tw, th) = measure(screen, st.font, text, (18.0 * s) as i32);
            ReleaseDC(null_mut(), screen);
            let w = tw.max((180.0 * s) as i32);
            let h = if big.is_empty() { th + (14.0 * s) as i32 } else { (110.0 * s) as i32 };
            let (x, y) = place(w, h);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, &mut *st as *mut Badge as isize);
            // 찍히는 화면에 이 창이 들어가지 않게(Windows 10 2004 이상). 안 되는 PC 는 찍기 전에 숨긴다.
            SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE);
            SetWindowPos(hwnd, null_mut(), x, y, w, h, SWP_NOACTIVATE | SWP_NOZORDER);
            ShowWindow(hwnd, SW_SHOWNOACTIVATE);
            pump();
            Some(Self { hwnd, st })
        }
    }

    fn set(&mut self, big: &str, text: &str) {
        if self.st.big != big || self.st.text != text {
            self.st.big = big.to_string();
            self.st.text = text.to_string();
            unsafe { InvalidateRect(self.hwnd, null(), 0) };
        }
        pump();
    }

    fn clicked(&self) -> bool {
        self.st.clicked
    }
}

impl Drop for BadgeWindow {
    fn drop(&mut self) {
        unsafe {
            SetWindowLongPtrW(self.hwnd, GWLP_USERDATA, 0);
            DestroyWindow(self.hwnd);
            DeleteObject(self.st.font as HGDIOBJ);
            DeleteObject(self.st.font_big as HGDIOBJ);
        }
        pump();
    }
}

/// 남은 초를 보이며 기다린다. Esc 나 창을 누르면 그만둔다(false).
fn countdown(secs: u32) -> bool {
    let (mon, _) = monitor_at_cursor();
    let text = "초 뒤에 찍습니다 · Esc 를 누르면 그만둡니다";
    let badge = BadgeWindow::show(&secs.to_string(), text, |w, _h| (mon.left + (width(&mon) - w) / 2, mon.top + height(&mon) / 12));
    let Some(mut badge) = badge else {
        wait(secs as u64 * 1000);
        return true;
    };
    let until = Instant::now() + Duration::from_secs(secs as u64);
    loop {
        let left = until.saturating_duration_since(Instant::now());
        if left.is_zero() {
            break;
        }
        if esc_down() || badge.clicked() {
            return false;
        }
        badge.set(&((left.as_millis() as u64).div_ceil(1000)).to_string(), text);
        std::thread::sleep(Duration::from_millis(30));
    }
    drop(badge);
    // 창이 사라진 화면이 다시 그려질 때까지
    wait(150);
    true
}

// ── 스크롤 캡처 ───────────────────────────────────────────────────

/// 이어 붙인 그림의 높이 한도(점). 넘으면 거기서 멈춘다.
const SCROLL_MAX_HEIGHT: usize = 20_000;
const SCROLL_MAX_STEPS: usize = 400;

fn wheel_down() {
    unsafe {
        let mut input: INPUT = zeroed();
        input.r#type = INPUT_MOUSE;
        input.Anonymous.mi = MOUSEINPUT { dx: 0, dy: 0, mouseData: (-120i32) as u32, dwFlags: MOUSEEVENTF_WHEEL, time: 0, dwExtraInfo: 0 };
        SendInput(1, &input, size_of::<INPUT>() as i32);
    }
}

/// 굴린 뒤 화면이 멈출 때까지(부드러운 스크롤) 기다렸다가 찍는다.
fn grab_settled(r: &RECT) -> Result<Vec<u8>, String> {
    wait(120);
    let mut last = grab(r)?;
    let start = Instant::now();
    while start.elapsed() < Duration::from_millis(1500) {
        wait(80);
        let now = grab(r)?;
        if now == last {
            return Ok(now);
        }
        last = now;
    }
    Ok(last)
}

fn scroll_capture(r: RECT) -> Result<Option<Vec<u8>>, String> {
    let (w, h) = (width(&r) as usize, height(&r) as usize);
    if h < 60 {
        return Err("스크롤 캡처는 높이 60점 이상인 영역을 골라 주세요.".to_string());
    }
    let (mon, _) = monitor_at(POINT { x: r.left + width(&r) / 2, y: r.top + height(&r) / 2 });
    let text = |n: usize| format!("스크롤 캡처 중 · {n}장 · 마우스를 움직이지 마세요 · Esc 또는 이 창을 누르면 멈춥니다");
    // 진행 창은 고른 곳 밖(아래, 안 되면 위, 그것도 안 되면 모니터 아래쪽)에 둔다
    let mut badge = BadgeWindow::show("", &text(1), |bw, bh| {
        let x = (r.left + (width(&r) - bw) / 2).clamp(mon.left, mon.right - bw);
        if r.bottom + 8 + bh <= mon.bottom {
            (x, r.bottom + 8)
        } else if r.top - 8 - bh >= mon.top {
            (x, r.top - 8 - bh)
        } else {
            (x, mon.bottom - bh - 8)
        }
    });
    let mut saved: POINT = unsafe { zeroed() };
    unsafe { GetCursorPos(&mut saved) };
    let (cx, cy) = (r.left + width(&r) / 2, r.top + height(&r) / 2);
    // 마우스가 고른 곳 위에 있으면 그 자리의 단추·카드가 '마우스 올림' 모양으로 바뀌어 장마다 달라진다.
    // 휠을 굴릴 때만 가운데로 옮기고, 찍을 때는 고른 곳 바로 바깥에 둔다.
    let vs = virtual_screen();
    let park = [
        POINT { x: r.right + 6, y: cy },
        POINT { x: r.left - 7, y: cy },
        POINT { x: cx, y: r.bottom + 6 },
        POINT { x: cx, y: r.top - 7 },
    ]
    .into_iter()
    .find(|p| contains(&vs, p.x, p.y))
    .unwrap_or(POINT { x: cx, y: cy });
    // 휠은 마우스 아래 창이 받는다. 그 창을 앞으로 가져와 휠이 확실히 먹게 한다.
    unsafe {
        let target = WindowFromPoint(POINT { x: cx, y: cy });
        if !target.is_null() {
            SetForegroundWindow(GetAncestor(target, GA_ROOT));
        }
        SetCursorPos(park.x, park.y);
    }
    wait(250);
    let first = grab(&r)?;
    let mut stitcher = Stitcher::new(first, w, h);
    let mut shots = 1usize;
    let mut same = 0;
    for _ in 0..SCROLL_MAX_STEPS {
        if esc_down() || badge.as_ref().is_some_and(|b| b.clicked()) {
            break;
        }
        unsafe { SetCursorPos(cx, cy) };
        wait(20);
        wheel_down();
        wait(40);
        unsafe { SetCursorPos(park.x, park.y) };
        let frame = grab_settled(&r)?;
        let result = stitcher.push(frame);
        match result {
            Push::Added(_) => {
                same = 0;
                shots += 1;
                if let Some(b) = badge.as_mut() {
                    b.set("", &text(shots));
                }
            }
            Push::Same => {
                same += 1;
                if same >= 2 {
                    break;
                }
            }
            Push::NoMatch => break,
        }
        if stitcher.height() >= SCROLL_MAX_HEIGHT {
            break;
        }
    }
    unsafe { SetCursorPos(saved.x, saved.y) };
    drop(badge);
    let (ow, oh, out) = stitcher.finish();
    super::encode_png(ow, oh, &out).map(Some)
}

// ── 찍기 ─────────────────────────────────────────────────────────

pub fn capture(mode: Mode, delay: u32) -> Result<Option<Vec<u8>>, String> {
    unsafe { SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) };
    // UI 자동화(브라우저·엑셀 칸 찾기)를 쓰려면 이 스레드에서 COM 을 켠다
    let com = unsafe { windows::Win32::System::Com::CoInitializeEx(None, windows::Win32::System::Com::COINIT_MULTITHREADED) }.is_ok();
    let result = capture_inner(mode, delay);
    if com {
        unsafe { windows::Win32::System::Com::CoUninitialize() };
    }
    result
}

fn capture_inner(mode: Mode, delay: u32) -> Result<Option<Vec<u8>>, String> {
    if delay > 0 && !countdown(delay) {
        return Ok(None);
    }
    match mode {
        Mode::Screen => {
            let list = monitors();
            if list.len() <= 1 {
                let (mon, _) = monitor_at_cursor();
                let shot = grab(&mon)?;
                return super::encode_png(width(&mon) as usize, height(&mon) as usize, &shot).map(Some);
            }
            // 모니터가 둘 이상이면 찍을 모니터를 누르게 한다(마우스가 JB업무ON 단추 위에 있어 그 모니터만 찍히지 않게)
            let vs = virtual_screen();
            let frozen = grab(&vs)?;
            let Some(mon) = select_region(&frozen, &vs, list.into_iter().map(|m| vec![m]).collect(), "찍을 모니터를 누르세요 · Esc 취소", true)? else {
                return Ok(None);
            };
            let local = RECT { left: mon.left - vs.left, top: mon.top - vs.top, right: mon.right - vs.left, bottom: mon.bottom - vs.top };
            let part = crop(&frozen, width(&vs), &local);
            super::encode_png(width(&local) as usize, height(&local) as usize, &part).map(Some)
        }
        Mode::Region | Mode::Scroll => {
            let vs = virtual_screen();
            let windows = visible_windows();
            let frozen = grab(&vs)?;
            let hint = if mode == Mode::Scroll {
                "스크롤할 곳을 끌어서 고르거나 누르세요 · 휠: 넓게·좁게 · Esc 취소"
            } else {
                "끌어서 영역을 고르거나 누르세요(누른 곳의 칸·창) · 휠: 넓게·좁게 · Esc 취소"
            };
            let Some(sel) = select_region(&frozen, &vs, windows, hint, false)? else {
                return Ok(None);
            };
            if mode == Mode::Scroll {
                // 덮개 창이 사라진 진짜 화면에서 굴린다
                wait(150);
                return scroll_capture(sel);
            }
            let local = RECT { left: sel.left - vs.left, top: sel.top - vs.top, right: sel.right - vs.left, bottom: sel.bottom - vs.top };
            let part = crop(&frozen, width(&vs), &local);
            super::encode_png(width(&local) as usize, height(&local) as usize, &part).map(Some)
        }
    }
}

// ── 화면에 고정 ───────────────────────────────────────────────────

struct Pin {
    image: (HDC, HBITMAP, HGDIOBJ),
    iw: i32,
    ih: i32,
    scale: f64,
    png: Vec<u8>,
}

static PIN_CLASS: Once = Once::new();
const PIN_NAME: &str = "JBEduCapturePin";
const PIN_COPY: usize = 1;
const PIN_ACTUAL: usize = 2;
const PIN_CLOSE: usize = 3;

unsafe fn pin_resize(hwnd: HWND, st: &Pin) {
    let w = ((st.iw as f64 * st.scale).round() as i32).max(24);
    let h = ((st.ih as f64 * st.scale).round() as i32).max(24);
    SetWindowPos(hwnd, null_mut(), 0, 0, w, h, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
    InvalidateRect(hwnd, null(), 0);
}

unsafe extern "system" fn pin_proc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut Pin;
    if ptr.is_null() {
        return DefWindowProcW(hwnd, msg, wparam, lparam);
    }
    let st = &mut *ptr;
    match msg {
        WM_PAINT => {
            let mut ps: PAINTSTRUCT = zeroed();
            let hdc = BeginPaint(hwnd, &mut ps);
            let mut rc: RECT = zeroed();
            GetClientRect(hwnd, &mut rc);
            SetStretchBltMode(hdc, HALFTONE);
            SetBrushOrgEx(hdc, 0, 0, null_mut());
            StretchBlt(hdc, 0, 0, rc.right, rc.bottom, st.image.0, 0, 0, st.iw, st.ih, SRCCOPY);
            for edge in [
                RECT { left: 0, top: 0, right: rc.right, bottom: 1 },
                RECT { left: 0, top: rc.bottom - 1, right: rc.right, bottom: rc.bottom },
                RECT { left: 0, top: 0, right: 1, bottom: rc.bottom },
                RECT { left: rc.right - 1, top: 0, right: rc.right, bottom: rc.bottom },
            ] {
                fill(hdc, &edge, ACCENT);
            }
            EndPaint(hwnd, &ps);
            0
        }
        WM_ERASEBKGND => 1,
        // 어디를 잡아도 창이 끌려 옮겨진다
        WM_NCHITTEST => HTCAPTION as LRESULT,
        WM_SETCURSOR => {
            SetCursor(LoadCursorW(null_mut(), IDC_SIZEALL));
            1
        }
        WM_NCLBUTTONDBLCLK => {
            DestroyWindow(hwnd);
            0
        }
        WM_MOUSEWHEEL => {
            let delta = ((wparam >> 16) & 0xFFFF) as u16 as i16 as f64 / 120.0;
            st.scale = (st.scale * 1.1f64.powf(delta)).clamp(0.1, 4.0);
            pin_resize(hwnd, st);
            0
        }
        WM_KEYDOWN if wparam == VK_ESCAPE as usize => {
            DestroyWindow(hwnd);
            0
        }
        WM_NCRBUTTONUP => {
            let menu = CreatePopupMenu();
            let items = [(PIN_COPY, "그림 복사"), (PIN_ACTUAL, "원래 크기"), (0, ""), (PIN_CLOSE, "닫기")];
            let labels: Vec<Vec<u16>> = items.iter().map(|(_, t)| wide(t)).collect();
            for ((id, _), label) in items.iter().zip(&labels) {
                if *id == 0 {
                    AppendMenuW(menu, MF_SEPARATOR, 0, null());
                } else {
                    AppendMenuW(menu, MF_STRING, *id, label.as_ptr());
                }
            }
            SetForegroundWindow(hwnd);
            let cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, lo(lparam), hi(lparam), 0, hwnd, null()) as usize;
            DestroyMenu(menu);
            match cmd {
                PIN_COPY => {
                    let _ = crate::clipboard_image::write_png_to_clipboard(&st.png);
                }
                PIN_ACTUAL => {
                    st.scale = 1.0;
                    pin_resize(hwnd, st);
                }
                PIN_CLOSE => {
                    DestroyWindow(hwnd);
                }
                _ => {}
            }
            0
        }
        WM_DESTROY => {
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
            let st = Box::from_raw(ptr);
            free_dc(st.image);
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

pub fn pin(png_bytes: Vec<u8>) -> Result<(), String> {
    let (iw, ih, bgra) = super::decode_png_bgra(&png_bytes)?;
    let (tx, rx) = std::sync::mpsc::channel::<Result<(), String>>();
    std::thread::Builder::new()
        .name("screen-pin".into())
        .spawn(move || unsafe {
            SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
            register_class(&PIN_CLASS, PIN_NAME, pin_proc, CS_DBLCLKS | CS_DROPSHADOW);
            let (iw, ih) = (iw as i32, ih as i32);
            let Some(image) = dib_dc(iw, ih, &bgra) else {
                let _ = tx.send(Err("그림이 너무 커서 고정하지 못했습니다.".to_string()));
                return;
            };
            drop(bgra);
            let (_, work) = monitor_at_cursor();
            // 모니터 작업 영역의 80% 안에 들어오게 줄인다(키우지는 않는다)
            let fit = (width(&work) as f64 * 0.8 / iw as f64).min(height(&work) as f64 * 0.8 / ih as f64).min(1.0);
            let (w, h) = (((iw as f64) * fit).round() as i32, ((ih as f64) * fit).round() as i32);
            let class = wide(PIN_NAME);
            let title = wide("화면에 고정");
            let hwnd = CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
                class.as_ptr(),
                title.as_ptr(),
                WS_POPUP,
                work.left + (width(&work) - w) / 2,
                work.top + (height(&work) - h) / 2,
                w.max(24),
                h.max(24),
                null_mut(),
                null_mut(),
                GetModuleHandleW(null()),
                null(),
            );
            if hwnd.is_null() {
                free_dc(image);
                let _ = tx.send(Err("고정 창을 만들지 못했습니다.".to_string()));
                return;
            }
            let st = Box::new(Pin { image, iw, ih, scale: fit, png: png_bytes });
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, Box::into_raw(st) as isize);
            ShowWindow(hwnd, SW_SHOW);
            SetForegroundWindow(hwnd);
            let _ = tx.send(Ok(()));
            let mut msg: MSG = zeroed();
            while GetMessageW(&mut msg, null_mut(), 0, 0) > 0 {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
        })
        .map_err(|e| format!("고정 창을 만들지 못했습니다: {e}"))?;
    rx.recv().map_err(|_| "고정 창을 만들지 못했습니다.".to_string())?
}
