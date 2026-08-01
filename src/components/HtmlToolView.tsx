import { useEffect, useMemo, useState } from "react";
import { ExternalLink, LoaderCircle, RotateCw } from "lucide-react";
import { readToolHtml } from "../lib/bridge";
import type { ToolManifest } from "../types";

export function HtmlToolView({ tool }: { tool: ToolManifest }) {
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    readToolHtml(tool.id)
      .then((content) => {
        if (live) setHtml(content);
      })
      .catch((reason) => {
        if (live) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [tool.id, reloadKey]);

  const sandbox = useMemo(
    () =>
      [
        "allow-downloads",
        "allow-forms",
        "allow-modals",
        "allow-popups",
        "allow-same-origin",
        "allow-scripts",
      ].join(" "),
    [],
  );

  return (
    <div className="tool-workspace">
      <div className="workspace-toolbar">
        <div>
          <strong>{tool.name}</strong>
          <span>HTML 도구 · 통합 프레임</span>
        </div>
        <div className="toolbar-actions">
          <button
            className="secondary-button"
            onClick={() => setReloadKey((value) => value + 1)}
          >
            <RotateCw size={15} />
            새로고침
          </button>
          <button
            className="secondary-button"
            onClick={() => {
              const blob = new Blob([html], { type: "text/html" });
              window.open(URL.createObjectURL(blob), "_blank");
            }}
          >
            <ExternalLink size={15} />
            새 창
          </button>
        </div>
      </div>
      <div className="html-frame-shell">
        {loading && (
          <div className="frame-message">
            <LoaderCircle className="spin" size={25} />
            <span>도구를 불러오는 중입니다.</span>
          </div>
        )}
        {error && (
          <div className="frame-message is-error">
            <strong>도구를 열지 못했습니다.</strong>
            <span>{error}</span>
          </div>
        )}
        {!loading && !error && (
          <iframe
            key={reloadKey}
            title={tool.name}
            srcDoc={html}
            sandbox={sandbox}
            className="html-tool-frame"
          />
        )}
      </div>
    </div>
  );
}
