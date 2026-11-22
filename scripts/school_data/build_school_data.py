"""학교 위치 지도 시각화(tools/school_visualizer) 도구에 넣는 학교·경계 데이터를 다시 만든다.

학교 현황이 바뀌면(새 교육행정자료) 이 스크립트를 다시 돌린다.

  python scripts/school_data/build_school_data.py <교육행정자료_YYYY-MM-DD.xls> <HangJeongDong_verXXXXXXXX.geojson>

- 학교 목록·학생·학급·교원: 교육행정자료(.xls, 첫 시트). 사립유치원은 뺀다. .xls 를 읽으려면 xlrd 가 있어야 한다(개발할 때만: pip install xlrd).
  · 교육행정자료의 주소·행정동은 틀린 것이 많아 쓰지 않는다.
- 학교 위치·주소·행정동: 같은 폴더의 school_locations.json
  · 초·중·고: 전국초중등학교위치표준데이터(공공데이터포털)
  · 유치원·특수·각종: 주소정보누리집에서 확인한 도로명주소·건물 위치, 병설유치원은 본교 위치
  · 새로 생긴 학교는 school_locations.json 에 넣는다. 없으면 지도에서 빠지고 끝에 목록을 보여 준다.
- 경계: vuski/admdongkor 행정동 경계(원자료 통계청 SGIS, 공공누리 제1유형 / 가공 admdongkor, CC BY 4.0)
  · mapshaper(npx, 개발할 때만)로 전북 행정동을 단순화(8%)하고, 그것을 합쳐 시·군을 만든다(이웃 경계가 어긋나지 않게).
  · 메르카토르(중심 경도 127)로 바꿔 화면 좌표(가로 1000, 소수 첫째 자리)로 옮긴다. 학교 점도 같은 식으로 옮긴다.
- 결과는 tools/school_visualizer/web/index.html 의 <script type="application/json" id="schoolData"> 안을 바꿔 넣는다.
- 기준일은 교육행정자료 파일 이름의 YYYY-MM-DD 를 쓴다. 경계 날짜가 바뀌면 BOUNDARY_DATE 를 고친다.
"""
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TOOL_HTML = ROOT / "tools" / "school_visualizer" / "web" / "index.html"
LOCATIONS = HERE / "school_locations.json"
MAPSHAPER = ["npx", "-y", "mapshaper@0.6.121"]
BOUNDARY_DATE = "2026. 7. 1."
WIDTH = 1000
LON0 = 127.0

# 교육행정자료의 줄인·잘못 바뀐 학교명 → 정식 학교명
NAME_ALIAS = {
    "동국대학교사범대부속금산중학교": "동국대학교사범대학부속금산중학교",
    "동국대사범대학부속금산고등학교": "동국대학교사범대학부속금산고등학교",
    "전주대사범대학부설고등학교": "전주대학교사범대학부설고등학교",
    "전북대사범대학부설고등학교": "전북대학교사범대학부설고등학교",
    "전주교대군산부설초등학교": "전주교육대학교군산부설초등학교",
    "전주교대전주부설초등학교": "전주교육대학교전주부설초등학교",
    "원광대사대부속유치원": "원광대학교사범대학부속유치원",
    "호원대부속유치원": "호원대학교부속유치원",
    "우석대부설유치원": "우석대학교부설유치원",
    "번암초동화분교장초등학교": "번암초등학교동화분교장",
    "봉동초양화분교장초등학교": "봉동초등학교양화분교장",
    "번암초동화분교병설유치원": "번암초등학교동화분교병설유치원",
    "고등학교산고등학교": "고산고등학교",  # 자료에서 '고산' 이 '고등학교산' 으로 바뀌어 있음
}
# 붙여 넣기에서 옛 이름도 알아보게(옛 이름 → 지금 이름)
OLD_NAMES = [
    ["줄포자동차공업고등학교", "전북자동차고등학교"],
    ["남원서진여자고등학교", "남원서진고등학교"],
    ["전주상업정보고등학교", "전주여자상업고등학교"],
]
INNER = (("초등학교병설유치원", "초병설유"), ("대학교사범대학", "대사대"), ("교육대학교", "교대"), ("대학교", "대"), ("초등학교", "초"))
SUFFIX = (("병설유치원", "병설유"), ("여자고등학교", "여고"), ("여자중학교", "여중"), ("고등학교", "고"), ("중학교", "중"),
          ("초등학교", "초"), ("유치원", "유"))


def mapshaper(args: list[str]) -> None:
    subprocess.run(MAPSHAPER + args, check=True, shell=sys.platform == "win32")


def merc(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 타원체 메르카토르(미터)."""
    a, e = 6378137.0, 0.0818191908426
    phi = math.radians(lat)
    x = a * math.radians(lon - LON0)
    s = e * math.sin(phi)
    y = a * math.log(math.tan(math.pi / 4 + phi / 2) * ((1 - s) / (1 + s)) ** (e / 2))
    return x, y


def short_name(full: str) -> str:
    s = full
    for a, b in INNER:
        s = s.replace(a, b)
    for a, b in SUFFIX:
        if s.endswith(a):
            return s[: -len(a)] + b
    return s


def read_xls(path: Path) -> list[dict]:
    import xlrd  # 개발할 때만 쓰는 의존성

    sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
    head = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    need = ["지역명", "설립구분", "학교급명", "학교명", "전화번호", "교원인원수", "학급수", "학생인원수"]
    miss = [h for h in need if h not in head]
    if miss:
        raise SystemExit(f"교육행정자료에 없는 열: {', '.join(miss)}")
    return [{head[c]: str(sh.cell_value(r, c)).strip() for c in range(sh.ncols)} for r in range(1, sh.nrows)]


def num(v: str) -> int:
    v = v.replace(",", "").strip()
    return int(float(v)) if v else 0


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("사용법: python scripts/school_data/build_school_data.py <교육행정자료_YYYY-MM-DD.xls> <HangJeongDong_verXXXXXXXX.geojson>")
    xls, geo = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", xls.name)
    asof = f"{int(m.group(1))}. {int(m.group(2))}. {int(m.group(3))}." if m else ""

    with tempfile.TemporaryDirectory() as tmp:
        dong, sgg = Path(tmp) / "dong.json", Path(tmp) / "sgg.json"
        mapshaper([str(geo), "-filter", "sido=='52'",
                   "-each", "sggc=sgg.slice(0,4)=='5211'?'52110':sgg, sggn=sgg.slice(0,4)=='5211'?'전주시':sggnm, dn=adm_nm.split(' ').pop()",
                   "-simplify", "8%", "keep-shapes", "-o", str(dong), "format=geojson", "precision=0.00001"])
        mapshaper([str(dong), "-dissolve", "sggc", "copy-fields=sggn", "-o", str(sgg), "format=geojson", "precision=0.00001"])
        dong_f = json.loads(dong.read_text(encoding="utf-8"))["features"]
        sgg_f = json.loads(sgg.read_text(encoding="utf-8"))["features"]

    def polys(g):
        return g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]

    xs, ys = [], []
    for f in sgg_f:
        for poly in polys(f["geometry"]):
            for ring in poly:
                for lon, lat in ring:
                    x, y = merc(lon, lat)
                    xs.append(x)
                    ys.append(y)
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = WIDTH / (maxx - minx)

    def pt(lon, lat):
        x, y = merc(lon, lat)
        return round((x - minx) * s, 1), round((maxy - y) * s, 1)

    def flat_polys(g):
        out = []
        for poly in polys(g):
            rings = []
            for ring in poly:
                flat = []
                for lon, lat in ring[:-1]:  # 닫는 점은 빼고(그릴 때 닫는다)
                    flat += pt(lon, lat)
                rings.append(flat)
            out.append(rings)
        return out

    sgg_names = sorted({f["properties"]["sggn"] for f in sgg_f})
    sgg_out = [{"n": f["properties"]["sggn"], "p": flat_polys(f["geometry"])} for f in sorted(sgg_f, key=lambda f: f["properties"]["sggc"])]
    dong_out = [{"s": f["properties"]["sggn"], "n": f["properties"]["dn"], "p": flat_polys(f["geometry"])} for f in dong_f]

    locs = json.loads(LOCATIONS.read_text(encoding="utf-8"))["학교"]
    by_region = {(l["시군"], l["학교명"]): l for l in locs}
    by_name: dict[str, list] = {}
    for l in locs:
        by_name.setdefault(l["학교명"], []).append(l)

    schools, no_loc, moved, skipped = [], [], [], 0
    for r in read_xls(xls):
        if r["학교급명"] == "유치원" and r["설립구분"] == "사립":
            skipped += 1  # 사립유치원은 넣지 않는다(사용자 요청, 1.5.1)
            continue
        region = next((n for n in sgg_names if n.startswith(r["지역명"])), None)
        if not region:
            raise SystemExit(f"시군을 알 수 없는 지역명: {r['지역명']} ({r['학교명']})")
        raw = r["학교명"]
        status = "".join(re.findall(r"\(([^)]*)\)", raw))
        name = re.sub(r"\(.*?\)", "", raw).strip()
        full = NAME_ALIAS.get(name, name.replace("초병설유치원", "초등학교병설유치원"))
        loc = by_region.get((region, full))
        if not loc and len(by_name.get(full, [])) == 1:
            loc = by_name[full][0]  # 자료의 지역명이 주소와 다른 곳(주소의 시군을 따른다)
            moved.append(f"{full}: {region} → {loc['시군']}")
        if not loc:
            no_loc.append(f"{region} {raw}")
            continue
        level = r["학교급명"] or "각종학교"
        kind = ("병설" if "병설" in full else "단설") if level == "유치원" else ""  # 유치원 표시 고르기(병설·단설)에 씀
        x, y = pt(loc["경도"], loc["위도"])
        schools.append([short_name(full), full, loc["시군"], level, r["설립구분"], x, y, num(r["학생인원수"]), num(r["학급수"]),
                        num(r["교원인원수"]), loc["주소"], r["전화번호"], status, loc["행정동"], kind])

    source = (f"학교 현황: 교육행정자료({asof} 기준) / 위치·주소·행정동: 전국초중등학교위치표준데이터, 주소정보누리집"
              f" / 경계: 통계청 SGIS({BOUNDARY_DATE}), vuski/admdongkor 가공(CC BY 4.0)")
    if no_loc:
        source += " / 위치 없어 뺀 학교: " + ", ".join(n.split(" ", 1)[1] for n in no_loc)
    data = {
        "w": WIDTH, "h": round((maxy - miny) * s, 1), "source": source,
        "sgg": sgg_out, "dong": dong_out,
        "f": ["약칭", "학교명", "시군", "학교급", "설립", "x", "y", "학생", "학급", "교원", "주소", "전화", "상태", "행정동", "유치원 구분"],
        "d": schools, "alias": OLD_NAMES,
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(".0,", ",").replace(".0]", "]")
    if "</" in text:
        raise SystemExit("데이터에 '</' 가 있어 HTML 에 넣을 수 없습니다.")
    html = TOOL_HTML.read_text(encoding="utf-8")
    pattern = re.compile(r'(<script type="application/json" id="schoolData">)(.*?)(</script>)', re.S)
    if len(pattern.findall(html)) != 1:
        raise SystemExit('index.html 에서 데이터 자리(id="schoolData")를 찾지 못했습니다.')
    html = pattern.sub(lambda mm: mm.group(1) + text + mm.group(3), html)
    TOOL_HTML.write_text(html, encoding="utf-8")
    print(f"학교 {len(schools):,}곳(사립유치원 {skipped}곳 뺌), 데이터 {len(text.encode('utf-8')):,} bytes")
    for line in moved:
        print("  시군을 주소대로:", line)
    if no_loc:
        print(f"위치가 없어 지도에서 뺀 학교 {len(no_loc)}곳(school_locations.json 에 넣으세요):")
        for n in no_loc:
            print("  -", n)


if __name__ == "__main__":
    main()
