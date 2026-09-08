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
    error. Every stage reads config at import, so making it an error would
    stop the whole pipeline loading for a study whose operator has simply not
    reached the channel table yet - and the settings dialog writes defaults
    that produce exactly that state. The stages that need channels ask for
    them at the point of use instead.

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
            # Not reported when the value was there but the wrong shape: that
            # is the same fault said twice, and the operator did name their
            # markers - just not as a list.
            errors.append(
                "`acquisition.markers` must name this study's markers. A "
                "paired study declares no channel table - each scan "
                "carries the nuclear channel plus one marker - so this "
                "list is the only record of what those markers are.")
        seen = set()
        for m in declared or []:
            if m in seen:
                errors.append(
                    f"marker {m!r} is declared twice in "
                    f"`acquisition.markers`. Output paths are built from "
                    f"these names, so a repeat would have two markers "
                    f"writing to one file.")
            seen.add(m)
            if not NAME_RE.match(str(m)):
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

    Called by a stage that cannot work without channels, so the failure lands
    in that stage rather than at import of all forty-five. `block` is the
    `acquisition` block, same as validate().
    """
    errors, warnings = validate(block, layout)
    table = block.get("channels") if isinstance(block, dict) else None
    if errors or warnings:
        raise SystemExit(
            "this study's channel table is not usable yet:\n  "
            + "\n  ".join(errors + warnings)
            + "\n  Set it in the app under Pipeline > Settings.")
    return parse(table)
