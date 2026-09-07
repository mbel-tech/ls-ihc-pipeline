"""The settings of one study, offered from the spec that defines them.

This used to carry three hand-written entries - the slides folder, the output
root and the atlas - with a comment saying everything else had a working
default. Several of those defaults were not settings anyone had chosen; they
were whatever the code fell back to.

The fields now come from `ls_config.SPEC`, so a key added there appears here
without anyone remembering to edit a second list, its hint is the same sentence
the validator uses when it rejects a value, and the dialog cannot offer a key
the pipeline does not read.
"""

import json
import os

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget)

import ls_config as LC


class _PathRow(QWidget):
    """A line edit with a Browse button, for the three path kinds."""

    def __init__(self, kind, value, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.edit = QLineEdit("" if value is None else str(value))
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def _browse(self):
        if self.kind == "file":
            p, _ = QFileDialog.getOpenFileName(self, "Choose file",
                                               self.edit.text(),
                                               "All files (*)")
        else:
            p = QFileDialog.getExistingDirectory(self, "Choose folder",
                                                 self.edit.text())
        if p:
            self.edit.setText(p)

    def value(self):
        return self.edit.text().strip()


class _PatternRow(QWidget):
    """The filename pattern, with the builder behind a button.

    The builder needs real filenames to preview against, which is why it is
    offered here rather than as a bare text box: the folder is one field above.
    """

    def __init__(self, value, source_getter, parent=None):
        super().__init__(parent)
        self.source_getter = source_getter
        self.edit = QLineEdit("" if value is None else str(value))
        btn = QPushButton("Build…")
        btn.clicked.connect(self._build)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def _build(self):
        from naming_dialog import NamingDialog, scan_names
        names = scan_names(self.source_getter() or "")
        if not names:
            QMessageBox.warning(
                self, "No files",
                "Set the slides folder first - the pattern is checked against "
                "the filenames that are actually there.")
            return
        dlg = NamingDialog(names, self.edit.text().strip(), self)
        if dlg.exec() == QDialog.Accepted and dlg.result_block:
            self.edit.setText(dlg.result_block["pattern"])
            self.built = dlg.result_block

    def value(self):
        return self.edit.text().strip() or None


def _widget_for(key, value):
    """The editor for one spec key, and a callable giving its typed value."""
    if key.ui in ("dir", "file", "outdir"):
        row = _PathRow(key.ui, value)
        return row, row.value
    if key.ui == "bool":
        box = QCheckBox()
        box.setChecked(bool(value))
        return box, box.isChecked
    if key.ui == "choice":
        combo = QComboBox()
        combo.addItems(list(key.choices or []))
        if value in (key.choices or []):
            combo.setCurrentText(value)
        return combo, combo.currentText
    edit = QLineEdit("" if value is None else str(value))

    if key.ui in ("number", "int"):
        def typed():
            text = edit.text().strip()
            if not text:
                return None
            try:
                return int(text) if key.ui == "int" else float(text)
            except ValueError:
                # Handed back as written, so validate() reports it against the
                # key's own doc rather than this dialog inventing a message.
                return text
        return edit, typed

    return edit, lambda: (edit.text().strip() or None)


class ConfigDialog(QDialog):
    """Edit one study's config. `path` names it; default is the active one."""

    def __init__(self, repo_root, path=None, study_name=None, parent=None):
        super().__init__(parent)
        self.repo_root = repo_root
        self.path = os.path.abspath(path or LC.resolve_path())
        self.study_name = study_name
        self.setWindowTitle(f"Settings — {os.path.basename(self.path)}")
        self.resize(760, 620)

        cfg = self._load()
        if study_name:
            cfg.setdefault("study", {})["name"] = study_name

        form = QFormLayout()
        self.rows = {}
        for key in LC.dialog_fields():
            found, value = LC._get(cfg, key.parts)
            if key.path == "slide_naming.pattern":
                widget = _PatternRow(
                    value if found else key.default,
                    lambda: self.rows["source_dir"][1]())
                getter = widget.value
                self.pattern_row = widget
            else:
                widget, getter = _widget_for(key, value if found else key.default)
            self.rows[key.path] = (key, getter)
            form.addRow(key.label + ("  *" if key.required else ""), widget)
            hint = QLabel(key.doc)
            hint.setStyleSheet("color:#9aa0a8;font-size:11px")
            hint.setWordWrap(True)
            form.addRow("", hint)

        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Save
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        note = QLabel(f"Writing to {self.path}")
        note.setStyleSheet("color:#9aa0a8;font-size:11px")
        note.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addWidget(scroll, 1)
        lay.addWidget(note)
        lay.addWidget(buttons)

    def _load(self):
        """The study being edited, or the template for one that is new."""
        for candidate in (self.path,
                          os.path.join(self.repo_root, "config.example.json")):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                continue
        return {}

    def _save(self):
        """Validate before writing.

        A wrong value written here surfaces much later, inside a stage, as a
        message about a missing file rather than a wrong setting. This is the
        one place the user can act on it, so paths must exist HERE even though
        they only warn everywhere else.
        """
        cfg = self._load()
        for path, (key, getter) in self.rows.items():
            value = getter()
            if value is None and not key.required:
                # An optional key left blank is absent, not empty - export_dir
                # blank has to mean "derive it", not "write to ''".
                node, parts = cfg, key.parts
                for part in parts[:-1]:
                    node = node.get(part) if isinstance(node, dict) else None
                    if node is None:
                        break
                if isinstance(node, dict):
                    node.pop(parts[-1], None)
                continue
            LC._set(cfg, key.parts, value)

        built = getattr(getattr(self, "pattern_row", None), "built", None)
        if built:
            # The builder settled the example and the case rule too; saving
            # only the regex would leave the other two describing a pattern
            # that is no longer there.
            LC._set(cfg, ["slide_naming", "example"], built["example"])
            LC._set(cfg, ["slide_naming", "case_insensitive"],
                    built["case_insensitive"])

        errors, _ = LC.validate(cfg, self.path, strict_paths=True)
        if errors:
            QMessageBox.warning(self, "Not saved yet",
                                "\n\n".join(errors[:6]))
            return

        cfg = LC.apply_defaults(cfg)
        out_root = cfg.get("out_root")
        if out_root:
            os.makedirs(out_root, exist_ok=True)

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, self.path)
        LC.clear_cache()
        self.accept()
