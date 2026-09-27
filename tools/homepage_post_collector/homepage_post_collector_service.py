"""게시판 수집 엔진.

게시판 목록 페이지를 읽어 표(게시글 목록)를 찾고, 각 행의 상세 페이지에서
본문과 첨부파일 정보를 모아 엑셀로 저장한다.

설계 원칙 — 컬럼 이름에 의존하지 않는다
    게시판마다 제목 컬럼 이름이 '제목', '도구명', '자료명', '데이터명', '학교명'
    등으로 제각각이라, 헤더 문자열로 게시판을 찾으면 새 게시판이 생길 때마다
    깨진다. 그래서 '행 안에 게시글 상세 링크가 들어 있는 표'를 게시판으로 보고,
    '상세 링크가 들어 있는 칸'을 제목 칸으로 본다.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Comment
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import get_column_letter
import datetime


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BoardCollector/2.0"

# 게시글 상세 페이지 링크 패턴 (컬럼명과 무관하게 게시판을 식별하는 기준)
#
# 지원 솔루션 계열:
#   A. 전북교육청 표준(eGov RFC3): www.jbe.go.kr, news.jbe.go.kr, www.jbedu.kr …
#      → /board/view.jbe, /board/view.jbedu, dataSid=
#   B. 학교홈페이지형: office.jbedu.kr/{기관}, school.jbedu.kr/{기관}
#      → /{메뉴코드}/view/6855899.do (숫자 id)
#   C. 도서관형: lib.jbe.go.kr/{기관}
#      → board/view.do?…&board_idx=…  (목록의 a는 href가 비고 keyvalue 속성만 있음)
POST_LINK_PATTERNS = (
    "/board/view.",      # A 계열 (view.jbe / view.jbedu / view.do 모두 걸림)
    "/board/read.",
    "boardid=",          # 쿼리스트링에 boardId 가 있는 경우(소문자 비교)
    "datasid=",
    "board_idx=",        # C 계열 상세 링크
)
POST_LINK_REGEXES = (
    # B 계열: /MABAGAB/view/6855899.do  (신형은 .do 없이 /MABADAJ/view/6041360)
    re.compile(r"/view/\d+(?:\.do)?(?:[?#]|$)"),
)

# 목록 페이지 번호를 담는 파라미터 후보. 주소에 이미 들어 있는 것을 우선 사용한다.
PAGE_PARAM_CANDIDATES = ("startPage", "pageIndex", "pageNo", "currPage", "cpage",
                         "viewPage", "s_idx", "page")
DEFAULT_PAGE_PARAM = "startPage"

# B 계열 메뉴코드 경로: /jbetc/MABAGAB/list.do 또는 신형 /woori/MABADAJ/ 처럼
# 대문자 메뉴코드가 들어간다.
_MENU_CODE_PATH_RE = re.compile(r"/[A-Z][A-Z0-9]{3,}/(?:(?:index|list)\.do)?$")

ATTACH_EXTS = (
    ".hwp", ".hwpx", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".pdf", ".zip", ".hml", ".jpg", ".jpeg", ".png", ".gif",
)

# 엑셀에 공통으로 덧붙이는 열
EXTRA_HEADERS = ["게시판URL", "상세URL", "본문내용", "첨부파일개수", "첨부파일목록"]


def make_timestamp() -> str:
    """결과 파일과 첨부 폴더 이름에 붙일 시각. 같은 실행에서는 같은 값을 쓴다."""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class Cancelled(Exception):
    """사용자가 '중지'를 눌렀을 때."""


def http_get(session, url, **kw):
    """GET 요청. 관공서 사이트의 인증서 문제로 실패하면 검증을 완화해 한 번 더 시도."""
    try:
        return session.get(url, **kw)
    except requests.exceptions.SSLError:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        return session.get(url, verify=False, **kw)


@dataclass
class CrawlResult:
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    headers: list = field(default_factory=list)
    cancelled: bool = False
    # 목록 페이지를 연 수와, 열지 못한 페이지의 이유. 하나도 못 열었으면 수집이 실패한 것이다.
    pages_opened: int = 0
    page_failures: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def attach_count(self) -> int:
        return sum(int(r.get("_첨부파일개수") or 0) for r in self.rows)


# ==========================================================
# URL / 페이지
# ==========================================================

def detect_page_param(url: str) -> str:
    """주소에 이미 들어 있는 페이지 파라미터 이름을 찾는다.

    없으면 주소 모양(솔루션 계열)으로 정한다.
      · lib.jbe.go.kr 계열(board/index.do + menu_idx)  → viewPage
      · 학교홈페이지형(/{대문자 메뉴코드}/index|list.do) → s_idx
      · 그 외(전북교육청 표준)                          → startPage
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    lower = {k.lower(): k for k in qs}
    for cand in PAGE_PARAM_CANDIDATES:
        if cand.lower() in lower:
            return lower[cand.lower()]

    path = parsed.path
    if "/board/index.do" in path and "menu_idx" in lower:
        return "viewPage"
    if _MENU_CODE_PATH_RE.search(path):
        return "s_idx"
    return DEFAULT_PAGE_PARAM


def build_page_url(base_url: str, page: int) -> str:
    """게시판 목록 주소에 페이지 번호를 넣은 주소를 만든다."""
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)
    param = detect_page_param(base_url)
    if param == DEFAULT_PAGE_PARAM:
        qs["paging"] = ["ok"]
    qs[param] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))


_PAGE_HREF_RE = re.compile(
    r"(?:startPage|pageIndex|pageNo|currPage|cpage|viewPage|s_idx)=(\d+)", re.I)


def detect_last_page(soup: BeautifulSoup, current: int = 1) -> int:
    """페이지 이동 영역에서 마지막 페이지 번호를 추정한다."""
    best = current
    for a in soup.find_all("a"):
        href = a.get("href", "")
        # ① href의 페이지 파라미터 값 (startPage=4, s_idx=8 …)
        for m in _PAGE_HREF_RE.finditer(href):
            try:
                best = max(best, int(m.group(1)))
            except ValueError:
                pass
        # ② 숫자 텍스트 링크 (목록/페이지 이동 링크에 한정)
        text = a.get_text(strip=True)
        if text.isdigit() and ("list." in href.lower() or "page" in href.lower()):
            try:
                best = max(best, int(text))
            except ValueError:
                pass
        # ③ lib 계열: <a class="paginate_button" keyvalue="15">맨끝</a>
        kv = a.get("keyvalue")
        classes = " ".join(a.get("class") or [])
        if kv and str(kv).isdigit() and "paginate" in classes:
            best = max(best, int(kv))
    # '총 44건 (1/4 페이지)' 형태에서도 읽어 본다.
    m = re.search(r"\(\s*\d+\s*/\s*(\d+)\s*페이지\s*\)", soup.get_text(" ", strip=True))
    if m:
        try:
            best = max(best, int(m.group(1)))
        except ValueError:
            pass
    return best


# ==========================================================
# 표(게시판) 찾기
# ==========================================================

def is_attachment_href(href: str) -> bool:
    """첨부파일 URL로 보이는 href인지 판단"""
    if not href:
        return False
    h = href.lower()
    if any(h.endswith(ext) for ext in ATTACH_EXTS):
        return True
    return "download" in h or "filedown" in h


def is_post_link(href: str) -> bool:
    """행 안의 a 태그가 '게시글 상세'로 가는 링크인지 판정"""
    if not href:
        return False
    h = href.strip().lower()
    if h.startswith("#") or h.startswith("javascript:"):
        return False
    if is_attachment_href(href):
        return False
    if any(p in h for p in POST_LINK_PATTERNS):
        return True
    return any(rx.search(h) for rx in POST_LINK_REGEXES)


def resolve_post_link(a, page_url: str) -> str:
    """a 태그에서 상세 페이지 URL을 얻는다. 실패 시 빈 문자열.

    · 보통: href가 상세 링크 패턴이면 절대주소로 변환.
    · lib.jbe.go.kr 계열: href가 비어 있고 keyvalue="글번호"만 있으므로,
      목록 주소(board/index.do?menu_idx=..&manage_idx=..)를 바탕으로
      board/view.do?…&board_idx=글번호 를 만들어 준다.
    """
    href = (a.get("href") or "").strip()
    if is_post_link(href):
        return urljoin(page_url, href)

    key = a.get("keyvalue")
    if key and str(key).isdigit():
        parsed = urlparse(page_url)
        if "/board/index.do" in parsed.path:
            qs = parse_qs(parsed.query)
            if "menu_idx" in {k.lower() for k in qs}:
                qs["board_idx"] = [str(key)]
                qs.pop("viewPage", None)
                new = parsed._replace(
                    path=parsed.path.replace("index.do", "view.do"),
                    query=urlencode(qs, doseq=True))
                return urlunparse(new)
    return ""


def _row_post_link(tr, page_url: str) -> str:
    """행(tr) 안에서 상세 링크 하나를 찾는다."""
    for a in tr.find_all("a"):
        url = resolve_post_link(a, page_url)
        if url:
            return url
    return ""


def count_post_links(table, page_url: str = "") -> int:
    """표 본문 안에 있는 게시글 상세 링크 개수(행 단위)."""
    body = table.find("tbody") or table
    count = 0
    for tr in body.find_all("tr"):
        if _row_post_link(tr, page_url):
            count += 1
    return count


def find_title_cell_index(table, page_url: str = "") -> int:
    """게시글 상세 링크가 들어있는 td의 컬럼 인덱스. 실패 시 -1.

    반응형 게시판은 번호 칸에도 (모바일용) 제목 링크가 숨어 있어 후보가 여럿일
    수 있다. 링크 텍스트가 가장 긴 칸을 고르고, 동률이면 뒤쪽 칸을 택한다.
    """
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        candidates = []   # (텍스트 길이, 칸 번호)
        for i, td in enumerate(tds):
            for a in td.find_all("a"):
                if resolve_post_link(a, page_url):
                    text = (a.get("title") or "").strip() or a.get_text(" ", strip=True)
                    candidates.append((len(text), i))
                    break
        if candidates:
            return max(candidates)[1]
    return -1


def find_board_table(soup: BeautifulSoup, page_url: str = ""):
    """게시글 상세 링크가 가장 많이 들어 있는 표를 게시판으로 본다.

    컬럼명('제목', '도구명', '자료명', '데이터명', '학교명' …)에 의존하지 않는다.
    링크가 하나도 안 잡히는 예외적인 경우에만 헤더 키워드 방식으로 물러선다.
    """
    best_table, best_score = None, 0
    for table in soup.find_all("table"):
        score = count_post_links(table, page_url)
        if score > best_score:
            best_table, best_score = table, score
    if best_table is not None:
        return best_table

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if not headers:
            continue
        header_text = " ".join(headers)
        if "번호" in header_text and any(
            k in header_text
            for k in ["제목", "도구명", "자료명", "데이터명", "한 줄 후기", "한줄소감", "학교명"]
        ):
            return table
    return None


def collect_gallery_links(soup: BeautifulSoup, page_url: str) -> list:
    """표가 없는 갤러리/카드형 게시판에서 게시글 링크 목록을 뽑는다.

    같은 게시판(boardId가 URL에 있으면 그 게시판)의 상세 링크만 모으고,
    글번호(dataSid/board_idx) 기준으로 중복을 제거한다.
    반환: [{'title', 'url'}]
    """
    qs = parse_qs(urlparse(page_url).query)
    want_board = (qs.get("boardId") or qs.get("boardid") or [None])[0]

    out, seen = [], set()
    for a in soup.find_all("a"):
        full = resolve_post_link(a, page_url)
        if not full:
            continue
        fqs = parse_qs(urlparse(full).query)
        if want_board:
            link_board = (fqs.get("boardId") or fqs.get("boardid") or [None])[0]
            if link_board != want_board:
                continue
        m = re.search(r"/view/(\d+)(?:\.do)?(?:[?#]|$)", full)
        key = (fqs.get("dataSid") or fqs.get("board_idx")
               or ([m.group(1)] if m else None) or [full])[0]
        title = (a.get("title") or "").strip() or a.get_text(" ", strip=True)
        if not title or key in seen:
            # 썸네일(제목 없는 이미지 링크)은 건너뛰고 제목 있는 링크를 기다린다.
            continue
        seen.add(key)
        out.append({"title": title, "url": full})
    return out


def read_headers(table) -> list:
    """표의 헤더(th) 목록. 빈 헤더는 자리를 유지하되 이름을 붙여 준다."""
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    out, blank = [], 0
    for h in headers:
        if h:
            out.append(h)
        else:
            blank += 1
            out.append(f"열{blank}")
    return out


# ==========================================================
# 본문 / 첨부
# ==========================================================

def extract_body_from_view(html: str, title_hint: str) -> str:
    """상세 페이지에서 제목 아래에 있는 본문만 최대한 텍스트로 추출"""
    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n", strip=True).splitlines() if ln.strip()]

    idx = None
    hint = (title_hint or "").strip()
    # 목록 제목 뒤에 붙는 '(댓글 : 3)' 같은 꼬리는 상세 페이지 제목에는 없다.
    short = re.sub(r"\s*\(\s*댓글\s*:\s*\d+\s*\)\s*$", "", hint)
    for candidate in dict.fromkeys(h for h in (hint, short) if h):
        for i, line in enumerate(lines):
            if candidate in line:
                idx = i
                break
        if idx is not None:
            break
    if idx is None:
        return ""

    start = idx + 1
    while start < len(lines) and lines[start].startswith(("작성자", "작성일", "등록일", "조회수")):
        start += 1

    body_lines = []
    for line in lines[start:]:
        if line.startswith(("이전글", "다음글", "목록")):
            break
        if "공공저작물 자유이용 허락 표시" in line:
            break
        body_lines.append(line)
    return "\n".join(body_lines).strip()


# ==========================================================
# 상세 페이지 구조 읽기 (1.3.5)
# ==========================================================
#
# 교육청 계열 홈페이지는 상세 페이지 틀이 정해져 있다. 틀을 알아보면
# 제목·작성자·등록일·조회수·본문·게시판 입력 항목·입력 표를 칸 단위로 읽는다.
# 틀을 모르는 사이트는 예전 방식(extract_body_from_view)을 그대로 쓴다.
#
#   jbe    : www.jbe.go.kr 계열        .bbs_vtop(제목·작성자·항목) + .bbs_con(본문)
#   usm    : office/school.jbedu.kr     table.usm-brd-vew (th/td) + td.tch-ctnt(본문)
#   jbedu  : www.jbedu.kr              .basicView .titleField + .conText(본문)
#   lib    : lib.jbe.go.kr             .bbs-view-header + .bbs-view-body(본문), 신착도서 .sview
#
# 반환 값(dict)
#   skin   : 알아본 틀 이름('' 이면 예전 방식)
#   title  : 상세 페이지 제목
#   meta   : {작성자, 등록일, 조회수 …}  게시글 정보
#   fields : {항목: 값}  게시판이 정해 놓은 입력 항목(채용구분, 신청기간, 만족도 …)
#   tables : [{'name', 'header': [...], 'rows': [[...], ...]}]  게시판이 정해 놓은 입력 표
#   body   : 본문 글(본문 안에 그려 넣은 표는 줄·칸을 ' | ' 로 구분해 넣는다)

_META_SKIP = {"첨부파일", "첨부", "IP", "ip", "댓글"}
_BLANK_RE = re.compile(r"\n{3,}")


def _clean(text) -> str:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def _label(text) -> str:
    return _clean(text).rstrip(":：").strip()


def _value(text) -> str:
    return re.sub(r"^[:：]\s*", "", _clean(text))


def _table_to_lines(table) -> list:
    lines = []
    for tr in table.find_all("tr"):
        cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


_BLOCK_TAGS = ("p", "div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5",
               "h6", "blockquote", "pre", "section", "article", "tr", "hr", "figure", "figcaption")


def element_text(el) -> str:
    """본문 영역을 글로 바꾼다.

    문단·목록 같은 덩어리 사이에서만 줄을 바꾸고(글자 모양 태그로 잘게 나뉜 문장은 한 줄로 이어 붙인다),
    본문 안의 표는 한 줄에 한 행씩 칸을 ' | ' 로 나눈다.
    """
    if el is None:
        return ""
    el = copy.copy(el)
    for bad in el.find_all(["script", "style", "noscript"]):
        bad.decompose()
    maker = BeautifulSoup("", "html.parser")
    for table in el.find_all("table"):
        if table.find_parent("table") is not None:
            continue
        block = maker.new_tag("div")
        block.string = "\n".join(_table_to_lines(table))
        table.replace_with(block)
    for br in el.find_all("br"):
        br.replace_with("\n")
    for tag in el.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = [_clean(line) for line in el.get_text().split("\n")]
    return "\n".join(line for line in lines if line)


def _put(target: dict, key: str, value: str) -> None:
    """같은 이름이 또 나오면 '이름(2)' 로 이어 붙인다(값을 덮어쓰지 않는다)."""
    if not key:
        return
    if key not in target:
        target[key] = value
        return
    n = 2
    while f"{key}({n})" in target:
        n += 1
    target[f"{key}({n})"] = value


def _table_name(table, fallback: str) -> str:
    cap = table.find("caption")
    name = ""
    if cap is not None:
        strong = cap.find("strong")
        name = _clean((strong or cap).get_text(" ", strip=True))
    name = re.sub(r"\s*(상세\s*)?등록$", lambda m: " 상세" if m.group(1) else "", name).strip()
    return name or fallback


def _read_form_table(table, name: str):
    """게시판이 정해 놓은 입력 표를 {'name','header','rows'} 로 읽는다. 빈 표면 None."""
    header, rows = [], []
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        tds = tr.find_all("td")
        if ths and not tds:
            cells = [_clean(th.get_text(" ", strip=True)) for th in ths]
            # 표 전체 제목 줄(칸 하나가 여러 칸을 덮음)은 이름으로만 쓴다.
            if len(ths) == 1 and ths[0].get("colspan"):
                continue
            header = cells
        elif tds:
            cells = [_clean(td.get_text(" ", strip=True)) for td in tds]
            if any(cells):
                rows.append(cells)
    if not rows:
        return None
    width = max(len(header), max(len(r) for r in rows))
    header = header + [f"칸{i + 1}" for i in range(len(header), width)]
    return {"name": name, "header": header, "rows": rows}


def _parse_jbe(soup):
    top = soup.select_one(".bbs_vtop")
    if top is None or (top.find(["h4", "h3"]) is None and top.select_one("ul.col") is None):
        return None
    con = soup.select_one(".bbs_con")
    if con is None:
        # 동영상 게시판처럼 본문 칸 이름이 다른 경우: 제목 영역·첨부·이전/다음 글을 뺀 나머지
        view = top.parent
        con = copy.copy(view)
        for junk in con.select(".bbs_vtop, .bbs_filedown, .pagelist, .bbs_btn, .screen_area, .bbs_img"):
            junk.decompose()
    out = {"skin": "jbe", "meta": {}, "fields": {}, "tables": []}
    h = top.find(["h4", "h3"])
    out["title"] = _clean(h.get_text(" ", strip=True)) if h else ""
    for li in top.select("ul.col li"):
        strong = li.find("strong")
        if strong is None:
            continue
        full = li.get_text(" ", strip=True)
        lab = strong.get_text(" ", strip=True)
        label = _label(lab)
        value = _value(full[len(lab):] if full.startswith(lab) else full)
        if label and label not in _META_SKIP:
            _put(out["meta"], label, value)

    # 입력 항목: 소제목(h5)마다 묶는다. 소제목이 둘 이상이면 '소제목_항목' 으로 이름을 붙인다.
    sections, current = [], ""
    table_no = 0
    for node in top.find_all(["h5", "ul", "table"]):
        if node.name == "h5":
            current = _clean(node.get_text(" ", strip=True))
        elif node.name == "ul" and "tt_list" in (node.get("class") or []):
            sections.append((current, node))
        elif node.name == "table" and node.find_parent("table") is None:
            table_no += 1
            got = _read_form_table(node, _table_name(node, current or f"표{table_no}"))
            if got:
                out["tables"].append(got)
    multi = len({s for s, _ in sections}) > 1
    for section, ul in sections:
        for li in ul.find_all("li"):
            strong = li.find("strong")
            if strong is None:
                continue
            label = _label(strong.get_text(" ", strip=True))
            span = li.find("span")
            value = _clean(span.get_text(" ", strip=True)) if span else \
                _value(li.get_text(" ", strip=True).replace(strong.get_text(" ", strip=True), "", 1))
            key = f"{section}_{label}" if (multi and section) else label
            _put(out["fields"], key, value)
    out["body"] = element_text(con)
    return out


def _parse_usm(soup):
    table = soup.select_one("table.usm-brd-vew")
    if table is None:
        return None
    out = {"skin": "usm", "meta": {}, "fields": {}, "tables": []}
    tit = table.select_one("th.tch-tit")
    out["title"] = _clean(tit.get_text(" ", strip=True)) if tit else ""
    body_td = table.select_one("td.tch-ctnt")
    target = out["meta"] if body_td is not None else out["fields"]
    pending = None   # 제목 칸만 있는 줄(다음 줄 td 가 값)
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        if body_td is not None and body_td in cells:
            continue
        if tit is not None and tit in cells:
            continue
        if pending is not None and len(cells) == 1 and cells[0].name == "td":
            _put(target, pending, element_text(cells[0]))
            pending = None
            continue
        if len(cells) == 1 and cells[0].name == "th":
            pending = _label(cells[0].get_text(" ", strip=True))
            continue
        i = 0
        while i < len(cells):
            c = cells[i]
            if c.name == "th" and i + 1 < len(cells) and cells[i + 1].name == "td":
                label = _label(c.get_text(" ", strip=True))
                td = cells[i + 1]
                if label not in _META_SKIP and "tch-fil" not in (td.get("class") or []):
                    _put(target, label, _clean(td.get_text(" ", strip=True)))
                i += 2
            else:
                i += 1
    if body_td is not None:
        body = copy.copy(body_td)
        for ul in body.select("ul.usm-editor-img"):
            if not ul.get_text(strip=True):
                ul.decompose()
        out["body"] = element_text(body)
    else:
        out["body"] = ""
    return out


def _parse_jbedu(soup):
    box = soup.select_one(".basicView")
    if box is None:
        return None
    out = {"skin": "jbedu", "meta": {}, "fields": {}, "tables": []}
    h = box.select_one(".titleField h4")
    out["title"] = _clean(h.get_text(" ", strip=True)) if h else ""
    for li in box.select(".titleField li"):
        strong, span = li.find("strong"), li.find("span")
        if strong is not None:
            label = _label(strong.get_text(" ", strip=True))
            if label and label not in _META_SKIP:
                _put(out["meta"], label, _clean(span.get_text(" ", strip=True)) if span else "")
    for li in box.select(".conField li"):
        span = li.find("span", recursive=False)
        p = li.find("p", recursive=False)
        if span is None:
            continue
        label = _label(span.get_text(" ", strip=True))
        if label and label not in _META_SKIP:
            _put(out["fields"], label, _clean(p.get_text(" ", strip=True)) if p else "")
    out["body"] = element_text(box.select_one(".conText"))
    return out


def _parse_lib(soup):
    view = soup.select_one(".bbs-view")
    sview = soup.select_one(".sview")
    if view is None and sview is None:
        return None
    out = {"skin": "lib", "meta": {}, "fields": {}, "tables": [], "title": ""}
    if view is not None:
        head = view.select_one(".bbs-view-header")
        if head is not None:
            dt = head.find("dt")
            out["title"] = _clean(dt.get_text(" ", strip=True)) if dt else ""
            for i in head.find_all("i"):
                label = _label(i.get_text(" ", strip=True))
                span = i.find_next_sibling("span")
                if label and label not in _META_SKIP and span is not None:
                    _put(out["meta"], label, _clean(span.get_text(" ", strip=True)))
        out["body"] = element_text(view.select_one(".bbs-view-body"))
        return out
    # 신착도서처럼 책 정보(저자·출판사 …)와 소개 글로 된 게시판
    info = sview.select_one(".info")
    if info is not None:
        for li in info.find_all("li"):
            text = _clean(li.get_text(" ", strip=True))
            if li.find("b") is not None and not out["title"]:
                out["title"] = text
                continue
            if ":" in text:
                label, value = text.split(":", 1)
                _put(out["fields"], _label(label), _clean(value))
    body = copy.copy(sview)
    for junk in body.select(".sinfo, .button, form"):
        junk.decompose()
    out["body"] = element_text(body)
    return out


_SKIN_PARSERS = (_parse_jbe, _parse_usm, _parse_jbedu, _parse_lib)


def parse_detail(html: str, title_hint: str = "") -> dict:
    """상세 페이지를 틀에 맞춰 칸 단위로 읽는다. 틀을 모르면 예전 방식으로 본문만 읽는다."""
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    for parser in _SKIN_PARSERS:
        try:
            got = parser(soup)
        except Exception:
            got = None
        if got is not None:
            got.setdefault("body", "")
            return got
    return {"skin": "", "title": "", "meta": {}, "fields": {}, "tables": [],
            "body": extract_body_from_view(html, title_hint)}


def request_error_text(error: Exception) -> str:
    """페이지 요청이 실패한 이유를 한국어로. 원래 오류 문구도 뒤에 붙인다."""
    if isinstance(error, requests.exceptions.SSLError):
        head = "보안 인증서(TLS) 문제로 접속하지 못했습니다"
    elif isinstance(error, requests.exceptions.ProxyError):
        head = "프록시 설정 문제로 접속하지 못했습니다"
    elif isinstance(error, requests.exceptions.Timeout):
        head = "사이트가 제시간에 응답하지 않았습니다"
    elif isinstance(error, requests.exceptions.ConnectionError):
        head = "사이트에 접속하지 못했습니다(인터넷 연결·주소 확인)"
    elif isinstance(error, requests.exceptions.HTTPError):
        status = getattr(getattr(error, "response", None), "status_code", "")
        head = f"사이트가 오류를 돌려주었습니다(HTTP {status})"
    else:
        head = "페이지를 열지 못했습니다"
    return f"{head}: {error}"


def safe_filename(name: str) -> str:
    """윈도우 파일 이름에 쓸 수 없는 문자 제거"""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip() or "무제"


def _header_filename(cd: str) -> str:
    """Content-Disposition 에서 서버가 알려 준 파일 이름을 꺼낸다(한글 이름 복원 포함)."""
    if not cd:
        return ""
    m = re.search(r"filename\*\s*=\s*([^;]+)", cd, flags=re.I)
    if m:
        part = m.group(1).strip().strip('"')
        charset, _, encoded = part.partition("''")
        if encoded:
            try:
                return unquote(encoded, encoding=charset or "utf-8", errors="strict")
            except (LookupError, UnicodeDecodeError):
                return unquote(encoded)
        return unquote(part)
    m = re.search(r'filename\s*=\s*("([^"]*)"|[^;]+)', cd, flags=re.I)
    if not m:
        return ""
    name = (m.group(2) if m.group(2) is not None else m.group(1)).strip()
    # requests 는 머리글을 latin-1 로 읽는다. 원래 바이트로 되돌려 UTF-8 → cp949 순으로 읽는다.
    try:
        raw = name.encode("latin-1")
        for encoding in ("utf-8", "cp949"):
            try:
                name = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    except UnicodeEncodeError:
        pass
    if re.search(r"%[0-9A-Fa-f]{2}", name):
        name = unquote(name)
    return name


def choose_attachment_name(desired: str, server_name: str) -> str:
    """저장할 첨부 이름. 링크 글자('다운로드', '미리보기')를 이름으로 쓰면 확장자가 빠지므로,
    고른 이름에 서버 파일의 확장자가 없으면 서버 파일 이름을 쓴다."""
    desired = (desired or "").strip()
    server_name = (server_name or "").strip()
    server_ext = os.path.splitext(server_name)[1]
    if not desired:
        return server_name
    if not server_ext or desired.lower().endswith(server_ext.lower()):
        return desired
    return server_name


def clean_attachment_display_name(text: str) -> str:
    """'계획서.hwp (123KB)' → '계획서.hwp'"""
    name = (text or "").strip()
    m = re.match(r"(.+?)\s*\(\s*\d[\d,.]*\s*(kb|mb|byte|bytes)\s*\)?", name, flags=re.I)
    if m:
        name = m.group(1).strip()
    return name


def extract_attachments_from_detail(soup: BeautifulSoup, base_url: str) -> list:
    """상세 페이지에서 첨부파일 링크 목록을 추출(중복 제거)."""
    files, seen = [], set()
    for a in soup.find_all("a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href") or ""
        if not href:
            continue
        lower_text = text.lower()
        full_url = urljoin(base_url, href)

        if "kb)" in lower_text or "(kb" in lower_text or is_attachment_href(href):
            name = clean_attachment_display_name(text) if text else os.path.basename(full_url)
            if full_url in seen:
                continue
            seen.add(full_url)
            files.append({"name": name or os.path.basename(full_url), "url": full_url})
    return files


def download_attachment(session, full_url, save_dir, log_func, error_list,
                        page, post_no, title, desired_filename=None):
    """첨부파일 1개 다운로드. 성공 시 저장된 파일명, 실패 시 None."""
    try:
        resp = http_get(session, full_url, timeout=30, stream=True)
        resp.raise_for_status()

        server_name = _header_filename(resp.headers.get("Content-Disposition", ""))
        if not server_name:
            url_name = unquote(os.path.basename(urlparse(full_url).path))
            # 'download.do' 같은 주소 끝은 파일 이름이 아니다.
            if os.path.splitext(url_name)[1].lower() in ATTACH_EXTS:
                server_name = url_name
        filename = choose_attachment_name(desired_filename or "", server_name)
        if not filename:
            filename = os.path.basename(urlparse(full_url).path) or "downloaded_file"

        filename = safe_filename(filename)
        os.makedirs(save_dir, exist_ok=True)
        full_path = os.path.join(save_dir, filename)

        base_name, ext = os.path.splitext(full_path)
        idx = 1
        while os.path.exists(full_path):
            full_path = f"{base_name}({idx}){ext}"
            idx += 1

        with open(full_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        log_func(f"      · 첨부 저장: {os.path.basename(full_path)}")
        return os.path.basename(full_path)

    except Exception as e:
        msg = f"첨부파일 다운로드 실패 ({full_url}): {e}"
        error_list.append({"page": page, "post_no": post_no, "title": title, "error": msg})
        log_func(f"      ! {msg}")
        return None


# ==========================================================
# 수집 본체
# ==========================================================

def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()


def _collect_detail(session, post_url, title_hint, author_hint, page, post_no,
                    result, log_func, collect_body, download_files, attach_dir,
                    cancel_event, note_error):
    """상세 페이지에서 본문·첨부 목록을 모으고(옵션) 첨부를 내려받는다.

    반환: (body, attach_names, detail)  detail 은 parse_detail() 결과(본문 제외)
    """
    body, attach_names, detail = "", [], {}
    if not post_url or not (collect_body or download_files):
        return body, attach_names, detail
    try:
        dresp = http_get(session, post_url, timeout=15)
        dresp.raise_for_status()
        dresp.encoding = dresp.apparent_encoding or "utf-8"
        detail_html = dresp.text
        detail_soup = BeautifulSoup(detail_html, "html.parser")

        if collect_body:
            try:
                detail = parse_detail(detail_html, title_hint)
                body = detail.pop("body", "")
            except Exception as e:
                note_error(page, post_no, title_hint, f"본문 수집 실패: {e}")
                log_func(f"    - [{title_hint}] 본문 수집 실패")

        try:
            attach_infos = extract_attachments_from_detail(detail_soup, post_url)
        except Exception as e:
            attach_infos = []
            note_error(page, post_no, title_hint, f"첨부파일 목록 추출 실패: {e}")
            log_func(f"    - [{title_hint}] 첨부파일 정보 추출 실패")

        attach_names = [i["name"] for i in attach_infos]

        if download_files and attach_dir and attach_infos:
            base_name = title_hint or f"게시글_{post_no or (len(result.rows) + 1)}"
            if author_hint:
                base_name = f"{base_name}_{author_hint}"
            post_folder = os.path.join(attach_dir, safe_filename(base_name))
            os.makedirs(post_folder, exist_ok=True)
            for info in attach_infos:
                _check_cancel(cancel_event)
                download_attachment(
                    session=session, full_url=info["url"], save_dir=post_folder,
                    log_func=log_func, error_list=result.errors, page=page,
                    post_no=post_no, title=title_hint, desired_filename=info["name"])

    except Cancelled:
        raise
    except Exception as e:
        note_error(page, post_no, title_hint, f"상세 페이지 요청 실패: {e}")
        log_func(f"    - [{title_hint}] 상세 페이지 불러오기 실패")
    return body, attach_names, detail


def crawl_board(board_url, start_page, end_page, max_posts, log_func,
                collect_body=True, download_files=False, attach_dir=None,
                cancel_event=None, progress_func=None) -> CrawlResult:
    """게시판을 훑어 행 목록을 만든다.

    각 행(dict)은 화면에 보이는 헤더를 키로 갖고, 아래 특수 키가 덧붙는다.
        _상세URL, _본문내용, _첨부파일개수, _첨부파일목록
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    result = CrawlResult()
    headers = None
    collected = 0

    def note_error(page, post_no, title, error):
        result.errors.append({"page": page, "post_no": post_no, "title": title, "error": error})

    try:
        for page in range(start_page, end_page + 1):
            _check_cancel(cancel_event)
            if max_posts and collected >= max_posts:
                break

            page_url = build_page_url(board_url, page)
            log_func(f"[페이지 {page}] 요청 중...")

            try:
                resp = http_get(session, page_url, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                log_func(f"  → 페이지 요청 실패: {e}")
                note_error(page, "", "", f"페이지 요청 실패: {e}")
                result.page_failures.append(request_error_text(e))
                continue
            result.pages_opened += 1

            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            table = find_board_table(soup, page_url)
            if not table:
                # 갤러리/카드형(표 없음) 게시판 폴백
                links = collect_gallery_links(soup, page_url)
                if not links:
                    log_func("  → 게시판 표(또는 게시글 목록)를 찾지 못했습니다. (이 페이지는 건너뜀)")
                    note_error(page, "", "", "게시판 표 미발견")
                    continue
                if headers is None:
                    headers = ["제목"]
                    result.headers = headers
                    log_func(f"  → 목록형(갤러리) 게시판으로 인식 — 이 페이지 {len(links)}건")
                for item in links:
                    _check_cancel(cancel_event)
                    if max_posts and collected >= max_posts:
                        break
                    title_hint, post_url = item["title"], item["url"]
                    try:
                        body, attach_names, detail = _collect_detail(
                            session, post_url, title_hint, "", page, "",
                            result, log_func, collect_body, download_files,
                            attach_dir, cancel_event, note_error)
                        row = {"제목": title_hint,
                               "_상세URL": post_url,
                               "_본문내용": body if collect_body else "",
                               "_첨부파일개수": len(attach_names),
                               "_첨부파일목록": "; ".join(attach_names) if attach_names else "",
                               "_상세": detail, "_번호": "", "_제목": title_hint}
                        collected += 1
                        result.rows.append(row)
                        log_func(f"    - 수집됨: {title_hint}")
                        if progress_func:
                            progress_func(collected)
                    except Cancelled:
                        raise
                    except Exception as e:
                        note_error(page, "", title_hint, f"행 파싱 실패: {e}")
                        log_func(f"    - 행 파싱 중 오류 (건너뜀): {e}")
                continue

            if headers is None:
                headers = read_headers(table)
                result.headers = headers
                log_func(f"  → 인식된 헤더: {headers}")

            title_idx = find_title_cell_index(table, page_url)
            if page == start_page and 0 <= title_idx < len(headers):
                log_func(f"  → 제목 칸 인식: '{headers[title_idx]}' ({title_idx + 1}번째)")

            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                _check_cancel(cancel_event)
                if max_posts and collected >= max_posts:
                    break

                tds = tr.find_all("td")
                if not tds:
                    continue

                try:
                    row = {}
                    for i, h in enumerate(headers):
                        row[h] = tds[i].get_text(" ", strip=True) if i < len(tds) else ""

                    post_no = title_hint = author_hint = ""

                    # 제목: 상세 링크가 있는 칸을 최우선으로 사용
                    if 0 <= title_idx < len(tds):
                        link = next(
                            (a for a in tds[title_idx].find_all("a")
                             if resolve_post_link(a, page_url)), None)
                        if link is not None:
                            title_hint = (link.get("title") or "").strip() \
                                or link.get_text(" ", strip=True)
                        else:
                            title_hint = tds[title_idx].get_text(" ", strip=True)

                    for h in headers:
                        if not post_no and "번호" in h:
                            post_no = row.get(h, "")
                        if not title_hint and any(
                            k in h for k in ["제목", "도구명", "자료명", "데이터명",
                                             "학교명", "한 줄 후기", "한줄소감"]):
                            title_hint = row.get(h, "")
                        if not author_hint and any(
                                k in h for k in ["부서", "작성자", "학교명", "학교", "기관"]):
                            author_hint = row.get(h, "")

                    if not title_hint and len(headers) >= 2:
                        title_hint = row.get(headers[1], "")
                    if not post_no and headers:
                        post_no = row.get(headers[0], "")

                    # 상세 페이지 주소 (href형 + keyvalue형 모두 지원)
                    post_url = _row_post_link(tr, page_url)
                    if not post_url:
                        for a in tr.find_all("a"):
                            href = a.get("href", "")
                            if not href or href.strip().startswith(("#", "javascript:")):
                                continue
                            if is_attachment_href(href):
                                continue
                            post_url = urljoin(board_url, href)
                            break

                    body, attach_names, detail = _collect_detail(
                        session, post_url, title_hint, author_hint, page, post_no,
                        result, log_func, collect_body, download_files,
                        attach_dir, cancel_event, note_error)

                    row["_상세URL"] = post_url
                    row["_본문내용"] = body if collect_body else ""
                    row["_첨부파일개수"] = len(attach_names)
                    row["_첨부파일목록"] = "; ".join(attach_names) if attach_names else ""
                    row["_상세"] = detail
                    row["_번호"] = post_no
                    row["_제목"] = title_hint

                    collected += 1
                    result.rows.append(row)
                    log_func(f"    - 수집됨: {title_hint or post_no or '(제목 없음)'}")
                    if progress_func:
                        progress_func(collected)

                except Cancelled:
                    raise
                except Exception as e:
                    note_error(page, "", "", f"행 파싱 실패: {e}")
                    log_func(f"    - 행 파싱 중 오류 (건너뜀): {e}")

    except Cancelled:
        result.cancelled = True
        log_func("\n※ 사용자가 중지했습니다. 그때까지 수집한 내용만 저장합니다.")

    result.headers = headers or []
    return result


# ==========================================================
# 엑셀 저장
# ==========================================================

def adjust_column_width(ws) -> None:
    for column_cells in ws.columns:
        max_len = 0
        col = get_column_letter(column_cells[0].column)
        for cell in column_cells:
            try:
                val = str(cell.value) if cell.value is not None else ""
            except Exception:
                val = ""
            max_len = max(max_len, len(val))
        ws.column_dimensions[col].width = min(max_len + 2, 60)


def _detail_columns(headers, rows):
    """상세 페이지에서 읽은 칸들을 어떤 열로 둘지 정한다.

    · 게시글 정보(작성자·등록일·조회수 …)와 입력 항목은 처음 나온 순서대로 열이 된다.
      목록 표에 이미 같은 이름의 열이 있으면 새로 만들지 않는다.
    · 입력 표 중 모든 글에서 한 줄뿐인 표는 '표이름_칸이름' 열로 붙인다.
    · 줄이 여럿인 표는 별도 시트로 보낸다(sheet_tables).
    """
    have = set(headers) | set(EXTRA_HEADERS)
    info_cols, seen = [], set()
    multi_tables = {}
    for row in rows:
        detail = row.get("_상세") or {}
        for part in ("meta", "fields"):
            for key in (detail.get(part) or {}):
                if key not in have and key not in seen:
                    seen.add(key)
                    info_cols.append(key)
        for table in detail.get("tables") or []:
            if len(table["rows"]) > 1:
                multi_tables[table["name"]] = True
    flat_cols = []
    for row in rows:
        for table in (row.get("_상세") or {}).get("tables") or []:
            if table["name"] in multi_tables:
                continue
            for h in table["header"]:
                key = f"{table['name']}_{h}"
                if key not in have and key not in seen:
                    seen.add(key)
                    flat_cols.append(key)
    info_cols = [c for c in info_cols if not _repeats_list_column(c, headers, rows)]
    return info_cols, flat_cols, list(multi_tables)


def _norm_cell(value) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _repeats_list_column(col, headers, rows) -> bool:
    """상세 칸의 값이 모든 글에서 목록 표의 어떤 열과 똑같으면 True(같은 내용을 두 번 싣지 않는다).
    예) 목록의 '이 름' 열과 상세의 '작성자' 가 늘 같은 학교 게시판."""
    values = [_flat_values(row).get(col, "") for row in rows]
    if not any(_norm_cell(v) for v in values):
        return False
    for h in headers:
        if all(_norm_cell(v) == _norm_cell(row.get(h, "")) for v, row in zip(values, rows)):
            return True
    return False


def _flat_values(row) -> dict:
    detail = row.get("_상세") or {}
    out = {}
    out.update(detail.get("meta") or {})
    out.update(detail.get("fields") or {})
    for table in detail.get("tables") or []:
        if len(table["rows"]) == 1:
            for h, v in zip(table["header"], table["rows"][0]):
                out[f"{table['name']}_{h}"] = v
    return out


def _cell_value(value):
    """엑셀 칸에 넣을 값. 제목 등에 섞인 제어 문자(\\x08 등)는 엑셀이 받지 않아 저장 전체가
    실패하므로 지운다. '=' 로 시작하는 글자는 함수가 아니라 글자로 넣는다(_append_row)."""
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _append_row(ws, values) -> None:
    ws.append([_cell_value(value) for value in values])
    for cell in ws[ws.max_row]:
        if cell.data_type == "f":
            cell.data_type = "s"


def _sheet_title(name: str, used: set) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "_", ILLEGAL_CHARACTERS_RE.sub("", str(name))).strip() or "표"
    base = base[:31]
    title, n = base, 2
    while title in used:
        suffix = f"({n})"
        title = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(title)
    return title


def save_to_excel(headers, rows, errors, excel_path, board_url) -> str:
    """게시판 헤더를 그대로 열로 쓰고, 상세 페이지에서 읽은 칸과 공통 열을 뒤에 붙여 저장.

    줄이 여럿인 입력 표(학년별 인원 등)는 표마다 시트를 따로 만들고,
    어느 글의 표인지 알 수 있게 번호·제목·상세URL 을 앞에 붙인다.
    """
    info_cols, flat_cols, multi_names = _detail_columns(headers, rows)
    count_cols = [f"{name}(행수)" for name in multi_names]

    wb = Workbook()
    ws = wb.active
    ws.title = "게시글"
    _append_row(ws, list(headers) + info_cols + flat_cols + count_cols + EXTRA_HEADERS)

    for row in rows:
        values = [row.get(h, "") for h in headers]
        flat = _flat_values(row)
        values += [flat.get(c, "") for c in info_cols + flat_cols]
        tables = {t["name"]: t for t in (row.get("_상세") or {}).get("tables") or []}
        values += [len(tables[name]["rows"]) if name in tables else "" for name in multi_names]
        values += [
            board_url,
            row.get("_상세URL", ""),
            row.get("_본문내용", ""),
            row.get("_첨부파일개수", ""),
            row.get("_첨부파일목록", ""),
        ]
        _append_row(ws, values)
    adjust_column_width(ws)

    used = {"게시글", "오류_건너뜀"}
    for name in multi_names:
        header = []
        for row in rows:
            for t in (row.get("_상세") or {}).get("tables") or []:
                if t["name"] == name and len(t["header"]) > len(header):
                    header = t["header"]
        sheet = wb.create_sheet(_sheet_title(name, used))
        _append_row(sheet, ["번호", "제목", "상세URL"] + header)
        for row in rows:
            for t in (row.get("_상세") or {}).get("tables") or []:
                if t["name"] != name:
                    continue
                for cells in t["rows"]:
                    _append_row(sheet, [row.get("_번호", ""), row.get("_제목", ""), row.get("_상세URL", "")] + cells)
        adjust_column_width(sheet)

    ws_err = wb.create_sheet("오류_건너뜀")
    _append_row(ws_err, ["페이지", "게시글번호", "제목", "오류내용"])
    for err in errors:
        _append_row(ws_err, [err.get("page", ""), err.get("post_no", ""),
                             err.get("title", ""), err.get("error", "")])
    adjust_column_width(ws_err)

    wb.save(excel_path)
    return excel_path


# ==========================================================
# 미리 확인(게시판 주소가 올바른지 빠르게 점검)
# ==========================================================

def probe_board(board_url: str, timeout: float = 15.0) -> dict:
    """게시판 주소를 한 번 열어 표·헤더·제목 칸·마지막 페이지를 알려 준다.

    반환: {'ok', 'message', 'headers', 'title_column', 'rows', 'last_page'}
    """
    out = {"ok": False, "message": "", "headers": [], "title_column": "",
           "rows": 0, "last_page": 1}
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        resp = http_get(session, build_page_url(board_url, 1), timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except Exception as e:
        out["message"] = f"주소를 열지 못했습니다: {e}"
        return out

    # 로그인이 필요한 게시판: 본문 대신 짧은 스크립트(알림+이동)만 내려온다.
    if len(resp.text) < 1000 and ("로그인" in resp.text or "login" in resp.text.lower()):
        out["message"] = ("로그인이 필요한 게시판입니다.\n"
                          "로그인 후에만 볼 수 있는 게시판은 수집할 수 없습니다.")
        return out

    page_url = build_page_url(board_url, 1)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = find_board_table(soup, page_url)
    if table is None:
        # 갤러리/카드형 폴백
        links = collect_gallery_links(soup, page_url)
        if links:
            out.update({
                "ok": True,
                "headers": ["제목"],
                "title_column": "(목록형)",
                "rows": len(links),
                "last_page": detect_last_page(soup),
            })
            out["message"] = (f"목록형(갤러리) 게시판을 찾았습니다. "
                              f"이 페이지에 {out['rows']}건이 있습니다. "
                              f"마지막 페이지는 {out['last_page']}쪽으로 보입니다.")
            return out
        out["message"] = ("이 주소에서 게시판 표를 찾지 못했습니다.\n"
                          "게시판 '목록' 화면 주소인지 확인해 주세요.\n"
                          "(로그인이 필요하거나 화면을 스크립트로 그리는 게시판은 지원되지 않습니다.)")
        return out

    headers = read_headers(table)
    idx = find_title_cell_index(table, page_url)
    out.update({
        "ok": True,
        "headers": headers,
        "title_column": headers[idx] if 0 <= idx < len(headers) else "(자동)",
        "rows": count_post_links(table, page_url),
        "last_page": detect_last_page(soup),
    })
    out["message"] = (f"게시판을 찾았습니다. 제목 칸은 '{out['title_column']}'이고, "
                      f"이 페이지에 {out['rows']}건이 있습니다. "
                      f"마지막 페이지는 {out['last_page']}쪽으로 보입니다.")
    return out
