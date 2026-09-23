"""Plate identity: which set, which plate, and whether it is still that plate.

`verify()` is the whole point. A stored plate assignment that no longer matches
must come back as a NAMED outcome - resized, changed, gone - and never as a
silent success, because an id-keyed restore against a re-rendered atlas
succeeds and is wrong. That happened on this drive on 2026-09-06.

Run:  work/appenv/Scripts/python.exe tests/test_ls_atlas.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_atlas as A                                          # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


# --- which set ------------------------------------------------------------
chk("the configured set is used",
    A.set_dir({"atlas_plate_set": {"dir": "plates_final"}}), "plates_final")
chk("a config that says nothing gets the extraction set",
    A.set_dir({}), A.EXTRACTED)
chk("a malformed block is judged, not crashed on",
    A.set_dir({"atlas_plate_set": "plates_final"}), A.EXTRACTED)
chk("plate_dir joins out_root/atlas/<set>",
    A.plate_dir({"out_root": os.path.join("X:", "s"),
                 "atlas_plate_set": {"dir": "plates_final"}}),
    os.path.join("X:", "s", "atlas", "plates_final"))
chk("...and can be asked for a different set by name",
    A.plate_dir({"out_root": os.path.join("X:", "s")}, set_name="plates_merged"),
    os.path.join("X:", "s", "atlas", "plates_merged"))


# --- ordering -------------------------------------------------------------
# The live atlas zero-pads to three digits, so a string sort happens to work.
# An atlas that does not pad scrambles under one, silently.
padded = [{"plate_id": "plate_%03d" % n} for n in (3, 1, 2)]
chk("padded ids order numerically",
    [r["plate_id"] for r in A.plate_order(padded)],
    ["plate_001", "plate_002", "plate_003"])

bare = [{"plate_id": "plate_%d" % n} for n in (2, 10, 1, 100)]
chk("UNPADDED ids order numerically too",
    [r["plate_id"] for r in A.plate_order(bare)],
    ["plate_1", "plate_2", "plate_10", "plate_100"])

words = [{"plate_id": x} for x in ("caudal", "atlas_b", "atlas_a")]
chk("ids with no number order as text, deterministically",
    [r["plate_id"] for r in A.plate_order(words)],
    ["atlas_a", "atlas_b", "caudal"])

mixed = [{"plate_id": "plate_1"}, {"plate_id": "rostral"}]
chk("a mixed set falls back to text rather than guessing",
    [r["plate_id"] for r in A.plate_order(mixed)], ["plate_1", "rostral"])


# --- fingerprints and verify ----------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    def plate(name, data):
        path = os.path.join(tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    a = plate("a.png", b"PLATE-A-BYTES")
    b = plate("b.png", b"PLATE-B-BYTES")
    chk("a fingerprint is stable", A.fingerprint(a), A.fingerprint(a))
    chk("...and different content gives a different one",
        A.fingerprint(a) == A.fingerprint(b), False)
    chk("a file that is not there has no fingerprint",
        A.fingerprint(os.path.join(tmp, "nope.png")), None)

    fp_a, fp_b = A.fingerprint(a), A.fingerprint(b)
    current = {"plate_001": {"fp": fp_a, "px_w": 100, "px_h": 200},
               "plate_002": {"fp": fp_b, "px_w": 100, "px_h": 200}}

    chk("same id, same bytes -> ok",
        A.verify({"plate_id": "plate_001", "fp": fp_a}, current), A.OK)
    chk("same id, new bytes, same shape -> resized",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "50x100"}, current),
        A.RESIZED)
    chk("same id, new bytes, new shape -> changed",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "50x400"}, current),
        A.CHANGED)
    chk("an id the set does not have -> gone",
        A.verify({"plate_id": "plate_099", "fp": fp_a}, current), A.GONE)
    chk("an id with no stored fingerprint is UNCHECKED, not ok",
        A.verify({"plate_id": "plate_001"}, current), A.UNCHECKED)
    chk("...and an id this set does not have is still gone",
        A.verify({"plate_id": "plate_099"}, current), A.GONE)
    chk("no id at all restores by index",
        A.verify({}, current), A.BY_INDEX)

    # The aspect test is what separates a re-render from a re-crop, and 1% is
    # wide enough for a rounding difference and narrow enough to catch a crop.
    chk("a 0.5% aspect drift still reads as a resize",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "1000x2005"}, current),
        A.RESIZED)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
