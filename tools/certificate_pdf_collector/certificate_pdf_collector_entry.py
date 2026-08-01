from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QFileDialog,
    QVBoxLayout,
    QWidget,
)

from certificate_pdf_collector_service import (
    build_output_path,
    process_pdfs,
    save_result_excel,
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


class CertificatePdfCollectorPage(QWidget):
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

        page_title = QLabel("교육·연수 이수증 PDF 취합 도구(v1.0) ")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("여러 연수기관 이수증 PDF를 한 번에 분석해 엑셀로 정리합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard(
            "1. PDF 파일 선택",
            "이수증 PDF를 선택하거나 드래그 앤 드롭으로 추가합니다."
        )
        right_card = SectionCard(
            "2. 실행 방식",
            "추출 결과를 정상 / 확인필요 / 에러 시트로 나누어 엑셀 파일로 저장합니다."
        )

        left_card.setMinimumWidth(650)
        right_card.setMinimumWidth(560)

        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.folder_label = QLabel("선택된 파일: 0개")
        self.folder_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        self.folder_label.setWordWrap(True)
        left_card.body_layout.addWidget(self.folder_label)

        self.list_widget = PdfDropListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        left_card.body_layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.btn_add = self.make_secondary_button("파일 선택", self.on_select_files)
        self.btn_remove = self.make_secondary_button("선택 제거", self.on_remove_selected)
        self.btn_clear = self.make_secondary_button("전체 초기화", self.on_clear_files)

        button_row.addWidget(self.btn_add)
        button_row.addWidget(self.btn_remove)
        button_row.addWidget(self.btn_clear)
        button_row.addStretch(1)

        left_card.body_layout.addLayout(button_row)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)

        self.status_label = QLabel("대기 중")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:13px; color:#334155;")
        info_layout.addWidget(self.status_label)

        hint = QLabel(
            "지원 연수기관\n"
            "- 전북특별자치도교육청교육연수원\n"
            "- 전북특별자치도교육청미래교육연구원\n"
            "- 중앙교육연수원\n"
            "- 통계인재개발원\n"
            "- 국립평화통일민주교육원\n\n"
            "※ 위 기관 외 이수증은 일부만 추출되어 '확인필요'로 분류될 수 있습니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)

        right_card.body_layout.addWidget(info_box)

        self.btn_help = self.make_secondary_button("지원 연수기관 안내", self.show_supported_orgs)
        right_card.body_layout.addWidget(self.btn_help, alignment=Qt.AlignLeft)

        self.btn_run = QPushButton("실행")
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
        self.btn_run.clicked.connect(self.on_run)

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

        base_info = f"선택된 파일: {len(self.files)}개"
        if self.files:
            base_info += f"\n저장 위치: {self.files[0].parent}"
        self.folder_label.setText(base_info)

        if not self.files:
            self.status_label.setText("대기 중")
        else:
            self.status_label.setText(f"현재 {len(self.files)}개 PDF 파일이 선택되어 있습니다.")

    def add_files(self, paths: list[Path]):
        existing = {p.resolve() for p in self.files}
        for p in paths:
            p = Path(p).resolve()
            if p.is_file() and p.suffix.lower() == ".pdf" and p not in existing:
                self.files.append(p)
                existing.add(p)
        self.refresh_list()

    def on_select_files(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "이수증 PDF 파일 선택",
            "",
            "PDF (*.pdf);;모든 파일 (*.*)"
        )
        if filenames:
            self.add_files([Path(f) for f in filenames])

    def on_remove_selected(self):
        rows = sorted((i.row() for i in self.list_widget.selectedIndexes()), reverse=True)
        if not rows:
            QMessageBox.warning(self, "알림", "삭제할 항목을 선택하세요.")
            return
        for row in rows:
            del self.files[row]
        self.refresh_list()

    def on_clear_files(self):
        self.files = []
        self.refresh_list()

    def show_supported_orgs(self):
        txt = (
            "[지원 연수기관]\n\n"
            "· 전북특별자치도교육청교육연수원\n"
            "· 전북특별자치도교육청미래교육연구원\n"
            "· 중앙교육연수원\n"
            "· 통계인재개발원\n"
            "· 국립평화통일민주교육원\n\n"
            "※ 위 기관 이수증은 구조를 분석해 최적화해 두었습니다.\n"
            "   다른 기관 이수증은 일부만 추출될 수 있으며\n"
            "   '확인필요' 시트에 분류될 수 있습니다."
        )
        QMessageBox.information(self, "지원 연수기관 안내", txt)

    def on_run(self):
        if not self.files:
            QMessageBox.warning(self, "알림", "먼저 PDF 파일을 선택해 주세요.")
            return

        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        try:
            df_good, df_bad, df_error = process_pdfs(self.files)
            base_dir = self.files[0].parent
            output_path = build_output_path(base_dir)
            save_result_excel(output_path, df_good, df_bad, df_error)

            msg = (
                "작업이 완료되었습니다.\n\n"
                f"정상 추출: {len(df_good)}개\n"
                f"확인 필요: {len(df_bad)}개\n"
                f"에러 발생: {len(df_error)}개\n\n"
                f"결과 파일:\n{output_path}\n\n"
                "엑셀에서 '정상 / 확인필요 / 에러' 시트를 확인해 주세요."
            )
            QMessageBox.information(self, "완료", msg)
            self.status_label.setText("완료")

        except PermissionError:
            QMessageBox.critical(
                self,
                "에러",
                "엑셀 파일을 저장할 수 없습니다.\n\n해당 엑셀 파일이 열려 있지 않은지 확인해 주세요."
            )
            self.status_label.setText("오류 발생")
        except Exception as e:
            QMessageBox.critical(self, "에러", f"처리 중 에러가 발생했습니다.\n\n{e}")
            self.status_label.setText("오류 발생")
        finally:
            self.btn_run.setEnabled(True)
            QApplication.processEvents()


def build_page():
    return CertificatePdfCollectorPage()