import { useMemo, useState } from "react";
import {
  FileInput,
  FolderOpen,
  LoaderCircle,
  Play,
  ShieldCheck,
} from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
import { runNativeTool } from "../lib/bridge";
import type { ToolManifest } from "../types";

export function NativeToolView({ tool }: { tool: ToolManifest }) {
  const [inputs, setInputs] = useState<string[]>([]);
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const acceptsFolder = useMemo(
    () =>
      [
        "folder_unpacker",
        "file_inventory",
        "rename_files",
        "zip_batch_extractor",
        "homepage_post_collector",
      ].includes(tool.id),
    [tool.id],
  );

  const chooseInput = async () => {
    const selected = await open({
      multiple: true,
      directory: acceptsFolder,
    });
    if (!selected) return;
    setInputs(Array.isArray(selected) ? selected : [selected]);
  };

  const run = async () => {
    setRunning(true);
    setLog((current) => [...current, `${tool.name} 작업을 시작합니다.`]);
    try {
      const result = await runNativeTool(tool.id, { inputs, output });
      setLog((current) => [
        ...current,
        String(result.message ?? "작업이 완료되었습니다."),
      ]);
    } catch (reason) {
      setLog((current) => [
        ...current,
        `실패: ${reason instanceof Error ? reason.message : String(reason)}`,
      ]);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="native-tool content-column">
      <div className="native-hero">
        <div className="tool-icon type-internal_python">
          <FileInput size={23} />
        </div>
        <div>
          <span className="eyebrow">{tool.top_tab}</span>
          <h2>{tool.name}</h2>
          <p>{tool.description || "로컬 파일을 안전하게 처리합니다."}</p>
        </div>
      </div>

      <section className="task-card">
        <div className="task-heading">
          <div>
            <span className="step-badge">1</span>
            <strong>처리 대상 선택</strong>
          </div>
          <span className="privacy-note">
            <ShieldCheck size={15} />
            파일은 PC 밖으로 전송되지 않습니다.
          </span>
        </div>
        <button className="drop-zone" onClick={chooseInput}>
          <FolderOpen size={30} />
          <strong>
            {acceptsFolder ? "폴더를 선택하세요" : "파일을 선택하세요"}
          </strong>
          <span>클릭해서 처리 대상을 불러옵니다.</span>
        </button>
        {!!inputs.length && (
          <ul className="selected-files">
            {inputs.map((path) => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="task-card">
        <div className="task-heading">
          <div>
            <span className="step-badge">2</span>
            <strong>저장 위치</strong>
          </div>
        </div>
        <input
          className="text-input"
          value={output}
          onChange={(event) => setOutput(event.target.value)}
          placeholder="비워 두면 원본 폴더 또는 다운로드 폴더에 저장합니다."
        />
      </section>

      <div className="run-row">
        <button
          className="primary-button"
          onClick={run}
          disabled={!inputs.length || running}
        >
          {running ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <Play size={17} />
          )}
          {running ? "처리 중" : "작업 실행"}
        </button>
      </div>

      <section className="log-panel">
        <strong>작업 기록</strong>
        <pre>{log.length ? log.join("\n") : "아직 실행한 작업이 없습니다."}</pre>
      </section>
    </div>
  );
}
