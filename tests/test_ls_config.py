"""ls_config: the spec table, the validator, the defaults and the loader.

The point of the module is that a bad config fails with a sentence a user can
act on, and that a key nobody reads is visibly different from a key everybody
reads. Both are tested here rather than discovered on a twelve-hour run.

Run:  python tests/test_ls_config.py
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import ls_config as C                                       # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:66} {got!r}")
    if not ok:
        failures.append(name)


def minimal(tmp, **over):
    """A config that validates, with every required key present."""
    src = os.path.join(tmp, "slides")
    os.makedirs(src, exist_ok=True)
    atlas = os.path.join(tmp, "atlas.pdf")
    open(atlas, "wb").close()
    cfg = {
        "source_dir": src,
        "out_root": os.path.join(tmp, "out"),
        "atlas_pdf": atlas,
        "pixel_size_um": 0.65,
        "section_thickness_um": 14.0,
        "overview_target_um_per_px": 5.2,
        "slide_naming": {"pattern": r"^(?P<subject>[A-Z]+\d+)_(?P<slide>\d+)\.czi$"},
    }
    cfg.update(over)
    return cfg


def write(tmp, cfg, name="config.json"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return path


# --------------------------------------------------------------------------
print("--- validation ---")

with tempfile.TemporaryDirectory() as tmp:
    errs, warns = C.validate(minimal(tmp))
    chk("a minimal config validates clean", (errs, warns), ([], []))

    cfg = minimal(tmp)
    del cfg["pixel_size_um"]
    errs, _ = C.validate(cfg)
    chk("a missing required key is one error", len(errs), 1)
    chk("the error names the key", "`pixel_size_um`" in errs[0], True)
    chk("the error carries the hint", "micrometres" in errs[0], True)

    errs, _ = C.validate(minimal(tmp, pixel_size_um="0.65"))
    chk("a string where a number belongs is an error", len(errs), 1)
    chk("the type error says what it got", "got str" in errs[0], True)

    errs, _ = C.validate(minimal(tmp, pixel_size_um=-1.0))
    chk("a non-positive size is an error", len(errs), 1)

    errs, _ = C.validate(minimal(tmp, section_order_convention="whatever"))
    chk("a value outside `choices` is an error", len(errs), 1)

    errs, _ = C.validate(minimal(tmp, source_dir=17))
    chk("a number where a path belongs is an error", len(errs), 1)

    errs, _ = C.validate(minimal(tmp, out_root=os.path.join(tmp, "not-yet")))
    chk("out_root need not exist yet", errs, [])

    errs, _ = C.validate(minimal(tmp, export_dir=os.path.join(tmp, "not-yet")))
    chk("export_dir need not exist yet", errs, [])

# --------------------------------------------------------------------------
print()
print("--- the naming pattern is the join key, so it is checked ---")

with tempfile.TemporaryDirectory() as tmp:
    errs, _ = C.validate(minimal(tmp, slide_naming={"pattern": r"^(\w+)_(\d+)\.czi$"}))
    chk("a pattern with no (?P<subject>) group is an error", len(errs), 1)
    chk("the error says why subject matters", "joins on" in errs[0], True)

    errs, _ = C.validate(minimal(tmp, slide_naming={"pattern": r"^(?P<subject>[\.czi$"}))
    chk("an uncompilable pattern is an error", len(errs), 1)
    chk("the error quotes the regex complaint", "not a valid regex" in errs[0], True)

# --------------------------------------------------------------------------
print()
print("--- unknown keys warn, notes never do ---")

with tempfile.TemporaryDirectory() as tmp:
    cfg = minimal(tmp)
    cfg["flatfield"] = {"tile_sample_per_channel": 2000}
    cfg["detection"] = {"local_contrast_threshold": None}
    errs, warns = C.validate(cfg)
    chk("a retired key is a warning, not an error", errs, [])
    chk("both retired keys are reported", len(warns), 2)
    chk("each warning names its key",
        sorted("`flatfield`" in w for w in warns), [False, True])

    cfg = minimal(tmp)
    cfg["_comment"] = "notes are documentation, not settings"
    cfg["_section_order_note"] = "..."
    cfg["atlas_plate_set"] = {"dir": "plates", "_note": "...", "_options": ["a"]}
    errs, warns = C.validate(cfg)
    chk("underscore-prefixed notes are never reported", (errs, warns), ([], []))

    cfg = minimal(tmp)
    cfg["groups"] = {"order": ["a", "b"], "by_animal": {"XX9": "a", "YY7": "b"}}
    errs, warns = C.validate(cfg)
    chk("a `raw` key's contents are data, not schema", (errs, warns), ([], []))

# --------------------------------------------------------------------------
print()
print("--- the Fiji stages cannot see a Python default ---")

with tempfile.TemporaryDirectory() as tmp:
    chk("the four keys Groovy reads are marked materialise",
        sorted(k.path for k in C.SPEC if k.materialise),
        ["out_root", "overview_target_um_per_px", "pixel_size_um", "source_dir"])

    cfg = minimal(tmp)
    del cfg["overview_target_um_per_px"]
    errs, _ = C.validate(cfg)
    chk("omitting a materialise key is an error even though it has a default",
        len(errs), 1)
    chk("and the error says why", "cannot see Python defaults" in errs[0], True)
    chk("...it would otherwise have been filled in silently",
        C.apply_defaults(cfg)["overview_target_um_per_px"], 5.2)

# --------------------------------------------------------------------------
print()
print("--- an unplugged drive warns; it does not stop 45 stages importing ---")

with tempfile.TemporaryDirectory() as tmp:
    gone = os.path.join(tmp, "unplugged")
    cfg = minimal(tmp)
    cfg["source_dir"] = gone
    errs, warns = C.validate(cfg)
    chk("a source_dir that is not there is a warning, not an error", errs, [])
    chk("the warning names the path", any(gone in w for w in warns), True)
    chk("missing_paths reports it",
        [k.path for k, _ in C.missing_paths(cfg)], ["source_dir"])

    errs, _ = C.validate(cfg, strict_paths=True)
    chk("the settings dialog gets it as an error instead", len(errs), 1)

    try:
        C.require_path("source_dir", cfg)
        chk("require_path raises where the file is opened", False, True)
    except SystemExit as exc:
        chk("require_path raises where the file is opened", True, True)
        chk("and names the config to fix", "config:" in str(exc), True)

    chk("require_path returns the path when it is there",
        C.require_path("source_dir", minimal(tmp)),
        os.path.join(tmp, "slides"))

# --------------------------------------------------------------------------
print()
print("--- defaults ---")

with tempfile.TemporaryDirectory() as tmp:
    full = C.apply_defaults(minimal(tmp))
    chk("schema_version is filled in", full["schema_version"], C.SCHEMA_VERSION)
    chk("atlas_plate_set.dir defaults to plates",
        full["atlas_plate_set"]["dir"], "plates")
    chk("abercrombie defaults on",
        full["detection"]["abercrombie"]["enabled"], True)
    chk("case_insensitive defaults on",
        full["slide_naming"]["case_insensitive"], True)
    chk("a supplied value is not overwritten",
        C.apply_defaults(minimal(tmp, section_order_convention="S_scan_order"))
        ["section_order_convention"], "S_scan_order")

    before = minimal(tmp)
    C.apply_defaults(before)
    chk("apply_defaults does not mutate its argument",
        "atlas_plate_set" in before, False)

    mutable = C.apply_defaults(minimal(tmp))
    mutable["detection"]["abercrombie"]["enabled"] = False
    chk("defaults are copied, not shared between calls",
        C.apply_defaults(minimal(tmp))["detection"]["abercrombie"]["enabled"],
        True)

# --------------------------------------------------------------------------
print()
print("--- loading, LS_CONFIG and the cache ---")

_saved = os.environ.get("LS_CONFIG")
with tempfile.TemporaryDirectory() as tmp:
    deep = os.path.join(tmp, "somewhere", "else")
    os.makedirs(deep)
    path = write(deep, minimal(tmp), "study.json")

    os.environ["LS_CONFIG"] = path
    C.clear_cache()
    chk("resolve_path follows LS_CONFIG",
        os.path.normcase(C.resolve_path()), os.path.normcase(path))
    cfg = C.load()
    chk("load returns the file LS_CONFIG names",
        cfg["source_dir"], os.path.join(tmp, "slides"))
    chk("load applies defaults", cfg["atlas_plate_set"]["dir"], "plates")

    chk("a second load is the cached object", C.load() is cfg, True)

    # The app re-execs stage modules on a config change but this module stays
    # in sys.modules, so an uncached read here would serve the old config.
    changed = minimal(tmp)
    changed["pixel_size_um"] = 0.325
    write(deep, changed, "study.json")
    chk("the cache notices the file changed", C.load()["pixel_size_um"], 0.325)

    del os.environ["LS_CONFIG"]
    C.clear_cache()
    chk("without LS_CONFIG the repo config is the fallback",
        os.path.normcase(C.resolve_path()),
        os.path.normcase(os.path.join(REPO, "config.json")))

    os.environ["LS_CONFIG"] = os.path.join(tmp, "absent.json")
    C.clear_cache()
    try:
        C.load()
        chk("a missing config raises SystemExit", False, True)
    except SystemExit as exc:
        chk("a missing config raises SystemExit", True, True)
        chk("and says how to fix it", "LS_CONFIG" in str(exc), True)

    bad = write(tmp, {}, "bad.json")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    os.environ["LS_CONFIG"] = bad
    C.clear_cache()
    try:
        C.load()
        chk("invalid JSON raises SystemExit", False, True)
    except SystemExit as exc:
        chk("invalid JSON raises SystemExit", True, True)
        chk("and names the file", os.path.basename(bad) in str(exc), True)

if _saved is None:
    os.environ.pop("LS_CONFIG", None)
else:
    os.environ["LS_CONFIG"] = _saved
C.clear_cache()

# --------------------------------------------------------------------------
print()
print("--- the spec table itself ---")

chk("every key has a one-line doc",
    [k.path for k in C.SPEC if not k.doc], [])
chk("every key path is unique",
    len({k.path for k in C.SPEC}), len(C.SPEC))
chk("every required key is either defaulted or has no default",
    [k.path for k in C.SPEC if k.required and k.default is not None
     and k.type in ("path_dir", "path_file")], [])
chk("documented keys are marked, not silently live",
    sorted(k.path for k in C.SPEC if k.status == C.DOCUMENTED),
    ["atlas_scope", "marker_identity"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
