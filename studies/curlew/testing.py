"""The programs and tests, against their expected output.

A program in programs/ or a test in tests/cw/ may name its console input
in its first lines: `-- input: FILE`, relative to the program. Its
expected output is expected/NAME.txt next to it, which the reference
interpreter writes (reference.py --write-expected).
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = os.path.join(HERE, "programs")
TESTS = os.path.join(HERE, "tests", "cw")
INPUT_RE = re.compile(r"^--\s*input:\s*(\S+)", re.M)


class Program:
    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.dir = os.path.dirname(path)
        with open(path) as f:
            self.text = f.read()
        m = INPUT_RE.search(self.text[:400])
        self.input = b""
        if m:
            with open(os.path.join(self.dir, m.group(1)), "rb") as f:
                self.input = f.read()
        self.expected_path = os.path.join(self.dir, "expected", self.name + ".txt")

    @property
    def expected(self):
        if not os.path.exists(self.expected_path):
            return None
        with open(self.expected_path, "rb") as f:
            return f.read()


def programs(names=None, tests=True):
    """The benchmark programs (and the tests), by name."""
    out = []
    dirs = [PROGRAMS] + ([TESTS] if tests else [])
    for d in dirs:
        for f in sorted(os.listdir(d)):
            if f.endswith(".cw"):
                p = Program(os.path.join(d, f))
                if not names or p.name in names:
                    out.append(p)
    return out


def write_expected():
    from . import reference
    for p in programs():
        out = reference.run(p.text, p.input)
        os.makedirs(os.path.dirname(p.expected_path), exist_ok=True)
        with open(p.expected_path, "wb") as f:
            f.write(out)
        print(f"wrote {os.path.relpath(p.expected_path)}")
    return 0


def diff(out, expected):
    k = next((i for i, (a, b) in enumerate(zip(out, expected)) if a != b), min(len(out), len(expected)))
    return (f"output differs at byte {k}:\n"
            f"  got      {out[max(0, k - 60):k + 60]!r}\n"
            f"  expected {expected[max(0, k - 60):k + 60]!r}")


def run_suite(names=(), features=(), verbose=False, tests=True):
    """Run programs on the machine against their expected output: 0 if all
    pass."""
    from . import machine
    from .lexer import CurlewError
    bad = 0
    for p in programs(names, tests):
        exp = p.expected
        if exp is None:
            print(f"{p.name}: no expected output (reference.py --write-expected)")
            bad += 1
            continue
        try:
            r = machine.run(p.text, p.input, features)
        except CurlewError as e:
            print(f"{p.name}: {e}")
            bad += 1
            continue
        m = r.machine
        ok = r.error is None and r.output == exp
        if verbose or not ok:
            status = "ok" if ok else "FAIL"
            print(f"{p.name}: {status}, {m.instructions:,} instructions, "
                  f"{m.cycles_for(machine.CONFIG):,} cycles")
        if not ok:
            bad += 1
            if r.error:
                print(f"  {r.error}")
            if r.output != exp:
                print("  " + diff(r.output, exp))
    n = len(programs(names, tests))
    print(f"{n - bad} of {n} passed" + (f" ({', '.join(features)})" if features else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run_suite(sys.argv[1:]))
