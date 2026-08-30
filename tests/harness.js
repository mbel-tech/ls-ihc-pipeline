// A DOM stub just large enough to run the ROI curator's own JavaScript.
//
// The curator is a generated page, so its logic cannot be imported - it is
// evaluated here against a fake document, and then poked through an explicit
// list of the identifiers a suite needs. That list is per-suite and deliberate:
// a test that reaches for something the page does not export is asking about
// implementation rather than behaviour.
//
// The stub used to be copy-pasted into each suite, which is how a missing
// focus() came to need fixing in three places at once. It lives here now.
//
// What the stub does NOT do is render. Canvas calls are swallowed, so nothing
// here proves anything about what is drawn - that needs a real browser, and the
// browser checks are done separately. These suites are for the logic: ordering,
// state, filters, exports, key handling.

const fs = require("fs");
const path = require("path");

const CURATOR_JS = path.join(__dirname, "build", "curator.js");

const store = {};      // stands in for localStorage
const win = {};        // window-level listeners, keyed by event name
const els = {};        // getElementById cache, created on demand

function makeClassList() {
  const s = new Set();
  return {
    add: c => s.add(c),
    remove: c => s.delete(c),
    toggle: (c, v) => {
      if (v === undefined) { s.has(c) ? s.delete(c) : s.add(c); }
      else { v ? s.add(c) : s.delete(c); }
    },
    contains: c => s.has(c),
  };
}

// One fake element. The defaults matter: an animal select that reports LS105
// and a 600x600 box are what let geometry-dependent code run at all.
function mk(id) {
  return {
    checked: false, textContent: "", innerHTML: "", style: {}, title: "",
    value: (id === "animal" ? "LS105" : "0"),
    classList: makeClassList(), disabled: false,
    click() {}, focus() {}, blur() {},
    addEventListener() {}, querySelectorAll() { return []; },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 600 }),
    // measureText has to return something with a width or the section labels
    // throw; everything else on the context is a no-op.
    getContext: () => new Proxy({}, {
      get: (t, k) => k === "measureText"
        ? (s => ({ width: String(s).length * 8 }))
        : () => {},
    }),
    width: 600, height: 600,
  };
}

function installGlobals(blobs) {
  global.document = {
    getElementById: id => els[id] || (els[id] = mk(id)),
    querySelectorAll: () => [],
    querySelector: () => null,
    createElement: () => mk(),
    addEventListener() {},
    body: mk(),
    hidden: false,
  };
  global.window = global;
  global.addEventListener = (ev, fn) => { (win[ev] = win[ev] || []).push(fn); };
  global.setInterval = () => 1;
  global.localStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = v; },
    removeItem: k => { delete store[k]; },
  };
  global.Image = function () {
    return {
      addEventListener() {}, set src(v) {},
      get naturalWidth() { return 768 }, get naturalHeight() { return 768 },
    };
  };
  // Export builds a Blob and clicks a download link; capturing the parts is how
  // a suite reads what would have been written.
  global.Blob = function (parts) { if (blobs) blobs.push(String(parts[0])); };
  global.URL = { createObjectURL: () => "" };
  global.CSS = { escape: s => s };
  global.confirm = () => true;
  global.console.warn = () => {};
}

/**
 * Evaluate the curator page's JS and return the identifiers named in `exports`.
 * `exports` is the body of an object literal, e.g. "{KEY, st, rows}".
 */
function load(exportsExpr, opts = {}) {
  if (!fs.existsSync(CURATOR_JS)) {
    console.error(`no ${CURATOR_JS}\nRun tests/run.sh, which builds it.`);
    process.exit(2);
  }
  installGlobals(opts.blobs);
  let js = fs.readFileSync(CURATOR_JS, "utf8");
  // The page calls render() on load, which needs a strip that does not exist
  // here. Everything the suites drive, they drive explicitly.
  js = js.replace(/\nrender\(\);\s*$/, "\n");
  js += `\nglobalThis._X=${exportsExpr};`;
  try {
    (0, eval)(js);
  } catch (e) {
    console.error("LOAD ERROR:", e.message);
    process.exit(1);
  }
  return globalThis._X;
}

let fails = 0;

function chk(label, got, want) {
  const ok = String(got) === String(want);
  if (!ok) fails++;
  console.log((ok ? "ok   " : "FAIL ") + String(label).padEnd(52) + " " + got +
              (ok ? "" : "   want " + want));
}

function note(...a) { console.log(...a); }

// Dispatch to window-level listeners the page registered - mousemove and
// mouseup are on window, not on the canvas.
function fire(ev, o) { (win[ev] || []).forEach(f => f(o)); }

function done() {
  console.log(fails ? `\n${fails} FAILED` : "\nALL PASS");
  process.exit(fails ? 1 : 0);
}

module.exports = { load, chk, note, fire, done, els, store, win, mk };
