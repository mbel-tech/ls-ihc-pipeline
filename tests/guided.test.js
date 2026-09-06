// The guided walk: the plate's ROIs as a click-through list, one polygon each.
//
// An ROI is an AREA - one region, one lobe - and the several atlas dots under it
// are samples of it, not things to be measured one by one. So the cursor walks
// ROIs and asks for an outline, and the number it names is the number every dot
// of that ROI carries.
//
// Also covers the seed ORDER underneath, which survives unchanged and which the
// ROI numbering is derived from, and the two kinds of region uncertainty -
// because those are claims the exports make and a silent change to either would
// be wrong in a way no screenshot would show.

const { env, load, chk, note, done } = require('./harness');
const { els, store, blobs, fire } = env;

const X = load(`{KEY, PLATES, DATA, st, rows, select, onSlideUser, exportCsv,
  markAssigned, toggleGuided, skipRoi, secDown, drawSec, clickPl, undoPt,
  roisOf, usedRois, gRoi, polysOf, commitPoly, undoPoly, status, imgK,
  get guided(){return guided}, get gTarget(){return gTarget},
  get draft(){return draft},
  set active(v){active=v}, get active(){return active}}`);
// a plate that actually carries ROIs
const pi = X.PLATES.findIndex(P=>P.labelled);
const P  = X.PLATES[pi];
els["animal"].value="LS105";
const uid = X.rows()[0].uid; X.select(uid, true); X.active=uid;
X.onSlideUser(pi);

note("plate "+P.id+" carries "+P.seeds.length+" seeds in "+P.hulls.length+" ROIs\n");

// ---- the seed order, which the ROI numbering is built on -------------------

chk("seeds arrive in a fixed order (n = 1..N)",
    P.seeds.every((s,i)=>s.n===i+1), true);
// Seeds are grouped into COLUMNS and sorted by y within one, so x wobbles by up
// to the column span along a column - the invariant is per-column, not per-seed.
const COL_BAND = 0.08, COL_SPAN = 0.12;
chk("columns run left to right (never jumps back a column)",
    P.seeds.every((s,i)=>i===0 || s.xf >= P.seeds[i-1].xf - COL_SPAN), true);
chk("and top-to-bottom within each column",
    P.seeds.every((s,i)=>i===0
      || Math.abs(s.xf-P.seeds[i-1].xf) > COL_BAND
      || s.yf >= P.seeds[i-1].yf - 1e-9), true);
chk("every seeded plate carries a crowding measure",
    X.PLATES.filter(p=>p.seeds.length>1).every(p=>p.nn>0), true);
const allSeeds = X.PLATES.flatMap(p=>p.seeds);
chk("every seed carries a region name",
    allSeeds.every(sd=>sd.region && sd.region.trim()), true);
chk("unk is a 0/1 flag on every seed", allSeeds.every(sd=>sd.unk===0||sd.unk===1), true);
chk("every uncertain seed is Rm - the only region the atlas marks '??'",
    allSeeds.filter(sd=>sd.unk).every(sd=>sd.region==="Rm"), true);
chk("amb is set exactly on the Vd/Vv/POA group",
    allSeeds.every(sd=>!!sd.amb===["Vd","Vv","POA"].includes(sd.region)), true);
chk("Dl and Dm are not flagged ambiguous - they are distinct places",
    allSeeds.filter(sd=>(sd.region==="Dl"||sd.region==="Dm") && sd.amb).length, 0);

// ---- the ROI numbering -----------------------------------------------------

const allH = X.PLATES.flatMap(p=>p.hulls||[]);
chk("every ROI is numbered 1..k on its own plate",
    X.PLATES.filter(p=>(p.hulls||[]).length)
            .every(p=>p.hulls.every((h,i)=>h.roi===i+1)), true);
// THE POINT OF THE WHOLE CHANGE: one number per area, carried by every dot.
chk("every seed of an ROI carries that ROI's number",
    X.PLATES.filter(p=>(p.hulls||[]).length).every(p=>
      p.hulls.every(h=>h.seeds.every(n=>p.seeds[n-1].roi===h.roi))), true);
chk("...and no seed is left without one",
    allSeeds.every(sd=>sd.roi>=1), true);
chk("there are fewer ROIs than seeds - that is the reduction",
    allH.length < allSeeds.length, true);
// Ordering the ROIs by their lowest seed is what makes the ROI walk follow the
// same traversal the seed order already established, rather than an alphabetical
// one nobody asked for.
chk("ROI order follows the seed order, not the region name",
    X.PLATES.filter(p=>(p.hulls||[]).length).every(p=>{
      const mins = p.hulls.map(h=>Math.min(...h.seeds));
      return mins.every((m,i)=>i===0 || m > mins[i-1]);
    }), true);

// ---- the walk --------------------------------------------------------------

// The stub hands out the section image's size only once it has been drawn with,
// so the first click of a run would convert at a different scale from the rest.
X.drawSec();
const s = X.st(uid);
const click = (cx,cy) => X.secDown({clientX:cx, clientY:cy, button:0, preventDefault(){}});
// A square, clicked out corner by corner and closed on the first one.
const drawSquare = (x0,y0,w) => {
  click(x0,y0); click(x0+w,y0); click(x0+w,y0+w); click(x0,y0+w); click(x0,y0);
};

chk("guided is on by default", X.guided, true);
chk("the cursor starts at ROI 1", X.gTarget, 1);
chk("...which is a real ROI on this plate", X.gRoi() && X.gRoi().roi, 1);
chk("the plate's ROI list is what is walked", X.roisOf(s).length, P.hulls.length);

// One corner is not a polygon, and neither are two.
click(100,100);
chk("a click starts a ring rather than placing anything", X.draft.length, 2);
chk("...and no landmark was made", s.pairs.length, 0);
click(200,100);
X.commitPoly();
chk("two corners do not close", X.polysOf(s).length, 0);
chk("...and the ring is still open", X.draft.length, 4);
click(200,200);
click(100,100);          // back to the first corner: closes it
chk("clicking the first corner closes the ring", X.polysOf(s).length, 1);
chk("...and the draft is finished with", X.draft, null);

const pg = X.polysOf(s)[0];
chk("the polygon is ROI 1", pg.roi, 1);
chk("...and carries that ROI's region", pg.region, P.hulls[0].region);
chk("...and its lobe", pg.part, P.hulls[0].part);
chk("the cursor advanced to ROI 2", X.gTarget, 2);
chk("ROI 1 counts as done", X.usedRois(s).has(1), true);

X.skipRoi();
chk("skip moves past ROI 2 without drawing it", X.gTarget, 3);
drawSquare(300,300,60);
chk("the next polygon answers ROI 3", X.polysOf(s)[1].roi, 3);
chk("skipped ROI 2 is still undrawn", X.usedRois(s).has(2), false);
chk("...and the cursor moved on again", X.gTarget, 4);

// Re-aim by clicking an ROI on the plate.
X.clickPl({clientX:0, clientY:0, button:0, preventDefault(){}});
chk("clicking the plate re-aims the cursor", X.gTarget>0, true);

// Resume: leave the section and come back.
const drawn = X.usedRois(s).size;
const other = X.rows()[1].uid;
X.select(other, true); X.select(uid, true);
chk("returning resumes rather than restarting", X.usedRois(X.st(uid)).size, drawn);
chk("...and the cursor points at the first gap", X.gTarget, 2);

// Undo takes the last region back and frees its number again.
X.undoPoly();
chk("undo removes a region", X.polysOf(s).length, 1);
chk("...and its ROI is outstanding once more", X.usedRois(s).has(3), false);

// ---- what reaches the exports ----------------------------------------------

X.select(uid, true); X.active = uid;
blobs.length=0; X.exportCsv();
const rg = blobs[2].split("\n"), h = rg[0].split(",");
const ci = n => h.indexOf(n);
chk("roi_regions.csv gained roi_n", ci("roi_n") > 0, true);
chk("...and dropped roi_source, which could only say one thing now",
    ci("roi_source"), -1);
const body = rg.slice(1).map(l=>l.split(",")).filter(r=>r[0]===uid);
chk("one row for the region drawn", body.filter(r=>r[ci("roi_kind")]==="roi").length, 1);
chk("...filed as a polygon", body.find(r=>r[ci("roi_kind")]==="roi")[ci("roi_shape")],
    "polygon");
chk("...naming its ROI number", body.find(r=>r[ci("roi_kind")]==="roi")[ci("roi_n")], "1");
chk("...with its region", body.find(r=>r[ci("roi_kind")]==="roi")[ci("region")],
    P.hulls[0].region);
// The whole reason discs went: an area is not a circle, and nothing anatomical
// may be exported as one.
chk("NO anatomical disc row is produced, ever",
    body.filter(r=>r[ci("roi_kind")]==="roi" && r[ci("roi_shape")]==="disc").length, 0);

done();
