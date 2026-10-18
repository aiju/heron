"""What-if microcode: block instructions the software here wanted, added
to a copy of the mini's control store (studies/mini/ucode.py, untouched)
in FD's free encodings, to measure what they'd buy. Microcode costs no
chips, so these are options for the mini as it is. RFC 0042's X1 (EXPAND
for 8, 2 and 1 bits, a BLIT by a bit count) is here, and two more:

    FD 04  FILLX    r3 words from r1, each XORed with r2 (rubber bands,
                    carets, selections)
    FD 05  EXPANDT  EXPAND, transparent: each word d ^ ((d ^ r5) & m), m
                    the byte's mask from the table at r4 (text over
                    anything)
    FD 06  EXPAND2  2 bits a pixel: r3 words, each from two bytes at r2 up,
                    m = r4[b0] | r0[b1] (two tables of 256 masks), as
                    EXPAND: r6 ^ (m & r5)
    FD 07  EXPAND1  1 bit a pixel, linear: r3 words, each from a word at
                    r2 up as its own mask: r6 ^ (w & r5)
    FD 08  EXPAND8  8 bits a pixel: r3 bytes at r2 up, each two words from
                    a table at r4 of two masks a byte: r6 ^ (m & r5);
                    r1 ends 8 r3 bytes on
    FD 2n  BLITN n  BLIT by n bits (n = 0-31): each source word rotated
                    right by n and merged with the one before under r0 =
                    ~0 >> n; r5 the first lo, the last rotated on exit

Each is written as ucode.py's block instructions are (block_routine):
R <- 0; LC <- -r3 and CL <- (r3 == 0); MAR <- r1 in the cycle that
branches on CL; the loop through LC; r1 moved past the words. They're
built into a Microcode by wrapping ucode's classify and routine while it's
made; sim.machine(mc=extended()) runs them. New microwords have no static
timing analysis (studies/mini/ticks.json): timing.assign_classes gives
them estimated lengths, so their times are estimates.
"""

from heron.studies.mini import ucode as uc

NEW = {}
mi, chain, end, branch, Node = uc.mi, uc.chain, uc.end, uc.branch, uc.Node
TMP1, TMP2, TMP3 = uc.TMP1, uc.TMP2, uc.TMP3


def block(name, steps, scale=4, blit=False):
    """A block instruction around a loop of `steps` (the last one
    counting LC); r1 ends `scale` r3 bytes on."""
    doubling = {4: 1, 8: 2}[scale]
    tail = [mi(ra=3, alu="passa", ldr=1), mi(a="r2", sina="0", alu="dbl", cin="0", ldr=1)]
    tail += [mi(a="r2", sina="0", alu="passa", ldr=1)] * (doubling - 1)
    finish = chain(name, *tail, end(name, a="r", rb=1, alu="add", w=1))
    if blit:
        finish = chain(name, mi(rb=TMP2, alu="passb", w=5), finish)
    nodes = [Node(f, None, name) for f in steps]
    for a, b in zip(nodes, nodes[1:]):
        a.succ = ("next", b)
    nodes[-1].succ = ("branch", uc.CONDS["tc"], nodes[0], finish)
    setup = [mi(ra=5, alu="passa", w=TMP2)] if blit else []
    setup += [mi(kv=0, alu="passb", ldr=1), mi(a="r", rb=3, alu="sub", ldlc=1, ldcl="zero")]
    start = branch(name, mi(ra=1, alu="passa", ldmar=1), "cl", nodes[0], end(name))
    return chain(name, *setup, start)


WRITE = mi(a="r", mem="write", size="word", marinc=1, lcinc=1)


def fillx():
    return block("FILLX", [mi(mem="read", size="word"),
                           mi(ra=2, b="t", alu="xor", ldr=1),
                           WRITE])


def mask_from_byte(table):
    """A byte at r2 (r2 steps) through the table at register `table`: the
    mask in T."""
    return [mi(mem="reada", size="byte", ra=2, kv=1, alu="add", w=2),
            mi(b="tbyte", alu="passb", ldr=1),
            mi(a="r2", sina="0", alu="dbl", cin="0", ldr=1),
            mi(a="r", rb=table, alu="add", w=TMP1),
            mi(mem="reada", size="word", ra=TMP1)]


def expandt():
    return block("EXPANDT", mask_from_byte(4) + [
        mi(b="t", alu="passb", w=TMP2),                 # m
        mi(mem="read", size="word"),                    # d
        mi(ra=5, b="t", alu="xor", ldr=1),              # d ^ fg
        mi(a="r", rb=TMP2, alu="and", ldr=1),           # & m
        mi(a="r", b="t", alu="xor", ldr=1),             # ^ d
        WRITE])


def expand2():
    return block("EXPAND2", mask_from_byte(4) + [
        mi(b="t", alu="passb", w=TMP2)] + mask_from_byte(0) + [
        mi(ra=TMP2, b="t", alu="or", ldr=1),            # m
        mi(a="r", rb=5, alu="and", ldr=1),
        mi(a="r", rb=6, alu="xor", ldr=1),
        WRITE])


def expand1():
    return block("EXPAND1", [
        mi(mem="reada", size="word", ra=2, kv=4, alu="add", w=2),
        mi(ra=5, b="t", alu="and", ldr=1),
        mi(a="r", rb=6, alu="xor", ldr=1),
        WRITE])


def expand8():
    w1 = mi(a="r", mem="write", size="word", marinc=1)
    return block("EXPAND8", [
        mi(mem="reada", size="byte", ra=2, kv=1, alu="add", w=2),
        mi(b="tbyte", alu="passb", ldr=1),
        mi(a="r2", sina="0", alu="dbl", cin="0", ldr=1),        # x 4
        mi(a="r2", sina="0", alu="passa", ldr=1),               # x 8
        mi(a="r", rb=4, alu="add", w=TMP1),
        mi(mem="reada", size="word", ra=TMP1),
        mi(ra=5, b="t", alu="and", ldr=1),
        mi(a="r", rb=6, alu="xor", ldr=1),
        w1,
        mi(ra=TMP1, kv=4, alu="add", w=TMP1),
        mi(mem="reada", size="word", ra=TMP1),
        mi(ra=5, b="t", alu="and", ldr=1),
        mi(a="r", rb=6, alu="xor", ldr=1),
        WRITE], scale=8)


def rot_bits(n):
    """Microinstructions rotating right by n bits, the first taking the
    word from T: whole bytes by the byte and half rotations, then up to four
    single bits right (the bit out back in at the top) or left (the
    doubling with bit 31 carried in)."""
    best = None
    for m in range(4):
        rem = (n - 8 * m) % 32
        if rem <= 4:
            bits = [mi(a="r", alu="passa", rms="shr", sin="f0", ldr=1)] * rem
        elif rem >= 28:
            bits = [mi(a="r", alu="dbl", cin="a31", ldr=1)] * (32 - rem)
        else:
            continue
        rots = {0: [], 1: ["ror8"], 2: ["ror16"], 3: ["ror16", "ror8"]}[m]
        first = [mi(b="t", alu="passb", rms=rots[0], ldr=1) if rots
                 else mi(b="t", alu="passb", ldr=1)]
        steps = first + [mi(a="r", alu="passa", rms=r, ldr=1) for r in rots[1:]] + bits
        if best is None or len(steps) < len(best):
            best = steps
    return best


def blitn(n):
    rot = rot_bits(n)
    rot[-1] = uc.merge(rot[-1], mi(w=TMP3))                      # hi
    return block(f"BLITN {n}", [mi(mem="reada", size="word", ra=2, kv=4, alu="add", w=2)] + rot
                 + [mi(a="r", rb=TMP2, alu="xor", ldr=1),             # lo ^ hi
                    mi(a="r", rb=0, alu="and", ldr=1),                # & mask
                    mi(a="r", rb=TMP3, alu="xor", ldr=1),             # ^ hi
                    mi(a="r", mem="write", size="word", marinc=1, lcinc=1,
                       rb=TMP3, alu="passb", w=TMP2)], blit=True)     # hi is the next lo


NEW.update({0x04: fillx, 0x05: expandt, 0x06: expand2, 0x07: expand1, 0x08: expand8})
for _n in range(32):
    NEW[0x20 + _n] = (lambda n: lambda: blitn(n))(_n)

_built = None


def extended():
    """The mini's microcode with NEW's instructions in FD's free cells."""
    global _built
    if _built is not None:
        return _built
    classify, routine = uc.classify, uc.routine

    def classify2(w):
        op, rb = w & 0xFF, w >> 8
        if op == 0xFD and rb in NEW:
            return ("whatif", rb)
        return classify(w)

    def routine2(key):
        if key[0] == "whatif":
            return NEW[key[1]]()
        return routine(key)

    uc.classify, uc.routine = classify2, routine2
    try:
        _built = uc.Microcode()
    finally:
        uc.classify, uc.routine = classify, routine
    return _built
