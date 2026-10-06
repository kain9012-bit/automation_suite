// 프런트엔드 순수 함수 회귀 검사. 실행: node tests/regression/frontend_helpers.test.ts
// (Node 22.18+ 는 TypeScript 형식 표기를 그대로 벗겨 실행한다. 더 낮으면 --experimental-strip-types)
import assert from "node:assert/strict";
import {
  describeFailure,
  failureMessage,
  summarizeFailures,
} from "../../src/lib/failureSummary.ts";
import { dragDropDecision, filterByExtension } from "../../src/hooks/useFileDrop.ts";
import {
  beginToolRun,
  getToolRun,
  openToolRun,
  updateToolRun,
} from "../../src/lib/toolRunStore.ts";
import { readFileSync, readdirSync } from "node:fs";
import { TAB_STYLES, TOOL_ICONS, toolIcon, toolTone } from "../../src/lib/toolIcons.ts";
import { DOWNLOAD_MESSAGE, injectDownloadBridge, readDownloadMessage } from "../../src/lib/htmlToolDownload.ts";

let passed = 0;
const test = (name: string, body: () => void) => {
  body();
  passed += 1;
  console.log(`ok - ${name}`);
};

// ── 9. 실패 목록 ────────────────────────────────────────────────
test("새 약속 {name, error}", () => {
  assert.equal(describeFailure({ name: "a.pdf", error: "암호" }), "a.pdf: 암호");
});
test("예전 모양: 문자열, path/reason, message", () => {
  assert.equal(describeFailure("tool: 모듈 없음"), "tool: 모듈 없음");
  assert.equal(describeFailure({ path: "C:\\자료\\b.hwp", reason: "잠김" }), "b.hwp: 잠김");
  assert.equal(describeFailure({ message: "알 수 없음" }), "알 수 없음");
  assert.equal(describeFailure({ code: 3 }), '{"code":3}');
  assert.equal(describeFailure(null), "");
});
test("실패가 없으면 null", () => {
  assert.equal(summarizeFailures({ ok: true, failed: [] }), null);
  assert.equal(summarizeFailures({ ok: true, fail_count: 0 }), null);
  assert.equal(summarizeFailures({ ok: true }), null);
});
test("fail_count 만 있어도 경고 (중첩 result 포함)", () => {
  const summary = summarizeFailures({ ok: true, result: { fail_count: 2 } });
  assert.deepEqual(summary, { count: 2, lines: [], hidden: 0 });
});
test("10개까지만 보이고 나머지는 개수로", () => {
  const failed = Array.from({ length: 13 }, (_, i) => ({ name: `f${i}.zip`, error: "손상" }));
  const summary = summarizeFailures({ failed });
  assert.ok(summary);
  assert.equal(summary.count, 13);
  assert.equal(summary.lines.length, 10);
  assert.equal(summary.hidden, 3);
  const text = failureMessage(summary, "압축을 풀었습니다.", "C:\\out");
  assert.match(text, /처리하지 못한 항목: 13개/);
  assert.match(text, /· f0\.zip: 손상/);
  assert.match(text, /… 외 3개/);
  assert.match(text, /저장 위치: C:\\out/);
});

// ── 5. 끌어다 놓기 ──────────────────────────────────────────────
test("enter 는 경로가 있어도 파일을 넣지 않는다", () => {
  assert.deepEqual(dragDropDecision({ type: "enter", paths: ["C:\\a.pdf"] }), { highlight: true });
  assert.deepEqual(dragDropDecision({ type: "over" }), { highlight: true });
  assert.deepEqual(dragDropDecision({ type: "leave" }), { highlight: false });
  assert.deepEqual(dragDropDecision({ type: "drop", paths: ["C:\\a.pdf"] }), {
    highlight: false,
    paths: ["C:\\a.pdf"],
  });
});
test("확장자 거르기는 그대로", () => {
  assert.deepEqual(filterByExtension(["a.HWP", "b.txt", "폴더"], ["hwp"]), ["a.HWP"]);
});

// ── 6. 도구 실행 상태 ───────────────────────────────────────────
test("같은 도구는 겹쳐 돌지 않고, 화면을 다시 열어도 실행 중으로 남는다", () => {
  openToolRun("t1");
  assert.equal(beginToolRun("t1", "시작"), true);
  assert.equal(beginToolRun("t1", "또 시작"), false);
  openToolRun("t1"); // 다른 화면에 갔다가 돌아옴
  assert.equal(getToolRun("t1").running, true);
  assert.deepEqual(getToolRun("t1").log, ["시작"]);
  updateToolRun("t1", () => ({
    running: false,
    popup: { level: "success", title: "끝", message: "" },
  }));
  openToolRun("t1"); // 결과 팝업을 아직 안 봤으면 남긴다
  assert.equal(getToolRun("t1").popup?.title, "끝");
  updateToolRun("t1", () => ({ popup: null }));
  openToolRun("t1"); // 다 본 뒤 새로 열면 빈 상태
  assert.deepEqual(getToolRun("t1").log, []);
});

// ── 7. 도구 카드 아이콘 ─────────────────────────────────────────
test("tools 폴더의 모든 도구에 기능 아이콘과 탭 색이 정해져 있다", () => {
  const root = new URL("../../tools/", import.meta.url);
  const missingIcon: string[] = [];
  const unknownTab: string[] = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    let text: string;
    try {
      text = readFileSync(new URL(`${entry.name}/manifest.json`, root), "utf-8");
    } catch {
      continue;
    }
    const manifest = JSON.parse(text.replace(/^\uFEFF/, ""));
    if (!TOOL_ICONS[manifest.id]) missingIcon.push(manifest.id);
    if (!TAB_STYLES[manifest.top_tab]) unknownTab.push(`${manifest.id}(${manifest.top_tab})`);
  }
  assert.deepEqual(missingIcon, [], "src/lib/toolIcons.ts 의 TOOL_ICONS 에 추가하세요");
  assert.deepEqual(unknownTab, [], "src/lib/toolIcons.ts 의 TAB_STYLES 와 index.css tone-* 에 추가하세요");
});
test("아이콘을 정하지 않은 도구는 탭 아이콘, 모르는 탭은 기본 색", () => {
  assert.equal(toolIcon({ id: "새_도구", top_tab: "PDF·문서" }), TAB_STYLES["PDF·문서"].icon);
  assert.equal(toolTone({ top_tab: "새 탭" }), "default");
  assert.equal(toolTone({ top_tab: "엑셀·데이터" }), "data");
});

// ── HTML 도구 내려받기 가로채기 ─────────────────────────────────
test("가로채기 스크립트는 <head> 바로 뒤, doctype 앞에는 넣지 않음", () => {
  const out = injectDownloadBridge("<!DOCTYPE html>\n<html lang=ko><head><meta charset=utf-8></head><body></body></html>");
  assert.ok(out.startsWith("<!DOCTYPE html>\n<html lang=ko><head><script>"));
  assert.equal(out.match(/__jbeduDownloadBridge = true/g)?.length, 1);
  assert.ok(injectDownloadBridge("<!doctype html><p>x").startsWith("<!doctype html><script>"));
  assert.ok(injectDownloadBridge("<p>x").startsWith("<script>"));
});
test("가로채기 스크립트에 </script> 가 섞이지 않음", () => {
  const out = injectDownloadBridge("<head></head>");
  assert.equal(out.indexOf("</script>"), out.lastIndexOf("</script>"));
});
test("내려받기 메시지만 받아들임", () => {
  const bytes = new ArrayBuffer(3);
  assert.deepEqual(readDownloadMessage({ type: DOWNLOAD_MESSAGE, name: "a.xlsx", bytes }), { name: "a.xlsx", bytes });
  assert.equal(readDownloadMessage({ type: "other", bytes }), null);
  assert.equal(readDownloadMessage({ type: DOWNLOAD_MESSAGE, bytes: "x" }), null);
  assert.equal(readDownloadMessage(null), null);
});

console.log(`\n${passed}개 통과`);
