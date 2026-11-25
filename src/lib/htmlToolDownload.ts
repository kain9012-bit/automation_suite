/**
 * HTML 도구의 파일 내려받기를 앱이 대신 저장한다.
 *
 * HTML 도구는 앱 안의 iframe(srcdoc)에서 돈다. 도구가 엑셀 등을 만들면
 * `<a download href="blob:...">` 를 눌러 내려받는데, 앱 안(WebView2)에서는 이것이
 * 아무 반응 없이 끝나는 일이 있었다(K-에듀파인·교데통 수신그룹). 같은 도구를 '새 창'
 * (기본 브라우저)으로 열면 된다.
 * 그래서 앱 안에서는 내려받기 링크를 가로채 파일 내용을 앱으로 넘기고,
 * 앱이 '다운로드' 폴더에 저장한다(Rust `save_tool_download`).
 *
 * - 도구 코드는 고치지 않는다. iframe 에 넣는 HTML 맨 앞(<head> 바로 뒤)에 짧은 스크립트만 끼운다.
 * - blob 은 `URL.createObjectURL` 을 지켜보다가 주소로 찾는다. fetch(blob:) 는 앱 CSP(connect-src)에 막힌다.
 * - 가로채지 못한 경우(blob·data 가 아닌 주소)는 원래대로 둔다.
 *
 * 그림 복사(1.5.1): 도구가 `window.__jbeduCopyImage(pngBlob)` 를 부르면 앱이 클립보드에 직접 넣는다
 * (Rust `copy_tool_image`). 브라우저 복사로는 투명한 곳이 한글에서 검게 붙기 때문이다.
 * 이 함수는 앱 안에서만 있으므로, 도구는 함수가 없으면(새 창·브라우저) 원래 방식으로 복사한다.
 *
 * 화면 캡처(1.5.3): 화면 캡처 편집기에만 `window.__jbeduCaptureScreen({ mode, delay })`(찍은 PNG Blob, 그만두면 null)와
 * `window.__jbeduPinImage(pngBlob)`(화면에 고정)을 더한다(Rust `capture_screen`·`pin_capture_image`).
 * 다른 도구에는 넣지 않는다(화면을 찍을 수 없다).
 */

export const DOWNLOAD_MESSAGE = "jbedu-tool-download";
export const COPY_IMAGE_MESSAGE = "jbedu-tool-copy-image";
export const COPY_IMAGE_RESULT = "jbedu-tool-copy-image-result";
export const CAPTURE_MESSAGE = "jbedu-tool-capture";
export const CAPTURE_RESULT = "jbedu-tool-capture-result";
export const PIN_MESSAGE = "jbedu-tool-pin";
export const PIN_RESULT = "jbedu-tool-pin-result";
/** 화면 캡처를 쓸 수 있는 도구 */
export const CAPTURE_TOOL_ID = "screen_capture";

const BRIDGE = `(function () {
  if (window.__jbeduDownloadBridge) return;
  window.__jbeduDownloadBridge = true;
  var blobs = new Map();
  var create = URL.createObjectURL.bind(URL);
  var revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = function (obj) {
    var url = create(obj);
    if (obj instanceof Blob) blobs.set(url, obj);
    return url;
  };
  URL.revokeObjectURL = function (url) {
    blobs.delete(url);
    return revoke(url);
  };
  function fromDataUrl(href) {
    var comma = href.indexOf(",");
    if (comma < 0) return null;
    var meta = href.slice(5, comma);
    var body = href.slice(comma + 1);
    var type = meta.split(";")[0] || "application/octet-stream";
    if (/;base64/i.test(meta)) {
      var raw = atob(body);
      var bytes = new Uint8Array(raw.length);
      for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      return new Blob([bytes], { type: type });
    }
    return new Blob([decodeURIComponent(body)], { type: type });
  }
  function take(a) {
    if (!a || !a.hasAttribute || !a.hasAttribute("download")) return false;
    var href = a.href || "";
    var blob = /^blob:/i.test(href) ? blobs.get(href) : /^data:/i.test(href) ? fromDataUrl(href) : null;
    if (!blob) return false;
    var name = a.getAttribute("download") || "";
    blob.arrayBuffer().then(function (buffer) {
      window.parent.postMessage({ type: "${DOWNLOAD_MESSAGE}", name: name, bytes: buffer }, "*", [buffer]);
    });
    return true;
  }
  var click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (take(this)) return;
    return click.call(this);
  };
  document.addEventListener("click", function (event) {
    var target = event.target;
    var a = target && target.closest ? target.closest("a[download]") : null;
    if (a && take(a)) event.preventDefault();
  }, true);
  var copies = {};
  var copySeq = 0;
  window.__jbeduCopyImage = function (blob) {
    return blob.arrayBuffer().then(function (buffer) {
      return new Promise(function (resolve, reject) {
        var id = ++copySeq;
        copies[id] = { resolve: resolve, reject: reject };
        window.parent.postMessage({ type: "${COPY_IMAGE_MESSAGE}", id: id, bytes: buffer }, "*", [buffer]);
        setTimeout(function () {
          if (!copies[id]) return;
          delete copies[id];
          reject(new Error("앱이 응답하지 않습니다."));
        }, 10000);
      });
    });
  };
  window.addEventListener("message", function (event) {
    var data = event.data;
    if (event.source !== window.parent || !data || data.type !== "${COPY_IMAGE_RESULT}" || !copies[data.id]) return;
    var waiting = copies[data.id];
    delete copies[data.id];
    if (data.ok) waiting.resolve();
    else waiting.reject(new Error(data.error || "그림을 복사하지 못했습니다."));
  });
})();`;

const CAPTURE_BRIDGE = `(function () {
  if (window.__jbeduCaptureScreen) return;
  var waiting = {};
  var seq = 0;
  function ask(message, transfer) {
    return new Promise(function (resolve, reject) {
      var id = ++seq;
      waiting[id] = { resolve: resolve, reject: reject };
      message.id = id;
      window.parent.postMessage(message, "*", transfer || []);
    });
  }
  window.__jbeduCaptureScreen = function (options) {
    options = options || {};
    return ask({ type: "${CAPTURE_MESSAGE}", mode: String(options.mode || "region"), delay: Number(options.delay) || 0 });
  };
  window.__jbeduPinImage = function (blob) {
    return blob.arrayBuffer().then(function (buffer) {
      return ask({ type: "${PIN_MESSAGE}", bytes: buffer }, [buffer]);
    });
  };
  window.addEventListener("message", function (event) {
    var data = event.data;
    if (event.source !== window.parent || !data || !waiting[data.id]) return;
    if (data.type !== "${CAPTURE_RESULT}" && data.type !== "${PIN_RESULT}") return;
    var w = waiting[data.id];
    delete waiting[data.id];
    if (!data.ok) { w.reject(new Error(data.error || "화면을 찍지 못했습니다.")); return; }
    if (data.type === "${PIN_RESULT}") { w.resolve(); return; }
    w.resolve(data.bytes && data.bytes.byteLength ? new Blob([data.bytes], { type: "image/png" }) : null);
  });
})();`;

/** 도구 HTML 의 <head> 바로 뒤(없으면 <html> 뒤, 그것도 없으면 맨 앞)에 내려받기 가로채기를 끼운다.
 *  <!doctype> 앞에 넣으면 문서가 호환 모드로 바뀌므로 그 뒤에 넣는다.
 *  allowCapture: 화면 캡처 편집기에만 화면 찍기·화면에 고정 연결을 더한다. */
export function injectDownloadBridge(html: string, allowCapture = false): string {
  const script = `<script>${BRIDGE}${allowCapture ? CAPTURE_BRIDGE : ""}</script>`;
  for (const pattern of [/<head(\s[^>]*)?>/i, /<html(\s[^>]*)?>/i, /<!doctype[^>]*>/i]) {
    const match = pattern.exec(html);
    if (match) {
      const at = match.index + match[0].length;
      return html.slice(0, at) + script + html.slice(at);
    }
  }
  return script + html;
}

/** 내려받기 메시지인지와 그 내용. */
export function readDownloadMessage(data: unknown): { name: string; bytes: ArrayBuffer } | null {
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; name?: unknown; bytes?: unknown };
  if (message.type !== DOWNLOAD_MESSAGE || !(message.bytes instanceof ArrayBuffer)) return null;
  return { name: typeof message.name === "string" ? message.name : "", bytes: message.bytes };
}

/** 그림 복사 요청인지와 그 내용(PNG 바이트). */
export function readCopyImageMessage(data: unknown): { id: number; bytes: ArrayBuffer } | null {
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; id?: unknown; bytes?: unknown };
  if (message.type !== COPY_IMAGE_MESSAGE || typeof message.id !== "number" || !(message.bytes instanceof ArrayBuffer)) return null;
  return { id: message.id, bytes: message.bytes };
}

/** 화면 찍기 요청인지와 그 내용. */
export function readCaptureMessage(data: unknown): { id: number; mode: string; delay: number } | null {
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; id?: unknown; mode?: unknown; delay?: unknown };
  if (message.type !== CAPTURE_MESSAGE || typeof message.id !== "number") return null;
  return { id: message.id, mode: typeof message.mode === "string" ? message.mode : "region", delay: typeof message.delay === "number" ? message.delay : 0 };
}

/** 화면에 고정 요청인지와 그 내용(PNG 바이트). */
export function readPinMessage(data: unknown): { id: number; bytes: ArrayBuffer } | null {
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; id?: unknown; bytes?: unknown };
  if (message.type !== PIN_MESSAGE || typeof message.id !== "number" || !(message.bytes instanceof ArrayBuffer)) return null;
  return { id: message.id, bytes: message.bytes };
}
