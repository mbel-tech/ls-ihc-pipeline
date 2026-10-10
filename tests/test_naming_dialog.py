"""The pattern builder as a window, driven without one.

naming_build.py is tested on its own; this is the wiring around it - that
marking a span really does regenerate the pattern, that Save is disabled while
a file does not match, and that the settings dialog can reach the slides folder
it needs to preview against.

Runs offscreen, so it needs no display. Skipped rather than failed when PySide6
is not installed, since the pipeline's stages do not need it.

Run:  python tests/test_naming_dialog.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

try:
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
except ImportError:
    print("SKIP PySide6 is not installed - the stages do not need it")
    sys.exit(0)

from _fixture import use_temp_study                         # noqa: E402

STUDY = use_temp_study()

import naming_build as B                                    # noqa: E402
from naming_dialog import NamingDialog, scan_names          # noqa: E402
from config_dialog import ConfigDialog                      # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 90 else f"<{type(got).__name__}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:58} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


app = QApplication.instance() or QApplication([])
NAMES = ["LS105_10a.czi", "LS105_1b.czi", "LS22_3a.czi", "notes.txt"]

# --------------------------------------------------------------------------
print("--- marking spans builds the pattern ---")

dlg = NamingDialog(NAMES)
chk("the first scanned name is the example",
    dlg.example.currentText(), "LS105_10a.czi")
chk("with nothing marked there is nothing to save",
    dlg.buttons.button(QDialogButtonBox.Save).isEnabled(), False)

dlg.spans = [B.Span(0, 5, "subject"), B.Span(6, 8, "slide"),
             B.Span(8, 9, "replicate")]
dlg._rebuild()
chk("marking spans fills the pattern box",
    dlg.regex.text(),
    r"^(?P<subject>[A-Za-z]+\d+)_(?P<slide>\d+)(?P<replicate>[A-Za-z]+)\.czi$")
chk("the chips list what was marked", dlg.chips.count(), 3)

# --------------------------------------------------------------------------
print()
print("--- a file the pattern misses blocks Save ---")

chk("the count is on screen", "3 of 4 matched" in dlg.status.text(), True)
chk("...and so is the consequence",
    "never reaches any stage" in dlg.status.text(), True)
chk("Save is disabled", dlg.buttons.button(QDialogButtonBox.Save).isEnabled(),
    False)
chk("the failure is the first row shown", dlg.table.item(0, 0).text(),
    "notes.txt")
chk("...and says why", dlg.table.item(0, 1).text(), "no match")

dlg.accept_bad.setChecked(True)
chk("leaving it out deliberately enables Save",
    dlg.buttons.button(QDialogButtonBox.Save).isEnabled(), True)

dlg._save()
chk("the saved block carries the example and the case rule too",
    sorted(dlg.result_block), ["case_insensitive", "example", "pattern"])
chk("...and the example is the one that was marked up",
    dlg.result_block["example"], "LS105_10a.czi")

# --------------------------------------------------------------------------
print()
print("--- editing the regex by hand is still the escape hatch ---")

dlg2 = NamingDialog(NAMES)
dlg2.regex.setText(r"^(?P<subject>[A-Za-z]+\d+)_(?P<slide>\d+)"
                   r"(?P<replicate>[a-z])\.czi$")
dlg2._recheck()
chk("a hand-typed pattern is previewed the same way",
    "3 of 4 matched" in dlg2.status.text(), True)

dlg2.regex.setText(r"^(?P<nope>.+)$")
dlg2._recheck()
chk("one with no subject group cannot be saved",
    dlg2.buttons.button(QDialogButtonBox.Save).isEnabled(), False)
chk("...and says why", "joins on" in dlg2.status.text(), True)

# --------------------------------------------------------------------------
print()
print("--- the settings dialog, generated from the spec ---")

cfg = ConfigDialog(REPO, path=STUDY.path)
chk("it offers every key the spec marks editable",
    len(cfg.rows), len(__import__("ls_config").dialog_fields()))
chk("the pattern gets the builder row", hasattr(cfg, "pattern_row"), True)
chk("which can reach the slides folder it previews against",
    cfg.pattern_row.source_getter(), STUDY.source_dir)
chk("required keys are marked as such in the form",
    any(k.required for k, _ in cfg.rows.values()), True)

# scan_names is what feeds the builder from that folder.
open(os.path.join(STUDY.source_dir, "AB1_2c.czi"), "wb").close()
chk("scan_names reads the folder", scan_names(STUDY.source_dir), ["AB1_2c.czi"])
chk("...and a folder that is not there is empty, not an error",
    scan_names(os.path.join(STUDY.root, "nope")), [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
