from __future__ import annotations

import dataclasses
import importlib
import os
import sys
from pathlib import Path
from typing import Any


TOOLS_ROOT = Path(
    os.environ.get("JBEDU_TOOLS_ROOT")
    or Path(__file__).resolve().parent.parent / "tools"
).resolve()


def _module(tool_id: str, module_name: str):
    tool_root = TOOLS_ROOT / tool_id
    if str(tool_root) not in sys.path:
        sys.path.insert(0, str(tool_root))
    return importlib.import_module(module_name)


def _paths(payload: dict[str, Any]) -> list[Path]:
    paths = [
        Path(str(value)).expanduser().resolve()
        for value in payload.get("inputs") or []
    ]
    if not paths:
        raise ValueError("처리 대상을 선택하세요.")
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"파일 또는 폴더를 찾을 수 없습니다: {path}")
    return paths


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return value


def run_empty_folder_cleaner(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(payload.get("confirmed", False)):
        raise ValueError("빈 폴더 삭제 작업을 확인한 뒤 다시 실행하세요.")
    roots = [path for path in _paths(payload) if path.is_dir()]
    if len(roots) != 1:
        raise ValueError("정리할 기준 폴더 하나를 선택하세요.")
    service = _module(
        "empty_folder_cleaner",
        "services.empty_folder_cleaner_service",
    )
    scan = service.scan_empty_folders(
        roots[0],
        include_root=bool(payload.get("include_root", False)),
    )
    result = service.delete_empty_folders(scan.folders)
    return {
        "ok": True,
        "message": f"빈 폴더 {result.deleted_count}개를 정리했습니다.",
        "scanned_count": len(scan.folders),
        "result": _plain(result),
    }


def _certificate_fields(payload: dict[str, Any]) -> list[str]:
    value = str(payload.get("filename_fields") or "과정명,성명,근무기관")
    fields = [item.strip() for item in value.split(",") if item.strip()]
    if not fields:
        raise ValueError("파일명에 사용할 항목을 하나 이상 입력하세요.")
    return fields


def run_certificate_splitter(payload: dict[str, Any]) -> dict[str, Any]:
    pdf_files = [
        path for path in _paths(payload) if path.suffix.lower() == ".pdf"
    ]
    output_text = str(payload.get("output") or "").strip()
    output_root = (
        Path(output_text).expanduser().resolve()
        if output_text
        else pdf_files[0].parent
    )
    output_root.mkdir(parents=True, exist_ok=True)
    service = _module(
        "certificate_pdf_splitter",
        "services.splitter_service",
    )
    result = service.split_certificate_pdfs(
        pdf_files,
        output_root,
        _certificate_fields(payload),
        str(payload.get("delimiter") or "_"),
    )
    return {
        "ok": True,
        "message": f"이수증 PDF 분리를 완료했습니다.",
        "output": str(result.get("run_dir") or output_root),
        "result": _plain(result),
    }


def run_certificate_renamer(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(payload.get("confirmed", False)):
        raise ValueError("원본 PDF 파일명 변경을 확인한 뒤 다시 실행하세요.")
    pdf_files = [
        path for path in _paths(payload) if path.suffix.lower() == ".pdf"
    ]
    service = _module(
        "certificate_pdf_renamer",
        "services.renamer_service",
    )
    result = service.rename_certificate_pdfs(
        pdf_files,
        _certificate_fields(payload),
        str(payload.get("delimiter") or "_"),
    )
    return {
        "ok": True,
        "message": f"이수증 PDF 파일명 변경을 완료했습니다.",
        "result": _plain(result),
    }


def run_homepage_collector(payload: dict[str, Any]) -> dict[str, Any]:
    board_url = str(payload.get("board_url") or "").strip()
    if not board_url.startswith(("http://", "https://")):
        raise ValueError("게시판 목록 URL을 입력하세요.")
    service = _module(
        "homepage_post_collector",
        "homepage_post_collector_service",
    )
    output_text = str(payload.get("output") or "").strip()
    output_dir = (
        Path(output_text).expanduser().resolve()
        if output_text
        else Path.home() / "Downloads" / "게시글_취합"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    download_files = bool(payload.get("download_files", False))
    attach_dir = output_dir / "첨부파일" if download_files else None
    logs: list[str] = []
    result = service.crawl_board(
        board_url,
        int(payload.get("start_page") or 1),
        int(payload.get("end_page") or 1),
        int(payload.get("max_posts") or 0),
        logs.append,
        collect_body=bool(payload.get("collect_body", True)),
        download_files=download_files,
        attach_dir=attach_dir,
    )
    excel_path = output_dir / f"게시글_취합_{service.make_timestamp()}.xlsx"
    if bool(payload.get("create_excel", True)):
        service.save_to_excel(result.headers, result.rows, result.errors, excel_path, board_url)
    return {
        "ok": True,
        "message": f"게시글 {result.count}건, 첨부파일 {result.attach_count}개를 처리했습니다.",
        "output": str(excel_path if excel_path.exists() else output_dir),
        "error_count": len(result.errors),
        "cancelled": result.cancelled,
        "attachment_count": result.attach_count,
        "logs": logs[-20:],
    }


def run_excel_merge(payload: dict[str, Any]) -> dict[str, Any]:
    service = _module("excel_merge", "excel_merge_service")
    sources = [path for path in _paths(payload) if path.is_file()]
    if not sources:
        raise ValueError("병합할 엑셀 파일을 선택하세요.")

    output_text = str(payload.get("output") or "").strip()
    output_path = (
        Path(output_text).expanduser().resolve()
        if output_text
        else sources[0].parent / f"병합_{sources[0].stem}.xlsx"
    )
    if output_path.is_dir():
        output_path = output_path / f"병합_{sources[0].stem}.xlsx"
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")

    mode = str(payload.get("mode") or service.MODE_FILES_TO_SHEETS)
    options = service.MergeOptions(
        mode=mode,
        source_paths=sources,
        output_path=output_path,
        add_source_file=bool(payload.get("add_source_file", False)),
        add_source_sheet=bool(payload.get("add_source_sheet", False)),
        include_hidden_sheets=bool(payload.get("include_hidden_sheets", False)),
    )
    logs: list[str] = []
    result = service.merge_excel(options, logs.append)
    return {
        "ok": True,
        "message": f"시트 {result.sheet_count}개, 데이터 {result.data_row_count}행을 병합했습니다.",
        "output": str(result.output_path),
        "skipped_count": result.skipped_count,
        "warnings": result.warnings[-10:],
        "logs": logs[-20:],
    }


def run_excel_split(payload: dict[str, Any]) -> dict[str, Any]:
    service = _module("excel_split", "excel_split_service")
    sources = [path for path in _paths(payload) if path.is_file()]
    if len(sources) != 1:
        raise ValueError("분할할 엑셀 파일 하나를 선택하세요.")
    source = sources[0]

    output_text = str(payload.get("output") or "").strip()
    output_folder = (
        Path(output_text).expanduser().resolve()
        if output_text
        else source.parent / f"{source.stem}_분할"
    )
    if output_folder.suffix:
        output_folder = output_folder.parent

    options = service.SplitOptions(
        mode=str(payload.get("mode") or service.MODE_SHEET),
        source_path=source,
        output_folder=output_folder,
        sheet_name=str(payload.get("sheet_name") or ""),
        header_row=int(payload.get("header_row") or 1),
        split_column=int(payload.get("split_column") or 1),
        rows_per_file=int(payload.get("rows_per_file") or 1000),
        skip_empty_key=bool(payload.get("skip_empty_key", True)),
    )
    logs: list[str] = []
    result = service.split_excel(options, logs.append)
    return {
        "ok": True,
        "message": f"파일 {result.created_count}개로 분할했습니다.",
        "output": str(result.output_folder or output_folder),
        "error_count": len(result.errors),
        "errors": result.errors[-10:],
        "logs": logs[-20:],
    }


EXTRA_HANDLERS = {
    "certificate_pdf_renamer": run_certificate_renamer,
    "certificate_pdf_splitter": run_certificate_splitter,
    "empty_folder_cleaner": run_empty_folder_cleaner,
    "excel_merge": run_excel_merge,
    "excel_split": run_excel_split,
    "homepage_post_collector": run_homepage_collector,
}
