"""Graphics kernels on Heron Mini's register-transfer model (RFC 0041,
Part II): the inner loops of a 4-bit framebuffer's fills, copies (aligned
and shifted) and glyph expansion, as draft 2 code (the graphics study's
kernels, studies/graphics/asm/v2 on the Egret branch, reduced to their
loops) and as the mini's block instructions, in master ticks a word.

    heron mini bench
"""

import heron.studies.v2_isa  # noqa: F401
from heron.infra import asm as asmcore
from heron.infra import isas

from . import system, rtl
from .timing import TICK

WORDS = 960                     # 3 lines of 640 pixels at 4 bits
DST, SRC, TAB = 0x210000, 0x220000, 0x230000

HEAD = """
        .org 0x00
        JMP  start
        .org 0x1C
start:  MOV  sp, #0x100000
        MOV  r1, #{dst}
        MOV  r2, #{src}
        MOV  r3, #{n}
        MOV  r4, #{arg4}
        MOV  r5, #{arg5}
        MOV  r6, #{arg6}
"""
TAIL = """
        HALT
"""

# the loops, each over r3 words from r2 to r1 (fill: r5 the pattern)
SOFTWARE = {
    # fill_rows' COPY: eight stores a loop
    "fill": """
        LSR  r3, #3
.l:     MOV  [r1]+, r5
        MOV  [r1]+, r5
        MOV  [r1]+, r5
        MOV  [r1]+, r5
        MOV  [r1]+, r5
        MOV  [r1]+, r5
        MOV  [r1]+, r5
        MOV  [r1]+, r5
        DEC  r3
        BNE  .l
""",
    # blit_rows, aligned: four words a loop
    "copy": """
        LSR  r3, #2
.l:     MOV  r12, [r2]+
        MOV  [r1]+, r12
        MOV  r12, [r2]+
        MOV  [r1]+, r12
        MOV  r12, [r2]+
        MOV  [r1]+, r12
        MOV  r12, [r2]+
        MOV  [r1]+, r12
        DEC  r3
        BNE  .l
""",
    # blit_rows, shifted by r6 bits: each source word rotated once, merged
    # with its neighbour under r0 = ~0 >> r6; two words a loop
    "shift": """
        MOV  r0, #-1
        LSR  r0, r6
        MOV  r11, #0
        LSR  r3, #1
.l:     MOV  r12, [r2]+
        ROR  r12, r6
        XOR  r11, r12
        AND  r11, r0
        XOR  r11, r12
        MOV  [r1]+, r11
        MOV  r11, [r2]+
        ROR  r11, r6
        XOR  r12, r11
        AND  r12, r0
        XOR  r12, r11
        MOV  [r1]+, r12
        DEC  r3
        BNE  .l
""",
    # expand: a glyph's byte (8 pixels) through a 256-word table of nibble
    # masks, into fg where set and bg where clear: bg ^ (mask & (fg ^ bg)),
    # r5 = fg ^ bg, r6 = bg, r4 the table
    "expand": """
.l:     MOVS r12, byte [r2]+
        MOV  r12, [r4 + r12*4]
        AND  r12, r5
        XOR  r12, r6
        MOV  [r1]+, r12
        DEC  r3
        BNE  .l
""",
}

# the block instructions (ucode.py), a row of up to 256 words at a time
# (here 240): the same jobs
CHUNK = 240


def _rows(body):
    return f"""
        MOV  r10, #{WORDS // CHUNK}
.l:     MOV  r3, #{CHUNK}
{body}
        DEC  r10
        BNE  .l
"""


MICRO = {
    "fill": "        MOV  r2, r5\n" + _rows("        .half 0x01FD            ; FILL"),
    "copy": _rows("        .half 0x02FD            ; COPY"),
    "shift": """
        MOV  r0, #-1
        LSR  r0, r6
        MOV  r5, #0
        MOV  r7, r6
        LSR  r7, #2             ; k
        LEA  r8, [.ops]
        MOV  r8, half [r8 + r7*2]
        LEA  r9, [.op]
        MOV  half [r9], r8      ; BLIT k
""" + _rows(".op:    .half 0x10FD") + """
        BRA  .end
.ops:   .half 0x10FD, 0x11FD, 0x12FD, 0x13FD, 0x14FD, 0x15FD, 0x16FD, 0x17FD
.end:
""",
    "expand": _rows("        .half 0x03FD            ; EXPAND"),
}

CASES = [("fill", 0, 0x11111111, 0), ("copy", 0, 0, 0),
         ("shift", 0, 0, 4), ("shift", 0, 0, 12), ("shift", 0, 0, 28),
         ("expand", TAB, 0x55555555, 0x22222222)]


def program(loop, arg4, arg5, arg6, n=WORDS):
    src = HEAD.format(dst=DST, src=SRC, n=n, arg4=arg4, arg5=arg5, arg6=arg6) + loop + TAIL
    return asmcore.assemble_text(isas.get("v2"), src) if hasattr(asmcore, "assemble_text") \
        else _assemble(src)


def _assemble(src):
    a = asmcore.Assembler(isas.get("v2"))
    a.load("bench.s", text=src)
    return a.assemble()


def setup(ram):
    """The expansion table, and a source."""
    for i in range(256):
        m = sum(0xF << (4 * k) for k in range(8) if i >> k & 1)
        ram[TAB + 4 * i:TAB + 4 * i + 4] = m.to_bytes(4, "little")
    for i in range(4 * WORDS + 16):
        ram[SRC + i] = (i * 37) & 0xFF


def run(loop, arg4, arg5, arg6, n=WORDS):
    """The program on the model: (ticks, the destination's words)."""
    img = program(loop, arg4, arg5, arg6, n)
    s = system.System()
    s.load(img)
    setup(s.ram)
    m = rtl.RTL(s).run(10_000_000)
    return m.ticks, bytes(s.ram[DST:DST + 4 * WORDS])


def ticks(loop, arg4, arg5, arg6):
    """Master ticks a word: the loop over WORDS words against over none,
    and the destination."""
    t, out = run(loop, arg4, arg5, arg6)
    t0, _ = run("", arg4, arg5, arg6, 0)
    return (t - t0) / WORDS, out


def table():
    """[(kernel, software ticks a word, block instruction's)], checking that
    both leave the same destination."""
    out = []
    for name, a4, a5, a6 in CASES:
        ts, ds = ticks(SOFTWARE[name], a4, a5, a6)
        tm, dm = ticks(MICRO[name], a4, a5, a6)
        if ds != dm:
            raise AssertionError(f"{name} {a6}: the block instruction's result differs")
        out.append((f"{name} {a6}" if name == "shift" else name, ts, tm))
    return out


def main(args=None):
    print(f"{'kernel':12s} {'software':>10s} {'block':>10s} {'speed-up':>9s}   ms a screen (38400 words)")
    for label, ts, tm in table():
        print(f"{label:12s} {ts:10.1f} {tm:10.1f} {ts / tm:8.2f}x   {ts * TICK * 38400 / 1e6:6.1f} "
              f"{tm * TICK * 38400 / 1e6:6.1f}")
    return 0
