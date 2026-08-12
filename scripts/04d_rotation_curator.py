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
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
INDEX_CSV = os.path.join(REFORMAT_DIR, "reformat_index.csv")
MATCH_CSV = os.path.join(OUT_ROOT, "qc", "atlasmatch", "atlas_proposals_v2.csv")
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
  <kbd>f</kbd> flip &middot; <kbd>r</kbd> reset &middot; <kbd>0</kbd> zero &middot; <kbd>x</kbd> exclude &middot;
  changes autosave
</footer>
<script>
const DATA = __DATA__;
const THUMB = __THUMB__;
const KEY = "ls_rotation_curator_v2";
let state = JSON.parse(localStorage.getItem(KEY) || "{}");   // uid -> {r:deg, f:bool}
let showRef = false;
let active = null;

const el = id => document.getElementById(id);
document.getElementById("wall").style.gridTemplateColumns =
  `repeat(auto-fill,minmax(${THUMB}px,1fr))`;

const animals = [...new Set(DATA.map(d => d.animal))].sort((a,b)=>+a.slice(2)-+b.slice(2));
el("animal").innerHTML = ['<option value="">all animals</option>']
  .concat(animals.map(a => `<option>${a}</option>`)).join("");

const save = () => localStorage.setItem(KEY, JSON.stringify(state));
const get  = uid => state[uid] || {r:0, f:false, x:false};
const isExcluded = uid => !!(state[uid] && state[uid].x);

function setState(uid, r, f, x){
  r = ((Math.round(r) % 360) + 360) % 360;
  if(x === undefined) x = isExcluded(uid);
  // Drop the entry only when it carries no information at all, so the export
  // stays minimal but an exclusion is never silently lost.
  if(r === 0 && !f && !x) delete state[uid]; else state[uid] = {r, f, x};
  save(); paint(uid); counts();
}

function toggleExclude(uid){
  const s = get(uid);
  setState(uid, s.r, s.f, !s.x);
}

function counts(){
  const vals = Object.values(state);
  el("changed").textContent = vals.filter(v => v.r || v.f).length;
  el("excl").textContent = vals.filter(v => v.x).length;
}

function toggleHide(){
  document.body.classList.toggle("hideexcl");
  const on = document.body.classList.contains("hideexcl");
  el("hideBtn").textContent = "hide excluded: " + (on ? "on" : "off");
  el("hideBtn").classList.toggle("on", on);
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
  cell.classList.toggle("changed", adjusted && !s.x);
  cell.classList.toggle("excluded", !!s.x);
  cell.querySelector(".tag").textContent =
    s.x ? "" : (adjusted ? `${s.r}\\u00B0${s.f ? " flip" : ""}` : "");
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

function render(){
  const a = el("animal").value;
  const rows = a ? DATA.filter(d => d.animal === a) : DATA;
  el("count").textContent = rows.length;
  counts();
  el("wall").innerHTML = rows.map(d => `
    <div class="cell" data-uid="${d.uid}">
      <div class="stack${showRef?' showref':''}">
        ${d.ref ? `<img class="ref" src="${d.ref}" loading="lazy" alt="">` : ""}
        <img class="sec" src="${d.img}" loading="lazy" alt="" draggable="false">
      </div>
      <div class="cap">${d.order} &middot; ${d.uid.split('_').slice(1).join('_')}
        ${d.plate ? '&middot; ' + d.plate : ''} <span class="tag"></span></div>
    </div>`).join("");
  rows.forEach(d => {
    const cell = document.querySelector(`[data-uid="${CSS.escape(d.uid)}"]`);
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
  const a = el("animal").value;
  const rows = a ? DATA.filter(d => d.animal === a) : DATA;
  // Exclusions are quality judgements made by eye and are expensive to redo, so
  // clearing them gets a confirmation that says how many. Rotations alone go
  // without one - they are cheap to re-drag.
  const nx = rows.filter(d => isExcluded(d.uid)).length;
  if(nx && !confirm(`This also clears ${nx} exclusion${nx>1?"s":""}${a?" for "+a:""}. Continue?`)) return;
  rows.forEach(d => delete state[d.uid]);
  save(); render();
}

function exportCsv(){
  const rows = [["scene_uid","extra_rotation","flip","excluded"]].concat(
    Object.entries(state).map(([uid,s]) => [uid, s.r, s.f ? 1 : 0, s.x ? 1 : 0]));
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
    ap.add_argument("--thumb", type=int, default=170,
                    help="thumbnail size in px; bigger gives finer drag control")
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

    data = []
    for r in rows:
        plate = proposed.get(r["id"])
        ref = f"plates/{plate}.png" if plate and os.path.exists(
            os.path.join(REFORMAT_DIR, "plates", plate + ".png")) else None
        data.append({
            "uid": r["id"], "animal": r["animal"], "order": r["section_order"],
            "img": f"sections/{r['id']}.png", "ref": ref, "plate": plate or "",
        })

    page = PAGE.replace("__DATA__", json.dumps(data)).replace("__THUMB__", str(args.thumb))
    with open(CURATOR_HTML, "w", encoding="utf-8") as fh:
        fh.write(page)

    with_ref = sum(1 for d in data if d["ref"])
    print(f"wrote {CURATOR_HTML}")
    print(f"  {len(data)} sections, {len({d['animal'] for d in data})} animals, "
          f"{with_ref} with a reference plate")
    print()
    print("Drag a section to rotate it freely (1 degree). Shift-drag snaps to 15.")
    print("Arrow keys nudge the last-touched section by 1 degree, 10 with shift.")
    print("Turn the reference on to see the proposed atlas plate behind it in red -")
    print("only the section rotates, so you are turning it into the atlas frame.")
    print()
    print("Right-click (or 'x') marks a section as too damaged to measure.")
    print("Excluded sections are skipped by 04a_reformat.py, so they never reach")
    print("matching, registration or counting - not filtered out later, absent.")
    print()
    print("Export when done, save next to this file, then:")
    print("  python 04a_reformat.py --apply-overrides")


if __name__ == "__main__":
    main()
