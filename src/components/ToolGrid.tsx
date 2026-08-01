import {
  ArrowUpRight,
  Code2,
  FileSpreadsheet,
  FileText,
  Globe2,
  Star,
} from "lucide-react";
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

function ToolGlyph({ tool }: { tool: ToolManifest }) {
  if (tool.type === "html") return <Globe2 size={21} />;
  if (tool.top_tab === "엑셀·데이터") return <FileSpreadsheet size={21} />;
  if (tool.top_tab === "PDF·문서") return <FileText size={21} />;
  return <Code2 size={21} />;
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
                onDoubleClick={() => onOpen(tool)}
              >
                <div className={`tool-icon type-${tool.type}`}>
                  <ToolGlyph tool={tool} />
                </div>
                <button
                  className={`favorite-button ${favorite ? "is-active" : ""}`}
                  onClick={() => onToggleFavorite(tool.id)}
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
                <button className="open-tool" onClick={() => onOpen(tool)}>
                  열기
                  <ArrowUpRight size={15} />
                </button>
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
