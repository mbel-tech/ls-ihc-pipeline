// 04k level curator: anchors, the interpolation between them, and the export.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs, fire } = env;

const X = load(`{KEY, DATA, PLATES, anchors, rows, assign, render, select, setAnchor,
  dropAnchor, showPlate, exportCsv, set active(v){active=v}, get active(){return active}}`,
  "level_curator");

els["animal"].value = X.DATA[0].animal;
const list = X.rows();
chk("the animal has sections", list.length >= 3, true);
chk("plates are loaded", X.PLATES.length >= 2, true);

chk("no anchors -> nothing assigned", X.assign(list).every(a => a.plate === null), true);
X.render();
chk("render selects the first section", X.active, list[0].uid);

X.active = list[0].uid; els["slider"].value = 0; X.setAnchor();
X.active = list[list.length - 1].uid; els["slider"].value = 1; X.setAnchor();
const asg = X.assign(list);
chk("two anchors", asg.filter(a => a.kind === "anchor").length, 2);
chk("everything between is interpolated", asg.slice(1, -1).every(a => a.kind === "interp"), true);
chk("anchors persist", Object.keys(JSON.parse(store[X.KEY])).length, 2);

blobs.length = 0; X.exportCsv();
const lines = blobs[0].split("\n");
chk("export header", lines[0],
    "scene_uid,animal,section_order,plate_set,plate_id,plate_index,source,regions");
chk("one row per section of the anchored animal", lines.length - 1, list.length);

// ---- escaping and delegated clicks ---------------------------------------
note("");
X.render();
chk("the strip carries no inline handlers", els["strip"].innerHTML.includes("onclick="), false);
chk("...cells are addressed by data-uid", els["strip"].innerHTML.includes(`data-uid="${list[0].uid}"`), true);
X.PLATES[0].regions = "Dm|<b>x</b>";
X.showPlate(0);
chk("region labels are escaped before the pipe becomes a dot",
    els["plateRegions"].innerHTML, "Dm &middot; &lt;b&gt;x&lt;/b&gt;");

// ---- keyboard guards ------------------------------------------------------
note("");
X.active = list[1].uid;
const key = (k, extra) => fire("keydown",
  Object.assign({key: k, target: {tagName: "BODY"}, preventDefault() {}}, extra || {}));
const nBefore = Object.keys(X.anchors).length;
key("a", {ctrlKey: true});
chk("ctrl+a selects text, sets no anchor", Object.keys(X.anchors).length, nBefore);
key("a", {target: {tagName: "SELECT"}});
chk("type-ahead in the animal select sets no anchor", Object.keys(X.anchors).length, nBefore);
els["slider"].value = 0;
key("a");
chk("plain a anchors", X.anchors[list[1].uid].at, 0);
chk("...and the anchor carries the plate id, not just its slot",
    X.anchors[list[1].uid].id, X.PLATES[0].id);
key("d");
chk("plain d drops it", list[1].uid in X.anchors, false);

// ---- a level anchor is a plate id, not an array position -------------------
// 04k stores uid -> plate index too. An anchor that no longer resolves must
// leave the monotonic constraint rather than anchor a whole animal's series to
// the wrong level: everything between two anchors is interpolated from them.
note("");
const L = load(`{migrateAnchors}`, "level_curator");

const FAKE = [{id: "plate_001"}, {id: "plate_002"}, {id: "plate_003"}];

chk("an anchor follows its plate id",
    L.migrateAnchors({ "LS1_s01a": { id: "plate_003", at: 0 } }, FAKE)["LS1_s01a"].at,
    2);
chk("an anchor whose plate is gone is dropped, not moved",
    L.migrateAnchors({ "LS1_s01a": { id: "plate_099", at: 0 } }, FAKE)["LS1_s01a"],
    undefined);
chk("a bare integer anchor from before this change still loads",
    L.migrateAnchors({ "LS1_s01a": 1 }, FAKE)["LS1_s01a"].at, 1);
chk("...and picks up the id that was at that position",
    L.migrateAnchors({ "LS1_s01a": 1 }, FAKE)["LS1_s01a"].id, "plate_002");
// A bare integer past the end of a SHORTER atlas is dropped too, not kept
// with a blank id - kept, it would still hand assign()'s unclamped
// interpolation a real (wrong) number, carrying it into OTHER sections'
// plates. That is exactly "a wrong anchor is worse than a missing one" for a
// legacy record instead of an id-keyed one.
chk("a bare integer past the end of a shorter atlas is dropped, not kept blank",
    L.migrateAnchors({ "LS1_s01a": 99 }, FAKE)["LS1_s01a"], undefined);

// ---- a stale anchor never takes the page down ------------------------------
// migrateAnchors keeps a legacy bare-integer anchor's raw index even when it
// lands past the end of a shorter atlas - there is nothing to check it
// against at migration time, only at READ time - so every place that turns an
// index into a plate has to fail closed (plateAt/BLANK_PLATE) rather than
// throw. Exercised against the live page, not just the pure function.
note("");
X.anchors[list[0].uid] = { id: "", at: 99999 };
let threw = null;
try { X.showPlate(99999); X.select(list[0].uid); X.render(); }
catch (e) { threw = e && e.message; }
chk("a stale out-of-range anchor does not crash render/select/showPlate", threw, null);
delete X.anchors[list[0].uid];

// ---- migration runs at LOAD time, against seeded localStorage -------------
// The two blocks above test migrateAnchors as a pure function and plateAt as
// a read-time guard; neither exercises `let anchors = migrateAnchors(...)`
// itself, the one call every operator's browser actually makes. Seed
// localStorage the way a real upgrade would find it and load the page again.
note("");
store[X.KEY] = JSON.stringify({
  a: { id: X.PLATES[1].id, at: 0 },   // id-keyed, resolves - follows the id
  b: { id: "plate_does_not_exist_in_this_atlas", at: 0 },   // gone -> dropped
  c: 1,                                // legacy bare index, resolves
});
const M = load(`{anchors, droppedAnchors}`, "level_curator");
chk("an id-keyed anchor survives load-time migration and follows its id",
    M.anchors["a"].at, 1);
chk("a gone id-keyed anchor is absent after load-time migration", "b" in M.anchors, false);
chk("...and counted in droppedAnchors", M.droppedAnchors.includes("b"), true);
chk("a legacy bare-integer anchor survives load-time migration",
    M.anchors["c"].at, 1);
chk("...and picks up the id at that position", M.anchors["c"].id, X.PLATES[1].id);
chk("the header notice reports the drop count", els["ndropped"].textContent, "1");
chk("...and the notice row is shown", els["dropRow"].style.display, "");

done();
