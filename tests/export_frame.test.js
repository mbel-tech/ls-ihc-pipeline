// The export's scale is PER SECTION, and the quoting is per FIELD.
//
// Landmarks are stored in the pixels of the image the section was shown with:
// 768 for a section with a colour composite, 256 (the canonical grid) for one
// that fell back to greyscale. Export divides by K = frame / 256 so the CSVs
// are always canonical. K used to be read ONCE from the image on screen and
// applied to every row, so on a page carrying both kinds the rows of whichever
// kind was not active were off by a factor of three - and nothing said so,
// because the harness's Image was 768 for everything and a browser only ever
// shows one section at a time.
//
// The second half: dl() joined with "," and quoted nothing. Region names such
// as "Rm (Raphe) ??" and subsets like roi_worklist:core are already in the
// files; the first one with a comma in it would have shifted every column
// after it.

const { env, load, chk, note, done } = require("./harness");
const { els, blobs, fire } = env;

// 768 for a composite, 256 for a greyscale - the frames the real page shows.
env.imgSize = src => /_rgb\//.test(src) ? 768 : 256;

const X = load(`{toggleGuided, clickPl, PLATES, DATA, D_BY, S, st, rows, select, onSlideUser, exportCsv,
  secDown, toggleBgMode, roiPairs, bgPairs, drawSec,
  get bgMode(){return bgMode}, get secImg(){return secImg},
  set active(v){active=v}, get active(){return active}}`);

const pi = X.PLATES.findIndex(P => P.labelled);
const P = X.PLATES[pi];
els["animal"].value = "LS105";
const list = X.rows();
const [A, B, C, D, E] = list.slice(0, 5).map(d => d.uid);
chk("five sections to work with", list.length >= 5, true);

// The page was built with --rgb, so every section claims a composite. Take the
// composite away from B and D: what the page does for a section 04o has not
// built yet.
for (const u of [B, D]) {
  const d = X.D_BY[u];
  d.rgb = false; d.img = d.img.replace("_rgb/", "/");
}
X.select(A, true);
chk("A shows the 768 composite", X.secImg.naturalWidth, 768);
X.select(B, true);
chk("B shows the 256 greyscale", X.secImg.naturalWidth, 256);

const clickAt = (cx, cy) => {
  X.secDown({ clientX: cx, clientY: cy, button: 0, preventDefault() {} });
  fire("mouseup", {});
};
// Three landmarks and one background disc, through the same clicks the operator
// makes, so the frame is stamped where the page stamps it. Landmarks are placed
// FREE - section, then the matching point on the plate - because the guided walk
// asks for areas now.
const place = uid => {
  X.select(uid, true); X.active = uid; X.onSlideUser(pi); X.drawSec();
  X.toggleGuided();
  [[100,100,30,30],[200,150,90,45],[150,250,140,80]].forEach(([sx,sy,px,py]) => {
    clickAt(sx, sy);
    X.clickPl({clientX: px, clientY: py, button: 0, preventDefault(){}});
  });
  X.toggleGuided();
  X.toggleBgMode(); clickAt(300, 300); X.toggleBgMode();
  // ...and one drawn region, because that is what an ROI is now and its
  // vertices ride the same per-section divisor.
  clickAt(120, 120); clickAt(220, 120); clickAt(220, 220); clickAt(120, 220);
  clickAt(120, 120);
  return X.st(uid);
};

note("\n(a) one page, two frames\n");
const sA = place(A), sB = place(B);
chk("A: 3 landmarks + 1 disc", X.roiPairs(sA).length + "/" + X.bgPairs(sA).length, "3/1");
chk("B: 3 landmarks + 1 disc", X.roiPairs(sB).length + "/" + X.bgPairs(sB).length, "3/1");
chk("A's record carries its frame", sA.frame, 768);
chk("B's record carries its frame", sB.frame, 256);
// Same clicks, different image: the stored pixels differ by about the frame
// ratio (the canvas is the rounded diagonal, so not exactly), which is what the
// export has to undo per section.
chk("the same click lands ~3x further in A's pixels",
    Math.abs(sA.pairs[0][0] / sB.pairs[0][0] - 3) < 0.15, true);

const rows = t => t.split("\n").map(l => l.split(","));
const canon = (ps, frame) =>
  ps.map(p => [p[0], p[1], p[5]].map(v => (v * 256 / frame).toFixed(2)).join()).join("|");
const canonPoly = (s, frame) => (s.polys || []).map(pg => {
  const o = [];
  for (let i = 0; i < pg.v.length; i += 2)
    o.push((pg.v[i] * 256 / frame).toFixed(2) + " " + (pg.v[i+1] * 256 / frame).toFixed(2));
  return o.join(";");
}).join("|");
const want = (s, frame) => ({ lm: canon(X.roiPairs(s), frame),
                              bg: canon(X.bgPairs(s), frame),
                              poly: canonPoly(s, frame) });
const got = (lm, rg, uid) => {
  const h = lm[0], xi = h.indexOf("sec_x"), yi = h.indexOf("sec_y"), ri = h.indexOf("sec_r");
  const g = rg[0], gx = g.indexOf("sec_x"), gy = g.indexOf("sec_y"), gr = g.indexOf("sec_r"),
        ki = g.indexOf("roi_kind");
  const pick = (r, a, b, c) => [r[a], r[b], r[c]].join();
  return {
    lm: lm.slice(1).filter(r => r[0] === uid).map(r => pick(r, xi, yi, ri)).join("|"),
    // A region is a polygon now, so what the divisor has to be right about is
    // its VERTEX LIST, not a centre and a radius it no longer has.
    poly: rg.slice(1).filter(r => r[0] === uid && r[ki] === "roi")
            .map(r => r[g.indexOf("sec_poly")]).join("|"),
    bg: rg.slice(1).filter(r => r[0] === uid && r[ki] === "background").map(r => pick(r, gx, gy, gr)).join("|"),
  };
};
const exportWith = uid => {
  X.select(uid, true); X.active = uid; X.drawSec();
  blobs.length = 0; X.exportCsv();
  return { lm: rows(blobs[1]), rg: rows(blobs[2]) };
};
const WA = want(sA, 768), WB = want(sB, 256);
for (const act of [A, B]) {
  const { lm, rg } = exportWith(act);
  const gA = got(lm, rg, A), gB = got(lm, rg, B);
  note(`  active = ${act === A ? "A (768)" : "B (256)"}`);
  chk("  A landmarks canonical", gA.lm, WA.lm);
  chk("  A regions canonical", gA.poly, WA.poly);
  chk("  A background canonical", gA.bg, WA.bg);
  chk("  B landmarks canonical", gB.lm, WB.lm);
  chk("  B regions canonical", gB.poly, WB.poly);
  chk("  B background canonical", gB.bg, WB.bg);
}
// Canonical means inside the 256 grid, whichever image the click was made on.
{
  const { lm } = exportWith(B);
  const xi = lm[0].indexOf("sec_x");
  const vals = lm.slice(1).filter(r => r[0] === A || r[0] === B).map(r => +r[xi]);
  chk("every sec_x fits the canonical grid", vals.every(v => v >= 0 && v < 256), true);
}

note("\n(b) a record with no frame is read in the frame its rgb flag implies\n");
// Stores written before the frame was recorded: a composite section's pairs are
// in 768 px, a greyscale one's in 256 px. Seeded straight into S, no click.
const seed = P.seeds[0];
const roi0 = P.hulls[0];
const mk = (x, y, r) => ({
  plate: pi,
  // The landmark keeps a seed number here on purpose: pairs written before ROIs
  // became areas carry one, the operator's store is full of them, and
  // roi_landmarks.csv still resolves `seed_region` through it. New pairs get 0.
  pairs: [[x, y, seed.xf * P.w, seed.yf * P.h, 1, r], [x + 30, y, 0, 0, 0, r, "bg"]],
  // A region carries the name now, so a comma in one has to survive through a
  // polygon row rather than a disc row.
  polys: [{v: [x, y, x + 40, y, x + 40, y + 40, x, y + 40],
           roi: roi0.roi, region: roi0.region, part: roi0.part}],
  assigned: true, noroi: false, fav: false, rot: 0, excl: false,
});
X.S[C] = mk(300, 150, 33);        // composite -> 768 frame
X.S[D] = mk(100, 50, 11);         // greyscale -> 256 frame
{
  const { lm, rg } = exportWith(B);
  const gC = got(lm, rg, C), gD = got(lm, rg, D);
  chk("composite, no frame: divided by 3", gC.lm, "100.00,50.00,11.00");
  chk("...its disc too", gC.bg, "110.00,50.00,11.00");
  chk("greyscale, no frame: divided by 1", gD.lm, "100.00,50.00,11.00");
  chk("...its disc too", gD.bg, "130.00,50.00,11.00");
}

note("\n(b') a store written without --rgb draws correctly under --rgb\n");
// E has a composite now, but its pairs were placed on the greyscale: the record
// says frame 256. Showing it at 768 must lift the pairs into that frame, not
// draw them in the wrong corner - and the export must still read canonical.
X.S[E] = Object.assign(mk(100, 50, 11), { frame: 256 });
X.select(E, true); X.active = E; X.drawSec();
chk("pairs were lifted to the 768 frame",
    X.S[E].pairs[0].slice(0, 2).join() + "," + X.S[E].pairs[0][5], "300,150,33");
chk("...the disc with them",
    X.S[E].pairs[1].slice(0, 2).join() + "," + X.S[E].pairs[1][5], "390,150,33");
chk("...and the record now says so", X.S[E].frame, 768);
{
  const { lm, rg } = exportWith(E);
  chk("export unchanged by the rescale", got(lm, rg, E).lm, "100.00,50.00,11.00");
}

note("\n(c) a comma in a region name is one quoted field\n");
const orig = roi0.region, origSeed = seed.region;
roi0.region = seed.region = "Rm (Raphe), ??";
X.S[C] = mk(300, 150, 33);
X.S[C].polys[0].region = roi0.region;
{
  blobs.length = 0; X.exportCsv();
  const rg = blobs[2].split("\n"), ri = rg[0].split(",").indexOf("region");
  const line = rg.find(l => l.startsWith(C + ",") && l.includes("Raphe")) || "";
  chk("the field is quoted in the file", line.includes('"Rm (Raphe), ??"'), true);
  // A minimal RFC-4180 reader: the row must come back with the header's width.
  const parse = l => {
    const out = []; let f = "", q = false;
    for (let i = 0; i < l.length; i++) {
      const c = l[i];
      if (q) { if (c === '"') { if (l[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ",") { out.push(f); f = ""; }
      else f += c;
    }
    out.push(f); return out;
  };
  const row = parse(line), ncol = rg[0].split(",").length;
  chk("...and the row keeps the header's width", row.length, ncol);
  chk("...with the name intact", row[ri], "Rm (Raphe), ??");
  chk("the header is untouched", rg[0].includes('"'), false);
  chk("a plain row has no quotes", (rg.find(l => l.startsWith(A + ",")) || '"').includes('"'), false);
  // roi_plates carries the subset, which holds a colon but never a comma.
  chk("roi_plates is byte-identical when nothing needs quoting", blobs[0].includes('"'), false);
  // roi_landmarks names the seed's region too, so the same name is quoted
  // there and nowhere else in that file.
  const lmLines = blobs[1].split("\n");
  chk("roi_landmarks quotes the same name", lmLines.some(l => l.includes('"Rm (Raphe), ??"')), true);
  chk("...and nothing else", lmLines.filter(l => !l.includes("Raphe")).some(l => l.includes('"')), false);
}
roi0.region = orig; seed.region = origSeed;

done();
