import { invoke } from "@tauri-apps/api/core";
import type { ContextMenuEntry, ContextRequest, ToolManifest } from "../types";

const isTauri = () => "__TAURI_INTERNALS__" in window;

export async function listTools(): Promise<ToolManifest[]> {
  if (isTauri()) {
    return invoke<ToolManifest[]>("list_tools");
  }
  const response = await fetch("/dev-tools.json");
  if (!response.ok) return [];
  return response.json() as Promise<ToolManifest[]>;
}

export async function readToolHtml(toolId: string): Promise<string> {
  if (isTauri()) {
    return invoke<string>("read_tool_html", { toolId });
  }
  const response = await fetch(`/dev-html/${toolId}`);
  if (!response.ok) throw new Error("HTML 도구를 불러오지 못했습니다.");
  return response.text();
}

export async function openToolInBrowser(toolId: string): Promise<void> {
  if (!isTauri()) {
    throw new Error("새 창 열기는 설치된 앱에서 사용할 수 있습니다.");
  }
  return invoke<void>("open_tool_in_browser", { toolId });
}

// ── 탐색기 우클릭 메뉴 ───────────────────────────────────────────────

/** 우클릭 메뉴에 넣을 수 있는 도구와 지금 등록되어 있는지. */
export async function listContextMenu(): Promise<ContextMenuEntry[]> {
  if (!isTauri()) return [];
  return invoke<ContextMenuEntry[]>("list_context_menu");
}

/** 도구 하나를 우클릭 메뉴에 등록하거나 해제한다. */
export async function setContextMenu(toolId: string, enabled: boolean): Promise<void> {
  if (!isTauri()) throw new Error("우클릭 메뉴는 설치된 앱에서 설정할 수 있습니다.");
  return invoke<void>("set_context_menu", { toolId, enabled });
}

/** 등록된 우클릭 메뉴를 전부 지운다. 몇 개를 지웠는지 돌려준다. */
export async function clearContextMenus(): Promise<number> {
  if (!isTauri()) throw new Error("우클릭 메뉴는 설치된 앱에서 설정할 수 있습니다.");
  return invoke<number>("clear_context_menus");
}

/**
 * 앱이 꺼져 있던 상태에서 우클릭으로 실행된 경우, 화면이 준비된 뒤 요청을 가져온다.
 * 한 번 가져가면 비워지므로 같은 요청이 두 번 열리지 않는다.
 */
export async function takeContextRequest(): Promise<ContextRequest | null> {
  if (!isTauri()) return null;
  return (await invoke<ContextRequest | null>("take_context_request")) ?? null;
}

/** 우클릭 요청이 도착했을 때 Rust가 보내는 이벤트 이름. */
export const CONTEXT_OPEN_EVENT = "context-open";

/** 작업 결과가 저장된 폴더를 탐색기로 연다. */
export async function revealPath(path: string): Promise<void> {
  if (!isTauri()) throw new Error("결과 폴더 열기는 설치된 앱에서 사용할 수 있습니다.");
  return invoke<void>("reveal_path", { path });
}

/** 도구가 돌려준 결과에서 열어 볼 만한 경로를 찾는다. */
export function resultPath(result: Record<string, unknown>): string {
  const direct = result.output ?? result.output_path ?? result.folder;
  if (typeof direct === "string" && direct.trim()) return direct;
  const nested = result.result;
  if (nested && typeof nested === "object") {
    const inner = nested as Record<string, unknown>;
    for (const key of ["output_folder", "output_path", "output", "folder"]) {
      const value = inner[key];
      if (typeof value === "string" && value.trim()) return value;
    }
  }
  const outputs = result.outputs;
  if (Array.isArray(outputs) && outputs.length) {
    const first = outputs[0] as Record<string, unknown>;
    if (typeof first?.path === "string") return first.path;
  }
  return "";
}

export async function runNativeTool(
  toolId: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (!isTauri()) {
    throw new Error("네이티브 도구는 Tauri 앱에서 실행할 수 있습니다.");
  }
  return invoke<Record<string, unknown>>("run_native_tool", {
    toolId,
    payload,
  });
}

export interface AppPreferences {
  auto_start: boolean;
  close_to_tray: boolean;
  minimize_to_tray: boolean;
  start_minimized: boolean;
  /** 앱 창을 보였다 숨겼다 하는 전역 단축키 */
  toggle_hotkey: string;
}

export const DEFAULT_TOGGLE_HOTKEY = "Ctrl+Alt+J";

/** 설정이 저장되면 앱 전체가 알아차리도록 알린다. */
export const PREFERENCES_CHANGED = "jbedu:preferences-changed";

export interface MacroActionPayload {
  id: string;
  name: string;
  type: string;
  target?: string;
  arguments?: string;
  hotkey?: string;
  color?: string;
  size?: string;
  steps?: MacroActionPayload[];
}

export async function getAppPreferences(): Promise<AppPreferences> {
  if (!isTauri()) {
    return {
      auto_start: true,
      close_to_tray: true,
      minimize_to_tray: true,
      start_minimized: true,
      toggle_hotkey: DEFAULT_TOGGLE_HOTKEY,
    };
  }
  return invoke<AppPreferences>("get_app_preferences");
}

export async function setAppPreferences(preferences: AppPreferences): Promise<AppPreferences> {
  if (!isTauri()) return preferences;
  const saved = await invoke<AppPreferences>("set_app_preferences", { preferences });
  window.dispatchEvent(new CustomEvent(PREFERENCES_CHANGED));
  return saved;
}

export async function runMacroAction(action: MacroActionPayload): Promise<Record<string, unknown>> {
  if (!isTauri()) {
    throw new Error("빠른 실행은 설치된 앱에서 사용할 수 있습니다.");
  }
  return invoke<Record<string, unknown>>("run_macro_action", { action });
}
