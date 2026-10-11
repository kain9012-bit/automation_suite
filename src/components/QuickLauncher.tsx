import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  AppWindow,
  ChevronDown,
  ChevronUp,
  Clock3,
  Edit3,
  FileText,
  Folder,
  FolderOpen,
  Globe,
  Layers3,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  ACTION_TYPES,
  listenDeckRuns,
  readStoredDeck,
  runDeckAction,
  writeStoredDeck,
  type ActionType,
  type DeckAction,
  type DeckState,
} from "../lib/quickDeck";
import { HotkeyInput } from "./HotkeyInput";
import "./quick-launcher.css";

export type { ActionType, DeckAction };

const ACTION_LABELS: Record<ActionType, string> = {
  site: "사이트",
  folder: "폴더",
  file: "파일",
  program: "프로그램",
};

/** 카드 왼쪽 아이콘. 유형마다 달리 보여 어떤 버튼인지 한눈에 구분한다. */
const ACTION_ICONS: Record<ActionType, LucideIcon> = {
  site: Globe,
  folder: Folder,
  file: FileText,
  program: AppWindow,
};

const PROGRAM_EXTENSIONS = ["exe", "lnk", "bat", "cmd", "ps1", "msi"];

function uid() {
  return crypto.randomUUID();
}

function emptyAction(type: ActionType = "site"): DeckAction {
  return { id: uid(), name: "", type, target: "", arguments: "", hotkey: "", color: "navy", size: "normal" };
}

function initialState(): DeckState {
  const id = uid();
  return { activePageId: id, pages: [{ id, name: "기본", actions: [] }], recent: [] };
}

function readState(): DeckState {
  return readStoredDeck() ?? initialState();
}

/** 고른 경로를 보고 폴더·프로그램·파일 중 무엇인지 추측한다. */
function guessFromPath(path: string): { type: ActionType; name: string } {
  const cleaned = path.replace(/[\\/]+$/, "");
  const base = cleaned.split(/[\\/]/).pop() || cleaned;
  const dot = base.lastIndexOf(".");
  const extension = dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
  if (!extension) return { type: "folder", name: base };
  if (PROGRAM_EXTENSIONS.includes(extension)) return { type: "program", name: base.slice(0, dot) };
  return { type: "file", name: base.slice(0, dot) };
}

/** 중복 판정을 위해 경로·주소를 한 모양으로 맞춘다. */
function normalizeTarget(target: string) {
  return target.trim().replace(/[\\/]+$/, "").toLowerCase();
}

export function QuickLauncher() {
  const [deck, setDeck] = useState<DeckState>(readState);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<DeckAction | null>(null);
  const [status, setStatus] = useState("");
  const [undo, setUndo] = useState<DeckState[]>([]);
  const deckRef = useRef(deck);

  useEffect(() => {
    deckRef.current = deck;
  });

  // 저장하면서 App 의 단축키 등록에도 알린다(useQuickLauncherHotkeys).
  useEffect(() => writeStoredDeck(deck), [deck]);

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

  // 버튼 단축키는 App 에서 등록한다(useQuickLauncherHotkeys). 여기서는 단축키로
  // 실행된 것까지 포함해 실행 상황을 받아 상태 줄과 최근 기록에 반영한다.
  useEffect(
    () =>
      listenDeckRuns((event) => {
        if (event.phase === "start") {
          setStatus(`실행 중: ${event.action.name}`);
        } else if (event.phase === "done") {
          setDeck((current) => ({ ...current, recent: [event.entry, ...current.recent].slice(0, 10) }));
          setStatus(event.message);
        } else {
          setStatus(`실행 실패: ${event.message}`);
        }
      }),
    [],
  );

  const run = useCallback((action: DeckAction) => runDeckAction(action), []);

  // 같은 대상이 이미 있으면 등록하지 않는다. 등록했으면 true.
  const addAction = useCallback(
    (action: DeckAction) => {
      const key = normalizeTarget(action.target);
      const page = deckRef.current.pages.find((item) => item.id === deckRef.current.activePageId) ?? deckRef.current.pages[0];
      if (key && page?.actions.some((item) => normalizeTarget(item.target) === key)) return false;

      setDeck((current) => {
        const target = current.pages.find((item) => item.id === current.activePageId) ?? current.pages[0];
        return {
          ...current,
          pages: current.pages.map((item) =>
            item.id === target.id ? { ...item, actions: [...item.actions, action] } : item,
          ),
        };
      });
      return true;
    },
    [],
  );


  const saveEditor = () => {
    if (!editor || !editor.name.trim()) {
      setStatus("버튼 이름을 입력해 주세요.");
      return;
    }
    if (!editor.target.trim()) {
      setStatus("실행할 주소나 경로를 입력해 주세요.");
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
    <section className="quick-launcher" data-tour="quick-launcher">
      <header className="launcher-head">
        <div>
          <h2>빠른 실행</h2>
          <p>자주 쓰는 사이트·폴더·파일·프로그램을 등록해 두고 클릭이나 단축키로 실행합니다.</p>
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
              <b>새 버튼</b>을 눌러 사이트·폴더·파일·프로그램을 등록하세요.
            </span>
          </div>
        )}
        {actions.map((action) => (
          <article key={action.id} className={`launcher-card color-${action.color} size-${action.size}`}>
            <button className="launcher-run" onClick={() => void run(action)}>
              <span className="launcher-play">
                <ActionIcon type={action.type} />
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
                  onChange={(event) => setEditor({ ...editor, type: event.target.value as ActionType, target: "" })}
                >
                  {ACTION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {ACTION_LABELS[type]}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                <span>주소 또는 경로</span>
                <div className="target-row">
                  <input
                    value={editor.target}
                    onChange={(event) => setEditor({ ...editor, target: event.target.value })}
                    placeholder={editor.type === "site" ? "https://..." : "경로"}
                  />
                  {editor.type !== "site" && (
                    <button className="secondary-button" onClick={() => void pickTarget()}>
                      <FolderOpen size={14} />
                      찾기
                    </button>
                  )}
                </div>
              </label>

              {editor.type === "program" && (
                <label>
                  <span>실행 인수(선택)</span>
                  <input
                    value={editor.arguments}
                    onChange={(event) => setEditor({ ...editor, arguments: event.target.value })}
                  />
                </label>
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

function ActionIcon({ type }: { type: ActionType }) {
  const Icon = ACTION_ICONS[type] ?? Globe;
  return <Icon size={15} />;
}
