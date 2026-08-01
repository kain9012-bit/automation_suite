from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, margin: int = 0, h_spacing: int = 12, v_spacing: int = 12):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            item_w = hint.width()
            item_h = hint.height()

            next_x = x + item_w + self._h_spacing
            if line_height > 0 and next_x - self._h_spacing > effective.right() + 1:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + item_w + self._h_spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, item_h)

        used_height = (y - effective.y()) + line_height
        return used_height + margins.top() + margins.bottom()


class QuickLinkEditDialog(QDialog):
    def __init__(self, parent=None, initial_data: dict | None = None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.resize(520, 260)

        initial_data = initial_data or {}
        is_edit = bool(initial_data)

        self.setStyleSheet("""
            QDialog {
                background: #ffffff;
                border: 1px solid #d8dee8;
                border-radius: 12px;
            }
            QLabel {
                color: #1f2937;
                font-size: 13px;
                background: transparent;
                border: none;
            }
            QLineEdit, QComboBox {
                min-height: 38px;
                border: 1px solid #d4dbe8;
                border-radius: 8px;
                padding: 0 10px;
                background: white;
                color: #111827;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #8ab4f8;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("바로가기 수정" if is_edit else "바로가기 추가")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #1f2937;")
        root.addWidget(title)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("바로가기 이름")
        self.name_input.setText(initial_data.get("name", ""))

        self.type_combo = QComboBox()
        self.type_combo.addItem("사이트", "site")
        self.type_combo.addItem("폴더", "folder")
        self.type_combo.addItem("파일", "file")
        self.type_combo.addItem("프로그램", "program")
        current_type = initial_data.get("type", "site")
        idx = max(0, self.type_combo.findData(current_type))
        self.type_combo.setCurrentIndex(idx)
        self.type_combo.currentIndexChanged.connect(self._update_placeholder)

        self.target_input = QLineEdit()
        self.target_input.setText(initial_data.get("target", ""))

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        form.addWidget(QLabel("이름"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("종류"), 1, 0)
        form.addWidget(self.type_combo, 1, 1)
        form.addWidget(QLabel("주소/경로"), 2, 0)
        form.addWidget(self.target_input, 2, 1)
        root.addLayout(form)

        browse_btn = QPushButton("찾아보기")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setFixedHeight(36)
        browse_btn.setStyleSheet(self._secondary_style())
        browse_btn.clicked.connect(self._browse_target)

        save_btn = QPushButton("저장")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setFixedHeight(36)
        save_btn.setStyleSheet(self._primary_style())
        save_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("닫기")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedHeight(36)
        cancel_btn.setStyleSheet(self._secondary_style())
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(browse_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        self._update_placeholder()

    def _primary_style(self):
        return """
            QPushButton {
                background: #2c67b3;
                color: white;
                border: 1px solid #2c67b3;
                border-radius: 8px;
                padding: 0 14px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #23579b;
                border-color: #23579b;
            }
        """

    def _secondary_style(self):
        return """
            QPushButton {
                background: white;
                color: #374151;
                border: 1px solid #d8dee8;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #f8fafc;
            }
        """

    def _update_placeholder(self):
        kind = self.type_combo.currentData()
        if kind == "site":
            self.target_input.setPlaceholderText("https://... 사이트 주소")
        elif kind == "folder":
            self.target_input.setPlaceholderText("폴더 경로")
        elif kind == "program":
            self.target_input.setPlaceholderText("프로그램 실행 파일 경로 (.exe 등)")
        else:
            self.target_input.setPlaceholderText("파일 경로")

    def _browse_target(self):
        kind = self.type_combo.currentData()
        if kind == "folder":
            folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
            if folder:
                self.target_input.setText(folder)
        elif kind == "file":
            file_path, _ = QFileDialog.getOpenFileName(self, "파일 선택", "", "모든 파일 (*.*)")
            if file_path:
                self.target_input.setText(file_path)
        elif kind == "program":
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "프로그램 선택",
                "",
                "프로그램 (*.exe *.bat *.cmd *.lnk *.url *.msc);;모든 파일 (*.*)"
            )
            if file_path:
                self.target_input.setText(file_path)

    def get_values(self) -> tuple[str, str, str]:
        return (
            self.name_input.text().strip(),
            self.type_combo.currentData(),
            self.target_input.text().strip(),
        )



class SectionTitle(QWidget):
    ICON_MAP = {
        "사이트": "🌐",
        "폴더": "📁",
        "파일": "📄",
        "프로그램": "🖥",
    }

    def __init__(
        self,
        title: str,
        count: int | None = None,
        section_type: str | None = None,
        edit_mode: bool = False,
        move_handler: Callable[[str, str], None] | None = None,
    ):
        super().__init__()
        self._section_type = section_type
        self._move_handler = move_handler

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        icon = QLabel(self.ICON_MAP.get(title, "•"))
        icon.setStyleSheet("font-size: 20px;")
        layout.addWidget(icon)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: 900; color: #1f2937;")
        layout.addWidget(title_label)

        if count is not None:
            badge = QLabel(str(count))
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(26, 26)
            badge.setStyleSheet(
                "background:#eaf2ff; color:#1f4f8f; border-radius:13px; font-size:12px; font-weight:800;"
            )
            layout.addWidget(badge)

        layout.addStretch(1)

        self.up_btn = QPushButton("˄")
        self.up_btn.setCursor(Qt.PointingHandCursor)
        self.up_btn.setFixedSize(22, 22)
        self.up_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #1f4f8f;
                border: none;
                font-size: 13px;
                font-weight: 900;
            }
            QPushButton:hover {
                color: #163a6b;
            }
        """)
        self.up_btn.clicked.connect(self._move_up)

        self.down_btn = QPushButton("˅")
        self.down_btn.setCursor(Qt.PointingHandCursor)
        self.down_btn.setFixedSize(22, 22)
        self.down_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #1f4f8f;
                border: none;
                font-size: 13px;
                font-weight: 900;
            }
            QPushButton:hover {
                color: #163a6b;
            }
        """)
        self.down_btn.clicked.connect(self._move_down)

        layout.addWidget(self.up_btn)
        layout.addWidget(self.down_btn)
        self.set_edit_mode(edit_mode)

    def set_edit_mode(self, enabled: bool) -> None:
        self.up_btn.setVisible(enabled)
        self.down_btn.setVisible(enabled)

    def _move_up(self):
        if self._move_handler and self._section_type:
            self._move_handler(self._section_type, "up")

    def _move_down(self):
        if self._move_handler and self._section_type:
            self._move_handler(self._section_type, "down")


class QuickLinkCard(QFrame):

    def __init__(
        self,
        link_data: dict,
        open_handler: Callable[[str], None] | None = None,
        edit_handler: Callable[[str], None] | None = None,
        remove_handler: Callable[[str], None] | None = None,
        move_handler: Callable[[str, str], None] | None = None,
        edit_mode: bool = False,
    ):
        super().__init__()
        self.link_data = link_data
        self.open_handler = open_handler
        self.edit_mode = edit_mode

        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(184, 88)
        self.setObjectName("quickLinkCard")
        self.setStyleSheet("""
            QFrame#quickLinkCard {
                background: #ffffff;
                border: 1px solid #d8e2ee;
                border-radius: 12px;
            }
            QFrame#quickLinkCard:hover {
                border: 1px solid #c9d8ee;
                background: #ffffff;
            }
            QLabel {
                background: transparent;
                border: none;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(2)

        self.move_left_btn = QPushButton("<")
        self.move_left_btn.setCursor(Qt.PointingHandCursor)
        self.move_left_btn.setFixedSize(20, 20)
        self.move_left_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #1f4f8f;
                border: none;
                font-size: 13px;
                font-weight: 900;
                padding: 0;
            }
            QPushButton:hover {
                color: #163a6b;
            }
        """)
        if move_handler:
            self.move_left_btn.clicked.connect(lambda checked=False, link_id=link_data.get("id", ""): move_handler(link_id, "left"))

        self.edit_btn = QPushButton("✎")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setFixedSize(20, 20)
        self.edit_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #475467;
                border: none;
                font-size: 12px;
                font-weight: 700;
                padding: 0;
            }
            QPushButton:hover {
                color: #1f2937;
            }
        """)
        if edit_handler:
            self.edit_btn.clicked.connect(lambda checked=False, link_id=link_data.get("id", ""): edit_handler(link_id))

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setFixedSize(20, 20)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #c2410c;
                border: none;
                font-size: 12px;
                font-weight: 800;
                padding: 0;
            }
            QPushButton:hover {
                color: #9a3412;
            }
        """)
        if remove_handler:
            self.remove_btn.clicked.connect(lambda checked=False, link_id=link_data.get("id", ""): remove_handler(link_id))

        self.move_right_btn = QPushButton(">")
        self.move_right_btn.setCursor(Qt.PointingHandCursor)
        self.move_right_btn.setFixedSize(20, 20)
        self.move_right_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #1f4f8f;
                border: none;
                font-size: 13px;
                font-weight: 900;
                padding: 0;
            }
            QPushButton:hover {
                color: #163a6b;
            }
        """)
        if move_handler:
            self.move_right_btn.clicked.connect(lambda checked=False, link_id=link_data.get("id", ""): move_handler(link_id, "right"))

        top_row.addWidget(self.move_left_btn, 0, Qt.AlignLeft | Qt.AlignTop)
        top_row.addStretch(1)
        top_row.addWidget(self.edit_btn, 0, Qt.AlignRight | Qt.AlignTop)
        top_row.addWidget(self.remove_btn, 0, Qt.AlignRight | Qt.AlignTop)
        top_row.addWidget(self.move_right_btn, 0, Qt.AlignRight | Qt.AlignTop)
        root.addLayout(top_row)

        root.addStretch(1)
        title = QLabel(link_data.get("name", "이름 없음"))
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #1f2937; background: transparent; border: none; padding: 0;")
        root.addWidget(title, 0, Qt.AlignCenter)
        root.addStretch(1)

        self.set_edit_mode(edit_mode)

    def set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = enabled
        self.edit_btn.setVisible(enabled)
        self.remove_btn.setVisible(enabled)
        self.move_left_btn.setVisible(enabled)
        self.move_right_btn.setVisible(enabled)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.open_handler and not self.edit_mode:
            self.open_handler(self.link_data.get("id", ""))
        super().mousePressEvent(event)


class HomePage(QWidget):
    def __init__(
        self,
        quick_links: list[dict] | None = None,
        quick_link_open_handler: Callable[[str], None] | None = None,
        quick_link_add_handler: Callable[[str, str, str], None] | None = None,
        quick_link_edit_handler: Callable[[str], None] | None = None,
        quick_link_remove_handler: Callable[[str], None] | None = None,
        quick_link_move_handler: Callable[[str, str], None] | None = None,
        quick_link_section_order: list[str] | None = None,
        quick_link_section_move_handler: Callable[[str, str], None] | None = None,
        initial_edit_mode: bool = False,
    ):
        super().__init__()

        self.quick_link_add_handler = quick_link_add_handler
        self._open_handler = quick_link_open_handler
        self._edit_handler = quick_link_edit_handler
        self._remove_handler = quick_link_remove_handler
        self._move_handler = quick_link_move_handler
        self._section_order = quick_link_section_order or ["site", "folder", "file", "program"]
        self._section_move_handler = quick_link_section_move_handler
        self._edit_mode = bool(initial_edit_mode)
        self._cards: list[QuickLinkCard] = []
        self._section_titles: list[SectionTitle] = []
        quick_links = quick_links or []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(scroll)

        body = QWidget()
        body.setStyleSheet("background: #ffffff;")
        scroll.setWidget(body)

        root = QVBoxLayout(body)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(18)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(4)

        title = QLabel("홈")
        title.setStyleSheet("font-size: 28px; font-weight: 900; color: #1f2937;")
        desc = QLabel("자주 사용하는 사이트·폴더·파일·프로그램을 바로가기로 등록해 빠르게 실행할 수 있습니다.")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #667085;")
        title_wrap.addWidget(title)
        title_wrap.addWidget(desc)

        self.edit_toggle_btn = QPushButton("편집")
        self.edit_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.edit_toggle_btn.setCheckable(True)
        self.edit_toggle_btn.setFixedSize(88, 40)
        self.edit_toggle_btn.setStyleSheet("""
            QPushButton {
                background: white;
                color: #1f4f8f;
                border: 1px solid #c8d6eb;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 800;
            }
            QPushButton:hover {
                background: #f8fbff;
            }
            QPushButton:checked {
                background: #1f4f8f;
                border-color: #1f4f8f;
                color: white;
            }
        """)
        self.edit_toggle_btn.clicked.connect(self._toggle_edit_mode)

        add_btn = QPushButton("바로가기 추가")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setFixedSize(132, 40)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #2c67b3;
                color: white;
                border: 1px solid #2c67b3;
                border-radius: 10px;
                padding: 0 14px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #23579b;
                border-color: #23579b;
            }
        """)
        add_btn.clicked.connect(self._open_add_dialog)

        header_row.addLayout(title_wrap, 1)
        header_row.addWidget(self.edit_toggle_btn, 0, Qt.AlignTop)
        header_row.addWidget(add_btn, 0, Qt.AlignTop)
        root.addLayout(header_row)

        if self._edit_mode:
            self.edit_toggle_btn.setChecked(True)
            self.edit_toggle_btn.setText("편집 완료")

        type_meta = {
            "site": ("사이트", [x for x in quick_links if x.get("type") == "site"]),
            "folder": ("폴더", [x for x in quick_links if x.get("type") == "folder"]),
            "file": ("파일", [x for x in quick_links if x.get("type") == "file"]),
            "program": ("프로그램", [x for x in quick_links if x.get("type") == "program"]),
        }

        ordered_types = [x for x in self._section_order if x in type_meta]
        for type_key in ("site", "folder", "file", "program"):
            if type_key not in ordered_types:
                ordered_types.append(type_key)

        for type_key in ordered_types:
            group_name, items = type_meta[type_key]
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(12)

            title_widget = SectionTitle(
                group_name,
                len(items),
                section_type=type_key,
                edit_mode=self._edit_mode,
                move_handler=self._section_move_handler,
            )
            self._section_titles.append(title_widget)
            section_layout.addWidget(title_widget)

            if not items:
                empty = QLabel(f"등록된 {group_name.lower()} 바로가기가 없습니다.")
                empty.setStyleSheet("font-size: 13px; color: #6b7280; padding: 2px 0 0 0;")
                section_layout.addWidget(empty)
            else:
                flow_wrap = QWidget()
                flow = FlowLayout(flow_wrap, margin=0, h_spacing=12, v_spacing=12)
                for link in items:
                    card = QuickLinkCard(
                        link_data=link,
                        open_handler=self._open_handler,
                        edit_handler=self._edit_handler,
                        remove_handler=self._remove_handler,
                        move_handler=self._move_handler,
                        edit_mode=self._edit_mode,
                    )
                    self._cards.append(card)
                    flow.addWidget(card)
                section_layout.addWidget(flow_wrap)

            root.addWidget(section)

        root.addStretch(1)

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self.edit_toggle_btn.blockSignals(True)
        self.edit_toggle_btn.setChecked(enabled)
        self.edit_toggle_btn.setText("편집 완료" if enabled else "편집")
        self.edit_toggle_btn.blockSignals(False)
        for card in self._cards:
            card.set_edit_mode(enabled)
        for title in self._section_titles:
            title.set_edit_mode(enabled)

    def _toggle_edit_mode(self, checked: bool) -> None:
        self.set_edit_mode(checked)

    def _open_add_dialog(self):
        if self.quick_link_add_handler is None:
            return
        dialog = QuickLinkEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            name, link_type, target = dialog.get_values()
            self.quick_link_add_handler(name, link_type, target)
