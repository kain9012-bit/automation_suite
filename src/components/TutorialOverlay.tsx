import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";

const STEPS = [
  { selector: '[data-tour="sidebar"]', title: "업무별 도구 메뉴", body: "엑셀 데이터, PDF 문서, 수집·추출, 업무 자동화, 간단 도구 순서로 필요한 기능을 찾을 수 있습니다." },
  { selector: '[data-tour="search"]', title: "빠른 도구 검색", body: "도구 이름이나 하려는 업무를 검색하세요. Ctrl+K를 눌러 어디서든 검색창을 열 수도 있습니다." },
  { selector: '[data-tour="tool-area"]', title: "한 화면에서 실행", body: "도구를 선택하면 이 영역에서 바로 작업합니다. HTML 도구도 별도 창 없이 내부에서 열립니다." },
  { selector: '[data-tour="macro-toggle"]', title: "빠른 실행", body: "홈 화면의 빠른 실행에 자주 쓰는 사이트·폴더·프로그램을 등록해 두고 클릭이나 단축키로 실행합니다. 파일을 끌어다 놓아도 바로 등록되고, 반복 작업은 매크로로 묶을 수 있습니다." },
  { selector: '[data-tour="support"]', title: "관련 문의", body: "오류나 개선 의견이 있을 때 확인할 수 있는 문의 안내를 사이드바 하단에 두었습니다." },
  { selector: '[data-tour="settings"]', title: "시작 및 트레이 설정", body: "Windows 자동 시작, 트레이 최소화, 업데이트 설정을 여기에서 관리하고 이 안내를 다시 볼 수 있습니다." },
];

export function TutorialOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (!open) return;
    setIndex(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const update = () => {
      const element = document.querySelector(STEPS[index].selector);
      element?.scrollIntoView({ behavior: "smooth", block: "center" });
      window.setTimeout(() => setRect(element?.getBoundingClientRect() ?? null), 180);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [index, open]);

  if (!open) return null;
  const step = STEPS[index];
  const cardTop = rect ? Math.min(window.innerHeight - 250, Math.max(24, rect.bottom + 18)) : window.innerHeight / 2 - 110;
  const cardLeft = rect ? Math.min(window.innerWidth - 390, Math.max(24, rect.left)) : window.innerWidth / 2 - 180;

  const finish = () => {
    localStorage.setItem("jbedu-suite:tutorial-complete", "true");
    onClose();
  };

  return (
    <div className="tutorial-layer" role="dialog" aria-modal="true" aria-label="처음 사용 안내">
      {rect && <div className="tutorial-spotlight" style={{ top: rect.top - 7, left: rect.left - 7, width: rect.width + 14, height: rect.height + 14 }} />}
      <section className="tutorial-card" style={{ top: cardTop, left: cardLeft }}>
        <div className="tutorial-progress"><span>{index + 1} / {STEPS.length}</span><button onClick={finish} aria-label="안내 닫기"><X size={17} /></button></div>
        <strong>{step.title}</strong>
        <p>{step.body}</p>
        <div className="tutorial-actions">
          <button className="secondary-button" onClick={() => setIndex((value) => value - 1)} disabled={index === 0}><ArrowLeft size={15} />이전</button>
          {index === STEPS.length - 1 ? (
            <button className="primary-button" onClick={finish}><Check size={15} />시작하기</button>
          ) : (
            <button className="primary-button" onClick={() => setIndex((value) => value + 1)}>다음<ArrowRight size={15} /></button>
          )}
        </div>
      </section>
    </div>
  );
}
