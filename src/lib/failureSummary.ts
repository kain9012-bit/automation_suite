/**
 * 도구 결과에서 실패한 항목을 읽어 사람이 읽을 줄로 만든다.
 *
 * 파이썬 쪽의 약속은 `failed: [{ name, error }]` 이다. 예전 도구는 문자열 목록이나
 * path·reason·message 같은 다른 키를 쓰는 것도 있어 모두 받아 준다.
 * 이 파일은 화면 코드에 기대지 않는 순수 함수만 둔다(tests/regression 에서 직접 부른다).
 */

export const FAILURE_LIST_LIMIT = 10;

const NAME_KEYS = ["name", "path", "file", "source", "input", "target", "item"];
const REASON_KEYS = ["error", "reason", "message", "detail"];

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** 경로면 파일 이름만 남긴다. 목록이 길어지지 않게. */
function shortName(value: string) {
  const parts = value.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || value;
}

/** 실패 항목 하나를 한 줄로. 알아볼 수 없는 모양이면 빈 문자열. */
export function describeFailure(item: unknown): string {
  if (item === null || item === undefined) return "";
  if (typeof item !== "object") return text(item);
  if (Array.isArray(item)) return item.map(text).filter(Boolean).join(": ");
  const record = item as Record<string, unknown>;
  const nameKey = NAME_KEYS.find((key) => text(record[key]));
  const reasonKey = REASON_KEYS.find((key) => text(record[key]));
  const name = nameKey ? shortName(text(record[nameKey])) : "";
  const reason = reasonKey ? text(record[reasonKey]) : "";
  if (name && reason) return `${name}: ${reason}`;
  if (name || reason) return name || reason;
  return text(record);
}

function pickFailed(source: Record<string, unknown>): unknown[] | null {
  const failed = source.failed;
  return Array.isArray(failed) ? failed : null;
}

function pickCount(source: Record<string, unknown>): number {
  const value = source.fail_count;
  const count = typeof value === "number" ? value : Number(value);
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

export interface FailureSummary {
  /** 실패한 개수. 목록과 fail_count 중 큰 쪽. */
  count: number;
  /** 보여 줄 줄(최대 FAILURE_LIST_LIMIT 개). */
  lines: string[];
  /** 목록에서 잘려 안 보이는 개수. */
  hidden: number;
}

/**
 * 결과(또는 결과 안의 result)에 실패가 있으면 요약을 돌려준다. 없으면 null.
 * failed 가 비어 있고 fail_count 도 0 이면 실패로 보지 않는다.
 */
export function summarizeFailures(result: Record<string, unknown>): FailureSummary | null {
  const nested =
    result.result && typeof result.result === "object" && !Array.isArray(result.result)
      ? (result.result as Record<string, unknown>)
      : null;
  const failed = pickFailed(result) ?? (nested ? pickFailed(nested) : null) ?? [];
  const counted = Math.max(pickCount(result), nested ? pickCount(nested) : 0);
  const described = failed.map(describeFailure).filter(Boolean);
  const count = Math.max(failed.length, counted);
  if (!count) return null;
  const lines = described.slice(0, FAILURE_LIST_LIMIT);
  return { count, lines, hidden: Math.max(0, described.length - lines.length) };
}

/** 실패 요약을 경고 팝업 본문으로 만든다. */
export function failureMessage(summary: FailureSummary, message: string, saved: string): string {
  const list = summary.lines.map((line) => `· ${line}`);
  if (summary.hidden) list.push(`… 외 ${summary.hidden}개`);
  return [
    message,
    `처리하지 못한 항목: ${summary.count}개`,
    list.join("\n"),
    saved ? `저장 위치: ${saved}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}
