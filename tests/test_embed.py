"""JSON embedded in a <script> block: escaped, and substituted in one pass.

Run:  python tests/test_embed.py
"""

import importlib.util
import os

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


chk("plain values are plain JSON", IO.embed({"a": 1, "b": [True, None]}), '{"a": 1, "b": [true, null]}')
chk("a closing tag cannot end the block", IO.embed("x</script>y"), '"x<\\/script>y"')
chk("a comment opener is neutralised", IO.embed("<!-- z"), '"<\\!-- z"')
chk("other slashes are left alone", IO.embed("a/b"), '"a/b"')
chk("an int embeds as itself", IO.embed(170), "170")

page = IO.fill("<script>const A = __A__; const B = __B__; const N = __N__;</script>",
               {"__A__": {"s": "</script><!--"}, "__B__": ["__A__", "__N__"], "__N__": 7})
chk("the closing tag is escaped in place", "</script><!--" in page, False)
chk("placeholders inside a VALUE are not substituted", '["__A__", "__N__"]' in page, True)
chk("every placeholder is filled", "__N__;" in page, False)
chk("the number lands", "const N = 7;" in page, True)

# A placeholder the template does not carry is a programming error, not a no-op.
boom = ""
try:
    IO.fill("<script>__A__</script>", {"__A__": 1, "__ZZ__": 2})
except KeyError as exc:
    boom = str(exc)
chk("an unused placeholder raises", "__ZZ__" in boom, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
