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

// Smallest legal PNG: 1x1, so a stubbed toBlob hands back something that is
// really a PNG rather than a placeholder that only looks like one.
const PNG_1PX = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
  0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00,
  0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x00, 0x01, 0x00, 0x00,
  0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49,
  0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82]);

/** Flatten an array of Uint8Array (and strings) into one buffer. */
function concat(parts) {
  const enc = new TextEncoder();
  const bufs = (parts || []).map(p => typeof p === "string" ? enc.encode(p)
                                    : p instanceof Uint8Array ? p
                                    : new Uint8Array(p));
  const out = new Uint8Array(bufs.reduce((n, b) => n + b.length, 0));
  let o = 0;
  for (const b of bufs) { out.set(b, o); o += b.length; }
  return out;
}

// Written by tests/run.sh, which regenerates each page into tests/build/ and
// lifts out its <script>. Not committed: build products of generated files.
//   curator.js           04l_roi_curator.py   (--no-seed)
//   rotation_curator.js  04d_rotation_curator.py (--no-proposals)
//   level_curator.js     04k_level_curator.py
const builtJs = page => path.join(__dirname, "build", page + ".js");
const CURATOR_JS = builtJs("curator");

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
    // Shotgun turns each deck tile into PNG bytes through the canvas. Nothing
    // here renders, so this hands back a fixed 1x1 PNG: what the suites check
    // is the package that gets built around it, not the picture.
    toBlob(cb) { cb(mkBlob([PNG_1PX])); },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 600 }),
    // Every element in a real document has a parent, and the page dresses the
    // label AROUND a checkbox - disabling it also dims and re-titles the
    // wrapper. A stub with no parentElement made that a TypeError, which reads
    // as "the page is broken" when it is the fake DOM that is thin.
    get parentElement() {
      return (this._parent ||= { style: {}, title: "", classList: mkCL() });
    },
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
  // Every image is 768 square unless a suite says otherwise. The page shows a
  // 768 px composite where one exists and the 256 px greyscale where it does
  // not, and both frames can be on one page - so a suite that cares sets
  // env.imgSize to a function of the src the page assigned (null keeps 768).
  // The stub never fires onload; a suite drives drawSec() itself.
  const imgSize = img => ret.imgSize ? ret.imgSize(img._src || "") : 768;
  global.Image = function () {
    return {
      _src: "", addEventListener() {},
      set src(v) { this._src = String(v); }, get src() { return this._src; },
      get naturalWidth() { return imgSize(this); },
      get naturalHeight() { return imgSize(this); },
    };
  };
  // Kept as a string for the CSV suites, which read env.blobs and compare text.
  // Binary needs the parts themselves, so those are recorded alongside rather
  // than instead - and the Blob object carries them too, because the pptx path
  // reads its own images back with arrayBuffer().
  const mkBlob = parts => ({
    parts,
    arrayBuffer: () => Promise.resolve(concat(parts).buffer),
  });
  global.Blob = function (parts) {
    blobs.push(String(parts && parts[0]));
    blobParts.push(parts);
    return mkBlob(parts);
  };
  // A page loaded from disk cannot read its own images back, and the curator
  // disables Shotgun when it sees file:. The suites run against the served case.
  global.location = { protocol: "http:" };
  global.URL = { createObjectURL: () => "" };
  global.CSS = { escape: s => s };
  global.confirm = () => true;
  global.console.warn = () => {};

  const blobs = [], blobParts = [];
  // Dispatch a window-level event the page registered for. The page listens on
  // window for mousemove/mouseup, so a drag has to be delivered this way.
  const fire = (ev, o) => (win[ev] || []).forEach(f => f(o));
  const ret = { store, win, els, blobs, blobParts, fire, concat, imgSize: null };
  return ret;
}

const env = makeEnv();

/**
 * Evaluate the curator page's script and hand back the internals a suite names.
 *
 * `exportExpr` is the object literal the page evaluates in its own scope, so a
 * suite can reach `active`, `guided` and friends - which are `let` bindings with
 * no other way out. Getters and setters keep them live rather than snapshotting.
 */
function load(exportExpr, page = "curator") {
  const file = builtJs(page);
  if (!fs.existsSync(file)) {
    console.error(`missing ${file}\nRun tests/run.sh, which builds it.`);
    process.exit(2);
  }
  let js = fs.readFileSync(file, "utf8");
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
