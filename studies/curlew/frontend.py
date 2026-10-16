"""The front end: a program's text (and the prelude's) to the checked,
annotated kernel (typecheck.Program)."""

import os

from . import derive, parse, sugar, typecheck

HERE = os.path.dirname(os.path.abspath(__file__))
PRELUDE = os.path.join(HERE, "prelude.cw")


def prelude_text():
    with open(PRELUDE) as f:
        return f.read()


def check(text, prelude=None):
    """Parse and check a program (str) with the prelude: a Program."""
    if prelude is None:
        prelude = prelude_text()
    pd = parse.parse(prelude)
    qd = parse.parse(text)
    fix = sugar.fixities(pd + qd)
    dd = parse.parse(derive.derive(pd + qd, fix))
    pk = sugar.kernel(pd + dd, fix)
    qk = sugar.kernel(qd, fix)
    return typecheck.Checker().program(pk, qk)
