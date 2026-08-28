"""First-run setup: the three paths everything else is derived from.

`config.example.json` is the template, so the keys and their comments stay in one
place and a new setting added there appears here without editing this file.
"""

import json
import os
import shutil

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

# The three the user must supply. Everything else in config has a working
# default and is left alone.
FIELDS = [
    ("source_dir", "Slides folder", "dir",
     "The folder holding the .czi files."),
    ("out_root", "Analysis output", "dir",
     "Where every result is written. Needs room - overviews alone run to "
     "several GB."),
    ("atlas_pdf", "Atlas PDF", "file",
     "The salmon atlas the plates and region seeds are extracted from."),
]


class _PathRow(QWidget):
    def __init__(self, kind, value, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.edit = QLineEdit(value or "")
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def _browse(self):
        if self.kind == "dir":
            p = QFileDialog.getExistingDirectory(self, "Choose folder", self.edit.text())
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose file", self.edit.text(),
                                               "PDF (*.pdf);;All files (*)")
        if p:
            self.edit.setText(p)

    def value(self):
        return self.edit.text().strip()


class ConfigDialog(QDialog):
    def __init__(self, repo_root, parent=None):
        super().__init__(parent)
        self.repo_root = repo_root
        self.path = os.path.join(repo_root, "config.json")
        self.example = os.path.join(repo_root, "config.example.json")
        self.setWindowTitle("Pipeline settings")
        self.resize(720, 260)

        cfg = self._load()
        form = QFormLayout()
        self.rows = {}
        for key, label, kind, help_text in FIELDS:
            row = _PathRow(kind, cfg.get(key, ""))
            self.rows[key] = row
            form.addRow(label, row)
            hint = QLabel(help_text)
            hint.setStyleSheet("color:#9aa0a8;font-size:11px")
            hint.setWordWrap(True)
            form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _load(self):
        for p in (self.path, self.example):
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    return json.load(fh)
        return {}

    def _save(self):
        """Validate before writing - a wrong path here fails much later, in a
        stage, with a message about a missing file rather than a wrong setting."""
        values = {k: r.value() for k, r in self.rows.items()}
        for key, label, kind, _ in FIELDS:
            v = values[key]
            if not v:
                QMessageBox.warning(self, "Missing", f"{label} is required.")
                return
            if key == "out_root":
                continue                      # created on demand if absent
            exists = os.path.isdir(v) if kind == "dir" else os.path.isfile(v)
            if not exists:
                QMessageBox.warning(self, "Not found", f"{label} does not exist:\n{v}")
                return

        if not os.path.exists(self.path) and os.path.exists(self.example):
            shutil.copy2(self.example, self.path)
        cfg = self._load()
        cfg.update(values)
        os.makedirs(values["out_root"], exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        os.replace(tmp, self.path)
        self.accept()


def ensure_config(repo_root, parent=None):
    """Return True when a usable config.json exists, asking for one if not."""
    path = os.path.join(repo_root, "config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            if all(cfg.get(k) for k, *_ in FIELDS):
                return True
        except (OSError, json.JSONDecodeError):
            pass
    return ConfigDialog(repo_root, parent).exec() == QDialog.Accepted
