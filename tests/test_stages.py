"""The app's stage list must cover the pipeline and describe real scripts.

`app/stages.py` is the pipeline as data. It drifted once - the figure in
docs/pipeline-methods.md had 04f, 04g, 04j, 06f and the atlas chain on it and
the sidebar did not - so this pins the two together: every numbered script
in scripts/ is either a stage or is named in NOT_LISTED with a reason, every
stage's script exists and has a main(), and every box on the workflow figure
has a stage id.

docs/pipeline-guide.md is held to the same list, and for the same reason: it
walks the stages one by one, so a stage nobody wrote up is exactly the drift
above in a third document. Its entries are anchored `{#stage-<sid>}`.

Run:  python tests/test_stages.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, os.path.join(REPO, "app"))

import stages as S                                          # noqa: E402

failures = []


def chk(name, got, want=True):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:64} {'' if ok else got!r}")
    if not ok:
        failures.append(name)


ids = [st.sid for st in S.STAGES]
chk("stage ids are unique", len(ids), len(set(ids)))
chk("BY_ID indexes every stage", set(S.BY_ID), set(ids))

numbered = sorted(f for f in os.listdir(SCRIPTS)
                  if re.match(r"^\d", f) and f.endswith((".py", ".groovy")))
listed = {st.script for st in S.STAGES if st.script}
orphans = [f for f in numbered if f not in listed and f not in S.NOT_LISTED]
chk("every numbered script is a stage or explained in NOT_LISTED", orphans, [])
stale = [f for f in S.NOT_LISTED if f in listed or f not in numbered]
chk("NOT_LISTED names only real, unlisted scripts", stale, [])
chk("NOT_LISTED entries carry a reason",
    all(isinstance(v, str) and v.strip() for v in S.NOT_LISTED.values()))

for st in S.STAGES:
    if st.script:
        path = os.path.join(SCRIPTS, st.script)
        chk(f"{st.sid}: script exists", os.path.exists(path))
        if st.script.endswith(".py") and os.path.exists(path):
            src = open(path, encoding="utf-8").read()
            chk(f"{st.sid}: {st.script} has main()", "def main(" in src)
    chk(f"{st.sid}: group is known", st.group in S.GROUPS)
    chk(f"{st.sid}: has a blurb", bool(st.blurb.strip()))
    chk(f"{st.sid}: reader is known", st.reader in S.READERS)
    chk(f"{st.sid}: needs are stage ids", [n for n in st.needs if n not in S.BY_ID], [])
    chk(f"{st.sid}: outputs are relative", [o for o in st.outputs if os.path.isabs(o)], [])
    bad = [a for a in st.argv
           if "{" in a and not re.fullmatch(r"[^{}]*(\{(out_root|repo|scripts)\}[^{}]*)+", a)]
    chk(f"{st.sid}: argv placeholders are the ones the runner expands", bad, [])
    if st.curator:
        chk(f"{st.sid}: a curator stage is an operator step", st.operator)
        chk(f"{st.sid}: the curator page is among its outputs", st.curator in st.outputs)
    reason = st.cli_reason()
    chk(f"{st.sid}: cli_reason() is a string or None",
        reason is None or (isinstance(reason, str) and bool(reason)))

# The workflow figure, box by box. A box with no stage is the drift this
# file exists to catch; keep the names in step with docs/pipeline-methods.md.
FIGURE = {
    "manifest", "verify", "channel_identity",                    # 00, 00b/00c
    "overviews",                                                 # 01
    "tile_geometry", "tilefield_build", "tilefield_verify",      # 01c-01k
    "artifact_before", "artifact_after", "tilefield_raw",
    "saturation_raw", "saturation_map",
    "contactsheets",                                             # 01d
    "pair",                                                      # 02
    "atlas_extract", "atlas_remerge", "atlas_reframe",           # 04a atlas
    "atlas_enforce", "atlas_rebuild",
    "reformat_pcna", "reformat_pcna_curated", "reformat_pcna_final",   # 04a reformat
    "propagate_perk", "reformat_perk", "reformat_perk_final",
    "exclusion", "symmetry", "rotation_curator",                 # 04f
    "artifact_pcna", "artifact_perk",                            # 04g
    "censor_perk", "censor_pcna", "recensor",                    # 04j / 06f
    "worklist", "provenance", "roi_curator", "import_curation",  # 04l
    "roi_geometry",                                              # 05a
    "detect",                                                    # 05c
    "off_tissue", "roi_dataset",                                 # 06a
    "join_sampling", "excel_sample", "excel_slide", "refresh_loop",   # 06b-06e
}
chk("every box on the workflow figure has a stage", sorted(FIGURE - set(ids)), [])

# Order: a stage never needs something listed after it.
pos = {sid: i for i, sid in enumerate(ids)}
back = [(st.sid, n) for st in S.STAGES for n in st.needs if pos[n] > pos[st.sid]]
chk("no stage needs a later stage", back, [])
chk("groups appear in sidebar order",
    [S.GROUPS.index(st.group) for st in S.STAGES]
    == sorted(S.GROUPS.index(st.group) for st in S.STAGES))

# The guide, entry by entry. Same drift the FIGURE set above exists to catch,
# one document further out: a stage nobody wrote up, or a write-up of a stage
# that no longer exists. Entries are anchored `{#stage-<sid>}`, which pandoc
# consumes into the heading id and does not print.
GUIDE = os.path.join(REPO, "docs", "pipeline-guide.md")
chk("docs/pipeline-guide.md exists", os.path.exists(GUIDE))
if os.path.exists(GUIDE):
    guide = open(GUIDE, encoding="utf-8").read()
    cited = re.findall(r"\{#stage-([A-Za-z0-9_]+)\}", guide)
    chk("every stage has an entry in the guide", sorted(set(ids) - set(cited)), [])
    chk("the guide names no stage that does not exist",
        sorted(set(cited) - set(ids)), [])
    chk("no stage is written up twice",
        sorted(s for s in set(cited) if cited.count(s) > 1), [])
    # The guide's whole claim is that reading it top to bottom follows what
    # actually runs, so its order is pinned to the pipeline's own.
    chk("the guide's entries follow the pipeline's order",
        cited, sorted(cited, key=pos.get))
    # Measured counts live in pipeline-methods.md, where check_methods_claims.py
    # verifies them. Anything shaped like one here is an unchecked second copy
    # that will go stale - the guide states settings and structure, not results.
    chk("the guide quotes no moving count of its own",
        sorted(set(re.findall(r"\d{1,3},\d{3}", guide))), [])

# Detection is CLI-only in the frozen build and wherever StarDist is missing,
# and runnable otherwise - the venv the app runs from has it.
chk("detect is CLI-only when frozen", isinstance(S.detect_cli_reason(True, True), str))
chk("detect is CLI-only without StarDist", isinstance(S.detect_cli_reason(False, False), str))
chk("detect runs from source with StarDist", S.detect_cli_reason(False, True), None)

# done() is existence-only and relative to out_root.
import tempfile                                                  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    st = S.BY_ID["manifest"]
    chk("a stage with no outputs on disk is not done", st.done(tmp), False)
    for o in st.outputs:
        os.makedirs(os.path.dirname(os.path.join(tmp, o)) or tmp, exist_ok=True)
        open(os.path.join(tmp, o), "w").close()
    chk("...and is done once every output exists", st.done(tmp), True)
    chk("blocked_by names undone prerequisites",
        S.blocked_by(S.BY_ID["overviews"], tmp), [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
