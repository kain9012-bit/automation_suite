from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from app.ui.exe_tool_page import ExeToolPage
from app.ui.html_tool_page import HtmlToolPage


class ToolRouter:
    def build_page(self, tool):
        if tool.type == "html":
            return HtmlToolPage(tool.entry_path)

        if tool.type == "external_exe":
            return ExeToolPage(
                name=tool.name,
                description=tool.description,
                exe_path=tool.entry_path,
            )

        if tool.type == "internal_python":
            module_name = f"tool_{tool.id}"
            tool_dir = str(Path(tool.entry_path).parent)

            if tool_dir not in sys.path:
                sys.path.insert(0, tool_dir)

            spec = spec_from_file_location(module_name, tool.entry_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"모듈을 불러올 수 없습니다: {tool.entry_path}")

            module = module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "build_page"):
                return module.build_page()

            raise RuntimeError(f"internal_python 도구 진입점을 찾을 수 없습니다: {tool.entry_path}")

        return ExeToolPage(
            name=tool.name,
            description=f"아직 지원하지 않는 도구 유형입니다: {tool.type}",
            exe_path=tool.entry_path,
        )