import { useEffect, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  CheckSquare,
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
  excluded?: boolean;
  filled_total?: number;
  filled_upto?: number[];
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
    hint: "각 파일의 시트를 결과 파일에 시트로 그대로 옮깁니다. 서식은 그대로, 함수는 계산된 값으로 넣습니다. 내용을 이어 붙이지는 않습니다.",
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

type SheetRef = { file: string; sheet: string };

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
  // 체크를 풀어 병합에서 뺀 시트. 키: 파일+시트. 새로 넣은 파일의 시트는 기본으로 모두 들어간다.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  // 항목명 줄을 한꺼번에 바꿀 시트.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkRow, setBulkRow] = useState("");
  // 숫자를 입력하는 도중의 글자(비우고 다시 쓰는 중에도 칸이 튀지 않게).
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzedFor, setAnalyzedFor] = useState("");
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
  const excludedList = useMemo<SheetRef[]>(
    () =>
      [...excluded].map((key) => {
        const [file, sheet] = key.split("\u0000");
        return { file, sheet };
      }),
    [excluded],
  );

  const request = useMemo(
    () => ({
      inputs,
      mode,
      include_hidden_sheets: includeHidden,
      add_source_file: addSourceFile,
      add_source_sheet: addSourceSheet,
      header_overrides: overrideList,
      excluded_sheets: excludedList,
    }),
    [inputs, mode, includeHidden, addSourceFile, addSourceSheet, overrideList, excludedList],
  );
  const requestKey = useMemo(() => JSON.stringify(request), [request]);

  // 설정이 바뀌면 잠시 뒤 다시 읽어 결과 미리보기를 새로 만든다. 파일은 만들지 않는다.
  // 항목명 줄 색·데이터 행 수는 화면에서 바로 다시 그리고, 이 조회는 결과 미리보기만 늦게 따라온다.
  useEffect(() => {
    if (!inputs.length) {
      setAnalysis(null);
      setAnalyzedFor("");
      setAnalyzeError("");
      return;
    }
    const id = ++requestId.current;
    setAnalyzing(true);
    const timer = window.setTimeout(() => {
      runNativeTool(`${TOOL_ID}__analyze`, request)
        .then((result) => {
          if (id !== requestId.current) return;
          setAnalysis(result as unknown as Analysis);
          setAnalyzedFor(requestKey);
          setAnalyzeError("");
        })
        .catch((reason) => {
          if (id !== requestId.current) return;
          setAnalysis(null);
          setAnalyzedFor("");
          setAnalyzeError(reason instanceof Error ? reason.message : String(reason));
        })
        .finally(() => {
          if (id === requestId.current) setAnalyzing(false);
        });
    }, 450);
    return () => window.clearTimeout(timer);
  }, [request, requestKey, inputs.length]);

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

  const dropKeysOf = <T,>(record: Record<string, T>, path: string) =>
    Object.fromEntries(Object.entries(record).filter(([key]) => !key.startsWith(`${path}\u0000`)));
  const dropSetOf = (set: Set<string>, path: string) =>
    new Set([...set].filter((key) => !key.startsWith(`${path}\u0000`)));

  const removeInput = (path: string) => {
    setInputs((current) => current.filter((item) => item !== path));
    setOverrides((current) => dropKeysOf(current, path));
    setDrafts((current) => dropKeysOf(current, path));
    setExcluded((current) => dropSetOf(current, path));
    setSelected((current) => dropSetOf(current, path));
  };

  const clearInputs = () => {
    setInputs([]);
    setOverrides({});
    setDrafts({});
    setExcluded(new Set());
    setSelected(new Set());
  };

  const headerOf = (sheet: SheetInfo) =>
    overrides[sheetKey(sheet.file, sheet.sheet)] ?? sheet.auto_header_row ?? sheet.header_row ?? 1;

  const clampRow = (sheet: SheetInfo, row: number) =>
    Math.max(1, Math.min(Math.round(row) || 1, sheet.row_count ?? Math.max(1, Math.round(row) || 1)));

  /** 여러 시트의 항목명 줄을 한 번에 정한다. 자동으로 찾은 값과 같으면 '직접 고침' 표시를 지운다. */
  const applyHeaders = (targets: SheetInfo[], pick: (sheet: SheetInfo) => number) => {
    setOverrides((current) => {
      const next = { ...current };
      for (const sheet of targets) {
        const key = sheetKey(sheet.file, sheet.sheet);
        const value = clampRow(sheet, pick(sheet));
        if (value === sheet.auto_header_row) delete next[key];
        else next[key] = value;
      }
      return next;
    });
  };
  const setHeader = (sheet: SheetInfo, row: number) => applyHeaders([sheet], () => row);

  const typeHeader = (sheet: SheetInfo, text: string) => {
    const key = sheetKey(sheet.file, sheet.sheet);
    setDrafts((current) => ({ ...current, [key]: text }));
    const value = Number(text);
    if (text.trim() && Number.isInteger(value) && value >= 1 && value <= (sheet.row_count ?? value)) {
      setHeader(sheet, value);
    }
  };
  const endTyping = (sheet: SheetInfo) =>
    setDrafts((current) => {
      const next = { ...current };
      delete next[sheetKey(sheet.file, sheet.sheet)];
      return next;
    });

  const toggleIn = (setter: typeof setExcluded, keys: string[], on: boolean) =>
    setter((current) => {
      const next = new Set(current);
      for (const key of keys) {
        if (on) next.add(key);
        else next.delete(key);
      }
      return next;
    });

  const toggle = (key: string) => toggleIn(setExpanded, [key], !expanded.has(key));

  const pickOutput = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "저장 폴더 선택" });
    if (typeof chosen === "string") setOutput(chosen);
  };

  const allSheets = analysis?.mode === mode ? analysis.sheets : [];
  const liveKeys = new Set(allSheets.map((sheet) => sheetKey(sheet.file, sheet.sheet)));
  // 목록에 지금 있는 시트에 대해서만 뺀 표시를 보낸다(숨긴 시트를 다시 감추는 등).
  const isIn = (sheet: SheetInfo) => !excluded.has(sheetKey(sheet.file, sheet.sheet));
  const chosenSheets = allSheets.filter(isIn);
  const results = analysis?.mode === mode && analyzedFor === requestKey ? analysis.results : [];
  const staleResults = analysis?.mode === mode && analyzedFor !== requestKey ? analysis.results : [];
  const shownResults = results.length ? results : staleResults;
  const resultsStale = !results.length && !!staleResults.length;
  const changedCount = chosenSheets.filter((sheet) => sheetKey(sheet.file, sheet.sheet) in overrides).length;
  const selectedSheets = chosenSheets.filter((sheet) => selected.has(sheetKey(sheet.file, sheet.sheet)));
  const allSelected = !!chosenSheets.length && selectedSheets.length === chosenSheets.length;
  const nothingChosen = !!allSheets.length && !chosenSheets.length;

  // 시트 이름별로 묶어 '3월만' 처럼 한 번에 고를 수 있게 한다.
  const sheetNames = useMemo(() => {
    const names = new Map<string, string[]>();
    for (const sheet of allSheets) {
      const list = names.get(sheet.sheet) ?? [];
      list.push(sheetKey(sheet.file, sheet.sheet));
      names.set(sheet.sheet, list);
    }
    return [...names.entries()];
  }, [allSheets]);
  const byFile = useMemo(() => {
    const files = new Map<string, SheetInfo[]>();
    for (const sheet of allSheets) {
      const list = files.get(sheet.file) ?? [];
      list.push(sheet);
      files.set(sheet.file, list);
    }
    return [...files.entries()];
  }, [allSheets]);

  const dataRowsOf = (sheet: SheetInfo, header: number): number | null => {
    const upto = sheet.filled_upto;
    if (upto && sheet.filled_total !== undefined && header < upto.length) return sheet.filled_total - upto[header];
    if (sheet.header_row === header && sheet.data_rows !== undefined) return sheet.data_rows;
    return null;
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
        excluded_sheets: excludedList.filter((ref) => liveKeys.has(sheetKey(ref.file, ref.sheet))),
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

  const bulkValue = Number(bulkRow);
  const bulkValid = !!bulkRow.trim() && Number.isInteger(bulkValue) && bulkValue >= 1;

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
              <button className="link-button" onClick={clearInputs}>
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
              <strong>병합할 시트 고르기</strong>
            </div>
            {analyzing && !allSheets.length && (
              <span className="em-busy">
                <LoaderCircle className="spin" size={14} />
                읽는 중
              </span>
            )}
          </div>

          {analyzeError && <p className="em-error">파일을 읽지 못했습니다: {analyzeError}</p>}
          {!!analysis?.errors.length && analysis.mode === mode && (
            <ul className="em-notes is-error">
              {analysis.errors.map((text) => (
                <li key={text}>
                  <TriangleAlert size={14} />
                  {text}
                </li>
              ))}
            </ul>
          )}

          {!!allSheets.length && (
            <>
              <div className="em-pick-bar">
                <span className="em-pick-count">
                  시트 {allSheets.length}개 중 <b>{chosenSheets.length}개</b>를 넣습니다.
                </span>
                <button className="link-button" onClick={() => setExcluded(new Set())}>
                  모두 넣기
                </button>
                <button className="link-button" onClick={() => setExcluded(new Set(liveKeys))}>
                  모두 빼기
                </button>
              </div>
              {sheetNames.length > 1 && (
                <div className="em-name-chips">
                  <span>시트 이름으로 한 번에</span>
                  {sheetNames.map(([name, keys]) => {
                    const inCount = keys.filter((key) => !excluded.has(key)).length;
                    const state = inCount === keys.length ? "is-all" : inCount ? "is-some" : "is-none";
                    return (
                      <button
                        key={name}
                        className={`em-name-chip ${state}`}
                        title={state === "is-all" ? `'${name}' 시트를 모두 뺍니다` : `'${name}' 시트를 모두 넣습니다`}
                        onClick={() => toggleIn(setExcluded, keys, state === "is-all")}
                      >
                        {name}
                        <small>
                          {inCount}/{keys.length}
                        </small>
                      </button>
                    );
                  })}
                </div>
              )}
              {sheetNames.length > 1 && (
                <p className="em-help">
                  이름을 누르면 모든 파일의 그 시트를 한꺼번에 넣거나 뺍니다. 한 가지 시트만 쓰려면 '모두 빼기'를 누른 뒤 그
                  이름을 누르세요.
                </p>
              )}
              <div className="em-files">
                {byFile.map(([file, list]) => (
                  <div key={file} className="em-file">
                    <strong title={file}>{fileName(file)}</strong>
                    <div className="em-file-sheets">
                      {list.map((sheet) => {
                        const key = sheetKey(sheet.file, sheet.sheet);
                        const on = isIn(sheet);
                        return (
                          <label key={key} className={`em-sheet-check ${on ? "is-on" : ""}`}>
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={(event) => toggleIn(setExcluded, [key], !event.target.checked)}
                            />
                            {sheet.sheet}
                            {sheet.hidden && <small> (숨김)</small>}
                            {!merging && on && sheet.result_title && <em>→ '{sheet.result_title}'</em>}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
              {nothingChosen && <p className="em-error">병합할 시트를 하나 이상 고르세요.</p>}
            </>
          )}
        </section>
      )}

      {merging && !!chosenSheets.length && (
        <section className="task-card split-card">
          <div className="task-heading">
            <div>
              <span className="step-badge">4</span>
              <strong>시트별 항목명 줄 확인</strong>
            </div>
          </div>
          <p className="em-help">
            각 시트는 <b>항목명 줄(학교명·학생수처럼 칸 이름이 적힌 줄) 아래부터</b> 이어 붙입니다. 자동으로 찾은 줄이 틀리면
            숫자를 고치거나, 미리보기에서 행 번호를 누르세요.
            {changedCount > 0 && <b className="em-changed"> 직접 고친 시트 {changedCount}개</b>}
          </p>

          <div className="em-bulk">
            <label className="em-bulk-all">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(node) => {
                  if (node) node.indeterminate = !allSelected && selectedSheets.length > 0;
                }}
                onChange={(event) =>
                  setSelected(
                    event.target.checked
                      ? new Set(chosenSheets.map((sheet) => sheetKey(sheet.file, sheet.sheet)))
                      : new Set(),
                  )
                }
              />
              전체 선택
            </label>
            <span className="em-bulk-text">
              <CheckSquare size={14} />
              선택한 시트 <b>{selectedSheets.length}개</b>의 항목명 줄을
            </span>
            <input
              className="em-bulk-input"
              type="number"
              min={1}
              value={bulkRow}
              placeholder="번호"
              onChange={(event) => setBulkRow(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && bulkValid && selectedSheets.length) applyHeaders(selectedSheets, () => bulkValue);
              }}
            />
            <span className="em-bulk-text">번째 줄로</span>
            <button
              className="secondary-button"
              disabled={!bulkValid || !selectedSheets.length}
              onClick={() => applyHeaders(selectedSheets, () => bulkValue)}
            >
              바꾸기
            </button>
            <button
              className="secondary-button"
              disabled={!selectedSheets.length}
              onClick={() => applyHeaders(selectedSheets, (sheet) => sheet.auto_header_row ?? 1)}
            >
              자동으로 되돌리기
            </button>
          </div>

          <div className="em-sheets">
            {chosenSheets.map((sheet) => {
              const key = sheetKey(sheet.file, sheet.sheet);
              const open = expanded.has(key);
              const manual = key in overrides;
              const header = headerOf(sheet);
              const rowsCount = dataRowsOf(sheet, header);
              const preview = sheet.preview ?? [];
              const shown = Math.min(preview.length, Math.max(10, header + 6));
              return (
                <div key={key} className={`em-sheet ${manual ? "is-manual" : ""} ${selected.has(key) ? "is-selected" : ""}`}>
                  <div className="em-sheet-head">
                    <input
                      className="em-select"
                      type="checkbox"
                      title="한꺼번에 바꿀 시트로 선택"
                      checked={selected.has(key)}
                      onChange={(event) => toggleIn(setSelected, [key], event.target.checked)}
                    />
                    <button className="em-toggle" onClick={() => toggle(key)} title="위쪽 행 미리보기">
                      {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      <span className="em-sheet-name">
                        {fileName(sheet.file)} <em>›</em> {sheet.sheet}
                        {sheet.hidden && <small> (숨긴 시트)</small>}
                      </span>
                    </button>
                    <span className="em-rows">
                      데이터 {rowsCount === null ? "…" : rowsCount.toLocaleString()}행
                    </span>
                    <label className="em-header-input">
                      항목명
                      <input
                        type="number"
                        min={1}
                        max={sheet.row_count}
                        value={drafts[key] ?? String(header)}
                        onChange={(event) => typeHeader(sheet, event.target.value)}
                        onBlur={() => endTyping(sheet)}
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
                          {preview.slice(0, shown).map((row, index) => {
                            const rowNo = index + 1;
                            const kind = rowNo < header ? "is-above" : rowNo === header ? "is-header" : "is-data";
                            return (
                              <tr key={rowNo} className={kind}>
                                <th>
                                  <button title={`${rowNo}번째 줄을 항목명 줄로`} onClick={() => setHeader(sheet, rowNo)}>
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
                      {header > preview.length && (
                        <p className="em-more">미리보기는 위쪽 {preview.length}줄까지만 보여 줍니다.</p>
                      )}
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
        </section>
      )}

      {merging && !!chosenSheets.length && !!shownResults.length && (
        <section className={`task-card split-card ${resultsStale ? "em-stale" : ""}`}>
          <div className="task-heading">
            <div>
              <span className="step-badge">5</span>
              <strong>결과 미리보기</strong>
            </div>
            {resultsStale && (
              <span className="em-busy">
                <LoaderCircle className="spin" size={14} />
                바뀐 설정으로 새로 만드는 중
              </span>
            )}
          </div>
          {shownResults.map((item) => (
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
        <button className="primary-button" onClick={() => void run()} disabled={running || !inputs.length || nothingChosen}>
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
