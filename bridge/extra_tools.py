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


def unique_path(path: Path, folder: bool = False) -> Path:
    """같은 이름이 이미 있으면 '이름(1).확장자', '이름(2).확장자' 처럼 번호를 붙인다.
    결과물이 기존 파일을 덮어쓰지 않게 한다. folder=True 면 확장자 없이 이름 뒤에 붙인다."""
    if not path.exists():
        return path
    for number in range(1, 10000):
        if folder:
            candidate = path.with_name(f"{path.name}({number})")
        else:
            candidate = path.with_name(f"{path.stem}({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"저장할 이름을 정하지 못했습니다: {path.name}")


def time_stamp() -> str:
    """결과 파일 이름에 붙이는 일시. 예: 20260922_1530"""
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M")


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
    service = _module(
        "empty_folder_cleaner",
        "services.empty_folder_cleaner_service",
    )
    # 고른 폴더 자체가 바로가기(정션·링크)면 경로를 풀면서 다른 곳이 기준 폴더가 된다.
    for raw in payload.get("inputs") or []:
        if service.is_link_or_junction(str(raw)):
            raise ValueError(f"바로가기(정션·링크) 폴더는 기준 폴더로 선택할 수 없습니다. 실제 폴더를 골라 주세요: {raw}")
    roots = [path for path in _paths(payload) if path.is_dir()]
    if len(roots) != 1:
        raise ValueError("정리할 기준 폴더 하나를 선택하세요.")
    scan = service.scan_empty_folders(
        roots[0],
        include_root=bool(payload.get("include_root", False)),
    )
    result = service.delete_empty_folders(scan.folders, root=scan.root_folder)
    message = f"빈 폴더 {result.deleted_count}개를 정리했습니다."
    failed = [
        {"name": Path(text.split(": ", 1)[0]).name, "error": f"지우지 못했습니다 ({text.split(': ', 1)[-1]})"}
        for text in result.errors
    ]
    if failed:
        message += f" {len(failed)}개는 지우지 못했습니다."
    return {
        "ok": True,
        "message": message,
        "scanned_count": len(scan.folders),
        "result": _plain(result),
        "failed": failed,
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
    failed = result.get("failed") or []
    message = "이수증 PDF 분리를 완료했습니다."
    if failed:
        message = (
            f"이수증 PDF {len(pdf_files)}개 중 {len(pdf_files) - len(failed)}개를 분리했습니다. "
            f"{len(failed)}개는 처리하지 못했습니다."
        )
    return {
        "ok": True,
        "message": message,
        "output": str(result.get("run_dir") or output_root),
        "result": _plain(result),
        "failed": _plain(failed),
    }


def run_certificate_renamer(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(payload.get("confirmed", False)):
        raise ValueError("원본 PDF 파일명 변경을 확인한 뒤 다시 실행하세요.")
    selected = _paths(payload)
    pdf_files = [
        path for path in selected if path.suffix.lower() == ".pdf"
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

    # 이름을 바꾸고 나면 화면이 들고 있는 경로는 더 이상 없는 파일을 가리킨다.
    # 그대로 두면 이어서 한 번 더 돌릴 때 "파일을 찾을 수 없습니다"가 뜬다.
    # rename_files 처럼 바뀐 이름으로 목록을 갈아 끼워 돌려준다.
    renamed = result.get("renamed") or {}
    updated: list[str] = []
    for path in selected:
        if path.exists():
            updated.append(str(path))
            continue
        candidate = renamed.get(str(path))
        if candidate and Path(candidate).exists():
            updated.append(str(candidate))

    failed = result.get("failed") or []
    message = "이수증 PDF 파일명 변경을 완료했습니다."
    if failed:
        message = (
            f"이수증 PDF {result.get('total', 0)}개 중 {result.get('changed', 0)}개의 파일명을 변경했습니다. "
            f"{len(failed)}개는 처리하지 못했습니다."
        )
    return {
        "ok": True,
        "message": message,
        "result": _plain(result),
        "inputs": updated,
        "failed": _plain(failed),
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
    # 목록 페이지를 하나도 열지 못했으면(인터넷·프록시·인증서 문제 등) '0건 성공'이 아니라 실패다.
    if not result.cancelled and not result.pages_opened and result.page_failures:
        raise RuntimeError(
            "게시판 페이지를 열지 못해 수집하지 못했습니다.\n\n이유: " + str(result.page_failures[0])
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

    # 저장 위치를 비우거나 폴더만 고르면 '엑셀병합_일시.xlsx' 로 새로 만든다.
    # 같은 이름을 계속 쓰면 다시 병합할 때마다 앞 결과를 덮어써 버린다.
    default_name = f"엑셀병합_{time_stamp()}.xlsx"
    output_text = str(payload.get("output") or "").strip()
    output_path = (
        Path(output_text).expanduser().resolve()
        if output_text
        else unique_path(sources[0].parent / default_name)
    )
    if output_path.is_dir():
        output_path = unique_path(output_path / default_name)
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
        header_overrides=_header_overrides(payload),
        excluded_sheets=_excluded_sheets(payload),
    )
    logs: list[str] = []
    result = service.merge_excel(options, logs.append)
    failed = list(getattr(result, "failed", []) or [])
    message = (
        f"시트 {result.sheet_count}개를 한 파일에 모았습니다."
        if mode == service.MODE_FILES_TO_SHEETS
        else f"시트 {result.sheet_count}개, 데이터 {result.data_row_count}행을 병합했습니다."
    )
    if failed:
        message += f" {len(failed)}개는 읽지 못해 넣지 않았습니다."
    return {
        "ok": True,
        "message": message,
        "failed": failed,
        "output": str(result.output_path),
        "skipped_count": result.skipped_count,
        "warnings": result.warnings[-30:],
        "logs": logs[-20:],
        "popup": _excel_merge_popup(service, mode, result, len(options.excluded_sheets)),
    }


def _header_overrides(payload: dict[str, Any]) -> dict:
    """화면에서 직접 고친 항목명 줄: [{file, sheet, header_row}] → {(file, sheet): row}"""
    result = {}
    for item in payload.get("header_overrides") or []:
        try:
            result[(str(Path(str(item["file"])).expanduser().resolve()), str(item["sheet"]))] = int(item["header_row"])
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _excluded_sheets(payload: dict[str, Any]) -> set:
    """화면에서 체크를 푼 시트: [{file, sheet}] → {(file, sheet)}"""
    result = set()
    for item in payload.get("excluded_sheets") or []:
        try:
            result.add((str(Path(str(item["file"])).expanduser().resolve()), str(item["sheet"])))
        except (KeyError, TypeError):
            continue
    return result


def _excel_merge_popup(service, mode: str, result, excluded_count: int = 0) -> dict[str, str]:
    what = (
        f"시트 {result.sheet_count}개를 한 파일에 모았습니다."
        if mode == service.MODE_FILES_TO_SHEETS
        else f"데이터 {result.data_row_count:,}행을 시트 {result.sheet_count}개로 병합했습니다."
    )
    lines = [what, f"저장 파일: {result.output_path.name}"]
    if excluded_count:
        lines.append(f"체크를 푼 시트 {excluded_count}개는 넣지 않았습니다.")
    if getattr(result, "formula_count", 0):
        lines.append(f"함수 {result.formula_count:,}개는 계산된 값으로 넣었습니다. (원본 파일은 그대로)")
    lines.append(("✔ " if result.verified else "⚠ ") + (result.verify_message or ""))
    if result.warnings:
        lines.append("")
        lines.append("확인할 점")
        lines.extend(f"· {text}" for text in result.warnings[:12])
        if len(result.warnings) > 12:
            lines.append(f"· 외 {len(result.warnings) - 12}건")
    problem = (not result.verified) or result.skipped_count > 0
    return {
        "level": "warning" if problem or result.warnings else "success",
        "title": "엑셀 병합을 마쳤습니다" if not problem else "엑셀 병합을 마쳤지만 확인이 필요합니다",
        "message": "\n".join(lines),
    }


def analyze_excel_merge(payload: dict[str, Any]) -> dict[str, Any]:
    """병합 전에 화면에 보여 줄 시트별 자동 헤더·위쪽 행·결과 미리보기. 파일은 만들지 않는다."""
    service = _module("excel_merge", "excel_merge_service")
    sources = [path for path in _paths(payload) if path.is_file()]
    info = service.analyze_merge(
        sources,
        str(payload.get("mode") or service.MODE_FILES_TO_SHEETS),
        include_hidden_sheets=bool(payload.get("include_hidden_sheets", False)),
        header_overrides=_header_overrides(payload),
        add_source_file=bool(payload.get("add_source_file", False)),
        add_source_sheet=bool(payload.get("add_source_sheet", False)),
        excluded_sheets=_excluded_sheets(payload),
    )
    return {"ok": True, "message": "", **info}


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

    # 화면(ExcelSplitPanel)은 '저장 폴더'를 폴더 고르기 창으로만 받는다. 그래서 output 은 늘 폴더다.
    # 이름에 점이 든 폴더('2026.03 자료')를 파일로 오해하지 않도록 확장자로 판단하지 않는다.
    output_text = str(payload.get("output") or "").strip()
    output_folder = (
        Path(output_text).expanduser().resolve()
        if output_text
        # 다시 분할해도 앞 결과를 덮어쓰지 않게 '이름_분할(1)' 처럼 새 폴더를 만든다.
        else unique_path(source.parent / f"{source.stem}_분할", folder=True)
    )
    if output_folder.is_file():
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


# 문서 개인정보 마스킹: 화면과 주고받는 모양은 도구 폴더(document_privacy_masker_service 의 app_*)가 정한다.
def run_document_privacy_masker(payload: dict[str, Any]) -> dict[str, Any]:
    service = _module("document_privacy_masker", "document_privacy_masker_service")
    return service.app_apply(payload, progress=emit_progress, cancel=FileCancel().is_set)


def analyze_document_privacy_masker(payload: dict[str, Any]) -> dict[str, Any]:
    service = _module("document_privacy_masker", "document_privacy_masker_service")
    return service.app_analyze(payload, progress=emit_progress)


def page_document_privacy_masker(payload: dict[str, Any]) -> dict[str, Any]:
    service = _module("document_privacy_masker", "document_privacy_masker_service")
    return service.app_page(payload)


# 한글 용량 압축: hwp·hwpx 안의 그림을 줄여 hwpx 로 저장한다.
# 방식: basic(기본 줄이기, 목표 용량 없음) · each(파일마다 목표 용량 이하) · total(전체 합계를 목표 용량 이하)
def run_hwp_compress(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = [path for path in _paths(payload) if path.suffix.lower() in (".hwp", ".hwpx")]
    if not inputs:
        raise ValueError("한글(hwp·hwpx) 파일을 선택하세요.")
    service = _module("hwp_compress", "hwp_compress_service")
    mode = str(payload.get("target_mode") or "basic")
    if mode not in service.MODES:
        mode = "basic"
    target_mb = 0.0
    if mode != "basic":
        try:
            target_mb = float(payload.get("target_mb") or 5)
        except (TypeError, ValueError):
            raise ValueError(
                f"'목표 용량(MB)' 칸에는 숫자를 입력하세요. (입력값: {payload.get('target_mb')})"
            ) from None
        if target_mb <= 0:
            raise ValueError("'목표 용량(MB)'은 0보다 크게 입력하세요.")
    raw_output = str(payload.get("output") or "").strip()
    folder = Path(raw_output).expanduser().resolve() if raw_output else None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)

    group = service.compress_files(
        inputs, mode, target_mb, folder, progress=emit_progress, cancel=FileCancel().is_set
    )
    results, failed = group["results"], group["failed"]
    if not results and not group["stopped"]:
        raise ValueError(
            "용량을 줄인 파일이 없습니다.\n\n"
            + "\n".join(f"· {item['name']}: {item['error']}" for item in failed)
        )
    if mode == "total" and results:
        message = f"한글 파일 {len(results)}개를 합계 {group['final_total'] / 1048576:.2f}MB로 저장했습니다."
    elif failed:
        message = f"한글 파일 {len(inputs)}개 중 {len(results)}개를 줄였습니다. {len(failed)}개는 처리하지 못했습니다."
    else:
        message = f"한글 파일 {len(results)}개의 용량을 줄였습니다."
    if group["stopped"]:
        message = "중지 요청으로 멈췄습니다. " + message
    output = group.get("folder") or str(
        folder or (Path(results[0]["output"]).parent if results else inputs[0].parent)
    )
    return {
        "ok": True,
        "message": message,
        "output": output,
        "results": results,
        "failed": failed,
        "stopped": group["stopped"],
        "popup": _hwp_compress_popup(group),
    }


def _hwp_compress_line(item: dict[str, Any], target_mb: float) -> str:
    before, after = item["original_bytes"] / 1048576, item["output_bytes"] / 1048576
    if item["output_bytes"] < item["original_bytes"]:
        change = f"{(1 - item['output_bytes'] / max(item['original_bytes'], 1)) * 100:.0f}% 줄임"
    else:
        change = "줄지 않음"
    if target_mb and item.get("target_reached") is not None:
        change += ", 달성" if item["target_reached"] else ", 미달"
    line = f"· {item['name']}\n   {before:.2f}MB → {after:.2f}MB ({change})"
    notes = []
    if item.get("converted"):
        notes.append("hwp를 hwpx로 바꿔 저장")
    if item.get("images_total"):
        notes.append(f"그림 {item['images_total']}개 중 {item['images_reduced']}개 줄임")
    if item.get("note"):
        notes.append(item["note"])
    if notes:
        line += "\n   " + " · ".join(notes)
    return line


def _hwp_compress_popup(group: dict[str, Any]) -> dict[str, str]:
    results, failed, stopped = group["results"], group["failed"], group["stopped"]
    mode, target = group["mode"], group.get("target_mb") or 0
    body = "\n".join(_hwp_compress_line(item, target) for item in results)
    fail_lines = "".join(f"\n· {item['name']}: {item['error']}" for item in failed)
    tail = ("\n\n" + body if body else "") + ("\n\n처리하지 못한 파일" + fail_lines if failed else "")
    summary = ""
    if mode == "total" and results:
        summary = (
            f"합계 {group['original_total'] / 1048576:.2f}MB → {group['final_total'] / 1048576:.2f}MB"
            f" (목표 {target:g}MB)\n저장 폴더: {group['folder']}"
        )
    if stopped:
        head = (f"중지 요청으로 멈췄습니다. 지금까지 줄인 결과로 한글 파일 {len(results)}개를 저장했습니다."
                if results else "중지 요청으로 멈춰 저장한 파일이 없습니다.")
        if group.get("skipped"):
            head += f"\n나머지 {group['skipped']}개는 처리하지 않았습니다."
        return {"level": "warning", "title": "압축을 중지했습니다",
                "message": (summary + "\n" if summary else "") + head + tail}
    if mode == "total":
        if group["achieved"]:
            return {"level": "warning" if failed else "success", "title": "합계 목표 용량으로 줄였습니다",
                    "message": summary + tail}
        return {"level": "warning", "title": "합계 목표 용량까지 줄이지 못했습니다",
                "message": summary + f"\n가장 작게 줄여도 합계 {group['final_total'] / 1048576:.2f}MB입니다."
                " 그림이 적고 글자·표 위주인 파일은 더 줄지 않습니다." + tail}
    missed = [item for item in results if item.get("target_reached") is False]
    if failed or missed:
        head = []
        if missed:
            head.append(f"{len(missed)}개는 가장 작게 줄여도 목표 {target:g}MB보다 큽니다."
                        " 그림이 적고 글자·표 위주인 파일은 더 줄지 않습니다.")
        if failed:
            head.append(f"{len(failed)}개는 처리하지 못했습니다.")
        return {"level": "warning",
                "title": "목표 용량까지 줄이지 못했습니다" if missed else "일부 파일을 처리하지 못했습니다",
                "message": "\n".join(head) + tail}
    head = f"파일마다 {target:g}MB 이하로 줄였습니다.\n\n" if mode == "each" else ""
    return {"level": "success", "title": "한글 용량을 줄였습니다",
            "message": head + body + "\n\n결과 파일을 열어 글·표·그림이 제대로 보이는지 확인해 주세요."}


EXTRA_HANDLERS = {
    "certificate_pdf_renamer": run_certificate_renamer,
    "certificate_pdf_splitter": run_certificate_splitter,
    "document_privacy_masker": run_document_privacy_masker,
    "document_privacy_masker__analyze": analyze_document_privacy_masker,
    "document_privacy_masker__page": page_document_privacy_masker,
    "empty_folder_cleaner": run_empty_folder_cleaner,
    "excel_merge": run_excel_merge,
    "excel_merge__analyze": analyze_excel_merge,
    "excel_split": run_excel_split,
    "excel_split__analyze": analyze_excel_split,
    "homepage_post_collector": run_homepage_collector,
    "homepage_post_collector__probe": probe_homepage_board,
    "hwp_compress": run_hwp_compress,
}
