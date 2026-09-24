// A section's plate must survive an atlas swap, or say that it did not.
//
// The failure this pins: keyed on the integer index, every assignment silently
// means a different plate after a swap. Keyed on the id ALONE it silently
// succeeds against a plate that has been re-rendered - which is what happened
// here on 2026-09-06, same 64 ids, 34 rows differing in geometry.
//
// The vocabulary is ls_atlas.plate_status's, exactly: ok / resized / changed /
// gone / unchecked / by_index. A seventh name, or the same six in a different
// order, is a section that verifies in the importer and not in the page.

const { load, chk, note, done } = require("./harness");

const P = load(`{resolvePlate, verifyPlate, plateAt, plateNotice, transform,
  BLANK_PLATE, ASPECT_TOL, PLATES, DATA, st, drawPl, set active(v){active=v}}`);

// A five-plate atlas standing in for the one on screen. Passed in rather than
// swapped for PLATES, so this suite does not depend on the operator's atlas.
//
//   plate_004 is 1028x1024 against a stored 1024x1024: inside ASPECT_TOL, so
//   RESIZED, and the two axis factors DIFFER. That is the case a single
//   width-only factor gets wrong, and the only one in this table that can tell
//   the two implementations apart. The sizes are powers of two plus a small
//   multiple so 1028/1024 is exactly 1.00390625 - this suite is testing which
//   axis a factor comes from, not floating point.
//   plate_005 is in the table with no readable image - a gap, not a shift.
const FAKE = [
  { id: "plate_001", fp: "aaaaaaaaaaaa", w: 100,  h: 200,  missing: 0, seeds: [], hulls: [] },
  { id: "plate_002", fp: "bbbbbbbbbbbb", w: 150,  h: 300,  missing: 0, seeds: [], hulls: [] },
  { id: "plate_003", fp: "cccccccccccc", w: 50,   h: 200,  missing: 0, seeds: [], hulls: [] },
  { id: "plate_004", fp: "dddddddddddd", w: 1028, h: 1024, missing: 0, seeds: [], hulls: [] },
  { id: "plate_005", fp: "",             w: 80,   h: 80,   missing: 1, seeds: [], hulls: [] },
];

// ---- the tolerance is the module's, not a literal -------------------------

chk("the aspect tolerance came through IO.fill as a number",
    typeof P.ASPECT_TOL === "number" && P.ASPECT_TOL > 0, true);

// ---- the six outcomes -----------------------------------------------------

chk("an assignment whose fingerprint matches is verified",
    P.resolvePlate({ plate: 0, plate_id: "plate_001", plate_fp: "aaaaaaaaaaaa",
                     plate_px: "100x200" }, FAKE).verified, "ok");

chk("a re-rendered plate is a resize",
    P.resolvePlate({ plate: 0, plate_id: "plate_002", plate_fp: "old",
                     plate_px: "100x200" }, FAKE).verified, "resized");

chk("...and its landmarks are scaled by the size ratio",
    P.resolvePlate({ plate: 0, plate_id: "plate_002", plate_fp: "old",
                     plate_px: "100x200",
                     pairs: [[10, 10, 20, 20, 0, 0, "roi"]] }, FAKE)
      .pairs[0][2], 30);

// ls_atlas.scale_between returns (sx, sy), not one k. A 1024x1024 plate
// re-rendered at 1028x1024 is RESIZED - the aspect moved by 0.39%, inside the
// tolerance - and a width-only factor would move every landmark's Y by 4 px
// that nothing measured. These two checks fail on `k = p.w / was[0]` for both.
const skew = P.resolvePlate(
  { plate: 0, plate_id: "plate_004", plate_fp: "old", plate_px: "1024x1024",
    pairs: [[7, 7, 1024, 1024, 0, 0, "roi"]] }, FAKE);
chk("a resize inside the aspect tolerance is still a resize", skew.verified, "resized");
chk("...x scales by the WIDTH ratio", skew.pairs[0][2], 1028);
chk("...and y by the HEIGHT ratio, not the width's", skew.pairs[0][3], 1024);
chk("...and the section coordinates are untouched",
    [skew.pairs[0][0], skew.pairs[0][1]].join(","), "7,7");

chk("a re-cropped plate has changed",
    P.resolvePlate({ plate: 0, plate_id: "plate_003", plate_fp: "old",
                     plate_px: "100x200" }, FAKE).verified, "changed");

chk("a plate the set no longer has is gone",
    P.resolvePlate({ plate: 0, plate_id: "plate_099", plate_fp: "x" }, FAKE).verified,
    "gone");

// ls_atlas.plate_status decides GONE before UNCHECKED, and a plate whose image
// cannot be read is GONE there too. Both halves, or the page and the importer
// disagree about a plate that is in the table with no picture.
chk("a plate in the table with no readable image is gone",
    P.resolvePlate({ plate: 4, plate_id: "plate_005", plate_fp: "x",
                     plate_px: "80x80" }, FAKE).verified, "gone");
chk("...and gone beats unchecked, as it does in plate_status",
    P.resolvePlate({ plate: 4, plate_id: "plate_005" }, FAKE).verified, "gone");

chk("the ASSIGNMENT is kept in every case",
    P.resolvePlate({ plate: 1, plate_id: "plate_099", plate_fp: "x" }, FAKE).plate_id,
    "plate_099");

chk("...and so is the index, when the id cannot be placed",
    P.resolvePlate({ plate: 1, plate_id: "plate_099", plate_fp: "x" }, FAKE).plate, 1);

chk("an export with no id at all restores by index and says so",
    P.resolvePlate({ plate: 2 }, FAKE).verified, "by_index");

chk("an id with no fingerprint is unchecked, not verified",
    P.resolvePlate({ plate: 0, plate_id: "plate_001" }, FAKE).verified, "unchecked");

chk("...and by index means the index, not a guess",
    P.resolvePlate({ plate: 2 }, FAKE).plate, 2);

chk("an id that moved position is followed to its new slot",
    P.resolvePlate({ plate: 0, plate_id: "plate_003", plate_fp: "cccccccccccc",
                     plate_px: "50x200" }, FAKE).plate, 2);

// The slot has to come from the array being resolved AGAINST. Reading an index
// out of the page's own 64-plate PLATES and then indexing the caller's array
// with it is the same class of bug one level up.
const other = [FAKE[2], FAKE[1], FAKE[0]];   // plate_003 first, plate_001 last
chk("the new slot is read from the atlas actually passed in",
    P.resolvePlate({ plate: 0, plate_id: "plate_001", plate_fp: "aaaaaaaaaaaa",
                     plate_px: "100x200" }, other).plate, 2);

// A polygon's vertices are coordinates on the SECTION, not on the plate, so a
// plate re-render must not touch them.
const withPoly = P.resolvePlate(
  { plate: 0, plate_id: "plate_002", plate_fp: "old", plate_px: "100x200",
    polys: [{ roi: 1, region: "Dl", v: [10, 10, 20, 20, 30, 10] }] }, FAKE);
chk("a re-render does not move the polygons drawn on the section",
    withPoly.polys[0].v.join(","), "10,10,20,20,30,10");

// The record is rebuilt, not mutated: an unresolved copy must not be left
// pointing into the same arrays.
const original = { plate: 0, plate_id: "plate_002", plate_fp: "old",
                   plate_px: "100x200", pairs: [[10, 10, 20, 20, 0, 0, "roi"]] };
P.resolvePlate(original, FAKE);
chk("resolving does not rewrite the record it was given",
    original.pairs[0][2], 20);

// ---- the gate -------------------------------------------------------------

// Three non-collinear pairs: TPS_MIN is 6, so this is the affine branch, and a
// degenerate triangle would return null for the wrong reason.
const TRI = [[0, 0, 0, 0, 0, 0, "roi"],
             [10, 0, 10, 0, 0, 0, "roi"],
             [0, 10, 0, 10, 0, 0, "roi"]];

chk("an unverified section's landmarks do not reach the transform",
    P.transform({ verified: "changed", pairs: TRI }), null);

chk("...nor a by_index one's", P.transform({ verified: "by_index", pairs: TRI }), null);
chk("...nor an unchecked one's", P.transform({ verified: "unchecked", pairs: TRI }), null);
chk("...nor a gone one's", P.transform({ verified: "gone", pairs: TRI }), null);
// A rescale is a correction, not a confirmation: the ratio cannot tell a
// re-render from a re-crop, so the scaled points still wait for a person.
chk("...nor a rescaled one's", P.transform({ verified: "resized", pairs: TRI }), null);

chk("...and a verified one's do",
    P.transform({ verified: "ok", pairs: TRI }) !== null, true);

// A record made in this session has no verdict at all, because it was matched
// against the atlas now loaded. An absent verdict is not a failed one.
chk("a section curated in this session is not gated",
    P.transform({ pairs: TRI }) !== null, true);

chk("a transform still cannot be asked for with the background discs in",
    P.transform({ verified: "ok",
                  pairs: TRI.concat([[99, 99, 0, 0, 0, 5, "bg"]]) }).kind, "affine");

chk("and below three points there is still no transform",
    P.transform({ verified: "ok", pairs: TRI.slice(0, 2) }), null);

// ---- bounds ---------------------------------------------------------------

chk("a stored index past the end of a shorter atlas does not throw",
    P.plateAt({ plate: 99 }, FAKE).id, "");
chk("...and the blank it gets back reads as having no image",
    P.plateAt({ plate: 99 }, FAKE).missing, 1);
chk("...and has the arrays every caller iterates",
    P.plateAt({ plate: 99 }, FAKE).seeds.length + P.plateAt({ plate: 99 }, FAKE).hulls.length,
    0);
chk("a record with no plate at all is bounds-safe too",
    P.plateAt({}, FAKE).id, "");
chk("and so is no record at all", P.plateAt(null, FAKE).id, "");
chk("a real index still returns the real plate", P.plateAt({ plate: 1 }, FAKE).id,
    "plate_002");
chk("with no atlas named it reads the page's own", P.plateAt({ plate: 0 }).id,
    P.PLATES.length ? P.PLATES[0].id : "");

// ---- the gap plate still fails CLOSED -------------------------------------
//
// Task 3 made drawPl check P.missing BEFORE touching the image, clear the
// canvas and draw a placeholder, so a plate with no readable image can never
// leave the PREVIOUS plate's pixels on screen under the NEW plate's header.
// plateAt has to keep that working: an index past the end of the atlas becomes
// the blank, which carries missing:1, so the same branch fires rather than a
// TypeError on `.seeds`. Exercised, not read.
if (P.DATA.length) {
  const uid = P.DATA[0].uid;
  P.active = uid;
  P.st(uid).plate = 99999;
  let threw = null;
  try { P.drawPl(); } catch (e) { threw = e && e.message; }
  chk("an index past the end of the atlas does not take drawPl down", threw, null);
  chk("...because it resolves to a plate with no readable image",
      P.plateAt(P.st(uid)).missing, 1);
  P.st(uid).plate = 0;
  P.active = null;
} else {
  note("no sections in this page - skipping the drawPl gap check");
}

// ---- what the operator is told --------------------------------------------

// plateNotice counts the live store, which --no-seed leaves empty, so this
// pins the shape of the report rather than a number off the operator's data.
chk("nothing to re-confirm is not reported", P.plateNotice(), 0);

done();
