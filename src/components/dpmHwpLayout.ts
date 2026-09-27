/**
 * 문서 개인정보 마스킹 — 한글(hwp·hwpx) 쪽 미리보기.
 *
 * rhwp(@rhwp/core, MIT, https://github.com/edwardkim/rhwp)로 한글 문서를 화면 안에서 쪽 그림(SVG)으로
 * 그린다. 파이썬 실행기를 따로 켜지 않아 쪽 넘김이 바로 된다. (Docufinder 가 한글 미리보기에 쓰는 부품)
 *
 * 가릴 곳 표시: 파이썬이 찾은 글자는 'hwpx 문단 순번 · 문단 안 글자 순번'(pspots)으로 오고, rhwp 는
 * 쪽마다 글자 위치(getPageTextLayout)를 준다. 두 쪽 문단을 문서 순서대로 글자가 같은 것끼리 짝지은 뒤,
 * 빈칸을 뺀 글자끼리 차례로 맞춰 쪽 번호와 글자 사각형을 얻는다. 맞출 수 없는 항목은 쪽 없이 둔다.
 */
import init, { HwpDocument } from "@rhwp/core";
import wasmUrl from "@rhwp/core/rhwp_bg.wasm?url";

type Run = {
  text: string;
  x: number;
  y: number;
  h: number;
  charX: number[];
  secIdx: number;
  paraIdx: number;
  charStart: number;
  parentParaIdx?: number;
  cellPath?: { controlIndex: number; cellIndex: number; cellParaIndex: number }[];
};

type CharBox = { page: number; box: number[] };

export type HwpItemGeom = { page: number | null; boxes: (CharBox | null)[] };

export type HwpLayout = {
  pageCount: number;
  pages: { width: number; height: number }[];
  svg: (page: number) => string;
  geom: Map<string, HwpItemGeom>;
  mapped: number;
  close: () => void;
};

let ready: Promise<void> | null = null;

function ensureReady() {
  if (!ready) {
    const g = globalThis as unknown as { measureTextWidth?: (font: string, text: string) => number };
    if (!g.measureTextWidth) {
      let ctx: CanvasRenderingContext2D | null = null;
      let last = "";
      g.measureTextWidth = (font: string, text: string) => {
        if (!ctx) ctx = document.createElement("canvas").getContext("2d");
        if (!ctx) return text.length * 10;
        if (font !== last) {
          ctx.font = font;
          last = font;
        }
        return ctx.measureText(text).width;
      };
    }
    ready = init({ module_or_path: wasmUrl }).then(() => undefined);
    ready.catch(() => {
      ready = null;
    });
  }
  return ready;
}

const fromBase64 = (data: string) => {
  const bin = atob(data);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes;
};

const squeeze = (text: string) => text.replace(/\s+/g, "");

export async function buildHwpLayout(
  data: string,
  paras: string[],
  items: { id: string; pspots?: (number[] | null)[] }[],
): Promise<HwpLayout> {
  await ensureReady();
  const doc = new HwpDocument(fromBase64(data));
  const pageCount = doc.pageCount();
  const pages: { width: number; height: number }[] = [];

  // rhwp 문단: 열쇠 → 글자 순번 → {글자, 쪽, 사각형}
  const rParas = new Map<string, { order: number[]; chars: Map<number, { ch: string } & CharBox> }>();
  for (let p = 0; p < pageCount; p += 1) {
    const info = JSON.parse(doc.getPageInfo(p)) as { width: number; height: number };
    pages.push({ width: info.width, height: info.height });
    let runs: Run[] = [];
    try {
      runs = (JSON.parse(doc.getPageTextLayout(p)) as { runs: Run[] }).runs ?? [];
    } catch {
      runs = [];
    }
    for (const run of runs) {
      const path = run.cellPath ?? [];
      const key = path.length
        ? `${run.secIdx}|${run.parentParaIdx ?? run.paraIdx}|${path.map((c) => `${c.controlIndex}.${c.cellIndex}.${c.cellParaIndex}`).join("/")}`
        : `${run.secIdx}|${run.paraIdx}`;
      const order = path.length
        ? [run.secIdx, run.parentParaIdx ?? run.paraIdx, 1, ...path.flatMap((c) => [c.controlIndex, c.cellIndex, c.cellParaIndex])]
        : [run.secIdx, run.paraIdx, 0];
      let entry = rParas.get(key);
      if (!entry) {
        entry = { order, chars: new Map() };
        rParas.set(key, entry);
      }
      for (let k = 0; k < run.text.length; k += 1) {
        const x0 = run.x + (run.charX[k] ?? 0);
        const x1 = run.x + (run.charX[k + 1] ?? run.charX[k] ?? 0);
        entry.chars.set(run.charStart + k, { ch: run.text[k], page: p, box: [x0, run.y, x1, run.y + run.h] });
      }
    }
  }

  // 문서 순서로 정렬한 rhwp 문단: 빈칸 뺀 글자 목록
  const cmp = (a: number[], b: number[]) => {
    for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
      const d = (a[i] ?? -1) - (b[i] ?? -1);
      if (d) return d;
    }
    return 0;
  };
  const ordered = [...rParas.values()]
    .sort((a, b) => cmp(a.order, b.order))
    .map((entry) =>
      [...entry.chars.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([, c]) => c)
        .filter((c) => !/\s/.test(c.ch)),
    )
    .filter((chars) => chars.length);
  const rTexts = ordered.map((chars) => chars.map((c) => c.ch).join(""));

  // 우리 문단 ↔ rhwp 문단: 문서 순서대로, 빈칸 뺀 글이 같은 것끼리
  const paraMap = new Map<number, number>();
  let j = 0;
  paras.forEach((text, n) => {
    const want = squeeze(text);
    if (!want) return;
    for (let r = j; r < Math.min(rTexts.length, j + 80); r += 1) {
      if (rTexts[r] === want) {
        paraMap.set(n, r);
        j = r + 1;
        return;
      }
    }
  });

  // 우리 문단 안 글자 순번 → 빈칸 뺀 순번
  const nonSpaceIndex = paras.map((text) => {
    const idx: number[] = [];
    let k = 0;
    for (const ch of text) {
      idx.push(/\s/.test(ch) ? -1 : k++);
    }
    return idx;
  });

  const geom = new Map<string, HwpItemGeom>();
  let mapped = 0;
  for (const item of items) {
    const boxes = (item.pspots ?? []).map((spot) => {
      if (!spot) return null;
      const [n, i] = spot;
      const r = paraMap.get(n);
      if (r === undefined) return null;
      const k = nonSpaceIndex[n]?.[i] ?? -1;
      const c = k >= 0 ? ordered[r][k] : undefined;
      return c ? { page: c.page, box: c.box } : null;
    });
    const first = boxes.find((b) => b);
    if (first) mapped += 1;
    geom.set(item.id, { page: first ? first.page + 1 : null, boxes });
  }

  const svgCache = new Map<number, string>();
  return {
    pageCount,
    pages,
    svg: (page: number) => {
      let svg = svgCache.get(page);
      if (svg === undefined) {
        svg = doc.renderPageSvg(page - 1);
        svgCache.set(page, svg);
      }
      return svg;
    },
    geom,
    mapped,
    close: () => {
      try {
        doc.free();
      } catch {
        /* 이미 닫힘 */
      }
    },
  };
}
