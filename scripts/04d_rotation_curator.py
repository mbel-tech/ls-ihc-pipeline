"""Stage 4d - manual rotation curator, with free-angle drag.

The hand-drawn scan regions are one-section-accurate, so section *division* needs
no adjudication. Orientation does: `04a_reformat.py` rotates each section by the
principal axis of its tissue mask, which gets the long axis horizontal but cannot
know which way round is correct, and for an obliquely cut section the axis itself
is only approximate.

Interaction:

  **drag to rotate freely**, 1 degree resolution - grab the section and turn it,
  the angle following the pointer around the centre of the cell. Quantising to
  90 degrees was wrong for this task: matching to an atlas plate needs the
  section turned to the plate's actual angle, not to the nearest quadrant.

  **reference underlay** - the proposed atlas plate can be shown behind the
  section in red, so rotating to align is a direct visual comparison rather than
  a judgement made from memory. This is the whole reason fine rotation matters.

  **right-click to exclude** a section that is too damaged to measure. Some
  sections are torn or folded badly enough that including them would add noise
  to a group comparison rather than evidence, and no amount of rotation fixes
  that. Right-click again to bring one back; `x` does the same from the keyboard.
  Excluded sections drop out of *everything* downstream, not just the rotation:
  `04a_reformat.py` skips them, so they never enter `reformat_index.csv` and
  therefore cannot reach matching, registration or quantification.

  This is a judgement about tissue quality, made on the DAPI channel before any
  marker signal has been looked at, and it is recorded per section with a reason
  - so it stays a documented exclusion criterion rather than a silent one.

  a wall rather than a queue, because most sections are already close and the
  task is to spot and fix the ones that are not.

Corrections are stored as a delta *on top of* the automatic angle, so improving
the auto-rotation later does not invalidate the manual work.

Output: `reformatted/rotation_overrides.csv` (scene_uid, extra_rotation, flip,
excluded), read back by `04a_reformat.py --apply-overrides`, which also writes
`reformatted/excluded_sections.csv` as the canonical exclusion list for stages
that do not read the reformat index.

Run:  python 04d_rotation_curator.py
      python 04d_rotation_curator.py --animal LS45 --thumb 190
"""

import argparse
import csv
import importlib.util
import json
import os

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
INDEX_CSV = os.path.join(REFORMAT_DIR, "reformat_index.csv")
MATCH_CSV = os.path.join(OUT_ROOT, "qc", "atlasmatch", "atlas_proposals_v2.csv")
CANDIDATES_CSV = os.path.join(REFORMAT_DIR, "exclusion_candidates.csv")
SYMMETRY_CSV = os.path.join(REFORMAT_DIR, "symmetry_proposals.csv")
CURATOR_HTML = os.path.join(REFORMAT_DIR, "rotation_curator.html")

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Rotation curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);
       padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}.grow{flex:1}
.row{color:var(--dim)}.row b{color:var(--fg)}
button,select{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;
       padding:7px 11px;cursor:pointer;font:inherit}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
button.on{border-color:var(--ok);color:var(--ok)}
#wall{display:grid;gap:8px;padding:14px}
.cell{border:2px solid var(--line);border-radius:8px;background:#0e1014;padding:5px;
      display:flex;flex-direction:column;align-items:center;user-select:none;touch-action:none}
.cell:hover{border-color:var(--accent)}
.cell.changed{border-color:var(--warn);background:#1a1610}
.cell.active{border-color:var(--accent);box-shadow:0 0 0 2px rgba(77,163,255,.25)}
.cell.excluded{border-color:#c0392b;background:#1c1010}
.cell.excluded .stack{opacity:.32;filter:grayscale(1)}
.cell.excluded .stack::after{content:"EXCLUDED";position:absolute;inset:0;display:flex;
  align-items:center;justify-content:center;color:#ff6b5e;font:700 12px system-ui;
  letter-spacing:.08em;pointer-events:none}
/* An unreviewed proposal is dashed amber, not solid red - the machine has an
   opinion, you have not confirmed it, and the page should not pretend otherwise. */
.cell.excluded.auto{border-style:dashed;border-color:var(--warn);background:#161208}
.cell.excluded.auto .stack{opacity:.42}
.cell.excluded.auto .stack::after{content:"PROPOSED";color:var(--warn)}
.cell.symauto{border-color:#7c5cff;background:#141026}
.cell.symauto .tag{color:#a48bff}
.cell.restored{border-color:var(--ok)}
.cell.restored .cap::after{content:" kept";color:var(--ok);font-weight:600}
.why{color:var(--warn);font-size:9px;line-height:1.3;margin-top:2px;
     overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
body.hideexcl .cell.excluded{display:none}
.stack{position:relative;width:100%;aspect-ratio:1;cursor:grab;overflow:hidden;border-radius:5px}
.stack:active{cursor:grabbing}
.stack img{position:absolute;inset:0;margin:auto;max-width:100%;max-height:100%}
.ref{opacity:0;filter:sepia(1) saturate(6) hue-rotate(-30deg)}
.showref .ref{opacity:.45}
.cap{font-size:10px;color:var(--dim);margin-top:3px;text-align:center;line-height:1.25;word-break:break-all}
.tag{color:var(--warn);font-weight:600}
footer{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);
       padding:9px 16px;font-size:12px;color:var(--dim)}
kbd{display:inline-block;padding:1px 6px;border:1px solid var(--line);border-radius:4px;
    background:#1c2027;font:600 11px ui-monospace,monospace}
</style>
<header>
  <h1>Rotation curator</h1>
  <select id="animal" onchange="render()"></select>
  <button id="refBtn" onclick="toggleRef()">reference: off</button>
  <span class="row"><b id="count"></b> shown</span>
  <span class="row"><b id="changed"></b> adjusted</span>
  <span class="row" style="color:#ff6b5e"><b id="excl"></b> excluded</span>
  <span class="row" style="color:#d29922">(<b id="auto"></b> unreviewed)</span>
  <span class="row" style="color:#a48bff"><b id="symauto"></b> auto-rotated</span>
  <span class="row" id="restoredWrap" style="color:#3fb950"><b id="restored"></b> kept</span>
  <button id="reviewBtn" onclick="toggleReview()">review proposals: off</button>
  <button id="hideBtn" onclick="toggleHide()">hide excluded: off</button>
  <span class="row" id="live"></span>
  <span class="grow"></span>
  <button onclick="resetAll()">Reset visible</button>
  <button class="primary" onclick="exportCsv()">Export CSV</button>
</header>
<div id="wall"></div>
<footer>
  <kbd>drag</kbd> rotate freely (1&deg;) &middot;
  <kbd>shift+drag</kbd> snap 15&deg; &middot;
  <kbd>&larr;</kbd><kbd>&rarr;</kbd> nudge 1&deg; (hold shift for 10&deg;) &middot;
  <kbd>right-click</kbd> exclude / restore &middot;
  dashed amber = exclusion proposed &middot;
  purple = auto-rotated to its symmetry axis (04h) &middot;
  <kbd>f</kbd> flip &middot; <kbd>r</kbd> reset &middot; <kbd>0</kbd> zero &middot; <kbd>x</kbd> exclude &middot;
  changes autosave
</footer>
<script>
const DATA = __DATA__;
const THUMB = __THUMB__;
const KEY = "ls_rotation_curator_v3";
// uid -> {r:deg, f:bool, x?:bool}. `x` ABSENT means "no decision yet", which is
// what lets a proposal stand; `x:false` is an explicit "keep this one".
let state = JSON.parse(localStorage.getItem(KEY) || "null");

if(state === null){
  // Migrate v2. There, every touched section was written with x:false because
  // exclusion was two-state. Read literally under the tri-state rule that would
  // mean "explicitly kept", and every proposal on a section the user had merely
  // rotated would be silently overridden. So drop the falses and keep the work.
  const old = JSON.parse(localStorage.getItem("ls_rotation_curator_v2") || "{}");
  state = {};
  for(const [uid, s] of Object.entries(old)){
    const e = {r: s.r || 0, f: !!s.f};
    if(s.x === true) e.x = true;
    if(e.r || e.f || e.x) state[uid] = e;
  }
  localStorage.setItem(KEY, JSON.stringify(state));
  if(Object.keys(old).length) console.log(`migrated ${Object.keys(state).length} entries from v2`);
}
let showRef = false;
let reviewOnly = false;
let active = null;

const el = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
document.getElementById("wall").style.gridTemplateColumns =
  `repeat(auto-fill,minmax(${THUMB}px,1fr))`;

const animals = [...new Set(DATA.map(d => d.animal))].sort((a,b)=>+a.slice(2)-+b.slice(2));
el("animal").innerHTML = ['<option value="">all animals</option>']
  .concat(animals.map(a => `<option>${a}</option>`)).join("");

// Proposals from 04f, keyed by uid: {reason, mm2}. Pre-marked as excluded but
// never merged into `state` - a proposal the user has not looked at must stay
// distinguishable from one they accepted, or "how often was the machine wrong"
// becomes unanswerable.
const AUTO = __AUTO__;

// Symmetry proposals from 04h, keyed by uid: {r: degrees, score, conf}. Same
// tri-state discipline as exclusions - a proposal the user has not touched is
// applied but stays visibly a proposal, so "how often was it right" remains
// answerable. ~1 in 10 is wrong, so these are shown, not assumed.
const SYM = __SYM__;

const symOf = uid => (SYM[uid] ? SYM[uid].r : 0);
// The user's own rotation wins; with none, the symmetry proposal stands.
const isSymAuto = uid => !!SYM[uid] && !(state[uid] && state[uid].r !== undefined);

const save = () => localStorage.setItem(KEY, JSON.stringify(state));
// Effective rotation: the user's if they have set one, otherwise 04h's proposal.
// Dragging writes into `state` and takes over from then on.
const get  = uid => state[uid] || {r: symOf(uid), f:false};

// Tri-state. The user's explicit decision wins; with no decision the proposal
// stands. `x` is absent, not false, until they actually click.
const isExcluded = uid =>
  (state[uid] && state[uid].x !== undefined) ? !!state[uid].x : !!AUTO[uid];
const isAuto     = uid => !!AUTO[uid] && !(state[uid] && state[uid].x !== undefined);
const isRestored = uid => !!AUTO[uid] && state[uid] && state[uid].x === false;

function setState(uid, r, f, x){
  r = ((Math.round(r) % 360) + 360) % 360;
  const prev = state[uid];
  if(x === undefined) x = prev ? prev.x : undefined;   // keep "no decision yet"
  // Drop the entry only when it carries no information at all - no rotation, no
  // flip, and no decision that differs from what the proposal already says.
  if(r === 0 && !f && x === undefined) delete state[uid];
  else { state[uid] = {r, f}; if(x !== undefined) state[uid].x = x; }
  save(); paint(uid); counts();
}

function toggleExclude(uid){
  const s = get(uid);
  // Flips against the *effective* state, so the first right-click on a proposal
  // restores it rather than appearing to do nothing.
  setState(uid, s.r, s.f, !isExcluded(uid));
}

function counts(){
  const vis = visible();
  el("changed").textContent = vis.filter(d => { const s = get(d.uid); return s.r || s.f; }).length;
  el("excl").textContent    = vis.filter(d => isExcluded(d.uid)).length;
  el("auto").textContent    = vis.filter(d => isAuto(d.uid)).length;
  el("symauto").textContent = vis.filter(d => isSymAuto(d.uid) && symOf(d.uid)).length;
  const restored = vis.filter(d => isRestored(d.uid)).length;
  el("restored").textContent = restored;
  el("restoredWrap").style.display = restored ? "" : "none";
}

function toggleHide(){
  document.body.classList.toggle("hideexcl");
  const on = document.body.classList.contains("hideexcl");
  el("hideBtn").textContent = "hide excluded: " + (on ? "on" : "off");
  el("hideBtn").classList.toggle("on", on);
}

// Review mode: show only the machine's proposals, hardest call first. 103 of
// 1381 sections, so adjudicating them as a batch is minutes rather than an hour
// of scrolling past sections that need nothing.
function toggleReview(){
  reviewOnly = !reviewOnly;
  el("reviewBtn").textContent = "review proposals: " + (reviewOnly ? "on" : "off");
  el("reviewBtn").classList.toggle("on", reviewOnly);
  render();
}

function paint(uid){
  const cell = document.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if(!cell) return;
  const s = get(uid);
  // Only the section turns; the reference underlay stays fixed, so the section
  // is being rotated INTO the atlas frame rather than both moving together.
  cell.querySelector(".sec").style.transform =
    `rotate(${s.r}deg) scaleX(${s.f ? -1 : 1})`;
  const adjusted = !!(state[uid] && (s.r || s.f));
  const excl = isExcluded(uid);
  const symAuto = isSymAuto(uid) && s.r;
  cell.classList.toggle("changed", adjusted && !excl);
  cell.classList.toggle("excluded", excl);
  // Amber-dashed for a proposal nobody has looked at, solid red once the
  // exclusion is the user's own. The distinction is the whole point: it shows
  // at a glance how much of the exclusion list is still unreviewed.
  cell.classList.toggle("auto", excl && isAuto(uid));
  cell.classList.toggle("restored", isRestored(uid));
  cell.classList.toggle("symauto", !!symAuto && !excl);
  cell.querySelector(".tag").textContent = excl ? ""
    : symAuto ? `${s.r}\\u00B0 auto${SYM[uid].conf === "low" ? "?" : ""}`
    : (adjusted ? `${s.r}\\u00B0${s.f ? " flip" : ""}` : "");
}

// --- free rotation by dragging around the cell centre ------------------------
let drag = null;
function angleOf(e, rect){
  return Math.atan2(e.clientY - (rect.top + rect.height/2),
                    e.clientX - (rect.left + rect.width/2)) * 180 / Math.PI;
}
function onDown(e, uid){
  if(e.button !== 0) return;
  const stack = e.currentTarget;
  const rect = stack.getBoundingClientRect();
  drag = {uid, rect, start: angleOf(e, rect), base: get(uid).r, moved:false};
  setActive(uid);
  stack.setPointerCapture(e.pointerId);
  e.preventDefault();
}
function onMove(e){
  if(!drag) return;
  let delta = angleOf(e, drag.rect) - drag.start;
  if(Math.abs(delta) > 0.5) drag.moved = true;
  let r = drag.base + delta;
  if(e.shiftKey) r = Math.round(r/15)*15;
  setState(drag.uid, r, get(drag.uid).f);
  el("live").textContent = `${drag.uid}: ${get(drag.uid).r}\\u00B0`;
}
function onUp(){ drag = null; }

function setActive(uid){
  document.querySelectorAll(".cell.active").forEach(c => c.classList.remove("active"));
  const c = document.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if(c) c.classList.add("active");
  active = uid;
}

addEventListener("keydown", e => {
  if(!active) return;
  const s = get(active);
  const step = e.shiftKey ? 10 : 1;
  if(e.key === "ArrowRight"){ setState(active, s.r + step, s.f); e.preventDefault(); }
  else if(e.key === "ArrowLeft"){ setState(active, s.r - step, s.f); e.preventDefault(); }
  else if(e.key === "f"){ setState(active, s.r, !s.f); }
  else if(e.key === "r"){ setState(active, 0, false); }
  else if(e.key === "0"){ setState(active, 0, s.f); }
  else if(e.key === "x"){ toggleExclude(active); }
  if(active) el("live").textContent = `${active}: ${get(active).r}\\u00B0`;
});

function toggleRef(){
  showRef = !showRef;
  el("refBtn").textContent = "reference: " + (showRef ? "on" : "off");
  el("refBtn").classList.toggle("on", showRef);
  document.querySelectorAll(".stack").forEach(s => s.classList.toggle("showref", showRef));
}

function visible(){
  const a = el("animal").value;
  let rows = a ? DATA.filter(d => d.animal === a) : DATA;
  if(reviewOnly){
    // Descending mm2: the biggest proposed section is the one most likely to be
    // a mistake, so it gets looked at while attention is freshest.
    rows = rows.filter(d => AUTO[d.uid]).slice()
               .sort((p,q) => (AUTO[q.uid].mm2||0) - (AUTO[p.uid].mm2||0));
  }
  return rows;
}

function render(){
  const rows = visible();
  el("count").textContent = rows.length;
  el("wall").innerHTML = rows.map(d => `
    <div class="cell" data-uid="${d.uid}">
      <div class="stack${showRef?' showref':''}">
        ${d.ref ? `<img class="ref" src="${d.ref}" loading="lazy" alt="">` : ""}
        <img class="sec" src="${d.img}" loading="lazy" alt="" draggable="false">
      </div>
      <div class="cap">${d.order} &middot; ${d.uid.split('_').slice(1).join('_')}
        ${d.plate ? '&middot; ' + d.plate : ''} <span class="tag"></span>
        ${AUTO[d.uid] ? `<div class="why" title="${esc(AUTO[d.uid].reason)}">${esc(AUTO[d.uid].reason)}</div>` : ""}
      </div>
    </div>`).join("");
  counts();
  rows.forEach(d => {
    const cell = document.querySelector(`[data-uid="${CSS.escape(d.uid)}"]`);
    if(!cell) return;
    const stack = cell.querySelector(".stack");
    stack.addEventListener("pointerdown", e => onDown(e, d.uid));
    stack.addEventListener("pointermove", onMove);
    stack.addEventListener("pointerup", onUp);
    stack.addEventListener("pointercancel", onUp);
    cell.addEventListener("contextmenu", e => { e.preventDefault(); setActive(d.uid); toggleExclude(d.uid); });
    paint(d.uid);
  });
}

function resetAll(){
  const rows = visible();
  // Counts only decisions the USER made - their own exclusions and their own
  // restores. Resetting sends proposals back to proposed, which costs nothing,
  // so warning about those would be noise that trains you to click through.
  const nx = rows.filter(d => state[d.uid] && state[d.uid].x !== undefined).length;
  if(nx && !confirm(`This discards ${nx} exclusion decision${nx>1?"s":""} you made `
                    + `(proposals return to proposed). Continue?`)) return;
  rows.forEach(d => delete state[d.uid]);
  save(); render();
}

function exportCsv(){
  // Export every section that carries a decision, INCLUDING untouched
  // proposals - the CSV is the pipeline's input, so it has to state the
  // effective outcome rather than only what was clicked.
  const seen = new Set(Object.keys(state));
  Object.keys(AUTO).forEach(u => seen.add(u));
  Object.keys(SYM).forEach(u => seen.add(u));
  const rows = [["scene_uid","extra_rotation","flip","excluded",
                 "rotation_source","decision","reason"]];
  DATA.filter(d => seen.has(d.uid)).forEach(d => {
    const s = get(d.uid), excl = isExcluded(d.uid);
    if(!s.r && !s.f && !excl && !AUTO[d.uid]) return;
    const decision = excl ? (isAuto(d.uid) ? "auto" : "manual")
                          : (AUTO[d.uid] ? "restored" : "");
    const reason = excl && AUTO[d.uid] ? AUTO[d.uid].reason
                 : excl ? "manually excluded: tissue too damaged to measure" : "";
    // Where the angle came from. Same reason as `decision`: without it there is
    // no way to report how often 04h's proposal was accepted, and "the operator
    // rotated 1,278 sections" and "the operator accepted 1,150 proposals" are
    // different claims in a methods section.
    const rsrc = !s.r ? ""
               : isSymAuto(d.uid) ? "auto_symmetry"
               : (SYM[d.uid] ? "manual_overrode_auto" : "manual");
    rows.push([d.uid, s.r||0, s.f?1:0, excl?1:0, rsrc, decision,
               '"'+reason.replace(/"/g,"'")+'"']);
  });
  const b = new Blob([rows.map(r=>r.join(",")).join("\\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(b); a.download = "rotation_overrides.csv"; a.click();
}
render();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None)
    ap.add_argument("--no-proposals", action="store_true",
                    help="build the curator with nothing pre-marked")
    ap.add_argument("--thumb", type=int, default=170,
                    help="thumbnail size in px; bigger gives finer drag control")
    ap.add_argument("--out", default=CURATOR_HTML, metavar="HTML",
                    help="where to write the page (default: the live curator under "
                         "out_root). tests/run.sh points this at tests/build/ so a "
                         "test run never rewrites the page being curated in")
    args = ap.parse_args()

    if not os.path.exists(INDEX_CSV):
        raise SystemExit(f"{INDEX_CSV} not found - run 04a_reformat.py first")
    with open(INDEX_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
    if args.animal:
        rows = [r for r in rows if r["animal"] == args.animal]
    rows.sort(key=lambda r: (r["animal"], int(r["section_order"] or 0)))

    # Proposed atlas plate per section, for the reference underlay. Optional:
    # the curator still works for plain orientation fixing without it.
    proposed = {}
    if os.path.exists(MATCH_CSV):
        with open(MATCH_CSV, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                plate = r.get("confirmed_plate") or r.get("proposed_plate")
                if plate:
                    proposed[r["scene_uid"]] = plate
        print(f"reference underlay available for {len(proposed)} sections")
    else:
        print("no atlas proposals yet - reference underlay disabled "
              "(run 04c_atlas_match.py to enable it)")

    # Exclusion proposals from 04f. Optional - without them the curator is a
    # plain manual tool, which is what it was before.
    auto = {}
    if os.path.exists(CANDIDATES_CSV) and not args.no_proposals:
        with open(CANDIDATES_CSV, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("proposed") == "1":
                    auto[r["uid"]] = {"reason": r.get("reason", ""),
                                      "mm2": float(r.get("largest_mm2") or 0)}
        print(f"{len(auto)} exclusion proposals loaded from 04f")
    elif args.no_proposals:
        print("proposals disabled (--no-proposals)")
    else:
        print("no exclusion proposals - run 04f_exclusion_candidates.py to enable them")
    auto = {k: v for k, v in auto.items() if k in {r["id"] for r in rows}}

    # Symmetry-axis proposals from 04h. Only non-zero, non-excluded ones are
    # embedded: a zero correction is not a proposal, it is agreement.
    sym = {}
    if os.path.exists(SYMMETRY_CSV) and not args.no_proposals:
        with open(SYMMETRY_CSV, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r["proposed_rotation"]:
                    continue
                deg = int(r["proposed_rotation"])
                if deg == 0:
                    continue
                sym[r["scene_uid"]] = {"r": deg, "score": r["sym_score"],
                                       "conf": r["confidence"]}
        n_low = sum(1 for v in sym.values() if v["conf"] == "low")
        print(f"{len(sym)} symmetry rotations loaded from 04h "
              f"({n_low} low confidence)")
    elif not args.no_proposals:
        print("no symmetry proposals - run 04h_symmetry_axis.py to pre-rotate sections")
    sym = {k: v for k, v in sym.items() if k in {r["id"] for r in rows}}

    data = []
    for r in rows:
        plate = proposed.get(r["id"])
        ref = f"plates/{plate}.png" if plate and os.path.exists(
            os.path.join(REFORMAT_DIR, "plates", plate + ".png")) else None
        data.append({
            "uid": r["id"], "animal": r["animal"], "order": r["section_order"],
            "img": f"sections/{r['id']}.png", "ref": ref, "plate": plate or "",
        })

    page = IO.fill(PAGE, {"__DATA__": data, "__AUTO__": auto, "__SYM__": sym,
                          "__THUMB__": args.thumb})
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)

    with_ref = sum(1 for d in data if d["ref"])
    print(f"wrote {args.out}")
    print(f"  {len(data)} sections, {len({d['animal'] for d in data})} animals, "
          f"{with_ref} with a reference plate")
    print()
    print("Drag a section to rotate it freely (1 degree). Shift-drag snaps to 15.")
    print("Arrow keys nudge the last-touched section by 1 degree, 10 with shift.")
    print("Turn the reference on to see the proposed atlas plate behind it in red -")
    print("only the section rotates, so you are turning it into the atlas frame.")
    print()
    print("Right-click (or 'x') excludes a section, or restores a proposed one.")
    print("Excluded sections are skipped by 04a_reformat.py, so they never reach")
    print("matching, registration or counting - not filtered out later, absent.")

    if auto:
        print()
        print(f"{len(auto)} sections are PRE-MARKED for exclusion (dashed amber, 'PROPOSED').")
        print("They hold no contiguous piece of tissue big enough to measure. Nothing")
        print("is decided until you look: 'review proposals' shows only these, biggest")
        print("first, so the most arguable calls come while attention is freshest.")
        print()
        _report_gradient(rows, auto)
    print()
    print("Export when done, save next to this file, then:")
    print("  python 04a_reformat.py --apply-overrides")


def _report_gradient(rows, auto):
    """State where the proposals fall along the brain, because they are not
    uniform and the non-uniformity is a real property of the data.

    Proposals concentrate heavily in the first sections of each series. That may
    be entirely correct - rostral tips are genuinely small and frequently
    fragmentary - but it means accepting them wholesale trims rostral coverage
    specifically, not a random sample. Whoever reviews this should know that
    before clicking through, not discover it in the results.
    """
    from collections import defaultdict
    by = defaultdict(list)
    for r in rows:
        by[r["animal"]].append(r)
    n_bins = 5
    hit = [0] * n_bins
    tot = [0] * n_bins
    for group in by.values():
        group.sort(key=lambda r: int(r["section_order"] or 0))
        n = len(group)
        for i, r in enumerate(group):
            b = min(n_bins - 1, int(n_bins * i / max(n, 1)))
            tot[b] += 1
            hit[b] += r["id"] in auto
    labels = ["rostral", "  |", " mid", "  |", "caudal"]
    print("  where the proposals fall along each brain:")
    for b in range(n_bins):
        rate = 100 * hit[b] / max(tot[b], 1)
        print(f"    {labels[b]:<8} {hit[b]:>3}/{tot[b]:<4} {rate:>5.1f}%  {'#' * int(rate)}")
    if tot[0] and tot[2] and (hit[0] / tot[0]) > 3 * (hit[2] / max(tot[2], 1)):
        print("  NOT uniform. Accepting all of these trims rostral coverage")
        print("  specifically - review that end rather than waving it through.")


if __name__ == "__main__":
    main()
