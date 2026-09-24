"""Stage 4b - propose an atlas plate for every section, and build a curator.

The agreed pattern: the pipeline proposes, the user adjudicates. This does the
proposing for rostro-caudal level assignment.

Two things make naive image matching fail here, and both are handled by
comparing *silhouettes* rather than pixels:

  polarity   atlas plates are Nissl - dark tissue on a light background. The
             sections are DAPI - bright tissue on dark. Correlating intensities
             directly would score the best match as the worst.

  stain      even after inverting, Nissl density and DAPI density are different
             quantities. The reliable shared signal is the outline of the
             section, which changes systematically along the rostro-caudal axis.

So both are reduced to a tissue mask, centred, scaled to fill a fixed grid, and
compared by intersection-over-union. Shape only.

The second idea does more work than the similarity does: **sections are ordered**.
Within an animal, plate assignments must not run backwards. A monotonic dynamic
program over the whole series finds the best globally-consistent assignment
rather than picking each section's local best, so one section with an ambiguous
silhouette gets pulled into line by its neighbours instead of dragging the
sequence out of order.

Outputs a proposal CSV and a curator page where the top candidates are shown
side by side with the section.

Run:  python 04b_atlas_match.py
      then open D:/LS-analysis/qc/atlasmatch/atlas_curator.html
"""

import sys
import argparse
import csv
import importlib.util
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_atlas as AT  # noqa: E402
import ls_channels as CH  # noqa: E402
import ls_naming as NM  # noqa: E402

MARKERS = list(CH.marker_names(CONFIG))

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
# THE EXTRACTION SET, deliberately - not the study's configured set.
#
# 04b is in app/stages.py NOT_LISTED as "measured to fail on this data
# (LOGS 2026-08-12); kept as evidence". Re-pointing it at plates_final would
# change the candidate universe from 47 figures to 64 plates and invalidate the
# measurement it exists to record. The literal is gone; the choice is not.
#
# KNOWN GAP: its atlas_proposals_v2.csv still feeds 04d's plate preview, which
# renders from the configured set. Not closed here - see the plan's scope note.
PLATE_DIR = AT.plate_dir(CONFIG, set_name=AT.EXTRACTED)
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "atlasmatch")

GRID = 64          # silhouettes are compared on a GRID x GRID binary raster
TOP_K = 4          # candidates offered per section
# Assignments may not run backwards, but consecutive sections need not advance:
# a slide often holds several sections from one atlas level.
MONOTONIC = True


def _otsu(values):
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(np.float64)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1, w2 = np.cumsum(hist), np.cumsum(hist[::-1])[::-1]
    valid = (w1 > 0) & (w2 > 0)
    m1 = np.cumsum(hist * centres) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[~valid] = -1
    return float(centres[int(np.argmax(var))])


def silhouette(path, invert):
    """Filled tissue mask, centred and scaled to fill a fixed grid.

    Two failure modes had to be fixed here, both visible only by rendering what
    the function actually produced:

    Atlas plates are dark tissue on a light background. Inverting and taking a
    high percentile selects the *darkest* parts - the section's edges - so the
    silhouette came out as a thin rim with the body missing. Instead: anything
    darker than the background is tissue, then fill.

    DAPI sections are faint against black, and a percentile threshold on a
    mostly-black frame selects scattered specks rather than the section. Instead:
    Otsu in log space, as everywhere else in this pipeline, then fill.

    Both then need hole filling and small-component removal, or the silhouette
    is a texture map rather than an outline - which is what made all eight
    orientations score identically at ~0.28, i.e. noise.
    """
    try:
        img = np.asarray(Image.open(path).convert("L").resize((256, 256), Image.BILINEAR))
    except OSError:
        return None
    v = img.astype(np.float32)

    if invert:
        # Light background: tissue is everything meaningfully darker than it.
        background = np.percentile(v, 90)
        mask = v < background * 0.92
    else:
        positive = v[v > 0]
        if positive.size < 100:
            return None
        mask = v > float(np.expm1(_otsu(np.log1p(positive))))

    mask = ndimage.binary_closing(mask, np.ones((5, 5)))
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, np.ones((3, 3)))
    labels, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = np.array(ndimage.sum(mask, labels, range(1, n + 1)))
    # Keep the section (and its second lobe), drop dust and debris.
    keep = np.where(sizes >= 0.12 * sizes.max())[0] + 1
    mask = np.isin(labels, keep)
    if mask.sum() < 200:
        return None

    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = mask[y0:y1, x0:x1]
    # Preserve aspect: pad the shorter axis rather than stretching, or every
    # section would be squashed into the same rectangle and shape lost.
    h, w = crop.shape
    side = max(h, w)
    square = np.zeros((side, side), bool)
    square[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = crop
    small = np.asarray(Image.fromarray(square.astype(np.uint8) * 255)
                       .resize((GRID, GRID), Image.BILINEAR)) > 127
    return small


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


# The eight dihedral transforms. Sections are mounted at a different orientation
# from the one the atlas plates are printed in - measured aspect is 0.86 for
# sections against 2.07 for plates, i.e. roughly a quarter turn - and comparing
# without correcting for it scored a mean IoU of 0.24, which is noise.
DIHEDRAL = [
    ("identity", lambda m: m),
    ("rot90", lambda m: np.rot90(m, 1)),
    ("rot180", lambda m: np.rot90(m, 2)),
    ("rot270", lambda m: np.rot90(m, 3)),
    ("flip", lambda m: np.fliplr(m)),
    ("flip_rot90", lambda m: np.rot90(np.fliplr(m), 1)),
    ("flip_rot180", lambda m: np.rot90(np.fliplr(m), 2)),
    ("flip_rot270", lambda m: np.rot90(np.fliplr(m), 3)),
]


def solve_orientation(section_sils, plate_sils, sample=40):
    """Find the one transform that best aligns sections to plates.

    Solved once over a sample rather than per section: the mounting convention
    is systematic, so letting each section pick its own transform would just let
    noise choose, and a section matched under a different transform from its
    neighbours cannot be ordered against them.
    """
    idx = np.linspace(0, len(section_sils) - 1, min(sample, len(section_sils))).astype(int)
    scores = []
    for name, fn in DIHEDRAL:
        best = [max(iou(fn(section_sils[i]), p) for p in plate_sils) for i in idx]
        scores.append((float(np.mean(best)), name, fn))
    scores.sort(reverse=True, key=lambda s: s[0])
    for s, name, _ in scores:
        print(f"    {name:<12} mean best IoU {s:.3f}")
    return scores[0]


def best_path(sim):
    """Monotonic assignment maximising total similarity.

    dp[i][j] = best total for assigning section i to plate j, given every
    earlier section took a plate index <= j. Without this each section takes its
    own local best and the series can jump back and forth along the brain,
    which is anatomically impossible for serial sections.
    """
    n, m = sim.shape
    dp = np.full((n, m), -np.inf)
    back = np.zeros((n, m), dtype=np.int32)
    dp[0] = sim[0]
    for i in range(1, n):
        run = -np.inf
        arg = 0
        for j in range(m):
            if dp[i - 1, j] > run:
                run = dp[i - 1, j]
                arg = j
            dp[i, j] = sim[i, j] + run
            back[i, j] = arg
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(np.argmax(dp[-1]))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path


def build_parser():
    """The parser, built separately so a test can read the marker choices and
    default off the object argparse will actually use.

    `--marker` used to be `default="AF488"` with NO `choices=` at all - the one
    shape argparse cannot validate: it accepted any string, the `marker_channel`
    filter matched nothing, and the stage walked zero sections and wrote zero
    atlas proposals without erroring. Derived choices make a marker this study
    does not have a usage error instead.

    The default is the SECOND declared marker. That is not a fluorophore fact:
    the sections registered against the atlas are the pass whose geometry every
    other stage is expressed in, which is `04a.DEFAULT_MARKER`, and under
    `paired` that is `MARKERS[1]`. Deriving `MARKERS[0]` here would silently
    register the other pass - the trap this migration keeps meeting, since the
    marker with the unsuffixed outputs is the second declared.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None, help="restrict to one animal")
    _default = MARKERS[1] if len(MARKERS) > 1 else (MARKERS[0] if MARKERS else None)
    ap.add_argument("--marker", default=_default, choices=MARKERS,
                    help=f"channel whose DAPI is used (default {_default})")
    return ap


def main():
    args = build_parser().parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)

    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        plates = list(csv.DictReader(fh))
    print(f"atlas: {len(plates)} plates, "
          f"{sum(1 for p in plates if int(p['n_seeds']) > 0)} with region labels")

    plate_sil, plate_meta = [], []
    for p in plates:
        s = silhouette(os.path.join(PLATE_DIR, p["image_file"]), invert=True)
        if s is None:
            continue
        plate_sil.append(s)
        plate_meta.append(p)
    print(f"  {len(plate_sil)} plate silhouettes built")

    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["marker_channel"] == args.marker]
    if args.animal:
        rows = [r for r in rows if r["animal"] == args.animal]
    by_animal = {}
    for r in rows:
        by_animal.setdefault(r["animal"], []).append(r)

    proposals = []
    for animal, group in sorted(by_animal.items(), key=lambda kv: NM.natural_key(kv[0])):
        group.sort(key=lambda r: int(r["section_order"]))
        sils, keep = [], []
        for r in group:
            p = os.path.join(OVERVIEW_DIR, r["animal"], r["marker_channel"],
                             r["scene_uid"] + "_DAPI.png")
            s = silhouette(p, invert=False)
            if s is not None:
                sils.append(s)
                keep.append(r)
        if not sils:
            continue

        print(f"  {animal}: solving orientation ...")
        score, tname, tfn = solve_orientation(sils, plate_sil)
        print(f"    -> using {tname} (mean best IoU {score:.3f})")
        sils = [tfn(s) for s in sils]

        sim = np.array([[iou(s, p) for p in plate_sil] for s in sils])
        path = best_path(sim) if MONOTONIC else sim.argmax(axis=1)

        for i, r in enumerate(keep):
            order = np.argsort(-sim[i])[:TOP_K]
            cands = [{
                "plate_id": plate_meta[j]["plate_id"],
                "page": plate_meta[j]["page"],
                "img": os.path.join("..", "..", "atlas", "plates",
                                    plate_meta[j]["image_file"]).replace("\\", "/"),
                "score": round(float(sim[i, j]), 3),
                "regions": plate_meta[j]["regions"],
            } for j in order]
            proposed = plate_meta[int(path[i])]
            proposals.append({
                "scene_uid": r["scene_uid"], "animal": animal,
                "section_order": r["section_order"],
                "img": os.path.join("..", "..", "overviews", r["animal"],
                                    r["marker_channel"],
                                    r["scene_uid"] + "_DAPI.png").replace("\\", "/"),
                "proposed_plate": proposed["plate_id"],
                "proposed_page": proposed["page"],
                "proposed_score": round(float(sim[i, int(path[i])]), 3),
                "local_best": plate_meta[int(np.argmax(sim[i]))]["plate_id"],
                "candidates": cands,
                "confirmed_plate": "",
            })
        print(f"  {animal:<7} {len(keep):>4} sections  "
              f"plates {plate_meta[int(path.min())]['plate_id']} -> "
              f"{plate_meta[int(path.max())]['plate_id']}  "
              f"mean score {sim[np.arange(len(keep)), path].mean():.3f}")

    csv_path = os.path.join(REPORT_DIR, "atlas_proposals.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        keys = ["scene_uid", "animal", "section_order", "proposed_plate",
                "proposed_page", "proposed_score", "local_best", "confirmed_plate"]
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(proposals)

    build_curator(proposals)

    disagree = sum(1 for p in proposals if p["proposed_plate"] != p["local_best"])
    weak = sum(1 for p in proposals if p["proposed_score"] < 0.5)
    print()
    print("=" * 72)
    print(f"{len(proposals)} sections matched, {csv_path}")
    print(f"  monotonic constraint moved {disagree} off their local best "
          f"({100 * disagree / max(len(proposals), 1):.0f}%)")
    print(f"  {weak} have a weak score (<0.5) and are shown first for review")
    print()
    print("Silhouette IoU is a coarse signal - it locates the level, it does not")
    print("confirm it. The curator is where the assignment is actually decided.")
    print("=" * 72)


def build_curator(proposals):
    # Weakest and most-disputed first: that is where a human changes the outcome.
    ordered = sorted(proposals,
                     key=lambda p: (p["proposed_score"],
                                    p["proposed_plate"] == p["local_best"]))
    page = IO.fill(TEMPLATE, {"__DATA__": ordered})
    out = os.path.join(REPORT_DIR, "atlas_curator.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"  wrote {out}")


TEMPLATE = """<!doctype html>
<meta charset="utf-8"><title>Atlas level curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}.grow{flex:1}
.bar{height:5px;background:var(--line);border-radius:3px;width:200px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--ok);width:0}
main{flex:1;display:flex;min-height:0;gap:14px;padding:14px}
.pane{display:flex;flex-direction:column;align-items:center;min-width:0}
#sectionPane{flex:1.2}
#sectionPane img{max-width:100%;max-height:100%;object-fit:contain;background:#000;border:2px solid var(--accent)}
#cands{flex:2;display:grid;grid-template-columns:repeat(2,1fr);gap:10px;min-height:0}
.cand{border:2px solid var(--line);border-radius:8px;padding:6px;cursor:pointer;display:flex;
      flex-direction:column;align-items:center;min-height:0;background:#0e1014}
.cand:hover{border-color:var(--accent)}
.cand.chosen{border-color:var(--ok);background:#0f1a12}
.cand img{max-width:100%;max-height:100%;object-fit:contain;flex:1;min-height:0}
.cap{font-size:11px;color:var(--dim);margin-top:4px;text-align:center}
.cap b{color:var(--fg)}
aside{width:250px;border-left:1px solid var(--line);padding:14px;overflow:auto}
.k{display:inline-block;min-width:22px;padding:2px 7px;border:1px solid var(--line);border-radius:5px;
   background:#1c2027;font:600 12px ui-monospace,monospace;text-align:center;margin-right:6px}
.row{margin:9px 0;color:var(--dim)}.row b{color:var(--fg)}
button{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:8px 12px;cursor:pointer;font:inherit}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
footer{padding:8px 16px;border-top:1px solid var(--line);font-size:12px;color:var(--dim)}
</style>
<header>
  <h1>Atlas level curator</h1><span id="pos" class="row"></span>
  <div class="bar"><i id="prog"></i></div><span id="done" class="row"></span>
  <span class="grow"></span>
  <button class="primary" onclick="exportCsv()">Export CSV</button>
</header>
<main>
  <div class="pane" id="sectionPane">
    <img id="sec" alt="">
    <div class="cap" id="secCap"></div>
  </div>
  <div id="cands"></div>
  <aside>
    <div class="row"><b id="uid"></b></div>
    <div class="row">proposed <b id="prop"></b></div>
    <div class="row">score <b id="score"></b></div>
    <div class="row" id="movedRow" style="color:var(--warn)"></div>
    <hr style="border:0;border-top:1px solid var(--line);margin:12px 0">
    <div class="row">Pick the plate at the same rostro-caudal level.</div>
    <div class="row"><span class="k">1</span>-<span class="k">4</span> choose candidate</div>
    <div class="row"><span class="k">a</span> accept proposal</div>
    <div class="row"><span class="k">x</span> none of these fit</div>
    <div class="row"><span class="k">&larr;</span><span class="k">&rarr;</span> navigate</div>
    <div class="row"><span class="k">u</span> next undecided</div>
    <div class="row" style="margin-top:14px">decision: <b id="decision">-</b></div>
  </aside>
</main>
<footer id="hint">Weakest matches first. Decisions autosave in this browser.</footer>
<script>
const DATA = __DATA__;
const KEY = "ls_atlas_curator_v1";
let marks = JSON.parse(localStorage.getItem(KEY) || "{}");
let i = 0;
const el = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
el("cands").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".cand"); if(c) setMark(c.dataset.plate);
});

function render(){
  const d = DATA[i];
  el("sec").src = d.img;
  el("secCap").textContent = `${d.scene_uid}  (section ${d.section_order})`;
  el("uid").textContent = d.scene_uid;
  el("prop").textContent = d.proposed_plate + " / p" + d.proposed_page;
  el("score").textContent = d.proposed_score;
  el("movedRow").textContent = d.proposed_plate !== d.local_best
    ? `order constraint moved this off its local best (${d.local_best})` : "";
  el("pos").textContent = `${i+1} / ${DATA.length}`;

  const chosen = marks[d.scene_uid];
  el("decision").textContent = chosen || "-";
  el("cands").innerHTML = d.candidates.map((c,k) => `
    <div class="cand ${chosen===c.plate_id?'chosen':''}" data-plate="${esc(c.plate_id)}">
      <img src="${esc(c.img)}" alt="">
      <div class="cap"><b>${k+1}. ${esc(c.plate_id)}</b> p${esc(c.page)} &middot; IoU ${c.score}
      ${c.regions ? '<br>'+esc(c.regions) : ''}</div>
    </div>`).join("");

  const n = Object.keys(marks).length;
  el("done").textContent = `${n} decided`;
  el("prog").style.width = (100*n/DATA.length) + "%";
}
function setMark(v){
  marks[DATA[i].scene_uid] = v;
  localStorage.setItem(KEY, JSON.stringify(marks));
  render(); setTimeout(()=>go(1),110);
}
function go(s){ i=Math.max(0,Math.min(DATA.length-1,i+s)); render(); }
function nextUndecided(){
  for(let k=1;k<=DATA.length;k++){ const j=(i+k)%DATA.length;
    if(!marks[DATA[j].scene_uid]){ i=j; render(); return; } }
  el("hint").textContent="All decided - export the CSV.";
}
addEventListener("keydown", e => {
  const d = DATA[i];
  if(e.key>="1"&&e.key<="4"){ const c=d.candidates[+e.key-1]; if(c) setMark(c.plate_id); }
  else if(e.key==="a") setMark(d.proposed_plate);
  else if(e.key==="x") setMark("NONE");
  else if(e.key==="ArrowRight") go(1);
  else if(e.key==="ArrowLeft") go(-1);
  else if(e.key==="u") nextUndecided();
});
function exportCsv(){
  const rows=[["scene_uid","confirmed_plate"]].concat(
    DATA.filter(d=>marks[d.scene_uid]).map(d=>[d.scene_uid,marks[d.scene_uid]]));
  const b=new Blob([rows.map(r=>r.join(",")).join("\\n")],{type:"text/csv"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(b); a.download="curated_atlas_levels.csv"; a.click();
  el("hint").textContent="Saved curated_atlas_levels.csv - put it in qc/atlasmatch/";
}
render();
</script>
"""


if __name__ == "__main__":
    main()
