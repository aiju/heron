"""The fonts as data for the programs, as one assembly file of far data:

    font_sans12, font_mono12   the graphics study's bitmap fonts
                               (studies/graphics/fonts.py has the layout)
    font_cell8                 mono12 in cells of 8 x 16: for each of
                               ' '-'~', 16 bytes, a row each, bit 0 the
                               leftmost pixel, the baseline under row 12
"""

import functools

from heron.studies.graphics import fonts as gfonts

CELL_H = 16
BASELINE = 12


@functools.lru_cache(maxsize=None)
def cell8():
    import os
    ascent, descent, glyphs = gfonts.read_bitmap(os.path.join(gfonts.FONTS, "mono12.txt"))
    out = bytearray()
    for c in range(32, 127):
        rows = [0] * CELL_H
        if c in glyphs:
            adv, xo, yo, g = glyphs[c]
            w = len(g[0]) if g else 0
            x0 = max(0, min(xo, 8 - w))
            for y, row in enumerate(g):
                ty = BASELINE + yo + y
                if 0 <= ty < CELL_H:
                    for x, ch in enumerate(row):
                        if ch == "#" and 0 <= x0 + x < 8:
                            rows[ty] |= 1 << (x0 + x)
        out += bytes(rows)
    return bytes(out)


def blobs():
    b = gfonts.blobs()
    return {"font_sans12": b["font_sans12"], "font_mono12": b["font_mono12"], "font_cell8": cell8()}


def data_asm():
    out = ["; the fonts (studies/mini_gfx/fonts.py)", ""]
    for name, data in blobs().items():
        sym = "_" + name
        out += [f"        .global {sym}", f"        .far {sym}", f"        .section .fardata.{sym}",
                "        .align 4", f"{sym}:"]
        for k in range(0, len(data), 16):
            out.append("        .byte " + ", ".join(str(b) for b in data[k:k + 16]))
        out.append("")
    return "\n".join(out)
