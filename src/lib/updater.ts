import { invoke } from "@tauri-apps/api/core";

export interface ToolUpdateInfo {
  id: string;
  name: string;
  current_version?: string;
  version: string;
  size: number;
  is_new: boolean;
}

export interface ToolUpdateCheck {
  configured: boolean;
  updates: ToolUpdateInfo[];
  message: string;
}

export interface ToolInstallResult {
  installed: string[];
  message: string;
}

/** 게시글 표식에서 읽어 온 새 버전. */
export interface BoardUpdate {
  version: string;
  download: string;
  signature: string;
}

export interface BoardUpdateCheck {
  configured: boolean;
  current: string;
  update: BoardUpdate | null;
  message: string;
}

export const isTauriRuntime = () => "__TAURI_INTERNALS__" in window;

/** 받아 두었지만 아직 적용하지 않은 업데이트가 생기면 알린다. */
export const UPDATE_READY = "jbedu:update-ready";

// 내려받아 서명까지 확인한 설치본을 적용할 때까지 들고 있는다.
let pendingPath = "";
let pendingVersion = "";
// 마지막 확인에서 게시판이 돌려준 설명. 새 버전이 없을 때 무슨 상태인지 알려 준다.
let lastMessage = "";

export function pendingUpdateVersion() {
  return pendingVersion;
}

/** 마지막 확인 결과 설명. 표식이 잘못돼 있으면 여기서 드러난다. */
export function lastCheckMessage() {
  return lastMessage;
}

/**
 * 새 버전이 있으면 조용히 내려받기만 한다. 설치는 하지 않는다.
 * 작업 도중에 앱이 예고 없이 재시작되는 일을 막기 위한 것이다.
 *
 * 확인·내려받기·서명 검증은 모두 Rust에서 한다. 서명이 어긋나면 여기서 오류가 난다.
 */
export async function downloadUpdateIfAvailable(
  onProgress?: (message: string) => void,
): Promise<string> {
  if (!isTauriRuntime()) return "";

  const check = await invoke<BoardUpdateCheck>("check_board_update");
  lastMessage = check.message;
  if (!check.configured || !check.update) return "";

  // 미뤄 둔 사이에 더 새 버전이 나왔으면 그쪽을 받는다.
  if (pendingVersion === check.update.version) return pendingVersion;

  onProgress?.(`새 버전 ${check.update.version}을 내려받는 중입니다.`);
  const path = await invoke<string>("download_board_update", { update: check.update });

  pendingPath = path;
  pendingVersion = check.update.version;
  onProgress?.(`새 버전 ${check.update.version} 준비 완료`);
  window.dispatchEvent(new CustomEvent(UPDATE_READY));
  return pendingVersion;
}

/**
 * 받아 둔 설치본을 실행한다. 설치가 끝나면 설치본이 앱을 다시 실행하므로
 * 여기서 따로 재시작하지 않는다.
 */
export async function applyPendingUpdate(
  onProgress?: (message: string) => void,
): Promise<void> {
  if (!pendingPath) return;
  onProgress?.("업데이트를 적용하고 다시 시작합니다.");
  await invoke("apply_board_update", { path: pendingPath });
}

export async function checkToolUpdates(): Promise<ToolUpdateCheck> {
  if (!isTauriRuntime()) {
    return {
      configured: false,
      updates: [],
      message: "도구 업데이트는 데스크톱 앱에서 확인할 수 있습니다.",
    };
  }
  return invoke<ToolUpdateCheck>("check_tool_updates");
}

export async function installToolUpdates(): Promise<ToolInstallResult> {
  return invoke<ToolInstallResult>("install_tool_updates");
}
