from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from homepage_post_collector_service import crawl_board, make_timestamp, save_to_excel

BRAND = "#0b5ed7"
BRAND_DARK = "#0a58ca"
BORDER = "#d9e2f0"
TEXT = "#1f2937"
MUTED = "#6b7280"
PAGE_BG = "#ffffff"
CARD_BG = "#ffffff"


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


class JbeBoardCollectorPage(QWidget):
    def __init__(self):
        super().__init__()
        self.running = False
        self._build_ui()

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
            QPushButton {{
                min-height: 36px;
                padding: 0 14px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
            }}
            QTextEdit {{
                background: #f8fafc;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px;
                color: {TEXT};
            }}
            QCheckBox {{
                color: {TEXT};
                spacing: 6px;
                background: transparent;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        outer = QHBoxLayout()
        outer.setContentsMargins(30, 24, 30, 24)
        outer.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(1500)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        title = QLabel("전북교육청 홈페이지 게시글 추출 도구(v1.0)")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignHCenter)

        desc = QLabel("전북교육청 게시판 게시글을 수집해 엑셀로 저장하고, 필요시 첨부파일도 함께 다운로드합니다.")
        desc.setObjectName("pageDescription")
        desc.setAlignment(Qt.AlignHCenter)

        layout.addWidget(title)
        layout.addWidget(desc)

        top_row = QHBoxLayout()
        top_row.setSpacing(20)

        left_card = SectionCard("1. 게시판 정보 입력", "게시판 URL과 페이지 범위를 입력하고 수집 옵션을 선택합니다.")
        right_card = SectionCard("2. 실행 및 진행 상황", "수집 시작 후 진행 로그를 확인합니다.")

        left_card.setMinimumWidth(600)
        right_card.setMinimumWidth(400)

        top_row.addWidget(left_card, 3)
        top_row.addWidget(right_card, 2)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("게시판 목록 URL 입력")

        self.start_input = QLineEdit()
        self.start_input.setText("1")

        self.end_input = QLineEdit()
        self.end_input.setText("1")

        self.max_input = QLineEdit()
        self.max_input.setText("0")

        left_card.body_layout.addWidget(QLabel("게시판 목록 URL"))
        left_card.body_layout.addWidget(self.url_input)

        range_row = QHBoxLayout()
        range_row.setSpacing(10)

        start_box = QVBoxLayout()
        start_box.setSpacing(6)
        start_box.addWidget(QLabel("시작 페이지"))
        start_box.addWidget(self.start_input)

        end_box = QVBoxLayout()
        end_box.setSpacing(6)
        end_box.addWidget(QLabel("끝 페이지"))
        end_box.addWidget(self.end_input)

        max_box = QVBoxLayout()
        max_box.setSpacing(6)
        max_box.addWidget(QLabel("최대 게시글 수(선택)"))
        max_box.addWidget(self.max_input)

        range_row.addLayout(start_box)
        range_row.addLayout(end_box)
        range_row.addLayout(max_box)

        left_card.body_layout.addLayout(range_row)

        self.collect_body_chk = QCheckBox("게시글 취합(엑셀 생성)")
        self.collect_body_chk.setChecked(True)

        self.download_files_chk = QCheckBox("첨부파일 일괄 다운로드")

        left_card.body_layout.addWidget(self.collect_body_chk)
        left_card.body_layout.addWidget(self.download_files_chk)

        hint = QLabel("※ 첨부파일 다운로드만 선택하면 첨부파일만 저장되고 엑셀은 생성되지 않습니다.")
        hint.setStyleSheet(f"font-size:12px; color:{MUTED};")
        hint.setWordWrap(True)
        left_card.body_layout.addWidget(hint)
        left_card.body_layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.start_btn = QPushButton("수집 시작")
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BRAND};
                border: 1px solid {BRAND};
                color: white;
                border-radius: 6px;
                min-height: 38px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {BRAND_DARK};
                border: 1px solid {BRAND_DARK};
            }}
        """)
        self.start_btn.clicked.connect(self.on_start)

        self.reset_btn = QPushButton("초기화")
        self.reset_btn.clicked.connect(self.on_reset)
        self.reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: #ffffff;
                border: 1px solid {BORDER};
                color: {TEXT};
                border-radius: 6px;
                min-height: 38px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #f8fafc;
                border: 1px solid #c6d5eb;
            }}
        """)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.reset_btn)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        right_card.body_layout.addLayout(btn_row)
        right_card.body_layout.addWidget(self.log_text)

        layout.addLayout(top_row)
        layout.addStretch(1)

        outer.addWidget(container)
        outer.addStretch(1)
        root.addLayout(outer)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.ensureCursorVisible()
        QApplication.processEvents()

    def on_reset(self):
        self.url_input.clear()
        self.start_input.setText("1")
        self.end_input.setText("1")
        self.max_input.setText("0")
        self.collect_body_chk.setChecked(True)
        self.download_files_chk.setChecked(False)
        self.log_text.clear()

    def on_start(self):
        if self.running:
            return

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "확인", "게시판 목록 URL을 입력해주세요.")
            return

        try:
            start_page = int(self.start_input.text().strip())
            end_page = int(self.end_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "확인", "시작/끝 페이지는 숫자로 입력해주세요.")
            return

        if start_page <= 0 or end_page <= 0 or end_page < start_page:
            QMessageBox.warning(self, "확인", "페이지 범위를 다시 확인해주세요.")
            return

        try:
            max_posts = int(self.max_input.text().strip() or "0")
        except ValueError:
            max_posts = 0

        collect_body = self.collect_body_chk.isChecked()
        download_files = self.download_files_chk.isChecked()

        if not collect_body and not download_files:
            QMessageBox.warning(self, "확인", "본문 취합 또는 첨부파일 다운로드 중 하나 이상 선택해주세요.")
            return

        timestamp = make_timestamp()

        attach_dir = None
        if download_files:
            base_dir = QFileDialog.getExistingDirectory(self, "첨부파일을 저장할 폴더를 선택하세요")
            if not base_dir:
                return
            attach_dir = os.path.join(base_dir, f"첨부파일_{timestamp}")
            os.makedirs(attach_dir, exist_ok=True)

        excel_path = None
        if collect_body:
            default_name = f"게시글_취합_{timestamp}.xlsx"
            excel_path, _ = QFileDialog.getSaveFileName(
                self,
                "게시글을 저장할 엑셀 파일을 선택하세요",
                default_name,
                "엑셀 파일 (*.xlsx);;모든 파일 (*.*)"
            )
            if not excel_path:
                return

        self.running = True
        self.start_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        self.log_text.clear()
        QApplication.processEvents()

        try:
            self.log("===== 수집 시작 =====")
            self.log(f"URL: {url}")
            self.log(f"페이지: {start_page} ~ {end_page}")

            rows, errors, headers = crawl_board(
                board_url=url,
                start_page=start_page,
                end_page=end_page,
                max_posts=max_posts,
                log_func=self.log,
                collect_body=collect_body,
                download_files=download_files,
                attach_dir=attach_dir,
            )

            self.log(f"총 수집된 게시글: {len(rows)}개")
            self.log(f"오류/건너뜀: {len(errors)}개")

            if collect_body and excel_path:
                save_to_excel(headers, rows, errors, excel_path, url)
                self.log(f"엑셀 저장 완료: {excel_path}")

            msg_lines = ["수집이 완료되었습니다."]
            if collect_body and excel_path:
                msg_lines.append(f"\n· 게시글 엑셀: {excel_path}")
            if download_files and attach_dir:
                msg_lines.append(f"\n· 첨부파일 루트 폴더: {attach_dir}")

            QMessageBox.information(self, "완료", "\n".join(msg_lines))

        except Exception as e:
            QMessageBox.critical(self, "오류", f"수집 중 오류가 발생했습니다.\n\n{e}")

        finally:
            self.running = False
            self.start_btn.setEnabled(True)
            self.reset_btn.setEnabled(True)
            QApplication.processEvents()


def build_page():
    return JbeBoardCollectorPage()