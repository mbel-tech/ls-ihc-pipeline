"""The existing study must survive being moved into the study store.

This work changes how config is READ, not what any stage computes. So the sharp
check is not to run a stage - stage scripts overwrite out_root, and the dataset
they would run against is 733 GB - but to import every one of them under the old
config and again under the migrated study, and compare every path, threshold and
index each derived.

A mistyped key or a wrong default shows up here as a directory quietly moving,
which is the failure that would otherwise be discovered by finding results
written beside the real ones.

The migration is done into a TEMP home, never the operator's, so running this
suite cannot change which study they have open.

Skipped, not failed, when this checkout has no config.json: on a fresh clone
there is nothing to regress against.

Run:  python tests/test_ls_regression.py
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)

import _stage_probe as P                                    # noqa: E402
import ls_config as C                                       # noqa: E402

REAL = os.path.join(REPO, "config.json")

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 88 else f"<{type(got).__name__}, {len(got)}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {shown!r}")
    if not ok:
        failures.append(name)


def probe(config_path, out_path):
    env = dict(os.environ, LS_CONFIG=config_path)
    env.pop("LS_CONFIG_STRICT", None)
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "_stage_probe.py"),
         config_path, out_path],
        capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"the probe failed on {config_path}")
    with open(out_path, encoding="utf-8") as fh:
        return json.load(fh)


if not os.path.exists(REAL):
    print("SKIP no config.json in this checkout - nothing to regress against")
    sys.exit(0)

saved = {n: os.environ.get(n) for n in ("LS_HOME", "LS_CONFIG", "LS_STUDY")}
try:
    with tempfile.TemporaryDirectory() as tmp:
        for n in ("LS_CONFIG", "LS_STUDY"):
            os.environ.pop(n, None)
        os.environ["LS_HOME"] = tmp
        C.clear_cache()

        study = C.migrate("Regression Check", REAL)
        print(f"migrated a copy of config.json into {study}")

        before = probe(REAL, os.path.join(tmp, "before.json"))
        after = probe(study, os.path.join(tmp, "after.json"))

        chk("every stage imports under the old config", before["_failed"], {})
        chk("every stage imports under the migrated study", after["_failed"], {})
        chk("the same stages were compared",
            sorted(before) == sorted(after), True)
        chk("all 46 of them", len(before) - 1, 46)

        differences = P.diff(before, after)
        chk("no stage derives anything different from the migrated study",
            differences, [])
        for script, const, bv, av in differences[:20]:
            print(f"     {script} {const}:\n       before {bv!r}\n       after  {av!r}")

        # The migration must not quietly drop a setting either.
        original = json.load(open(REAL, encoding="utf-8"))
        migrated = json.load(open(study, encoding="utf-8"))
        chk("no top-level key was lost in the migration",
            [k for k in original if k not in migrated], [])
        chk("the original config is still where it was",
            os.path.exists(REAL), True)
finally:
    for n, v in saved.items():
        if v is None:
            os.environ.pop(n, None)
        else:
            os.environ[n] = v
    C.clear_cache()

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
