from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolManifest:
    id: str
    name: str
    top_tab: str
    type: str
    entry: str
    icon: str
    description: str = ""
    submenu_group: str = ""
    order: int = 999
    enabled: bool = True
    version: str = "1.0.0"
    keywords: list[str] = field(default_factory=list)
    base_dir: Path = Path()

    @property
    def entry_path(self) -> Path:
        return self.base_dir / self.entry

    @property
    def icon_path(self) -> Path:
        return self.base_dir / self.icon