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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf_compress_service import (
    bytes_to_mb,
    compress_to_target,
    find_ghostscript,
    safe_output_path,
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


class PdfDropListWidget(QListWidget):
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
                if p.is_file() and p.suffix.lower() == ".pdf":
                    paths.append(p.resolve())

        self.parent_page.add_files(paths)
        event.acceptProposedAction()


class PdfCompressPage(QWidget):
    def __init__(self):
        super().__init__()
        self.pdf_files: list[Path] = []
        self._build_ui()
        self.refresh_list()

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
            QLineEdit:focus {{
                border: 1px solid {BRAND};
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

        page_title = QLabel("PDF 용량 압축 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("목표 용량 이하가 될 때까지 Ghostscript를 이용해 PDF를 자동 반복 압축합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard(
            "1. PDF 파일 선택 및 압축 설정",
            "PDF 파일을 추가하고 목표 용량, 안전 여유, 최대 시도 횟수를 설정합니다."
        )
        right_card = SectionCard(
            "2. 실행 방식",
            "목표 용량 이하가 될 때까지 자동으로 반복 압축하며, 결과 파일은 원본 폴더에 저장됩니다."
        )

        left_card.setMinimumWidth(650)
        right_card.setMinimumWidth(560)

        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        self.target_input = QLineEdit()
        self.target_input.setText("10")

        self.margin_input = QLineEdit()
        self.margin_input.setText("0.3")

        self.tries_input = QLineEdit()
        self.tries_input.setText("8")

        target_box = QVBoxLayout()
        target_box.addWidget(QLabel("목표 용량(MB)"))
        target_box.addWidget(self.target_input)

        margin_box = QVBoxLayout()
        margin_box.addWidget(QLabel("안전 여유(MB)"))
        margin_box.addWidget(self.margin_input)

        tries_box = QVBoxLayout()
        tries_box.addWidget(QLabel("최대 시도 횟수"))
        tries_box.addWidget(self.tries_input)

        settings_row.addLayout(target_box)
        settings_row.addLayout(margin_box)
        settings_row.addLayout(tries_box)

        left_card.body_layout.addLayout(settings_row)

        self.list_widget = PdfDropListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        left_card.body_layout.addWidget(self.list_widget)

        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)

        self.btn_add = self.make_secondary_button("파일 추가", self.on_add_files)
        self.btn_remove = self.make_secondary_button("선택 삭제", self.on_remove_selected)
        self.btn_clear = self.make_secondary_button("전체 삭제", self.on_clear_all)

        file_btn_row.addWidget(self.btn_add)
        file_btn_row.addWidget(self.btn_remove)
        file_btn_row.addWidget(self.btn_clear)
        file_btn_row.addStretch(1)

        left_card.body_layout.addLayout(file_btn_row)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)

        self.status_label = QLabel("대기 중")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:13px; color:#334155;")
        info_layout.addWidget(self.status_label)

        hint = QLabel(
            "※ 스캔/사진 PDF는 압축 시 이미지 해상도가 낮아질 수 있습니다.\n"
            "※ 텍스트 위주 PDF는 줄일 여지가 적어 목표를 못 맞출 수 있습니다.\n"
            "※ Ghostscript가 설치되어 있어야 합니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)

        right_card.body_layout.addWidget(info_box)

        self.run_btn = QPushButton("압축 실행")
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
        self.run_btn.clicked.connect(self.on_run_compress)

        right_card.body_layout.addWidget(self.run_btn, alignment=Qt.AlignLeft)
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
        for p in self.pdf_files:
            self.list_widget.addItem(QListWidgetItem(str(p)))

        if not self.pdf_files:
            self.status_label.setText("대기 중")
        else:
            self.status_label.setText(f"현재 {len(self.pdf_files)}개 PDF 파일이 선택되어 있습니다.")

    def add_files(self, paths: list[Path]):
        existing = {p.resolve() for p in self.pdf_files}
        for p in paths:
            p = Path(p).resolve()
            if p.exists() and p.suffix.lower() == ".pdf" and p not in existing:
                self.pdf_files.append(p)
                existing.add(p)
        self.refresh_list()

    def on_add_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "PDF 파일 선택",
            "",
            "PDF (*.pdf);;모든 파일 (*.*)"
        )
        if filenames:
            self.add_files([Path(f) for f in filenames])

    def on_remove_selected(self):
        rows = sorted((i.row() for i in self.list_widget.selectedIndexes()), reverse=True)
        if not rows:
            QMessageBox.warning(self, "알림", "삭제할 파일을 선택하세요.")
            return
        for row in rows:
            del self.pdf_files[row]
        self.refresh_list()

    def on_clear_all(self):
        self.pdf_files = []
        self.refresh_list()

    def on_run_compress(self):
        if not self.pdf_files:
            QMessageBox.warning(self, "알림", "목록에 PDF 파일을 추가하세요.")
            return

        gs = find_ghostscript()
        if not gs:
            QMessageBox.critical(
                self,
                "Ghostscript 필요",
                "Ghostscript를 찾지 못했습니다.\n번들(gs 폴더 포함) 또는 시스템 설치 상태를 확인하세요."
            )
            return

        try:
            target_mb = float(self.target_input.text().strip())
            margin_mb = float(self.margin_input.text().strip())
            max_tries = int(self.tries_input.text().strip())

            if target_mb <= 0:
                raise ValueError("목표 용량은 0보다 커야 합니다.")
            if margin_mb < 0:
                raise ValueError("안전 여유는 0 이상이어야 합니다.")
            if max_tries < 1:
                raise ValueError("최대 시도 횟수는 1 이상이어야 합니다.")
        except Exception as e:
            QMessageBox.critical(self, "입력 오류", str(e))
            return

        effective_target_mb = max(0.01, target_mb - margin_mb)
        target_bytes = int(effective_target_mb * 1024 * 1024)

        total = len(self.pdf_files)
        ok_cnt = 0
        fail_cnt = 0

        self.run_btn.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.btn_clear.setEnabled(False)
        QApplication.processEvents()

        try:
            for idx, in_fp in enumerate(self.pdf_files, start=1):
                out_fp = safe_output_path(in_fp, effective_target_mb)
                self.status_label.setText(f"[{idx}/{total}] 처리 중: {in_fp.name}")
                QApplication.processEvents()

                orig = in_fp.stat().st_size
                try:
                    out_size, achieved = compress_to_target(gs, in_fp, out_fp, target_bytes, max_tries)
                    if achieved:
                        ok_cnt += 1
                        self.status_label.setText(
                            f"[{idx}/{total}] 완료: {in_fp.name}  "
                            f"({bytes_to_mb(orig):.2f}MB → {bytes_to_mb(out_size):.2f}MB, 목표 달성)"
                        )
                    else:
                        fail_cnt += 1
                        self.status_label.setText(
                            f"[{idx}/{total}] 완료: {in_fp.name}  "
                            f"({bytes_to_mb(orig):.2f}MB → {bytes_to_mb(out_size):.2f}MB, 목표 미달)"
                        )
                    QApplication.processEvents()
                except Exception as e:
                    fail_cnt += 1
                    self.status_label.setText(f"[{idx}/{total}] 실패: {in_fp.name}")
                    QApplication.processEvents()
                    QMessageBox.critical(self, "오류", f"{in_fp.name}\n\n{e}")

            QMessageBox.information(
                self,
                "완료",
                f"처리 완료\n\n- 목표 달성: {ok_cnt}개\n- 목표 미달/실패: {fail_cnt}개\n\n"
                "※ 결과는 원본 파일과 같은 폴더에 저장됩니다."
            )

        finally:
            self.run_btn.setEnabled(True)
            self.btn_add.setEnabled(True)
            self.btn_remove.setEnabled(True)
            self.btn_clear.setEnabled(True)
            QApplication.processEvents()


def build_page():
    return PdfCompressPage()