"""A throwaway study config, so a suite tests itself and not the operator.

Not a test. Shared setup.

Every stage reads config at import. A suite that does not say which config it
means falls through to the repo's own `config.json` - the operator's live
study - and then passes or fails on their paths, their plate set and their
thresholds. `tests/test_export_target.py` was asserting against the real
`export_dir`, so it would have started failing the day that value changed, for
reasons having nothing to do with the code under test.

`tests/run.sh` sets `LS_CONFIG_STRICT=1`, which turns that fallback into an
error, so a suite that forgets is told rather than quietly succeeding.

    with temp_study(atlas_plate_set={"dir": "plates_final"}) as study:
        mod = load_stage("04l_roi_curator.py")
        ...                     # study.out_root, study.source_dir, study.path

Generalises what 21 suites were already doing by hand - load the example,
rewrite the paths into a TemporaryDirectory, write it, name it through
LS_CONFIG - and adds the part they all left out: dropping `ls_config` and the
stage modules from `sys.modules` on the way in and out, so one suite cannot
inherit the config of the one before it.
"""

import atexit
import contextlib
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")


class Study:
    """Where a temporary study put its things."""

    def __init__(self, path, root, config):
        self.path = path
        self.root = root
        self.config = config
        self.source_dir = config["source_dir"]
        self.out_root = config["out_root"]
        self.export_dir = config["export_dir"]
        self.atlas_pdf = config["atlas_pdf"]


def _forget_modules():
    """Drop ls_config and any stage module, so the next import re-reads."""
    for name in [n for n in sys.modules
                 if n == "ls_config" or n.startswith(("probe_", "lsstage_"))]:
        del sys.modules[name]


def write_study(tmp, **overrides):
    """Lay out a usable study under `tmp`. Returns its config path."""
    for sub in ("slides", "out", "exports"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=True)
    atlas = os.path.join(tmp, "atlas.pdf")
    if not os.path.exists(atlas):
        open(atlas, "wb").close()

    with open(os.path.join(REPO, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["source_dir"] = os.path.join(tmp, "slides")
    cfg["out_root"] = os.path.join(tmp, "out")
    cfg["export_dir"] = os.path.join(tmp, "exports")
    cfg["atlas_pdf"] = atlas
    cfg.update(overrides)

    path = os.path.join(tmp, "study.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, indent=2)
    return path


@contextlib.contextmanager
def temp_study(**overrides):
    """A validating study config in a temp tree, named through LS_CONFIG."""
    saved_config = os.environ.get("LS_CONFIG")
    saved_strict = os.environ.get("LS_CONFIG_STRICT")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_study(tmp, **overrides)
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)

        os.environ["LS_CONFIG"] = path
        os.environ.pop("LS_CONFIG_STRICT", None)
        _forget_modules()
        try:
            yield Study(path, tmp, cfg)
        finally:
            _forget_modules()
            for name, value in (("LS_CONFIG", saved_config),
                                ("LS_CONFIG_STRICT", saved_strict)):
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def use_temp_study(**overrides):
    """Name a throwaway study for the rest of this process, and return it.

    The suites here are plain scripts, not pytest: they import stage modules at
    module level and there is no fixture to hang a `with` block on. So this
    version enters the context and leaves it entered, cleaning up at exit.

    Two lines at the top of a suite, above its first stage import:

        from _fixture import use_temp_study
        STUDY = use_temp_study()
    """
    ctx = temp_study(**overrides)
    study = ctx.__enter__()
    atexit.register(lambda: ctx.__exit__(None, None, None))
    return study


def load_stage(script, name=None):
    """Import a numbered stage under whatever config is currently named."""
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    name = name or "lsstage_" + script[:-3]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS, script))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    # `python tests/_fixture.py <dir>` lays out a study there and prints its
    # config path. tests/run.sh uses it so the curator pages are built against
    # a throwaway study rather than the operator's - the same reason the build
    # already passes --no-seed and --no-proposals.
    print(write_study(os.path.abspath(sys.argv[1])))
