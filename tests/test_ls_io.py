"""ls_io: tmp-then-replace writes, with a retry.

Run:  python tests/test_ls_io.py
"""

import csv
import importlib.util
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location("lsio", os.path.join(SCRIPTS, "ls_io.py"))
IO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IO)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


tmp = tempfile.mkdtemp(prefix="lsio_")
real_replace, real_sleep = IO.os.replace, IO.time.sleep
try:
    p = os.path.join(tmp, "out.csv")
    IO.atomic_write_csv(p, [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], ["a", "b"])
    chk("rows round-trip", read(p), [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}])
    chk("no .tmp left behind", os.path.exists(p + ".tmp"), False)

    IO.atomic_write_csv(p, [], ["a", "b"])
    # newline="" so the CRLF the csv writer emits is not translated away on read.
    with open(p, newline="", encoding="utf-8") as fh:
        chk("empty rows -> header only", fh.read(), "a,b\r\n")

    IO.atomic_write_csv(p, [{"a": 1, "b": 2, "extra": 3}], ["a", "b"])
    chk("extra keys are ignored", read(p), [{"a": "1", "b": "2"}])

    # A dropout: os.replace fails twice, then works. The old file must be intact
    # in between, and the retry must not sleep for real.
    IO.atomic_write_csv(p, [{"a": "old", "b": "old"}], ["a", "b"])
    calls, slept = {"n": 0}, []

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError("volume vanished")
        return real_replace(src, dst)

    IO.os.replace, IO.time.sleep = flaky, slept.append
    try:
        IO.atomic_write_csv(p, [{"a": "new", "b": "new"}], ["a", "b"])
    finally:
        IO.os.replace, IO.time.sleep = real_replace, real_sleep
    chk("retried until the replace went through", calls["n"], 3)
    chk("backoff doubled", slept, [1, 2])
    chk("the new content landed", read(p)[0]["a"], "new")

    # Exhausted attempts propagate, and the previous file is still there.
    IO.atomic_write_csv(p, [{"a": "keep", "b": "keep"}], ["a", "b"])

    def dead(src, dst):
        raise OSError("gone")

    IO.os.replace, IO.time.sleep = dead, lambda s: None
    raised = ""
    try:
        IO.atomic_write_csv(p, [{"a": "lost", "b": "lost"}], ["a", "b"], attempts=2)
    except OSError as exc:
        raised = str(exc)
    finally:
        IO.os.replace, IO.time.sleep = real_replace, real_sleep
    chk("exhausted attempts raise", raised, "gone")
    chk("...and the old file is untouched", read(p)[0]["a"], "keep")

    # atomic_save: a context that hands out the temp path.
    q = os.path.join(tmp, "blob.bin")
    with IO.atomic_save(q) as t:
        chk("temp path is beside the target", os.path.dirname(t), tmp)
        with open(t, "wb") as fh:
            fh.write(b"abc")
        chk("target absent until the block ends", os.path.exists(q), False)
    with open(q, "rb") as fh:
        chk("target written on exit", fh.read(), b"abc")
    chk("temp gone on exit", os.path.exists(t), False)

    boom = ""
    try:
        with IO.atomic_save(q) as t:
            with open(t, "wb") as fh:
                fh.write(b"partial")
            raise ValueError("writer died")
    except ValueError as exc:
        boom = str(exc)
    chk("an exception inside the block propagates", boom, "writer died")
    with open(q, "rb") as fh:
        chk("...and leaves the previous file alone", fh.read(), b"abc")
    chk("...and cleans the temp up", os.path.exists(t), False)
finally:
    IO.os.replace, IO.time.sleep = real_replace, real_sleep
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
