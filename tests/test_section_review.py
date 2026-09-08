"""`section_review.csv` merged into 04a's exclusion list.

This is the path that CHANGES WHAT GETS REFORMATTED, so it is the one worth
pinning. The Review mode in the curator only records decisions; `apply_review`
is what acts on them, and everything it can get wrong is quiet:

  * reinstating a section that stays excluded looks like the operator never
    clicked anything;
  * dropping one that stays kept measures tissue somebody rejected;
  * a mask rejection that also changes the exclusion state, or an exclusion
    that also drops a mask, are each a decision nobody made;
  * a row for the OTHER marker applying to this run would act on a section this
    index has never heard of;
  * mutating the caller's dict would leave 04a's own `excluded` half-merged.

None of those raise. All of them produce a plausible reformatted set.

`select_only` is here for the same reason. A `--only` run re-renders pictures
and writes no index, so letting it touch an INDEXED section would leave the
analysis pointing at an image that no longer matches the angle and fill in its
row - silent, and undetectable downstream. The guard is the whole safety of
that flag, so it is pinned rather than trusted.

Run:  python tests/test_section_review.py
"""

import csv
import importlib.util
import os
import shutil
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

# PAIRED, explicitly. Every assertion below about "the other marker's row"
# is a statement about the paired layout, where the two markers are separate
# scans with separate indexes. config.example.json is multiplex - one frame
# per scene, shared by every marker - and there the same rows deliberately DO
# apply; see tests/test_reformat_layout.py. This suite used to inherit the
# example's multiplex layout while asserting the paired rule, which only
# passed because apply_review did not yet know the difference.
STUDY = use_temp_study(acquisition={"layout": "paired",
                                    "markers": ["AF568", "AF488"]})

_spec = importlib.util.spec_from_file_location(
    "rf", os.path.join(SCRIPTS, "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


FIELDS = ["scene_uid", "marker", "excluded", "decision", "mask_rejected", "reason"]


def write_review(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main():
    tmp = tempfile.mkdtemp(prefix="lsrev_")
    keep = RF.REVIEW_CSV
    try:
        RF.REVIEW_CSV = os.path.join(tmp, "section_review.csv")
        write_review(RF.REVIEW_CSV, [
            {"scene_uid": "A1", "marker": "AF568", "excluded": 0,
             "decision": "restored", "mask_rejected": 0,
             "reason": "focus call was wrong"},
            {"scene_uid": "A2", "marker": "AF568", "excluded": 1,
             "decision": "manual", "mask_rejected": 0,
             "reason": "debris across the whole section"},
            # A mask rejection ALONE - it must not touch the exclusion state.
            {"scene_uid": "A3", "marker": "AF568", "excluded": 0, "decision": "",
             "mask_rejected": 1, "reason": "mask is eating the pial rim"},
            # The other marker's row: a different run's business entirely.
            {"scene_uid": "B1", "marker": "AF488", "excluded": 0,
             "decision": "restored", "mask_rejected": 1, "reason": "other marker"},
        ])

        prior = {"A1": ("auto", "no tissue"), "B1": ("auto", "no tissue")}
        out, rejected = RF.apply_review(prior, "AF568")

        chk("reinstated section leaves the exclusion list", "A1" in out, False)
        chk("dropped section joins it", out.get("A2", ("", ""))[0], "manual")
        chk("...carrying the operator's reason",
            out.get("A2", ("", ""))[1], "debris across the whole section")
        chk("mask rejection is collected", "A3" in rejected, True)
        chk("...and does NOT change the exclusion state", "A3" in out, False)
        chk("other marker's exclusion is ignored", "B1" in out, True)
        chk("other marker's mask rejection is ignored", "B1" in rejected, False)
        chk("the caller's dict is not mutated", sorted(prior), ["A1", "B1"])

        # No file at all is the normal case for a dataset nobody has reviewed:
        # it must be a no-op, not an error.
        RF.REVIEW_CSV = os.path.join(tmp, "absent.csv")
        out2, rej2 = RF.apply_review(prior, "AF568")
        chk("no review file is a no-op", (out2 == prior, rej2), (True, set()))

        # A row with no marker column applies to whichever run reads it - that
        # is the hand-written case, and refusing it would be unhelpful.
        RF.REVIEW_CSV = os.path.join(tmp, "nomarker.csv")
        write_review(RF.REVIEW_CSV, [
            {"scene_uid": "A1", "marker": "", "excluded": 0,
             "decision": "restored", "mask_rejected": 0, "reason": "by hand"}])
        out3, _ = RF.apply_review(prior, "AF568")
        chk("a row with no marker still applies", "A1" in out3, False)
    finally:
        RF.REVIEW_CSV = keep
        shutil.rmtree(tmp, ignore_errors=True)

    test_select_only()

    print()
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


def test_select_only():
    """--only may touch excluded sections and nothing else."""
    excluded = {"A": "manual", "B": "focus"}

    chk("an excluded uid is allowed", RF.select_only("A", excluded), {"A"})
    chk("several, comma separated", RF.select_only("A,B", excluded), {"A", "B"})
    chk("whitespace is not a uid", RF.select_only(" A , B ", excluded), {"A", "B"})

    # The one that matters: a section the index carries must be refused.
    try:
        RF.select_only("A,KEPT", excluded)
        chk("an INDEXED section is refused", "no error", "SystemExit")
    except SystemExit as e:
        chk("an INDEXED section is refused", "KEPT" in str(e), True)
        chk("...and the message says why",
            "writes no index" in str(e), True)

    # An empty selection would silently render nothing and look like success.
    try:
        RF.select_only("", excluded)
        chk("an empty selection is refused", "no error", "SystemExit")
    except SystemExit:
        chk("an empty selection is refused", True, True)

    # @file, which is how a list of 45 actually arrives.
    tmp = tempfile.mkdtemp(prefix="lsonly_")
    try:
        p = os.path.join(tmp, "uids.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(os.linesep.join(["A", "", "B", ""]))
        chk("@file reads one uid per line", RF.select_only("@" + p, excluded), {"A", "B"})
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(os.linesep.join(["A", "KEPT", ""]))
        try:
            RF.select_only("@" + p, excluded)
            chk("@file is guarded too", "no error", "SystemExit")
        except SystemExit:
            chk("@file is guarded too", True, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
