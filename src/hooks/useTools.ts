import { useCallback, useEffect, useMemo, useState } from "react";
import { listTools } from "../lib/bridge";
import type { ToolManifest } from "../types";

const FAVORITES_KEY = "jbedu-suite:favorites";
const RECENT_KEY = "jbedu-suite:recent";
const CATEGORY_ORDER = [
  "엑셀·데이터",
  "PDF·문서",
  "수집·추출",
  "업무 자동화",
  "간단 도구",
];


function readIds(key: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(key) || "[]") as string[];
  } catch {
    return [];
  }
}

export function useTools() {
  const [tools, setTools] = useState<ToolManifest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [favorites, setFavorites] = useState<string[]>(() =>
    readIds(FAVORITES_KEY),
  );
  const [recent, setRecent] = useState<string[]>(() => readIds(RECENT_KEY));

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setTools(await listTools());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void refresh(), [refresh]);

  const categories = useMemo(
    () => {
      const found = new Set(tools.map((tool) => tool.top_tab));
      const ordered = CATEGORY_ORDER.filter((category) => found.delete(category));
      return [...ordered, ...Array.from(found)];
    },
    [tools],
  );

  const toggleFavorite = useCallback((id: string) => {
    setFavorites((current) => {
      const next = current.includes(id)
        ? current.filter((item) => item !== id)
        : [id, ...current];
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const markRecent = useCallback((id: string) => {
    setRecent((current) => {
      const next = [id, ...current.filter((item) => item !== id)].slice(0, 20);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const toolsByIds = useCallback(
    (ids: string[]) => {
      const index = new Map(tools.map((tool) => [tool.id, tool]));
      return ids.flatMap((id) => {
        const tool = index.get(id);
        return tool ? [tool] : [];
      });
    },
    [tools],
  );

  return {
    tools,
    loading,
    error,
    categories,
    favorites,
    recent,
    favoriteTools: toolsByIds(favorites),
    recentTools: toolsByIds(recent),
    toggleFavorite,
    markRecent,
    refresh,
  };
}
