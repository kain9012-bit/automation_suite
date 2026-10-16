"""HTML 도구에 사용가이드 넣기(JB업무ON 처음 사용 안내와 같은 방식).

  python scripts/html_guide/inject.py <도구ID> [<도구ID> ...]   # tools/<도구ID>/web/index.html 에 steps/<도구ID>.json 을 넣는다
  python scripts/html_guide/inject.py --all                     # steps 폴더의 모든 도구

- 오른쪽 위 [사용가이드] 버튼은 <body> 바로 뒤, 스타일(jb-tour-style)은 </head> 앞, 스크립트(jb-tour)는 </body> 앞에 넣는다.
  이미 있으면 바꿔 넣으므로 엔진(engine.js·engine.css)을 고친 뒤 --all 로 다시 돌리면 모든 도구가 같이 바뀐다.
- steps/<도구ID>.json: [["data-tour 이름", "제목", "설명"], ...] — 화면 위에서 아래 순서.
  짚을 영역에는 도구 HTML 에 data-tour="이름" 을 붙여 둔다(처음 열었을 때 보이는 영역만).
- 줄바꿈은 원래 파일대로(CRLF 파일은 CRLF) 둔다.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def inject(tool_id: str) -> None:
    path = ROOT / "tools" / tool_id / "web" / "index.html"
    steps = json.loads((HERE / "steps" / f"{tool_id}.json").read_text(encoding="utf-8"))
    with open(path, encoding="utf-8", newline="") as f:
        h = f.read()
    nl = "\r\n" if "\r\n" in h else "\n"
    h = h.replace("\r\n", "\n")
    for key, _title, _body in steps:
        count = h.count(f'data-tour="{key}"')
        assert count == 1, f"{tool_id}: data-tour=\"{key}\" 표시가 {count}개입니다(하나여야 함)"
    css = (HERE / "engine.css").read_text(encoding="utf-8").rstrip("\n")
    js = (HERE / "engine.js").read_text(encoding="utf-8").rstrip("\n")
    js = js.replace("/*STEPS*/[]", "[\n" + ",\n".join("    " + json.dumps(s, ensure_ascii=False) for s in steps) + "\n  ]")
    h = re.sub(r'\n?<style id="jb-tour-style">.*?</style>', "", h, flags=re.S)
    h = re.sub(r'\n?<script id="jb-tour">.*?</script>', "", h, flags=re.S)
    h = re.sub(r'\n?<div class="jbt-top">.*?</div>', "", h, flags=re.S)
    assert "usageGuideBtn" not in h, f"{tool_id}: 예전 사용가이드 버튼(usageGuideBtn)을 먼저 지워야 합니다"
    assert h.count("</head>") == 1 and h.count("</body>") == 1, f"{tool_id}: </head>·</body> 가 하나씩이어야 합니다"
    h = h.replace("</head>", '<style id="jb-tour-style">\n' + css + "\n</style>\n</head>")
    h = h.replace("</body>", '<script id="jb-tour">\n' + js + "\n</script>\n</body>")
    m = re.search(r"<body[^>]*>", h)
    h = h[: m.end()] + '\n<div class="jbt-top"><button type="button" id="usageGuideBtn">사용가이드</button></div>' + h[m.end():]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(h.replace("\n", nl))
    print(f"ok {tool_id} ({len(steps)}단계)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    ids = sorted(p.stem for p in (HERE / "steps").glob("*.json")) if args == ["--all"] else args
    for tool_id in ids:
        inject(tool_id)
