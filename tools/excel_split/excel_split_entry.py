from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from excel_split_service import (
    MODE_CHUNK,
    MODE_COLUMN,
    MODE_SHEET,
    SplitOptions,
    analyze_workbook,
    preview_rows,
    split_excel,
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


class ExcelSplitWorker(QThread):
    log_message = Signal(str)
    finished_result = Signal(object)
    failed = Signal(str)

    def __init__(self, options: SplitOptions):
        super().__init__()
        self.options = options

    def run(self) -> None:
        try:
            self.log_message.emit("===== 엑셀 분할 시작 =====")
            result = split_excel(self.options, self.log_message.emit)
            self.log_message.emit("===== 완료 =====")
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ExcelSplitPage(QWidget):
    def __init__(self):
        super().__init__()
        self.source_path: Path | None = None
        self.workbook_info = None
        self.worker: ExcelSplitWorker | None = None
        self.running = False
        self._build_ui()
        self.update_mode_ui()
        self.update_summary()

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
            QLineEdit, QComboBox, QSpinBox {{
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
                font-size: 12px;
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

        page_title = QLabel("엑셀 분할 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("하나의 엑셀 파일을 열 값, 시트, 행 수 기준으로 여러 파일로 분할합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard("1. 파일 선택 및 분할 기준", "원본 파일과 분할 방식을 선택합니다.")
        right_card = SectionCard("2. 미리보기 및 진행 상황", "선택한 시트 구조와 처리 로그를 확인합니다.")
        left_card.body_layout.setSpacing(10)
        right_card.body_layout.setSpacing(8)
        left_card.setMinimumWidth(620)
        right_card.setMinimumWidth(720)
        cards_row.addWidget(left_card, 2)
        cards_row.addWidget(right_card, 3)

        file_row = QHBoxLayout()
        self.source_input = QLineEdit()
        self.source_input.setReadOnly(True)
        self.source_input.setPlaceholderText("분할할 엑셀 파일을 선택하세요.")
        self.btn_file = self.make_secondary_button("파일 선택", self.on_select_file)
        file_row.addWidget(self.source_input, 1)
        file_row.addWidget(self.btn_file)
        left_card.body_layout.addLayout(file_row)

        output_row = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("분할 결과를 저장할 폴더를 선택하세요.")
        self.btn_output = self.make_secondary_button("저장 폴더", self.on_select_output)
        output_row.addWidget(self.output_input, 1)
        output_row.addWidget(self.btn_output)
        left_card.body_layout.addLayout(output_row)

        mode_box = QFrame()
        mode_box.setObjectName("infoBox")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(14, 12, 14, 12)
        mode_layout.setSpacing(8)
        mode_layout.addWidget(self.make_label("분할 모드"))
        self.radio_column = QRadioButton("특정 열 값별 분할")
        self.radio_sheet = QRadioButton("시트별 분할")
        self.radio_chunk = QRadioButton("행 수 기준 분할")
        self.radio_column.setChecked(True)
        for radio in (self.radio_column, self.radio_sheet, self.radio_chunk):
            radio.toggled.connect(self.update_mode_ui)
            mode_layout.addWidget(radio)
        left_card.body_layout.addWidget(mode_box)

        option_box = QFrame()
        option_box.setObjectName("infoBox")
        option_layout = QGridLayout(option_box)
        option_layout.setContentsMargins(14, 12, 14, 12)
        option_layout.setHorizontalSpacing(8)
        option_layout.setVerticalSpacing(8)

        option_layout.addWidget(QLabel("시트"), 0, 0)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.on_sheet_changed)
        option_layout.addWidget(self.sheet_combo, 0, 1, 1, 3)

        self.chk_auto_header = QCheckBox("헤더 행 자동 감지")
        self.chk_auto_header.setChecked(True)
        self.chk_auto_header.stateChanged.connect(self.apply_auto_header)
        option_layout.addWidget(self.chk_auto_header, 1, 0, 1, 2)

        option_layout.addWidget(QLabel("헤더 행"), 1, 2)
        self.header_spin = QSpinBox()
        self.header_spin.setRange(1, 100000)
        self.header_spin.setValue(1)
        self.header_spin.valueChanged.connect(self.refresh_column_options)
        option_layout.addWidget(self.header_spin, 1, 3)

        option_layout.addWidget(QLabel("기준 열"), 2, 0)
        self.column_combo = QComboBox()
        option_layout.addWidget(self.column_combo, 2, 1, 1, 3)

        self.chk_skip_empty = QCheckBox("기준 열 값이 비어있는 행은 건너뛰기")
        self.chk_skip_empty.setChecked(True)
        option_layout.addWidget(self.chk_skip_empty, 3, 0, 1, 4)

        option_layout.addWidget(QLabel("파일당 데이터 행 수"), 4, 0, 1, 2)
        self.rows_per_file_spin = QSpinBox()
        self.rows_per_file_spin.setRange(1, 1000000)
        self.rows_per_file_spin.setValue(1000)
        option_layout.addWidget(self.rows_per_file_spin, 4, 2, 1, 2)

        left_card.body_layout.addWidget(option_box)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-size:13px; color:#334155;")
        left_card.body_layout.addWidget(self.summary_label)

        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        self.btn_run = self.make_primary_button("분할 실행", self.on_run)
        self.btn_reset = self.make_secondary_button("초기화", self.on_reset)
        run_row.addWidget(self.btn_run)
        run_row.addWidget(self.btn_reset)
        run_row.addStretch(1)
        left_card.body_layout.addLayout(run_row)
        left_card.body_layout.addStretch(1)

        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setMinimumHeight(240)
        right_card.body_layout.addWidget(self.preview_table, 2)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)
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
        if self.radio_sheet.isChecked():
            return MODE_SHEET
        if self.radio_chunk.isChecked():
            return MODE_CHUNK
        return MODE_COLUMN

    def update_mode_ui(self) -> None:
        mode = self.current_mode()
        is_column = mode == MODE_COLUMN
        is_chunk = mode == MODE_CHUNK
        editable = not self.running
        self.column_combo.setEnabled(editable and is_column)
        self.chk_skip_empty.setEnabled(editable and is_column)
        self.rows_per_file_spin.setEnabled(editable and is_chunk)
        self.sheet_combo.setEnabled(editable and mode != MODE_SHEET)
        self.header_spin.setEnabled(editable and mode != MODE_SHEET)
        self.chk_auto_header.setEnabled(editable and mode != MODE_SHEET)
        self.update_summary()

    def on_select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "분할할 엑셀 파일 선택",
            os.path.expanduser("~"),
            "엑셀/CSV 파일 (*.xlsx *.xlsm *.csv);;모든 파일 (*.*)",
        )
        if not path:
            return
        self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        try:
            info = analyze_workbook(path)
        except Exception as exc:
            QMessageBox.critical(self, "파일 읽기 실패", str(exc))
            return

        self.source_path = path
        self.workbook_info = info
        self.source_input.setText(str(path))
        if not self.output_input.text().strip():
            self.output_input.setText(str(path.parent / f"{path.stem}_분할결과"))

        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        for sheet in info.sheet_infos:
            self.sheet_combo.addItem(sheet.name)
        self.sheet_combo.blockSignals(False)

        self.apply_auto_header()
        self.refresh_column_options()
        self.refresh_preview()
        self.append_log(f"파일을 읽었습니다: {path.name}")
        self.update_summary()

    def on_select_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "분할 결과 저장 폴더 선택", os.path.expanduser("~"))
        if folder:
            self.output_input.setText(folder)
            self.update_summary()

    def selected_sheet_info(self):
        if not self.workbook_info:
            return None
        current = self.sheet_combo.currentText()
        for sheet in self.workbook_info.sheet_infos:
            if sheet.name == current:
                return sheet
        return self.workbook_info.sheet_infos[0] if self.workbook_info.sheet_infos else None

    def on_sheet_changed(self) -> None:
        self.apply_auto_header()
        self.refresh_column_options()
        self.refresh_preview()
        self.update_summary()

    def apply_auto_header(self) -> None:
        sheet = self.selected_sheet_info()
        if sheet and self.chk_auto_header.isChecked():
            self.header_spin.blockSignals(True)
            self.header_spin.setValue(sheet.auto_header_row)
            self.header_spin.blockSignals(False)
        self.refresh_column_options()

    def refresh_column_options(self) -> None:
        sheet = self.selected_sheet_info()
        self.column_combo.clear()
        if not sheet:
            return
        headers = sheet.headers
        if self.source_path and self.sheet_combo.currentText():
            try:
                from excel_split_service import load_source_workbook, get_headers
                wb, _ = load_source_workbook(self.source_path, data_only=True)
                ws = wb[self.sheet_combo.currentText()]
                headers = get_headers(ws, self.header_spin.value())
            except Exception:
                pass
        for index, header in enumerate(headers, start=1):
            self.column_combo.addItem(f"{index}열 - {header}", index)

    def refresh_preview(self) -> None:
        self.preview_table.clear()
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        if not self.source_path or not self.sheet_combo.currentText():
            return
        try:
            rows = preview_rows(self.source_path, self.sheet_combo.currentText(), max_rows=80, max_cols=20)
        except Exception as exc:
            self.append_log(f"미리보기 실패: {exc}")
            return
        if not rows:
            return
        max_cols = max(len(row) for row in rows)
        self.preview_table.setColumnCount(max_cols)
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setHorizontalHeaderLabels([str(i) for i in range(1, max_cols + 1)])
        for row_idx, row in enumerate(rows):
            for col_idx in range(max_cols):
                self.preview_table.setItem(row_idx, col_idx, QTableWidgetItem(row[col_idx] if col_idx < len(row) else ""))
        self.preview_table.resizeColumnsToContents()

    def update_summary(self) -> None:
        file_text = self.source_path.name if self.source_path else "미선택"
        output = self.output_input.text().strip() or "미선택"
        mode_text = {
            MODE_COLUMN: "특정 열 값별 분할",
            MODE_SHEET: "시트별 분할",
            MODE_CHUNK: "행 수 기준 분할",
        }[self.current_mode()]
        self.summary_label.setText(f"원본 파일: {file_text}\n실행 방식: {mode_text}\n저장 폴더: {output}")
        self.btn_run.setEnabled(bool(self.source_path) and not self.running)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def set_running(self, running: bool) -> None:
        self.running = running
        for widget in (
            self.btn_file,
            self.btn_output,
            self.btn_run,
            self.btn_reset,
            self.source_input,
            self.output_input,
            self.radio_column,
            self.radio_sheet,
            self.radio_chunk,
            self.sheet_combo,
            self.chk_auto_header,
            self.header_spin,
            self.column_combo,
            self.chk_skip_empty,
            self.rows_per_file_spin,
        ):
            widget.setEnabled(not running)
        self.update_mode_ui()
        self.btn_run.setEnabled(bool(self.source_path) and not running)

    def on_run(self) -> None:
        if not self.source_path:
            QMessageBox.warning(self, "확인", "분할할 파일을 먼저 선택해 주세요.")
            return
        output_text = self.output_input.text().strip()
        if not output_text:
            QMessageBox.warning(self, "확인", "분할 결과를 저장할 폴더를 선택해 주세요.")
            return

        split_column = self.column_combo.currentData() or 1
        options = SplitOptions(
            mode=self.current_mode(),
            source_path=self.source_path,
            output_folder=Path(output_text),
            sheet_name=self.sheet_combo.currentText(),
            header_row=self.header_spin.value(),
            split_column=int(split_column),
            rows_per_file=self.rows_per_file_spin.value(),
            skip_empty_key=self.chk_skip_empty.isChecked(),
        )

        message = (
            f"분할 방식: {self.summary_label.text()}\n\n"
            "분할 결과 파일을 저장 폴더에 생성합니다.\n계속할까요?"
        )
        if QMessageBox.question(self, "분할 실행 확인", message) != QMessageBox.Yes:
            return

        self.log_view.clear()
        self.set_running(True)
        self.worker = ExcelSplitWorker(options)
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_result.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def on_finished(self, result) -> None:
        self.set_running(False)
        self.worker = None
        self.append_log(f"생성 파일: {result.created_count}개 / 오류: {len(result.errors)}개")
        for error in result.errors[:20]:
            self.append_log(f"- {error}")
        if result.errors:
            QMessageBox.warning(self, "완료", f"일부 항목 처리에 실패했습니다.\n생성: {result.created_count}개\n오류: {len(result.errors)}개")
        else:
            QMessageBox.information(self, "완료", f"엑셀 분할이 완료되었습니다.\n생성 파일: {result.created_count}개")

    def on_failed(self, message: str) -> None:
        self.set_running(False)
        self.worker = None
        self.append_log(f"오류: {message}")
        QMessageBox.critical(self, "오류", message)

    def on_reset(self) -> None:
        self.source_path = None
        self.workbook_info = None
        self.source_input.clear()
        self.output_input.clear()
        self.sheet_combo.clear()
        self.column_combo.clear()
        self.header_spin.setValue(1)
        self.rows_per_file_spin.setValue(1000)
        self.preview_table.clear()
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        self.log_view.clear()
        self.update_summary()


def build_page():
    return ExcelSplitPage()
