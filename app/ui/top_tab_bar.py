from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QHBoxLayout, QWidget


class TopTabBar(QWidget):
    tab_selected = Signal(str)

    def __init__(self, tabs: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        for tab in tabs:
            button = QPushButton(tab)
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, name=tab: self.select_tab(name))
            layout.addWidget(button)
            self._buttons[tab] = button
        layout.addStretch(1)

    def select_tab(self, tab_name: str) -> None:
        for name, button in self._buttons.items():
            button.setChecked(name == tab_name)
        self.tab_selected.emit(tab_name)
