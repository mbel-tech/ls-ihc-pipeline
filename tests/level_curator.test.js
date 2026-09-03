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

done();
