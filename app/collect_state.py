"""One-shot migration: lift curation out of a browser's localStorage into files.

The app cannot read another application's storage, and reading a browser's
profile database directly is - correctly - not something to reach for. The only
legitimate route is to have a page on the *same origin* as the curators read its
own localStorage and hand it over.

That origin detail is the whole difficulty. localStorage is partitioned by
origin, so a page opened from `file://` sees nothing a page served over `http://`
stored, and the other way round. The collector page is therefore written next to
the curators and opened the same way they are, so it lands on the same origin
whichever that turns out to be.

It POSTs rather than downloads: a download means a dialog, a chosen folder and a
second step. A POST to a loopback server that is listening for exactly one
delivery is the same data with none of that.

Run:  python -m app.collect_state
"""

import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import state as ST                                          # noqa: E402

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Collecting curation state</title>
<style>
 body{background:#0e1014;color:#e6e6e6;font:15px system-ui;padding:36px;max-width:720px}
 h1{font-size:20px} li{margin:4px 0} code{background:#1c2027;padding:1px 5px;border-radius:4px}
 .ok{color:#3fb950} .no{color:#8b949e} .err{color:#f85149} #done{font-size:17px;margin-top:18px}
 button{background:#4da3ff;border:0;color:#04121f;font:600 15px system-ui;
        padding:10px 18px;border-radius:8px;cursor:pointer;margin-top:10px}
</style>
<h1>Collecting curation state</h1>
<p>Reading what this browser holds for <code id="org"></code> and sending it to the
pipeline app. You can close this tab when it says done.</p>
<ul id="list"></ul>
<div id="done"></div>
<script>
const KEYS = __KEYS__, POST = "__POST__";
document.getElementById("org").textContent = location.origin || "file://";
const found = {};
for (const k of KEYS) {
  let v = null;
  try { v = localStorage.getItem(k); } catch (e) {}
  const li = document.createElement("li");
  if (v === null) li.innerHTML = `<span class=no>-</span> ${k}`;
  else { found[k] = v;
         li.innerHTML = `<span class=ok>${(v.length/1024).toFixed(1)} KB</span> ${k}`; }
  document.getElementById("list").appendChild(li);
}
const n = Object.keys(found).length;
const el = document.getElementById("done");

function offerDownload(msg) {
  el.innerHTML = `<span class=err>${msg}</span>`;
  const b = document.createElement("button");
  b.textContent = "Save curation_state.json instead";
  b.onclick = () => {
    const blob = new Blob([JSON.stringify(found, null, 1)], {type: "application/json"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "curation_state.json"; a.click();
  };
  el.appendChild(document.createElement("br")); el.appendChild(b);
}

const report = {__origin: location.origin || "file://",
                __href: location.href,
                __allKeys: (() => { try { return Object.keys(localStorage); }
                                    catch (e) { return ["<blocked: " + e.name + ">"]; } })()};
document.getElementById("list").insertAdjacentHTML("afterend",
  `<p class=no>origin <code>${report.__origin}</code> holds
   ${report.__allKeys.length} key(s) in total</p>`);
{
  // text/plain keeps this a simple request, so no preflight is needed from a
  // file:// page whose Origin header is null.
  fetch(POST, {method: "POST", headers: {"Content-Type": "text/plain"},
               body: JSON.stringify(Object.assign({}, found, report))})
    .then(r => r.ok
      ? el.innerHTML = n
          ? `<span class=ok>Sent ${n} key(s). Done - you can close this tab.</span>`
          : `<span class=err>No curation state on this origin.</span> The app has
             been told what this page could see; close the tab.`
      : offerDownload("The app did not accept it."))
    .catch(() => offerDownload("Could not reach the app."));
}
</script>
"""



BROWSERS = {
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
               os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")],
    "edge":   [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
               r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"],
}


def _find_browser(name):
    for c in BROWSERS.get(name, []):
        if os.path.exists(c):
            return c
    return None

class Handler(http.server.BaseHTTPRequestHandler):
    received = {}
    done = threading.Event()

    def log_message(self, *a):
        pass

    def _cors(self):
        # The page is on file:// (Origin: null) or on some http port; either way
        # this server exists for one delivery from one page on this machine.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            Handler.received = json.loads(raw)
            ok = True
        except ValueError:
            ok = False
        self.send_response(200 if ok else 400)
        self._cors()
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"bad json")
        Handler.done.set()


def main():
    cfg_path = os.path.join(os.path.dirname(HERE), "config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        out_root = json.load(fh)["out_root"]

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    page = PAGE.replace("__KEYS__", json.dumps(ST.KEYS)) \
               .replace("__POST__", f"http://127.0.0.1:{port}/collect")
    path = os.path.join(out_root, "reformatted", "collect_state.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)

    print(f"listening on 127.0.0.1:{port}")

    # WHICH browser matters as much as which origin. localStorage belongs to one
    # browser's profile, so the collector has to run in the browser the curating
    # was done in - the default one is only a guess, and a wrong guess reports
    # "nothing found" rather than failing, which reads like there is nothing to
    # recover.
    want = None
    for i, a in enumerate(sys.argv):
        if a == "--browser" and i + 1 < len(sys.argv):
            want = sys.argv[i + 1].lower()
    exe = _find_browser(want) if want else None

    if exe:
        print(f"opening in {os.path.basename(exe)}")
        subprocess.Popen([exe, path])
    else:
        if want:
            print(f"could not find {want}; using the default browser")
        print(f"opening {path}")
        try:
            os.startfile(path)                              # noqa: S606
        except AttributeError:
            webbrowser.open("file:///" + path.replace("\\", "/"))

    if not Handler.done.wait(timeout=90):
        print("nothing arrived within 90s.")
        print("If the page opened, it will show what it found and offer a download.")
        srv.shutdown()
        return 1

    store = ST.CurationStore(out_root)
    written = []
    for key, value in (Handler.received or {}).items():
        if key in ST.KEYS and isinstance(value, str) and value.strip():
            store.write(key, value)
            written.append((key, len(value)))

    srv.shutdown()
    try:
        os.remove(path)
    except OSError:
        pass

    got = Handler.received or {}
    print("")
    print(f"  origin      : {got.get('__origin', '?')}")
    print(f"  page URL    : {got.get('__href', '?')}")
    allk = got.get("__allKeys") or []
    print(f"  keys there  : {len(allk)}")
    for k in allk[:15]:
        print(f"                {k}")

    if not written:
        print("")
        print("No curation state on that origin.")
        return 1
    print(f"\nwrote {len(written)} file(s) to {os.path.join(out_root, 'curation')}:")
    for key, n in written:
        print(f"  {key:28} {n/1024:8.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
