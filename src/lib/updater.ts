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

export async function installAppUpdateIfAvailable(
  onProgress?: (message: string) => void,
): Promise<boolean> {
  if (!isTauriRuntime()) return false;
  const update = await check();
  if (!update) return false;
  onProgress?.(`새 앱 버전 ${update.version}을 내려받는 중입니다.`);
  let downloaded = 0;
  let total = 0;
  await update.downloadAndInstall((event) => {
    if (event.event === "Started") {
      total = event.data.contentLength ?? 0;
    } else if (event.event === "Progress") {
      downloaded += event.data.chunkLength;
      if (total > 0) {
        onProgress?.(`앱 업데이트 ${Math.round((downloaded / total) * 100)}%`);
      }
    } else if (event.event === "Finished") {
      onProgress?.("앱 업데이트 설치를 마쳤습니다. 다시 시작합니다.");
    }
  });
  await relaunch();
  return true;
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

