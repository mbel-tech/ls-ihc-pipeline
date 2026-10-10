"""Choosing which study the app is working on.

A study is one config file with a name. Everything the app then does - the
stage list, the local server, the curator pages - is rooted in that file's
`out_root`, so this is the first question the app has to answer and the one it
must never answer by guessing.

It replaces `ensure_config`, which asked only whether a usable `config.json`
existed. That was fine while there was one dataset. With several, "which one am
I looking at" has to be visible and deliberate, which is why the chosen study's
name sits in the status bar for the rest of the session.
"""

import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

import ls_config as LC


def reveal(path):
    """Open a folder in the platform's file manager."""
    path = os.path.abspath(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)                              # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


class StudyPicker(QDialog):
    """Pick a study, make one, or bring a pre-study config in as one."""

    def __init__(self, repo_root, parent=None):
        super().__init__(parent)
        self.repo_root = repo_root
        self.chosen = None
        self.setWindowTitle("Studies")
        self.resize(560, 380)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._open())

        where = QLabel(f"Studies live in {LC.studies_dir()}")
        where.setStyleSheet("color:#9aa0a8;font-size:11px")
        where.setWordWrap(True)

        new = QPushButton("New study…")
        new.clicked.connect(self._new)
        self.migrate_btn = QPushButton("Import existing config…")
        self.migrate_btn.clicked.connect(self._migrate)
        show = QPushButton("Reveal folder")
        show.clicked.connect(lambda: reveal(LC.studies_dir()))

        row = QHBoxLayout()
        row.addWidget(new)
        row.addWidget(self.migrate_btn)
        row.addWidget(show)
        row.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Open
                                        | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._open)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Which study are you working on?"))
        lay.addWidget(self.list, 1)
        lay.addWidget(where)
        lay.addLayout(row)
        lay.addWidget(self.buttons)

        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self):
        self.list.clear()
        active = LC.read_settings().get("active_study")
        for slug, name, path in LC.list_studies():
            item = QListWidgetItem(f"{name}    ({slug})")
            item.setData(Qt.UserRole, (slug, path))
            self.list.addItem(item)
            if slug == active:
                self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentItem() is None:
            self.list.setCurrentRow(0)

        legacy = os.path.join(self.repo_root, "config.json")
        self.migrate_btn.setEnabled(os.path.exists(legacy))
        self.migrate_btn.setToolTip(
            f"Copy {legacy} into a named study" if os.path.exists(legacy)
            else "No pre-study config.json to import")
        self.buttons.button(QDialogButtonBox.Open).setEnabled(
            self.list.count() > 0)

    def _ask_name(self, title, prompt):
        name, ok = QInputDialog.getText(self, title, prompt)
        return name.strip() if ok and name.strip() else None

    def _new(self):
        """A study with no settings yet: made here, filled in by the dialog."""
        name = self._ask_name("New study", "Name for this study:")
        if not name:
            return
        from config_dialog import ConfigDialog
        try:
            path = LC.study_path(name)
        except SystemExit as exc:
            QMessageBox.warning(self, "Name", str(exc))
            return
        if os.path.exists(path):
            QMessageBox.warning(self, "Already exists",
                                f"A study called {os.path.basename(path)} is "
                                f"already there.")
            return
        dlg = ConfigDialog(self.repo_root, path=path, study_name=name,
                           parent=self)
        if dlg.exec() == QDialog.Accepted:
            LC.write_settings({"active_study": LC.slugify(name)})
            self._refresh()

    def _migrate(self):
        """Bring the pre-study config.json in under a name, leaving it in place."""
        name = self._ask_name("Import existing config",
                              "Name for the study in config.json:")
        if not name:
            return
        try:
            path = LC.migrate(name)
        except SystemExit as exc:
            QMessageBox.warning(self, "Could not import", str(exc))
            return
        QMessageBox.information(
            self, "Imported",
            f"Written to {path}\n\nThe original config.json is untouched.")
        self._refresh()

    def _open(self):
        item = self.list.currentItem()
        if item is None:
            return
        slug, path = item.data(Qt.UserRole)
        LC.write_settings({"active_study": slug})
        LC.clear_cache()
        self.chosen = path
        self.accept()


def ensure_study(repo_root, parent=None):
    """The path of the study to work in, or None if the user backed out.

    A study already resolvable - LS_CONFIG, LS_STUDY, or the one last opened -
    is used without asking. Only a first run, or a settings file pointing at a
    study that has since been deleted, brings the picker up.
    """
    try:
        path = LC.resolve_path()
        if os.path.exists(path):
            return path
    except SystemExit:
        pass

    dlg = StudyPicker(repo_root, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    return dlg.chosen
