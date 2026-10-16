import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
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
  Search,
  Square,
  Trash2,
  TriangleAlert,
  X,
  RotateCcw,
} from "lucide-react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { cancelNativeTool, fileSizes, pathKinds, resultPath, revealPath, runNativeTool } from "../lib/bridge";
import { failureMessage, summarizeFailures } from "../lib/failureSummary";
import {
  appendToolLog,
  beginToolRun,
  getToolRun,
  openToolRun,
  subscribeToolRuns,
  updateToolRun,
} from "../lib/toolRunStore";
import {
  getToolSchema,
  initialToolOptions,
  type ToolField,
} from "../lib/toolSchemas";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import "./native-tool-panel.css";
import { ResultDialog, readResultPopup, type ResultPopup } from "./ResultDialog";

type Options = Record<string, string | number | boolean>;

/** 목록에는 파일 이름을 크게 보여주고 전체 경로는 아래에 작게 붙인다. */
/** 1MB 이상은 MB, 그보다 작으면 KB 로. */
function formatSize(bytes: number) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)}MB`;
  return `${Math.max(1, Math.round(bytes / 1024))}KB`;
}

function fileName(path: string) {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function NativeToolPanel({
  tool,
  // 초기화: 넣은 파일·설정·기록을 모두 지우고 처음 들어온 상태로 되돌린다.
  onReset,
}: {
  tool: ToolManifest;
  onReset?: () => void;
}) {
  const schema = useMemo(() => getToolSchema(tool.id), [tool.id]);
  const [inputs, setInputs] = useState<string[]>([]);
  const [output, setOutput] = useState("");
  const [options, setOptions] = useState<Options>(() => initialToolOptions(schema));
  const [confirmed, setConfirmed] = useState(false);
  // 실행 상태·기록·결과는 화면 바깥(toolRunStore)에 둔다. 실행 중에 다른 화면에
  // 다녀와도 이어서 보이고, 중지할 수 있고, 같은 도구를 겹쳐 돌리지 못한다.
  useState(() => openToolRun(tool.id));
  const runState = useSyncExternalStore(subscribeToolRuns, () => getToolRun(tool.id));
  const { running, stopping, log, done, popup } = runState;
  const setLog = (...lines: string[]) => appendToolLog(tool.id, ...lines);
  // 크기를 보여 주는 도구에서 쓰는 파일별 크기. 한 번 잰 파일은 다시 묻지 않는다.
  const [sizes, setSizes] = useState<Record<string, number | null>>({});
  // 합치는 순서가 결과를 바꾸는 도구에서만 순서 조작 목록을 쓴다.
  const orderable = schema.orderable === true && schema.multiple;
  // 끌어 옮기는 중인 줄과 지금 가리키고 있는 자리.
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const logRef = useRef<HTMLPreElement>(null);

  // 도구가 바꾼 입력 경로(파일명 변경 등)를 받아 온다. 실행이 끝났을 때 이 화면이
  // 잠깐 사라져 있었어도, 돌아오면 여기서 받아 간다.
  useEffect(() => {
    if (!runState.nextInputs) return;
    setInputs(runState.nextInputs);
    updateToolRun(tool.id, () => ({ nextInputs: null }));
  }, [runState.nextInputs, tool.id]);

  useEffect(() => {
    if (!schema.showSizes) return;
    const missing = inputs.filter((path) => !(path in sizes));
    if (!missing.length) return;
    let cancelled = false;
    void fileSizes(missing)
      .then((values) => {
        if (cancelled) return;
        setSizes((current) => {
          const next = { ...current };
          missing.forEach((path, index) => { next[path] = values[index] ?? null; });
          return next;
        });
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [inputs, sizes, schema.showSizes]);

  const totalSize = schema.showSizes
    ? inputs.reduce((sum, path) => sum + (sizes[path] ?? 0), 0)
    : 0;
  const sizeOf = (path: string) =>
    schema.showSizes && typeof sizes[path] === "number" ? formatSize(sizes[path] as number) : "";

  // 새 줄이 붙으면 아래로 따라 내린다.
  useEffect(() => {
    const box = logRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [log]);

  useEffect(() => {
    setOutput("");
    setOptions(initialToolOptions(schema));
    setConfirmed(false);
    setDragFrom(null);
    setDragOver(null);
  }, [schema, tool.id]);

  /**
   * 여러 개를 받는 도구는 새로 고른 파일을 목록 뒤에 덧붙인다. 한 번에 다 고르지 않고
   * 여러 폴더에서 나눠 넣을 수 있게 하려는 것이다. 목록을 비우려면 초기화나 빼기 버튼을 쓴다.
   * 파일 하나만 받는 도구는 새로 고른 것으로 바꾼다.
   */
  const takeInputs = (paths: string[]) => {
    if (!schema.multiple) {
      setInputs(paths.slice(0, 1));
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
        setLog(`이미 목록에 있는 ${skipped}개는 넣지 않았습니다.`);
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

  const chooseInput = async (directory = schema.inputMode === "folder") => {
    const selected = await open({
      multiple: schema.multiple,
      directory,
      filters: schema.extensions && !directory
        ? [{ name: "지원 파일", extensions: schema.extensions }]
        : undefined,
    });
    if (!selected) return;
    takeInputs(Array.isArray(selected) ? selected : [selected]);
  };

  const dropping = useFileDrop((paths) => {
    void acceptDropped(paths);
  }, schema.inputMode !== "none");

  /**
   * 끌어다 놓은 것 중 이 도구가 받을 수 있는 것만 넣는다.
   * 폴더만 받는 도구에 파일을 넣으면 실행한 뒤에야 파이썬 쪽에서 실패하므로 여기서 거른다.
   */
  const acceptDropped = async (paths: string[]) => {
    if (schema.inputMode === "file") {
      const usable = filterByExtension(paths, schema.extensions);
      if (!usable.length) {
        setLog("이 도구가 처리할 수 있는 파일이 없습니다.");
        return;
      }
      takeInputs(usable);
      return;
    }

    let kinds: string[] | null = null;
    try {
      kinds = await pathKinds(paths);
    } catch {
      kinds = null;
    }
    // 종류를 알 수 없으면(앱 밖 등) 예전처럼 넘기고 도구가 판단하게 한다.
    if (!kinds) {
      takeInputs(paths);
      return;
    }
    const isFolder = (index: number) => kinds?.[index] === "folder";
    const usable =
      schema.inputMode === "folder"
        ? paths.filter((_, index) => isFolder(index))
        : paths.filter(
            (path, index) =>
              isFolder(index) || filterByExtension([path], schema.extensions).length > 0,
          );
    const rejected = paths.length - usable.length;
    if (!usable.length) {
      setLog(
        schema.inputMode === "folder"
          ? "이 도구는 폴더만 받습니다. 파일이 아니라 폴더를 끌어다 놓으세요."
          : "이 도구가 처리할 수 있는 파일이나 폴더가 없습니다.",
      );
      return;
    }
    if (rejected) {
      setLog(
        schema.inputMode === "folder"
          ? `폴더가 아닌 ${rejected}개는 넣지 않았습니다.`
          : `처리할 수 없는 ${rejected}개는 넣지 않았습니다.`,
      );
    }
    takeInputs(usable);
  };

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

  // 중지를 누른 뒤에는 버튼을 다시 누르지 못하게 막는다(stopping).
  const stop = async () => {
    const toolId = tool.id;
    updateToolRun(toolId, () => ({ stopping: true }));
    appendToolLog(toolId, "중지를 요청했습니다. 하던 항목까지 마치고 멈춥니다.");
    try {
      await cancelNativeTool(toolId);
    } catch (reason) {
      appendToolLog(
        toolId,
        `중지 요청 실패: ${reason instanceof Error ? reason.message : String(reason)}`,
      );
    }
  };

  // 칸 옆 확인 버튼. 결과 설명은 작업 기록에 남기고, 돌려받은 값으로 다른 칸을 채운다.
  const [checking, setChecking] = useState("");

  const runFieldAction = async (field: ToolField) => {
    const action = field.action;
    if (!action) return;
    setChecking(field.key);
    setLog(`${action.label} 중입니다...`);
    try {
      const result = await runNativeTool(action.tool, {
        [action.payloadKey]: options[field.key],
      });
      setLog(String(result.message ?? "확인했습니다."));
      const fill = result.fill;
      if (fill && typeof fill === "object" && !Array.isArray(fill)) {
        setOptions((current) => ({ ...current, ...(fill as Options) }));
      }
    } catch (reason) {
      setLog(`${action.label} 실패: ${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setChecking("");
    }
  };

  const run = async () => {
    // 이 화면이 실행 중에 사라졌다 다시 만들어져도 결과는 toolRunStore 로 간다.
    // 그래서 아래에서는 화면 상태(setState)를 건드리지 않는다.
    const toolId = tool.id;
    if (!beginToolRun(toolId, `${tool.name} 작업을 시작합니다.`)) return;
    try {
      const result = await runNativeTool(toolId, {
        inputs,
        output,
        ...options,
        confirmed,
      });
      const saved = resultPath(result);
      const message = String(result.message ?? "작업이 완료되었습니다.");
      const failures = summarizeFailures(result);

      // 파일명 일괄 변경처럼 원본 이름을 바꾸는 도구는 새 경로를 돌려준다.
      // 갈아 끼우지 않으면 이어서 한 번 더 돌릴 때 없는 파일을 가리켜 실패한다.
      const nextInputs = (result as { inputs?: unknown }).inputs;
      const renamed =
        Array.isArray(nextInputs) && nextInputs.every((item) => typeof item === "string")
          ? (nextInputs as string[])
          : null;

      // 도구가 따로 문구를 주면 그것을 쓴다. 없으면 실패한 항목이 있을 때는 경고,
      // 모두 됐으면 결과 메시지와 저장 위치로 성공 팝업을 띄운다.
      const popup: ResultPopup =
        readResultPopup((result as { popup?: unknown }).popup) ??
        (failures
          ? {
              level: "warning",
              title: "일부 항목을 처리하지 못했습니다",
              message: failureMessage(failures, message, saved),
            }
          : {
              level: "success",
              title: "작업을 마쳤습니다",
              message: [message, saved ? `저장 위치: ${saved}` : ""].filter(Boolean).join("\n\n"),
            });

      updateToolRun(toolId, (current) => ({
        done: saved,
        popup,
        nextInputs: renamed,
        log: [
          ...current.log,
          message,
          failures ? `처리하지 못한 항목: ${failures.count}개` : "",
          saved ? `저장 위치: ${saved}` : "",
        ].filter(Boolean),
      }));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      updateToolRun(toolId, (current) => ({
        log: [...current.log, `실패: ${message}`],
        popup: { level: "error", title: "작업을 마치지 못했습니다", message },
      }));
    } finally {
      updateToolRun(toolId, () => ({ running: false, stopping: false }));
    }
  };

  const closePopup = () => updateToolRun(tool.id, () => ({ popup: null }));

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
      <section className="task-card" data-tour="tool-input">
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
        <button className={`drop-zone ${dropping ? "is-dropping" : ""}`} onClick={() => void chooseInput()}>
          <FolderOpen size={30} />
          <strong>{schema.inputLabel}</strong>
          <span>
            {dropping
              ? "여기에 놓으면 처리 대상으로 넣습니다."
              : schema.multiple && inputs.length
                ? "클릭하거나 끌어다 놓으면 목록 뒤에 더 넣습니다."
                : schema.inputMode === "both"
                  ? "클릭해서 파일을 고르거나, 파일·폴더를 창으로 끌어다 놓으세요."
                  : "클릭해서 고르거나, 창으로 끌어다 놓으세요."}
          </span>
        </button>
        {schema.inputMode === "both" && (
          <div className="folder-pick-row">
            <button className="link-button" onClick={() => void chooseInput(true)}>
              <FolderOpen size={14} />
              폴더로 고르기
            </button>
          </div>
        )}
        {!!inputs.length && !orderable && (
          <div className="picked-files">
            {schema.multiple && (
              <div className="picked-files-head">
                <span>
                  <b>{inputs.length}개</b>를 넣었습니다.
                  {schema.showSizes && totalSize > 0 && (
                    <>
                      {" "}합계 <b className="size-total">{formatSize(totalSize)}</b>
                    </>
                  )}
                </span>
                <button className="link-button" onClick={() => setInputs([])}>
                  <Trash2 size={14} />
                  모두 지우기
                </button>
              </div>
            )}
            <ul className="selected-files">
              {inputs.map((path, index) => (
                <li key={path} title={path}>
                  <span>{fileName(path)}</span>
                  {!!sizeOf(path) && <em className="file-size">{sizeOf(path)}</em>}
                  <button title="목록에서 빼기" onClick={() => removeInput(index)}>
                    <X size={16} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!!inputs.length && orderable && (
          <div className="ordered-files">
            <div className="ordered-files-head">
              <span className="ordered-files-hint">
                <b>{inputs.length}개</b>
                {schema.showSizes && totalSize > 0 && <> · 합계 <b>{formatSize(totalSize)}</b></>}
                {" "}— 위에서부터 이 순서로 합칩니다. 끌어서 옮길 수도 있습니다.
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
                    <b title={path}>{fileName(path)}</b>
                    {!!sizeOf(path) && <em className="file-size">{sizeOf(path)}</em>}
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
            <div className="option-grid" data-tour="tool-options">
              {schema.fields.map((field) => (
                <OptionField
                  key={field.key}
                  field={field}
                  value={options[field.key]}
                  busy={checking === field.key}
                  disabled={Boolean(
                    field.disabledWhen &&
                      field.disabledWhen.values.includes(String(options[field.disabledWhen.key] ?? "")),
                  )}
                  onAction={() => void runFieldAction(field)}
                  onChange={(value) => setOption(field.key, value)}
                />
              ))}
            </div>
          )}

          {schema.outputMode !== "hidden" && (
            <label className="form-field output-field" data-tour="tool-output">
              <span>{schema.outputLabel ?? "저장 위치"}</span>
              <div className="path-picker">
                <input
                  className="text-input"
                  value={output}
                  onChange={(event) => setOutput(event.target.value)}
                  placeholder={schema.outputPlaceholder ?? "비워 두면 원본과 같은 폴더에 저장합니다."}
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
        <label className="destructive-confirm" data-tour="tool-confirm">
          <TriangleAlert size={18} />
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>{schema.destructiveLabel ?? "원본 파일이 이동되거나 이름이 바뀌는 작업임을 확인했습니다."}</span>
        </label>
      )}

      <div className="run-row" data-tour="tool-run">
        {onReset && (
          <button
            className="secondary-button"
            onClick={onReset}
            disabled={running}
            title="넣은 파일과 설정을 모두 지우고 처음 상태로 돌아갑니다."
          >
            <RotateCcw size={15} />
            초기화
          </button>
        )}
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
        {schema.cancellable && (
          <button
            className="secondary-button"
            onClick={() => void stop()}
            disabled={!running || stopping}
          >
            <Square size={15} />
            {stopping ? "멈추는 중" : "중지"}
          </button>
        )}
      </div>

      <section className="log-panel" data-tour="tool-log">
        <div className="log-head">
          <strong>작업 기록</strong>
          {!!done && (
            <button className="secondary-button" onClick={() => void revealPath(done).catch(() => undefined)}>
              <FolderOpen size={15} />
              결과 폴더 열기
            </button>
          )}
        </div>
        <pre ref={logRef}>{log.length ? log.join("\n") : "아직 실행한 작업이 없습니다."}</pre>
      </section>

      {popup && (
        <ResultDialog
          popup={popup}
          onClose={closePopup}
          onReveal={done ? () => void revealPath(done).catch(() => undefined) : undefined}
        />
      )}
    </div>
  );
}

function OptionField({
  field,
  value,
  busy,
  disabled,
  onAction,
  onChange,
}: {
  field: ToolField;
  value: string | number | boolean;
  busy?: boolean;
  disabled?: boolean;
  onAction?: () => void;
  onChange: (value: string | number | boolean) => void;
}) {
  if (field.type === "select" && field.appearance === "cards") {
    return (
      <div className="choice-field">
        <span>{field.label}</span>
        <div className="choice-cards" role="radiogroup" aria-label={field.label}>
          {(field.choices ?? []).map((choice) => {
            const active = String(value ?? "") === choice.value;
            return (
              <button
                key={choice.value}
                type="button"
                role="radio"
                aria-checked={active}
                className={`choice-card ${active ? "is-active" : ""}`}
                onClick={() => onChange(choice.value)}
              >
                <strong>{choice.label}</strong>
                {choice.hint && <small>{choice.hint}</small>}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

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
    <label className={`form-field ${disabled ? "is-disabled" : ""}`}>
      <span>{field.label}</span>
      {field.type === "select" ? (
        <select
          className="text-input"
          value={String(value ?? "")}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          {(field.choices ?? []).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      ) : field.action ? (
        <div className="path-picker">
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
          <button
            className="secondary-button"
            onClick={onAction}
            disabled={busy || !String(value ?? "").trim()}
          >
            {busy ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}
            {field.action.label}
          </button>
        </div>
      ) : (
        <input
          className="text-input"
          type={field.type}
          value={String(value ?? "")}
          placeholder={field.placeholder}
          disabled={disabled}
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
