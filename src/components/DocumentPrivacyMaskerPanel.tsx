import { useCallback, useEffect, useMemo, useRef, useState, type JSX, type PointerEvent as ReactPointerEvent } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  ChevronLeft,
  ChevronRight,
  EyeOff,
  FolderOpen,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  SquareDashedMousePointer,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { revealPath, runNativeTool } from "../lib/bridge";
import { filterByExtension, useFileDrop } from "../hooks/useFileDrop";
import type { ToolManifest } from "../types";
import { ResultDialog, readResultPopup, type ResultPopup } from "./ResultDialog";
import "./native-tool-panel.css";
import "./excel-split-panel.css";
import "./document-privacy-masker.css";
import { buildHwpLayout, type HwpLayout } from "./dpmHwpLayout";

/**
 * 문서 개인정보 마스킹 전용 화면.
 *
 * 1) 한글(hwpx)·PDF 를 넣으면 파일마다 개인정보로 보이는 곳을 찾아 목록으로 보여 준다(파일은 만들지 않음).
 * 2) 사람이 목록을 보며 항목마다 처리 방식을 고르고, 빠진 글자는 '직접 추가', PDF 는 영역을 직접 그린다.
 * 3) '확인했습니다'에 표시해야 가린 사본을 만든다. 원본은 고치지 않는다.
 *
 * 화면이 확인한 항목 목록(reviewed_ids)과 파일 표시(fingerprint)를 함께 보내, 확인한 뒤 파일이
 * 바뀌었거나 다시 찾은 목록이 다르면 파이썬 쪽이 사본을 만들지 않고 멈춘다.
 */

type Action = "mask_all" | "mask_part" | "keep";

type Item = {
  id: string;
  kind: string;
  label: string;
  text: string;
  confidence: number;
  reasons: string[];
  where: string;
  context: string;
  fixed: boolean;
  action: Action;
  previews: Partial<Record<Action, string>>;
  /** 처리 방식마다 바뀌는 글자 자리(text 안의 순번). 미리보기에서 원래 글자 위에 칠한다. */
  changes: Partial<Record<Action, number[]>>;
  page?: number;
  rects?: number[][];
  /** PDF: text 의 글자마다 사각형(줄바꿈 등은 null) */
  char_rects?: (number[] | null)[];
  /** 한글: text 의 글자마다 글 미리보기 안 자리 [블록, 행, 열, 글자] (문단은 행·열 -1) */
  spots?: (number[] | null)[];
  /** 한글: text 의 글자마다 [문서 순서 문단 번호, 문단 안 글자 번호] (쪽 미리보기에 맞출 때) */
  pspots?: (number[] | null)[];
};

type ViewCell = { text: string; rs: number; cs: number } | null;
type ViewBlock = { type: "p"; text: string } | { type: "table"; rows: ViewCell[][] };

type Analysis = {
  file: string;
  name: string;
  format: "hwpx" | "pdf";
  fingerprint: string;
  items: Item[];
  counts: Record<string, number>;
  warnings: string[];
  pages: { width: number; height: number }[];
  view: ViewBlock[];
  /** 한글 쪽 미리보기(rhwp)용: 그리는 hwpx 파일(base64)과 문서 순서 문단 글 */
  hwp_preview?: { data: string; paras: string[] } | null;
  actions: Record<Action, string>;
};

type FileState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; analysis: Analysis };

type Term = { text: string; kind: string };
type Box = { id: number; page: number; x0: number; y0: number; x1: number; y1: number };
type Picture = { image: string; width: number; height: number };

const TOOL_ID = "document_privacy_masker";
const EXTENSIONS = ["hwp", "hwpx", "pdf"];
const LOW_CONFIDENCE = 0.8;

const ACTION_LABELS: Record<Action, string> = {
  mask_all: "전부 가림",
  mask_part: "일부 가림",
  keep: "가리지 않음",
};
const ACTION_ORDER: Action[] = ["mask_part", "mask_all", "keep"];
// 체크한 항목에 한꺼번에 적용하는 방식
const BULK_ACTIONS: Action[] = ["mask_part", "mask_all", "keep"];

// '직접 추가'로 고를 수 있는 종류. 고른 종류의 가림 모양(일부 가림 등)을 쓴다.
const TERM_KINDS: { code: string; label: string }[] = [
  { code: "CUSTOM", label: "기타(전부 가림)" },
  { code: "PERSON", label: "성명" },
  { code: "ADDRESS", label: "주소" },
  { code: "PHONE", label: "일반전화" },
  { code: "EMAIL", label: "이메일" },
  { code: "BIRTH", label: "생년월일" },
  { code: "EMPLOYEE_ID", label: "사번" },
];

const fileName = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? path;
const errorText = (reason: unknown) => (reason instanceof Error ? reason.message : String(reason));
const actionsFor = (item: Item) => ACTION_ORDER.filter((action) => item.previews[action] !== undefined);

/** 처리 방식 이름 */
function actionName(_item: Item, action: Action) {
  return ACTION_LABELS[action];
}

/** 같은 줄에서 붙어 있는 글자 사각형을 하나로 합친다(PDF 미리보기). */
function mergeRuns(rects: number[][]): number[][] {
  const out: number[][] = [];
  for (const r of rects) {
    const last = out[out.length - 1];
    if (last && Math.abs(last[1] - r[1]) < 1.5 && Math.abs(last[3] - r[3]) < 1.5 && r[0] - last[2] < 1 && r[0] >= last[0] - 0.5) {
      last[2] = Math.max(last[2], r[2]);
      last[1] = Math.min(last[1], r[1]);
      last[3] = Math.max(last[3], r[3]);
    } else {
      out.push([...r]);
    }
  }
  return out;
}

type Mark = { item: Item; changed: boolean };

/**
 * 한글 글 미리보기. 원래 글을 그대로 보여 주고, 가려질 글자에 검은 형광펜을 칠한다.
 * 찾았지만 바뀌지 않는 글자(일부 가림에서 남는 글자, '가리지 않음')는 밑줄만 긋는다.
 * 형광펜은 화면에만 있고 사본에는 들어가지 않는다.
 */
function HwpxView({
  view,
  items,
  actionOf,
  selectedItem,
  onPick,
}: {
  view: ViewBlock[];
  items: Item[];
  actionOf: (item: Item) => Action;
  selectedItem: string;
  onPick: (item: Item) => void;
}) {
  const marks = useMemo(() => {
    const map = new Map<string, Mark>();
    for (const item of items) {
      const changed = new Set(item.changes[actionOf(item)] ?? []);
      (item.spots ?? []).forEach((spot, index) => {
        if (!spot) return;
        map.set(spot.join("|"), { item, changed: changed.has(index) });
      });
    }
    return map;
  }, [items, actionOf]);

  const render = (text: string, b: number, r: number, c: number) => {
    const out: JSX.Element[] = [];
    let run = "";
    let runMark: Mark | undefined;
    const flush = (key: number) => {
      if (!run) return;
      if (!runMark) {
        out.push(<span key={key}>{run}</span>);
      } else {
        const item = runMark.item;
        out.push(
          <span
            key={key}
            data-item={item.id}
            className={`dpm-ink ${runMark.changed ? "is-on" : "is-found"} ${selectedItem === item.id ? "is-selected" : ""}`}
            title={`${item.label}: ${item.text} (${actionName(item, actionOf(item))})`}
            onClick={() => onPick(item)}
          >
            {run}
          </span>,
        );
      }
      run = "";
    };
    for (let i = 0; i < text.length; i += 1) {
      const mark = marks.get(`${b}|${r}|${c}|${i}`);
      const same = mark === runMark || (mark && runMark && mark.item === runMark.item && mark.changed === runMark.changed);
      if (!same) {
        flush(i);
        runMark = mark;
      }
      run += text[i];
    }
    flush(text.length);
    return out;
  };

  if (!view.length) return <p className="dpm-muted">보여 줄 글이 없습니다.</p>;
  return (
    <div className="dpm-doc">
      {view.map((block, b) =>
        block.type === "p" ? (
          <p key={b}>{render(block.text, b, -1, -1)}</p>
        ) : (
          <table key={b}>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) =>
                    cell ? (
                      <td key={c} rowSpan={cell.rs > 1 ? cell.rs : undefined} colSpan={cell.cs > 1 ? cell.cs : undefined}>
                        {render(cell.text, b, r, c)}
                      </td>
                    ) : null,
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ),
      )}
    </div>
  );
}

export function DocumentPrivacyMaskerPanel({
  tool,
  onReset,
}: {
  tool: ToolManifest;
  onReset?: () => void;
}) {
  const [inputs, setInputs] = useState<string[]>([]);
  const [states, setStates] = useState<Record<string, FileState>>({});
  // 사람이 고친 처리 방식. 파일 → 항목 id → 방식. 고치지 않은 항목은 기본 방식.
  const [decisions, setDecisions] = useState<Record<string, Record<string, Action>>>({});
  const [terms, setTerms] = useState<Term[]>([]);
  const [termText, setTermText] = useState("");
  const [termKind, setTermKind] = useState("CUSTOM");
  const [boxes, setBoxes] = useState<Record<string, Box[]>>({});
  const [active, setActive] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedItem, setSelectedItem] = useState("");
  // 한꺼번에 처리 방식을 바꿀 항목(체크한 것). 파일을 바꾸면 비운다.
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState(false);

  const [pageNo, setPageNo] = useState<Record<string, number>>({});
  const [pictures, setPictures] = useState<Record<string, Picture>>({});
  const [pictureError, setPictureError] = useState("");
  const [drawMode, setDrawMode] = useState(false);
  const [drawing, setDrawing] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [done, setDone] = useState("");
  const [popup, setPopup] = useState<ResultPopup | null>(null);

  const queue = useRef<Promise<void>>(Promise.resolve());
  const generation = useRef<Record<string, number>>({});
  const nextBoxId = useRef(1);
  const logRef = useRef<HTMLPreElement>(null);
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});
  const docRef = useRef<HTMLDivElement>(null);
  const termsRef = useRef(terms);
  termsRef.current = terms;

  const say = (text: string) => setLog((items) => [...items, text]);

  useEffect(() => {
    let stop: UnlistenFn | undefined;
    void listen<{ toolId: string; text: string }>("tool-progress", (event) => {
      if (event.payload.toolId.split("__")[0] !== TOOL_ID) return;
      setLog((items) => [...items, event.payload.text]);
    })
      .then((unlisten) => {
        stop = unlisten;
      })
      .catch(() => undefined);
    return () => stop?.();
  }, []);

  useEffect(() => {
    const box = logRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [log]);

  /** 파일 하나를 (다시) 읽는다. 파이썬을 한 번에 여러 개 띄우지 않게 차례로 부른다. */
  const analyze = (path: string, withTerms: Term[]) => {
    const gen = (generation.current[path] ?? 0) + 1;
    generation.current[path] = gen;
    setStates((current) => ({ ...current, [path]: { status: "loading" } }));
    queue.current = queue.current.then(async () => {
      if (generation.current[path] !== gen) return;
      try {
        const raw = await runNativeTool(`${TOOL_ID}__analyze`, { path, extra_terms: withTerms });
        if (generation.current[path] !== gen) return;
        // 도구가 결과(JSON) 말고 다른 글을 함께 찍으면 앱은 그 글을 message 로만 넘긴다.
        // 모양을 확인하지 않으면 화면이 'undefined' 오류로 멈추므로 여기서 걸러 알린다.
        if (!Array.isArray((raw as { items?: unknown }).items)) {
          throw new Error(`도구 결과를 읽지 못했습니다. ${String(raw.message ?? "").slice(0, 300)}`);
        }
        const result = raw as unknown as Analysis;
        setStates((current) => (path in current ? { ...current, [path]: { status: "ready", analysis: result } } : current));
        // 다시 읽어도 같은 항목은 id 가 같다. 사라진 항목의 결정만 버린다.
        const alive = new Set(result.items.map((item) => item.id));
        setDecisions((current) => {
          const mine = current[path] ?? {};
          const kept = Object.fromEntries(Object.entries(mine).filter(([id]) => alive.has(id)));
          return { ...current, [path]: kept };
        });
      } catch (reason) {
        if (generation.current[path] !== gen) return;
        setStates((current) => (path in current ? { ...current, [path]: { status: "error", message: errorText(reason) } } : current));
      }
    });
  };

  // 확인한 뒤 무엇이든 바뀌면 확인 표시를 다시 받는다.
  const reviewKey = useMemo(
    () =>
      JSON.stringify([
        inputs,
        Object.entries(states).map(([path, state]) => [path, state.status, state.status === "ready" ? state.analysis.fingerprint : ""]),
        terms,
      ]),
    [inputs, states, terms],
  );
  useEffect(() => setConfirmed(false), [reviewKey]);

  const takeInputs = (paths: string[]) => {
    const usable = filterByExtension(paths, EXTENSIONS).filter((path) => !inputs.includes(path));
    if (!usable.length) {
      say("한글(hwp·hwpx)·PDF 파일만 넣을 수 있습니다.");
      return;
    }
    setInputs((current) => [...current, ...usable]);
    for (const path of usable) analyze(path, terms);
    if (!active) setActive(usable[0]);
  };

  const pickFiles = async () => {
    const chosen = await openDialog({
      multiple: true,
      title: "개인정보를 가릴 문서 선택",
      filters: [{ name: "한글·PDF 문서", extensions: EXTENSIONS }],
    });
    if (!chosen) return;
    takeInputs(Array.isArray(chosen) ? chosen : [chosen]);
  };

  const dropping = useFileDrop(takeInputs, !running);

  const forget = <T,>(record: Record<string, T>, path: string) => {
    const next = { ...record };
    delete next[path];
    return next;
  };

  const removeInput = (path: string) => {
    generation.current[path] = (generation.current[path] ?? 0) + 1;
    const rest = inputs.filter((item) => item !== path);
    setInputs(rest);
    setStates((current) => forget(current, path));
    setDecisions((current) => forget(current, path));
    setBoxes((current) => forget(current, path));
    if (active === path) setActive(rest[0] ?? "");
  };

  const clearInputs = () => {
    for (const path of inputs) generation.current[path] = (generation.current[path] ?? 0) + 1;
    setInputs([]);
    setStates({});
    setDecisions({});
    setBoxes({});
    setActive("");
  };

  const addTerm = () => {
    const text = termText.trim();
    if (text.length < 2) {
      say("직접 추가할 글자는 두 글자 이상 적어 주세요.");
      return;
    }
    if (terms.some((term) => term.text === text)) return;
    const next = [...terms, { text, kind: termKind }];
    setTerms(next);
    setTermText("");
    for (const path of inputs) analyze(path, next);
  };

  const removeTerm = (text: string) => {
    const next = terms.filter((term) => term.text !== text);
    setTerms(next);
    for (const path of inputs) analyze(path, next);
  };

  const state = active ? states[active] : undefined;
  const analysis = state?.status === "ready" ? state.analysis : null;
  const rawItems = analysis?.items;

  // 한글 쪽 미리보기(rhwp). 고른 파일 것만 만든다. 실패하면 글 미리보기로 보여 준다.
  const [hwpLayouts, setHwpLayouts] = useState<Record<string, { key: string; layout?: HwpLayout; error?: string }>>({});
  const hwpKey = analysis?.hwp_preview ? `${analysis.fingerprint}\u0000${(rawItems ?? []).map((it) => it.id).join(",")}` : "";
  const hwpEntry = active ? hwpLayouts[active] : undefined;
  const hwpLayout = hwpEntry && hwpEntry.key === hwpKey ? hwpEntry.layout : undefined;
  const hwpFailed = !!hwpEntry && hwpEntry.key === hwpKey && !!hwpEntry.error;
  useEffect(() => {
    if (!active || !analysis?.hwp_preview || !hwpKey) return;
    if (hwpLayouts[active]?.key === hwpKey) return;
    let stale = false;
    const path = active;
    const key = hwpKey;
    setHwpLayouts((current) => {
      // 같은 파일을 다시 읽어 바뀐 경우: 앞 그림은 더 쓰지 않으므로 닫는다(메모리).
      current[path]?.layout?.close();
      return { ...current, [path]: { key } };
    });
    buildHwpLayout(analysis.hwp_preview.data, analysis.hwp_preview.paras, analysis.items)
      .then((layout) => {
        if (stale) {
          layout.close();
          return;
        }
        setHwpLayouts((current) => {
          current[path]?.layout?.close();
          return { ...current, [path]: { key, layout } };
        });
      })
      .catch((reason) => {
        if (!stale) setHwpLayouts((current) => ({ ...current, [path]: { key, error: errorText(reason) } }));
      });
    return () => {
      stale = true;
      // 그리는 도중에 다른 파일로 옮기면 '그리는 중' 표시를 지운다. 남겨 두면 돌아왔을 때 다시 그리지 않고 멈춘다.
      setHwpLayouts((current) => {
        const entry = current[path];
        if (!entry || entry.key !== key || entry.layout || entry.error) return current;
        const next = { ...current };
        delete next[path];
        return next;
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, hwpKey]);

  // 목록에서 뺀 파일의 한글 쪽 그림은 닫는다. 도구 화면을 닫을 때도 모두 닫는다.
  useEffect(() => {
    setHwpLayouts((current) => {
      const gone = Object.keys(current).filter((path) => !inputs.includes(path));
      if (!gone.length) return current;
      const next = { ...current };
      for (const path of gone) {
        next[path]?.layout?.close();
        delete next[path];
      }
      return next;
    });
  }, [inputs]);
  const hwpLayoutsRef = useRef(hwpLayouts);
  hwpLayoutsRef.current = hwpLayouts;
  useEffect(
    () => () => {
      for (const entry of Object.values(hwpLayoutsRef.current)) entry.layout?.close();
    },
    [],
  );

  // 한글 쪽 미리보기가 있으면 항목마다 쪽 번호와 글자 사각형을 붙여 PDF 와 같은 방식으로 보여 준다.
  const items = useMemo(() => {
    const list = rawItems ?? [];
    if (!hwpLayout) return list;
    return list.map((it) => {
      const g = hwpLayout.geom.get(it.id);
      if (!g || !g.page) return it;
      const charRects = g.boxes.map((b) => (b && b.page + 1 === g.page ? b.box : null));
      return { ...it, page: g.page, char_rects: charRects, rects: mergeRuns(charRects.filter((r): r is number[] => !!r)) };
    });
  }, [rawItems, hwpLayout]);
  const myDecisions = useMemo(() => (active && decisions[active]) || {}, [active, decisions]);
  const actionOf = useCallback(
    (item: Item): Action => {
      return myDecisions[item.id] ?? item.action;
    },
    [myDecisions],
  );

  const setAction = (targets: Item[], action: Action) => {
    if (!active) return;
    setDecisions((current) => {
      const mine = { ...(current[active] ?? {}) };
      for (const item of targets) {
        if (!actionsFor(item).includes(action)) continue;
        if (action === item.action) delete mine[item.id];
        else mine[item.id] = action;
      }
      return { ...current, [active]: mine };
    });
  };

  const kindsHere = useMemo(() => {
    const map = new Map<string, { label: string; items: Item[] }>();
    for (const item of items) {
      const entry = map.get(item.kind) ?? { label: item.label, items: [] };
      entry.items.push(item);
      map.set(item.kind, entry);
    }
    return [...map.entries()];
  }, [items]);

  const lowCount = items.filter((item) => item.confidence < LOW_CONFIDENCE).length;
  const shown = items.filter((item) =>
    filter === "all" ? true : filter === "check" ? item.confidence < LOW_CONFIDENCE : item.kind === filter,
  );
  useEffect(() => {
    if (filter !== "all" && filter !== "check" && !kindsHere.some(([kind]) => kind === filter)) setFilter("all");
  }, [filter, kindsHere]);

  // 파일을 바꾸거나 다시 읽어 사라진 항목은 체크에서 뺀다.
  useEffect(() => {
    const alive = new Set(items.map((item) => item.id));
    setChecked((current) => {
      const next = new Set([...current].filter((id) => alive.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [items]);
  useEffect(() => {
    setChecked(new Set());
    setDrawMode(false);
  }, [active]);

  const checkedShown = shown.filter((item) => checked.has(item.id));
  const allShownChecked = !!shown.length && checkedShown.length === shown.length;
  const toggleChecked = (ids: string[], on: boolean) =>
    setChecked((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });

  // ── PDF 미리보기 ──────────────────────────────────────────────
  const isPdf = analysis?.format === "pdf";
  // 쪽으로 보여 주는지: PDF, 또는 한글 쪽 미리보기가 준비된 한글
  const paged = isPdf || !!hwpLayout;
  const hwpPending = !isPdf && !!analysis?.hwp_preview && !hwpLayout && !hwpFailed;
  const pageCount = isPdf ? analysis?.pages.length ?? 0 : hwpLayout?.pageCount ?? 0;
  const page = Math.min(Math.max(1, (active && pageNo[active]) || 1), Math.max(1, pageCount));
  const pictureKey = `${active}\u0000${analysis?.fingerprint ?? ""}\u0000${page}`;
  const hwpPicture = useMemo(
    () => (hwpLayout ? { image: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(hwpLayout.svg(page))}`, width: 0, height: 0 } : undefined),
    [hwpLayout, page],
  );
  const picture = isPdf ? pictures[pictureKey] : hwpPicture;
  const pageSize = isPdf ? analysis?.pages[page - 1] : hwpLayout?.pages[page - 1];
  const myBoxes = (active && boxes[active]) || [];

  useEffect(() => {
    if (!isPdf || !active || picture) return;
    let stale = false;
    setPictureError("");
    runNativeTool(`${TOOL_ID}__page`, { path: active, page, width: 1000 })
      .then((result) => {
        if (stale) return;
        const pic = result as unknown as Picture;
        if (typeof pic.image !== "string") throw new Error(`미리보기를 읽지 못했습니다. ${String(result.message ?? "").slice(0, 300)}`);
        setPictures((current) => ({ ...current, [pictureKey]: pic }));
      })
      .catch((reason) => {
        if (!stale) setPictureError(errorText(reason));
      });
    return () => {
      stale = true;
    };
  }, [isPdf, active, page, picture, pictureKey]);

  const goPage = (next: number) => {
    if (!active) return;
    setPageNo((current) => ({ ...current, [active]: Math.min(Math.max(1, next), Math.max(1, pageCount)) }));
  };

  const selectItem = (item: Item, fromPicture = false) => {
    setSelectedItem(item.id);
    if (item.page && item.page !== page) goPage(item.page);
    if (!fromPicture && !paged) {
      // 한글 글 미리보기에서 그 자리로 옮긴다.
      window.setTimeout(
        () => docRef.current?.querySelector(`[data-item="${item.id}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }),
        30,
      );
    }
    if (fromPicture) {
      if (filter !== "all" && !shown.includes(item)) setFilter("all");
      window.setTimeout(() => rowRefs.current[item.id]?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 30);
    }
  };

  const pointFrom = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const w = pageSize?.width ?? 1;
    const h = pageSize?.height ?? 1;
    const x = Math.min(Math.max(0, event.clientX - rect.left), rect.width);
    const y = Math.min(Math.max(0, event.clientY - rect.top), rect.height);
    return { x: (x / rect.width) * w, y: (y / rect.height) * h };
  };

  const startDraw = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drawMode || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const p = pointFrom(event);
    setDrawing({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  const moveDraw = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drawing) return;
    const p = pointFrom(event);
    setDrawing({ ...drawing, x1: p.x, y1: p.y });
  };
  const endDraw = () => {
    if (!drawing || !active) return;
    const box = {
      id: nextBoxId.current++,
      page,
      x0: Math.min(drawing.x0, drawing.x1),
      y0: Math.min(drawing.y0, drawing.y1),
      x1: Math.max(drawing.x0, drawing.x1),
      y1: Math.max(drawing.y0, drawing.y1),
    };
    setDrawing(null);
    if (box.x1 - box.x0 < 3 || box.y1 - box.y0 < 3) return;
    setBoxes((current) => ({ ...current, [active]: [...(current[active] ?? []), box] }));
  };
  const removeBox = (id: number) => {
    if (!active) return;
    setBoxes((current) => ({ ...current, [active]: (current[active] ?? []).filter((box) => box.id !== id) }));
  };

  const pct = (value: number, total: number | undefined) => `${(value / Math.max(total ?? 1, 1)) * 100}%`;
  const boxStyle = (x0: number, y0: number, x1: number, y1: number) => ({
    left: pct(x0, pageSize?.width),
    top: pct(y0, pageSize?.height),
    width: pct(x1 - x0, pageSize?.width),
    height: pct(y1 - y0, pageSize?.height),
  });

  // ── 실행 ─────────────────────────────────────────────────────
  const readyFiles = inputs.filter((path) => states[path]?.status === "ready");
  const loadingCount = inputs.filter((path) => states[path]?.status === "loading").length;
  const errorFiles = inputs.filter((path) => states[path]?.status === "error");
  const totalItems = readyFiles.reduce(
    (sum, path) => sum + ((states[path] as { analysis: Analysis }).analysis.items.length ?? 0),
    0,
  );
  const totalBoxes = readyFiles.reduce((sum, path) => sum + (boxes[path]?.length ?? 0), 0);
  const canRun = !running && !loadingCount && readyFiles.length > 0 && confirmed;

  const pickOutput = async () => {
    const chosen = await openDialog({ directory: true, multiple: false, title: "저장 폴더 선택" });
    if (typeof chosen === "string") setOutput(chosen);
  };

  const run = async () => {
    setRunning(true);
    say(`${tool.name}: ${readyFiles.length}개 파일의 가린 사본을 만듭니다.`);
    if (errorFiles.length) say(`읽지 못한 파일 ${errorFiles.length}개는 빼고 만듭니다.`);
    try {
      const files = readyFiles.map((path) => {
        const info = (states[path] as { analysis: Analysis }).analysis;
        const mine = decisions[path] ?? {};
        return {
          path,
          fingerprint: info.fingerprint,
          reviewed_ids: info.items.map((item) => item.id),
          decisions: Object.fromEntries(
            info.items.map((item) => {
              return [item.id, mine[item.id] ?? item.action];
            }),
          ),
          extra_terms: terms,
          manual_boxes: info.format === "pdf" ? (boxes[path] ?? []).map(({ page: p, x0, y0, x1, y1 }) => ({ page: p, x0, y0, x1, y1 })) : [],
        };
      });
      const result = await runNativeTool(TOOL_ID, { confirmed: true, output, files });
      const saved = typeof result.output === "string" ? result.output : "";
      setDone(saved);
      const made = Array.isArray(result.results) ? (result.results as { output: string }[]) : [];
      setLog((current) => [...current, String(result.message ?? ""), ...made.map((item) => `저장: ${item.output}`)].filter(Boolean));
      setPopup(
        readResultPopup((result as { popup?: unknown }).popup) ?? {
          level: "success",
          title: "작업을 마쳤습니다",
          message: String(result.message ?? ""),
        },
      );
    } catch (reason) {
      const message = errorText(reason);
      say(`실패: ${message}`);
      setPopup({ level: "error", title: "가린 사본을 만들지 못했습니다", message });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="native-tool content-column dpm-panel">
      <div className="native-hero">
        <div className="tool-icon type-internal_python">
          <EyeOff size={23} />
        </div>
        <div>
          <span className="eyebrow">{tool.top_tab}</span>
          <h2>{tool.name}</h2>
          <p>{tool.description || "한글(hwpx)·PDF 문서에서 개인정보를 찾아 확인한 뒤 가린 사본을 만듭니다."}</p>
        </div>
      </div>

      <section className="task-card split-card" data-tour="mask-files">
        <div className="task-heading">
          <div>
            <span className="step-badge">1</span>
            <strong>가릴 문서</strong>
          </div>
          <span className="privacy-note">
            <ShieldCheck size={15} />
            파일은 PC 밖으로 전송되지 않습니다.
          </span>
        </div>
        <button className={`drop-zone ${dropping ? "is-dropping" : ""}`} onClick={() => void pickFiles()}>
          <FolderOpen size={30} />
          <strong>한글(hwp·hwpx)·PDF 문서를 선택하세요</strong>
          <span>
            {dropping
              ? "여기에 놓으면 목록에 넣습니다."
              : "옛 한글(hwp)은 한글로 hwpx 로 바꿔 읽고 사본도 hwpx 로 저장합니다(한글이 설치된 PC). 스캔한 PDF(글자가 그림인 문서)는 처리하지 않습니다."}
          </span>
        </button>
        {!!inputs.length && (
          <div className="picked-files">
            <div className="picked-files-head">
              <span>
                <b>{inputs.length}개</b>를 넣었습니다.
                {loadingCount > 0 && (
                  <span className="dpm-busy">
                    <LoaderCircle className="spin" size={13} />
                    {loadingCount}개 읽는 중
                  </span>
                )}
              </span>
              <button className="link-button" onClick={clearInputs} disabled={running}>
                <Trash2 size={14} />
                모두 지우기
              </button>
            </div>
            <ul className="dpm-files">
              {inputs.map((path) => {
                const fileState = states[path];
                const count = fileState?.status === "ready" ? fileState.analysis.items.length : null;
                return (
                  <li key={path} className={`${active === path ? "is-active" : ""} ${fileState?.status === "error" ? "is-error" : ""}`}>
                    <button className="dpm-file-pick" title={path} onClick={() => setActive(path)}>
                      <span>{fileName(path)}</span>
                      <small>
                        {fileState?.status === "loading" && "읽는 중"}
                        {fileState?.status === "error" && "읽지 못함"}
                        {count !== null && `${count}곳`}
                      </small>
                    </button>
                    <button title="목록에서 빼기" onClick={() => removeInput(path)} disabled={running}>
                      <X size={16} />
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>

      {!!inputs.length && (
        <section className="task-card split-card">
          <div className="task-heading">
            <div>
              <span className="step-badge">2</span>
              <strong>찾은 개인정보 확인</strong>
            </div>
            {analysis && (
              <span className="dpm-muted">
                {analysis.name} · {items.length}곳
              </span>
            )}
          </div>

          {state?.status === "loading" && (
            <p className="dpm-muted">
              <LoaderCircle className="spin" size={14} /> 문서를 읽는 중입니다.
            </p>
          )}
          {state?.status === "error" && (
            <div className="dpm-error">
              <TriangleAlert size={15} />
              <span>{state.message}</span>
              <button className="link-button" onClick={() => analyze(active, terms)}>
                <RefreshCw size={13} />
                다시 읽기
              </button>
            </div>
          )}

          {analysis && (
            <>
              {!!analysis.warnings.length && (
                <ul className="dpm-notes">
                  {analysis.warnings.map((text) => (
                    <li key={text}>
                      <TriangleAlert size={14} />
                      {text}
                    </li>
                  ))}
                </ul>
              )}

              <div className="dpm-kinds">
                <button className={`dpm-chip ${filter === "all" ? "is-on" : ""}`} onClick={() => setFilter("all")}>
                  전체 <small>{items.length}</small>
                </button>
                {lowCount > 0 && (
                  <button className={`dpm-chip is-check ${filter === "check" ? "is-on" : ""}`} onClick={() => setFilter("check")}>
                    확인 필요 <small>{lowCount}</small>
                  </button>
                )}
                {kindsHere.map(([kind, entry]) => (
                  <button key={kind} className={`dpm-chip ${filter === kind ? "is-on" : ""}`} onClick={() => setFilter(kind)}>
                    {entry.label} <small>{entry.items.length}</small>
                  </button>
                ))}
              </div>

              <p className="dpm-help">
                {isPdf
                  ? "미리보기의 반투명 검은 칸 아래 글자가 지워질 글자입니다. 사본에서는 그 자리가 검은 칸이 되고 복사해도 나오지 않습니다."
                  : paged || hwpPending
                    ? "미리보기의 반투명 검은 칸 아래 글자가 가려질 글자입니다. 사본에서는 * 로 바뀌고, 검은 칸은 사본에 들어가지 않습니다."
                    : "미리보기에서 검은 형광펜을 칠한 글자가 가려질 글자입니다. 사본에서는 * 로 바뀌고, 형광펜은 사본에 들어가지 않습니다."}
              </p>

              <div className="dpm-review has-preview">
                <div className="dpm-list-col">
                <div className="dpm-list-inner">
                <div className="dpm-list-bar">
                  <label className="dpm-check-all">
                    <input
                      type="checkbox"
                      checked={allShownChecked}
                      disabled={!shown.length}
                      ref={(node) => {
                        if (node) node.indeterminate = !allShownChecked && checkedShown.length > 0;
                      }}
                      onChange={(event) => toggleChecked(shown.map((item) => item.id), event.target.checked)}
                    />
                    전체 선택
                  </label>
                  <span className="dpm-check-count">
                    선택 <b>{checkedShown.length}</b>곳
                  </span>
                  {BULK_ACTIONS.map((action) => (
                    <button
                      key={action}
                      className="secondary-button"
                      disabled={!checkedShown.length}
                      onClick={() => setAction(checkedShown, action)}
                    >
                      {ACTION_LABELS[action]}
                    </button>
                  ))}
                </div>
                <div className="dpm-table-wrap">
                  {items.length ? (
                    <table className="dpm-table">
                      <thead>
                        <tr>
                          <th className="dpm-col-check" />
                          {paged && <th className="dpm-col-page">쪽</th>}
                          <th className="dpm-col-kind">종류</th>
                          <th>찾은 내용 → 바뀐 모양</th>
                          <th className="dpm-col-action">처리</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shown.map((item) => {
                          const action = actionOf(item);
                          const changed = action !== item.action;
                          return (
                            <tr
                              key={item.id}
                              ref={(node) => {
                                rowRefs.current[item.id] = node;
                              }}
                              className={`${selectedItem === item.id ? "is-selected" : ""} ${action === "keep" ? "is-keep" : ""}`}
                              onClick={() => selectItem(item)}
                            >
                              <td className="dpm-check" onClick={(event) => event.stopPropagation()}>
                                <input
                                  type="checkbox"
                                  checked={checked.has(item.id)}
                                  onChange={(event) => toggleChecked([item.id], event.target.checked)}
                                  aria-label={`${item.text} 선택`}
                                />
                              </td>
                              {paged && <td className="dpm-page-no">{item.page ?? "-"}</td>}
                              <td className="dpm-kind">
                                <span className="dpm-kind-badge">
                                  {item.label}
                                </span>
                                {item.confidence < LOW_CONFIDENCE && <span className="dpm-check-badge">확인 필요</span>}
                              </td>
                              <td className="dpm-value">
                                <span className="dpm-original">{item.text}</span>
                                <span className="dpm-arrow">→</span>
                                <span className="dpm-result">{item.previews[action] ?? item.text}</span>
                              </td>
                              <td className="dpm-action">
                                <select
                                  value={action}
                                  className={changed ? "is-changed" : ""}
                                  onClick={(event) => event.stopPropagation()}
                                  onFocus={() => selectItem(item)}
                                  onChange={(event) => {
                                    setAction([item], event.target.value as Action);
                                    selectItem(item);
                                  }}
                                  aria-label={`${item.text} 처리 방식`}
                                >
                                  {actionsFor(item).map((option) => (
                                    <option key={option} value={option}>
                                      {actionName(item, option)}
                                    </option>
                                  ))}
                                </select>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  ) : (
                    <p className="dpm-empty">
                      찾은 개인정보가 없습니다. 빠진 것이 있으면 아래 '직접 추가'로 넣거나{isPdf ? ", 미리보기에 영역을 그리세요" : ""}.
                    </p>
                  )}
                </div>
                </div>
                </div>

                {(paged || hwpPending) && (
                  <div className="dpm-preview">
                    <div className="dpm-preview-bar">
                      <button className="icon-button" onClick={() => goPage(page - 1)} disabled={page <= 1} title="앞 쪽">
                        <ChevronLeft size={16} />
                      </button>
                      <span>
                        {page} / {pageCount}쪽
                      </span>
                      <button className="icon-button" onClick={() => goPage(page + 1)} disabled={page >= pageCount} title="다음 쪽">
                        <ChevronRight size={16} />
                      </button>
                      {isPdf && (
                        <button
                          className={`secondary-button dpm-draw ${drawMode ? "is-on" : ""}`}
                          onClick={() => setDrawMode((on) => !on)}
                          title="목록에 없는 곳(도장·사진·그림 속 글자 등)을 끌어서 직접 가립니다"
                        >
                          <SquareDashedMousePointer size={15} />
                          {drawMode ? "그리기 끝" : "영역 직접 가리기"}
                        </button>
                      )}
                    </div>
                    <div className="dpm-page">
                      {picture ? (
                        <div
                          className={`dpm-page-inner ${drawMode ? "is-drawing" : ""}`}
                          style={{ aspectRatio: `${pageSize?.width ?? 1} / ${pageSize?.height ?? 1}` }}
                          onPointerDown={startDraw}
                          onPointerMove={moveDraw}
                          onPointerUp={endDraw}
                          onPointerCancel={() => setDrawing(null)}
                        >
                          <img src={picture.image} alt={`${page}쪽`} draggable={false} />
                          {items
                            .filter((item) => item.page === page)
                            .flatMap((item) => {
                              const action = actionOf(item);
                              const changed = item.changes[action] ?? [];
                              // 그대로 두는 항목은 찾은 자리 전체에 점선, 가리는 항목은 바뀌는 글자만 반투명 검은 칸
                              const boxes =
                                action === "keep" || !changed.length
                                  ? item.rects ?? []
                                  : mergeRuns(changed.map((index) => item.char_rects?.[index]).filter((r): r is number[] => !!r));
                              const kind = action === "keep" || !changed.length ? "is-keep" : "is-ink";
                              return boxes.map((r, index) => (
                                <button
                                  key={`${item.id}-${index}`}
                                  className={`dpm-mark ${kind} ${selectedItem === item.id ? "is-selected" : ""}`}
                                  style={boxStyle(r[0], r[1], r[2], r[3])}
                                  title={`${item.label}: ${item.text} → ${item.previews[action] ?? item.text} (${actionName(item, action)})`}
                                  onPointerDown={(event) => {
                                    if (!drawMode) event.stopPropagation();
                                  }}
                                  onClick={() => !drawMode && selectItem(item, true)}
                                />
                              ));
                            })}
                          {myBoxes
                            .filter((box) => box.page === page)
                            .map((box) => (
                              <div key={box.id} className="dpm-box" style={boxStyle(box.x0, box.y0, box.x1, box.y1)}>
                                <button
                                  title="이 영역 빼기"
                                  onPointerDown={(event) => event.stopPropagation()}
                                  onClick={() => removeBox(box.id)}
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            ))}
                          {drawing && (
                            <div
                              className="dpm-box is-drawing"
                              style={boxStyle(
                                Math.min(drawing.x0, drawing.x1),
                                Math.min(drawing.y0, drawing.y1),
                                Math.max(drawing.x0, drawing.x1),
                                Math.max(drawing.y0, drawing.y1),
                              )}
                            />
                          )}
                        </div>
                      ) : pictureError ? (
                        <p className="dpm-error">
                          <TriangleAlert size={14} /> 미리보기를 그리지 못했습니다: {pictureError}
                        </p>
                      ) : (
                        <p className="dpm-muted">
                          <LoaderCircle className="spin" size={14} /> 미리보기를 그리는 중
                        </p>
                      )}
                    </div>
                    <p className="dpm-legend">
                      <span className="is-mask" /> 지워질 글자
                      <span className="is-keep" /> 찾았지만 가리지 않을 곳
                      {isPdf && (
                        <>
                          <span className="is-box" /> 직접 그린 영역{myBoxes.length ? ` ${myBoxes.length}개` : ""}
                        </>
                      )}
                    </p>
                  </div>
                )}

                {!paged && !hwpPending && analysis && (
                  <div className="dpm-preview">
                    <div className="dpm-preview-bar">
                      <span>글 미리보기 · 원래 글 위에 가려질 곳을 표시합니다(글자 모양·배치는 실제와 다를 수 있음)</span>
                    </div>
                    <div className="dpm-page dpm-doc-wrap" ref={docRef}>
                      <HwpxView
                        view={analysis.view ?? []}
                        items={items}
                        actionOf={actionOf}
                        selectedItem={selectedItem}
                        onPick={(item) => selectItem(item, true)}
                      />
                    </div>
                    <p className="dpm-legend">
                      <span className="is-mask" /> 가려질 글자
                      <span className="is-found" /> 찾았지만 가리지 않는 글자
                    </p>
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      )}

      {!!inputs.length && (
        <section className="task-card split-card">
          <div className="task-heading">
            <div>
              <span className="step-badge">3</span>
              <strong>빠진 글자 직접 추가</strong>
            </div>
          </div>
          <p className="dpm-help">
            목록에 없는 이름·번호를 적으면 <b>넣은 모든 파일</b>에서 같은 글자를 찾아 목록에 넣습니다.
          </p>
          <div className="dpm-term-row">
            <input
              value={termText}
              placeholder="예: 홍길동, 교무행정지원사 A"
              onChange={(event) => setTermText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") addTerm();
              }}
            />
            <select value={termKind} onChange={(event) => setTermKind(event.target.value)} aria-label="추가할 글자의 종류">
              {TERM_KINDS.map((kind) => (
                <option key={kind.code} value={kind.code}>
                  {kind.label}
                </option>
              ))}
            </select>
            <button className="secondary-button" onClick={addTerm} disabled={running || !termText.trim()}>
              <Plus size={15} />
              추가
            </button>
          </div>
          {!!terms.length && (
            <div className="dpm-terms">
              {terms.map((term) => (
                <span key={term.text} className="dpm-term">
                  {term.text}
                  <small>{TERM_KINDS.find((kind) => kind.code === term.kind)?.label ?? term.kind}</small>
                  <button title="빼기" onClick={() => removeTerm(term.text)} disabled={running}>
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="task-card split-card" data-tour="mask-output">
        <label className="split-output">
          <span>저장 폴더</span>
          <div className="split-row">
            <input value={output} readOnly placeholder="비우면 원본과 같은 폴더에 '원본이름_마스킹'으로 저장합니다" />
            <button className="secondary-button" onClick={() => void pickOutput()}>
              <FolderOpen size={15} />
              찾아보기
            </button>
          </div>
        </label>
        {!!readyFiles.length && (
          <label className={`dpm-confirm ${confirmed ? "is-on" : ""}`}>
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={!!loadingCount} />
            <span>
              파일 {readyFiles.length}개의 찾은 곳 {totalItems}곳{totalBoxes ? `과 직접 그린 영역 ${totalBoxes}개` : ""}의 처리 방식을 확인했습니다.
              그림·도장·사진처럼 도구가 찾지 못하는 곳도 직접 확인했습니다.
            </span>
          </label>
        )}
        {!!errorFiles.length && (
          <p className="dpm-error">
            <TriangleAlert size={14} /> 읽지 못한 파일 {errorFiles.length}개는 사본을 만들지 않습니다.
          </p>
        )}
      </section>

      <div className="run-row" data-tour="mask-run">
        {onReset && (
          <button className="secondary-button" onClick={onReset} disabled={running} title="넣은 파일과 설정을 모두 지우고 처음 상태로 돌아갑니다.">
            <RotateCcw size={15} />
            초기화
          </button>
        )}
        <button className="primary-button" onClick={() => void run()} disabled={!canRun} title={confirmed ? "" : "찾은 곳을 확인한 뒤 확인 칸에 표시하세요."}>
          {running ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
          {running ? "만드는 중" : "가린 사본 만들기"}
        </button>
      </div>

      <section className="log-panel" data-tour="mask-log">
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
          onClose={() => setPopup(null)}
          onReveal={done ? () => void revealPath(done).catch(() => undefined) : undefined}
        />
      )}
    </div>
  );
}
