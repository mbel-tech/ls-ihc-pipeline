// 04d rotation curator: the record per section, what a proposal is, and the
// export. Built with --no-proposals, so AUTO and SYM start empty and each
// test injects what it needs.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs, fire } = env;

const X = load(`{KEY, DATA, AUTO, SYM, state, get, setState, toggleExclude, isExcluded,
  isAuto, isSymAuto, symOf, exportCsv, render, counts, paint, onDown, onMove, onUp,
  get drag(){return drag}, set active(v){active=v}, get active(){return active}}`,
  "rotation_curator");

els["animal"].value = "";                 // all animals
chk("the page carries sections", X.DATA.length > 0, true);
chk("no proposals were embedded", Object.keys(X.AUTO).length + Object.keys(X.SYM).length, 0);
const disk = u => JSON.parse(store[X.KEY] || "{}")[u];

const u = X.DATA[0].uid;
chk("untouched: rotation 0, not excluded", X.get(u).r + "/" + X.isExcluded(u), "0/false");
X.setState(u, 45, false);
chk("a rotation is stored", X.state[u].r, 45);
chk("...and written to storage", disk(u).r, 45);
X.setState(u, 0, false);
chk("back to 0 with no proposal drops the record", u in X.state, false);

blobs.length = 0; X.exportCsv();
chk("nothing to export -> only the header line", blobs[0].split("\n").length, 1);
chk("export header", blobs[0].split("\n")[0],
    "scene_uid,extra_rotation,flip,excluded,rotation_source,decision,reason");

// ---- attribute escaping ---------------------------------------------------
note("");
X.AUTO[u] = {reason: 'no tissue" onmouseover="alert(1)', mm2: 1};
X.render();
chk("a reason cannot break out of the title attribute",
    els["wall"].innerHTML.includes('onmouseover="alert'), false);
chk("...it is entity-escaped", els["wall"].innerHTML.includes("&quot; onmouseover=&quot;"), true);
delete X.AUTO[u];

// ---- keyboard guards ------------------------------------------------------
note("");
X.active = u;
const key = (k, extra) => fire("keydown",
  Object.assign({key: k, target: {tagName: "BODY"}, preventDefault() {}}, extra || {}));
key("x", {ctrlKey: true});
chk("ctrl+x does not exclude", X.isExcluded(u), false);
key("x", {target: {tagName: "SELECT"}});
chk("a key inside the animal select does nothing", X.isExcluded(u), false);
key("ArrowRight", {target: {tagName: "INPUT", type: "range"}});
chk("arrows inside a slider do nothing", X.get(u).r, 0);
key("x");
chk("plain x excludes", X.isExcluded(u), true);
key("x");
chk("...and toggles back", X.isExcluded(u), false);

// ---- drag: a draft until release ------------------------------------------
note("");
const ev = (x, y) => ({clientX: x, clientY: y, button: 0, pointerId: 1, preventDefault() {},
  currentTarget: {getBoundingClientRect: () => ({left: 0, top: 0, width: 200, height: 200}),
                  setPointerCapture() {}}});
const v = X.DATA[1].uid;
delete X.state[v];
X.onDown(ev(200, 100), v);                     // 0 deg from the centre (100,100)
X.onMove({clientX: 100, clientY: 200, shiftKey: false});   // 90 deg
chk("mid-drag: nothing in the record", v in X.state, false);
chk("...nothing on disk", disk(v), undefined);
chk("...but the draft is live", Math.round(X.drag.r), 90);
X.onUp();
chk("release commits the angle", X.state[v].r, 90);
chk("...to disk", disk(v).r, 90);
chk("...and ends the drag", X.drag, null);

X.onDown(ev(200, 100), v);
X.onUp();
chk("a press that never moved changes nothing", X.state[v].r, 90);

// ---- tri-state rotation ---------------------------------------------------
note("");
const w = X.DATA[2].uid;
delete X.state[w];
X.SYM[w] = {r: 30, score: 0.9, conf: "high"};
chk("a proposal is applied", X.get(w).r, 30);
chk("...and reads as auto", X.isSymAuto(w), true);
X.toggleExclude(w);
chk("excluding does not adopt the proposal", X.state[w].r, undefined);
chk("...it is still auto", X.isSymAuto(w), true);
chk("...and the exclusion is recorded", X.state[w].x, true);
X.toggleExclude(w);
chk("restoring is an explicit keep", X.state[w].x, false);
X.setState(w, 0, false, undefined);
chk("0 on a proposed section is a decision", X.get(w).r, 0);
chk("...that is stored", X.state[w].r, 0);
chk("...and is no longer auto", X.isSymAuto(w), false);

blobs.length = 0; X.exportCsv();
const rowsOut = blobs[0].split("\n").slice(1).map(l => l.split(","));
const rw = rowsOut.find(r => r[0] === w);
chk("the export carries the explicit 0", rw[1], "0");
chk("...sourced as an overruled proposal", rw[4], "manual_overrode_auto");
const w2 = X.DATA[3].uid;
delete X.state[w2]; X.SYM[w2] = {r: 12, score: 0.9, conf: "high"};
blobs.length = 0; X.exportCsv();
const rw2 = blobs[0].split("\n").slice(1).map(l => l.split(",")).find(r => r[0] === w2);
chk("an untouched proposal exports as auto_symmetry", rw2[4], "auto_symmetry");
delete X.SYM[w]; delete X.SYM[w2];
X.setState(X.DATA[4].uid, 0, false, undefined);
chk("0 with no proposal stores nothing", X.DATA[4].uid in X.state, false);

done();
