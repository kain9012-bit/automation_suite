use serde::{Deserialize, Serialize};
use std::{fs, process::Command, sync::{atomic::{AtomicBool, Ordering}, Mutex}};
use tauri::{menu::{Menu, MenuItem}, tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent}, App, AppHandle, Emitter, Manager, State, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const RUN_KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";
const RUN_VALUE: &str = "JBEduAutomationSuite";

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct AppPreferences {
    #[serde(default)] pub auto_start: bool,
    #[serde(default = "enabled")] pub close_to_tray: bool,
    #[serde(default = "enabled")] pub minimize_to_tray: bool,
    #[serde(default = "enabled")] pub start_minimized: bool,
    /// 앱 창을 보였다 숨겼다 하는 전역 단축키.
    #[serde(default = "default_toggle_hotkey")] pub toggle_hotkey: String,
}

fn enabled() -> bool { true }

fn default_toggle_hotkey() -> String { "Ctrl+Alt+J".to_string() }

impl Default for AppPreferences {
    fn default() -> Self {
        Self {
            auto_start: true,
            close_to_tray: true,
            minimize_to_tray: true,
            start_minimized: true,
            toggle_hotkey: default_toggle_hotkey(),
        }
    }
}

pub struct RuntimeState {
    pub preferences: Mutex<AppPreferences>,
    pub quitting: AtomicBool,
}

impl RuntimeState {
    fn new(preferences: AppPreferences) -> Self {
        Self { preferences: Mutex::new(preferences), quitting: AtomicBool::new(false) }
    }
}

fn preferences_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app.path().app_config_dir().map_err(|error| format!("설정 폴더를 찾지 못했습니다: {error}"))?;
    fs::create_dir_all(&dir).map_err(|error| format!("설정 폴더를 만들지 못했습니다: {error}"))?;
    Ok(dir.join("desktop-preferences.json"))
}

fn load_preferences(app: &AppHandle) -> AppPreferences {
    preferences_path(app).ok().and_then(|path| fs::read_to_string(path).ok()).and_then(|raw| serde_json::from_str(&raw).ok()).unwrap_or_default()
}

fn save_preferences(app: &AppHandle, preferences: &AppPreferences) -> Result<(), String> {
    let raw = serde_json::to_string_pretty(preferences).map_err(|error| format!("설정을 저장하지 못했습니다: {error}"))?;
    fs::write(preferences_path(app)?, raw).map_err(|error| format!("설정을 저장하지 못했습니다: {error}"))
}

fn hidden_command(program: &str) -> Command {
    let mut command = Command::new(program);
    #[cfg(windows)] command.creation_flags(0x08000000);
    command
}

fn auto_start_enabled() -> bool {
    hidden_command("reg").args(["query", RUN_KEY, "/v", RUN_VALUE]).output().map(|output| output.status.success()).unwrap_or(false)
}

fn set_auto_start(enabled: bool) -> Result<(), String> {
    let status = if enabled {
        let exe = std::env::current_exe().map_err(|error| format!("실행 파일 경로를 찾지 못했습니다: {error}"))?;
        let target = format!("\"{}\" --tray", exe.display());
        hidden_command("reg").args(["add", RUN_KEY, "/v", RUN_VALUE, "/t", "REG_SZ", "/d", &target, "/f"]).status()
    } else {
        hidden_command("reg").args(["delete", RUN_KEY, "/v", RUN_VALUE, "/f"]).status()
    }.map_err(|error| format!("Windows 자동 시작 설정을 변경하지 못했습니다: {error}"))?;
    if enabled && !status.success() { return Err("Windows 자동 시작 등록에 실패했습니다.".to_string()); }
    Ok(())
}

#[tauri::command]
pub fn get_app_preferences(state: State<'_, RuntimeState>) -> Result<AppPreferences, String> {
    let mut preferences = state.preferences.lock().map_err(|_| "설정 잠금을 열지 못했습니다.".to_string())?.clone();
    preferences.auto_start = auto_start_enabled();
    Ok(preferences)
}

#[tauri::command]
pub fn set_app_preferences(app: AppHandle, state: State<'_, RuntimeState>, preferences: AppPreferences) -> Result<AppPreferences, String> {
    set_auto_start(preferences.auto_start)?;
    save_preferences(&app, &preferences)?;
    *state.preferences.lock().map_err(|_| "설정 잠금을 열지 못했습니다.".to_string())? = preferences.clone();
    Ok(preferences)
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus();
    }
}

/// 두 번째 인스턴스가 실행됐을 때 기존 창을 다시 띄운다.
pub fn focus_main_window(app: &AppHandle) {
    show_main_window(app);
}

pub fn setup_desktop(app: &mut App) -> Result<(), Box<dyn std::error::Error>> {
    // 설정 파일이 아직 없으면 이 컴퓨터에서 처음 실행하는 것이다.
    let first_run = preferences_path(app.handle()).map(|path| !path.is_file()).unwrap_or(false);
    let preferences = load_preferences(app.handle());

    // 자동 시작은 설정값이 아니라 레지스트리가 실제 상태다. 처음 실행일 때만
    // 기본값대로 등록해 둔다. 꺼 두신 분의 설정을 다시 켜지 않기 위해서다.
    // 개발 빌드가 사용자의 자동 시작을 건드리지 않도록 여기서도 막는다.
    if first_run && preferences.auto_start && !cfg!(debug_assertions) {
        let _ = set_auto_start(true);
        let _ = save_preferences(app.handle(), &preferences);
    }

    // 자동 시작이 켜져 있으면 지금 실행 파일 경로로 다시 써 둔다.
    // 설치 위치나 프로그램 이름이 바뀌면 등록된 경로가 옛 것을 가리켜, 로그인할 때
    // 지금 깔린 것이 아니라 예전 프로그램이 뜬다. 값을 읽어 비교하려 해도 reg 출력이
    // 콘솔 코드 페이지라 한글이 섞인 경로가 깨진다. 그래서 조건 없이 덮어쓴다.
    //
    // 개발 빌드는 제외한다. 개발용으로 한 번 띄울 때마다 사용자의 자동 시작이
    // target\debug 의 실행 파일로 바뀌어, 로그인하면 설치본이 아니라 개발 빌드가 뜬다.
    if !first_run && !cfg!(debug_assertions) && auto_start_enabled() {
        let _ = set_auto_start(true);
    }

    app.manage(RuntimeState::new(preferences.clone()));
    let show_item = MenuItem::with_id(app, "show", "열기", true, None::<&str>)?;
    let settings_item = MenuItem::with_id(app, "settings", "설정", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "완전히 종료", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &settings_item, &quit_item])?;
    let mut tray = TrayIconBuilder::with_id("main-tray").menu(&menu).show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main_window(app),
            "settings" => { show_main_window(app); let _ = app.emit("open-settings", ()); }
            "quit" => { app.state::<RuntimeState>().quitting.store(true, Ordering::SeqCst); app.exit(0); }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event { show_main_window(tray.app_handle()); }
        });
    if let Some(icon) = app.default_window_icon() { tray = tray.icon(icon.clone()); }
    tray.build(app)?;
    if std::env::args().any(|arg| arg == "--tray") && preferences.start_minimized {
        if let Some(window) = app.get_webview_window("main") { let _ = window.hide(); }
    }
    Ok(())
}

pub fn handle_window_event(window: &tauri::Window, event: &WindowEvent) {
    let state = window.state::<RuntimeState>();
    let preferences = state.preferences.lock().ok().map(|value| value.clone()).unwrap_or_default();
    match event {
        WindowEvent::CloseRequested { api, .. } if !state.quitting.load(Ordering::SeqCst) && preferences.close_to_tray => { api.prevent_close(); let _ = window.hide(); }
        WindowEvent::Resized(_) if preferences.minimize_to_tray => { if window.is_minimized().unwrap_or(false) { let _ = window.hide(); } }
        _ => {}
    }
}
