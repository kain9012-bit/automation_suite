# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

project_root = Path.cwd()


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

# PDF 용량 압축은 PyMuPDF 를 쓴다. 파이썬 모듈 말고도 C 라이브러리(DLL)가 있어야 한다.
binaries = []
for _name in ("pymupdf", "fitz"):
    try:
        _d, _b, _h = collect_all(_name)
    except Exception:
        continue
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    [str(project_root / "bridge" / "runner.py")],
    pathex=[str(project_root)],
    binaries=binaries,
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

