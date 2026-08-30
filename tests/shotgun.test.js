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
  markerOnly}`);

// ---- a curation state of our own -------------------------------------------
// Cleared first: the page may have been generated with the operator's curation
// embedded, and a suite whose numbers move when somebody favourites a section
// is not a test of anything.
for (const k of Object.keys(X.S)) delete X.S[k];

const perk = X.DATA.filter(d => d.m === "AF568");
const pcna = X.DATA.filter(d => d.m === "AF488");
const byAnimal = a => perk.filter(d => d.animal === a);

// GROUPS is a const in the page, so it is filled rather than replaced.
X.GROUPS.order.push("control", "exercise");
Object.assign(X.GROUPS.by_animal, {
  LS22: "control", LS45: "control", LS61: "control",
  LS69: "exercise", LS85: "exercise", LS105: "exercise",
});

const fav = (d, plate, extra) => {
  const s = X.st(d.uid);
  s.fav = true; s.plate = plate; s.assigned = true;
  Object.assign(s, extra || {});
  return d;
};

// plate 9: one section per treatment, the simplest slide there is.
const a9 = fav(byAnimal("LS22")[0], 9);
const b9 = fav(byAnimal("LS69")[0], 9);
// plate 12: twelve control sections, so one half overflows and the other does not.
const twelve = byAnimal("LS45").slice(0, 12);
twelve.forEach(d => fav(d, 12));
fav(byAnimal("LS85")[0], 12);
// plate 9 again, other channel: a separate slide, never mixed in with the pERK one.
fav(pcna.filter(d => d.animal === "LS22")[0], 9);
// the ones that must NOT come through
const noPlate = X.st(byAnimal("LS61")[0].uid);   noPlate.fav = true;
const dropped = fav(byAnimal("LS61")[1], 9, {excl: true});
const ungrouped = fav(byAnimal("LS120")[0], 9);  // animal not in the key

// ---- the gate ---------------------------------------------------------------
chk("group key present -> enabled", X.shotWhyNot(), "");
X.shotBtnState();
chk("button enabled", els["shotBtn"].disabled, false);
const savedProto = global.location.protocol;
global.location = { protocol: "file:" };
chk("file:// -> refused", X.shotWhyNot().includes("cannot read its own images"), true);
X.shotBtnState();
chk("button disabled off disk", els["shotBtn"].disabled, true);
global.location = { protocol: savedProto };
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
chk("plate 9 pERK, plate 9 PCNA, plate 12 over two pages", slides.length, 4);
chk("ordered by plate then marker",
    slides.map(s => s.plate + s.marker).join(" "),
    "9AF568 9AF488 12AF568 12AF568");
chk("pERK before PCNA on the same plate",
    slides[0].marker + " " + slides[1].marker, "AF568 AF488");

const p9 = slides[0];
chk("plate 9: one each side", p9.halves.map(h => h.length).join("/"), "1/1");
chk("left half is groups.order[0]", p9.halves[0][0].g, "control");
chk("right half is groups.order[1]", p9.halves[1][0].g, "exercise");
chk("left half is the control animal", p9.halves[0][0].d.animal, "LS22");

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

  // Four slides, each showing a plate, but only two DISTINCT plates: plate 9 on
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
  chk("slide names its plate", s1.includes(X.PLATES[9].id), true);
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
  done();
}).catch(e => { console.error("BUILD ERROR:", e && e.stack || e); process.exit(1); });
