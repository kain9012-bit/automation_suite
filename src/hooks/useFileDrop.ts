import { useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";

/**
 * 창에 파일이나 폴더를 끌어다 놓으면 경로를 넘겨준다.
 *
 * 등록이 비동기라 화면을 금방 벗어나면 정리 함수가 먼저 돈다. 그대로 두면
 * 리스너가 쌓여 한 번 놓은 파일이 여러 번 처리되므로 취소 처리를 넣는다.
 */
export function useFileDrop(onDrop: (paths: string[]) => void, enabled = true) {
  const [dropping, setDropping] = useState(false);
  const handlerRef = useRef(onDrop);

  useEffect(() => {
    handlerRef.current = onDrop;
  });

  useEffect(() => {
    if (!enabled) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;

    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (cancelled) return;
        const decision = dragDropDecision(event.payload);
        if (decision.highlight !== undefined) setDropping(decision.highlight);
        if (decision.paths?.length) handlerRef.current(decision.paths);
      })
      .then((stop) => {
        if (cancelled) {
          stop();
          return;
        }
        unlisten = stop;
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      setDropping(false);
      unlisten?.();
    };
  }, [enabled]);

  return dropping;
}

/**
 * 끌기 이벤트 하나를 어떻게 처리할지.
 *
 * Tauri 2 는 enter → over … → drop 또는 leave 순서로 알린다. enter 에도 경로가
 * 실려 오지만 아직 놓은 것이 아니다. 파일을 받는 것은 drop 하나뿐이다.
 * 예전에는 enter 가 drop 처럼 처리되어, 창 위로 끌고 지나가기만 해도 파일이 들어가고
 * 실제로 놓으면 한 번 더 들어갔다.
 */
export function dragDropDecision(payload: { type: string; paths?: string[] }): {
  highlight?: boolean;
  paths?: string[];
} {
  switch (payload.type) {
    case "enter":
    case "over":
      return { highlight: true };
    case "leave":
      return { highlight: false };
    case "drop":
      return { highlight: false, paths: payload.paths ?? [] };
    default:
      return {};
  }
}

/** 확장자 목록에 맞는 경로만 남긴다. 목록이 없으면 전부 통과시킨다. */
export function filterByExtension(paths: string[], extensions?: string[]) {
  if (!extensions?.length) return paths;
  const allowed = extensions.map((item) => item.toLowerCase());
  return paths.filter((path) => {
    const dot = path.lastIndexOf(".");
    if (dot < 0) return false;
    return allowed.includes(path.slice(dot + 1).toLowerCase());
  });
}
