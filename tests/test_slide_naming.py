"""The filename grammar, and the key everything else joins on.

The scene uid is the primary key of every table on disk, a component of a great
many filenames, and a key in `out_root/curation/*.json`, which holds the
operator's irreplaceable manual work. If moving the grammar into config changed
a single uid, every lookup would miss and the ROI curator would come up showing
hundreds of unstarted sections - with no exception and no error, just the work
apparently gone.

So the first section here pins real LS filenames to the exact uids the old
hard-coded `NAME_RE` in 00_manifest produced. It is the most important thing in
this suite.

Run:  python tests/test_slide_naming.py
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import ls_naming as NM                                      # noqa: E402

#: The grammar migrated out of 00_manifest on 2026-09-07, stated here rather
#: than read from a config so this suite does not depend on the operator's.
LS = {
    "pattern": r"^(?P<subject>LS\d+)_(?P<slide>\d+)(?P<replicate>[a-z])"
               r"(?P<rescan>-?)(?P<pass>_[A-Za-z0-9]+)?\.czi$",
    "case_insensitive": False,
}
PAT = NM.compile_pattern(LS)

failures = []


def chk(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:58} {got!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


# --------------------------------------------------------------------------
print("--- real filenames, pinned to the uids the old grammar built ---")

# filename, scene index, expected uid, expected name_suffix
PINNED = [
    ("LS105_10a.czi", 3, "LS105_s10a_sc03", ""),
    ("LS105_1b.czi", 0, "LS105_s01b_sc00", ""),
    ("LS120_9a.czi", 12, "LS120_s09a_sc12", ""),
    ("LS136_2b.czi", 7, "LS136_s02b_sc07", ""),
    ("LS22_1a.czi", 1, "LS22_s01a_sc01", ""),
    ("LS7_3b.czi", 15, "LS7_s03b_sc15", ""),
    ("LS85_11a.czi", 99, "LS85_s11a_sc99", ""),
    # Historic shapes the old regex accepted, kept so the suffix rule cannot
    # drift even though this corpus no longer carries one.
    ("LS85_7b-.czi", 2, "LS85_s07b_sc02", "-"),
    ("LS53_2b-_A568.czi", 4, "LS53_s02b_sc04", "-_A568"),
    ("LS45_8b_A488.czi", 6, "LS45_s08b_sc06", "_A488"),
    ("LS61_12a.czi", 0, "LS61_s12a_sc00", ""),
    ("LS138_4b.czi", 8, "LS138_s04b_sc08", ""),
]
for name, idx, uid, suffix in PINNED:
    parsed = NM.parse_name(name, PAT)
    chk(f"{name} -> uid", NM.scene_uid(parsed, idx), uid)
    if suffix:
        chk(f"{name} -> name_suffix", parsed["name_suffix"], suffix)

parsed = NM.parse_name("LS105_10a.czi", PAT)
chk("the slide is an int, so :02d still pads",
    (parsed["slide"], parsed["replicate"]), (10, "a"))
chk("a path is read by its basename",
    NM.scene_uid(NM.parse_name(r"D:\slides\LS105_10a.czi", PAT), 3),
    "LS105_s10a_sc03")

# --------------------------------------------------------------------------
print()
print("--- what does not match is reported, not quietly dropped ---")

for bad in ("LS45_8b copy.czi", "notes.txt", "LS45.czi", "45_8b.czi",
            "ls45_8b.czi"):
    chk(f"{bad!r} does not parse", NM.parse_name(bad, PAT), None)

# A subject with an underscore would hand every uid reader half an id.
odd = NM.compile_pattern({"pattern": r"^(?P<subject>[A-Za-z_]+\d+)_(?P<slide>\d+)\.czi$"})
chk("a subject containing '_' is refused, not truncated",
    NM.parse_name("AB_C12_3.czi", odd), None)
chk("...while the same pattern accepts one without",
    (NM.parse_name("ABC12_3.czi", odd) or {}).get("subject"), "ABC12")

# --------------------------------------------------------------------------
print()
print("--- a grammar that cannot work says so ---")

for spec, why in (({}, "no pattern"),
                  ({"pattern": ""}, "empty pattern"),
                  ({"pattern": r"^(?P<subject>[\.czi$"}, "uncompilable"),
                  ({"pattern": r"^(\w+)_(\d+)\.czi$"}, "no subject group")):
    try:
        NM.compile_pattern(spec)
        chk(f"{why} raises NamingError", False, True)
    except NM.NamingError as exc:
        chk(f"{why} raises NamingError", True, True)
        if why == "no subject group":
            chk("...and says why subject is not optional",
                "joins on" in str(exc), True)

# --------------------------------------------------------------------------
print()
print("--- studies whose names carry less ---")

slide_only = NM.compile_pattern(
    {"pattern": r"^(?P<subject>[A-Za-z]+\d+)_(?P<slide>\d+)\.czi$"})
chk("no replicate: the uid simply omits it",
    NM.scene_uid(NM.parse_name("AB12_3.czi", slide_only), 5), "AB12_s03_sc05")

subject_only = NM.compile_pattern({"pattern": r"^(?P<subject>[A-Za-z0-9]+)\.czi$"})
chk("no slide either: subject and scene alone",
    NM.scene_uid(NM.parse_name("Fish07.czi", subject_only), 5), "Fish07_sc05")

extra = NM.compile_pattern(
    {"pattern": r"^(?P<subject>[A-Za-z]+\d+)_(?P<batch>[A-Z])_(?P<slide>\d+)\.czi$"})
chk("a group the pipeline does not know is carried, not dropped",
    NM.parse_name("AB12_C_3.czi", extra)["extras"], {"batch": "C"})

# --------------------------------------------------------------------------
print()
print("--- the uid round-trips, so nothing needs to re-parse it ---")

for spec, name in ((LS, "LS105_10a.czi"),
                   ({"pattern": slide_only.pattern}, "AB12_3.czi"),
                   ({"pattern": subject_only.pattern}, "Fish07.czi")):
    pat = NM.compile_pattern(spec)
    p = NM.parse_name(name, pat)
    uid = NM.scene_uid(p, 4)
    back = NM.split_uid(uid)
    chk(f"{uid} splits back to what built it",
        (back["subject"], back["slide"], back["replicate"], back["scene"]),
        (p["subject"], p["slide"], p["replicate"], 4))

chk("slide_key is the section's slide, which 06d groups by",
    NM.split_uid("LS105_s10a_sc03")["slide_key"], "LS105_s10a")

# subject_of replaced six copies of uid.split("_")[0]. It must agree with them
# on every uid this pipeline has ever built, and degrade to them on anything
# else rather than raising.
chk("subject_of reads a real uid", NM.subject_of("LS105_s10a_sc03"), "LS105")
chk("...and one with no replicate", NM.subject_of("AB12_s03_sc05"), "AB12")
chk("...and one with no slide", NM.subject_of("Fish07_sc05"), "Fish07")
chk("...and falls back on something it did not build",
    NM.subject_of("whatever_else_here"), "whatever")
chk("...without raising on an empty string", NM.subject_of(""), "")
chk("a string this did not build is not a uid", NM.split_uid("nonsense"), None)
chk("...nor is an empty one", NM.split_uid(""), None)

# --------------------------------------------------------------------------
print()
print("--- sorting ids without assuming a grammar ---")

chk("LS7 < LS22 < LS120",
    sorted(["LS120", "LS7", "LS22"], key=NM.natural_key),
    ["LS7", "LS22", "LS120"])
chk("and a shape the old int(a[2:]) would have crashed on",
    sorted(["Fish-12", "Fish-3", "Fish-100"], key=NM.natural_key),
    ["Fish-3", "Fish-12", "Fish-100"])
chk("and one it would have put all in one bucket",
    sorted(["B1", "A2", "A10"], key=NM.natural_key), ["A2", "A10", "B1"])

# --------------------------------------------------------------------------
print()
print("--- the whole corpus, when the drive is here ---")

# The slides live wherever the study says they live. This was the literal
# `D:\SLIDES HE DEC 2025 LS` until the drive became E:, at which point the
# corpus check below stopped running and said "SKIP" - a green suite over 222
# files it never opened. A path that only one machine can satisfy is a skip
# waiting to happen; the config is the one place that knows.
def _source_dir():
    """The study's slide folder, or "" when there is no config to read.

    Read from the config file by PATH rather than through `ls_config`, and
    named explicitly - which is the same thing `tests/run.sh` does for the
    curator page builds, for the same reason. `run.sh` sets LS_CONFIG_STRICT so
    that a suite which does not name a config fails rather than silently
    reading the operator's; this block is the one that WANTS the operator's,
    because it is the real-corpus check and the corpus is theirs. Naming it is
    how that dependency gets stated instead of inherited.

    One key, read once, only to decide whether an extra check can run. Nothing
    here validates or derives anything from the config, so going around
    `ls_config` costs nothing it would have given.

    This was the literal `D:\SLIDES HE DEC 2025 LS`. The drive became E: and
    the check printed SKIP - a green suite over 222 files it never opened.
    """
    named = os.environ.get("LS_CONFIG") or os.path.join(REPO, "config.json")
    try:
        with open(named, encoding="utf-8") as fh:
            return json.load(fh).get("source_dir") or ""
    except (OSError, ValueError):
        return ""


SRC = _source_dir()
if not SRC or not os.path.isdir(SRC):
    print("SKIP no slide drive to read: " + (SRC or "no study resolved here"))
else:
    OLD = re.compile(r"^(LS\d+)_(\d+)([a-z])(-?)(_[A-Za-z0-9]+)?\.czi$",
                     re.IGNORECASE)
    names = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".czi"))
    bad_uid = []
    for n in names:
        m, p = OLD.match(n), NM.parse_name(n, PAT)
        if (m is None) != (p is None):
            bad_uid.append((n, "accepted by one grammar only"))
            continue
        if m is None:
            continue
        want = f"{m.group(1).upper()}_s{int(m.group(2)):02d}{m.group(3).lower()}_sc07"
        if NM.scene_uid(p, 7) != want:
            bad_uid.append((n, NM.scene_uid(p, 7), want))
    chk(f"all {len(names)} filenames give the uid the old grammar gave",
        bad_uid, [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
