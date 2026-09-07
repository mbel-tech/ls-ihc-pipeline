"""config.example.json is generated, so the drift it used to guard is gone.

This suite used to assert that every key path in `config.json` also existed in
`config.example.json`, because the two drifted the same way every time: a key
was added to the working config while a stage was being written, the stage read
it through `.get(...)`, and the template never got it. Nothing failed loudly
afterwards - the stage fell back to a default that was wrong for the new dataset
and said nothing about it.

The template is now generated from `SPEC` in `scripts/ls_config.py`, so it
cannot fall behind: adding a key to the spec adds it to the template, and the
check is a byte comparison rather than a key-path comparison.

That leaves a different drift, and it points the other way. A study config can
still carry a key that nothing has ever read - a typo, or a setting whose owner
expected it to do something. Keys deliberately removed from the schema are
listed in `ls_config.RETIRED` and reported as removed, with the reason. Anything
left over after that is the real fault, and is what this suite now checks.

Run:  python tests/test_config_example.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import ls_config as C                                       # noqa: E402

REAL = os.path.join(REPO, "config.json")
EXAMPLE = os.path.join(REPO, "config.example.json")

failures = []


def chk(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:62} {got!r}")
    if not ok:
        failures.append(name)


# --------------------------------------------------------------------------
print("--- the template is generated, not maintained ---")

generated = C.example_text()
chk("generation is deterministic", C.example_text() == generated, True)

with open(EXAMPLE, encoding="utf-8") as fh:
    committed = fh.read()
chk("the committed template is what the spec generates",
    committed == generated, True)
if committed != generated:
    print("     run: python scripts/ls_config.py --write-example")
    print(f"     committed {len(committed)} bytes, generated {len(generated)}")

chk("it parses as JSON", isinstance(json.loads(committed), dict), True)

example = json.loads(committed)
chk("every required key is present in the template",
    [k.path for k in C.SPEC
     if k.required and not C._get(example, k.parts)[0]], [])
chk("every materialise key is a literal, not left to a default",
    [k.path for k in C.SPEC
     if k.materialise and not C._get(example, k.parts)[0]], [])

errors, _ = C.validate(example, EXAMPLE)
placeholder = [e for e in errors if "<" in e]
chk("the template validates apart from its placeholders",
    [e for e in errors if e not in placeholder], [])

# --------------------------------------------------------------------------
print()
print("--- retired keys are named as retired, not as typos ---")

chk("every retired key has a reason",
    [k for k, why in C.RETIRED.items() if not why], [])
chk("no key is both retired and in the spec",
    sorted(set(C.RETIRED) & {k.path for k in C.SPEC}), [])

stale = dict(json.loads(committed))
stale["flatfield"] = {"tile_sample_per_channel": 2000}
stale["what_is_this"] = 3
_, warns = C.validate(stale, "stale.json")
chk("a retired key says it was removed, and why",
    any("was removed in schema" in w and "flatfield" in w for w in warns), True)
chk("a key nobody has heard of does not claim to have been removed",
    any("what_is_this" in w and "was removed" not in w for w in warns), True)
chk("unexpected_keys reports only the genuine unknown",
    C.unexpected_keys(stale), ["what_is_this"])

# --------------------------------------------------------------------------
print()
print("--- the live config, if this checkout has one ---")

if not os.path.exists(REAL):
    print("SKIP no config.json in this checkout")
else:
    with open(REAL, encoding="utf-8") as fh:
        real = json.load(fh)
    unexpected = C.unexpected_keys(real)
    chk("config.json carries no key the spec has never heard of",
        unexpected, [])
    if unexpected:
        print("     Either add them to SPEC, or to RETIRED with the reason.")
    retired_present = [p for p in C._unknown_paths(real) if p in C.RETIRED]
    print(f"note: {len(retired_present)} retired key(s) still in config.json: "
          + ", ".join(retired_present))

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
