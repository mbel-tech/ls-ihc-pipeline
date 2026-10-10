"""Stage 4x - turn the Wullimann plates' region outlines into numbered polygons.

The salmon atlas marks each region with dots and 04l shades a numbered area from
them. The Wullimann plates draw every region as a closed outline, so the outline
is the area: this stage finds the enclosed cells in each plate's drawing half and
writes one polygon per cell to `polygons.csv`, in the same reading order the
pipeline already numbers ROIs in. 04l then shows those numbered polygons as the
guide when the operator draws the region on a section.

How a plate is read
  1. The drawing half is everything left of `midline_frac` (04w measured it).
  2. White pixels are the inside of a region; every dark pixel - outline, label,
     leader line - is wall. The walls are thickened by one pixel before the cells
     are labelled so a gap in a dashed outline does not merge two regions.
  3. Each cell's own label is read by OCR on a crop that shows only that cell's
     interior, against the abbreviations that plate's legend lists. A cell is
     named only when the reading matches one of them closely; anything else
     stays UNASSIGNED. A wrong name is worse than none: the curator uses the
     name as a measurement key.
  4. Cells are simplified to polygons and numbered.

What this does not do: read labels that sit outside their region on a leader line
(LOT, MOT and similar), or split two regions whose shared outline is missing.
Those cells come out unassigned or merged and are fixed in the review page
(`--review`), which also shows the plate's legend.

Needs tesseract (system) and pytesseract; both are optional, and without them
every cell is left unassigned for hand naming.

Run:  python 04x_wullimann_polygons.py [--plate wplate_071] [--qc]
      python 04x_wullimann_polygons.py --review
"""

import argparse
import csv
import difflib
import importlib.util
import json
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


IO = _load("_lsio", "ls_io.py")
AP = _load("_atlas_polygons", "atlas_polygons.py")

try:
    import pytesseract
    pytesseract.get_tesseract_version()
    HAVE_OCR = True
except Exception:          # module missing, or the tesseract binary is
    HAVE_OCR = False

WHITE = 225            # a pixel at least this bright is region interior
MIN_AREA = 0.0006      # smallest cell kept, as a fraction of the drawing half
SIMPLIFY = 0.0015      # polygon simplification, as a fraction of the half's diagonal
NAME_MIN = 0.75        # least similarity between a reading and a legend entry
OCR_SCALE = 4
LEADER_SLACK = 0.8     # ink reaching this many text-heights past a word is a leader line
DEPTH_MIN = 0.45       # a label nearer a wall than this is not the cell's own


def find_cells(gray, mid):
    """Enclosed white cells of the drawing half: list of (mask uint8, area_px).

    Everything right of the midline is painted as wall, not cropped away: a
    region that touches the midline (Dm, Dl, Vd on the telencephalic plates)
    would otherwise reach the crop's edge and be dropped as open. The outer panel
    is gray, not white, so it never forms a cell; a cell touching the top, left
    or bottom edge is a speck of paper outside the drawing and is dropped.
    """
    h, w = gray.shape
    work = gray.copy()
    work[:, int(round(mid * w)):] = 0
    white = (work >= WHITE).astype(np.uint8)
    white = cv2.erode(white, np.ones((3, 3), np.uint8))     # thicken walls by 1 px
    n, lab, st, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area < MIN_AREA * h * w * 0.5:
            continue
        if x == 0 or y == 0 or y + bh >= h:
            continue
        m = (lab == i).astype(np.uint8)
        m = cv2.dilate(m, np.ones((3, 3), np.uint8))        # give the wall back
        out.append((m, int(area)))
    return out


def cell_polygon(mask, w, h):
    """Outer contour of a cell as [[xf, yf], ...] fractions of the full plate."""
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    eps = SIMPLIFY * (h * h + w * w) ** 0.5
    c = cv2.approxPolyDP(c, eps, True)[:, 0, :]
    return [[round(float(x) / w, 5), round(float(y) / h, 5)] for x, y in c]


def norm(s):
    """Fold the characters OCR cannot tell apart before comparing a reading."""
    return s.replace("I", "l").replace("1", "l").replace("|", "l").replace("0", "O").lower()


def read_cell(gray, mask):
    """OCR the labels inside one cell: [(reading, depth_ratio, conf)], deepest first.

    Only the cell's interior is shown (the filled outer contour, shrunk so the
    outline is not read as strokes; everything else white). A cell can hold two
    kinds of text: its own name, which a draughtsman puts in the middle, and the
    name of a small neighbour, which sits near an edge with a leader line to the
    neighbour. `depth_ratio` is how far from the nearest wall the text sits,
    against the deepest point of the cell, so the caller can take the first and
    refuse the second.
    """
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, cs, -1, 1, thickness=-1)
    depth = cv2.distanceTransform(filled, cv2.DIST_L2, 3)
    inner = cv2.erode(filled, np.ones((7, 7), np.uint8))
    ys, xs = np.where(inner > 0)
    if len(xs) == 0:
        return []
    x0, y0 = xs.min(), ys.min()
    crop = np.where(inner > 0, gray, 255).astype(np.uint8)[y0:ys.max() + 1, x0:xs.max() + 1]
    if (crop < 150).sum() < 8:
        return []
    big = cv2.resize(crop, None, fx=OCR_SCALE, fy=OCR_SCALE, interpolation=cv2.INTER_CUBIC)
    pad = 12
    big = cv2.copyMakeBorder(big, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    d = pytesseract.image_to_data(big, config="--psm 11", output_type=pytesseract.Output.DICT)
    top = float(depth.max()) or 1.0
    # Ink components of the un-upscaled crop, to tell a label from one that has a
    # leader line attached: a draughtsman's pointer touches the lettering, so the
    # component holding the word runs far beyond the word's own box.
    ink = (crop < 150).astype(np.uint8)
    _, _, ist, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = []
    for i, t in enumerate(d["text"]):
        t = t.strip().replace(" ", "")
        if not t or float(d["conf"][i]) < 20:
            continue
        wx0 = (d["left"][i] - pad) / OCR_SCALE
        wy0 = (d["top"][i] - pad) / OCR_SCALE
        wx1, wy1 = wx0 + d["width"][i] / OCR_SCALE, wy0 + d["height"][i] / OCR_SCALE
        slack = LEADER_SLACK * (wy1 - wy0)
        ux0, uy0, ux1, uy1 = wx0, wy0, wx1, wy1
        for cx0, cy0, cw, ch, _a in ist[1:]:
            if cx0 < wx1 and cx0 + cw > wx0 and cy0 < wy1 and cy0 + ch > wy0:
                ux0, uy0 = min(ux0, cx0), min(uy0, cy0)
                ux1, uy1 = max(ux1, cx0 + cw), max(uy1, cy0 + ch)
        if (wx0 - ux0 > slack or wy0 - uy0 > slack or ux1 - wx1 > slack or uy1 - wy1 > slack):
            continue
        cx = x0 + (d["left"][i] + d["width"][i] / 2 - pad) / OCR_SCALE
        cy = y0 + (d["top"][i] + d["height"][i] / 2 - pad) / OCR_SCALE
        r = float(depth[min(int(cy), depth.shape[0] - 1), min(int(cx), depth.shape[1] - 1)]) / top
        out.append((t, r, float(d["conf"][i]) / 100.0))
    return sorted(out, key=lambda o: -o[1])


def match_name(reading, legend, taken):
    """(abbreviation, similarity) for the legend entry `reading` is closest to."""
    if not reading:
        return None, 0.0
    r = norm(reading)
    best, score = None, 0.0
    for a in legend:
        if a in taken:
            continue
        s = difflib.SequenceMatcher(None, r, norm(a)).ratio()
        if s > score:
            best, score = a, s
    return (best, score) if score >= NAME_MIN else (None, score)


def extract_plate(path, mid, legend, ocr=True):
    """Polygons for one plate: list of dicts (see atlas_polygons.py)."""
    gray = cv2.imread(path, 0)
    h, w = gray.shape
    half = gray
    polys, taken = [], set()
    cells = sorted(find_cells(gray, mid), key=lambda c: -c[1])
    for mask, area in cells:
        v = cell_polygon(mask, w, h)
        if len(v) < 3:
            continue
        # cell_polygon scales by the full plate; the half shares its height and
        # left edge, so x only needs the full width, which it was given.
        name, conf = (None, 0.0)
        if ocr and HAVE_OCR:
            for reading, depth, ocr_conf in read_cell(half, mask):
                if depth < DEPTH_MIN:
                    continue
                name, sim = match_name(reading, legend, taken)
                if name:
                    conf = sim * ocr_conf
                    break
        if name:
            taken.add(name)
        polys.append({"roi_number": 0, "region": name or "", "label_conf": conf,
                      "status": "auto" if name else "unassigned", "v": v})
    AP.renumber(polys)
    return polys


def read_plates(plate_dir):
    with open(os.path.join(plate_dir, "plates.csv"), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def draw_qc(path, polys, out):
    im = cv2.cvtColor(cv2.imread(path, 0), cv2.COLOR_GRAY2BGR)
    h, w = im.shape[:2]
    for p in polys:
        pts = np.array([[x * w, y * h] for x, y in p["v"]], np.int32)
        hexc = AP.region_colour(p["region"]) if p["region"] else "#ff4040"
        col = tuple(int(hexc[i:i + 2], 16) for i in (5, 3, 1))
        ov = im.copy()
        cv2.fillPoly(ov, [pts], col)
        im = cv2.addWeighted(ov, 0.45, im, 0.55, 0)
        cv2.polylines(im, [pts], True, col, 1)
        cx, cy = AP.interior_point(p["v"])
        cv2.putText(im, "%d %s" % (p["roi_number"], p["region"] or "?"),
                    (int(cx * w) - 12, int(cy * h)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    cv2.imwrite(out, im)


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Wullimann polygons - review</title>
<style>
body{margin:0;background:#0d1117;color:#e6edf3;font:13px system-ui,sans-serif;display:flex;height:100vh}
#side{width:150px;overflow:auto;border-right:1px solid #30363d}
#side div{padding:5px 8px;cursor:pointer;border-bottom:1px solid #21262d}
#side div.on{background:#1f6feb}#side div .t{color:#8b949e;font-size:11px}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#bar{padding:6px 10px;border-bottom:1px solid #30363d;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:5px;padding:3px 9px;cursor:pointer}
#cv{flex:1;min-height:0;width:100%;background:#010409}
#leg{width:300px;overflow:auto;border-left:1px solid #30363d;padding:6px}
#leg div{padding:3px 5px;cursor:pointer;border-radius:4px}#leg div:hover{background:#21262d}
#leg div.used{color:#6e7681}#leg b{display:inline-block;width:46px}
kbd{background:#21262d;border:1px solid #30363d;border-radius:3px;padding:0 4px}
</style></head><body>
<div id="side"></div>
<div id="main"><div id="bar"><span id="info"></span>
<button onclick="confirmSel()">Confirm name <kbd>Enter</kbd></button>
<button onclick="unassignSel()">Unname <kbd>u</kbd></button>
<button onclick="removeSel()">Delete <kbd>Del</kbd></button>
<button onclick="startDraw()">Draw polygon <kbd>n</kbd></button>
<button onclick="exportCsv()">Export</button>
<span style="color:#8b949e">click a polygon, then a legend entry to name it. Reviewed polygons are the ones 04l shows.</span></div>
<canvas id="cv"></canvas></div>
<div id="leg"></div>
<script>
const KEY = __KEY__;
const PLATES = __PLATES__;   // [{id,img,w,h,level,legend:[{ab,def}],polys:[{region,status,conf,v}]}]
const el = id => document.getElementById(id);
let state = JSON.parse(localStorage.getItem(KEY) || "{}");   // plate id -> polys
let cur = Math.min(Math.max(parseInt(((typeof location !== "undefined" && location.hash) || "").slice(1)) || 0, 0), PLATES.length - 1), sel = -1, draw = null;
const imgs = {};
const polysOf = P => state[P.id] || (state[P.id] = JSON.parse(JSON.stringify(P.polys)));
const save = () => localStorage.setItem(KEY, JSON.stringify(state));
const colour = n => { let h = 0; for (const c of n || "?") h = (h * 31 + c.charCodeAt(0)) % 360; return `hsl(${h},70%,62%)`; };

function inside(x, y, v){
  let r = false;
  for (let i = 0, j = v.length - 1; i < v.length; j = i++)
    if ((v[i][1] > y) !== (v[j][1] > y) && x < (v[j][0]-v[i][0]) * (y-v[i][1]) / (v[j][1]-v[i][1]) + v[i][0]) r = !r;
  return r;
}
const area = v => Math.abs(v.reduce((s, p, i) => s + p[0]*v[(i+1)%v.length][1] - v[(i+1)%v.length][0]*p[1], 0)) / 2;
function hit(P, x, y){
  let best = -1;
  polysOf(P).forEach((q, i) => { if (inside(x, y, q.v) && (best < 0 || area(q.v) < area(polysOf(P)[best].v))) best = i; });
  return best;
}
function setName(name){
  const q = polysOf(PLATES[cur])[sel]; if (!q) return;
  // a name may sit on one polygon per hemisphere-part only once per plate by default
  q.region = name; q.status = name ? "reviewed" : "unassigned"; save(); render();
}
function confirmSel(){ const q = polysOf(PLATES[cur])[sel]; if (q && q.region){ q.status = "reviewed"; save(); render(); } }
function unassignSel(){ const q = polysOf(PLATES[cur])[sel]; if (q){ q.region = ""; q.status = "unassigned"; save(); render(); } }
function removeSel(){ const L = polysOf(PLATES[cur]); if (sel >= 0){ L.splice(sel, 1); sel = -1; save(); render(); } }
function startDraw(){ draw = []; render(); }
function addPoly(v){ polysOf(PLATES[cur]).push({region: "", status: "unassigned", conf: 0, v}); sel = polysOf(PLATES[cur]).length - 1; save(); }
function exportRows(){
  const rows = [["plate_id","roi_number","region","status","label_conf","vertices"]];
  for (const P of PLATES) polysOf(P).forEach((q, i) => rows.push([P.id, q.roi_number || 0, q.region, q.status,
    (q.conf || 0).toFixed(3), q.v.map(p => p[0].toFixed(5) + " " + p[1].toFixed(5)).join(";")]));
  return rows.map(r => r.join(",")).join("\n") + "\n";
}
function exportCsv(){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([exportRows()], {type: "text/csv"}));
  a.download = "polygons_review.csv"; a.click();
}
function show(i){ cur = i; sel = -1; draw = null; render(); }
function render(){
  const P = PLATES[cur];
  el("side").innerHTML = PLATES.map((p, i) => {
    const L = polysOf(p), r = L.filter(q => q.status === "reviewed").length;
    return `<div class="${i===cur?"on":""}" onclick="show(${i})">${p.level}<span class="t"> ${r}/${L.length} reviewed</span></div>`;
  }).join("");
  const L = polysOf(P), used = new Set(L.filter(q => q.region).map(q => q.region));
  el("leg").innerHTML = P.legend.map(g => `<div class="${used.has(g.ab)?"used":""}" onclick="setName(${JSON.stringify(g.ab).replace(/"/g,"&quot;")})"><b>${g.ab}</b>${g.def}</div>`).join("");
  el("info").textContent = `section ${P.level}: ${L.length} polygons`;
  const cv = el("cv"), x = cv.getContext("2d");
  let im = imgs[P.id];
  if (!im){ im = imgs[P.id] = new Image(); im.onload = render; im.src = P.img; }
  cv.width = cv.clientWidth || 800; cv.height = cv.clientHeight || 600;
  const sc = Math.min(cv.width / P.w, cv.height / P.h);
  x.clearRect(0, 0, cv.width, cv.height);
  if (im.complete) x.drawImage(im, 0, 0, P.w * sc, P.h * sc);
  L.forEach((q, i) => {
    x.beginPath(); q.v.forEach((p, k) => k ? x.lineTo(p[0]*P.w*sc, p[1]*P.h*sc) : x.moveTo(p[0]*P.w*sc, p[1]*P.h*sc)); x.closePath();
    x.globalAlpha = i === sel ? .55 : .3; x.fillStyle = q.region ? colour(q.region) : "#f85149"; x.fill();
    x.globalAlpha = 1; x.lineWidth = q.status === "reviewed" ? 2 : 1; x.strokeStyle = i === sel ? "#7ee787" : x.fillStyle; x.stroke();
    const c = q.v.reduce((s, p) => [s[0]+p[0]/q.v.length, s[1]+p[1]/q.v.length], [0, 0]);
    x.fillStyle = "#000"; x.fillText((i+1) + " " + (q.region || "?"), c[0]*P.w*sc - 10, c[1]*P.h*sc);
  });
  if (draw && draw.length){ x.beginPath(); draw.forEach((p, k) => k ? x.lineTo(p[0]*P.w*sc, p[1]*P.h*sc) : x.moveTo(p[0]*P.w*sc, p[1]*P.h*sc)); x.strokeStyle = "#d29922"; x.stroke(); }
}
el("cv").addEventListener("click", e => {
  const P = PLATES[cur], r = el("cv").getBoundingClientRect();
  const sc = Math.min(el("cv").width / P.w, el("cv").height / P.h);
  const fx = (e.clientX - r.left) / sc / P.w, fy = (e.clientY - r.top) / sc / P.h;
  if (draw){ draw.push([fx, fy]); render(); return; }
  sel = hit(P, fx, fy); render();
});
window.addEventListener("keydown", e => {
  if (e.key === "Enter"){ if (draw && draw.length > 2){ addPoly(draw); draw = null; render(); } else confirmSel(); }
  else if (e.key === "Escape"){ draw = null; render(); }
  else if (e.key === "Delete") removeSel();
  else if (e.key === "u") unassignSel();
  else if (e.key === "n") startDraw();
  else if (e.key === "ArrowDown" && cur < PLATES.length - 1) show(cur + 1);
  else if (e.key === "ArrowUp" && cur > 0) show(cur - 1);
});
render();
</script></body></html>
"""


def load_legend_defs(path):
    """{section: [{ab, def}]} from legends.csv, for the review page's legend."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(int(r["cross_section"]), []).append(
                {"ab": r["abbreviation"], "def": r["definition"]})
    return out


def build_review(plate_dir, legends_path, out):
    plates = read_plates(plate_dir)
    polys = AP.read_polygons(os.path.join(plate_dir, "polygons.csv"))
    defs = load_legend_defs(legends_path)
    data = []
    for p in plates:
        level = int(p["section_level"]) if p.get("section_level") else 0
        legend = defs.get(level) or [{"ab": a, "def": ""} for a in p["regions"].split("|") if a]
        data.append({"id": p["plate_id"], "img": p["image_file"], "w": int(p["px_w"]),
                     "h": int(p["px_h"]), "level": level, "legend": legend,
                     "polys": [{"region": q["region"], "status": q["status"],
                                "conf": q["label_conf"], "roi_number": q["roi_number"],
                                "v": q["v"]} for q in polys.get(p["plate_id"], [])]})
    page = IO.fill(PAGE, {"__KEY__": "wullimann_polygon_review_v1", "__PLATES__": data})
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    return len(data)


def import_review(plate_dir, review_csv):
    """Merge an exported review into polygons.csv: the plates in it are replaced
    wholesale, the others are left alone, and every plate is renumbered."""
    incoming = AP.read_polygons(review_csv)
    path = os.path.join(plate_dir, "polygons.csv")
    cur = AP.read_polygons(path)
    for pid, polys in incoming.items():
        AP.renumber(polys)
        cur[pid] = polys
    AP.write_polygons(path, cur)
    reviewed = sum(1 for v in cur.values() for q in v if q["status"] == "reviewed")
    return len(incoming), reviewed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plate-dir", help="plate set (default: <out_root>/atlas/plates_wullimann)")
    ap.add_argument("--plate", action="append", help="only this plate id (repeatable)")
    ap.add_argument("--no-ocr", action="store_true", help="leave every cell unassigned")
    ap.add_argument("--qc", action="store_true", help="write qc/<plate>_polygons.png")
    ap.add_argument("--keep-reviewed", action="store_true",
                    help="do not overwrite polygons a person has already reviewed")
    ap.add_argument("--review", action="store_true",
                    help="write the review page (polygon_review.html) into the plate set")
    ap.add_argument("--legends", help="legends.csv for the review page "
                    "(default: <repo>/atlas/wullimann1996/legends.csv)")
    ap.add_argument("--import-review", metavar="CSV",
                    help="merge an exported polygons_review.csv into polygons.csv")
    args = ap.parse_args()
    plate_dir = args.plate_dir
    if not plate_dir:
        cfg_path = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(HERE), "config.json")
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        plate_dir = os.path.join(cfg["out_root"], "atlas", IO.WULLIMANN_SET)
    if args.review:
        legends = args.legends or os.path.join(os.path.dirname(HERE), "atlas", "wullimann1996", "legends.csv")
        out = os.path.join(plate_dir, "polygon_review.html")
        n = build_review(plate_dir, legends, out)
        print("%d plates -> %s" % (n, out))
        return
    if args.import_review:
        n, reviewed = import_review(plate_dir, args.import_review)
        print("%d plates replaced; %d polygons reviewed in total" % (n, reviewed))
        return
    if not HAVE_OCR and not args.no_ocr:
        print("tesseract not available: cells will be left unassigned for hand naming")
    out_csv = os.path.join(plate_dir, "polygons.csv")
    existing = AP.read_polygons(out_csv)
    result = dict(existing)
    os.makedirs(os.path.join(plate_dir, "qc"), exist_ok=True)
    tot = named = 0
    for p in read_plates(plate_dir):
        pid = p["plate_id"]
        if args.plate and pid not in args.plate:
            continue
        if args.keep_reviewed and any(q["status"] == "reviewed" for q in existing.get(pid, [])):
            continue
        path = os.path.join(plate_dir, p["image_file"])
        legend = [a for a in p["regions"].split("|") if a]
        polys = extract_plate(path, float(p["midline_frac"]), legend, ocr=not args.no_ocr)
        result[pid] = polys
        n = sum(1 for q in polys if q["region"])
        tot += len(polys)
        named += n
        print("%s  %2d polygons, %2d named, legend %2d" % (pid, len(polys), n, len(legend)))
        if args.qc:
            draw_qc(path, polys, os.path.join(plate_dir, "qc", pid + "_polygons.png"))
    AP.write_polygons(out_csv, result)
    print("%d polygons, %d named -> %s" % (tot, named, out_csv))


if __name__ == "__main__":
    main()
