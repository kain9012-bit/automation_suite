from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hwp_collector_service import (
    is_supported_hanfile,
    list_han_files_in_folder,
    merge_han_files,
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


class HanDropListWidget(QListWidget):
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

        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                p = Path(local)
                if p.is_file() and p.suffix.lower() in {".hwp", ".hwpx"}:
                    paths.append(p.resolve())

        self.parent_page.add_files(paths)
        event.acceptProposedAction()


class HwpCollectorPage(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[Path] = []
        self.current_folder_text = "(없음)"
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

        page_title = QLabel("한글 파일 취합 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("선택한 HWP/HWPX 파일을 순서대로 하나의 한글 문서로 이어 붙입니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard(
            "1. 파일 선택 및 순서 설정",
            "폴더/파일 선택 또는 드래그 앤 드롭으로 한글 파일을 추가한 뒤 병합 순서를 조정합니다."
        )
        right_card = SectionCard(
            "2. 실행 방식",
            "선택한 순서대로 한글 파일을 하나의 문서로 취합합니다."
        )

        left_card.setMinimumWidth(650)
        right_card.setMinimumWidth(560)

        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.folder_label = QLabel("선택된 폴더: (없음)")
        self.folder_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        self.folder_label.setWordWrap(True)
        left_card.body_layout.addWidget(self.folder_label)

        self.list_widget = HanDropListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        left_card.body_layout.addWidget(self.list_widget)

        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)

        self.btn_folder = self.make_secondary_button("폴더 선택", self.on_select_folder)
        self.btn_files = self.make_secondary_button("파일 선택", self.on_select_files)
        file_btn_row.addWidget(self.btn_folder)
        file_btn_row.addWidget(self.btn_files)
        file_btn_row.addStretch(1)
        left_card.body_layout.addLayout(file_btn_row)

        order_row = QHBoxLayout()
        order_row.setSpacing(8)

        self.btn_up = self.make_secondary_button("위로", self.on_move_up)
        self.btn_down = self.make_secondary_button("아래로", self.on_move_down)
        self.btn_delete = self.make_secondary_button("선택 삭제", self.on_delete_selected)

        order_row.addWidget(self.btn_up)
        order_row.addWidget(self.btn_down)
        order_row.addWidget(self.btn_delete)
        order_row.addStretch(1)
        left_card.body_layout.addLayout(order_row)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)

        self.status_label = QLabel("대기 중")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:13px; color:#334155;")
        info_layout.addWidget(self.status_label)

        hint = QLabel(
            "※ 결과 문서의 용지/방향/여백 등 페이지 설정은 첫 번째 파일 기준으로 적용될 수 있습니다.\n"
            "※ 취합 후 한글에서 [쪽] → [편집용지]에서 설정을 확인/조정해 주세요.\n"
            "※ 한글(HWP) 프로그램과 pywin32가 설치되어 있어야 합니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)

        right_card.body_layout.addWidget(info_box)

        self.btn_run = QPushButton("취합 실행")
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
        """)
        self.btn_run.clicked.connect(self.on_run_merge)

        right_card.body_layout.addWidget(self.btn_run, alignment=Qt.AlignLeft)
        right_card.body_layout.addStretch(1)

        container_layout.addLayout(cards_row)
        container_layout.addStretch(1)

        outer.addWidget(container)
        outer.addStretch(1)
        root.addLayout(outer)

    def make_secondary_button(self, text: str, callback):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(callback)
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
        return btn

    def refresh_list(self):
        self.list_widget.clear()
        for p in self.files:
            self.list_widget.addItem(QListWidgetItem(p.name))

        self.folder_label.setText(f"선택된 폴더: {self.current_folder_text}")

        if not self.files:
            self.status_label.setText("대기 중")
        else:
            self.status_label.setText(f"현재 {len(self.files)}개 한글 파일이 선택되어 있습니다.")

    def add_files(self, paths: list[Path]):
        existing = {p.resolve() for p in self.files}
        for p in paths:
            p = Path(p).resolve()
            if is_supported_hanfile(p) and p not in existing:
                self.files.append(p)
                existing.add(p)
        self.refresh_list()

    def on_select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "한글 파일이 있는 폴더 선택 (.hwp/.hwpx)")
        if not folder:
            return

        folder_path = Path(folder)
        self.files = list_han_files_in_folder(folder_path)
        self.current_folder_text = str(folder_path)

        if not self.files:
            QMessageBox.information(self, "안내", "선택한 폴더에 .hwp 또는 .hwpx 파일이 없습니다.")

        self.refresh_list()

    def on_select_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "추가할 한글 파일 선택",
            "",
            "한글 문서 (*.hwp *.hwpx);;모든 파일 (*.*)"
        )
        if filenames:
            self.add_files([Path(f) for f in filenames])

    def on_move_up(self):
        sel = self.list_widget.selectedIndexes()
        if not sel:
            return
        idx = min(i.row() for i in sel)
        if idx == 0:
            return
        self.files[idx - 1], self.files[idx] = self.files[idx], self.files[idx - 1]
        self.refresh_list()
        self.list_widget.setCurrentRow(idx - 1)

    def on_move_down(self):
        sel = self.list_widget.selectedIndexes()
        if not sel:
            return
        idx = max(i.row() for i in sel)
        if idx == len(self.files) - 1:
            return
        self.files[idx], self.files[idx + 1] = self.files[idx + 1], self.files[idx]
        self.refresh_list()
        self.list_widget.setCurrentRow(idx + 1)

    def on_delete_selected(self):
        rows = sorted((i.row() for i in self.list_widget.selectedIndexes()), reverse=True)
        if not rows:
            QMessageBox.warning(self, "알림", "삭제할 파일을 선택하세요.")
            return
        for row in rows:
            del self.files[row]
        self.refresh_list()

    def on_run_merge(self):
        if not self.files:
            QMessageBox.warning(self, "알림", "먼저 한글 파일(.hwp/.hwpx)을 추가해 주세요.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "취합 결과를 저장할 파일 선택",
            "",
            "한글 문서 (*.hwp);;모든 파일 (*.*)"
        )
        if not save_path:
            return

        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        try:
            merge_han_files(self.files, save_path)
            QMessageBox.information(self, "완료", f"파일 취합이 완료되었습니다.\n\n파일 위치:\n{save_path}")
            self.status_label.setText("완료")
        except Exception as e:
            QMessageBox.critical(self, "에러", f"취합 중 오류가 발생했습니다.\n\n{e}")
            self.status_label.setText("오류 발생")
        finally:
            self.btn_run.setEnabled(True)
            QApplication.processEvents()


def build_page():
    return HwpCollectorPage()