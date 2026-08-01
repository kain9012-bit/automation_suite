from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QComboBox,
    QVBoxLayout,
    QWidget,
)

from pdf_page_number_adder_service import (
    add_page_numbers,
    build_output_path,
    format_preview_text,
    get_pdf_page_count,
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
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

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


class CompactField(QWidget):
    def __init__(self, label_text: str, field_widget: QWidget):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel(label_text)
        label.setStyleSheet("font-size:12px; color:#334155; font-weight:600;")
        layout.addWidget(label)
        layout.addWidget(field_widget)


class PreviewCanvas(QFrame):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(420)
        self.setObjectName("previewCanvas")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self.page_area = QFrame()
        self.page_area.setObjectName("previewPage")
        self.page_area.setMinimumHeight(340)

        page_layout = QVBoxLayout(self.page_area)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(0)

        self.top_row = QHBoxLayout()
        self.top_row.setContentsMargins(0, 0, 0, 0)

        self.bottom_row = QHBoxLayout()
        self.bottom_row.setContentsMargins(0, 0, 0, 0)

        self.top_left = QLabel("")
        self.top_center = QLabel("")
        self.top_right = QLabel("")
        self.bottom_left = QLabel("")
        self.bottom_center = QLabel("")
        self.bottom_right = QLabel("")

        for lbl in [
            self.top_left, self.top_center, self.top_right,
            self.bottom_left, self.bottom_center, self.bottom_right,
        ]:
            lbl.setStyleSheet("font-size:13px; color:#1f2937; font-weight:600; background:transparent;")
            lbl.setAlignment(Qt.AlignCenter)

        self.top_row.addWidget(self.top_left, 1)
        self.top_row.addWidget(self.top_center, 1)
        self.top_row.addWidget(self.top_right, 1)

        self.bottom_row.addWidget(self.bottom_left, 1)
        self.bottom_row.addWidget(self.bottom_center, 1)
        self.bottom_row.addWidget(self.bottom_right, 1)

        page_layout.addLayout(self.top_row)
        page_layout.addStretch(1)
        page_layout.addLayout(self.bottom_row)

        self.preview_info = QLabel("미리보기")
        self.preview_info.setStyleSheet(f"font-size:12px; color:{MUTED};")
        self.preview_info.setAlignment(Qt.AlignCenter)

        root.addWidget(self.page_area)
        root.addWidget(self.preview_info)

    def update_preview(self, position_label: str, number_text: str):
        for lbl in [
            self.top_left, self.top_center, self.top_right,
            self.bottom_left, self.bottom_center, self.bottom_right,
        ]:
            lbl.setText("")

        mapping = {
            "좌상단": self.top_left,
            "상단 중앙": self.top_center,
            "우상단": self.top_right,
            "좌하단": self.bottom_left,
            "하단 중앙": self.bottom_center,
            "우하단": self.bottom_right,
        }

        target = mapping.get(position_label, self.bottom_center)
        target.setText(number_text)
        self.preview_info.setText(f"미리보기 형식: {number_text} / 위치: {position_label}")


class PdfPageNumberAdderPage(QWidget):
    def __init__(self):
        super().__init__()
        self.pdf_path: Path | None = None
        self.page_count = 0
        self.last_output_path: Path | None = None
        self._build_ui()
        self._refresh_preview()

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
                font-size: 24px;
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
                font-size: 17px;
                font-weight: 700;
                color: {TEXT};
                background: transparent;
            }}
            QLabel#sectionDescription {{
                font-size: 12px;
                color: {MUTED};
                background: transparent;
            }}
            QFrame#infoBox {{
                background: {INFO_BG};
                border: 1px dashed #cfdcf2;
                border-radius: 8px;
            }}
            QFrame#previewCanvas {{
                background: #f8fbff;
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            QFrame#previewPage {{
                background: white;
                border: 1px solid #cfdcf2;
                border-radius: 8px;
            }}
            QLineEdit, QComboBox {{
                min-height: 34px;
                max-height: 34px;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 0 10px;
                background: white;
                color: {TEXT};
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid #8ab4f8;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        outer = QHBoxLayout()
        outer.setContentsMargins(26, 18, 26, 18)
        outer.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(1480)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(16)

        page_title = QLabel("PDF 페이지번호 추가 도구(v1.0)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("PDF 파일에 페이지번호를 일괄 추가하고 새 파일로 저장합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        content_row = QHBoxLayout()
        content_row.setSpacing(18)

        # 왼쪽
        left_wrap = QWidget()
        left_wrap.setFixedWidth(650)

        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(16)

        # 1. PDF 파일 선택
        file_card = SectionCard(
            "1. PDF 파일 선택",
            "PDF 파일 1개를 선택하면 전체 페이지 수를 확인할 수 있습니다."
        )

        file_info_layout = QVBoxLayout()
        file_info_layout.setSpacing(8)

        top_info_row = QHBoxLayout()
        top_info_row.setSpacing(10)

        self.file_label = QLabel("선택된 파일: (없음)")
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet(f"font-size:13px; color:{TEXT};")

        self.page_count_label = QLabel("전체 페이지 수: -")
        self.page_count_label.setStyleSheet(f"font-size:13px; color:{TEXT}; font-weight:600;")

        top_info_row.addWidget(self.file_label, 1)
        top_info_row.addWidget(self.page_count_label, 0)

        file_button_row = QHBoxLayout()
        file_button_row.setSpacing(10)

        self.btn_select_file = self.make_secondary_button("PDF 파일 선택", self.on_select_file)
        file_button_row.addWidget(self.btn_select_file, 0)
        file_button_row.addStretch(1)

        file_info_layout.addLayout(top_info_row)
        file_info_layout.addLayout(file_button_row)
        file_card.body_layout.addLayout(file_info_layout)

        # 2. 번호 설정
        setting_card = SectionCard(
            "2. 번호 설정",
            "설정을 간단히 입력하고 바로 미리보기로 확인합니다."
        )

        self.combo_format = QComboBox()
        self.combo_format.addItems([
            "1",
            "01",
            "001",
            "- 1 -",
            "1쪽",
            "1페이지",
            "1 / 전체페이지수",
        ])
        self.combo_format.currentTextChanged.connect(self._refresh_preview)

        self.combo_position = QComboBox()
        self.combo_position.addItems([
            "좌상단",
            "상단 중앙",
            "우상단",
            "좌하단",
            "하단 중앙",
            "우하단",
        ])
        self.combo_position.setCurrentText("하단 중앙")
        self.combo_position.currentTextChanged.connect(self._refresh_preview)

        self.input_start_page = QLineEdit("1")
        self.input_start_number = QLineEdit("1")
        self.input_font_size = QLineEdit("10")

        self.input_start_page.textChanged.connect(self._refresh_preview)
        self.input_start_number.textChanged.connect(self._refresh_preview)
        self.input_font_size.textChanged.connect(self._refresh_preview)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addWidget(CompactField("번호 형식", self.combo_format), 1)
        row1.addWidget(CompactField("위치", self.combo_position), 1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(CompactField("시작 페이지", self.input_start_page), 1)
        row2.addWidget(CompactField("시작 번호", self.input_start_number), 1)
        row2.addWidget(CompactField("글꼴 크기(pt)", self.input_font_size), 1)

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QHBoxLayout(info_box)
        info_layout.setContentsMargins(12, 10, 12, 10)

        hint = QLabel("※ 기본 위치: 하단 중앙 / 시작 페이지 이전은 미표시 / 원본은 덮어쓰지 않음")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)

        setting_card.body_layout.addLayout(row1)
        setting_card.body_layout.addLayout(row2)
        setting_card.body_layout.addWidget(info_box)

        # 4. 실행 및 저장
        run_card = SectionCard(
            "4. 실행 및 저장",
            "페이지번호를 추가하여 새 PDF 파일로 저장합니다."
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.btn_run = QPushButton("페이지번호 추가 실행")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self.on_run)
        self.btn_run.setStyleSheet(f"""
            QPushButton {{
                background: {BRAND};
                border: 1px solid {BRAND};
                color: white;
                border-radius: 6px;
                min-height: 36px;
                max-height: 36px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {BRAND_DARK};
                border: 1px solid {BRAND_DARK};
            }}
        """)

        self.btn_open_folder = self.make_secondary_button("저장 폴더 열기", self.on_open_output_folder)
        self.btn_open_folder.setEnabled(False)

        action_row.addWidget(self.btn_run)
        action_row.addWidget(self.btn_open_folder)
        action_row.addStretch(1)

        self.result_label = QLabel("처리 결과: 아직 실행하지 않았습니다.")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(f"font-size:13px; color:{TEXT};")

        run_card.body_layout.addLayout(action_row)
        run_card.body_layout.addWidget(self.result_label)

        left_layout.addWidget(file_card)
        left_layout.addWidget(setting_card)
        left_layout.addWidget(run_card)
        left_layout.addStretch(1)

        # 오른쪽
        preview_card = SectionCard(
            "3. 미리보기",
            "설정한 형식과 위치를 간단히 확인합니다."
        )
        preview_card.setFixedWidth(560)

        self.preview_canvas = PreviewCanvas()
        preview_card.body_layout.addWidget(self.preview_canvas)
        preview_card.body_layout.addStretch(1)

        content_row.addWidget(left_wrap, 0)
        content_row.addWidget(preview_card, 0)
        content_row.addStretch(1)

        container_layout.addLayout(content_row)
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
                min-height: 34px;
                max-height: 34px;
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

    def _safe_int(self, text: str, default: int = 1) -> int:
        try:
            return int(text.strip())
        except Exception:
            return default

    def _refresh_preview(self):
        fmt = self.combo_format.currentText()
        start_number = self._safe_int(self.input_start_number.text(), 1)
        position = self.combo_position.currentText()

        preview_text = format_preview_text(
            number=start_number,
            total_pages=self.page_count if self.page_count > 0 else 10,
            format_type=fmt,
        )
        self.preview_canvas.update_preview(position, preview_text)

    def on_select_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "페이지번호를 추가할 PDF 파일 선택",
            "",
            "PDF (*.pdf);;모든 파일 (*.*)"
        )
        if not filename:
            return

        try:
            pdf_path = Path(filename).resolve()
            page_count = get_pdf_page_count(pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"PDF 파일을 읽는 중 오류가 발생했습니다.\n\n{e}")
            return

        self.pdf_path = pdf_path
        self.page_count = page_count
        self.file_label.setText(f"선택된 파일: {pdf_path.name}")
        self.page_count_label.setText(f"전체 페이지 수: {page_count}")
        self.result_label.setText("처리 결과: 파일을 선택했습니다.")
        self._refresh_preview()

    def on_run(self):
        if self.pdf_path is None:
            QMessageBox.warning(self, "알림", "먼저 PDF 파일을 선택해 주세요.")
            return

        start_page = self._safe_int(self.input_start_page.text(), -1)
        start_number = self._safe_int(self.input_start_number.text(), -1)
        font_size = self._safe_int(self.input_font_size.text(), -1)

        if start_page < 1:
            QMessageBox.warning(self, "입력 오류", "시작 페이지는 1 이상이어야 합니다.")
            return
        if start_number < 1:
            QMessageBox.warning(self, "입력 오류", "시작 번호는 1 이상이어야 합니다.")
            return
        if font_size < 1:
            QMessageBox.warning(self, "입력 오류", "글꼴 크기는 1 이상이어야 합니다.")
            return
        if self.page_count and start_page > self.page_count:
            QMessageBox.warning(self, "입력 오류", "시작 페이지가 전체 페이지 수를 초과했습니다.")
            return

        output_path = build_output_path(self.pdf_path)

        try:
            saved_path = add_page_numbers(
                input_pdf=self.pdf_path,
                output_pdf=output_path,
                format_type=self.combo_format.currentText(),
                start_page=start_page,
                start_number=start_number,
                position=self.combo_position.currentText(),
                font_name="굴림체",
                font_size=font_size,
            )
        except Exception as e:
            QMessageBox.critical(self, "오류", f"페이지번호 추가 중 오류가 발생했습니다.\n\n{e}")
            return

        self.last_output_path = saved_path
        self.btn_open_folder.setEnabled(True)
        self.result_label.setText(f"처리 결과: 저장 완료\n{saved_path}")
        QMessageBox.information(
            self,
            "완료",
            f"페이지번호 추가가 완료되었습니다.\n\n저장 위치:\n{saved_path}"
        )

    def on_open_output_folder(self):
        if not self.last_output_path:
            QMessageBox.information(self, "안내", "먼저 페이지번호 추가를 실행해 주세요.")
            return

        folder = self.last_output_path.parent
        try:
            os.startfile(str(folder))
        except Exception as e:
            QMessageBox.warning(self, "안내", f"폴더를 여는 중 오류가 발생했습니다.\n\n{e}")

def build_page():
    return PdfPageNumberAdderPage()