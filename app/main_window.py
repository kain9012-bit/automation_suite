from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt, QUrl, QSize
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    WEBENGINE_WARMUP_AVAILABLE = True
except Exception:
    QWebEngineView = None
    QWebEnginePage = None
    WEBENGINE_WARMUP_AVAILABLE = False

from app.registry import ToolRegistry
from app.router import ToolRouter
from app.services.settings_service import SettingsService
from app.ui.home_page import HomePage, QuickLinkEditDialog
from app.ui.settings_page import SettingsPage
from app.user_state import DEFAULT_SETTINGS, UserState


class HomeFavoriteSubmenuItem(QWidget):
    def __init__(self, tool_name: str, item_width: int, open_handler, remove_handler):
        super().__init__()
        self.tool_name = tool_name

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.open_btn = QToolButton()
        self.open_btn.setObjectName("homeFavoriteButton")
        self.open_btn.setCheckable(True)
        self.open_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.open_btn.setText(tool_name)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setFixedSize(max(item_width, 156), 56)
        self.open_btn.clicked.connect(lambda checked=False, name=tool_name: open_handler(name))

        remove_btn = QPushButton("✕")
        remove_btn.setObjectName("favoriteRemoveButton")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setFixedSize(16, 16)
        remove_btn.clicked.connect(lambda checked=False, name=tool_name: remove_handler(name))

        root.addWidget(self.open_btn, 0, 0)
        root.addWidget(remove_btn, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)

    def set_checked(self, checked: bool):
        self.open_btn.setChecked(checked)


class HomeShortcutSubmenuButton(QWidget):
    def __init__(self, open_handler):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.open_btn = QToolButton()
        self.open_btn.setObjectName("homeShortcutButton")
        self.open_btn.setCheckable(True)
        self.open_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.open_btn.setText("★ 바로가기")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setFixedSize(156, 56)
        self.open_btn.clicked.connect(open_handler)
        root.addWidget(self.open_btn)

    def set_checked(self, checked: bool):
        self.open_btn.setChecked(checked)


class SubmenuDivider(QLabel):
    def __init__(self):
        super().__init__("|")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(14)
        self.setObjectName("submenuDividerLabel")


class AllMenuDialog(QDialog):
    def __init__(self, parent, tools_by_tab: dict[str, list], open_handler, favorites: list[str], favorite_toggle_handler):
        super().__init__(parent)
        self.tools_by_tab = tools_by_tab
        self.open_handler = open_handler
        self.favorites = favorites
        self.favorite_toggle_handler = favorite_toggle_handler
        self.favorite_buttons: dict[str, QPushButton] = {}
        self._drag_pos = None

        total_count = sum(len(tools) for tools in tools_by_tab.values())

        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        # size is computed from actual content after widgets are built

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(4)

        title_label = QLabel("전체 메뉴")
        title_label.setObjectName("allMenuDialogTitle")
        info_label = QLabel(f"총 {total_count}개 기능을 탭별로 확인할 수 있습니다.")
        info_label.setObjectName("allMenuDialogMeta")
        title_wrap.addWidget(title_label)
        title_wrap.addWidget(info_label)

        close_btn = QPushButton("닫기")
        close_btn.setObjectName("dialogCloseButton")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self.reject)

        top_row.addLayout(title_wrap)
        top_row.addStretch(1)
        top_row.addWidget(close_btn)
        root.addLayout(top_row)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)
        root.addWidget(body)

        ordered_tabs = list(tools_by_tab.keys())
        for tab_name in ordered_tabs:
            tools = tools_by_tab.get(tab_name, [])
            card = self._build_tab_card(tab_name, tools)
            body_layout.addWidget(card, 1)

        self.adjustSize()
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            hint = self.sizeHint()
            width = min(max(hint.width() + 24, 1240), int(available.width() * 0.96))
            height = min(hint.height() + 18, int(available.height() * 0.92))
            self.resize(width, height)

    def _build_tab_card(self, tab_name: str, tools: list):
        card = QFrame()
        card.setObjectName("allMenuCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel(tab_name)
        title.setObjectName("allMenuCardTitle")

        count_badge = QLabel(str(len(tools)))
        count_badge.setAlignment(Qt.AlignCenter)
        count_badge.setFixedSize(24, 24)
        count_badge.setObjectName("countBadge")

        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(count_badge)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e4edf8; background:#e4edf8; min-height:1px; max-height:1px;")

        layout.addLayout(header_row)
        layout.addWidget(line)

        if not tools:
            empty = QLabel("도구 없음")
            empty.setStyleSheet("font-size:13px; color:#6b7280;")
            layout.addWidget(empty)
            layout.addStretch(1)
            return card

        for tool in tools:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            btn = QPushButton(tool.name)
            btn.setObjectName("allMenuToolButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, t=tool: self._open_tool_and_close(t))

            fav_btn = QPushButton()
            fav_btn.setObjectName("allMenuFavoriteButton")
            fav_btn.setCursor(Qt.PointingHandCursor)
            fav_btn.setFixedSize(28, 28)
            fav_btn.clicked.connect(lambda checked=False, name=tool.name: self._toggle_favorite(name))
            self.favorite_buttons[tool.name] = fav_btn
            self._refresh_favorite_button(tool.name)

            row.addWidget(btn, 1)
            row.addWidget(fav_btn, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
            layout.addLayout(row)

        layout.addStretch(1)
        return card

    def _refresh_favorite_button(self, tool_name: str) -> None:
        btn = self.favorite_buttons.get(tool_name)
        if btn is None:
            return
        btn.setText("♥" if tool_name in self.favorites else "♡")

    def _toggle_favorite(self, tool_name: str) -> None:
        self.favorite_toggle_handler(tool_name)
        self._refresh_favorite_button(tool_name)

    def _open_tool_and_close(self, tool):
        self.accept()
        self.open_handler(tool)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, base_dir: Path):
        super().__init__()
        self.base_dir = base_dir
        self.registry = ToolRegistry(base_dir / "tools")
        self.router = ToolRouter()

        self.user_state = UserState(base_dir)
        state = self.user_state.load()

        self.favorites: list[str] = state.get("favorites", [])
        self.recent_tools: list[str] = state.get("recent_tools", [])
        self.settings: dict = state.get("settings", {}).copy()
        self.settings.setdefault("home_quick_links", [])
        self.settings.setdefault("home_quick_link_section_order", ["site", "folder", "file", "program"])
        self._apply_windows_auto_start_setting(show_warning=False)

        self.setWindowTitle("자동화 도구실")
        self.resize(1600, 900)

        self.current_top_tab: str | None = None
        self.current_tool = None
        self.settings_page: SettingsPage | None = None

        self.top_tab_buttons: list[QPushButton] = []
        self.sub_tool_buttons: list[QToolButton] = []
        self.home_favorite_buttons: dict[str, HomeFavoriteSubmenuItem] = {}
        self.home_shortcut_button: HomeShortcutSubmenuButton | None = None

        self._webengine_warmup_view = None
        self._webengine_warmup_page = None

        self._build_ui()
        self._load_top_tabs()
        self._refresh_home_page()

        self._apply_startup_window_mode()
        QTimer.singleShot(0, self._warm_up_webengine)
        QTimer.singleShot(0, self._restore_last_tool_if_needed)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = QWidget()
        self.top_bar.setObjectName("topBar")
        self.top_bar.setFixedHeight(88)

        top_bar_layout = QHBoxLayout(self.top_bar)
        top_bar_layout.setContentsMargins(24, 16, 24, 16)
        top_bar_layout.setSpacing(18)

        brand_wrap = QWidget()
        brand_layout = QVBoxLayout(brand_wrap)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(2)

        self.app_title_label = QLabel("자동화 도구실")
        self.app_title_label.setObjectName("appTitleLabel")
        self.app_subtitle_label = QLabel("통합 업무도구를 한 곳에서 실행하고 관리합니다.")
        self.app_subtitle_label.setObjectName("appSubtitleLabel")
        brand_layout.addWidget(self.app_title_label)
        brand_layout.addWidget(self.app_subtitle_label)

        self.top_tab_host = QWidget()
        self.top_tab_layout = QHBoxLayout(self.top_tab_host)
        self.top_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.top_tab_layout.setSpacing(8)

        top_bar_layout.addWidget(brand_wrap, 0)
        top_bar_layout.addWidget(self.top_tab_host, 1)

        self.btn_all_menu = QPushButton("전체메뉴")
        self.btn_all_menu.setObjectName("headerActionButton")
        self.btn_all_menu.setFixedHeight(38)
        self.btn_all_menu.setCursor(Qt.PointingHandCursor)
        self.btn_all_menu.clicked.connect(self._show_all_menu_dialog)

        self.btn_favorite = QPushButton("♡")
        self.btn_favorite.setObjectName("headerFavoriteButton")
        self.btn_favorite.setFixedSize(54, 38)
        self.btn_favorite.setCursor(Qt.PointingHandCursor)
        self.btn_favorite.clicked.connect(self._toggle_current_tool_favorite)

        top_bar_layout.addWidget(self.btn_all_menu, 0)
        top_bar_layout.addWidget(self.btn_favorite, 0)
        root.addWidget(self.top_bar)

        self.sub_menu_wrap = QWidget()
        self.sub_menu_wrap.setObjectName("subMenuWrap")

        self.sub_menu_layout = QHBoxLayout(self.sub_menu_wrap)
        self.sub_menu_layout.setContentsMargins(4, 6, 4, 6)
        self.sub_menu_layout.setSpacing(6)

        self.sub_menu_group = QButtonGroup(self)
        self.sub_menu_group.setExclusive(True)

        self.sub_menu_surface = QWidget()
        self.sub_menu_surface.setObjectName("subMenuSurface")
        sub_surface_layout = QVBoxLayout(self.sub_menu_surface)
        sub_surface_layout.setContentsMargins(0, 2, 0, 2)
        sub_surface_layout.setSpacing(0)

        sub_scroll = QScrollArea()
        sub_scroll.setObjectName("subMenuScrollArea")
        sub_scroll.setWidgetResizable(True)
        sub_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sub_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sub_scroll.setFrameShape(QFrame.NoFrame)
        sub_scroll.setWidget(self.sub_menu_wrap)
        sub_scroll.setFixedHeight(72)
        sub_surface_layout.addWidget(sub_scroll)
        root.addWidget(self.sub_menu_surface)

        content_bg = QWidget()
        content_bg.setObjectName("contentBackground")
        content_layout = QVBoxLayout(content_bg)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.content_shell = QFrame()
        self.content_shell.setObjectName("contentShell")
        shell_layout = QVBoxLayout(self.content_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.stack = QStackedWidget()
        shell_layout.addWidget(self.stack, 1)

        self.home_page = HomePage(
            quick_links=self._get_home_quick_links(),
            quick_link_open_handler=self._open_quick_link,
            quick_link_add_handler=self._add_quick_link,
            quick_link_edit_handler=self._edit_quick_link,
            quick_link_remove_handler=self._remove_quick_link,
            quick_link_move_handler=self._move_quick_link,
            quick_link_section_order=self._get_home_quick_link_section_order(),
            quick_link_section_move_handler=self._move_quick_link_section,
            initial_edit_mode=False,
        )
        self.stack.addWidget(self.home_page)

        self.settings_page = SettingsPage(
            settings=self.settings.copy(),
            save_callback=self._save_settings,
            reset_callback=self._reset_settings,
        )
        self.stack.addWidget(self.settings_page)

        content_layout.addWidget(self.content_shell)
        root.addWidget(content_bg, 1)

        self.footer_bar = QWidget()
        self.footer_bar.setObjectName("footerBar")
        self.footer_bar.setFixedHeight(38)

        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(12, 0, 12, 0)

        self.footer_left = QLabel("관련 문의 : 전북특별자치도교육청 정책기획과 빅데이터팀(063-239-3176)")
        self.footer_left.setObjectName("footerLeft")

        self.footer_right = QLabel("홈")
        self.footer_right.setObjectName("footerRight")

        footer_layout.addWidget(self.footer_left)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.footer_right)

        root.addWidget(self.footer_bar)
        self._ensure_footer_visible()

    def _warm_up_webengine(self) -> None:
        if not WEBENGINE_WARMUP_AVAILABLE:
            return
        try:
            self._webengine_warmup_view = QWebEngineView(self)
            self._webengine_warmup_page = QWebEnginePage(self._webengine_warmup_view)
            self._webengine_warmup_view.setPage(self._webengine_warmup_page)
            self._webengine_warmup_view.resize(1, 1)
            self._webengine_warmup_view.hide()
            self._webengine_warmup_view.setUrl(QUrl("about:blank"))
            QTimer.singleShot(1500, self._release_webengine_warmup)
        except Exception as e:
            print(f"[WebEngine warmup warning] {e}")

    def _release_webengine_warmup(self) -> None:
        try:
            if self._webengine_warmup_view is not None:
                self._webengine_warmup_view.deleteLater()
                self._webengine_warmup_view = None
        except Exception:
            pass
        try:
            if self._webengine_warmup_page is not None:
                self._webengine_warmup_page.deleteLater()
                self._webengine_warmup_page = None
        except Exception:
            pass

    def _show_all_menu_dialog(self) -> None:
        dialog = AllMenuDialog(
            self,
            self._get_all_tools_by_tab_objects(),
            self._open_tool_object,
            self.favorites,
            self._toggle_favorite_by_name,
        )
        dialog.exec()

    def _get_all_tools_by_tab_objects(self) -> dict[str, list]:
        ordered_tabs = [
            "엑셀·데이터",
            "PDF·문서",
            "수집·추출",
            "업무 자동화",
            "한글·보고서",
            "간단 도구",
        ]
        result: dict[str, list] = {}
        for tab_name in ordered_tabs:
            tools = self.registry.get_tools_by_tab(tab_name)
            if tools:
                result[tab_name] = tools
        for tab_name in self.registry.get_top_tabs():
            if tab_name in ("홈", "설정"):
                continue
            if tab_name not in result:
                tools = self.registry.get_tools_by_tab(tab_name)
                if tools:
                    result[tab_name] = tools
        return result

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _clear_sub_menu(self) -> None:
        self._clear_layout(self.sub_menu_layout)
        self.sub_tool_buttons.clear()
        self.home_favorite_buttons.clear()
        self.home_shortcut_button = None
        for old_btn in self.sub_menu_group.buttons():
            self.sub_menu_group.removeButton(old_btn)

    def _save_user_state(self) -> None:
        self.user_state.save(
            favorites=self.favorites,
            recent_tools=self.recent_tools,
            settings=self.settings,
        )

    def _get_home_favorites(self) -> list[str]:
        return self.favorites

    def _get_home_quick_links(self) -> list[dict]:
        return list(self.settings.get("home_quick_links", []))

    def _get_home_quick_link_section_order(self) -> list[str]:
        order = list(self.settings.get("home_quick_link_section_order", ["site", "folder", "file", "program"]))
        valid = ["site", "folder", "file", "program"]
        normalized = [x for x in order if x in valid]
        for item in valid:
            if item not in normalized:
                normalized.append(item)
        return normalized


    def _load_top_tabs(self) -> None:
        self._clear_layout(self.top_tab_layout)
        self.top_tab_buttons.clear()

        preferred_order = [
            "홈",
            "엑셀·데이터",
            "PDF·문서",
            "수집·추출",
            "업무 자동화",
            "한글·보고서",
            "간단 도구",
            "설정",
        ]
        loaded_tabs = set(self.registry.get_top_tabs())
        top_tabs = [tab for tab in preferred_order if tab == "홈" or tab in loaded_tabs or tab == "설정"]

        for tab_name in top_tabs:
            btn = QPushButton(tab_name)
            btn.setObjectName("topTabButton")
            btn.setCheckable(True)
            btn.setFixedHeight(38)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, name=tab_name: self._on_top_tab_clicked(name))
            self.top_tab_layout.addWidget(btn)
            self.top_tab_buttons.append(btn)

        self.top_tab_layout.addStretch(1)
        if self.top_tab_buttons:
            self.top_tab_buttons[0].setChecked(True)
            self._on_top_tab_clicked("홈")

    def _resolve_tool_icon_path(self, tool) -> Path | None:
        icon_value = getattr(tool, "icon", "") or ""
        if not icon_value:
            return None
        try:
            tool_dir = Path(getattr(tool, "base_dir", ""))
            icon_path = Path(icon_value)
            if not icon_path.is_absolute():
                icon_path = tool_dir / icon_path
            if icon_path.exists():
                return icon_path.resolve()
        except Exception:
            return None
        return None

    def _tool_sort_key(self, tool_name: str):
        preferred_tabs = [
            "엑셀·데이터",
            "PDF·문서",
            "수집·추출",
            "업무 자동화",
            "한글·보고서",
            "간단 도구",
        ]
        tab_index_map = {name: idx for idx, name in enumerate(preferred_tabs)}
        target_tool = next((tool for tool in self.registry.tools if tool.name == tool_name), None)
        if target_tool is None:
            return (9999, 999999, tool_name)
        return (tab_index_map.get(target_tool.top_tab, 9998), getattr(target_tool, "order", 999999), target_tool.name)

    def _sub_tool_button_width(self, text: str) -> int:
        font = QFont(self.font())
        if font.pointSize() <= 0:
            font.setPointSize(11)
        else:
            font.setPointSize(max(font.pointSize(), 11))
        font.setBold(True)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + 52
        return max(132, width)

    def _refresh_home_submenu_selection(self) -> None:
        if self.home_shortcut_button is not None:
            self.home_shortcut_button.set_checked(self.stack.currentWidget() is self.home_page)
        for tool_name, item in self.home_favorite_buttons.items():
            is_current = self.current_top_tab == "홈" and self.current_tool is not None and self.current_tool.name == tool_name
            item.set_checked(is_current)

    def _go_to_home_quick_links(self) -> None:
        self.current_top_tab = "홈"
        self.current_tool = None
        self.stack.setCurrentWidget(self.home_page)
        self.footer_right.setText("홈")
        self._update_page_header("HOME", "자동화 도구실", "즐겨찾기 도구와 바로가기를 빠르게 실행할 수 있습니다.")
        self._update_top_favorite_button()
        self._refresh_home_submenu_selection()

    def _build_home_favorites_submenu(self) -> None:
        self._clear_sub_menu()

        self.home_shortcut_button = HomeShortcutSubmenuButton(self._go_to_home_quick_links)
        self.sub_menu_layout.addWidget(self.home_shortcut_button)
        self.sub_menu_group.addButton(self.home_shortcut_button.open_btn)

        home_favorites = sorted(self._get_home_favorites(), key=self._tool_sort_key)
        if home_favorites:
            self.sub_menu_layout.addWidget(SubmenuDivider())

        for tool_name in home_favorites:
            item = HomeFavoriteSubmenuItem(
                tool_name=tool_name,
                item_width=self._sub_tool_button_width(tool_name),
                open_handler=self._open_tool_in_home_context,
                remove_handler=self._toggle_favorite_by_name,
            )
            self.sub_menu_layout.addWidget(item)
            self.sub_menu_group.addButton(item.open_btn)
            self.home_favorite_buttons[tool_name] = item

        self.sub_menu_layout.addStretch(1)
        self._refresh_home_submenu_selection()

    def _update_top_favorite_button(self) -> None:
        if self.current_tool is None:
            self.btn_favorite.setText("♡")
            return
        self.btn_favorite.setText("♥" if self.current_tool.name in self.favorites else "♡")

    def _toggle_current_tool_favorite(self) -> None:
        if self.current_tool is None:
            return
        self._toggle_favorite_by_name(self.current_tool.name)

    def _on_top_tab_clicked(self, tab_name: str) -> None:
        self.current_top_tab = tab_name
        self.current_tool = None
        self._clear_sub_menu()
        self.footer_right.setText(tab_name)
        self._ensure_footer_visible()
        self._update_page_header(tab_name.upper() if tab_name != "설정" else "SETTINGS", tab_name, "하위 메뉴에서 실행할 도구를 선택하세요." if tab_name not in ("홈", "설정") else "프로그램 기본 동작과 실행 옵션을 관리합니다.")
        self._update_top_favorite_button()

        for btn in self.top_tab_buttons:
            btn.setChecked(btn.text() == tab_name)

        if tab_name == "홈":
            self._clear_tool_pages()
            self.stack.setCurrentWidget(self.home_page)
            self._build_home_favorites_submenu()
            self._ensure_footer_visible_later()
            return

        if tab_name == "설정":
            self._clear_tool_pages()
            if self.settings_page is not None:
                self.stack.setCurrentWidget(self.settings_page)
            self._ensure_footer_visible_later()
            return

        tools = self.registry.get_tools_by_tab(tab_name)
        for tool in tools:
            btn = QToolButton()
            btn.setObjectName("subMenuButton")
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setText(tool.name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(self._sub_tool_button_width(tool.name), 56)

            btn.clicked.connect(lambda checked=False, t=tool: self._on_tool_clicked(t))
            self.sub_menu_layout.addWidget(btn)
            self.sub_menu_group.addButton(btn)
            self.sub_tool_buttons.append(btn)

        self.sub_menu_layout.addStretch(1)

    def _update_page_header(self, eyebrow: str, title: str, description: str) -> None:
        return

    def _show_tool_page(self, tool, footer_label: str, keep_home_context: bool = False) -> None:
        self.current_tool = tool
        self._clear_tool_pages()

        page = self.router.build_page(tool)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.footer_right.setText(footer_label)
        self._ensure_footer_visible_later()
        self._update_page_header(tool.top_tab.upper(), tool.name, getattr(tool, "description", "선택한 도구를 아래 작업영역에서 사용할 수 있습니다."))

        if tool.name in self.recent_tools:
            self.recent_tools.remove(tool.name)
        self.recent_tools.append(tool.name)

        tool_id = getattr(tool, "id", "") or getattr(tool, "tool_id", "") or ""
        self.settings["last_tool_id"] = tool_id

        if not keep_home_context:
            self.current_top_tab = tool.top_tab

        self._update_top_favorite_button()
        self._save_user_state()

    def _on_tool_clicked(self, tool) -> None:
        self._show_tool_page(tool, f"{tool.top_tab} > {tool.name}", keep_home_context=False)

    def _ensure_footer_visible(self) -> None:
        footer = getattr(self, "footer_bar", None)
        if footer is None:
            return
        footer.setVisible(True)
        footer.setFixedHeight(38)
        footer.raise_()
        self.footer_left.setVisible(True)
        self.footer_right.setVisible(True)

    def _ensure_footer_visible_later(self) -> None:
        self._ensure_footer_visible()
        QTimer.singleShot(0, self._ensure_footer_visible)
        QTimer.singleShot(100, self._ensure_footer_visible)
        QTimer.singleShot(300, self._ensure_footer_visible)

    def _clear_tool_pages(self) -> None:
        for i in range(self.stack.count() - 1, -1, -1):
            widget = self.stack.widget(i)
            if widget is None or widget in (self.home_page, self.settings_page):
                continue

            cleanup = getattr(widget, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception as e:
                    print(f"[cleanup warning] {e}")

            self.stack.removeWidget(widget)
            widget.deleteLater()

    def _open_tool_in_home_context(self, tool_name: str) -> None:
        target_tool = next((tool for tool in self.registry.tools if tool.name == tool_name), None)
        if target_tool is None:
            QMessageBox.warning(self, "도구 찾기 실패", f"'{tool_name}' 도구를 찾을 수 없습니다.")
            return

        self.current_top_tab = "홈"
        self._show_tool_page(target_tool, f"홈 > {target_tool.name}", keep_home_context=True)
        self._refresh_home_submenu_selection()

    def _toggle_favorite_by_name(self, tool_name: str) -> None:
        if tool_name in self.favorites:
            self.favorites.remove(tool_name)
        else:
            self.favorites.append(tool_name)

        self._update_top_favorite_button()
        if self.current_top_tab == "홈":
            self._build_home_favorites_submenu()
        else:
            self._refresh_home_submenu_selection()
        self._save_user_state()

    def _add_quick_link(self, name: str, link_type: str, target: str) -> None:
        name = (name or "").strip()
        target = (target or "").strip()
        link_type = (link_type or "").strip()

        if not name:
            QMessageBox.warning(self, "입력 오류", "바로가기 이름을 입력하세요.")
            return
        if not target:
            QMessageBox.warning(self, "입력 오류", "사이트 주소 또는 폴더/파일 경로를 입력하세요.")
            return
        if link_type not in ("site", "folder", "file", "program"):
            QMessageBox.warning(self, "입력 오류", "바로가기 종류가 올바르지 않습니다.")
            return

        links = self.settings.setdefault("home_quick_links", [])
        links.append({
            "id": str(uuid4()),
            "name": name,
            "type": link_type,
            "target": target,
        })

        self._refresh_home_page()
        if self.home_page is not None:
            self.home_page.set_edit_mode(False)
        self._save_user_state()

    def _edit_quick_link(self, link_id: str) -> None:
        links = self.settings.setdefault("home_quick_links", [])
        target_link = next((x for x in links if x.get("id") == link_id), None)
        if target_link is None:
            QMessageBox.warning(self, "수정 실패", "바로가기를 찾을 수 없습니다.")
            return

        dialog = QuickLinkEditDialog(self, initial_data=target_link)
        if dialog.exec() != QDialog.Accepted:
            return

        name, link_type, target = dialog.get_values()
        if not name:
            QMessageBox.warning(self, "입력 오류", "바로가기 이름을 입력하세요.")
            return
        if not target:
            QMessageBox.warning(self, "입력 오류", "사이트 주소 또는 폴더/파일 경로를 입력하세요.")
            return

        target_link["name"] = name
        target_link["type"] = link_type
        target_link["target"] = target

        self._refresh_home_page()
        self._save_user_state()

    def _remove_quick_link(self, link_id: str) -> None:
        links = self.settings.setdefault("home_quick_links", [])
        self.settings["home_quick_links"] = [x for x in links if x.get("id") != link_id]
        self._refresh_home_page()
        self._save_user_state()


    def _move_quick_link_section(self, section_type: str, direction: str) -> None:
        order = self._get_home_quick_link_section_order()
        if section_type not in order:
            return

        current_index = order.index(section_type)
        if direction == "up":
            if current_index <= 0:
                return
            swap_index = current_index - 1
        elif direction == "down":
            if current_index >= len(order) - 1:
                return
            swap_index = current_index + 1
        else:
            return

        order[current_index], order[swap_index] = order[swap_index], order[current_index]
        self.settings["home_quick_link_section_order"] = order
        self._refresh_home_page()
        if self.home_page is not None:
            self.home_page.set_edit_mode(True)
        self._save_user_state()

    def _move_quick_link(self, link_id: str, direction: str) -> None:
        links = self.settings.setdefault("home_quick_links", [])
        current_index = next((i for i, item in enumerate(links) if item.get("id") == link_id), -1)
        if current_index < 0:
            return

        current_type = links[current_index].get("type")
        same_type_indices = [i for i, item in enumerate(links) if item.get("type") == current_type]
        if current_index not in same_type_indices:
            return

        pos = same_type_indices.index(current_index)
        if direction == "left":
            if pos <= 0:
                return
            swap_index = same_type_indices[pos - 1]
        elif direction == "right":
            if pos >= len(same_type_indices) - 1:
                return
            swap_index = same_type_indices[pos + 1]
        else:
            return

        links[current_index], links[swap_index] = links[swap_index], links[current_index]
        self._refresh_home_page()
        if self.home_page is not None:
            self.home_page.set_edit_mode(True)
        self._save_user_state()

    def _open_quick_link(self, link_id: str) -> None:
        links = self.settings.setdefault("home_quick_links", [])
        target_link = next((x for x in links if x.get("id") == link_id), None)

        if target_link is None:
            QMessageBox.warning(self, "열기 실패", "바로가기를 찾을 수 없습니다.")
            return

        try:
            link_type = target_link.get("type")
            target = target_link.get("target", "")
            if link_type in ("folder", "file", "program"):
                os.startfile(target)
            else:
                webbrowser.open(target)
        except Exception as e:
            QMessageBox.warning(self, "열기 실패", f"바로가기를 여는 중 오류가 발생했습니다.\n\n{e}")

    def _save_settings(self, new_settings: dict) -> None:
        previous_fullscreen = bool(self.settings.get("start_fullscreen", True))

        merged = DEFAULT_SETTINGS.copy()
        merged.update(self.settings)
        merged.update(new_settings)

        requested_auto_start = bool(merged.get("auto_start_windows", False))
        ok, message = SettingsService.set_windows_auto_start(requested_auto_start, self.base_dir)
        if not ok:
            QMessageBox.warning(self, "자동 실행 설정 실패", message)
            merged["auto_start_windows"] = SettingsService.is_windows_auto_start_enabled(self.base_dir)

        self.settings = merged
        self.settings.setdefault("home_quick_links", [])

        if self.settings_page is not None:
            self.settings_page.settings = self.settings.copy()

        self._refresh_home_page()
        self._save_user_state()

        current_fullscreen = bool(self.settings.get("start_fullscreen", True))
        if previous_fullscreen != current_fullscreen:
            if current_fullscreen:
                self.showFullScreen()
            else:
                self.showNormal()

    def _reset_settings(self) -> None:
        keep_last_tool_id = self.settings.get("last_tool_id", "")
        keep_quick_links = self.settings.get("home_quick_links", [])

        self.settings = DEFAULT_SETTINGS.copy()
        self.settings["last_tool_id"] = keep_last_tool_id
        self.settings["home_quick_links"] = keep_quick_links
        ok, message = SettingsService.set_windows_auto_start(
            bool(self.settings.get("auto_start_windows", False)),
            self.base_dir,
        )
        if not ok:
            QMessageBox.warning(self, "자동 실행 설정 실패", message)
            self.settings["auto_start_windows"] = SettingsService.is_windows_auto_start_enabled(self.base_dir)

        if self.settings_page is not None:
            self.stack.removeWidget(self.settings_page)
            self.settings_page.deleteLater()

        self.settings_page = SettingsPage(
            settings=self.settings.copy(),
            save_callback=self._save_settings,
            reset_callback=self._reset_settings,
        )
        self.stack.addWidget(self.settings_page)

        if self.current_top_tab == "설정":
            self.stack.setCurrentWidget(self.settings_page)

        self._refresh_home_page()
        self._save_user_state()

    def _apply_windows_auto_start_setting(self, show_warning: bool = True) -> None:
        enabled = bool(self.settings.get("auto_start_windows", False))
        ok, message = SettingsService.set_windows_auto_start(enabled, self.base_dir)
        if not ok:
            self.settings["auto_start_windows"] = SettingsService.is_windows_auto_start_enabled(self.base_dir)
            if show_warning:
                QMessageBox.warning(self, "자동 실행 설정 실패", message)

    def _refresh_home_page(self) -> None:
        old_home = self.home_page
        current_widget = self.stack.currentWidget()

        self.home_page = HomePage(
            quick_links=self._get_home_quick_links(),
            quick_link_open_handler=self._open_quick_link,
            quick_link_add_handler=self._add_quick_link,
            quick_link_edit_handler=self._edit_quick_link,
            quick_link_remove_handler=self._remove_quick_link,
            quick_link_move_handler=self._move_quick_link,
            quick_link_section_order=self._get_home_quick_link_section_order(),
            quick_link_section_move_handler=self._move_quick_link_section,
            initial_edit_mode=False,
        )

        self.stack.removeWidget(old_home)
        old_home.deleteLater()
        self.stack.insertWidget(0, self.home_page)

        if current_widget == old_home:
            self.stack.setCurrentWidget(self.home_page)

        if self.current_top_tab == "홈":
            self._build_home_favorites_submenu()
        else:
            self._refresh_home_submenu_selection()

    def _apply_startup_window_mode(self) -> None:
        if self.settings.get("start_fullscreen", True):
            self.showFullScreen()
        else:
            self.showNormal()

    def _restore_last_tool_if_needed(self) -> None:
        if not self.settings.get("reopen_last_tool", False):
            return

        last_tool_id = (self.settings.get("last_tool_id", "") or "").strip()
        if not last_tool_id:
            return

        target_tool = self._find_tool_by_id(last_tool_id)
        if target_tool is None:
            return

        self._open_tool_object(target_tool)

    def _find_tool_by_id(self, tool_id: str):
        for tool in self.registry.tools:
            current_id = getattr(tool, "id", "") or getattr(tool, "tool_id", "") or ""
            if current_id == tool_id:
                return tool
        return None

    def _open_tool_object(self, target_tool) -> None:
        self._on_top_tab_clicked(target_tool.top_tab)

        tools_in_tab = self.registry.get_tools_by_tab(target_tool.top_tab)
        for btn, sub_tool in zip(self.sub_tool_buttons, tools_in_tab):
            sub_tool_id = getattr(sub_tool, "id", "") or getattr(sub_tool, "tool_id", "") or ""
            target_tool_id = getattr(target_tool, "id", "") or getattr(target_tool, "tool_id", "") or ""

            if sub_tool_id == target_tool_id or sub_tool.name == target_tool.name:
                btn.setChecked(True)
                self._on_tool_clicked(sub_tool)
                return

    def _open_tool_by_name(self, tool_name: str) -> None:
        target_tool = next((tool for tool in self.registry.tools if tool.name == tool_name), None)
        if not target_tool:
            QMessageBox.warning(self, "도구 찾기 실패", f"'{tool_name}' 도구를 찾을 수 없습니다.")
            return
        self._open_tool_object(target_tool)

    def closeEvent(self, event):
        self._release_webengine_warmup()

        if self.settings.get("confirm_on_exit", False):
            answer = QMessageBox.question(
                self,
                "프로그램 종료",
                "자동화 도구실을 종료하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        for i in range(self.stack.count()):
            widget = self.stack.widget(i)
            if widget is None:
                continue
            cleanup = getattr(widget, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception as e:
                    print(f"[cleanup warning] {e}")

        super().closeEvent(event)
