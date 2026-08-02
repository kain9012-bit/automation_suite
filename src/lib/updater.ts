import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
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

export const isTauriRuntime = () => "__TAURI_INTERNALS__" in window;

/** 받아 두었지만 아직 적용하지 않은 업데이트가 생기면 알린다. */
export const UPDATE_READY = "jbedu:update-ready";

// 내려받은 업데이트를 적용할 때까지 들고 있는다.
let pending: Awaited<ReturnType<typeof check>> = null;
let pendingVersion = "";

export function pendingUpdateVersion() {
  return pending ? pendingVersion : "";
}

/**
 * 새 버전이 있으면 조용히 내려받기만 한다. 설치는 하지 않는다.
 * 작업 도중에 앱이 예고 없이 재시작되는 일을 막기 위한 것이다.
 */
export async function downloadUpdateIfAvailable(
  onProgress?: (message: string) => void,
): Promise<string> {
  if (!isTauriRuntime()) return "";

  const update = await check();
  if (!update) return "";

  // 미뤄 둔 사이에 더 새 버전이 나왔으면 그쪽을 받는다.
  if (pending && pendingVersion === update.version) return pendingVersion;

  onProgress?.(`새 버전 ${update.version}을 내려받는 중입니다.`);
  let downloaded = 0;
  let total = 0;
  await update.download((event) => {
    if (event.event === "Started") {
      total = event.data.contentLength ?? 0;
    } else if (event.event === "Progress") {
      downloaded += event.data.chunkLength;
      if (total > 0) {
        onProgress?.(`새 버전 내려받는 중 ${Math.round((downloaded / total) * 100)}%`);
      }
    }
  });

  pending = update;
  pendingVersion = update.version;
  onProgress?.(`새 버전 ${update.version} 준비 완료`);
  window.dispatchEvent(new CustomEvent(UPDATE_READY));
  return update.version;
}

/** 받아 둔 업데이트를 설치하고 앱을 다시 시작한다. */
export async function applyPendingUpdate(
  onProgress?: (message: string) => void,
): Promise<void> {
  if (!pending) return;
  onProgress?.("업데이트를 적용하고 다시 시작합니다.");
  await pending.install();
  await relaunch();
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

