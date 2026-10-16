import { useEffect, useMemo, useRef, useState } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  ChevronLeft,
  ChevronRight,
  FileInput,
  FilePlus2,
  FolderOpen,
  LoaderCircle,
  Maximize2,
  Redo2,
  RotateCcw,
  RotateCw,
  Save,
  ShieldCheck,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { resultPath, revealPath, runNativeTool } from "../lib/bridge";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import { ResultDialog, readResultPopup, type ResultPopup } from "./ResultDialog";
import "./excel-split-panel.css";
import "./pdf-organizer.css";

/** 불러온 PDF 한 개. */
type PdfDoc = { id: number; path: string; name: string; pageCount: number };
/** 화면에 놓인 페이지 한 장. 같은 원본 페이지를 두 번 넣을 수도 있어 key 를 따로 둔다. */
type PageItem = { key: string; docId: number; page: number; rotate: number };
type Picture = { image: string; width: number; height: number };
type SaveMode = "single" | "every_n" | "each";

const TOOL_ID = "pdf_page_organizer";
const HISTORY_LIMIT = 60;

const SAVE_MODES: { id: SaveMode; label: string; hint: string }[] = [
  { id: "single", label: "한 파일로 저장", hint: "화면의 순서대로 PDF 하나를 만듭니다." },
  { id: "every_n", label: "N쪽씩 나눠 저장", hint: "정한 쪽수마다 파일을 나눕니다." },
  { id: "each", label: "한 쪽씩 따로 저장", hint: "페이지마다 PDF 한 개씩 만듭니다." },
];

const pictureKey = (docId: number, page: number) => `${docId}:${page}`;

/** 90도 단위 회전을 0·90·180·270 으로 맞춘다. */
const turn = (value: number, delta: number) => (((value + delta) % 360) + 360) % 360;

export function PdfOrganizerPanel({
  tool,
  onReset,
}: {
  tool: ToolManifest;
  onReset?: () => void;
}) {
  const [docs, setDocs] = useState<PdfDoc[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, Picture>>({});
  const [pages, setPages] = useState<PageItem[]>([]);
  const [past, setPast] = useState<PageItem[][]>([]);
  const [future, setFuture] = useState<PageItem[][]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  const [saveMode, setSaveMode] = useState<SaveMode>("single");
  const [number, setNumber] = useState(2);
  const [onlySelected, setOnlySelected] = useState(false);
  const [zipOutput, setZipOutput] = useState(false);
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [done, setDone] = useState("");
  const [popup, setPopup] = useState<ResultPopup | null>(null);

  // 크게 보기: 지금 보고 있는 화면상 순서.
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [bigPictures, setBigPictures] = useState<Record<string, Picture>>({});
  const [bigLoading, setBigLoading] = useState(false);

  // 끌어 옮기기: 옮기는 페이지들과 끼워 넣을 자리.
  const [dragKeys, setDragKeys] = useState<string[] | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);

  const nextDocId = useRef(1);
  const nextPageKey = useRef(1);
  const lastClicked = useRef<string | null>(null);
  const suppressClick = useRef(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLPreElement>(null);

  // 불러오기처럼 기다렸다가 목록을 바꾸는 동작이 최신 목록을 쓰도록 한다.
  const pagesRef = useRef(pages);
  pagesRef.current = pages;

  const docById = useMemo(() => new Map(docs.map((doc) => [doc.id, doc])), [docs]);
  const selectedCount = pages.filter((item) => selected.has(item.key)).length;

  // 불러오는 동안 파이썬이 올리는 진행 상황을 기록에 붙인다.
  useEffect(() => {
    let stop: UnlistenFn | undefined;
    void listen<{ toolId: string; text: string }>("tool-progress", (event) => {
      if (event.payload.toolId.split("__")[0] !== TOOL_ID) return;
      setLog((items) => [...items, event.payload.text]);
    })
      .then((unlisten) => { stop = unlisten; })
      .catch(() => undefined);
    return () => stop?.();
  }, []);

  useEffect(() => {
    const box = logRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [log]);

  /** 페이지 목록을 바꾼다. 되돌리기를 위해 바꾸기 전 상태를 쌓아 둔다. */
  const commit = (next: PageItem[]) => {
    const before = pagesRef.current;
    setPast((items) => [...items.slice(-(HISTORY_LIMIT - 1)), before]);
    setFuture([]);
    pagesRef.current = next;
    setPages(next);
    const alive = new Set(next.map((item) => item.key));
    setSelected((current) => new Set([...current].filter((key) => alive.has(key))));
  };

  const undo = () => {
    if (!past.length) return;
    setFuture((items) => [pages, ...items]);
    setPages(past[past.length - 1]);
    setPast((items) => items.slice(0, -1));
  };

  const redo = () => {
    if (!future.length) return;
    setPast((items) => [...items, pages]);
    setPages(future[0]);
    setFuture((items) => items.slice(1));
  };

  const addFiles = async (paths: string[]) => {
    const usable = filterByExtension(paths, ["pdf"]);
    if (!usable.length) {
      setLog((items) => [...items, "PDF 파일만 넣을 수 있습니다."]);
      return;
    }
    setLoading(true);
    setLog((items) => [...items, `PDF ${usable.length}개를 불러옵니다.`]);
    try {
      const result = (await runNativeTool(`${TOOL_ID}__load`, { inputs: usable })) as unknown as {
        documents: { path: string; name: string; page_count: number; pages: Picture[] }[];
      };
      const newDocs: PdfDoc[] = [];
      const newThumbs: Record<string, Picture> = {};
      const newPages: PageItem[] = [];
      for (const item of result.documents) {
        const id = nextDocId.current++;
        newDocs.push({ id, path: item.path, name: item.name, pageCount: item.page_count });
        item.pages.forEach((picture, page) => {
          newThumbs[pictureKey(id, page)] = picture;
          newPages.push({ key: `p${nextPageKey.current++}`, docId: id, page, rotate: 0 });
        });
      }
      setDocs((current) => [...current, ...newDocs]);
      setThumbs((current) => ({ ...current, ...newThumbs }));
      commit([...pagesRef.current, ...newPages]);
      setLog((items) => [
        ...items,
        ...newDocs.map((doc) => `${doc.name}: ${doc.pageCount}쪽을 넣었습니다.`),
      ]);
    } catch (reason) {
      setLog((items) => [
        ...items,
        `불러오지 못했습니다: ${reason instanceof Error ? reason.message : String(reason)}`,
      ]);
    } finally {
      setLoading(false);
    }
  };

  const pickFiles = async () => {
    const chosen = await openDialog({
      multiple: true,
      title: "편집할 PDF 선택",
      filters: [{ name: "PDF 파일", extensions: ["pdf"] }],
    });
    if (!chosen) return;
    void addFiles(Array.isArray(chosen) ? chosen : [chosen]);
  };

  const dropping = useFileDrop((paths) => void addFiles(paths), !loading && !running);

  const pickOutput = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "저장 폴더 선택" });
    if (typeof chosen === "string") setOutput(chosen);
  };

  // ---- 페이지 조작 ----

  const deleteKeys = (keys: string[]) => {
    if (!keys.length) return;
    const drop = new Set(keys);
    commit(pages.filter((item) => !drop.has(item.key)));
  };

  const rotateKeys = (keys: string[], delta: number) => {
    if (!keys.length) return;
    const target = new Set(keys);
    commit(pages.map((item) => (target.has(item.key) ? { ...item, rotate: turn(item.rotate, delta) } : item)));
  };

  const selectedKeys = () => pages.filter((item) => selected.has(item.key)).map((item) => item.key);

  const clickCard = (key: string, event: React.MouseEvent) => {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    if (event.shiftKey && lastClicked.current) {
      const from = pages.findIndex((item) => item.key === lastClicked.current);
      const to = pages.findIndex((item) => item.key === key);
      if (from >= 0 && to >= 0) {
        const [start, end] = from < to ? [from, to] : [to, from];
        setSelected((current) => {
          const next = new Set(current);
          pages.slice(start, end + 1).forEach((item) => next.add(item.key));
          return next;
        });
        return;
      }
    }
    lastClicked.current = key;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /**
   * 카드를 끌어 순서를 바꾼다. 고른 카드를 끌면 고른 것 전부가 함께 움직인다.
   *
   * HTML의 draggable 은 Tauri 의 파일 드롭 감지와 부딪혀 쓰지 않고 마우스 위치를 직접 읽는다.
   * 조금 움직여야 끌기로 보고, 그 전에 놓으면 그냥 클릭(선택)이다.
   */
  const startDrag = (key: string, event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    if ((event.target as HTMLElement).closest(".po-card-actions")) return;
    const startX = event.clientX;
    const startY = event.clientY;
    let moving: string[] | null = null;
    let insertAt: number | null = null;
    let lastY = startY;

    const scroller = (() => {
      let node: HTMLElement | null = gridRef.current;
      while (node) {
        const style = getComputedStyle(node);
        if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) return node;
        node = node.parentElement;
      }
      return document.scrollingElement as HTMLElement | null;
    })();

    /** 마우스 위치에서 끼워 넣을 자리. 가장 가까운 카드의 왼쪽 절반이면 앞, 오른쪽이면 뒤. */
    const slotAt = (x: number, y: number) => {
      const cards = Array.from(gridRef.current?.querySelectorAll<HTMLElement>(".po-card") ?? []);
      let best = -1;
      let bestDistance = Infinity;
      cards.forEach((card, index) => {
        const box = card.getBoundingClientRect();
        const cx = box.left + box.width / 2;
        const cy = box.top + box.height / 2;
        const dx = Math.max(0, Math.abs(x - cx) - box.width / 2);
        const dy = Math.max(0, Math.abs(y - cy) - box.height / 2);
        const distance = dy * 4 + dx + Math.abs(x - cx) * 0.01;
        if (distance < bestDistance) {
          bestDistance = distance;
          best = index;
        }
      });
      if (best < 0) return 0;
      const box = cards[best].getBoundingClientRect();
      return x < box.left + box.width / 2 ? best : best + 1;
    };

    const timer = window.setInterval(() => {
      if (!moving || !scroller) return;
      const edge = 70;
      const top = scroller === document.scrollingElement ? 0 : scroller.getBoundingClientRect().top;
      const bottom = scroller === document.scrollingElement ? window.innerHeight : scroller.getBoundingClientRect().bottom;
      if (lastY < top + edge) scroller.scrollTop -= 14;
      else if (lastY > bottom - edge) scroller.scrollTop += 14;
    }, 30);

    const onMove = (moveEvent: PointerEvent) => {
      lastY = moveEvent.clientY;
      if (!moving) {
        if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 6) return;
        moving = selected.has(key) ? selectedKeys() : [key];
        setDragKeys(moving);
      }
      insertAt = slotAt(moveEvent.clientX, moveEvent.clientY);
      setDropAt(insertAt);
    };

    const finish = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.clearInterval(timer);
      if (moving && insertAt !== null) {
        suppressClick.current = true;
        const moveSet = new Set(moving);
        const before = pages.slice(0, insertAt).filter((item) => !moveSet.has(item.key)).length;
        const rest = pages.filter((item) => !moveSet.has(item.key));
        const block = pages.filter((item) => moveSet.has(item.key));
        const next = [...rest.slice(0, before), ...block, ...rest.slice(before)];
        if (next.some((item, index) => item.key !== pages[index].key)) commit(next);
        // 클릭 이벤트가 오지 않는 경우를 대비해 잠시 뒤 풀어 둔다.
        window.setTimeout(() => { suppressClick.current = false; }, 0);
      }
      setDragKeys(null);
      setDropAt(null);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
  };

  // ---- 크게 보기 ----

  const previewItem = previewIndex !== null ? pages[previewIndex] : undefined;

  useEffect(() => {
    if (previewIndex !== null && !pages[previewIndex]) {
      setPreviewIndex(pages.length ? Math.min(previewIndex, pages.length - 1) : null);
    }
  }, [pages, previewIndex]);

  useEffect(() => {
    if (!previewItem) return;
    const id = pictureKey(previewItem.docId, previewItem.page);
    if (bigPictures[id]) {
      setBigLoading(false);
      return;
    }
    const doc = docById.get(previewItem.docId);
    if (!doc) return;
    let cancelled = false;
    setBigLoading(true);
    runNativeTool(`${TOOL_ID}__preview`, { inputs: [doc.path], page: previewItem.page })
      .then((result) => {
        if (cancelled) return;
        const picture = result as unknown as Picture;
        if (typeof picture.image === "string") {
          setBigPictures((current) => ({ ...current, [id]: picture }));
        }
      })
      .catch(() => undefined)
      .finally(() => { if (!cancelled) setBigLoading(false); });
    return () => { cancelled = true; };
  }, [previewItem, bigPictures, docById]);

  // ---- 단축키 ----

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (popup) return;
      const ctrl = event.ctrlKey || event.metaKey;
      if (previewIndex !== null) {
        if (event.key === "Escape") setPreviewIndex(null);
        else if (event.key === "ArrowLeft") setPreviewIndex((index) => Math.max(0, (index ?? 0) - 1));
        else if (event.key === "ArrowRight") setPreviewIndex((index) => Math.min(pages.length - 1, (index ?? 0) + 1));
        return;
      }
      if (ctrl && event.key.toLowerCase() === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if (ctrl && (event.key.toLowerCase() === "y" || (event.key.toLowerCase() === "z" && event.shiftKey))) {
        event.preventDefault();
        redo();
      } else if (ctrl && event.key.toLowerCase() === "a" && pages.length) {
        event.preventDefault();
        setSelected(new Set(pages.map((item) => item.key)));
      } else if (event.key === "Delete" && selectedCount) {
        event.preventDefault();
        deleteKeys(selectedKeys());
      } else if (event.key === "Escape") {
        setSelected(new Set());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---- 저장 ----

  const save = async () => {
    const chosen = onlySelected ? pages.filter((item) => selected.has(item.key)) : pages;
    if (!chosen.length) {
      setLog((items) => [...items, "저장할 페이지가 없습니다."]);
      return;
    }
    const sequence = chosen.map((item) => ({
      path: docById.get(item.docId)?.path ?? "",
      page: item.page,
      rotate: item.rotate,
    }));
    setRunning(true);
    setLog((items) => [...items, `${chosen.length}쪽을 저장합니다.`]);
    try {
      const result = await runNativeTool(TOOL_ID, {
        sequence,
        save_mode: saveMode,
        number,
        zip_output: saveMode !== "single" && zipOutput,
        output,
      });
      const saved = resultPath(result);
      setDone(saved);
      setLog((items) =>
        [...items, String(result.message ?? "저장했습니다."), saved ? `저장 위치: ${saved}` : ""].filter(Boolean),
      );
      const info = readResultPopup((result as { popup?: unknown }).popup);
      if (info) setPopup(info);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setLog((items) => [...items, `실패: ${message}`]);
      setPopup({ level: "error", title: "저장하지 못했습니다", message });
    } finally {
      setRunning(false);
    }
  };

  const multiDocs = docs.length > 1;

  return (
    <div className={`native-tool content-column ${pages.length ? "po-wide" : ""}`}>
      <div className="native-hero">
        <div className="tool-icon type-internal_python">
          <FileInput size={23} />
        </div>
        <div>
          <span className="eyebrow">{tool.top_tab}</span>
          <h2>{tool.name}</h2>
          <p>{tool.description || "PDF 페이지를 미리 보면서 정리합니다."}</p>
        </div>
      </div>

      <section className="task-card split-card" data-tour="organize-pages">
        <div className="task-heading">
          <div>
            <span className="step-badge">1</span>
            <strong>페이지 편집</strong>
          </div>
          <span className="privacy-note">
            <ShieldCheck size={15} />
            파일은 PC 밖으로 전송되지 않습니다.
          </span>
        </div>

        {!pages.length ? (
          <button
            className={`drop-zone ${dropping ? "is-dropping" : ""}`}
            onClick={() => void pickFiles()}
            disabled={loading}
          >
            {loading ? <LoaderCircle className="spin" size={30} /> : <FolderOpen size={30} />}
            <strong>{loading ? "페이지를 불러오는 중입니다" : "편집할 PDF 파일을 선택하세요"}</strong>
            <span>
              {dropping
                ? "여기에 놓으면 불러옵니다."
                : "여러 개를 한꺼번에 넣으면 페이지를 섞어서 편집할 수 있습니다. 클릭해서 고르거나 창으로 끌어다 놓으세요."}
            </span>
          </button>
        ) : (
          <>
            <div className="po-toolbar">
              <div className="po-toolbar-group">
                <button className="secondary-button" onClick={undo} disabled={!past.length} title="되돌리기 (Ctrl+Z)">
                  <Undo2 size={15} />
                  되돌리기
                </button>
                <button className="secondary-button" onClick={redo} disabled={!future.length} title="다시 하기 (Ctrl+Y)">
                  <Redo2 size={15} />
                  다시 하기
                </button>
              </div>
              <div className="po-toolbar-group">
                <button
                  className="secondary-button"
                  onClick={() =>
                    setSelected(selectedCount === pages.length ? new Set() : new Set(pages.map((item) => item.key)))
                  }
                  title="전체 선택 (Ctrl+A) / 선택 해제 (Esc)"
                >
                  {selectedCount === pages.length ? "선택 해제" : "전체 선택"}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => rotateKeys(selectedKeys(), -90)}
                  disabled={!selectedCount}
                  title="고른 페이지를 왼쪽으로 돌리기"
                >
                  <RotateCcw size={15} />
                  왼쪽
                </button>
                <button
                  className="secondary-button"
                  onClick={() => rotateKeys(selectedKeys(), 90)}
                  disabled={!selectedCount}
                  title="고른 페이지를 오른쪽으로 돌리기"
                >
                  <RotateCw size={15} />
                  오른쪽
                </button>
                <button
                  className="secondary-button po-danger"
                  onClick={() => deleteKeys(selectedKeys())}
                  disabled={!selectedCount}
                  title="고른 페이지 지우기 (Delete)"
                >
                  <Trash2 size={15} />
                  지우기
                </button>
              </div>
              <div className="po-toolbar-group">
                <button className="secondary-button" onClick={() => void pickFiles()} disabled={loading}>
                  {loading ? <LoaderCircle className="spin" size={15} /> : <FilePlus2 size={15} />}
                  PDF 추가
                </button>
              </div>
            </div>

            <p className="po-status">
              총 <strong>{pages.length}</strong>쪽
              {selectedCount > 0 && (
                <>
                  {" · "}
                  <strong>{selectedCount}</strong>쪽 선택됨
                </>
              )}
              <span className="po-tip">
                클릭으로 고르기(Shift로 범위) · 끌어서 순서 바꾸기 · 두 번 클릭하면 크게 보기
              </span>
            </p>

            <div className={`po-grid ${dropping ? "is-dropping" : ""}`} ref={gridRef}>
              {pages.map((item, index) => {
                const doc = docById.get(item.docId);
                const thumb = thumbs[pictureKey(item.docId, item.page)];
                const isSelected = selected.has(item.key);
                const isDragging = dragKeys?.includes(item.key);
                return (
                  <div
                    key={item.key}
                    className={[
                      "po-card",
                      isSelected ? "is-selected" : "",
                      isDragging ? "is-dragging" : "",
                      dropAt === index ? "drop-before" : "",
                      dropAt === pages.length && index === pages.length - 1 ? "drop-after" : "",
                    ].join(" ")}
                    onPointerDown={(event) => startDrag(item.key, event)}
                    onClick={(event) => clickCard(item.key, event)}
                    onDoubleClick={() => setPreviewIndex(index)}
                    title={doc ? `${doc.name} · 원본 ${item.page + 1}쪽` : undefined}
                  >
                    <div className="po-thumb">
                      {thumb ? (
                        <img
                          src={thumb.image}
                          alt={`${index + 1}쪽`}
                          draggable={false}
                          style={{ transform: `rotate(${item.rotate}deg)` }}
                        />
                      ) : (
                        <LoaderCircle className="spin" size={18} />
                      )}
                    </div>
                    <div className="po-card-foot">
                      <span className="po-number">{index + 1}</span>
                      <span className="po-source">
                        {multiDocs && doc ? `${doc.name} · ` : ""}원본 {item.page + 1}쪽
                      </span>
                    </div>
                    <div
                      className="po-card-actions"
                      onClick={(event) => event.stopPropagation()}
                      onDoubleClick={(event) => event.stopPropagation()}
                    >
                      <button title="크게 보기" onClick={() => setPreviewIndex(index)}>
                        <Maximize2 size={13} />
                      </button>
                      <button title="오른쪽으로 돌리기" onClick={() => rotateKeys([item.key], 90)}>
                        <RotateCw size={13} />
                      </button>
                      <button className="po-delete" title="이 페이지 지우기" onClick={() => deleteKeys([item.key])}>
                        <X size={14} />
                      </button>
                    </div>
                    {isSelected && <span className="po-check">✓</span>}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>

      <section className="task-card split-card">
        <div className="task-heading">
          <div>
            <span className="step-badge">2</span>
            <strong>저장 방식</strong>
          </div>
        </div>

        <div className="split-modes" data-tour="organize-modes">
          {SAVE_MODES.map((item) => (
            <button
              key={item.id}
              className={`split-mode ${saveMode === item.id ? "is-active" : ""}`}
              onClick={() => setSaveMode(item.id)}
            >
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </div>

        {saveMode === "every_n" && (
          <div className="split-fields">
            <label>
              <span>몇 쪽씩 나눌지</span>
              <input
                type="number"
                min={1}
                value={number}
                onChange={(event) => setNumber(Math.max(1, Number(event.target.value) || 1))}
              />
            </label>
          </div>
        )}

        <label className="field-check standalone" data-tour="organize-selected">
          <input
            type="checkbox"
            checked={onlySelected && selectedCount > 0}
            disabled={!selectedCount}
            onChange={(event) => setOnlySelected(event.target.checked)}
          />
          고른 페이지만 저장{selectedCount ? ` (${selectedCount}쪽)` : " (먼저 페이지를 고르세요)"}
        </label>

        {saveMode !== "single" && (
          <label className="field-check standalone">
            <input type="checkbox" checked={zipOutput} onChange={(event) => setZipOutput(event.target.checked)} />
            나눈 결과를 ZIP으로도 만들기
          </label>
        )}

        <label className="split-output" data-tour="organize-output">
          <span>저장 폴더</span>
          <div className="split-row">
            <input value={output} readOnly placeholder="비우면 첫 번째 PDF와 같은 폴더에 저장합니다" />
            <button className="secondary-button" onClick={() => void pickOutput()}>
              <FolderOpen size={15} />
              찾아보기
            </button>
          </div>
        </label>
      </section>

      <div className="run-row" data-tour="organize-run">
        {onReset && (
          <button
            className="secondary-button"
            onClick={onReset}
            disabled={running || loading}
            title="넣은 파일과 설정을 모두 지우고 처음 상태로 돌아갑니다."
          >
            <RotateCcw size={15} />
            초기화
          </button>
        )}
        <button
          className="primary-button"
          onClick={() => void save()}
          disabled={running || loading || !pages.length || (onlySelected && !selectedCount)}
        >
          {running ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}
          {running ? "저장 중" : "PDF 저장"}
        </button>
      </div>

      <section className="log-panel" data-tour="organize-log">
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

      {previewItem && previewIndex !== null && (
        <div className="po-viewer" onClick={() => setPreviewIndex(null)}>
          <div className="po-viewer-bar" onClick={(event) => event.stopPropagation()}>
            <span>
              <strong>{previewIndex + 1}</strong> / {pages.length}쪽
              <small>
                {docById.get(previewItem.docId)?.name} · 원본 {previewItem.page + 1}쪽
              </small>
            </span>
            <div className="po-viewer-actions">
              <button onClick={() => rotateKeys([previewItem.key], -90)} title="왼쪽으로 돌리기">
                <RotateCcw size={16} />
              </button>
              <button onClick={() => rotateKeys([previewItem.key], 90)} title="오른쪽으로 돌리기">
                <RotateCw size={16} />
              </button>
              <button className="po-delete" onClick={() => deleteKeys([previewItem.key])} title="이 페이지 지우기">
                <Trash2 size={16} />
              </button>
              <button onClick={() => setPreviewIndex(null)} title="닫기 (Esc)">
                <X size={18} />
              </button>
            </div>
          </div>
          <button
            className="po-viewer-nav is-prev"
            disabled={previewIndex === 0}
            onClick={(event) => {
              event.stopPropagation();
              setPreviewIndex(Math.max(0, previewIndex - 1));
            }}
            title="이전 쪽 (←)"
          >
            <ChevronLeft size={30} />
          </button>
          <div className="po-viewer-stage" onClick={(event) => event.stopPropagation()}>
            {(() => {
              const id = pictureKey(previewItem.docId, previewItem.page);
              const picture = bigPictures[id] ?? thumbs[id];
              const sideways = previewItem.rotate % 180 !== 0;
              return picture ? (
                <img
                  src={picture.image}
                  alt=""
                  draggable={false}
                  className={sideways ? "is-sideways" : ""}
                  style={{
                    transform: sideways
                      ? `translate(-50%, -50%) rotate(${previewItem.rotate}deg)`
                      : `rotate(${previewItem.rotate}deg)`,
                  }}
                />
              ) : null;
            })()}
            {bigLoading && (
              <span className="po-viewer-loading">
                <LoaderCircle className="spin" size={18} />
                선명하게 불러오는 중
              </span>
            )}
          </div>
          <button
            className="po-viewer-nav is-next"
            disabled={previewIndex >= pages.length - 1}
            onClick={(event) => {
              event.stopPropagation();
              setPreviewIndex(Math.min(pages.length - 1, previewIndex + 1));
            }}
            title="다음 쪽 (→)"
          >
            <ChevronRight size={30} />
          </button>
        </div>
      )}

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
