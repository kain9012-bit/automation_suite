import { useEffect, useState } from "react";
import {
  checkToolUpdates,
  installAppUpdateIfAvailable,
  installToolUpdates,
  isTauriRuntime,
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

  useEffect(() => {
    if (!isTauriRuntime() || !isAutoUpdateEnabled()) return;
    let cancelled = false;

    const timer = window.setTimeout(async () => {
      try {
        setStatus("업데이트 확인 중");
        const restarting = await installAppUpdateIfAvailable((message) => {
          if (!cancelled) setStatus(message);
        });
        if (restarting || cancelled) return;

        const toolCheck = await checkToolUpdates();
        if (toolCheck.configured && toolCheck.updates.length > 0) {
          setStatus(
            `도구 업데이트 ${toolCheck.updates.length}개 설치 중`,
          );
          const result = await installToolUpdates();
          if (result.installed.length > 0) onToolsChanged();
          setStatus(result.message);
        } else {
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

  return status;
}

