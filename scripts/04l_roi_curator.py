"""Stage 4l - assign a plate, place landmarks, warp the atlas regions onto the section.

This is SHARCQ's workflow (Lauridsen et al. 2022, eNeuro), rebuilt for the salmon
atlas. SHARCQ cannot be used directly - MATLAB, and bound to the Allen or
Franklin-Paxinos 3D atlas - but its shape is the right one, and the important
thing about it is what it does **not** automate: its user "must scroll to the
correct AP coordinate and DV/ML tilt" by eye, then clicks numbered corresponding
points between the slice and the atlas. What it automates is the landmark
registration, the warping, and the per-region counting.

That matters here because automatic level assignment has now been measured to
fail twice on this data, for a reason in the data rather than in the algorithm:

  * `04c`, silhouette IoU: correlation between serial order and best-matching
    plate is -0.05, 0.00, 0.17, -0.04;
  * giRAff's method, registered-intensity cross-correlation: -0.18 to +0.09 in
    both polarities.

See REFERENCES.md. The published tool for this exact task picks the plate by
hand, so this does too.

Interaction
-----------

  **Scrub the plate slider** until the plate matches the section, then **click
  matching points** - once on the section, once on the plate, alternating. Three
  pairs are the minimum for an affine; more improves it.

  **Press `Rotate`, then drag left or right on the section to tilt it.** Rotation
  is a mode rather than a gesture, so dragging can never be mistaken for placing
  a landmark - while it is on, clicks on the section are inert. Hold shift for
  fine control. The tilt stays a **draft** until `Save tilt`; leaving the tool
  discards it, and `Restore original tilt` (or `r`) puts the section back the way
  `04a_reformat` produced it, which is exactly rot = 0. The rotation is a
  **viewing aid and nothing else** - every stored coordinate stays in the
  unrotated reformatted frame, so the transform, the residuals and all three
  exports are identical whether the section was turned or not. The angle is
  carried in `roi_plates.csv` as `view_rotation_deg` for provenance only.

  **`f` marks a section favourite** - the subset worth carrying into actual
  quantification. It is orthogonal to the plate assignment, because a section can
  be worth quantifying before anyone has landmarked it, so it sets no other flag
  and is reported on its own. "favourites only" narrows the strip to that subset.

  **The plate and the section step independently.** `z`/`x` move through
  sections and leave the plate where it is - consecutive sections are at
  neighbouring levels, so the plate rarely needs to move more than a notch.
  Returning to a section that was already assigned or landmarked does show its
  own plate again, because that is a recorded decision rather than a position.

  From three pairs on, the atlas **region seeds are warped live onto the section**
  in their atlas colours. That is the actual deliverable: it shows immediately
  whether the registration is placing Dl, Dm, Vv and POA where they belong, which
  is the only check that matters.

  The residual per landmark is shown, so a mis-clicked pair is visible as a large
  error rather than quietly degrading the fit.

Scope, deliberately bounded
---------------------------

**Only 24 of the 101 plates carry region seeds** - plate_009 to plate_032,
telencephalon and POA, 316 seeds over 8 regions (Dl 142, Dm 114, Vv 16, POA 16,
Vd 10, Vl 10, Vs 4, Vc 4). A section assigned to any other plate has no regions to
receive, so the tool marks those plates and there is no reason to place landmarks
on such a section. The working subset is therefore self-selecting: it is whatever
lands in that 24-plate window.

Affine below six points, thin-plate spline above
------------------------------------------------

Three or more pairs determine an **affine** by least squares. From **six** pairs
the tool switches to a **thin-plate spline**, and the header says which is live.

The gate is the whole argument. A TPS interpolates its landmarks *exactly*, so
its residual is zero by construction and tells you nothing; with 3-4 points it
would fit them perfectly and invent deformation everywhere else from almost no
evidence. From six well-spread points the interpolation is constrained by enough
real correspondences to be worth having - and an affine genuinely cannot follow
the local distortion that sectioning and mounting put into a slice, which is why
BigWarp and VisuAlign both use a TPS for exactly this task.

So: read the residual while it is an affine, and read the **overlay** once it is a
spline. `04e_register_elastix.py` remains available for an automatic B-spline
refinement once a plate assignment is trusted.

**The plate is shown in its ORIGINAL form, not reformatted.** The seeds are
recorded as fractions of the original plate, so using the original avoids
carrying them through the reformat's rotate-crop-pad-resize chain - a transform
that `04e` notes is not invertible from the index alone.

Three outputs, because there are three separable decisions
----------------------------------------------------------

`roi_plates.csv`     one row per section the operator has *touched*, with its
                     plate and a `status` of `registered` (3+ landmarks),
                     `plate_only` (plate chosen, not landmarked) or `no_roi`
                     (deliberately marked as having nothing to measure).
`roi_landmarks.csv`  every landmark pair, with its residual. Registered only.
`roi_regions.csv`    warped seed positions in the section's reformatted frame.

**A plate assignment is a judgement in its own right.** An earlier version wrote
nothing for a section with fewer than three landmarks, which discarded exactly
the case where the operator had looked at a section and decided it was not worth
landmarking. `assigned` is set only by a real slider move or an explicit button -
never by merely selecting a section - so an untouched section still says
nothing.

Run:  python 04l_roi_curator.py
      python 04l_roi_curator.py --animal LS45
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
# Which plate set to use, from config. The two sets reuse the same plate_NNN
# names for different images, so this must not be hard-coded in two places.
PLATE_SET = CONFIG.get("atlas_plate_set", {}).get("dir", "plates")
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", PLATE_SET)
CURATOR_HTML = os.path.join(REFORMAT_DIR, "roi_curator.html")

PAGE = """<!doctype html>
<meta charset="utf-8"><title>ROI curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;
      --ok:#3fb950;--warn:#d29922;--done:#7c5cff}
*{box-sizing:border-box}
/* The whole tool is one screen. body is a flex column, the panes take what is
   left, and only the side card and the strip scroll - inside themselves. */
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;
     display:flex;flex-direction:column;overflow:hidden}
header{flex:0 0 auto;background:var(--bg);border-bottom:1px solid var(--line);
       padding:7px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}.grow{flex:1}
.row{color:var(--dim)}.row b{color:var(--fg)}
button,select{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;
       padding:6px 10px;cursor:pointer;font:inherit}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
#panes{flex:1 1 auto;min-height:0;display:grid;grid-template-columns:1fr 1fr 250px;
       grid-template-rows:minmax(0,1fr);gap:10px;padding:10px}
.pane{position:relative;background:#0e1014;border:1px solid var(--line);border-radius:9px;
      overflow:hidden;min-width:0;min-height:0}
.pane h2{position:absolute;top:6px;left:8px;margin:0;font-size:11px;color:var(--dim);
         z-index:3;pointer-events:none;text-shadow:0 0 6px #000}
canvas{display:block;width:100%;height:100%;object-fit:contain;cursor:crosshair;
       user-select:none;-webkit-user-drag:none}
#cSec.rotmode{cursor:ew-resize}
#cSec.rotating{cursor:ew-resize}
button[disabled]{opacity:.4;cursor:default}
button[disabled]:hover{border-color:var(--line)}
#side{display:flex;flex-direction:column;gap:9px;min-height:0;overflow-y:auto}
.card{border:1px solid var(--line);border-radius:9px;padding:9px;background:#0e1014}
.card h3{font-size:11px;margin:0 0 5px;color:var(--dim);font-weight:600;letter-spacing:.04em}
.kv{font-size:12px;color:var(--dim)}.kv b{color:var(--fg)}
input[type=range]{width:100%}
.unlab{color:var(--warn);font-size:11px}
.lab{color:var(--ok);font-size:11px}
#lmlist{font:11px ui-monospace,monospace;color:var(--dim);max-height:130px;overflow-y:auto}
#lmlist div{display:flex;justify-content:space-between}
#lmlist .bad{color:#ff6b5e}
#strip{flex:0 0 auto;display:flex;gap:4px;overflow-x:auto;overflow-y:hidden;
       padding:7px 14px;border-top:1px solid var(--line);background:#101318}
.cell{flex:0 0 auto;width:74px;border:2px solid var(--line);border-radius:6px;padding:2px;
      background:#0e1014;cursor:pointer;user-select:none}
.cell:hover{border-color:var(--accent)}
.cell.active{border-color:var(--accent);box-shadow:0 0 0 2px rgba(77,163,255,.3)}
.cell.done{border-color:var(--done);background:#141026}
.cell.plateonly{border-color:var(--accent);background:#0d1520}
.cell.noroi{border-color:#3a3f47;opacity:.55}
.cell.fav{box-shadow:inset 0 0 0 2px #e3b341}
.fav-on{border-color:#e3b341 !important;color:#e3b341}
.mode-on{border-color:var(--accent) !important;color:var(--accent)}
label.chk{color:var(--dim);font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer}
.cell img{width:100%;aspect-ratio:1;object-fit:contain;display:block;border-radius:3px}
.cap{font-size:9px;color:var(--dim);text-align:center;line-height:1.15;margin-top:1px}
footer{flex:0 0 auto;background:var(--bg);border-top:1px solid var(--line);
       padding:6px 14px;font-size:12px;color:var(--dim)}
kbd{display:inline-block;padding:1px 5px;border:1px solid var(--line);border-radius:4px;
    background:#1c2027;font:600 11px ui-monospace,monospace}
</style>
<header>
  <h1>ROI curator</h1>
  <select id="animal" onchange="render(); this.blur()"></select>
  <span class="row"><b id="nsec"></b> shown</span>
  <span class="row" style="color:#7c5cff"><b id="ndone"></b> registered</span>
  <span class="row" style="color:#4da3ff"><b id="nassign"></b> plate only</span>
  <span class="row" style="color:#9aa0a8"><b id="nnoroi"></b> no ROI</span>
  <span class="row" style="color:#e3b341"><b id="nfav"></b> favourite</span>
  <label class="chk"><input type="checkbox" id="favOnly" onchange="render(); this.blur()">favourites only</label>
  <span class="row"><b id="npair"></b> pairs on this section</span>
  <span class="row" id="fit"></span>
  <span class="grow"></span>
  <button onclick="markAssigned()">Assign plate</button>
  <button id="rotBtn" onclick="toggleRotMode()">Rotate</button>
  <button id="rotSave" onclick="saveRot()">Save tilt</button>
  <button id="rotReset" onclick="restoreTilt()">Restore original tilt</button>
  <button id="favBtn" onclick="toggleFav()">Favourite</button>
  <button id="noroiBtn" onclick="toggleNoRoi()">No ROI here</button>
  <button onclick="undoPt()">Undo point</button>
  <button onclick="clearPts()">Clear points</button>
  <button class="primary" onclick="exportCsv()">Export</button>
</header>
<div id="panes">
  <div class="pane"><h2>SECTION - click to place a point</h2>
    <canvas id="cSec" onclick="clickSec(event)" onmousedown="secDown(event)"></canvas></div>
  <div class="pane"><h2>ATLAS PLATE - click the matching point</h2>
    <canvas id="cPl" onclick="clickPl(event)"></canvas></div>
  <div id="side">
    <div class="card"><h3>SECTION</h3><div class="kv" id="secInfo">-</div>
      <div class="kv" id="rotInfo"></div></div>
    <div class="card"><h3>PLATE</h3>
      <input type="range" id="slider" min="0" max="0" value="0" oninput="onSlideUser(this.value)" onchange="this.blur()">
      <div class="kv"><b id="plName">-</b></div>
      <div id="plLab"></div>
    </div>
    <div class="card"><h3>LANDMARKS</h3>
      <div class="kv" id="lmHint">click section, then plate</div>
      <div id="lmlist"></div>
    </div>
    <div class="card"><h3>REGIONS WARPED</h3>
      <div class="kv" id="regInfo">needs 3 pairs</div></div>
  </div>
</div>
<div id="strip"></div>
<footer>
  <kbd>click</kbd> section then plate to add a pair &middot;
  <kbd>&larr;</kbd><kbd>&rarr;</kbd> plate &middot; <kbd>u</kbd> undo &middot;
  <kbd>z</kbd>/<kbd>x</kbd> previous / next section (the plate stays put) &middot;
  <kbd>Rotate</kbd> then drag the section left/right (<kbd>shift</kbd> fine), <kbd>Save tilt</kbd> to keep it,
  <kbd>r</kbd> restores the original &middot;
  <kbd>f</kbd> favourite &middot;
  3 pairs for an affine, 6 for a spline &middot;
  <span style="color:#7c5cff">purple</span> = registered &middot;
  <span style="color:#4da3ff">blue</span> = plate assigned only &middot;
  <span style="color:#e3b341">gold edge</span> = favourite &middot;
  faded = marked no-ROI &middot; autosaves
</footer>
<script>
const DATA = __DATA__;      // [{uid, animal, order, img}]
const PLATES = __PLATES__;  // [{id, img, w, h, labelled, seeds:[{region,xf,yf,hex}]}]
// Which plate set these ids belong to. plate_012 exists in every set and is a
// DIFFERENT image in each, so every export carries this and a landmark file can
// never be silently matched against the wrong plates.
const PLATE_SET = __PLATESET__;
const KEY = "ls_roi_curator_v1";
let S = JSON.parse(localStorage.getItem(KEY) || "{}");   // uid -> {plate, pairs:[[sx,sy,px,py]]}
let active = null, pending = null;   // pending section point awaiting its plate partner
const el = id => document.getElementById(id);
const save = () => localStorage.setItem(KEY, JSON.stringify(S));
const animals = [...new Set(DATA.map(d=>d.animal))].sort((a,b)=>+a.slice(2)-+b.slice(2));
el("animal").innerHTML = animals.map(a=>`<option>${a}</option>`).join("");
el("slider").max = PLATES.length-1;
const inAnimal = () => DATA.filter(d=>d.animal===el("animal").value);
// The favourites filter narrows the strip to the subset chosen for
// quantification, so `rows` - which also drives z/x and the counts - honours it.
const rows = () => inAnimal()
  .filter(d => !el("favOnly").checked || S[d.uid]?.fav)
  .sort((a,b)=>a.order-b.order);
// `assigned` is set only by a real slider move or an explicit button, never by
// merely selecting a section - otherwise clicking through the strip would record
// a plate_001 assignment for everything it touched.
const st = uid => S[uid] || (S[uid] = {plate: 0, pairs: [], assigned: false,
                                       noroi: false, fav: false, rot: 0});

const secImg = new Image();
secImg.onload = drawSec;

// All 101 plates preloaded - 7.4 MB total, median 71 KB. Setting plImg.src on
// every slider step made each step wait on a disk read and a JPEG decode, which
// is what made scrubbing feel heavy. Held as decoded Image objects instead, so
// changing plate is just a canvas draw.
const PLIMG = PLATES.map(p => { const im = new Image(); im.src = p.img; return im; });
const plateImg = () => PLIMG[st(active).plate];

// ---- affine from >=3 correspondences, least squares ------------------------
// A thin-plate spline would fit the clicked points exactly and invent
// deformation between them that nothing measured. With 3-6 landmarks an affine
// is the honest transform, and it is the class SHARCQ uses from the same input.
function solve3(A, b){
  const M = A.map((r,i)=>[...r, b[i]]);
  for(let c=0;c<3;c++){
    let p=c; for(let r=c+1;r<3;r++) if(Math.abs(M[r][c])>Math.abs(M[p][c])) p=r;
    if(Math.abs(M[p][c])<1e-12) return null;
    [M[c],M[p]]=[M[p],M[c]];
    for(let r=0;r<3;r++){ if(r===c) continue;
      const f=M[r][c]/M[c][c]; for(let k=c;k<4;k++) M[r][k]-=f*M[c][k]; }
  }
  return [M[0][3]/M[0][0], M[1][3]/M[1][1], M[2][3]/M[2][2]];
}
function affine(pairs){          // plate (px,py) -> section (sx,sy)
  if(pairs.length < 3) return null;
  const N=[[0,0,0],[0,0,0],[0,0,0]], bx=[0,0,0], by=[0,0,0];
  for(const [sx,sy,px,py] of pairs){
    const v=[px,py,1];
    for(let i=0;i<3;i++){ for(let j=0;j<3;j++) N[i][j]+=v[i]*v[j];
      bx[i]+=v[i]*sx; by[i]+=v[i]*sy; }
  }
  const a=solve3(N.map(r=>[...r]),bx), d=solve3(N.map(r=>[...r]),by);
  return (a&&d) ? {kind:"affine", a, d} : null;
}

// ---- thin-plate spline, used from TPS_MIN pairs upward ----------------------
// An affine cannot follow the local distortion that sectioning and mounting put
// into a slice; a TPS can, and it is what BigWarp and VisuAlign use for exactly
// this job. The reason it is gated rather than always on: a TPS interpolates the
// landmarks EXACTLY, so with 3-4 points it fits them perfectly and invents
// deformation everywhere else from almost no evidence. From six well-spread
// points the interpolation is constrained by enough real correspondences to be
// worth having.
const TPS_MIN = 6;
function solveN(A, b){                       // Gaussian elimination with pivoting
  const n=A.length, M=A.map((r,i)=>[...r,b[i]]);
  for(let c=0;c<n;c++){
    let p=c; for(let r=c+1;r<n;r++) if(Math.abs(M[r][c])>Math.abs(M[p][c])) p=r;
    if(Math.abs(M[p][c])<1e-10) return null;
    [M[c],M[p]]=[M[p],M[c]];
    for(let r=0;r<n;r++){ if(r===c) continue;
      const f=M[r][c]/M[c][c]; for(let k=c;k<=n;k++) M[r][k]-=f*M[c][k]; }
  }
  return M.map((r,i)=>r[n]/r[i]);
}
const U = r2 => r2 < 1e-12 ? 0 : r2 * Math.log(r2);   // r^2 log r^2, the 2-D TPS kernel
function tps(pairs){
  const n=pairs.length; if(n < TPS_MIN) return null;
  const P=pairs.map(p=>[p[2],p[3]]), S=pairs.map(p=>[p[0],p[1]]);
  const m=n+3, A=Array.from({length:m},()=>new Array(m).fill(0));
  for(let i=0;i<n;i++){
    for(let j=0;j<n;j++){
      const dx=P[i][0]-P[j][0], dy=P[i][1]-P[j][1];
      A[i][j]=U(dx*dx+dy*dy);
    }
    A[i][n]=1; A[i][n+1]=P[i][0]; A[i][n+2]=P[i][1];
    A[n][i]=1; A[n+1][i]=P[i][0]; A[n+2][i]=P[i][1];
  }
  const bx=new Array(m).fill(0), by=new Array(m).fill(0);
  for(let i=0;i<n;i++){ bx[i]=S[i][0]; by[i]=S[i][1]; }
  const wx=solveN(A.map(r=>[...r]),bx), wy=solveN(A.map(r=>[...r]),by);
  return (wx&&wy) ? {kind:"tps", P, wx, wy, n} : null;
}
function tpsApply(T,px,py){
  let X=T.wx[T.n]+T.wx[T.n+1]*px+T.wx[T.n+2]*py;
  let Y=T.wy[T.n]+T.wy[T.n+1]*px+T.wy[T.n+2]*py;
  for(let i=0;i<T.n;i++){
    const dx=px-T.P[i][0], dy=py-T.P[i][1], u=U(dx*dx+dy*dy);
    X+=T.wx[i]*u; Y+=T.wy[i]*u;
  }
  return [X,Y];
}

// The transform actually used: TPS once there are enough points, affine below.
function transform(pairs){ return tps(pairs) || affine(pairs); }
function apply(T,px,py){
  return T.kind==="tps" ? tpsApply(T,px,py)
                        : [T.a[0]*px+T.a[1]*py+T.a[2], T.d[0]*px+T.d[1]*py+T.d[2]];
}

// ---- drawing ---------------------------------------------------------------
function fit(c, img){ c.width=img.naturalWidth||600; c.height=img.naturalHeight||600; }
// ---- rotation, as a VIEWING aid only ---------------------------------------
// Every stored coordinate - landmarks, pending points, warped seeds - stays in
// the UNROTATED reformatted frame. Only the drawing and the click mapping know
// the angle. That is the whole point: the transform, the residuals and all
// three exports are byte-identical whether the operator rotated or not, so
// turning the section to see it better can never move a landmark.
//
// The canvas is the DIAGONAL of the image, not the image, so a rotated section
// never has its corners clipped.
function secGeom(){
  const w=secImg.naturalWidth||256, h=secImg.naturalHeight||256;
  const a=effRot()*Math.PI/180;
  return {w, h, D:Math.ceil(Math.hypot(w,h)), a, cos:Math.cos(a), sin:Math.sin(a)};
}
const img2can = (x,y,g) => { const dx=x-g.w/2, dy=y-g.h/2;
  return [g.D/2 + dx*g.cos - dy*g.sin, g.D/2 + dx*g.sin + dy*g.cos]; };
const can2img = (X,Y,g) => { const dx=X-g.D/2, dy=Y-g.D/2;
  return [g.w/2 + dx*g.cos + dy*g.sin, g.h/2 - dx*g.sin + dy*g.cos]; };

function drawSec(){
  const c=el("cSec"), x=c.getContext("2d"); if(!secImg.naturalWidth) return;
  const g=secGeom();
  c.width=g.D; c.height=g.D;
  x.clearRect(0,0,g.D,g.D);
  x.save(); x.translate(g.D/2,g.D/2); x.rotate(g.a);
  x.drawImage(secImg, -g.w/2, -g.h/2);
  x.restore();
  const s=st(active), T=transform(s.pairs);
  if(T){                                   // warped atlas seeds - the deliverable
    const P=PLATES[s.plate];
    for(const sd of P.seeds){
      const [ix,iy]=apply(T, sd.xf*P.w, sd.yf*P.h);
      const [X,Y]=img2can(ix,iy,g);
      x.beginPath(); x.arc(X,Y,7,0,6.284); x.fillStyle=sd.hex||"#4da3ff"; x.globalAlpha=.85; x.fill();
      x.globalAlpha=1; x.lineWidth=2; x.strokeStyle="#000"; x.stroke();
      x.fillStyle="#fff"; x.font="bold 13px system-ui"; x.fillText(sd.region, X+10, Y+4);
    }
  }
  s.pairs.forEach(([sx,sy],i)=>{ const [X,Y]=img2can(sx,sy,g); mark(x,X,Y,i+1,"#4da3ff"); });
  if(pending){ const [X,Y]=img2can(pending[0],pending[1],g);
               mark(x,X,Y,s.pairs.length+1,"#d29922"); }
}
function drawPl(){
  const c=el("cPl"), x=c.getContext("2d");
  if(!active) return;
  const img=plateImg();
  if(!img.naturalWidth){ img.addEventListener("load", drawPl, {once:true}); return; }
  fit(c,img); x.drawImage(img,0,0);
  const s=st(active), P=PLATES[s.plate];
  for(const sd of P.seeds){
    const X=sd.xf*c.width, Y=sd.yf*c.height;
    x.beginPath(); x.arc(X,Y,6,0,6.284); x.fillStyle=sd.hex||"#4da3ff"; x.globalAlpha=.8; x.fill();
    x.globalAlpha=1; x.lineWidth=1.5; x.strokeStyle="#000"; x.stroke();
  }
  s.pairs.forEach(([,,px,py],i)=>mark(x,px,py,i+1,"#4da3ff"));
}
function mark(x,X,Y,n,col){
  x.beginPath(); x.arc(X,Y,9,0,6.284); x.lineWidth=3; x.strokeStyle=col; x.stroke();
  x.fillStyle=col; x.font="bold 15px system-ui"; x.fillText(n, X+11, Y-9);
}
// `object-fit:contain` fits the bitmap inside the element and centres it, so the
// element box is NOT the drawn area - there is a letterbox on two sides whose
// size depends on the aspect ratios. Scaling by width alone, as this used to,
// would put every landmark off-target by the size of that band. Undo the fit.
const canvasXY = (c,e) => {
  const r=c.getBoundingClientRect(), k=Math.min(r.width/c.width, r.height/c.height);
  const ox=r.left+(r.width-c.width*k)/2, oy=r.top+(r.height-c.height*k)/2;
  return [(e.clientX-ox)/k, (e.clientY-oy)/k];
};

// Rotating and placing a landmark are separated by the MODE, not by watching how
// far the mouse moved. An earlier version guessed from the drag distance and
// suppressed the click that followed; once `secDown` also had to return early
// when the tool was closed, that flag could be left set from the last rotation
// and would silently swallow the next genuine click. The mode makes it
// unnecessary, so it is gone: `live` below is local to one drag and never
// consulted by the click handler.
let rotDrag=null, rotMode=false, draftRot=null;
const DEG_PER_PX = 0.4, DEG_PER_PX_FINE = 0.05;
// The angle actually drawn: the uncommitted draft while the tool is open,
// otherwise whatever was saved for this section.
const effRot = () => (rotMode && draftRot!==null) ? draftRot : (st(active).rot||0);

// Rotate is a MODE, so dragging cannot be mistaken for placing a landmark and
// vice versa. While it is on, clicks on the section do not place points.
function toggleRotMode(){
  if(!active) return;
  rotMode = !rotMode;
  draftRot = null;            // leaving the tool discards an uncommitted tilt
  el("cSec").classList.toggle("rotmode", rotMode);
  drawSec(); status();
}
function saveRot(){
  if(!active || draftRot===null) return;
  st(active).rot = draftRot; draftRot = null; save(); drawSec(); status(); paintCell(active);
}
// "Original" is the orientation 04a_reformat produced - the frame every stored
// coordinate already lives in - so restoring it is exactly rot = 0. It commits
// immediately, and discards any draft, because there is nothing to preview.
function restoreTilt(){
  if(!active) return;
  draftRot = null; st(active).rot = 0; save(); drawSec(); status(); paintCell(active);
}
function secDown(e){
  if(!active || !rotMode || e.button!==0) return;
  rotDrag={x:e.clientX, rot:effRot(), live:false}; e.preventDefault();
}
addEventListener("mousemove", e=>{
  if(!rotDrag) return;
  const dx=e.clientX-rotDrag.x;
  if(!rotDrag.live && Math.abs(dx)<=3) return;   // ignore the jitter of a plain press
  rotDrag.live = true;
  el("cSec").classList.add("rotating");
  const per = e.shiftKey ? DEG_PER_PX_FINE : DEG_PER_PX;   // shift = fine
  draftRot = ((rotDrag.rot + dx*per) % 360 + 360) % 360;
  drawSec(); status();
});
// No save here - the tilt stays a draft until Save tilt is pressed.
addEventListener("mouseup", ()=>{ rotDrag=null; el("cSec").classList.remove("rotating"); });

function clickSec(e){
  if(!active) return;
  if(rotMode) return;                          // the rotate tool owns the mouse
  pending = can2img(...canvasXY(el("cSec"), e), secGeom());
  drawSec(); status();
}
function clickPl(e){
  if(!active || !pending) return;
  const [px,py]=canvasXY(el("cPl"), e);
  st(active).pairs.push([pending[0],pending[1],px,py]); pending=null;
  save(); drawSec(); drawPl(); status(); paintCell(active);
}
function undoPt(){
  if(!active) return;
  if(pending){ pending=null; } else st(active).pairs.pop();
  save(); drawSec(); drawPl(); status(); paintCell(active);
}
function clearPts(){ if(!active) return; st(active).pairs=[]; pending=null; save();
  drawSec(); drawPl(); status(); paintCell(active); }

function status(){
  const s=st(active), T=transform(s.pairs);
  el("npair").textContent = s.pairs.length;
  el("lmHint").textContent = pending ? "now click the matching point on the plate"
                                     : "click section, then plate";
  // Residual per landmark: a mis-clicked pair shows as a large error instead of
  // quietly dragging the whole fit.
  let html="";
  if(T){
    let tot=0;
    s.pairs.forEach(([sx,sy,px,py],i)=>{
      const [X,Y]=apply(T,px,py), r=Math.hypot(X-sx,Y-sy); tot+=r;
      html += `<div class="${r>25?"bad":""}"><span>#${i+1}</span><span>${r.toFixed(1)} px</span></div>`;
    });
    el("fit").innerHTML = T.kind==="tps"
      ? `<b style="color:#7c5cff">thin-plate spline</b> on ${s.pairs.length} points `
        + `&middot; residual is 0 by construction`
      : `<b>affine</b> &middot; mean residual <b>${(tot/s.pairs.length).toFixed(1)} px</b>`
        + ` &middot; ${TPS_MIN - s.pairs.length} more point${TPS_MIN-s.pairs.length===1?"":"s"} for a spline`;
    const P=PLATES[s.plate];
    el("regInfo").innerHTML = P.seeds.length
      ? `<b>${P.seeds.length}</b> seeds warped: ${[...new Set(P.seeds.map(x=>x.region))].join(", ")}`
      : "<span class='unlab'>this plate has no region seeds</span>";
  } else {
    el("fit").textContent = "";
    el("regInfo").textContent = `needs 3 pairs for an affine, ${TPS_MIN} for a spline `
      + `(have ${s.pairs.length})`;
    s.pairs.forEach((_,i)=>html+=`<div><span>#${i+1}</span><span>-</span></div>`);
  }
  el("lmlist").innerHTML = html;
  const sa = st(active);
  el("noroiBtn").textContent = sa.noroi ? "No ROI here ✓" : "No ROI here";
  el("noroiBtn").style.borderColor = sa.noroi ? "#3fb950" : "";
  el("favBtn").textContent = sa.fav ? "Favourite ★" : "Favourite";
  el("favBtn").classList.toggle("fav-on", !!sa.fav);
  // Three separate facts: is the tool open, is there an uncommitted tilt, and
  // what is actually being drawn. The buttons only offer what is available.
  const saved = sa.rot||0, dirty = draftRot!==null && Math.abs(draftRot-saved) > 1e-9;
  el("rotBtn").textContent = rotMode ? "Rotate ✓" : "Rotate";
  el("rotBtn").classList.toggle("mode-on", rotMode);
  el("rotSave").disabled  = !dirty;
  el("rotReset").disabled = !(saved || dirty);
  const dim = t => `<span style="color:#9aa0a8">${t}</span>`;
  el("rotInfo").innerHTML =
      dirty   ? `tilt <b>${effRot().toFixed(1)}&deg;</b> <span class="unlab">unsaved - press Save tilt</span>`
    : rotMode ? `tilt <b>${saved.toFixed(1)}&deg;</b> ` + dim("drag left/right &middot; shift = fine")
    : saved   ? `tilted <b>${saved.toFixed(1)}&deg;</b> ` + dim("view only, landmarks unaffected")
    : dim("press Rotate to tilt the view");
}

// Called by the slider's oninput, which fires ONLY on user interaction -
// setting .value from script does not dispatch it. That is what makes the
// distinction between "the operator chose this plate" and "this section has
// never been looked at" reliable.
function onSlideUser(v){
  const s=st(active); s.assigned=true; save(); onSlide(v); paintCell(active);
}
function markAssigned(){ if(active){ st(active).assigned=true; save(); paintCell(active); status(); } }
// Favourite marks the subset chosen for actual quantification. It is ORTHOGONAL
// to the plate assignment - a section can be worth quantifying before anyone has
// landmarked it - so it sets no other flag and the export carries it on its own.
function toggleFav(){
  if(!active) return;
  const s=st(active); s.fav=!s.fav; save(); paintCell(active); status();
}
function toggleNoRoi(){
  if(!active) return;
  const s=st(active); s.noroi=!s.noroi; if(s.noroi) s.assigned=true;
  save(); paintCell(active); status();
}

function onSlide(v){
  const s=st(active); s.plate=+v; save();
  const P=PLATES[+v];
  el("plName").textContent = P.id;
  el("plLab").innerHTML = P.labelled
    ? `<span class="lab">${P.seeds.length} region seeds: ${[...new Set(P.seeds.map(x=>x.region))].join(", ")}</span>`
    : `<span class="unlab">no region labels on this plate</span>`;
  drawPl(); status();
  // NO render() here. render -> select -> onSlide -> render was a cycle: on load
  // it recursed until the stack blew, leaving the page half-built with dead
  // handlers - which looks exactly like "the buttons do nothing".
}

function select(uid, keep){
  active = uid; pending = null;
  const list=rows(), i=list.findIndex(d=>d.uid===uid), d=list[i], s=st(uid);
  el("secInfo").innerHTML = `<b>${d.uid}</b><br>section ${d.order} &middot; ${i+1} of ${list.length}`;
  // The plate slider does NOT follow the section. Serial sections sit at
  // neighbouring atlas levels, so the plate just scrubbed to is nearly always
  // still the right one; reloading each section's stored plate meant every z/x
  // snapped the slider back and the level had to be found again by hand.
  // The one exception is a section carrying a real decision - assigned, or
  // landmarked - where the stored plate IS the thing worth seeing.
  draftRot = null;            // a tilt drafted on one section is not another's
  const decided = s.assigned || s.pairs.length > 0;
  const p = decided ? s.plate : Math.min(PLATES.length - 1, +el("slider").value || 0);
  el("slider").value = p;
  secImg.src = d.img;
  onSlide(p);
  document.querySelectorAll(".cell").forEach(c=>c.classList.toggle("active", c.dataset.uid===uid));
  if(!keep) document.querySelector(`[data-uid="${CSS.escape(uid)}"]`)
    ?.scrollIntoView({inline:"center", block:"nearest"});
}
const isDone   = uid => (S[uid]?.pairs?.length || 0) >= 3;
const isNoRoi  = uid => !!S[uid]?.noroi;
// Plate chosen deliberately but not landmarked - a real decision, and one the
// export used to discard.
const isPlateOnly = uid => !!S[uid]?.assigned && !isDone(uid) && !isNoRoi(uid);

// One source of truth for a cell's appearance, so the full build and the
// single-cell update cannot drift apart.
function cellClass(uid){
  const base = isDone(uid) ? "done" : isNoRoi(uid) ? "noroi"
             : isPlateOnly(uid) ? "plateonly" : "";
  return S[uid]?.fav ? base + " fav" : base;
}
function cellTag(uid){
  const s=S[uid], n=s?.pairs?.length||0;
  return isNoRoi(uid) ? "no ROI" : n ? n+" pts"
       : isPlateOnly(uid) ? PLATES[s.plate].id.replace("plate_","pl ") : "";
}
function counts(){
  const list=rows();
  el("nsec").textContent    = list.length;
  el("ndone").textContent   = list.filter(d=>isDone(d.uid)).length;
  el("nassign").textContent = list.filter(d=>isPlateOnly(d.uid)).length;
  el("nnoroi").textContent  = list.filter(d=>isNoRoi(d.uid)).length;
  // counted over the animal, not the filtered view, so it does not collapse to
  // the list length the moment "favourites only" is ticked
  el("nfav").textContent    = inAnimal().filter(d=>S[d.uid]?.fav).length;
}
// Update ONE strip cell. Every interaction used to rebuild all 87 cells and
// reload their images, which is why it felt slow even when it was not recursing.
function paintCell(uid){
  const c=document.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if(!c) return;
  c.className = "cell " + cellClass(uid) + (active===uid ? " active" : "");
  const cap=c.querySelector(".cap");
  if(cap) cap.innerHTML = `${DATA.find(d=>d.uid===uid).order}<br>${cellTag(uid)}`;
  counts();
}
// Full rebuild. Only on load and on animal change - not on interaction.
function render(){
  const list=rows();
  counts();
  el("strip").innerHTML = list.map(d=>
    `<div class="cell ${cellClass(d.uid)} ${active===d.uid?"active":""}"
      data-uid="${d.uid}" onclick="select('${d.uid}')">
      <img src="${d.img}" loading="lazy" alt="">
      <div class="cap">${d.order}<br>${cellTag(d.uid)}</div></div>`).join("");
  if(active && !list.some(d=>d.uid===active)) active=null;
  if(list.length) select(active && list.some(d=>d.uid===active) ? active : list[0].uid, true);
}

addEventListener("keydown", e=>{
  // A focused control eats its own keys. The plate slider is an input[type=range]
  // that already steps on the arrows, so without this it would step twice per
  // press, and the animal select does type-ahead on letters and would swallow x.
  const tag = e.target && e.target.tagName;
  if(tag==="SELECT" || tag==="INPUT" || tag==="TEXTAREA") return;
  if(!active) return;
  const list=rows(), i=list.findIndex(d=>d.uid===active);
  if(e.key==="ArrowRight"){ el("slider").value=Math.min(PLATES.length-1,+el("slider").value+1); onSlide(el("slider").value); e.preventDefault(); }
  else if(e.key==="ArrowLeft"){ el("slider").value=Math.max(0,+el("slider").value-1); onSlide(el("slider").value); e.preventDefault(); }
  else if(e.key==="u"){ undoPt(); }
  else if(e.key==="x" && i<list.length-1){ select(list[i+1].uid); }
  else if(e.key==="z" && i>0){ select(list[i-1].uid); }
  else if(e.key==="f"){ toggleFav(); }
  else if(e.key==="r"){ restoreTilt(); }
});

function exportCsv(){
  // THREE files, because there are three different decisions and collapsing them
  // loses one. A plate assignment is a judgement in its own right - "this section
  // is plate_020" - and it used to be discarded whenever it carried fewer than
  // three landmarks, which is exactly the case where the operator has decided the
  // section is not worth landmarking.
  const pl=[["scene_uid","animal","section_order","plate_set","plate_id","plate_index",
             "plate_has_seeds","n_landmarks","transform","status",
             "favorite","view_rotation_deg"]];
  const lm=[["scene_uid","animal","section_order","plate_set","plate_id","pair",
             "sec_x","sec_y","plate_x","plate_y","residual_px"]];
  const rg=[["scene_uid","animal","plate_set","plate_id","region","sec_x","sec_y",
             "n_landmarks","transform","mean_residual_px"]];

  for(const d of DATA){
    const s=S[d.uid];
    // A favourite is a decision too, so it is reported even with no plate yet.
    if(!s || !(s.assigned || s.fav)) continue;      // never looked at - say nothing
    const P=PLATES[s.plate], n=s.pairs.length;
    const T=transform(s.pairs);
    const chosen = s.assigned || n>0;   // is the plate a decision, or still the default?
    const status = s.noroi ? "no_roi" : n>=3 ? "registered"
                 : chosen ? "plate_only" : "favourite_only";
    // Blank rather than plate_001 when no plate was ever chosen - otherwise a
    // favourite with no assignment reads as a deliberate call on plate_001.
    pl.push([d.uid,d.animal,d.order,PLATE_SET, chosen?P.id:"", chosen?s.plate:"",
             chosen?(P.labelled?1:0):"", n, T?T.kind:"", status,
             s.fav?1:0, (s.rot||0).toFixed(1)]);
    if(status!=="registered") continue;

    let tot=0;
    s.pairs.forEach(([sx,sy,px,py],i)=>{
      const [X,Y]=apply(T,px,py), r=Math.hypot(X-sx,Y-sy); tot+=r;
      lm.push([d.uid,d.animal,d.order,PLATE_SET,P.id,i+1,sx.toFixed(2),sy.toFixed(2),
               px.toFixed(2),py.toFixed(2),r.toFixed(2)]);
    });
    const mr=(tot/n).toFixed(2);
    for(const sd of P.seeds){
      const [X,Y]=apply(T, sd.xf*P.w, sd.yf*P.h);
      rg.push([d.uid,d.animal,PLATE_SET,P.id,sd.region,X.toFixed(2),Y.toFixed(2),n,T.kind,mr]);
    }
  }
  dl(pl,"roi_plates.csv");
  dl(lm,"roi_landmarks.csv");
  dl(rg,"roi_regions.csv");
}
function dl(rowsArr,name){
  const b=new Blob([rowsArr.map(r=>r.join(",")).join("\\n")],{type:"text/csv"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(b); a.download=name; a.click();
}
render();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None)
    args = ap.parse_args()

    with open(INDEX_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
    if args.animal:
        rows = [r for r in rows if r["animal"] == args.animal]
    rows.sort(key=lambda r: (r["animal"], int(r["section_order"] or 0)))

    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        plates = list(csv.DictReader(fh))
    seeds = {}
    with open(os.path.join(PLATE_DIR, "seeds.csv"), newline="", encoding="utf-8") as fh:
        for s in csv.DictReader(fh):
            seeds.setdefault(s["plate_id"], []).append(
                {"region": s["region"], "xf": float(s["x_frac"]), "yf": float(s["y_frac"]),
                 "hex": s.get("colour_hex") or "#4da3ff"})

    pl = []
    for p in sorted(plates, key=lambda p: p["plate_id"]):
        img = os.path.join(PLATE_DIR, p["image_file"])
        if not os.path.exists(img):
            continue
        sd = seeds.get(p["plate_id"], [])
        pl.append({"id": p["plate_id"],
                   # Original plate, NOT reformatted: the seeds are fractions of
                   # this image, so no transform chain is needed.
                   "img": f"../atlas/{PLATE_SET}/{p['image_file']}",
                   "w": int(p["px_w"]), "h": int(p["px_h"]),
                   "labelled": int(bool(sd)), "seeds": sd})

    data = [{"uid": r["id"], "animal": r["animal"], "order": int(r["section_order"] or 0),
             "img": f"sections/{r['id']}.png"} for r in rows]

    page = (PAGE.replace("__DATA__", json.dumps(data))
                .replace("__PLATES__", json.dumps(pl))
                .replace("__PLATESET__", json.dumps(PLATE_SET)))
    with open(CURATOR_HTML, "w", encoding="utf-8") as fh:
        fh.write(page)

    lab = [p for p in pl if p["labelled"]]
    print(f"wrote {CURATOR_HTML}")
    print(f"  {len(data)} sections, {len(pl)} plates, "
          f"{sum(len(p['seeds']) for p in pl)} region seeds")
    print(f"  {len(lab)} plates carry seeds: {lab[0]['id']} .. {lab[-1]['id']}")
    print()
    print("Scrub the plate slider until it matches, then click matching points -")
    print("section first, then plate. From three pairs the atlas regions are warped")
    print("live onto the section in their atlas colours; that overlay is the check")
    print("that matters, not the residual number.")
    print()
    print("Only the plates listed above have regions to give. A section assigned")
    print("elsewhere gets no ROIs, so there is no reason to place landmarks on it -")
    print("the working subset selects itself.")
    print()
    print("Export writes roi_landmarks.csv (every pair, with its residual) and")
    print("roi_regions.csv (warped seed positions in the reformatted section frame).")


if __name__ == "__main__":
    main()
