import { runMacroAction, type MacroActionPayload } from "./bridge";

/**
 * 빠른 실행 버튼 묶음을 저장하는 곳과, 버튼을 실행하는 공용 함수.
 *
 * 버튼 편집 화면(QuickLauncher)은 홈에서만 보이지만, 버튼 단축키는 앱이 떠 있는
 * 내내 살아 있어야 한다. 그래서 단축키 등록은 App 에서 하고(useQuickLauncherHotkeys),
 * 두 쪽이 이 모듈을 통해 같은 저장값과 실행 결과를 나눠 쓴다.
 */

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

export interface DeckPage {
  id: string;
  name: string;
  actions: DeckAction[];
}

export interface DeckRecent {
  name: string;
  time: string;
}

export interface DeckState {
  activePageId: string;
  pages: DeckPage[];
  recent: DeckRecent[];
}

// 기존 슬라이드 패널이 쓰던 키를 그대로 이어받아 등록해 둔 버튼이 사라지지 않게 한다.
export const DECK_STORAGE_KEY = "jbedu-suite:macro-deck";

/** 버튼 묶음이 바뀌었을 때 단축키를 다시 등록하도록 알리는 이벤트. */
export const DECK_CHANGED = "jbedu:macro-deck-changed";

export function readStoredDeck(): DeckState | null {
  try {
    const saved = JSON.parse(localStorage.getItem(DECK_STORAGE_KEY) || "null") as DeckState | null;
    return saved?.pages?.length ? saved : null;
  } catch {
    return null;
  }
}

export function writeStoredDeck(deck: DeckState) {
  try {
    localStorage.setItem(DECK_STORAGE_KEY, JSON.stringify(deck));
  } catch {
    // 저장이 막혀도 실행은 계속한다.
  }
  window.dispatchEvent(new CustomEvent(DECK_CHANGED));
}

/** 지금 보고 있는 페이지. 저장값이 어긋나 있으면 첫 페이지. */
export function activeDeckPage(deck: DeckState): DeckPage | undefined {
  return deck.pages.find((page) => page.id === deck.activePageId) ?? deck.pages[0];
}

export type DeckRunEvent =
  | { phase: "start"; action: DeckAction }
  | { phase: "done"; action: DeckAction; entry: DeckRecent; message: string }
  | { phase: "failed"; action: DeckAction; message: string };

let runListener: ((event: DeckRunEvent) => void) | null = null;

/**
 * 버튼 편집 화면이 떠 있는 동안 실행 상황을 받아 상태 줄과 최근 기록을 고친다.
 * 화면이 없을 때는 최근 기록을 저장값에 바로 적는다.
 */
export function listenDeckRuns(listener: (event: DeckRunEvent) => void) {
  runListener = listener;
  return () => {
    if (runListener === listener) runListener = null;
  };
}

export async function runDeckAction(action: DeckAction) {
  runListener?.({ phase: "start", action });
  try {
    const result = await runMacroAction(action);
    const entry: DeckRecent = {
      name: action.name,
      time: new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
    };
    const message = String(result.message || `${action.name} 실행 완료`);
    if (runListener) {
      runListener({ phase: "done", action, entry, message });
    } else {
      const deck = readStoredDeck();
      if (deck) writeStoredDeck({ ...deck, recent: [entry, ...deck.recent].slice(0, 10) });
    }
  } catch (error) {
    runListener?.({ phase: "failed", action, message: String(error) });
  }
}
