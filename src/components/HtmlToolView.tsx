import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, FolderOpen, LoaderCircle, RotateCw } from "lucide-react";
import { openToolInBrowser, readToolHtml, revealPath, saveToolDownload } from "../lib/bridge";
import { injectDownloadBridge, readDownloadMessage } from "../lib/htmlToolDownload";
import type { ToolManifest } from "../types";

export function HtmlToolView({ tool }: { tool: ToolManifest }) {
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  // 새 창 열기 실패는 도구 화면을 가리지 않고 도구 이름 옆에만 알린다.
  const [notice, setNotice] = useState("");
  // 도구가 내려받은 파일: 앱이 '다운로드' 폴더에 저장한 경로
  const [saved, setSaved] = useState("");
  const frameRef = useRef<HTMLIFrameElement>(null);

  // 도구 안의 내려받기 링크를 가로챈 내용이 오면 '다운로드' 폴더에 저장한다(src/lib/htmlToolDownload.ts).
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!frameRef.current || event.source !== frameRef.current.contentWindow) return;
      const download = readDownloadMessage(event.data);
      if (!download) return;
      setNotice("");
      void saveToolDownload(download.name, download.bytes)
        .then((path) => setSaved(path))
        .catch((reason) => {
          setSaved("");
          setNotice(`파일을 저장하지 못했습니다: ${reason instanceof Error ? reason.message : String(reason)}`);
        });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  useEffect(() => {
    setSaved("");
  }, [tool.id]);

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

  const frameHtml = useMemo(() => injectDownloadBridge(html), [html]);

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
          <span>
            {notice ||
              (saved ? `다운로드 폴더에 저장했습니다: ${saved.split(/[\\/]/).pop()}` : "HTML 도구 · 통합 프레임")}
          </span>
        </div>
        <div className="toolbar-actions">
          {saved && (
            <button
              className="secondary-button"
              onClick={() =>
                void revealPath(saved).catch((reason) =>
                  setNotice(reason instanceof Error ? reason.message : String(reason)),
                )
              }
            >
              <FolderOpen size={15} />
              다운로드 폴더
            </button>
          )}
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
              setNotice("");
              void openToolInBrowser(tool.id).catch((reason) =>
                setNotice(reason instanceof Error ? reason.message : String(reason)),
              );
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
            ref={frameRef}
            srcDoc={frameHtml}
            sandbox={sandbox}
            className="html-tool-frame"
          />
        )}
      </div>
    </div>
  );
}
