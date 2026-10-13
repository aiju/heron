"""The fonts as data for the programs: fonts/sans.ttf as it is, and the
bitmap fonts (fonts/*12.txt) in the form font_bitmap (src/font.c) reads:

    0   first character, count, ascent, descent       (bytes)
    4   words per strike row (16 bits), strike height, 0
    8   per character: width, height, advance, x offset, y offset (signed),
        0, and where its bitmap starts in the strike, in words (16 bits)
        then the strike: every glyph side by side, each starting on a word,
        top-aligned, one bit per pixel, the first pixel in bit 0

Each goes into the program as a byte array: as assembly for the machine
(data_asm), as C for the host build (data_c).
"""

import functools
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")

# C name -> file
BLOBS = {"font_sans12": "sans12.txt", "font_mono12": "mono12.txt", "ttf_sans": "sans.ttf"}


def read_bitmap(path):
    """(ascent, descent, {char: (adv, xoff, yoff, rows)}), rows as '#.' strings."""
    glyphs, ascent, descent = {}, 0, 0
    with open(path) as f:
        lines = [x.strip() for x in f]
    i = next(k for k, x in enumerate(lines) if x.startswith("font "))    # after the comments
    lines = [x for x in lines[i:] if x]
    i = 0
    while i < len(lines):
        w = lines[i].split()
        if w[0] == "font":
            ascent, descent = int(w[2]), int(w[4])
            i += 1
        elif w[0] == "char":
            c, adv, xo, yo, gw, gh = (int(w[k]) for k in (1, 3, 5, 6, 7, 8))
            rows = lines[i + 1:i + 1 + gh]
            assert all(len(r) == gw for r in rows), f"{path}: char {c}"
            glyphs[c] = (adv, xo, yo, rows)
            i += 1 + gh
        else:
            raise ValueError(f"{path}: {lines[i]!r}")
    return ascent, descent, glyphs


def bitmap_blob(path):
    ascent, descent, glyphs = read_bitmap(path)
    first, last = min(glyphs), max(glyphs)
    count = last - first + 1
    table, cols, sw = bytearray(), [], 0
    for c in range(first, last + 1):
        adv, xo, yo, rows = glyphs.get(c, (0, 0, 0, []))
        w, h = (len(rows[0]) if rows else 0), len(rows)
        table += bytes([w, h, adv, xo & 255, yo & 255, 0, sw & 255, sw >> 8])
        cols.append((sw, rows))
        sw += (w + 31) // 32
    sh = max(len(rows) for _, rows in cols)
    strike = [[0] * sw for _ in range(sh)]
    for start, rows in cols:
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == "#":
                    strike[y][start + x // 32] |= 1 << (x % 32)
    out = bytearray([first, count, ascent, descent, sw & 255, sw >> 8, sh, 0]) + table
    for row in strike:
        for word in row:
            out += word.to_bytes(4, "little")
    return bytes(out)


@functools.lru_cache(maxsize=None)
def blobs():
    out = {}
    for name, fn in BLOBS.items():
        path = os.path.join(FONTS, fn)
        if fn.endswith(".ttf"):
            with open(path, "rb") as f:
                out[name] = f.read()
        else:
            out[name] = bitmap_blob(path)
    return out


def data_asm():
    """The fonts as an assembly file (either ISA): far data, word aligned."""
    out = ["; the graphics study's fonts (studies/graphics/fonts.py)", ""]
    for name, data in blobs().items():
        sym = "_" + name
        out += [f"        .global {sym}", f"        .far {sym}", f"        .section .fardata.{sym}",
                "        .align 4", f"{sym}:"]
        for k in range(0, len(data), 16):
            out.append("        .byte " + ", ".join(str(b) for b in data[k:k + 16]))
        out.append("")
    return "\n".join(out)


def data_c():
    out = ["/* the graphics study's fonts (studies/graphics/fonts.py) */", ""]
    for name, data in blobs().items():
        out.append(f"const unsigned char {name}[{len(data)}] __attribute__((aligned(4))) = {{")
        for k in range(0, len(data), 16):
            out.append("    " + ", ".join(str(b) for b in data[k:k + 16]) + ",")
        out.append("};")
    return "\n".join(out) + "\n"
