import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";

/**
 * 처음 사용 안내(1.4.6에서 jb_quickpanel 방식으로 다시 만듦).
 * 단계마다 그 화면으로 옮겨 가서 실제 화면 부분을 밝게 두고 나머지만 어둡게 한다.
 * 강조할 곳은 각 화면의 data-tour 표시로 찾는다.
 */

export type TutorialDestination = {
  /** 이 단계를 보여 줄 화면 */
  view: "home" | "docsearch" | "settings";
};

type TutorialStep = TutorialDestination & {
  selector: string;
  title: string;
  body: string;
};

const STEPS: TutorialStep[] = [
  {
    view: "home",
    selector: '[data-tour="nav-main"]',
    title: "탐색 메뉴",
    body: "홈, 별표로 모아 둔 즐겨찾기, 최근에 쓴 도구, 내 PC 문서를 찾는 문서 검색으로 바로 이동합니다.",
  },
  {
    view: "home",
    selector: '[data-tour="nav-tools"]',
    title: "업무별 도구 분류",
    body: "엑셀·데이터, PDF·문서, 업무 자동화, 간단 도구, 수집·추출로 나뉘어 있습니다. 분류를 누르면 그 분류의 도구만 모아 보여 줍니다.",
  },
  {
    view: "home",
    selector: '[data-tour="home-search"]',
    title: "도구 찾기",
    body: "도구 이름이나 하려는 업무(예: 병합, 압축, 마스킹)를 입력하면 아래 도구 목록이 바로 걸러집니다.",
  },
  {
    view: "home",
    selector: '[data-tour="search"]',
    title: "명령 검색 (Ctrl+K)",
    body: "어느 화면에서든 Ctrl+K를 누르면 검색창이 열립니다. 도구 이름을 입력하고 눌러 바로 엽니다.",
  },
  {
    view: "home",
    selector: '[data-tour="quick-launcher"]',
    title: "빠른 실행",
    body: "자주 여는 사이트·폴더·파일·프로그램을 ‘새 버튼’으로 등록해 두고 클릭 한 번으로 엽니다. 버튼마다 단축키를 정할 수 있고, 페이지를 나눠 정리할 수 있습니다.",
  },
  {
    view: "home",
    selector: '[data-tour="all-tools"] .tool-card',
    title: "도구 실행",
    body: "카드를 누르면 바로 열립니다. 파일 처리 도구는 파일을 끌어다 놓거나 골라 넣고 ‘작업 실행’을 누르면, 끝난 뒤 결과와 저장 위치를 팝업으로 알려 줍니다. ‘초기화’로 넣은 파일과 설정을 비웁니다.",
  },
  {
    view: "home",
    selector: '[data-tour="all-tools"] .tool-card .favorite-button',
    title: "즐겨찾기",
    body: "카드의 별을 누르면 즐겨찾기에 들어가 홈 위쪽과 왼쪽 ‘즐겨찾기’에 모입니다. 한 번 더 누르면 빠집니다.",
  },
  {
    view: "home",
    selector: '[data-tour="header-actions"]',
    title: "위쪽 버튼",
    body: "명령 검색, 도구 목록 새로고침, 빠른 실행으로 이동, 밝은·어두운 화면 바꾸기가 있습니다. 왼쪽 끝 버튼으로 사이드바를 접고 펼 수 있습니다.",
  },
  {
    view: "docsearch",
    selector: '[data-tour="docsearch"]',
    title: "문서 검색",
    body: "내 PC의 한글·PDF·워드 등 문서를 파일 이름과 내용으로 찾습니다. 처음에는 찾을 폴더와 내용까지 찾을 문서 종류를 고르며, 고르기 전에는 아무 파일도 읽지 않습니다. 색인은 PC 안에만 저장됩니다.",
  },
  {
    view: "settings",
    selector: '[data-tour="settings-desktop"]',
    title: "Windows 시작과 트레이",
    body: "컴퓨터를 켤 때 자동 실행할지, 닫기·최소화할 때 작업 표시줄 대신 트레이에 숨길지 정합니다.",
  },
  {
    view: "settings",
    selector: '[data-tour="settings-hotkey"]',
    title: "창 열기·숨기기 단축키",
    body: "어느 프로그램을 쓰고 있든 이 키(기본 Ctrl+Alt+J)를 누르면 JB업무ON을 꺼내고, 다시 누르면 숨깁니다.",
  },
  {
    view: "settings",
    selector: '[data-tour="settings-notify"]',
    title: "작업 완료 알림",
    body: "오래 걸리는 작업을 실행해 두고 다른 일을 할 때, 끝나면 윈도우 알림으로 알려 줍니다.",
  },
  {
    view: "settings",
    selector: '[data-tour="settings-update"]',
    title: "앱 업데이트",
    body: "새 버전을 미리 받아 두고, 화면 위쪽 안내에서 ‘지금 적용’이나 ‘나중에’를 고릅니다. 아래 ‘업데이트 내역’에서 버전마다 바뀐 내용을 볼 수 있습니다.",
  },
  {
    view: "settings",
    selector: '[data-tour="settings-tutorial"]',
    title: "안내 다시 보기",
    body: "이 안내는 설정의 ‘튜토리얼 다시 보기’로 언제든 다시 볼 수 있습니다.",
  },
  {
    view: "home",
    selector: '[data-tour="status"]',
    title: "상태 표시줄",
    body: "업데이트 확인 상태와 불러온 도구 수가 표시됩니다. 도구 목록을 불러오지 못하면 이곳에 이유가 나옵니다.",
  },
  {
    view: "home",
    selector: '[data-tour="support"]',
    title: "문의",
    body: "오류나 개선 의견은 정책기획과 빅데이터팀으로 알려 주세요. 이 카드를 누르면 JB에듀 메신저로 담당자에게 쪽지를 쓰는 창이 열립니다. 설정 아래에 있는 버전 번호를 함께 알려 주시면 빨리 확인할 수 있습니다.",
  },
];

/** 강조할 곳이 그려지기를 기다리는 최대 시간(화면을 옮긴 직후 등). 넘으면 강조 없이 카드만 띄운다. */
const WAIT_MS = 2000;

export function TutorialOverlay({
  open,
  onNavigate,
  onClose,
}: {
  open: boolean;
  onNavigate: (destination: TutorialDestination) => void;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (!open) return;
    setIndex(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const step = STEPS[Math.min(index, STEPS.length - 1)];
    onNavigate({ view: step.view });
    setRect(null);
    const started = performance.now();
    let scrolled = false;
    let frame = 0;
    const measure = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const element = document.querySelector(step.selector);
        const box = element?.getBoundingClientRect();
        if (!element || !box || box.width === 0 || box.height === 0) {
          if (performance.now() - started < WAIT_MS) measure();
          else setRect(null);
          return;
        }
        if (!scrolled) {
          element.scrollIntoView({ behavior: "instant", block: "nearest" });
          scrolled = true;
        }
        const elementRect = element.getBoundingClientRect();
        let left = Math.max(8, elementRect.left);
        let top = Math.max(8, elementRect.top);
        let right = Math.min(window.innerWidth - 8, elementRect.right);
        let bottom = Math.min(window.innerHeight - 8, elementRect.bottom);
        // 스크롤 영역 안에서 실제로 보이는 부분만 강조한다.
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
        if (right - left < 4 || bottom - top < 4) {
          setRect(null);
          return;
        }
        setRect(new DOMRect(left, top, right - left, bottom - top));
      });
    };
    measure();
    // 화면을 옮긴 뒤 내용이 늦게 채워져 크기가 바뀌는 곳(문서 검색 등)이 있어 몇 번 더 잰다.
    const timers = [250, 700, 1500].map((ms) => window.setTimeout(measure, ms));
    window.addEventListener("resize", measure);
    return () => {
      window.cancelAnimationFrame(frame);
      timers.forEach((timer) => window.clearTimeout(timer));
      window.removeEventListener("resize", measure);
    };
  }, [index, onNavigate, open]);

  if (!open) return null;
  const step = STEPS[Math.min(index, STEPS.length - 1)];
  const last = index === STEPS.length - 1;
  const cardWidth = Math.min(380, window.innerWidth - 28);
  const estimatedHeight = 230;
  const cardTop = rect
    ? Math.max(14, Math.min(window.innerHeight - estimatedHeight - 14,
      rect.bottom + 14 + estimatedHeight < window.innerHeight ? rect.bottom + 14 : rect.top - estimatedHeight - 14))
    : Math.max(14, window.innerHeight / 2 - estimatedHeight / 2);
  const cardLeft = rect
    ? Math.max(14, Math.min(window.innerWidth - cardWidth - 14, rect.left))
    : Math.max(14, (window.innerWidth - cardWidth) / 2);

  const finish = () => {
    localStorage.setItem("jbedu-suite:tutorial-complete", "true");
    setIndex(0);
    setRect(null);
    onClose();
  };

  return (
    // 어둡게 하는 것은 강조 상자의 바깥 그림자 하나뿐이라 강조한 곳은 원래 밝기 그대로 보인다.
    // 강조할 곳을 못 찾았을 때만 화면 전체를 어둡게 한다(is-plain).
    <div className={`tutorial-layer ${rect ? "" : "is-plain"}`} role="dialog" aria-modal="true" aria-label="처음 사용 안내">
      {rect && (
        <div
          className="tutorial-spotlight"
          style={{ top: rect.top - 6, left: rect.left - 6, width: rect.width + 12, height: rect.height + 12 }}
        />
      )}
      <section className="tutorial-card" style={{ top: cardTop, left: cardLeft, width: cardWidth }}>
        <div className="tutorial-progress">
          <span>{index + 1} / {STEPS.length}</span>
          <button type="button" onClick={finish} aria-label="안내 닫기"><X size={17} /></button>
        </div>
        <strong>{step.title}</strong>
        <p>{step.body}</p>
        <div className="tutorial-actions">
          <button className="secondary-button" onClick={() => setIndex((value) => value - 1)} disabled={index === 0}>
            <ArrowLeft size={15} />이전
          </button>
          {last ? (
            <button className="primary-button" onClick={finish}><Check size={15} />시작하기</button>
          ) : (
            <button className="primary-button" onClick={() => setIndex((value) => value + 1)}>다음<ArrowRight size={15} /></button>
          )}
        </div>
      </section>
    </div>
  );
}
