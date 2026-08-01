from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from file_inventory_service import (
    collect_inventory,
    default_excel_path,
    get_downloads_folder,
    parse_extension_filter,
    save_inventory_excel,
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


class FileInventoryWorker(QThread):
    log_message = Signal(str)
    finished_result = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self,
        root_folder: Path,
        excel_path: Path,
        include_subfolders: bool,
        target_mode: str,
        ext_filter: set[str],
        exclude_office_temp: bool,
        options_text: str,
    ):
        super().__init__()
        self.root_folder = root_folder
        self.excel_path = excel_path
        self.include_subfolders = include_subfolders
        self.target_mode = target_mode
        self.ext_filter = ext_filter
        self.exclude_office_temp = exclude_office_temp
        self.options_text = options_text

    def run(self) -> None:
        try:
            self.log_message.emit("===== 파일 현황표 작성 시작 =====")
            self.log_message.emit(f"기준 폴더: {self.root_folder}")
            self.log_message.emit(f"엑셀 저장 위치: {self.excel_path}")
            self.log_message.emit(f"수집 대상: {self.target_mode}")
            self.log_message.emit(f"하위 폴더 포함: {'예' if self.include_subfolders else '아니오'}")
            self.log_message.emit(f"Office 임시파일 제외: {'예' if self.exclude_office_temp else '아니오'}")
            self.log_message.emit(f"확장자 필터: {', '.join(sorted(self.ext_filter)) if self.ext_filter else '전체'}")
            self.log_message.emit("")

            inventory = collect_inventory(
                root_folder=self.root_folder,
                include_subfolders=self.include_subfolders,
                target_mode=self.target_mode,
                ext_filter=self.ext_filter,
                exclude_office_temp=self.exclude_office_temp,
                log_func=self.log_message.emit,
            )

            self.log_message.emit(f"수집 완료: {len(inventory.rows)}건")
            self.log_message.emit(f"오류/건너뜀: {len(inventory.errors)}건")
            self.log_message.emit("엑셀 파일을 저장하는 중...")

            save_inventory_excel(
                excel_path=self.excel_path,
                root_folder=self.root_folder,
                inventory=inventory,
                options_text=self.options_text,
            )

            self.log_message.emit(f"저장 완료: {self.excel_path}")
            self.log_message.emit("===== 완료 =====")
            self.finished_result.emit(inventory, str(self.excel_path))
        except Exception as exc:
            self.failed.emit(str(exc))


class FileInventoryPage(QWidget):
    def __init__(self):
        super().__init__()
        self.running = False
        self.worker: FileInventoryWorker | None = None
        self._build_ui()
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
        outer.setContentsMargins(30, 24, 30, 24)
        outer.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(1500)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(18)

        page_title = QLabel("파일 현황표 작성 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("선택한 폴더의 파일·폴더 목록을 엑셀 현황표로 작성합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard("1. 기준 폴더 및 저장 위치", "현황표로 만들 폴더와 엑셀 저장 위치를 선택합니다.")
        right_card = SectionCard("2. 실행 및 진행 상황", "수집 옵션을 확인하고 작성 로그를 확인합니다.")
        left_card.setMinimumWidth(780)
        right_card.setMinimumWidth(520)
        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(10)

        form.addWidget(QLabel("기준 폴더"), 0, 0)
        self.root_input = QLineEdit()
        self.root_input.setPlaceholderText("현황표로 작성할 기준 폴더")
        form.addWidget(self.root_input, 0, 1)
        self.btn_root = self.make_secondary_button("폴더 선택", self.on_select_root)
        form.addWidget(self.btn_root, 0, 2)

        form.addWidget(QLabel("엑셀 저장 위치"), 1, 0)
        self.excel_input = QLineEdit()
        self.excel_input.setPlaceholderText("저장할 .xlsx 파일 경로")
        form.addWidget(self.excel_input, 1, 1)
        self.btn_save = self.make_secondary_button("저장 위치", self.on_select_excel)
        form.addWidget(self.btn_save, 1, 2)
        form.setColumnStretch(1, 1)
        left_card.body_layout.addLayout(form)

        options_card = QFrame()
        options_card.setObjectName("infoBox")
        options_layout = QGridLayout(options_card)
        options_layout.setContentsMargins(14, 12, 14, 12)
        options_layout.setHorizontalSpacing(12)
        options_layout.setVerticalSpacing(10)

        options_layout.addWidget(QLabel("수집 대상"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["파일만", "폴더만", "파일+폴더"])
        self.mode_combo.currentTextChanged.connect(self.update_summary)
        options_layout.addWidget(self.mode_combo, 0, 1)

        self.chk_subfolders = QCheckBox("하위 폴더 포함")
        self.chk_subfolders.setChecked(True)
        self.chk_subfolders.stateChanged.connect(self.update_summary)
        options_layout.addWidget(self.chk_subfolders, 0, 2)

        self.chk_office_temp = QCheckBox("Office 임시파일(~$) 제외")
        self.chk_office_temp.setChecked(True)
        self.chk_office_temp.stateChanged.connect(self.update_summary)
        options_layout.addWidget(self.chk_office_temp, 0, 3)

        self.chk_open_after = QCheckBox("완료 후 저장 폴더 열기")
        self.chk_open_after.setChecked(True)
        options_layout.addWidget(self.chk_open_after, 1, 2, 1, 2)

        options_layout.addWidget(QLabel("확장자 필터"), 1, 0)
        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText("예: hwp, hwpx, pdf, xlsx")
        self.ext_input.textChanged.connect(self.update_summary)
        options_layout.addWidget(self.ext_input, 1, 1)
        options_layout.setColumnStretch(1, 1)
        left_card.body_layout.addWidget(options_card)

        hint = QLabel("확장자 필터를 비워두면 전체 파일을 수집합니다.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        left_card.body_layout.addWidget(hint)
        left_card.body_layout.addStretch(1)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(8)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-size:13px; color:#334155;")
        info_layout.addWidget(self.summary_label)
        right_card.body_layout.addWidget(info_box)

        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        self.btn_reset = self.make_secondary_button("초기화", self.on_reset)
        self.btn_run = QPushButton("현황표 작성")
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
        run_row.addWidget(self.btn_reset)
        run_row.addWidget(self.btn_run)
        run_row.addStretch(1)
        right_card.body_layout.addLayout(run_row)

        log_label = QLabel("진행 상황")
        log_label.setStyleSheet("font-size:13px; font-weight:700; color:#1f2937;")
        right_card.body_layout.addWidget(log_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(320)
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

    def on_select_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "기준 폴더를 선택하세요")
        if not folder:
            return
        self.root_input.setText(folder)
        if not self.excel_input.text().strip():
            self.excel_input.setText(str(default_excel_path()))

    def on_select_excel(self) -> None:
        initial_dir = get_downloads_folder()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "파일 현황표 저장 위치를 선택하세요",
            str(default_excel_path()),
            "엑셀 파일 (*.xlsx);;모든 파일 (*.*)",
        )
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.excel_input.setText(path)

    def on_reset(self) -> None:
        if self.running:
            return
        self.root_input.clear()
        self.excel_input.clear()
        self.ext_input.clear()
        self.mode_combo.setCurrentText("파일만")
        self.chk_subfolders.setChecked(True)
        self.chk_office_temp.setChecked(True)
        self.chk_open_after.setChecked(True)
        self.log_view.clear()
        self.update_summary()

    def update_summary(self, *_args) -> None:
        ext_filter = parse_extension_filter(self.ext_input.text() if hasattr(self, "ext_input") else "")
        text = (
            f"수집 대상: {self.mode_combo.currentText() if hasattr(self, 'mode_combo') else '파일만'}\n"
            f"하위 폴더 포함: {'예' if getattr(self, 'chk_subfolders', None) and self.chk_subfolders.isChecked() else '아니오'}\n"
            f"Office 임시파일 제외: {'예' if getattr(self, 'chk_office_temp', None) and self.chk_office_temp.isChecked() else '아니오'}\n"
            f"확장자 필터: {', '.join(sorted(ext_filter)) if ext_filter else '전체'}"
        )
        self.summary_label.setText(text)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def on_run(self) -> None:
        if self.running:
            return

        root_folder_text = self.root_input.text().strip()
        excel_path_text = self.excel_input.text().strip()

        if not root_folder_text:
            QMessageBox.warning(self, "확인", "기준 폴더를 선택해 주세요.")
            return
        root_folder = Path(root_folder_text)
        if not root_folder.is_dir():
            QMessageBox.warning(self, "확인", "기준 폴더 경로가 존재하지 않습니다.")
            return
        if not excel_path_text:
            QMessageBox.warning(self, "확인", "엑셀 저장 위치를 선택해 주세요.")
            return

        if not excel_path_text.lower().endswith(".xlsx"):
            excel_path_text += ".xlsx"
            self.excel_input.setText(excel_path_text)

        excel_path = Path(excel_path_text)
        save_dir = excel_path.parent
        if save_dir and not save_dir.is_dir():
            QMessageBox.warning(self, "확인", "엑셀 저장 폴더가 존재하지 않습니다.")
            return

        include_subfolders = self.chk_subfolders.isChecked()
        target_mode = self.mode_combo.currentText()
        exclude_office_temp = self.chk_office_temp.isChecked()
        ext_filter = parse_extension_filter(self.ext_input.text())
        options_text = (
            f"수집 대상={target_mode}, "
            f"하위 폴더 포함={'예' if include_subfolders else '아니오'}, "
            f"Office 임시파일 제외={'예' if exclude_office_temp else '아니오'}, "
            f"확장자 필터={', '.join(sorted(ext_filter)) if ext_filter else '전체'}"
        )

        self.log_view.clear()
        self.set_running(True)
        self.worker = FileInventoryWorker(
            root_folder=root_folder,
            excel_path=excel_path,
            include_subfolders=include_subfolders,
            target_mode=target_mode,
            ext_filter=ext_filter,
            exclude_office_temp=exclude_office_temp,
            options_text=options_text,
        )
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_result.connect(self.on_worker_finished)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def set_running(self, value: bool) -> None:
        self.running = value
        for widget in (
            self.btn_root,
            self.btn_save,
            self.btn_reset,
            self.btn_run,
            self.root_input,
            self.excel_input,
            self.ext_input,
            self.mode_combo,
            self.chk_subfolders,
            self.chk_office_temp,
            self.chk_open_after,
        ):
            widget.setEnabled(not value)

    def on_worker_finished(self, inventory, excel_path: str) -> None:
        self.set_running(False)
        QMessageBox.information(
            self,
            "완료",
            (
                "파일 현황표 작성이 완료되었습니다.\n\n"
                f"목록 건수: {len(inventory.rows)}건\n"
                f"오류/건너뜀: {len(inventory.errors)}건\n\n"
                f"저장 위치:\n{excel_path}"
            ),
        )
        if self.chk_open_after.isChecked():
            try:
                if os.name == "nt":
                    os.startfile(str(Path(excel_path).parent))
            except Exception:
                pass

    def on_worker_failed(self, message: str) -> None:
        self.set_running(False)
        self.append_log(f"실행 중 오류 발생: {message}")
        QMessageBox.critical(self, "오류", f"실행 중 문제가 발생했습니다.\n\n{message}")


def build_page():
    return FileInventoryPage()
