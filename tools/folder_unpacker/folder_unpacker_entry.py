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
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from folder_unpacker_service import (
    filter_redundant_folders,
    is_drive_root,
    normalize_folder_path,
    select_folders_multi_windows,
    summarize_folder,
    unpack_folders,
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


class FolderUnpackWorker(QThread):
    log_message = Signal(str)
    finished_result = Signal(object)
    failed = Signal(str)

    def __init__(self, folders: list[Path], recursive: bool, prefix_folder: bool):
        super().__init__()
        self.folders = folders
        self.recursive = recursive
        self.prefix_folder = prefix_folder

    def run(self) -> None:
        try:
            result = unpack_folders(
                self.folders,
                recursive=self.recursive,
                prefix_folder=self.prefix_folder,
                log=self.log_message.emit,
            )
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class FolderUnpackerPage(QWidget):
    def __init__(self):
        super().__init__()
        self.folders: list[Path] = []
        self.folder_set: set[str] = set()
        self.worker: FolderUnpackWorker | None = None
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
            QCheckBox {{
                background: transparent;
                color: {TEXT};
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
            }}
            QFrame#infoBox {{
                background: {INFO_BG};
                border: 1px dashed #cfdcf2;
                border-radius: 8px;
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
        container.setMaximumWidth(1500)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(18)

        page_title = QLabel("파일 꺼내기 도구(v1.3)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("선택한 폴더 안의 파일을 상위 폴더로 이동하고 빈 폴더를 정리합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard("1. 폴더 선택", "파일을 꺼낼 폴더를 추가하고 처리 옵션을 선택합니다.")
        right_card = SectionCard("2. 실행 및 진행 상황", "실행 전 내용을 확인하고 처리 로그를 확인합니다.")
        left_card.setMinimumWidth(780)
        right_card.setMinimumWidth(520)
        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        left_card.body_layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["폴더명", "이동 위치", "파일", "하위", "경로"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        left_card.body_layout.addWidget(self.table, 1)

        folder_btn_row = QHBoxLayout()
        folder_btn_row.setSpacing(8)
        self.btn_add = self.make_secondary_button("폴더 선택", self.on_add_folders)
        self.btn_remove = self.make_secondary_button("선택 제거", self.on_remove_selected)
        self.btn_reset = self.make_secondary_button("초기화", self.on_reset)
        folder_btn_row.addWidget(self.btn_add)
        folder_btn_row.addWidget(self.btn_remove)
        folder_btn_row.addWidget(self.btn_reset)
        folder_btn_row.addStretch(1)
        left_card.body_layout.addLayout(folder_btn_row)

        self.chk_recursive = QCheckBox("하위 폴더 파일까지 포함")
        self.chk_recursive.setChecked(True)
        self.chk_recursive.stateChanged.connect(self.refresh_table)

        self.chk_prefix = QCheckBox("파일명 앞에 폴더명 붙이기")
        self.chk_prefix.stateChanged.connect(self.update_run_summary)
        option_row = QHBoxLayout()
        option_row.setSpacing(18)
        option_row.addWidget(self.chk_recursive)
        option_row.addWidget(self.chk_prefix)
        option_row.addStretch(1)
        left_card.body_layout.addLayout(option_row)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(8)

        self.run_summary_label = QLabel()
        self.run_summary_label.setWordWrap(True)
        self.run_summary_label.setStyleSheet("font-size:13px; color:#334155;")
        info_layout.addWidget(self.run_summary_label)

        hint = QLabel("파일은 삭제하지 않고 이동합니다. 이동 후 비어 있는 폴더만 삭제됩니다.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)
        right_card.body_layout.addWidget(info_box)

        self.btn_run = QPushButton("파일 꺼내기 실행")
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
        self.log_view.setMinimumHeight(300)
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

    def on_add_folders(self) -> None:
        if self.running:
            return

        selected_paths = select_folders_multi_windows("파일을 꺼낼 폴더를 선택하세요")
        if selected_paths is None:
            folder = QFileDialog.getExistingDirectory(self, "파일을 꺼낼 폴더를 선택하세요")
            selected_paths = [folder] if folder else []

        if not selected_paths:
            return

        added = 0
        skipped = 0
        for folder in selected_paths:
            if self.add_folder(folder):
                added += 1
            else:
                skipped += 1

        self.append_log(f"폴더 추가: {added}개")
        if skipped:
            self.append_log(f"건너뜀: {skipped}개")
        self.refresh_table()

    def add_folder(self, folder: str | Path) -> bool:
        path = Path(folder).resolve()
        if not path.is_dir():
            return False

        if is_drive_root(path):
            QMessageBox.warning(self, "확인", "드라이브 루트 폴더는 선택할 수 없습니다.")
            return False

        norm = normalize_folder_path(path)
        if norm in self.folder_set:
            return False

        self.folder_set.add(norm)
        self.folders.append(path)
        return True

    def on_remove_selected(self) -> None:
        if self.running:
            return

        selected_rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        if not selected_rows:
            QMessageBox.information(self, "안내", "목록에서 제거할 폴더를 선택해 주세요.")
            return

        for row in selected_rows:
            if 0 <= row < len(self.folders):
                folder = self.folders.pop(row)
                self.folder_set.discard(normalize_folder_path(folder))
        self.refresh_table()

    def on_reset(self) -> None:
        if self.running:
            return
        self.folders.clear()
        self.folder_set.clear()
        self.log_view.clear()
        self.refresh_table()

    def refresh_table(self, *_args) -> None:
        recursive = self.chk_recursive.isChecked() if hasattr(self, "chk_recursive") else True
        self.table.setRowCount(0)

        valid_folders: list[Path] = []
        self.folder_set.clear()

        for folder in self.folders:
            if not folder.is_dir():
                continue
            valid_folders.append(folder)
            self.folder_set.add(normalize_folder_path(folder))

            summary = summarize_folder(folder, recursive=recursive)
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                summary.path.name,
                str(summary.path.parent),
                str(summary.file_count),
                str(summary.subfolder_count),
                str(summary.path),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)

        self.folders = valid_folders
        count = len(self.folders)
        self.summary_label.setText(f"선택한 폴더: {count}개")
        self.update_run_summary()

    def update_run_summary(self, *_args) -> None:
        recursive = self.chk_recursive.isChecked() if hasattr(self, "chk_recursive") else True
        target_folders, redundant_folders = filter_redundant_folders(self.folders, recursive=recursive)
        text = (
            f"실행 대상 폴더: {len(target_folders)}개\n"
            f"중복 제외 폴더: {len(redundant_folders)}개\n"
            f"하위 폴더 포함: {'예' if recursive else '아니오'}"
        )
        if hasattr(self, "chk_prefix"):
            text += f"\n폴더명 접두어: {'예' if self.chk_prefix.isChecked() else '아니오'}"
        self.run_summary_label.setText(text)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def on_run(self) -> None:
        if self.running:
            return

        folders = [folder for folder in self.folders if folder.is_dir()]
        if not folders:
            QMessageBox.warning(self, "확인", "폴더를 먼저 선택해 주세요.")
            return

        recursive = self.chk_recursive.isChecked()
        prefix_folder = self.chk_prefix.isChecked()
        target_folders, redundant_folders = filter_redundant_folders(folders, recursive=recursive)

        message = (
            f"목록의 폴더 {len(target_folders)}개에서 파일을 꺼냅니다.\n\n"
            "각 폴더 안의 파일은 해당 폴더의 상위 폴더로 이동하고,\n"
            "파일 이동 후 비어 있는 폴더만 삭제합니다.\n\n"
            "파일은 삭제하지 않습니다."
        )
        if redundant_folders:
            message += f"\n\n상위 폴더와 중복되어 제외될 하위 폴더: {len(redundant_folders)}개"
        message += "\n\n계속할까요?"

        answer = QMessageBox.question(self, "실행 확인", message)
        if answer != QMessageBox.Yes:
            return

        self.log_view.clear()
        self.set_running(True)
        self.worker = FolderUnpackWorker(folders, recursive=recursive, prefix_folder=prefix_folder)
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_result.connect(self.on_worker_finished)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def set_running(self, value: bool) -> None:
        self.running = value
        for widget in (
            self.btn_add,
            self.btn_remove,
            self.btn_reset,
            self.btn_run,
            self.chk_recursive,
            self.chk_prefix,
        ):
            widget.setEnabled(not value)

    def on_worker_finished(self, result) -> None:
        self.set_running(False)
        self.refresh_table()

        QMessageBox.information(
            self,
            "완료",
            (
                "파일 꺼내기가 완료되었습니다.\n\n"
                f"이동한 파일: {result.moved_count}개\n"
                f"삭제한 빈 폴더: {result.removed_folder_count}개\n"
                f"오류: {result.error_count}개"
            ),
        )

        try:
            if result.first_parent is not None and os.name == "nt":
                os.startfile(str(result.first_parent))
        except Exception:
            pass

    def on_worker_failed(self, message: str) -> None:
        self.set_running(False)
        self.append_log(f"실행 중 오류 발생: {message}")
        QMessageBox.critical(self, "오류", f"실행 중 오류가 발생했습니다.\n\n{message}")


def build_page():
    return FolderUnpackerPage()
