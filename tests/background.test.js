// Background discs: a second kind of ROI, marking tissue with no real signal.
//
// The reason this suite exists is that a background disc is stored as an
// ordinary pair with a 7th element, so every piece of code that walks
// `s.pairs` is a place it can be mistaken for a landmark. Three of those
// mistakes are silent and expensive:
//
//   * the guided cursor advancing, which files the NEXT region under the wrong
//     seed number and desyncs the rest of the plate;
//   * the disc entering the thin-plate spline, whose (0,0) plate coordinate
//     would drag the whole fit to the corner;
//   * the disc reaching roi_regions.csv as a region, where it would be counted
//     as a measurement of somewhere.
//
// None of the three changes anything visible on screen, so each is asserted
// here rather than trusted to review.

const { env, load, chk, note, done } = require("./harness");
const { els, blobs, fire } = env;

const X = load(`{KEY, PLATES, DATA, st, rows, select, onSlideUser, exportCsv,
  markAssigned, toggleFav, secDown, toggleBgMode, transform, toggleGuided,
  clickPl,
  usedRois, roisOf, polysOf, roiPairs, bgPairs, isBg, pairR, defaultR,
  drawSec,
  get guided(){return guided}, get gTarget(){return gTarget},
  get bgMode(){return bgMode},
  set active(v){active=v}, get active(){return active}}`);

const pi = X.PLATES.findIndex(P => P.labelled);
const P = X.PLATES[pi];
els["animal"].value = "LS105";
const uid = X.rows()[0].uid;
X.select(uid, true); X.active = uid;
X.onSlideUser(pi);

const clickAt = (cx, cy, dragTo) => {
  X.secDown({ clientX: cx, clientY: cy, button: 0, preventDefault() {} });
  if (dragTo) fire("mousemove", { clientX: dragTo[0], clientY: dragTo[1] });
  fire("mouseup", {});
};

const s = X.st(uid);
// The stub sizes the section image only once it has been drawn with.
X.drawSec();

// ---- the interleaving that breaks the cursor -----------------------------
note("\ndrawing ROI 1, then a background disc, then the next ROI\n");

const square = (x0, y0, w) => {
  clickAt(x0, y0); clickAt(x0 + w, y0); clickAt(x0 + w, y0 + w);
  clickAt(x0, y0 + w); clickAt(x0, y0);
};
square(100, 100, 80);
chk("ROI 1 drawn", X.polysOf(s)[0].roi, 1);
chk("cursor advanced to 2", X.gTarget, 2);

X.toggleBgMode();
chk("background mode is on", X.bgMode, true);
clickAt(300, 300);
chk("the disc was stored", s.pairs.length, 1);
chk("...marked as background", X.isBg(s.pairs[0]), true);
chk("...with no seed number", !s.pairs[0][4], true);

// The whole point of the suite: a background disc must not consume an ROI.
chk("the guided cursor did NOT advance", X.gTarget, 2);
chk("...and ROI 2 is still undrawn", X.usedRois(s).has(2), false);
chk("...nor did it become a region", X.polysOf(s).length, 1);

X.toggleBgMode();
chk("background mode is off again", X.bgMode, false);
square(400, 400, 80);
chk("the next region answers ROI 2, not ROI 3", X.polysOf(s)[1].roi, 2);
chk("usedRois counts regions only", [...X.usedRois(s)].sort().join(), "1,2");
chk("roiPairs / bgPairs split the list",
    X.roiPairs(s).length + "/" + X.bgPairs(s).length, "0/1");

// ---- the fit must not see them -------------------------------------------
// A background disc carries plate coords (0,0). If it reached the spline the
// fit would be pulled to the plate's corner, and nothing on screen would say so
// - the landmarks would still be drawn where they were placed.
note("\nthe transform:\n");
// Landmarks are placed FREE now - section, then the matching point on the plate
// - because the guided walk asks for areas, not points.
X.toggleGuided();
chk("guided off, so clicks place landmarks", X.guided, false);
const pair = (sx, sy, px, py) => {
  clickAt(sx, sy);
  X.clickPl({clientX: px, clientY: py, button: 0, preventDefault() {}});
};
pair(120, 120, 30, 30);
pair(200, 140, 90, 45);
pair(260, 120, 140, 80);
chk("three landmarks placed", X.roiPairs(s).length, 3);
const withBg = X.transform(s.pairs);
const withoutBg = X.transform(X.roiPairs(s));
chk("a fit exists", !!withBg, true);
chk("it is identical to one built without the background disc",
    JSON.stringify(withBg), JSON.stringify(withoutBg));

// ---- what reaches the exports --------------------------------------------
note("\nthe exports:\n");
X.markAssigned();
X.toggleFav();
blobs.length = 0;
X.exportCsv();

const rows = t => t.split("\n").map(l => l.split(","));
const pl = rows(blobs[0]), lm = rows(blobs[1]), rg = rows(blobs[2]);
const col = (h, name) => h.indexOf(name);

const rgH = rg[0], kindI = col(rgH, "roi_kind"), regI = col(rgH, "region");
const rgBody = rg.slice(1).filter(r => r[0] === uid);
chk("roi_regions.csv gained roi_kind", kindI > 0, true);
chk("...and every row declares one",
    rgBody.every(r => r[kindI] === "roi" || r[kindI] === "background"), true);
// TWO areas were drawn, and three landmarks placed. The landmarks are not ROIs
// any more, which is the whole change: a region is an area, and a point is not.
chk("2 regions drawn -> 2 roi rows",
    rgBody.filter(r => r[kindI] === "roi").length, 2);
chk("...every one a polygon, never a disc",
    rgBody.filter(r => r[kindI] === "roi")
          .every(r => r[col(rgH, "roi_shape")] === "polygon"), true);
chk("1 background disc -> 1 background row",
    rgBody.filter(r => r[kindI] === "background").length, 1);
chk("...named so it cannot be read as a place",
    rgBody.find(r => r[kindI] === "background")[regI], "__background__");
chk("...and it is the only thing left carrying a radius",
    +rgBody.find(r => r[kindI] === "background")[col(rgH, "sec_r")] > 0, true);
chk("no background row claims a seed",
    rgBody.filter(r => r[kindI] === "background" && r[col(rgH, "seed_n")] !== "").length, 0);

const lmBody = lm.slice(1).filter(r => r[0] === uid);
chk("roi_landmarks.csv holds landmarks only", lmBody.length, 3);
chk("...numbered 1..3 with no gap",
    lmBody.map(r => r[col(lm[0], "pair")]).join(), "1,2,3");

const plRow = pl.slice(1).find(r => r[0] === uid);
chk("roi_plates.csv gained n_background", col(pl[0], "n_background") > 0, true);
chk("...and reports it", plRow[col(pl[0], "n_background")], "1");
chk("n_landmarks excludes the background disc", plRow[col(pl[0], "n_landmarks")], "3");
// The header and the row are built in two different places in the source -
// a header of N names and a row of N+1 values silently shifts every column
// after the mismatch, with nothing on screen or in the diff saying so. Check
// it mechanically rather than by eye.
chk("roi_plates.csv header and row line up", plRow.length, pl[0].length);
chk("...gained plate_fp", col(pl[0], "plate_fp") > 0, true);
chk("...carrying the chosen plate's own fingerprint",
    plRow[col(pl[0], "plate_fp")], P.fp || "");
chk("...and plate_px, the size that fingerprint was taken at",
    plRow[col(pl[0], "plate_px")], P.w + "x" + P.h);
chk("...and plate_verified, blank until a later task gives it meaning",
    plRow[col(pl[0], "plate_verified")], "");
X.toggleGuided();

// ---- a section with too few landmarks for a fit --------------------------
// Both files used to be gated on `n >= 3 && transform`, so a lightly curated
// section exported nothing and read exactly like one nobody had touched. A
// region and a landmark are both just things the operator put somewhere, and a
// transform is not the price of admission for recording them. What goes blank is
// the residual, which really is unmeasurable without a fit - blank rather than
// 0, which would be a claim.
note("\na section with background discs but only one landmark:\n");
const thin = X.rows()[1].uid;
X.select(thin, true); X.active = thin;
X.onSlideUser(pi);
X.drawSec();
// One region, drawn the ordinary way.
clickAt(100, 100); clickAt(180, 100); clickAt(180, 180); clickAt(100, 180);
clickAt(100, 100);
// ...and one landmark, free, which is not enough for a fit.
X.toggleGuided();
clickAt(240, 240);
X.clickPl({clientX: 60, clientY: 60, button: 0, preventDefault() {}});
X.toggleGuided();
X.toggleBgMode();
clickAt(300, 300); clickAt(340, 340);
X.toggleBgMode();
X.markAssigned();
blobs.length = 0; X.exportCsv();
const rg2 = rows(blobs[2]).slice(1).filter(r => r[0] === thin);
const lm2 = rows(blobs[1]).slice(1).filter(r => r[0] === thin);
chk("the one drawn region is still exported",
    rg2.filter(r => r[kindI] === "roi").length, 1);
chk("...and both background discs",
    rg2.filter(r => r[kindI] === "background").length, 2);
chk("its landmark is exported too", lm2.length, 1);
chk("...with a blank residual rather than a zero",
    lm2[0][col(lm[0], "residual_px")], "");
chk("...and a blank mean residual on the region row",
    rg2.find(r => r[kindI] === "roi")[col(rgH, "mean_residual_px")], "");

// ---- a fit is either absent or finite, never NaN --------------------------
// solve3 can divide by a pivot that cleared its own floor and still return a
// non-finite result. An array of NaNs is truthy, so affine() used to hand it
// back as a real fit, and it would reach mean_residual_px as the string "NaN".
//
// Seeds are numbered down each column, so the first three placed on any plate
// are the most nearly collinear three the operator can produce - which makes
// them the right input to check this on. Note that on THIS plate set none of
// them actually degenerate: the guard is a net, not a behaviour change, and
// this asserts it has not become one.
note("\nconditioning, over every seeded plate:\n");
let nPlates = 0, nNoFit = 0, nNaN = 0;
for (const Q of X.PLATES) {
  if (Q.seeds.length < 3) continue;
  nPlates++;
  const pr = Q.seeds.slice(0, 3).map((sd, i) =>
    [100 + i * 10, 100 + i * 90, sd.xf * Q.w, sd.yf * Q.h, i + 1, 8]);
  const T2 = X.transform(pr);
  if (T2 === null) nNoFit++;
  else if (![...T2.a, ...T2.d].every(Number.isFinite)) nNaN++;
}
chk("plates with at least three seeds", nPlates > 20, true);
chk("no plate yields a fit made of NaN", nNaN, 0);
chk("...and none is rejected either, so the guard changed nothing", nNoFit, 0);

// ---- old saved state is unaffected ---------------------------------------
// The 7th element is additive: pairs written before this change are 5 or 6 long
// and must not read as background. Asserted rather than assumed, because the
// operator's store holds 268 sections written by the old code.
note("\nbackward compatibility:\n");
chk("a 5-element pair is not background", X.isBg([1, 2, 3, 4, 5]), false);
chk("a 6-element pair is not background", X.isBg([1, 2, 3, 4, 5, 6]), false);
chk("a pair with an unrelated 7th is not background",
    X.isBg([1, 2, 3, 4, 5, 6, "something"]), false);
chk("only the marker counts", X.isBg([1, 2, 0, 0, 0, 6, "bg"]), true);

done();
