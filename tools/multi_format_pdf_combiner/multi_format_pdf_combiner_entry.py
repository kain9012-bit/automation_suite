from __future__ import annotations

import tempfile
from datetime import datetime
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

from multi_format_pdf_combiner_service import (
    SUPPORTED_ALL,
    ensure_pdf,
    human_size,
    is_pdf_file,
    merge_pdf_ordered,
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


class FileDropListWidget(QListWidget):
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
                if p.is_file() and p.suffix.lower() in SUPPORTED_ALL:
                    paths.append(p.resolve())

        self.parent_page.add_files(paths)
        event.acceptProposedAction()


class MultiFormatPdfCombinerPage(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[Path] = []
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

        page_title = QLabel("다형식 파일 PDF 통합 도구(v1.1)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("PDF, 이미지, DOCX, PPT, HWP 파일을 하나의 PDF로 통합합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard(
            "1. 파일 선택 및 순서 설정",
            "지원 파일을 추가한 뒤, 목록 순서를 최종 PDF 통합 순서로 사용합니다."
        )
        right_card = SectionCard(
            "2. 실행 방식",
            "각 파일을 먼저 PDF로 맞춘 뒤, 목록 순서대로 하나의 PDF로 통합합니다."
        )

        left_card.setMinimumWidth(650)
        right_card.setMinimumWidth(560)

        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.list_widget = FileDropListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        left_card.body_layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.btn_add = self.make_secondary_button("파일 선택", self.on_pick_files)
        self.btn_remove = self.make_secondary_button("선택 제거", self.on_remove_selected)
        self.btn_clear = self.make_secondary_button("선택 초기화", self.on_clear_files)

        button_row.addWidget(self.btn_add)
        button_row.addWidget(self.btn_remove)
        button_row.addWidget(self.btn_clear)
        button_row.addStretch(1)

        left_card.body_layout.addLayout(button_row)

        order_row = QHBoxLayout()
        order_row.setSpacing(8)

        self.btn_up = self.make_secondary_button("위로 ▲", self.on_move_up)
        self.btn_down = self.make_secondary_button("아래로 ▼", self.on_move_down)

        order_row.addWidget(self.btn_up)
        order_row.addWidget(self.btn_down)
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
            "지원 형식\n"
            "- PDF\n"
            "- 이미지(png/jpg/jpeg/webp/bmp/tif/tiff)\n"
            "- DOCX (Word 설치 + pywin32 필요)\n"
            "- PPT/PPTX (PowerPoint 설치 + pywin32 필요)\n"
            "- HWP/HWPX (한글 설치 + pywin32 필요)\n\n"
            "※ pikepdf 설치 시 일부 PDF 자동 복구 후 병합을 시도합니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)

        right_card.body_layout.addWidget(info_box)

        self.btn_run = QPushButton("PDF 통합")
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
        self.btn_run.clicked.connect(self.on_merge)

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
            try:
                size = human_size(p.stat().st_size)
            except Exception:
                size = "-"
            self.list_widget.addItem(QListWidgetItem(f"{p.name}  |  {p.suffix.lower()}  |  {size}"))

        if not self.files:
            self.status_label.setText("대기 중")
        else:
            self.status_label.setText(f"선택 {len(self.files)}개  |  통합 순서 = 목록 순서")

    def add_files(self, paths: list[Path]):
        exist = {str(p.resolve()).lower() for p in self.files}
        for p in paths:
            try:
                rp = str(p.resolve()).lower()
            except Exception:
                rp = str(p).lower()

            if rp in exist:
                continue
            if (not p.exists()) or (not p.is_file()):
                continue
            if p.suffix.lower() not in SUPPORTED_ALL:
                continue

            self.files.append(p)
            exist.add(rp)

        self.refresh_list()

    def on_pick_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "통합할 파일 선택",
            "",
            "지원 파일 (*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.docx *.ppt *.pptx *.hwp *.hwpx);;모든 파일 (*.*)"
        )
        if filenames:
            self.add_files([Path(p) for p in filenames])

    def on_clear_files(self):
        self.files = []
        self.refresh_list()

    def on_remove_selected(self):
        rows = sorted((i.row() for i in self.list_widget.selectedIndexes()), reverse=True)
        if not rows:
            QMessageBox.information(self, "알림", "삭제할 항목을 선택하세요.")
            return
        for row in rows:
            del self.files[row]
        self.refresh_list()

    def on_move_up(self):
        sel = list(self.list_widget.selectedIndexes())
        if len(sel) != 1:
            QMessageBox.information(self, "알림", "이동할 항목 1개를 선택하세요.")
            return
        idx = sel[0].row()
        if idx <= 0:
            return
        self.files[idx - 1], self.files[idx] = self.files[idx], self.files[idx - 1]
        self.refresh_list()
        self.list_widget.setCurrentRow(idx - 1)

    def on_move_down(self):
        sel = list(self.list_widget.selectedIndexes())
        if len(sel) != 1:
            QMessageBox.information(self, "알림", "이동할 항목 1개를 선택하세요.")
            return
        idx = sel[0].row()
        if idx >= len(self.files) - 1:
            return
        self.files[idx + 1], self.files[idx] = self.files[idx], self.files[idx + 1]
        self.refresh_list()
        self.list_widget.setCurrentRow(idx + 1)

    def on_merge(self):
        if not self.files:
            QMessageBox.warning(self, "알림", "먼저 파일을 선택하세요.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "통합 결과 PDF 저장 위치 선택",
            f"통합_{datetime.now().strftime('%m%d_%H%M')}.pdf",
            "PDF (*.pdf)"
        )
        if not save_path:
            return

        out_pdf = Path(save_path).resolve()
        tmp_dir = Path(tempfile.mkdtemp(prefix="merge2pdf_"))

        ok_count = 0
        fail_count = 0
        skipped: list[str] = []
        pdfs: list[Path] = []

        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        try:
            total = len(self.files)
            for idx, src in enumerate(self.files, start=1):
                self.status_label.setText(f"[{idx}/{total}] 처리 중: {src.name}")
                QApplication.processEvents()

                if not src.exists():
                    fail_count += 1
                    skipped.append(f"{src.name} (파일 없음)")
                    continue

                if src.suffix.lower() not in SUPPORTED_ALL:
                    fail_count += 1
                    skipped.append(f"{src.name} (지원하지 않는 확장자)")
                    continue

                pdf, reason = ensure_pdf(src, tmp_dir)
                if pdf is None:
                    fail_count += 1
                    skipped.append(f"{src.name} (변환 실패: {reason})")
                    continue

                pdfs.append(pdf)
                ok_count += 1

            self.status_label.setText("PDF 병합 중...")
            QApplication.processEvents()

            _, bad = merge_pdf_ordered(pdfs, out_pdf)
            if bad:
                for n, err in bad:
                    skipped.append(f"{n} (병합 실패: {err})")
                fail_count += len(bad)

            msg = f"PDF 통합 완료\n\n저장 위치:\n{out_pdf}\n\n- 포함: {ok_count}개\n- 제외/실패: {len(skipped)}개"
            if skipped:
                preview = "\n".join(["  • " + s for s in skipped[:12]])
                more = f"\n  ... 외 {len(skipped)-12}건" if len(skipped) > 12 else ""
                msg += "\n\n[제외/실패 목록]\n" + preview + more

            QMessageBox.information(self, "완료", msg)
            self.status_label.setText("완료")

        except Exception as e:
            QMessageBox.critical(self, "에러", f"PDF 통합 중 오류가 발생했습니다.\n\n{e}")
            self.status_label.setText("오류 발생")

        finally:
            self.btn_run.setEnabled(True)
            QApplication.processEvents()
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


def build_page():
    return MultiFormatPdfCombinerPage()