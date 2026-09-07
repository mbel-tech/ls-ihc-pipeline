"""The pipeline's configuration: one spec table, one loader, one validator.

Until now the loader was six lines copy-pasted into 37 stages, with no schema,
no defaults and no validation. A mistyped key was a `KeyError` at import; a key
nobody read looked exactly like a key everybody read.

`SPEC` below is the single source of truth. Every entry names a key, its type,
whether it is required, its default, a one-line hint used in error messages and
in the app's settings dialog, and the long-form operator note that belongs
beside it in a written config. Four things are generated from that one table:
validation, `config.example.json`, the docs reference, and the dialog fields.
That is why this is hand-rolled rather than jsonschema, which would supply the
first and leave the other three to drift.

Stages use it as:

    from ls_config import CONFIG, OUT_ROOT, SOURCE_DIR

`LS_CONFIG` names the file explicitly; the repo-root `config.json` is the
fallback. Frozen, the scripts sit inside `_internal/` while config.json is
beside the executable, so the file-relative fallback would point at a file that
does not exist - which is why `LS_CONFIG` exists and why every stage must
honour it.

An unknown key WARNS rather than fails. A stale config should surface, not
abort a twelve-hour run.
"""

import json
import os
import re
import sys

SCHEMA_VERSION = 1

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Status of a key, as reported by the generated docs.
#   live       - read by at least one stage
#   documented - read by nothing, but carries operator knowledge a later
#                sub-project will wire. Emitted into the example config.
LIVE, DOCUMENTED = "live", "documented"


class Key:
    """One configuration key.

    `path` is dotted: "detection.abercrombie.enabled". `note` is the long-form
    text emitted as a sibling `_note` in a generated config - it is where the
    reasoning lives, and several of them are the only written record of an
    operator decision, so they are data, not decoration.
    """

    def __init__(self, path, type, doc, required=False, default=None,
                 note=None, consumers=(), status=LIVE, choices=None,
                 materialise=False):
        self.path = path
        self.type = type
        self.doc = doc
        self.required = required
        self.default = default
        self.note = note
        self.consumers = tuple(consumers)
        self.status = status
        self.choices = choices
        # A key the Fiji/Groovy stages read straight out of the JSON. They
        # cannot see a Python default, so it must be present as a literal in
        # every written config or they get null.
        self.materialise = materialise

    @property
    def parts(self):
        return self.path.split(".")

    def __repr__(self):
        return f"<Key {self.path} {self.type}{' required' if self.required else ''}>"


# --------------------------------------------------------------------------
# The spec. Order here is the order keys appear in a generated config.
# --------------------------------------------------------------------------

SPEC = [
    Key("schema_version", "int",
        "Config format version. Written by the app; do not edit by hand.",
        required=True, default=SCHEMA_VERSION, consumers=["ls_config"]),

    Key("study.name", "str",
        "A short name for this study, shown in the app's study picker.",
        default="", consumers=["app"]),

    # ---- paths -----------------------------------------------------------
    Key("source_dir", "path_dir",
        "The folder holding the .czi files.",
        required=True, materialise=True,
        consumers=["00_manifest", "00b", "00d", "01b_pick", "01e", "01h",
                   "01_overviews", "05a", "05c", "06b", "app"]),

    Key("out_root", "path_dir_create",
        "Where every result is written. Needs room - overviews alone run to "
        "several GB.",
        required=True, materialise=True, consumers=["every stage"]),

    Key("atlas_pdf", "path_file",
        "The atlas the plates and region seeds are extracted from.",
        required=True,
        consumers=["04a_atlas_extract", "04a2", "04a4", "app"]),

    Key("export_dir", "path_dir_opt",
        "Where the ROI curator files its exports. Empty means "
        "<out_root>/exports.",
        default=None,
        note="One folder per export, named DD.MM.YYYY_HH.MM, with the same "
             "stamp on every file in it. Read by 04l (shown in the page, and "
             "the default for --export-dir) and by the app's download handler, "
             "so the two cannot disagree. A browser writes here only after the "
             "operator picks the folder with the page's Folder... button - a "
             "web page cannot be handed a path.",
        consumers=["04l", "05a", "app/curator_view"]),

    Key("source_files", "list_str_opt",
        "Optional allowlist of filenames to process. Empty means every file "
        "in source_dir.",
        default=None, consumers=["00_manifest", "app/import_slides"]),

    # ---- slide naming ----------------------------------------------------
    Key("slide_naming.pattern", "regex",
        "Regex matching your slide filenames, with a named group 'subject'. "
        "Optional named groups 'slide' and 'replicate'; any others are "
        "carried through as manifest columns.",
        required=True,
        note="Built by the app's pattern builder, and editable by hand. A "
             "filename that does not match is REPORTED, never silently "
             "skipped - an invisible file is the failure mode this whole "
             "block exists to prevent. `subject` becomes the `animal` column "
             "and the first field of every scene_uid, so it is the key the "
             "metadata join later runs on.",
        consumers=["00_manifest", "app/slides"]),

    Key("slide_naming.example", "str",
        "One real filename, used by the app to preview the parse.",
        default="", consumers=["app/slides"]),

    Key("slide_naming.case_insensitive", "bool",
        "Match filenames case-insensitively.",
        default=True, consumers=["00_manifest", "app/slides"]),

    # ---- acquisition geometry -------------------------------------------
    Key("section_order_convention", "str",
        "How serial section order is recovered from the scan.",
        required=True, default="S_scan_order", choices=["S_scan_order"],
        note="Confirmed by user 2026-08-11 for the LS dataset. Serial order = "
             "scene index as acquired. The scanner ran column-major (s0 "
             "top-left, s1 below it, s2 next column top), and on staggered "
             "slides such as LS120_1a no grid model reproduces the physical "
             "layout at all.",
        consumers=["00_manifest"]),

    Key("pixel_size_um", "float",
        "Camera pixel size at the objective used, in micrometres.",
        required=True, materialise=True,
        note="The CZI carries this too - czi_meta.py reads it from "
             "Scaling/Items/Distance[@Id='X'] - so a future revision should "
             "check this value against the files rather than trust it.",
        consumers=["01c", "01e", "01f", "01_overviews", "05a", "05c", "06a"]),

    Key("section_thickness_um", "float",
        "How thick the sections were cut, in micrometres.",
        required=True,
        note="NOT recoverable from the CZIs - they carry no size_z, being "
             "single-plane images of a physical section - so it has to be "
             "supplied. This is the number the Abercrombie correction needs; "
             "see detection.abercrombie below. 14.0 for the LS dataset, "
             "operator-stated 2026-08-30.",
        consumers=["06a"]),

    Key("overview_target_um_per_px", "float",
        "Resolution the per-section overviews are exported at.",
        required=True, default=5.2, materialise=True,
        consumers=["01_overviews", "01_overviews.groovy"]),

    # ---- channels (replaced by the channels/markers sub-project) ---------
    Key("channels.dapi_index", "int",
        "Which CZI channel plane is the nuclear counterstain.",
        required=True, default=0,
        note="Read only by 05c_detect_rois today; every earlier stage assumes "
             "plane 0 structurally. The channels/markers sub-project replaces "
             "this whole block with a per-channel role table, so it is left "
             "as-is rather than changed twice.",
        consumers=["05c"]),

    Key("channels.marker_index", "int",
        "Which CZI channel plane carries the marker.",
        required=True, default=1, consumers=["05c"]),

    Key("marker_identity", "raw",
        "Which fluorophore is which marker. Filled in by "
        "00c_channel_identity.py, then confirmed by the operator.",
        default=None, status=DOCUMENTED,
        note="Written by 00c --accept and read by no stage. Until it is "
             "filled in, neither fluorophore may be referred to by a "
             "biological name downstream. Kept because it is the only written "
             "record of the confirmed assignment; the channels/markers "
             "sub-project wires it.",
        consumers=["00c (writes)"]),

    # ---- detection -------------------------------------------------------
    Key("detection.nucleus_diameter_um", "float",
        "Expected nucleus diameter, the scale StarDist is run at.",
        required=True, default=7.0, consumers=["05c"]),

    Key("detection.abercrombie.enabled", "bool",
        "Correct counted nuclear profiles to nuclei.",
        default=True,
        note="A single-plane image of a section counts nuclear PROFILES, not "
             "nuclei: a nucleus straddling the cut face still appears in the "
             "section it is cut into. Abercrombie N = n * T/(T + h), with T "
             "the section thickness and h the mean diameter of the counted "
             "object along the axis perpendicular to the section. At T=14 and "
             "h=7 the factor is 0.667 - uncorrected counts are 50% too high. "
             "h is MEASURED per marker and region from the nuclear-counterstain "
             "segmentation, not taken from nucleus_diameter_um above: that "
             "value is a detection-scale assumption, and the factor moves from "
             "0.737 to 0.583 across a plausible 5-10 um range, so using it "
             "would bury an unmeasured constant in every density. Abercrombie "
             "assumes spherical, randomly positioned objects and applies no "
             "lost-caps correction; the unbiased alternative is the optical or "
             "physical disector, which needs z-stacks a single-plane dataset "
             "does not have. Report raw and corrected counts side by side and "
             "say which is which.",
        consumers=["06a"]),

    # ---- atlas -----------------------------------------------------------
    Key("atlas_plate_set.dir", "str",
        "Which plate set the ROI curator and the registration use.",
        default="plates", choices=["plates", "plates_merged", "plates_final"],
        note="Both read this, so they cannot drift apart. IDs COLLIDE between "
             "sets - the same plate_NNN name exists in more than one set and "
             "points at a different image - so a landmark file records the set "
             "it was made against. Set this once, before any landmark is "
             "placed; changing it later invalidates landmarks made against the "
             "old set. plates = one image per atlas page as extracted; "
             "plates_merged = one image per figure; plates_final = the curated "
             "set. Start at plates and move up as the atlas chain produces "
             "them.",
        consumers=["04e", "04k", "04l"]),

    Key("atlas_figure_sections.two_sections", "str_opt",
        "Inclusive figure-number range, as a string, of merged figures "
        "holding two sections each - e.g. \"31-47\". Empty leaves every "
        "figure at whatever 04a2 detected.",
        default=None,
        note="Operator knowledge, not measurement: the band detector in 04a2 "
             "mis-counts when two sections touch (their legend text bridges "
             "every row, so no row is empty) and when one section is crossed "
             "by an internal white band (read as two). This declaration is the "
             "authority; the detector is not. 04a3b_enforce_sections.py takes "
             "the count from here and decides only WHERE to cut. Record the "
             "date and the reason alongside it when you fill it in.",
        consumers=["04a3b"]),

    Key("atlas_figure_sections.drop_inset_boxes", "raw",
        "Merged figure id -> the 1-based index of the box to drop, counted "
        "top to bottom.",
        default={},
        note="Boxes that are labelled INSETS, not sections - a detached "
             "callout of a structure that is also shown attached and labelled "
             "inside a section elsewhere in the atlas. An inset is not a "
             "plate, and holds no region seed. Empty by default on purpose: "
             "an entry is a claim about a figure in YOUR atlas, and a copied "
             "one would drop a real section box. Note that listing a figure "
             "here also exempts it from the two_sections count above, so list "
             "only the figures that really carry an inset.",
        consumers=["04a3b"]),

    Key("atlas_scope", "raw",
        "Which regions the atlas already labels, and which are still wanted.",
        default=None, status=DOCUMENTED,
        note="Read by no stage. Names are recorded exactly as the atlas writes "
             "them - no abbreviating, no reinterpreting - so the anatomy stays "
             "the atlas author's statement rather than this file's. Kept "
             "because it is the only written record of that scope decision; "
             "the replaceable-atlas sub-project wires it.",
        consumers=[]),

    # ---- unblinding (replaced by the metadata-join sub-project) ----------
    Key("groups.order", "list_str",
        "Which treatment is the LEFT half of every Shotgun slide, and the "
        "order the halves are drawn in.",
        default=[],
        note="Explicit because dict order is not a decision. Two entries: the "
             "slide splits in two.",
        consumers=["04l", "06c", "06d"]),

    Key("groups.by_animal", "raw",
        "Subject ID -> treatment, using exactly the labels in groups.order.",
        default={},
        note="UNBLINDING KEY. A DELIBERATE EXCEPTION to the blinding rule "
             "('no stage before 06b may read a group label'): a figure that "
             "compares groups cannot be built without knowing them. Nothing "
             "here reaches a count, a threshold or a curation decision - the "
             "curator's own state is written before this file is read and does "
             "not depend on it - but a deck laid out by group is, by "
             "construction, not blind. Leave empty to keep it that way; the "
             "Shotgun button disables itself when it is. An animal left out is "
             "reported and skipped rather than guessed at. The metadata-join "
             "sub-project replaces this with a real table join.",
        consumers=["04l", "05c", "06c", "06d"]),
]

BY_PATH = {k.path: k for k in SPEC}


# --------------------------------------------------------------------------
# Type checking
# --------------------------------------------------------------------------

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check(key, value):
    """Return an error string, or None if `value` is acceptable for `key`."""
    t = key.type

    if t in ("str", "str_opt"):
        if not isinstance(value, str):
            return f"expected a string, got {type(value).__name__}"
        if key.choices and value not in key.choices:
            return f"must be one of {', '.join(key.choices)}"
    elif t == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"expected a whole number, got {type(value).__name__}"
    elif t == "float":
        if not _is_num(value):
            return f"expected a number, got {type(value).__name__}"
        if value <= 0:
            return f"must be greater than zero, got {value}"
    elif t == "bool":
        if not isinstance(value, bool):
            return f"expected true or false, got {type(value).__name__}"
    elif t in ("list_str", "list_str_opt"):
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            return "expected a list of strings"
    elif t == "regex":
        if not isinstance(value, str):
            return f"expected a regex string, got {type(value).__name__}"
        try:
            compiled = re.compile(value)
        except re.error as exc:
            return f"is not a valid regex: {exc}"
        if "subject" not in compiled.groupindex:
            return ("must contain a named group (?P<subject>...) - it is the "
                    "key every later table joins on")
    elif t in ("path_dir", "path_file", "path_dir_create", "path_dir_opt"):
        if not isinstance(value, str) or not value.strip():
            return "expected a path"
        # Existence is deliberately NOT checked here - see `missing_paths`.
        # path_dir_create and path_dir_opt are made on demand by whoever
        # writes into them - out_root by the app, export_dir by the curator's
        # first export - so neither is required to exist yet.
    elif t == "raw":
        pass
    else:                                                   # pragma: no cover
        return f"unknown spec type {t!r}"
    return None


def _get(tree, parts):
    """(found, value) for a dotted path in a nested dict."""
    node = tree
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return False, None
        node = node[p]
    return True, node


def _set(tree, parts, value):
    node = tree
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _declared_prefixes():
    """Every dotted path the spec knows, including intermediate containers."""
    out = set()
    for key in SPEC:
        parts = key.parts
        for i in range(1, len(parts) + 1):
            out.add(".".join(parts[:i]))
    return out


def _unknown_paths(cfg):
    """Dotted paths present in `cfg` that the spec does not declare.

    Keys starting with `_` are notes and are never reported. Descent stops at
    a declared `raw` key, whose contents are the user's data, not our schema.
    """
    declared = _declared_prefixes()
    raw_paths = {k.path for k in SPEC if k.type == "raw"}
    found = []

    def walk(node, prefix):
        for name, value in node.items():
            if name.startswith("_"):
                continue
            path = f"{prefix}.{name}" if prefix else name
            if path in raw_paths:
                continue
            if path not in declared:
                found.append(path)
                continue
            if isinstance(value, dict):
                walk(value, path)

    walk(cfg, "")
    return sorted(found)


#: Path keys whose target must already exist to be usable. path_dir_create
#: and path_dir_opt are made on demand by whoever writes into them.
MUST_EXIST = {"path_dir": os.path.isdir, "path_file": os.path.isfile}


def missing_paths(cfg):
    """[(key, value)] for configured paths that are not there right now.

    Kept apart from validate() because absence is not the same fault as a
    malformed value. Forty of the forty-five stages never open `source_dir`,
    and the drive it lives on has gone away mid-run before - see ls_io.py. A
    stage list that refuses to load because a drive is unplugged is worse than
    a stage that says so when it is actually run, which is `require_path`.
    """
    out = []
    for key in SPEC:
        test = MUST_EXIST.get(key.type)
        if test is None:
            continue
        found, value = _get(cfg, key.parts)
        if found and isinstance(value, str) and value.strip() and not test(value):
            out.append((key, value))
    return out


def validate(cfg, path="<config>", strict_paths=False):
    """Return (errors, warnings) as lists of printable strings.

    Errors are fatal: a required key missing, or a value of the wrong shape.
    Warnings are not: an unknown key, and a configured path that is not there,
    are both reported and carried past - a stale config or an unplugged drive
    should surface, not abort a twelve-hour run.

    `strict_paths` promotes the path warnings to errors. The settings dialog
    passes it, because that is the one place the user can act on them.
    """
    errors, warnings = [], []

    for key in SPEC:
        found, value = _get(cfg, key.parts)
        if not found or value is None:
            if key.required and key.default is None:
                errors.append(f"{path}: `{key.path}` is required - {key.doc}")
            elif key.materialise:
                # The Fiji stages slurp this JSON directly and never see a
                # Python default, so a defaulted-but-absent key reaches them
                # as null.
                errors.append(
                    f"{path}: `{key.path}` must be written out, not left to "
                    f"its default - the Fiji stages read this file directly "
                    f"and cannot see Python defaults")
            continue
        problem = _check(key, value)
        if problem:
            errors.append(f"{path}: `{key.path}` {problem}\n    {key.doc}")

    for key, value in missing_paths(cfg):
        line = f"{path}: `{key.path}` does not exist: {value}"
        (errors if strict_paths else warnings).append(line)

    for unknown in _unknown_paths(cfg):
        warnings.append(f"{path}: `{unknown}` is not a setting this pipeline "
                        f"reads - it is ignored")

    return errors, warnings


def require_path(dotted, cfg=None):
    """A configured path that must exist NOW. Call it where the file is opened.

    The other half of missing_paths(): absence warns at import and fails here,
    in the one stage that actually needs the thing, with the remedy attached.
    """
    cfg = cfg if cfg is not None else load()
    found, value = _get(cfg, dotted.split("."))
    if not found or not value or not os.path.exists(value):
        raise SystemExit(
            f"`{dotted}` is {value!r}, which does not exist.\n"
            f"  config: {resolve_path()}\n"
            f"  Fix it in the app under Pipeline > Settings, or edit the file.")
    return value



def apply_defaults(cfg):
    """Fill every absent key that has a default. Returns a new dict."""
    out = json.loads(json.dumps(cfg))
    for key in SPEC:
        if key.default is None:
            continue
        found, value = _get(out, key.parts)
        if not found or value is None:
            _set(out, key.parts, json.loads(json.dumps(key.default)))
    return out


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def resolve_path(explicit=None):
    """Where the active config lives.

    `LS_CONFIG` names it explicitly; the repo-root `config.json` is the
    fallback, so a bare `python scripts/XX.py` and a fresh clone keep working.
    Frozen, the fallback points inside `_internal/` at a file that is not
    there, which is the whole reason `LS_CONFIG` exists.
    """
    return os.path.abspath(
        explicit
        or os.environ.get("LS_CONFIG")
        or os.path.join(REPO, "config.json"))


_cache = {}


def load(path=None, strict=True):
    """The validated, defaulted config as a plain dict.

    Cached on (path, mtime, size), because `app/runner.py` re-execs stage
    modules on a config change but this module stays in `sys.modules` - an
    uncached read here would serve the previous config to every stage.
    """
    path = resolve_path(path)
    try:
        st = os.stat(path)
        stamp = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None

    if stamp is not None and _cache.get("stamp") == stamp:
        return _cache["cfg"]

    if not os.path.exists(path):
        raise SystemExit(
            f"no config at {path}\n"
            f"  Set LS_CONFIG to your study's config file, or copy "
            f"config.example.json to {os.path.join(REPO, 'config.json')} and "
            f"fill it in.")

    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}")

    errors, warnings = validate(raw, path)
    for w in warnings:
        print(f"  !! {w}", file=sys.stderr)
    if errors and strict:
        raise SystemExit("config is not usable:\n  " + "\n  ".join(errors))

    cfg = apply_defaults(raw)
    if stamp is not None:
        _cache["stamp"], _cache["cfg"] = stamp, cfg
    return cfg


def clear_cache():
    """Drop the memoised config. For tests, and for the app after a save."""
    _cache.clear()


# PEP 562: `from ls_config import CONFIG, OUT_ROOT` reads config on first use,
# so this module stays importable by the generators and the tests when no
# config exists at all.
_LAZY = {
    "CONFIG": lambda c: c,
    "OUT_ROOT": lambda c: c["out_root"],
    "SOURCE_DIR": lambda c: c["source_dir"],
    "CONFIG_PATH": lambda c: resolve_path(),
}


def __getattr__(name):
    if name in _LAZY:
        return _LAZY[name](load())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
