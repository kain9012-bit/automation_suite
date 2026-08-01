from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class SectionCard(QFrame):
    def __init__(self, title: str, description: str | None = None):
        super().__init__()
        self.setObjectName("sectionCard")
        self.setStyleSheet("""
            QFrame#sectionCard {
                background: #ffffff;
                border: 1px solid #d8e2ee;
                border-radius: 14px;
            }
        """)

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 20, 22, 20)
        self.root.setSpacing(12)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #1f2937;")
        self.root.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("font-size: 13px; color: #667085;")
            self.root.addWidget(desc_label)


class SettingsPage(QWidget):
    def __init__(
        self,
        settings: dict,
        save_callback,
        reset_callback,
        clear_recent_callback=None,
        clear_favorites_callback=None,
    ):
        super().__init__()
        self.settings = settings
        self.save_callback = save_callback
        self.reset_callback = reset_callback
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QWidget {
                background: #ffffff;
            }
            QLabel {
                color: #1f2937;
                background: transparent;
            }
            QCheckBox {
                font-size: 14px;
                font-weight: 600;
                color: #1f2937;
                spacing: 8px;
                padding: 6px 0;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #b8c6d9;
                border-radius: 5px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #2c67b3;
                border: 1px solid #2c67b3;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        title = QLabel("설정")
        title.setStyleSheet("font-size: 28px; font-weight: 900; color: #1f2937;")
        root.addWidget(title)

        summary = QLabel("프로그램 실행 방식과 기본 동작을 설정합니다.")
        summary.setStyleSheet("font-size: 13px; color: #667085;")
        root.addWidget(summary)

        launch_card = SectionCard("시작 및 실행 설정")
        self.chk_auto_start_windows = QCheckBox("컴퓨터 시작 시 프로그램 자동 실행")
        self.chk_auto_start_windows.setChecked(bool(self.settings.get("auto_start_windows", False)))
        self.chk_start_fullscreen = QCheckBox("프로그램 시작 시 전체화면으로 열기")
        self.chk_start_fullscreen.setChecked(bool(self.settings.get("start_fullscreen", True)))
        self.chk_reopen_last_tool = QCheckBox("마지막으로 사용한 도구 다시 열기")
        self.chk_reopen_last_tool.setChecked(bool(self.settings.get("reopen_last_tool", False)))
        self.chk_confirm_on_exit = QCheckBox("프로그램 종료 시 확인창 표시")
        self.chk_confirm_on_exit.setChecked(bool(self.settings.get("confirm_on_exit", False)))
        for widget in (
            self.chk_auto_start_windows,
            self.chk_start_fullscreen,
            self.chk_reopen_last_tool,
            self.chk_confirm_on_exit,
        ):
            launch_card.root.addWidget(widget)
        root.addWidget(launch_card)

        note = QLabel("※ 설정 변경 후 저장을 눌러야 반영됩니다. 자동 실행과 전체화면 설정은 저장 즉시 적용됩니다.")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px; color: #667085;")
        root.addWidget(note)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 6, 0, 0)
        button_row.setSpacing(10)
        button_row.addStretch(1)

        btn_reset = QPushButton("기본값으로 초기화")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setFixedSize(160, 44)
        btn_reset.setStyleSheet(self._secondary_button_style())
        btn_reset.clicked.connect(self.reset_callback)

        btn_save = QPushButton("설정 저장")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setFixedSize(140, 44)
        btn_save.setStyleSheet(self._primary_button_style())
        btn_save.clicked.connect(self._save)

        button_row.addWidget(btn_reset)
        button_row.addWidget(btn_save)
        root.addLayout(button_row)
        root.addStretch(1)

    def _primary_button_style(self) -> str:
        return """
            QPushButton {
                background-color: #2c67b3;
                color: white;
                border: 1px solid #2c67b3;
                border-radius: 12px;
                padding: 0 18px;
                font-size: 14px;
                font-weight: 800;
            }
            QPushButton:hover {
                background-color: #23579b;
                border-color: #23579b;
            }
        """

    def _secondary_button_style(self) -> str:
        return """
            QPushButton {
                background-color: #ffffff;
                color: #1f2937;
                border: 1px solid #d0d9e6;
                border-radius: 12px;
                padding: 0 18px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #f8fafc;
            }
        """

    def _save(self):
        self.save_callback({
            "auto_start_windows": self.chk_auto_start_windows.isChecked(),
            "start_fullscreen": self.chk_start_fullscreen.isChecked(),
            "reopen_last_tool": self.chk_reopen_last_tool.isChecked(),
            "confirm_on_exit": self.chk_confirm_on_exit.isChecked(),
        })
