"""What a study's CZI channels are, and what each one is for.

A channel is declared once, in the study config, and resolved to a plane index
per file. Resolution goes by the CZI's own channel name first and the declared
index only as a fallback, because a file acquired with its channels in a
different order would otherwise be read plane-for-plane and produce a
perfectly plausible wrong number.

Nothing here opens a CZI. It takes the channel names a file reports - which
`czi_meta.read_metadata` already extracts - and says which plane each declared
channel is. `czi_read.py` does the reading.
"""

import re

NUCLEAR, MARKER, REGISTRATION, IGNORE = (
    "nuclear", "marker", "registration", "ignore")
ROLES = (NUCLEAR, MARKER, REGISTRATION, IGNORE)

#: How a marker's own objects are found.
SEGMENT_NUCLEAR, SEGMENT_OWN = "nuclear", "own"
SEGMENTS = (SEGMENT_NUCLEAR, SEGMENT_OWN)

#: What finds them when they are found on the marker's own channel.
BACKENDS = ("stardist", "threshold")

# The two acquisition layouts, so no caller writes the string itself.
LAYOUT_MULTIPLEX, LAYOUT_PAIRED = "multiplex", "paired"
LAYOUTS = (LAYOUT_MULTIPLEX, LAYOUT_PAIRED)

#: A channel name becomes a directory and a CSV value, so it has to survive
#: both. Deliberately narrow: a name is typed once and lives for years.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,63}$")


class ChannelError(Exception):
    """A declared channel could not be found in a file."""


class Channel:
    def __init__(self, name, role, czi_name=None, index=None,
                 segment=None, backend=None, nucleus_shaped=True):
        self.name = name
        self.role = role
        self.czi_name = czi_name
        self.index = index
        self.segment = segment
        self.backend = backend
        self.nucleus_shaped = nucleus_shaped

    def __repr__(self):
        return f"<Channel {self.name} {self.role}>"


def parse(block, has_nuclear=None):
    """`acquisition.channels` as a list of Channel, with defaults filled in."""
    entries = list(block or [])
    if has_nuclear is None:
        has_nuclear = any((e or {}).get("role") == NUCLEAR for e in entries)

    out = []
    for entry in entries:
        entry = entry or {}
        role = entry.get("role")
        segment = entry.get("segment")
        if role == MARKER and not segment:
            # Measuring a marker inside nuclei is what this pipeline has always
            # done, so it stays the default wherever there are nuclei to use.
            segment = SEGMENT_NUCLEAR if has_nuclear else SEGMENT_OWN
        backend = entry.get("backend")
        if segment == SEGMENT_OWN and not backend:
            backend = "stardist"
        out.append(Channel(
            name=entry.get("name"), role=role,
            czi_name=entry.get("czi_name"), index=entry.get("index"),
            segment=segment, backend=backend,
            nucleus_shaped=entry.get("nucleus_shaped", True)))
    return out


def nuclear(channels):
    """The nuclear counterstain, or None when a study has none."""
    return next((c for c in channels if c.role == NUCLEAR), None)


def markers(channels):
    """The channels that get measured, in declared order."""
    return [c for c in channels if c.role == MARKER]


def marker_names(cfg):
    """The markers this study measures, in declared order, as plain names.

    Layout-aware because the two layouts genuinely know it differently:

      multiplex  one scan carries every marker, so the channel table says
                 which channels are markers and what they are called.
      paired     each scan carries the nuclear channel plus ONE marker, so
                 there is no table to read - the study declares the list.

    Deliberately NOT derived from the manifest's marker_channel column, though
    the values are there. Every caller of this is a module-level constant
    evaluated at import, the manifest lives under out_root, and out_root may be
    absent or on an unplugged drive - which is the exact failure P0 removed by
    making a missing path warn rather than kill all 45 stages at import. Stage
    00 also WRITES the manifest, so it would depend on its own output to
    import.

    Takes the whole config, not the acquisition block, because which of the two
    sources to read is itself decided by `acquisition.layout`. A config that is
    malformed anywhere on that path yields no markers rather than raising: this
    is called at import of module-level constants, where a traceback would take
    every stage down with it.
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    acq = cfg.get("acquisition")
    if not isinstance(acq, dict):
        return []
    if acq.get("layout") == LAYOUT_PAIRED:
        declared = acq.get("markers") or []
        # A string is iterable, so list("AF568") would "succeed" and give six
        # single-letter markers. Judged, not crashed on and not accepted.
        if not isinstance(declared, (list, tuple)):
            return []
        return [str(m) for m in declared]
    table = acq.get("channels")
    if not isinstance(table, (list, tuple)):
        # Same trap the other way round: parse() would read a string channel
        # table one letter at a time. validate() is what says so; this only
        # declines to invent markers out of it.
        return []
    if not all(isinstance(e, dict) or e is None for e in table):
        return []
    return [c.name for c in markers(parse(table))]


#: The colours a marker may be drawn in. A CLOSED set, on purpose: the
#: settings dialog needs a choice widget and the generated docs need to list
#: what is on offer, and an arbitrary string is a typo that renders black.
#: `#rrggbb` is the escape hatch for a study that wants one of its own.
NAMED_COLOURS = {"red": (1., 0., 0.), "green": (0., 1., 0.),
                 "blue": (0., 0., 1.), "cyan": (0., 1., 1.),
                 "magenta": (1., 0., 1.), "yellow": (1., 1., 0.),
                 "orange": (1., .5, 0.), "white": (1., 1., 1.),
                 "grey": (.5, .5, .5)}

#: A colour is a name from the table above or six hex digits. Three-digit hex
#: is deliberately not accepted: `#f0f` and `#ff00ff` would be the same colour
#: written two ways in the same config, and the docs can only show one form.
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: The counterstain's colour when a study does not say. Blue is what every
#: composite and every curator page this pipeline has produced has used.
DEFAULT_NUCLEAR = "blue"

#: The positional default, by index into `composite_order`. Index 2 and beyond
#: are deliberately absent: a third marker is measured but not drawn until the
#: study says what colour it is, which is visible rather than silently blended
#: into one of the first two.
_POSITIONAL = ("red", "green")


def parse_colour(value):
    """A colour name or `#rrggbb` as (r, g, b) in 0-1, else ChannelError.

    Raises rather than returning a fallback: a colour that could not be read
    has no safe substitute. Black would draw nothing and look like missing
    data; any real colour would be a marker silently wearing the wrong one,
    which is the bug this whole model exists to remove.
    """
    if not isinstance(value, str):
        raise ChannelError(
            f"a colour must be a name or #rrggbb, not a "
            f"{type(value).__name__} ({value!r}). Names: "
            f"{', '.join(sorted(NAMED_COLOURS))}.")
    text = value.strip()
    if text.lower() in NAMED_COLOURS:
        return NAMED_COLOURS[text.lower()]
    if _HEX_RE.match(text):
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    raise ChannelError(
        f"{value!r} is not a colour this pipeline knows. Use one of "
        f"{', '.join(sorted(NAMED_COLOURS))}, or six hex digits like "
        f"#ff00ff.")


def composite_order(cfg):
    """WHICH markers the composite shows, in order. Not their colours.

    `display.composite`, when a study sets it, otherwise every declared marker
    in declared order. Its order is what the positional colour default reads,
    so a study that wants its second marker in red can say so either way
    round - by reordering here, or by naming the colour in `display.colours`.
    """
    names = marker_names(cfg)
    chosen = ((cfg or {}).get("display") or {}).get("composite")
    if not chosen:
        return list(names)
    if not isinstance(chosen, (list, tuple)):
        raise ChannelError(
            f"`display.composite` must be a list of marker names, not a "
            f"{type(chosen).__name__}.")
    for m in chosen:
        if m not in names:
            raise ChannelError(
                f"`display.composite` names {m!r}, which is not one of "
                f"this study's markers ({', '.join(names) or 'none'}). "
                f"The composite can only show a marker that is measured.")
    return list(chosen)


def _default_planes(cfg):
    """{marker: index into `_POSITIONAL`} - the colourless positional rule.

    Private, and used only by `marker_colours`. It was `marker_planes`, public,
    and the curator's Review pane did not call it - which is exactly how the
    pane came to pick its colours from `p.marker === "AF568"` while the
    composites in the same grid picked theirs from here. One public answer,
    `marker_colours`, so the two cannot disagree again.
    """
    return {m: i for i, m in enumerate(composite_order(cfg)[:len(_POSITIONAL)])}


def marker_colours(cfg):
    """{marker: (r, g, b) in 0-1} - THE source of truth for marker colour.

    Read by the section composites (`04o_section_rgb`) and by the ROI
    curator's Review pane (`04l_roi_curator`), which is the point: the same
    section is drawn in both, and until this existed they decided its colour
    separately and disagreed for every study but one.

    Positional by default - first shown marker red, second green - because
    that is what this pipeline has always produced and the curator's eye is
    trained on it. `display.colours` names a colour per marker and wins.

    A marker with no colour is ABSENT from the map rather than mapped to
    black. Absent is a question the caller has to answer - 04o declines to
    build it and says so, the curator draws it grey and says "no colour set" -
    where black would be a picture of nothing that looks like a failed render.
    """
    out = {m: NAMED_COLOURS[_POSITIONAL[i]]
           for m, i in _default_planes(cfg).items()}
    declared = ((cfg or {}).get("display") or {}).get("colours")
    if declared is None:
        return out
    if not isinstance(declared, dict):
        raise ChannelError(
            f"`display.colours` must be a block of marker -> colour, not a "
            f"{type(declared).__name__}.")
    names = marker_names(cfg)
    for marker, value in declared.items():
        if marker not in names:
            raise ChannelError(
                f"`display.colours` gives {marker!r} a colour, but this study "
                f"does not measure it (its markers are "
                f"{', '.join(names) or 'none'}).")
        out[marker] = parse_colour(value)
    return out


def nuclear_colour(cfg):
    """The counterstain's colour, blue unless `display.nuclear_colour` says."""
    value = ((cfg or {}).get("display") or {}).get("nuclear_colour")
    return parse_colour(value or DEFAULT_NUCLEAR)


def validate_display(cfg):
    """(errors, warnings) for the whole `display` block.

    Takes the WHOLE config, not the block: every rule here is about markers,
    and which source names the markers is itself decided by
    `acquisition.layout`. A validator handed `display` alone could only check
    that the colours are spellable.

    Reported rather than raised, because the reading functions above raise -
    their callers are module-level constants where a traceback takes all 46
    stages down at import - and this is the one place that turns the same
    faults into lines among the others. Every fault, not just the first.

    A marker with no colour is a WARNING. It is a legitimate state - a study
    with three markers and two positional defaults starts there - and the
    stages say so at the point of use rather than refusing to load.
    """
    errors, warnings = [], []
    try:
        shown = composite_order(cfg)
    except ChannelError as exc:
        # Nothing below can be judged without knowing which markers are shown.
        return [str(exc)], warnings

    names = marker_names(cfg)
    declared = ((cfg or {}).get("display") or {}).get("colours")
    if declared is not None and not isinstance(declared, dict):
        errors.append(
            f"`display.colours` must be a block of marker -> colour, not a "
            f"{type(declared).__name__}.")
        declared = None
    # Each entry judged on its own, so a config with three colours misspelled
    # learns all three in one pass instead of one per attempt. marker_colours()
    # raises on the first, which is right for a stage at import and wrong here.
    for marker, value in sorted((declared or {}).items()):
        if marker not in names:
            errors.append(
                f"`display.colours` gives {marker!r} a colour, but this study "
                f"does not measure it (its markers are "
                f"{', '.join(names) or 'none'}).")
            continue
        try:
            parse_colour(value)
        except ChannelError as exc:
            errors.append(f"`display.colours` for {marker!r}: {exc}")
    try:
        nuclear_colour(cfg)
    except ChannelError as exc:
        errors.append(f"`display.nuclear_colour`: {exc}")
    if errors:
        # A colour that could not be read means marker_colours() below would
        # raise, and "which markers end up undrawn" is not a question worth
        # answering about a config that does not parse yet.
        return errors, warnings

    colours = marker_colours(cfg)
    for marker in shown:
        if marker not in colours:
            warnings.append(
                f"marker {marker!r} has no colour, so it is measured but not "
                f"drawn - not in the section composites and grey in the "
                f"curator's Review pane. Give it one with "
                f"`display.colours: {{\"{marker}\": \"magenta\"}}`.")
    return errors, warnings


def resolve(channels, czi_channel_names):
    """{channel name: plane index} for one file.

    `czi_channel_names` is what the file reports, in plane order - the `name`
    of each entry `czi_meta` returns, which may be None.
    """
    names = list(czi_channel_names)

    # Built as a list per name rather than a dict, so a file with two planes
    # under the same name is caught instead of the later one quietly winning.
    # Picking one of two identically-named planes is precisely the plausible
    # wrong answer this module exists to prevent.
    by_name = {}
    for i, n in enumerate(names):
        if n:
            by_name.setdefault(str(n).lower(), []).append(i)

    out = {}
    for chan in channels:
        wanted = str(chan.czi_name).lower() if chan.czi_name else None
        found = by_name.get(wanted, []) if wanted else []
        if len(found) > 1:
            raise ChannelError(
                f"channel {chan.name!r} is declared as {chan.czi_name!r}, and "
                f"this file has {len(found)} planes with that name "
                f"(planes {', '.join(str(i) for i in found)}). Which one is "
                f"meant cannot be guessed; rename them at the microscope, or "
                f"declare this channel by index instead of by name.")
        if len(found) == 1:
            out[chan.name] = found[0]
            continue
        if chan.index is not None and 0 <= chan.index < len(names):
            out[chan.name] = chan.index
            continue
        raise ChannelError(
            f"channel {chan.name!r} is declared as {chan.czi_name!r} "
            f"(plane {chan.index}), and this file has "
            f"{[n for n in names] or 'no named channels'} - "
            f"{len(names)} plane(s). Fix the channel table in Settings, or "
            f"this file is not part of this study.")

    # A file can still have two DECLARED channels land on the same plane, even
    # with no duplicate CZI name in sight: two markers can both fall back to
    # the same index. That is two markers measured off identical pixels -
    # exactly the plausible wrong number this module exists to prevent.
    taken = {}
    for name, plane in out.items():
        if plane in taken:
            raise ChannelError(
                f"channels {taken[plane]!r} and {name!r} both resolve to "
                f"plane {plane} of this file, so they would be measured off "
                f"identical pixels. Give them different czi_name or index "
                f"values in the channel table.")
        taken[plane] = name
    return out


def validate(block, layout):
    """(errors, warnings) for a study's `acquisition` block.

    A multiplex study with no channels declared yet is a WARNING, not an
    error, and so is a paired study that has not named its markers yet. Every
    stage reads config at import, so making either an error would stop the
    whole pipeline loading for a study whose operator has simply not reached
    that part of the settings - and the settings dialog writes defaults that
    produce exactly that state. The stages that need channels or markers ask
    for them at the point of use instead, through require().

    Every other fault is reported, not just the first. This returns a pair of
    lists rather than raising so that someone with three things wrong in
    their channel table learns all three in one pass instead of one per
    attempt - and so that the table itself, not just its content, can be
    judged: a `channels` value that is a string or a number is exactly what
    this function exists to catch, not something it should choke on.

    `block` is the `acquisition` block itself; `block["channels"]` is the
    table. Reading the table out of the block is this function's job, not its
    caller's, and the signature takes nothing else. An earlier version also
    accepted a bare channels list and quietly skipped the
    `acquisition.markers` rules whenever it was given one - which is precisely
    what ls_config passed, so those rules were dead in the only path that
    matters while their unit test went on passing. A function that decides
    which half of its checks to run from its argument's runtime type has no
    way to tell you it took the other branch.
    """
    errors = []
    warnings = []

    if not isinstance(block, dict):
        # Judged, not raised on: the config being validated is not trusted to
        # have the right shape, and that is the whole point of validating it.
        return ([f"`acquisition` must be a block of settings, not a "
                 f"{type(block).__name__}."], warnings)

    declared = block.get("markers")
    malformed = declared is not None and not isinstance(
        declared, (list, tuple))
    if malformed:
        errors.append(
            f"`acquisition.markers` must be a list of marker names, not a "
            f"{type(declared).__name__}. A string would be read one letter "
            f"at a time.")
        declared = None

    if layout == LAYOUT_PAIRED:
        if not declared and not malformed:
            # A WARNING for the same reason an empty multiplex channel table
            # is one, above: every stage validates config at import, so an
            # error would stop the whole pipeline loading for an operator who
            # has simply not named their markers yet - and apply_defaults
            # writes `markers: []`, so that is the state a fresh paired study
            # starts in. require() is where it is fatal, in the one stage that
            # needs the names.
            #
            # Not reported when the value was there but the wrong shape: that
            # is the same fault said twice, and the operator did name their
            # markers - just not as a list.
            warnings.append(
                "`acquisition.markers` does not name this study's markers "
                "yet. A paired study declares no channel table - each scan "
                "carries the nuclear channel plus one marker - so this "
                "list is the only record of what those markers are.")
        seen = set()
        for m in declared or []:
            if not isinstance(m, str):
                # Refused by type, before either rule below runs, because both
                # of them have to be decided on the same value the output path
                # is built from - and that value is `str(m)`. Judging `str(m)`
                # while comparing the raw entry lets `["1", 1]` through as two
                # distinct markers writing to one file, which is exactly what
                # the duplicate rule exists to prevent; `[None]` likewise
                # becomes a directory named `None`. A dict entry is the most
                # likely mistake of all - it is the shape of the
                # `acquisition.channels` table a few lines above this one in
                # the same config file - and it used to raise TypeError here,
                # unhashable, at import of every stage.
                errors.append(
                    f"marker {m!r} in `acquisition.markers` is a "
                    f"{type(m).__name__}, not a name. This is a list of plain "
                    f"marker names - [\"AF568\", \"AF488\"] - not a table of "
                    f"settings like `acquisition.channels`.")
                continue
            if m in seen:
                errors.append(
                    f"marker {m!r} is declared twice in "
                    f"`acquisition.markers`. Output paths are built from "
                    f"these names, so a repeat would have two markers "
                    f"writing to one file.")
            seen.add(m)
            if not NAME_RE.match(m):
                errors.append(
                    f"marker name {m!r} is not usable in a file path. "
                    f"Use letters, digits, spaces, and . _ + - only.")
    elif declared:
        errors.append(
            "`acquisition.markers` applies to `paired` studies only. Under "
            "`multiplex` the channel table already says which channels are "
            "markers, and two sources for one fact is how they drift.")

    table = block.get("channels")
    if table is not None and not isinstance(table, list):
        # `list("abc")` silently succeeds and gives `['a', 'b', 'c']`, which
        # is how a string channel table used to get as far as parse() and
        # blow up on `.get`. Caught here, before entries is even built. `None`
        # is not a fault - it is simply absent, same as an empty list.
        errors.append(f"acquisition.channels must be a list of channels, not "
                      f"a {type(table).__name__}.")
        return errors, warnings
    entries = list(table or [])

    if layout == LAYOUT_PAIRED:
        if entries:
            errors.append(
                "acquisition.channels must be empty for the paired layout: "
                "each scan carries the nuclear channel plus whichever marker "
                "that pass used, so the marker is read per file rather than "
                "declared once.")
        return errors, warnings

    if not entries:
        warnings.append(
            "acquisition.channels is empty. A multiplex study has to say what "
            "its channels are; nothing can be inferred safely from a file.")
        return errors, warnings

    bad_shape = [i for i, e in enumerate(entries) if not isinstance(e, dict)]
    if bad_shape:
        # parse() cannot run on these, and every later message would be noise
        # about a table that has not been read.
        errors.extend(f"acquisition.channels entry {i} is a "
                      f"{type(entries[i]).__name__}, not a block of settings."
                      for i in bad_shape)
        return errors, warnings

    channels = parse(entries)

    seen = set()
    for chan in channels:
        if not chan.name or not NAME_RE.match(str(chan.name)):
            errors.append(
                f"channel name {chan.name!r} is not usable - it becomes a "
                f"folder name and a CSV value. Use letters, digits, spaces, "
                f"and any of _ . + - starting with a letter or digit.")
        elif chan.name in seen:
            errors.append(f"two channels are both called {chan.name!r}.")
        seen.add(chan.name)

        if chan.role not in ROLES:
            errors.append(
                f"channel {chan.name!r} has role {chan.role!r}; it must be one "
                f"of {', '.join(ROLES)}.")

        if not chan.czi_name and chan.index is None:
            errors.append(
                f"channel {chan.name!r} declares neither czi_name nor index, "
                f"so there is no way to find it in a file. Give it the name "
                f"the microscope uses, or the plane it sits on.")

    by_czi = {}
    for chan in channels:
        if chan.czi_name:
            by_czi.setdefault(str(chan.czi_name).lower(), []).append(chan.name)
    for czi_name, names in sorted(by_czi.items()):
        if len(names) > 1:
            errors.append(
                f"channels {' and '.join(repr(n) for n in names)} all declare "
                f"czi_name {czi_name!r}, so they would resolve to the same "
                f"plane.")

    nuclei = [c for c in channels if c.role == NUCLEAR]
    if len(nuclei) > 1:
        errors.append(
            f"{len(nuclei)} channels are marked nuclear "
            f"({', '.join(c.name for c in nuclei)}); there can be at most one.")

    if not markers(channels):
        errors.append(
            "no channel has role 'marker', so there is nothing to measure.")

    for chan in markers(channels):
        if chan.segment not in SEGMENTS:
            errors.append(
                f"channel {chan.name!r} has segment {chan.segment!r}; it must "
                f"be one of {', '.join(SEGMENTS)}.")
        if chan.segment == SEGMENT_NUCLEAR and not nuclei:
            errors.append(
                f"channel {chan.name!r} is segmented on the nuclear channel, "
                f"but this study declares none. Give it segment 'own', or "
                f"declare a nuclear channel.")
        if chan.segment == SEGMENT_OWN:
            if chan.backend not in BACKENDS:
                errors.append(
                    f"channel {chan.name!r} has backend {chan.backend!r}; it "
                    f"must be one of {', '.join(BACKENDS)}.")
            elif chan.backend == "stardist" and not chan.nucleus_shaped:
                errors.append(
                    f"channel {chan.name!r} asks for the stardist backend but "
                    f"is declared not nucleus_shaped. StarDist is a nucleus "
                    f"detector: on cytoplasmic or fibre staining it would "
                    f"under-detect and report no error. Use the threshold "
                    f"backend, or say the objects are nucleus-shaped.")
    return errors, warnings


def require(block, layout):
    """The parsed channel table, or exit saying what is missing.

    Called by a stage that cannot work without channels - or, under paired,
    without the marker list - so the failure lands in that stage rather than
    at import of all forty-five. `block` is the `acquisition` block, same as
    validate().

    Warnings are fatal here, and only here. "Not declared yet" is a warning in
    validate() so that the pipeline still imports for a half-configured study;
    this is the point of use, where a missing channel table or a missing
    marker list is simply the answer to a question the stage has to ask.
    """
    errors, warnings = validate(block, layout)
    table = block.get("channels") if isinstance(block, dict) else None
    if errors or warnings:
        raise SystemExit(
            "this study's acquisition settings are not usable yet:\n  "
            + "\n  ".join(errors + warnings)
            + "\n  Set them in the app under Pipeline > Settings.")
    return parse(table)
