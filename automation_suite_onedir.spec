# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_dir = Path.cwd()

datas = []
for folder_name in ("app", "tools", "shared"):
    folder_path = project_dir / folder_name
    if folder_path.exists():
        datas.append((str(folder_path), folder_name))

hiddenimports = [
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "win32gui",
    "win32api",
    "win32con",

    # PDF
    "pypdf",
    "PyPDF2",
    "fitz",
    "pymupdf",
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
    "pdfminer.layout",
    "pdfminer.pdfinterp",
    "pdfminer.pdfpage",
    "pdfminer.converter",
    "reportlab",
    "reportlab.pdfgen",
    "reportlab.pdfbase",
    "reportlab.lib",
    "reportlab.lib.pagesizes",
    "reportlab.lib.units",
    "reportlab.lib.colors",

    # Image
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL.ImageFont",
    "PIL.ImageDraw",

    # Web / crawling
    "requests",
    "bs4",
    "lxml",
    "lxml.etree",

    # Excel
    "openpyxl",
]

hiddenimports += collect_submodules("PySide6")

try:
    hiddenimports += collect_submodules("PySide6.QtWebEngineWidgets")
    hiddenimports += collect_submodules("PySide6.QtWebEngineCore")
except Exception:
    pass

for pkg in [
    "pypdf",
    "PyPDF2",
    "fitz",
    "pdfplumber",
    "pdfminer",
    "reportlab",
    "PIL",
    "bs4",
    "openpyxl",
]:
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="automation_suite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="automation_suite",
)