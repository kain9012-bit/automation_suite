import { useEffect, useRef } from "react";
import { CircleAlert, CircleCheck, CircleX, FolderOpen } from "lucide-react";
import "./result-dialog.css";

export type ResultPopup = {
  level: "success" | "warning" | "error";
  title: string;
  message: string;
};

/** 결과를 문자열 그대로 믿지 않고 모양을 확인한 뒤에만 팝업으로 쓴다. */
export function readResultPopup(value: unknown): ResultPopup | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const level = item.level;
  if (level !== "success" && level !== "warning" && level !== "error") return null;
  return {
    level,
    title: String(item.title ?? ""),
    message: String(item.message ?? ""),
  };
}

const ICONS = {
  success: CircleCheck,
  warning: CircleAlert,
  error: CircleX,
};

/**
 * 작업이 끝난 뒤 결과를 크게 보여 주는 창.
 * 작업 기록은 글씨가 작아 지나치기 쉬워서, 성공·일부 미달·실패를 한눈에 알린다.
 */
export function ResultDialog({
  popup,
  onClose,
  onReveal,
}: {
  popup: ResultPopup;
  onClose: () => void;
  onReveal?: () => void;
}) {
  const okRef = useRef<HTMLButtonElement>(null);
  const Icon = ICONS[popup.level];

  useEffect(() => {
    okRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="result-dialog-backdrop" onClick={onClose}>
      <div
        className={`result-dialog is-${popup.level}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="result-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="result-dialog-icon">
          <Icon size={34} />
        </div>
        <h3 id="result-dialog-title">{popup.title}</h3>
        {popup.message && <p className="result-dialog-message">{popup.message}</p>}
        <div className="result-dialog-actions">
          {onReveal && (
            <button className="secondary-button" onClick={onReveal}>
              <FolderOpen size={15} />
              결과 폴더 열기
            </button>
          )}
          <button ref={okRef} className="primary-button" onClick={onClose}>
            확인
          </button>
        </div>
      </div>
    </div>
  );
}
