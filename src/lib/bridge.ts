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

export async function openToolInBrowser(toolId: string): Promise<void> {
  if (!isTauri()) {
    throw new Error("새 창 열기는 설치된 앱에서 사용할 수 있습니다.");
  }
  return invoke<void>("open_tool_in_browser", { toolId });
}

/** HTML 도구가 내려받으려던 파일을 '다운로드' 폴더에 저장하고, 저장한 경로를 돌려준다.
 *  파일 내용은 JSON 이 아닌 그대로(바이트) 보낸다. 이름은 헤더로(한글이라 인코딩해서). */
export async function saveToolDownload(name: string, bytes: ArrayBuffer): Promise<string> {
  if (!isTauri()) throw new Error("내려받기는 설치된 앱에서 사용할 수 있습니다.");
  return invoke<string>("save_tool_download", new Uint8Array(bytes), {
    headers: { "x-file-name": encodeURIComponent(name) },
  });
}

/** 파일을 그 파일의 기본 프로그램으로 연다(엑셀이면 엑셀). */
export async function openFilePath(path: string): Promise<void> {
  if (!isTauri()) throw new Error("파일 열기는 설치된 앱에서 사용할 수 있습니다.");
  return invoke<void>("open_file_path", { path });
}

/** 사이드바 [업무경감 도구 바로가기]: 업무경감 도구 게시판을 기본 브라우저로 연다. 주소는 Rust 쪽에 있다. */
export async function openWorkToolsBoard(): Promise<void> {
  if (!isTauri()) {
    window.open("https://www.jbe.go.kr/board/view.jbe?boardId=BBS_0000683&menuCd=DOM_000000106011002002&dataSid=1165417", "_blank");
    return;
  }
  return invoke<void>("open_work_tools_board");
}

/** 작업 결과가 저장된 폴더를 탐색기로 연다. */
export async function revealPath(path: string): Promise<void> {
  if (!isTauri()) throw new Error("결과 폴더 열기는 설치된 앱에서 사용할 수 있습니다.");
  return invoke<void>("reveal_path", { path });
}

/** 파일 크기(바이트). 없는 파일·폴더는 null. 앱 밖(브라우저)에서는 모두 null. */
export async function fileSizes(paths: string[]): Promise<(number | null)[]> {
  if (!isTauri() || !paths.length) return paths.map(() => null);
  return invoke<(number | null)[]>("file_sizes", { paths });
}

export type PathKind = "file" | "folder" | "missing";

/** 경로마다 파일인지 폴더인지. 앱 밖(브라우저)에서는 알 수 없어 모두 "missing". */
export async function pathKinds(paths: string[]): Promise<PathKind[]> {
  if (!isTauri() || !paths.length) return paths.map(() => "missing");
  return invoke<PathKind[]>("path_kinds", { paths });
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
  // 미리보기·분석처럼 중간 단계(이름에 "__")는 알리지 않고, 실제 [작업 실행]이 끝났을 때만 알린다.
  const isJob = !toolId.includes("__");
  try {
    const result = await invoke<Record<string, unknown>>("run_native_tool", {
      toolId,
      payload,
    });
    if (isJob) notifyToolFinished(toolId, jobStatus(result), jobMessage(result));
    return result;
  } catch (error) {
    if (isJob) notifyToolFinished(toolId, "failed", error instanceof Error ? error.message : String(error));
    throw error;
  }
}

/** 결과 팝업이 성공이 아니거나(일부 실패·중지·목표 미달) 실패 목록이 있으면 "확인 필요". */
function jobStatus(result: Record<string, unknown>): "done" | "check" {
  const popup = result.popup as { level?: unknown } | undefined;
  if (popup && typeof popup.level === "string" && popup.level !== "success") return "check";
  if (Array.isArray(result.failed) && result.failed.length > 0) return "check";
  if (result.ok === false) return "check";
  return "done";
}

function jobMessage(result: Record<string, unknown>): string {
  if (typeof result.message === "string" && result.message.trim()) return result.message;
  const popup = result.popup as { title?: unknown } | undefined;
  return typeof popup?.title === "string" ? popup.title : "";
}

/** 창이 가려져 있을 때만 Rust 쪽에서 윈도우 알림을 띄운다. 알림 실패는 작업 결과에 영향을 주지 않는다. */
function notifyToolFinished(toolId: string, status: "done" | "check" | "failed", message: string) {
  void invoke<boolean>("notify_tool_finished", { toolId, status, message }).catch(() => undefined);
}

/** 실행 중인 도구에 그만두라고 알린다. */
export async function cancelNativeTool(toolId: string): Promise<void> {
  if (!isTauri()) return;
  return invoke<void>("cancel_native_tool", { toolId });
}

export interface AppPreferences {
  auto_start: boolean;
  close_to_tray: boolean;
  minimize_to_tray: boolean;
  start_minimized: boolean;
  /** 앱 창을 보였다 숨겼다 하는 전역 단축키 */
  toggle_hotkey: string;
  /** 작업이 끝났을 때 창이 가려져 있으면 윈도우 알림 */
  notify_on_finish: boolean;
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
}

export async function getAppPreferences(): Promise<AppPreferences> {
  if (!isTauri()) {
    return {
      auto_start: true,
      close_to_tray: true,
      minimize_to_tray: false,
      start_minimized: true,
      toggle_hotkey: DEFAULT_TOGGLE_HOTKEY,
      notify_on_finish: true,
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
