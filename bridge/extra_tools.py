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


# 진행 상황 줄 앞에 붙이는 표시. Rust가 이 표시를 보고 결과가 아니라
# 화면에 바로 올릴 안내로 구분한다. (src-tauri/src/lib.rs 의 PROGRESS_PREFIX)
PROGRESS_PREFIX = "@@JBEDU_PROGRESS@@"


def emit_progress(text: Any) -> None:
    """진행 상황 한 줄을 지금 바로 내보낸다.

    모아 두었다가 끝에 돌려주면 오래 걸리는 작업에서 아무것도 안 보인다.
    줄바꿈이 섞이면 Rust가 여러 줄로 읽으므로 한 줄로 눌러 준다.
    """
    line = str(text).replace("\r", " ").replace("\n", " ").strip()
    if not line:
        return
    print(f"{PROGRESS_PREFIX}{line}", flush=True)


class FileCancel:
    """중지 신호 파일이 생기면 멈추라고 알리는 물건.

    도구는 threading.Event 처럼 is_set() 만 본다. 앱이 그 파일을 만들면
    도구가 하던 항목까지 마치고 스스로 멈춘다. 프로세스를 죽이는 것과 달리
    그때까지 모은 결과를 저장할 수 있다.
    """

    def __init__(self) -> None:
        self.path = os.environ.get("JBEDU_CANCEL_FILE", "").strip()

    def is_set(self) -> bool:
        return bool(self.path) and os.path.exists(self.path)


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
    if output_text:
        output_dir = Path(output_text).expanduser().resolve()
    else:
        # 저장 위치를 비워 두면 다운로드 폴더에 바로 만든다.
        # 예전에는 '게시글_취합' 폴더를 하나 더 만들어 파일을 찾기 번거로웠다.
        downloads = Path.home() / "Downloads"
        output_dir = downloads if downloads.is_dir() else Path.home()
    output_dir.mkdir(parents=True, exist_ok=True)
    download_files = bool(payload.get("download_files", False))

    # 저장할 이름은 긁기 전에 정한다. 예전에는 크롤링이 다 끝난 뒤에 이 줄을 만들다가
    # 실패해서, 오래 걸린 수집 결과가 통째로 버려졌다.
    stamp = service.make_timestamp()
    excel_path = output_dir / f"게시글_취합_{stamp}.xlsx"
    # 첨부 폴더에도 시각을 붙인다. 안 그러면 여러 번 돌릴 때 한 폴더에 뒤섞인다.
    attach_dir = output_dir / f"첨부파일_{stamp}" if download_files else None

    logs: list[str] = []
    start_page = int(payload.get("start_page") or 1)
    end_page = int(payload.get("end_page") or 1)
    max_posts = int(payload.get("max_posts") or 0)

    def note(text: Any) -> None:
        logs.append(str(text))
        emit_progress(text)

    def counted(collected: int) -> None:
        # 몇 건까지 왔는지 짚어 준다. 목표 건수가 있으면 함께 보여 준다.
        if max_posts:
            emit_progress(f"　　… {collected}/{max_posts}건 수집")
        else:
            emit_progress(f"　　… {collected}건 수집")

    emit_progress(f"게시판을 확인합니다. ({start_page}~{end_page}페이지)")
    result = service.crawl_board(
        board_url,
        start_page,
        end_page,
        max_posts,
        note,
        collect_body=bool(payload.get("collect_body", True)),
        download_files=download_files,
        attach_dir=attach_dir,
        cancel_event=FileCancel(),
        progress_func=counted,
    )
    emit_progress(
        "중지했습니다. 그때까지 모은 것만 저장합니다."
        if result.cancelled
        else f"수집을 마쳤습니다. 모두 {result.count}건."
    )
    if bool(payload.get("create_excel", True)):
        emit_progress("엑셀 파일로 정리하는 중...")
    if bool(payload.get("create_excel", True)):
        service.save_to_excel(result.headers, result.rows, result.errors, excel_path, board_url)
    return {
        "ok": True,
        "message": (
            f"중지했습니다. 그때까지 모은 게시글 {result.count}건, 첨부파일 {result.attach_count}개를 저장했습니다."
            if result.cancelled
            else f"게시글 {result.count}건, 첨부파일 {result.attach_count}개를 처리했습니다."
        ),
        "output": str(excel_path if excel_path.exists() else output_dir),
        "error_count": len(result.errors),
        "cancelled": result.cancelled,
        "attachment_count": result.attach_count,
        "logs": logs[-20:],
    }


def probe_homepage_board(payload: dict[str, Any]) -> dict[str, Any]:
    """주소를 한 번 열어 게시판을 제대로 찾는지, 끝 페이지가 몇 쪽인지 알려 준다.

    끝 페이지를 모르고 찍어 넣으면 헛돌거나 덜 가져온다. 미리 확인해서
    화면의 끝 페이지 칸까지 채워 준다.
    """
    board_url = str(payload.get("board_url") or "").strip()
    if not board_url.startswith(("http://", "https://")):
        raise ValueError("게시판 목록 URL을 입력하세요.")
    service = _module(
        "homepage_post_collector",
        "homepage_post_collector_service",
    )
    info = service.probe_board(board_url)

    lines = [str(info.get("message") or "").strip()]
    fill: dict[str, Any] = {}
    if info.get("ok"):
        headers = info.get("headers") or []
        if headers:
            lines.append(f"인식된 헤더: {', '.join(str(h) for h in headers)}")
        if info.get("title_column"):
            lines.append(f"제목 칸: {info['title_column']}")
        last_page = int(info.get("last_page") or 0)
        if last_page > 0:
            fill["end_page"] = last_page
            lines.append(f"끝 페이지를 {last_page}쪽으로 채웠습니다.")

    return {
        "ok": bool(info.get("ok")),
        "message": "\n".join(line for line in lines if line),
        "fill": fill,
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


def analyze_excel_split(payload: dict[str, Any]) -> dict[str, Any]:
    """분할 화면이 시트 목록·헤더·미리보기를 먼저 읽어오기 위한 조회 전용 동작."""
    service = _module("excel_split", "excel_split_service")
    sources = [path for path in _paths(payload) if path.is_file()]
    if len(sources) != 1:
        raise ValueError("분석할 엑셀 파일 하나를 선택하세요.")
    source = sources[0]

    info = service.analyze_workbook(source)
    sheets = [
        {
            "name": sheet.name,
            "max_row": sheet.max_row,
            "max_column": sheet.max_column,
            "auto_header_row": sheet.auto_header_row,
            "headers": list(sheet.headers),
        }
        for sheet in info.sheet_infos
    ]
    if not sheets:
        raise ValueError("읽을 수 있는 시트가 없습니다.")

    sheet_name = str(payload.get("sheet_name") or "").strip() or sheets[0]["name"]
    preview = service.preview_rows(source, sheet_name, max_rows=30, max_cols=20)

    return {
        "ok": True,
        "message": f"시트 {len(sheets)}개를 읽었습니다.",
        "csv_source": bool(info.csv_source),
        "sheets": sheets,
        "preview": preview,
        "preview_sheet": sheet_name,
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
    "excel_split__analyze": analyze_excel_split,
    "homepage_post_collector": run_homepage_collector,
    "homepage_post_collector__probe": probe_homepage_board,
}
