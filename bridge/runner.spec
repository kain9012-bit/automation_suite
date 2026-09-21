# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path.cwd()


def collect_ghostscript():
    """vendor/gs 전체를 사이드카 안 gs/ 로 넣는다.

    PDF 용량 압축(pdf_compress_service)은 실행 중 _MEIPASS/gs/bin/gswin64c.exe 를
    먼저 찾는다. 이게 없으면 Ghostscript 를 따로 설치한 PC 에서만 압축이 된다.
    lib/cidfmap 은 한글 글꼴(굴림·바탕·맑은 고딕)을 Windows 글꼴로 잇도록 손본
    것이라 그대로 넣어야 한다. 원본은 pdf_doc_tools_tk/gs 이다.
    """
    gs_root = project_root / "vendor" / "gs"
    exe = gs_root / "bin" / "gswin64c.exe"
    if not exe.is_file():
        raise SystemExit(
            f"[runner.spec] {exe} 가 없습니다. Ghostscript 없이 만들면 PDF 압축이 "
            "다른 PC 에서 동작하지 않습니다. vendor/gs 를 먼저 준비하세요."
        )
    items = []
    for dirpath, _dirs, files in os.walk(gs_root):
        rel = Path(dirpath).relative_to(gs_root)
        dest = str(Path("gs") / rel)
        for name in files:
            items.append((str(Path(dirpath) / name), dest))
    print(f"[runner.spec] Ghostscript 파일 {len(items)}개를 넣습니다.")
    return items

hiddenimports = [
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32com",
    "win32com.client",
    "pypdf",
    "pdfplumber",
    "pandas",
    "openpyxl",
    "reportlab",
    "requests",
    "bs4",
    "lxml",
    "PIL",
]

# 도구 코드는 실행 중에 디스크에서 불러오므로 PyInstaller 가 그 안의 import 를 못 본다.
# 꼭대기 이름만 적으면 하위 모듈이 빠진다. reportlab.pdfbase 가 빠져 PDF 페이지번호가
# 다른 PC 에서 "No module named 'reportlab.pdfbase'" 로 실패했다.
hiddenimports += collect_submodules("reportlab")

datas = []
datas += collect_data_files("reportlab")
datas += collect_ghostscript()


a = Analysis(
    [str(project_root / "bridge" / "runner.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "PyQt5",
        "PyQt6",
        "tkinter",
        "matplotlib",
        "notebook",
        "IPython",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bridge-runner-x86_64-pc-windows-msvc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

