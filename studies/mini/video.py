"""Heron Mini's video, as board.py builds it (RFC 0041): the timing ROM's
contents, the picture a frame's memory makes, and the picture the
chip-level netlist sent, decoded from a capture of its outputs.

640 x 480 at 4 bits a pixel, VGA timing from a 25.175 MHz pixel clock
(two master ticks). A line is 100 characters of 8 pixels: 0-79 the
picture, 80-81 the front porch, 82-93 the sync, 94-99 the back porch. A
frame is 525 lines: 0-9 the front porch, 10-11 the sync, 12-44 the back
porch, 45-524 the picture (lines 0-44 come first, so the picture's end is
the frame's). The syncs are active low.

The picture comes from bank 1 of the RAM (0x0020_0000 up), by a table of
line descriptors at its word 0 (1024 with TSEL): picture line y's at word
44 + y, read in the line before's blanking. A descriptor holds

    bits 18-0   the line's first word, a word address in bank 1
    bits 22-19  the line's palette bank
    bit 23      an interrupt as the line is set up (in the line before's
                blanking)

and the line is the 80 words from there, each eight pixels, the low nibble
first. A pixel's colour is palette entry 16 x bank + pixel, RGB 5:6:5.

The video's registers are in region 7 (LOC0, LOC1): 0xF000_0000 the
control register (bit 0 the picture on, 1 TSEL, 2 the interrupt on),
0xF000_0004 the interrupt's acknowledge (any write), 0xF000_0400 + 4n the
palette's entry n (written, not read). The interrupt is set as the
picture ends (the frame's last line) and by a line whose descriptor asks;
its state is bit 4 of the interrupt status (0xF000_0800).
"""

H_CHARS, V_LINES = 100, 525
WIDTH, HEIGHT = 640, 480
WORDS = 80                       # a line's words
FIRST = 45                       # the picture's first line
TABLE = 44                       # picture line y's descriptor: table word TABLE + y
BANK1 = 0x200000                 # bank 1, the video's, in bytes
TICKS_FRAME = 2 * 8 * H_CHARS * V_LINES

# the timing ROM's bits (board.TIMING_BITS)
HSYNC, VSYNC, DE, SHLD, DESC, DSE, LEND, FEND = range(8)


def _wanted(h, v):
    """The bits the timing register should hold during character h of
    line v."""
    b = 0
    if not 82 <= h <= 93:
        b |= 1 << HSYNC
    if v not in (10, 11):
        b |= 1 << VSYNC
    if h < 80 and v >= FIRST:
        b |= 1 << DE
    # the shifters take a word at the ends of the characters before the
    # picture's 80: character 99 of the line before, then 0-78
    if (h <= 78 and v >= FIRST) or (h == 99 and FIRST - 1 <= v < V_LINES - 1):
        b |= 1 << SHLD
    # the next line's descriptor: its address into VAD at character 82's
    # end, the descriptor itself at 84's
    if FIRST - 1 <= v < V_LINES - 1:
        if h == 82:
            b |= 1 << DESC
        if h == 84:
            b |= 1 << DSE
    if h == 99:
        b |= 1 << LEND
        if v == V_LINES - 1:
            b |= 1 << FEND
    return b


def timing_rom():
    """The 128K timing ROM: at character h and line v (address h + 128v),
    what the register should hold in the next character (it loads the
    ROM's output at each character's end). Characters and lines past the
    frame (only at power-up) end the line and the frame."""
    rom = bytearray(1 << 17)
    for v in range(1024):
        for h in range(128):
            if h < H_CHARS - 1:
                nh, nv = h + 1, v
            elif h == H_CHARS - 1:
                nh, nv = 0, (v + 1) % V_LINES if v < V_LINES else v + 1
            else:
                nh, nv = h + 1, v
            if nh < H_CHARS and nv < V_LINES:
                b = _wanted(nh, nv)
            else:
                b = (1 << HSYNC) | (1 << VSYNC)
                if h >= H_CHARS:
                    b |= 1 << LEND
                if v >= V_LINES:
                    b |= (1 << LEND) | (1 << FEND)
            rom[h | (v << 7)] = b
    return bytes(rom)


def rgb(c):
    """RGB 5:6:5 as 8-bit components."""
    return ((c >> 11) & 31) << 3, ((c >> 5) & 63) << 2, (c & 31) << 3


def render(ram, palette, tsel=0):
    """The picture a frame's memory makes: 480 rows of 640 RGB565 values,
    from the descriptors in bank 1 (ram: 4 MB, bytes) and the palette (256
    entries)."""
    def word(byte_addr):
        return int.from_bytes(ram[byte_addr:byte_addr + 4], "little")
    table = BANK1 + 4096 * tsel
    rows = []
    for y in range(HEIGHT):
        d = word(table + 4 * (TABLE + y))
        base = d & 0x7FFFF
        bank = (d >> 19) & 15
        row = []
        for j in range(WORDS):
            w = word(BANK1 + 4 * ((base + j) & 0x7FFFF))
            for k in range(8):
                row.append(palette[(bank << 4) | ((w >> (4 * k)) & 15)])
        rows.append(row)
    return rows


# the capture: board.py's outputs at each pixel clock, in this order
CAPTURE = [f"RGB{i}" for i in range(16)] + ["HSYNCQ", "VSYNCQ", "DED"]


def decode(log, n=len(CAPTURE)):
    """The frames in a capture (bytes, n a sample): [480 rows of 640
    RGB565], each frame from a VSYNC to the next, its rows the samples with
    DE, a row from each HSYNC. Partial frames are left out."""
    samples = [log[i:i + n] for i in range(0, len(log) - n + 1, n)]
    frames, rows, row = [], None, []
    prev_v = prev_h = 1
    for s in samples:
        hs, vs, de = s[16], s[17], s[18]
        if prev_v and not vs:                        # a VSYNC starts: a frame ends
            if rows is not None and len(rows) == HEIGHT:
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
