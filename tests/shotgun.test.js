// Shotgun: what goes in the deck, how it is split, and whether the file is real.
//
// Two halves to this. The first is selection and layout - which sections are
// picked up, which slide each lands on, which side it lands on - and that is
// ordinary state logic the stub can drive. The second is the package: the page
// hand-writes a .pptx, so "it produced bytes" is not evidence of anything. The
// ZIP is parsed back here and every entry's CRC recomputed with zlib, which is
// an independent check rather than the page agreeing with itself.
//
// What this cannot cover: whether PowerPoint likes the result. The canvas is a
// stub, so every tile is the same 1x1 PNG and nothing is rendered.
// tests/test_shotgun_pptx.py takes the file this writes and goes further.

const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { env, load, chk, note, done } = require("./harness");
const { els, concat } = env;

const X = load(`{DATA, PLATES, MARKERS, S, GROUPS, st, roiPairs,
  shotPick, shotSlides, shotWhyNot, shotBtnState, shotBuild, zipStore, crc32,
  markerOnly, secRegions}`);

// ---- a curation state of our own -------------------------------------------
// Cleared first: the page may have been generated with the operator's curation
// embedded, and a suite whose numbers move when somebody favourites a section
// is not a test of anything.
for (const k of Object.keys(X.S)) delete X.S[k];

const perk = X.DATA.filter(d => d.m === "AF568");
const pcna = X.DATA.filter(d => d.m === "AF488");
const byAnimal = a => perk.filter(d => d.animal === a);

// The fixture needs six animals: one control with twelve sections (the
// overflow), one control with a PCNA section, one control with two sections,
// two exercise animals, and one outside the key. They are picked from whatever
// the page carries rather than named, so the suite does not depend on which
// animals were scanned.
const A = [...new Set(perk.map(d => d.animal))].sort((a, b) => +a.slice(2) - +b.slice(2));
const CTRL_BIG = A.find(a => byAnimal(a).length >= 12);
const rest = A.filter(a => a !== CTRL_BIG && byAnimal(a).length >= 2 && pcna.some(d => d.animal === a));
chk("an animal with twelve pERK sections exists", !!CTRL_BIG, true);
chk("five more animals with two sections and a PCNA side", rest.length >= 5, true);
const [CTRL_A, CTRL_C, EX_A, EX_B, OUT] = rest;
// Two distinct plates are all the layout needs; which two does not matter.
const PA = 0, PB = Math.min(3, X.PLATES.length - 1);
chk("the page carries at least two plates", PA < PB, true);

// GROUPS is a const in the page, so it is emptied and refilled rather than
// replaced. CLEARED FIRST, for the same reason S is above: the page embeds
// whatever groups.by_animal config.json holds, and config.json is gitignored -
// it differs per machine and changes the day somebody fills in the real
// unblinding key.
X.GROUPS.order.length = 0;
for (const k of Object.keys(X.GROUPS.by_animal)) delete X.GROUPS.by_animal[k];
X.GROUPS.order.push("control", "exercise");
Object.assign(X.GROUPS.by_animal, {
  [CTRL_A]: "control", [CTRL_BIG]: "control", [CTRL_C]: "control",
  [EX_A]: "exercise", [EX_B]: "exercise",
});

const fav = (d, plate, extra) => {
  const s = X.st(d.uid);
  s.fav = true; s.plate = plate; s.assigned = true;
  Object.assign(s, extra || {});
  return d;
};

// plate PA: one section per treatment, the simplest slide there is.
const a9 = fav(byAnimal(CTRL_A)[0], PA);
const b9 = fav(byAnimal(EX_A)[0], PA);
// plate PB: twelve control sections, so one half overflows and the other does not.
const twelve = byAnimal(CTRL_BIG).slice(0, 12);
twelve.forEach(d => fav(d, PB));
fav(byAnimal(EX_B)[0], PB);
// plate PA again, other channel: a separate slide, never mixed in with the pERK one.
const pcna9 = fav(pcna.filter(d => d.animal === CTRL_A)[0], PA);
// the ones that must NOT come through
const noPlate = X.st(byAnimal(CTRL_C)[0].uid);   noPlate.fav = true;
const dropped = fav(byAnimal(CTRL_C)[1], PA, {excl: true});
const ungrouped = fav(byAnimal(OUT)[0], PA);     // animal not in the key

// ---- the gate ---------------------------------------------------------------
chk("group key present -> enabled", X.shotWhyNot(), "");
X.shotBtnState();
chk("button enabled", els["shotBtn"].disabled, false);
const savedProto = global.location.protocol;
global.location = { protocol: "file:" };
chk("file:// -> refused", X.shotWhyNot().includes("cannot read its own images"), true);
X.shotBtnState();
chk("button disabled off disk", els["shotBtn"].disabled, true);
// Opening the page from disk is the NORMAL way this file gets launched, so the
// disabled state is the one the operator sees most. It was reported as "not
// visible" twice while being present, enabled-looking in the DOM and greyed to
// 40% opacity - so the reason has to be on screen, not in a tooltip nobody
// hovers on a control they have decided is dead.
chk("...and says why on screen", els["shotStat"].innerHTML.includes("Shotgun off"), true);
chk("...naming the fix, not just the fault",
    els["shotStat"].innerHTML.includes("from the app"), true);
global.location = { protocol: savedProto };

// Re-enabling must NOT wipe the span: shotSay puts the build summary there and
// shotBtnState runs at the end of that chain.
els["shotStat"].innerHTML = "wrote 7 slides";
X.shotBtnState();
chk("enabling leaves the build summary alone", els["shotStat"].innerHTML, "wrote 7 slides");
els["shotStat"].innerHTML = "";
const savedOrder = X.GROUPS.order.splice(0, 2);
chk("no group key -> refused", X.shotWhyNot().includes("no group key"), true);
X.GROUPS.order.push(...savedOrder);

// ---- selection ---------------------------------------------------------------
note("");
const pick = X.shotPick();
chk("favourite with no plate is skipped", pick.noPlate.length, 1);
chk("excluded favourite is skipped", pick.excluded.length, 1);
chk("animal outside the key is skipped", pick.noGroup.length, 1);
chk("skipped sections are reported, not dropped",
    pick.noPlate.length + pick.excluded.length + pick.noGroup.length, 3);
chk("selected", pick.take.length, 2 + 13 + 1);
chk("nothing selected is excluded", pick.take.some(it => it.s.excl), false);
chk("every selection carries its treatment",
    pick.take.every(it => X.GROUPS.order.includes(it.g)), true);

// ---- slides -------------------------------------------------------------------
note("");
const slides = X.shotSlides(pick.take);
chk("plate A pERK, plate A PCNA, plate B over two pages", slides.length, 4);
chk("ordered by plate then marker",
    slides.map(s => s.plate + s.marker).join(" "),
    `${PA}AF568 ${PA}AF488 ${PB}AF568 ${PB}AF568`);
chk("pERK before PCNA on the same plate",
    slides[0].marker + " " + slides[1].marker, "AF568 AF488");

const p9 = slides[0];
chk("plate A: one each side", p9.halves.map(h => h.length).join("/"), "1/1");
chk("left half is groups.order[0]", p9.halves[0][0].g, "control");
chk("right half is groups.order[1]", p9.halves[1][0].g, "exercise");
chk("left half is the control animal", p9.halves[0][0].d.animal, CTRL_A);

const p12a = slides[2], p12b = slides[3];
chk("overflow: two pages", p12a.pages, 2);
chk("page 1 fills the half", p12a.halves[0].length, 10);
chk("page 2 carries the remainder", p12b.halves[0].length, 2);
chk("nothing is dropped in the overflow",
    p12a.halves[0].length + p12b.halves[0].length, 12);
chk("the other half is not padded",
    p12a.halves[1].length + p12b.halves[1].length, 1);
chk("the section count on both pages is the plate's total", p12a.n + "/" + p12b.n, "13/13");
chk("a section appears on exactly one slide",
    new Set(slides.flatMap(s => s.halves.flat().map(it => it.d.uid))).size,
    pick.take.length);

// ---- build --------------------------------------------------------------------
note("");
// The stub Image never fires onload, and fetch would go to the network. Both are
// replaced here rather than in the harness: no other suite loads an image.
global.Image = function () {
  const im = {naturalWidth: 768, naturalHeight: 768, addEventListener() {}};
  Object.defineProperty(im, "src", {set(v) { queueMicrotask(() => im.onload && im.onload()); }});
  return im;
};
const PLATE_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4, 5, 6, 7, 8]);
let fetched = 0;
global.fetch = url => { fetched++; return Promise.resolve(
  {ok: true, arrayBuffer: () => Promise.resolve(PLATE_BYTES.buffer.slice(0))}); };

X.shotBuild().then(res => {
  chk("built every slide", res.slides, 4);
  chk("built every section", res.sections, pick.take.length);

  const names = res.files.map(f => f.name);
  const need = ["[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml",
                "ppt/_rels/presentation.xml.rels", "ppt/presProps.xml",
                "ppt/theme/theme1.xml", "ppt/slideMasters/slideMaster1.xml",
                "ppt/slideMasters/_rels/slideMaster1.xml.rels",
                "ppt/slideLayouts/slideLayout1.xml",
                "ppt/slideLayouts/_rels/slideLayout1.xml.rels"];
  chk("every required part is present", need.filter(n => !names.includes(n)).join(",") || "-", "-");
  chk("one slide part per slide", names.filter(n => /ppt.slides.slide\d+\.xml$/.test(n)).length, 4);
  chk("one rels part per slide", names.filter(n => /slide\d+\.xml\.rels$/.test(n)).length, 4);
  chk("no duplicate part names", new Set(names).size, names.length);

  // Four slides, each showing a plate, but only two DISTINCT plates: plate A on
  // the pERK and the PCNA slide, plate 12 on both of its pages. Storing per
  // slide would put two extra copies of a megabyte-sized plate in the file.
  const media = names.filter(n => n.startsWith("ppt/media/"));
  chk("media = one per section plus one per distinct plate",
      media.length, pick.take.length + 2);
  chk("a plate on two slides is fetched once", fetched, 2);

  // Every r:embed has to resolve, or PowerPoint reports a corrupt file.
  const text = f => Buffer.from(f.bytes).toString("utf8");
  let unresolved = 0;
  for (let i = 1; i <= 4; i++) {
    const sl = text(res.files.find(f => f.name === `ppt/slides/slide${i}.xml`));
    const rl = text(res.files.find(f => f.name === `ppt/slides/_rels/slide${i}.xml.rels`));
    const ids = new Set([...rl.matchAll(/Id="([^"]+)"/g)].map(m => m[1]));
    for (const m of sl.matchAll(/r:embed="([^"]+)"/g)) if (!ids.has(m[1])) unresolved++;
    for (const m of rl.matchAll(/Target="\.\.\/media\/([^"]+)"/g))
      if (!names.includes("ppt/media/" + m[1])) unresolved++;
  }
  chk("every picture reference resolves", unresolved, 0);

  const s1 = text(res.files.find(f => f.name === "ppt/slides/slide1.xml"));
  chk("slide names its plate", s1.includes(X.PLATES[PA].id), true);
  chk("slide names both treatments", s1.includes("CONTROL") && s1.includes("EXERCISE"), true);
  chk("continuation slide says so",
      text(res.files.find(f => f.name === "ppt/slides/slide4.xml")).includes("(2 of 2)"), true);

  // ---- the ZIP itself ---------------------------------------------------------
  note("");
  const buf = Buffer.from(concat(res.blob.parts));
  const eocd = buf.length - 22;
  chk("ends with an EOCD record", buf.readUInt32LE(eocd).toString(16), "6054b50");
  const n = buf.readUInt16LE(eocd + 8);
  chk("central directory counts every part", n, res.files.length);

  let off = buf.readUInt32LE(eocd + 16), bad = 0, badCrc = 0, seen = 0;
  for (let i = 0; i < n; i++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) { bad++; break; }
    const nameLen = buf.readUInt16LE(off + 28);
    const extra = buf.readUInt16LE(off + 30), cmt = buf.readUInt16LE(off + 32);
    const crc = buf.readUInt32LE(off + 16), size = buf.readUInt32LE(off + 24);
    const name = buf.slice(off + 46, off + 46 + nameLen).toString("latin1");
    const lo = buf.readUInt32LE(off + 42);
    if (buf.readUInt32LE(lo) !== 0x04034b50) { bad++; }
    if (buf.readUInt16LE(lo + 8) !== 0) { bad++; }          // method 0, stored
    const body = buf.slice(lo + 30 + buf.readUInt16LE(lo + 26) + buf.readUInt16LE(lo + 28),
                           lo + 30 + buf.readUInt16LE(lo + 26) + buf.readUInt16LE(lo + 28) + size);
    if (zlib.crc32(body) !== crc) badCrc++;
    if (name === "[Content_Types].xml") seen++;
    off += 46 + nameLen + extra + cmt;
  }
  chk("every local header is where the directory says", bad, 0);
  chk("every CRC matches the stored bytes", badCrc, 0);
  chk("the package is addressable by name", seen, 1);

  const out = path.join(__dirname, "build", "shotgun.pptx");
  fs.mkdirSync(path.dirname(out), {recursive: true});
  fs.writeFileSync(out, buf);
  note(`\nwrote ${out} (${buf.length} bytes) for test_shotgun_pptx.py`);

  return region();
}).then(done)
  .catch(e => { console.error("BUILD ERROR:", e && e.stack || e); process.exit(1); });

// ---- the other cut: one slide per region -------------------------------------
//
// Runs AFTER the plate build, deliberately. It adds ROIs to sections the plate
// assertions above have already counted, and doing that first would move every
// number in them.
//
// Seeds are synthesised rather than read from the atlas. Which plates carry
// region seeds is data on disk that a re-extraction can change, and five
// assertions that quietly depend on it is the trap the GROUPS block at the top
// of this file already documents.
function region() {
  note("");
  X.PLATES[PA].seeds = [{region: "Dm"}, {region: "Dl"}];
  X.PLATES[PB].seeds = [{region: "Dm"}, {region: "Vv"}];
  const seed = (d, n) => X.st(d.uid).pairs.push([10, 10, 20, 20, n, 5]);
  seed(a9, 1); seed(a9, 2);              // one control section in two regions
  seed(b9, 1);                           // its exercise counterpart, in one
  twelve.forEach(d => seed(d, 2));       // twelve control sections in Vv
  // pcna9 is left with no ROI at all, and must therefore reach no region slide.

  chk("regions come from the seeds the ROIs answer",
      X.secRegions(X.st(a9.uid)).join(","), "Dm,Dl");
  chk("a free-clicked ROI has no region",
      X.secRegions({plate: PA, pairs: [[1, 1, 2, 2]]}).length, 0);
  chk("no seeded ROI -> no region", X.secRegions(X.st(pcna9.uid)).length, 0);

  const pick = X.shotPick();
  const rs = X.shotSlides(pick.take, "region");
  chk("one slide per region, rostral first", rs.map(s => s.region).join(" "),
      "Dl Dm Vv");
  chk("...and no plate on any of them", rs.some(s => s.plate !== undefined), false);
  chk("a section lands on every region it carries",
      rs.filter(s => s.halves.flat().some(it => it.d.uid === a9.uid)).length, 2);
  chk("a favourite with no seeded ROI lands on none",
      rs.filter(s => s.halves.flat().some(it => it.d.uid === pcna9.uid)).length, 0);
  // The plate deck splits twelve over two pages at ten a half. The region deck
  // has the plate band back, so they fit on one.
  const vv = rs.filter(s => s.region === "Vv");
  chk("a region half holds twenty, so twelve fit on one page", vv.length, 1);
  chk("...all twelve of them", vv[0].halves[0].length, 12);
  chk("the empty half is still drawn", vv[0].halves.length, X.GROUPS.order.length);

  const before = fetched;
  return X.shotBuild("region").then(res => {
    chk("built every region slide", res.slides, 3);
    const names = res.files.map(f => f.name);
    chk("one slide part per region slide",
        names.filter(n => /ppt.slides.slide\d+\.xml$/.test(n)).length, 3);
    // 14 distinct sections carry a region; a section on two slides is one image.
    chk("media = one per section, none per plate",
        names.filter(n => n.startsWith("ppt/media/")).length, 14);
    chk("no plate is fetched for a region slide", fetched - before, 0);

    const text = f => Buffer.from(f.bytes).toString("utf8");
    const s1 = text(res.files.find(f => f.name === "ppt/slides/slide1.xml"));
    chk("the slide names its region", s1.includes("Dl"), true);
    chk("...and not a plate it does not have", s1.includes(X.PLATES[PA].id), false);
    // The level moved from the title to the captions; it must not just vanish.
    chk("every cell carries its own plate",
        s1.includes(X.PLATES[PA].id.replace("plate_", "p")), true);

    let unresolved = 0;
    for (let i = 1; i <= 3; i++) {
      const sl = text(res.files.find(f => f.name === `ppt/slides/slide${i}.xml`));
      const rl = text(res.files.find(f => f.name === `ppt/slides/_rels/slide${i}.xml.rels`));
      const ids = new Set([...rl.matchAll(/Id="([^"]+)"/g)].map(m => m[1]));
      for (const m of sl.matchAll(/r:embed="([^"]+)"/g)) if (!ids.has(m[1])) unresolved++;
    }
    chk("every picture reference resolves", unresolved, 0);
  });
}
