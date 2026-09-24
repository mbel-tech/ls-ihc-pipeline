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

done();
