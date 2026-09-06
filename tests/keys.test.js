// Shortcuts fire on plain keys only, and never while a form control has focus.

const { env, load, chk, note, done } = require("./harness");
const { els, fire } = env;

const X = load(`{st, rows, select, isExcl, set active(v){active=v}, get active(){return active}}`);
els["animal"].value = "LS105";
const uid = X.rows()[0].uid; X.select(uid, true); X.active = uid;
const key = (k, extra) => fire("keydown",
  Object.assign({key: k, target: {tagName: "BODY"}, preventDefault() {}}, extra || {}));

key("x", {ctrlKey: true});  chk("ctrl+x is the browser's", X.isExcl(uid), false);
key("x", {metaKey: true});  chk("cmd+x too", X.isExcl(uid), false);
key("x", {altKey: true});   chk("alt+x too", X.isExcl(uid), false);
key("x", {target: {tagName: "INPUT", type: "text"}});
chk("typing in a text box is typing", X.isExcl(uid), false);
key("x");                   chk("plain x excludes", X.isExcl(uid), true);
key("X", {shiftKey: true}); chk("shift is not a modifier here", X.isExcl(uid), false);

done();
