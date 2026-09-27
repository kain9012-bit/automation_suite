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
  source?: "builtin" | "user";
  has_html?: boolean;
}

export type View =
  | { kind: "home" }
  | { kind: "favorites" }
  | { kind: "recent" }
  | { kind: "category"; category: string }
  | { kind: "settings" }
  | { kind: "tool"; tool: ToolManifest };
