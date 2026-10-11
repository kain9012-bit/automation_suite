import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { ask, open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  Check,
  Eraser,
  File,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  FolderPlus,
  HardDrive,
  LoaderCircle,
  Presentation,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  CONTENT_TYPES,
  contentTypeLabel,
  docSearch,
  folderName,
  hasPath,
  splitHighlights,
  statusNote,
  type DocSearchHit,
  type DocSearchProgress,
  type DocSearchResult,
  type DocSearchStatus,
  type FolderChoices,
} from "../lib/docsearch";
import "./doc-search.css";

/**
 * 문서 검색(1.4.4): 사이드바 '문서 검색' 화면.
 * 처음에는 어느 폴더에서 찾을지 먼저 고르게 하고(고르기 전에는 아무것도 읽지 않음),
 * 고른 폴더는 검색창 바로 아래에 늘 보여 "이 안에서만 찾는다"를 알 수 있게 한다.
 * 1.4.5: 내용까지 찾을 문서 종류도 고른다(처음 고르는 화면과 왼쪽 '내용 검색 문서').
 */

const KINDS: { id: string; label: string }[] = [
  { id: "hwp", label: "한글" },
  { id: "pdf", label: "PDF" },
  { id: "excel", label: "엑셀" },
  { id: "word", label: "워드" },
  { id: "ppt", label: "파워포인트" },
  { id: "text", label: "텍스트" },
  { id: "other", label: "기타" },
];

const PERIODS: { id: string; label: string; days: number }[] = [
  { id: "all", label: "전체 기간", days: 0 },
  { id: "week", label: "최근 1주", days: 7 },
  { id: "month", label: "최근 1개월", days: 31 },
  { id: "quarter", label: "최근 3개월", days: 92 },
  { id: "year", label: "최근 1년", days: 366 },
];

/** `child` 가 `parent` 폴더 안(같은 폴더 제외)에 있는지. 대소문자·끝의 \ 는 가리지 않는다. */
function isInside(child: string, parent: string) {
  const norm = (p: string) => p.replace(/[\\/]+$/, "").toLowerCase() + "\\";
  const c = norm(child);
  const p = norm(parent);
  return c !== p && c.startsWith(p);
}

/** 탐색기 아이콘: 확장자 → PNG data URL(받지 못했으면 null). 화면을 다시 열어도 다시 묻지 않는다. */
const systemIcons = new Map<string, string | null>();

function iconFor(ext: string): LucideIcon {
  if (["xlsx", "xls", "csv"].includes(ext)) return FileSpreadsheet;
  if (["pptx", "ppt"].includes(ext)) return Presentation;
  if (["hwp", "hwpx", "pdf", "docx", "doc", "txt", "md"].includes(ext)) return FileText;
  return File;
}

const pad = (n: number) => String(n).padStart(2, "0");

function formatDate(secs: number) {
  if (!secs) return "";
  const d = new Date(secs * 1000);
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`;
}

function formatTime(secs: number) {
  if (!secs) return "";
  const d = new Date(secs * 1000);
  return d.toDateString() === new Date().toDateString()
    ? `오늘 ${pad(d.getHours())}:${pad(d.getMinutes())}`
    : `${d.getMonth() + 1}.${d.getDate()}. ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)}GB`;
}

function Highlighted({ text, highlights }: { text: string; highlights: string[] }) {
  return (
    <>
      {splitHighlights(text, highlights).map((part, index) =>
        part.mark ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </>
  );
}

function progressText(progress: DocSearchProgress | null) {
  if (!progress) return "새 문서 확인 중…";
  if (progress.phase === "compact") return "색인 정리 중…";
  if (progress.phase === "scan") return `파일 목록 대조 중… ${progress.done.toLocaleString()}개`;
  return `바뀐 문서 읽는 중… ${progress.done.toLocaleString()}/${progress.total.toLocaleString()}`;
}

const RECENT_KEY = "jbedu-suite:docsearch-recent";

function readRecent(): string[] {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(list) ? list.filter((x) => typeof x === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
}

function writeRecent(list: string[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 8)));
  } catch {
    // 저장이 막혀도 검색은 된다
  }
}

export function DocSearchView() {
  const [status, setStatus] = useState<DocSearchStatus | null>(null);
  const [choices, setChoices] = useState<FolderChoices | null>(null);
  const [progress, setProgress] = useState<DocSearchProgress | null>(null);
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [folder, setFolder] = useState("");
  const [period, setPeriod] = useState("all");
  const [result, setResult] = useState<DocSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState("");
  const [recent, setRecent] = useState<string[]>(readRecent);
  /** 처음 고르는 화면에서 고른 내용 검색 종류 */
  const [setupTypes, setSetupTypes] = useState<string[] | null>(null);
  const [, setIconsLoaded] = useState(0);
  const searchSeq = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filters = useMemo(() => {
    const days = PERIODS.find((p) => p.id === period)?.days ?? 0;
    return {
      kinds,
      folder: folder || null,
      since: days ? Math.floor(Date.now() / 1000) - days * 86400 : null,
    };
  }, [kinds, folder, period]);

  const runSearch = useCallback(
    async (text: string) => {
      const seq = ++searchSeq.current;
      if (!text.trim()) {
        setResult(null);
        setSearching(false);
        return;
      }
      setSearching(true);
      try {
        const found = await docSearch.search(text, filters);
        if (seq === searchSeq.current) setResult(found);
      } catch (error) {
        if (seq === searchSeq.current) setMessage(String(error));
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    },
    [filters],
  );

  // 화면을 열 때: 폴더를 골라 둔 PC면 10분 지났을 때 뒤에서 대조. 고르기 전이면 고르는 화면.
  useEffect(() => {
    void docSearch.folderChoices().then(setChoices).catch(() => setChoices({ common: [], drives: [] }));
    void docSearch
      .defaultContentTypes()
      .then(setSetupTypes)
      .catch(() => setSetupTypes(["hwp", "pdf", "word", "text"]));
    void docSearch
      .openScreen()
      .then((s) => {
        setStatus(s);
        setProgress(s.progress);
      })
      .catch((error) => setMessage(String(error)));
  }, []);

  useEffect(() => {
    if (status?.confirmed) inputRef.current?.focus();
  }, [status?.confirmed]);

  // 대조 진행 상황과 끝남을 받는다. 끝나면 보고 있는 결과를 다시 찾아 새 문서를 더한다.
  const queryRef = useRef(query);
  queryRef.current = query;
  const runSearchRef = useRef(runSearch);
  runSearchRef.current = runSearch;
  useEffect(() => {
    const stops: UnlistenFn[] = [];
    let alive = true;
    const keep = (stop: UnlistenFn) => (alive ? stops.push(stop) : stop());
    void listen<DocSearchProgress | null>("docsearch-progress", (event) => setProgress(event.payload)).then(keep);
    void listen("docsearch-updated", () => {
      void docSearch.status().then(setStatus).catch(() => undefined);
      void runSearchRef.current(queryRef.current);
    }).then(keep);
    void listen<string>("docsearch-error", (event) =>
      setMessage(`문서 목록을 읽다가 멈췄습니다: ${event.payload}`),
    ).then(keep);
    return () => {
      alive = false;
      stops.forEach((stop) => stop());
    };
  }, []);

  // 결과에 처음 나온 확장자는 탐색기 아이콘을 받아 온다. 못 받으면 원래 아이콘을 쓴다.
  useEffect(() => {
    const missing = [...new Set((result?.hits ?? []).map((hit) => hit.ext).filter((ext) => ext && !systemIcons.has(ext)))];
    if (!missing.length) return;
    missing.forEach((ext) => systemIcons.set(ext, null));
    void docSearch
      .fileIcons(missing)
      .then((icons) => {
        Object.entries(icons).forEach(([ext, url]) => systemIcons.set(ext, url));
        setIconsLoaded((n) => n + 1);
      })
      .catch(() => undefined);
  }, [result]);

  // 입력이 멈추면 찾는다
  useEffect(() => {
    const timer = window.setTimeout(() => void runSearch(query), 250);
    return () => window.clearTimeout(timer);
  }, [query, runSearch]);

  // 결과가 나온 검색어를 2초 그대로 두면 최근 검색에 남긴다
  useEffect(() => {
    const text = query.trim();
    if (!text || !result || result.total === 0) return;
    const timer = window.setTimeout(() => {
      setRecent((list) => {
        const next = [text, ...list.filter((q) => q !== text)].slice(0, 8);
        writeRecent(next);
        return next;
      });
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [query, result]);

  const running = !!status?.running || !!progress;
  const compacting = progress?.phase === "compact";

  const saveFolders = async (folders: string[], contentTypes?: string[]) => {
    try {
      const s = await docSearch.setFolders(folders, contentTypes);
      setStatus(s);
      setProgress(s.progress);
      if (folder && !hasPath(folders, folder)) setFolder("");
      setMessage("");
    } catch (error) {
      setMessage(String(error));
    }
  };

  const act = async (action: () => Promise<unknown>) => {
    try {
      const value = await action();
      if (value && typeof value === "object" && "confirmed" in (value as object)) {
        const s = value as DocSearchStatus;
        setStatus(s);
        setProgress(s.progress);
      }
    } catch (error) {
      setMessage(String(error));
    }
  };

  // [색인 정리]: 끈 문서 종류·뺀 폴더의 글이 남긴 빈 자리를 비운다.
  const compactIndex = async () => {
    const yes = await ask(
      "색인 파일의 빈 자리를 비워 크기를 줄입니다.\n\n" +
        "내용 검색 종류를 끄거나 검색 폴더를 뺀 뒤에 하면 효과가 큽니다. " +
        "색인 크기에 따라 몇 초에서 몇 분 걸리고, 그동안은 검색할 수 없습니다. " +
        "읽던 문서가 있으면 잠시 멈췄다가 정리가 끝나면 이어서 읽습니다.\n\n" +
        "지금 색인 크기만큼 디스크 여유 공간이 필요합니다.",
      { title: "색인 정리", kind: "info", okLabel: "정리", cancelLabel: "취소" },
    );
    if (!yes) return;
    setResult(null);
    setProgress({ phase: "compact", done: 0, total: 0, current: "" });
    try {
      const done = await docSearch.compact();
      setStatus(done.status);
      setProgress(done.status.progress);
      setMessage(`색인을 정리했습니다: ${formatSize(done.before)} → ${formatSize(done.after)}`);
    } catch (error) {
      setProgress(null);
      setMessage(String(error));
      void docSearch.status().then(setStatus).catch(() => undefined);
    }
  };

  const toggleKind = (id: string) =>
    setKinds((current) => (current.includes(id) ? current.filter((k) => k !== id) : [...current, id]));

  if (!status || !choices || !setupTypes) {
    return <div className="ds-view ds-loading" data-tour="docsearch">{message || "불러오는 중…"}</div>;
  }

  // ── 처음: 어느 폴더에서 찾을지 고르기 ──
  if (!status.confirmed) {
    const initial = status.folders.length
      ? status.folders.map((f) => f.path)
      : choices.common.map((c) => c.path);
    return (
      <div className="ds-view" data-tour="docsearch">
        <section className="ds-setup">
          <h2>어느 폴더에서 문서를 찾을까요?</h2>
          <p>
            고른 폴더 안의 문서만 읽어서 찾습니다(하위 폴더 포함). 고르기 전에는 아무 파일도 읽지 않으며,
            나중에 검색 화면 왼쪽 '검색 폴더'에서 언제든 더하거나 뺄 수 있습니다.
          </p>
          <FolderPicker
            initial={initial}
            choices={choices}
            submitLabel="이 폴더들에서 찾기 시작"
            onSubmit={(folders) => void saveFolders(folders, setupTypes)}
          >
            <h3>내용까지 찾을 문서</h3>
            <div className="ds-pick-grid">
              {CONTENT_TYPES.map((t) => {
                const on = setupTypes.includes(t.id);
                return (
                  <button
                    key={t.id}
                    className={`ds-pick ${on ? "is-on" : ""}`}
                    onClick={() =>
                      setSetupTypes(on ? setupTypes.filter((x) => x !== t.id) : [...setupTypes, t.id])
                    }
                    aria-pressed={on}
                  >
                    <span className="ds-check">{on && <Check size={13} />}</span>
                    {(() => {
                      const Icon = iconFor(t.exts.split(" ")[0]);
                      return <Icon size={16} />;
                    })()}
                    <span className="ds-pick-text">
                      <strong>{t.label}</strong>
                      <small>{t.exts}</small>
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="ds-pick-note">
              고르지 않은 종류도 파일 이름으로는 찾습니다. 엑셀·파워포인트는 글자가 많아 처음 읽는 데 오래 걸리고
              색인이 커질 수 있어 기본으로 꺼 두었습니다. 나중에 검색 화면 왼쪽 '내용 검색 문서'에서 바꿀 수 있습니다.
            </p>
          </FolderPicker>
          {message && <div className="ds-message">{message}</div>}
        </section>
      </div>
    );
  }

  const folders = status.folders;
  const paths = folders.map((f) => f.path);
  const suggestions = [...choices.common, ...choices.drives].filter((c) => !hasPath(paths, c.path));

  const addFolder = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "검색할 폴더 선택" });
    if (typeof chosen === "string" && !hasPath(paths, chosen)) await saveFolders([...paths, chosen]);
  };

  // [×]: 실수로 빼지 않게 한 번 묻는다. 빼면 그 폴더의 색인이 지워져 다시 넣을 때 처음부터 읽기 때문.
  const removeFolder = async (path: string) => {
    const name = folderName(path, choices);
    const rest = paths.filter((p) => p !== path);
    const parent = rest.find((p) => isInside(path, p));
    const detail = parent
      ? `이 폴더는 '${folderName(parent, choices)}' 안에 있어서, 빼도 그 안의 문서는 계속 검색됩니다.`
      : "이 폴더의 문서는 색인에서 지워집니다.\n다시 추가하면 문서를 처음부터 다시 읽어야 합니다.";
    const yes = await ask(`'${name}' 폴더를 검색 대상에서 제거하시겠습니까?\n\n${detail}`, {
      title: "검색 폴더 제거",
      kind: "warning",
      okLabel: "제거",
      cancelLabel: "취소",
    });
    if (yes) await saveFolders(rest);
  };

  // 내용 검색 종류 켜기·끄기. 끌 때는 읽어 둔 글이 지워지므로 한 번 묻는다.
  const enabledTypes = status.contentTypes;
  const toggleContentType = async (id: string) => {
    const on = enabledTypes.includes(id);
    const label = contentTypeLabel(id);
    if (on) {
      const yes = await ask(
        `'${label}' 문서의 내용 검색을 끄시겠습니까?\n\n` +
          `이미 읽어 둔 ${label} 문서의 내용은 색인에서 지워지고, 파일 이름으로만 찾습니다.\n` +
          "다시 켜면 내용을 처음부터 다시 읽어야 합니다.",
        { title: "내용 검색 끄기", kind: "warning", okLabel: "끄기", cancelLabel: "취소" },
      );
      if (!yes) return;
    }
    const next = on ? enabledTypes.filter((x) => x !== id) : [...enabledTypes, id];
    await act(() => docSearch.setContentTypes(next));
  };

  const highlights = result?.highlights ?? [];
  const percent =
    progress?.phase === "read" && progress.total ? Math.floor((progress.done / progress.total) * 100) : null;

  return (
    <div className="ds-shell" data-tour="docsearch">
      <aside className="ds-side">
        <div className="ds-side-head">
          <span>
            검색 폴더 <em>({folders.length})</em>
          </span>
          <button onClick={() => void addFolder()} title="폴더 추가">
            <Plus size={15} />
          </button>
        </div>
        <ul className="ds-side-list">
          {folders.map((f) => (
            <li key={f.path} className={folder === f.path ? "is-active" : ""}>
              <button
                className="ds-side-folder"
                onClick={() => setFolder(folder === f.path ? "" : f.path)}
                title={f.exists ? `${f.path}\n누르면 이 폴더 안에서만 찾습니다` : `${f.path} (지금 없음)`}
              >
                {/^[a-zA-Z]:[\\/]?$/.test(f.path) ? <HardDrive size={15} /> : <FolderOpen size={15} />}
                <span className={f.exists ? "" : "is-missing"}>{folderName(f.path, choices)}</span>
                <b>{f.documents.toLocaleString()}</b>
              </button>
              <button className="ds-side-remove" onClick={() => void removeFolder(f.path)} title="검색 폴더에서 빼기">
                <X size={13} />
              </button>
            </li>
          ))}
          {!folders.length && <li className="ds-side-empty">+ 를 눌러 검색할 폴더를 넣으세요.</li>}
        </ul>

        {suggestions.length > 0 && (
          <>
            <div className="ds-side-sub">추천 ({suggestions.length})</div>
            <ul className="ds-side-list is-suggest">
              {suggestions.map((c) => (
                <li key={c.path}>
                  <button
                    className="ds-side-folder"
                    onClick={() => void saveFolders([...paths, c.path])}
                    title={`${c.path}\n누르면 검색 폴더에 넣습니다`}
                  >
                    {/^[a-zA-Z]:[\\/]?$/.test(c.path) ? <HardDrive size={15} /> : <FolderOpen size={15} />}
                    <span>{c.label}</span>
                    <Plus size={13} />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        <div className="ds-side-head is-section">
          <span>
            내용 검색 문서 <em>({enabledTypes.length})</em>
          </span>
        </div>
        <ul className="ds-side-list is-types">
          {CONTENT_TYPES.map((t) => {
            const on = enabledTypes.includes(t.id);
            return (
              <li key={t.id} className={on ? "" : "is-off"}>
                <button
                  className="ds-side-folder"
                  onClick={() => void toggleContentType(t.id)}
                  aria-pressed={on}
                  title={
                    on
                      ? `${t.exts}\n내용까지 찾습니다. 누르면 끕니다.`
                      : `${t.exts}\n파일 이름으로만 찾습니다. 누르면 내용까지 찾습니다.`
                  }
                >
                  <span className="ds-check">{on && <Check size={11} />}</span>
                  <span>{t.label}</span>
                  <small>{t.exts}</small>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="ds-side-head is-section">
          <span>
            최근 검색 <em>({recent.length})</em>
          </span>
          {recent.length > 0 && (
            <button
              onClick={() => {
                setRecent([]);
                writeRecent([]);
              }}
              title="최근 검색 지우기"
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
        <ul className="ds-side-list">
          {recent.map((q) => (
            <li key={q}>
              <button className="ds-side-folder" onClick={() => setQuery(q)}>
                <Search size={14} />
                <span>{q}</span>
              </button>
            </li>
          ))}
          {!recent.length && <li className="ds-side-empty">아직 없습니다.</li>}
        </ul>
      </aside>

      <div className="ds-view">
        <section className="ds-searchbox">
          <label className="hero-search ds-search">
            <Search size={18} />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              disabled={compacting}
              placeholder={
                compacting
                  ? "색인을 정리하는 동안은 검색할 수 없습니다"
                  : folder
                  ? `'${folderName(folder, choices)}' 안에서 찾을 낱말을 입력하세요`
                  : "찾을 낱말을 입력하세요 (띄어 쓰면 모두 들어 있는 문서)"
              }
              aria-label="문서 검색어"
            />
            {searching && <LoaderCircle size={16} className="ds-spin" />}
            {query && (
              <button className="ds-clear" onClick={() => setQuery("")} title="지우기">
                <X size={15} />
              </button>
            )}
          </label>
          <div className="ds-filters">
            <div className="ds-chips" role="group" aria-label="파일 종류">
              <button className={kinds.length === 0 ? "is-active" : ""} onClick={() => setKinds([])}>
                모든 종류
              </button>
              {KINDS.map((kind) => (
                <button
                  key={kind.id}
                  className={kinds.includes(kind.id) ? "is-active" : ""}
                  onClick={() => toggleKind(kind.id)}
                >
                  {kind.label}
                </button>
              ))}
            </div>
            <div className="ds-filter-right">
              {folder && (
                <button className="ds-scope-pill" onClick={() => setFolder("")} title="모든 검색 폴더에서 찾기">
                  <FolderOpen size={12} />
                  {folderName(folder, choices)} 안에서만
                  <X size={12} />
                </button>
              )}
              <select value={period} onChange={(event) => setPeriod(event.target.value)} aria-label="수정 기간">
                {PERIODS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {message && (
          <div className="ds-message" role="alert">
            <span>{message}</span>
            <button onClick={() => setMessage("")} title="닫기">
              <X size={14} />
            </button>
          </div>
        )}

        <section className="ds-results">
          {!query.trim() && (
            <div className="ds-empty">
              <Search size={30} />
              <strong>문서 검색</strong>
              <span>
                {enabledTypes.length ? (
                  <>
                    왼쪽 <b>검색 폴더</b> 안에서 파일 이름과 문서 내용(
                    {enabledTypes.map(contentTypeLabel).join("·")})을 함께 찾습니다.
                  </>
                ) : (
                  <>
                    왼쪽 <b>검색 폴더</b> 안에서 파일 이름으로 찾습니다.
                  </>
                )}
              </span>
              {recent.length > 0 && (
                <div className="ds-recent-chips">
                  {recent.slice(0, 5).map((q) => (
                    <button key={q} onClick={() => setQuery(q)}>
                      <Search size={12} />
                      {q}
                    </button>
                  ))}
                </div>
              )}
              <small>
                문서 {status.documents.toLocaleString()}개 · 폴더 {folders.length}곳
              </small>
            </div>
          )}

          {query.trim() && result && (
            <>
              <div className="ds-count">
                {result.total === 0
                  ? "찾는 문서가 없습니다."
                  : result.total > result.hits.length
                    ? `${result.total.toLocaleString()}개 중 잘 맞는 ${result.hits.length}개`
                    : `${result.total.toLocaleString()}개`}
                {result.total === 0 && running && <span> 문서를 읽는 중이라, 끝나면 다시 찾아 봅니다.</span>}
              </div>
              <ul className="ds-list">
                {result.hits.map((hit: DocSearchHit) => {
                  const Icon = iconFor(hit.ext);
                  const systemIcon = systemIcons.get(hit.ext);
                  const note = statusNote(hit.status);
                  return (
                    <li
                      key={hit.path}
                      className="ds-item"
                      onDoubleClick={() => void act(() => docSearch.openFile(hit.path))}
                    >
                      {systemIcon ? (
                        <span className="ds-icon is-system">
                          <img src={systemIcon} alt="" draggable={false} />
                        </span>
                      ) : (
                        <span className={`ds-icon ext-${hit.ext}`}>
                          <Icon size={18} />
                        </span>
                      )}
                      <div className="ds-body">
                        <div className="ds-title">
                          <strong>
                            <Highlighted text={hit.name} highlights={highlights} />
                          </strong>
                          <span className="ds-meta">
                            {formatDate(hit.mtime)} · {formatSize(hit.size)}
                          </span>
                        </div>
                        <div className="ds-path" title={hit.folder}>
                          {hit.folder}
                        </div>
                        {hit.snippet && (
                          <p className="ds-snippet">
                            <Highlighted text={hit.snippet} highlights={highlights} />
                          </p>
                        )}
                        {note && <span className="ds-note">{note}</span>}
                      </div>
                      <div className="ds-actions">
                        <button className="secondary-button" onClick={() => void act(() => docSearch.openFile(hit.path))}>
                          열기
                        </button>
                        <button
                          className="secondary-button"
                          onClick={() => void act(() => docSearch.revealFile(hit.path))}
                          title="폴더 열기"
                        >
                          <FolderOpen size={14} />
                          폴더
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </section>

        <footer className={`ds-foot ${running ? "is-running" : ""}`}>
          {running ? (
            <>
              <span className="ds-state">
                <i className="ds-dot" />
                <strong>{compacting ? "색인 정리 중" : progress?.phase === "scan" ? "목록 대조" : "색인"}</strong>
                {progress?.phase === "read" ? `${progress.done.toLocaleString()}/${progress.total.toLocaleString()}` : ""}
                {progress?.phase === "scan" ? `${progress.done.toLocaleString()}개 확인` : ""}
                {progress?.current && <span className="ds-current">· {progress.current}</span>}
              </span>
              <div className="ds-foot-right">
                {percent !== null && <b className="ds-percent">{percent}%</b>}
                {compacting ? (
                  <span className="ds-compact-note">끝날 때까지 검색할 수 없습니다</span>
                ) : (
                  <button className="secondary-button" onClick={() => void act(docSearch.cancel)}>
                    취소
                  </button>
                )}
              </div>
              {percent !== null && (
                <span className="ds-bar">
                  <span style={{ width: `${percent}%` }} />
                </span>
              )}
            </>
          ) : (
            <>
              <span className="ds-state">
                문서 {status.documents.toLocaleString()}개
                {status.indexBytes > 0 ? ` · 색인 ${formatSize(status.indexBytes)}` : ""}
                {status.lastCheck ? ` · 마지막 확인 ${formatTime(status.lastCheck)}` : ""}
              </span>
              <div className="ds-foot-right">
                {status.indexBytes > 0 && (
                  <button
                    className="secondary-button"
                    onClick={() => void compactIndex()}
                    title="끈 문서 종류·뺀 폴더의 글이 남긴 빈 자리를 비워 색인 파일 크기를 줄입니다"
                  >
                    <Eraser size={13} />
                    색인 정리
                  </button>
                )}
                <button className="secondary-button" onClick={() => void act(docSearch.refresh)}>
                  <RefreshCw size={13} />
                  지금 다시 읽기
                </button>
              </div>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

/** 검색 폴더 고르기: 자주 쓰는 폴더 · 드라이브 전체 · 직접 고른 폴더 */
function FolderPicker({
  initial,
  choices,
  missing = [],
  submitLabel,
  onSubmit,
  onCancel,
  children,
}: {
  initial: string[];
  choices: FolderChoices;
  missing?: string[];
  submitLabel: string;
  onSubmit: (folders: string[]) => void;
  onCancel?: () => void;
  /** 제출 단추 위에 더 보일 것(내용 검색 종류) */
  children?: ReactNode;
}) {
  const [selected, setSelected] = useState<string[]>(initial);
  const presets = [...choices.common, ...choices.drives];
  const custom = selected.filter((p) => !presets.some((c) => hasPath([c.path], p)));

  const toggle = (path: string) =>
    setSelected((list) => (hasPath(list, path) ? list.filter((p) => !hasPath([path], p)) : [...list, path]));

  const add = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "검색할 폴더 선택" });
    if (typeof chosen === "string" && !hasPath(selected, chosen)) setSelected([...selected, chosen]);
  };

  const Row = ({ label, path, icon: Icon }: { label: string; path: string; icon: LucideIcon }) => {
    const on = hasPath(selected, path);
    return (
      <button className={`ds-pick ${on ? "is-on" : ""}`} onClick={() => toggle(path)} aria-pressed={on}>
        <span className="ds-check">{on && <Check size={13} />}</span>
        <Icon size={16} />
        <span className="ds-pick-text">
          <strong>{label}</strong>
          <small>{path}</small>
        </span>
      </button>
    );
  };

  return (
    <div className="ds-picker">
      <h3>자주 쓰는 폴더</h3>
      <div className="ds-pick-grid">
        {choices.common.map((c) => (
          <Row key={c.path} label={c.label} path={c.path} icon={FolderOpen} />
        ))}
      </div>

      {choices.drives.length > 0 && (
        <>
          <h3>드라이브 전체</h3>
          <div className="ds-pick-grid">
            {choices.drives.map((c) => (
              <Row key={c.path} label={c.label} path={c.path} icon={HardDrive} />
            ))}
          </div>
          <p className="ds-pick-note">
            드라이브 전체를 고르면 처음 한 번 읽는 데 시간이 오래 걸릴 수 있습니다. 윈도우·프로그램 설치 폴더,
            숨김·시스템 폴더, 임시 파일은 자동으로 건너뜁니다.
          </p>
        </>
      )}

      <h3>직접 고른 폴더</h3>
      <ul className="ds-folder-list">
        {custom.map((path) => (
          <li key={path}>
            <FolderOpen size={15} />
            <span title={path}>{path}</span>
            {hasPath(missing, path) && <em>지금 없음</em>}
            <button onClick={() => toggle(path)} title="빼기">
              <Trash2 size={14} />
            </button>
          </li>
        ))}
        <li className="ds-add-row">
          <button className="secondary-button" onClick={() => void add()}>
            <FolderPlus size={14} />
            폴더 추가
          </button>
        </li>
      </ul>

      {children}

      <div className="ds-picker-foot">
        <span>{selected.length ? `${selected.length}곳에서 찾습니다.` : "한 곳 이상 골라 주세요."}</span>
        <div>
          {onCancel && (
            <button className="secondary-button" onClick={onCancel}>
              취소
            </button>
          )}
          <button className="primary-button" disabled={!selected.length} onClick={() => onSubmit(selected)}>
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
