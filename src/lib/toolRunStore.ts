import { listen } from "@tauri-apps/api/event";
import type { ResultPopup } from "../components/ResultDialog";

/**
 * 도구 실행 상태를 화면(컴포넌트) 바깥에 둔다.
 *
 * 실행 중에 다른 화면으로 갔다 오면 도구 화면은 새로 만들어진다. 상태가 화면 안에만
 * 있으면 돌아왔을 때 멈춘 것처럼 보이고, 중지 버튼이 꺼지고, 같은 도구를 또 돌릴 수
 * 있었다. 여기 두면 돌아와도 실행 중으로 보이고, 끝나면 결과가 그대로 뜬다.
 */
export interface ToolRunState {
  running: boolean;
  stopping: boolean;
  log: string[];
  /** 결과를 열어 볼 경로. */
  done: string;
  /** 아직 보여 주지 않은(또는 닫지 않은) 결과 팝업. */
  popup: ResultPopup | null;
  /** 도구가 바꾼 입력 경로(파일명 변경 등). 화면이 받아 가면 비운다. */
  nextInputs: string[] | null;
}

const EMPTY: ToolRunState = {
  running: false,
  stopping: false,
  log: [],
  done: "",
  popup: null,
  nextInputs: null,
};

const states = new Map<string, ToolRunState>();
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

export function subscribeToolRuns(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getToolRun(toolId: string): ToolRunState {
  return states.get(toolId) ?? EMPTY;
}

export function updateToolRun(toolId: string, change: (current: ToolRunState) => Partial<ToolRunState>) {
  const current = getToolRun(toolId);
  states.set(toolId, { ...current, ...change(current) });
  notify();
}

export function appendToolLog(toolId: string, ...lines: string[]) {
  const usable = lines.filter(Boolean);
  if (!usable.length) return;
  updateToolRun(toolId, (current) => ({ log: [...current.log, ...usable] }));
}

/**
 * 화면을 새로 열 때 부른다. 실행 중이거나 아직 못 본 결과가 있으면 그대로 두고,
 * 아니면 예전처럼 빈 상태로 시작한다.
 */
export function openToolRun(toolId: string) {
  ensureProgressListener();
  const current = states.get(toolId);
  if (current && (current.running || current.popup)) return;
  // 화면이 그려지는 중에 부르므로 알리지 않는다. 이 도구를 보고 있는 다른 화면은 없다.
  states.set(toolId, { ...EMPTY });
}

/** 이미 돌고 있으면 false. 같은 도구를 겹쳐 돌리지 않는다. */
export function beginToolRun(toolId: string, firstLine: string): boolean {
  if (getToolRun(toolId).running) return false;
  updateToolRun(toolId, (current) => ({
    running: true,
    stopping: false,
    popup: null,
    log: [...current.log, firstLine],
  }));
  return true;
}

// 진행 안내는 화면이 아니라 여기서 받는다. 화면이 잠깐 사라져 있어도 기록이 끊기지 않고,
// 화면이 여러 번 만들어져도 리스너는 하나뿐이다.
let progressListening = false;

function ensureProgressListener() {
  if (progressListening || typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
  progressListening = true;
  void listen<{ toolId: string; text: string }>("tool-progress", (event) => {
    // 도구 하나가 보조 동작을 가질 수 있어 앞부분으로 견준다.
    const toolId = event.payload.toolId.split("__")[0];
    // 이 화면이 한 번도 연 적 없는 도구(전용 화면을 쓰는 도구)는 건드리지 않는다.
    if (!states.has(toolId)) return;
    appendToolLog(toolId, event.payload.text);
  }).catch(() => {
    progressListening = false;
  });
}
