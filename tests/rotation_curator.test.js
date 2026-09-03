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

done();
