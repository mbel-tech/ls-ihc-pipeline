"""The application shell: stages down the left, work on the right.

Deliberately a thin frame. Every judgement about the pipeline lives in
`stages.py`; everything about running one lives in `runner.py`. This file decides
only what is on screen.
"""

import json
import os

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

import stages as S
from curator_view import CuratorView, LocalServer
from import_slides import ImportScreen
from runner import Runner

DOT = {"done": "#3fb950", "todo": "#8b949e", "cli": "#6e4d99",
       "running": "#4da3ff", "failed": "#f85149"}


class _Job(QObject):
    """Runs one stage off the GUI thread."""
    line = Signal(str)
    finished = Signal(object)

    def __init__(self, runner, stage):
        super().__init__()
        self.runner, self.stage = runner, stage

    def run(self):
        res = self.runner.run(self.stage, on_line=self.line.emit)
        self.finished.emit(res)


class MainWindow(QMainWindow):
    def __init__(self, repo_root):
        super().__init__()
        self.repo_root = repo_root
        self.config_path = os.path.join(repo_root, "config.json")
        self.scripts_dir = os.path.join(repo_root, "scripts")
        self.runner = Runner(self.scripts_dir, self.config_path)
        self.out_root = self._config()["out_root"]
        self.server = LocalServer(self.out_root)
        self._thread = None
        self._states = {}

        self.setWindowTitle("LS IHC pipeline")
        self.resize(1360, 860)

        # ---- left: the pipeline ------------------------------------------
        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        self.list.currentItemChanged.connect(self._on_select)
        self.list.setMinimumWidth(330)

        self.run_btn = QPushButton("Run stage")
        self.run_btn.clicked.connect(self._run_current)
        self.refresh_btn = QPushButton("Refresh status")
        self.refresh_btn.clicked.connect(self.refresh)
        btns = QHBoxLayout()
        btns.addWidget(self.run_btn, 1)
        btns.addWidget(self.refresh_btn)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.addWidget(self.list, 1)
        lv.addLayout(btns)

        # ---- right: log, import, curators --------------------------------
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumBlockCount(20000)

        self.blurb = QLabel("")
        self.blurb.setWordWrap(True)
        self.blurb.setStyleSheet("padding:6px")

        log_page = QWidget()
        lg = QVBoxLayout(log_page)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.addWidget(self.blurb)
        lg.addWidget(self.log, 1)

        self.importer = ImportScreen(self.config_path, self.runner)
        self.importer.logged.connect(self._log)
        self.importer.imported.connect(self.refresh)

        self.curator = CuratorView(self.server, self.out_root)
        self.curator.logged.connect(self._log)

        self.stack = QStackedWidget()
        self.stack.addWidget(log_page)      # 0
        self.stack.addWidget(self.importer)  # 1
        self.stack.addWidget(self.curator)   # 2

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self.statusBar().showMessage(f"out_root  {self.out_root}")
        self._build_list()
        self.refresh()
        self._log(f"repo    {repo_root}")
        self._log(f"out     {self.out_root}")
        self._log(f"serving {self.out_root} on 127.0.0.1:{self.server.port}")

    # ---- helpers ----------------------------------------------------------

    def _config(self):
        with open(self.config_path, encoding="utf-8") as fh:
            return json.load(fh)

    def _log(self, text):
        self.log.appendPlainText(text)

    def _build_list(self):
        self.list.clear()
        add = QListWidgetItem("  Add slides")
        add.setData(Qt.UserRole, "__import__")
        f = add.font(); f.setBold(True); add.setFont(f)
        self.list.addItem(add)
        for group in S.GROUPS:
            head = QListWidgetItem(group.upper())
            head.setFlags(Qt.NoItemFlags)
            hf = head.font(); hf.setPointSize(max(7, hf.pointSize() - 1)); head.setFont(hf)
            head.setForeground(Qt.gray)
            self.list.addItem(head)
            for st in S.in_group(group):
                it = QListWidgetItem("   " + st.title)
                it.setData(Qt.UserRole, st.sid)
                self.list.addItem(it)

    def _state_of(self, st):
        if self._states.get(st.sid) in ("running", "failed"):
            return self._states[st.sid]
        if st.cli_only:
            return "cli"
        return "done" if st.done(self.out_root) else "todo"

    def refresh(self):
        self.out_root = self._config()["out_root"]
        for i in range(self.list.count()):
            it = self.list.item(i)
            sid = it.data(Qt.UserRole)
            if not sid or sid == "__import__":
                continue
            st = S.BY_ID[sid]
            state = self._state_of(st)
            it.setText(f"  {'●'} {st.title}")
            it.setForeground(Qt.GlobalColor.white)
            from PySide6.QtGui import QColor
            it.setForeground(QColor(DOT[state]))
        self.statusBar().showMessage(f"out_root  {self.out_root}")

    # ---- selection --------------------------------------------------------

    def _current_stage(self):
        it = self.list.currentItem()
        if not it:
            return None
        sid = it.data(Qt.UserRole)
        return S.BY_ID.get(sid) if sid and sid != "__import__" else None

    def _on_select(self, item, _prev):
        if not item:
            return
        sid = item.data(Qt.UserRole)
        if sid == "__import__":
            self.stack.setCurrentIndex(1)
            self.run_btn.setEnabled(False)
            return
        st = S.BY_ID.get(sid)
        if not st:
            return
        if st.curator:
            self.curator.show_page(st.curator, st.title)
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(0)

        blocked = S.blocked_by(st, self.out_root)
        bits = [f"<b>{st.title}</b>", st.blurb]
        if st.cli_only:
            bits.append(f"<span style='color:#bc8cff'><b>Not run here.</b> "
                        f"{st.cli_only}</span>")
        elif blocked:
            names = ", ".join(S.BY_ID[b].title for b in blocked)
            bits.append(f"<span style='color:#d29922'>Usually run after: {names}"
                        "</span>")
        if st.script:
            bits.append(f"<code>{st.script} {' '.join(st.argv)}</code>")
        self.blurb.setText("<br>".join(b for b in bits if b))
        self.run_btn.setEnabled(bool(st.script) and not st.cli_only)
        self.run_btn.setText("Regenerate" if st.curator else "Run stage")

    # ---- running ----------------------------------------------------------

    def _run_current(self):
        st = self._current_stage()
        if not st or self._thread:
            return
        self._states[st.sid] = "running"
        self.refresh()
        self.run_btn.setEnabled(False)
        self._log(f"\n=== {st.title} ===")

        self._thread = QThread(self)
        self._job = _Job(self.runner, st)
        self._job.moveToThread(self._thread)
        self._thread.started.connect(self._job.run)
        self._job.line.connect(self._log)
        self._job.finished.connect(lambda res, s=st: self._done(s, res))
        self._thread.start()

    def _done(self, st, res):
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self._states[st.sid] = "done" if res.ok else "failed"
        if res.ok:
            self._log(f"--- {st.title}: done in {res.seconds:.1f}s")
        else:
            self._log(f"--- {st.title}: FAILED\n{res.error}")
            QMessageBox.warning(self, f"{st.title} failed",
                                (res.error or "").split("\n\n")[0][:600])
        if st.curator and res.ok:
            self.curator.show_page(st.curator, st.title)
        self.refresh()
        self.run_btn.setEnabled(True)

    def closeEvent(self, e):
        self.server.stop()
        super().closeEvent(e)
