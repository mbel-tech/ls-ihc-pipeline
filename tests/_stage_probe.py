"""Import every numbered stage under a given config and dump what it derived.

Not a test. A measuring instrument two tests use.

Stages read config at import and turn it into module-level constants - paths,
thresholds, indices - and that is where a config refactor can go wrong without
anything failing: a key renamed by accident falls back to a default, a stage
writes beside the real data instead of into it, and nothing says so. Comparing
those constants before and after a change catches exactly that, and it does it
at import, without running a stage. That matters here: stage scripts overwrite
`out_root`, so running one is never a safe test.

Paths are reported with the config's own roots substituted out - `{out_root}`,
`{source_dir}`, `{config}`, `{repo}` - so two runs under two different configs
produce identical output when the stages are behaving. A stage that hardcoded a
path shows an absolute one and stands out immediately.

Run:  python tests/_stage_probe.py <config.json> <out.json>
"""

import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")

#: Constants that are expected to differ between two configs - they ARE the
#: config location. Everything else must match.
EXPECTED_TO_DIFFER = {"CONFIG_PATH", "CONFIG", "STUDY_DIR"}


def stage_files():
    """Every numbered stage script, in pipeline order."""
    return sorted(f for f in os.listdir(SCRIPTS)
                  if f.endswith(".py") and f[0].isdigit())


def _norm(text, subs):
    """A path with the config's roots replaced by tokens, separators unified."""
    out = text.replace("\\", "/")
    for real, token in subs:
        if real:
            out = re.sub(re.escape(real), token, out, flags=re.IGNORECASE)
    return out


#: Above this, a string is not a setting - it is a payload. The curator stages
#: hold entire HTML pages in a module constant, which would bury the diff and,
#: because 04l embeds the group key into its page, would also write the
#: unblinding key into a file committed to a public repo. Hashed instead: a
#: change is still caught, the content never leaves the machine.
MAX_STR = 500


def _flatten(value, subs):
    """A JSON-safe, machine-independent view of one module constant.

    Only the shapes a config can produce are kept. A numpy array or a function
    is not a derived setting and would only add noise to the diff.
    """
    if isinstance(value, str):
        if len(value) > MAX_STR:
            digest = hashlib.sha256(_norm(value, subs).encode("utf-8"))
            return {"sha256": digest.hexdigest()[:16], "len": len(value)}
        return _norm(value, subs)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, re.Pattern):
        # The pattern text and the flags both change behaviour, so both are
        # part of the constant.
        return {"regex": _norm(value.pattern, subs), "flags": int(value.flags)}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_flatten(v, subs) for v in
                 (sorted(value, key=repr) if isinstance(value, (set, frozenset))
                  else value)]
        if any(i is _SKIP for i in items):
            return _SKIP
        return items
    return _SKIP


_SKIP = object()


def collect(mod, subs):
    """The module-level UPPERCASE constants of one stage."""
    out = {}
    for name in dir(mod):
        if not name.isupper() or name.startswith("_"):
            continue
        flat = _flatten(getattr(mod, name), subs)
        if flat is not _SKIP:
            out[name] = flat
    return out


def probe(config_path):
    """{script: {constant: value}} plus a `_failed` map of import errors."""
    config_path = os.path.abspath(config_path)
    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    # Every path the config itself supplies, so a constant derived from one is
    # reported by role rather than by location. Longest first, so a root nested
    # inside another cannot be masked by it.
    subs = sorted(
        [(str(cfg.get(key) or "").replace("\\", "/"), "{" + key + "}")
         for key in ("out_root", "source_dir", "atlas_pdf", "export_dir")]
        + [(config_path.replace("\\", "/"), "{config}"),
           (REPO.replace("\\", "/"), "{repo}")],
        key=lambda pair: len(pair[0]), reverse=True)

    os.environ["LS_CONFIG"] = config_path
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)

    result, failed = {}, {}
    for script in stage_files():
        name = "probe_" + script[:-3]
        try:
            spec = importlib.util.spec_from_file_location(
                name, os.path.join(SCRIPTS, script))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except BaseException as exc:                        # noqa: BLE001
            # A stage that will not import is reported, never skipped. The
            # check this replaces skipped nine stages silently.
            failed[script] = f"{type(exc).__name__}: {exc}"
            continue
        result[script] = collect(mod, subs)
    result["_failed"] = failed
    return result


def diff(before, after, ignore=EXPECTED_TO_DIFFER):
    """[(script, constant, before, after)] for everything that moved."""
    out = []
    for script in sorted(set(before) | set(after)):
        if script == "_failed":
            continue
        b, a = before.get(script), after.get(script)
        if b is None or a is None:
            out.append((script, "<module>",
                        "present" if b is not None else "absent",
                        "present" if a is not None else "absent"))
            continue
        for const in sorted(set(b) | set(a)):
            if const in ignore:
                continue
            bv, av = b.get(const, "<absent>"), a.get(const, "<absent>")
            if bv != av:
                out.append((script, const, bv, av))
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    result = probe(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
        fh.write("\n")
    ok = len(result) - 1
    print(f"probed {ok} stage(s), {len(result['_failed'])} failed to import")
    for script, why in sorted(result["_failed"].items()):
        print(f"  {script}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
