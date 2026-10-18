"""What-if microcode: block instructions the software here wanted, added
to a copy of the mini's control store (studies/mini/ucode.py, untouched)
in FD's free encodings, to measure what they'd buy. Microcode costs no
chips, so these are options for the mini as it is.

    FD 04  FILLX    r3 words from r1: each XORed with r2 (rubber bands,
                    carets, selections)

They're written as ucode.py's block instructions are (block_routine), and
built by wrapping its classify and routine while a Microcode is made.
sim.machine(mc=extended()) runs them.
"""

from heron.studies.mini import ucode as uc

NEW = {}


def _fillx():
    """FILLX: MAR <- r1, LC <- -r3 (CL from the count, tested the cycle
    after: a branch reads the latch as its cycle starts); then each word
    read at MAR, XORed with r2 into R, and written back; r1 <- r1 + 4 r3."""
    name = "FILLX"
    finish = uc.chain(name, uc.mi(ra=3, alu="passa", ldr=1),
                      uc.mi(a="r2", sina="0", alu="dbl", cin="0", ldr=1),
                      uc.end(name, a="r", rb=1, alu="add", w=1))
    steps = [uc.mi(mem="read", size="word"),
             uc.mi(ra=2, b="t", alu="xor", ldr=1),
             uc.mi(a="r", mem="write", size="word", marinc=1, lcinc=1)]
    nodes = [uc.Node(f, None, name) for f in steps]
    for a, b in zip(nodes, nodes[1:]):
        a.succ = ("next", b)
    nodes[-1].succ = ("branch", uc.CONDS["tc"], nodes[0], finish)
    count = uc.chain(name, uc.mi(a="r", rb=3, alu="sub", ldlc=1, ldcl="zero"),
                     uc.branch(name, uc.mi(), "cl", nodes[0], uc.end(name)))
    return uc.chain(name, uc.mi(ra=1, alu="passa", ldmar=1), uc.mi(kv=0, alu="passb", ldr=1),
                    count)


NEW[0x04] = _fillx

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
