// Region polygons: a region drawn as itself, and the corners staying live after.
//
// Two things are asserted here and they fail differently.
//
// THE ROI GROUPING is computed in Python and shipped as page data, which is the
// only reason the lobe split is testable at all - canvas calls are swallowed by
// the stub, so a shape drawn on the plate is invisible to a suite. The failure
// being guarded is specific: group a bilateral region without splitting it and
// Dl comes out as one band across the whole brain. That is the same mistake
// 04f_exclusion_candidates.py documents for section solidity, and on this atlas
// it is the difference between a shape 0.20 of a plate wide and one 0.90 wide.
//
// THE EDITING is the other half. A finished outline has to stay adjustable -
// corners moved, added and removed - for as long as no new ring is being drawn.
// That proviso is the whole rule: with a draft open every click belongs to the
// ring being built, and a click that silently grabbed a handle instead would
// leave a half-drawn polygon nobody can finish.

const { env, load, chk, note, done } = require("./harness");
const { els, blobs, fire } = env;

const X = load(`{PLATES, DATA, st, rows, select, onSlideUser, exportCsv, drawSec,
  secDown, clickPl, commitPoly, dropVertex, dropCorner, grabVertex, undoPoly,
  undoLast, polysOf, inPoly, hullOf, polyArea, roisOf, usedRois, gRoi,
  roiPairs, bgPairs, toggleBgMode, toggleGuided, transform, skipRoi, closeR,
  get guided(){return guided}, get gTarget(){return gTarget},
  get draft(){return draft}, get hullsOn(){return hullsOn},
  get vDrag(){return vDrag},
  set active(v){active=v}, get active(){return active}}`);

// ---- the ROI grouping ------------------------------------------------------

const HULLED = X.PLATES.filter(P => (P.hulls || []).length);
const allH = HULLED.flatMap(P => P.hulls);
note(`${HULLED.length} plates carry ROIs, ${allH.length} in all\n`);

chk("every ROI names a region", allH.every(h => h.region && h.region.trim()), true);
chk("...and carries a colour", allH.every(h => /^#[0-9a-fA-F]{3,8}$/.test(h.hex)), true);
chk("...a lobe within its own count",
    allH.every(h => h.part >= 1 && h.part <= h.n_parts), true);
chk("...at least one seed", allH.every(h => h.seeds.length >= 1), true);
chk("unk is a 0/1 flag on every ROI",
    allH.every(h => h.unk === 0 || h.unk === 1), true);

// The ROIs of a plate must account for its seeds exactly: a seed dropped is a
// piece of region nobody can draw, and a seed in two ROIs would be claimed twice.
chk("ROI seeds partition the plate's seeds - none lost, none doubled",
    HULLED.every(P => {
      const ns = P.hulls.flatMap(h => h.seeds);
      return ns.length === P.seeds.length &&
             new Set(ns).size === ns.length &&
             ns.slice().sort((a, b) => a - b).join() ===
               P.seeds.map(s => s.n).sort((a, b) => a - b).join();
    }), true);

// THE LOBE SPLIT. Without it the widest shape on this atlas is 0.90 of a plate -
// Dl reaching from one hemisphere to the other. 0.5 is not a tuned threshold, it
// is the gap between those two outcomes.
const widthOf = h => Math.max(...h.v.map(v => v[0])) - Math.min(...h.v.map(v => v[0]));
const widest = allH.reduce((a, h) => widthOf(h) > widthOf(a) ? h : a, allH[0]);
note(`widest ROI: ${widest.region} at ${widthOf(widest).toFixed(3)} of a plate`);
chk("no ROI spans half a plate - nothing bridges the midline",
    allH.every(h => widthOf(h) < 0.5), true);

const partsOf = (P, r) => new Set(P.hulls.filter(h => h.region === r).map(h => h.n_parts));
chk("Dl splits in two wherever it appears",
    HULLED.filter(P => P.hulls.some(h => h.region === "Dl"))
          .every(P => partsOf(P, "Dl").has(2)), true);
chk("POA stays in one lobe on the plates where it is midline",
    HULLED.some(P => partsOf(P, "POA").has(1)), true);
chk("amb is set exactly on the Vd/Vv/POA group",
    allH.every(h => !!h.amb === ["Vd", "Vv", "POA"].includes(h.region)), true);

// ---- drawing ---------------------------------------------------------------

const pi = X.PLATES.findIndex(P => (P.hulls || []).length >= 3);
const P = X.PLATES[pi];
els["animal"].value = "LS105";
const uid = X.rows()[0].uid;
X.select(uid, true); X.active = uid;
X.onSlideUser(pi);
// The stub hands out the section image's size only once it has been drawn with,
// so the first click of a run would convert at a different scale from the rest.
X.drawSec();
const s = X.st(uid);

const click = (cx, cy) => X.secDown({clientX: cx, clientY: cy, button: 0,
                                     preventDefault() {}});
const move = (cx, cy) => fire("mousemove", {clientX: cx, clientY: cy});
const up = () => fire("mouseup", {});

click(100, 100); click(220, 100); click(220, 220); click(100, 220);
chk("four corners clicked out", X.draft.length, 8);
X.commitPoly();
chk("Enter-equivalent closes it", X.polysOf(s).length, 1);
const pg = X.polysOf(s)[0];
chk("...as ROI 1", pg.roi, 1);
chk("...with four corners", pg.v.length, 8);
chk("a closed polygon has area", X.polyArea(pg.v) > 0, true);

// Three collinear clicks pass the corner count and still enclose nothing; 06a
// would divide by that area.
click(400, 400); click(420, 420); click(440, 440);
X.commitPoly();
chk("three collinear corners are refused - no area", X.polysOf(s).length, 1);
chk("...and the ring is left open to be fixed", X.draft.length, 6);
X.dropVertex(); X.dropVertex(); X.dropVertex();
chk("z clears it back to nothing", X.draft, null);

// ---- editing a finished polygon --------------------------------------------

// `undoLast` restores S[uid] by REPLACING the object, so a cached reference to
// it goes stale the moment undo is used. Re-read it each time rather than
// holding one - a suite that quietly measured the old object would report an
// undo working when it had not.
const cur = () => X.polysOf(X.st(uid))[0];
const before = cur().v.slice();

chk("nothing is being dragged yet", X.vDrag, null);
click(100, 100);                       // lands on corner 0
chk("clicking a corner grabs it", X.vDrag !== null, true);
chk("...and does not start a new ring", X.draft, null);
move(140, 130); up();
chk("dragging moves that corner", cur().v[0] !== before[0], true);
chk("...and only that one", cur().v[2] === before[2] && cur().v[3] === before[3], true);
chk("...and lets go on mouseup", X.vDrag, null);
chk("the polygon still has four corners", cur().v.length, 8);

// One drag is one undo step - the grab takes the mark, and undoMark coalesces.
X.undoLast();
chk("undo puts the corner back", cur().v[0].toFixed(3), before[0].toFixed(3));

// An edge midpoint inserts a corner there and starts dragging it.
const n0 = cur().v.length;
const mx = (cur().v[0] + cur().v[2]) / 2, my = (cur().v[1] + cur().v[3]) / 2;
chk("clicking an edge inserts a corner", X.grabVertex(mx, my) && cur().v.length, n0 + 2);
up();

// Delete removes the corner under the cursor, and refuses to go below three.
chk("Delete removes a corner", X.dropCorner(cur().v[0], cur().v[1]) && cur().v.length, n0);
let guard = 0;
while (cur().v.length > 6 && guard++ < 20) X.dropCorner(cur().v[0], cur().v[1]);
chk("...down to three", cur().v.length, 6);
chk("...and no further - two corners are a line", X.dropCorner(cur().v[0], cur().v[1]), false);
chk("the polygon survived", X.polysOf(X.st(uid)).length, 1);

// NONE of it is reachable while a ring is open. That is the rule asked for.
click(500, 500);
chk("a ring is open", X.draft.length, 2);
chk("Delete does nothing mid-draw", X.dropCorner(cur().v[0], cur().v[1]), false);
const held = cur().v.length;
click(500, 560);
chk("...and a click is a new vertex, not a grab", X.vDrag, null);
chk("...it went to the ring", X.draft.length, 4);
chk("...leaving the finished polygon alone", cur().v.length, held);
X.dropVertex(); X.dropVertex();
chk("ring abandoned", X.draft, null);

// ---- what reaches the export -----------------------------------------------

blobs.length = 0; X.exportCsv();
const parse = line => {
  const out = []; let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) { if (c === '"') { if (line[i+1] === '"') { cur += '"'; i++; } else q = false; }
             else cur += c; }
    else if (c === '"') q = true;
    else if (c === ",") { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur); return out;
};
const rg = blobs[2].split("\n"), h = rg[0].split(",");
const ci = n => h.indexOf(n);
chk("the columns are APPENDED, so an old reader still finds sec_x",
    h.slice(0, 17).join(),
    "scene_uid,animal,marker,plate_set,plate_id,roi_kind,region,region_ambiguous," +
    "ambiguity_group,region_uncertain_in_atlas,sec_x,sec_y,sec_r,seed_n," +
    "n_landmarks,transform,mean_residual_px");
const body = rg.slice(1).map(parse).filter(r => r[ci("scene_uid")] === uid);
const polys = body.filter(r => r[ci("roi_shape")] === "polygon");
chk("one polygon row", polys.length, 1);
chk("...filed as a real ROI, not a new kind", polys[0][ci("roi_kind")], "roi");
chk("...carrying its ROI number", polys[0][ci("roi_n")], "1");
chk("...with no radius, because it has none", polys[0][ci("sec_r")], "");
chk("...and no seed_n, because it answers an area", polys[0][ci("seed_n")], "");
chk("...but a centroid, because the join is positional",
    polys[0][ci("sec_x")] > 0 && polys[0][ci("sec_y")] > 0, true);
chk("the vertex list is three points",
    polys[0][ci("sec_poly")].split(";").length, 3);
chk("...each an x y pair",
    polys[0][ci("sec_poly")].split(";").every(v => /^[\d.]+ [\d.]+$/.test(v)), true);
chk("no anatomical disc row",
    body.filter(r => r[ci("roi_kind")] === "roi" && r[ci("roi_shape")] === "disc").length, 0);

done();
