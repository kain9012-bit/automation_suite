import { useEffect, useRef, useState } from "react";
import { Keyboard, RotateCcw } from "lucide-react";

/**
 * 글자를 직접 치는 대신 입력칸을 누른 뒤 원하는 단축키를 눌러 지정한다.
 * Tauri 전역 단축키가 알아듣는 형식("Ctrl+Alt+Space")으로 만들어 준다.
 */

const MODIFIER_KEYS = new Set(["Control", "Alt", "Shift", "Meta"]);

function keyName(code: string, key: string): string | null {
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Numpad")) return `Numpad${code.slice(6)}`;
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  const named: Record<string, string> = {
    Space: "Space",
    Enter: "Enter",
    NumpadEnter: "Enter",
    Escape: "Escape",
    Tab: "Tab",
    Backspace: "Backspace",
    Delete: "Delete",
    Insert: "Insert",
    Home: "Home",
    End: "End",
    PageUp: "PageUp",
    PageDown: "PageDown",
    ArrowUp: "Up",
    ArrowDown: "Down",
    ArrowLeft: "Left",
    ArrowRight: "Right",
    Minus: "Minus",
    Equal: "Equal",
    BracketLeft: "BracketLeft",
    BracketRight: "BracketRight",
    Semicolon: "Semicolon",
    Quote: "Quote",
    Backquote: "Backquote",
    Backslash: "Backslash",
    Comma: "Comma",
    Period: "Period",
    Slash: "Slash",
  };
  if (named[code]) return named[code];
  if (key.length === 1) return key.toUpperCase();
  return null;
}

export function HotkeyInput({
  value,
  fallback,
  onChange,
  disabled,
}: {
  value: string;
  fallback: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const [capturing, setCapturing] = useState(false);
  const [hint, setHint] = useState("");
  const boxRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!capturing) return;
    const handler = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();

      if (event.key === "Escape") {
        setCapturing(false);
        setHint("");
        return;
      }
      if (MODIFIER_KEYS.has(event.key)) {
        setHint("조합할 글자나 숫자를 함께 눌러 주세요.");
        return;
      }

      const parts: string[] = [];
      if (event.ctrlKey) parts.push("Ctrl");
      if (event.altKey) parts.push("Alt");
      if (event.shiftKey) parts.push("Shift");
      if (event.metaKey) parts.push("Super");

      const main = keyName(event.code, event.key);
      if (!main) {
        setHint("이 키는 단축키로 쓸 수 없습니다.");
        return;
      }
      if (!parts.length) {
        setHint("Ctrl, Alt, Shift 중 하나는 반드시 포함해야 합니다.");
        return;
      }

      parts.push(main);
      onChange(parts.join("+"));
      setCapturing(false);
      setHint("");
    };

    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [capturing, onChange]);

  useEffect(() => {
    if (capturing) boxRef.current?.focus();
  }, [capturing]);

  return (
    <div className="hotkey-input">
      <button
        ref={boxRef}
        type="button"
        className={`hotkey-box ${capturing ? "is-capturing" : ""}`}
        disabled={disabled}
        onClick={() => {
          setCapturing((current) => !current);
          setHint("");
        }}
        onBlur={() => setCapturing(false)}
      >
        <Keyboard size={14} />
        <span>{capturing ? "원하는 키를 누르세요" : value || "지정 안 됨"}</span>
      </button>
      {value !== fallback && (
        <button
          type="button"
          className="hotkey-reset"
          disabled={disabled}
          onClick={() => onChange(fallback)}
          title="기본값으로 되돌리기"
        >
          <RotateCcw size={13} />
        </button>
      )}
      {hint && <small className="hotkey-hint">{hint}</small>}
    </div>
  );
}
