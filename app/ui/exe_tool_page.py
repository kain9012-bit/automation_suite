import subprocess
from pathlib import Path

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget, QMessageBox


class ExeToolPage(QWidget):
    def __init__(self, name: str, description: str, exe_path: Path):
        super().__init__()
        self.exe_path = exe_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)

        title = QLabel(name)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")

        desc = QLabel(description or "도구 설명이 없습니다.")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 14px;")

        path_label = QLabel(f"실행 파일: {exe_path}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet("font-size: 12px; color: #666;")

        run_btn = QPushButton("도구 실행")
        run_btn.setFixedHeight(40)
        run_btn.clicked.connect(self.run_tool)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(path_label)
        layout.addWidget(run_btn)
        layout.addStretch(1)

    def run_tool(self) -> None:
        if not self.exe_path.exists():
            QMessageBox.warning(self, "실행 실패", f"실행 파일이 없습니다.\n{self.exe_path}")
            return

        try:
            subprocess.Popen([str(self.exe_path)], cwd=str(self.exe_path.parent))
        except Exception as e:
            QMessageBox.critical(self, "실행 실패", str(e))