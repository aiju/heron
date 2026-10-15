"""Cycles on the draft 1b hardware, for runs too long for its RTL model.

The RTL model (studies/v1b_hw/rtl.py) runs the microcode and gives the
hardware's exact cycles, about 100,000 a second. The suites take it in
seconds; Egret and the desktop run for hundreds of millions of cycles. For
those, a run's timing keys are costed here instead:

- calls, returns, jumps, SAVE, RESTORE, and pushes and pops: exactly what
  their microcode routine takes, push or link (ucode.built(link)), worked
  out from a representative instruction;
- everything else: the timing model calibrated on the hardware
  (studies/v1b_tradeoffs/cycles.py, HARDWARE), which comes within 0.1% of
  the RTL model over the suite.

The model on its own counts a call and a return a cycle short each, and an
extra register in SAVE a cycle short, which is most of what the link
register changes; so those are taken from the microcode.
"""

from functools import lru_cache

from heron.infra import asm as asmcore
from heron.studies.v1_isa import v1b
from heron.studies.v1b_hw import ucode as uc
from heron.studies.v1b_tradeoffs import cycles as tradeoffs

# An instruction with each timing key's shape: (kind, how or ea, parcels)
_SHAPES = {
    ("call", "rel", 1): "BSR  x",
    ("call", "rel", 2): "CALL x",
    ("call", "abs", 2): "CALL #0x1234",
    ("call", "abs", 3): "CALL #0x12345678",
    ("call", "reg", 1): "CALL r9",
    ("callm", "r", 1): "CALL [r9]",
    ("callm", "rd", 1): "CALL [sp + 4]",
    ("callm", "rd", 2): "CALL [r9 + 8]",
    ("callm", "pi", 1): "CALL [r9]+",
    ("callm", "pd", 1): "CALL -[r9]",
    ("callm", "idx", 2): "CALL [r2 + r3*4]",
    ("callm", "abs", 2): "CALL [0x1000]",
    ("callm", "abs", 3): "CALL [0x12345678]",
    ("callm", "pc", 2): "CALL [pc + x]",
    ("jmp", "rel", 2): "JMP  x",
    ("jmp", "abs", 2): "JMP  #0x1234",
    ("jmp", "abs", 3): "JMP  #0x12345678",
    ("jmp", "reg", 1): "JMP  r9",
    ("jmpm", "r", 1): "JMP  [r9]",
    ("jmpm", "rd", 1): "JMP  [sp + 4]",
    ("jmpm", "rd", 2): "JMP  [r9 + 8]",
    ("jmpm", "pi", 1): "JMP  [r9]+",
    ("jmpm", "pd", 1): "JMP  -[r9]",
    ("jmpm", "idx", 2): "JMP  [r2 + r3*4]",
    ("jmpm", "abs", 2): "JMP  [0x1000]",
    ("jmpm", "abs", 3): "JMP  [0x12345678]",
    ("jmpm", "pc", 2): "JMP  [pc + x]",
    ("ret", None, 1): "RET",
    ("st", "pd", 1): "ST   r7, -[sp]",
    ("ld", "pi", 1): "MOV  r7, [sp]+",
}
# v1bl's calls run the call instructions' routines from the link microcode
_LINK = {"link": "call", "linkm": "callm"}


def _routine_cycles(text, link):
    """Cycles of the microcode routine one instruction runs (a straight
    routine; the indexed mode's dispatch picks by the extension parcel)."""
    img = asmcore.assemble_text(v1b, "x:\n        " + text + "\n")
    words = [st.words for st in img.stmts if st.kind == "insn"][0]
    mc = uc.built(link)
    node, n = mc.entry[uc.classify(words[0])], 0
    while True:
        n += 1
        s = node.succ
        if s[0] == "decode":
            return n
        if s[0] == "next":
            node = s[1]
        elif s[0] == "dispatch":
            ext = words[1]
            node = s[1][(((ext >> 8) & 15) << 1) | int(ext & 0xFF != 0)]
        else:
            raise ValueError(f"{text}: the routine branches")


@lru_cache(maxsize=None)
def cycles(key):
    """Cycles of a timing key (parcels, pc & 2, kind, *params) on the 1b
    hardware."""
    n, kind, p = key[0], key[2], key[3:]
    if kind in ("save", "restore"):
        return _routine_cycles(f"{kind.upper()} r1-r{p[0]}", False)
    link = kind in _LINK
    shape = (_LINK.get(kind, kind), p[0] if p else None, n)
    if kind == "ld" and p[1] != 4 or kind == "st" and p[1] != 4:
        shape = None
    if shape in _SHAPES:
        return _routine_cycles(_SHAPES[shape], link)
    return tradeoffs.HARDWARE.cycles(key)


def total(pc_keys):
    """A run's cycles on the 1b hardware, from Machine32.pc_keys."""
    return sum(count * cycles(k) for (_pc, k), count in pc_keys.items())
