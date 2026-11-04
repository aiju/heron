"""A 2D game's frames: the games of studies/mini_gfx (the platformer, the
RTS, the bobs demo) as hand-written kernels on a 4-bit framebuffer of
640 x 480 (Heron Mini's mode M0: pixel p of a word in bits 4p to 4p + 3,
the left pixel a byte's low nibble).

The playfield is a map of 16 x 16 tiles (`tiles`, `tilemap`) under a
status line; NSPR sprites of 16 x 16 pixels move over it, bouncing off
its edges, so some always hang off the screen's sides, top and bottom
and are clipped. A frame is what such a game does without hardware
sprites or scrolling (report 0043: "drawing, erasing and copying under
moving objects took most of every game's frame"):

- every sprite erased, last drawn first, by putting back what was saved
  under it;
- every SCROLL frames the playfield scrolled 8 pixels left: a copy of
  all of it a word to the left, and the new column of tiles drawn at the
  right edge;
- the sprites moved, and those near the player (sprite 0) counted as
  hits;
- every sprite drawn: what's under it saved, then the sprite masked in,
  (d & keep) | image, from a copy of its art shifted to its pixel;
- the status line's numbers (score, hits, frame) redrawn in opaque
  character cells (mono12).

At start-up the program draws the map and the status line, and shifts
every sprite's art and mask to each of the 8 pixels of a word (as the
RTS and the bobs demo do), so that drawing moves whole words: three
(keep, image) pairs a row.

Where the time goes (ref, from the profile, in the reference
configuration's cycles): the sprites half of it (drawing them 29%, saving
and restoring under them 22%), the scrolls' copies 18%, start-up 12%
(the map's tiles, the shifted art), the status line 8% and the checksum
7%.

The results are the score and hits, and two checksums of the screen (the
words' sum and a Fletcher-style sum of sums). The reference (ref.c,
built with gcc) plays the same game and draws its final frame a pixel at
a time: the background from the map, the sprites in order with colour 0
transparent, the status line; the machine's incremental erasing,
scrolling and drawing must leave exactly that picture."""

import os
import random

from heron.studies.graphics import fonts

TITLE = "a 2D game's frames: masked sprites, save-under, scrolling tiles"
PART = "asm"
CATEGORY = "graphics"
SOURCES = ["game.s", "kernels.s"]
REFERENCE_C = ["ref.c"]
SIZES = {"test": {"SW": 256, "SH": 144, "NSPR": 12, "NKIND": 2, "FRAMES": 2, "SCROLL": 2},
         "ref": {"SW": 640, "SH": 480, "NSPR": 48, "NKIND": 8, "FRAMES": 24, "SCROLL": 8}}

MAPW = 64                       # the map's width in tiles (it wraps)
NTILES = 16
STATUS_H = 16                   # the status line's rows


def _tile(k):
    """Tile k: 16 rows of 16 colours."""
    rnd = random.Random(100 + k)
    a, b, c = (2, 10, 6, 14)[k % 4], (4, 12, 6, 5)[k % 4], (k * 5) % 16
    rows = []
    for y in range(16):
        row = []
        for x in range(16):
            if k < 4:               # grass: speckles
                v = b if rnd.random() < 0.15 else a
            elif k < 8:             # bricks
                edge = y % 8 == 7 or (x + (8 if (y // 8) % 2 else 0)) % 16 == 15
                v = 0 if edge else (c if rnd.random() < 0.1 else b)
            elif k < 12:            # water: waves
                v = 9 if (x + 2 * (y % 4)) % 8 < 2 else 1
            else:                   # stone: a framed block
                v = 8 if x in (0, 15) or y in (0, 15) else (7 if (x * y + k) % 5 else c)
            row.append(v)
        rows.append(row)
    return rows


def _pack(rows):
    """Rows of 16 colours as 2 words each, pixel 0 in the low nibble."""
    out = bytearray()
    for row in rows:
        v = 0
        for x, c in enumerate(row):
            v |= c << (4 * x)
        out += v.to_bytes(8, "little")
    return bytes(out)


def tiles():
    return b"".join(_pack(_tile(k)) for k in range(NTILES))


def tilemap(p):
    rows = (p["SH"] - STATUS_H) // 16
    rnd = random.Random(7)
    out = bytearray()
    for y in range(rows):
        for x in range(MAPW):
            if y == rows - 1:
                t = 4 + (x % 4)                     # a floor of bricks
            elif (x // 8 + y // 3) % 5 == 0:
                t = 8 + rnd.randrange(4)            # pools of water
            elif rnd.random() < 0.08:
                t = 12 + rnd.randrange(4)           # blocks
            else:
                t = rnd.randrange(4)                # grass
            out.append(t)
    return bytes(out)


def _sprite(k):
    """Sprite k: 16 rows of 16 colours, 0 transparent; kinds come in pairs,
    an object's two frames of animation."""
    obj, frame = k // 2, k % 2
    body, eye = 10 + obj % 6, 15
    rows = []
    for y in range(16):
        row = []
        for x in range(16):
            dx, dy = x - 7.5, y - 7.5
            r2 = dx * dx + dy * dy
            if obj % 2 == 0:            # a ball with a stripe that turns
                inside = r2 < 56
                v = (body if (x + y + 4 * frame) % 6 < 3 else 4) if inside else 0
                if inside and r2 > 42:
                    v = 0 if frame else 8
            else:                       # a diamond with legs
                inside = abs(dx) + abs(dy) < 8
                v = body if inside else 0
                if y >= 13 and (x % 4 == (2 if frame else 0)):
                    v = 6
            if 4 <= y <= 6 and x in (5, 10):
                v = eye
            row.append(v)
        rows.append(row)
    return rows


def sprite_art(p):
    """Each kind: 16 rows of four words, the image's two then the mask's
    (15 where the sprite has a pixel)."""
    out = bytearray()
    for k in range(p["NKIND"]):
        rows = _sprite(k)
        for row in rows:
            img = mask = 0
            for x, c in enumerate(row):
                img |= c << (4 * x)
                if c:
                    mask |= 15 << (4 * x)
            for v in (img & 0xFFFFFFFF, img >> 32, mask & 0xFFFFFFFF, mask >> 32):
                out += v.to_bytes(4, "little")
    return bytes(out)


def actors(p):
    """Each sprite: x, y, vx, vy and its kind (even: the first of its two
    frames), as signed halves. Some start off the edges."""
    rnd = random.Random(42)
    ph = p["SH"] - STATUS_H
    out = bytearray()
    for i in range(p["NSPR"]):
        x, y = rnd.randrange(-8, p["SW"] - 8), rnd.randrange(-8, ph - 8)
        vx = rnd.choice((-5, -4, -3, -2, -1, 1, 2, 3, 4, 5))
        vy = rnd.choice((-4, -3, -2, -1, 1, 2, 3, 4))
        kind = 2 * rnd.randrange(p["NKIND"] // 2)
        for v in (x, y, vx, vy, kind):
            out += (v & 0xFFFF).to_bytes(2, "little")
    return bytes(out)


def data(p):
    return {
        "font_mono": fonts.bitmap_blob(os.path.join(fonts.FONTS, "mono12.txt")),
        "tiles": tiles(),
        "tilemap": tilemap(p),
        "sprite_art": sprite_art(p),
        "actors": actors(p),
    }
