import { invoke } from "@tauri-apps/api/core";

/** PC 정보(1.5.2) — Rust 쪽 src-tauri/src/pcinfo.rs 와 주고받는 값 */
export interface PcInfo {
  manufacturer: string | null;
  model: string | null;
  computerName: string | null;
  windows: { name: string | null; version: string | null; build: string | null };
  uptimeSecs: number;
  cpu: { name: string | null; cores: number | null; threads: number | null };
  memory: { installed: number | null; usable: number | null; used: number | null };
  drives: {
    letter: string;
    kind: "fixed" | "removable" | "network";
    label: string | null;
    total: number | null;
    free: number | null;
  }[];
  gpus: string[];
  displays: { width: number; height: number; scale: number | null; primary: boolean }[];
  adapters: { name: string; ipv4: string[]; mac: string | null }[];
  elapsedMs: number;
}

export type PcDrive = PcInfo["drives"][number];

export const pcInfo = {
  read: () => invoke<PcInfo>("read_pc_info"),
  copy: (text: string) => invoke<void>("copy_pc_info", { text }),
};

export const UNKNOWN = "확인 안 됨";

const GB = 1024 ** 3;

/** 디스크 용량: 탐색기처럼 1024 단위. 1TB 이상은 TB, 10GB 미만은 소수 한 자리 */
export function formatSize(bytes: number): string {
  const gb = bytes / GB;
  if (gb >= 1024) return `${trim(gb / 1024, 1)} TB`;
  if (gb >= 10) return `${Math.round(gb).toLocaleString("ko-KR")} GB`;
  return `${trim(gb, 1)} GB`;
}

/** 메모리: 소수 한 자리(16.0 → 16) */
export function formatMemory(bytes: number): string {
  return `${trim(bytes / GB, 1)} GB`;
}

function trim(value: number, digits: number): string {
  return String(Number(value.toFixed(digits)));
}

export function formatUptime(secs: number): string {
  const days = Math.floor(secs / 86400);
  const hours = Math.floor((secs % 86400) / 3600);
  const minutes = Math.floor((secs % 3600) / 60);
  if (days > 0) return `${days}일 ${hours}시간 ${minutes}분`;
  if (hours > 0) return `${hours}시간 ${minutes}분`;
  return `${minutes}분`;
}

export function formatReadAt(date: Date): string {
  const h = date.getHours();
  const ampm = h < 12 ? "오전" : "오후";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${date.getFullYear()}. ${date.getMonth() + 1}. ${date.getDate()}. ${ampm} ${h12}:${mm}`;
}

export function memoryPercent(info: PcInfo): number | null {
  const { usable, used } = info.memory;
  return usable && used != null ? Math.round((used / usable) * 100) : null;
}

export function driveLabel(drive: PcDrive): string {
  if (drive.label) return drive.label;
  if (drive.kind === "network") return "네트워크 드라이브";
  return drive.kind === "removable" ? "이동식 디스크" : "로컬 디스크";
}

/** 남은 공간이 10% 아래면 주의(주황) */
export function driveLow(drive: PcDrive): boolean {
  return drive.total != null && drive.free != null && drive.total > 0 && drive.free / drive.total < 0.1;
}

export function displayNote(display: PcInfo["displays"][number]): string {
  return [display.scale != null ? `배율 ${display.scale}%` : null, display.primary ? "기본 화면" : null]
    .filter(Boolean)
    .join(" · ");
}

/** [전체 복사]에 넣을 글. 화면에 보이는 내용과 같다. */
export function pcInfoText(info: PcInfo, readAt: Date): string {
  const v = (s: string | null | undefined) => s || UNKNOWN;
  const lines: string[] = [`[PC 정보] ${formatReadAt(readAt)}`];
  lines.push(`컴퓨터: 제조사 ${v(info.manufacturer)} / 모델명 ${v(info.model)} / 컴퓨터 이름 ${v(info.computerName)}`);
  const win = [info.windows.name, info.windows.version].filter(Boolean).join(" ") || UNKNOWN;
  lines.push(
    `Windows: ${win}${info.windows.build ? ` (빌드 ${info.windows.build})` : ""} / 켜진 지 ${formatUptime(info.uptimeSecs)}`,
  );
  const cores = info.cpu.cores ? ` / ${info.cpu.cores}코어 ${info.cpu.threads ?? info.cpu.cores}스레드` : "";
  lines.push(`CPU: ${v(info.cpu.name)}${cores}`);
  const pct = memoryPercent(info);
  lines.push(
    `메모리: ${info.memory.installed ? formatMemory(info.memory.installed) : UNKNOWN}` +
      (info.memory.used != null ? ` / 사용 중 ${formatMemory(info.memory.used)}${pct != null ? ` (${pct}%)` : ""}` : ""),
  );
  lines.push(
    `디스크: ${
      info.drives
        .map((d) =>
          d.kind === "network" || d.total == null || d.free == null
            ? `${d.letter} ${driveLabel(d)} (네트워크 드라이브)`
            : `${d.letter} ${driveLabel(d)} ${formatSize(d.total)} 중 ${formatSize(d.free)} 남음`,
        )
        .join(" / ") || UNKNOWN
    }`,
  );
  lines.push(`그래픽: ${info.gpus.join(" / ") || UNKNOWN}`);
  lines.push(
    `화면: ${
      info.displays
        .map((d, i) => {
          const note = displayNote(d);
          return `화면 ${i + 1} ${d.width} × ${d.height}${note ? ` (${note})` : ""}`;
        })
        .join(" / ") || UNKNOWN
    }`,
  );
  lines.push(
    `네트워크: ${
      info.adapters
        .map((a) => `${a.name} IP ${a.ipv4.join(", ")}${a.mac ? `, MAC ${a.mac}` : ""}`)
        .join(" / ") || "연결된 네트워크 없음"
    }`,
  );
  return lines.join("\n");
}
