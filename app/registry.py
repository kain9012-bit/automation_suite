import json
import re
from collections.abc import Iterable
from pathlib import Path

from app.models import ToolManifest


class ToolRegistry:
    def __init__(self, tools_dir: Path | Iterable[Path]):
        if isinstance(tools_dir, Path):
            self.tools_dirs = [tools_dir]
        else:
            self.tools_dirs = [Path(path) for path in tools_dir]
        self.tools: list[ToolManifest] = []
        self.errors: list[str] = []
        self.load_tools()

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", str(version or ""))
        return tuple(int(number) for number in numbers) if numbers else (0,)

    def load_tools(self) -> None:
        self.tools.clear()
        self.errors.clear()
        selected: dict[str, ToolManifest] = {}

        for tools_dir in self.tools_dirs:
            if not tools_dir.exists():
                continue

            for tool_dir in tools_dir.iterdir():
                if not tool_dir.is_dir():
                    continue

                manifest_path = tool_dir / "manifest.json"
                if not manifest_path.exists():
                    continue

                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    tool = ToolManifest(
                        id=str(data["id"]).strip(),
                        name=str(data["name"]).strip(),
                        top_tab=str(data["top_tab"]).strip(),
                        type=str(data["type"]).strip(),
                        entry=str(data["entry"]).strip(),
                        icon=str(data.get("icon", "")).strip(),
                        description=str(data.get("description", "")).strip(),
                        submenu_group=str(data.get("submenu_group", "")).strip(),
                        order=int(data.get("order", 999)),
                        enabled=bool(data.get("enabled", True)),
                        version=str(data.get("version", "1.0.0")).strip(),
                        keywords=list(data.get("keywords", [])),
                        base_dir=tool_dir,
                    )
                    if not tool.id or not tool.name or not tool.top_tab:
                        raise ValueError("id, name, top_tab은 비워 둘 수 없습니다.")
                    if tool.enabled:
                        current = selected.get(tool.id)
                        if current is None or self._version_key(tool.version) >= self._version_key(current.version):
                            selected[tool.id] = tool
                except Exception as exc:
                    message = f"매니페스트 로드 실패: {manifest_path} / {exc}"
                    self.errors.append(message)
                    print(message)

        self.tools = list(selected.values())
        self.tools.sort(key=lambda item: (item.top_tab, item.order, item.name))

    def get_top_tabs(self) -> list[str]:
        return list(dict.fromkeys(tool.top_tab for tool in self.tools))

    def get_tools_by_tab(self, top_tab: str) -> list[ToolManifest]:
        return [tool for tool in self.tools if tool.top_tab == top_tab]

    def get_tool_by_id(self, tool_id: str) -> ToolManifest | None:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
        return None
