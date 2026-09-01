"""Stage 6e - rebuild both datasets and re-plot, every hour, until detection ends.

`05c_detect_rois.py` takes hours and is resumable, and both spreadsheets read
whatever nuclei are on disk. So the useful thing is not to wait for it: rebuild
the datasets and the figures on a timer, and stop when there is nothing left to
add.

Python rather than a .bat because the stop condition is a real comparison -
distinct sections in `results/roi_nuclei.csv` against `reformatted/roi_boxes.csv`
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

R_SCRIPT = os.path.join(_REPO, "analysis", "plot_roi_figures.R")


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
    hits = sorted(glob.glob(pattern))
    if hits:
        return hits[-1]           # newest version by name
    raise SystemExit("cannot find Rscript. Tried:\n  " + "\n  ".join(tried)
                     + "\nPass --rscript, or set the RSCRIPT environment variable.")


def progress():
    """(sections measured, sections planned). The stop condition, as numbers."""
    if not os.path.exists(G6C.NUCLEI_CSV):
        return 0, 0
    measured = {r["scene_uid"] for r in G5.load_csv(G6C.NUCLEI_CSV)}
    planned = {b["scene_uid"] for b in G5.load_csv(G5.BOX_CSV)}
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
    parser and abort the cycle with exit 2.
    """
    for label, mod in (("measurements", G6A), ("per sample", G6C),
                       ("per slide", G6D)):
        rc = mod.main([]) if label != "measurements" else mod.main()
        if rc:
            print(f"  {label} FAILED (exit {rc})")
            return False
    r = subprocess.run([rscript, R_SCRIPT], cwd=_REPO,
                       capture_output=quiet, text=True)
    if r.returncode:
        print("  plotting FAILED:")
        print((r.stderr or r.stdout or "").strip()[-2000:])
        return False
    if quiet and r.stderr:
        # Rscript writes message() to stderr; it is progress, not failure.
        for line in r.stderr.strip().splitlines()[-4:]:
            print("  " + line)
    return True


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
    print(f"figures: {R_SCRIPT}")

    last, stalled, n = None, 0, 0
    while True:
        n += 1
        done, total = progress()
        stamp = time.strftime("%H:%M:%S")
        print(f"\n[{stamp}] pass {n}: {done} of {total} sections measured")
        if not total:
            raise SystemExit("no roi_boxes.csv - run 05a_roi_geometry.py first")

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
        stalled = stalled + 1 if done == last else 0
        last = done
        if stalled >= args.stall_cycles:
            print(f"\nSTALLED: {done}/{total} unchanged for {stalled} cycles. "
                  f"05c_detect_rois.py is not running - restart it, then start "
                  f"this again.")
            return 2

        print(f"  next pass in {args.interval // 60} min "
              f"({total - done} sections still to measure)")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
