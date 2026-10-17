import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";
import type { GuideStep } from "../lib/toolGuides";

/**
 * 파이썬 도구의 사용가이드. HTML 도구의 [사용가이드](tools/*\/web/index.html 의 jb-tour)와
 * 같은 자리·모양의 버튼과, 처음 사용 안내(TutorialOverlay)와 같은 모양의 안내를 쓴다.
 * 단계마다 그 영역(data-tour 표시)만 밝게 두고 나머지는 어둡게 한 뒤 옆에 설명 카드를 띄운다.
 * 화면에 없는 영역(예: 저장 위치가 없는 도구)의 단계는 열 때 뺀다.
 */

const find = (step: GuideStep) => document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
const visible = (element: HTMLElement | null) => {
  const box = element?.getBoundingClientRect();
  return !!box && box.width > 0 && box.height > 0;
};

/** 스크롤 영역 안에서 실제로 보이는 부분(처음 사용 안내와 같은 방식) */
function visibleRect(element: HTMLElement) {
  const box = element.getBoundingClientRect();
  let left = Math.max(8, box.left);
  let top = Math.max(8, box.top);
  let right = Math.min(window.innerWidth - 8, box.right);
  let bottom = Math.min(window.innerHeight - 8, box.bottom);
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const style = window.getComputedStyle(parent);
    const bounds = parent.getBoundingClientRect();
    if (/^(auto|scroll|hidden|clip)$/.test(style.overflowX)) {
      left = Math.max(left, bounds.left + parent.clientLeft + 6);
      right = Math.min(right, bounds.left + parent.clientLeft + parent.clientWidth - 6);
    }
    if (/^(auto|scroll|hidden|clip)$/.test(style.overflowY)) {
      top = Math.max(top, bounds.top + parent.clientTop + 6);
      bottom = Math.min(bottom, bounds.top + parent.clientTop + parent.clientHeight - 6);
    }
  }
  if (right - left < 4 || bottom - top < 4) return null;
  return new DOMRect(left, top, right - left, bottom - top);
}

/**
 * 카드 자리: 영역 아래 → 위 → 오른쪽 → 왼쪽 중 영역을 가리지 않는 첫 자리.
 * 영역이 커서 그런 자리가 없으면 화면 안에서 영역을 가장 덜 가리는 자리(네 귀퉁이 포함).
 */
function cardPosition(rect: DOMRect | null, cw: number, ch: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const M = 14;
  const G = 14;
  const clampL = (l: number) => Math.max(M, Math.min(vw - cw - M, l));
  const clampT = (t: number) => Math.max(M, Math.min(vh - ch - M, t));
  if (!rect) return { top: Math.max(M, (vh - ch) / 2), left: Math.max(M, (vw - cw) / 2) };
  const R = { l: rect.left - 6, t: rect.top - 6, r: rect.right + 6, b: rect.bottom + 6 };
  const overlap = (p: { top: number; left: number }) => {
    const w = Math.min(p.left + cw, R.r) - Math.max(p.left, R.l);
    const h = Math.min(p.top + ch, R.b) - Math.max(p.top, R.t);
    return w > 0 && h > 0 ? w * h : 0;
  };
  const fits = (p: { top: number; left: number }) => p.top >= M && p.top + ch <= vh - M && p.left >= M && p.left + cw <= vw - M;
  const sides = [
    { top: rect.bottom + G, left: clampL(rect.left) },
    { top: rect.top - G - ch, left: clampL(rect.left) },
    { top: clampT(rect.top), left: R.r + G - 6 },
    { top: clampT(rect.top), left: R.l - G + 6 - cw },
  ];
  const free = sides.find((p) => fits(p) && !overlap(p));
  if (free) return free;
  const candidates = sides
    .map((p) => ({ top: clampT(p.top), left: clampL(p.left) }))
    .concat([
      { top: vh - ch - M, left: M },
      { top: vh - ch - M, left: vw - cw - M },
      { top: M, left: M },
      { top: M, left: vw - cw - M },
    ]);
  return candidates.reduce((best, p) => (overlap(p) < overlap(best) ? p : best));
}

export function ToolGuide({ steps }: { steps: GuideStep[] }) {
  const [list, setList] = useState<GuideStep[] | null>(null);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  // 처음 자리를 잡을 때는 미끄러지는 움직임 없이 바로 놓고, 그다음 단계부터 움직인다
  const [animate, setAnimate] = useState(false);
  const cardRef = useRef<HTMLElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);

  const start = () => {
    const shown = steps.filter((step) => visible(find(step)));
    if (!shown.length) return;
    setIndex(0);
    setRect(null);
    setPos(null);
    setAnimate(false);
    setList(shown);
  };
  const close = useCallback(() => {
    setList(null);
    setRect(null);
    setPos(null);
    buttonRef.current?.focus();
  }, []);

  // 단계가 바뀌면 그 영역이 보이게 옮기고 잰다. 화면 크기·스크롤이 바뀌면 다시 잰다.
  useEffect(() => {
    if (!list) return;
    const element = find(list[index]);
    if (element && visible(element)) {
      const box = element.getBoundingClientRect();
      element.scrollIntoView({ behavior: "instant", block: box.height + 260 < window.innerHeight ? "center" : "start" });
    }
    let frame = 0;
    const measure = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const target = find(list[index]);
        setRect(target && visible(target) ? visibleRect(target) : null);
      });
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [list, index]);

  // 카드 크기를 잰 뒤 자리를 정한다(글 길이마다 높이가 달라서)
  useLayoutEffect(() => {
    if (!list || !cardRef.current) return;
    const card = cardRef.current;
    setPos(cardPosition(rect, card.offsetWidth, card.offsetHeight));
  }, [list, index, rect]);

  useEffect(() => {
    if (!pos || animate) return;
    const frame = window.requestAnimationFrame(() => setAnimate(true));
    return () => window.cancelAnimationFrame(frame);
  }, [pos, animate]);

  useEffect(() => {
    if (!list) return;
    nextRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [list, close]);

  const step = list?.[index];
  const last = !!list && index === list.length - 1;
  const cardWidth = Math.min(380, window.innerWidth - 28);

  return (
    <>
      <div className="tool-guide-anchor">
        <button ref={buttonRef} type="button" className="tool-guide-button" onClick={start}>
          사용가이드
        </button>
      </div>
      {list && step && (
        <div className={`tutorial-layer ${rect ? "" : "is-plain"}`} role="dialog" aria-modal="true" aria-label="사용가이드">
          {rect && (
            <div
              className="tutorial-spotlight"
              style={{ top: rect.top - 6, left: rect.left - 6, width: rect.width + 12, height: rect.height + 12 }}
            />
          )}
          <section
            ref={cardRef}
            className="tutorial-card"
            style={{ width: cardWidth, top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden", transition: animate ? undefined : "none" }}
          >
            <div className="tutorial-progress">
              <span>{index + 1} / {list.length}</span>
              <button type="button" onClick={close} aria-label="안내 닫기"><X size={17} /></button>
            </div>
            <strong>{step.title}</strong>
            <ul className="tool-guide-body">
              {step.body.split("\n").map((line, i) => <li key={i}>{line}</li>)}
            </ul>
            <div className="tutorial-actions">
              <button className="secondary-button" onClick={() => setIndex((value) => value - 1)} disabled={index === 0}>
                <ArrowLeft size={15} />이전
              </button>
              {last ? (
                <button ref={nextRef} className="primary-button" onClick={close}><Check size={15} />마치기</button>
              ) : (
                <button ref={nextRef} className="primary-button" onClick={() => setIndex((value) => value + 1)}>
                  다음<ArrowRight size={15} />
                </button>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
