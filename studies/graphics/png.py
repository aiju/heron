"""Screens as PNG files: 8-bit indexed, with the palette of the depth
(as theme_rgb in src/theme.c has it)."""

import struct
import zlib

CUBE = (0, 95, 135, 175, 215, 255)
VGA16 = (0, 0, 0, 0, 0, 170, 0, 170, 0, 0, 170, 170, 170, 0, 0, 170, 0, 170, 170, 85, 0,
         170, 170, 170, 85, 85, 85, 85, 85, 255, 85, 255, 85, 85, 255, 255, 255, 85, 85,
         255, 85, 255, 255, 255, 85, 255, 255, 255)


def palette(depth):
    """[(r, g, b)] for every pixel value at a depth, as theme_rgb has it."""
    if depth == 0:
        return [(0, 0, 0), (255, 255, 255)]
    if depth == 1:
        return [(85 * c,) * 3 for c in range(4)]
    out = [tuple(VGA16[3 * c:3 * c + 3]) for c in range(16)]
    if depth == 3:
        out += [(CUBE[c // 36], CUBE[c // 6 % 6], CUBE[c % 6]) for c in range(216)]
        out += [(8 + 10 * k,) * 3 for k in range(24)]
    return out


def pixels(screen, w, h, depth):
    """The pixel values, a row at a time (LSB-first within bytes)."""
    bpp = 1 << depth
    pitch = (w * bpp) // 8
    mask = (1 << bpp) - 1
    rows = []
    for y in range(h):
        row = screen[y * pitch:(y + 1) * pitch]
        if depth == 3:
            rows.append(bytes(row))
            continue
        out = bytearray(w)
        for x in range(w):
            bit = x * bpp
            out[x] = (row[bit >> 3] >> (bit & 7)) & mask
        rows.append(bytes(out))
    return rows


def write(path, screen, w, h, depth):
    pal = palette(depth)
    raw = b"".join(b"\0" + r for r in pixels(screen, w, h, depth))

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
    png += chunk(b"PLTE", b"".join(bytes(c) for c in pal))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
