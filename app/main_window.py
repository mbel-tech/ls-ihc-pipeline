"""The application shell: stages down the left, work on the right.

Deliberately a thin frame. Every judgement about the pipeline lives in
`stages.py`; everything about running one lives in `runner.py`. This file decides
only what is on screen.
"""

import json
import os

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget)

import stages as S
import state as ST
from config_dialog import ConfigDialog
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
    def __init__(self, repo_root, scripts_dir=None, config_path=None):
        super().__init__()
        self.repo_root = repo_root
        # Whichever study the picker settled on. Falls back to the module's
        # own resolution so the window can still be opened directly in a test.
        import ls_config as LC
        self.config_path = os.path.abspath(config_path or LC.resolve_path())
        # Frozen, the stages ship inside the bundle while config.json sits beside
        # the executable, so the two roots are not the same folder.
        self.scripts_dir = scripts_dir or os.path.join(repo_root, "scripts")
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

        self._build_menu()
        self.statusBar().showMessage(
            f"{self._study_name()}   out_root  {self.out_root}")
        self._build_list()
        self.refresh()
        self._log(f"repo    {repo_root}")
        self._log(f"out     {self.out_root}")
        self._log(f"serving {self.out_root} on 127.0.0.1:{self.server.port}")
        # Written every start so it tracks the key list, and so it is sitting
        # next to the curators when someone needs it rather than being something
        # they have to be told to generate.
        try:
            ST.write_export_page(self.out_root)
        except OSError as e:
            self._log(f"could not write the state export page: {e}")
        held = ST.CurationStore(self.out_root).all_present()
        self._log(f"curation state on disk: "
                  + (", ".join(held) if held else "none yet"))

    # ---- menu -------------------------------------------------------------

    def _build_menu(self):
        """Kept on self deliberately.

        addMenu returns a QMenu that Python owns; without a reference here the
        wrapper is collected and the underlying C++ menu goes with it, so the
        menu bar ends up holding a deleted object. Same for the actions.
        """
        self._menu = self.menuBar().addMenu("&Pipeline")
        self._actions = []
        for label, slot in (("Studies…", self._studies),
                            ("Settings…", self._settings),
                            (None, None),
                            ("Import curation state…", self._import_state),
                            ("Where is my curation state?", self._explain_state)):
            if label is None:
                self._menu.addSeparator()
                continue
            act = self._menu.addAction(label)
            act.triggered.connect(slot)
            self._actions.append(act)

    def _studies(self):
        """Switch to another study, or make one."""
        from study_picker import StudyPicker
        dlg = StudyPicker(self.repo_root, self)
        if dlg.exec() and dlg.chosen and os.path.normcase(dlg.chosen) !=                 os.path.normcase(self.config_path):
            self.config_path = dlg.chosen
            self.runner.rebind(dlg.chosen)
            self.importer.config_path = dlg.chosen
            self._rebase()
            self._log(f"study is now {self.config_path}")

    def _rebase(self):
        """Re-root everything that was pointed at the previous out_root."""
        self.out_root = self._config()["out_root"]
        # The server, the curator view and the curation store were all rooted
        # at the old out_root; without this they keep serving and saving into
        # the tree that was just moved away from.
        self.server.stop()
        self.server = LocalServer(self.out_root)
        self.curator.rebase(self.server, self.out_root)
        self.refresh()
        self.statusBar().showMessage(f"{self._study_name()}   out_root  {self.out_root}")

    def _study_name(self):
        try:
            return (self._config().get("study") or {}).get("name") or                 os.path.splitext(os.path.basename(self.config_path))[0]
        except Exception:                                   # noqa: BLE001
            return "?"

    def _settings(self):
        if ConfigDialog(self.repo_root, path=self.config_path,
                        parent=self).exec():
            self._rebase()
            self._log(f"config updated - out_root {self.out_root}, serving on "
                      f"127.0.0.1:{self.server.port}; stage modules reload on next run")

    def _import_state(self):
        """Take over curation done in a browser, once.

        The app cannot read another application's localStorage, so this is the
        only honest route: the browser exports, the app imports.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "curation_state.json exported from your browser",
            self.out_root, "JSON (*.json)")
        if not path:
            return
        try:
            keys = ST.CurationStore(self.out_root).import_bundle(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Could not import", str(e))
            return
        self.curator.refresh_seed()
        self._log(f"imported curation state: {', '.join(keys) or 'nothing'}")
        QMessageBox.information(
            self, "Curation state imported",
            f"{len(keys)} key(s) imported into\n"
            f"{os.path.join(self.out_root, 'curation')}\n\n"
            "Reopen a curator to see it.")

    def _explain_state(self):
        page = os.path.join(self.out_root, "reformatted",
                            "export_curation_state.html")
        QMessageBox.information(
            self, "Curation state",
            "Decisions you make in this app are written to\n"
            f"{os.path.join(self.out_root, 'curation')}\n\n"
            "Curation you did earlier in a web browser is still in that "
            "browser's storage, which no application can read from outside. "
            "To bring it over, open this page in that browser:\n\n"
            f"{page}\n\n"
            "then use Pipeline > Import curation state.")

    # ---- helpers ----------------------------------------------------------

    def _config(self):
        with open(self.config_path, encoding="utf-8") as fh:
            return json.load(fh)

    def _log(self, text):
        self.log.appendPlainText(text)

    def _build_list(self):
        self.list.clear()

        def header(text):
            head = QListWidgetItem(text.upper())
            head.setFlags(Qt.NoItemFlags)
            hf = head.font(); hf.setPointSize(max(7, hf.pointSize() - 1)); head.setFont(hf)
            head.setForeground(Qt.gray)
            self.list.addItem(head)

        # The figure's first band. Add slides is a screen rather than a stage,
        # so it is the one row with no script behind it.
        header("Acquisition")
        add = QListWidgetItem("  Add slides")
        add.setData(Qt.UserRole, "__import__")
        f = add.font(); f.setBold(True); add.setFont(f)
        self.list.addItem(add)
        for group in S.GROUPS:
            header(group)
            for st in S.in_group(group):
                it = QListWidgetItem("   " + st.title)
                it.setData(Qt.UserRole, st.sid)
                self.list.addItem(it)

    def _state_of(self, st):
        if self._states.get(st.sid) in ("running", "failed"):
            return self._states[st.sid]
        if st.cli_reason():
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
            # The figure's red outline: a person decides here. And the one
            # stage that reads the group key, marked so it cannot be run by
            # accident while the analysis is meant to be blind.
            mark = "  ✎" if st.operator else ("  ⚠ unblinds" if st.unblinds else "")
            it.setText(f"  ● {st.title}{mark}")
            it.setForeground(QColor(DOT[state]))
            it.setToolTip(st.cli_reason() or st.blurb)
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
        reason = st.cli_reason()
        bits = [f"<b>{st.title}</b>", st.blurb]
        if st.operator:
            bits.append("<span style='color:#f85149'><b>An operator decides here.</b> "
                        "The page opens on the right; Export writes beside it.</span>")
        if st.unblinds:
            bits.append("<span style='color:#f85149'><b>Reads the treatment group.</b> "
                        "Nothing before this stage may.</span>")
        if reason:
            bits.append(f"<span style='color:#bc8cff'><b>Not run here.</b> {reason}</span>")
        elif blocked:
            names = ", ".join(S.BY_ID[b].title for b in blocked)
            bits.append(f"<span style='color:#d29922'>Usually run after: {names}"
                        "</span>")
        # The right-hand column of the figure: the file each stage leaves
        # behind, and which reader touched pixels to make it.
        if st.outputs:
            missing = set(st.missing(self.out_root))
            files = ", ".join(
                (f"<span style='color:#d29922'>{o}</span>" if o in missing else o)
                for o in st.outputs)
            bits.append(f"<span style='color:#9aa0a8'>leaves: {files}</span>")
        if st.reader != "none":
            bits.append(f"<span style='color:#9aa0a8'>pixels read by {st.reader}</span>")
        if st.script:
            bits.append(f"<code>{st.script} {' '.join(st.argv)}</code>")
        self.blurb.setText("<br>".join(b for b in bits if b))
        self.run_btn.setEnabled(bool(st.script) and not reason)
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
