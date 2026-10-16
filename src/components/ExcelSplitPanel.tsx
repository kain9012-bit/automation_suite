import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  FileInput,
  FileSpreadsheet,
  FolderOpen,
  LoaderCircle,
  Play,
  RotateCw,
  ShieldCheck,
  RotateCcw,
} from "lucide-react";
import { resultPath, revealPath, runNativeTool } from "../lib/bridge";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import "./excel-split-panel.css";
import { ResultDialog, readResultPopup, type ResultPopup } from "./ResultDialog";

const fileName = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? path;

interface SheetInfo {
  name: string;
  max_row: number;
  max_column: number;
  auto_header_row: number;
  headers: string[];
}

type Mode = "sheet" | "chunk" | "column";

const MODE_LABELS: Record<Mode, string> = {
  sheet: "시트별로 나누기",
  chunk: "행 개수로 나누기",
  column: "특정 열 값으로 나누기",
};

const MODE_HINTS: Record<Mode, string> = {
  sheet: "시트 하나가 파일 하나가 됩니다.",
  chunk: "정한 행 수만큼 잘라 여러 파일로 나눕니다.",
  column: "기준 열의 값이 같은 행끼리 모아 파일을 만듭니다.",
};

export function ExcelSplitPanel({
  tool,
  onReset,
}: {
  tool: ToolManifest;
  onReset?: () => void;
}) {
  const [source, setSource] = useState("");
  const [output, setOutput] = useState("");
  const [sheets, setSheets] = useState<SheetInfo[]>([]);
  const [sheetName, setSheetName] = useState("");
  const [preview, setPreview] = useState<string[][]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [done, setDone] = useState("");
  const [popup, setPopup] = useState<ResultPopup | null>(null);

  const [mode, setMode] = useState<Mode>("sheet");
  const [autoHeader, setAutoHeader] = useState(true);
  const [headerRow, setHeaderRow] = useState(1);
  const [splitColumn, setSplitColumn] = useState(1);
  const [rowsPerFile, setRowsPerFile] = useState(1000);
  const [skipEmptyKey, setSkipEmptyKey] = useState(true);

  const activeSheet = useMemo(
    () => sheets.find((sheet) => sheet.name === sheetName) ?? sheets[0],
    [sheets, sheetName],
  );

  // 분석 요청 번호. 큰 파일 A를 읽는 동안 작은 파일 B를 넣으면 B가 먼저 끝나고
  // A의 늦은 응답이 B를 덮어쓴다. 마지막 요청의 응답만 받는다.
  const analyzeSeq = useRef(0);

  const analyze = useCallback(
    async (path: string, wantedSheet?: string) => {
      const request = ++analyzeSeq.current;
      const stale = () => request !== analyzeSeq.current;
      setAnalyzing(true);
      try {
        const result = (await runNativeTool("excel_split__analyze", {
          inputs: [path],
          sheet_name: wantedSheet ?? "",
        })) as unknown as {
          sheets: SheetInfo[];
          preview: string[][];
          preview_sheet: string;
        };
        if (stale()) return;
        setSheets(result.sheets);
        setPreview(result.preview);
        setSheetName(result.preview_sheet);
        const found = result.sheets.find((sheet) => sheet.name === result.preview_sheet);
        if (found && autoHeader) setHeaderRow(found.auto_header_row || 1);
        setLog((items) => [...items, `파일을 읽었습니다. 시트 ${result.sheets.length}개`]);
      } catch (reason) {
        if (stale()) return;
        setSheets([]);
        setPreview([]);
        setLog((items) => [
          ...items,
          `파일을 읽지 못했습니다: ${reason instanceof Error ? reason.message : String(reason)}`,
        ]);
      } finally {
        if (!stale()) setAnalyzing(false);
      }
    },
    [autoHeader],
  );

  /** 새 파일을 받는다. 앞 파일의 시트 정보는 바로 비워 새 파일에 섞여 쓰이지 않게 한다. */
  const takeSource = (path: string) => {
    setSource(path);
    setSplitColumn(1);
    setSheets([]);
    setSheetName("");
    setPreview([]);
    void analyze(path);
  };

  useEffect(() => {
    if (activeSheet && autoHeader) setHeaderRow(activeSheet.auto_header_row || 1);
  }, [activeSheet, autoHeader]);

  const pickSource = async () => {
    const selected = await openDialog({
      multiple: false,
      directory: false,
      title: "분할할 엑셀 파일 선택",
      filters: [{ name: "엑셀 파일", extensions: ["xlsx", "xlsm", "csv"] }],
    });
    if (typeof selected !== "string") return;
    takeSource(selected);
  };

  const dropping = useFileDrop((paths) => {
    const usable = filterByExtension(paths, ["xlsx", "xlsm", "csv"]);
    if (!usable.length) {
      setLog((items) => [...items, "엑셀 파일(xlsx, xlsm, csv)만 넣을 수 있습니다."]);
      return;
    }
    takeSource(usable[0]);
  });

  const pickOutput = async () => {
    const selected = await openDialog({ directory: true, multiple: false, title: "저장 폴더 선택" });
    if (typeof selected === "string") setOutput(selected);
  };

  const changeSheet = (next: string) => {
    setSheetName(next);
    setSplitColumn(1);
    if (source) void analyze(source, next);
  };

  const run = async () => {
    // 분석이 끝나기 전에는 시트 이름이 앞 파일 것일 수 있다.
    if (analyzing) return;
    if (!source) {
      setLog((items) => [...items, "분할할 엑셀 파일을 먼저 선택하세요."]);
      return;
    }
    setRunning(true);
    setLog((items) => [...items, "분할하는 중입니다."]);
    try {
      const result = (await runNativeTool("excel_split", {
        inputs: [source],
        output,
        mode,
        sheet_name: sheetName,
        header_row: headerRow,
        split_column: splitColumn,
        rows_per_file: rowsPerFile,
        skip_empty_key: skipEmptyKey,
      })) as unknown as { message: string; output: string; error_count: number };
      const saved = resultPath(result as unknown as Record<string, unknown>);
      setDone(saved);
      setLog((items) => [...items, result.message, saved ? `저장 위치: ${saved}` : ""].filter(Boolean));
      setPopup(
        readResultPopup((result as unknown as { popup?: unknown }).popup) ?? {
          level: "success",
          title: "작업을 마쳤습니다",
          message: [result.message || "분할했습니다.", saved ? `저장 위치: ${saved}` : ""]
            .filter(Boolean)
            .join("\n\n"),
        },
      );
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setLog((items) => [...items, `실패: ${message}`]);
      setPopup({ level: "error", title: "작업을 마치지 못했습니다", message });
    } finally {
      setRunning(false);
    }
  };

  const headers = activeSheet?.headers ?? [];

  return (
    <div className="native-tool content-column">
      <div className="native-hero">
        <div className="tool-icon type-internal_python">
          <FileInput size={23} />
        </div>
        <div>
          <span className="eyebrow">{tool.top_tab}</span>
          <h2>{tool.name}</h2>
          <p>{tool.description || "하나의 엑셀 파일을 열 값, 시트, 행 수 기준으로 여러 파일로 나눕니다."}</p>
        </div>
      </div>

      <section className="task-card split-card" data-tour="split-input">
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
        <button
          className={`drop-zone ${dropping ? "is-dropping" : ""}`}
          onClick={() => void pickSource()}
        >
          {analyzing ? <LoaderCircle className="spin" size={30} /> : <FileSpreadsheet size={30} />}
          <strong>분할할 엑셀 파일을 선택하세요</strong>
          <span>
            {dropping
              ? "여기에 놓으면 처리 대상으로 넣습니다."
              : "클릭해서 고르거나, 창으로 끌어다 놓으세요."}
          </span>
        </button>
        {!!source && (
          <ul className="selected-files">
            <li title={source}>
              <span>{fileName(source)}</span>
            </li>
          </ul>
        )}
      </section>

          <section className="task-card split-card">
            <div className="task-heading">
              <div>
                <span className="step-badge">2</span>
                <strong>작업 설정</strong>
              </div>
              <button
                className="secondary-button"
                data-tour="split-reload"
                onClick={() => void analyze(source, sheetName)}
                disabled={analyzing || !source}
              >
                {analyzing ? <LoaderCircle className="spin" size={15} /> : <RotateCw size={15} />}
                다시 읽기
              </button>
            </div>

            <div className="split-modes" data-tour="split-modes">
              {(Object.keys(MODE_LABELS) as Mode[]).map((item) => (
                <button
                  key={item}
                  className={`split-mode ${mode === item ? "is-active" : ""}`}
                  onClick={() => setMode(item)}
                >
                  <strong>{MODE_LABELS[item]}</strong>
                  <small>{MODE_HINTS[item]}</small>
                </button>
              ))}
            </div>

            <div className="split-fields" data-tour="split-fields">
              <label>
                <span>대상 시트</span>
                <select
                  value={sheetName}
                  disabled={!sheets.length}
                  onChange={(event) => changeSheet(event.target.value)}
                >
                  {sheets.length ? (
                    sheets.map((sheet) => (
                      <option key={sheet.name} value={sheet.name}>
                        {sheet.name} ({sheet.max_row}행)
                      </option>
                    ))
                  ) : (
                    <option value="">파일을 선택하면 시트가 나옵니다</option>
                  )}
                </select>
              </label>

              <label>
                <span>항목명 줄 (몇 번째 줄)</span>
                <div className="field-inline">
                  <input
                    type="number"
                    min={1}
                    value={headerRow}
                    disabled={autoHeader || !sheets.length}
                    onChange={(event) => setHeaderRow(Number(event.target.value) || 1)}
                  />
                  <label className="field-check">
                    <input
                      type="checkbox"
                      checked={autoHeader}
                      disabled={!sheets.length}
                      onChange={(event) => setAutoHeader(event.target.checked)}
                    />
                    자동 감지
                  </label>
                </div>
              </label>

              {mode === "column" && (
                <label>
                  <span>기준 열</span>
                  <select
                    value={splitColumn}
                    disabled={!headers.length}
                    onChange={(event) => setSplitColumn(Number(event.target.value))}
                  >
                    {headers.length ? (
                      headers.map((header, index) => (
                        <option key={`${header}-${index}`} value={index + 1}>
                          {header?.trim() ? header : `(${index + 1}번째 열)`}
                        </option>
                      ))
                    ) : (
                      <option value={1}>파일을 선택하면 열 이름이 나옵니다</option>
                    )}
                  </select>
                </label>
              )}

              {mode === "chunk" && (
                <label>
                  <span>파일당 데이터 행 수</span>
                  <input
                    type="number"
                    min={1}
                    value={rowsPerFile}
                    onChange={(event) => setRowsPerFile(Number(event.target.value) || 1)}
                  />
                </label>
              )}
            </div>

            {mode === "column" && (
              <label className="field-check standalone">
                <input
                  type="checkbox"
                  checked={skipEmptyKey}
                  onChange={(event) => setSkipEmptyKey(event.target.checked)}
                />
                기준 열 값이 비어 있는 행은 건너뛰기
              </label>
            )}

            <label className="split-output" data-tour="split-output">
              <span>저장 폴더</span>
              <div className="split-row">
                <input
                  value={output}
                  readOnly
                  placeholder="비우면 원본 파일 옆에 '(파일명)_분할' 폴더를 만듭니다"
                />
                <button className="secondary-button" onClick={() => void pickOutput()}>
                  <FolderOpen size={15} />
                  찾아보기
                </button>
              </div>
            </label>
          </section>

          <section className="task-card split-card" data-tour="split-preview">
            <div className="task-heading">
              <div>
                <span className="step-badge">3</span>
                <strong>미리보기</strong>
              </div>
            </div>
            <p className="split-hint">
              앞쪽 30행까지만 보여 줍니다. 파란 줄이 항목명 줄(칸 이름이 적힌 줄)로 잡힌 위치입니다.
            </p>
            {preview.length ? (
              <div className="preview-wrap">
                <table className="preview-table">
                  <tbody>
                    {preview.map((row, rowIndex) => (
                      <tr key={rowIndex} className={rowIndex + 1 === headerRow ? "is-header" : ""}>
                        <th>{rowIndex + 1}</th>
                        {row.map((cell, cellIndex) => (
                          <td
                            key={cellIndex}
                            className={mode === "column" && cellIndex + 1 === splitColumn ? "is-key" : ""}
                          >
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="preview-empty">파일을 선택하면 내용이 여기에 나옵니다.</div>
            )}
          </section>

      <div className="run-row" data-tour="split-run">
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
        <button className="primary-button" onClick={() => void run()} disabled={running || analyzing || !source}>
          {running ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
          {running ? "처리 중" : "분할 실행"}
        </button>
      </div>

      <section className="log-panel" data-tour="split-log">
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
