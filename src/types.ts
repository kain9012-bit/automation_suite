export type ToolType =
  | "html"
  | "internal_python"
  | "external_exe"
  | "tk_python";

export interface ToolManifest {
  id: string;
  name: string;
  top_tab: string;
  type: ToolType;
  entry: string;
  icon?: string;
  description?: string;
  submenu_group?: string;
  order?: number;
  enabled?: boolean;
  version?: string;
  keywords?: string[];
  /** 이 블록이 있는 도구만 탐색기 우클릭 메뉴에 등록할 수 있다. */
  context_menu?: ContextMenuSpec;
  source?: "builtin" | "user";
  has_html?: boolean;
}

export interface ContextMenuSpec {
  /** 확장자 목록(["pdf", "xlsx"]) 또는 ["folder"] */
  targets: string[];
  label: string;
  multiple?: boolean;
}

/** 설정 화면에서 켜고 끄는 우클릭 메뉴 한 줄. */
export interface ContextMenuEntry {
  id: string;
  name: string;
  label: string;
  targets: string[];
  enabled: boolean;
}

/** 우클릭으로 들어온 요청. 경로는 Rust가 잠깐 모았다가 한 번에 준다. */
export interface ContextRequest {
  toolId: string;
  paths: string[];
}

export type View =
  | { kind: "home" }
  | { kind: "favorites" }
  | { kind: "recent" }
  | { kind: "category"; category: string }
  | { kind: "settings" }
  // presetPaths: 탐색기 우클릭으로 들어온 경로. 도구 화면이 이걸 미리 담는다.
  | { kind: "tool"; tool: ToolManifest; presetPaths?: string[] };
