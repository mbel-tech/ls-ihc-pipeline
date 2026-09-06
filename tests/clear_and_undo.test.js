// Taking work back: Clear section, and what `z` reaches for.
//
// Region drawing arrived after both of these were written, and neither was
// extended for it. `clearPts` emptied the landmarks and left a half-drawn ring
// on the canvas - every other place that discards work in progress clears
// `pending` and `draft` together (toggleGuided, skipRoi) and this one cleared
// only `pending`. And `z`, with no ring open, undid a landmark even when the
// last thing placed was a region, so finishing an outline and pressing z took
// away a landmark instead while the outline stayed.
//
// `z` is most-recent-first across both kinds. A region records `n`, the number
// of landmarks the section carried when the outline closed, and that is enough
// to compare their ages: still that many means nothing has been placed since
// and the region is newer; more means a landmark has. A pair carries no stamp -
// it is a positional array with nowhere to put one - and none is needed.
//
// The stamp goes out in roi_regions.csv as `landmarks_at_draw` and comes back
// through 04q_import_curation.py, so it survives a round trip. A region with no
// `n` is one from a curation older than the column; those read as newer, which
// is what `z` did before the stamp existed and never reaches past an outline to
// take a landmark instead.

const { env, load, chk, note, done } = require("./harness");
const { els, blobs } = env;

const X = load(`{PLATES, st, rows, select, onSlideUser, drawSec, secDown,
  commitPoly, commitPoint, dropVertex, undoPoly, undoPt, clearPts, undoZ,
  polysOf, toggleBgMode, exportCsv,
  get draft(){return draft}, set draft(v){draft=v},
  set active(v){active=v}, get active(){return active}}`);

const pi = X.PLATES.findIndex(P => (P.hulls || []).length);
els["animal"].value = "LS105";
const uid = X.rows()[0].uid;
X.select(uid, true); X.active = uid; X.onSlideUser(pi); X.drawSec();
const click = (cx, cy) => X.secDown({ clientX: cx, clientY: cy, button: 0,
                                      preventDefault() {} });
const outline = () => { click(100, 100); click(220, 100); click(220, 220); click(100, 220); };

note(`plate ${pi} carries ${X.PLATES[pi].hulls.length} ROIs\n`);

// ---- Clear section reaches everything placed on the section ----------------
let s = X.st(uid);
outline();
X.commitPoly();
chk("a region is drawn", X.polysOf(s).length, 1);
click(300, 300); click(340, 300);
chk("...a second ring is half clicked out", X.draft.length, 4);
s.pairs.push([10, 10, 20, 20, 0, 5]);
chk("...and a landmark is placed", s.pairs.length, 1);

X.clearPts();
s = X.st(uid);
chk("clear takes the landmarks", s.pairs.length, 0);
chk("...the half-drawn ring", X.draft, null);
chk("...and the regions", X.polysOf(s).length, 0);

// ---- z, while a ring is open ------------------------------------------------
click(100, 100); click(220, 100); click(220, 220);
chk("a ring is open", X.draft.length, 6);
X.undoZ();
chk("z drops a vertex", X.draft.length, 4);
X.undoZ(); X.undoZ();
chk("...and the ring is gone once its last vertex goes", X.draft, null);

// ---- z, with no ring open ---------------------------------------------------
outline();
X.commitPoly();
X.toggleBgMode();
X.commitPoint(30, 30, 5);           // a placed landmark, in its own right
X.toggleBgMode();
s = X.st(uid);
chk("the section carries a region and a landmark",
    [X.polysOf(s).length, s.pairs.length], [1, 1]);

chk("the region records how many landmarks preceded it", X.polysOf(s)[0].n, 0);

// The region was drawn first here, so the landmark is the newer of the two and
// z has to reach for that one - the case the order stamp exists to get right.
X.undoZ();
s = X.st(uid);
chk("z takes the landmark when the landmark is newer", s.pairs.length, 0);
chk("...and leaves the region standing", X.polysOf(s).length, 1);

X.undoZ();
s = X.st(uid);
chk("with the landmark gone, z takes the region", X.polysOf(s).length, 0);

// Now the other order: a landmark, then an outline closed after it.
X.toggleBgMode(); X.commitPoint(30, 30, 5); X.toggleBgMode();
outline();
X.commitPoly();
s = X.st(uid);
chk("a region drawn after one landmark records that one", X.polysOf(s)[0].n, 1);
X.undoZ();
s = X.st(uid);
chk("z takes the region when the region is newer", X.polysOf(s).length, 0);
chk("...and leaves the landmark standing", s.pairs.length, 1);
X.undoZ();
chk("then the landmark", X.st(uid).pairs.length, 0);

// A region that carries no stamp - an older curation, or one that came back
// through 04q, which has no column to rebuild it from.
X.toggleBgMode(); X.commitPoint(40, 40, 5); X.toggleBgMode();
outline();
X.commitPoly();
s = X.st(uid);
delete X.polysOf(s)[0].n;
X.undoZ();
s = X.st(uid);
chk("an unstamped region is treated as the newer one", X.polysOf(s).length, 0);
chk("...rather than reaching past it to a landmark", s.pairs.length, 1);
X.clearPts();

// ---- the stamp survives the export -----------------------------------------
// 04q rebuilds polys from roi_regions.csv, so a stamp that is not written out
// is a stamp that does not come back.
X.toggleBgMode(); X.commitPoint(30, 30, 5); X.toggleBgMode();
outline();
X.commitPoly();
blobs.length = 0;
X.exportCsv();
const rows = blobs[2].split("\n").map(l => l.split(","));
const head = rows[0];
const at = head.indexOf("landmarks_at_draw");
chk("roi_regions.csv carries the order stamp", at > -1, true);
chk("...appended, so the columns before it do not move",
    head.slice(0, 21).join(),
    "scene_uid,animal,marker,plate_set,plate_id,roi_kind,region,region_ambiguous," +
    "ambiguity_group,region_uncertain_in_atlas,sec_x,sec_y,sec_r,seed_n,n_landmarks," +
    "transform,mean_residual_px,roi_shape,part,sec_poly,roi_n");
const shape = head.indexOf("roi_shape");
const polyRow = rows.slice(1).find(r => r[shape] === "polygon");
const discRow = rows.slice(1).find(r => r[shape] === "disc");
chk("the polygon row states its stamp", polyRow[at], "1");
if (discRow) chk("a background disc has none", discRow[at], "");
X.clearPts();

// Nothing left to take: this must not throw.
let threw = null;
try { X.undoZ(); } catch (e) { threw = e.message; }
chk("z on an empty section does not throw", threw, null);

done();
