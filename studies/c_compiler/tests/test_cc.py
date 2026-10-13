"""The C compiler: every tests/cc/*.c program, compiled for drafts 1a and
1b, must print what the host's gcc build of it prints
(tests/cc/expected/, written by tests/cc/gen_expected.py)."""

import glob
import os
import unittest

from heron.studies.c_compiler.cc import driver

HERE = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(HERE, "cc")


def programs():
    return sorted(glob.glob(os.path.join(CDIR, "*.c")))


class CPrograms(unittest.TestCase):
    def check(self, path, isa):
        name = os.path.basename(path)[:-2]
        with open(os.path.join(CDIR, "expected", name + ".txt"), "rb") as f:
            expected = f.read()
        text, img, _ = driver.build([path], isa, verify_ir=True)
        m = driver.run_image(img, isa)
        self.assertIsNone(m.error, f"{name} ({isa}): {m.error}")
        self.assertFalse(m.traps, f"{name} ({isa}): traps {m.traps[:3]}")
        out = bytes(m.dev.out)
        if out != expected:
            k = next((i for i, (a, b) in enumerate(zip(out, expected)) if a != b), min(len(out), len(expected)))
            self.fail(f"{name} ({isa}): output differs at byte {k}:\n"
                      f"  got      {out[max(0, k - 60):k + 60]!r}\n"
                      f"  expected {expected[max(0, k - 60):k + 60]!r}")


def make(path, isa):
    return lambda self: self.check(path, isa)


for _p in programs():
    for _isa in ("v1a", "v1b"):
        setattr(CPrograms, f"test_{os.path.basename(_p)[:-2]}_{_isa}", make(_p, _isa))


if __name__ == "__main__":
    unittest.main()
