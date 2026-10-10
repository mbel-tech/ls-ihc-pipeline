"""Stage 1e - build a local curation GUI for section division.

The agreed working pattern: the pipeline proposes, the user adjudicates, and the
rule is calibrated on real judgement rather than on assumptions about salmonid
neuroanatomy. This builds the first of those tools.

For every scene with more than one large tissue blob it shows the DAPI overview
with the proposed grouping drawn on top, and asks one question: **how many brain
sections are in this frame?** A rostral telencephalic section is naturally two
lobes, so blob count cannot answer it and geometry alone would only encode a
guess.

Output is a single self-contained HTML file. Data is embedded rather than
fetched, because a browser opening a file:// page will not fetch a sibling JSON
(CORS); images still load fine through <img>. Verdicts are held in localStorage
as you go, so closing the tab does not lose work, and are exported as a CSV that
`01i_multisection_review.py --fit` reads back.

Run:  python 01j_build_curator.py
      then open D:/LS-analysis/qc/multisection/curator.html
"""

import argparse
import csv
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "multisection")
REVIEW_CSV = os.path.join(REPORT_DIR, "multisection_review.csv")
CURATOR_HTML = os.path.join(REPORT_DIR, "curator.html")

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Section curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}
.grow{flex:1}
.bar{height:5px;background:var(--line);border-radius:3px;width:220px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--ok);width:0}
main{flex:1;display:flex;min-height:0}
#stage{flex:1;display:flex;align-items:center;justify-content:center;padding:12px;min-width:0;position:relative}
#stage img{max-width:100%;max-height:100%;object-fit:contain;background:#000}
#boxes{position:absolute;pointer-events:none}
aside{width:290px;border-left:1px solid var(--line);padding:14px;overflow:auto}
.k{display:inline-block;min-width:22px;padding:2px 7px;border:1px solid var(--line);border-radius:5px;
   background:#1c2027;font:600 12px ui-monospace,monospace;text-align:center;margin-right:6px}
.row{margin:9px 0;color:var(--dim)}
.row b{color:var(--fg);font-weight:600}
button{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;
       padding:8px 12px;cursor:pointer;font:inherit}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
.verdict{font-size:26px;font-weight:700;color:var(--ok);min-width:34px;text-align:center}
.pending{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
td{padding:3px 0;color:var(--dim)}td:last-child{text-align:right;color:var(--fg);font-family:ui-monospace,monospace}
footer{padding:9px 16px;border-top:1px solid var(--line);display:flex;gap:10px;align-items:center;font-size:12px;color:var(--dim)}
</style>
<header>
  <h1>Section curator</h1>
  <span id="pos" class="row"></span>
  <div class="bar"><i id="prog"></i></div>
  <span id="done" class="row"></span>
  <span class="grow"></span>
  <button onclick="exportCsv()" class="primary">Export CSV</button>
</header>
<main>
  <div id="stage"><img id="img" alt=""><svg id="boxes"></svg></div>
  <aside>
    <div class="row"><b id="uid"></b></div>
    <table id="meta"></table>
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    <div class="row">How many <b>brain sections</b> in this frame?</div>
    <div class="row" style="font-size:12px">Two lobes of one telencephalic section count as <b>1</b>.</div>
    <div class="row" style="margin-top:14px">
      <span class="k">1</span><span class="k">2</span><span class="k">3</span><span class="k">4</span> set count
    </div>
    <div class="row"><span class="k">&larr;</span><span class="k">&rarr;</span> prev / next</div>
    <div class="row"><span class="k">s</span> skip (leave blank)</div>
    <div class="row"><span class="k">u</span> next unmarked</div>
    <div class="row" style="margin-top:16px">verdict: <span id="verdict" class="verdict pending">-</span></div>
  </aside>
</main>
<footer><span id="hint">Verdicts autosave in this browser. Export when done.</span></footer>
<script>
const DATA = __DATA__;
const KEY = "ls_section_curator_v1";
let marks = JSON.parse(localStorage.getItem(KEY) || "{}");
let i = 0;

const el = id => document.getElementById(id);

function render(){
  const d = DATA[i];
  el("img").src = d.img;
  el("uid").textContent = d.scene_uid;
  el("pos").textContent = `${i+1} / ${DATA.length}`;
  el("meta").innerHTML = [
    ["animal", d.animal], ["slide", d.slide], ["marker", d.marker],
    ["blobs", d.n_blobs], ["separation", d.separation_ratio],
    ["size ratio", d.size_ratio], ["tissue mm2", d.tissue_area_mm2],
  ].map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");

  const v = marks[d.scene_uid];
  const ve = el("verdict");
  ve.textContent = v || "-";
  ve.className = "verdict" + (v ? "" : " pending");

  const n = Object.keys(marks).length;
  el("done").textContent = `${n} marked`;
  el("prog").style.width = (100*n/DATA.length) + "%";
  drawBoxes(d);
}

// Blob boxes are drawn in the image's own pixel space and scaled to however
// the browser has letterboxed it, so they stay aligned at any window size.
function drawBoxes(d){
  const img = el("img"), svg = el("boxes");
  if(!img.naturalWidth){ img.onload = () => drawBoxes(d); return; }
  const box = img.getBoundingClientRect(), st = el("stage").getBoundingClientRect();
  const sc = Math.min(box.width/img.naturalWidth, box.height/img.naturalHeight);
  const w = img.naturalWidth*sc, h = img.naturalHeight*sc;
  svg.setAttribute("width", w); svg.setAttribute("height", h);
  svg.style.left = (box.left - st.left) + "px";
  svg.style.top  = (box.top  - st.top ) + "px";
  const cols = ["#ff4d4d","#4da3ff","#3fb950","#d29922","#c678dd"];
  svg.innerHTML = d.blobs.map((b,k) =>
    `<rect x="${b[0]*sc}" y="${b[1]*sc}" width="${b[2]*sc}" height="${b[3]*sc}"
       fill="none" stroke="${cols[k%cols.length]}" stroke-width="2"/>
     <text x="${b[0]*sc+6}" y="${b[1]*sc+20}" fill="${cols[k%cols.length]}"
       font-size="17" font-weight="700">${k+1}</text>`).join("");
}

function setMark(n){
  marks[DATA[i].scene_uid] = n;
  localStorage.setItem(KEY, JSON.stringify(marks));
  render();
  setTimeout(() => go(1), 120);
}
function go(step){ i = Math.max(0, Math.min(DATA.length-1, i+step)); render(); }
function nextUnmarked(){
  for(let k=1;k<=DATA.length;k++){
    const j = (i+k) % DATA.length;
    if(!marks[DATA[j].scene_uid]){ i=j; render(); return; }
  }
  el("hint").textContent = "All scenes marked - export the CSV.";
}

addEventListener("keydown", e => {
  if(e.key >= "1" && e.key <= "4") setMark(+e.key);
  else if(e.key === "ArrowRight") go(1);
  else if(e.key === "ArrowLeft") go(-1);
  else if(e.key === "s") go(1);
  else if(e.key === "u") nextUnmarked();
});
addEventListener("resize", () => drawBoxes(DATA[i]));

function exportCsv(){
  const rows = [["scene_uid","n_sections"]].concat(
    DATA.filter(d => marks[d.scene_uid]).map(d => [d.scene_uid, marks[d.scene_uid]]));
  const blob = new Blob([rows.map(r => r.join(",")).join("\\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "curated_sections.csv";
  a.click();
  el("hint").textContent = "Saved curated_sections.csv - put it in qc/multisection/ and run 01i --fit";
}
render();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=400)
    args = ap.parse_args()

    if not os.path.exists(REVIEW_CSV):
        raise SystemExit(f"{REVIEW_CSV} not found - run 01i_multisection_review.py first.")
    with open(REVIEW_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    # Most ambiguous first: similar-sized, well-separated blobs are exactly where
    # a geometric rule would go wrong, so those are worth a human's attention.
    def ambiguity(r):
        try:
            return float(r["size_ratio"]) * min(float(r["separation_ratio"]), 2.0)
        except ValueError:
            return 0.0
    rows.sort(key=ambiguity, reverse=True)
    rows = rows[: args.max]

    data = []
    for r in rows:
        img = os.path.join("..", "..", "overviews", r["animal"], r["marker_channel"],
                           r["scene_uid"] + "_DAPI.png").replace("\\", "/")
        data.append({
            "scene_uid": r["scene_uid"], "animal": r["animal"], "slide": r["slide"],
            "marker": r["marker_channel"], "n_blobs": r["n_blobs"],
            "separation_ratio": r["separation_ratio"], "size_ratio": r["size_ratio"],
            "tissue_area_mm2": r["tissue_area_mm2"],
            "img": img,
            "blobs": json.loads(r["blob_boxes"]) if r.get("blob_boxes") else [],
        })

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(CURATOR_HTML, "w", encoding="utf-8") as fh:
        fh.write(PAGE.replace("__DATA__", json.dumps(data)))

    print(f"wrote {CURATOR_HTML}")
    print(f"  {len(data)} scenes, most ambiguous first")
    print()
    print("Open it in a browser. Keys: 1-4 set the section count, arrows navigate,")
    print("u jumps to the next unmarked. Verdicts autosave; Export CSV when done,")
    print("save it into qc/multisection/, then run:")
    print("  python 01i_multisection_review.py --fit")


if __name__ == "__main__":
    main()
