"""config.example.json must not fall behind config.json.

`config.json` is gitignored - it holds machine-specific absolute paths - so
`config.example.json` is the only copy a fresh dataset ever sees. The two drift
the same way every time: a key is added to the working config while a stage is
being written, the stage reads it through `.get(...)`, and the template never
gets it. Nothing fails loudly afterwards. The stage falls back to a default that
is wrong for the new dataset and says nothing about it - `atlas_plate_set.dir`
falling back to `plates` while the landmarks were made against `plates_final`
is exactly that, and plate ids collide between the sets, so the mismatch shows
up as a wrong image rather than as an error.

So: every key path in `config.json` must also exist in `config.example.json`.
Values are not compared - the template carries placeholders on purpose - only
the shape. Keys starting with `_` are documentation and are skipped, though the
template is expected to carry its own.

Skipped, not failed, when there is no config.json: on a fresh clone there is
nothing to compare against.

Run:  python tests/test_config_example.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REAL = os.path.join(REPO, "config.json")
EXAMPLE = os.path.join(REPO, "config.example.json")


def load(path):
    """Parse a config, reporting the file and position on a syntax error."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FAIL {os.path.basename(path)} is not valid JSON: {exc}")


def key_paths(node, prefix=""):
    """Dotted paths of every non-underscore key, recursing into dicts only.

    Lists are values here, not structure: `atlas_scope.regions_to_add` differing
    between the two files is the template being generic, not drift.
    """
    out = []
    if not isinstance(node, dict):
        return out
    for k, v in node.items():
        if k.startswith("_"):
            continue
        path = f"{prefix}.{k}" if prefix else k
        out.append(path)
        out.extend(key_paths(v, path))
    return out


def main():
    if not os.path.exists(REAL):
        print("SKIP no config.json in this checkout - nothing to compare against")
        return 0

    real = load(REAL)
    example = load(EXAMPLE)
    print("both files parse as JSON")

    have = set(key_paths(example))
    want = key_paths(real)
    missing = [p for p in want if p not in have]

    extra = [p for p in sorted(have) if p not in set(want)]
    if extra:
        print(f"note: {len(extra)} key path(s) only in config.example.json: "
              + ", ".join(extra))

    if missing:
        print(f"FAIL {len(missing)} key path(s) in config.json are missing from "
              "config.example.json:")
        for p in missing:
            print(f"  {p}")
        print("Add them to the template with a generic placeholder and a _note.")
        return 1

    print(f"PASS all {len(want)} key paths in config.json exist in config.example.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
