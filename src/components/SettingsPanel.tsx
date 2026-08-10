import { useEffect, useState } from "react";
import {
  Download,
  Eraser,
  FolderCog,
  LoaderCircle,
  MonitorCog,
  MousePointerClick,
  PlayCircle,
  PackagePlus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  checkToolUpdates,
  downloadUpdateIfAvailable,
  installToolUpdates,
  lastCheckMessage,
} from "../lib/updater";
import {
  isAutoUpdateEnabled,
  setAutoUpdateEnabled,
} from "../hooks/useAutoUpdater";
import "./settings-panel.css";
import { HotkeyInput } from "./HotkeyInput";
import {
  DEFAULT_TOGGLE_HOTKEY,
  clearContextMenus,
  getAppPreferences,
  listContextMenu,
  setAppPreferences,
  setContextMenu,
  type AppPreferences,
} from "../lib/bridge";
import type { ContextMenuEntry } from "../types";

/** 우클릭 메뉴가 어디에 붙는지 사용자 말로 적는다. */
function targetLabel(target: string) {
  return target.toLowerCase() === "folder"
    ? "폴더"
    : `.${target.replace(/^\./, "").toLowerCase()} 파일`;
}

export function SettingsPanel({ onRefresh, onStartTutorial, hotkeyError }: { onRefresh: () => void; onStartTutorial: () => void; hotkeyError?: string }) {
  const [enabled, setEnabled] = useState(isAutoUpdateEnabled);
  const [busy, setBusy] = useState<"app" | "tools" | null>(null);
  const [message, setMessage] = useState("");

  const [desktop, setDesktop] = useState<AppPreferences>({ auto_start: false, close_to_tray: true, minimize_to_tray: true, start_minimized: true, toggle_hotkey: DEFAULT_TOGGLE_HOTKEY });
  const [desktopBusy, setDesktopBusy] = useState(false);

  // 탐색기 우클릭 메뉴. context_menu 블록이 있는 도구만 여기에 나온다.
  const [contextMenus, setContextMenus] = useState<ContextMenuEntry[]>([]);
  const [contextBusy, setContextBusy] = useState("");

  useEffect(() => {
    void getAppPreferences().then(setDesktop).catch((error) => setMessage(`Windows 설정을 불러오지 못했습니다: ${String(error)}`));
  }, []);

  useEffect(() => {
    void listContextMenu()
      .then(setContextMenus)
      .catch((error) => setMessage(`우클릭 메뉴 상태를 불러오지 못했습니다: ${String(error)}`));
  }, []);

  const changeContextMenu = async (entry: ContextMenuEntry, value: boolean) => {
    setContextBusy(entry.id);
    // 레지스트리 조회가 느릴 수 있으니 화면을 먼저 바꾸고, 실패하면 되돌린다.
    const apply = (enabled: boolean) =>
      setContextMenus((current) =>
        current.map((item) => (item.id === entry.id ? { ...item, enabled } : item)),
      );
    apply(value);
    try {
      await setContextMenu(entry.id, value);
      setMessage(
        value
          ? `우클릭 메뉴에 '${entry.label}'을 넣었습니다.`
          : `우클릭 메뉴에서 '${entry.label}'을 뺐습니다.`,
      );
    } catch (error) {
      apply(!value);
      setMessage(`우클릭 메뉴 설정 실패: ${String(error)}`);
    } finally {
      setContextBusy("");
    }
  };

  const clearContext = async () => {
    setContextBusy("all");
    try {
      const removed = await clearContextMenus();
      setContextMenus(await listContextMenu());
      setMessage(
        removed ? `우클릭 메뉴 ${removed}개를 정리했습니다.` : "정리할 우클릭 메뉴가 없습니다.",
      );
    } catch (error) {
      setMessage(`우클릭 메뉴 정리 실패: ${String(error)}`);
    } finally {
      setContextBusy("");
    }
  };

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
      const version = await downloadUpdateIfAvailable(setMessage);
      setMessage(
        version
          ? `새 버전 ${version}을 받아 두었습니다. 화면 위쪽에서 '지금 적용'을 누르면 반영됩니다.`
          // 게시판이 돌려준 설명을 그대로 보여 준다. 표식이 잘못돼 있으면 여기서 보인다.
          : lastCheckMessage() || "앱이 최신 버전입니다.",
      );
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
            {!!hotkeyError && (
              <p className="setting-warning">{hotkeyError}</p>
            )}
          </div>
        </div>
      </section>

      <section className="settings-card settings-card-stack">
        <div className="setting-icon"><MousePointerClick size={20} /></div>
        <div>
          <strong>탐색기 우클릭 메뉴</strong>
          <p>
            파일이나 폴더를 고르고 우클릭해서 도구를 바로 엽니다. 고른 파일이 처리 대상에
            미리 담긴 채로 열립니다. Windows 11에서는 <b>더 많은 옵션 표시</b> 안에 들어갑니다.
          </p>
          {contextMenus.length ? (
            <>
              <div className="setting-toggles">
                {contextMenus.map((entry) => (
                  <label key={entry.id}>
                    <span>
                      <b>{entry.label}</b>
                      <small>
                        {entry.name} · {entry.targets.map(targetLabel).join(", ")}에서 보임
                      </small>
                    </span>
                    <span className="switch">
                      <input
                        type="checkbox"
                        checked={entry.enabled}
                        disabled={contextBusy !== ""}
                        onChange={(event) => void changeContextMenu(entry, event.target.checked)}
                      />
                      <i />
                    </span>
                  </label>
                ))}
              </div>
              <div className="context-menu-actions">
                <button
                  className="secondary-button"
                  onClick={() => void clearContext()}
                  disabled={contextBusy !== ""}
                >
                  {contextBusy === "all" ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Eraser size={15} />
                  )}
                  모두 해제
                </button>
              </div>
            </>
          ) : (
            <div className="context-menu-actions">
              <span className="status-chip">우클릭 메뉴를 지원하는 도구가 없습니다</span>
            </div>
          )}
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
          <p>서명된 새 버전을 미리 내려받아 두고, 적용은 화면 위쪽에서 직접 고릅니다.</p>
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

