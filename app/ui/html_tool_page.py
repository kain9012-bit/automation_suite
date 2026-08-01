from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import (
        QWebEngineDownloadRequest,
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
    )
    WEB_ENGINE_AVAILABLE = True
except Exception:
    WEB_ENGINE_AVAILABLE = False
    QWebEngineView = None
    QWebEnginePage = None
    QWebEngineProfile = None
    QWebEngineSettings = None
    QWebEngineDownloadRequest = None


class DebugWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        print(f"[JS console] {source_id}:{line_number} - {message}")


class HtmlToolPage(QWidget):
    def __init__(self, html_path: Path):
        super().__init__()

        self.html_path = html_path
        self._cleaned_up = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not html_path.exists():
            label = QLabel(f"HTML 파일이 없습니다:\n{html_path}")
            label.setWordWrap(True)
            layout.addWidget(label)
            return

        if not WEB_ENGINE_AVAILABLE:
            label = QLabel(
                f"Qt WebEngine을 사용할 수 없습니다.\n\n"
                f"파일 경로:\n{html_path}\n\n"
                f"PySide6 WebEngine 설치 여부를 확인하세요."
            )
            label.setWordWrap(True)
            layout.addWidget(label)
            return

        self.profile = QWebEngineProfile(self)
        self.view = QWebEngineView(self)
        self.page = DebugWebPage(self.profile, self.view)
        self.view.setPage(self.page)

        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)

        self.view.setZoomFactor(1.1)

        self.profile.downloadRequested.connect(self.handle_download_requested)
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.load(QUrl.fromLocalFile(str(html_path.resolve())))

        layout.addWidget(self.view)

    def _on_load_finished(self, ok: bool):
        print(f"[HTML loadFinished] ok={ok}")

    def handle_download_requested(self, download: "QWebEngineDownloadRequest"):
        try:
            suggested_name = download.downloadFileName() or "download"
        except Exception:
            suggested_name = "download"

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "다운로드 저장 위치 선택",
            suggested_name,
            "모든 파일 (*.*)"
        )

        if not save_path:
            download.cancel()
            return

        save_path = Path(save_path)
        download.setDownloadDirectory(str(save_path.parent))
        download.setDownloadFileName(save_path.name)
        download.accept()

        try:
            download.finished.connect(
                lambda: QMessageBox.information(
                    self,
                    "다운로드 완료",
                    f"파일 저장 완료:\n{save_path}"
                )
            )
        except Exception:
            pass

    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True

        try:
            if hasattr(self, "profile") and self.profile is not None:
                try:
                    self.profile.downloadRequested.disconnect(self.handle_download_requested)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if hasattr(self, "view") and self.view is not None:
                try:
                    self.view.stop()
                except Exception:
                    pass
                try:
                    self.view.setHtml("")
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if hasattr(self, "view") and self.view is not None:
                self.view.deleteLater()
        except Exception:
            pass

        try:
            if hasattr(self, "page") and self.page is not None:
                self.page.deleteLater()
        except Exception:
            pass

        try:
            if hasattr(self, "profile") and self.profile is not None:
                QTimer.singleShot(0, self.profile.deleteLater)
        except Exception:
            pass

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)