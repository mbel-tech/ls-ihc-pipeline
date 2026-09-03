"""Every stage must find config.json where the caller says it is.

The stages locate config relative to their own file. From source that is the
repo root; frozen, the scripts ship inside `_internal/` while config.json sits
beside the executable, so the file-relative guess points at a file that does
not exist and every stage fails at import. `LS_CONFIG` names the file
explicitly; the file-relative path is only the fallback.

Run:  python tests/test_config_resolver.py
"""

import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")

failures = []


def chk(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {got!r}")
    if not ok:
        failures.append(name)


def load(script, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, script))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Every stage that reads config at import, so a stage that regresses to the
# file-relative path alone is caught here rather than in the frozen build.
STAGES = sorted(f for f in os.listdir(SCRIPTS)
                if f.endswith(".py") and f[0].isdigit())

with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(REPO, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    out_root = os.path.join(tmp, "out")
    os.makedirs(out_root)
    cfg["source_dir"] = tmp
    cfg["out_root"] = out_root
    cfg["atlas_pdf"] = os.path.join(tmp, "atlas.pdf")
    cfg_path = os.path.join(tmp, "elsewhere", "config.json")
    os.makedirs(os.path.dirname(cfg_path))
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)

    os.environ["LS_CONFIG"] = cfg_path
    sys.path.insert(0, SCRIPTS)
    checked = 0
    for script in STAGES:
        src = open(os.path.join(SCRIPTS, script), encoding="utf-8").read()
        if "CONFIG_PATH" not in src:
            continue
        chk(f"{script} honours LS_CONFIG in its source",
            'os.environ.get("LS_CONFIG")' in src, True)
        checked += 1
    chk("at least twenty stages declare CONFIG_PATH", checked >= 20, True)

    # Two light stages, actually imported: the env var must win over the
    # file-relative path and the values must come from the named file.
    for script in ("00b_verify_extraction.py", "01b_pick_sections.py"):
        mod = load(script, "t_" + script[:3])
        chk(f"{script} CONFIG_PATH is the LS_CONFIG file",
            os.path.normcase(mod.CONFIG_PATH), os.path.normcase(cfg_path))
        chk(f"{script} OUT_ROOT comes from that file", mod.OUT_ROOT, out_root)

    del os.environ["LS_CONFIG"]
    mod = load("00b_verify_extraction.py", "t_00b_default")
    chk("without LS_CONFIG the repo config is used",
        os.path.normcase(mod.CONFIG_PATH),
        os.path.normcase(os.path.join(REPO, "config.json")))

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
