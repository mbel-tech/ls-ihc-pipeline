// Rotation: committed on release, kept per section, survives a reload.
//
// Rotation is a viewing aid - every stored coordinate stays in the unrotated
// frame - so what matters here is not geometry but WHEN the angle is written.
// It used to be a draft until a button was pressed, and losing it was silent:
// the section sprang back to level and looked like it had never been turned.

const { env, load, chk, note, done } = require("./harness");
const { store, fire } = env;

const X = load(`{KEY, st, rows, toggleRotMode, restoreTilt, secDown, select,
  get rotMode(){return rotMode}, get draftRot(){return draftRot},
  set active(v){active=v}, get active(){return active}}`);

const uids = X.rows().map(r => r.uid);
const uid = uids[0], other = uids[1];
X.active = uid;

const disk = u => JSON.parse(store[X.KEY] || "{}")[u] || {};

chk("starts unrotated", X.st(uid).rot || 0, 0);

X.toggleRotMode();
X.secDown({ button: 0, clientX: 100, preventDefault() {} });
fire("mousemove", { clientX: 150, shiftKey: false });   // +50 px * 0.4 deg = 20
chk("mid-drag shows a live draft", X.draftRot.toFixed(1), "20.0");
chk("...and nothing is on disk yet", disk(uid).rot, undefined);

fire("mouseup", {});
chk("release commits the angle", X.st(uid).rot.toFixed(1), "20.0");
chk("...and writes it to storage", disk(uid).rot.toFixed(1), "20.0");
chk("...and clears the draft", X.draftRot, null);

X.select(other, true);
X.select(uid, true);
chk("leaving the section and returning keeps it", X.st(uid).rot.toFixed(1), "20.0");

// shift is the fine modifier: -20 px * 0.05 deg = -1, so 20 -> 19
X.secDown({ button: 0, clientX: 200, preventDefault() {} });
fire("mousemove", { clientX: 180, shiftKey: true });
fire("mouseup", {});
chk("a second drag starts from the saved angle", X.st(uid).rot.toFixed(1), "19.0");

const before = X.st(uid).rot;
X.secDown({ button: 0, clientX: 300, preventDefault() {} });
fire("mousemove", { clientX: 301, shiftKey: false });   // 1 px, under the jitter floor
fire("mouseup", {});
chk("a press that never moved changes nothing",
    X.st(uid).rot.toFixed(1), before.toFixed(1));

// Rebuilt from storage alone: this is what a reload would see.
const reloaded = JSON.parse(store[X.KEY])[uid];
chk("survives a reload", reloaded.rot.toFixed(1), "19.0");

X.restoreTilt();
chk("Restore original tilt zeroes it", X.st(uid).rot.toFixed(1), "0.0");
chk("...on disk too", disk(uid).rot.toFixed(1), "0.0");

done();
