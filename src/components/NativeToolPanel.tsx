import { useEffect, useMemo, useState } from "react";
import {
  FileInput,
  FolderOpen,
  LoaderCircle,
  Play,
  Save,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { runNativeTool } from "../lib/bridge";
import {
  getToolSchema,
  initialToolOptions,
  type ToolField,
} from "../lib/toolSchemas";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import "./native-tool-panel.css";

type Options = Record<string, string | number | boolean>;

export function NativeToolPanel({ tool }: { tool: ToolManifest }) {
  const schema = useMemo(() => getToolSchema(tool.id), [tool.id]);
  const [inputs, setInputs] = useState<string[]>([]);
  const [output, setOutput] = useState("");
  const [options, setOptions] = useState<Options>(() => initialToolOptions(schema));
  const [confirmed, setConfirmed] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);

  useEffect(() => {
    setInputs([]);
    setOutput("");
    setOptions(initialToolOptions(schema));
    setConfirmed(false);
    setLog([]);
  }, [schema, tool.id]);

  const chooseInput = async () => {
    const selected = await open({
      multiple: schema.multiple,
      directory: schema.inputMode === "folder",
      filters: schema.extensions
        ? [{ name: "지원 파일", extensions: schema.extensions }]
        : undefined,
    });
    if (!selected) return;
    setInputs(Array.isArray(selected) ? selected : [selected]);
  };

  const dropping = useFileDrop((paths) => {
    // 폴더를 받는 도구는 확장자를 따지지 않는다.
    const usable =
      schema.inputMode === "folder" ? paths : filterByExtension(paths, schema.extensions);
    if (!usable.length) {
      setLog((items) => [...items, "이 도구가 처리할 수 있는 파일이 없습니다."]);
      return;
    }
    setInputs(schema.multiple ? usable : usable.slice(0, 1));
  }, schema.inputMode !== "none");

  const chooseOutput = async () => {
    if (schema.outputMode === "folder") {
      const selected = await open({ directory: true, multiple: false });
      if (selected && !Array.isArray(selected)) setOutput(selected);
      return;
    }
    const selected = await save({
      filters: schema.outputExtension
        ? [{ name: "결과 파일", extensions: [schema.outputExtension] }]
        : undefined,
    });
    if (selected) setOutput(selected);
  };

  const setOption = (key: string, value: string | number | boolean) => {
    setOptions((current) => ({ ...current, [key]: value }));
  };

  const run = async () => {
    setRunning(true);
    setLog((current) => [...current, `${tool.name} 작업을 시작합니다.`]);
    try {
      const result = await runNativeTool(tool.id, {
        inputs,
        output,
        ...options,
        confirmed,
      });
      setLog((current) => [
        ...current,
        String(result.message ?? "작업이 완료되었습니다."),
        result.output ? `저장 위치: ${String(result.output)}` : "",
      ].filter(Boolean));
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

      {schema.inputMode !== "none" && (
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
        <button className={`drop-zone ${dropping ? "is-dropping" : ""}`} onClick={chooseInput}>
          <FolderOpen size={30} />
          <strong>{schema.inputLabel}</strong>
          <span>
            {dropping
              ? "여기에 놓으면 처리 대상으로 넣습니다."
              : "클릭해서 고르거나, 창으로 끌어다 놓으세요."}
          </span>
        </button>
        {!!inputs.length && (
          <ul className="selected-files">
            {inputs.map((path) => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        )}
      </section>
      )}

      {((schema.fields?.length ?? 0) > 0 || schema.outputMode !== "hidden") && (
        <section className="task-card">
          <div className="task-heading">
            <div>
              <span className="step-badge">2</span>
              <strong>작업 설정</strong>
            </div>
          </div>

          {!!schema.fields?.length && (
            <div className="option-grid">
              {schema.fields.map((field) => (
                <OptionField
                  key={field.key}
                  field={field}
                  value={options[field.key]}
                  onChange={(value) => setOption(field.key, value)}
                />
              ))}
            </div>
          )}

          {schema.outputMode !== "hidden" && (
            <label className="form-field output-field">
              <span>{schema.outputLabel ?? "저장 위치"}</span>
              <div className="path-picker">
                <input
                  className="text-input"
                  value={output}
                  onChange={(event) => setOutput(event.target.value)}
                  placeholder="비워 두면 원본과 같은 폴더에 저장합니다."
                />
                <button className="secondary-button" onClick={chooseOutput}>
                  <Save size={15} />
                  찾아보기
                </button>
              </div>
            </label>
          )}
        </section>
      )}

      {schema.destructive && (
        <label className="destructive-confirm">
          <TriangleAlert size={18} />
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>원본 파일이 이동되거나 이름이 바뀌는 작업임을 확인했습니다.</span>
        </label>
      )}

      <div className="run-row">
        <button
          className="primary-button"
          onClick={run}
          disabled={
            (schema.inputMode !== "none" && !inputs.length) ||
            running ||
            Boolean(schema.destructive && !confirmed)
          }
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

function OptionField({
  field,
  value,
  onChange,
}: {
  field: ToolField;
  value: string | number | boolean;
  onChange: (value: string | number | boolean) => void;
}) {
  if (field.type === "checkbox") {
    return (
      <label className="check-field">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{field.label}</span>
      </label>
    );
  }

  return (
    <label className="form-field">
      <span>{field.label}</span>
      {field.type === "select" ? (
        <select
          className="text-input"
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          {(field.choices ?? []).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          className="text-input"
          type={field.type}
          value={String(value ?? "")}
          placeholder={field.placeholder}
          onChange={(event) =>
            onChange(
              field.type === "number"
                ? Number(event.target.value)
                : event.target.value,
            )
          }
        />
      )}
    </label>
  );
}
