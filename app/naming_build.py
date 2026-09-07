"""Building a filename pattern from marked-up spans of one real filename.

Kept apart from the Qt widget for the same reason `slides.py` is: the part with
the judgement in it must be testable without opening a window.

The operator marks which run of characters is the subject, which is the slide,
which is the replicate. Everything they did NOT mark is escaped literally, so a
generated pattern can never be looser than the example it came from - the text
the user typed is never used as regex syntax.

Two things this file exists to prevent.

**A pattern that matches the example and nothing else.** A generated pattern is
always previewed against every filename that was scanned, and the count of what
did not match is part of the result rather than something to notice later.

**A pattern with no defined split.** `(?P<a>[A-Za-z0-9]+)(?P<b>[A-Za-z0-9]+)`
has no answer to where a stops and b begins - the regex engine picks one, and
whichever it picks is not a decision anyone made. Adjacent spans of the same
character class are detected and the left one is pinned to the width it has in
the example, with a sentence saying so.
"""

import re

#: Group names the pipeline gives a meaning to. Anything else the operator adds
#: rides along as an extra column.
SUBJECT, SLIDE, REPLICATE = "subject", "slide", "replicate"
ROLES = (SUBJECT, SLIDE, REPLICATE)


class Span:
    """One marked run of the example filename."""

    def __init__(self, start, end, name, optional=False):
        self.start = int(start)
        self.end = int(end)
        self.name = str(name)
        self.optional = bool(optional)

    def text(self, example):
        return example[self.start:self.end]

    def __repr__(self):
        return f"<Span {self.name} {self.start}:{self.end}>"


def _kinds(text):
    """Which character families a run is made of."""
    out = set()
    for ch in text:
        if ch.isdigit():
            out.add("digit")
        elif ch.isascii() and ch.isalpha():
            out.add("alpha")
        else:
            out.add("other")
    return out


def infer_body(text):
    """A regex body for a marked run, inferred from the run itself.

    Never from anything the user typed: the shape comes from the characters
    that are actually there, so the pattern cannot be wider than the example.
    """
    if not text:
        return ""
    kinds = _kinds(text)
    if kinds == {"digit"}:
        return r"\d+"
    if kinds == {"alpha"}:
        return r"[A-Za-z]+"
    if kinds == {"alpha", "digit"} and re.fullmatch(r"[A-Za-z]+\d+", text):
        return r"[A-Za-z]+\d+"
    # Anything else: the literal set of characters present, which is narrow and
    # predictable even when it is not pretty.
    chars = "".join(sorted(set(text)))
    return "[" + re.escape(chars).replace("]", r"\]").replace("^", r"\^") + "]+"


def _pin(body, width):
    """The same body, fixed to `width` characters instead of one-or-more."""
    if body.endswith("+"):
        return f"{body[:-1]}{{{width}}}"
    return body


def _open_kinds(body):
    """What a body can consume, for the adjacency check."""
    kinds = set()
    if r"\d" in body:
        kinds.add("digit")
    if "A-Za-z" in body:
        kinds.add("alpha")
    if body.startswith("[") and not kinds:
        kinds.add("other")
    return kinds


def spans_to_pattern(example, spans, ignore_case=False):
    """(pattern, warnings) for the marked-up example.

    Spans must not overlap. Everything outside them is escaped literally,
    including the extension, so the pattern is exactly as specific as the
    example was.
    """
    spans = sorted(spans, key=lambda s: s.start)
    for a, b in zip(spans, spans[1:]):
        if b.start < a.end:
            raise ValueError(f"{a.name} and {b.name} overlap")
    if not any(s.name == SUBJECT for s in spans):
        raise ValueError("one span must be the subject")

    bodies = [infer_body(s.text(example)) for s in spans]
    warnings = []

    # Adjacent spans of the same family have no defined split, so pin the left
    # one to the width it has here and say why.
    for i, (a, b) in enumerate(zip(spans, spans[1:])):
        if a.end != b.start:
            continue
        if _open_kinds(bodies[i]) & _open_kinds(bodies[i + 1]):
            width = a.end - a.start
            bodies[i] = _pin(bodies[i], width)
            warnings.append(
                f"{a.name} is fixed at {width} character"
                f"{'s' if width != 1 else ''} here, because nothing separates "
                f"it from {b.name}. Leave a character unmarked between them to "
                f"lift that.")

    out, cursor = ["^"], 0
    for span, body in zip(spans, bodies):
        out.append(re.escape(example[cursor:span.start]))
        group = f"(?P<{span.name}>{body})"
        out.append(f"(?:{group})?" if span.optional else group)
        cursor = span.end
    out.append(re.escape(example[cursor:]))
    out.append("$")
    pattern = "".join(out)

    try:
        re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:                                 # pragma: no cover
        raise ValueError(f"the generated pattern is not valid: {exc}")
    return pattern, warnings


def preview(names, pattern, ignore_case=False):
    """How a pattern reads a whole list of filenames.

    Returns rows (failures first, because those are what need looking at),
    counts, and the problems that must be fixed before it can be saved.
    """
    result = {"rows": [], "matched": 0, "failed": 0, "problems": [],
              "pattern": pattern}
    try:
        compiled = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        result["problems"].append(f"the pattern is not valid: {exc}")
        return result

    if SUBJECT not in compiled.groupindex:
        result["problems"].append(
            "the pattern has no (?P<subject>...) group. That group is the key "
            "every later table joins on, so it is not optional.")
        return result

    extras = [n for n in compiled.groupindex if n not in ROLES]
    seen = {}
    for name in names:
        m = compiled.match(name)
        if not m:
            result["rows"].append({"file": name, "ok": False, "why": "no match"})
            result["failed"] += 1
            continue
        g = m.groupdict()
        subject = g.get(SUBJECT) or ""
        row = {"file": name, "ok": True, SUBJECT: subject,
               SLIDE: g.get(SLIDE) or "", REPLICATE: g.get(REPLICATE) or "",
               "extras": {k: (g.get(k) or "") for k in extras}}
        if not subject:
            row["ok"], row["why"] = False, "subject is empty"
            result["failed"] += 1
        elif "_" in subject:
            row["ok"], row["why"] = False, "subject contains '_'"
            result["failed"] += 1
        else:
            result["matched"] += 1
            key = (subject, row[SLIDE], row[REPLICATE])
            seen.setdefault(key, []).append(name)
        result["rows"].append(row)

    result["rows"].sort(key=lambda r: (r["ok"], r["file"]))

    if not names:
        result["problems"].append("no files to check the pattern against.")
    elif result["matched"] == 0:
        result["problems"].append(
            "the pattern matches none of these files.")
    if any(r.get("why") == "subject contains '_'" for r in result["rows"]):
        result["problems"].append(
            "the subject captures an underscore. The scene uid separates on "
            "'_', and several stages take the subject back off a uid, so one "
            "there would hand them half an id.")

    # Two files reading as the same section is not a naming style, it is a
    # collision: every measurement from one would overwrite the other.
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    if clashes:
        first = next(iter(clashes.values()))
        result["problems"].append(
            f"{len(clashes)} group(s) of files read as the same section, "
            f"e.g. {', '.join(first[:3])}. Mark another part of the name so "
            f"they differ.")
    result["clashes"] = clashes
    return result


def can_save(result, accept_failures=False):
    """(bool, reason). A pattern is savable only when nothing is invisible."""
    if result["problems"]:
        return False, result["problems"][0]
    if result["failed"] and not accept_failures:
        return False, (f"{result['failed']} file(s) do not match. A file the "
                       f"pattern misses never reaches any stage and nothing "
                       f"says so - fix the pattern, or tick the box to leave "
                       f"them out deliberately.")
    return True, ""


def summary(result):
    total = result["matched"] + result["failed"]
    if not total:
        return "nothing scanned"
    if not result["failed"]:
        return f"all {total} filenames matched"
    return f"{result['matched']} of {total} matched — {result['failed']} did not"
