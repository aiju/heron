"""ISA v1bx: draft 1b with this study's experimental extensions for Lisp
(isa.md). The simulator runs it (studies/v1_isa/isa, Isa::V1bx); the
runtime is still assembled as 1b, and the compiler writes the new
instructions itself, so only the name differs here."""

from heron.studies.v1_isa.v1b import *  # noqa: F401,F403
from heron.studies.v1_isa.v1b import disassemble as _dis, kind as _kind

NAME = "v1bx"
DESCRIPTION = "draft 1b with a tagged register mode (the Lisp study's experiment)"


def disassemble(ws, pc=0, symbols=None):
    w = ws[0]
    if 1 <= w >> 12 <= 9 and w >> 12 not in (2, 3) and (w >> 4) & 15 == 0xE:
        ops = {1: "MOV", 4: "ADD", 5: "SUB", 6: "CMP", 7: "AND", 8: "OR", 9: "XOR"}
        return f"{ops[w >> 12]}.T r{(w >> 8) & 15}, r{w & 15}", 1
    return _dis(ws, pc, symbols)


def kind(ws):
    w = ws[0]
    if 1 <= w >> 12 <= 9 and (w >> 4) & 15 == 0xE:
        return "tagged"
    return _kind(ws)
