import { useEffect, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  FolderOpen,
  LoaderCircle,
  Play,
  RotateCcw,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { resultPath, revealPath, runNativeTool } from "../lib/bridge";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import { ResultDialog, readResultPopup, type ResultPopup } from "./ResultDialog";
import "./native-tool-panel.css";
import "./excel-split-panel.css";
import "./excel-merge-panel.css";

type Mode = "files_to_sheets" | "workbook_sheets_to_one" | "same_sheets_together";
type Cell = string | number;

type SheetInfo = {
  file: string;
  file_name: string;
  sheet: string;
  hidden?: boolean;
  row_count?: number;
  data_rows?: number;
  header_row?: number;
  auto_header_row?: number;
  missing_formula_values?: number;
  preview?: Cell[][];
  result_title?: string;
};

type ResultInfo = {
  title: string;
  sheet_count: number;
  data_rows: number;
  columns: number;
  header_rows: number;
  header: Cell[][];
  rows: Cell[][];
  notes: string[];
};

type Analysis = { mode: Mode; sheets: SheetInfo[]; results: ResultInfo[]; errors: string[] };

const TOOL_ID = "excel_merge";
const EXTENSIONS = ["xlsx", "xlsm", "csv"];

const MODES: { id: Mode; label: string; hint: string }[] = [
  {
    id: "files_to_sheets",
    label: "파일마다 시트로 모으기",
    hint: "각 파일의 시트를 결과 파일에 시트로 그대로 옮깁니다. 서식·수식이 유지되고, 내용을 이어 붙이지는 않습니다.",
  },
  {
    id: "workbook_sheets_to_one",
    label: "모든 시트를 한 시트로 합치기",
    hint: "넣은 모든 파일·모든 시트의 표를 아래로 이어 붙여 한 시트로 만듭니다. 항목명 줄(학교명·학생수처럼 칸 이름이 적힌 줄)은 한 번만 남깁니다.",
  },
  {
    id: "same_sheets_together",
    label: "같은 이름 시트끼리 합치기",
    hint: "여러 파일에서 이름이 같은 시트(예: '3월')끼리 이어 붙여, 시트 이름마다 한 시트씩 만듭니다.",
  },
];

const fileName = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? path;
const sheetKey = (file: string, sheet: string) => `${file}\u0000${sheet}`;
const cellText = (value: Cell | undefined) =>
  typeof value === "number" ? value.toLocaleString("ko-KR", { maximumFractionDigits: 6 }) : value ?? "";

export function ExcelMergePanel({
  tool,
  presetPaths,
  onReset,
}: {
  tool: ToolManifest;
  presetPaths?: string[];
  onReset?: () => void;
}) {
  const [inputs, setInputs] = useState<string[]>(() => filterByExtension(presetPaths ?? [], EXTENSIONS));
  const [mode, setMode] = useState<Mode>("files_to_sheets");
  const [addSourceFile, setAddSourceFile] = useState(false);
  const [addSourceSheet, setAddSourceSheet] = useState(false);
  const [includeHidden, setIncludeHidden] = useState(false);
  // 직접 고친 항목명 줄. 키: 파일+시트.
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [done, setDone] = useState("");
  const [popup, setPopup] = useState<ResultPopup | null>(null);
  const requestId = useRef(0);

  const merging = mode !== "files_to_sheets";

  const overrideList = useMemo(
    () =>
      Object.entries(overrides).map(([key, header_row]) => {
        const [file, sheet] = key.split("\u0000");
        return { file, sheet, header_row };
      }),
    [overrides],
  );

  // 파일·방식·항목명 줄을 바꿀 때마다 잠시 뒤 다시 읽어 미리보기를 새로 만든다. 파일은 만들지 않는다.
  useEffect(() => {
    if (!inputs.length) {
      setAnalysis(null);
      setAnalyzeError("");
      return;
    }
    const id = ++requestId.current;
    setAnalyzing(true);
    const timer = window.setTimeout(() => {
      runNativeTool(`${TOOL_ID}__analyze`, {
        inputs,
        mode,
        include_hidden_sheets: includeHidden,
        add_source_file: addSourceFile,
        add_source_sheet: addSourceSheet,
        header_overrides: overrideList,
      })
        .then((result) => {
          if (id !== requestId.current) return;
          setAnalysis(result as unknown as Analysis);
          setAnalyzeError("");
        })
        .catch((reason) => {
          if (id !== requestId.current) return;
          setAnalysis(null);
          setAnalyzeError(reason instanceof Error ? reason.message : String(reason));
        })
        .finally(() => {
          if (id === requestId.current) setAnalyzing(false);
        });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [inputs, mode, includeHidden, addSourceFile, addSourceSheet, overrideList]);

  const takeInputs = (paths: string[]) => {
    const usable = filterByExtension(paths, EXTENSIONS);
    if (!usable.length) {
      setLog((items) => [...items, "엑셀 파일(xlsx, xlsm, csv)만 넣을 수 있습니다."]);
      return;
    }
    setInputs((current) => [...current, ...usable.filter((path) => !current.includes(path))]);
  };

  const pickFiles = async () => {
    const chosen = await openDialog({
      multiple: true,
      title: "병합할 엑셀 파일 선택",
      filters: [{ name: "엑셀 파일", extensions: EXTENSIONS }],
    });
    if (!chosen) return;
    takeInputs(Array.isArray(chosen) ? chosen : [chosen]);
  };

  const dropping = useFileDrop(takeInputs, !running);

  const removeInput = (path: string) => {
    setInputs((current) => current.filter((item) => item !== path));
    setOverrides((current) =>
      Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${path}\u0000`))),
    );
  };

  const setHeader = (sheet: SheetInfo, row: number) => {
    const key = sheetKey(sheet.file, sheet.sheet);
    const max = sheet.row_count ?? row;
    const value = Math.max(1, Math.min(Math.round(row) || 1, max));
    setOverrides((current) => {
      const next = { ...current };
      if (value === sheet.auto_header_row) delete next[key];
      else next[key] = value;
      return next;
    });
  };

  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const pickOutput = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "저장 폴더 선택" });
    if (typeof chosen === "string") setOutput(chosen);
  };

  const run = async () => {
    setRunning(true);
    setLog((items) => [...items, `${tool.name} 작업을 시작합니다.`]);
    try {
      const result = await runNativeTool(TOOL_ID, {
        inputs,
        output,
        mode,
        add_source_file: merging && addSourceFile,
        add_source_sheet: merging && addSourceSheet,
        include_hidden_sheets: includeHidden,
        header_overrides: merging ? overrideList : [],
      });
      const saved = resultPath(result);
      setDone(saved);
      setLog((items) =>
        [...items, String(result.message ?? "병합했습니다."), saved ? `저장 위치: ${saved}` : ""].filter(Boolean),
      );
      setPopup(
        readResultPopup((result as { popup?: unknown }).popup) ?? {
          level: "success",
          title: "작업을 마쳤습니다",
          message: String(result.message ?? ""),
        },
      );
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setLog((items) => [...items, `실패: ${message}`]);
      setPopup({ level: "error", title: "병합하지 못했습니다", message });
    } finally {
      setRunning(false);
    }
  };

  const sheets = analysis?.mode === mode ? analysis.sheets : [];
  const results = analysis?.mode === mode ? analysis.results : [];
  const changedCount = Object.keys(overrides).length;

  return (
    <div className="native-tool content-column">
      <div className="native-hero">
        <div className="tool-icon type-internal_python">
          <FileSpreadsheet size={23} />
        </div>
        <div>
          <span className="eyebrow">{tool.top_tab}</span>
          <h2>{tool.name}</h2>
          <p>{tool.description || "여러 엑셀 파일을 하나로 병합합니다."}</p>
        </div>
      </div>

      <section className="task-card split-card">
        <div className="task-heading">
          <div>
            <span className="step-badge">1</span>
            <strong>병합할 파일</strong>
          </div>
          <span className="privacy-note">
            <ShieldCheck size={15} />
            파일은 PC 밖으로 전송되지 않습니다.
          </span>
        </div>
        <button className={`drop-zone ${dropping ? "is-dropping" : ""}`} onClick={() => void pickFiles()}>
          <FolderOpen size={30} />
          <strong>병합할 엑셀 파일을 선택하세요 (xlsx·xlsm·csv)</strong>
          <span>
            {dropping
              ? "여기에 놓으면 목록에 넣습니다."
              : inputs.length
                ? "클릭하거나 끌어다 놓으면 목록 뒤에 더 넣습니다."
                : "클릭해서 고르거나, 창으로 끌어다 놓으세요."}
          </span>
        </button>
        {!!inputs.length && (
          <div className="picked-files">
            <div className="picked-files-head">
              <span>
                <b>{inputs.length}개</b>를 넣었습니다.
              </span>
              <button
                className="link-button"
                onClick={() => {
                  setInputs([]);
                  setOverrides({});
                }}
              >
                <Trash2 size={14} />
                모두 지우기
              </button>
            </div>
            <ul className="selected-files">
              {inputs.map((path) => (
                <li key={path} title={path}>
                  <span>{fileName(path)}</span>
                  <button title="목록에서 빼기" onClick={() => removeInput(path)}>
                    <X size={16} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="task-card split-card">
        <div className="task-heading">
          <div>
            <span className="step-badge">2</span>
            <strong>병합 방식</strong>
          </div>
        </div>
        <div className="choice-cards em-modes" role="radiogroup" aria-label="병합 방식">
          {MODES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={mode === item.id}
              className={`choice-card ${mode === item.id ? "is-active" : ""}`}
              onClick={() => setMode(item.id)}
            >
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </div>
        <div className="em-options">
          {merging && (
            <>
              <label className="field-check standalone">
                <input type="checkbox" checked={addSourceFile} onChange={(e) => setAddSourceFile(e.target.checked)} />
                원본 파일명 열 추가
              </label>
              <label className="field-check standalone">
                <input type="checkbox" checked={addSourceSheet} onChange={(e) => setAddSourceSheet(e.target.checked)} />
                원본 시트명 열 추가
              </label>
            </>
          )}
          <label className="field-check standalone">
            <input type="checkbox" checked={includeHidden} onChange={(e) => setIncludeHidden(e.target.checked)} />
            숨긴 시트도 포함
          </label>
        </div>
      </section>

      {!!inputs.length && (
        <section className="task-card split-card">
          <div className="task-heading">
            <div>
              <span className="step-badge">3</span>
              <strong>{merging ? "시트별 항목명 줄 확인" : "결과 파일에 들어갈 시트"}</strong>
            </div>
            {analyzing && (
              <span className="em-busy">
                <LoaderCircle className="spin" size={14} />
                읽는 중
              </span>
            )}
          </div>

          {analyzeError && <p className="em-error">파일을 읽지 못했습니다: {analyzeError}</p>}
          {!!analysis?.errors.length && (
            <ul className="em-notes is-error">
              {analysis.errors.map((text) => (
                <li key={text}>
                  <TriangleAlert size={14} />
                  {text}
                </li>
              ))}
            </ul>
          )}

          {merging ? (
            <>
              <p className="em-help">
                각 시트는 <b>항목명 줄(학교명·학생수처럼 칸 이름이 적힌 줄) 아래부터</b> 이어 붙입니다. 자동으로 찾은 줄이 틀리면 숫자를 고치거나,
                미리보기에서 행 번호를 누르세요.
                {changedCount > 0 && <b className="em-changed"> 직접 고친 시트 {changedCount}개</b>}
              </p>
              <div className="em-sheets">
                {sheets.map((sheet) => {
                  const key = sheetKey(sheet.file, sheet.sheet);
                  const open = expanded.has(key);
                  const manual = key in overrides;
                  const header = sheet.header_row ?? 1;
                  return (
                    <div key={key} className={`em-sheet ${manual ? "is-manual" : ""}`}>
                      <div className="em-sheet-head">
                        <button className="em-toggle" onClick={() => toggle(key)} title="위쪽 행 미리보기">
                          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          <span className="em-sheet-name">
                            {fileName(sheet.file)} <em>›</em> {sheet.sheet}
                            {sheet.hidden && <small> (숨긴 시트)</small>}
                          </span>
                        </button>
                        <span className="em-rows">데이터 {(sheet.data_rows ?? 0).toLocaleString()}행</span>
                        <label className="em-header-input">
                          항목명
                          <input
                            type="number"
                            min={1}
                            max={sheet.row_count}
                            value={header}
                            onChange={(event) => setHeader(sheet, Number(event.target.value))}
                          />
                          번째 줄
                        </label>
                        {manual ? (
                          <button className="em-badge is-manual" onClick={() => setHeader(sheet, sheet.auto_header_row ?? 1)}>
                            직접 고침 · 자동({sheet.auto_header_row})으로
                          </button>
                        ) : (
                          <span className="em-badge">자동</span>
                        )}
                      </div>
                      {!!sheet.missing_formula_values && (
                        <p className="em-warn">
                          <TriangleAlert size={14} />
                          수식 결과가 저장돼 있지 않은 셀 {sheet.missing_formula_values}개가 빈 칸이 됩니다. 원본을
                          엑셀에서 열어 저장한 뒤 다시 넣으세요.
                        </p>
                      )}
                      {open && (
                        <div className="em-table-wrap">
                          <table className="em-table">
                            <tbody>
                              {(sheet.preview ?? []).map((row, index) => {
                                const rowNo = index + 1;
                                const kind = rowNo < header ? "is-above" : rowNo === header ? "is-header" : "is-data";
                                return (
                                  <tr key={rowNo} className={kind}>
                                    <th>
                                      <button
                                        title={`${rowNo}번째 줄을 항목명 줄로`}
                                        onClick={() => setHeader(sheet, rowNo)}
                                      >
                                        {rowNo}
                                      </button>
                                    </th>
                                    {row.map((value, col) => (
                                      <td key={col}>{cellText(value)}</td>
                                    ))}
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                          <p className="em-legend">
                            <span className="is-header" /> 항목명 줄(결과에 한 번만 남음)
                            <span className="is-above" /> 표 제목 등(결과에서 빠짐)
                            <span className="is-data" /> 이어 붙일 데이터
                          </p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <ul className="em-plan">
              {sheets.map((sheet) => (
                <li key={sheetKey(sheet.file, sheet.sheet)}>
                  <span>
                    {fileName(sheet.file)} <em>›</em> {sheet.sheet}
                  </span>
                  <b>→ '{sheet.result_title}' 시트</b>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {merging && !!results.length && (
        <section className="task-card split-card">
          <div className="task-heading">
            <div>
              <span className="step-badge">4</span>
              <strong>결과 미리보기</strong>
            </div>
          </div>
          {results.map((item) => (
            <div key={item.title} className="em-result">
              <div className="em-result-head">
                <strong>'{item.title}' 시트</strong>
                <span>
                  시트 {item.sheet_count}개 → 데이터 {item.data_rows.toLocaleString()}행 · 열 {item.columns}개
                </span>
              </div>
              {!!item.notes.length && (
                <ul className="em-notes">
                  {item.notes.map((text) => (
                    <li key={text}>
                      <TriangleAlert size={14} />
                      {text}
                    </li>
                  ))}
                </ul>
              )}
              <div className="em-table-wrap">
                <table className="em-table is-result">
                  <thead>
                    <tr>
                      {(item.header[item.header.length - 1] ?? []).map((value, col) => (
                        <th key={col}>{cellText(value)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {item.rows.map((row, index) => (
                      <tr key={index}>
                        {row.map((value, col) => (
                          <td key={col}>{cellText(value)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {item.data_rows > item.rows.length && (
                <p className="em-more">위쪽 {item.rows.length}행만 보여 줍니다. 나머지 {(item.data_rows - item.rows.length).toLocaleString()}행도 함께 병합됩니다.</p>
              )}
            </div>
          ))}
        </section>
      )}

      <section className="task-card split-card">
        <label className="split-output">
          <span>저장 폴더</span>
          <div className="split-row">
            <input value={output} readOnly placeholder="비우면 첫 번째 파일과 같은 폴더에 '엑셀병합_일시.xlsx'로 저장합니다" />
            <button className="secondary-button" onClick={() => void pickOutput()}>
              <FolderOpen size={15} />
              찾아보기
            </button>
          </div>
        </label>
      </section>

      <div className="run-row">
        {onReset && (
          <button className="secondary-button" onClick={onReset} disabled={running} title="넣은 파일과 설정을 모두 지우고 처음 상태로 돌아갑니다.">
            <RotateCcw size={15} />
            초기화
          </button>
        )}
        <button className="primary-button" onClick={() => void run()} disabled={running || !inputs.length}>
          {running ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
          {running ? "병합 중" : "병합 실행"}
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

      {popup && (
        <ResultDialog
          popup={popup}
          onClose={() => setPopup(null)}
          onReveal={done ? () => void revealPath(done).catch(() => undefined) : undefined}
        />
      )}
    </div>
  );
}
