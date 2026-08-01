import { useEffect, useState } from "react";
import {
  Download,
  FolderCog,
  LoaderCircle,
  MonitorCog,
  PlayCircle,
  PackagePlus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  checkToolUpdates,
  installAppUpdateIfAvailable,
  installToolUpdates,
} from "../lib/updater";
import {
  isAutoUpdateEnabled,
  setAutoUpdateEnabled,
} from "../hooks/useAutoUpdater";
import "./settings-panel.css";
import { HotkeyInput } from "./HotkeyInput";
import {
  DEFAULT_TOGGLE_HOTKEY,
  getAppPreferences,
  setAppPreferences,
  type AppPreferences,
} from "../lib/bridge";

export function SettingsPanel({ onRefresh, onStartTutorial }: { onRefresh: () => void; onStartTutorial: () => void }) {
  const [enabled, setEnabled] = useState(isAutoUpdateEnabled);
  const [busy, setBusy] = useState<"app" | "tools" | null>(null);
  const [message, setMessage] = useState("");

  const [desktop, setDesktop] = useState<AppPreferences>({ auto_start: false, close_to_tray: true, minimize_to_tray: true, start_minimized: true, toggle_hotkey: DEFAULT_TOGGLE_HOTKEY });
  const [desktopBusy, setDesktopBusy] = useState(false);

  useEffect(() => {
    void getAppPreferences().then(setDesktop).catch((error) => setMessage(`Windows 설정을 불러오지 못했습니다: ${String(error)}`));
  }, []);

  const changeDesktop = async (key: keyof AppPreferences, value: boolean) => {
    const next = { ...desktop, [key]: value };
    setDesktop(next);
    setDesktopBusy(true);
    try {
      setDesktop(await setAppPreferences(next));
      setMessage("Windows 실행 설정을 저장했습니다.");
    } catch (error) {
      setDesktop(desktop);
      setMessage(`설정 저장 실패: ${String(error)}`);
    } finally {
      setDesktopBusy(false);
    }
  };

  const changeHotkey = async (value: string) => {
    const previous = desktop;
    const next = { ...desktop, toggle_hotkey: value };
    setDesktop(next);
    setDesktopBusy(true);
    try {
      setDesktop(await setAppPreferences(next));
      setMessage(value ? `창 열기·숨기기 단축키를 ${value}로 저장했습니다.` : "단축키를 해제했습니다.");
    } catch (error) {
      setDesktop(previous);
      setMessage(`단축키 저장 실패: ${String(error)}`);
    } finally {
      setDesktopBusy(false);
    }
  };

  const toggleEnabled = (value: boolean) => {
    setEnabled(value);
    setAutoUpdateEnabled(value);
  };

  const checkApp = async () => {
    setBusy("app");
    setMessage("앱 업데이트를 확인하는 중입니다.");
    try {
      const found = await installAppUpdateIfAvailable(setMessage);
      if (!found) setMessage("앱이 최신 버전입니다.");
    } catch (error) {
      setMessage(`앱 업데이트 확인 실패: ${String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  const updateTools = async () => {
    setBusy("tools");
    setMessage("도구 업데이트를 확인하는 중입니다.");
    try {
      const check = await checkToolUpdates();
      if (!check.configured || check.updates.length === 0) {
        setMessage(check.message);
        return;
      }
      const newCount = check.updates.filter((item) => item.is_new).length;
      setMessage(
        `업데이트 ${check.updates.length}개${
          newCount ? ` (새 도구 ${newCount}개 포함)` : ""
        }를 설치합니다.`,
      );
      const result = await installToolUpdates();
      setMessage(result.message);
      onRefresh();
    } catch (error) {
      setMessage(`도구 업데이트 실패: ${String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="settings-view content-column">
      <div className="page-intro">
        <span className="eyebrow">환경 설정</span>
        <h1>앱과 도구를 관리합니다.</h1>
        <p>
          사용자 설정과 추가 도구는 LocalAppData에 보관되어 앱 업데이트 후에도
          유지됩니다.
        </p>
      </div>

      <section className="settings-card settings-card-stack">
        <div className="setting-icon"><MonitorCog size={20} /></div>
        <div>
          <strong>Windows 시작 및 트레이</strong>
          <p>컴퓨터를 켰을 때 자동 실행하고, 닫기·최소화 시 트레이에 보관합니다.</p>
          <div className="setting-toggles">
            <label><span><b>Windows 시작 시 자동 실행</b><small>로그인 후 트레이에서 조용히 시작합니다.</small></span><span className="switch"><input type="checkbox" checked={desktop.auto_start} disabled={desktopBusy} onChange={(event) => void changeDesktop("auto_start", event.target.checked)} /><i /></span></label>
            <label><span><b>닫기(X) 시 트레이로 숨기기</b><small>완전 종료는 트레이 메뉴에서 선택합니다.</small></span><span className="switch"><input type="checkbox" checked={desktop.close_to_tray} disabled={desktopBusy} onChange={(event) => void changeDesktop("close_to_tray", event.target.checked)} /><i /></span></label>
            <label><span><b>최소화 시 트레이로 숨기기</b><small>작업 표시줄을 깔끔하게 유지합니다.</small></span><span className="switch"><input type="checkbox" checked={desktop.minimize_to_tray} disabled={desktopBusy} onChange={(event) => void changeDesktop("minimize_to_tray", event.target.checked)} /><i /></span></label>
            <label><span><b>자동 실행 시 창 숨김</b><small>필요할 때 트레이 아이콘을 눌러 엽니다.</small></span><span className="switch"><input type="checkbox" checked={desktop.start_minimized} disabled={desktopBusy} onChange={(event) => void changeDesktop("start_minimized", event.target.checked)} /><i /></span></label>
            <label><span><b>창 열기·숨기기 단축키</b><small>어느 화면에서든 이 키로 앱을 꺼내고 숨깁니다.</small></span><HotkeyInput value={desktop.toggle_hotkey} fallback={DEFAULT_TOGGLE_HOTKEY} disabled={desktopBusy} onChange={(next) => void changeHotkey(next)} /></label>
          </div>
        </div>
      </section>

      <section className="settings-card">
        <div className="setting-icon"><PlayCircle size={20} /></div>
        <div>
          <strong>처음 사용 안내</strong>
          <p>화면의 주요 부분을 단계별로 강조해서 다시 안내합니다.</p>
        </div>
        <button className="secondary-button" onClick={onStartTutorial}><PlayCircle size={15} />튜토리얼 다시 보기</button>
      </section>

      <section className="settings-card">
        <div className="setting-icon">
          <FolderCog size={20} />
        </div>
        <div>
          <strong>도구 레지스트리</strong>
          <p>기본 도구와 자동 설치된 도구 패키지를 다시 검색합니다.</p>
        </div>
        <button className="secondary-button" onClick={onRefresh}>
          <RefreshCw size={15} />
          새로고침
        </button>
      </section>

      <section className="settings-card">
        <div className="setting-icon">
          <Download size={20} />
        </div>
        <div>
          <strong>앱 자동 업데이트</strong>
          <p>서명된 새 버전만 내려받아 설치하고 앱을 다시 시작합니다.</p>
        </div>
        <label className="switch">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => toggleEnabled(event.target.checked)}
          />
          <span />
        </label>
        <button
          className="secondary-button"
          onClick={checkApp}
          disabled={busy !== null}
        >
          {busy === "app" ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
          지금 확인
        </button>
      </section>

      <section className="settings-card">
        <div className="setting-icon">
          <PackagePlus size={20} />
        </div>
        <div>
          <strong>도구 자동 추가·업데이트</strong>
          <p>서명된 카탈로그를 확인해 새 도구와 기존 도구 업데이트를 설치합니다.</p>
        </div>
        <button
          className="secondary-button"
          onClick={updateTools}
          disabled={busy !== null}
        >
          {busy === "tools" ? <LoaderCircle className="spin" size={15} /> : <PackagePlus size={15} />}
          도구 확인
        </button>
      </section>

      <section className="settings-card">
        <div className="setting-icon">
          <ShieldCheck size={20} />
        </div>
        <div>
          <strong>로컬 처리 우선</strong>
          <p>사용자가 선택한 파일은 외부 서버로 전송하지 않습니다.</p>
        </div>
        <span className="status-chip">사용 중</span>
      </section>

      {message && <div className="update-message">{message}</div>}
    </div>
  );
}

