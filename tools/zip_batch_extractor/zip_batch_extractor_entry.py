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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from zip_batch_extractor_service import (
    EXTRACT_DIRECT,
    EXTRACT_TO_NAMED_FOLDER,
    OUTPUT_CUSTOM,
    OUTPUT_ORIGINAL,
    extract_zip_batch,
    format_size,
    get_downloads_folder,
    is_zip_file,
    scan_zip_files,
    zip_file_display_name,
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


class ZipExtractWorker(QThread):
    log_message = Signal(str)
    finished_result = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        zip_files: list[Path],
        output_location_mode: str,
        extract_mode: str,
        custom_output_folder: Path,
        exclude_junk: bool,
        password_text: str,
    ):
        super().__init__()
        self.zip_files = zip_files
        self.output_location_mode = output_location_mode
        self.extract_mode = extract_mode
        self.custom_output_folder = custom_output_folder
        self.exclude_junk = exclude_junk
        self.password_text = password_text

    def run(self) -> None:
        try:
            result = extract_zip_batch(
                zip_files=self.zip_files,
                output_location_mode=self.output_location_mode,
                extract_mode=self.extract_mode,
                custom_output_folder=self.custom_output_folder,
                exclude_junk=self.exclude_junk,
                password_text=self.password_text,
                log_func=self.log_message.emit,
            )
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ZipBatchExtractorPage(QWidget):
    def __init__(self):
        super().__init__()
        self.zip_files: list[Path] = []
        self.zip_set: set[str] = set()
        self.worker: ZipExtractWorker | None = None
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
            QLineEdit, QComboBox {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 22px;
                font-size: 13px;
                color: {TEXT};
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {BRAND};
            }}
            QCheckBox {{
                background: transparent;
                color: {TEXT};
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
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
            QHeaderView::section {{
                background: #f8fafc;
                color: #344054;
                border: none;
                border-right: 1px solid #e5edf7;
                border-bottom: 1px solid #e5edf7;
                padding: 8px;
                font-weight: 700;
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

        page_title = QLabel("압축파일 일괄 풀기 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("여러 ZIP 파일을 선택해 지정한 방식으로 일괄 압축 해제합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard("1. ZIP 파일 선택", "압축 해제할 ZIP 파일을 추가하거나 폴더에서 찾아옵니다.")
        right_card = SectionCard("2. 옵션 및 진행 상황", "저장 위치와 풀기 방식을 선택하고 진행 로그를 확인합니다.")
        left_card.body_layout.setSpacing(10)
        right_card.body_layout.setSpacing(8)
        left_card.setMinimumWidth(780)
        right_card.setMinimumWidth(520)
        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        left_card.body_layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파일명", "크기", "전체경로"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        left_card.body_layout.addWidget(self.table, 1)

        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)
        self.btn_add_files = self.make_secondary_button("ZIP 파일 선택", self.on_add_zip_files)
        self.btn_scan_folder = self.make_secondary_button("폴더에서 찾기", self.on_scan_folder)
        self.btn_remove = self.make_secondary_button("선택 제거", self.on_remove_selected)
        self.btn_reset = self.make_secondary_button("초기화", self.on_reset)
        file_btn_row.addWidget(self.btn_add_files)
        file_btn_row.addWidget(self.btn_scan_folder)
        file_btn_row.addWidget(self.btn_remove)
        file_btn_row.addWidget(self.btn_reset)
        file_btn_row.addStretch(1)
        left_card.body_layout.addLayout(file_btn_row)

        option_box = QFrame()
        option_box.setObjectName("infoBox")
        option_layout = QGridLayout(option_box)
        option_layout.setContentsMargins(14, 12, 14, 12)
        option_layout.setHorizontalSpacing(10)
        option_layout.setVerticalSpacing(6)

        option_layout.addWidget(QLabel("저장 위치"), 0, 0)
        self.output_combo = QComboBox()
        self.output_combo.addItems([OUTPUT_ORIGINAL, OUTPUT_CUSTOM])
        self.output_combo.currentTextChanged.connect(self.update_summary)
        option_layout.addWidget(self.output_combo, 0, 1)

        option_layout.addWidget(QLabel("풀기 방식"), 0, 2)
        self.extract_combo = QComboBox()
        self.extract_combo.addItems([EXTRACT_TO_NAMED_FOLDER, EXTRACT_DIRECT])
        self.extract_combo.currentTextChanged.connect(self.update_summary)
        option_layout.addWidget(self.extract_combo, 0, 3)

        option_layout.addWidget(QLabel("지정 위치"), 1, 0)
        self.output_input = QLineEdit(str(get_downloads_folder()))
        self.output_input.textChanged.connect(self.update_summary)
        option_layout.addWidget(self.output_input, 1, 1, 1, 2)
        self.btn_output = self.make_secondary_button("선택", self.on_select_output_folder)
        option_layout.addWidget(self.btn_output, 1, 3)

        option_layout.addWidget(QLabel("공통 비밀번호"), 2, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        option_layout.addWidget(self.password_input, 2, 1)

        self.chk_subfolders = QCheckBox("폴더 검색 시 하위 폴더 포함")
        self.chk_subfolders.setChecked(True)
        option_layout.addWidget(self.chk_subfolders, 2, 2, 1, 2)

        self.chk_junk = QCheckBox("불필요 파일 제외")
        self.chk_junk.setChecked(True)
        self.chk_junk.stateChanged.connect(self.update_summary)
        option_layout.addWidget(self.chk_junk, 3, 1)

        self.chk_open_after = QCheckBox("완료 후 저장 폴더 열기")
        self.chk_open_after.setChecked(True)
        option_layout.addWidget(self.chk_open_after, 3, 2, 1, 2)
        option_layout.setColumnStretch(1, 1)
        option_layout.setColumnStretch(3, 1)
        right_card.body_layout.addWidget(option_box)

        self.run_summary_label = QLabel()
        self.run_summary_label.setWordWrap(True)
        self.run_summary_label.setStyleSheet("font-size:13px; color:#334155;")
        right_card.body_layout.addWidget(self.run_summary_label)

        self.btn_run = QPushButton("ZIP 풀기 실행")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setStyleSheet(f"""
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
            QPushButton:disabled {{
                background: #98a2b3;
                border-color: #98a2b3;
            }}
        """)
        self.btn_run.clicked.connect(self.on_run)
        right_card.body_layout.addWidget(self.btn_run, alignment=Qt.AlignLeft)

        log_label = QLabel("진행 상황")
        log_label.setStyleSheet("font-size:13px; font-weight:700; color:#1f2937;")
        right_card.body_layout.addWidget(log_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        right_card.body_layout.addWidget(self.log_view, 1)

        container_layout.addLayout(cards_row, 1)
        outer.addWidget(container)
        outer.addStretch(1)
        root.addLayout(outer, 1)

    def make_secondary_button(self, text: str, callback):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setStyleSheet(f"""
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
            QPushButton:disabled {{
                color: #98a2b3;
                background: #f2f4f7;
            }}
        """)
        button.clicked.connect(callback)
        return button

    def normalize_zip_path(self, path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def on_add_zip_files(self) -> None:
        if self.running:
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "압축 해제할 ZIP 파일을 선택하세요",
            "",
            "ZIP 파일 (*.zip);;모든 파일 (*.*)",
        )
        if not paths:
            return

        added, skipped = self.add_zip_paths([Path(path) for path in paths])
        self.append_log(f"ZIP 파일 추가: {added}개")
        if skipped:
            self.append_log(f"건너뜀: {skipped}개")

    def on_scan_folder(self) -> None:
        if self.running:
            return

        folder = QFileDialog.getExistingDirectory(self, "ZIP 파일을 찾을 폴더를 선택하세요")
        if not folder:
            return

        try:
            found = scan_zip_files(folder, include_subfolders=self.chk_subfolders.isChecked())
            added, skipped = self.add_zip_paths(found)
            self.append_log(f"폴더에서 ZIP 찾기 완료: 추가 {added}개")
            if skipped:
                self.append_log(f"건너뜀: {skipped}개")
        except Exception as exc:
            QMessageBox.critical(self, "오류", f"폴더 조회 중 문제가 발생했습니다.\n\n{exc}")

    def add_zip_paths(self, paths: list[Path]) -> tuple[int, int]:
        added = 0
        skipped = 0
        for path in paths:
            if not is_zip_file(path):
                skipped += 1
                continue
            resolved = path.resolve()
            normalized = self.normalize_zip_path(resolved)
            if normalized in self.zip_set:
                skipped += 1
                continue
            self.zip_set.add(normalized)
            self.zip_files.append(resolved)
            added += 1
        self.refresh_table()
        return added, skipped

    def on_remove_selected(self) -> None:
        if self.running:
            return

        selected_rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        if not selected_rows:
            QMessageBox.information(self, "안내", "목록에서 제거할 항목을 선택해 주세요.")
            return

        for row in selected_rows:
            if 0 <= row < len(self.zip_files):
                path = self.zip_files.pop(row)
                self.zip_set.discard(self.normalize_zip_path(path))
        self.refresh_table()

    def on_reset(self) -> None:
        if self.running:
            return
        self.zip_files.clear()
        self.zip_set.clear()
        self.log_view.clear()
        self.refresh_table()

    def on_select_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "압축 해제 파일을 저장할 위치를 선택하세요")
        if folder:
            self.output_input.setText(folder)

    def refresh_table(self) -> None:
        self.table.setRowCount(0)
        valid_files: list[Path] = []
        self.zip_set.clear()

        for path in self.zip_files:
            if not is_zip_file(path):
                continue
            valid_files.append(path)
            self.zip_set.add(self.normalize_zip_path(path))
            row = self.table.rowCount()
            self.table.insertRow(row)

            try:
                size_text = format_size(path.stat().st_size)
            except Exception:
                size_text = ""

            values = [zip_file_display_name(path), size_text, str(path)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)

        self.zip_files = valid_files
        self.summary_label.setText(f"선택한 ZIP 파일: {len(self.zip_files)}개")
        self.update_summary()

    def update_summary(self, *_args) -> None:
        output_mode = self.output_combo.currentText() if hasattr(self, "output_combo") else OUTPUT_ORIGINAL
        extract_mode = self.extract_combo.currentText() if hasattr(self, "extract_combo") else EXTRACT_TO_NAMED_FOLDER
        text = (
            f"실행 대상 ZIP: {len(self.zip_files)}개\n"
            f"저장 위치: {output_mode}\n"
            f"풀기 방식: {extract_mode}\n"
            f"불필요 파일 제외: {'예' if getattr(self, 'chk_junk', None) and self.chk_junk.isChecked() else '아니오'}"
        )
        if output_mode == OUTPUT_CUSTOM and hasattr(self, "output_input"):
            text += f"\n지정 위치: {self.output_input.text().strip() or '(미선택)'}"
        self.run_summary_label.setText(text)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def on_run(self) -> None:
        if self.running:
            return

        zip_files = [path for path in self.zip_files if is_zip_file(path)]
        if not zip_files:
            QMessageBox.warning(self, "확인", "압축 해제할 ZIP 파일을 먼저 추가해 주세요.")
            return

        output_mode = self.output_combo.currentText()
        extract_mode = self.extract_combo.currentText()
        output_folder = Path(self.output_input.text().strip() or str(get_downloads_folder()))
        if output_mode == OUTPUT_CUSTOM and not output_folder.is_dir():
            QMessageBox.warning(self, "확인", "지정 위치 폴더가 존재하지 않습니다.")
            return

        message = (
            f"ZIP 파일 {len(zip_files)}개를 압축 해제합니다.\n\n"
            f"저장 위치: {output_mode}\n"
            f"풀기 방식: {extract_mode}\n\n"
            "같은 이름의 파일이나 폴더가 있으면 자동으로 (1), (2)를 붙입니다.\n\n"
            "계속할까요?"
        )
        answer = QMessageBox.question(self, "실행 확인", message)
        if answer != QMessageBox.Yes:
            return

        self.log_view.clear()
        self.set_running(True)
        self.worker = ZipExtractWorker(
            zip_files=zip_files,
            output_location_mode=output_mode,
            extract_mode=extract_mode,
            custom_output_folder=output_folder,
            exclude_junk=self.chk_junk.isChecked(),
            password_text=self.password_input.text(),
        )
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_result.connect(self.on_worker_finished)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def set_running(self, value: bool) -> None:
        self.running = value
        for widget in (
            self.btn_add_files,
            self.btn_scan_folder,
            self.btn_remove,
            self.btn_reset,
            self.btn_output,
            self.btn_run,
            self.output_combo,
            self.extract_combo,
            self.output_input,
            self.password_input,
            self.chk_subfolders,
            self.chk_junk,
            self.chk_open_after,
        ):
            widget.setEnabled(not value)

    def on_worker_finished(self, result) -> None:
        self.set_running(False)
        QMessageBox.information(
            self,
            "완료",
            (
                "ZIP 일괄 풀기가 완료되었습니다.\n\n"
                f"성공 ZIP: {result.success_count}개\n"
                f"실패 ZIP: {result.fail_count}개\n"
                f"압축 해제 파일: {result.total_files}개\n"
                f"오류: {result.total_errors}개"
            ),
        )

        if self.chk_open_after.isChecked() and result.opened_folder is not None:
            try:
                if os.name == "nt":
                    os.startfile(str(result.opened_folder))
            except Exception:
                pass

    def on_worker_failed(self, message: str) -> None:
        self.set_running(False)
        self.append_log(f"실행 중 오류 발생: {message}")
        QMessageBox.critical(self, "오류", f"실행 중 문제가 발생했습니다.\n\n{message}")


def build_page():
    return ZipBatchExtractorPage()
