"""The quick reference cards: they build, and every example assembles.
(Printing them needs Chromium, so that isn't tested here.)"""

import unittest

from heron.studies.v1_isa import refcard


class RefCard(unittest.TestCase):
    def test_examples_assemble(self):
        for isa in ("v1a", "v1b"):
            for line, words in refcard.assembled(isa):
                code = line.partition(";")[0].strip()
                if code and not code.endswith(":"):
                    self.assertTrue(words, f"{isa}: {line!r} has no encoding")

    def test_build(self):
        for isa in ("v1a", "v1b"):
            doc = refcard.build_html(isa)
            self.assertEqual(doc.count('<div class="page">'), 2, isa)


if __name__ == "__main__":
    unittest.main()
