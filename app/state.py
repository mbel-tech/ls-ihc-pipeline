"""Curation decisions, kept in files instead of a browser profile.

The curators store their state in `localStorage`. That is right for a page opened
in a browser and wrong for a desktop app: the embedded view has its own profile,
so state saved in the app would be invisible to Chrome and vice versa, and either
copy is one cleared profile from being gone.

**The generators are not modified.** An earlier version of this plan had each of
them write through a bridge, which meant editing three tools that currently work.
Wrapping `Storage.prototype.setItem` at document-creation time does the same job
from outside: every existing `localStorage.setItem` in every curator - and any
added later - is mirrored to disk without the page knowing. Opened in a plain
browser there is no injection, so behaviour there is untouched by construction.

The read side needs no bridge either. Seeding `localStorage` before the page's own
script runs means `JSON.parse(localStorage.getItem(KEY))` finds what it expects,
and the pages stay synchronous.
"""

import json
import os

from PySide6.QtCore import QObject, Slot

# Every key the curators use. Listed rather than discovered because the point of
# the file store is that a key nobody wrote this session is still carried
# forward; discovering from localStorage would only ever find the current one.
KEYS = [
    "ls_roi_curator_v1",
    "ls_rotation_curator_v3",
    "ls_rotation_curator_v2",      # read by 04d to migrate its own older format
    "ls_level_curator_v1",
    "ls_plate_reframe_v1",
    "ls_roi_curator_v1_backup",    # the rolling snapshot, worth keeping too
    "ls_roi_curator_v1_size",      # the landmark radius; mirrored, so seed it back
    "ls_atlas_curator_v1",         # 04b's page, retired but a browser may hold it
]


class CurationStore:
    """One JSON file per key under out_root/curation."""

    def __init__(self, out_root):
        self.dir = os.path.join(out_root, "curation")

    def path(self, key):
        return os.path.join(self.dir, key + ".json")

    def read(self, key):
        try:
            with open(self.path(key), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    def write(self, key, text):
        """Atomic, because a half-written state file is worse than none.

        The curators save on every decision, so this runs often and while the
        user is still working; a crash mid-write must not leave a truncated file
        where the day's curation used to be.
        """
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.path(key))

    def all_present(self):
        return {k: self.read(k) for k in KEYS if self.read(k) is not None}

    def import_bundle(self, path):
        """Load a JSON of {key: value} exported from a browser. Returns names."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        written = []
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            text = value if isinstance(value, str) else json.dumps(value)
            self.write(key, text)
            written.append(key)
        return written


class Bridge(QObject):
    """What the page calls to persist. One slot, deliberately."""

    def __init__(self, store, on_save=None):
        super().__init__()
        self.store = store
        self.on_save = on_save

    @Slot(str, str)
    def save(self, key, text):
        try:
            self.store.write(key, text)
            if self.on_save:
                self.on_save(key, len(text))
        except OSError as e:
            print(f"curation save failed for {key}: {e}")


def seed_script(store):
    """JS run before any page script: seed state, then mirror every write.

    Writes are queued until the channel is up. The page saves on the first
    decision the user makes, which can easily beat the asynchronous QWebChannel
    handshake - without the queue those early saves would reach localStorage and
    never reach disk, which is exactly the silent half-loss this module exists to
    prevent.
    """
    seed = {k: v for k, v in ((k, store.read(k)) for k in KEYS) if v is not None}
    return """
(function () {
  var SEED = %s;
  try {
    for (var k in SEED) {
      if (localStorage.getItem(k) === null) localStorage.setItem(k, SEED[k]);
    }
  } catch (e) {}

  var queue = [], bridge = null;
  window.__lsQueueSize = function () { return queue.length; };

  var orig = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    orig.call(this, k, v);
    if (this === window.localStorage) {
      if (bridge) { bridge.save(String(k), String(v)); }
      else { queue.push([String(k), String(v)]); }
    }
  };

  function connect() {
    if (!window.qt || !qt.webChannelTransport) { setTimeout(connect, 50); return; }
    new QWebChannel(qt.webChannelTransport, function (ch) {
      bridge = ch.objects.lsbridge;
      window.__lsbridge = bridge;
      while (queue.length) { var e = queue.shift(); bridge.save(e[0], e[1]); }
    });
  }
  connect();
})();
""" % json.dumps(seed)


EXPORT_PAGE = """<!doctype html>
<meta charset="utf-8"><title>Export curation state</title>
<style>
 body{background:#0e1014;color:#e6e6e6;font:15px system-ui;padding:32px;max-width:760px}
 h1{font-size:19px} code{background:#1c2027;padding:1px 5px;border-radius:4px}
 button{background:#4da3ff;border:0;color:#04121f;font:600 15px system-ui;
        padding:10px 18px;border-radius:8px;cursor:pointer}
 .none{color:#f85149} .found{color:#3fb950} li{margin:3px 0}
</style>
<h1>Export curation state</h1>
<p>This reads the curation decisions this browser is holding and saves them to one
file, so the desktop app can take them over. Open it in <b>the same browser you
have been curating in</b>.</p>
<ul id=list></ul>
<p><button id=go>Save curation_state.json</button></p>
<p id=note></p>
<script>
const KEYS = %s;
const found = {};
for (const k of KEYS) {
  const v = localStorage.getItem(k);
  const li = document.createElement("li");
  if (v === null) { li.innerHTML = `<span class=none>not present</span> &nbsp; ${k}`; }
  else { found[k] = v;
         li.innerHTML = `<span class=found>${(v.length/1024).toFixed(1)} KB</span> &nbsp; ${k}`; }
  document.getElementById("list").appendChild(li);
}
if (!Object.keys(found).length) {
  document.getElementById("note").innerHTML =
    "<span class=none>Nothing found in this browser's storage.</span> Pages opened " +
    "from <code>file://</code> may keep storage per file. Open the curator you " +
    "actually use, press F12, and run <code>copy(JSON.stringify(Object.fromEntries(" +
    "Object.keys(localStorage).map(k=>[k,localStorage.getItem(k)]))))</code> " +
    "to put the same JSON on your clipboard.";
}
document.getElementById("go").onclick = () => {
  const b = new Blob([JSON.stringify(found, null, 1)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(b); a.download = "curation_state.json"; a.click();
};
</script>
"""


def write_export_page(out_root):
    """Drop the export helper next to the curators, where the user will find it."""
    path = os.path.join(out_root, "reformatted", "export_curation_state.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(EXPORT_PAGE % json.dumps(KEYS))
    return path
