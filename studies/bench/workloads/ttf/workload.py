"""TrueType text, rasterised, laid out and drawn as Heron's desktop does it.

It stands for the text of the graphics library and window system
(studies/graphics, report 0019; Fen's wsys): the library's own TrueType
code, copied here (ttf.c, raster.c, expand.c, gfx.c, trimmed to what text
needs), reading the study's DejaVu-derived sans.ttf as it is (cmap format
4, loca, glyf, hmtx), its quadratic curves flattened by forward
differences and the outlines scan-converted, plainly or anti-aliased (4
sample rows a pixel, 16 steps across), all in fixed point. New here, as a
desktop's text service would have them: kerning from the font's kern
table (sans.ttf is the study's font with DejaVu Sans's ASCII kerning
pairs added, by make_font.py), and a glyph cache shared by every font (a
hash table on font and glyph, the bitmaps in one arena).

The program: (1) RASTER glyphs rasterised and thrown away, going round
12, 16, 24 and 48 pixels, anti-aliased and plain, what a cache miss
costs; (2) a WIN_W x WIN_H window of 8-bit greys with a title bar in
plain 12-pixel text and PARAS paragraphs anti-aliased at 12 pixels,
broken into lines by their kerned widths (the layout rasterises every
glyph it meets, so drawing then hits the cache); (3) the document
scrolled SCROLLS times by STEP lines and the window drawn whole again.
The results: hashes of the rasterised glyphs, the line breaks, the
window's pixels after the first drawing and after the scrolling, where
every string's pen ended, and the cache's counts.

The sizes: `test` one glyph and a 64 x 24 window with its title only;
`small` eight glyphs, two paragraphs in a 240 x 80 window, one scroll;
`ref` all 62 letters and digits, six paragraphs in a 480 x 240 window,
eight scrolls.

Where the time goes (`small`): about two thirds in rasterising (the
paragraphs' 46 distinct glyphs and part 1's eight): the scan converter
(sweep, prepare, start, aa_span, flush: 40%), decoding and flattening the
outlines (ttf_outline, decode, quad, rs_edge: 13%); then drawing coverage
through the ramp (ramp_rows, 12%), the kerning lookups (ttf_kern and its
big-endian reads, 11%), clearing the window (fill_rows, 5%), and hashing
it for the results (window_hash, 6%).
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))

TITLE = "TrueType text: glyphs rasterised, laid out and drawn through a cache"
PART = "c"
CATEGORY = "graphics"
SOURCES = ["main.c", "text.c", "ttf.c", "raster.c", "expand.c", "gfx.c"]
SIZES = {
    "test": {"RASTER": 1, "PARAS": 0, "SCROLLS": 0, "STEP": 3, "WIN_W": 64, "WIN_H": 24},
    "small": {"RASTER": 8, "PARAS": 2, "SCROLLS": 1, "STEP": 3, "WIN_W": 240, "WIN_H": 80},
    "ref": {"RASTER": 62, "PARAS": 6, "SCROLLS": 8, "STEP": 3, "WIN_W": 480, "WIN_H": 240}
}


def data(p):
    with open(os.path.join(HERE, "sans.ttf"), "rb") as f:
        return {"font": f.read()}
