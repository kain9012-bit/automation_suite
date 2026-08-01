import { invoke } from "@tauri-apps/api/core";
import type { ToolManifest } from "../types";

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

export const DEFAULT_TOGGLE_HOTKEY = "Ctrl+Alt+Space";

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
      auto_start: false,
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
