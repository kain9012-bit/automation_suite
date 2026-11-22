//! PC 정보(1.5.2): 사이드바 'PC 정보' 화면이 보여 줄 이 컴퓨터의 사양을 읽는다.
//!
//! PC 에 부담을 주지 않도록 정한 것
//! - 화면을 열 때와 [다시 읽기]를 누를 때 한 번만 읽는다. 감시하거나 뒤에서 계속 돌지 않는다.
//! - WMI·PowerShell 같은 다른 프로그램을 띄우지 않고, 레지스트리와 Windows 기본 함수만 바로 부른다.
//! - 네트워크 드라이브는 끊겨 있으면 오래 기다릴 수 있어 용량을 읽지 않는다(연결 이름만 읽음).
//! - 관리자 권한이 필요한 것(온도·디스크 수명 등)은 읽지 않는다.
//!
//! 읽은 값은 화면에 보여 주고 [전체 복사] 때 클립보드에 넣을 뿐, PC 밖으로 보내지 않는다.

use serde::Serialize;

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PcInfo {
    /// 제조사·모델명. 값이 비었거나 "To Be Filled By O.E.M." 같은 자리 채움 글이면 None.
    pub manufacturer: Option<String>,
    pub model: Option<String>,
    pub computer_name: Option<String>,
    pub windows: WindowsInfo,
    /// Windows 가 켜진 뒤 지난 시간(초). 작업 관리자의 '작동 시간'과 같은 값.
    pub uptime_secs: u64,
    pub cpu: CpuInfo,
    pub memory: MemoryInfo,
    pub drives: Vec<DriveInfo>,
    pub gpus: Vec<String>,
    pub displays: Vec<DisplayInfo>,
    pub adapters: Vec<AdapterInfo>,
    /// 읽는 데 걸린 시간(밀리초)
    pub elapsed_ms: u64,
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WindowsInfo {
    /// 예: "Windows 11 Pro"
    pub name: Option<String>,
    /// 예: "24H2"
    pub version: Option<String>,
    /// 예: "26100.4061"
    pub build: Option<String>,
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CpuInfo {
    pub name: Option<String>,
    pub cores: Option<u32>,
    pub threads: Option<u32>,
}

#[derive(Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryInfo {
    /// 꽂혀 있는 메모리(바이트). 못 읽으면 Windows 가 쓸 수 있는 메모리.
    pub installed: Option<u64>,
    /// Windows 가 쓸 수 있는 메모리(바이트)
    pub usable: Option<u64>,
    /// 사용 중(바이트) = 쓸 수 있는 메모리 - 남은 메모리
    pub used: Option<u64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DriveInfo {
    /// 예: "C:"
    pub letter: String,
    /// "fixed"(내장·외장 디스크) | "removable"(USB 메모리 등) | "network"
    pub kind: &'static str,
    /// 볼륨 이름. 네트워크 드라이브는 연결된 주소(예: \\server\share)
    pub label: Option<String>,
    pub total: Option<u64>,
    pub free: Option<u64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DisplayInfo {
    pub width: u32,
    pub height: u32,
    /// 배율(%). 못 읽으면 None
    pub scale: Option<u32>,
    pub primary: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AdapterInfo {
    /// 예: "이더넷", "Wi-Fi" (네트워크 연결 창에 보이는 이름)
    pub name: String,
    pub ipv4: Vec<String>,
    pub mac: Option<String>,
}

/// 제조사가 값을 채우지 않았을 때 BIOS 에 남는 자리 채움 글
const PLACEHOLDERS: [&str; 12] = [
    "to be filled by o.e.m.",
    "to be filled by oem",
    "system manufacturer",
    "system product name",
    "system version",
    "default string",
    "o.e.m.",
    "oem",
    "not applicable",
    "none",
    "not specified",
    "invalid",
];

/// 앞뒤 공백을 지우고, 비었거나 자리 채움 글이면 None
pub fn clean(value: Option<String>) -> Option<String> {
    let v = value?.trim().trim_matches('\0').trim().to_string();
    if v.is_empty() || PLACEHOLDERS.contains(&v.to_lowercase().as_str()) {
        None
    } else {
        Some(v)
    }
}

/// 레노버는 SystemProductName 에 기계 유형 번호(예: 20UES0J100)를, SystemVersion 에 제품 이름(예: ThinkPad E14 Gen 2)을 둔다.
pub fn model_name(manufacturer: Option<&str>, product: Option<String>, version: Option<String>) -> Option<String> {
    let is_lenovo = manufacturer.is_some_and(|m| m.to_lowercase().contains("lenovo"));
    match (is_lenovo, product, version) {
        (true, Some(p), Some(v)) if !v.eq_ignore_ascii_case(&p) => Some(format!("{v} ({p})")),
        (_, Some(p), _) => Some(p),
        (true, None, Some(v)) => Some(v),
        _ => None,
    }
}

/// 레지스트리의 제품 이름은 Windows 11 에서도 "Windows 10 …"으로 남아 있어 빌드 번호(22000 이상 = 11)로 고친다.
pub fn windows_name(product: Option<String>, build: Option<u32>) -> Option<String> {
    let p = product?;
    if build.is_some_and(|b| b >= 22000) && p.starts_with("Windows 10") {
        Some(p.replacen("Windows 10", "Windows 11", 1))
    } else {
        Some(p)
    }
}

pub fn format_mac(bytes: &[u8]) -> Option<String> {
    if bytes.is_empty() || bytes.iter().all(|b| *b == 0) {
        return None;
    }
    Some(bytes.iter().map(|b| format!("{b:02X}")).collect::<Vec<_>>().join("-"))
}

#[cfg(windows)]
pub fn read() -> PcInfo {
    let started = std::time::Instant::now();
    let mut info = PcInfo::default();
    win::read_system(&mut info);
    info.cpu = win::read_cpu();
    info.memory = win::read_memory();
    info.drives = win::read_drives();
    info.gpus = win::read_gpus();
    info.displays = win::read_displays();
    info.adapters = win::read_adapters();
    info.elapsed_ms = started.elapsed().as_millis() as u64;
    info
}

#[cfg(not(windows))]
pub fn read() -> PcInfo {
    PcInfo::default()
}

/// [전체 복사]: 글(유니코드)을 클립보드에 넣는다.
#[cfg(windows)]
pub fn copy_text(text: &str) -> Result<(), String> {
    win::copy_text(text)
}

#[cfg(not(windows))]
pub fn copy_text(_text: &str) -> Result<(), String> {
    Err("복사는 Windows 에서만 됩니다.".to_string())
}

#[cfg(windows)]
mod win {
    use super::*;
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::{ERROR_BUFFER_OVERFLOW, ERROR_SUCCESS, RECT, LPARAM};
    use windows_sys::Win32::System::Registry::{RegGetValueW, HKEY_LOCAL_MACHINE, RRF_RT_REG_DWORD, RRF_RT_REG_SZ};

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    fn from_wide(buf: &[u16]) -> String {
        let end = buf.iter().position(|c| *c == 0).unwrap_or(buf.len());
        String::from_utf16_lossy(&buf[..end])
    }

    unsafe fn from_pwstr(p: *const u16) -> Option<String> {
        if p.is_null() {
            return None;
        }
        let mut len = 0;
        while *p.add(len) != 0 {
            len += 1;
        }
        Some(String::from_utf16_lossy(std::slice::from_raw_parts(p, len)))
    }

    /// HKLM 아래 문자열 값
    fn reg_str(subkey: &str, value: &str) -> Option<String> {
        let (k, v) = (wide(subkey), wide(value));
        let mut size: u32 = 0;
        unsafe {
            if RegGetValueW(HKEY_LOCAL_MACHINE, k.as_ptr(), v.as_ptr(), RRF_RT_REG_SZ, null_mut(), null_mut(), &mut size) != ERROR_SUCCESS || size == 0 {
                return None;
            }
            let mut buf = vec![0u16; (size as usize).div_ceil(2) + 1];
            let mut bytes = (buf.len() * 2) as u32;
            if RegGetValueW(HKEY_LOCAL_MACHINE, k.as_ptr(), v.as_ptr(), RRF_RT_REG_SZ, null_mut(), buf.as_mut_ptr().cast(), &mut bytes) != ERROR_SUCCESS {
                return None;
            }
            Some(from_wide(&buf))
        }
    }

    fn reg_dword(subkey: &str, value: &str) -> Option<u32> {
        let (k, v) = (wide(subkey), wide(value));
        let mut data: u32 = 0;
        let mut size: u32 = 4;
        let ok = unsafe {
            RegGetValueW(HKEY_LOCAL_MACHINE, k.as_ptr(), v.as_ptr(), RRF_RT_REG_DWORD, null_mut(), (&mut data as *mut u32).cast(), &mut size)
        };
        (ok == ERROR_SUCCESS).then_some(data)
    }

    /// 제조사·모델명, 컴퓨터 이름, Windows 판·버전·빌드, 켜진 시간
    pub fn read_system(info: &mut PcInfo) {
        use windows_sys::Win32::System::SystemInformation::{ComputerNameDnsHostname, GetComputerNameExW, GetTickCount64};

        const BIOS: &str = r"HARDWARE\DESCRIPTION\System\BIOS";
        info.manufacturer = clean(reg_str(BIOS, "SystemManufacturer"));
        info.model = model_name(
            info.manufacturer.as_deref(),
            clean(reg_str(BIOS, "SystemProductName")),
            clean(reg_str(BIOS, "SystemVersion")),
        );

        let mut buf = [0u16; 256];
        let mut len = buf.len() as u32;
        if unsafe { GetComputerNameExW(ComputerNameDnsHostname, buf.as_mut_ptr(), &mut len) } != 0 {
            info.computer_name = clean(Some(from_wide(&buf[..len as usize])));
        }

        const CV: &str = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion";
        let build_no = reg_str(CV, "CurrentBuildNumber").and_then(|b| b.trim().parse::<u32>().ok());
        info.windows.name = windows_name(clean(reg_str(CV, "ProductName")), build_no);
        // DisplayVersion(예: 24H2)은 Windows 10 20H2 부터 있다. 그 전에는 ReleaseId(예: 1909).
        info.windows.version = clean(reg_str(CV, "DisplayVersion")).or_else(|| clean(reg_str(CV, "ReleaseId")));
        info.windows.build = build_no.map(|b| match reg_dword(CV, "UBR") {
            Some(ubr) => format!("{b}.{ubr}"),
            None => b.to_string(),
        });

        info.uptime_secs = unsafe { GetTickCount64() } / 1000;
    }

    pub fn read_cpu() -> CpuInfo {
        use windows_sys::Win32::System::SystemInformation::{
            GetLogicalProcessorInformationEx, RelationProcessorCore, SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX,
        };
        let mut cpu = CpuInfo {
            name: clean(reg_str(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")),
            ..Default::default()
        };
        unsafe {
            let mut len: u32 = 0;
            GetLogicalProcessorInformationEx(RelationProcessorCore, null_mut(), &mut len);
            if len == 0 {
                return cpu;
            }
            // 구조체 맞춤(8바이트)을 지키려고 u64 칸으로 잡는다.
            let mut buf = vec![0u64; (len as usize).div_ceil(8)];
            if GetLogicalProcessorInformationEx(RelationProcessorCore, buf.as_mut_ptr().cast(), &mut len) == 0 {
                return cpu;
            }
            let base = buf.as_ptr() as *const u8;
            let (mut offset, mut cores, mut threads) = (0usize, 0u32, 0u32);
            while offset < len as usize {
                let item = &*(base.add(offset) as *const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX);
                if item.Size == 0 {
                    break;
                }
                if item.Relationship == RelationProcessorCore {
                    cores += 1;
                    let p = &item.Anonymous.Processor;
                    let masks = std::slice::from_raw_parts(p.GroupMask.as_ptr(), p.GroupCount.max(1) as usize);
                    threads += masks.iter().map(|g| g.Mask.count_ones()).sum::<u32>();
                }
                offset += item.Size as usize;
            }
            if cores > 0 {
                cpu.cores = Some(cores);
                cpu.threads = Some(threads.max(cores));
            }
        }
        cpu
    }

    pub fn read_memory() -> MemoryInfo {
        use windows_sys::Win32::System::SystemInformation::{GetPhysicallyInstalledSystemMemory, GlobalMemoryStatusEx, MEMORYSTATUSEX};
        let mut mem = MemoryInfo::default();
        unsafe {
            let mut status: MEMORYSTATUSEX = std::mem::zeroed();
            status.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
            if GlobalMemoryStatusEx(&mut status) != 0 {
                mem.usable = Some(status.ullTotalPhys);
                mem.used = Some(status.ullTotalPhys.saturating_sub(status.ullAvailPhys));
            }
            let mut kb: u64 = 0;
            mem.installed = if GetPhysicallyInstalledSystemMemory(&mut kb) != 0 && kb > 0 {
                Some(kb * 1024)
            } else {
                mem.usable
            };
        }
        mem
    }

    pub fn read_drives() -> Vec<DriveInfo> {
        use windows_sys::Win32::NetworkManagement::WNet::WNetGetConnectionW;
        use windows_sys::Win32::Storage::FileSystem::{GetDiskFreeSpaceExW, GetDriveTypeW, GetLogicalDrives, GetVolumeInformationW};
        use windows_sys::Win32::System::Diagnostics::Debug::{SetThreadErrorMode, SEM_FAILCRITICALERRORS};
        const DRIVE_REMOVABLE: u32 = 2;
        const DRIVE_FIXED: u32 = 3;
        const DRIVE_REMOTE: u32 = 4;

        let mut drives = Vec::new();
        unsafe {
            // 빈 카드 리더 같은 드라이브에서 "디스크를 넣으세요" 창이 뜨지 않게 한다(이 스레드에서만).
            let mut old_mode = 0;
            SetThreadErrorMode(SEM_FAILCRITICALERRORS, &mut old_mode);
            let mask = GetLogicalDrives();
            for i in 0..26u32 {
                if mask & (1 << i) == 0 {
                    continue;
                }
                let letter = format!("{}:", (b'A' + i as u8) as char);
                let root = wide(&format!("{letter}\\"));
                let drive_type = GetDriveTypeW(root.as_ptr());
                match drive_type {
                    DRIVE_FIXED | DRIVE_REMOVABLE => {
                        let kind = if drive_type == DRIVE_FIXED { "fixed" } else { "removable" };
                        let (mut avail, mut total, mut free) = (0u64, 0u64, 0u64);
                        // 꽂힌 매체가 없는 드라이브(빈 카드 리더)는 건너뛴다.
                        if GetDiskFreeSpaceExW(root.as_ptr(), &mut avail, &mut total, &mut free) == 0 || total == 0 {
                            continue;
                        }
                        let mut name = [0u16; 261];
                        let label = if GetVolumeInformationW(root.as_ptr(), name.as_mut_ptr(), name.len() as u32, null_mut(), null_mut(), null_mut(), null_mut(), 0) != 0 {
                            clean(Some(from_wide(&name)))
                        } else {
                            None
                        };
                        drives.push(DriveInfo { letter, kind, label, total: Some(total), free: Some(free) });
                    }
                    DRIVE_REMOTE => {
                        // 연결해 둔 주소만 읽는다(서버에 묻지 않음). 용량은 읽지 않는다.
                        let local = wide(&letter);
                        let mut remote = [0u16; 1024];
                        let mut len = remote.len() as u32;
                        let r = WNetGetConnectionW(local.as_ptr(), remote.as_mut_ptr(), &mut len);
                        // 2250(ERROR_NOT_CONNECTED) 외에 끊긴 연결(1201)도 주소는 채워 준다.
                        let label = if r == ERROR_SUCCESS || remote[0] != 0 { clean(Some(from_wide(&remote))) } else { None };
                        drives.push(DriveInfo { letter, kind: "network", label, total: None, free: None });
                    }
                    _ => {} // CD·DVD 등은 읽지 않는다(빈 드라이브를 돌리지 않게).
                }
            }
            SetThreadErrorMode(old_mode, null_mut());
        }
        drives
    }

    /// 장치 관리자의 '디스플레이 어댑터'와 같은 목록(지금 연결된 장치만)
    pub fn read_gpus() -> Vec<String> {
        use windows_sys::Win32::Devices::DeviceAndDriverInstallation::{
            SetupDiDestroyDeviceInfoList, SetupDiEnumDeviceInfo, SetupDiGetClassDevsW, SetupDiGetDeviceRegistryPropertyW, DIGCF_PRESENT,
            GUID_DEVCLASS_DISPLAY, SPDRP_DEVICEDESC, SPDRP_FRIENDLYNAME, SP_DEVINFO_DATA,
        };
        let mut names: Vec<String> = Vec::new();
        unsafe {
            let set = SetupDiGetClassDevsW(&GUID_DEVCLASS_DISPLAY, null(), null_mut(), DIGCF_PRESENT);
            if set == -1 {
                return names;
            }
            let mut index = 0;
            loop {
                let mut data: SP_DEVINFO_DATA = std::mem::zeroed();
                data.cbSize = std::mem::size_of::<SP_DEVINFO_DATA>() as u32;
                if SetupDiEnumDeviceInfo(set, index, &mut data) == 0 {
                    break;
                }
                index += 1;
                let prop = |id| {
                    let mut buf = [0u16; 512];
                    let ok = SetupDiGetDeviceRegistryPropertyW(set, &data, id, null_mut(), buf.as_mut_ptr().cast(), (buf.len() * 2) as u32, null_mut());
                    if ok != 0 { clean(Some(from_wide(&buf))) } else { None }
                };
                if let Some(name) = prop(SPDRP_FRIENDLYNAME).or_else(|| prop(SPDRP_DEVICEDESC)) {
                    if !names.contains(&name) {
                        names.push(name);
                    }
                }
                if index > 32 {
                    break;
                }
            }
            SetupDiDestroyDeviceInfoList(set);
        }
        names
    }

    pub fn read_displays() -> Vec<DisplayInfo> {
        use windows_sys::Win32::Graphics::Gdi::{
            EnumDisplayMonitors, EnumDisplaySettingsW, GetMonitorInfoW, DEVMODEW, ENUM_CURRENT_SETTINGS, HDC, HMONITOR, MONITORINFOEXW,
        };
        use windows_sys::Win32::UI::HiDpi::{GetDpiForMonitor, SetThreadDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, MDT_EFFECTIVE_DPI};
        use windows_sys::Win32::UI::WindowsAndMessaging::MONITORINFOF_PRIMARY;

        unsafe extern "system" fn collect(monitor: HMONITOR, _: HDC, _: *mut RECT, data: LPARAM) -> windows_sys::core::BOOL {
            let list = &mut *(data as *mut Vec<HMONITOR>);
            list.push(monitor);
            1
        }

        let mut out = Vec::new();
        unsafe {
            // 배율을 실제 값으로 받으려고 이 스레드만 '모니터별 DPI 인식'으로 두었다가 되돌린다.
            let previous = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
            let mut monitors: Vec<HMONITOR> = Vec::new();
            EnumDisplayMonitors(null_mut(), null(), Some(collect), &mut monitors as *mut Vec<HMONITOR> as LPARAM);
            for monitor in monitors {
                let mut mi: MONITORINFOEXW = std::mem::zeroed();
                mi.monitorInfo.cbSize = std::mem::size_of::<MONITORINFOEXW>() as u32;
                if GetMonitorInfoW(monitor, &mut mi as *mut MONITORINFOEXW as *mut _) == 0 {
                    continue;
                }
                let mut dm: DEVMODEW = std::mem::zeroed();
                dm.dmSize = std::mem::size_of::<DEVMODEW>() as u16;
                let (width, height) = if EnumDisplaySettingsW(mi.szDevice.as_ptr(), ENUM_CURRENT_SETTINGS, &mut dm) != 0 {
                    (dm.dmPelsWidth, dm.dmPelsHeight)
                } else {
                    let r = mi.monitorInfo.rcMonitor;
                    ((r.right - r.left).max(0) as u32, (r.bottom - r.top).max(0) as u32)
                };
                let (mut dx, mut dy) = (0u32, 0u32);
                let scale = (GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &mut dx, &mut dy) == 0 && dx > 0).then(|| (dx * 100 + 48) / 96);
                out.push(DisplayInfo { width, height, scale, primary: mi.monitorInfo.dwFlags & MONITORINFOF_PRIMARY != 0 });
            }
            if !previous.is_null() {
                SetThreadDpiAwarenessContext(previous);
            }
        }
        // 기본 화면을 맨 앞에
        out.sort_by_key(|d| !d.primary);
        out
    }

    /// 지금 연결된 네트워크(켜져 있는 어댑터)의 IPv4 주소와 MAC 주소
    pub fn read_adapters() -> Vec<AdapterInfo> {
        use windows_sys::Win32::NetworkManagement::IpHelper::{
            GetAdaptersAddresses, GAA_FLAG_SKIP_ANYCAST, GAA_FLAG_SKIP_DNS_SERVER, GAA_FLAG_SKIP_MULTICAST, IF_TYPE_SOFTWARE_LOOPBACK,
            IF_TYPE_TUNNEL, IP_ADAPTER_ADDRESSES_LH,
        };
        use windows_sys::Win32::NetworkManagement::Ndis::IfOperStatusUp;
        use windows_sys::Win32::Networking::WinSock::{AF_INET, SOCKADDR_IN};

        let flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER;
        let mut out = Vec::new();
        unsafe {
            let mut size: u32 = 16 * 1024;
            let mut buf: Vec<u64> = Vec::new();
            let mut result = ERROR_BUFFER_OVERFLOW;
            for _ in 0..3 {
                buf = vec![0u64; (size as usize).div_ceil(8)];
                result = GetAdaptersAddresses(AF_INET as u32, flags, null(), buf.as_mut_ptr().cast(), &mut size);
                if result != ERROR_BUFFER_OVERFLOW {
                    break;
                }
            }
            if result != ERROR_SUCCESS {
                return out;
            }
            let mut p = buf.as_ptr() as *const IP_ADAPTER_ADDRESSES_LH;
            while !p.is_null() {
                let a = &*p;
                p = a.Next;
                if a.OperStatus != IfOperStatusUp || a.IfType == IF_TYPE_SOFTWARE_LOOPBACK || a.IfType == IF_TYPE_TUNNEL {
                    continue;
                }
                let mut ipv4 = Vec::new();
                let mut u = a.FirstUnicastAddress;
                while !u.is_null() {
                    let sa = (*u).Address.lpSockaddr;
                    if !sa.is_null() && (*sa).sa_family == AF_INET {
                        let b = (*(sa as *const SOCKADDR_IN)).sin_addr.S_un.S_addr.to_ne_bytes();
                        ipv4.push(format!("{}.{}.{}.{}", b[0], b[1], b[2], b[3]));
                    }
                    u = (*u).Next;
                }
                if ipv4.is_empty() {
                    continue;
                }
                let len = (a.PhysicalAddressLength as usize).min(8);
                let name = from_pwstr(a.FriendlyName).or_else(|| from_pwstr(a.Description)).unwrap_or_default();
                out.push(AdapterInfo { name, ipv4, mac: format_mac(&a.PhysicalAddress[..len]) });
            }
        }
        out
    }

    pub fn copy_text(text: &str) -> Result<(), String> {
        use windows_sys::Win32::Foundation::GlobalFree;
        use windows_sys::Win32::System::DataExchange::{CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData};
        use windows_sys::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE};
        const CF_UNICODETEXT: u32 = 13;

        // 메모장·한글 등에 붙였을 때 줄이 바뀌도록 CRLF 로 넣는다.
        let data: Vec<u16> = text.replace("\r\n", "\n").replace('\n', "\r\n").encode_utf16().chain(std::iter::once(0)).collect();
        // 다른 프로그램이 클립보드를 잠깐 쥐고 있을 수 있어 몇 번 다시 해 본다.
        let mut opened = false;
        for _ in 0..10 {
            if unsafe { OpenClipboard(null_mut()) } != 0 {
                opened = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(30));
        }
        if !opened {
            return Err("다른 프로그램이 클립보드를 쓰고 있습니다. 잠시 뒤 다시 누르세요.".to_string());
        }
        let result = unsafe {
            if EmptyClipboard() == 0 {
                Err("클립보드를 비우지 못했습니다.".to_string())
            } else {
                let bytes = data.len() * 2;
                let mem = GlobalAlloc(GMEM_MOVEABLE, bytes);
                let ptr = if mem.is_null() { null_mut() } else { GlobalLock(mem) as *mut u16 };
                if ptr.is_null() {
                    if !mem.is_null() {
                        GlobalFree(mem);
                    }
                    Err("클립보드에 넣을 자리를 만들지 못했습니다.".to_string())
                } else {
                    std::ptr::copy_nonoverlapping(data.as_ptr(), ptr, data.len());
                    GlobalUnlock(mem);
                    if SetClipboardData(CF_UNICODETEXT, mem as _).is_null() {
                        GlobalFree(mem);
                        Err("클립보드에 넣지 못했습니다.".to_string())
                    } else {
                        Ok(()) // 성공하면 그 메모리는 클립보드 것이 된다(놓지 않는다)
                    }
                }
            }
        };
        unsafe { CloseClipboard() };
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn placeholders_are_dropped() {
        assert_eq!(clean(Some("To Be Filled By O.E.M.".into())), None);
        assert_eq!(clean(Some("  System manufacturer ".into())), None);
        assert_eq!(clean(Some("Default string".into())), None);
        assert_eq!(clean(Some("".into())), None);
        assert_eq!(clean(Some(" SAMSUNG ELECTRONICS CO., LTD. ".into())).as_deref(), Some("SAMSUNG ELECTRONICS CO., LTD."));
    }

    #[test]
    fn lenovo_model_uses_version() {
        assert_eq!(model_name(Some("LENOVO"), Some("20UES0J100".into()), Some("ThinkPad E14 Gen 2".into())).as_deref(), Some("ThinkPad E14 Gen 2 (20UES0J100)"));
        assert_eq!(model_name(Some("Samsung"), Some("NT750XGR".into()), Some("P07RGR".into())).as_deref(), Some("NT750XGR"));
        assert_eq!(model_name(Some("LENOVO"), None, Some("ThinkCentre M70q".into())).as_deref(), Some("ThinkCentre M70q"));
    }

    #[test]
    fn windows_11_from_build() {
        assert_eq!(windows_name(Some("Windows 10 Pro".into()), Some(26100)).as_deref(), Some("Windows 11 Pro"));
        assert_eq!(windows_name(Some("Windows 10 Pro".into()), Some(19045)).as_deref(), Some("Windows 10 Pro"));
    }

    #[test]
    fn mac_format() {
        assert_eq!(format_mac(&[0x3c, 0x52, 0x82, 0x1a, 0x7f, 0x0d]).as_deref(), Some("3C-52-82-1A-7F-0D"));
        assert_eq!(format_mac(&[]), None);
        assert_eq!(format_mac(&[0, 0, 0, 0, 0, 0]), None);
    }
}
