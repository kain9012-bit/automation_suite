import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import {
  ChevronDown,
  ChevronUp,
  Clock3,
  Edit3,
  FolderOpen,
  Layers3,
  Plus,
  Play,
  RotateCcw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { runMacroAction, type MacroActionPayload } from "../lib/bridge";
import { HotkeyInput } from "./HotkeyInput";
import "./quick-launcher.css";

export type ActionType =
  | "site"
  | "folder"
  | "file"
  | "program"
  | "command"
  | "hotkey"
  | "text"
  | "wait"
  | "macro";

export interface DeckAction extends MacroActionPayload {
  id: string;
  name: string;
  type: ActionType;
  target: string;
  arguments: string;
  hotkey: string;
  color: string;
  size: string;
  steps: DeckAction[];
}

interface DeckPage {
  id: string;
  name: string;
  actions: DeckAction[];
}

interface DeckState {
  activePageId: string;
  pages: DeckPage[];
  recent: { name: string; time: string }[];
}

// 기존 슬라이드 패널이 쓰던 키를 그대로 이어받아 등록해 둔 버튼이 사라지지 않게 한다.
const STORAGE_KEY = "jbedu-suite:macro-deck";

const ACTION_LABELS: Record<ActionType, string> = {
  site: "사이트",
  folder: "폴더",
  file: "파일",
  program: "프로그램",
  command: "명령",
  hotkey: "단축키",
  text: "텍스트",
  wait: "대기",
  macro: "매크로",
};

const TYPES = Object.keys(ACTION_LABELS) as ActionType[];
const PROGRAM_EXTENSIONS = ["exe", "lnk", "bat", "cmd", "ps1", "msi"];

function uid() {
  return crypto.randomUUID();
}

function emptyAction(type: ActionType = "site"): DeckAction {
  return { id: uid(), name: "", type, target: "", arguments: "", hotkey: "", color: "navy", size: "normal", steps: [] };
}

function initialState(): DeckState {
  const id = uid();
  return { activePageId: id, pages: [{ id, name: "기본", actions: [] }], recent: [] };
}

function readState(): DeckState {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") as DeckState | null;
    return saved?.pages?.length ? saved : initialState();
  } catch {
    return initialState();
  }
}

/** 드롭된 경로를 보고 폴더·프로그램·파일 중 무엇인지 추측한다. */
function guessFromPath(path: string): { type: ActionType; name: string } {
  const cleaned = path.replace(/[\\/]+$/, "");
  const base = cleaned.split(/[\\/]/).pop() || cleaned;
  const dot = base.lastIndexOf(".");
  const extension = dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
  if (!extension) return { type: "folder", name: base };
  if (PROGRAM_EXTENSIONS.includes(extension)) return { type: "program", name: base.slice(0, dot) };
  return { type: "file", name: base.slice(0, dot) };
}

function guessFromUrl(url: string): { type: ActionType; name: string } {
  try {
    const parsed = new URL(url);
    return { type: "site", name: parsed.hostname.replace(/^www\./, "") };
  } catch {
    return { type: "site", name: url.slice(0, 24) };
  }
}

export function QuickLauncher() {
  const [deck, setDeck] = useState<DeckState>(readState);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<DeckAction | null>(null);
  const [status, setStatus] = useState("");
  const [undo, setUndo] = useState<DeckState[]>([]);
  const [dropping, setDropping] = useState(false);

  useEffect(() => localStorage.setItem(STORAGE_KEY, JSON.stringify(deck)), [deck]);

  const activePage = deck.pages.find((page) => page.id === deck.activePageId) ?? deck.pages[0];
  const actions = useMemo(
    () =>
      activePage.actions.filter((action) =>
        `${action.name} ${ACTION_LABELS[action.type]} ${action.hotkey}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [activePage.actions, query],
  );

  const commit = (next: DeckState) => {
    setUndo((items) => [deck, ...items].slice(0, 20));
    setDeck(next);
  };

  const updatePage = (nextActions: DeckAction[]) =>
    commit({
      ...deck,
      pages: deck.pages.map((page) => (page.id === activePage.id ? { ...page, actions: nextActions } : page)),
    });

  const run = useCallback(async (action: DeckAction) => {
    setStatus(`실행 중: ${action.name}`);
    try {
      const result = await runMacroAction(action);
      const entry = {
        name: action.name,
        time: new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
      };
      setDeck((current) => ({ ...current, recent: [entry, ...current.recent].slice(0, 10) }));
      setStatus(String(result.message || `${action.name} 실행 완료`));
    } catch (error) {
      setStatus(`실행 실패: ${String(error)}`);
    }
  }, []);

  const runRef = useRef(run);
  useEffect(() => {
    runRef.current = run;
  });

  // 전역 등록에 성공한 조합은 창 keydown 폴백에서 제외해 두 번 실행되지 않게 한다.
  const globalHotkeys = useRef(new Set<string>());

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.target instanceof HTMLSelectElement
      )
        return;
      const combo = [
        event.ctrlKey && "ctrl",
        event.altKey && "alt",
        event.shiftKey && "shift",
        event.metaKey && "win",
        event.key.toLowerCase(),
      ]
        .filter(Boolean)
        .join("+");
      if (globalHotkeys.current.has(combo)) return;
      const action = activePage.actions.find((item) => item.hotkey.trim().toLowerCase() === combo);
      if (action) {
        event.preventDefault();
        void runRef.current(action);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  const shortcutSignature = JSON.stringify(
    activePage.actions.map((action) => [action.id, action.hotkey, action.type, action.target, action.arguments, action.steps]),
  );

  useEffect(() => {
    let cancelled = false;
    const registered: string[] = [];
    const targets = activePage.actions.filter((action) => action.hotkey.trim());
    void (async () => {
      for (const action of targets) {
        if (cancelled) return;
        const hotkey = action.hotkey.trim();
        try {
          await register(hotkey, (event) => {
            if (event.state === "Pressed") void runRef.current(action);
          });
        } catch {
          continue;
        }
        if (cancelled) {
          void unregister(hotkey).catch(() => undefined);
          return;
        }
        registered.push(hotkey);
        globalHotkeys.current.add(hotkey.toLowerCase());
      }
    })();
    return () => {
      cancelled = true;
      for (const hotkey of registered) {
        globalHotkeys.current.delete(hotkey.toLowerCase());
        void unregister(hotkey).catch(() => undefined);
      }
    };
  }, [shortcutSignature]);

  const addAction = useCallback(
    (action: DeckAction) => {
      setDeck((current) => {
        const page = current.pages.find((item) => item.id === current.activePageId) ?? current.pages[0];
        return {
          ...current,
          pages: current.pages.map((item) =>
            item.id === page.id ? { ...item, actions: [...item.actions, action] } : item,
          ),
        };
      });
    },
    [],
  );

  // 파일·폴더·프로그램을 창으로 끌어다 놓으면 바로 버튼으로 등록한다.
  useEffect(() => {
    // 등록이 끝나기 전에 화면을 벗어나면 정리 함수가 먼저 돌아 리스너가 남는다.
    // 그대로 두면 홈에 드나들 때마다 리스너가 쌓여 파일 하나를 놓아도 여러 번 등록된다.
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (cancelled) return;
        if (event.payload.type === "over") {
          setDropping(true);
          return;
        }
        if (event.payload.type === "leave") {
          setDropping(false);
          return;
        }
        setDropping(false);
        const paths = event.payload.paths ?? [];
        if (!paths.length) return;
        let added = 0;
        for (const path of paths) {
          const guess = guessFromPath(path);
          addAction({ ...emptyAction(guess.type), name: guess.name, target: path });
          added += 1;
        }
        setStatus(`${added}개를 빠른 실행에 등록했습니다.`);
      })
      .then((stop) => {
        if (cancelled) {
          stop();
          return;
        }
        unlisten = stop;
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [addAction]);

  const handleDrop = (event: React.DragEvent) => {
    const url = event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain");
    if (!url.trim()) return;
    event.preventDefault();
    setDropping(false);
    const guess = guessFromUrl(url.trim());
    addAction({ ...emptyAction(guess.type), name: guess.name, target: url.trim() });
    setStatus(`${guess.name}을(를) 빠른 실행에 등록했습니다.`);
  };

  const saveEditor = () => {
    if (!editor || !editor.name.trim()) {
      setStatus("버튼 이름을 입력해 주세요.");
      return;
    }
    if (editor.type !== "macro" && !editor.target.trim()) {
      setStatus("실행할 주소나 경로를 입력해 주세요.");
      return;
    }
    if (editor.type === "macro" && !editor.steps.length) {
      setStatus("매크로 단계를 하나 이상 추가해 주세요.");
      return;
    }
    const exists = activePage.actions.some((item) => item.id === editor.id);
    updatePage(
      exists ? activePage.actions.map((item) => (item.id === editor.id ? editor : item)) : [...activePage.actions, editor],
    );
    setEditor(null);
    setStatus("빠른 실행 버튼을 저장했습니다.");
  };

  const pickTarget = async () => {
    if (!editor) return;
    const directory = editor.type === "folder";
    const selected = await openDialog({
      directory,
      multiple: false,
      title: directory ? "폴더 선택" : "파일 또는 프로그램 선택",
    });
    if (typeof selected === "string") {
      const guess = guessFromPath(selected);
      setEditor({ ...editor, target: selected, name: editor.name.trim() || guess.name });
    }
  };

  const addPage = () => {
    const name = window.prompt("새 페이지 이름", `페이지 ${deck.pages.length + 1}`)?.trim();
    if (!name) return;
    const page = { id: uid(), name, actions: [] };
    commit({ ...deck, activePageId: page.id, pages: [...deck.pages, page] });
  };

  const deletePage = () => {
    if (deck.pages.length === 1) {
      setStatus("페이지는 하나 이상 필요합니다.");
      return;
    }
    if (!window.confirm(`'${activePage.name}' 페이지를 삭제할까요?`)) return;
    const pages = deck.pages.filter((page) => page.id !== activePage.id);
    commit({ ...deck, activePageId: pages[0].id, pages });
  };

  const move = (id: string, direction: number) => {
    const list = [...activePage.actions];
    const index = list.findIndex((item) => item.id === id);
    const next = index + direction;
    if (index < 0 || next < 0 || next >= list.length) return;
    [list[index], list[next]] = [list[next], list[index]];
    updatePage(list);
  };

  return (
    <section
      className={`quick-launcher ${dropping ? "is-dropping" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDropping(true);
      }}
      onDragLeave={() => setDropping(false)}
      onDrop={handleDrop}
    >
      <header className="launcher-head">
        <div>
          <h2>빠른 실행</h2>
          <p>자주 쓰는 사이트·폴더·프로그램과 반복 작업을 등록해 두고 클릭이나 단축키로 실행합니다.</p>
        </div>
        <div className="launcher-tools">
          <div className="launcher-pages">
            {deck.pages.map((page) => (
              <button
                key={page.id}
                className={page.id === activePage.id ? "is-active" : ""}
                onClick={() => setDeck({ ...deck, activePageId: page.id })}
              >
                {page.name}
              </button>
            ))}
            <button className="page-add" onClick={addPage} title="페이지 추가">
              <Plus size={14} />
            </button>
            {deck.pages.length > 1 && (
              <button className="page-add" onClick={deletePage} title="현재 페이지 삭제">
                <Trash2 size={14} />
              </button>
            )}
          </div>
          <label className="launcher-search">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="등록한 버튼 검색" />
          </label>
          <button className="primary-button" onClick={() => setEditor(emptyAction())}>
            <Plus size={15} />새 버튼
          </button>
        </div>
      </header>

      <div className="launcher-grid">
        {!actions.length && (
          <div className="launcher-empty">
            <Layers3 size={30} />
            <strong>아직 등록한 버튼이 없습니다.</strong>
            <span>
              파일·폴더·프로그램을 이 영역으로 끌어다 놓거나, <b>새 버튼</b>을 눌러 사이트와 매크로를 등록하세요.
            </span>
          </div>
        )}
        {actions.map((action) => (
          <article key={action.id} className={`launcher-card color-${action.color} size-${action.size}`}>
            <button className="launcher-run" onClick={() => void run(action)}>
              <span className="launcher-play">
                <Play size={15} />
              </span>
              <span className="launcher-copy">
                <strong>{action.name}</strong>
                <small>
                  {ACTION_LABELS[action.type]}
                  {action.hotkey ? ` · ${action.hotkey}` : ""}
                </small>
              </span>
            </button>
            <div className="launcher-controls">
              <button onClick={() => move(action.id, -1)} title="앞으로">
                <ChevronUp size={13} />
              </button>
              <button onClick={() => move(action.id, 1)} title="뒤로">
                <ChevronDown size={13} />
              </button>
              <button onClick={() => setEditor(structuredClone(action))} title="편집">
                <Edit3 size={13} />
              </button>
              <button
                onClick={() => {
                  if (window.confirm(`'${action.name}' 버튼을 삭제할까요?`))
                    updatePage(activePage.actions.filter((item) => item.id !== action.id));
                }}
                title="삭제"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </article>
        ))}
      </div>

      {(status || undo.length > 0 || deck.recent[0]) && (
        <footer className="launcher-foot">
          <span>{status}</span>
          <div>
            {undo.length > 0 && (
              <button
                onClick={() => {
                  const [previous, ...rest] = undo;
                  setDeck(previous);
                  setUndo(rest);
                }}
              >
                <RotateCcw size={13} />
                되돌리기
              </button>
            )}
            {deck.recent[0] && (
              <small>
                <Clock3 size={12} />
                최근 {deck.recent[0].name} {deck.recent[0].time}
              </small>
            )}
          </div>
        </footer>
      )}

      {editor && (
        <div className="launcher-modal-backdrop" onMouseDown={() => setEditor(null)}>
          <section className="launcher-modal" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <strong>{activePage.actions.some((item) => item.id === editor.id) ? "빠른 실행 편집" : "빠른 실행 추가"}</strong>
              <button onClick={() => setEditor(null)}>
                <X size={17} />
              </button>
            </header>
            <div className="launcher-form">
              <label>
                <span>버튼 이름</span>
                <input
                  value={editor.name}
                  onChange={(event) => setEditor({ ...editor, name: event.target.value })}
                  placeholder="예: 업무포털 열기"
                />
              </label>
              <label>
                <span>동작 종류</span>
                <select
                  value={editor.type}
                  onChange={(event) => setEditor({ ...editor, type: event.target.value as ActionType, target: "", steps: [] })}
                >
                  {TYPES.map((type) => (
                    <option key={type} value={type}>
                      {ACTION_LABELS[type]}
                    </option>
                  ))}
                </select>
              </label>

              {editor.type !== "macro" && (
                <label>
                  <span>
                    {editor.type === "wait"
                      ? "대기 시간(초)"
                      : editor.type === "hotkey"
                        ? "실행할 단축키"
                        : editor.type === "text"
                          ? "입력할 텍스트"
                          : "주소 또는 경로"}
                  </span>
                  <div className="target-row">
                    <input
                      value={editor.target}
                      onChange={(event) => setEditor({ ...editor, target: event.target.value })}
                      placeholder={
                        editor.type === "site" ? "https://..." : editor.type === "hotkey" ? "ctrl+shift+s" : "경로 또는 실행 내용"
                      }
                    />
                    {["folder", "file", "program"].includes(editor.type) && (
                      <button className="secondary-button" onClick={() => void pickTarget()}>
                        <FolderOpen size={14} />
                        찾기
                      </button>
                    )}
                  </div>
                </label>
              )}

              {editor.type === "program" && (
                <label>
                  <span>실행 인수(선택)</span>
                  <input
                    value={editor.arguments}
                    onChange={(event) => setEditor({ ...editor, arguments: event.target.value })}
                  />
                </label>
              )}

              {editor.type === "macro" && (
                <div className="macro-steps">
                  <div>
                    <span>매크로 단계</span>
                    <button
                      className="secondary-button"
                      onClick={() => setEditor({ ...editor, steps: [...editor.steps, emptyAction("site")] })}
                    >
                      <Plus size={14} />
                      단계 추가
                    </button>
                  </div>
                  {editor.steps.map((step, index) => (
                    <div className="macro-step" key={step.id}>
                      <b>{index + 1}</b>
                      <select
                        value={step.type}
                        onChange={(event) =>
                          setEditor({
                            ...editor,
                            steps: editor.steps.map((item) =>
                              item.id === step.id ? { ...item, type: event.target.value as ActionType } : item,
                            ),
                          })
                        }
                      >
                        {TYPES.filter((type) => type !== "macro").map((type) => (
                          <option key={type} value={type}>
                            {ACTION_LABELS[type]}
                          </option>
                        ))}
                      </select>
                      <input
                        value={step.target}
                        onChange={(event) =>
                          setEditor({
                            ...editor,
                            steps: editor.steps.map((item) =>
                              item.id === step.id ? { ...item, target: event.target.value } : item,
                            ),
                          })
                        }
                        placeholder="주소·경로·텍스트·초"
                      />
                      <button onClick={() => setEditor({ ...editor, steps: editor.steps.filter((item) => item.id !== step.id) })}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="launcher-form-row">
                <label>
                  <span>버튼 단축키(선택)</span>
                  <HotkeyInput
                    value={editor.hotkey}
                    fallback=""
                    onChange={(next) => setEditor({ ...editor, hotkey: next })}
                  />
                </label>
                <label>
                  <span>색상</span>
                  <select value={editor.color} onChange={(event) => setEditor({ ...editor, color: event.target.value })}>
                    <option value="navy">남색</option>
                    <option value="sky">하늘</option>
                    <option value="teal">청록</option>
                    <option value="amber">호박</option>
                    <option value="rose">자주</option>
                  </select>
                </label>
                <label>
                  <span>크기</span>
                  <select value={editor.size} onChange={(event) => setEditor({ ...editor, size: event.target.value })}>
                    <option value="normal">보통</option>
                    <option value="wide">넓게</option>
                  </select>
                </label>
              </div>
            </div>
            <footer>
              <button className="secondary-button" onClick={() => setEditor(null)}>
                취소
              </button>
              <button className="primary-button" onClick={saveEditor}>
                저장
              </button>
            </footer>
          </section>
        </div>
      )}
    </section>
  );
}
