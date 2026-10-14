"""ISA v1bs: draft 1b with this study's system extensions (system.md): a
supervisor mode, register banks, the flat page map and cross-mode loads
and stores. The simulator runs it (studies/v1_isa/isa, Isa::V1bs, sys.rs)
and the assembler has its encoder (asm/v1bs.rs); this is the
disassembler's side."""

from heron.studies.v1_isa.v1b import *  # noqa: F401,F403
from heron.studies.v1_isa.v1b import disassemble as _dis, kind as _kind
from heron.studies.v1_isa.v1common import R

NAME = "v1bs"
DESCRIPTION = "draft 1b with a supervisor mode, register banks and a page map (the kernel study)"

SR_NAMES = ["flags", "hi", "far", "fsr", "ctx", "mapa", "mapd", "bank", "sysctl"]


def _sr(n):
    return SR_NAMES[n] if n < len(SR_NAMES) else str(n)


def disassemble(ws, pc=0, symbols=None):
    w = ws[0]
    if w >> 12 == 0:
        a, b, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
        if f == 10:
            return f"MFSR {R(a)}, {_sr(b)}", 1
        if f == 11:
            return f"MTSR {_sr(a)}, {R(b)}", 1
        if f == 14:
            return f"MFUR {R(a)}, {R(b)}", 1
        if f == 15:
            return f"MTUR {R(a)}, {R(b)}", 1
    return _dis(ws, pc, symbols)


def kind(ws):
    w = ws[0]
    if w >> 12 == 0 and w & 15 in (14, 15):
        return "MFUR" if w & 15 == 14 else "MTUR"
    return _kind(ws)
