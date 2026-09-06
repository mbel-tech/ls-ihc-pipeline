"""Handles closed, sys.path not duplicated, and a real middle pick.

Run:  python tests/test_stale_state.py
"""

import contextlib
import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


before = sys.path.count(SCRIPTS)
M = load("m1", "00_manifest.py")
load("m2", "00_manifest.py")
chk("loading 00_manifest twice adds scripts/ to sys.path at most once",
    sys.path.count(SCRIPTS) - before <= 1, True)

tmp = tempfile.mkdtemp(prefix="src_")
try:
    with open(os.path.join(tmp, "loose.czi"), "wb") as fh:
        fh.write(b"L")
    with zipfile.ZipFile(os.path.join(tmp, "arch.zip"), "w") as z:
        z.writestr("inner.czi", b"Z")
        z.writestr("notes.txt", b"n")
    M.SOURCE_DIR = tmp
    M.CONFIG["source_files"] = None
    with contextlib.ExitStack() as stack:
        entries = M.discover_sources(stack)
        chk("loose file then zip member", [e[1] for e in entries], ["loose.czi", "inner.czi"])
        with entries[1][3]() as fh:
            chk("the member opens while the stack is live", fh.read(), b"Z")
    closed = ""
    try:
        entries[1][3]()
    except ValueError as exc:
        closed = "closed" in str(exc)
    chk("the archive is closed with the stack", closed, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

B = load("b", "01b_pick_sections.py")
chk("one file from three is the middle one", B.pick_files(["a", "b", "c"], 1), ["b"])
chk("one file from one is that one", B.pick_files(["a"], 1), ["a"])
chk("two from five straddle the middle", B.pick_files(["a", "b", "c", "d", "e"], 2), ["b", "d"])
chk("all from all is all", B.pick_files(["a", "b", "c"], 3), ["a", "b", "c"])

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
