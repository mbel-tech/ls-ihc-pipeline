"""Every stage must find config where the caller says it is - and use it.

The stages locate config relative to their own file. From source that is the
repo root; frozen, the scripts ship inside `_internal/` while config.json sits
beside the executable, so the file-relative guess points at a file that does
not exist and every stage fails at import. `LS_CONFIG` names the file
explicitly; the file-relative path is only the fallback.

This used to be checked by grepping each stage's SOURCE for the string
`os.environ.get("LS_CONFIG")`. That had two holes. It skipped any stage whose
source did not mention `CONFIG_PATH` - nine of them, the ones that take config
from a sibling module - and it could only ever prove that a stage mentioned the
variable, never that it honoured it.

It is now functional. Every numbered stage is imported under two synthetic
configs in two different places, and what each derived is compared:

  * every stage resolves to the file it was pointed at, not to the repo's;
  * no constant differs between the two runs, so no stage has a path or a
    threshold baked in behind the config's back;
  * a stage that will not import is a failure, not a silent skip.

Run:  python tests/test_config_resolver.py
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

#: Every stage now resolves config itself. Nine used to take it from a sibling
#: module, which is why the check this replaced skipped them: it looked for
#: `CONFIG_PATH` in the source and moved on when it was absent. An empty set
#: here is the invariant, not a placeholder - a stage that goes back to
#: borrowing a sibling's config fails this suite.
NO_OWN_LOADER = set()

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 90 else f"<{type(got).__name__}, {len(got)}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:64} {shown!r}")
    if not ok:
        failures.append(name)


def synthetic(tmp, tag):
    """A validating config in its own folder, with recognisable roots."""
    root = os.path.join(tmp, tag)
    os.makedirs(os.path.join(root, "slides"))
    os.makedirs(os.path.join(root, "out"))
    open(os.path.join(root, "atlas.pdf"), "wb").close()
    with open(os.path.join(REPO, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["source_dir"] = os.path.join(root, "slides")
    cfg["out_root"] = os.path.join(root, "out")
    cfg["atlas_pdf"] = os.path.join(root, "atlas.pdf")
    cfg["export_dir"] = os.path.join(root, "exports")
    # Deliberately not beside the roots it names: a stage that guessed the
    # config's location from its own path would resolve somewhere else.
    deep = os.path.join(root, "elsewhere", "deeper")
    os.makedirs(deep)
    path = os.path.join(deep, "study.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return path


def run_probe(config_path, out_path):
    env = dict(os.environ, LS_CONFIG=config_path)
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


with tempfile.TemporaryDirectory() as tmp:
    a_cfg, b_cfg = synthetic(tmp, "study-a"), synthetic(tmp, "study-b")
    a = run_probe(a_cfg, os.path.join(tmp, "a.json"))
    b = run_probe(b_cfg, os.path.join(tmp, "b.json"))

    print("--- every stage imports, under a config it was pointed at ---")

    chk("no stage failed to import", a["_failed"], {})
    stages = [s for s in a if s != "_failed"]
    chk("every numbered stage was probed",
        len(stages), len(P.stage_files()))
    chk("...and that is 46", len(stages), 46)

    # The probe rewrites the config's own path to {config}, so this asserts the
    # stage resolved to the file we named and not to the repo's config.json.
    wrong = {s: a[s]["CONFIG_PATH"] for s in stages
             if "CONFIG_PATH" in a[s] and a[s]["CONFIG_PATH"] != "{config}"}
    chk("every stage that resolves config resolves to the named file",
        wrong, {})

    lacking = {s for s in stages if "CONFIG_PATH" not in a[s]}
    chk("the stages without their own loader are the known ones",
        lacking, NO_OWN_LOADER)

    print()
    print("--- and nothing is baked in behind the config's back ---")

    differences = P.diff(a, b)
    chk("no constant differs between two configs in two places",
        differences, [])
    for script, const, bv, av in differences[:12]:
        print(f"     {script} {const}: {bv!r} -> {av!r}")

    print()
    print("--- the fallback, for a bare run with nothing set ---")

    saved = os.environ.pop("LS_CONFIG", None)
    saved_strict = os.environ.pop("LS_CONFIG_STRICT", None)
    C.clear_cache()
    chk("without LS_CONFIG the repo config is used",
        os.path.normcase(C.resolve_path()),
        os.path.normcase(os.path.join(REPO, "config.json")))

    # And that fallback is exactly what a test must not get, which is what
    # run.sh sets LS_CONFIG_STRICT for.
    os.environ["LS_CONFIG_STRICT"] = "1"
    try:
        C.resolve_path()
        chk("under LS_CONFIG_STRICT the fallback is refused", False, True)
    except SystemExit as exc:
        chk("under LS_CONFIG_STRICT the fallback is refused", True, True)
        chk("and it says how a suite should name one",
            "_fixture.py" in str(exc), True)

    os.environ.pop("LS_CONFIG_STRICT", None)
    for name, value in (("LS_CONFIG", saved), ("LS_CONFIG_STRICT", saved_strict)):
        if value is not None:
            os.environ[name] = value
    C.clear_cache()

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
