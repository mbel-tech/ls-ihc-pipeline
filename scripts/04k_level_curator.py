"""Stage 4k - assign atlas levels by anchoring a few sections and interpolating.

`04c_atlas_match.py` tried to identify each section's level from its silhouette
and does not work: correlation between a section's serial order and its
best-matching plate is -0.05, 0.00, 0.17, -0.04 across four animals, and the
median IoU between *adjacent* sections is 0.595 against 0.551 between sections
**thirty apart**. There is no ordering signal in the shape to match on. See
LOGS.md and the module docstring of `04c`.

This uses the constraint that is actually strong. The sections were cut serially
at uniform thickness and their order is known, so **level is very nearly a linear
function of section number**. Fixing two points fixes the line. Anchor a handful
of sections by eye and the rest follow - the QUINT/VisuAlign shape of workflow,
and a few minutes per brain rather than an unsolved vision problem.

Interaction:

  **click a section** to make it active, then **drag the plate slider** (or use
  the arrow keys) to scrub through the 101 plates. The plate is drawn behind the
  section in red, so choosing a level is a direct comparison rather than a
  judgement from memory. Releasing sets an **anchor**.

  Everything between two anchors is **interpolated live** as you move - so the
  cost of an anchor is visible immediately across the whole series, which is the
  point. Sections before the first anchor and after the last are extrapolated at
  the same rate and marked separately, because they rest on a weaker assumption.

  **Two anchors per animal is the minimum** and is usually enough. More helps
  only where sectioning was uneven.

  Anchors are forced **monotonic**: an anchor that would place a later section at
  an earlier plate is rejected, because serial sections cannot run backwards.

**Only 24 of the 101 plates carry region labels** (plate_009 to plate_032,
telencephalon and POA). Those are marked in the plate strip. A section assigned
outside that range still gets a level, but no regions can be propagated to it
until the caudal plates are annotated.

Levels are assigned on the **PCNA** sections, which are the fuller set (788
against 454 for pERK), and carried to pERK through the pairing in
`perk_overrides.csv`.

Run:  python 04k_level_curator.py
      python 04k_level_curator.py --animal LS45
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
PLATES_CSV = os.path.join(OUT_ROOT, "atlas", "plates", "plates.csv")
CURATOR_HTML = os.path.join(REFORMAT_DIR, "level_curator.html")

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Atlas level curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;
      --ok:#3fb950;--warn:#d29922;--anchor:#7c5cff}
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
#stage{display:grid;grid-template-columns:minmax(340px,1fr) 300px;gap:16px;padding:14px}
#big{position:relative;aspect-ratio:1;background:#0e1014;border:1px solid var(--line);
     border-radius:9px;overflow:hidden;max-height:56vh;margin:auto;width:100%}
#big img{position:absolute;inset:0;margin:auto;max-width:100%;max-height:100%}
#big .plate{filter:sepia(1) saturate(6) hue-rotate(-30deg);opacity:.5}
#side{display:flex;flex-direction:column;gap:10px}
.card{border:1px solid var(--line);border-radius:9px;padding:10px;background:#0e1014}
.card h2{font-size:12px;margin:0 0 6px;color:var(--dim);font-weight:600;letter-spacing:.04em}
input[type=range]{width:100%}
.kv{font-size:12px;color:var(--dim)}.kv b{color:var(--fg)}
.regions{font-size:11px;color:var(--ok);word-break:break-word;min-height:1.2em}
.unlab{color:var(--warn)}
#strip{display:flex;gap:4px;overflow-x:auto;padding:10px 14px;border-top:1px solid var(--line);
       background:#101318}
.cell{flex:0 0 auto;width:84px;border:2px solid var(--line);border-radius:7px;padding:3px;
      background:#0e1014;cursor:pointer;user-select:none}
.cell:hover{border-color:var(--accent)}
.cell.active{border-color:var(--accent);box-shadow:0 0 0 2px rgba(77,163,255,.3)}
.cell.anchor{border-color:var(--anchor);background:#141026}
.cell.extrap{opacity:.62}
.cell img{width:100%;aspect-ratio:1;object-fit:contain;display:block;border-radius:4px}
.cap{font-size:9px;color:var(--dim);text-align:center;margin-top:2px;line-height:1.2}
.cap b{color:var(--fg)}
.cell.anchor .cap b{color:#a48bff}
footer{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);
       padding:9px 16px;font-size:12px;color:var(--dim)}
kbd{display:inline-block;padding:1px 6px;border:1px solid var(--line);border-radius:4px;
    background:#1c2027;font:600 11px ui-monospace,monospace}
</style>
<header>
  <h1>Atlas level curator</h1>
  <select id="animal" onchange="render()"></select>
  <span class="row"><b id="nsec"></b> sections</span>
  <span class="row" style="color:#a48bff"><b id="nanch"></b> anchors</span>
  <span class="row"><b id="ninterp"></b> interpolated</span>
  <span class="row" style="color:#d29922"><b id="nextrap"></b> extrapolated</span>
  <span class="row" id="live"></span>
  <span class="grow"></span>
  <button onclick="clearAnimal()">Clear this animal</button>
  <button class="primary" onclick="exportCsv()">Export CSV</button>
</header>
<div id="stage">
  <div id="big">
    <img id="bigPlate" class="plate" alt="">
    <img id="bigSec" alt="">
  </div>
  <div id="side">
    <div class="card">
      <h2>SECTION</h2>
      <div class="kv" id="secInfo">click a section below</div>
    </div>
    <div class="card">
      <h2>PLATE</h2>
      <input type="range" id="slider" min="0" max="0" value="0" oninput="onSlide(this.value)">
      <div class="kv"><b id="plateName">-</b> <span id="plateIdx"></span></div>
      <div class="regions" id="plateRegions"></div>
      <div style="margin-top:8px;display:flex;gap:6px">
        <button onclick="setAnchor()" style="flex:1">Set anchor</button>
        <button onclick="dropAnchor()" style="flex:1">Drop anchor</button>
      </div>
    </div>
    <div class="card">
      <h2>HOW THIS WORKS</h2>
      <div class="kv">Sections were cut serially at uniform thickness, so level is
      close to linear in section number. Two anchors fix the line; the rest follow.
      Anchors are forced monotonic.</div>
    </div>
  </div>
</div>
<div id="strip"></div>
<footer>
  <kbd>click</kbd> select a section &middot;
  <kbd>&larr;</kbd><kbd>&rarr;</kbd> change plate &middot;
  <kbd>shift</kbd>+arrows jump 10 &middot;
  <kbd>a</kbd> set anchor &middot; <kbd>d</kbd> drop anchor &middot;
  <span style="color:#7c5cff">purple</span> = anchor,
  faded = extrapolated beyond the outermost anchors &middot; changes autosave
</footer>
<script>
const DATA = __DATA__;      // [{uid, animal, order, img}]
const PLATES = __PLATES__;  // [{id, img, regions}]
const KEY = "ls_level_curator_v1";
let anchors = JSON.parse(localStorage.getItem(KEY) || "{}");   // uid -> plate index
let active = null;

const el = id => document.getElementById(id);
const animals = [...new Set(DATA.map(d => d.animal))].sort((a,b)=>+a.slice(2)-+b.slice(2));
el("animal").innerHTML = animals.map(a => `<option>${a}</option>`).join("");
el("slider").max = PLATES.length - 1;
const save = () => localStorage.setItem(KEY, JSON.stringify(anchors));
const rows = () => DATA.filter(d => d.animal === el("animal").value)
                       .sort((a,b) => a.order - b.order);

// --- the whole method, in one function ---------------------------------------
// Level is linear in section number between anchors. Outside the outermost
// anchors it continues at the same rate, which is a weaker claim, so those are
// marked separately rather than silently blended in.
function assign(list){
  const anc = list.map((d,i) => [i, anchors[d.uid]]).filter(x => x[1] !== undefined);
  const out = list.map(() => ({plate: null, kind: "none"}));
  if(!anc.length) return out;
  if(anc.length === 1){
    // One anchor fixes an offset but not a rate; hold it flat and say so.
    for(let i=0;i<list.length;i++) out[i] = {plate: anc[0][1], kind: i===anc[0][0] ? "anchor" : "extrap"};
    return out;
  }
  for(const [i,p] of anc) out[i] = {plate: p, kind: "anchor"};
  for(let k=0;k<anc.length-1;k++){
    const [i0,p0] = anc[k], [i1,p1] = anc[k+1];
    for(let i=i0+1;i<i1;i++){
      const t = (list[i].order - list[i0].order) / (list[i1].order - list[i0].order);
      out[i] = {plate: Math.round(p0 + t*(p1-p0)), kind: "interp"};
    }
  }
  const [f,pf] = anc[0], [l,pl] = anc[anc.length-1];
  const rate = (pl - pf) / Math.max(list[l].order - list[f].order, 1);
  for(let i=0;i<f;i++)
    out[i] = {plate: clamp(Math.round(pf + rate*(list[i].order-list[f].order))), kind:"extrap"};
  for(let i=l+1;i<list.length;i++)
    out[i] = {plate: clamp(Math.round(pl + rate*(list[i].order-list[l].order))), kind:"extrap"};
  return out;
}
const clamp = v => Math.max(0, Math.min(PLATES.length-1, v));

function render(){
  const list = rows();
  const asg = assign(list);
  el("nsec").textContent = list.length;
  el("nanch").textContent = asg.filter(a=>a.kind==="anchor").length;
  el("ninterp").textContent = asg.filter(a=>a.kind==="interp").length;
  el("nextrap").textContent = asg.filter(a=>a.kind==="extrap").length;
  el("strip").innerHTML = list.map((d,i) => {
    const a = asg[i];
    const lbl = a.plate===null ? "-" : PLATES[a.plate].id.replace("plate_","");
    return `<div class="cell ${a.kind==="anchor"?"anchor":""} ${a.kind==="extrap"?"extrap":""}
                 ${active===d.uid?"active":""}" data-uid="${d.uid}" onclick="select('${d.uid}')">
      <img src="${d.img}" loading="lazy" alt="">
      <div class="cap">${d.order}<br><b>${lbl}</b></div></div>`;
  }).join("");
  if(active && !list.some(d=>d.uid===active)) active = null;
  if(!active && list.length) select(list[0].uid, true);
  else if(active) select(active, true);
}

function select(uid, keep){
  active = uid;
  const list = rows(), i = list.findIndex(d=>d.uid===uid);
  const d = list[i], asg = assign(list)[i];
  el("bigSec").src = d.img;
  el("secInfo").innerHTML = `<b>${d.uid}</b><br>section ${d.order} &middot; ${i+1} of ${list.length}`
    + `<br>${asg.kind==="anchor"?"<span style='color:#a48bff'>anchor</span>"
        : asg.kind==="interp"?"interpolated"
        : asg.kind==="extrap"?"<span style='color:#d29922'>extrapolated</span>":"no anchors yet"}`;
  const p = anchors[uid] !== undefined ? anchors[uid] : (asg.plate === null ? 0 : asg.plate);
  el("slider").value = p;
  showPlate(p);
  document.querySelectorAll(".cell").forEach(c =>
    c.classList.toggle("active", c.dataset.uid === uid));
  if(!keep) document.querySelector(`[data-uid="${CSS.escape(uid)}"]`)
    ?.scrollIntoView({inline:"center", block:"nearest"});
}

function showPlate(i){
  const p = PLATES[i];
  el("bigPlate").src = p.img;
  el("plateName").textContent = p.id;
  el("plateIdx").textContent = `(${i+1} of ${PLATES.length})`;
  el("plateRegions").innerHTML = p.regions
    ? p.regions.replace(/\\|/g, " &middot; ")
    : "<span class='unlab'>no region labels on this plate</span>";
}

function onSlide(v){ showPlate(+v); el("live").textContent = PLATES[+v].id; }

function setAnchor(){
  if(!active) return;
  const list = rows(), i = list.findIndex(d=>d.uid===active);
  const p = +el("slider").value;
  // Monotonic: serial sections cannot run backwards through the atlas.
  for(const [j,d] of list.entries()){
    const q = anchors[d.uid];
    if(q === undefined || d.uid === active) continue;
    if(j < i && q > p){ alert(`Section ${list[j].order} is anchored at ${PLATES[q].id}, which is `
      + `after ${PLATES[p].id}. Serial sections cannot run backwards.`); return; }
    if(j > i && q < p){ alert(`Section ${list[j].order} is anchored at ${PLATES[q].id}, which is `
      + `before ${PLATES[p].id}. Serial sections cannot run backwards.`); return; }
  }
  anchors[active] = p; save(); render();
}
function dropAnchor(){ if(active){ delete anchors[active]; save(); render(); } }
function clearAnimal(){
  const list = rows();
  const n = list.filter(d=>anchors[d.uid]!==undefined).length;
  if(n && !confirm(`Clear ${n} anchor${n>1?"s":""} for ${el("animal").value}?`)) return;
  list.forEach(d => delete anchors[d.uid]); save(); render();
}

addEventListener("keydown", e => {
  if(!active) return;
  const step = e.shiftKey ? 10 : 1;
  if(e.key==="ArrowRight"){ el("slider").value = clamp(+el("slider").value+step); onSlide(el("slider").value); e.preventDefault(); }
  else if(e.key==="ArrowLeft"){ el("slider").value = clamp(+el("slider").value-step); onSlide(el("slider").value); e.preventDefault(); }
  else if(e.key==="a"){ setAnchor(); }
  else if(e.key==="d"){ dropAnchor(); }
});

function exportCsv(){
  const out = [["scene_uid","animal","section_order","plate_id","plate_index","source","regions"]];
  for(const a of animals){
    const list = DATA.filter(d=>d.animal===a).sort((x,y)=>x.order-y.order);
    const asg = assign(list);
    list.forEach((d,i) => {
      if(asg[i].plate === null) return;      // animal not curated yet
      const p = PLATES[asg[i].plate];
      out.push([d.uid, a, d.order, p.id, asg[i].plate, asg[i].kind, '"'+(p.regions||"")+'"']);
    });
  }
  const b = new Blob([out.map(r=>r.join(",")).join("\\n")], {type:"text/csv"});
  const u = document.createElement("a");
  u.href = URL.createObjectURL(b); u.download = "atlas_levels.csv"; u.click();
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

    with open(PLATES_CSV, newline="", encoding="utf-8") as fh:
        plates = [p for p in csv.DictReader(fh)
                  if os.path.exists(os.path.join(REFORMAT_DIR, "plates", p["plate_id"] + ".png"))]
    plates.sort(key=lambda p: p["plate_id"])

    data = [{"uid": r["id"], "animal": r["animal"], "order": int(r["section_order"] or 0),
             "img": f"sections/{r['id']}.png"} for r in rows]
    pl = [{"id": p["plate_id"], "img": f"plates/{p['plate_id']}.png",
           "regions": p.get("regions", "")} for p in plates]

    page = (PAGE.replace("__DATA__", json.dumps(data))
                .replace("__PLATES__", json.dumps(pl)))
    with open(CURATOR_HTML, "w", encoding="utf-8") as fh:
        fh.write(page)

    labelled = sum(1 for p in pl if p["regions"])
    print(f"wrote {CURATOR_HTML}")
    print(f"  {len(data)} sections, {len({d['animal'] for d in data})} animals, {len(pl)} plates")
    print(f"  {labelled} of {len(pl)} plates carry region labels")
    print()
    print("Click a section, drag the plate slider (or use the arrow keys) until the")
    print("red plate behind it matches, then press 'a' to anchor. Everything between")
    print("two anchors interpolates live by section number.")
    print()
    print("Two anchors per animal is the minimum and usually enough - the sections")
    print("were cut serially at uniform thickness, so level is close to linear in")
    print("section number. Add more only where sectioning was uneven.")
    print()
    print("Sections beyond the outermost anchors are extrapolated and shown faded:")
    print("they rest on a weaker assumption than the interpolated ones.")
    print()
    print(f"Only {labelled} plates carry region labels (telencephalon and POA). A section")
    print("assigned outside that range still gets a level, but no regions can be")
    print("propagated to it until the caudal plates are annotated.")
    print()
    print("Export when done, then levels can be carried to the pERK sections through")
    print("the pairing in perk_overrides.csv.")


if __name__ == "__main__":
    main()
