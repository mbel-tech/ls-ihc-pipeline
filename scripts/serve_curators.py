"""Serve the curator pages over http, so a browser gets what the app gets.

**Why this exists.** Opening `roi_curator.html` by double-clicking it loads it
as `file://`, and a `file://` page cannot read its own images back: every local
image taints the canvas, so `toBlob()` throws, and `fetch()` is refused outright.
The curator itself is written not to need either - channel toggling is done by
compositing rather than `getImageData`, deliberately - so landmarking, ROI
placement, rotation, the filters and all three CSV exports work perfectly well
from disk.

The one thing that cannot is the **Shotgun deck**, which has to read the plate
and section bitmaps back to put them in a .pptx. The page detects this and
disables the button with a reason rather than failing at the click, but the
capability is simply absent.

The app solves it by serving `out_root` on a loopback port, which is why
everything works there. This is the same server without the app: run it, and a
browser is on equal terms - Shotgun included.

It is also the answer to "the app will not start" or "I only want the curator":
nothing here imports PySide6.

Run:  python scripts/serve_curators.py
      python scripts/serve_curators.py --page reformatted/level_curator.html
      python scripts/serve_curators.py --no-open --port 8000
"""

import argparse
import functools
import http.server
import json
import os
import socketserver
import webbrowser

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

CURATORS = {
    "roi": "reformatted/roi_curator.html",
    "rotation": "reformatted/rotation_curator.html",
    "level": "reformatted/level_curator.html",
    "reframe": "atlas/plate_reframe.html",
}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static files, without logging every tile request to the console.

    A curator page pulls hundreds of section thumbnails; the default handler
    prints a line for each and buries anything worth reading.
    """

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="roi",
                    help="a curator name (%s) or a path relative to out_root"
                         % ", ".join(CURATORS))
    ap.add_argument("--port", type=int, default=0,
                    help="0 (default) lets the OS pick, so two copies never collide")
    ap.add_argument("--no-open", action="store_true",
                    help="print the URL instead of opening a browser")
    args = ap.parse_args()

    cfg = os.path.join(_REPO, "config.json")
    if not os.path.exists(cfg):
        print(f"no {cfg} - copy config.example.json and fill in the paths")
        return 1
    with open(cfg, encoding="utf-8") as fh:
        out_root = json.load(fh)["out_root"]
    if not os.path.isdir(out_root):
        print(f"out_root does not exist: {out_root}")
        return 1

    rel = CURATORS.get(args.page, args.page).lstrip("/")
    target = os.path.join(out_root, rel.replace("/", os.sep))
    if not os.path.exists(target):
        print(f"no page at {target}")
        print("  build it first, e.g. python scripts/04l_roi_curator.py")
        return 1

    # 127.0.0.1, never 0.0.0.0. This serves out_root - every overview, every
    # section, the whole atlas - and there is no reason for it to be reachable
    # from anything but this machine.
    handler = functools.partial(_QuietHandler, directory=out_root)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), handler) as srv:
        srv.daemon_threads = True
        port = srv.server_address[1]
        url = f"http://127.0.0.1:{port}/{rel}"
        print(f"serving {out_root}")
        print(f"  {url}")
        print("  Shotgun and every export work here exactly as they do in the app.")
        print("Ctrl+C to stop.")
        if not args.no_open:
            webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
