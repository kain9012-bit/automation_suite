import {
  ChevronRight,
  Command,
  Moon,
  PanelLeft,
  PanelsTopLeft,
  RefreshCw,
  Sun,
} from "lucide-react";

interface HeaderProps {
  title: string;
  subtitle?: string;
  dark: boolean;
  onToggleSidebar: () => void;
  onToggleDark: () => void;
  onOpenCommand: () => void;
  onToggleMacro: () => void;
  onRefresh: () => void;
}

export function Header({
  title,
  subtitle,
  dark,
  onToggleSidebar,
  onToggleDark,
  onRefresh,
  onOpenCommand,
  onToggleMacro,
}: HeaderProps) {
  return (
    <header className="app-header">
      <div className="header-leading">
        <button
          className="icon-button"
          onClick={onToggleSidebar}
          aria-label="사이드바 접기"
        >
          <PanelLeft size={18} />
        </button>
        <div className="breadcrumb">
          <span>업무도구</span>
          <ChevronRight size={14} />
          <strong>{title}</strong>
          {subtitle && <small>{subtitle}</small>}
        </div>
      </div>
      <div className="header-actions">
        <button className="header-command" type="button" onClick={onOpenCommand} data-tour="search">
          <Command size={15} />
          <span>명령 검색</span>
          <kbd>Ctrl K</kbd>
        </button>
        <button
          className="icon-button"
          onClick={onRefresh}
          aria-label="도구 새로고침"
        >
          <RefreshCw size={17} />
        </button>
        <button
          className="header-command macro-command"
          type="button"
          onClick={onToggleMacro}
          data-tour="macro-toggle"
        >
          <PanelsTopLeft size={15} /><span>빠른 실행</span>
        </button>
        <button
          className="icon-button"
          onClick={onToggleDark}
          aria-label="화면 테마 변경"
        >
          {dark ? <Sun size={17} /> : <Moon size={17} />}
        </button>
      </div>
    </header>
  );
}
