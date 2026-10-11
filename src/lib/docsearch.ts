import { invoke } from "@tauri-apps/api/core";

/** 문서 검색(1.4.4) — Rust 쪽 src-tauri/src/docsearch 와 주고받는 값 */

export interface DocSearchProgress {
  /** "scan": 목록 대조 · "read": 바뀐 문서 읽기 · "compact": 색인 정리(1.4.6) */
  phase: "scan" | "read" | "compact";
  done: number;
  total: number;
  current: string;
}

export interface DocSearchStatus {
  /** 사용자가 검색 폴더를 골라 시작했는지. 아니면 먼저 고르게 한다. */
  confirmed: boolean;
  folders: { path: string; exists: boolean; documents: number }[];
  files: number;
  documents: number;
  pending: number;
  lastCheck: number;
  running: boolean;
  progress: DocSearchProgress | null;
  indexBytes: number;
  /** 내용까지 찾는 문서 종류(CONTENT_TYPES 의 id). 나머지는 파일 이름으로만 찾는다. */
  contentTypes: string[];
}

/** 내용까지 찾을 문서 종류(1.4.5). id 와 확장자는 src-tauri/src/docsearch/types.rs 와 같아야 한다. */
export const CONTENT_TYPES: { id: string; label: string; exts: string }[] = [
  { id: "hwp", label: "한글", exts: "hwp · hwpx" },
  { id: "pdf", label: "PDF", exts: "pdf" },
  { id: "word", label: "워드", exts: "docx" },
  { id: "text", label: "텍스트(메모장)", exts: "txt · md" },
  { id: "excel", label: "엑셀", exts: "xlsx · csv" },
  { id: "ppt", label: "파워포인트", exts: "pptx" },
];

export function contentTypeLabel(id: string): string {
  return CONTENT_TYPES.find((t) => t.id === id)?.label ?? id;
}

export interface DocSearchCompactResult {
  /** 정리 전·후 색인 파일 크기(바이트) */
  before: number;
  after: number;
  status: DocSearchStatus;
}

export interface DocSearchFilters {
  kinds: string[];
  folder?: string | null;
  since?: number | null;
}

export interface DocSearchHit {
  path: string;
  name: string;
  folder: string;
  ext: string;
  size: number;
  mtime: number;
  /** ok · name · pending · too_large · cloud · encrypted · distribution · no_text · error */
  status: string;
  snippet: string;
  nameMatch: boolean;
}

export interface DocSearchResult {
  hits: DocSearchHit[];
  total: number;
  highlights: string[];
}

export interface FolderChoice {
  label: string;
  path: string;
}

export interface FolderChoices {
  /** 바탕화면 · 문서 · 다운로드 */
  common: FolderChoice[];
  /** 드라이브 전체(C:\ D:\ …) */
  drives: FolderChoice[];
}

export const docSearch = {
  folderChoices: () => invoke<FolderChoices>("docsearch_folder_choices"),
  openScreen: () => invoke<DocSearchStatus>("docsearch_open_screen"),
  status: () => invoke<DocSearchStatus>("docsearch_status"),
  refresh: () => invoke<DocSearchStatus>("docsearch_refresh"),
  cancel: () => invoke<void>("docsearch_cancel"),
  /** contentTypes 는 처음 고를 때만 넘긴다. 빼면 지금 종류를 그대로 둔다. */
  setFolders: (folders: string[], contentTypes?: string[]) =>
    invoke<DocSearchStatus>("docsearch_set_folders", { folders, contentTypes: contentTypes ?? null }),
  setContentTypes: (contentTypes: string[]) =>
    invoke<DocSearchStatus>("docsearch_set_content_types", { contentTypes }),
  defaultContentTypes: () => invoke<string[]>("docsearch_default_content_types"),
  /** [색인 정리]: 빈 자리를 비워 색인 파일 크기를 줄인다. 그동안 검색은 잠시 멈춘다. */
  compact: () => invoke<DocSearchCompactResult>("docsearch_compact"),
  search: (query: string, filters: DocSearchFilters) =>
    invoke<DocSearchResult>("docsearch_search", { query, filters }),
  openFile: (path: string) => invoke<void>("docsearch_open_file", { path }),
  revealFile: (path: string) => invoke<void>("docsearch_reveal_file", { path }),
  /** 확장자 → 그 PC 탐색기의 아이콘(PNG data URL). 받지 못한 확장자는 빠진다. */
  fileIcons: (exts: string[]) => invoke<Record<string, string>>("docsearch_file_icons", { exts }),
};

const samePath = (a: string, b: string) =>
  a.replace(/[\\/]+$/, "").toLowerCase() === b.replace(/[\\/]+$/, "").toLowerCase();

/** 검색 폴더를 짧게 부르는 이름: 바탕화면 · 문서 · 다운로드 · C: 드라이브 전체 · 폴더 이름 */
export function folderName(path: string, choices: FolderChoices | null): string {
  const known = [...(choices?.common ?? []), ...(choices?.drives ?? [])].find((c) => samePath(c.path, path));
  if (known) return known.label;
  if (/^[a-zA-Z]:[\\/]?$/.test(path)) return `${path.slice(0, 2).toUpperCase()} 드라이브 전체`;
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export function hasPath(list: string[], path: string) {
  return list.some((p) => samePath(p, path));
}

/** 내용 검색이 안 되는 까닭(결과에 표시). 문서가 아닌 파일(name)과 정상(ok)은 표시하지 않는다. */
export function statusNote(status: string): string {
  switch (status) {
    case "pending":
      return "내용 읽는 중";
    case "too_large":
      return "100MB가 넘어 내용 검색 안 됨";
    case "cloud":
      return "원드라이브 온라인 전용 파일이라 내용 검색 안 됨";
    case "encrypted":
      return "암호 문서라 내용 검색 안 됨";
    case "distribution":
      return "배포용 문서라 내용 검색 안 됨";
    case "no_text":
      return "글자가 없는 문서(스캔본 등)";
    case "error":
      return "내용을 읽지 못함";
    default:
      return "";
  }
}

/** 강조할 글자로 나눈 조각들. 대소문자는 가리지 않는다. */
export function splitHighlights(text: string, highlights: string[]): { text: string; mark: boolean }[] {
  const needles = highlights.filter((h) => h.length > 0).map((h) => h.toLowerCase());
  if (!needles.length || !text) return [{ text, mark: false }];
  const lower = text.toLowerCase();
  // 대소문자를 바꾸면 길이가 달라지는 글자가 섞이면 강조하지 않는다(위치가 어긋나므로).
  if (lower.length !== text.length) return [{ text, mark: false }];
  const parts: { text: string; mark: boolean }[] = [];
  let i = 0;
  let plain = "";
  while (i < text.length) {
    const hit = needles.find((n) => lower.startsWith(n, i));
    if (hit) {
      if (plain) parts.push({ text: plain, mark: false });
      plain = "";
      parts.push({ text: text.slice(i, i + hit.length), mark: true });
      i += hit.length;
    } else {
      plain += text[i];
      i += 1;
    }
  }
  if (plain) parts.push({ text: plain, mark: false });
  return parts;
}
