"""Stage 6e - rebuild both datasets and re-plot, every hour, until detection ends.

`05c_detect_rois.py` takes hours and is resumable, and both spreadsheets read
whatever nuclei are on disk. So the useful thing is not to wait for it: rebuild
the datasets and the figures on a timer, and stop when there is nothing left to
add.

Python rather than a .bat because the stop condition is a real comparison -
distinct sections in `results/roi_nuclei.csv` against every marker's box file
- rather than console text scraped from another program.

**Two stop conditions, and the second one matters more than it looks.**
Completion is the expected exit. The other is a STALL: if the measured count has
not moved for three cycles, detection has died or been stopped, and a loop that
keeps rebuilding identical figures forever is worse than one that says so and
quits. Exits non-zero in that case, so a scheduler notices.

Run:  python 06e_refresh_loop.py
      python 06e_refresh_loop.py --interval 1800
      python 06e_refresh_loop.py --once          # one pass, no waiting
"""

import argparse
import glob
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G5 = _load("_g5", "05a_roi_geometry.py")
G6A = _load("_g6a", "06a_roi_dataset.py")
G6C = _load("_g6c", "06c_excel_dataset.py")
G6D = _load("_g6d", "06d_excel_by_slide.py")

# Every R script that draws from the workbooks this loop rebuilds.
#
# plot_by_sample and plot_by_slide used to be in no runbook, no doc and no
# stage - so their four figures sat in results/ for a day drawn from the
# pre-refactor Abercrombie h while everything around them was rebuilt. Nothing
# structural stopped that recurring, and no PCNA version of them would ever have
# been produced. Listing them here is what makes them part of the pipeline
# rather than something someone remembers to run.
#
# plot_roi_figures goes first: it is the one the operator is actually watching.
R_SCRIPTS = [os.path.join(_REPO, "analysis", n) for n in
             ("plot_roi_figures.R", "plot_by_sample.R", "plot_by_slide.R")]


def r_command(rscript, script, results_dir):
    """The argv for one R script.

    The results directory goes on the command line, LAST. All three scripts
    take it as their first trailing argument and, given none, fall back to a
    default hard-coded in roi_plots.R - so a loop that called them bare drew
    every figure from that default no matter what config.json's out_root said.
    Passing it explicitly is what makes the figures land beside the workbooks
    this loop just rebuilt.
    """
    return [rscript, script, results_dir]


def rscript_version(path):
    """(major, minor, patch) from an `R-x.y.z` path component; (0,0,0) if none."""
    m = re.search(r"R-(\d+)\.(\d+)\.(\d+)", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def newest(hits):
    """The highest-versioned Rscript. Sorting the paths as text put R-4.9.1
    after R-4.10.0."""
    return max(hits, key=rscript_version)

def find_rscript(explicit=None):
    """Where R is, in decreasing order of how much someone meant it.

    Rscript is not on PATH on this machine - R 4.6.0 installs to Program Files
    without adding it - so falling back to a glob is the difference between
    working and not. The version is NOT hard-coded: pinning 4.6.0 here would
    break silently the day R updates.
    """
    tried = []
    for cand in (explicit, os.environ.get("RSCRIPT")):
        if cand:
            tried.append(cand)
            if os.path.exists(cand):
                return cand
    found = shutil.which("Rscript")
    tried.append("Rscript on PATH")
    if found:
        return found
    pattern = r"C:\Program Files\R\R-*\bin\Rscript.exe"
    tried.append(pattern)
    hits = glob.glob(pattern)
    if hits:
        return newest(hits)
    raise SystemExit("cannot find Rscript. Tried:\n  " + "\n  ".join(tried)
                     + "\nPass --rscript, or set the RSCRIPT environment variable.")


def marker_list():
    """The markers 06a has actually measured, in a stable order.

    Read from `roi_measurements.csv` rather than from config or a constant, so
    the loop plots what exists rather than what was expected to exist. Falls
    back to the R default if the column or the file is missing, which is what a
    dataset built before the column existed looks like.
    """
    path = G6C.MEAS_CSV
    if not os.path.exists(path):
        return ["AF568"]
    rows = G5.load_csv(path)
    seen = sorted({r.get("marker") for r in rows if r.get("marker")})
    if not seen:
        return ["AF568"]
    # AF568 FIRST. A plotting failure ends the loop, and plain sorted() puts
    # AF488 in front - so an untested marker on the thinnest data would take the
    # loop down before the pERK figures had been redrawn even once.
    return ([m for m in seen if m == "AF568"]
            + [m for m in seen if m != "AF568"])


def progress():
    """(sections measured, sections planned). The stop condition, as numbers."""
    if not os.path.exists(G6C.NUCLEI_CSV):
        return 0, 0
    measured = {r["scene_uid"] for r in G5.load_csv(G6C.NUCLEI_CSV)}
    planned = {b["scene_uid"] for b in G5.all_boxes()}
    return len(measured), len(planned)


def refresh(rscript, quiet=True):
    """One pass: 06a, both datasets, then the figures.

    06a runs FIRST and every cycle. It owns the per-ROI numbers - the positivity
    cut, the Abercrombie factor, the disc areas - and 06c/06d only group and
    format them, so a cycle that skipped it would rebuild the spreadsheets from
    the previous cycle's counts while detection had moved on. 06c refuses to run
    against a 06a that predates the nuclei file rather than doing that quietly,
    which would turn this loop into a stream of identical failures instead of
    stale numbers; either way the fix is to run 06a here.

    It costs about 16 s on the finished pERK file, against hours for detection.

    `main([])` rather than `main()`: these parse their own argv, and this
    process's argv carries 06e's flags - so `--interval 1800` would reach 06c's
    parser and abort the cycle with exit 2. 06a has no flags and ignores the
    list, so all three are called the same way.
    """
    for label, mod in (("measurements", G6A), ("per sample", G6C),
                       ("per slide", G6D)):
        rc = mod.main([])
        if rc:
            print(f"  {label} FAILED (exit {rc})")
            return False
    # ONE R RUN PER MARKER PRESENT.
    #
    # The figures draw one marker at a time - LS_MARKER selects it, defaulting
    # to AF568 - so a bare Rscript call rebuilds the pERK figures and nothing
    # else. That is wrong in exactly the situation this loop exists for: the
    # long run it is meant to babysit is the PCNA one, and it would have spent
    # hours redrawing unchanged pERK figures, reporting success, and never
    # producing a PCNA figure at all. Nothing would have errored.
    #
    # The markers come from what 06a actually wrote, so this follows the data
    # rather than a list that has to be kept in step.
    markers = marker_list()
    results_dir = os.path.join(G5.OUT_ROOT, "results")
    for mk in markers:
        env = dict(os.environ, LS_MARKER=mk)
        for script in R_SCRIPTS:
            name = os.path.basename(script)
            # R writes UTF-8 (a degree sign in a caption, an em dash in a
            # warning); the console codepage is not. Decode explicitly, and
            # never let a stray byte take the loop down.
            r = subprocess.run(r_command(rscript, script, results_dir),
                               cwd=_REPO, env=env,
                               capture_output=quiet, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode:
                print(f"  {name} FAILED for {mk}:")
                print((r.stderr or r.stdout or "").strip()[-2000:])
                return False
            if quiet and r.stderr:
                # Rscript writes message() to stderr; progress, not failure.
                for line in r.stderr.strip().splitlines()[-3:]:
                    print(f"  [{mk} {name}] " + line)
    return True


def stall_count(stalled, done, last):
    """Consecutive readings at the same count, the current one included.

    Three identical readings ARE three stalled cycles; counting from the
    second made --stall-cycles 3 wait for a fourth, an hour later.
    """
    return stalled + 1 if last is not None and done == last else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=3600, help="seconds (default 3600)")
    ap.add_argument("--once", action="store_true", help="one pass, then stop")
    ap.add_argument("--rscript", help="path to Rscript.exe")
    ap.add_argument("--stall-cycles", type=int, default=3,
                    help="give up after this many cycles with no new sections")
    args = ap.parse_args()

    rscript = find_rscript(args.rscript)
    print(f"Rscript: {rscript}")
    print("figures: " + ", ".join(os.path.basename(x) for x in R_SCRIPTS))

    last, stalled, n = None, 0, 0
    while True:
        n += 1
        done, total = progress()
        stamp = time.strftime("%H:%M:%S")
        print(f"\n[{stamp}] pass {n}: {done} of {total} sections measured")
        if not total:
            raise SystemExit("no roi_boxes_<marker>.csv - run "
                             "05a_roi_geometry.py first")

        ok = refresh(rscript)
        if not ok:
            return 1

        if done >= total:
            print(f"\n[{time.strftime('%H:%M:%S')}] detection complete "
                  f"({done}/{total}) - datasets and figures are final.")
            return 0
        if args.once:
            print("  --once: stopping with detection still in progress")
            return 0

        # A count that has not moved means 05c is not running. Rebuilding the
        # same figures on the hour forever would look like progress.
        stalled = stall_count(stalled, done, last)
        last = done
        if stalled >= args.stall_cycles:
            print(f"\nSTALLED: {done}/{total} unchanged over {stalled} readings. "
                  f"05c_detect_rois.py is not running - restart it, then start "
                  f"this again.")
            return 2

        print(f"  next pass in {args.interval // 60} min "
              f"({total - done} sections still to measure)")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
