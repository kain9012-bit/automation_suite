from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hwp_to_hwpx_converter_service import (
    collect_hwp_files_from_folder,
    convert_hwp_files_to_hwpx,
    is_hwp_file,
    normalize_path,
    output_hwpx_path,
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


class HwpDropListWidget(QListWidget):
    def __init__(self, parent_page):
        super().__init__()
        self.parent_page = parent_page
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return

        paths: list[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                path = Path(local)
                if is_hwp_file(path):
                    paths.append(path.resolve())
        self.parent_page.add_files(paths)
        event.acceptProposedAction()


class HwpToHwpxWorker(QThread):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    finished_result = Signal(object)
    failed = Signal(str)

    def __init__(self, files: list[Path], visible: bool):
        super().__init__()
        self.files = files
        self.visible = visible

    def run(self) -> None:
        try:
            result = convert_hwp_files_to_hwpx(
                self.files,
                visible=self.visible,
                log=self.log_message.emit,
                status=lambda path, text: self.status_changed.emit(str(path), text),
            )
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class HwpToHwpxConverterPage(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[Path] = []
        self.file_set: set[str] = set()
        self.worker: HwpToHwpxWorker | None = None
        self.running = False
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
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
            QListWidget {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background: #eaf2ff;
                color: {TEXT};
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

        outer = QHBoxLayout()
        outer.setContentsMargins(30, 24, 30, 24)
        outer.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(1500)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(18)

        page_title = QLabel("HWP → HWPX 일괄 변환 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("HWP 파일을 HWPX로 변환하고 성공한 원본 HWP를 삭제합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard(
            "1. HWP 파일 선택",
            "파일 또는 폴더를 선택해 변환할 HWP 목록과 순서를 확인합니다.",
        )
        right_card = SectionCard(
            "2. 실행 및 진행 상황",
            "변환 성공 시 같은 폴더에 HWPX를 만들고 원본 HWP를 삭제합니다.",
        )
        left_card.setMinimumWidth(650)
        right_card.setMinimumWidth(560)
        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.folder_label = QLabel("선택한 파일: 0개")
        self.folder_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        self.folder_label.setWordWrap(True)
        left_card.body_layout.addWidget(self.folder_label)

        self.list_widget = HwpDropListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        left_card.body_layout.addWidget(self.list_widget, 1)

        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)
        self.btn_folder = self.make_secondary_button("폴더 선택", self.on_select_folder)
        self.btn_files = self.make_secondary_button("파일 선택", self.on_select_files)
        file_btn_row.addWidget(self.btn_folder)
        file_btn_row.addWidget(self.btn_files)
        file_btn_row.addStretch(1)
        left_card.body_layout.addLayout(file_btn_row)

        manage_row = QHBoxLayout()
        manage_row.setSpacing(8)
        self.btn_delete = self.make_secondary_button("선택 제거", self.on_delete_selected)
        self.btn_clear = self.make_secondary_button("전체 초기화", self.on_clear_files)
        manage_row.addWidget(self.btn_delete)
        manage_row.addWidget(self.btn_clear)
        manage_row.addStretch(1)
        left_card.body_layout.addLayout(manage_row)

        option_box = QFrame()
        option_box.setObjectName("infoBox")
        option_layout = QVBoxLayout(option_box)
        option_layout.setContentsMargins(14, 12, 14, 12)
        option_layout.setSpacing(10)

        self.chk_recursive = QCheckBox("폴더 선택 시 하위 폴더 포함")
        self.chk_recursive.setChecked(True)
        option_layout.addWidget(self.chk_recursive)

        self.chk_open_folder = QCheckBox("완료 후 첫 번째 원본 폴더 열기")
        self.chk_open_folder.setChecked(True)
        option_layout.addWidget(self.chk_open_folder)

        self.chk_visible = QCheckBox("변환 중 한글 창 보이기")
        self.chk_visible.setChecked(False)
        option_layout.addWidget(self.chk_visible)

        note = QLabel("기존 같은 이름의 HWPX가 있으면 덮어씁니다. 실패한 파일의 원본 HWP는 삭제하지 않습니다.")
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size:12px; color:{MUTED};")
        option_layout.addWidget(note)
        right_card.body_layout.addWidget(option_box)

        self.btn_run = QPushButton("HWPX 변환 실행")
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

    def add_files(self, paths: list[Path]) -> None:
        added = 0
        skipped = 0
        for path in paths:
            if is_hwp_file(path):
                resolved = path.resolve()
                normalized = normalize_path(resolved)
                if normalized not in self.file_set:
                    self.file_set.add(normalized)
                    self.files.append(resolved)
                    added += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        self.refresh_list()
        if added:
            self.append_log(f"파일 추가: {added}개")
        if skipped:
            self.append_log(f"건너뜀: {skipped}개")

    def on_select_folder(self) -> None:
        if self.running:
            return
        folder = QFileDialog.getExistingDirectory(self, "HWP 파일이 있는 폴더 선택")
        if not folder:
            return
        files = collect_hwp_files_from_folder(folder, recursive=self.chk_recursive.isChecked())
        if not files:
            QMessageBox.information(self, "안내", "선택한 폴더에서 HWP 파일을 찾지 못했습니다.")
            return
        self.add_files(files)

    def on_select_files(self) -> None:
        if self.running:
            return
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "변환할 HWP 파일 선택",
            "",
            "한글 HWP 파일 (*.hwp);;모든 파일 (*.*)",
        )
        if filenames:
            self.add_files([Path(filename) for filename in filenames])

    def on_delete_selected(self) -> None:
        if self.running:
            return
        rows = sorted({index.row() for index in self.list_widget.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "안내", "목록에서 제거할 파일을 선택해 주세요.")
            return
        for row in rows:
            if 0 <= row < len(self.files):
                path = self.files.pop(row)
                self.file_set.discard(normalize_path(path))
        self.refresh_list()

    def on_clear_files(self) -> None:
        if self.running:
            return
        self.files.clear()
        self.file_set.clear()
        self.log_view.clear()
        self.refresh_list()

    def refresh_list(self) -> None:
        self.list_widget.clear()
        valid_files: list[Path] = []
        self.file_set.clear()
        for path in self.files:
            if is_hwp_file(path):
                valid_files.append(path)
                self.file_set.add(normalize_path(path))
                target_name = output_hwpx_path(path).name
                item = QListWidgetItem(f"{path.name}  ->  {target_name}")
                item.setData(Qt.UserRole, str(path))
                item.setToolTip(str(path))
                self.list_widget.addItem(item)
        self.files = valid_files
        self.folder_label.setText(f"선택한 파일: {len(self.files)}개")

    def update_file_status(self, path_text: str, status: str) -> None:
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item_path = item.data(Qt.UserRole)
            if normalize_path(item_path) == normalize_path(path_text):
                path = Path(item_path)
                item.setText(f"{path.name}  ->  {output_hwpx_path(path).name}  [{status}]")
                return

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        QApplication.processEvents()

    def on_run(self) -> None:
        if self.running:
            return
        files = [path for path in self.files if is_hwp_file(path)]
        if not files:
            QMessageBox.warning(self, "확인", "변환할 HWP 파일을 먼저 선택해 주세요.")
            return

        existing_hwpx_count = sum(1 for path in files if output_hwpx_path(path).exists())
        message = (
            f"HWP 파일 {len(files)}개를 HWPX로 변환합니다.\n\n"
            "- 각 HWP 파일과 같은 폴더에 같은 이름의 HWPX를 생성합니다.\n"
            "- 변환 성공 시 원본 HWP 파일을 삭제합니다.\n"
            "- 변환 실패 파일은 원본 HWP를 삭제하지 않습니다.\n"
        )
        if existing_hwpx_count:
            message += f"- 기존 같은 이름의 HWPX {existing_hwpx_count}개는 덮어씁니다.\n"
        message += "\n계속할까요?"

        answer = QMessageBox.question(self, "실행 확인", message)
        if answer != QMessageBox.Yes:
            return

        self.log_view.clear()
        self.set_running(True)
        self.worker = HwpToHwpxWorker(files, visible=self.chk_visible.isChecked())
        self.worker.log_message.connect(self.append_log)
        self.worker.status_changed.connect(self.update_file_status)
        self.worker.finished_result.connect(self.on_worker_finished)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def set_running(self, value: bool) -> None:
        self.running = value
        for widget in (
            self.btn_folder,
            self.btn_files,
            self.btn_delete,
            self.btn_clear,
            self.btn_run,
            self.chk_recursive,
            self.chk_open_folder,
            self.chk_visible,
        ):
            widget.setEnabled(not value)

    def on_worker_finished(self, result) -> None:
        self.set_running(False)
        self.refresh_list()
        QMessageBox.information(
            self,
            "완료",
            (
                "HWP → HWPX 변환이 완료되었습니다.\n\n"
                f"성공: {result.success_count}개\n"
                f"원본 삭제 실패: {result.delete_fail_count}개\n"
                f"변환 실패: {result.fail_count}개\n"
                f"기존 HWPX 덮어쓰기: {result.overwrite_count}개"
            ),
        )
        if self.chk_open_folder.isChecked() and self.files:
            try:
                if os.name == "nt":
                    os.startfile(str(self.files[0].parent))
            except Exception:
                pass

    def on_worker_failed(self, message: str) -> None:
        self.set_running(False)
        self.append_log(f"실행 중 오류 발생: {message}")
        QMessageBox.critical(self, "오류", f"실행 중 문제가 발생했습니다.\n\n{message}")


def build_page():
    return HwpToHwpxConverterPage()
