"""Plate identity: which set, which plate, and whether it is still that plate.

`verify()` is the whole point. A stored plate assignment that no longer matches
must come back as a NAMED outcome - resized, changed, gone - and never as a
silent success, because an id-keyed restore against a re-rendered atlas
succeeds and is wrong. That happened on this drive on 2026-09-06.

Run:  work/appenv/Scripts/python.exe tests/test_ls_atlas.py
"""

import csv
import hashlib
import os
import sys
import tempfile
import time

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

# Input order is the REVERSE of the expected text-sorted order, so a broken
# plate_order that just returned `rows` unchanged would fail this - unlike the
# previous version of this test, where the two happened to coincide.
mixed = [{"plate_id": "rostral"}, {"plate_id": "plate_1"}]
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
    # Pinned against an independently computed SHA-256, not against itself -
    # `def fingerprint(p): return ""` would pass "is stable" but fails this.
    chk("a fingerprint is the truncated SHA-256 of the bytes",
        A.fingerprint(a),
        hashlib.sha256(b"PLATE-A-BYTES").hexdigest()[:A.DIGEST_CHARS])
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

    # The id is IN plates.csv - fingerprints() still returns a row for it -
    # but the image is missing on disk, so fp is None. Distinct from "gone
    # because the id isn't in this set at all", but the same named outcome:
    # neither is something a person can act on without a plate to look at.
    gapped = {"plate_003": {"fp": None, "px_w": 5, "px_h": 6,
                            "image_file": "missing.png"}}
    chk("an id present in the set but with no image on disk -> gone",
        A.verify({"plate_id": "plate_003", "fp": "deadbeef0000"}, gapped), A.GONE)

    # An export written before `px` was recorded: the fingerprint differs and
    # there is nothing to check the aspect against, so the safe default is
    # CHANGED rather than assuming a resize.
    chk("fp differs and no stored px at all -> changed, not assumed resized",
        A.verify({"plate_id": "plate_001", "fp": fp_b}, current), A.CHANGED)

    # The aspect test is what separates a re-render from a re-crop, and 1% is
    # wide enough for a rounding difference and narrow enough to catch a crop.
    # 1000x2005 against the current 100x200 (ratio 0.5) is a 0.25% drift.
    chk("a 0.25% aspect drift still reads as a resize",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "1000x2005"}, current),
        A.RESIZED)
    # ASPECT_TOLERANCE itself, pinned: these two straddle it. Without these,
    # any tolerance from 0.25% to 74% passes the rest of this file unnoticed.
    chk("just inside ASPECT_TOLERANCE (0.79%) -> resized",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "1000x2016"}, current),
        A.RESIZED)
    chk("just outside ASPECT_TOLERANCE (2.44%) -> changed",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "1000x2050"}, current),
        A.CHANGED)

print()
print("--- scale_between(): the landmark rescale factor ---")
chk("rendered wider -> landmarks scale up",
    A.scale_between("100x200", {"px_w": 200, "px_h": 400}), 2.0)
chk("rendered narrower -> landmarks scale down",
    A.scale_between("200x400", {"px_w": 100, "px_h": 200}), 0.5)
chk("no stored px -> no factor",
    A.scale_between(None, {"px_w": 100, "px_h": 200}), None)
chk("no current row -> no factor",
    A.scale_between("100x200", None), None)
chk("current row with no px_w -> no factor",
    A.scale_between("100x200", {"px_w": 0, "px_h": 200}), None)

print()
print("--- fingerprints(): plates.csv, the cache, and the missing-image gap ---")
with tempfile.TemporaryDirectory() as tmp2:
    def write_plate(name, data):
        with open(os.path.join(tmp2, name), "wb") as fh:
            fh.write(data)

    write_plate("p1.png", b"PLATE-ONE")
    write_plate("p2.png", b"PLATE-TWO")
    with open(os.path.join(tmp2, "plates.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["plate_id", "image_file", "px_w", "px_h"])
        w.writerow(["plate_001", "p1.png", "10", "20"])
        w.writerow(["plate_002", "p2.png", "30", "40"])
        w.writerow(["plate_003", "gone.png", "5", "6"])

    fps1 = A.fingerprints(tmp2)
    chk("plates.csv is read when rows is not given",
        sorted(fps1), ["plate_001", "plate_002", "plate_003"])
    chk("a present image gets a real fingerprint",
        fps1["plate_001"]["fp"] is not None, True)
    chk("...and carries its declared shape",
        (fps1["plate_002"]["px_w"], fps1["plate_002"]["px_h"]), (30, 40))
    # THE invariant Task 3 depends on: a plate whose image is missing keeps
    # its place in the dict, with fp None, rather than being dropped - dropping
    # it is exactly what shifted every later index under the old array scheme.
    chk("a missing image keeps its row, with fp None",
        fps1["plate_003"],
        {"fp": None, "image_file": "gone.png", "px_w": 5, "px_h": 6})
    chk("the cache file is written",
        os.path.exists(os.path.join(tmp2, A.CACHE_NAME)), True)

    # Reused when nothing moved: fingerprint() must not be called again.
    real_fingerprint = A.fingerprint
    calls = []

    def counting(path):
        calls.append(path)
        return real_fingerprint(path)

    A.fingerprint = counting
    try:
        fps2 = A.fingerprints(tmp2)
    finally:
        A.fingerprint = real_fingerprint
    chk("nothing moved -> the cache is reused, nothing is re-hashed", calls, [])
    chk("...and the answer is unchanged", fps2, fps1)

    # Replace one image's bytes (same name, same declared shape). The cache
    # key is (size, mtime_ns); sleeping first guarantees a moved mtime even at
    # this filesystem's finest resolution.
    time.sleep(0.01)
    write_plate("p1.png", b"PLATE-ONE-REPLACED-CONTENT")
    calls = []
    A.fingerprint = counting
    try:
        fps3 = A.fingerprints(tmp2)
    finally:
        A.fingerprint = real_fingerprint
    chk("a replaced file is re-hashed",
        os.path.join(tmp2, "p1.png") in calls, True)
    chk("...and its fingerprint actually changed",
        fps3["plate_001"]["fp"] != fps1["plate_001"]["fp"], True)
    chk("...while the untouched plate was not re-hashed",
        os.path.join(tmp2, "p2.png") in calls, False)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
