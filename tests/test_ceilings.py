"""load_ceilings()/ceiling_for() in 01_overviews.py: the clip ceiling comes
from the manifest's clip_ceiling column, not a hardcoded 65535.

A temporary manifest directory stands in for OUT_ROOT/manifest, so this test
never reads or writes the real D:\\LS-analysis manifest.

Run:  python tests/test_ceilings.py
"""

import csv
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()

_spec = importlib.util.spec_from_file_location(
    "ov", os.path.join(SCRIPTS, "01_overviews.py"))
OV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OV)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {label:58} {'' if ok else f'{got!r} != {want!r}'}")
    if not ok:
        fails += 1


def write_manifest(tmpdir, header, rows):
    """Write <tmpdir>/manifest/manifest_files.csv and point OV.OUT_ROOT at tmpdir."""
    mdir = os.path.join(tmpdir, "manifest")
    os.makedirs(mdir, exist_ok=True)
    path = os.path.join(mdir, "manifest_files.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    OV.OUT_ROOT = tmpdir


# --- a manifest with clip_ceiling maps file -> int ---------------------------
with tempfile.TemporaryDirectory() as tmp:
    write_manifest(tmp, ["file", "clip_ceiling"],
                    [["LS105_1a.czi", "65535"], ["LS110_2b.czi", "65535"]])
    c = OV.load_ceilings()
    chk("file -> int mapping", c, {"LS105_1a.czi": 65535, "LS110_2b.czi": 65535})
    chk("known file returns its recorded ceiling", OV.ceiling_for(c, "LS105_1a.czi"), 65535)

    # --- a file absent from the mapping falls back to 65535 ------------------
    chk("unknown file falls back to 65535", OV.ceiling_for(c, "NOT_A_FILE.czi"), 65535)

# --- an empty mapping falls back to 65535 -------------------------------------
chk("empty mapping falls back to 65535", OV.ceiling_for({}, "anything.czi"), 65535)

# --- a manifest with no clip_ceiling column yields an empty mapping ----------
with tempfile.TemporaryDirectory() as tmp:
    write_manifest(tmp, ["file", "pixel_type"], [["LS105_1a.czi", "Gray16"]])
    c = OV.load_ceilings()
    chk("no clip_ceiling column -> empty mapping", c, {})
    chk("...and therefore the fallback", OV.ceiling_for(c, "LS105_1a.czi"), 65535)

# --- a blank or non-numeric clip_ceiling is skipped, not a crash -------------
with tempfile.TemporaryDirectory() as tmp:
    write_manifest(tmp, ["file", "clip_ceiling"],
                    [["LS105_1a.czi", ""], ["LS110_2b.czi", "not_a_number"],
                     ["LS120_1c.czi", "65535"]])
    c = OV.load_ceilings()
    chk("blank/non-numeric rows skipped, good row kept", c, {"LS120_1c.czi": 65535})

# --- a non-65535 ceiling is returned faithfully -------------------------------
# The case the whole task exists for: a synthetic 14-bit row. The real dataset
# cannot exercise this because every channel of every file in it is 16-bit.
with tempfile.TemporaryDirectory() as tmp:
    write_manifest(tmp, ["file", "clip_ceiling"], [["LS999_14bit.czi", "16383"]])
    c = OV.load_ceilings()
    chk("14-bit ceiling recorded faithfully", c, {"LS999_14bit.czi": 16383})
    chk("ceiling_for returns the 14-bit value, not 65535",
        OV.ceiling_for(c, "LS999_14bit.czi"), 16383)

# --- a missing manifest file entirely: no crash, empty mapping, warning path --
with tempfile.TemporaryDirectory() as tmp:
    OV.OUT_ROOT = tmp  # manifest/ subdirectory does not even exist
    c = OV.load_ceilings()
    chk("missing manifest file -> empty mapping", c, {})
    chk("...and therefore the fallback", OV.ceiling_for(c, "anything.czi"), 65535)

print()
print("FAILURES" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
