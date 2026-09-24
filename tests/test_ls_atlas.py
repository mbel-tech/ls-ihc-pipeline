"""Plate identity: which set, which plate, and whether it is still that plate.

`plate_status()` is the whole point. A stored plate assignment that no longer
matches must come back as a NAMED outcome - resized, changed, gone - and never
as a silent success, because an id-keyed restore against a re-rendered atlas
succeeds and is wrong. That happened on this drive on 2026-09-06.

Run:  work/appenv/Scripts/python.exe tests/test_ls_atlas.py
"""

import csv
import hashlib
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


def write_file(path, data):
    """The one place a temp plate image gets written, in this whole suite."""
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def write_plates_csv(directory, rows, columns=("plate_id", "image_file",
                                               "px_w", "px_h")):
    with open(os.path.join(directory, "plates.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        w.writerows(rows)


# --- which set ------------------------------------------------------------
chk("the configured set is used",
    A.set_name({"atlas_plate_set": {"dir": "plates_final"}}), "plates_final")
chk("a config that says nothing gets the extraction set",
    A.set_name({}), A.EXTRACTED)
chk("a malformed block is judged, not crashed on",
    A.set_name({"atlas_plate_set": "plates_final"}), A.EXTRACTED)
chk("plate_dir joins out_root/atlas/<set>",
    A.plate_dir({"out_root": os.path.join("X:", "s"),
                 "atlas_plate_set": {"dir": "plates_final"}}),
    os.path.join("X:", "s", "atlas", "plates_final"))
chk("...and can be asked for a different set by name",
    A.plate_dir({"out_root": os.path.join("X:", "s")}, set_name="plates_merged"),
    os.path.join("X:", "s", "atlas", "plates_merged"))
chk("...and still falls back to the study's own set with no override",
    A.plate_dir({"out_root": os.path.join("X:", "s"),
                 "atlas_plate_set": {"dir": "plates_final"}}),
    os.path.join("X:", "s", "atlas", "plates_final"))


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
# plate_order that just returned `rows` unchanged would fail this.
mixed = [{"plate_id": "rostral"}, {"plate_id": "plate_1"}]
chk("a mixed set falls back to text rather than guessing",
    [r["plate_id"] for r in A.plate_order(mixed)], ["plate_1", "rostral"])

# Two ids that share a trailing number are exactly as ambiguous as having no
# number at all - "plate_01" and "plate_1" both trail with "1" - so this must
# fall back to text too rather than picking one arbitrarily. Input order is
# again the reverse of the expected text order.
shared_trailing = [{"plate_id": "plate_1"}, {"plate_id": "plate_01"}]
chk("two ids sharing a trailing number fall back to text",
    [r["plate_id"] for r in A.plate_order(shared_trailing)],
    ["plate_01", "plate_1"])


# --- fingerprints() and plate_status() -------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    a = write_file(os.path.join(tmp, "a.png"), b"PLATE-A-BYTES")
    b = write_file(os.path.join(tmp, "b.png"), b"PLATE-B-BYTES")
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
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_a}, current),
        A.OK)
    chk("...and verified() agrees",
        A.verified(A.plate_status(
            {"plate_id": "plate_001", "plate_fp": fp_a}, current)), True)
    chk("same id, new bytes, same shape -> resized",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "50x100"}, current),
        A.RESIZED)
    chk("...and verified() says no - a rescale still needs the transform gate",
        A.verified(A.RESIZED), False)
    chk("same id, new bytes, new shape -> changed",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "50x400"}, current),
        A.CHANGED)
    chk("an id the set does not have -> gone",
        A.plate_status({"plate_id": "plate_099", "plate_fp": fp_a}, current),
        A.GONE)
    chk("an id with no stored fingerprint is UNCHECKED, not ok",
        A.plate_status({"plate_id": "plate_001"}, current), A.UNCHECKED)
    chk("...and an id this set does not have is still gone",
        A.plate_status({"plate_id": "plate_099"}, current), A.GONE)
    chk("no id at all restores by index",
        A.plate_status({}, current), A.BY_INDEX)
    chk("verified() is false for every non-OK outcome",
        [A.verified(o) for o in A.OUTCOMES if o != A.OK], [False] * 5)

    # The id is IN plates.csv - fingerprints() still returns a row for it -
    # but the image is missing on disk, so fp is None. Distinct from "gone
    # because the id isn't in this set at all", but the same named outcome:
    # neither is something a person can act on without a plate to look at.
    gapped = {"plate_003": {"fp": None, "px_w": 5, "px_h": 6,
                            "image_file": "missing.png"}}
    chk("an id present in the set but with no image on disk -> gone",
        A.plate_status({"plate_id": "plate_003", "plate_fp": "deadbeef0000"},
                       gapped), A.GONE)

    # An export written before `plate_px` was recorded: the fingerprint
    # differs and there is nothing to check the aspect against, so the safe
    # default is CHANGED rather than assuming a resize.
    chk("fp differs and no stored px at all -> changed, not assumed resized",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b}, current),
        A.CHANGED)

    # The aspect test is what separates a re-render from a re-crop, and 1% is
    # wide enough for a rounding difference and narrow enough to catch a crop.
    # 1000x2005 against the current 100x200 (ratio 0.5) is a 0.25% drift.
    chk("a 0.25% aspect drift still reads as a resize",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "1000x2005"}, current),
        A.RESIZED)
    # ASPECT_TOLERANCE itself, pinned: these two straddle it. Without these,
    # any tolerance from 0.25% to 74% passes the rest of this file unnoticed.
    chk("just inside ASPECT_TOLERANCE (0.79%) -> resized",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "1000x2016"}, current),
        A.RESIZED)
    chk("just outside ASPECT_TOLERANCE (2.44%) -> changed",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "1000x2050"}, current),
        A.CHANGED)

    # _shape's grammar, pinned against what the JS side accepts: integers,
    # lowercase x, nothing else. A float or an uppercase X must NOT parse -
    # the page's regex would reject them and fall through to CHANGED, so a
    # Python side that accepted them would read RESIZED for the same string.
    chk("a float-formatted px string does not parse as a shape",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "1000.0x2005.0"}, current),
        A.CHANGED)
    chk("an uppercase X does not parse as a shape either",
        A.plate_status({"plate_id": "plate_001", "plate_fp": fp_b,
                        "plate_px": "1000X2005"}, current),
        A.CHANGED)

print()
print("--- scale_between(): the landmark rescale factor, per axis ---")
chk("rendered wider -> both axes scale up",
    A.scale_between("100x200", {"px_w": 200, "px_h": 400}), (2.0, 2.0))
chk("rendered narrower -> both axes scale down",
    A.scale_between("200x400", {"px_w": 100, "px_h": 200}), (0.5, 0.5))
# An aspect-drifted RESIZED plate - width and height must NOT share one factor,
# since RESIZED tolerates exactly this kind of per-axis drift.
sx, sy = A.scale_between("1000x2000", {"px_w": 1010, "px_h": 2030})
chk("an aspect-drifted resize scales each axis by its OWN factor, not one",
    (round(sx, 6), round(sy, 6)), (1.01, 1.015))
chk("no stored px -> no factor",
    A.scale_between(None, {"px_w": 100, "px_h": 200}), None)
chk("no current row -> no factor",
    A.scale_between("100x200", None), None)
chk("current row with no px_w -> no factor",
    A.scale_between("100x200", {"px_w": 0, "px_h": 200}), None)
chk("current row with no px_h -> no factor",
    A.scale_between("100x200", {"px_w": 100, "px_h": 0}), None)

print()
print("--- restore_plate(): the one rule both importers restore through ---")
# 04q_import_curation and app/import_exports are mirrors. The last time one was
# fixed and the other was not, every ROI of one marker landed at a third of its
# true position for weeks. This is the rule they now share, so this is where it
# is pinned - a reintroduction in one importer alone shows up as that importer
# no longer calling this.
DISAGREE = {"plate_id": "plate_010", "plate_index": "9",
            "plate_fp": "aaaaaaaaaaaa", "plate_px": "100x200",
            "plate_verified": "ok"}
r = A.restore_plate(DISAGREE, 9)
chk("the id is carried, whatever the index said", r["plate_id"], "plate_010")
chk("...and the index is kept as the record it is", r["plate"], 9)
chk("...with the identity it was assigned against",
    (r["plate_fp"], r["plate_px"]), ("aaaaaaaaaaaa", "100x200"))

# THE COLUMN IS PREFERRED, NOT RECOMPUTED. A by_index row has a blank plate_fp
# BY DESIGN - the id names the plate at the stored index and nothing was ever
# fingerprinted - so recomputing from the row answers "unchecked" over a column
# that says "by_index", which is a vaguer statement standing in for a true one.
chk("a by_index row stays by_index rather than being recomputed",
    A.restore_plate({"plate_id": "plate_010", "plate_verified": "by_index"},
                    9)["verified"], A.BY_INDEX)
# The same the other way: a verdict that something MOVED is the only evidence
# of it that the CSV carries, and these importers have no atlas to re-reach it
# with.
for verdict in (A.CHANGED, A.RESIZED, A.GONE):
    chk(f"a {verdict} row keeps its verdict, not a fresh guess",
        A.restore_plate({"plate_id": "plate_010", "plate_fp": "aaaaaaaaaaaa",
                         "plate_px": "100x200", "plate_verified": verdict},
                        9)["verified"], verdict)

# An export written before the column existed - no plate_verified key at all -
# still imports exactly as it did, and cannot come back OK either way.
chk("a pre-fingerprint export with an id restores unchecked",
    A.restore_plate({"plate_id": "plate_010", "plate_index": "9"},
                    9)["verified"], A.UNCHECKED)
chk("...and one with no id at all restores by_index",
    A.restore_plate({"plate_index": "9"}, 9)["verified"], A.BY_INDEX)
chk("a blank cell is read the same as no column",
    A.restore_plate({"plate_id": "plate_010", "plate_verified": ""},
                    9)["verified"], A.UNCHECKED)
# A verdict is a statement ABOUT an id. With no id it names nothing, and
# carrying it would be a false OK reached by hand-editing a CSV - while
# plate_status and the page's verifyPlate both answer by_index there without
# reading anything else.
chk("a row that named no plate is by_index whatever the cell claims",
    A.restore_plate({"plate_id": "", "plate_verified": "ok"}, 0)["verified"],
    A.BY_INDEX)
chk("...and a blank cell with no id reads the same",
    A.restore_plate({"plate_id": "", "plate_verified": ""}, 0)["verified"],
    A.BY_INDEX)

# A newer export, or a hand-edited file. Passed through rather than translated:
# every reader downstream withholds a record whose verified is not exactly
# "ok", so an unknown word is already handled - and rewriting it would be this
# module inventing a verdict about a row it did not understand.
chk("an outcome this version does not know is carried, not translated",
    A.restore_plate({"plate_id": "plate_010", "plate_verified": "recropped"},
                    9)["verified"], "recropped")
chk("...and nothing derived can ever be OK",
    [A.restore_plate({"plate_id": p}, 0)["verified"] == A.OK
     for p in ("plate_010", "")], [False, False])
chk("the fields are exactly the ones STATE_FIELDS names",
    tuple(A.restore_plate(DISAGREE, 9)), A.STATE_FIELDS)

print()
print("--- fingerprints(): plates.csv, the cache, and the missing-image gap ---")
with tempfile.TemporaryDirectory() as tmp2:
    write_file(os.path.join(tmp2, "p1.png"), b"PLATE-ONE")
    write_file(os.path.join(tmp2, "p2.png"), b"PLATE-TWO")
    write_plates_csv(tmp2, [
        ["plate_001", "p1.png", "10", "20"],
        ["plate_002", "p2.png", "30", "40"],
        ["plate_003", "gone.png", "5", "6"],
    ])

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
    chk("...with the documented header",
        open(os.path.join(tmp2, A.CACHE_NAME), encoding="utf-8")
        .readline().strip(),
        ",".join(A.CACHE_COLUMNS))

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

    # Replace one image's bytes with a DIFFERENT-LENGTH payload (same name,
    # same declared shape). This alone is driven by st_size - it would pass
    # under a cache keyed on size only, with no mtime component at all - so
    # it is not evidence the ns key works. That evidence is the block below.
    write_file(os.path.join(tmp2, "p1.png"), b"PLATE-ONE-REPLACED-CONTENT")
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
print("--- the ns cache key itself: same size, same wall-clock second ---")
# THE guard against the 2026-09-06 failure mode, exercised directly rather
# than left to the docstring's word: a plate re-rendered to the SAME byte
# count, inside the SAME whole second, must still be caught. A cache keyed on
# (size, whole-second mtime) - what this module shipped with before spec
# review reproduced the false OK - cannot tell these two states apart; only
# nanosecond resolution can. Built with os.utime rather than a sleep, so the
# suite stays fast and the timing is exact rather than merely probable.
with tempfile.TemporaryDirectory() as tmp3:
    same_size_before = b"A" * 32
    same_size_after = b"B" * 32
    chk("the fixture really is same length, different bytes "
        "(or this test proves nothing)",
        (len(same_size_before) == len(same_size_after),
         same_size_before != same_size_after),
        (True, True))

    path3 = os.path.join(tmp3, "p1.png")
    write_file(path3, same_size_before)
    write_plates_csv(tmp3, [["plate_001", "p1.png", "1", "1"]])

    before_digest = A.fingerprints(tmp3)["plate_001"]["fp"]
    st = os.stat(path3)

    # Same length, different bytes, mtime pushed forward by 1 microsecond -
    # still the same whole second as before. mtime, not size, is the only
    # signal a whole-second-keyed cache and a nanosecond-keyed one disagree
    # on here.
    write_file(path3, same_size_after)
    os.utime(path3, ns=(st.st_atime_ns, st.st_mtime_ns + 1000))

    after_digest = A.fingerprints(tmp3)["plate_001"]["fp"]
    chk("same size, same second, 1us later -> the digest still moves",
        before_digest == after_digest, False)

print()
print("--- a failed hash is never cached as an empty fingerprint ---")
with tempfile.TemporaryDirectory() as tmp4:
    write_file(os.path.join(tmp4, "s1.png"), b"SOME-BYTES")
    write_plates_csv(tmp4, [["plate_001", "s1.png", "1", "1"]])

    real_fingerprint = A.fingerprint
    A.fingerprint = lambda path: None  # a locked or half-written file
    try:
        fps_fail = A.fingerprints(tmp4)
    finally:
        A.fingerprint = real_fingerprint
    chk("a hash that fails reports fp: None for THIS call",
        fps_fail["plate_001"]["fp"], None)

    cache_path = os.path.join(tmp4, A.CACHE_NAME)
    if os.path.exists(cache_path):
        with open(cache_path, newline="", encoding="utf-8") as fh:
            cache_rows = list(csv.DictReader(fh))
        chk("...and nothing with a blank digest was written to the cache",
            any(r.get("digest") == "" for r in cache_rows), False)

    # The file was never actually broken - only fingerprint() was stubbed.
    # Now that it is real again, the row must resolve to a REAL digest, not a
    # blank one served back from a cache entry it should never have written.
    fps_ok = A.fingerprints(tmp4)
    chk("...and a later, healthy call gets a real digest, not a cached blank",
        fps_ok["plate_001"]["fp"] is not None
        and len(fps_ok["plate_001"]["fp"]) == A.DIGEST_CHARS, True)

print()
print("--- a truncated cache row is not trusted ---")
with tempfile.TemporaryDirectory() as tmp5:
    write_file(os.path.join(tmp5, "r1.png"), b"REAL-BYTES-HERE")
    write_plates_csv(tmp5, [["plate_001", "r1.png", "1", "1"]])
    st5 = os.stat(os.path.join(tmp5, "r1.png"))
    # A hand-written cache with a TRUNCATED digest - what a write cut off
    # mid-line would leave behind. A corrupt read used to guard only the two
    # int() conversions and never checked the digest's own length.
    with open(os.path.join(tmp5, A.CACHE_NAME), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(A.CACHE_COLUMNS)
        w.writerow(["r1", "r1.png", st5.st_size, st5.st_mtime_ns, "b926"])

    real_fingerprint = A.fingerprint
    calls = []

    def counting2(path):
        calls.append(path)
        return real_fingerprint(path)

    A.fingerprint = counting2
    try:
        fps5 = A.fingerprints(tmp5)
    finally:
        A.fingerprint = real_fingerprint
    chk("a truncated digest in the cache is not trusted - it is re-hashed",
        os.path.join(tmp5, "r1.png") in calls, True)
    chk("...and the real, full-length digest is what comes back",
        len(fps5["plate_001"]["fp"]), A.DIGEST_CHARS)

print()
print("--- a duplicate plate_id: the first row wins, not the last ---")
with tempfile.TemporaryDirectory() as tmp6:
    write_file(os.path.join(tmp6, "first.png"), b"FIRST")
    write_file(os.path.join(tmp6, "second.png"), b"SECOND-DIFFERENT-BYTES")
    write_plates_csv(tmp6, [
        ["plate_001", "first.png", "1", "1"],
        ["plate_001", "second.png", "2", "2"],
    ])
    fps6 = A.fingerprints(tmp6)
    chk("a duplicate plate_id does not crash and keeps ONE entry",
        len(fps6), 1)
    chk("...and it is the FIRST row, not the last silently overwriting it",
        fps6["plate_001"]["image_file"], "first.png")

print()
print("--- fingerprints(): plates.csv cannot be opened ---")
real_sleep = A.IO.time.sleep
A.IO.time.sleep = lambda seconds: None   # keep the retry backoff instant
try:
    # Genuinely absent: retried, still not there, empty map - a legitimate
    # "this set has no plates" answer for a fresh out_root.
    with tempfile.TemporaryDirectory() as tmp7:
        chk("no plates.csv at all -> empty, not an exception",
            A.fingerprints(tmp7), {})

    # A non-ENOENT OSError must propagate rather than being reported as an
    # empty, atlas-less set - that reads as every plate GONE, indistinguishable
    # from a real swap. A directory named plates.csv raises PermissionError on
    # open() here, which is a real, reproducible non-ENOENT OSError.
    with tempfile.TemporaryDirectory() as tmp8:
        os.makedirs(os.path.join(tmp8, "plates.csv"))
        raised = None
        try:
            A.fingerprints(tmp8)
        except OSError as exc:
            raised = exc
        chk("a plates.csv that cannot be read for a reason OTHER than "
            "'it is not there' raises rather than reporting an empty set",
            raised is not None, True)
        chk("...and it is not silently folded into the 'not there' case",
            isinstance(raised, FileNotFoundError), False)

    # Transient: the read fails twice, then the same file is readable. This
    # must not give up after the first failure and report an empty set - that
    # is the exact conflation #6 exists to prevent.
    with tempfile.TemporaryDirectory() as tmp9:
        write_file(os.path.join(tmp9, "q1.png"), b"Q")
        write_plates_csv(tmp9, [["plate_001", "q1.png", "1", "1"]])

        # Patched on the PUBLIC name. This read used to reach into
        # ls_io._retry; a private name with an outside caller is not
        # private, so it was made public and given a `what` so the message
        # says 'read of' rather than claiming a failing write.
        real_retry = A.IO.retry
        attempts_seen = {"n": 0}

        def flaky(fn, path, attempts, what="write to"):
            def wrapped():
                attempts_seen["n"] += 1
                if attempts_seen["n"] < 3:
                    raise FileNotFoundError(2, "No such file or directory", path)
                return fn()
            return real_retry(wrapped, path, attempts, what=what)

        A.IO.retry = flaky
        try:
            fps9 = A.fingerprints(tmp9)
        finally:
            A.IO.retry = real_retry
        chk("a transient dropout that clears within the retry window still "
            "returns the real data, not an empty set",
            sorted(fps9), ["plate_001"])
        chk("...having actually retried rather than succeeding on the first try",
            attempts_seen["n"] >= 3, True)
finally:
    A.IO.time.sleep = real_sleep

print()
print("--- for_config(): the directory is memoised, the fingerprint map is not ---")
with tempfile.TemporaryDirectory() as tmp10:
    cfg = {"out_root": tmp10, "atlas_plate_set": {"dir": "plates_final"}}
    set_dir_path = os.path.join(tmp10, "atlas", "plates_final")
    os.makedirs(set_dir_path)
    write_file(os.path.join(set_dir_path, "t1.png"), b"BEFORE-SWAP")
    write_plates_csv(set_dir_path, [["plate_001", "t1.png", "1", "1"]])

    d1, fps10a = A.for_config(cfg)
    before_fp = fps10a["plate_001"]["fp"]

    # Simulate an atlas swap while a long-lived process (the curator's HTTP
    # server) is open: same id, different bytes - the 2026-09-06 failure.
    write_file(os.path.join(set_dir_path, "t1.png"), b"AFTER-SWAP-DIFFERENT")

    d2, fps10b = A.for_config(cfg)
    chk("the directory answer is stable across calls", d2, d1)
    chk("...but the fingerprint map is NOT memoised past one call - a swap "
        "made after the first call is visible on the very next one",
        fps10b["plate_001"]["fp"] == before_fp, False)

    # A DIFFERENT study must not be handed the first study's cached directory.
    # Given a real plates.csv (even an empty one) so this does not also
    # exercise the missing-file retry path - that is covered above already,
    # and retrying for real here would cost this suite real seconds.
    other_dir = os.path.join(tmp10, "other", "atlas", "plates_final")
    os.makedirs(other_dir)
    write_plates_csv(other_dir, [])
    cfg2 = {"out_root": os.path.join(tmp10, "other"),
            "atlas_plate_set": {"dir": "plates_final"}}
    d3, _ = A.for_config(cfg2)
    chk("a second study's directory is its own, not the first study's",
        d3 == d1, False)

print()
print("--- a whole plate set swapped underneath the curation ---")
sys.path.insert(0, HERE)
import _atlas_fixture as FIX                                  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    before, after = FIX.build(tmp)
    was = A.fingerprints(before)
    now = A.fingerprints(after)
    chk("four plates before", sorted(was), ["plate_00%d" % n for n in (1, 2, 3, 4)])
    chk("four after, one of them new",
        sorted(now), ["plate_001", "plate_002", "plate_003", "plate_005"])

    def stored(pid):
        # PERSISTED names - what a roi_plates.csv row carries - not the
        # `fp`/`px_w`/`px_h` that `fingerprints()` itself returns for `current`.
        return {"plate_id": pid, "plate_fp": was[pid]["fp"],
                "plate_px": "%dx%d" % (was[pid]["px_w"], was[pid]["px_h"])}

    chk("an untouched plate verifies",
        A.plate_status(stored("plate_001"), now), A.OK)
    chk("...and verified() agrees",
        A.verified(A.plate_status(stored("plate_001"), now)), True)
    chk("a re-rendered plate is a resize",
        A.plate_status(stored("plate_002"), now), A.RESIZED)
    chk("a re-cropped plate has changed",
        A.plate_status(stored("plate_003"), now), A.CHANGED)
    chk("a dropped plate is gone",
        A.plate_status(stored("plate_004"), now), A.GONE)

    # A design limit, not a fixture gap: plate_status cannot tell a genuine
    # re-render from an unrelated image dropped in at the same size - nothing
    # but the id ties two images together, so both read RESIZED. plate_004 is
    # a real, different image at exactly plate_001's original pixel size, so
    # this is a true same-size replacement, not a fabricated digest.
    chk("the fixture really is a different image, or this proves nothing",
        was["plate_001"]["fp"] != was["plate_004"]["fp"], True)
    replaced = {"plate_001": {"fp": was["plate_004"]["fp"],
                              "px_w": FIX.PLATE_W, "px_h": FIX.PLATE_H}}
    chk("a replacement at the same size reads RESIZED too - "
        "indistinguishable from a real re-render",
        A.plate_status(stored("plate_001"), replaced), A.RESIZED)

    sx, sy = A.scale_between(stored("plate_002")["plate_px"], now["plate_002"])
    chk("the rescale factor is the size ratio, on both axes",
        (round(sx, 3), round(sy, 3)), (1.5, 1.5))
    chk("...and there is none to apply for an unchanged plate",
        A.scale_between(stored("plate_001")["plate_px"], now["plate_001"]),
        (1.0, 1.0))

    # The cache must not answer for a file that has been replaced in place.
    import shutil
    swapped = os.path.join(tmp, "swapped")
    shutil.copytree(before, swapped)
    A.fingerprints(swapped)                     # writes the cache
    # plate_003's image_file is identical in `before` and `after` (page ==
    # plate number in both), so this really does replace the same path.
    image_file = now["plate_003"]["image_file"]
    chk("plate_003's filename really is identical before and after "
        "the swap, or this replace-in-place would land on a new path",
        was["plate_003"]["image_file"], image_file)
    shutil.copy(os.path.join(after, image_file),
                os.path.join(swapped, image_file))
    again = A.fingerprints(swapped)
    chk("a replaced image is re-hashed, not served from the cache",
        again["plate_003"]["fp"], now["plate_003"]["fp"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
