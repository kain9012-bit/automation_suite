from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from excel_merge_service import (
    MODE_FILES_TO_SHEETS,
    MODE_SAME_SHEETS_TOGETHER,
    MODE_WORKBOOK_SHEETS_TO_ONE,
    MergeOptions,
    is_supported_file,
    merge_excel,
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


class ExcelMergeWorker(QThread):
    log_message = Signal(str)
    finished_result = Signal(object)
    failed = Signal(str)

    def __init__(self, options: MergeOptions):
        super().__init__()
        self.options = options

    def run(self) -> None:
        try:
            self.log_message.emit("===== 엑셀 병합 시작 =====")
            result = merge_excel(self.options, self.log_message.emit)
            self.log_message.emit("===== 완료 =====")
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ExcelMergePage(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[Path] = []
        self.file_set: set[str] = set()
        self.worker: ExcelMergeWorker | None = None
        self.running = False
        self._build_ui()
        self.refresh_table()

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
            QLineEdit {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 22px;
                font-size: 13px;
                color: {TEXT};
            }}
            QCheckBox, QRadioButton {{
                background: transparent;
                color: {TEXT};
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
            }}
            QRadioButton::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 1px solid #94a3b8;
                background: #ffffff;
            }}
            QRadioButton::indicator:hover {{
                border-color: {BRAND};
            }}
            QRadioButton::indicator:checked {{
                border: 4px solid {BRAND};
                background: #ffffff;
            }}
            QRadioButton::indicator:disabled {{
                border-color: #cbd5e1;
                background: #f1f5f9;
            }}
            QTableWidget {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 8px;
                gridline-color: #eef2f7;
                font-size: 13px;
                selection-background-color: #eaf2ff;
                selection-color: {TEXT};
            }}
            QPlainTextEdit {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
                color: #334155;
            }}
            QFrame#infoBox {{
                background: {INFO_BG};
                border: 1px dashed #cfdcf2;
                border-radius: 8px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        outer = QHBoxLayout()
        outer.setContentsMargins(30, 18, 30, 16)
        outer.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(1500)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)

        page_title = QLabel("엑셀 병합 도구(v1.3)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("여러 엑셀 파일과 시트를 선택한 방식으로 하나의 엑셀 파일로 병합합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard("1. 파일 선택", "병합할 엑셀 파일을 추가하고 순서를 확인합니다.")
        right_card = SectionCard("2. 병합 방식 및 실행", "병합 모드와 옵션을 선택한 뒤 결과 파일을 생성합니다.")
        left_card.body_layout.setSpacing(10)
        right_card.body_layout.setSpacing(8)
        left_card.setMinimumWidth(720)
        right_card.setMinimumWidth(620)
        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        left_card.body_layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파일명", "형식", "경로"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(200)
        left_card.body_layout.addWidget(self.table, 1)

        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)
        self.btn_add = self.make_secondary_button("파일 선택", self.on_add_files)
        self.btn_remove = self.make_secondary_button("선택 제거", self.on_remove_selected)
        self.btn_reset = self.make_secondary_button("초기화", self.on_reset)
        file_btn_row.addWidget(self.btn_add)
        file_btn_row.addWidget(self.btn_remove)
        file_btn_row.addWidget(self.btn_reset)
        file_btn_row.addStretch(1)
        left_card.body_layout.addLayout(file_btn_row)

        mode_box = QFrame()
        mode_box.setObjectName("infoBox")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(14, 12, 14, 12)
        mode_layout.setSpacing(8)
        mode_layout.addWidget(self.make_label("병합 모드"))
        self.radio_mode1 = QRadioButton("단일 파일의 모든 시트를 하나의 시트로 병합")
        self.radio_mode2 = QRadioButton("여러 파일을 각각 별도 시트로 결합")
        self.radio_mode3 = QRadioButton("같은 시트명끼리 병합")
        self.radio_mode1.setChecked(True)
        for radio in (self.radio_mode1, self.radio_mode2, self.radio_mode3):
            radio.toggled.connect(self.update_mode_ui)
            mode_layout.addWidget(radio)
        right_card.body_layout.addWidget(mode_box)

        option_box = QFrame()
        option_box.setObjectName("infoBox")
        option_layout = QVBoxLayout(option_box)
        option_layout.setContentsMargins(14, 12, 14, 12)
        option_layout.setSpacing(8)
        self.chk_source_file = QCheckBox("원본 파일명 컬럼 추가")
        self.chk_source_sheet = QCheckBox("원본 시트명 컬럼 추가")
        self.chk_include_hidden = QCheckBox("숨김 시트 포함")
        for widget in (self.chk_source_file, self.chk_source_sheet, self.chk_include_hidden):
            option_layout.addWidget(widget)
        right_card.body_layout.addWidget(option_box)

        output_row = QHBoxLayout()
        output_row.setSpacing(8)
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("병합 결과 파일 저장 위치를 선택하세요.")
        self.btn_output = self.make_secondary_button("저장 위치", self.on_select_output)
        output_row.addWidget(self.output_input, 1)
        output_row.addWidget(self.btn_output)
        right_card.body_layout.addLayout(output_row)

        self.mode_summary_label = QLabel()
        self.mode_summary_label.setWordWrap(True)
        self.mode_summary_label.setStyleSheet("font-size:13px; color:#334155;")
        right_card.body_layout.addWidget(self.mode_summary_label)

        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        self.btn_run = self.make_primary_button("병합 실행", self.on_run)
        run_row.addWidget(self.btn_run)
        run_row.addStretch(1)
        right_card.body_layout.addLayout(run_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        right_card.body_layout.addWidget(self.log_view, 1)

        container_layout.addLayout(cards_row, 1)
        outer.addWidget(container, 1)
        outer.addStretch(1)
        root.addLayout(outer, 1)

    def make_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size:13px; font-weight:700; color:{TEXT};")
        return label

    def make_primary_button(self, text: str, handler) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(34)
        button.setStyleSheet(f"""
            QPushButton {{
                background: {BRAND};
                color: white;
                border: 1px solid {BRAND};
                border-radius: 8px;
                padding: 7px 16px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {BRAND_DARK};
            }}
            QPushButton:disabled {{
                background: #9bbce8;
                border-color: #9bbce8;
            }}
        """)
        button.clicked.connect(handler)
        return button

    def make_secondary_button(self, text: str, handler) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setMinimumHeight(32)
        button.setStyleSheet(f"""
            QPushButton {{
                background: #ffffff;
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #f3f6fb;
            }}
            QPushButton:disabled {{
                color: #9ca3af;
                background: #f8fafc;
            }}
        """)
        button.clicked.connect(handler)
        return button

    def current_mode(self) -> str:
        if self.radio_mode2.isChecked():
            return MODE_FILES_TO_SHEETS
        if self.radio_mode3.isChecked():
            return MODE_SAME_SHEETS_TOGETHER
        return MODE_WORKBOOK_SHEETS_TO_ONE

    def update_mode_ui(self) -> None:
        mode = self.current_mode()
        self.chk_source_file.setEnabled(mode == MODE_SAME_SHEETS_TOGETHER and not self.running)
        self.chk_source_sheet.setEnabled(mode != MODE_FILES_TO_SHEETS and not self.running)
        mode_name = {
            MODE_WORKBOOK_SHEETS_TO_ONE: "단일 파일의 모든 시트를 하나의 시트로 병합",
            MODE_FILES_TO_SHEETS: "여러 파일을 각각 별도 시트로 결합",
            MODE_SAME_SHEETS_TOGETHER: "같은 시트명끼리 병합",
        }[mode]
        self.mode_summary_label.setText(f"선택 모드: {mode_name}\n대상 파일: {len(self.files)}개")
        self.btn_run.setEnabled(bool(self.files) and not self.running)

    def on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "병합할 엑셀 파일 선택",
            os.path.expanduser("~"),
            "엑셀/CSV 파일 (*.xlsx *.xlsm *.csv);;모든 파일 (*.*)",
        )
        if not paths:
            return
        added = 0
        skipped = 0
        for raw in paths:
            path = Path(raw).resolve()
            key = str(path).lower()
            if key in self.file_set or not is_supported_file(path):
                skipped += 1
                continue
            self.file_set.add(key)
            self.files.append(path)
            added += 1
        self.refresh_table()
        self.append_log(f"파일 추가: {added}개")
        if skipped:
            self.append_log(f"건너뜀: {skipped}개")

    def refresh_table(self) -> None:
        self.table.setRowCount(0)
        for path in self.files:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [path.name, path.suffix.lower(), str(path)]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.summary_label.setText(f"선택한 파일: {len(self.files)}개")
        self.update_mode_ui()

    def on_remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.files):
                path = self.files.pop(row)
                self.file_set.discard(str(path).lower())
        self.refresh_table()

    def on_reset(self) -> None:
        self.files.clear()
        self.file_set.clear()
        self.output_input.clear()
        self.log_view.clear()
        self.refresh_table()

    def on_select_output(self) -> None:
        default_dir = self.files[0].parent if self.files else Path(os.path.expanduser("~"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "병합 결과 저장",
            str(default_dir / "엑셀_병합결과.xlsx"),
            "Excel 파일 (*.xlsx)",
        )
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.output_input.setText(path)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def set_running(self, running: bool) -> None:
        self.running = running
        for widget in (
            self.btn_add,
            self.btn_remove,
            self.btn_reset,
            self.btn_output,
            self.btn_run,
            self.output_input,
            self.table,
            self.radio_mode1,
            self.radio_mode2,
            self.radio_mode3,
            self.chk_source_file,
            self.chk_source_sheet,
            self.chk_include_hidden,
        ):
            widget.setEnabled(not running)
        self.update_mode_ui()

    def on_run(self) -> None:
        if not self.files:
            QMessageBox.warning(self, "확인", "병합할 파일을 먼저 선택해 주세요.")
            return
        if self.current_mode() == MODE_WORKBOOK_SHEETS_TO_ONE and len(self.files) > 1:
            QMessageBox.information(self, "안내", "이 모드는 첫 번째 파일만 사용합니다.")
        output_text = self.output_input.text().strip()
        if not output_text:
            QMessageBox.warning(self, "확인", "병합 결과 파일 저장 위치를 선택해 주세요.")
            return

        source_paths = self.files[:1] if self.current_mode() == MODE_WORKBOOK_SHEETS_TO_ONE else list(self.files)
        options = MergeOptions(
            mode=self.current_mode(),
            source_paths=source_paths,
            output_path=Path(output_text),
            add_source_file=self.chk_source_file.isChecked(),
            add_source_sheet=self.chk_source_sheet.isChecked(),
            include_hidden_sheets=self.chk_include_hidden.isChecked(),
        )

        if QMessageBox.question(self, "병합 실행 확인", "엑셀 파일을 병합합니다.\n계속할까요?") != QMessageBox.Yes:
            return

        self.log_view.clear()
        self.set_running(True)
        self.worker = ExcelMergeWorker(options)
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_result.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def on_finished(self, result) -> None:
        self.set_running(False)
        self.worker = None
        self.append_log(f"결과 파일: {result.output_path}")
        self.append_log(f"시트 수: {result.sheet_count}, 데이터 행: {result.data_row_count}, 건너뜀: {result.skipped_count}")
        for warning in result.warnings:
            self.append_log(f"- {warning}")
        QMessageBox.information(self, "완료", f"엑셀 병합이 완료되었습니다.\n\n{result.output_path}")

    def on_failed(self, message: str) -> None:
        self.set_running(False)
        self.worker = None
        self.append_log(f"오류: {message}")
        QMessageBox.critical(self, "오류", message)


def build_page():
    return ExcelMergePage()
