"""Host the existing HTML curators inside the app window.

The curators are working tools with their own tested behaviour - guided mode,
autosave, undo, the numbered seed order. Nothing here reimplements any of that.
This is a frame around them, and it exists to solve exactly two problems that
appear the moment a page moves from a browser into an embedded view.

**Serve over http, never file://.** A `file://` page cannot read its own images
back: every local image taints the canvas, so `toBlob()` throws and `fetch()` is
refused. It also cannot reach the plate images at all, since they are referenced
as `../atlas/<set>/...`, above the page's own directory. Serving `out_root` as
the document root makes both go away and costs one thread.

*What this is NOT still working around.* An early version split the DAPI channel
with `getImageData`, whose SecurityError killed `drawSec` partway and left two
empty panels; that was fixed in the page itself, by compositing instead of
reading pixels back, and the curator has not called `getImageData` since. So
from disk the page is fully usable for landmarking, ROI placement, rotation, the
filters and all three CSV exports. The one capability that genuinely needs http
is the **Shotgun deck**, which has to read bitmaps back to build a .pptx - the
page checks `location.protocol` and disables the button with a reason rather
than failing at the click.

`scripts/serve_curators.py` is this same server without the app, for a browser
that wants the same terms.

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
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEngineDownloadRequest, QWebEngineScript, QWebEngineProfile)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget

import state as ST


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
        self.store = ST.CurationStore(out_root)

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
        self._install_state_bridge()

    # ---- curation state ---------------------------------------------------

    def _install_state_bridge(self):
        """Seed the page's storage from disk, and mirror its writes back.

        The seeding script has to run at DocumentCreation - before the page's own
        script reads localStorage - or the curator starts empty and then
        overwrites the file with that emptiness on the first save.

        qwebchannel.js is Qt's own, loaded from the resource bundle rather than
        shipped as a copy, so it cannot drift from the QWebChannel on this side.
        """
        page = self.view.page()
        self.bridge = ST.Bridge(
            self.store,
            on_save=lambda k, n: self.logged.emit(f"saved   {k}  ({n/1024:.1f} KB)"))
        self.channel = QWebChannel(page)
        self.channel.registerObject("lsbridge", self.bridge)
        page.setWebChannel(self.channel)

        from PySide6.QtCore import QFile, QIODevice
        f = QFile(":/qtwebchannel/qwebchannel.js")
        qwc = ""
        if f.open(QIODevice.ReadOnly):
            qwc = bytes(f.readAll()).decode("utf-8")
            f.close()

        src = qwc + "\n" + ST.seed_script(self.store)
        sc = QWebEngineScript()
        sc.setName("ls_state_bridge")
        sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
        sc.setWorldId(QWebEngineScript.MainWorld)
        sc.setRunsOnSubFrames(False)
        sc.setSourceCode(src)
        page.scripts().insert(sc)

    def refresh_seed(self):
        """Rebuild the injected script so a later import is picked up on reload."""
        page = self.view.page()
        for sc in page.scripts().find("ls_state_bridge"):
            page.scripts().remove(sc)
        self._install_state_bridge()

    # ---- downloads --------------------------------------------------------

    def _on_download(self, item: QWebEngineDownloadRequest):
        """Send Export to the folder the page lives in, and say where it went.

        Accepting without a directory would drop the file in the profile's
        default download path, which is not anywhere the pipeline reads. The
        page's own folder is where its consumers look: the ROI curator's three
        CSVs in reformatted/, the plate reframer's plate_boxes.csv in atlas/.
        """
        name = item.downloadFileName() or "export.csv"
        target = os.path.join(self.out_root, os.path.dirname(self.rel or "reformatted/"))
        os.makedirs(target, exist_ok=True)
        item.setDownloadDirectory(target)
        item.setDownloadFileName(name)
        item.accept()

        def finished():
            # isFinishedChanged also fires for a cancelled or failed download,
            # and "exported" would then name a file that is not there.
            done = QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            if item.state() == done:
                self.logged.emit(f"exported  {os.path.join(target, name)}")
            else:
                self.logged.emit(f"export of {name} did not complete ({item.state().name})")
        item.isFinishedChanged.connect(finished)

    def rebase(self, server, out_root):
        """Point at a different out_root after Settings changed it."""
        self.server = server
        self.out_root = out_root
        self.store.dir = os.path.join(out_root, "curation")
        self.refresh_seed()
        if self.rel:
            self.show_page(self.rel, self.title.text())

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
