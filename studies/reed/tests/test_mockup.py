"""The 3D mockup's placement: every package once, inside the area, no two
overlapping."""

import unittest

from studies.reed import mockup


class TestMockup(unittest.TestCase):
    def test_placement(self):
        for name, b in mockup.layout().items():
            chips = b["chips"]
            for c in chips:
                self.assertGreaterEqual(c["x"] - c["L"] / 2, mockup.X0 - 0.01, c["ref"])
                self.assertLessEqual(c["x"] + c["L"] / 2, mockup.X1 + 0.01, c["ref"])
                self.assertGreaterEqual(c["y"] - c["W"] / 2, mockup.Y0, c["ref"])
                self.assertLessEqual(c["y"] + c["W"] / 2, mockup.Y1, c["ref"])
            for i, a in enumerate(chips):
                for c in chips[i + 1:]:
                    apart = (abs(a["x"] - c["x"]) >= (a["L"] + c["L"]) / 2 + 1.5
                             or abs(a["y"] - c["y"]) >= (a["W"] + c["W"]) / 2 + 1.5)
                    self.assertTrue(apart, f"{name}: {a['ref']} and {c['ref']} overlap")

    def test_write(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            text = mockup.write(Path(d) / "m.html").read_text()
        self.assertNotIn("/*LAYOUT*/", text)
        self.assertIn('"CTRL"', text)
