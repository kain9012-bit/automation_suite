import json
from pathlib import Path


DEFAULT_SETTINGS = {
    "auto_start_windows": False,
    "start_fullscreen": True,
    "reopen_last_tool": False,
    "show_home_favorites": True,
    "show_home_recent": True,
    "recent_tools_limit": 8,
    "confirm_on_exit": False,
    "last_tool_id": "",
}


class UserState:
    def __init__(self, base_dir: Path, state_dir: Path | None = None):
        self.base_dir = base_dir
        self.state_dir = state_dir or (base_dir / "shared" / "config")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "user_state.json"

    def load(self) -> dict:
        if not self.state_path.exists():
            return {
                "favorites": [],
                "recent_tools": [],
                "settings": DEFAULT_SETTINGS.copy(),
            }

        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "favorites": [],
                "recent_tools": [],
                "settings": DEFAULT_SETTINGS.copy(),
            }

        settings = DEFAULT_SETTINGS.copy()
        settings.update(data.get("settings", {}))

        return {
            "favorites": data.get("favorites", []),
            "recent_tools": data.get("recent_tools", []),
            "settings": settings,
        }

    def save(self, favorites: list[str], recent_tools: list[str], settings: dict) -> None:
        merged_settings = DEFAULT_SETTINGS.copy()
        merged_settings.update(settings or {})

        data = {
            "favorites": favorites,
            "recent_tools": recent_tools,
            "settings": merged_settings,
        }
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
