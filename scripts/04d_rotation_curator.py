"""Stage 4d - manual rotation curator.

The hand-drawn scan regions are one-section-accurate, so section *division* needs
no adjudication. Orientation does: `04a_reformat.py` rotates each section by the
principal axis of its tissue mask, which gets the long axis horizontal but cannot
know which way round is correct. For a roughly symmetric outline the axis is
right and the quadrant is a guess.

This is a wall, not a queue. Most sections are already correct and the task is to
*spot* the wrong ones, so showing many at once and clicking the offenders is far
faster than stepping through 2,572 one at a time. Each click rotates 90 degrees;
shift-click flips.

Rotation is stored as a correction *on top of* the automatic angle, not as an
absolute. That way re-running the reformatter with a better auto-rotation does
not invalidate the manual work.

Output: `reformatted/rotation_overrides.csv` (scene_uid, extra_rotation, flip),
read back by `04a_reformat.py --apply-overrides`.

Run:  python 04d_rotation_curator.py
      python 04d_rotation_curator.py --animal LS45
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
CURATOR_HTML = os.path.join(REFORMAT_DIR, "rotation_curator.html")

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Rotation curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);
       padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}.grow{flex:1}
.row{color:var(--dim)}.row b{color:var(--fg)}
button{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;
       padding:7px 12px;cursor:pointer;font:inherit}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
select{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit}
#wall{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;padding:14px}
.cell{border:2px solid var(--line);border-radius:8px;background:#0e1014;padding:5px;cursor:pointer;
      display:flex;flex-direction:column;align-items:center;user-select:none}
.cell:hover{border-color:var(--accent)}
.cell.changed{border-color:var(--warn);background:#1a1610}
.cell .imgwrap{width:100%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;overflow:hidden}
.cell img{max-width:100%;max-height:100%;transition:transform .12s ease}
.cap{font-size:10px;color:var(--dim);margin-top:3px;text-align:center;word-break:break-all;line-height:1.25}
.cap b{color:var(--warn)}
footer{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);
       padding:9px 16px;font-size:12px;color:var(--dim)}
kbd{display:inline-block;padding:1px 6px;border:1px solid var(--line);border-radius:4px;
    background:#1c2027;font:600 11px ui-monospace,monospace}
</style>
<header>
  <h1>Rotation curator</h1>
  <select id="animal" onchange="render()"></select>
  <span class="row"><b id="count"></b> shown</span>
  <span class="row"><b id="changed"></b> rotated</span>
  <span class="grow"></span>
  <button onclick="resetAll()">Reset visible</button>
  <button class="primary" onclick="exportCsv()">Export CSV</button>
</header>
<div id="wall"></div>
<footer>
  <kbd>click</kbd> rotate 90&deg; &middot;
  <kbd>shift+click</kbd> flip horizontally &middot;
  <kbd>alt+click</kbd> reset one &middot;
  changes autosave in this browser
</footer>
<script>
const DATA = __DATA__;
const KEY = "ls_rotation_curator_v1";
let state = JSON.parse(localStorage.getItem(KEY) || "{}");   // uid -> {r:deg, f:bool}

const el = id => document.getElementById(id);
const animals = [...new Set(DATA.map(d => d.animal))].sort((a,b)=>+a.slice(2)-+b.slice(2));
el("animal").innerHTML = ['<option value="">all animals</option>']
  .concat(animals.map(a => `<option>${a}</option>`)).join("");

function save(){ localStorage.setItem(KEY, JSON.stringify(state)); }

function get(uid){ return state[uid] || {r:0, f:false}; }

function bump(uid, e){
  e.preventDefault();
  const s = get(uid);
  if(e.altKey){ delete state[uid]; }
  else if(e.shiftKey){ state[uid] = {r:s.r, f:!s.f}; }
  else { state[uid] = {r:(s.r+90)%360, f:s.f}; }
  // Drop entries that are back to no-op, so the export stays minimal.
  const t = state[uid];
  if(t && t.r === 0 && !t.f) delete state[uid];
  save(); paint(uid);
  el("changed").textContent = Object.keys(state).length;
}

function paint(uid){
  const cell = document.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if(!cell) return;
  const s = get(uid);
  const img = cell.querySelector("img");
  img.style.transform = `rotate(${s.r}deg) scaleX(${s.f ? -1 : 1})`;
  cell.classList.toggle("changed", !!state[uid]);
  cell.querySelector(".tag").innerHTML =
    state[uid] ? `<b>${s.r}&deg;${s.f ? " flip" : ""}</b>` : "";
}

function render(){
  const a = el("animal").value;
  const rows = a ? DATA.filter(d => d.animal === a) : DATA;
  el("count").textContent = rows.length;
  el("changed").textContent = Object.keys(state).length;
  el("wall").innerHTML = rows.map(d => `
    <div class="cell" data-uid="${d.uid}" onclick="bump('${d.uid}',event)">
      <div class="imgwrap"><img src="${d.img}" loading="lazy" alt=""></div>
      <div class="cap">${d.order} &middot; ${d.uid.split('_').slice(1).join('_')}
        <span class="tag"></span></div>
    </div>`).join("");
  rows.forEach(d => paint(d.uid));
}

function resetAll(){
  const a = el("animal").value;
  const rows = a ? DATA.filter(d => d.animal === a) : DATA;
  rows.forEach(d => delete state[d.uid]);
  save(); render();
}

function exportCsv(){
  const rows = [["scene_uid","extra_rotation","flip"]].concat(
    Object.entries(state).map(([uid,s]) => [uid, s.r, s.f ? 1 : 0]));
  const b = new Blob([rows.map(r=>r.join(",")).join("\\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(b);
  a.download = "rotation_overrides.csv";
  a.click();
}
render();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None)
    args = ap.parse_args()

    if not os.path.exists(INDEX_CSV):
        raise SystemExit(f"{INDEX_CSV} not found - run 04a_reformat.py first")
    with open(INDEX_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
    if args.animal:
        rows = [r for r in rows if r["animal"] == args.animal]
    rows.sort(key=lambda r: (r["animal"], int(r["section_order"] or 0)))

    data = [{
        "uid": r["id"],
        "animal": r["animal"],
        "order": r["section_order"],
        "img": ("sections/" + r["id"] + ".png"),
    } for r in rows]

    with open(CURATOR_HTML, "w", encoding="utf-8") as fh:
        fh.write(PAGE.replace("__DATA__", json.dumps(data)))

    print(f"wrote {CURATOR_HTML}")
    print(f"  {len(data)} sections across {len({d['animal'] for d in data})} animals")
    print()
    print("Open it in a browser. Click a section to rotate it 90 degrees,")
    print("shift-click to flip, alt-click to reset. Filter by animal from the")
    print("dropdown. Export when done, save the CSV into reformatted/, then:")
    print("  python 04a_reformat.py --apply-overrides")


if __name__ == "__main__":
    main()
