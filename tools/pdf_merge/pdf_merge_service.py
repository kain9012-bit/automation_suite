from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

SUPPORTED_EXTS = {".pdf"}


def is_pdf(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in SUPPORTED_EXTS


def list_pdf_files_in_folder(folder: Path) -> list[Path]:
    return sorted([p.resolve() for p in folder.iterdir() if is_pdf(p)])


def merge_pdfs(file_paths: list[Path], output_path: str | Path):
    """
    - 입력: PDF 목록(사용자 순서)
    - 출력: 병합된 단일 PDF
    - 암호/손상 파일은 실패 처리
    """
    if not file_paths:
        raise ValueError("취합할 PDF 파일이 없습니다.")

    files = [Path(p).resolve() for p in file_paths if Path(p).exists() and Path(p).suffix.lower() == ".pdf"]
    if not files:
        raise ValueError("취합할 PDF 파일이 없습니다(존재하는 파일이 없음).")

    writer = PdfWriter()

    ok_files: list[str] = []
    bad_files: list[tuple[str, str]] = []

    for fp in files:
        try:
            reader = PdfReader(str(fp))

            if getattr(reader, "is_encrypted", False):
                try:
                    if reader.decrypt("") == 0:
                        raise RuntimeError("암호화된 PDF(비밀번호 필요)")
                except Exception:
                    raise RuntimeError("암호화된 PDF(비밀번호 필요)")

            for page in reader.pages:
                writer.add_page(page)

            ok_files.append(fp.name)

        except Exception as e:
            bad_files.append((fp.name, str(e)))

    if len(writer.pages) == 0:
        msg = "병합할 페이지가 없습니다.\n"
        if bad_files:
            msg += "\n[실패 파일]\n" + "\n".join([f"- {n}: {err}" for n, err in bad_files[:10]])
            if len(bad_files) > 10:
                msg += f"\n... 외 {len(bad_files) - 10}건"
        raise RuntimeError(msg)

    out_path = Path(output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "wb") as f:
        writer.write(f)

    return ok_files, bad_files