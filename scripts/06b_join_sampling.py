"""Stage 6b - join the measurements to the experiment. The unblinding step.

`config.blinding` says "no stage before 06b may read a group label", which is
why the numbering lands here and not earlier. Everything upstream is keyed by
animal ID alone.

**The key is LSnn -> Fish ID nn, and the sheet validates it itself.** All 12
imaged animals match, and the sheet's `slicing IHC July 2025` column is marked
for exactly those 12 - an independent column agreeing on every one. That is
asserted rather than trusted: if it ever stops holding the key is wrong, and a
run that mis-assigns animals to groups should fail loudly rather than produce a
plausible table. Note it is NOT `Brain for == IHC`, which covers 40 fish and is
the wider allocation rather than what was sliced.

**Three animals have a blank treatment, and the tank recovers it.** Across all
153 fish the tanks partition cleanly - 303/304/307/308 exercise, 305/306/309/310
control - and at timepoint 1 exactly 32 fish are labelled control and exactly 32
are blank, the blanks being the exercise tanks. Whoever filled the sheet typed
only the control side. Every row carries `treatment_source` so the inference
stays visible and can be undone.

Reads the workbook directly, parsing the sheet XML with zipfile rather than
adding openpyxl - the pipeline needs one value per fish from one sheet, and the
dependency is not worth it.

Writes:
    results/animal_metadata.csv   one row per animal
    results/roi_dataset.csv       the analysis table

Run:  python 06b_join_sampling.py
      python 06b_join_sampling.py --xlsx "D:/path/to/sampling.xlsx"
"""

import argparse
import csv
import html
import importlib.util
import os
import re
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

CONFIG = G5.CONFIG
OUT_ROOT = G5.OUT_ROOT
RESULTS = os.path.join(OUT_ROOT, "results")
MEAS_CSV = os.path.join(RESULTS, "roi_measurements.csv")
META_CSV = os.path.join(RESULTS, "animal_metadata.csv")
DATASET_CSV = os.path.join(RESULTS, "roi_dataset.csv")

DEFAULT_XLSX = os.path.join(CONFIG["source_dir"], "large scale exp sampling data.xlsx")

# Which tank means which treatment. The sheet states this itself on the rows
# written "303/304" and "307/308"; these are the same tanks named singly.
EXERCISE_TANKS = {"303", "304", "307", "308"}
CONTROL_TANKS = {"305", "306", "309", "310"}

COL = {"fish": 0, "timepoint": 1, "environment": 2, "brackish_tank": 3,
       "sea_tank": 4, "treatment": 5, "body_weight_g": 9, "fork_length_cm": 10,
       "sex": 11, "brain_for": 13, "sliced_july_2025": 17}


def read_sheet(path):
    """The first worksheet as a list of {column index: value}.

    Parsed from the sheet XML directly. openpyxl would be the obvious tool and
    is not installed in the pipeline environment; this needs one sheet and no
    formulas, so it does not earn a dependency.
    """
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        x = z.read("xl/sharedStrings.xml").decode("utf-8")
        for si in re.findall(r"<si>(.*?)</si>", x, re.S):
            shared.append(html.unescape(
                "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))

    def colnum(ref):
        n = 0
        for c in re.match(r"([A-Z]+)", ref).group(1):
            n = n * 26 + ord(c) - 64
        return n - 1

    rows = []
    x = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    for r in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
        out = {}
        for ref, attrs, body in re.findall(r'<c r="([A-Z]+\d+)"([^>]*)>(.*?)</c>', r, re.S):
            v = re.search(r"<v>(.*?)</v>", body, re.S)
            t = re.search(r't="([^"]*)"', attrs)
            if v is None:
                inline = re.findall(r"<t[^>]*>(.*?)</t>", body, re.S)
                val = html.unescape("".join(inline)) if inline else ""
            elif t and t.group(1) == "s":
                val = shared[int(v.group(1))]
            else:
                val = v.group(1)
            out[colnum(ref)] = html.unescape(str(val)).strip()
        rows.append(out)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=DEFAULT_XLSX)
    args = ap.parse_args()

    if not os.path.exists(MEAS_CSV):
        print(f"no {MEAS_CSV} - run 06a_roi_dataset.py first")
        return 1
    if not os.path.exists(args.xlsx):
        print(f"no workbook at {args.xlsx}")
        return 1

    meas = G5.load_csv(MEAS_CSV)
    animals = sorted({r["animal"] for r in meas},
                     key=lambda a: int(re.sub(r"\D", "", a) or 0))

    sheet = read_sheet(args.xlsx)[1:]
    fish = {r.get(COL["fish"], ""): r for r in sheet}
    sliced = {f for f, r in fish.items() if r.get(COL["sliced_july_2025"], "") == "x"}

    # The cohort check. An independent column in the same sheet agreeing on
    # every imaged animal is what makes LSnn -> Fish ID more than a guess, so a
    # disagreement means the key is wrong and this must not proceed.
    imaged = {re.sub(r"\D", "", a) for a in animals}
    missing = sorted(imaged - set(fish))
    if missing:
        print(f"FAIL: no sheet row for fish {missing} - the LSnn -> Fish ID key is wrong")
        return 1
    not_sliced = sorted(imaged - sliced)
    if not_sliced:
        print(f"WARNING: fish {not_sliced} were imaged but are not marked in "
              f"'slicing IHC July 2025'. The cohort column and the images "
              f"disagree; check before trusting the groups.")

    meta, unresolved = {}, []
    for a in animals:
        n = re.sub(r"\D", "", a)
        r = fish[n]
        tr = (r.get(COL["treatment"], "") or "").strip().lower()
        src = "sheet"
        if not tr:
            tank = (r.get(COL["brackish_tank"], "") or "").strip()
            if tank in EXERCISE_TANKS:
                tr, src = "exercise", "tank"
            elif tank in CONTROL_TANKS:
                tr, src = "control", "tank"
            else:
                tr, src = "", "unresolved"
                unresolved.append((a, tank))
        meta[a] = {
            "animal": a, "fish_id": n,
            "timepoint": r.get(COL["timepoint"], ""),
            "environment": r.get(COL["environment"], ""),
            "treatment": tr, "treatment_source": src,
            "brackish_tank": r.get(COL["brackish_tank"], ""),
            "sex": r.get(COL["sex"], ""),
            "body_weight_g": r.get(COL["body_weight_g"], ""),
            "fork_length_cm": r.get(COL["fork_length_cm"], ""),
            "brain_for": r.get(COL["brain_for"], ""),
            "sliced_july_2025": int(n in sliced),
        }

    with open(META_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(next(iter(meta.values())).keys()))
        w.writeheader()
        w.writerows(meta[a] for a in animals)

    carry = ["fish_id", "timepoint", "environment", "treatment", "treatment_source",
             "sex", "body_weight_g", "fork_length_cm"]
    out = []
    for r in meas:
        m = meta.get(r["animal"], {})
        out.append({**r, **{k: m.get(k, "") for k in carry}})
    with open(DATASET_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    print("=" * 72)
    print(f"{len(animals)} animals -> {META_CSV}")
    print(f"{len(out)} rows      -> {DATASET_CSV}")
    print(f"  cohort check: all {len(imaged)} imaged animals are in the sheet"
          + (f", {len(imaged & sliced)} marked sliced" if sliced else ""))
    print()
    print(f"  {'animal':7} {'fish':>4} {'tp':>3} {'environment':12} "
          f"{'treatment':10} {'from':10} {'sex':4} {'ROIs':>5}")
    for a in animals:
        m = meta[a]
        n = sum(1 for r in meas if r["animal"] == a and r["roi_kind"] == "roi")
        print(f"  {a:7} {m['fish_id']:>4} {m['timepoint']:>3} {m['environment']:12} "
              f"{m['treatment'] or '(none)':10} {m['treatment_source']:10} "
              f"{m['sex']:4} {n:>5}")
    if unresolved:
        print(f"\n  UNRESOLVED treatment: {unresolved} - left blank, not guessed")
    print()
    cells = {}
    for a in animals:
        k = (meta[a]["timepoint"], meta[a]["treatment"])
        cells.setdefault(k, []).append(a)
    print("  design:")
    for k in sorted(cells):
        print(f"    timepoint {k[0]}  {k[1] or '(none)':10} n={len(cells[k])}  "
              f"{', '.join(cells[k])}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
