"""The test suite: every program in programs/ and tests/lisp/ runs on the
1b simulator, and its output is checked against expected/NAME.txt next to
it, which the reference interpreter wrote (reference.py --write-expected).
"""

import os
import time

from heron.infra.programs import first_diff

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = [os.path.join(HERE, "programs"), os.path.join(HERE, "tests", "lisp")]


def program_paths(names=None):
    out = []
    for d in DIRS:
        if os.path.isdir(d):
            out += sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".lisp"))
    if names:
        out = [p for p in out if os.path.basename(p)[:-5] in names]
    return out


def expected(path):
    p = os.path.join(os.path.dirname(path), "expected", os.path.basename(path)[:-5] + ".txt")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def run_program(path, features=(), compiled=False):
    """Run one program: (Run, problem or None)."""
    from . import machine
    with open(path, "rb") as f:
        text = f.read()
    r = machine.run(text, features, compiled=compiled)
    exp = expected(path)
    if r.error:
        return r, r.error
    if exp is None:
        return r, "no expected output (run reference.py --write-expected)"
    if r.output != exp:
        return r, "output differs from expected"
    return r, None


def run_suite(names=None, features=(), verbose=False, compiled=False):
    paths = program_paths(names)
    if not paths:
        print("no programs found")
        return 1
    failed = 0
    print(f"{'program':<14} {'result':<6} {'instructions':>13} {'cycles':>14} {'GCs':>4} {'secs':>6}")
    for p in paths:
        t = time.time()
        r, problem = run_program(p, features, compiled)
        m = r.machine
        print(f"{os.path.basename(p)[:-5]:<14} {'ok' if problem is None else 'FAIL':<6} "
              f"{m.instructions:>13,} {m.cycles_for('D32-separate'):>14,} "
              f"{r.stats()['gc_count']:>4} {time.time() - t:>6.1f}")
        if problem:
            failed += 1
            print(f"    {problem}")
            exp = expected(p)
            if verbose and exp is not None:
                i = first_diff(r.output, exp)
                print(f"    first difference at byte {i}:")
                print(f"      got:      {r.output[max(0, i - 60):i + 60]!r}")
                print(f"      expected: {exp[max(0, i - 60):i + 60]!r}")
    print(f"\n{len(paths) - failed}/{len(paths)} passed")
    return 1 if failed else 0
