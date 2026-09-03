// A record is work only if it holds a decision. Looking at a section is not one.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs } = env;

const X = load(`{KEY, S, SEED_STATE, st, rows, select, onSlide, status, initState, hasDecision,
  hasRoiWork, adoptSeed, exportCsv, isExcl, isDone, cellTag, toggleExcl,
  set active(v){active=v}, get active(){return active}}`);

const blank = () => ({plate: 0, pairs: [], assigned: false, noroi: false, fav: false, rot: 0, excl: false});
chk("a fresh record is not a decision", X.hasDecision(blank()), false);
chk("a favourite is", X.hasDecision({...blank(), fav: true}), true);
chk("a background disc is", X.hasDecision({...blank(), pairs: [[1, 2, 3, 4, 0, 5, "bg"]]}), true);
chk("a review verdict is", X.hasDecision({...blank(), rev: {act: "drop"}}), true);
chk("a tilt is", X.hasDecision({...blank(), rot: 12}), true);
chk("but a tilt is not ROI work", X.hasRoiWork({...blank(), rot: 12}), false);
chk("undefined is not", X.hasDecision(undefined), false);

const seed = {A: {...blank(), fav: true}, B: blank()};
chk("seed fills an empty store, minus blanks", Object.keys(X.initState(null, seed)).join(), "A");
chk("stored work wins over the seed",
    Object.keys(X.initState(JSON.stringify({C: {...blank(), excl: true}}), seed)).join(), "C");
chk("a store holding only blanks counts as empty",
    Object.keys(X.initState(JSON.stringify({B: blank()}), seed)).join(), "A");
chk("garbage in the store is ignored", Object.keys(X.initState("{not json", seed)).join(), "A");

els["animal"].value = "LS105";
const uids = X.rows().map(d => d.uid);
chk("fixture needs five sections", uids.length >= 5, true);
X.select(uids[0], true);
X.onSlide(4);
chk("select + slide stores no record", uids[0] in JSON.parse(store[X.KEY] || "{}"), false);
X.active = uids[0]; X.toggleExcl();
chk("...but a decision does", JSON.parse(store[X.KEY])[uids[0]].excl, true);

X.active = null; X.status();
chk("status() with nothing selected adds no record", "null" in X.S, false);

for (const k of Object.keys(X.SEED_STATE)) delete X.SEED_STATE[k];
Object.assign(X.SEED_STATE, {[uids[1]]: {...blank(), fav: true}, [uids[2]]: blank()});
X.adoptSeed();
chk("adopt takes the decided seed entry", X.S[uids[1]].fav, true);
chk("...and skips the blank one", uids[2] in X.S, false);

const s = X.st(uids[3]);
s.pairs.push([1, 1, 2, 2, 0, 5, "bg"], [1, 1, 2, 2, 0, 5, "bg"], [1, 1, 2, 2, 0, 5, "bg"]);
chk("three background discs do not make a section done", X.isDone(uids[3]), false);
chk("...and the cell tag counts landmarks only", X.cellTag(uids[3]), "");
s.pairs.push([1, 1, 2, 2, 1, 5], [1, 1, 2, 2, 2, 5], [1, 1, 2, 2, 3, 5]);
chk("three landmarks do", X.isDone(uids[3]), true);
chk("...and the tag says 3 pts", X.cellTag(uids[3]), "3 pts");

const t = X.st(uids[4]); t.excl = true; t.rev = {act: "restore"};
chk("a reinstated section is not excluded on screen", X.isExcl(uids[4]), false);
blobs.length = 0; X.exportCsv();
const pl = blobs[0].split("\n"), h = pl[0].split(",");
const row = pl.slice(1).map(l => l.split(",")).find(r => r[0] === uids[4]);
chk("...nor in the export", row[h.indexOf("excluded")], "0");
chk("...and its status is not 'excluded'", row[h.indexOf("status")] === "excluded", false);

done();
