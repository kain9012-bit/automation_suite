"""지역별 수치 지도 시각화(tools/map_visualizer) 도구에 넣는 지도 좌표를 다시 만든다.

행정구역이 바뀌면(시·군 통합 등) 새 경계 파일로 이 스크립트를 다시 돌린다.

  1) 경계 파일 받기: vuski/admdongkor 의 최신 시점 행정동 경계
     https://github.com/vuski/admdongkor  → ver<날짜>/HangJeongDong_ver<날짜>.geojson
     (원자료: 통계청 통계지리정보서비스 SGIS, 공공누리 제1유형 / 가공: admdongkor, CC BY 4.0)
  2) python scripts/map_data/build_map_data.py <HangJeongDong_verXXXXXXXX.geojson>

- mapshaper(npx, 개발할 때만 씀)로 행정동을 합쳐 전북 시·군(전주 완산·덕진은 전주시로)과 전국 시·도를 만들고,
  이웃 경계가 어긋나지 않게 단순화한 뒤(전북 8%, 전국 1.5%) 메르카토르로 바꾼다.
- 화면 좌표(가로 800, 소수 첫째 자리)로 옮겨 tools/map_visualizer/web/index.html 의
  <script type="application/json" id="mapData"> 안을 바꿔 넣는다(약 70KB).
- 경계 날짜가 바뀌면 index.html 화면 아래 출처 문구와 tools/map_visualizer/NOTICE.md 의 날짜도 고친다.
- 전북 시·군 코드는 52 로 시작한다(2024 전북특별자치도). 코드가 또 바뀌면 아래 JB_FILTER 를 고친다.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_HTML = ROOT / "tools" / "map_visualizer" / "web" / "index.html"
MAPSHAPER = ["npx", "-y", "mapshaper@0.6.121"]
JB_FILTER = "sido=='52'"
JB_MERGE = "sggc=sgg.slice(0,4)=='5211'?'52110':sgg, sggn=sgg.slice(0,4)=='5211'?'전주시':sggnm"
WIDTH = 800


def mapshaper(args: list[str]) -> None:
    subprocess.run(MAPSHAPER + args, check=True, shell=sys.platform == "win32")


def build(path: Path, code_key: str, name_key: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    feats, xs, ys = [], [], []
    for f in data["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        feats.append((f["properties"][code_key], f["properties"][name_key], polys))
        for poly in polys:
            for ring in poly:
                for x, y in ring:
                    xs.append(x)
                    ys.append(y)
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = WIDTH / (maxx - minx)
    regions = []
    for code, name, polys in feats:
        out_polys = []
        for poly in polys:
            out_rings = []
            for ring in poly:
                flat = []
                for x, y in ring[:-1]:  # 닫는 점은 빼고(그릴 때 닫는다)
                    flat += [round((x - minx) * s, 1), round((maxy - y) * s, 1)]
                out_rings.append(flat)
            out_polys.append(out_rings)
        regions.append({"c": code, "n": name, "p": out_polys})
    return {"w": WIDTH, "h": round((maxy - miny) * s, 1), "r": regions}


def dump(obj: dict) -> str:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return text.replace(".0,", ",").replace(".0]", "]")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python scripts/map_data/build_map_data.py <HangJeongDong_verXXXXXXXX.geojson>")
    src = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        jb = Path(tmp) / "jb.json"
        kr = Path(tmp) / "kr.json"
        mapshaper([str(src), "-filter", JB_FILTER, "-each", JB_MERGE, "-dissolve", "sggc", "copy-fields=sggn",
                   "-simplify", "8%", "keep-shapes", "-proj", "+proj=merc", "+lon_0=127",
                   "-o", str(jb), "format=geojson", "precision=1"])
        mapshaper([str(src), "-dissolve", "sido", "copy-fields=sidonm",
                   "-simplify", "1.5%", "keep-shapes", "-proj", "+proj=merc", "+lon_0=127",
                   "-o", str(kr), "format=geojson", "precision=1"])
        data = dump({"jb": build(jb, "sggc", "sggn"), "kr": build(kr, "sido", "sidonm")})
    if "</" in data:
        raise SystemExit("지도 데이터에 '</' 가 있어 HTML 에 넣을 수 없습니다.")
    html = TOOL_HTML.read_text(encoding="utf-8")
    pattern = re.compile(r'(<script type="application/json" id="mapData">)(.*?)(</script>)', re.S)
    if len(pattern.findall(html)) != 1:
        raise SystemExit("index.html 에서 지도 데이터 자리(id=\"mapData\")를 찾지 못했습니다.")
    html = pattern.sub(lambda m: m.group(1) + data + m.group(3), html)
    TOOL_HTML.write_text(html, encoding="utf-8")
    print(f"지도 데이터를 넣었습니다: {len(data.encode('utf-8')):,} bytes")


if __name__ == "__main__":
    main()
