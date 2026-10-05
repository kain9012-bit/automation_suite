import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  File,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  FolderPlus,
  LoaderCircle,
  Presentation,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  docSearch,
  splitHighlights,
  statusNote,
  type DocSearchHit,
  type DocSearchProgress,
  type DocSearchResult,
  type DocSearchStatus,
} from "../lib/docsearch";
import "./doc-search.css";

/**
 * 문서 검색(1.4.4): 사이드바 '문서 검색' 화면.
 * 화면을 열면 기존 색인으로 바로 검색되고, 마지막 대조 후 10분이 지났으면 뒤에서 바뀐 파일만 대조한다.
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

function iconFor(ext: string): LucideIcon {
  if (["xlsx", "xls", "csv"].includes(ext)) return FileSpreadsheet;
  if (["pptx", "ppt"].includes(ext)) return Presentation;
  if (["hwp", "hwpx", "pdf", "docx", "doc", "txt", "md"].includes(ext)) return FileText;
  return File;
}

function formatDate(secs: number) {
  if (!secs) return "";
  const d = new Date(secs * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`;
}

function formatTime(secs: number) {
  if (!secs) return "";
  const d = new Date(secs * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? `오늘 ${pad(d.getHours())}:${pad(d.getMinutes())}`
    : `${d.getMonth() + 1}.${d.getDate()}. ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

function folderLabel(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || path;
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
  if (progress.phase === "scan") return `파일 목록 대조 중… ${progress.done.toLocaleString()}개`;
  return `바뀐 문서 읽는 중… ${progress.done.toLocaleString()}/${progress.total.toLocaleString()}`;
}

export function DocSearchView() {
  const [status, setStatus] = useState<DocSearchStatus | null>(null);
  const [progress, setProgress] = useState<DocSearchProgress | null>(null);
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [folder, setFolder] = useState("");
  const [period, setPeriod] = useState("all");
  const [result, setResult] = useState<DocSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState("");
  const [managing, setManaging] = useState(false);
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

  // 화면을 열 때: 처음이면 기본 폴더로 시작, 10분 지났으면 뒤에서 대조
  useEffect(() => {
    inputRef.current?.focus();
    void docSearch
      .openScreen()
      .then((s) => {
        setStatus(s);
        setProgress(s.progress);
      })
      .catch((error) => setMessage(String(error)));
  }, []);

  // 대조 진행 상황과 끝남을 받는다. 끝나면 보고 있는 결과를 다시 찾아 새 문서를 더한다.
  const queryRef = useRef(query);
  queryRef.current = query;
  const runSearchRef = useRef(runSearch);
  runSearchRef.current = runSearch;
  useEffect(() => {
    const stops: UnlistenFn[] = [];
    let alive = true;
    void listen<DocSearchProgress | null>("docsearch-progress", (event) => setProgress(event.payload)).then(
      (stop) => (alive ? stops.push(stop) : stop()),
    );
    void listen("docsearch-updated", () => {
      void docSearch.status().then(setStatus).catch(() => undefined);
      void runSearchRef.current(queryRef.current);
    }).then((stop) => (alive ? stops.push(stop) : stop()));
    void listen<string>("docsearch-error", (event) => setMessage(`문서 목록을 읽다가 멈췄습니다: ${event.payload}`)).then(
      (stop) => (alive ? stops.push(stop) : stop()),
    );
    return () => {
      alive = false;
      stops.forEach((stop) => stop());
    };
  }, []);

  // 입력이 멈추면 찾는다
  useEffect(() => {
    const timer = window.setTimeout(() => void runSearch(query), 250);
    return () => window.clearTimeout(timer);
  }, [query, runSearch]);

  const running = !!status?.running || !!progress;

  const refresh = async () => {
    try {
      const s = await docSearch.refresh();
      setStatus(s);
      setProgress(s.progress);
      setMessage("");
    } catch (error) {
      setMessage(String(error));
    }
  };

  const toggleKind = (id: string) =>
    setKinds((current) => (current.includes(id) ? current.filter((k) => k !== id) : [...current, id]));

  const openFile = async (hit: DocSearchHit) => {
    try {
      await docSearch.openFile(hit.path);
    } catch (error) {
      setMessage(String(error));
    }
  };

  const revealFile = async (hit: DocSearchHit) => {
    try {
      await docSearch.revealFile(hit.path);
    } catch (error) {
      setMessage(String(error));
    }
  };

  const highlights = result?.highlights ?? [];

  return (
    <div className="ds-view">
      <header className="ds-head">
        <div>
          <h2>문서 검색</h2>
          <p>내 PC 문서를 파일 이름과 내용으로 찾습니다. 한글·PDF·엑셀·워드·파워포인트·텍스트 문서의 내용까지 찾습니다.</p>
        </div>
      </header>

      <label className="hero-search ds-search">
        <Search size={18} />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="찾을 낱말을 입력하세요 (띄어 쓰면 모두 들어 있는 문서)"
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
            전체
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
        <div className="ds-selects">
          <select value={folder} onChange={(event) => setFolder(event.target.value)} aria-label="검색 폴더">
            <option value="">모든 검색 폴더</option>
            {status?.folders.map((f) => (
              <option key={f.path} value={f.path}>
                {folderLabel(f.path)}
              </option>
            ))}
          </select>
          <select value={period} onChange={(event) => setPeriod(event.target.value)} aria-label="수정 기간">
            {PERIODS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>

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
            <Search size={28} />
            <strong>찾을 낱말을 입력하세요.</strong>
            <span>
              파일 이름과 문서 내용에서 함께 찾습니다. 예: <b>예산 편성</b> → 두 낱말이 모두 들어 있는 문서
            </span>
            {status && status.folders.length === 0 && (
              <span>
                검색할 폴더가 없습니다. 아래 <b>검색 폴더 관리</b>에서 폴더를 넣어 주세요.
              </span>
            )}
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
              {result.total === 0 && running && <span> 새 문서를 확인하는 중이라, 끝나면 다시 찾아 봅니다.</span>}
            </div>
            <ul className="ds-list">
              {result.hits.map((hit) => {
                const Icon = iconFor(hit.ext);
                const note = statusNote(hit.status);
                return (
                  <li key={hit.path} className="ds-item" onDoubleClick={() => void openFile(hit)}>
                    <span className={`ds-icon ext-${hit.ext}`}>
                      <Icon size={18} />
                    </span>
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
                      <button className="secondary-button" onClick={() => void openFile(hit)}>
                        열기
                      </button>
                      <button className="secondary-button" onClick={() => void revealFile(hit)} title="폴더 열기">
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

      <footer className="ds-foot">
        <span className="ds-state">
          {running ? (
            <>
              <LoaderCircle size={13} className="ds-spin" />
              {progressText(progress)}
            </>
          ) : status ? (
            <>
              문서 {status.documents.toLocaleString()}개 · 파일 {status.files.toLocaleString()}개
              {status.lastCheck ? ` · 마지막 확인 ${formatTime(status.lastCheck)}` : ""}
            </>
          ) : (
            "불러오는 중…"
          )}
        </span>
        <div>
          <button className="secondary-button" onClick={() => void refresh()} disabled={running}>
            <RefreshCw size={13} />
            지금 다시 읽기
          </button>
          <button className="secondary-button" onClick={() => setManaging(true)}>
            <Settings2 size={13} />
            검색 폴더 관리
          </button>
        </div>
      </footer>

      {managing && status && (
        <FolderManager
          folders={status.folders.map((f) => f.path)}
          missing={status.folders.filter((f) => !f.exists).map((f) => f.path)}
          onCancel={() => setManaging(false)}
          onSave={async (folders) => {
            setManaging(false);
            try {
              const s = await docSearch.setFolders(folders);
              setStatus(s);
              setProgress(s.progress);
              if (folder && !folders.includes(folder)) setFolder("");
            } catch (error) {
              setMessage(String(error));
            }
          }}
        />
      )}
    </div>
  );
}

function FolderManager({
  folders,
  missing,
  onCancel,
  onSave,
}: {
  folders: string[];
  missing: string[];
  onCancel: () => void;
  onSave: (folders: string[]) => void;
}) {
  const [list, setList] = useState(folders);

  const add = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "검색할 폴더 선택" });
    if (typeof chosen === "string" && !list.some((f) => f.toLowerCase() === chosen.toLowerCase())) {
      setList([...list, chosen]);
    }
  };

  return (
    <div className="ds-modal-backdrop" onMouseDown={onCancel}>
      <section className="ds-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <strong>검색 폴더 관리</strong>
          <button onClick={onCancel} title="닫기">
            <X size={17} />
          </button>
        </header>
        <p className="ds-modal-help">
          이 폴더들 안의 파일을 찾습니다(하위 폴더 포함). 숨김·시스템 폴더와 임시 파일은 건너뜁니다.
        </p>
        <ul className="ds-folder-list">
          {list.map((path) => (
            <li key={path}>
              <FolderOpen size={15} />
              <span title={path}>{path}</span>
              {missing.includes(path) && <em>지금 없음</em>}
              <button onClick={() => setList(list.filter((f) => f !== path))} title="빼기">
                <Trash2 size={14} />
              </button>
            </li>
          ))}
          {!list.length && <li className="is-empty">검색할 폴더가 없습니다.</li>}
        </ul>
        <footer>
          <button className="secondary-button" onClick={() => void add()}>
            <FolderPlus size={14} />
            폴더 추가
          </button>
          <div>
            <button className="secondary-button" onClick={onCancel}>
              취소
            </button>
            <button className="primary-button" onClick={() => onSave(list)}>
              저장
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
