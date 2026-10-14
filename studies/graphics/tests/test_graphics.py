"""The graphics study: every scene at every depth, for drafts 1a and 1b,
compiled C and with the assembly kernels, must draw the same screens as
the host build with gcc (expected/, written by heron graphics expected);
and the kernels must match pixel-at-a-time references (src/selftest.c)."""

import unittest

from heron.studies.c_compiler.cc import driver
from heron.studies.graphics import build, fonts, run

VARIANTS = [("v1a", False, False), ("v1a", True, False), ("v1b", False, False),
            ("v1b", True, False), ("v1b", True, True)]


class Scenes(unittest.TestCase):
    def check(self, isa, kernels, stm, scene):
        img = build.image(isa, kernels, stm)
        for d in range(4):
            msgs = run.check(run.run(img, isa, scene, d), scene, d)
            self.assertEqual(msgs, [], f"{scene} at depth {d}")


def make(isa, kernels, stm, scene):
    return lambda self: self.check(isa, kernels, stm, scene)


for _isa, _k, _s in VARIANTS:
    for _scene in run.SCENES:
        _what = "stm" if _s else "asm" if _k else "c"
        setattr(Scenes, f"test_{_scene}_{_isa}_{_what}", make(_isa, _k, _s, _scene))


class Kernels(unittest.TestCase):
    """src/selftest.c on the simulator, with the assembly kernels: fills,
    blits, expansion, ramps, lines and spans at random places."""

    def test_selftest(self):
        for isa, stm in (("v1a", False), ("v1b", False), ("v1b", True)):
            m = driver.run_image(build.selftest_image(isa, 60, stm), isa, max_cycles=2_000_000_000)
            self.assertIsNone(m.error)
            self.assertEqual(bytes(m.dev.out), b"all good\n", f"{isa}{' stm' if stm else ''}")


class Fonts(unittest.TestCase):
    def test_bitmap_fonts(self):
        for name in ("sans12.txt", "mono12.txt"):
            ascent, descent, glyphs = fonts.read_bitmap(f"{fonts.FONTS}/{name}")
            self.assertEqual(sorted(glyphs), list(range(32, 127)))
            self.assertEqual((ascent, descent), (12, 3))

    def test_ttf(self):
        data = fonts.blobs()["ttf_sans"]
        self.assertEqual(data[:4], b"\0\1\0\0")


if __name__ == "__main__":
    unittest.main()
