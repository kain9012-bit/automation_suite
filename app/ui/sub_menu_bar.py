from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from app.models import ToolManifest


class SubMenuBar(QWidget):
    tool_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(16, 8, 16, 8)
        self._layout.setHorizontalSpacing(12)
        self._layout.setVerticalSpacing(12)
        self._buttons: list[QPushButton] = []

    def set_tools(self, tools: list[ToolManifest]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()

        columns = 6
        for index, tool in enumerate(tools):
            button = QPushButton(tool.name)
            button.setToolTip(tool.description)
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.setMinimumSize(120, 72)
            button.clicked.connect(lambda checked=False, tool_id=tool.id: self._emit_tool(tool_id))
            row = index // columns
            col = index % columns
            self._layout.addWidget(button, row, col)
            self._buttons.append(button)
        self._layout.setColumnStretch(columns, 1)

    def _emit_tool(self, tool_id: str) -> None:
        sender = self.sender()
        if isinstance(sender, QPushButton):
            for button in self._buttons:
                button.setChecked(button is sender)
        self.tool_selected.emit(tool_id)
