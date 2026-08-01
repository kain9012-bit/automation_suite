from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from app.runtime_paths import bundled_apps_root, resource_root


PDF_TOOL_IDS = {
    "pdf_merge", "pdf_compress", "pdf_page_organizer", "pdf_page_number_adder",
    "multi_format_pdf_combiner", "hwp_collector", "hwp_to_pdf_converter",
    "hwp_to_hwpx_converter",
}
FILE_TOOL_IDS = {
    "zip_batch_extractor", "folder_unpacker", "file_inventory", "rename_files",
    "empty_folder_cleaner",
}
CERTIFICATE_TOOL_IDS = {
    "certificate_pdf_collector", "certificate_pdf_splitter", "certificate_pdf_renamer",
}
BOARD_TOOL_IDS = {"homepage_post_collector"}


APP_GROUPS = {
    "pdf": {
        "title": "PDF·한글 문서정리 도우미",
        "description": "PDF 및 한글 문서 작업용 CustomTkinter 통합 앱을 실행합니다.",
        "bundled_names": ["PDF·한글 문서정리 도우미 v2.2.exe", "PDF·한글 문서정리 도우미 v2.1.exe"],
        "dev_project": "pdf_doc_tools_tk",
        "patterns": ["*문서정리*도우미*.exe"],
    },
    "file": {
        "title": "업무자동화 파일정리 도우미",
        "description": "파일명 변경, 파일 꺼내기, 현황표, ZIP 작업용 앱을 실행합니다.",
        "bundled_names": ["업무자동화 파일정리 도우미 v2.1.exe", "업무자동화 파일정리 도우미 v2.0.exe"],
        "dev_project": "file_automation_tools_tk",
        "patterns": ["*파일정리*도우미*.exe"],
    },
    "certificate": {
        "title": "이수증 PDF 도우미",
        "description": "이수증 PDF 분할, 파일명 정리 및 취합용 앱을 실행합니다.",
        "bundled_names": ["이수증 PDF 도우미 v1.6.exe", "이수증 PDF 도우미 v1.5.exe"],
        "dev_project": "certificate_pdf_tools_tk",
        "patterns": ["*이수증*PDF*도우미*.exe"],
    },
    "board": {
        "title": "홈페이지 게시글 취합기",
        "description": "교육청 홈페이지 게시글과 첨부파일 수집용 앱을 실행합니다.",
        "bundled_names": ["홈페이지 게시글 취합기 v2.0.exe"],
        "dev_project": "board_app",
        "patterns": ["*게시글*취합기*.exe"],
    },
}


def _group_for_tool(tool_id: str) -> str | None:
    if tool_id in PDF_TOOL_IDS:
        return "pdf"
    if tool_id in FILE_TOOL_IDS:
        return "file"
    if tool_id in CERTIFICATE_TOOL_IDS:
        return "certificate"
    if tool_id in BOARD_TOOL_IDS:
        return "board"
    return None


def _find_app_executable(group: str) -> Path | None:
    spec = APP_GROUPS[group]
    for name in spec["bundled_names"]:
        path = bundled_apps_root() / name
        if path.is_file():
            return path

    project_root = resource_root().parent / spec["dev_project"] / "dist"
    if project_root.is_dir():
        matches: list[Path] = []
        for pattern in spec["patterns"]:
            matches.extend(project_root.glob(pattern))
        matches = [path for path in matches if path.is_file()]
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)
    return None


class AppLauncherPage(ctk.CTkFrame):
    def __init__(self, master, tool, group: str, status_callback=None):
        super().__init__(master, fg_color="transparent")
        self.tool = tool
        self.group = group
        self.status_callback = status_callback
        info = APP_GROUPS[group]

        card = ctk.CTkFrame(self, corner_radius=16, fg_color="#ffffff", border_width=1, border_color="#dce4ee")
        card.pack(fill="x", padx=28, pady=28)
        ctk.CTkLabel(card, text=tool.name, font=ctk.CTkFont(size=25, weight="bold"), text_color="#17324d").pack(anchor="w", padx=28, pady=(28, 8))
        ctk.CTkLabel(
            card, text=tool.description or info["description"], font=ctk.CTkFont(size=14),
            text_color="#5f7185", wraplength=760, justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 20))
        ctk.CTkButton(
            card, text=f"{info['title']} 실행", command=self.launch, height=42,
            corner_radius=9, fg_color="#1769aa", hover_color="#12578f",
        ).pack(anchor="w", padx=28, pady=(0, 28))
        self.after(120, self.launch)

    def launch(self) -> None:
        executable = _find_app_executable(self.group)
        if executable is None:
            messagebox.showerror(
                "도구 실행", "실행 파일을 찾지 못했습니다.\n새 CustomTkinter onefile 빌드에 참고 앱을 포함해 주세요.",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            env = os.environ.copy()
            env["JBEDU_START_TOOL"] = self.tool.id
            subprocess.Popen([str(executable)], cwd=str(executable.parent), env=env)
            if self.status_callback:
                self.status_callback(f"{self.tool.name} 실행됨")
        except Exception as exc:
            messagebox.showerror("도구 실행", str(exc), parent=self.winfo_toplevel())


class EmbeddedHtmlPage(ctk.CTkFrame):
    RUNTIME_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

    def __init__(self, master, tool, html_path: Path, status_callback=None):
        super().__init__(master, fg_color="transparent")
        self.tool = tool
        self.html_path = html_path
        self.status_callback = status_callback
        self.webview = None
        toolbar = ctk.CTkFrame(self, height=43, corner_radius=0, fg_color="#e8edf3")
        toolbar.pack(fill="x", padx=1, pady=(0, 1))
        toolbar.pack_propagate(False)
        ctk.CTkButton(toolbar, text="←", width=38, height=29, command=self.go_back).pack(side="left", padx=(8, 3), pady=7)
        ctk.CTkButton(toolbar, text="새로고침", width=78, height=29, command=self.reload).pack(side="left", padx=3, pady=7)
        ctk.CTkButton(toolbar, text="외부 창", width=72, height=29, command=self.open_external).pack(side="left", padx=3, pady=7)
        ctk.CTkLabel(toolbar, text=tool.name, text_color="#526579").pack(side="left", padx=12)
        self.browser_host = ctk.CTkFrame(self, corner_radius=0, fg_color="white")
        self.browser_host.pack(fill="both", expand=True)
        self.after(30, self._create_webview)

    def _create_webview(self):
        if not self.html_path.is_file():
            self._show_error(f"HTML 파일을 찾지 못했습니다.\n{self.html_path}")
            return
        try:
            from tkwebview2.tkwebview2 import WebView2, have_runtime
        except Exception as exc:
            self._show_error(f"내장 WebView2 모듈을 불러오지 못했습니다.\n{exc}")
            return
        try:
            if not have_runtime():
                self._show_error("Microsoft Edge WebView2 Runtime이 설치되어 있지 않습니다.", True)
                return
            self.update_idletasks()
            width = max(self.browser_host.winfo_width(), 800)
            height = max(self.browser_host.winfo_height(), 560)
            self.webview = WebView2(self.browser_host, width, height, url=self.html_path.resolve().as_uri())
            self.webview.pack(fill="both", expand=True)
            if self.status_callback:
                self.status_callback(f"{self.tool.name} 내장 WebView2에서 열림")
        except Exception as exc:
            self._show_error(f"WebView2 초기화에 실패했습니다.\n{exc}")

    def _show_error(self, text: str, show_runtime_button: bool = False):
        for child in self.browser_host.winfo_children():
            child.destroy()
        card = ctk.CTkFrame(self.browser_host, fg_color="white", corner_radius=14, border_width=1, border_color="#dce4ee")
        card.pack(fill="x", padx=28, pady=28)
        ctk.CTkLabel(card, text=text, text_color="#b03a2e", justify="left", wraplength=760).pack(anchor="w", padx=24, pady=(22, 12))
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(anchor="w", padx=24, pady=(0, 22))
        ctk.CTkButton(buttons, text="기본 브라우저에서 열기", command=self.open_external).pack(side="left", padx=(0, 8))
        if show_runtime_button:
            ctk.CTkButton(buttons, text="WebView2 설치 안내", command=lambda: webbrowser.open(self.RUNTIME_DOWNLOAD_URL)).pack(side="left")

    def go_back(self):
        try:
            if self.webview and self.webview.core and self.webview.core.CanGoBack:
                self.webview.core.GoBack()
        except Exception:
            pass

    def reload(self):
        try:
            if self.webview and self.webview.core:
                self.webview.reload()
        except Exception:
            pass

    def open_external(self):
        if self.html_path.is_file():
            webbrowser.open(self.html_path.resolve().as_uri())

class ExternalExePage(ctk.CTkFrame):
    def __init__(self, master, tool, status_callback=None):
        super().__init__(master, fg_color="transparent")
        self.tool = tool
        self.status_callback = status_callback
        ctk.CTkButton(self, text=f"{tool.name} 실행", command=self.launch, height=44).pack(padx=30, pady=40)
        self.after(120, self.launch)

    def launch(self) -> None:
        path = self.tool.entry_path
        if not path.is_file():
            messagebox.showerror("도구 실행", f"실행 파일을 찾지 못했습니다.\n{path}", parent=self.winfo_toplevel())
            return
        subprocess.Popen([str(path)], cwd=str(path.parent))
        if self.status_callback:
            self.status_callback(f"{self.tool.name} 실행됨")


class TkToolRouter:
    def __init__(self, status_callback=None):
        self.status_callback = status_callback

    @staticmethod
    def _load_tk_plugin(tool, master, context):
        module_name = f"tk_tool_{tool.id}"
        spec = importlib.util.spec_from_file_location(module_name, tool.entry_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"도구 모듈을 불러올 수 없습니다: {tool.entry_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        builder = getattr(module, "build_tk_page", None)
        if builder is None:
            raise RuntimeError("CustomTkinter 도구에는 build_tk_page(master, context)가 필요합니다.")
        return builder(master, context)

    def build_page(self, tool, master, context=None):
        html_path = tool.entry_path if tool.type == "html" else tool.base_dir / "web" / "index.html"
        if html_path.is_file() and (tool.type == "html" or tool.id in {"excel_merge", "excel_split"}):
            return EmbeddedHtmlPage(master, tool, html_path, self.status_callback)
        if tool.type == "external_exe":
            return ExternalExePage(master, tool, self.status_callback)
        group = _group_for_tool(tool.id)
        if group:
            return AppLauncherPage(master, tool, group, self.status_callback)
        if tool.type in {"internal_python", "tk_python"}:
            return self._load_tk_plugin(tool, master, context or {})
        raise RuntimeError(f"지원하지 않는 도구 유형입니다: {tool.type}")
