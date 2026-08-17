import {
  BarChart3,
  Clock3,
  FileSpreadsheet,
  FileText,
  FolderSearch,
  Home,
  Settings,
  Sparkles,
  Star,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import type { View } from "../types";

interface SidebarProps {
  collapsed: boolean;
  categories: string[];
  activeView: View;
  onNavigate: (view: View) => void;
}

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  "엑셀·데이터": FileSpreadsheet,
  "PDF·문서": FileText,
  "수집·추출": FolderSearch,
  "업무 자동화": Workflow,
  "간단 도구": Sparkles,
};

function isActive(view: View, target: View) {
  if (view.kind !== target.kind) return false;
  if (view.kind === "category" && target.kind === "category") {
    return view.category === target.category;
  }
  return true;
}

function NavigationButton({
  icon: Icon,
  label,
  collapsed,
  active,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  collapsed: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`sidebar-item ${active ? "is-active" : ""}`}
      onClick={onClick}
      title={collapsed ? label : undefined}
    >
      <Icon size={18} />
      {!collapsed && <span>{label}</span>}
    </button>
  );
}

export function Sidebar({
  collapsed,
  categories,
  activeView,
  onNavigate,
}: SidebarProps) {
  const [appVersion, setAppVersion] = useState("");
  useEffect(() => {
    void getVersion()
      .then(setAppVersion)
      .catch(() => undefined);
  }, []);

  return (
    <aside className={`sidebar ${collapsed ? "is-collapsed" : ""}`} data-tour="sidebar">
      <div className="brand">
        <div className="brand-mark">JB</div>
        {!collapsed && (
          <div>
            <strong>JB업무ON</strong>
            <span>전북교육 업무도구 모음</span>
          </div>
        )}
      </div>

      <nav className="sidebar-nav">
        <div className="nav-group">
          {!collapsed && <p className="nav-label">탐색</p>}
          <NavigationButton
            icon={Home}
            label="홈"
            collapsed={collapsed}
            active={isActive(activeView, { kind: "home" })}
            onClick={() => onNavigate({ kind: "home" })}
          />
          <NavigationButton
            icon={Star}
            label="즐겨찾기"
            collapsed={collapsed}
            active={isActive(activeView, { kind: "favorites" })}
            onClick={() => onNavigate({ kind: "favorites" })}
          />
          <NavigationButton
            icon={Clock3}
            label="최근 사용"
            collapsed={collapsed}
            active={isActive(activeView, { kind: "recent" })}
            onClick={() => onNavigate({ kind: "recent" })}
          />
        </div>

        <div className="nav-group">
          {!collapsed && <p className="nav-label">도구</p>}
          {categories.map((category) => {
            const Icon = CATEGORY_ICONS[category] ?? BarChart3;
            return (
              <NavigationButton
                key={category}
                icon={Icon}
                label={category}
                collapsed={collapsed}
                active={
                  activeView.kind === "category" &&
                  activeView.category === category
                }
                onClick={() =>
                  onNavigate({ kind: "category", category })
                }
              />
            );
          })}
        </div>
      </nav>

      <div className="sidebar-bottom">
        {!collapsed && (
          <div className="support-card" data-tour="support">
            <strong>문의</strong>
            <span>전북특별자치도교육청</span>
            <span>정책기획과 빅데이터팀</span>
            <b>063-239-3176</b>
          </div>
        )}
        <div data-tour="settings">
          <NavigationButton
            icon={Settings}
            label="설정"
            collapsed={collapsed}
            active={isActive(activeView, { kind: "settings" })}
            onClick={() => onNavigate({ kind: "settings" })}
          />
        </div>
        {!collapsed && appVersion && <span className="version">v{appVersion}</span>}
      </div>
    </aside>
  );
}
