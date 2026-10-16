// 사용가이드: JB업무ON 처음 사용 안내(TutorialOverlay)와 같은 방식.
// 단계마다 그 영역만 밝게 두고 나머지는 어둡게 한 뒤 옆에 설명 카드를 띄운다. 영역은 data-tour 표시로 찾는다.
(function () {
  'use strict';
  var STEPS = /*STEPS*/[];
  var ICON = {
    left: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>', right: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    check: '<path d="M20 6 9 17l-5-5"/>', x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'
  };
  function icon(name) { return '<svg viewBox="0 0 24 24" aria-hidden="true">' + ICON[name] + '</svg>'; }
  var tour = null;
  function target() { return document.querySelector('[data-tour="' + STEPS[tour.i][0] + '"]'); }
  function visible(node) { if (!node) return false; var b = node.getBoundingClientRect(); return b.width > 0 && b.height > 0; }
  function open() {
    if (tour || !STEPS.length) return;
    var layer = document.createElement('div'), spot = document.createElement('div'), card = document.createElement('section');
    layer.className = 'jbt-layer'; spot.className = 'jbt-spot'; card.className = 'jbt-card';
    layer.setAttribute('role', 'dialog'); layer.setAttribute('aria-modal', 'true'); layer.setAttribute('aria-label', '사용가이드');
    card.innerHTML = '<div class="jbt-progress"><span></span><button type="button" aria-label="안내 닫기">' + icon('x') + '</button></div><strong class="jbt-title"></strong><p class="jbt-body"></p>'
      + '<div class="jbt-actions"><button type="button" class="jbt-btn jbt-prev">' + icon('left') + '이전</button><button type="button" class="jbt-btn jbt-next"></button></div>';
    layer.appendChild(spot); layer.appendChild(card);
    document.body.appendChild(layer);
    tour = { layer: layer, spot: spot, card: card, i: 0 };
    card.querySelector('.jbt-progress button').addEventListener('click', close);
    card.querySelector('.jbt-prev').addEventListener('click', function () { if (tour.i > 0) show(tour.i - 1); });
    card.querySelector('.jbt-next').addEventListener('click', function () { if (tour.i < STEPS.length - 1) show(tour.i + 1); else close(); });
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    document.addEventListener('keydown', onKey, true);
    show(0);
    card.querySelector('.jbt-next').focus();
  }
  function close() {
    if (!tour) return;
    window.removeEventListener('resize', place);
    window.removeEventListener('scroll', place, true);
    document.removeEventListener('keydown', onKey, true);
    tour.layer.parentNode.removeChild(tour.layer); tour = null;
    var b = document.getElementById('usageGuideBtn'); if (b) b.focus();
  }
  function onKey(ev) { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); close(); } }
  function show(i) {
    tour.i = i;
    var step = STEPS[i], last = i === STEPS.length - 1, card = tour.card;
    card.querySelector('.jbt-progress span').textContent = (i + 1) + ' / ' + STEPS.length;
    card.querySelector('.jbt-title').textContent = step[1];
    card.querySelector('.jbt-body').textContent = step[2];
    card.querySelector('.jbt-prev').disabled = i === 0;
    card.querySelector('.jbt-next').innerHTML = last ? icon('check') + '마치기' : '다음' + icon('right');
    var t = target();
    if (visible(t)) scrollTo(t);
    place();
  }
  // 영역이 화면에 다 들어오면 가운데로, 화면보다 크면 위쪽부터 보이게 옮긴다.
  // scrollIntoView 는 JB업무ON 화면(도구를 담은 바깥 창)까지 움직일 수 있어, 이 문서 안의 스크롤만 직접 옮긴다.
  function scrollTo(t) {
    var r = t.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
    var dy = r.height + 260 < vh ? r.top + r.height / 2 - vh / 2 : r.top - 16;
    for (var p = t.parentElement; p && p !== document.body && p !== document.documentElement && Math.abs(dy) >= 1; p = p.parentElement) {
      var st = window.getComputedStyle(p);
      if (/(auto|scroll)/.test(st.overflowY) && p.scrollHeight > p.clientHeight + 1) { var before = p.scrollTop; p.scrollTop += dy; dy -= p.scrollTop - before; }
    }
    var dx = r.left < 8 ? r.left - 16 : (r.right > vw - 8 && r.width < vw - 32 ? r.right - vw + 16 : 0);
    if (Math.abs(dy) >= 1 || dx) window.scrollBy(dx, Math.abs(dy) >= 1 ? dy : 0);
  }
  function place() {
    if (!tour) return;
    var t = target(), rect = null;
    if (visible(t)) {
      var b = t.getBoundingClientRect();
      var left = Math.max(8, b.left), top = Math.max(8, b.top), right = Math.min(window.innerWidth - 8, b.right), bottom = Math.min(window.innerHeight - 8, b.bottom);
      if (right - left >= 4 && bottom - top >= 4) rect = { left: left, top: top, width: right - left, height: bottom - top, bottom: bottom };
    }
    tour.layer.classList.toggle('is-plain', !rect);
    tour.spot.style.display = rect ? '' : 'none';
    if (rect) { tour.spot.style.top = (rect.top - 6) + 'px'; tour.spot.style.left = (rect.left - 6) + 'px'; tour.spot.style.width = (rect.width + 12) + 'px'; tour.spot.style.height = (rect.height + 12) + 'px'; }
    // 카드 자리: 영역 아래 → 위 → 오른쪽 → 왼쪽 중 영역을 가리지 않는 첫 자리.
    // 영역이 커서 그런 자리가 없으면 화면 안에서 영역을 가장 덜 가리는 자리(네 귀퉁이 포함)에 둔다.
    var card = tour.card, vw = window.innerWidth, vh = window.innerHeight, M = 14, G = 14;
    var cw = Math.min(380, vw - 2 * M);
    card.style.width = cw + 'px';
    var ch = card.offsetHeight;
    var clampL = function (l) { return Math.max(M, Math.min(vw - cw - M, l)); };
    var clampT = function (t) { return Math.max(M, Math.min(vh - ch - M, t)); };
    var pos;
    if (rect) {
      var R = { l: rect.left - 6, t: rect.top - 6, r: rect.left + rect.width + 6, b: rect.top + rect.height + 6 };
      var overlap = function (p) { var w = Math.min(p.l + cw, R.r) - Math.max(p.l, R.l), h = Math.min(p.t + ch, R.b) - Math.max(p.t, R.t); return w > 0 && h > 0 ? w * h : 0; };
      var fits = function (p) { return p.t >= M && p.t + ch <= vh - M && p.l >= M && p.l + cw <= vw - M; };
      var sides = [{ t: R.b + G - 6, l: clampL(rect.left) }, { t: R.t - G + 6 - ch, l: clampL(rect.left) }, { t: clampT(rect.top), l: R.r + G - 6 }, { t: clampT(rect.top), l: R.l - G + 6 - cw }];
      for (var k = 0; k < sides.length && !pos; k++) if (fits(sides[k]) && !overlap(sides[k])) pos = sides[k];
      if (!pos) {
        var all = sides.map(function (p) { return { t: clampT(p.t), l: clampL(p.l) }; })
          .concat([{ t: vh - ch - M, l: M }, { t: vh - ch - M, l: vw - cw - M }, { t: M, l: M }, { t: M, l: vw - cw - M }]);
        all.forEach(function (p) { p.o = overlap(p); if (!pos || p.o < pos.o) pos = p; });
      }
    } else pos = { t: (vh - ch) / 2, l: (vw - cw) / 2 };
    card.style.top = Math.max(M, pos.t) + 'px'; card.style.left = Math.max(M, pos.l) + 'px';
  }
  var btn = document.getElementById('usageGuideBtn');
  if (btn) btn.addEventListener('click', open);
})();
