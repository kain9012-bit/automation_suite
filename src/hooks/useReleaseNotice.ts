import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { compareVersion, notesBetween, type ReleaseNote } from "../lib/releaseNotes";

// 마지막으로 업데이트 내용을 본(또는 넘긴) 버전
const SEEN_KEY = "jbedu-suite:seen-version";

const read = (key: string) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};
const write = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 저장이 막혀 있어도 앱은 동작한다 */
  }
};

/** 이 PC 에서 앱을 써 온 흔적이 있는지(처음 설치와 업데이트를 가린다). */
const usedBefore = () => {
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i) ?? "";
      if (key !== SEEN_KEY && (key.startsWith("jbedu-suite:") || key.startsWith("jbedu:"))) return true;
    }
  } catch {
    /* 무시 */
  }
  return false;
};

// 앱 화면이 설정값(테마 등)을 저장하기 전에, 이 모듈을 불러오는 시점에 확인해 둔다.
const HAD_DATA = usedBefore();

/**
 * 업데이트 뒤 처음 켰는지 알아내 위쪽 띠에 보여 줄 업데이트 내용을 돌려준다.
 * - 처음 설치: 띠를 띄우지 않고 지금 버전을 본 것으로 둔다.
 * - 이 기능이 생기기 전 버전에서 올라온 경우(기록 없음·써 온 흔적 있음): 지금 버전 내용만 보여 준다.
 * - 여러 버전을 건너뛰었으면 그 사이 버전 내용을 모두 보여 준다.
 */
export function useReleaseNotice() {
  const [current, setCurrent] = useState("");
  const [notes, setNotes] = useState<ReleaseNote[]>([]);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let cancelled = false;
    void getVersion()
      .then((version) => {
        if (cancelled) return;
        setCurrent(version);
        const seen = read(SEEN_KEY);
        if (seen && compareVersion(seen, version) >= 0) {
          if (seen !== version) write(SEEN_KEY, version);
          return;
        }
        if (!seen && !HAD_DATA) {
          write(SEEN_KEY, version);
          return;
        }
        const list = notesBetween(seen ?? "", version);
        if (list.length) setNotes(list);
        else write(SEEN_KEY, version);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    current,
    notes,
    /** 띠를 닫거나 내용을 본 뒤 부른다. 다음부터 이 버전은 띄우지 않는다. */
    done: () => {
      if (current) write(SEEN_KEY, current);
      setNotes([]);
    },
  };
}
