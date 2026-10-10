"""Marking up one filename to get the grammar for all of them.

The operator selects a run of characters in a real filename and says what it
is. Everything they did not mark is escaped literally, so the pattern can never
be looser than the example - and the generated regex stays editable, because
some naming schemes have exceptions no marking-up will cover.

The preview underneath is the point of the screen, not decoration. A file the
pattern misses never reaches any stage and nothing else in the pipeline says
so, so the count of what did not match is always on screen, the failures are
listed first, and Save is disabled until they are either fixed or deliberately
accepted.

The logic lives in `naming_build.py`, which has no Qt in it and is tested
without a window.
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

import naming_build as B

MONO = "Consolas, Menlo, monospace"


class NamingDialog(QDialog):
    """Build a slide_naming block from a list of real filenames."""

    def __init__(self, filenames, current=None, parent=None):
        super().__init__(parent)
        self.filenames = [os.path.basename(f) for f in filenames]
        self.spans = []
        self.result_block = None
        self.setWindowTitle("Filename pattern")
        self.resize(860, 700)

        self.example = QComboBox()
        self.example.addItems(self.filenames or ["<no files scanned>"])
        self.example.currentIndexChanged.connect(self._example_changed)

        self.strip = QLineEdit(self.filenames[0] if self.filenames else "")
        self.strip.setReadOnly(True)
        self.strip.setFont(QFont(MONO, 13))
        self.strip.setToolTip("Select part of the name, then say what it is.")

        marks = QHBoxLayout()
        for role in ("subject", "slide", "replicate"):
            btn = QPushButton(f"Mark as {role}")
            btn.clicked.connect(lambda _=False, r=role: self._mark(r))
            marks.addWidget(btn)
        other = QPushButton("Mark as…")
        other.clicked.connect(self._mark_other)
        marks.addWidget(other)
        clear = QPushButton("Clear marks")
        clear.clicked.connect(self._clear)
        marks.addWidget(clear)
        marks.addStretch(1)

        self.chips = QListWidget()
        self.chips.setMaximumHeight(90)

        self.case = QCheckBox("Match filenames case-insensitively")
        self.case.stateChanged.connect(self._rebuild)

        self.regex = QLineEdit(current or "")
        self.regex.setFont(QFont(MONO, 11))
        self.regex.textEdited.connect(self._recheck)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["File", "", "subject", "slide", "replicate"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 90)

        self.accept_bad = QCheckBox(
            "Leave the files that do not match out of this study")
        self.accept_bad.stateChanged.connect(self._recheck)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save
                                        | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Example filename"))
        lay.addWidget(self.example)
        lay.addWidget(self.strip)
        lay.addLayout(marks)
        lay.addWidget(self.chips)
        lay.addWidget(self.case)
        lay.addWidget(QLabel("Pattern (edit it directly if you prefer)"))
        lay.addWidget(self.regex)
        lay.addWidget(self.status)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.accept_bad)
        lay.addWidget(self.buttons)

        self._recheck() if current else self._rebuild()

    # ------------------------------------------------------------------ marks
    def _example_text(self):
        return self.strip.text()

    def _example_changed(self):
        self.strip.setText(self.example.currentText())
        self._clear()

    def _selection(self):
        start = self.strip.selectionStart()
        text = self.strip.selectedText()
        if start < 0 or not text:
            return None
        return start, start + len(text)

    def _mark(self, role):
        sel = self._selection()
        if sel is None:
            self.status.setText("Select part of the filename first.")
            return
        start, end = sel
        # One span per position and one subject per pattern: re-marking
        # replaces rather than stacking, which is what a second click means.
        self.spans = [s for s in self.spans
                      if s.end <= start or s.start >= end]
        self.spans = [s for s in self.spans if s.name != role]
        self.spans.append(B.Span(start, end, role))
        self._rebuild()

    def _mark_other(self):
        name, ok = QInputDialog.getText(
            self, "Mark as", "Name for this part (it becomes a column):")
        name = (name or "").strip()
        if not ok or not name:
            return
        if not name.isidentifier():
            self.status.setText(f"{name!r} is not usable as a group name.")
            return
        self._mark(name)

    def _clear(self):
        self.spans = []
        self._rebuild()

    # --------------------------------------------------------------- building
    def _block(self, reason):
        """Nothing savable yet. Say why, and make Save unclickable.

        Every path that leaves the dialog without a usable pattern must come
        through here: the button starts life enabled, so an early return that
        only set a message would leave Save live with nothing behind it.
        """
        self.status.setText(reason)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self._render(None)

    def _rebuild(self):
        self.chips.clear()
        for s in sorted(self.spans, key=lambda s: s.start):
            self.chips.addItem(
                f"{s.name}: {s.text(self._example_text())!r} "
                f"({s.start}–{s.end})")
        if not self.spans:
            self._block("Select part of the filename and mark it. "
                        "The subject is required.")
            return
        try:
            pattern, warnings = B.spans_to_pattern(
                self._example_text(), self.spans, self.case.isChecked())
        except ValueError as exc:
            self._block(str(exc))
            return
        self.regex.setText(pattern)
        self._recheck(extra=warnings)

    def _recheck(self, *_args, extra=()):
        pattern = self.regex.text().strip()
        if not pattern:
            self._block("No pattern yet.")
            return
        result = B.preview(self.filenames, pattern, self.case.isChecked())
        ok, reason = B.can_save(result, self.accept_bad.isChecked())
        lines = [B.summary(result)]
        lines += list(extra)
        if not ok:
            lines.append(reason)
        self.status.setText("\n".join(lines))
        self.buttons.button(QDialogButtonBox.Save).setEnabled(ok)
        self._render(result)

    def _render(self, result):
        rows = (result or {}).get("rows", [])
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            cells = [row["file"],
                     "ok" if row["ok"] else (row.get("why") or "no match"),
                     row.get("subject", ""), row.get("slide", ""),
                     row.get("replicate", "")]
            for j, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, j, item)

    # ----------------------------------------------------------------- saving
    def _save(self):
        self.result_block = {
            "pattern": self.regex.text().strip(),
            "example": self._example_text(),
            "case_insensitive": self.case.isChecked(),
        }
        self.accept()


def scan_names(source_dir, limit=5000):
    """The filenames in a folder, for previewing a pattern against."""
    try:
        names = sorted(f for f in os.listdir(source_dir)
                       if os.path.isfile(os.path.join(source_dir, f)))
    except OSError:
        return []
    return names[:limit]
