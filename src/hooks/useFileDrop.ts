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
        if (event.payload.type === "over") {
          setDropping(true);
          return;
        }
        if (event.payload.type === "leave") {
          setDropping(false);
          return;
        }
        setDropping(false);
        const paths = event.payload.paths ?? [];
        if (paths.length) handlerRef.current(paths);
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
