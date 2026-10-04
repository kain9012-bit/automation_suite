from __future__ import annotations

import argparse
import base64
import dataclasses
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from extra_tools import EXTRA_HANDLERS, FileCancel, emit_progress, time_stamp, unique_path

# Windows 기본 코드페이지로 나가면 한글 메시지가 앱에서 깨진다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


PROJECT_ROOT = Path(
    os.environ.get("JBEDU_PROJECT_ROOT") or Path(__file__).resolve().parent.parent
).resolve()
TOOLS_ROOT = Path(
    os.environ.get("JBEDU_TOOLS_ROOT") or PROJECT_ROOT / "tools"
).resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _module(tool_id: str, module_name: str):
    tool_root = TOOLS_ROOT / tool_id
    if str(tool_root) not in sys.path:
        sys.path.insert(0, str(tool_root))
    return importlib.import_module(module_name)


def _paths(payload: dict[str, Any]) -> list[Path]:
    values = payload.get("inputs") or []
    if not isinstance(values, list):
        raise ValueError("입력 파일 목록 형식이 올바르지 않습니다.")
    paths = [Path(str(value)).expanduser().resolve() for value in values]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"파일 또는 폴더를 찾을 수 없습니다: {missing[0]}")
    if not paths:
        raise ValueError("처리할 파일 또는 폴더를 선택하세요.")
    return paths


def _expand(paths: list[Path], suffixes: set[str], recursive: bool) -> list[Path]:
    """폴더를 골랐을 때 안쪽 파일까지 찾아 준다. recursive면 하위 폴더도 훑는다."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            found.extend(
                child
                for child in sorted(path.glob(pattern))
                if child.is_file() and child.suffix.lower() in suffixes
            )
        elif path.suffix.lower() in suffixes:
            found.append(path)
    return found


def _output_path(
    payload: dict[str, Any],
    inputs: list[Path],
    default_name: str,
    *,
    directory: bool = False,
) -> Path:
    raw = str(payload.get("output") or "").strip()
    if raw:
        output = Path(raw).expanduser().resolve()
    else:
        base = inputs[0] if inputs[0].is_dir() else inputs[0].parent
        # 기본 이름으로 저장할 때 같은 이름이 있으면 번호를 붙여 덮어쓰지 않는다.
        # (직접 고른 파일은 저장 창에서 이미 덮어쓸지 물어보므로 그대로 둔다.)
        output = base if directory else unique_path(base / default_name)
    if directory:
        output.mkdir(parents=True, exist_ok=True)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {key: _plain(item) for key, item in dataclasses.asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return value


def _success(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **{k: _plain(v) for k, v in extra.items()}}


def run_hwp_collector(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    output = _output_path(payload, inputs, f"한글취합_{time_stamp()}.hwpx")
    service = _module("hwp_collector", "hwp_collector_service")
    result = service.merge_han_files(
        inputs, output, progress=emit_progress, cancel=FileCancel().is_set
    )
    failed = result["failed"]
    stopped = bool(result["stopped"])
    if not result["saved"]:
        return _success("중지했습니다. 취합한 파일이 없어 저장하지 않았습니다.", stopped=True, failed=failed)
    if not failed and not stopped:
        return _success("한글 문서 취합을 완료했습니다.", output=output, failed=[])
    count = len(result["inserted"])
    message = (
        f"중지했습니다. 그때까지 넣은 한글 문서 {count}개만 취합했습니다."
        if stopped
        else f"한글 문서 {count}개를 취합했습니다."
    )
    if failed:
        message += f" {len(failed)}개는 넣지 못해 빠졌습니다."
    lines = "".join(f"\n· {item['name']}: {item['error']}" for item in failed)
    return _success(
        message,
        output=output,
        failed=failed,
        stopped=stopped,
        popup={
            "level": "warning",
            "title": "일부 파일만 취합했습니다",
            "message": message + f"\n\n저장 위치: {output}" + (f"\n\n빠진 파일{lines}" if lines else ""),
        },
    )


def run_multi_format_pdf_combiner(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    output = _output_path(payload, inputs, f"PDF통합_{time_stamp()}.pdf")
    service = _module(
        "multi_format_pdf_combiner", "multi_format_pdf_combiner_service"
    )
    converted: list[Path] = []
    names: list[str] = []
    failed: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="jbedu_pdf_") as temp_name:
        temp_dir = Path(temp_name)
        for index, source in enumerate(inputs, start=1):
            if len(inputs) > 1:
                emit_progress(f"[{index}/{len(inputs)}] {source.name}")
            pdf_path, error = service.ensure_pdf(source, temp_dir, progress=emit_progress)
            if pdf_path:
                converted.append(pdf_path)
                names.append(source.name)
            else:
                failed.append({"name": source.name, "error": error or "PDF로 바꾸지 못했습니다."})
                emit_progress(f"{source.name}: 처리하지 못했습니다 ({error or '변환 실패'})")
        if not converted:
            raise RuntimeError(
                "PDF로 합칠 수 있는 파일이 없습니다.\n\n"
                + "\n".join(f"· {item['name']}: {item['error']}" for item in failed)
            )
        try:
            ok_files, merge_errors = service.merge_pdf_ordered(converted, output, names)
        except RuntimeError as error:
            # 합칠 쪽이 하나도 없을 때: 앞에서 변환하지 못한 파일도 함께 알린다.
            lines = [f"· {item['name']}: {item['error']}" for item in failed]
            raise RuntimeError(str(error) + ("\n" + "\n".join(lines) if lines else "")) from error
    failed.extend({"name": name, "error": reason} for name, reason in merge_errors)
    # 넣은 순서대로 실패 목록을 보여 준다.
    order = {path.name: position for position, path in enumerate(inputs)}
    failed.sort(key=lambda item: order.get(item["name"], len(order)))
    if failed:
        message = (
            f"문서 {len(inputs)}개 중 {len(ok_files)}개를 PDF로 통합했습니다. "
            f"{len(failed)}개는 처리하지 못했습니다."
        )
    else:
        message = f"문서 {len(ok_files)}개를 PDF로 통합했습니다."
    return _success(message, output=output, failed=failed)


def run_certificate_pdf_collector(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = [path for path in _paths(payload) if path.suffix.lower() == ".pdf"]
    service = _module(
        "certificate_pdf_collector", "certificate_pdf_collector_service"
    )
    good, bad, errors = service.process_pdfs(inputs)
    output = _output_path(payload, inputs, "이수증_취합결과.xlsx")
    service.save_result_excel(output, good, bad, errors)
    failed = [
        {"name": str(row.get("파일명", "")), "error": str(row.get("에러메시지", ""))}
        for row in errors.to_dict("records")
    ]
    rows = len(good) + len(bad)
    if failed:
        message = (
            f"이수증 PDF {len(inputs)}개 중 {len(inputs) - len(failed)}개에서 이수증 {rows}건을 읽었습니다. "
            f"{len(failed)}개는 처리하지 못했습니다."
        )
    elif rows != len(inputs):
        message = f"이수증 PDF {len(inputs)}개에서 이수증 {rows}건을 분석했습니다."
    else:
        message = f"이수증 {len(inputs)}개를 분석했습니다."
    return _success(
        message,
        output=output,
        valid_count=len(good),
        review_count=len(bad),
        error_count=len(errors),
        failed=failed,
    )


def run_hwp_to_pdf(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    output_dir = _output_path(payload, inputs, "", directory=True)
    service = _module("hwp_to_pdf_converter", "hwp_to_pdf_converter_service")
    ok_files, bad_files = service.convert_files(
        inputs, output_dir, progress=emit_progress, cancel=FileCancel().is_set
    )
    failed = [{"name": name, "error": error} for name, error in bad_files]
    # 중지하면 남은 파일은 손대지 않으므로 성공+실패 수가 입력 수보다 적다.
    stopped = len(ok_files) + len(bad_files) < len(inputs)
    lines = "".join(f"\n· {item['name']}: {item['error']}" for item in failed)
    if not ok_files and failed and not stopped:
        raise RuntimeError("PDF로 변환하지 못했습니다.\n" + lines)
    message = f"{len(ok_files)}개 파일을 PDF로 변환했습니다."
    if failed:
        message += f" {len(failed)}개는 변환하지 못했습니다."
    if stopped:
        message = "중지했습니다. " + message
    extra: dict[str, Any] = {}
    if failed or stopped:
        extra["popup"] = {
            "level": "warning",
            "title": "일부 파일만 변환했습니다",
            "message": message + f"\n\n저장 위치: {output_dir}" + (f"\n\n변환하지 못한 파일{lines}" if lines else ""),
        }
    return _success(message, output=output_dir, failed=failed, stopped=stopped, **extra)


def run_hwp_to_hwpx(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _expand(_paths(payload), {".hwp"}, bool(payload.get("recursive", True)))
    if not inputs:
        raise ValueError("변환할 한글(.hwp) 파일을 찾지 못했습니다.")
    service = _module("hwp_to_hwpx_converter", "hwp_to_hwpx_converter_service")
    result = service.convert_hwp_files_to_hwpx(
        inputs,
        visible=bool(payload.get("visible", False)),
        log=emit_progress,
        cancel=FileCancel().is_set,
    )
    failed = [
        {
            "name": item.source_path.name,
            "error": (str(item.error).strip().splitlines() or ["변환 실패"])[0][:200],
        }
        for item in result.results
        if not item.success
    ]
    if not failed and not result.stopped and not result.delete_fail_count:
        return _success("HWPX 변환 작업을 완료했습니다.", result=result, failed=[])
    converted = result.success_count + result.delete_fail_count
    message = f"{converted}개 파일을 HWPX로 변환했습니다."
    if failed:
        message += f" {len(failed)}개는 변환하지 못했습니다(원본 그대로 둠)."
    if result.delete_fail_count:
        message += f" {result.delete_fail_count}개는 원본 HWP를 지우지 못했습니다."
    if result.stopped:
        message = "중지했습니다. " + message
    lines = "".join(f"\n· {item['name']}: {item['error']}" for item in failed)
    return _success(
        message,
        result=result,
        failed=failed,
        stopped=result.stopped,
        popup={
            "level": "warning",
            "title": "일부 파일만 변환했습니다" if failed or result.stopped else "원본을 지우지 못한 파일이 있습니다",
            "message": message + (f"\n\n변환하지 못한 파일{lines}" if lines else ""),
        },
    )


def _whole_number(payload: dict[str, Any], key: str, label: str, default: int) -> int:
    """숫자 칸 값을 정수로. 비었으면 기본값, 숫자가 아니면 한국어로 알린다."""
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"'{label}' 칸에는 숫자를 입력하세요. (입력값: {value})") from None
    if number != int(number):
        raise ValueError(f"'{label}' 칸에는 소수점 없는 숫자를 입력하세요. (입력값: {value})")
    return int(number)


def run_pdf_page_number(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    if len(inputs) != 1:
        raise ValueError("페이지 번호를 넣을 PDF 파일 하나를 선택하세요.")
    service = _module("pdf_page_number_adder", "pdf_page_number_adder_service")
    start_page = _whole_number(payload, "start_page", "시작 페이지", 1) or 1
    start_number = _whole_number(payload, "start_number", "시작 번호", 1)
    font_size = _whole_number(payload, "font_size", "글자 크기", 10) or 10
    if start_page < 1:
        raise ValueError("'시작 페이지'는 1 이상으로 입력하세요.")
    if font_size < 1:
        raise ValueError("'글자 크기'는 1 이상으로 입력하세요.")
    output = _output_path(payload, inputs, f"{inputs[0].stem}_페이지번호.pdf")
    try:
        result = service.add_page_numbers(
            inputs[0],
            output,
            str(payload.get("format_type") or "숫자"),
            start_page,
            start_number,
            str(payload.get("position") or "하단 가운데"),
            str(payload.get("font_name") or "굴림체"),
            font_size,
        )
    except Exception as error:
        raise RuntimeError(
            f"{inputs[0].name}: {service.describe_pdf_error(error)}"
        ) from error
    return _success("페이지 번호를 추가했습니다.", output=result)


def run_pdf_organizer(payload: dict[str, Any]) -> dict[str, Any]:
    # 미리보기 편집 화면은 페이지 순서(sequence)를 통째로 넘긴다.
    if payload.get("sequence") is not None:
        return _run_pdf_organizer_sequence(payload)
    inputs = _paths(payload)
    if len(inputs) != 1:
        raise ValueError("정리할 PDF 파일 하나를 선택하세요.")
    action = str(payload.get("action") or "").strip()
    if action not in {"extract", "delete", "reorder", "split"}:
        raise ValueError("페이지 작업 종류(추출/삭제/재배열/분할)를 선택하세요.")
    service = _module("pdf_page_organizer", "pdf_page_organizer_service")
    output_dir = _output_path(payload, inputs, "", directory=True)
    mode = str(payload.get("mode") or "")
    spec = str(payload.get("spec") or "")
    try:
        if action == "extract":
            result = service.run_extract(inputs[0], output_dir, mode or "pages", spec)
        elif action == "delete":
            result = service.run_delete(inputs[0], output_dir, mode or "pages", spec)
        elif action == "reorder":
            result = service.run_reorder(
                inputs[0],
                output_dir,
                mode or "sequence",
                spec,
                _whole_number(payload, "source_page", "옮길 페이지", 1),
                _whole_number(payload, "target_page", "옮길 위치", 1),
            )
        else:
            result = service.run_split(
                inputs[0],
                output_dir,
                mode or "every_n",
                _whole_number(payload, "number", "페이지 수", 1),
                spec,
                bool(payload.get("zip_output", False)),
            )
    except Exception as error:
        raise RuntimeError(service.pdf_error_message(error, inputs[0].name)) from error
    return _success("PDF 페이지 작업을 완료했습니다.", output=result)


def _run_pdf_organizer_sequence(payload: dict[str, Any]) -> dict[str, Any]:
    sequence = payload.get("sequence") or []
    if not isinstance(sequence, list) or not sequence:
        raise ValueError("저장할 페이지가 없습니다.")
    first = Path(str(sequence[0].get("path") or "")).expanduser().resolve()
    if not first.exists():
        raise FileNotFoundError(f"원본 PDF 를 찾을 수 없습니다: {first}")
    service = _module("pdf_page_organizer", "pdf_page_organizer_service")
    output_dir = _output_path(payload, [first], "", directory=True)
    save_mode = str(payload.get("save_mode") or "single")
    try:
        outputs = service.save_sequence(
            sequence,
            output_dir,
            save_mode,
            _whole_number(payload, "number", "페이지 수", 1),
            bool(payload.get("zip_output", False)),
        )
    except Exception as error:
        raise RuntimeError(service.pdf_error_message(error, first.name)) from error
    pdfs = [path for path in outputs if path.suffix.lower() == ".pdf"]
    names = "\n".join(f"· {path.name}" for path in outputs[:12])
    if len(outputs) > 12:
        names += f"\n· 외 {len(outputs) - 12}개"
    return _success(
        f"PDF {len(pdfs)}개를 저장했습니다. ({len(sequence)}쪽)",
        output=str(output_dir),
        outputs=[{"path": path} for path in outputs],
        popup={
            "level": "success",
            "title": "PDF를 저장했습니다",
            "message": f"{len(sequence)}쪽을 PDF {len(pdfs)}개로 저장했습니다.\n저장 폴더: {output_dir}\n\n{names}",
        },
    )


def load_pdf_organizer(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = [path for path in _paths(payload) if path.suffix.lower() == ".pdf"]
    if not inputs:
        raise ValueError("PDF 파일을 선택하세요.")
    service = _module("pdf_page_organizer", "pdf_page_organizer_service")
    documents = service.load_documents(inputs, progress=emit_progress, cancel=FileCancel().is_set)
    return _success(f"PDF {len(documents)}개를 불러왔습니다.", documents=documents)


def preview_pdf_organizer(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    service = _module("pdf_page_organizer", "pdf_page_organizer_service")
    try:
        image = service.render_preview(inputs[0], _whole_number(payload, "page", "페이지", 0))
    except Exception as error:
        raise RuntimeError(service.pdf_error_message(error, inputs[0].name)) from error
    return _success("", **image)


def run_file_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    if len(inputs) != 1 or not inputs[0].is_dir():
        raise ValueError("현황표를 만들 폴더 하나를 선택하세요.")
    service = _module("file_inventory", "file_inventory_service")
    extensions = service.parse_extension_filter(str(payload.get("extensions") or ""))
    inventory = service.collect_inventory(
        inputs[0],
        bool(payload.get("recursive", True)),
        str(payload.get("target_mode") or "파일+폴더"),
        extensions,
        bool(payload.get("exclude_office_temp", True)),
    )
    output = _output_path(payload, inputs, "파일_폴더_현황표.xlsx")
    service.save_inventory_excel(
        output,
        inputs[0],
        inventory,
        "Tauri 통합 화면에서 생성",
    )
    message = f"항목 {len(inventory.rows)}개를 현황표로 저장했습니다."
    failed = [
        {"name": Path(str(item.get("path", ""))).name or str(item.get("path", "")), "error": str(item.get("error", ""))}
        for item in inventory.errors
    ]
    if failed:
        message += f" 읽지 못한 항목 {len(failed)}개는 '오류_기록' 시트에 적었습니다."
    return _success(
        message,
        output=output,
        error_count=len(inventory.errors),
        failed=failed,
    )


def run_folder_unpacker(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(payload.get("confirmed", False)):
        raise ValueError("파일 이동 작업을 확인한 뒤 다시 실행하세요.")
    service = _module("folder_unpacker", "folder_unpacker_service")
    # 고른 폴더 자체가 바로가기(정션·링크)면 경로를 풀면서 엉뚱한 곳이 대상이 된다.
    for raw in payload.get("inputs") or []:
        if service.is_link_or_junction(str(raw)):
            raise ValueError(f"바로가기(정션·링크) 폴더는 선택할 수 없습니다. 실제 폴더를 골라 주세요: {raw}")
    folders = [path for path in _paths(payload) if path.is_dir()]
    result = service.unpack_folders(
        folders,
        recursive=bool(payload.get("recursive", True)),
        prefix_folder=bool(payload.get("prefix_folder", False)),
    )
    message = f"파일 {result.moved_count}개를 상위 폴더로 이동했습니다."
    if result.failed:
        message += f" {len(result.failed)}개는 옮기지 못했습니다."
    return _success(
        message,
        result=result,
        failed=result.failed,
        **({"popup": _failed_popup(message, result.failed)} if result.failed else {}),
    )


def _failed_popup(message: str, failed: list[dict[str, str]], title: str = "일부 항목을 처리하지 못했습니다") -> dict[str, str]:
    """일부 실패가 있을 때 띄울 경고 팝업. 실패 항목과 이유를 적는다."""
    lines = [f"· {item['name']}: {item['error']}" for item in failed[:15]]
    if len(failed) > 15:
        lines.append(f"· 외 {len(failed) - 15}개")
    return {"level": "warning", "title": title, "message": message + "\n\n" + "\n".join(lines)}


def run_rename_files(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(payload.get("confirmed", False)):
        raise ValueError("파일명 변경 작업을 확인한 뒤 다시 실행하세요.")
    files = [path for path in _paths(payload) if path.is_file()]
    service = _module("rename_files", "rename_files_service")
    mode = str(payload.get("mode") or service.MODE_REPLACE)
    before = str(payload.get("before") or "")
    after = str(payload.get("after") or "")
    if mode == service.MODE_REPLACE and not before:
        raise ValueError("바꿀 문자열을 입력하세요.")
    # 새 이름을 쓸 수 없는 파일(/ \\ < > : " | ? *, CON 등)은 그 파일만 빼고 나머지는 계속 바꾼다.
    invalid: list[dict[str, str]] = []
    changes = service.build_changes(files, before, after, mode, failed=invalid)
    result = service.apply_changes(changes)
    failed = [*invalid, *result.failed]

    # 이름을 바꾸고 나면 화면이 들고 있는 경로는 더 이상 없는 파일을 가리킨다.
    # 그대로 두면 이어서 한 번 더 바꾸려 할 때 "파일을 찾을 수 없습니다"가 뜬다.
    # 바뀐 이름으로 목록을 갈아 끼워 돌려준다. 실패한 건 원래 이름 그대로 둔다.
    renamed = {old_path: new_path for old_path, new_path in changes}
    updated: list[str] = []
    for path in files:
        # 원본이 그대로 있으면 그 파일은 안 바뀐 것이다. 이름이 겹쳐 실패했을 때
        # 새 이름을 넣어 버리면 남의 파일을 가리키게 된다.
        if path.exists():
            updated.append(str(path))
            continue
        candidate = renamed.get(path)
        if candidate is not None and candidate.exists():
            updated.append(str(candidate))

    message = f"파일명 {result.success_count}개를 변경했습니다."
    if failed:
        message += f" {len(failed)}개는 바꾸지 못했습니다."
    return _success(
        message,
        result=result,
        inputs=updated,
        failed=failed,
        **({"popup": _failed_popup(message, failed, "일부 파일의 이름을 바꾸지 못했습니다")} if failed else {}),
    )


def run_zip_extractor(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _expand(_paths(payload), {".zip"}, bool(payload.get("recursive", True)))
    if not inputs:
        raise ValueError("풀어야 할 ZIP 파일을 찾지 못했습니다.")
    service = _module("zip_batch_extractor", "zip_batch_extractor_service")
    output = str(payload.get("output") or "")
    result = service.extract_zip_batch(
        inputs,
        service.OUTPUT_CUSTOM if output else service.OUTPUT_ORIGINAL,
        (
            service.EXTRACT_DIRECT
            if bool(payload.get("extract_direct", False))
            else service.EXTRACT_TO_NAMED_FOLDER
        ),
        output,
        bool(payload.get("exclude_junk", True)),
        str(payload.get("password") or ""),
        log_func=emit_progress,
    )
    failed = list(result.failed)
    if failed and result.success_count == 0:
        raise RuntimeError(
            "ZIP을 풀지 못했습니다.\n\n" + "\n".join(f"· {item['name']}: {item['error']}" for item in failed)
        )
    message = f"ZIP {result.success_count}개를 풀었습니다."
    partial = len(failed) - result.fail_count
    if result.fail_count:
        message += f" {result.fail_count}개는 풀지 못했습니다."
    if partial:
        message += f" {partial}개는 일부 파일을 풀지 못했습니다."
    return _success(
        message,
        result=result,
        failed=failed,
        **({"popup": _failed_popup(message, failed, "일부 ZIP을 풀지 못했습니다")} if failed else {}),
    )


def run_pdf_compress(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = [path for path in _paths(payload) if path.suffix.lower() == ".pdf"]
    if not inputs:
        raise ValueError("PDF 파일을 선택하세요.")
    service = _module("pdf_compress", "pdf_compress_service")
    cancel = FileCancel()
    try:
        target_mb = float(payload.get("target_mb") or 5)
    except (TypeError, ValueError):
        raise ValueError(
            f"'목표 용량(MB)' 칸에는 숫자를 입력하세요. (입력값: {payload.get('target_mb')})"
        ) from None
    if target_mb <= 0:
        raise ValueError("'목표 용량(MB)'은 0보다 크게 입력하세요.")
    target_bytes = int(target_mb * 1024 * 1024)
    raw_output = str(payload.get("output") or "").strip()
    folder = Path(raw_output).expanduser().resolve() if raw_output else None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)

    # 전체 합계 방식: 여러 PDF 의 합계를 목표 용량 이하로.
    if str(payload.get("target_mode") or "each") == "total":
        group = service.compress_group_to_total(
            inputs,
            folder or inputs[0].parent,
            target_bytes,
            progress=emit_progress,
            cancel=cancel.is_set,
        )
        message = (
            f"PDF {len(group['results'])}개를 합계 {group['final_total'] / 1048576:.2f}MB로 저장했습니다."
        )
        if group.get("cancelled"):
            message = "중지 요청으로 멈췄습니다. 지금까지 줄인 결과로 " + message
        return _success(
            message,
            output=str(group["folder"]),
            outputs=group["results"],
            failed=group["failed"],
            popup=_pdf_compress_total_popup(group, target_mb),
        )

    # 파일마다 방식: 한 파일이 실패해도 나머지는 계속한다.
    # 중지하면 하던 파일까지(또는 그 전까지) 저장한 결과를 남기고 멈춘다.
    outputs = []
    failed = []
    cancelled = False
    for index, input_path in enumerate(inputs, start=1):
        if cancel.is_set():
            cancelled = True
            break
        if len(inputs) > 1:
            emit_progress(f"[{index}/{len(inputs)}] {input_path.name}")
        output = service.safe_output_path(input_path, target_mb, folder)
        try:
            size, achieved = service.compress_to_target(
                input_path,
                output,
                target_bytes,
                len(service.LEVELS),
                progress=emit_progress,
                cancel=cancel.is_set,
            )
        except service.CompressCancelled:
            cancelled = True
            break
        except Exception as error:
            reason = service.describe_pdf_error(error)
            failed.append({"name": input_path.name, "error": reason})
            emit_progress(f"{input_path.name}: 압축하지 못했습니다 ({reason})")
            continue
        outputs.append({
            "path": output,
            "name": input_path.name,
            "original_mb": round(input_path.stat().st_size / (1024 * 1024), 2),
            "size_mb": round(size / (1024 * 1024), 2),
            "target_achieved": achieved,
        })
    if not outputs and failed and not cancelled:
        raise RuntimeError(
            "압축하지 못했습니다.\n\n" + "\n".join(f"· {item['name']}: {item['error']}" for item in failed)
        )
    skipped = len(inputs) - len(outputs) - len(failed) if cancelled else 0
    if cancelled:
        message = f"중지 요청으로 멈췄습니다. PDF {len(outputs)}개를 압축했습니다."
    elif failed:
        message = (
            f"PDF {len(inputs)}개 중 {len(outputs)}개를 압축했습니다. "
            f"{len(failed)}개는 압축하지 못했습니다."
        )
    else:
        message = f"PDF {len(outputs)}개를 압축했습니다."
    return _success(
        message,
        output=str(folder) if folder else "",
        outputs=outputs,
        failed=failed,
        popup=_pdf_compress_popup(outputs, target_mb, failed, skipped, cancelled),
    )


def _failed_lines(failed: list[dict[str, str]]) -> str:
    if not failed:
        return ""
    return "\n\n압축하지 못한 파일\n" + "\n".join(
        f"· {item['name']}: {item['error']}" for item in failed
    )


def _pdf_compress_popup(
    outputs: list[dict[str, Any]],
    target_mb: float,
    failed: list[dict[str, str]] | None = None,
    skipped: int = 0,
    cancelled: bool = False,
) -> dict[str, str]:
    """파일마다 방식의 결과 팝업. 목표를 못 맞췄거나 실패·중지한 파일이 있으면 경고로 띄운다."""
    failed = failed or []
    lines = []
    for item in outputs:
        mark = "달성" if item["target_achieved"] else "미달"
        lines.append(
            f"· {item['name']}\n   {item['original_mb']:.2f}MB → {item['size_mb']:.2f}MB ({mark})"
        )
    missed = [item for item in outputs if not item["target_achieved"]]
    if cancelled:
        head = (
            f"중지 요청으로 멈췄습니다. PDF {len(outputs)}개를 압축해 저장했습니다."
            if outputs
            else "중지 요청으로 멈춰 압축해 저장한 파일이 없습니다."
        )
        if skipped:
            head += f"\n나머지 {skipped}개는 압축하지 않았습니다."
        return {
            "level": "warning",
            "title": "압축을 중지했습니다",
            "message": head + ("\n\n" + "\n".join(lines) if lines else "") + _failed_lines(failed),
        }
    if not missed and not failed and outputs:
        return {
            "level": "success",
            "title": "압축에 성공했습니다",
            "message": f"파일마다 {target_mb:g}MB 이하로 줄였습니다.\n\n" + "\n".join(lines),
        }
    head = []
    if missed:
        head.append(
            f"{len(outputs)}개 중 {len(missed)}개가 목표 {target_mb:g}MB 보다 큽니다.\n"
            "사진이 적고 글자·도형 위주인 파일은 더 줄일 수 없어, 가장 작게 만든 결과를 저장했습니다."
        )
    return {
        "level": "warning",
        "title": "목표 용량까지 줄이지 못했습니다" if missed else "일부 파일을 압축하지 못했습니다",
        "message": ("\n".join(head) + "\n\n" if head else "") + "\n".join(lines) + _failed_lines(failed),
    }


def _pdf_compress_total_popup(group: dict[str, Any], target_mb: float) -> dict[str, str]:
    """전체 합계 방식의 결과 팝업."""
    before = group["original_total"] / 1048576
    after = group["final_total"] / 1048576
    lines = [
        f"· {item['name']}\n   {item['original_mb']:.2f}MB → {item['size_mb']:.2f}MB"
        + ("" if item["level"] else " (원본 유지)")
        for item in group["results"]
    ]
    summary = f"합계 {before:.2f}MB → {after:.2f}MB (목표 {target_mb:g}MB)\n저장 폴더: {group['folder']}"
    if group.get("cancelled"):
        return {
            "level": "warning",
            "title": "압축을 중지했습니다",
            "message": (
                summary
                + "\n중지 요청으로 멈춰 지금까지 줄인 결과로 저장했습니다. '원본 유지' 파일은 압축하지 않았습니다.\n\n"
                + "\n".join(lines)
                + _failed_lines(group["failed"])
            ),
        }
    if group["achieved"]:
        return {
            "level": "warning" if group["failed"] else "success",
            "title": "합계 목표 용량으로 압축했습니다",
            "message": summary + "\n\n" + "\n".join(lines) + _failed_lines(group["failed"]),
        }
    return {
        "level": "warning",
        "title": "합계 목표 용량까지 줄이지 못했습니다",
        "message": (
            summary
            + f"\n최대로 줄여도 합계 {after:.2f}MB입니다. 글자·도형 위주 파일은 더 줄지 않습니다.\n\n"
            + "\n".join(lines)
            + _failed_lines(group["failed"])
        ),
    }


HANDLERS = {
    "certificate_pdf_collector": run_certificate_pdf_collector,
    "file_inventory": run_file_inventory,
    "folder_unpacker": run_folder_unpacker,
    "hwp_collector": run_hwp_collector,
    "hwp_to_hwpx_converter": run_hwp_to_hwpx,
    "hwp_to_pdf_converter": run_hwp_to_pdf,
    "multi_format_pdf_combiner": run_multi_format_pdf_combiner,
    "pdf_compress": run_pdf_compress,
    "pdf_page_number_adder": run_pdf_page_number,
    "pdf_page_organizer": run_pdf_organizer,
    "pdf_page_organizer__load": load_pdf_organizer,
    "pdf_page_organizer__preview": preview_pdf_organizer,
    "rename_files": run_rename_files,
    "zip_batch_extractor": run_zip_extractor,
}
HANDLERS.update(EXTRA_HANDLERS)


def run_selftest() -> dict[str, Any]:
    """설치본에 들어갈 사이드카가 모든 파이썬 도구를 실제로 불러올 수 있는지 본다.

    도구 코드는 실행 중에 디스크에서 불러오기 때문에, 빌드할 때 빠진 라이브러리는
    그 도구를 누군가 처음 눌렀을 때에야 드러난다. 그래서 빌드 직후 여기서 전부
    한 번씩 불러 보고, 하나라도 실패하면 배포를 멈추게 한다.
    """
    import subprocess

    checked: list[str] = []
    failed: list[str] = []

    manifests = sorted(TOOLS_ROOT.glob("*/manifest.json"))
    python_tools = 0
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as error:
            failed.append(f"{manifest_path.parent.name}: manifest 를 읽지 못함 ({error})")
            continue
        if manifest.get("type") != "internal_python" or not manifest.get("enabled", True):
            continue
        python_tools += 1
        tool_id = str(manifest.get("id") or manifest_path.parent.name)
        tool_root = manifest_path.parent

        modules = [path.stem for path in sorted(tool_root.glob("*_service.py"))]
        if not modules:
            modules = [
                f"services.{path.stem}"
                for path in sorted((tool_root / "services").glob("*_service.py"))
            ]
        if not modules:
            failed.append(f"{tool_id}: 처리 모듈(*_service.py)을 찾지 못함")
            continue

        # 여러 도구가 같은 이름의 services 패키지를 쓴다. 앞 도구 것이 남아 있으면
        # 뒤 도구가 엉뚱한 모듈을 불러오므로 매번 지운다.
        for name in list(sys.modules):
            if name == "services" or name.startswith("services."):
                del sys.modules[name]
        sys.path.insert(0, str(tool_root))
        try:
            for module_name in modules:
                try:
                    importlib.import_module(module_name)
                    checked.append(f"{tool_id}: {module_name}")
                except Exception as error:
                    failed.append(
                        f"{tool_id}: {module_name} → {type(error).__name__}: {error}"
                    )
        finally:
            try:
                sys.path.remove(str(tool_root))
            except ValueError:
                pass

    if python_tools == 0:
        failed.append(f"파이썬 도구를 하나도 찾지 못함 (도구 폴더: {TOOLS_ROOT})")

    # PDF 용량 압축: PyMuPDF 는 C 라이브러리를 품고 있어 import 만으로는 빠진 파일을
    # 다 못 잡는다. 사진이 든 작은 PDF 를 실제로 만들어 한 번 압축해 본다.
    try:
        sys.path.insert(0, str(TOOLS_ROOT / "pdf_compress"))
        compress = importlib.import_module("pdf_compress_service")
        import pymupdf
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "probe.pdf"
            out = Path(tmp) / "probe_out.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), 0)
            pix.clear_with(200)
            page.insert_image(page.rect, pixmap=pix)
            page.insert_text((72, 72), "압축 확인 probe", fontname="helv")
            doc.save(str(src))
            doc.close()
            size = compress.compress_once(src, out, 100, 60)
            check = pymupdf.open(str(out))
            pages = check.page_count
            check.close()
            if pages != 1 or size <= 0:
                failed.append(f"PDF 압축: 결과가 이상함 (쪽 {pages}, 크기 {size})")
            else:
                checked.append(f"PDF 압축: PyMuPDF {pymupdf.__version__} 동작 확인")
    except Exception as error:
        failed.append(f"PDF 압축: 확인 중 오류 → {type(error).__name__}: {error}")

    return {
        "ok": not failed,
        "python_tools": python_tools,
        "checked": checked,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool")
    parser.add_argument("--payload")
    parser.add_argument("--payload-b64")
    # 명령줄 한도(윈도 32,767자)를 넘는 입력값은 앱이 임시 파일로 넘긴다(파일은 앱이 지운다).
    parser.add_argument("--payload-file")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        report = run_selftest()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    try:
        if args.payload_file:
            payload_text = Path(args.payload_file).read_text(encoding="utf-8")
        elif args.payload_b64:
            payload_text = base64.b64decode(args.payload_b64).decode("utf-8")
        else:
            payload_text = args.payload or "{}"
        payload = json.loads(payload_text)
        handler = HANDLERS.get(args.tool)
        if not args.tool:
            raise ValueError("실행할 도구를 지정해 주세요.")
        if handler is None:
            raise ValueError(
                "이 도구의 Tauri 통합 실행기는 아직 연결되지 않았습니다."
            )
        result = handler(payload)
        print(json.dumps(_plain(result), ensure_ascii=False))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
