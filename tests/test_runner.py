"""The in-process stage runner, without a window.

Three things the app depends on and nothing else checked:

  * a stage's `\\r` progress lines reach the log as they happen, not as one
    line when the stage ends;
  * `{out_root}` and friends in a stage's argv are expanded, because 04q and
    06b take absolute paths and stages.py cannot know them;
  * the stage sees the runner's config through LS_CONFIG, which is what makes
    the frozen build work at all.

Run:  python tests/test_runner.py
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "app"))

import runner as R                                          # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {got!r}")
    if not ok:
        failures.append(name)


# ---------------------------------------------------------------- _Tee
lines = []
t = R._Tee(lines.append)
t.write("  1/10\r  2/10\r  3/10\n")
chk("carriage-return progress is delivered per update", lines,
    ["  1/10", "  2/10", "  3/10"])
lines.clear()
t.write("half")
chk("a partial line waits", lines, [])
t.write(" line\nnext\r")
chk("...until its terminator, either kind", lines, ["half line", "next"])

# ------------------------------------------------------------- argv
with tempfile.TemporaryDirectory() as tmp:
    out_root = os.path.join(tmp, "out")
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump({"out_root": out_root}, fh)
    scripts = os.path.join(tmp, "scripts")
    os.makedirs(scripts)

    r = R.Runner(scripts, cfg_path)
    chk("LS_CONFIG names the runner's config",
        os.environ.get("LS_CONFIG"), os.path.abspath(cfg_path))
    chk("{out_root} expands", r.expand_argv(["--x", "{out_root}/a.csv"]),
        ["--x", os.path.join(out_root, "a.csv")])
    chk("{repo} is the folder holding config.json",
        r.expand_argv(["{repo}"]), [os.path.dirname(os.path.abspath(cfg_path))])
    chk("plain arguments pass through", r.expand_argv(["--n", "96"]), ["--n", "96"])

    # A stage that reports what it was handed.
    with open(os.path.join(scripts, "99_probe.py"), "w", encoding="utf-8") as fh:
        fh.write("import os, sys\n"
                 "def main():\n"
                 "    print('cfg=' + os.environ.get('LS_CONFIG', ''))\n"
                 "    print('argv=' + '|'.join(sys.argv[1:]))\n"
                 "    for i in range(3): print(f'  {i}/3', end='\\r')\n"
                 "    print()\n")

    class St:
        sid, title, script, cli_only = "probe", "Probe", "99_probe.py", None
        argv = ["--in", "{out_root}/x"]

    got = []
    res = r.run(St(), on_line=got.append)
    chk("the probe stage ran", res.ok, True)
    chk("...and saw the config", "cfg=" + os.path.abspath(cfg_path) in got, True)
    chk("...and the expanded argv",
        "argv=--in|" + os.path.join(out_root, "x") in got, True)
    chk("...and its progress arrived line by line",
        [g for g in got if g.strip().endswith("/3")], ["  0/3", "  1/3", "  2/3"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
