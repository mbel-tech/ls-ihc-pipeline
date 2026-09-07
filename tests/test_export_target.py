"""Where a stamped export is found again, and where the app files one.

The curator writes each export into its own `DD.MM.YYYY_HH.MM` folder with the
stamp on every file in it. Two readers have to cope with that: 05a, which finds
its own input when not given one, and the app's download handler, which rebuilds
the folder from the name because QtWebEngine cannot make it in the page.
"""

import importlib.util
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


def touch(path, when=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("scene_uid,region\n")
    if when is not None:
        os.utime(path, (when, when))
    return path


# ---------------------------------------------------------------- 05a resolver
spec = importlib.util.spec_from_file_location("_g", os.path.join(SCRIPTS, "05a_roi_geometry.py"))
G = importlib.util.module_from_spec(spec)
sys.modules["_g"] = G
spec.loader.exec_module(G)

with tempfile.TemporaryDirectory() as tmp:
    reformat = os.path.join(tmp, "reformatted")
    exports = os.path.join(tmp, "exports")
    home = os.path.join(tmp, "home", "Downloads")
    G.REFORMAT_DIR, G.EXPORT_DIR = reformat, exports
    real_expanduser = os.path.expanduser
    os.path.expanduser = lambda p: p.replace("~", os.path.join(tmp, "home"), 1)
    try:
        chk("nothing anywhere resolves to nothing", G.find_regions_csv(None), None)

        explicit = os.path.join(tmp, "given.csv")
        chk("an explicit path always wins", G.find_regions_csv(explicit), explicit)

        # The old flat name, as the app used to file it.
        old = touch(os.path.join(reformat, "roi_regions.csv"), time.time() - 900)
        chk("a flat file in the reformat dir is still found", G.find_regions_csv(None), old)

        # A stamped export in its own folder, newer. This is the case the old
        # resolver got wrong: it returned the flat file merely because it existed,
        # so a fresh export sat unread while the previous curation was analysed.
        new = touch(os.path.join(exports, "06.09.2026_18.20",
                                 "roi_regions_06.09.2026_18.20.csv"), time.time() - 60)
        chk("a newer stamped export one level deep wins", G.find_regions_csv(None), new)

        # And the download folder is still searched, flat and one deep.
        newest = touch(os.path.join(home, "07.09.2026_09.00",
                                    "roi_regions_07.09.2026_09.00.csv"), time.time())
        chk("the download folder is searched too", G.find_regions_csv(None), newest)

        # Depth stops at one: a file two levels down is not an export folder.
        touch(os.path.join(exports, "a", "b", "roi_regions_08.09.2026_09.00.csv"), time.time() + 60)
        chk("the search does not run deeper than one level",
            G.find_regions_csv(None), newest)
    finally:
        os.path.expanduser = real_expanduser

# ------------------------------------------------------------ app stamp parser
# Read the two helpers out of curator_view rather than importing it: the module
# pulls in QtWebEngine, which is a heavy and headless-hostile import for two
# pure functions.
src = open(os.path.join(REPO, "app", "curator_view.py"), encoding="utf-8").read()
start = src.index("_STAMP_RE =")
end = src.index("class ", start)
ns = {"os": os, "re": re, "json": __import__("json"), "HERE": os.path.join(REPO, "app")}
exec(compile(src[start:end], "curator_view_helpers", "exec"), ns)
stamp, root = ns["_export_stamp"], ns["_export_root"]

chk("a stamped CSV name yields its stamp",
    stamp("roi_regions_06.09.2026_18.20.csv"), "06.09.2026_18.20")
chk("...and so does the deck", stamp("shotgun_plates_final_06.09.2026_18.20.pptx"),
    "06.09.2026_18.20")
chk("an unstamped export has none", stamp("plate_boxes.csv"), None)
chk("a date in the wrong order is not a stamp", stamp("x_2026.09.06_18.20.csv"), None)
chk("a bare date with no time is not a stamp", stamp("x_06.09.2026.csv"), None)
# This used to assert against the operator's live config.json, so it would have
# started failing the day they chose a different export folder - a failure about
# their data, not about this code. _export_root still finds config by guessing
# its own location instead of honouring LS_CONFIG, so until that is fixed the
# test points its idea of "beside me" at a config it wrote itself.
with tempfile.TemporaryDirectory() as _tmp:
    _app = os.path.join(_tmp, "app")
    os.makedirs(_app)
    _chosen = os.path.join(_tmp, "chosen-exports")
    _cfg = os.path.join(_tmp, "config.json")
    with open(_cfg, "w", encoding="utf-8") as _fh:
        __import__("json").dump({"export_dir": _chosen}, _fh)
    ns["HERE"] = _app
    chk("the export root comes from config", root(r"D:\nowhere"), _chosen)

    os.remove(_cfg)
    chk("with no export_dir configured it falls back to out_root/exports",
        root(os.path.join(_tmp, "out")), os.path.join(_tmp, "out", "exports"))

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
