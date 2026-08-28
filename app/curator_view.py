"""Host the existing HTML curators inside the app window.

The curators are working tools with their own tested behaviour - guided mode,
autosave, undo, the numbered seed order. Nothing here reimplements any of that.
This is a frame around them, and it exists to solve exactly two problems that
appear the moment a page moves from a browser into an embedded view.

**Serve over http, never file://.** The plate images are referenced as
`../atlas/<set>/...`, above the page's own directory, and a `file://` page throws
SecurityError from `getImageData` - which is what once killed `drawSec` partway
and left two empty panels. Serving `out_root` as the document root makes both
problems go away and costs one thread.

**Catch the download.** Export builds a Blob and clicks an `<a download>`. A
browser saves it; QtWebEngine raises `downloadRequested` and, with nothing
attached, silently discards it. Export would appear to do nothing at all.
"""

import functools
import http.server
import os
import socketserver
import threading

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static files, without logging every tile request to the console."""

    def log_message(self, fmt, *args):
        pass


class LocalServer:
    """Serve out_root on an ephemeral loopback port for the lifetime of the app."""

    def __init__(self, root):
        self.root = root
        handler = functools.partial(_QuietHandler, directory=root)
        # Port 0 lets the OS pick, so two copies of the app do not collide.
        self._srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self._srv.daemon_threads = True
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()

    def url_for(self, rel):
        return QUrl(f"http://127.0.0.1:{self.port}/{rel.replace(os.sep, '/')}")

    def stop(self):
        try:
            self._srv.shutdown()
            self._srv.server_close()
        except Exception:                                   # noqa: BLE001
            pass


class CuratorView(QWidget):
    """One curator page, with a reload and a note of where exports land."""

    logged = Signal(str)

    def __init__(self, server, out_root, parent=None):
        super().__init__(parent)
        self.server = server
        self.out_root = out_root
        self.rel = None

        self.view = QWebEngineView(self)
        self.title = QLabel("", self)
        self.title.setStyleSheet("color:#9aa0a8;padding:2px 6px")

        reload_btn = QPushButton("Reload", self)
        reload_btn.clicked.connect(self.view.reload)
        browser_btn = QPushButton("Open in browser", self)
        browser_btn.clicked.connect(self._open_external)

        bar = QHBoxLayout()
        bar.addWidget(self.title, 1)
        bar.addWidget(reload_btn)
        bar.addWidget(browser_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)

        prof = self.view.page().profile()
        prof.downloadRequested.connect(self._on_download)

    # ---- downloads --------------------------------------------------------

    def _on_download(self, item: QWebEngineDownloadRequest):
        """Send Export straight to reformatted/, and say where it went.

        Accepting without a directory would drop the file in the profile's
        default download path, which is not anywhere the pipeline reads.
        """
        name = item.downloadFileName() or "export.csv"
        target = os.path.join(self.out_root, "reformatted")
        os.makedirs(target, exist_ok=True)
        item.setDownloadDirectory(target)
        item.setDownloadFileName(name)
        item.accept()
        item.isFinishedChanged.connect(
            lambda: self.logged.emit(f"exported  {os.path.join(target, name)}"))

    def _open_external(self):
        import webbrowser
        if self.rel:
            webbrowser.open(self.server.url_for(self.rel).toString())

    # ---- loading ----------------------------------------------------------

    def show_page(self, rel, label=""):
        self.rel = rel
        self.title.setText(label or rel)
        path = os.path.join(self.out_root, rel)
        if not os.path.exists(path):
            self.view.setHtml(
                "<body style='background:#0e1014;color:#e6e6e6;font:14px system-ui;"
                "padding:24px'><h2>Not built yet</h2>"
                f"<p><code>{rel}</code> does not exist. Run the stage that "
                "generates it, then reload.</p></body>")
            return
        self.view.setUrl(self.server.url_for(rel))
