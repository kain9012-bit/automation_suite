from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from app.constants import DEFAULT_TOP_TABS, WINDOW_TITLE
from app.registry import ToolRegistry
from app.runtime_paths import builtin_tools_root, resource_root, state_root, user_tools_root
from app.tk_tool_router import TkToolRouter
from app.user_state import DEFAULT_SETTINGS, UserState


APP_VERSION = "3.0.0"
NAV = "#17324d"
PRIMARY = "#1769aa"
CANVAS = "#f3f6fa"
TEXT = "#17324d"
MUTED = "#65778a"
BORDER = "#dce4ee"


def _asset(name: str):
    for path in (resource_root() / name, resource_root().parent / "pdf_doc_tools_tk" / name):
        if path.is_file():
            return path
    return None


class ToolCard(ctk.CTkFrame):
    def __init__(self, master, tool, on_open, favorite, on_favorite):
        super().__init__(master, fg_color="white", corner_radius=13, border_width=1, border_color=BORDER, height=148)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=tool.name, font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT, anchor="w").grid(row=0, column=0, sticky="ew", padx=(17, 4), pady=(16, 4))
        ctk.CTkButton(
            self, text="★" if favorite else "☆", width=32, height=29, fg_color="transparent",
            hover_color="#e8f2fb", text_color="#e19b25" if favorite else MUTED,
            command=lambda: on_favorite(tool.id),
        ).grid(row=0, column=1, padx=(0, 9), pady=(11, 2))
        ctk.CTkLabel(
            self, text=tool.description or f"{tool.top_tab} 도구", font=ctk.CTkFont(size=12),
            text_color=MUTED, anchor="nw", justify="left", wraplength=250,
        ).grid(row=1, column=0, columnspan=2, sticky="nsew", padx=17)
        ctk.CTkButton(self, text="열기", width=76, height=30, command=lambda: on_open(tool)).grid(row=2, column=0, columnspan=2, sticky="e", padx=15, pady=(4, 13))


class AutomationSuiteApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.title(f"{WINDOW_TITLE} v{APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(1040, 680)
        try:
            self.state("zoomed")
        except Exception:
            pass
        icon = _asset("icon.ico")
        if icon:
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass

        self.registry = ToolRegistry([builtin_tools_root(), user_tools_root()])
        self.state_store = UserState(resource_root(), state_dir=state_root())
        saved = self.state_store.load()
        self.favorites = list(saved.get("favorites", []))
        self.recent = list(saved.get("recent_tools", []))
        self.settings = DEFAULT_SETTINGS.copy()
        self.settings.update(saved.get("settings", {}))
        self.current_tab = "홈"
        self.tab_buttons = {}
        self.router = TkToolRouter(self.set_status)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._header()
        self._sidebar()
        self._content()
        self._statusbar()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.show_tab("홈")

    def tabs(self):
        base = list(DEFAULT_TOP_TABS)
        extra = [name for name in self.registry.get_top_tabs() if name not in base and name not in {"홈", "설정"}]
        point = base.index("설정")
        return base[:point] + extra + base[point:]

    def _header(self):
        bar = ctk.CTkFrame(self, height=74, corner_radius=0, fg_color="white")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)
        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=19, sticky="w")
        image_path = _asset("brand.png")
        if image_path:
            try:
                raw = Image.open(image_path)
                ratio = 38 / max(raw.height, 1)
                size = (max(1, int(raw.width * ratio)), 38)
                raw = raw.resize(size)
                self.brand_image = ctk.CTkImage(light_image=raw, dark_image=raw, size=size)
                ctk.CTkLabel(brand, text="", image=self.brand_image).pack(side="left", padx=(0, 8))
            except Exception:
                pass
        ctk.CTkLabel(brand, text=WINDOW_TITLE, font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT).pack(side="left")
        tab_box = ctk.CTkFrame(bar, fg_color="transparent")
        tab_box.grid(row=0, column=1, padx=14, sticky="e")
        for name in self.tabs():
            button = ctk.CTkButton(
                tab_box, text=name, width=83 if len(name) < 6 else 102, height=35,
                fg_color="transparent", hover_color="#e8f2fb", text_color=TEXT,
                font=ctk.CTkFont(size=13, weight="bold"), command=lambda value=name: self.show_tab(value),
            )
            button.pack(side="left", padx=1)
            self.tab_buttons[name] = button

    def _sidebar(self):
        side = ctk.CTkFrame(self, width=222, corner_radius=0, fg_color=NAV)
        side.grid(row=1, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.grid_rowconfigure(1, weight=1)
        self.side_title = ctk.CTkLabel(side, text="도구 메뉴", font=ctk.CTkFont(size=17, weight="bold"), text_color="white", anchor="w")
        self.side_title.grid(row=0, column=0, sticky="ew", padx=17, pady=(19, 10))
        self.nav = ctk.CTkScrollableFrame(side, width=196, fg_color="transparent", scrollbar_button_color="#355d7e")
        self.nav.grid(row=1, column=0, sticky="nsew", padx=(7, 3), pady=(0, 8))
        ctk.CTkLabel(side, text=f"v{APP_VERSION}", text_color="#9fb4c7", font=ctk.CTkFont(size=11)).grid(row=2, column=0, pady=10)

    def _content(self):
        wrap = ctk.CTkFrame(self, corner_radius=0, fg_color=CANVAS)
        wrap.grid(row=1, column=1, sticky="nsew")
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)
        self.title_label = ctk.CTkLabel(wrap, text="홈", font=ctk.CTkFont(size=27, weight="bold"), text_color=TEXT, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 14))
        self.host = ctk.CTkFrame(wrap, fg_color="transparent")
        self.host.grid(row=1, column=0, sticky="nsew")

    def _statusbar(self):
        bar = ctk.CTkFrame(self, height=27, corner_radius=0, fg_color="#e8edf3")
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        self.status = ctk.CTkLabel(bar, text=f"도구 {len(self.registry.tools)}개 준비됨", text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w")
        self.status.pack(fill="x", padx=11)

    def set_status(self, text):
        self.status.configure(text=text)

    @staticmethod
    def clear(frame):
        for child in frame.winfo_children():
            child.destroy()

    def save(self):
        self.state_store.save(self.favorites, self.recent, self.settings)

    def show_tab(self, name):
        self.current_tab = name
        for tab, button in self.tab_buttons.items():
            button.configure(fg_color="#e8f2fb" if tab == name else "transparent", text_color=PRIMARY if tab == name else TEXT)
        self.title_label.configure(text=name)
        self.build_nav(name)
        if name == "홈":
            self.show_home()
        elif name == "설정":
            self.show_settings()
        else:
            self.show_grid(self.registry.get_tools_by_tab(name), name)

    def build_nav(self, name):
        self.clear(self.nav)
        self.side_title.configure(text=name if name not in {"홈", "설정"} else "도구 메뉴")
        if name == "홈":
            items = [("전체 도구", self.show_home), ("즐겨찾기", lambda: self.show_grid(self.favorite_tools(), "즐겨찾기")), ("최근 사용", lambda: self.show_grid(self.recent_tools(), "최근 사용"))]
        elif name == "설정":
            items = [("일반 설정", self.show_settings), ("도구 새로고침", self.reload_tools)]
        else:
            items = [(tool.name, lambda value=tool: self.open_tool(value)) for tool in self.registry.get_tools_by_tab(name)]
        for text, command in items:
            ctk.CTkButton(
                self.nav, text=text, anchor="w", height=38, fg_color="transparent", hover_color="#244967",
                text_color="#f5f8fb", command=command,
            ).pack(fill="x", pady=2)

    def by_ids(self, ids):
        tools = {tool.id: tool for tool in self.registry.tools}
        return [tools[item] for item in ids if item in tools]

    def favorite_tools(self):
        return self.by_ids(self.favorites)

    def recent_tools(self):
        return self.by_ids(self.recent)

    def show_home(self):
        self.clear(self.host)
        self.title_label.configure(text="홈")
        page = ctk.CTkScrollableFrame(self.host, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=18, pady=(0, 17))
        intro = ctk.CTkFrame(page, fg_color="#eaf4fc", corner_radius=15)
        intro.pack(fill="x", padx=7, pady=(0, 15))
        ctk.CTkLabel(intro, text="업무에 필요한 도구를 한곳에서 빠르게 실행하세요.", font=ctk.CTkFont(size=21, weight="bold"), text_color=TEXT).pack(anchor="w", padx=23, pady=(20, 4))
        ctk.CTkLabel(intro, text=f"현재 {len(self.registry.tools)}개 도구가 등록되어 있습니다.", text_color=MUTED).pack(anchor="w", padx=23, pady=(0, 20))
        if self.favorites:
            self.add_section(page, "즐겨찾기", self.favorite_tools())
        if self.recent:
            self.add_section(page, "최근 사용", self.recent_tools()[:8])
        self.add_section(page, "전체 도구", self.registry.tools)

    def add_section(self, parent, title, tools):
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=19, weight="bold"), text_color=TEXT).pack(anchor="w", padx=9, pady=(8, 8))
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", padx=2, pady=(0, 12))
        for column in range(3):
            grid.grid_columnconfigure(column, weight=1, uniform="cards")
        for index, tool in enumerate(tools):
            card = ToolCard(grid, tool, self.open_tool, tool.id in self.favorites, self.toggle_favorite)
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)

    def show_grid(self, tools, title=None):
        self.clear(self.host)
        if title:
            self.title_label.configure(text=title)
        page = ctk.CTkScrollableFrame(self.host, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=18, pady=(0, 17))
        self.add_section(page, title or self.current_tab, tools)

    def toggle_favorite(self, tool_id):
        if tool_id in self.favorites:
            self.favorites.remove(tool_id)
        else:
            self.favorites.insert(0, tool_id)
        self.save()
        self.show_tab(self.current_tab)

    def open_tool(self, tool):
        self.title_label.configure(text=tool.name)
        self.clear(self.host)
        if tool.id in self.recent:
            self.recent.remove(tool.id)
        self.recent.insert(0, tool.id)
        self.recent = self.recent[:20]
        self.save()
        try:
            page = self.router.build_page(tool, self.host, {"app": self, "resource_root": resource_root()})
            page.pack(fill="both", expand=True)
            self.set_status(f"{tool.name} 선택됨")
        except Exception as exc:
            messagebox.showerror("도구 열기", str(exc), parent=self)

    def show_settings(self):
        self.clear(self.host)
        self.title_label.configure(text="설정")
        page = ctk.CTkScrollableFrame(self.host, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        card = ctk.CTkFrame(page, fg_color="white", corner_radius=14, border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=8)
        ctk.CTkLabel(card, text="일반 설정", font=ctk.CTkFont(size=19, weight="bold"), text_color=TEXT).pack(anchor="w", padx=23, pady=(21, 10))
        self.update_var = ctk.BooleanVar(value=bool(self.settings.get("update_check", True)))
        ctk.CTkCheckBox(card, text="시작할 때 자동 업데이트 확인", variable=self.update_var, command=self.save_settings).pack(anchor="w", padx=23, pady=(6, 20))
        tools = ctk.CTkFrame(page, fg_color="white", corner_radius=14, border_width=1, border_color=BORDER)
        tools.pack(fill="x", pady=8)
        ctk.CTkLabel(tools, text="도구 관리", font=ctk.CTkFont(size=19, weight="bold"), text_color=TEXT).pack(anchor="w", padx=23, pady=(21, 7))
        ctk.CTkLabel(tools, text=f"사용자 도구 폴더: {user_tools_root()}", text_color=MUTED, wraplength=850).pack(anchor="w", padx=23, pady=(0, 10))
        ctk.CTkButton(tools, text="도구 목록 새로고침", command=self.reload_tools, height=37).pack(anchor="w", padx=23, pady=(0, 21))

    def save_settings(self):
        self.settings["update_check"] = bool(self.update_var.get())
        self.save()

    def reload_tools(self):
        self.registry.load_tools()
        self.set_status(f"도구 {len(self.registry.tools)}개를 다시 불러왔습니다.")
        self.show_tab("홈")

    def close_app(self):
        self.save()
        self.destroy()


def run_app() -> int:
    pythoncom = None
    try:
        import pythoncom as _pythoncom
        pythoncom = _pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        app = AutomationSuiteApp()
        app.mainloop()
        return 0
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
