from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = BASE_DIR / "tools"
SHARED_DIR = BASE_DIR / "shared"
CONFIG_DIR = SHARED_DIR / "config"

DEFAULT_TOP_TABS = [
    "홈",
    "엑셀·데이터",
    "PDF·문서",
    "수집·추출",
    "업무 자동화",
    "한글·보고서",
    "설정",
]

WINDOW_TITLE = "업무 자동화 도구실"
