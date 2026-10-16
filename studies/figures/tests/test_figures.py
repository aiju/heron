"""The figure languages: every figure in the repository's Markdown draws,
and its SVG is what its source draws now; drawing is deterministic; and
bad sources say what's wrong, on the document's line."""

import unittest

from heron.studies.figures import bits, blocks, docs, grid, maps, timing
from heron.studies.figures.svg import Error, lines, textwidth


class Documents(unittest.TestCase):
    def test_every_figure_is_current(self):
        figs = docs.every()
        self.assertTrue(any(f.doc == "studies/figures/gallery.md" for f in figs))
        bad = [f"{f}: {why}" for f, why in docs.stale(figs)]
        self.assertEqual(bad, [], "heron figures write draws them again")

    def test_deterministic(self):
        for f in docs.every(["studies/figures/gallery.md"]):
            self.assertEqual(f.render(), f.render(), str(f))

    def test_finding_figures(self):
        text = ("Prose.\n\n<!-- timing\n  S :0 1:1\n-->\n\n![a](a/s.svg)\n\n"
                "```bits\nword 4\n  3-0 x\n```\n![b](b.svg)\n\n"
                "```timing\nS :0\n```\n\nNot a figure: no image.\n\n"
                "```markdown\n<!-- timing\nS :0\n-->\n![c](c.svg)\n```\n")
        figs = docs.figures("r/doc.md", text)
        self.assertEqual([(f.line, f.lang, f.svg) for f in figs],
                         [(3, "timing", "r/a/s.svg"), (9, "bits", "r/b.svg")])
        self.assertEqual(figs[0].source, "S :0 1:1")

    def test_errors_name_the_document_line(self):
        f = docs.figures("r/doc.md", "\n<!-- bits\nword 8\n  7-1 x\n-->\n![a](a.svg)\n")[0]
        with self.assertRaisesRegex(Error, r"r/doc.md: line 3: bits 0 have no field"):
            f.render()
        with self.assertRaisesRegex(Error, "followed by its image"):
            docs.figures("r/doc.md", "<!-- bits\nword 8\n-->\n\nNo image.\n")


class Languages(unittest.TestCase):
    def bad(self, lang, src, msg):
        with self.assertRaisesRegex(Error, msg):
            lang.render(src)

    def test_lines(self):
        ls = lines('box a "two words" x=1 note="a b" # a comment\n\n  7-0 \'it\'\'s\'')
        self.assertEqual(ls[0].toks, [("word", "box"), ("word", "a"), ("str", "two words"),
                                      ("attr", "x", "1"), ("attr", "note", "a b")])
        self.assertEqual((ls[1].n, ls[1].indent, ls[1].toks), (3, 2, [("word", "7-0"), ("str", "it's")]))

    def test_textwidth(self):
        self.assertAlmostEqual(textwidth("MMMM", 10, mono=True), 24)
        self.assertGreater(textwidth("WAIT", 12, 600), textwidth("WAIT", 12))

    def test_timing(self):
        self.bad(timing, "S :0 3[a]:1 2:0", "goes back in time")
        self.bad(timing, "S :0 foo:1", "foo isn't defined")
        self.bad(timing, "S 3{:1 .5:0 +.5}", "relative")
        self.bad(timing, "a -> b", "no edge is named a")
        svg = timing.render("c = 5\nclk 5{:1 +.5c:0 +.5c}\ndata :x 2.3c:DQ 4c|:x")
        self.assertIn(">DQ</text>", svg)

    def test_bits(self):
        self.bad(bits, "word 8\n  7-4 a\n  5-0 b", "line 3: bit 4 is in two fields")
        self.bad(bits, "word 8\n  7-4 a\n  3-1 = 01", "isn't 3 bits")
        self.bad(bits, "  7-0 a", "belongs under a word")
        svg = bits.render("word 8\n  7-4 = 1x01\n  3-0 reserved")
        self.assertIn("diagram-hatch", svg)

    def test_blocks(self):
        self.bad(blocks, "box a \"A\" right of b", "b isn't a box")
        self.bad(blocks, "box a \"A\" at 0,0\na -> c", "c isn't a box or a bus")
        self.bad(blocks, "bus b from 0,0 to 4,4", "straight")
        svg = blocks.render('box a "A" at 0,0\nbox b "B" right of a\na -> b "x"')
        self.assertIn(">x</text>", svg)

    def test_blocks_routing(self):
        # boxes side by side meet straight, at the middle of their overlap
        d = blocks.Diagram('box a "A" at 0,0\nbox b "B" right of a dy=1')
        (p1, d1, s1), (p2, d2, s2) = blocks.resolve(("box", d.boxes["a"]), ("box", d.boxes["b"]))
        self.assertEqual((s1, s2, d1), ("right", "left", "h"))
        self.assertEqual(p1[1], p2[1])
        self.assertEqual(blocks.route((p1, d1, s1), (p2, d2, s2), [], 20), [p1, p2])
        # two bottoms go around as a U
        u = blocks.route(((0, 10), "v", "bottom"), ((50, 10), "v", "bottom"), [], 20)
        self.assertEqual(u, [(0, 10), (0, 30), (50, 30), (50, 10)])

    def test_map(self):
        self.bad(maps, "0x10 a\n0x0 b\n0x20", "addresses go up")
        self.bad(maps, "0x0 a\n0x10 b", "where the map ends")
        self.bad(maps, "0x0 a\n0x10\ngroup 0x0 0x8 g", "isn't where a region starts or ends")
        self.assertEqual(maps.hexa(0x7F00_0000, 8), "0x7F00_0000")

    def test_grid(self):
        heads, body, _ = grid.parse("| | _0 | _1 | _2 |\n|---|---|---|---|\n| 7_ | `MVI` ×2 | ↳ | |")
        self.assertEqual(heads, ["_0", "_1", "_2"])
        self.assertEqual(body, [("7_", [(0, 2, "MVI ×2"), (2, 1, "")])])
        self.bad(grid, "| | a | b |\n| 1 | x |", "1 cells, but 2 columns")
        self.bad(grid, "| | a |\n| 1 | ↳ |", "there's none")


if __name__ == "__main__":
    unittest.main()
