import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Command,
  Download,
  LoaderCircle,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import "@fontsource-variable/outfit";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { isRegistered, register, unregister } from "@tauri-apps/plugin-global-shortcut";
import { Header } from "./components/Header";
import { HtmlToolView } from "./components/HtmlToolView";
import { NativeToolPanel } from "./components/NativeToolPanel";
import { ExcelSplitPanel } from "./components/ExcelSplitPanel";
import { PdfOrganizerPanel } from "./components/PdfOrganizerPanel";
import { QuickLauncher } from "./components/QuickLauncher";
import { SettingsPanel } from "./components/SettingsPanel";
import { Sidebar } from "./components/Sidebar";
import { ToolGrid } from "./components/ToolGrid";
import { TutorialOverlay } from "./components/TutorialOverlay";
import { useTools } from "./hooks/useTools";
import { useAutoUpdater } from "./hooks/useAutoUpdater";
import {
  CONTEXT_OPEN_EVENT,
  DEFAULT_TOGGLE_HOTKEY,
  PREFERENCES_CHANGED,
  getAppPreferences,
  takeContextRequest,
} from "./lib/bridge";
import type { ContextRequest, ToolManifest, View } from "./types";

function titleFor(view: View) {
  if (view.kind === "home") return "홈";
  if (view.kind === "favorites") return "즐겨찾기";
  if (view.kind === "recent") return "최근 사용";
  if (view.kind === "settings") return "설정";
  if (view.kind === "category") return view.category;
  return view.tool.name;
}

export default function App() {
  const registry = useTools();
  const updater = useAutoUpdater(registry.refresh);
  const [view, setView] = useState<View>({ kind: "home" });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [dark, setDark] = useState(
    () => localStorage.getItem("jbedu-suite:theme") === "dark",
  );
  const [query, setQuery] = useState("");
  const [commandOpen, setCommandOpen] = useState(false);
  const [tutorialOpen, setTutorialOpen] = useState(
    () => localStorage.getItem("jbedu-suite:tutorial-complete") !== "true",
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("jbedu-suite:theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((current) => !current);
      }
      if (event.key === "Escape") setCommandOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);


  useEffect(() => {
    let stop: UnlistenFn | undefined;
    void listen("open-settings", () => setView({ kind: "settings" }))
      .then((unlisten) => { stop = unlisten; })
      .catch(() => undefined);
    return () => stop?.();
  }, []);

  // 탐색기 우클릭으로 들어온 요청. 도구 목록이 준비된 뒤에 화면을 연다.
  const [contextRequest, setContextRequest] = useState<ContextRequest | null>(null);

  useEffect(() => {
    let stop: UnlistenFn | undefined;
    void listen<ContextRequest>(CONTEXT_OPEN_EVENT, (event) =>
      setContextRequest(event.payload),
    )
      .then((unlisten) => { stop = unlisten; })
      .catch(() => undefined);
    // 앱이 꺼져 있다가 우클릭으로 실행된 경우는 이벤트가 아니라 여기로 들어온다.
    void takeContextRequest()
      .then((request) => { if (request) setContextRequest(request); })
      .catch(() => undefined);
    return () => stop?.();
  }, []);

  useEffect(() => {
    // 도구 목록을 아직 못 불러왔으면 그대로 두고 다음 렌더에서 다시 본다.
    if (!contextRequest || !registry.tools.length) return;
    const tool = registry.tools.find((item) => item.id === contextRequest.toolId);
    setContextRequest(null);
    if (!tool) return;
    registry.markRecent(tool.id);
    setCommandOpen(false);
    // 안내 오버레이가 떠 있으면 도구 화면을 가리므로 닫는다.
    setTutorialOpen(false);
    setView({ kind: "tool", tool, presetPaths: contextRequest.paths });
  }, [contextRequest, registry.tools, registry.markRecent]);

  // 창을 보였다 숨겼다 하는 전역 단축키. 설정에서 바꾸면 곧바로 다시 등록한다.
  const [toggleHotkey, setToggleHotkey] = useState(DEFAULT_TOGGLE_HOTKEY);
  useEffect(() => {
    const load = () => {
      void getAppPreferences()
        .then((preferences) => setToggleHotkey(preferences.toggle_hotkey?.trim() || DEFAULT_TOGGLE_HOTKEY))
        .catch(() => undefined);
    };
    load();
    window.addEventListener(PREFERENCES_CHANGED, load);
    return () => window.removeEventListener(PREFERENCES_CHANGED, load);
  }, []);

  // 등록에 실패하면 사용자는 이유를 알 길이 없다. 설정 화면에서 보여 준다.
  const [hotkeyError, setHotkeyError] = useState("");

  useEffect(() => {
    const shortcut = toggleHotkey.trim();
    if (!shortcut) {
      setHotkeyError("");
      return;
    }

    // 등록이 비동기라, 그냥 두면 정리 함수의 해제가 다음 등록보다 늦게 끝나
    // 방금 등록한 단축키를 도로 풀어 버린다. 그래서 순서를 지켜 처리한다.
    let cancelled = false;
    let mine = false;

    const run = async () => {
      try {
        // 앞선 등록이 남아 있으면 먼저 푼다. 남아 있으면 등록이 실패한다.
        if (await isRegistered(shortcut)) await unregister(shortcut);
        if (cancelled) return;

        await register(shortcut, async (event) => {
          if (event.state !== "Pressed") return;
          const appWindow = getCurrentWindow();
          const visible = await appWindow.isVisible();
          const minimized = await appWindow.isMinimized();
          if (visible && !minimized) {
            await appWindow.hide();
          } else {
            await appWindow.show();
            await appWindow.unminimize();
            await appWindow.setFocus();
          }
        });

        if (cancelled) {
          await unregister(shortcut).catch(() => undefined);
          return;
        }
        mine = true;
        setHotkeyError("");
      } catch {
        if (!cancelled) {
          setHotkeyError(shortcut);
        }
      }
    };
    void run();

    return () => {
      cancelled = true;
      if (mine) void unregister(shortcut).catch(() => undefined);
    };
  }, [toggleHotkey]);

  const openTool = (tool: ToolManifest) => {
    registry.markRecent(tool.id);
    setView({ kind: "tool", tool });
    setCommandOpen(false);
  };

  const displayedTools = useMemo(() => {
    if (view.kind === "favorites") return registry.favoriteTools;
    if (view.kind === "recent") return registry.recentTools;
    if (view.kind === "category") {
      return registry.tools.filter((tool) => tool.top_tab === view.category);
    }
    return registry.tools;
  }, [
    registry.favoriteTools,
    registry.recentTools,
    registry.tools,
    view,
  ]);

  const content = () => {
    if (registry.loading) {
      return (
        <div className="full-message">
          <LoaderCircle className="spin" size={28} />
          <strong>도구 레지스트리를 불러오는 중입니다.</strong>
        </div>
      );
    }
    if (registry.error) {
      return (
        <div className="full-message is-error">
          <strong>도구 목록을 불러오지 못했습니다.</strong>
          <span>{registry.error}</span>
          <button className="secondary-button" onClick={registry.refresh}>
            다시 시도
          </button>
        </div>
      );
    }
    if (view.kind === "settings") {
      return <SettingsPanel onRefresh={registry.refresh} hotkeyError={hotkeyError} onStartTutorial={() => { setView({ kind: "home" }); setTutorialOpen(true); }} />;
    }
    if (view.kind === "tool") {
      if (view.tool.type === "html" || view.tool.has_html) {
        return <HtmlToolView tool={view.tool} />;
      }
      // 일부 도구는 파일을 먼저 읽어 선택지를 만들어야 해서 전용 화면을 쓴다.
      if (view.tool.id === "excel_split") {
        return <ExcelSplitPanel tool={view.tool} />;
      }
      if (view.tool.id === "pdf_page_organizer") {
        return <PdfOrganizerPanel tool={view.tool} />;
      }
      return <NativeToolPanel tool={view.tool} presetPaths={view.presetPaths} />;
    }
    if (view.kind === "home") {
      return (
        <div className="home-view">
          <section className="welcome-hero">
            <span className="hero-kicker">
              <Sparkles size={15} />
              반복 업무를 간단하게
            </span>
            <h1>
              필요한 도구를 찾고,
              <br />
              바로 업무를 시작하세요.
            </h1>
            <p>
              PDF, 한글, 엑셀, 파일 정리와 자료 수집 도구를 한곳에서
              실행합니다.
            </p>
            <label className="hero-search">
              <Search size={20} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="도구 이름이나 업무를 검색하세요"
                autoFocus
              />
              <kbd>Ctrl K</kbd>
            </label>
          </section>
          <QuickLauncher />
          {!!registry.favoriteTools.length && (
            <ToolGrid
              title="즐겨찾기"
              description="자주 사용하는 도구"
              tools={registry.favoriteTools}
              favorites={registry.favorites}
              query={query}
              onOpen={openTool}
              onToggleFavorite={registry.toggleFavorite}
            />
          )}
          <ToolGrid
            title="전체 도구"
            description="등록된 업무 도구를 분류별로 탐색합니다."
            tools={registry.tools}
            favorites={registry.favorites}
            query={query}
            onOpen={openTool}
            onToggleFavorite={registry.toggleFavorite}
          />
        </div>
      );
    }
    return (
      <div className="category-view">
        <ToolGrid
          title={titleFor(view)}
          description={
            view.kind === "favorites"
              ? "별표로 저장한 도구"
              : view.kind === "recent"
                ? "최근에 실행한 도구"
                : "업무별 도구 모음"
          }
          tools={displayedTools}
          favorites={registry.favorites}
          onOpen={openTool}
          onToggleFavorite={registry.toggleFavorite}
        />
      </div>
    );
  };

  return (
    <div className="app-shell">
      <Sidebar
        collapsed={sidebarCollapsed}
        categories={registry.categories}
        activeView={view}
        onNavigate={setView}
      />
      <div className="app-main">
        <Header
          title={titleFor(view)}
          subtitle={
            view.kind === "tool" ? view.tool.top_tab : `${registry.tools.length}개 도구`
          }
          dark={dark}
          onToggleSidebar={() => setSidebarCollapsed((current) => !current)}
          onToggleDark={() => setDark((current) => !current)}
          onRefresh={registry.refresh}
          onOpenCommand={() => setCommandOpen(true)}
          onToggleMacro={() => setView({ kind: "home" })}
        />
        {!!updater.readyVersion && (
          <div className="update-banner">
            <span>
              <Download size={15} />새 버전 {updater.readyVersion}을 받아 두었습니다.
            </span>
            <div>
              <button className="secondary-button" onClick={updater.dismiss}>
                나중에
              </button>
              <button className="primary-button" onClick={() => void updater.apply()}>
                지금 적용
              </button>
            </div>
          </div>
        )}
        <main className="app-content" data-tour="tool-area">{content()}</main>
        <footer className="status-bar">
          <span>
            <i className="status-dot" />
            {updater.status}
          </span>
          <span>도구 {registry.tools.length}개</span>
        </footer>
      </div>


      {commandOpen && (
        <div className="command-backdrop" onMouseDown={() => setCommandOpen(false)}>
          <section
            className="command-palette"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="command-input">
              <Command size={18} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="도구 또는 명령 검색"
                autoFocus
              />
              <button onClick={() => setCommandOpen(false)}>
                <X size={17} />
              </button>
            </div>
            <div className="command-results">
              {registry.tools
                .filter((tool) =>
                  `${tool.name} ${tool.description ?? ""} ${tool.top_tab}`
                    .toLocaleLowerCase()
                    .includes(query.toLocaleLowerCase()),
                )
                .slice(0, 10)
                .map((tool) => (
                  <button key={tool.id} onClick={() => openTool(tool)}>
                    <span>
                      <strong>{tool.name}</strong>
                      <small>{tool.top_tab}</small>
                    </span>
                    <ArrowRight size={16} />
                  </button>
                ))}
            </div>
          </section>
        </div>
      )}
      <TutorialOverlay open={tutorialOpen} onClose={() => setTutorialOpen(false)} />
    </div>
  );
}
