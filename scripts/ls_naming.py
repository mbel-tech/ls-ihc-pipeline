"""Reading a slide filename, and building the key everything else joins on.

One grammar, in the study config, used by both the manifest and the app's Add
slides screen. It used to be a constant in `00_manifest.py` with `LS` written
into it, copied into `app/slides.py` as a fallback, and re-derived twice more
downstream from the scene uid.

Two rules this module exists to hold.

**A filename that does not match is reported, never skipped.** An unreadable
name that is silently dropped is a section that never reaches any stage and
nothing ever says so. `parse_name` returns None and the caller must say so.

**The scene uid's shape is fixed, its contents are not.** The uid is the
primary key of every table on disk, a filename component, and a key in the
curation JSON that holds the operator's manual work. Making its shape
configurable would let a user orphan every prior result by editing a string.
Only the values come from the study's own grammar:

    subject + slide + replicate ->  LS105_s10a_sc03
    subject + slide             ->  LS105_s10_sc03
    subject alone               ->  LS105_sc03

For the LS grammar that is byte-for-byte what 00_manifest built before.
"""

import os
import re

#: Named groups with a meaning here. Any other named group in a study's pattern
#: is carried through as an extra column rather than being ignored.
RESERVED = ("subject", "slide", "replicate")

#: The inverse of scene_uid(). Subject cannot contain "_" - parse_name refuses
#: one that does - so the first underscore is unambiguous.
UID_RE = re.compile(
    r"^(?P<subject>[^_]+)"
    r"(?:_s(?P<slide>\d+)(?P<replicate>[A-Za-z]*))?"
    r"_sc(?P<scene>\d+)$")


class NamingError(Exception):
    """The study's grammar is unusable, as opposed to a file not matching it."""


def compile_pattern(spec):
    """Compile a study's `slide_naming` block into a regex.

    `spec` is the config block, or a bare pattern string.
    """
    if isinstance(spec, str):
        spec = {"pattern": spec}
    spec = spec or {}
    pattern = spec.get("pattern")
    if not pattern:
        raise NamingError(
            "this study has no slide_naming.pattern, so a filename cannot be "
            "read.\n  Set one in the app under Pipeline > Settings, or copy "
            "the example from config.example.json.")
    flags = re.IGNORECASE if spec.get("case_insensitive") else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise NamingError(f"slide_naming.pattern is not a valid regex: {exc}")
    if "subject" not in compiled.groupindex:
        raise NamingError(
            "slide_naming.pattern has no (?P<subject>...) group. That group is "
            "the key every later table joins on, so it is not optional.")
    return compiled


def extra_groups(pattern):
    """The pattern's own named groups, in pattern order, minus the reserved."""
    return [name for name, _ in
            sorted(pattern.groupindex.items(), key=lambda kv: kv[1])
            if name not in RESERVED]


def parse_name(filename, pattern):
    """{subject, slide, replicate, name_suffix, extras} or None.

    `slide` is an int when the pattern captured digits, else None. A subject
    containing "_" is REFUSED rather than parsed: the scene uid puts the
    subject first and separates on "_", and several readers take the subject
    back off a uid, so an underscore there would hand them half an id without
    any error.
    """
    m = pattern.match(os.path.basename(filename))
    if not m:
        return None
    groups = m.groupdict()

    subject = (groups.get("subject") or "").strip()
    if not subject or "_" in subject:
        return None

    slide = groups.get("slide")
    extras = {name: (groups.get(name) or "") for name in extra_groups(pattern)}
    return {
        "subject": subject,
        "slide": int(slide) if slide and slide.isdigit() else None,
        "replicate": groups.get("replicate") or "",
        # The old grammar's trailing "-" and "_A568" concatenated, in the order
        # the pattern captured them.
        "name_suffix": "".join(extras[k] for k in extra_groups(pattern)),
        "extras": extras,
    }


def scene_uid(parsed, scene_index):
    """The pipeline's primary key. Shape fixed, values from `parsed`."""
    parts = [parsed["subject"]]
    if parsed.get("slide") is not None:
        parts.append(f"s{parsed['slide']:02d}{parsed.get('replicate') or ''}")
    parts.append(f"sc{int(scene_index):02d}")
    uid = "_".join(parts)
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9.\-]*(_[A-Za-z0-9.\-]+)*$", uid):
        raise NamingError(
            f"the scene uid {uid!r} is not usable as a filename or a join key. "
            f"Check slide_naming.pattern - the subject group is capturing "
            f"something it should not.")
    return uid


def split_uid(uid):
    """The inverse of scene_uid(), or None for anything this did not build.

    Replaces the second grammar 06d kept for the same job, which had `LS`
    written into it and so could only read one study's uids.
    """
    m = UID_RE.match(uid or "")
    if not m:
        return None
    slide = m.group("slide")
    out = {
        "subject": m.group("subject"),
        "slide": int(slide) if slide else None,
        "replicate": m.group("replicate") or "",
        "scene": int(m.group("scene")),
    }
    # What 06d groups a slide's sections by.
    out["slide_key"] = (uid.rsplit("_sc", 1)[0] if slide is not None
                        else out["subject"])
    return out


def subject_of(uid):
    """The subject a scene uid belongs to.

    Six places did `uid.split("_")[0]` for this. That is right only while a
    subject cannot contain "_" - which parse_name now enforces, but which
    nothing enforced when those lines were written. Going through split_uid
    means the rule lives in one place, and an id this module did not build
    still degrades to the old behaviour rather than raising.
    """
    parsed = split_uid(uid)
    return parsed["subject"] if parsed else str(uid).split("_")[0]


_CHUNKS = re.compile(r"(\d+)")


def natural_key(text):
    """Sort key for an id, with no grammar assumed.

    Replaces `int(a[2:])` in 02_pair_passes, which raises ValueError on any id
    that is not two letters and digits, and `int(a[2:]) if a[2:].isdigit()
    else 0` in app/slides, which sorted every other shape into one bucket.
    LS7 < LS22 < LS120, and Fish-3 < Fish-12, and A1 < B1.
    """
    return tuple((1, int(part)) if part.isdigit() else (0, part.lower())
                 for part in _CHUNKS.split(str(text)) if part != "")
