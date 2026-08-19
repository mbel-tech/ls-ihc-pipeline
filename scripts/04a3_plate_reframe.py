"""Stage 4a3 - reframe the merged atlas figures into individual plates.

`04a2_atlas_remerge.py` fixed the mechanical fault: the PDF stores each figure as
several horizontal image strips, and the original extraction treated every strip
as a plate, so 101 "plates" were really 47 figures - more than half of them
fragments cut through the middle of a section.

What it cannot fix is that **a figure often contains more than one section.**
Measured on the 47: 30 hold one section, 14 hold two, 2 hold three, 1 holds four -
about 68 actual plates. Deciding where one section ends and the next begins is an
anatomical judgement about what is a plate, not a geometric fact about the PDF, so
it is done here by eye.

The work is bounded. Boxes are **proposed** from the tissue bands in each figure,
so a figure holding one section is already correct and needs no interaction; only
the 17 multi-section figures really need looking at. The seeded plates - the ones
that can actually yield ROIs - are almost all single-section already.

Interaction:

  **drag on empty space** to draw a new plate box
  **drag inside a box** to move it, **drag near an edge or corner** to resize
  **click** a box to select, `Delete` to remove it
  `n` / `p` step through figures, `r` restores the proposed boxes for this figure

Export writes `atlas/plate_boxes.csv` - one row per box, as fractions of its
figure. `04a4_plate_rebuild.py` then re-renders those crops from the PDF at full
resolution and carries the region seeds across.

Run:  python 04a3_plate_reframe.py
"""

import argparse
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
ATLAS_DIR = os.path.join(OUT_ROOT, "atlas")
PROPOSALS = os.path.join(ATLAS_DIR, "_reframe_proposals.json")
CURATOR_HTML = os.path.join(ATLAS_DIR, "plate_reframe.html")

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Plate reframe</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;
      --ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);
       padding:9px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}.grow{flex:1}
.row{color:var(--dim)}.row b{color:var(--fg)}
button{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;
       padding:6px 10px;cursor:pointer;font:inherit}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
#wrap{display:grid;grid-template-columns:1fr 230px;gap:12px;padding:12px}
#stage{background:#0e1014;border:1px solid var(--line);border-radius:9px;overflow:auto;
       max-height:76vh;display:flex;align-items:center;justify-content:center}
canvas{display:block;cursor:crosshair;max-width:100%}
.card{border:1px solid var(--line);border-radius:9px;padding:9px;background:#0e1014;margin-bottom:9px}
.card h3{font-size:11px;margin:0 0 5px;color:var(--dim);font-weight:600;letter-spacing:.04em}
.kv{font-size:12px;color:var(--dim)}.kv b{color:var(--fg)}
#list{font:11px ui-monospace,monospace;color:var(--dim)}
#list div{padding:2px 4px;border-radius:4px;cursor:pointer}
#list div.sel{background:#1d2733;color:var(--fg)}
#strip{display:flex;gap:4px;overflow-x:auto;padding:8px 14px;border-top:1px solid var(--line);
       background:#101318}
.cell{flex:0 0 auto;width:72px;border:2px solid var(--line);border-radius:6px;padding:2px;
      background:#0e1014;cursor:pointer;user-select:none;text-align:center}
.cell:hover{border-color:var(--accent)}
.cell.active{border-color:var(--accent);box-shadow:0 0 0 2px rgba(77,163,255,.3)}
.cell.multi{border-color:var(--warn)}
.cell.edited{border-color:var(--ok)}
.cell img{width:100%;aspect-ratio:1;object-fit:contain;display:block;border-radius:3px}
.cap{font-size:9px;color:var(--dim);line-height:1.15;margin-top:1px}
footer{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);
       padding:8px 14px;font-size:12px;color:var(--dim)}
kbd{display:inline-block;padding:1px 5px;border:1px solid var(--line);border-radius:4px;
    background:#1c2027;font:600 11px ui-monospace,monospace}
</style>
<header>
  <h1>Plate reframe</h1>
  <span class="row"><b id="fid"></b></span>
  <span class="row"><b id="nfig"></b> figures</span>
  <span class="row" style="color:#d29922"><b id="nmulti"></b> multi-section</span>
  <span class="row" style="color:#3fb950"><b id="nedit"></b> edited</span>
  <span class="row"><b id="nbox"></b> boxes here</span>
  <span class="grow"></span>
  <button onclick="restore()">Restore proposed</button>
  <button onclick="delSel()">Delete box</button>
  <button class="primary" onclick="exportCsv()">Export</button>
</header>
<div id="wrap">
  <div id="stage"><canvas id="c"></canvas></div>
  <div>
    <div class="card"><h3>FIGURE</h3><div class="kv" id="info">-</div></div>
    <div class="card"><h3>PLATE BOXES</h3><div id="list"></div></div>
    <div class="card"><h3>NOTE</h3><div class="kv">
      Boxes are proposed from the tissue bands. A figure holding one section is
      already right - only the multi-section ones (amber) need attention.
    </div></div>
  </div>
</div>
<div id="strip"></div>
<footer>
  <kbd>drag empty</kbd> new box &middot; <kbd>drag inside</kbd> move &middot;
  <kbd>drag edge</kbd> resize &middot; <kbd>click</kbd> select &middot;
  <kbd>Del</kbd> delete &middot; <kbd>n</kbd>/<kbd>p</kbd> figure &middot;
  <kbd>r</kbd> restore proposed &middot; autosaves
</footer>
<script>
const FIGS = __FIGS__;
const KEY = "ls_plate_reframe_v1";
let S = JSON.parse(localStorage.getItem(KEY) || "{}");   // id -> [[x0,y0,x1,y1], ...] fractions
let idx = 0, sel = -1, drag = null;
const el = id => document.getElementById(id);
const save = () => localStorage.setItem(KEY, JSON.stringify(S));
const fig = () => FIGS[idx];
const boxes = () => (S[fig().id] || (S[fig().id] = fig().boxes.map(b => [...b])));
const edited = id => {
  const f = FIGS.find(x => x.id === id), b = S[id];
  if (!b) return false;
  return JSON.stringify(b) !== JSON.stringify(f.boxes);
};

const img = new Image();
img.onload = draw;

const HANDLE = 8;   // px, hit zone for an edge grab

function draw(){
  const c = el("c"), x = c.getContext("2d");
  if(!img.naturalWidth) return;
  // Fit to a sane on-screen size; all geometry is kept in FRACTIONS so the
  // display scale never leaks into the exported boxes.
  const maxW = 980, sc = Math.min(1, maxW / img.naturalWidth);
  c.width = Math.round(img.naturalWidth * sc);
  c.height = Math.round(img.naturalHeight * sc);
  x.drawImage(img, 0, 0, c.width, c.height);
  boxes().forEach((b, i) => {
    const [X0,Y0,X1,Y1] = [b[0]*c.width, b[1]*c.height, b[2]*c.width, b[3]*c.height];
    x.lineWidth = i === sel ? 3 : 2;
    x.strokeStyle = i === sel ? "#4da3ff" : "#3fb950";
    x.strokeRect(X0, Y0, X1-X0, Y1-Y0);
    x.fillStyle = i === sel ? "rgba(77,163,255,.12)" : "rgba(63,185,80,.07)";
    x.fillRect(X0, Y0, X1-X0, Y1-Y0);
    x.fillStyle = "#fff"; x.font = "bold 13px system-ui";
    x.fillText(String(i+1), X0+6, Y0+16);
  });
  el("nbox").textContent = boxes().length;
  el("list").innerHTML = boxes().map((b,i) =>
    `<div class="${i===sel?"sel":""}" onclick="sel=${i};draw()">#${i+1} &nbsp; `
    + `${(b[0]*100).toFixed(1)},${(b[1]*100).toFixed(1)} &rarr; `
    + `${(b[2]*100).toFixed(1)},${(b[3]*100).toFixed(1)}</div>`).join("");
}

function xy(e){
  const c = el("c"), r = c.getBoundingClientRect();
  return [(e.clientX-r.left)*c.width/r.width/c.width,
          (e.clientY-r.top)*c.height/r.height/c.height];   // fractions
}
function hit(fx, fy){
  const c = el("c"), px = fx*c.width, py = fy*c.height;
  for(let i = boxes().length-1; i >= 0; i--){
    const b = boxes()[i];
    const X0=b[0]*c.width, Y0=b[1]*c.height, X1=b[2]*c.width, Y1=b[3]*c.height;
    if(px < X0-HANDLE || px > X1+HANDLE || py < Y0-HANDLE || py > Y1+HANDLE) continue;
    const L=Math.abs(px-X0)<HANDLE, R=Math.abs(px-X1)<HANDLE;
    const T=Math.abs(py-Y0)<HANDLE, B=Math.abs(py-Y1)<HANDLE;
    if(L||R||T||B) return {i, mode:"resize", L,R,T,B};
    if(px>X0&&px<X1&&py>Y0&&py<Y1) return {i, mode:"move"};
  }
  return null;
}
el("c").addEventListener("pointerdown", e => {
  const [fx,fy] = xy(e), h = hit(fx,fy);
  if(h){ sel = h.i; drag = {...h, fx, fy, orig:[...boxes()[h.i]]}; }
  else { boxes().push([fx,fy,fx,fy]); sel = boxes().length-1;
         drag = {i:sel, mode:"resize", L:false,R:true,T:false,B:true, fx, fy,
                 orig:[...boxes()[sel]]}; }
  el("c").setPointerCapture(e.pointerId); draw(); e.preventDefault();
});
el("c").addEventListener("pointermove", e => {
  if(!drag) return;
  const [fx,fy] = xy(e), b = boxes()[drag.i], o = drag.orig;
  const dx = fx-drag.fx, dy = fy-drag.fy;
  if(drag.mode === "move"){ b[0]=o[0]+dx; b[1]=o[1]+dy; b[2]=o[2]+dx; b[3]=o[3]+dy; }
  else {
    if(drag.L) b[0]=Math.min(o[0]+dx, o[2]-0.01);
    if(drag.R) b[2]=Math.max(o[2]+dx, o[0]+0.01);
    if(drag.T) b[1]=Math.min(o[1]+dy, o[3]-0.01);
    if(drag.B) b[3]=Math.max(o[3]+dy, o[1]+0.01);
  }
  for(let k=0;k<4;k++) b[k]=Math.max(0, Math.min(1, b[k]));
  draw();
});
el("c").addEventListener("pointerup", () => {
  if(drag){
    const b = boxes()[drag.i];
    // A stray click leaves a degenerate box; drop it rather than exporting it.
    if(Math.abs(b[2]-b[0]) < 0.02 || Math.abs(b[3]-b[1]) < 0.02){
      boxes().splice(drag.i,1); sel = -1;
    }
    drag = null; save(); paintCell(fig().id); draw();
  }
});

function delSel(){ if(sel>=0){ boxes().splice(sel,1); sel=-1; save(); paintCell(fig().id); draw(); } }
function restore(){ S[fig().id] = fig().boxes.map(b=>[...b]); sel=-1; save(); paintCell(fig().id); draw(); }
function select(i){ idx=i; sel=-1; const f=fig();
  el("fid").textContent = f.id;
  el("info").innerHTML = `<b>${f.id}</b><br>page ${f.page} &middot; ${f.strips} strip(s)`
    + `<br>${f.w} &times; ${f.h} px<br>${f.boxes.length} proposed`;
  img.src = f.img;
  document.querySelectorAll(".cell").forEach(c =>
    c.classList.toggle("active", c.dataset.id === f.id));
  document.querySelector(`[data-id="${CSS.escape(f.id)}"]`)
    ?.scrollIntoView({inline:"center", block:"nearest"});
  draw();
}
function cellCls(f){
  return (edited(f.id) ? "edited " : "") + (f.boxes.length > 1 ? "multi" : "");
}
function paintCell(id){
  const c = document.querySelector(`[data-id="${CSS.escape(id)}"]`);
  const f = FIGS.find(x=>x.id===id);
  if(c && f){
    c.className = "cell " + cellCls(f) + (fig().id===id ? " active" : "");
    c.querySelector(".cap").innerHTML = `${f.id.replace("mplate_","")}<br>${(S[f.id]||f.boxes).length} box`;
  }
  counts();
}
function counts(){
  el("nfig").textContent = FIGS.length;
  el("nmulti").textContent = FIGS.filter(f => (S[f.id]||f.boxes).length > 1).length;
  el("nedit").textContent = FIGS.filter(f => edited(f.id)).length;
}
function build(){
  el("strip").innerHTML = FIGS.map((f,i) =>
    `<div class="cell ${cellCls(f)}" data-id="${f.id}" onclick="select(${i})">
      <img src="${f.img}" loading="lazy" alt="">
      <div class="cap">${f.id.replace("mplate_","")}<br>${(S[f.id]||f.boxes).length} box</div>
    </div>`).join("");
  counts();
  select(0);
}
addEventListener("keydown", e => {
  if(e.key === "n" && idx < FIGS.length-1) select(idx+1);
  else if(e.key === "p" && idx > 0) select(idx-1);
  else if(e.key === "Delete" || e.key === "Backspace"){ delSel(); e.preventDefault(); }
  else if(e.key === "r") restore();
});
function exportCsv(){
  const rows = [["figure_id","page","box","x0_frac","y0_frac","x1_frac","y1_frac","edited"]];
  for(const f of FIGS){
    (S[f.id] || f.boxes).forEach((b,i) =>
      rows.push([f.id, f.page, i+1, b[0].toFixed(5), b[1].toFixed(5),
                 b[2].toFixed(5), b[3].toFixed(5), edited(f.id)?1:0]));
  }
  const blob = new Blob([rows.map(r=>r.join(",")).join("\\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "plate_boxes.csv"; a.click();
}
build();
</script>
"""


def main():
    argparse.ArgumentParser().parse_args()
    if not os.path.exists(PROPOSALS):
        raise SystemExit(f"{PROPOSALS} not found - run 04a2_atlas_remerge.py first")
    with open(PROPOSALS, encoding="utf-8") as fh:
        figs = json.load(fh)

    with open(CURATOR_HTML, "w", encoding="utf-8") as fh:
        fh.write(PAGE.replace("__FIGS__", json.dumps(figs)))

    multi = [f for f in figs if len(f["boxes"]) > 1]
    total = sum(len(f["boxes"]) for f in figs)
    print(f"wrote {CURATOR_HTML}")
    print(f"  {len(figs)} merged figures -> {total} proposed plate boxes")
    print(f"  {len(multi)} figures hold more than one section and are flagged amber")
    print()
    print("Figures holding a single section are already correct - the proposal is")
    print("the whole section - so only the amber ones need looking at.")
    print()
    print("Drag on empty space for a new box, inside one to move it, near an edge to")
    print("resize. Del removes the selected box, r restores the proposal.")
    print()
    print("Export writes atlas/plate_boxes.csv, then run 04a4_plate_rebuild.py to")
    print("re-render the crops from the PDF and carry the region seeds across.")


if __name__ == "__main__":
    main()
