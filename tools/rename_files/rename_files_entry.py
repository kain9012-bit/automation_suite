from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rename_files_service import (
    MODE_PREFIX,
    MODE_REPLACE,
    MODE_SUFFIX,
    apply_changes,
    build_changes,
    build_preview_lines,
    list_files_in_folder,
    update_selected_paths_after_rename,
)

BRAND = "#0b5ed7"
BRAND_DARK = "#0a58ca"
BORDER = "#d9e2f0"
TEXT = "#1f2937"
MUTED = "#6b7280"
PAGE_BG = "#ffffff"
CARD_BG = "#ffffff"
INFO_BG = "#f7faff"


class SectionCard(QFrame):
    def __init__(self, title: str, description: str | None = None):
        super().__init__()
        self.setObjectName("sectionCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setObjectName("sectionDescription")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        self.body_layout = layout


class RenameFilesPage(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_files: list[Path] = []
        self._build_ui()
        self.update_selected_label()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background: {PAGE_BG};
                color: {TEXT};
                font-size: 13px;
            }}

            QLabel {{
                background: transparent;
                border: none;
            }}

            QFrame#sectionCard {{
                background: {CARD_BG};
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}

            QLabel#pageTitle {{
                font-size: 26px;
                font-weight: 700;
                color: {TEXT};
                background: transparent;
            }}

            QLabel#pageDescription {{
                font-size: 13px;
                color: {MUTED};
                background: transparent;
            }}

            QLabel#sectionTitle {{
                font-size: 18px;
                font-weight: 700;
                color: {TEXT};
                background: transparent;
            }}

            QLabel#sectionDescription {{
                font-size: 13px;
                color: {MUTED};
                background: transparent;
            }}

            QLabel#selectedLabel {{
                font-size: 13px;
                color: {TEXT};
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 10px 12px;
            }}

            QLineEdit {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 22px;
                font-size: 13px;
                color: {TEXT};
            }}

            QLineEdit:focus {{
                border: 1px solid {BRAND};
            }}

            QPushButton {{
                min-height: 36px;
                padding: 0 14px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
            }}

            QFrame#infoBox {{
                background: {INFO_BG};
                border: 1px dashed #cfdcf2;
                border-radius: 8px;
            }}

            QLabel#summaryLabel {{
                font-size: 13px;
                color: #334155;
                background: transparent;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        outer = QHBoxLayout()
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(0)

        outer.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(1400)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(18)

        page_title = QLabel("파일명 일괄 변경 도구(v1.1)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_description = QLabel(
            "선택한 파일 또는 폴더 안의 파일 이름에서 문자열을 바꾸거나 앞뒤에 일괄 추가합니다."
        )
        page_description.setObjectName("pageDescription")
        page_description.setAlignment(Qt.AlignHCenter)
        page_description.setWordWrap(False)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_description)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)

        # 1번 카드
        input_card = SectionCard(
            "1. 파일 선택 및 문자열 입력",
            "폴더 또는 여러 파일을 선택한 뒤, 바꿀 문자열을 입력하고 이름 변경을 실행합니다."
        )
        input_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        input_card.setMinimumWidth(600)
        cards_row.addWidget(input_card, 3)

        self.selected_label = QLabel()
        self.selected_label.setObjectName("selectedLabel")
        self.selected_label.setWordWrap(True)
        input_card.body_layout.addWidget(self.selected_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.btn_folder = QPushButton("폴더 선택")
        self.btn_files = QPushButton("파일 선택")
        self.btn_clear = QPushButton("선택 초기화")

        for btn in (self.btn_folder, self.btn_files, self.btn_clear):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #ffffff;
                    border: 1px solid {BORDER};
                    color: {TEXT};
                    border-radius: 6px;
                    min-height: 36px;
                    padding: 0 14px;
                    font-size: 13px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: #f8fafc;
                    border: 1px solid #c6d5eb;
                }}
            """)

        self.btn_folder.clicked.connect(self.on_select_folder)
        self.btn_files.clicked.connect(self.on_select_files)
        self.btn_clear.clicked.connect(self.on_clear_selection)

        button_row.addWidget(self.btn_folder)
        button_row.addWidget(self.btn_files)
        button_row.addWidget(self.btn_clear)
        button_row.addStretch(1)

        input_card.body_layout.addLayout(button_row)

        mode_label = QLabel("작업 방식")
        mode_label.setStyleSheet("font-size:13px; font-weight:600; color:#1f2937; background:transparent;")
        input_card.body_layout.addWidget(mode_label)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(14)
        self.mode_replace = QRadioButton("문자열 바꾸기")
        self.mode_prefix = QRadioButton("앞에 붙이기")
        self.mode_suffix = QRadioButton("뒤에 붙이기")
        self.mode_replace.setChecked(True)
        for radio in (self.mode_replace, self.mode_prefix, self.mode_suffix):
            radio.setStyleSheet("font-size:13px; font-weight:600; color:#1f2937; background:transparent;")
            radio.toggled.connect(self.on_mode_changed)
            mode_row.addWidget(radio)
        mode_row.addStretch(1)
        input_card.body_layout.addLayout(mode_row)

        before_label = QLabel("바꾸기 전 문자열")
        self.before_label = before_label
        before_label.setStyleSheet("font-size:13px; font-weight:600; color:#1f2937; background:transparent;")
        input_card.body_layout.addWidget(before_label)

        self.before_input = QLineEdit()
        self.before_input.setPlaceholderText("예: 2025")
        input_card.body_layout.addWidget(self.before_input)

        after_label = QLabel("바꾼 후 문자열")
        self.after_label = after_label
        after_label.setStyleSheet("font-size:13px; font-weight:600; color:#1f2937; background:transparent;")
        input_card.body_layout.addWidget(after_label)

        self.after_input = QLineEdit()
        self.after_input.setPlaceholderText("예: 2026")
        input_card.body_layout.addWidget(self.after_input)

        hint = QLabel("※ 확장자(.pdf, .xlsx 등)는 그대로 두고 파일명 부분만 변경합니다.")
        self.hint_label = hint
        hint.setStyleSheet("font-size:12px; color:#6b7280; background:transparent;")
        hint.setWordWrap(True)
        input_card.body_layout.addWidget(hint)

        self.run_btn = QPushButton("이름 변경 실행")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BRAND};
                border: 1px solid {BRAND};
                color: white;
                border-radius: 6px;
                min-height: 38px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {BRAND_DARK};
                border: 1px solid {BRAND_DARK};
            }}
        """)
        self.run_btn.clicked.connect(self.on_run)
        input_card.body_layout.addWidget(self.run_btn, alignment=Qt.AlignLeft)

        # 2번 카드
        preview_card = SectionCard(
            "2. 실행 방식",
            "실행 버튼을 누르면 변경 예정 파일명을 먼저 보여준 뒤, 확인 시 실제 이름을 변경합니다."
        )
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        preview_card.setMinimumWidth(450)
        cards_row.addWidget(preview_card, 2)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)

        info_layout.addWidget(self.summary_label)
        preview_card.body_layout.addWidget(info_box)
        preview_card.body_layout.addStretch(1)

        container_layout.addLayout(cards_row)
        container_layout.addStretch(1)

        outer.addWidget(container)
        outer.addStretch(1)

        root.addLayout(outer)
        self.on_mode_changed()

    def update_selected_label(self) -> None:
        if not self.selected_files:
            text = "선택된 파일: 0개"
            summary = "현재 선택된 파일이 없습니다."
        else:
            parents = {p.parent for p in self.selected_files}
            if len(parents) == 1:
                base = next(iter(parents))
                text = f"선택된 파일: {len(self.selected_files)}개\n위치: {base}"
            else:
                text = f"선택된 파일: {len(self.selected_files)}개\n위치: 여러 폴더"

            summary = f"현재 {len(self.selected_files)}개 파일이 선택되어 있습니다."

        self.selected_label.setText(text)
        self.summary_label.setText(summary)

    def current_mode(self) -> str:
        if self.mode_prefix.isChecked():
            return MODE_PREFIX
        if self.mode_suffix.isChecked():
            return MODE_SUFFIX
        return MODE_REPLACE

    def on_mode_changed(self) -> None:
        mode = self.current_mode()
        is_replace = mode == MODE_REPLACE
        self.before_label.setVisible(is_replace)
        self.before_input.setVisible(is_replace)

        if mode == MODE_PREFIX:
            self.after_label.setText("앞에 붙일 문자열")
            self.after_input.setPlaceholderText("예: 2026_")
            self.hint_label.setText("※ 입력한 문자열을 파일명 맨 앞에 붙입니다. 확장자는 그대로 유지됩니다.")
        elif mode == MODE_SUFFIX:
            self.after_label.setText("뒤에 붙일 문자열")
            self.after_input.setPlaceholderText("예: _최종")
            self.hint_label.setText("※ 입력한 문자열을 확장자 앞, 파일명 맨 뒤에 붙입니다.")
        else:
            self.after_label.setText("바꾼 후 문자열")
            self.after_input.setPlaceholderText("예: 2026")
            self.hint_label.setText("※ 확장자(.pdf, .xlsx 등)는 그대로 두고 파일명 부분에서만 문자열을 교체합니다.")

    def on_select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "파일 이름을 변경할 폴더 선택")
        if not folder:
            return

        self.selected_files = list_files_in_folder(Path(folder))
        self.update_selected_label()

    def on_select_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "이름을 변경할 파일 선택",
            "",
            "모든 파일 (*.*)"
        )
        if not filenames:
            return

        self.selected_files = [Path(f) for f in filenames]
        self.update_selected_label()

    def on_clear_selection(self) -> None:
        self.selected_files = []
        self.update_selected_label()

    def on_run(self) -> None:
        if not self.selected_files:
            QMessageBox.warning(self, "알림", "먼저 폴더 또는 파일을 선택해 주세요.")
            return

        before = self.before_input.text()
        after = self.after_input.text()
        mode = self.current_mode()

        if mode == MODE_REPLACE and not before:
            QMessageBox.warning(self, "알림", "바꾸기 전 문자열을 입력해 주세요.")
            return

        if mode in (MODE_PREFIX, MODE_SUFFIX) and not after:
            QMessageBox.warning(self, "알림", "추가할 문자열을 입력해 주세요.")
            return

        changes = build_changes(self.selected_files, before, after, mode)

        if not changes:
            if mode == MODE_REPLACE:
                message = "선택된 파일들 중에서 변경할 문자열이 포함된 이름이 없습니다."
            else:
                message = "변경할 파일명이 없습니다."
            QMessageBox.information(self, "안내", message)
            return

        preview_lines = build_preview_lines(changes)
        preview_msg = (
            f"총 {len(changes)}개 파일의 이름을 변경합니다.\n\n"
            "예시:\n" + "\n".join(preview_lines) + "\n\n"
            "계속하시겠습니까?"
        )

        answer = QMessageBox.question(self, "이름 변경 확인", preview_msg)
        if answer != QMessageBox.Yes:
            return

        result = apply_changes(changes)
        self.selected_files = update_selected_paths_after_rename(self.selected_files, changes)
        self.update_selected_label()

        result_msg = f"이름 변경 완료.\n\n성공: {result.success_count}개"
        if result.conflict_count > 0:
            result_msg += f"\n실패/충돌: {result.conflict_count}개"

        if result.conflict_list:
            result_msg += "\n\n자세한 내용:\n" + "\n".join(result.conflict_list[:10])
            if len(result.conflict_list) > 10:
                result_msg += f"\n... 외 {len(result.conflict_list) - 10}개"

        QMessageBox.information(self, "결과", result_msg)


def build_page():
    return RenameFilesPage()
