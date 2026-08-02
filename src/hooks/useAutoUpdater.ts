import { useCallback, useEffect, useState } from "react";
import {
  UPDATE_READY,
  applyPendingUpdate,
  checkToolUpdates,
  downloadUpdateIfAvailable,
  installToolUpdates,
  isTauriRuntime,
  pendingUpdateVersion,
} from "../lib/updater";

const AUTO_UPDATE_KEY = "jbedu-suite:auto-update";

export function isAutoUpdateEnabled() {
  return localStorage.getItem(AUTO_UPDATE_KEY) !== "off";
}

export function setAutoUpdateEnabled(enabled: boolean) {
  localStorage.setItem(AUTO_UPDATE_KEY, enabled ? "on" : "off");
}

export function useAutoUpdater(onToolsChanged: () => void) {
  const [status, setStatus] = useState("준비됨");
  // 받아 두었지만 아직 적용하지 않은 버전. 화면 위 띠에 쓴다.
  const [ready, setReady] = useState("");
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const sync = () => {
      setReady(pendingUpdateVersion());
      setDismissed(false);
    };
    window.addEventListener(UPDATE_READY, sync);
    return () => window.removeEventListener(UPDATE_READY, sync);
  }, []);

  useEffect(() => {
    if (!isTauriRuntime() || !isAutoUpdateEnabled()) return;
    let cancelled = false;

    const timer = window.setTimeout(async () => {
      try {
        setStatus("업데이트 확인 중");
        // 내려받기만 하고 설치는 사용자가 고르게 한다.
        const version = await downloadUpdateIfAvailable((message) => {
          if (!cancelled) setStatus(message);
        });
        if (cancelled) return;

        const toolCheck = await checkToolUpdates();
        if (cancelled) return;
        if (toolCheck.configured && toolCheck.updates.length > 0) {
          setStatus(`도구 업데이트 ${toolCheck.updates.length}개 설치 중`);
          const result = await installToolUpdates();
          if (result.installed.length > 0) onToolsChanged();
          setStatus(result.message);
        } else if (!version) {
          setStatus("최신 상태");
        }
      } catch {
        if (!cancelled) setStatus("준비됨");
      }
    }, 1800);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [onToolsChanged]);

  const apply = useCallback(async () => {
    try {
      await applyPendingUpdate(setStatus);
    } catch (reason) {
      setStatus(`업데이트 적용 실패: ${reason instanceof Error ? reason.message : String(reason)}`);
    }
  }, []);

  return {
    status,
    // '나중에'를 누르면 이번 실행 동안에는 띠를 숨긴다. 다음에 켜면 다시 뜬다.
    readyVersion: dismissed ? "" : ready,
    apply,
    dismiss: () => setDismissed(true),
  };
}
