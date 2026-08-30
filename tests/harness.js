// Shared harness for the curator suites.
//
// The curators are ~2000 lines of browser JS embedded in a generated page, and
// the interesting behaviour - guided mode's cursor, the rotation commit, the
// per-row export - is all in there. Running it under Node against a stub DOM is
// what makes that behaviour testable at all: there is no build step to hook and
// no module boundary to import across.
//
// The stub was copied into each suite until it drifted. Adding tabindex to the
// canvases meant the page called focus(), which the stub did not model, and the
// same one-line fix had to be made three times. One copy now.
//
// What the stub deliberately does NOT do: render. Canvas operations are absorbed
// by a proxy, so anything only observable as pixels has to be checked in a real
// browser instead. These suites cover state, ordering and export - the things a
// screenshot would not catch anyway.

const fs = require("fs");
const path = require("path");

// Written by tests/run.sh, which regenerates the page with --no-seed and lifts
// out its <script>. Not committed: it is a build product of a generated file.
const CURATOR_JS = path.join(__dirname, "build", "curator.js");

function makeEnv() {
  const store = {};          // localStorage
  const win = {};            // window event listeners, by type
  const els = {};            // getElementById cache

  const mkCL = () => {
    const s = new Set();
    return {
      add: c => s.add(c),
      remove: c => s.delete(c),
      toggle: (c, v) => {
        v === undefined ? (s.has(c) ? s.delete(c) : s.add(c)) : (v ? s.add(c) : s.delete(c));
      },
      contains: c => s.has(c),
    };
  };

  // One element shape for everything. Ids that matter get a sensible default -
  // `animal` has to name a real animal or rows() is empty and every suite fails
  // on an empty list rather than on what it meant to test.
  const mk = id => ({
    checked: false, textContent: "", innerHTML: "", style: {}, title: "",
    value: id === "animal" ? "LS105" : "0",
    classList: mkCL(), disabled: false, click() {},
    addEventListener() {}, querySelectorAll() { return []; },
    focus() {}, blur() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 600 }),
    getContext: () => new Proxy({}, {
      get: (t, k) => k === "measureText"
        ? (s => ({ width: String(s).length * 8 }))
        : () => {},
    }),
    width: 600, height: 600,
  });

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
    getItem: k => store[k] ?? null,
    setItem: (k, v) => { store[k] = v; },
    removeItem: k => { delete store[k]; },
  };
  global.Image = function () {
    return {
      addEventListener() {}, set src(v) {},
      get naturalWidth() { return 768 }, get naturalHeight() { return 768 },
    };
  };
  global.Blob = function (parts) { blobs.push(String(parts && parts[0])); };
  global.URL = { createObjectURL: () => "" };
  global.CSS = { escape: s => s };
  global.confirm = () => true;
  global.console.warn = () => {};

  const blobs = [];
  // Dispatch a window-level event the page registered for. The page listens on
  // window for mousemove/mouseup, so a drag has to be delivered this way.
  const fire = (ev, o) => (win[ev] || []).forEach(f => f(o));
  return { store, win, els, blobs, fire };
}

const env = makeEnv();

/**
 * Evaluate the curator page's script and hand back the internals a suite names.
 *
 * `exportExpr` is the object literal the page evaluates in its own scope, so a
 * suite can reach `active`, `guided` and friends - which are `let` bindings with
 * no other way out. Getters and setters keep them live rather than snapshotting.
 */
function load(exportExpr) {
  if (!fs.existsSync(CURATOR_JS)) {
    console.error(`missing ${CURATOR_JS}\nRun tests/run.sh, which extracts it.`);
    process.exit(2);
  }
  let js = fs.readFileSync(CURATOR_JS, "utf8");
  // The page calls render() on load; the suites drive it themselves.
  js = js.replace(/\nrender\(\);\s*$/, "\n");
  js += "\nglobalThis._X=" + exportExpr + ";";
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
  console.log((ok ? "ok   " : "FAIL ") + String(label).padEnd(52) +
              " " + got + (ok ? "" : "   want " + want));
}

function note(text) { console.log(text); }

function done() {
  console.log(fails ? `\n${fails} FAILED` : "\nALL PASS");
  process.exit(fails ? 1 : 0);
}

module.exports = { env, load, chk, note, done, CURATOR_JS };
