"""A window system redrawing a desktop: Fen's window system (srv/wsys) and
Heron Mini's window manager (studies/mini_gfx/wm), as hand-written
kernels on a 4-bit framebuffer of 640 x 480 (Heron Mini's mode M0: pixel
p of a word in bits 4p to 4p + 3, so the left pixel is a byte's low
nibble).

The program draws a desktop (a patterned background, terminals and text
documents in overlapping windows, with frames and title bars) and then
plays a session of user actions from `session`, each after a mouse
cursor's path to it:

- **moving** the top window by a few pixels: a shifted copy of the whole
  window, overlapping itself (backwards when it moves right on the same
  rows), then what it uncovers redrawn;
- **scrolling** a terminal a line: a copy up inside each visible piece,
  then the new line drawn in opaque character cells (mono12);
- **raising** a window: all of it redrawn;
- **typing** into a document: its edit line redrawn, transparent
  proportional text (sans12);
- **selecting**: the old selection XORed off and the new one on;
- **the cursor** (a 16 x 16 masked arrow, shifted to its pixel) with
  save-under and restore, around everything else.

Every redraw is clipped as a window manager clips: each window's visible
region is a list of rectangles (its own minus those above it), a damaged
area is redrawn layer by layer through it, and every primitive (fills,
XOR fills, glyphs) is clipped to the rectangle in hand. The kernels work
on words, as wsys/kernels.s and mini_gfx's gfx/asm do: fills and copies
with edge masks, copies shifted by any number of pixels, glyphs as their
1-bit rows shifted to the pixel and expanded a byte to a word through a
table, and opaque text through a table made for its two colours.

Where the time goes (`small`, from the profile, in the reference
configuration's cycles): text about half (draw_text 29%, draw_cells 22%,
as in report 0043's tools), the copies of moves and scrolls 14%
(copy_rect), fills 13%, the cursor 6%, the region arithmetic (visible
regions, intersections) 4%, and the checksum 8%.

The results are two checksums of the screen: the words' sum and a
Fletcher-style sum of sums (bench_hash's byte at a time would cost
900,000 instructions for a 640 x 480 screen). The reference (ref.c,
built with gcc) replays the session's effect on the windows and draws
the final state pixel by pixel, painter's order, without clipping lists,
copies or tables: the machine's incremental redraws must leave exactly
that picture.

`full` is the full screen, eight windows and 200 actions, `small` five
windows and 14 actions; `tiny` a screen of
192 x 128 (the top left corner of the same framebuffer), the first three
windows and two actions. The windows are the same desktop, scaled."""

import os
import random

from heron.studies.graphics import fonts

TITLE = "a window system redrawing a desktop: copies, fills, text, a cursor"
PART = "asm"
CATEGORY = "graphics"
SOURCES = ["wm.s", "text.s", "kernels.s"]
REFERENCE_C = ["ref.c"]
SIZES = {"tiny": {"SW": 192, "SH": 128, "WINDOWS": 3, "ACTIONS": 2},
         "small": {"SW": 640, "SH": 480, "WINDOWS": 5, "ACTIONS": 14},
         "full": {"SW": 640, "SH": 480, "WINDOWS": 8, "ACTIONS": 200}}

# ---- the session ------------------------------------------------------------
#
# Little-endian halves, signed where they can be negative:
#
#   header (16 bytes): windows, operations, the cursor's x and y, 0...
#   a window (48 bytes): x, y, w, h, kind (0 a terminal, 1 a document),
#       the title bar's colour, the client area's, the text's, the first
#       corpus line, the edit line (documents), columns and rows
#       (terminals), then the title, NUL-terminated, in 24 bytes
#   an operation (12 bytes): code, window, then four arguments
#
# Windows start in their order, the last on top.

OP_CURSOR, OP_MOVE, OP_SCROLL, OP_RAISE, OP_TYPE, OP_SELECT = 1, 2, 3, 4, 5, 6
TERM, DOC = 0, 1
CELL_W, LINE_H, TITLE_H = 7, 15, 18     # mono12's cell; a title bar and its line
EDIT_MAX = 40                           # characters in an edit line

# x, y, w, h on a 640 x 480 screen; kind; title, client and text colours; title
DESKTOP = [
    (16, 20, 330, 270, DOC, 1, 15, 0, "README"),
    (250, 150, 290, 220, TERM, 4, 0, 10, "fen: shell"),
    (380, 40, 240, 190, DOC, 2, 7, 1, "notes.txt"),
    (40, 300, 250, 160, TERM, 5, 1, 14, "log"),
    (440, 290, 180, 150, DOC, 3, 15, 4, "about"),
]

CORPUS = """\
fen 0.4 (heron draft 2) login: emily
$ ls -l /bin
-rwxr-xr-x  1 root  wheel   5120 cat
-rwxr-xr-x  1 root  wheel   9216 cc
-rwxr-xr-x  1 root  wheel   3584 echo
-rwxr-xr-x  1 root  wheel  14848 ed
-rwxr-xr-x  1 root  wheel   7680 grep
-rwxr-xr-x  1 root  wheel   6144 ls
-rwxr-xr-x  1 root  wheel  11264 sh
-rwxr-xr-x  1 root  wheel   4608 wc
$ cat /etc/motd
Welcome to Fen on Heron, a computer built from 7400-series logic.
The window system draws into a 640 x 480 frame of 16 colours.
$ grep -n blit src/wsys/*.c | wc -l
      42
$ cc -O hello.c -o hello && ./hello
hello, world
$ ps
  PID TTY   TIME CMD
    1 con  0:01 init
    7 con  0:00 wsys
   12 win1 0:00 sh
   19 win1 0:00 ps
$ make -C /src/lisp
cc -c reader.c
cc -c eval.c
cc -c gc.c
ld -o lisp reader.o eval.o gc.o -lc
$ ./lisp bench.lisp
(deriv '(* x (+ x 3)) 'x) => (+ x (+ x 3))
(sort '(5 3 9 1 7)) => (1 3 5 7 9)
; 1204 conses, 2 collections
$ date
Wed Nov  4 10:42:17 2026
$ df
Filesystem  1K-blocks  Used Avail Capacity  Mounted on
/dev/cf0        30720 18112 12608    59%    /
$ echo $PATH
/bin:/usr/bin:/home/emily/bin
The quick brown fox jumps over the lazy dog.
Pack my box with five dozen liquor jugs.
Heron is a 32-bit minicomputer: a CPU of microcode and chips,
a bus of cards, and the software to make it useful.
Draft 2's instructions are a parcel of 16 bits and up to two more,
with sixteen addressing modes, a stack and a link register.
A window is a frame, a title bar and a client area; the window
system keeps a list of them from back to front, and redraws what
moves uncover from that list, clipped to what each can show.
Text is a font's glyphs expanded from one bit to four, a byte of
the glyph at a time through a table of word masks.
To do: faster scrolling, a second font, colour palettes per line.
Meeting notes: bring the logic analyser; the bus card needs
termination at both ends; order 74F299s for the video shifters.
"""


def _lines():
    return CORPUS.splitlines()


def _layout(p):
    """The windows, scaled to the screen: (x, y, w, h, kind, colours,
    first line, edit line, columns, rows, title)."""
    sw, sh = p["SW"], p["SH"]
    nl = len(_lines())
    out = []
    for k, (x, y, w, h, kind, tc, cc, fg, title) in enumerate(DESKTOP[:p["WINDOWS"]]):
        x, w = x * sw // 640, w * sw // 640
        y, h = y * sh // 480, h * sh // 480
        # the cells that fit the client area (w - 2 by h - TITLE_H - 1),
        # 2 pixels in from its left and 1 from its top
        cols = (w - 2 - 4) // CELL_W
        rows = (h - TITLE_H - 1 - 2) // LINE_H
        if kind == TERM:
            first = (11 * k) % nl
            edit = 0
        else:
            first = 30 + 3 * k
            edit = max(0, min(rows - 2, 5))
            cols = rows = 0
        out.append([x, y, w, h, kind, tc, cc, fg, first, edit, cols, rows, title])
    return out


def _session(p):
    """(windows, actions, the cursor's start): ACTIONS actions, each after
    four steps of the cursor towards a random point; the actions cycle
    through moves (some along the rows only, some by whole words), scrolls,
    raises, typing and selections. The windows stay on the screen."""
    sw, sh = p["SW"], p["SH"]
    rnd = random.Random(2026)
    wins = _layout(p)
    order = list(range(len(wins)))          # back to front
    edit = [0] * len(wins)
    ops = []
    cur = [sw // 2, sh // 2]
    typing = "make all && ./desktop -v "
    for a in range(p["ACTIONS"]):
        # the cursor's path there, in four steps
        tx, ty = rnd.randrange(0, sw - 16), rnd.randrange(0, sh - 16)
        x0, y0 = cur
        for s in range(1, 5):
            cur = [x0 + (tx - x0) * s // 4, y0 + (ty - y0) * s // 4]
            ops.append((OP_CURSOR, 0, cur[0], cur[1], 0, 0))
        kind = ("move", "scroll", "raise", "type", "move", "scroll",
                "select", "type", "move")[a % 9]
        terms = [i for i in range(len(wins)) if wins[i][4] == TERM]
        docs = [i for i in range(len(wins)) if wins[i][4] == DOC]
        if kind == "move":
            w = wins[order[-1]]
            for _ in range(100):
                dx, dy = rnd.randrange(-37, 38), rnd.randrange(-29, 30)
                if a % 3 == 0:
                    dy = 0              # along its rows: a backward copy if right
                if a % 9 == 8:          # by whole words, right if there's room
                    dx, dy = 8 * rnd.choice((2, 3, 4)), 0
                    if w[0] + dx + w[2] > sw:
                        dx = -dx
                nx, ny = w[0] + dx, w[1] + dy
                if (dx or dy) and 0 <= nx and nx + w[2] <= sw and 0 <= ny and ny + w[3] <= sh:
                    break
            else:
                dx = dy = 0
            w[0] += dx
            w[1] += dy
            ops.append((OP_MOVE, order[-1], dx, dy, 0, 0))
        elif kind == "scroll":
            ops.append((OP_SCROLL, terms[a % len(terms)], 0, 0, 0, 0))
        elif kind == "raise":
            k = order[a % (len(order) - 1)]
            order.remove(k)
            order.append(k)
            ops.append((OP_RAISE, k, 0, 0, 0, 0))
        elif kind == "type":
            k = docs[a % len(docs)]
            for _ in range(3):
                if edit[k] < EDIT_MAX:
                    ops.append((OP_TYPE, k, ord(typing[edit[k] % len(typing)]), 0, 0, 0))
                    edit[k] += 1
        elif kind == "select":
            k = docs[a % len(docs)]
            cw, ch = wins[k][2] - 2, wins[k][3] - TITLE_H - 1
            x0, y0 = rnd.randrange(0, cw // 2), rnd.randrange(0, ch // 2)
            ops.append((OP_SELECT, k, x0, y0, x0 + rnd.randrange(8, cw // 2),
                        y0 + rnd.randrange(8, ch // 2)))
    return _layout(p), ops, [sw // 2, sh // 2]


def _h(*vals):
    return b"".join((v & 0xFFFF).to_bytes(2, "little") for v in vals)


def session(p):
    """The session, in the format above."""
    wins, ops, cur = _session(p)
    out = bytearray(_h(len(wins), len(ops), cur[0], cur[1], 0, 0, 0, 0))
    for x, y, w, h, kind, tc, cc, fg, first, edit, cols, rows, title in wins:
        rec = _h(x, y, w, h, kind, tc, cc, fg, first, edit, cols, rows)
        rec += title.encode().ljust(24, b"\0")
        out += rec
    for op in ops:
        out += _h(*op)
    return bytes(out)


# The mouse cursor: an arrow, '#' black, 'o' white, '.' transparent.
CURSOR = """\
#...............
##..............
#o#.............
#oo#............
#ooo#...........
#oooo#..........
#ooooo#.........
#oooooo#........
#ooooooo#.......
#oooooooo#......
#ooooo#####.....
#oo#oo#.........
#o#.#oo#........
##..#oo#........
#....#oo#.......
......###.......
"""


def cursor():
    """16 rows of four words: the image's two (16 pixels), then the mask's
    (a pixel 15 where the cursor is opaque)."""
    out = bytearray()
    for row in CURSOR.splitlines():
        img = mask = 0
        for x, ch in enumerate(row):
            if ch != ".":
                mask |= 15 << (4 * x)
                img |= (0 if ch == "#" else 15) << (4 * x)
        for v in (img & 0xFFFFFFFF, img >> 32, mask & 0xFFFFFFFF, mask >> 32):
            out += v.to_bytes(4, "little")
    return bytes(out)


def data(p):
    path = os.path.join(fonts.FONTS, "{}.txt")
    return {
        "font_mono": fonts.bitmap_blob(path.format("mono12")),
        "font_sans": fonts.bitmap_blob(path.format("sans12")),
        "corpus": CORPUS.encode(),
        "session": session(p),
        "cursor_art": cursor(),
    }
