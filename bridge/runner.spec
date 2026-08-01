# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

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


a = Analysis(
    [str(project_root / "bridge" / "runner.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
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

