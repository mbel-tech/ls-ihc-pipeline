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


def resolve(channels, czi_channel_names):
    """{channel name: plane index} for one file.

    `czi_channel_names` is what the file reports, in plane order - the `name`
    of each entry `czi_meta` returns, which may be None.
    """
    names = list(czi_channel_names)
    lowered = {str(n).lower(): i for i, n in enumerate(names) if n}
    out = {}
    for chan in channels:
        if chan.czi_name and str(chan.czi_name).lower() in lowered:
            out[chan.name] = lowered[str(chan.czi_name).lower()]
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
    return out


def validate(block, layout):
    """Errors in a declared channel table. [] when it is usable.

    Every fault is reported, not just the first. This returns a list rather
    than raising so that someone with three things wrong in their channel
    table learns all three in one pass instead of one per attempt.
    """
    errors = []
    entries = list(block or [])

    if layout == "paired":
        if entries:
            errors.append(
                "acquisition.channels must be empty for the paired layout: "
                "each scan carries the nuclear channel plus whichever marker "
                "that pass used, so the marker is read per file rather than "
                "declared once.")
        return errors

    if not entries:
        errors.append(
            "acquisition.channels is empty. A multiplex study has to say what "
            "its channels are; nothing can be inferred safely from a file.")
        return errors

    channels = parse(entries)

    seen = set()
    for chan in channels:
        if not chan.name or not NAME_RE.match(str(chan.name)):
            errors.append(
                f"channel name {chan.name!r} is not usable - it becomes a "
                f"folder name and a CSV value.")
        elif chan.name in seen:
            errors.append(f"two channels are both called {chan.name!r}.")
        seen.add(chan.name)

        if chan.role not in ROLES:
            errors.append(
                f"channel {chan.name!r} has role {chan.role!r}; it must be one "
                f"of {', '.join(ROLES)}.")

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
    return errors
