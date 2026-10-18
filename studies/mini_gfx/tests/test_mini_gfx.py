"""The library against its references in every format and variant, the
formats against the video's decoder, and every program running its
script without a trap."""

import unittest

from heron.studies.mini_gfx import check, programs


class Library(unittest.TestCase):
    def test_selftest(self):
        for v in ("c", "asm", "blk"):
            ok, last = check.selftest(v)
            self.assertTrue(ok, f"{v}: {last}")

    def test_modes(self):
        for layout, mode, f1, bad in check.modes():
            self.assertEqual(bad, 0, f"{layout} M{mode} F1={f1}")


class Programs(unittest.TestCase):
    def test_programs_run(self):
        for name, p in programs.all_programs().items():
            if name.startswith("check/"):
                continue
            with self.subTest(name):
                r = p.run(shots_dir=None)
                self.assertIsNone(r.trap, f"{name}: {r.trap}")
