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
from extra_tools import EXTRA_HANDLERS
from macro_actions import run_action as run_macro_action

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
        output = base if directory else base / default_name
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
    output = _output_path(payload, inputs, "한글문서_취합본.hwpx")
    service = _module("hwp_collector", "hwp_collector_service")
    service.merge_han_files(inputs, output)
    return _success("한글 문서 취합을 완료했습니다.", output=output)


def run_multi_format_pdf_combiner(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    output = _output_path(payload, inputs, "문서_통합본.pdf")
    service = _module(
        "multi_format_pdf_combiner", "multi_format_pdf_combiner_service"
    )
    converted: list[Path] = []
    conversion_errors: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="jbedu_pdf_") as temp_name:
        temp_dir = Path(temp_name)
        for source in inputs:
            pdf_path, error = service.ensure_pdf(source, temp_dir)
            if pdf_path:
                converted.append(pdf_path)
            else:
                conversion_errors.append((source.name, error or "변환 실패"))
        ok_files, merge_errors = service.merge_pdf_ordered(converted, output)
    errors = [*conversion_errors, *merge_errors]
    return _success(
        f"문서 {len(ok_files)}개를 PDF로 통합했습니다.",
        output=output,
        failed=errors,
    )


def run_certificate_pdf_collector(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = [path for path in _paths(payload) if path.suffix.lower() == ".pdf"]
    service = _module(
        "certificate_pdf_collector", "certificate_pdf_collector_service"
    )
    good, bad, errors = service.process_pdfs(inputs)
    output = _output_path(payload, inputs, "이수증_취합결과.xlsx")
    service.save_result_excel(output, good, bad, errors)
    return _success(
        f"이수증 {len(inputs)}개를 분석했습니다.",
        output=output,
        valid_count=len(good),
        review_count=len(bad),
        error_count=len(errors),
    )


def run_hwp_to_pdf(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    output_dir = _output_path(payload, inputs, "", directory=True)
    service = _module("hwp_to_pdf_converter", "hwp_to_pdf_converter_service")
    ok_files, bad_files = service.convert_files(inputs, output_dir)
    return _success(
        f"{len(ok_files)}개 파일을 PDF로 변환했습니다.",
        output=output_dir,
        failed=bad_files,
    )


def run_hwp_to_hwpx(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _expand(_paths(payload), {".hwp"}, bool(payload.get("recursive", True)))
    if not inputs:
        raise ValueError("변환할 한글(.hwp) 파일을 찾지 못했습니다.")
    service = _module("hwp_to_hwpx_converter", "hwp_to_hwpx_converter_service")
    result = service.convert_hwp_files_to_hwpx(
        inputs,
        visible=bool(payload.get("visible", False)),
    )
    return _success("HWPX 변환 작업을 완료했습니다.", result=result)


def run_pdf_page_number(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = _paths(payload)
    if len(inputs) != 1:
        raise ValueError("페이지 번호를 넣을 PDF 파일 하나를 선택하세요.")
    service = _module("pdf_page_number_adder", "pdf_page_number_adder_service")
    output = _output_path(payload, inputs, f"{inputs[0].stem}_페이지번호.pdf")
    result = service.add_page_numbers(
        inputs[0],
        output,
        str(payload.get("format_type") or "숫자"),
        int(payload.get("start_page") or 1),
        int(payload.get("start_number") or 1),
        str(payload.get("position") or "하단 가운데"),
        str(payload.get("font_name") or "굴림체"),
        int(payload.get("font_size") or 10),
    )
    return _success("페이지 번호를 추가했습니다.", output=result)


def run_pdf_organizer(payload: dict[str, Any]) -> dict[str, Any]:
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
            int(payload.get("source_page") or 1),
            int(payload.get("target_page") or 1),
        )
    else:
        result = service.run_split(
            inputs[0],
            output_dir,
            mode or "every_n",
            int(payload.get("number") or 1),
            spec,
            bool(payload.get("zip_output", False)),
        )
    return _success("PDF 페이지 작업을 완료했습니다.", output=result)


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
    return _success(
        f"항목 {len(inventory.rows)}개를 현황표로 저장했습니다.",
        output=output,
        error_count=len(inventory.errors),
    )


def run_folder_unpacker(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(payload.get("confirmed", False)):
        raise ValueError("파일 이동 작업을 확인한 뒤 다시 실행하세요.")
    folders = [path for path in _paths(payload) if path.is_dir()]
    service = _module("folder_unpacker", "folder_unpacker_service")
    result = service.unpack_folders(
        folders,
        recursive=bool(payload.get("recursive", True)),
        prefix_folder=bool(payload.get("prefix_folder", False)),
    )
    return _success(
        f"파일 {result.moved_count}개를 상위 폴더로 이동했습니다.",
        result=result,
    )


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
    changes = service.build_changes(files, before, after, mode)
    result = service.apply_changes(changes)
    return _success(
        f"파일명 {result.success_count}개를 변경했습니다.",
        result=result,
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
    )
    return _success(
        f"ZIP {result.success_count}개를 풀었습니다.",
        result=result,
    )


def run_pdf_compress(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = [path for path in _paths(payload) if path.suffix.lower() == ".pdf"]
    service = _module("pdf_compress", "pdf_compress_service")
    ghostscript = service.find_ghostscript()
    if not ghostscript:
        raise RuntimeError("PDF 압축에 필요한 Ghostscript를 찾지 못했습니다.")
    target_mb = float(payload.get("target_mb") or 5)
    outputs = []
    for input_path in inputs:
        raw_output = str(payload.get("output") or "").strip()
        if raw_output and len(inputs) == 1:
            output = Path(raw_output).expanduser().resolve()
        else:
            output = service.safe_output_path(input_path, target_mb)
        tries, achieved = service.compress_to_target(
            ghostscript,
            input_path,
            output,
            int(target_mb * 1024 * 1024),
            int(payload.get("max_tries") or 18),
        )
        outputs.append({"path": output, "tries": tries, "target_achieved": achieved})
    return _success(f"PDF {len(outputs)}개를 압축했습니다.", outputs=outputs)


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
    "rename_files": run_rename_files,
    "zip_batch_extractor": run_zip_extractor,
}
HANDLERS.update(EXTRA_HANDLERS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool")
    parser.add_argument("--payload")
    parser.add_argument("--payload-b64")
    parser.add_argument("--macro-action-b64")
    args = parser.parse_args()

    try:
        if args.macro_action_b64:
            action = json.loads(base64.b64decode(args.macro_action_b64).decode("utf-8"))
            print(json.dumps(run_macro_action(action), ensure_ascii=False))
            return 0

        if args.payload_b64:
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
