import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowDownAZ,
  ArrowDownZA,
  ArrowUp,
  ChevronsDown,
  ChevronsUp,
  FileInput,
  FolderOpen,
  GripVertical,
  LoaderCircle,
  Play,
  Save,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { resultPath, revealPath, runNativeTool } from "../lib/bridge";
import {
  getToolSchema,
  initialToolOptions,
  type ToolField,
} from "../lib/toolSchemas";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import "./native-tool-panel.css";

type Options = Record<string, string | number | boolean>;

/** 목록에는 파일 이름을 크게 보여주고 전체 경로는 아래에 작게 붙인다. */
function fileName(path: string) {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function NativeToolPanel({
  tool,
  // 탐색기 우클릭으로 열렸을 때 이미 정해진 처리 대상.
  presetPaths,
}: {
  tool: ToolManifest;
  presetPaths?: string[];
}) {
  const schema = useMemo(() => getToolSchema(tool.id), [tool.id]);
  const [inputs, setInputs] = useState<string[]>([]);
  const [output, setOutput] = useState("");
  const [options, setOptions] = useState<Options>(() => initialToolOptions(schema));
  const [confirmed, setConfirmed] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  // 작업이 끝난 뒤 결과를 바로 열어 볼 수 있도록 저장 경로를 기억한다.
  const [done, setDone] = useState("");
  // 합치는 순서가 결과를 바꾸는 도구에서만 순서 조작 목록을 쓴다.
  const orderable = schema.orderable === true && schema.multiple;
  // 끌어 옮기는 중인 줄과 지금 가리키고 있는 자리.
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    // 우클릭으로 들어온 경로는 미리 담아 두고, 사용자는 실행만 누르면 되게 한다.
    // 파일 하나만 받는 도구에는 첫 번째만 넣는다.
    const preset = presetPaths?.length
      ? schema.multiple
        ? presetPaths
        : presetPaths.slice(0, 1)
      : [];
    setInputs(preset);
    setOutput("");
    setOptions(initialToolOptions(schema));
    setConfirmed(false);
    setLog(
      preset.length
        ? [`탐색기에서 ${preset.length}개를 받아 왔습니다. 설정을 확인하고 실행하세요.`]
        : [],
    );
    setDone("");
    setDragFrom(null);
    setDragOver(null);
  }, [schema, tool.id, presetPaths]);

  /**
   * 순서가 중요한 도구는 고른 파일을 목록 뒤에 덧붙인다. 여러 폴더에서 나눠
   * 가져오는 일이 많아서다. 나머지 도구는 지금까지처럼 통째로 갈아 끼운다.
   */
  const takeInputs = (paths: string[]) => {
    if (!schema.multiple) {
      setInputs(paths.slice(0, 1));
      return;
    }
    if (!orderable) {
      setInputs(paths);
      return;
    }
    setInputs((current) => {
      const merged = [...current];
      let skipped = 0;
      for (const path of paths) {
        if (merged.includes(path)) {
          skipped += 1;
          continue;
        }
        merged.push(path);
      }
      if (skipped) {
        setLog((items) => [...items, `이미 목록에 있는 ${skipped}개는 넣지 않았습니다.`]);
      }
      return merged;
    });
  };

  const moveInput = (from: number, to: number) => {
    setInputs((current) => {
      if (from === to || to < 0 || to >= current.length) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  };

  const removeInput = (index: number) => {
    setInputs((current) => current.filter((_, position) => position !== index));
  };

  /**
   * 파일 이름으로 정렬한다. 경로가 아니라 이름만 본다.
   * numeric을 켜야 문서2가 문서10보다 앞에 온다.
   */
  const sortInputs = (descending: boolean) => {
    setInputs((current) => {
      const next = [...current].sort((left, right) =>
        fileName(left).localeCompare(fileName(right), "ko", {
          numeric: true,
          sensitivity: "base",
        }),
      );
      return descending ? next.reverse() : next;
    });
  };

  /**
   * 줄을 끌어 순서를 바꾼다.
   *
   * HTML의 draggable을 쓰지 않는 이유: 창 전체에 Tauri의 파일 드롭 감지가 걸려 있어
   * WebView2가 끌기 이벤트를 가로챈다. 그래서 마우스 위치를 직접 읽어 처리한다.
   */
  const startDrag = (index: number, event: React.PointerEvent<HTMLLIElement>) => {
    // 왼쪽 버튼만, 그리고 위로·아래로·빼기 버튼을 누른 것이면 끌기로 보지 않는다.
    if (event.button !== 0) return;
    if ((event.target as HTMLElement).closest(".file-actions")) return;
    event.preventDefault();

    /** 마우스 높이가 어느 줄에 해당하는지. 줄 절반을 넘기면 다음 줄로 친다. */
    const rowAt = (clientY: number) => {
      const rows = Array.from(listRef.current?.children ?? []) as HTMLElement[];
      for (let position = 0; position < rows.length; position += 1) {
        const box = rows[position].getBoundingClientRect();
        if (clientY < box.top + box.height / 2) return position;
      }
      return rows.length - 1;
    };

    let target = index;
    setDragFrom(index);
    setDragOver(index);

    const onMove = (moveEvent: PointerEvent) => {
      target = rowAt(moveEvent.clientY);
      setDragOver(target);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      moveInput(index, target);
      setDragFrom(null);
      setDragOver(null);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const chooseInput = async () => {
    const selected = await open({
      multiple: schema.multiple,
      directory: schema.inputMode === "folder",
      filters: schema.extensions
        ? [{ name: "지원 파일", extensions: schema.extensions }]
        : undefined,
    });
    if (!selected) return;
    takeInputs(Array.isArray(selected) ? selected : [selected]);
  };

  const dropping = useFileDrop((paths) => {
    // 폴더를 받는 도구는 확장자를 따지지 않는다.
    const usable =
      schema.inputMode === "folder" ? paths : filterByExtension(paths, schema.extensions);
    if (!usable.length) {
      setLog((items) => [...items, "이 도구가 처리할 수 있는 파일이 없습니다."]);
      return;
    }
    takeInputs(usable);
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
      const saved = resultPath(result);
      setDone(saved);
      setLog((current) => [
        ...current,
        String(result.message ?? "작업이 완료되었습니다."),
        saved ? `저장 위치: ${saved}` : "",
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
              : orderable && inputs.length
                ? "클릭하거나 끌어다 놓으면 목록 뒤에 더 넣습니다."
                : "클릭해서 고르거나, 창으로 끌어다 놓으세요."}
          </span>
        </button>
        {!!inputs.length && !orderable && (
          <ul className="selected-files">
            {inputs.map((path) => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        )}

        {!!inputs.length && orderable && (
          <div className="ordered-files">
            <div className="ordered-files-head">
              <span className="ordered-files-hint">
                <b>{inputs.length}개</b> — 위에서부터 이 순서로 합칩니다. 끌어서 옮길 수도 있습니다.
              </span>
              <span className="ordered-files-tools">
                <button
                  className="link-button"
                  title="파일 이름 오름차순 (가나다, 1·2·10 순)"
                  onClick={() => sortInputs(false)}
                >
                  <ArrowDownAZ size={14} />
                  이름순
                </button>
                <button
                  className="link-button"
                  title="파일 이름 내림차순"
                  onClick={() => sortInputs(true)}
                >
                  <ArrowDownZA size={14} />
                  역순
                </button>
                <button className="link-button" onClick={() => setInputs([])}>
                  <Trash2 size={14} />
                  모두 지우기
                </button>
              </span>
            </div>
            <ol ref={listRef}>
              {inputs.map((path, index) => (
                <li
                  key={path}
                  className={[
                    dragFrom === index ? "is-dragging" : "",
                    dragOver === index && dragFrom !== index ? "is-over" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onPointerDown={(event) => startDrag(index, event)}
                >
                  <GripVertical className="drag-grip" size={15} />
                  <span className="file-order">{index + 1}</span>
                  <span className="file-label">
                    <b>{fileName(path)}</b>
                    <small title={path}>{path}</small>
                  </span>
                  <span className="file-actions">
                    <button
                      title="맨 위로"
                      disabled={index === 0}
                      onClick={() => moveInput(index, 0)}
                    >
                      <ChevronsUp size={14} />
                    </button>
                    <button
                      title="위로"
                      disabled={index === 0}
                      onClick={() => moveInput(index, index - 1)}
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      title="아래로"
                      disabled={index === inputs.length - 1}
                      onClick={() => moveInput(index, index + 1)}
                    >
                      <ArrowDown size={14} />
                    </button>
                    <button
                      title="맨 아래로"
                      disabled={index === inputs.length - 1}
                      onClick={() => moveInput(index, inputs.length - 1)}
                    >
                      <ChevronsDown size={14} />
                    </button>
                    <button title="목록에서 빼기" onClick={() => removeInput(index)}>
                      <X size={14} />
                    </button>
                  </span>
                </li>
              ))}
            </ol>
          </div>
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
        <div className="log-head">
          <strong>작업 기록</strong>
          {!!done && (
            <button className="secondary-button" onClick={() => void revealPath(done).catch(() => undefined)}>
              <FolderOpen size={15} />
              결과 폴더 열기
            </button>
          )}
        </div>
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
