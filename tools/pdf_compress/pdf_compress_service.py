from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def _candidate_gs_paths() -> List[Path]:
    candidates: List[Path] = []

    if _is_frozen():
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        candidates.append(meipass / "gs" / "bin" / "gswin64c.exe")
        candidates.append(meipass / "gswin64c.exe")

    for cmd in ("gswin64c", "gs", "gswin32c"):
        p = shutil.which(cmd)
        if p:
            candidates.append(Path(p))

    for root in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ):
        gs_root = root / "gs"
        if gs_root.exists():
            for sub in sorted(gs_root.glob("gs*"), reverse=True):
                candidates.append(sub / "bin" / "gswin64c.exe")

    out: List[Path] = []
    seen = set()
    for c in candidates:
        s = str(c).lower()
        if s not in seen:
            seen.add(s)
            out.append(c)
    return out


def configure_gs_env_if_bundled() -> None:
    if not _is_frozen():
        return

    meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    gs_dir = meipass / "gs"
    if not gs_dir.exists():
        return

    lib_dir = gs_dir / "lib"
    res_dir = gs_dir / "Resource"
    if not res_dir.exists():
        res_dir = gs_dir / "resource"

    font_dir = res_dir / "Font"

    libs = []
    if lib_dir.exists():
        libs.append(str(lib_dir))
    if res_dir.exists():
        libs.append(str(res_dir))
    if libs:
        os.environ["GS_LIB"] = ";".join(libs)
    if font_dir.exists():
        os.environ["GS_FONTPATH"] = str(font_dir)

    bin_dir = gs_dir / "bin"
    if bin_dir.exists():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def find_ghostscript() -> Optional[str]:
    configure_gs_env_if_bundled()
    for p in _candidate_gs_paths():
        try:
            if p.exists():
                return str(p)
        except Exception:
            continue
    return None


def bytes_to_mb(n: int) -> float:
    return n / (1024 * 1024)


def safe_output_path(in_fp: Path, target_mb: float) -> Path:
    stem = in_fp.stem
    out_name = f"{stem}_압축_{target_mb:.1f}MB.pdf"
    return in_fp.with_name(out_name)


def run_gs_compress(gs: str, in_fp: Path, out_fp: Path, preset: str, dpi: int) -> None:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    args = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={preset}",
        "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDownsampleColorImages=true",
        "-dDownsampleGrayImages=true",
        "-dDownsampleMonoImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        "-dGrayImageDownsampleType=/Bicubic",
        "-dMonoImageDownsampleType=/Subsample",
        f"-dColorImageResolution={dpi}",
        f"-dGrayImageResolution={dpi}",
        f"-dMonoImageResolution={dpi}",
        "-dColorImageFilter=/DCTEncode",
        "-dGrayImageFilter=/DCTEncode",
        "-sOutputFile=" + str(out_fp),
        str(in_fp),
    ]

    cp = subprocess.run(args, capture_output=True, text=True, creationflags=creationflags)
    if cp.returncode != 0:
        err = (cp.stderr or "").strip()
        out = (cp.stdout or "").strip()
        raise RuntimeError(f"Ghostscript 실패 (code={cp.returncode})\n\nSTDERR:\n{err}\n\nSTDOUT:\n{out}")


def compress_to_target(gs: str, in_fp: Path, out_fp: Path, target_bytes: int, max_tries: int) -> Tuple[int, bool]:
    presets = ["/ebook", "/screen"]
    dpis = [200, 170, 150, 130, 120, 110, 100, 90, 80]

    tries = 0
    last_size = -1

    for preset in presets:
        for dpi in dpis:
            tries += 1
            if tries > max_tries:
                break

            try:
                if out_fp.exists():
                    out_fp.unlink()
            except Exception:
                pass

            run_gs_compress(gs, in_fp, out_fp, preset, dpi)

            if not out_fp.exists():
                last_size = -1
                continue

            last_size = out_fp.stat().st_size
            if last_size <= target_bytes:
                return last_size, True

        if tries > max_tries:
            break

    return max(last_size, 0), False