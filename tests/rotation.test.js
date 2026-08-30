// rotation commits on release and survives a reload
//
// Ported from the scratch suite used while building the curator. The scenario is
// unchanged - it is the record of the bug where a tilt sprang back to level
// because it was only a draft until a button was pressed.
//
// The original printed its results and decided pass/fail at the end from two of
// them. Rewritten as assertions: every step now says what it expects, so a
// regression anywhere in the sequence fails rather than scrolling past.

const { load, chk, note, fire, done, store } = require("./harness");

const X = load(
  '{KEY,st,rows,toggleRotMode,restoreTilt,secDown,select,' +
  'get rotMode(){return rotMode},get draftRot(){return draftRot},' +
  'set active(v){active=v},get active(){return active}}');

const uids = X.rows().map(r => r.uid);
const uid = uids[0], other = uids[1];
X.active = uid;
const disk = u => JSON.parse(store[X.KEY] || "{}")[u] || {};

chk("starts untilted", X.st(uid).rot || 0, 0);
chk("nothing on disk yet", disk(uid).rot === undefined, true);

X.toggleRotMode();
X.secDown({ button: 0, clientX: 100, preventDefault() {} });
fire("mousemove", { clientX: 150, shiftKey: false });     // +50 px * 0.4 = 20 deg

chk("mid-drag shows a live draft", X.draftRot.toFixed(1), "20.0");
chk("...and has still written nothing", disk(uid).rot === undefined, true);

fire("mouseup", {});
chk("release commits the tilt", X.st(uid).rot.toFixed(1), "20.0");
chk("...writes it to storage", disk(uid).rot.toFixed(1), "20.0");
chk("...and clears the draft", X.draftRot, null);

X.select(other, true); X.select(uid, true);
chk("leaving and returning keeps it", X.st(uid).rot.toFixed(1), "20.0");

// shift is the fine modifier: -20 px * 0.05 = -1 deg, from the saved 20
X.secDown({ button: 0, clientX: 200, preventDefault() {} });
fire("mousemove", { clientX: 180, shiftKey: true });
fire("mouseup", {});
chk("a second drag starts from the saved angle", X.st(uid).rot.toFixed(1), "19.0");

// a press that never passes the jitter floor must not count as a drag
const before = X.st(uid).rot;
X.secDown({ button: 0, clientX: 300, preventDefault() {} });
fire("mousemove", { clientX: 301, shiftKey: false });     // 1 px
fire("mouseup", {});
chk("a click that never moved changes nothing",
    X.st(uid).rot.toFixed(1), before.toFixed(1));

// rebuilt from storage alone, as a reload would
chk("survives a reload", JSON.parse(store[X.KEY])[uid].rot.toFixed(1), "19.0");

X.restoreTilt();
chk("Restore returns it to the reformatted frame", X.st(uid).rot, 0);
chk("...and persists that too", disk(uid).rot, 0);

done();
