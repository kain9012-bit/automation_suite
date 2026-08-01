import { useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { FileInput, FolderOpen, LoaderCircle, Play, ShieldCheck } from "lucide-react";
import { resultPath, revealPath, runNativeTool } from "../lib/bridge";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import "./excel-split-panel.css";

type Action = "extract" | "delete" | "split" | "reorder";

const ACTIONS: { id: Action; label: string; hint: string }[] = [
  { id: "extract", label: "페이지 추출", hint: "필요한 페이지만 새 PDF로 뽑습니다." },
  { id: "delete", label: "페이지 삭제", hint: "지정한 페이지를 뺀 PDF를 만듭니다." },
  { id: "split", label: "페이지 분할", hint: "PDF를 여러 파일로 나눕니다." },
  { id: "reorder", label: "페이지 재배열", hint: "페이지 순서를 바꿉니다." },
];

const MODES: Record<Action, { id: string; label: string; spec?: string }[]> = {
  extract: [
    { id: "pages", label: "특정 페이지 / 범위 추출", spec: "예: 1,3,5-8" },
    { id: "odd", label: "홀수 페이지 추출" },
    { id: "even", label: "짝수 페이지 추출" },
  ],
  delete: [
    { id: "pages", label: "특정 페이지 / 범위 삭제", spec: "예: 2,4,9-11" },
    { id: "first", label: "첫 페이지 삭제" },
    { id: "last", label: "마지막 페이지 삭제" },
    { id: "odd", label: "홀수 페이지 삭제" },
    { id: "even", label: "짝수 페이지 삭제" },
  ],
  split: [
    { id: "every_n", label: "N페이지 단위 분할" },
    { id: "at_pages", label: "기준 페이지로 분할", spec: "예: 5,12 (해당 페이지 앞에서 자름)" },
  ],
  reorder: [
    { id: "sequence", label: "새 페이지 순서 직접 입력", spec: "예: 3,1,2,4" },
    { id: "move", label: "한 페이지를 다른 위치로 이동" },
    { id: "swap", label: "두 페이지 위치 맞바꾸기" },
  ],
};

export function PdfOrganizerPanel({ tool }: { tool: ToolManifest }) {
  const [source, setSource] = useState("");
  const [output, setOutput] = useState("");
  const [action, setAction] = useState<Action>("extract");
  const [mode, setMode] = useState("pages");
  const [spec, setSpec] = useState("");
  const [number, setNumber] = useState(2);
  const [sourcePage, setSourcePage] = useState(1);
  const [targetPage, setTargetPage] = useState(1);
  const [zipOutput, setZipOutput] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [done, setDone] = useState("");

  // 작업을 바꾸면 그 작업의 첫 방식으로 되돌린다.
  useEffect(() => {
    setMode(MODES[action][0].id);
    setSpec("");
  }, [action]);

  const activeMode = MODES[action].find((item) => item.id === mode) ?? MODES[action][0];

  const pickSource = async () => {
    const selected = await openDialog({
      multiple: false,
      title: "정리할 PDF 선택",
      filters: [{ name: "PDF 파일", extensions: ["pdf"] }],
    });
    if (typeof selected === "string") setSource(selected);
  };

  const dropping = useFileDrop((paths) => {
    const usable = filterByExtension(paths, ["pdf"]);
    if (!usable.length) {
      setLog((items) => [...items, "PDF 파일만 넣을 수 있습니다."]);
      return;
    }
    setSource(usable[0]);
  });

  const pickOutput = async () => {
    const selected = await openDialog({ directory: true, multiple: false, title: "저장 폴더 선택" });
    if (typeof selected === "string") setOutput(selected);
  };

  const run = async () => {
    if (!source) {
      setLog((items) => [...items, "정리할 PDF를 먼저 선택하세요."]);
      return;
    }
    if (activeMode.spec && !spec.trim()) {
      setLog((items) => [...items, "페이지 지정 값을 입력하세요."]);
      return;
    }
    setRunning(true);
    setLog((items) => [...items, `${tool.name} 작업을 시작합니다.`]);
    try {
      const result = await runNativeTool("pdf_page_organizer", {
        inputs: [source],
        output,
        action,
        mode,
        spec,
        number,
        source_page: sourcePage,
        target_page: targetPage,
        zip_output: zipOutput,
      });
      const saved = resultPath(result);
      setDone(saved);
      setLog((items) =>
        [...items, String(result.message ?? "작업이 완료되었습니다."), saved ? `저장 위치: ${saved}` : ""].filter(
          Boolean,
        ),
      );
    } catch (reason) {
      setLog((items) => [
        ...items,
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
          <p>{tool.description || "PDF 페이지를 추출·삭제·분할·재배열합니다."}</p>
        </div>
      </div>

      <section className="task-card split-card">
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
        <button className={`drop-zone ${dropping ? "is-dropping" : ""}`} onClick={() => void pickSource()}>
          <FolderOpen size={30} />
          <strong>정리할 PDF 파일을 선택하세요</strong>
          <span>
            {dropping ? "여기에 놓으면 처리 대상으로 넣습니다." : "클릭해서 고르거나, 창으로 끌어다 놓으세요."}
          </span>
        </button>
        {!!source && (
          <ul className="selected-files">
            <li>{source}</li>
          </ul>
        )}
      </section>

      <section className="task-card split-card">
        <div className="task-heading">
          <div>
            <span className="step-badge">2</span>
            <strong>작업 설정</strong>
          </div>
        </div>

        <div className="split-modes">
          {ACTIONS.map((item) => (
            <button
              key={item.id}
              className={`split-mode ${action === item.id ? "is-active" : ""}`}
              onClick={() => setAction(item.id)}
            >
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </div>

        <div className="split-fields">
          <label>
            <span>세부 방식</span>
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              {MODES[action].map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          {!!activeMode.spec && (
            <label>
              <span>페이지 지정</span>
              <input
                type="text"
                value={spec}
                placeholder={activeMode.spec}
                onChange={(event) => setSpec(event.target.value)}
              />
            </label>
          )}

          {action === "split" && mode === "every_n" && (
            <label>
              <span>몇 페이지씩 나눌지</span>
              <input
                type="number"
                min={1}
                value={number}
                onChange={(event) => setNumber(Number(event.target.value) || 1)}
              />
            </label>
          )}

          {action === "reorder" && (mode === "move" || mode === "swap") && (
            <>
              <label>
                <span>{mode === "move" ? "옮길 페이지" : "첫 번째 페이지"}</span>
                <input
                  type="number"
                  min={1}
                  value={sourcePage}
                  onChange={(event) => setSourcePage(Number(event.target.value) || 1)}
                />
              </label>
              <label>
                <span>{mode === "move" ? "옮겨 놓을 위치" : "두 번째 페이지"}</span>
                <input
                  type="number"
                  min={1}
                  value={targetPage}
                  onChange={(event) => setTargetPage(Number(event.target.value) || 1)}
                />
              </label>
            </>
          )}
        </div>

        {action === "split" && (
          <label className="field-check standalone">
            <input
              type="checkbox"
              checked={zipOutput}
              onChange={(event) => setZipOutput(event.target.checked)}
            />
            분할 결과를 ZIP으로도 만들기
          </label>
        )}

        <label className="split-output">
          <span>저장 폴더</span>
          <div className="split-row">
            <input value={output} readOnly placeholder="비우면 원본과 같은 폴더에 저장합니다" />
            <button className="secondary-button" onClick={() => void pickOutput()}>
              <FolderOpen size={15} />
              찾아보기
            </button>
          </div>
        </label>
      </section>

      <div className="run-row">
        <button className="primary-button" onClick={() => void run()} disabled={running || !source}>
          {running ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
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
