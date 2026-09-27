import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { ReleaseNote } from "../lib/releaseNotes";
import "./release-notes.css";

/**
 * 업데이트 내용 창. 새 버전으로 처음 켰을 때(띠의 [업데이트 내용 보기])와
 * 설정의 [업데이트 내역]에서 같이 쓴다.
 */
export function ReleaseNotesDialog({
  title,
  notes,
  current,
  onClose,
}: {
  title: string;
  notes: ReleaseNote[];
  current?: string;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="release-backdrop" onClick={onClose}>
      <div
        className="release-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="release-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="release-head">
          <h3 id="release-dialog-title">{title}</h3>
          <button className="icon-button" onClick={onClose} title="닫기">
            <X size={17} />
          </button>
        </div>
        <div className="release-body">
          {notes.map((note) => (
            <section key={note.version} className="release-version">
              <h4>
                {note.version}
                {note.version === current && <em>지금 버전</em>}
                {note.date && <small>{note.date}</small>}
              </h4>
              <ul>
                {note.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <div className="release-actions">
          <button ref={closeRef} className="primary-button" onClick={onClose}>
            확인
          </button>
        </div>
      </div>
    </div>
  );
}
