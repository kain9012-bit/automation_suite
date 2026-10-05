import { invoke } from "@tauri-apps/api/core";

/** 문서 검색(1.4.4) — Rust 쪽 src-tauri/src/docsearch 와 주고받는 값 */

export interface DocSearchProgress {
  /** "scan": 목록 대조 · "read": 바뀐 문서 읽기 */
  phase: "scan" | "read";
  done: number;
  total: number;
  current: string;
}

export interface DocSearchStatus {
  folders: { path: string; exists: boolean }[];
  files: number;
  documents: number;
  pending: number;
  lastCheck: number;
  running: boolean;
  progress: DocSearchProgress | null;
  indexBytes: number;
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

export const docSearch = {
  openScreen: () => invoke<DocSearchStatus>("docsearch_open_screen"),
  status: () => invoke<DocSearchStatus>("docsearch_status"),
  refresh: () => invoke<DocSearchStatus>("docsearch_refresh"),
  setFolders: (folders: string[]) => invoke<DocSearchStatus>("docsearch_set_folders", { folders }),
  search: (query: string, filters: DocSearchFilters) =>
    invoke<DocSearchResult>("docsearch_search", { query, filters }),
  openFile: (path: string) => invoke<void>("docsearch_open_file", { path }),
  revealFile: (path: string) => invoke<void>("docsearch_reveal_file", { path }),
};

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
