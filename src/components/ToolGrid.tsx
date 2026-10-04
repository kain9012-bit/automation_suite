import { Globe2, Star } from "lucide-react";
import { toolIcon, toolTone } from "../lib/toolIcons";
import type { ToolManifest } from "../types";

interface ToolGridProps {
  title: string;
  description?: string;
  tools: ToolManifest[];
  favorites: string[];
  query?: string;
  onOpen: (tool: ToolManifest) => void;
  onToggleFavorite: (id: string) => void;
}

/** 기능 아이콘(도구별)과 탭 색. 정하는 곳은 lib/toolIcons.ts */
function ToolGlyph({ tool }: { tool: ToolManifest }) {
  const Icon = toolIcon(tool);
  return <Icon size={21} />;
}

export function ToolGrid({
  title,
  description,
  tools,
  favorites,
  query = "",
  onOpen,
  onToggleFavorite,
}: ToolGridProps) {
  const normalized = query.trim().toLocaleLowerCase();
  const filtered = normalized
    ? tools.filter((tool) =>
        [
          tool.name,
          tool.description,
          tool.top_tab,
          ...(tool.keywords ?? []),
        ]
          .join(" ")
          .toLocaleLowerCase()
          .includes(normalized),
      )
    : tools;

  return (
    <section className="tool-section">
      <div className="section-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        <span className="count-badge">{filtered.length}개</span>
      </div>
      {filtered.length ? (
        <div className="tool-grid">
          {filtered.map((tool, index) => {
            const favorite = favorites.includes(tool.id);
            return (
              <article
                className="tool-card stagger-item"
                style={{ animationDelay: `${Math.min(index, 10) * 25}ms` }}
                key={tool.id}
                // 카드 어디를 눌러도 바로 연다. 키보드로는 Tab 으로 옮겨 Enter/Space.
                role="button"
                tabIndex={0}
                title={`${tool.name} 열기`}
                onClick={() => onOpen(tool)}
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onOpen(tool);
                  }
                }}
              >
                <div className={`tool-icon tone-${toolTone(tool)}`}>
                  <ToolGlyph tool={tool} />
                </div>
                <button
                  className={`favorite-button ${favorite ? "is-active" : ""}`}
                  onClick={(event) => {
                    // 별을 눌렀을 때 카드가 같이 열리지 않게 한다.
                    event.stopPropagation();
                    onToggleFavorite(tool.id);
                  }}
                  aria-label={
                    favorite ? "즐겨찾기에서 제거" : "즐겨찾기에 추가"
                  }
                >
                  <Star size={16} fill={favorite ? "currentColor" : "none"} />
                </button>
                <div className="tool-copy">
                  <div className="tool-meta">
                    <span>{tool.top_tab}</span>
                  </div>
                  <h3>{tool.name}</h3>
                  <p>{tool.description || "업무 자동화 도구"}</p>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <Globe2 size={28} />
          <strong>조건에 맞는 도구가 없습니다.</strong>
          <span>검색어를 바꾸거나 다른 분류를 선택해 보세요.</span>
        </div>
      )}
    </section>
  );
}
