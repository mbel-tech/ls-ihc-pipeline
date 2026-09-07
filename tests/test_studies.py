"""Named studies, the settings beside them, and migrating a pre-study config.

A study is one config file with a name. The app keeps a small settings file
saying which was open last. Stages still see exactly one thing - LS_CONFIG, an
absolute path - so run_all.sh and the three Groovy stages need no change at all;
the study layer sits above that, not instead of it.

Every test here points LS_HOME at a temp directory. None of them may touch a
real home: a suite that wrote to ~/.ls-pipeline would change which study the
operator has open, from a test run.

Run:  python tests/test_studies.py
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
    shown = got if len(repr(got)) < 88 else f"<{type(got).__name__}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:62} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


class home:
    """A temp LS_HOME, with LS_CONFIG and the rest cleared inside it."""

    NAMES = ("LS_HOME", "LS_CONFIG", "LS_STUDY", "LS_STUDIES_DIR",
             "LS_CONFIG_STRICT")

    def __enter__(self):
        self.saved = {n: os.environ.get(n) for n in self.NAMES}
        self.tmp = tempfile.TemporaryDirectory()
        for n in self.NAMES:
            os.environ.pop(n, None)
        os.environ["LS_HOME"] = self.tmp.name
        C.clear_cache()
        return self.tmp.name

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v
        C.clear_cache()
        self.tmp.cleanup()


def a_config(tmp, **over):
    """A validating config on disk, standing in for a pre-study one."""
    root = os.path.join(tmp, "study-data")
    os.makedirs(os.path.join(root, "slides"), exist_ok=True)
    atlas = os.path.join(root, "atlas.pdf")
    open(atlas, "wb").close()
    with open(os.path.join(REPO, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["source_dir"] = os.path.join(root, "slides")
    cfg["out_root"] = os.path.join(root, "out")
    cfg["atlas_pdf"] = atlas
    cfg["export_dir"] = os.path.join(root, "exports")
    cfg.update(over)
    path = os.path.join(tmp, "legacy-config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return path


# --------------------------------------------------------------------------
print("--- where things live ---")

with home() as tmp:
    chk("LS_HOME wins over the real home", C.app_home(), os.path.abspath(tmp))
    chk("settings sit in it", C.settings_path(),
        os.path.join(os.path.abspath(tmp), "settings.json"))
    chk("studies sit beside them", C.studies_dir(),
        os.path.join(os.path.abspath(tmp), "studies"))
    chk("no settings yet is {}, not a crash", C.read_settings(), {})
    chk("no studies yet is []", C.list_studies(), [])

    C.write_settings({"active_study": "one"})
    chk("settings round-trip", C.read_settings()["active_study"], "one")
    C.write_settings({"recent": ["one"]})
    chk("a second write merges rather than replaces",
        sorted(k for k in C.read_settings() if not k.startswith("schema")),
        ["active_study", "recent"])

    chk("a name becomes a filename-safe slug",
        [C.slugify(n) for n in ("LS Dec 2025", "Pilot #2!", "  spaced  ")],
        ["ls-dec-2025", "pilot-2", "spaced"])
    try:
        C.slugify("!!!")
        chk("a name with nothing usable is refused", False, True)
    except SystemExit:
        chk("a name with nothing usable is refused", True, True)

# --------------------------------------------------------------------------
print()
print("--- migrating a pre-study config ---")

with home() as tmp:
    source = a_config(tmp)
    before = open(source, encoding="utf-8").read()

    target = C.migrate("LS Dec 2025", source)
    chk("the study is written under its slug",
        os.path.basename(target), "ls-dec-2025.json")
    chk("the original is left exactly as it was",
        open(source, encoding="utf-8").read(), before)
    chk("it becomes the active study",
        C.read_settings()["active_study"], "ls-dec-2025")
    chk("and it is listed", [s[:2] for s in C.list_studies()],
        [("ls-dec-2025", "LS Dec 2025")])

    migrated = json.load(open(target, encoding="utf-8"))
    original = json.load(open(source, encoding="utf-8"))
    lost = [k for k in original if k not in migrated]
    chk("no key is lost in the move", lost, [])
    chk("the display name is recorded", migrated["study"]["name"], "LS Dec 2025")
    chk("...and the schema version", migrated["schema_version"], C.SCHEMA_VERSION)

    try:
        C.migrate("LS Dec 2025", source)
        chk("migrating the same name twice is refused", False, True)
    except SystemExit as exc:
        chk("migrating the same name twice is refused", True, True)
        chk("and it says what to do", "Pick another name" in str(exc), True)

with home() as tmp:
    broken = a_config(tmp, pixel_size_um="not a number")
    try:
        C.migrate("Broken", broken)
        chk("an invalid config is not migrated", False, True)
    except SystemExit as exc:
        chk("an invalid config is not migrated", True, True)
        chk("and the reason is the validation error",
            "pixel_size_um" in str(exc), True)
    chk("...and nothing was written", C.list_studies(), [])

    try:
        C.migrate("Absent", os.path.join(tmp, "nope.json"))
        chk("a source that is not there is refused", False, True)
    except SystemExit:
        chk("a source that is not there is refused", True, True)

# --------------------------------------------------------------------------
print()
print("--- which config a stage ends up reading ---")

with home() as tmp:
    source = a_config(tmp)
    target = C.migrate("Study A", source)

    chk("with nothing set, the active study wins",
        os.path.normcase(C.resolve_path()), os.path.normcase(target))

    other = C.migrate("Study B", source)
    C.write_settings({"active_study": "study-a"})
    os.environ["LS_STUDY"] = "study-b"
    chk("LS_STUDY beats the active study",
        os.path.normcase(C.resolve_path()), os.path.normcase(other))

    os.environ["LS_CONFIG"] = source
    chk("LS_CONFIG beats everything",
        os.path.normcase(C.resolve_path()), os.path.normcase(source))
    del os.environ["LS_CONFIG"]

    # Falling back to whichever study is active would run the pipeline against
    # different data than the caller named, and say nothing about it.
    os.environ["LS_STUDY"] = "does-not-exist"
    try:
        C.resolve_path()
        chk("a study named but absent is an error, not a fallback", False, True)
    except SystemExit as exc:
        chk("a study named but absent is an error, not a fallback", True, True)
        chk("and it lists the ones that do exist", "study-a" in str(exc), True)
    del os.environ["LS_STUDY"]

    # A test must never inherit the operator's study by accident, which is the
    # whole reason run.sh sets this.
    os.environ["LS_CONFIG_STRICT"] = "1"
    try:
        C.resolve_path()
        chk("strict refuses even a configured study", False, True)
    except SystemExit:
        chk("strict refuses even a configured study", True, True)

with home() as tmp:
    chk("with no study at all, the repo config is still the fallback",
        os.path.normcase(C.resolve_path()),
        os.path.normcase(os.path.join(REPO, "config.json")))

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
