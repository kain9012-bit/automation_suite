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
 */

export const DOWNLOAD_MESSAGE = "jbedu-tool-download";

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
})();`;

/** 도구 HTML 의 <head> 바로 뒤(없으면 <html> 뒤, 그것도 없으면 맨 앞)에 내려받기 가로채기를 끼운다.
 *  <!doctype> 앞에 넣으면 문서가 호환 모드로 바뀌므로 그 뒤에 넣는다. */
export function injectDownloadBridge(html: string): string {
  const script = `<script>${BRIDGE}</script>`;
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
