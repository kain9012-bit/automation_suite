from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from pdf_page_organizer_service import (
    PreviewSummary,
    get_total_pages,
    preview_delete,
    preview_extract,
    preview_reorder,
    preview_split,
    run_delete,
    run_extract,
    run_reorder,
    run_split,
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


class PdfPageOrganizerPage(QWidget):
    def __init__(self):
        super().__init__()
        self.pdf_path: Path | None = None
        self.output_dir: Path | None = None
        self.total_pages = 0
        self._build_ui()
        self.refresh_status()

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
            QLineEdit {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 22px;
                font-size: 13px;
                color: {TEXT};
            }}
            QListWidget {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px;
                font-size: 13px;
                color: {TEXT};
            }}
            QListWidget::item {{
                min-height: 26px;
                padding: 4px 8px;
            }}
            QListWidget::item:selected {{
                background: #eaf2ff;
                color: {TEXT};
                border-radius: 5px;
            }}
            QSpinBox {{
                background: #ffffff;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 28px;
                font-size: 13px;
                color: {TEXT};
            }}
            QFrame#infoBox {{
                background: {INFO_BG};
                border: 1px dashed #cfdcf2;
                border-radius: 8px;
            }}
            QRadioButton, QCheckBox {{
                color: {TEXT};
                spacing: 8px;
                background: transparent;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #94a3b8;
                background-color: #ffffff;
            }}
            QRadioButton::indicator:hover {{
                border: 2px solid {BRAND};
                background-color: #ffffff;
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {BRAND};
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.5, radius: 0.5,
                    fx: 0.5, fy: 0.5,
                    stop: 0 #0b5ed7,
                    stop: 0.32 #0b5ed7,
                    stop: 0.33 #ffffff,
                    stop: 1 #ffffff
                );
            }}
            QRadioButton::indicator:disabled {{
                border: 2px solid #cbd5e1;
                background-color: #f8fafc;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 2px solid #94a3b8;
                background: #ffffff;
            }}
            QCheckBox::indicator:hover {{
                border: 2px solid {BRAND};
            }}
            QCheckBox::indicator:checked {{
                background: {BRAND};
                border: 2px solid {BRAND};
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

        page_title = QLabel("PDF 페이지 정리 도구(v1.1)")
        page_title.setObjectName("pageTitle")
        page_title.setAlignment(Qt.AlignHCenter)

        page_desc = QLabel("PDF 페이지 추출, 삭제, 분할, 재배열을 로컬에서 수행합니다.")
        page_desc.setObjectName("pageDescription")
        page_desc.setAlignment(Qt.AlignHCenter)

        container_layout.addWidget(page_title)
        container_layout.addWidget(page_desc)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        left_card = SectionCard(
            "1. PDF 파일 선택 및 작업 설정",
            "PDF 파일을 선택한 뒤 페이지 추출, 삭제, 분할 중 원하는 작업을 선택하고 조건을 입력합니다."
        )
        right_card = SectionCard(
            "2. 실행 방식",
            "입력한 조건대로 PDF를 처리하고, 결과 파일은 선택한 출력 폴더에 저장합니다."
        )

        left_card.setMinimumWidth(650)
        right_card.setMinimumWidth(560)

        cards_row.addWidget(left_card, 3)
        cards_row.addWidget(right_card, 2)

        self.file_label = QLabel("선택된 PDF: (없음)")
        self.file_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        self.file_label.setWordWrap(True)
        left_card.body_layout.addWidget(self.file_label)

        self.page_count_label = QLabel("전체 페이지 수: -")
        self.page_count_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        left_card.body_layout.addWidget(self.page_count_label)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)

        self.btn_pdf = self.make_secondary_button("PDF 선택", self.on_select_pdf)
        self.btn_output = self.make_secondary_button("출력 폴더 선택", self.on_select_output_dir)

        file_row.addWidget(self.btn_pdf)
        file_row.addWidget(self.btn_output)
        file_row.addStretch(1)

        left_card.body_layout.addLayout(file_row)

        self.output_dir_label = QLabel("출력 폴더: (미선택)")
        self.output_dir_label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        self.output_dir_label.setWordWrap(True)
        left_card.body_layout.addWidget(self.output_dir_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(16)

        self.rb_extract = QRadioButton("페이지 추출")
        self.rb_delete = QRadioButton("페이지 삭제")
        self.rb_split = QRadioButton("페이지 분할")
        self.rb_reorder = QRadioButton("페이지 재배열")
        self.rb_extract.setChecked(True)

        for rb in (self.rb_extract, self.rb_delete, self.rb_split, self.rb_reorder):
            rb.toggled.connect(self.update_mode_ui)
            action_row.addWidget(rb)

        action_row.addStretch(1)
        left_card.body_layout.addLayout(action_row)

        self.extract_card = SectionCard("추출 옵션")
        self.ext_rb_pages = QRadioButton("특정 페이지 / 범위 추출")
        self.ext_rb_odd = QRadioButton("홀수 페이지 추출")
        self.ext_rb_even = QRadioButton("짝수 페이지 추출")
        self.ext_rb_pages.setChecked(True)

        self.ext_spec = QLineEdit()
        self.ext_spec.setPlaceholderText("예: 1,3,5 / 2-6 / 1,3-5,8")

        self.extract_card.body_layout.addWidget(self.ext_rb_pages)
        self.extract_card.body_layout.addWidget(self.ext_spec)
        self.extract_card.body_layout.addWidget(self.ext_rb_odd)
        self.extract_card.body_layout.addWidget(self.ext_rb_even)
        left_card.body_layout.addWidget(self.extract_card)

        self.delete_card = SectionCard("삭제 옵션")
        self.del_rb_pages = QRadioButton("특정 페이지 / 범위 삭제")
        self.del_rb_first = QRadioButton("첫 페이지 삭제")
        self.del_rb_last = QRadioButton("마지막 페이지 삭제")
        self.del_rb_odd = QRadioButton("홀수 페이지 삭제")
        self.del_rb_even = QRadioButton("짝수 페이지 삭제")
        self.del_rb_pages.setChecked(True)

        self.del_spec = QLineEdit()
        self.del_spec.setPlaceholderText("예: 1,3,5 / 2-6 / 1,3-5,8")

        self.delete_card.body_layout.addWidget(self.del_rb_pages)
        self.delete_card.body_layout.addWidget(self.del_spec)
        self.delete_card.body_layout.addWidget(self.del_rb_first)
        self.delete_card.body_layout.addWidget(self.del_rb_last)
        self.delete_card.body_layout.addWidget(self.del_rb_odd)
        self.delete_card.body_layout.addWidget(self.del_rb_even)
        left_card.body_layout.addWidget(self.delete_card)

        self.split_card = SectionCard("분할 옵션")
        self.split_rb_n = QRadioButton("N페이지 단위 분할")
        self.split_rb_at = QRadioButton("기준 페이지로 분할")
        self.split_rb_n.setChecked(True)

        split_n_row = QHBoxLayout()
        split_n_row.setSpacing(8)
        split_n_row.addWidget(QLabel("N 페이지"))
        self.split_n_value = QSpinBox()
        self.split_n_value.setMinimum(1)
        self.split_n_value.setMaximum(9999)
        self.split_n_value.setValue(2)
        split_n_row.addWidget(self.split_n_value)
        split_n_row.addStretch(1)

        self.split_spec = QLineEdit()
        self.split_spec.setPlaceholderText("예: 5 또는 3,7,12")

        self.zip_check = QCheckBox("분할 결과 ZIP도 함께 생성")

        self.split_card.body_layout.addWidget(self.split_rb_n)
        self.split_card.body_layout.addLayout(split_n_row)
        self.split_card.body_layout.addWidget(self.split_rb_at)
        self.split_card.body_layout.addWidget(self.split_spec)
        self.split_card.body_layout.addWidget(self.zip_check)
        left_card.body_layout.addWidget(self.split_card)

        self.reorder_card = SectionCard("재배열 옵션")
        self.reorder_rb_list = QRadioButton("페이지 목록에서 위/아래로 조정")
        self.reorder_rb_sequence = QRadioButton("새 페이지 순서 직접 입력")
        self.reorder_rb_move = QRadioButton("한 페이지를 다른 위치로 이동")
        self.reorder_rb_swap = QRadioButton("두 페이지 위치 맞바꾸기")
        self.reorder_rb_list.setChecked(True)
        for rb in (self.reorder_rb_list, self.reorder_rb_sequence, self.reorder_rb_move, self.reorder_rb_swap):
            rb.toggled.connect(self.update_reorder_ui)

        self.reorder_list_box = QWidget()
        list_box_layout = QVBoxLayout(self.reorder_list_box)
        list_box_layout.setContentsMargins(0, 0, 0, 0)
        list_box_layout.setSpacing(8)

        self.reorder_list = QListWidget()
        self.reorder_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.reorder_list.setMinimumHeight(160)
        list_box_layout.addWidget(self.reorder_list)

        list_btn_row = QHBoxLayout()
        list_btn_row.setSpacing(8)
        self.btn_reorder_up = self.make_secondary_button("위로", lambda: self.move_selected_reorder_page(-1))
        self.btn_reorder_down = self.make_secondary_button("아래로", lambda: self.move_selected_reorder_page(1))
        self.btn_reorder_top = self.make_secondary_button("맨 위", lambda: self.move_selected_reorder_page_to(0))
        self.btn_reorder_bottom = self.make_secondary_button("맨 아래", lambda: self.move_selected_reorder_page_to(self.reorder_list.count() - 1))
        self.btn_reorder_reset = self.make_secondary_button("초기화", self.reset_reorder_list)
        for btn in (
            self.btn_reorder_up,
            self.btn_reorder_down,
            self.btn_reorder_top,
            self.btn_reorder_bottom,
            self.btn_reorder_reset,
        ):
            list_btn_row.addWidget(btn)
        list_btn_row.addStretch(1)
        list_box_layout.addLayout(list_btn_row)

        self.reorder_spec = QLineEdit()
        self.reorder_spec.setPlaceholderText("예: 3,1-2,4-10 / 5-1,6-10")

        self.reorder_move_box = QWidget()
        move_row = QHBoxLayout(self.reorder_move_box)
        move_row.setContentsMargins(0, 0, 0, 0)
        move_row.setSpacing(8)
        move_row.addWidget(QLabel("이동할 페이지"))
        self.reorder_move_source_value = QSpinBox()
        self.reorder_move_source_value.setMinimum(1)
        self.reorder_move_source_value.setMaximum(9999)
        self.reorder_move_source_value.setValue(1)
        move_row.addWidget(self.reorder_move_source_value)
        move_row.addWidget(QLabel("새 위치"))
        self.reorder_move_target_value = QSpinBox()
        self.reorder_move_target_value.setMinimum(1)
        self.reorder_move_target_value.setMaximum(9999)
        self.reorder_move_target_value.setValue(1)
        move_row.addWidget(self.reorder_move_target_value)
        move_row.addStretch(1)

        self.reorder_swap_box = QWidget()
        swap_row = QHBoxLayout(self.reorder_swap_box)
        swap_row.setContentsMargins(0, 0, 0, 0)
        swap_row.setSpacing(8)
        swap_row.addWidget(QLabel("첫 번째 페이지"))
        self.reorder_swap_first_value = QSpinBox()
        self.reorder_swap_first_value.setMinimum(1)
        self.reorder_swap_first_value.setMaximum(9999)
        self.reorder_swap_first_value.setValue(1)
        swap_row.addWidget(self.reorder_swap_first_value)
        swap_row.addWidget(QLabel("두 번째 페이지"))
        self.reorder_swap_second_value = QSpinBox()
        self.reorder_swap_second_value.setMinimum(1)
        self.reorder_swap_second_value.setMaximum(9999)
        self.reorder_swap_second_value.setValue(2)
        swap_row.addWidget(self.reorder_swap_second_value)
        swap_row.addStretch(1)

        self.reorder_card.body_layout.addWidget(self.reorder_rb_list)
        self.reorder_card.body_layout.addWidget(self.reorder_list_box)
        self.reorder_card.body_layout.addWidget(self.reorder_rb_sequence)
        self.reorder_card.body_layout.addWidget(self.reorder_spec)
        self.reorder_card.body_layout.addWidget(self.reorder_rb_move)
        self.reorder_card.body_layout.addWidget(self.reorder_move_box)
        self.reorder_card.body_layout.addWidget(self.reorder_rb_swap)
        self.reorder_card.body_layout.addWidget(self.reorder_swap_box)
        left_card.body_layout.addWidget(self.reorder_card)

        self.update_mode_ui()

        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)

        self.summary_label = QLabel("작업 전 요약이 여기에 표시됩니다.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-size:13px; color:#334155;")
        info_layout.addWidget(self.summary_label)

        hint = QLabel(
            "※ 페이지 지정 예시: 1,3,5 / 2-6 / 1,3-5,8\n"
            "※ 암호가 설정된 PDF는 지원하지 않습니다.\n"
            "※ 같은 이름 파일이 있으면 자동으로 번호를 붙여 저장합니다.\n"
            "※ 분할 결과는 여러 개 파일로 저장되며, ZIP 생성도 선택할 수 있습니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        info_layout.addWidget(hint)

        right_card.body_layout.addWidget(info_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_preview = self.make_secondary_button("처리 요약 확인", self.on_preview)

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

        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch(1)

        right_card.body_layout.addLayout(btn_row)
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

    def refresh_status(self):
        if not self.pdf_path:
            self.file_label.setText("선택된 PDF: (없음)")
            self.page_count_label.setText("전체 페이지 수: -")
        else:
            self.file_label.setText(f"선택된 PDF: {self.pdf_path}")
            self.page_count_label.setText(f"전체 페이지 수: {self.total_pages}")

        if self.output_dir is None:
            self.output_dir_label.setText("출력 폴더: (미선택)")
        else:
            self.output_dir_label.setText(f"출력 폴더: {self.output_dir}")
        self.update_page_spin_ranges()

    def update_mode_ui(self):
        self.extract_card.setVisible(self.rb_extract.isChecked())
        self.delete_card.setVisible(self.rb_delete.isChecked())
        self.split_card.setVisible(self.rb_split.isChecked())
        self.reorder_card.setVisible(self.rb_reorder.isChecked())
        self.update_reorder_ui()

    def update_reorder_ui(self):
        is_reorder = self.rb_reorder.isChecked()
        is_list = self.reorder_rb_list.isChecked()
        is_sequence = self.reorder_rb_sequence.isChecked()
        is_move = self.reorder_rb_move.isChecked()
        is_swap = self.reorder_rb_swap.isChecked()
        self.reorder_list_box.setVisible(is_reorder and is_list)
        self.reorder_spec.setVisible(is_reorder and is_sequence)
        self.reorder_move_box.setVisible(is_reorder and is_move)
        self.reorder_swap_box.setVisible(is_reorder and is_swap)
        self.reorder_list_box.setEnabled(is_reorder and is_list)
        self.reorder_spec.setEnabled(is_reorder and is_sequence)
        self.reorder_move_box.setEnabled(is_reorder and is_move)
        self.reorder_swap_box.setEnabled(is_reorder and is_swap)

    def update_page_spin_ranges(self):
        maximum = max(1, self.total_pages)
        for spin in (
            self.reorder_move_source_value,
            self.reorder_move_target_value,
            self.reorder_swap_first_value,
            self.reorder_swap_second_value,
        ):
            spin.setMaximum(maximum)
            if spin.value() > maximum:
                spin.setValue(maximum)
        if maximum >= 2 and self.reorder_swap_first_value.value() == self.reorder_swap_second_value.value():
            self.reorder_swap_second_value.setValue(2 if self.reorder_swap_first_value.value() != 2 else 1)

    def populate_reorder_list(self):
        self.reorder_list.clear()
        if not self.pdf_path or self.total_pages <= 0:
            return
        for page_no in range(1, self.total_pages + 1):
            item = QListWidgetItem(f"{page_no}쪽")
            item.setData(Qt.UserRole, page_no)
            self.reorder_list.addItem(item)
        self.reorder_list.setCurrentRow(0)

    def reset_reorder_list(self):
        self.populate_reorder_list()

    def move_selected_reorder_page(self, direction: int):
        row = self.reorder_list.currentRow()
        if row < 0:
            return
        self.move_selected_reorder_page_to(row + direction)

    def move_selected_reorder_page_to(self, target_row: int):
        row = self.reorder_list.currentRow()
        count = self.reorder_list.count()
        if row < 0 or count <= 0:
            return
        target_row = max(0, min(target_row, count - 1))
        if target_row == row:
            return
        item = self.reorder_list.takeItem(row)
        self.reorder_list.insertItem(target_row, item)
        self.reorder_list.setCurrentRow(target_row)

    def reorder_list_spec(self) -> str:
        pages: list[int] = []
        for index in range(self.reorder_list.count()):
            item = self.reorder_list.item(index)
            page_no = item.data(Qt.UserRole)
            if page_no is None:
                continue
            pages.append(int(page_no))
        if not pages:
            raise ValueError("먼저 PDF 파일을 선택해 주세요.")
        return ",".join(map(str, pages))

    def on_select_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF 파일 선택", "", "PDF (*.pdf)")
        if not path:
            return

        self.pdf_path = Path(path).resolve()
        try:
            self.total_pages = get_total_pages(self.pdf_path)
        except Exception as e:
            self.total_pages = 0
            self.pdf_path = None
            QMessageBox.critical(self, "오류", str(e))

        self.refresh_status()
        self.populate_reorder_list()

    def on_select_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if not folder:
            return
        self.output_dir = Path(folder).resolve()
        self.refresh_status()

    def _build_preview(self) -> PreviewSummary:
        if not self.pdf_path:
            raise ValueError("먼저 PDF 파일을 선택해 주세요.")

        if self.rb_extract.isChecked():
            if self.ext_rb_pages.isChecked():
                return preview_extract(self.pdf_path, "pages", self.ext_spec.text())
            if self.ext_rb_odd.isChecked():
                return preview_extract(self.pdf_path, "odd")
            return preview_extract(self.pdf_path, "even")

        if self.rb_delete.isChecked():
            if self.del_rb_pages.isChecked():
                return preview_delete(self.pdf_path, "pages", self.del_spec.text())
            if self.del_rb_first.isChecked():
                return preview_delete(self.pdf_path, "first")
            if self.del_rb_last.isChecked():
                return preview_delete(self.pdf_path, "last")
            if self.del_rb_odd.isChecked():
                return preview_delete(self.pdf_path, "odd")
            return preview_delete(self.pdf_path, "even")

        if self.rb_reorder.isChecked():
            if self.reorder_rb_list.isChecked():
                return preview_reorder(self.pdf_path, "sequence", spec=self.reorder_list_spec())
            if self.reorder_rb_sequence.isChecked():
                return preview_reorder(self.pdf_path, "sequence", spec=self.reorder_spec.text())
            if self.reorder_rb_move.isChecked():
                return preview_reorder(
                    self.pdf_path,
                    "move",
                    source_page=self.reorder_move_source_value.value(),
                    target_page=self.reorder_move_target_value.value(),
                )
            return preview_reorder(
                self.pdf_path,
                "swap",
                source_page=self.reorder_swap_first_value.value(),
                target_page=self.reorder_swap_second_value.value(),
            )

        if self.split_rb_n.isChecked():
            return preview_split(self.pdf_path, "every_n", number=self.split_n_value.value())
        return preview_split(self.pdf_path, "at_pages", spec=self.split_spec.text())

    def on_preview(self):
        try:
            summary = self._build_preview()
            self.summary_label.setText(f"{summary.action_text}\n{summary.detail_text}")
        except Exception as e:
            QMessageBox.warning(self, "입력 확인", str(e))

    def on_run(self):
        if not self.pdf_path:
            QMessageBox.warning(self, "알림", "먼저 PDF 파일을 선택하세요.")
            return
        if self.output_dir is None:
            QMessageBox.warning(self, "알림", "출력 폴더를 선택하세요.")
            return

        self.btn_run.setEnabled(False)
        QApplication.processEvents()

        try:
            if self.rb_extract.isChecked():
                if self.ext_rb_pages.isChecked():
                    out = run_extract(self.pdf_path, self.output_dir, "pages", self.ext_spec.text())
                elif self.ext_rb_odd.isChecked():
                    out = run_extract(self.pdf_path, self.output_dir, "odd")
                else:
                    out = run_extract(self.pdf_path, self.output_dir, "even")

                QMessageBox.information(self, "완료", f"추출이 완료되었습니다.\n\n저장 파일:\n{out}")

            elif self.rb_delete.isChecked():
                if self.del_rb_pages.isChecked():
                    out = run_delete(self.pdf_path, self.output_dir, "pages", self.del_spec.text())
                elif self.del_rb_first.isChecked():
                    out = run_delete(self.pdf_path, self.output_dir, "first")
                elif self.del_rb_last.isChecked():
                    out = run_delete(self.pdf_path, self.output_dir, "last")
                elif self.del_rb_odd.isChecked():
                    out = run_delete(self.pdf_path, self.output_dir, "odd")
                else:
                    out = run_delete(self.pdf_path, self.output_dir, "even")

                QMessageBox.information(self, "완료", f"삭제 처리가 완료되었습니다.\n\n저장 파일:\n{out}")

            elif self.rb_reorder.isChecked():
                if self.reorder_rb_list.isChecked():
                    out = run_reorder(
                        self.pdf_path,
                        self.output_dir,
                        "sequence",
                        spec=self.reorder_list_spec(),
                    )
                elif self.reorder_rb_sequence.isChecked():
                    out = run_reorder(
                        self.pdf_path,
                        self.output_dir,
                        "sequence",
                        spec=self.reorder_spec.text(),
                    )
                elif self.reorder_rb_move.isChecked():
                    out = run_reorder(
                        self.pdf_path,
                        self.output_dir,
                        "move",
                        source_page=self.reorder_move_source_value.value(),
                        target_page=self.reorder_move_target_value.value(),
                    )
                else:
                    out = run_reorder(
                        self.pdf_path,
                        self.output_dir,
                        "swap",
                        source_page=self.reorder_swap_first_value.value(),
                        target_page=self.reorder_swap_second_value.value(),
                    )

                QMessageBox.information(self, "완료", f"페이지 재배열이 완료되었습니다.\n\n저장 파일:\n{out}")

            else:
                if self.split_rb_n.isChecked():
                    outputs = run_split(
                        self.pdf_path,
                        self.output_dir,
                        "every_n",
                        number=self.split_n_value.value(),
                        zip_output=self.zip_check.isChecked(),
                    )
                else:
                    outputs = run_split(
                        self.pdf_path,
                        self.output_dir,
                        "at_pages",
                        spec=self.split_spec.text(),
                        zip_output=self.zip_check.isChecked(),
                    )

                QMessageBox.information(
                    self,
                    "완료",
                    f"분할이 완료되었습니다.\n\n생성 파일 수: {len(outputs)}개\n저장 폴더:\n{self.output_dir}"
                )

            self.on_preview()

        except Exception as e:
            QMessageBox.critical(self, "오류", str(e))

        finally:
            self.btn_run.setEnabled(True)
            QApplication.processEvents()


def build_page():
    return PdfPageOrganizerPage()
