"""Heron Mini's video, as board.py builds it (RFC 0041, RFC 0042): the
timing ROM's contents, the picture a frame's memory and registers make,
and the picture the chip-level netlist sent, decoded from a capture of
its outputs.

Two timing families, each a table in the timing ROM (512K x 8, by the
family, the line and the character):

    VGA   640 x 480, a 25.175 MHz pixel: two ticks of the 50.35 MHz master
          clock. A line is 100 characters of 8 pixels (0-79 the picture,
          80-81 the front porch, 82-93 the sync, 94-99 the back porch), a
          frame 525 lines (0-9 the front porch, 10-11 the sync, 12-44 the
          back porch, 45-524 the picture)
    XGA   1024 x 768, a 65 MHz pixel: the master clock itself, switched to
          65 MHz while an XGA mode is shown. A line is 168 characters (0-127
          the picture, 128-130 the front porch, 131-147 the sync, 148-167
          the back porch), a frame 806 lines (0-2, 3-8 the sync, 9-37,
          38-805 the picture)

The syncs are active low. The picture's lines come last, so its end is
the frame's.

The modes (the control register's bits 6-4, taken as a frame starts):

    0  M0  VGA, 4 bits a pixel          4  M4  VGA, 1 bit
    1  M1  VGA, 8 bits, pixels 2 wide   5  M5  XGA, 2 bits
    2  M2  VGA, 8 bits                  6  M6  XGA, 1 bit
    3  M3  VGA, 2 bits                  7  black (VGA timing)

A word's pixels are linear in every mode, pixel 0 in the low bits: pixel
p is bits b*p up to b*p + b - 1 for b bits a pixel. An 8-bit pixel is its
palette index; a narrower one is 16 x the line's bank + the pixel.

The picture comes from bank 1 of the RAM (0x0020_0000 up). Picture line
y's descriptor is word T + y of the table at bank 1's word 0 (1024 with
TSEL), T = 44 (VGA) or 37 (XGA), read in the line before:

    bits 18-0   the line's first word, a word address in bank 1
    bits 22-19  the line's palette bank
    bit 23      an interrupt as the line is set up

and the line is the mode's words from there.

The cursor (control bit 8): its rows are in two tables in bank 1, like
the descriptors, picture line y's at words 2048 + T + y (pixels 0-15) and
3072 + T + y (pixels 16-31), 2 bits a pixel (pixel k at bits 2k and
2k + 1 of the pair), read in the line before; the software writes the
cursor's 32 rows into the lines it covers and zeros elsewhere. Value 0 is
transparent, 1-3 palette entries 253-255. Its left edge is the X
register's (0xF000_0010, written): the beam position (bits 10-3 the
character, 2-0 the pixel in it) XSTART family pixels before it, so
X = (x - XSTART) mod the line's pixels for a cursor at x, from -32 to the
picture's width; in XGA x is even (bit 0 is ignored).

The registers (region 7, LOC0): 0xF000_0000 the control register (bit 0
the picture on, 1 TSEL, 2 the interrupt on, 6-4 the mode, 8 the cursor
on), 0xF000_0004 the interrupt's acknowledge (any write), 0xF000_0008 the
beam (read: bits 9-0 the line, 23-16 the character; a half and a byte
read), 0xF000_0010 the cursor's X; 0xF000_0400 + 4n the palette's entry n
(RGB 5:6:5, written, not read). The interrupt is set as the picture ends
and by a line whose descriptor asks; its state is bit 4 of the interrupt
status (0xF000_0800).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    name: str
    width: int
    height: int
    chars: int          # characters of 8 pixels a line
    picture: int        # the picture's characters: 0 .. picture - 1
    hsync: range        # the sync's characters
    lines: int
    first: int          # the picture's first line
    vsync: range
    xga: int            # the family bit (the ROM's address bit 18)

    @property
    def table(self):
        """Picture line y's descriptor is table word table + y."""
        return self.first - 1

    @property
    def line_pixels(self):
        return 8 * self.chars

    def ticks(self, n=1):
        """Master ticks for n pixels."""
        return n if self.xga else 2 * n


VGA = Family("VGA", 640, 480, 100, 80, range(82, 94), 525, 45, range(10, 12), 0)
XGA = Family("XGA", 1024, 768, 168, 128, range(131, 148), 806, 38, range(3, 9), 1)
FAMILIES = (VGA, XGA)

# the modes: (family, bits a pixel, pixels two wide)
MODES = {0: (VGA, 4, False), 1: (VGA, 8, True), 2: (VGA, 8, False), 3: (VGA, 2, False),
         4: (VGA, 1, False), 5: (XGA, 2, False), 6: (XGA, 1, False)}


def family_of(mode):
    return MODES[mode][0] if mode in MODES else VGA


BANK1 = 0x200000                 # bank 1, the video's, in bytes
CURSOR0, CURSOR1 = 2048, 3072    # the cursor's tables (words in bank 1)
TICKS_FRAME = 2 * 8 * VGA.chars * VGA.lines

# the timing ROM's bits (board.TIMING_BITS): the syncs, the picture (DE),
# the shifters' load at the character's end (SHLD), an event (EV, three
# bits) and the frame's end (FEND, with the line's end)
HSYNC, VSYNC, DE, SHLD, EV0, EV1, EV2, FEND = range(8)
# the events, at a character's end: VAD to the cursor's first table and
# the holding registers emptied (C0LD); the cursor's first word into its
# shifters, VAD to its second table (C0TK); the second word in, VAD to
# the descriptor's table (C1TK); VAD to the descriptor (DSE); the line's
# end (LEND). The holding registers are emptied at each
EV_C0LD, EV_C0TK, EV_C1TK, EV_DSE, EV_LEND = 1, 2, 3, 4, 7


def _events(f):
    """{character: event} in the line before a picture line: the cursor's
    words, then the descriptor, after the picture's last load."""
    p = f.picture - 1
    return {p: EV_C0LD, p + 2: EV_C0TK, p + 4: EV_C1TK, p + 6: EV_DSE}


# XSTART: the X register's beam position is this many family pixels
# before the cursor's first pixel (board.py's cursor pipeline)
XSTART = {0: 1, 1: 4}


def _wanted(f, h, v):
    """The bits the timing register holds during character h of line v."""
    b = 0
    if h not in f.hsync:
        b |= 1 << HSYNC
    if v not in f.vsync:
        b |= 1 << VSYNC
    if h < f.picture and v >= f.first:
        b |= 1 << DE
    # a word into the shifters at the ends of the characters before the
    # picture's: the line before's last, then 0 .. picture - 2 (the modes
    # with words of more characters load at the ends of their last)
    if (h <= f.picture - 2 and v >= f.first) or (h == f.chars - 1 and f.first - 1 <= v < f.lines - 1):
        b |= 1 << SHLD
    ev = 0
    if f.first - 1 <= v < f.lines - 1:
        ev = _events(f).get(h, 0)
    if h == f.chars - 1:
        ev = EV_LEND
        if v == f.lines - 1:
            b |= 1 << FEND
    return b | ev << EV0


def timing_rom():
    """The 512K timing ROM: at character h and line v of family x
    (address h + 256v + 2^18 x), what the register should hold in the
    next character (it loads the ROM's output at each character's end).
    Characters and lines past the frame (only as it powers up, or as the
    family changes) end the line and the frame."""
    rom = bytearray(1 << 19)
    for f in FAMILIES:
        base = f.xga << 18
        for v in range(1024):
            for h in range(256):
                if h < f.chars - 1:
                    nh, nv = h + 1, v
                elif h == f.chars - 1:
                    nh, nv = 0, (v + 1) % f.lines if v < f.lines else v + 1
                else:
                    nh, nv = h + 1, v
                if nh < f.chars and nv < f.lines:
                    b = _wanted(f, nh, nv)
                else:
                    b = (1 << HSYNC) | (1 << VSYNC)
                    if h >= f.chars:
                        b |= EV_LEND << EV0
                    if v >= f.lines:
                        b |= (EV_LEND << EV0) | (1 << FEND)
                rom[base | h | (v << 8)] = b
    return bytes(rom)


def rgb(c):
    """RGB 5:6:5 as 8-bit components."""
    return ((c >> 11) & 31) << 3, ((c >> 5) & 63) << 2, (c & 31) << 3


def _word(ram, w):
    a = BANK1 + 4 * (w & 0x7FFFF)
    return int.from_bytes(ram[a:a + 4], "little")


def render(ram, palette, ctrl=1, cursor_x=0):
    """The picture a frame's memory and registers make: rows of RGB 5:6:5
    values (black with the picture off, or in mode 7), from the
    descriptors and the cursor's tables in bank 1 (ram: 4 MB, bytes), the
    palette (256 entries), the control register and the cursor's X."""
    mode = (ctrl >> 4) & 7
    f = family_of(mode)
    if not ctrl & 1 or mode not in MODES:
        return [[0] * f.width for _ in range(f.height)]
    _, bits, double = MODES[mode]
    table = 1024 * ((ctrl >> 1) & 1)
    per_word = 32 // bits
    pixels = f.width // 2 if double else f.width
    words = pixels // per_word
    xs = cursor_x & 0x7FF
    if f.xga:
        xs &= ~1
    # the beam position X names, in pixels from the line's start, and the
    # cursor's first pixel after it
    x0 = ((xs >> 3) * 8 + (xs & 7) + XSTART[f.xga]) % f.line_pixels
    if x0 >= f.line_pixels - 32:
        x0 -= f.line_pixels
    rows = []
    for y in range(f.height):
        d = _word(ram, table + f.table + y)
        base, bank = d & 0x7FFFF, (d >> 19) & 15
        idx = []
        for j in range(words):
            w = _word(ram, base + j)
            for p in range(per_word):
                v = (w >> (bits * p)) & ((1 << bits) - 1)
                i = v if bits == 8 else 16 * bank + v
                idx += [i, i] if double else [i]
        if ctrl & 0x100:
            c = _word(ram, CURSOR0 + f.table + y) | _word(ram, CURSOR1 + f.table + y) << 32
            for k in range(32):
                v = (c >> (2 * k)) & 3
                if v and 0 <= x0 + k < f.width:
                    idx[x0 + k] = 252 + v
        rows.append([palette[i] for i in idx])
    return rows


# the capture: board.py's outputs at each pixel, in this order (DEO: the
# colour register holds a picture's pixel)
CAPTURE = [f"RGB{i}" for i in range(16)] + ["HSYNCQ", "VSYNCQ", "DEO", "VIFLAG", "FAM",
                                              "DSE_n", "HR23", "STRETCH"]


def decode(log, n=len(CAPTURE)):
    """The frames in a capture (bytes, n a sample): [rows of RGB565], each
    frame from a VSYNC to the next, its rows the samples with DE, a row
    from each HSYNC. Partial frames (rows of differing widths, too few
    rows) are left out."""
    samples = [log[i:i + n] for i in range(0, len(log) - n + 1, n)]
    frames, rows, row = [], None, []
    prev_v = prev_h = 1
    for s in samples:
        hs, vs, de = s[16], s[17], s[18]
        if prev_v and not vs:                        # a VSYNC starts: a frame ends
            if rows and len(rows) in (VGA.height, XGA.height) and \
                    len({len(r) for r in rows}) == 1 and len(rows[0]) in (VGA.width, XGA.width):
                frames.append(rows)
            rows = []
        if prev_h and not hs and row:                # an HSYNC starts: a row ends
            if rows is not None:
                rows.append(row)
            row = []
        if de:
            row.append(sum(s[i] << i for i in range(16)))
        prev_v, prev_h = vs, hs
    return frames
