import { useEffect, useMemo, useRef, useState } from "react";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";
import {
  DECK_CHANGED,
  activeDeckPage,
  readStoredDeck,
  runDeckAction,
  type DeckAction,
} from "../lib/quickDeck";

/** 등록·해제가 비동기라 순서가 뒤섞이지 않게 한 줄로 세운다. */
let queue: Promise<void> = Promise.resolve();
const enqueue = (task: () => Promise<void>) => {
  queue = queue.then(task).catch(() => undefined);
};

function hotkeyActions(): DeckAction[] {
  const deck = readStoredDeck();
  const page = deck ? activeDeckPage(deck) : undefined;
  return (page?.actions ?? []).filter((action) => action.hotkey?.trim());
}

/**
 * 빠른 실행 버튼의 단축키를 앱이 떠 있는 내내 등록해 둔다.
 *
 * 예전에는 홈 화면의 빠른 실행 영역이 등록을 맡아, 도구나 설정 화면을 열면
 * 단축키가 모두 풀렸다. 이제 App 에서 한 번만 쓰고, 버튼을 고치면
 * (DECK_CHANGED 이벤트) 바뀐 것만 보고 다시 등록한다.
 */
export function useQuickLauncherHotkeys() {
  const [actions, setActions] = useState<DeckAction[]>(hotkeyActions);

  useEffect(() => {
    const reload = () => setActions(hotkeyActions());
    window.addEventListener(DECK_CHANGED, reload);
    return () => window.removeEventListener(DECK_CHANGED, reload);
  }, []);

  // 단축키에 영향을 주는 값이 바뀔 때만 다시 등록한다. 최근 기록만 바뀐 경우는 그대로 둔다.
  const signature = JSON.stringify(
    actions.map((action) => [action.id, action.hotkey, action.type, action.target, action.arguments]),
  );
  const current = useMemo(() => actions, [signature]); // eslint-disable-line react-hooks/exhaustive-deps

  // 전역 등록에 성공한 조합은 창 keydown 폴백에서 제외해 두 번 실행되지 않게 한다.
  const globalHotkeys = useRef(new Set<string>());

  useEffect(() => {
    let cancelled = false;
    const registered: string[] = [];
    enqueue(async () => {
      for (const action of current) {
        if (cancelled) return;
        const hotkey = action.hotkey.trim();
        try {
          await register(hotkey, (event) => {
            if (event.state === "Pressed") void runDeckAction(action);
          });
        } catch {
          continue;
        }
        registered.push(hotkey);
        globalHotkeys.current.add(hotkey.toLowerCase());
      }
    });
    return () => {
      cancelled = true;
      enqueue(async () => {
        for (const hotkey of registered) {
          globalHotkeys.current.delete(hotkey.toLowerCase());
          await unregister(hotkey).catch(() => undefined);
        }
      });
    };
  }, [current]);

  // 전역 등록에 실패한 조합은 창이 앞에 있을 때만이라도 동작하게 한다.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.target instanceof HTMLSelectElement
      )
        return;
      const combo = [
        event.ctrlKey && "ctrl",
        event.altKey && "alt",
        event.shiftKey && "shift",
        event.metaKey && "win",
        event.key.toLowerCase(),
      ]
        .filter(Boolean)
        .join("+");
      if (globalHotkeys.current.has(combo)) return;
      const action = current.find((item) => item.hotkey.trim().toLowerCase() === combo);
      if (action) {
        event.preventDefault();
        void runDeckAction(action);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [current]);
}
