"""A fixed-base mode for struct fields, [rT + 4R], measured on draft 1b.
See README.md.

The simulator and the assembler know the mode by the ISA's name: v1b+rtN,
v1bx+rtN and v1bs+rtN are 1b, the Lisp's v1bx and the kernel's v1bs with
mode E the word at rN + 4R (studies/v1_isa/isa, Isa::parse). isa() makes
the Python side of such an ISA: a module the tools can use, registered
under that name."""

import sys
import types

import heron.studies.kernel  # noqa: F401  (registers v1bs)
import heron.studies.lisp  # noqa: F401  (registers v1bx)
import heron.studies.v1_isa  # noqa: F401  (registers v1b)
from heron.infra import isas

EA_OPS = {1: "MOV", 2: "ST", 3: "LEA", 4: "ADD", 5: "SUB", 6: "CMP", 7: "AND", 8: "OR",
          9: "XOR"}
# v1bx+rtN: the tagged register operations are op F's functions 9-E
TAGGED = ["MOV", "ADD", "SUB", "CMP", "AND", "OR"]


def isa(base, rt):
    """The ISA module for `base` (v1b, v1bx or v1bs) with rT = r`rt`."""
    name = f"{base}+rt{rt}"
    modname = f"{__name__}.isa_{base}_rt{rt}"
    if modname in sys.modules:
        return sys.modules[modname]
    b = isas.get(base)
    mod = types.ModuleType(modname)
    mod.__dict__.update({k: v for k, v in vars(b).items() if not k.startswith("__")})
    mod.NAME = name
    mod.DESCRIPTION = f"{base} with mode E the word at [r{rt} + 4R]"

    def disassemble(ws, pc=0, symbols=None):
        w = ws[0]
        op, d, m, r = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
        if m == 0xE and op in EA_OPS:
            return f"{EA_OPS[op]} r{d}, [r{rt} + {4 * r}]", 1
        if m == 0xE and op == 0xB and d < 2:
            return f"{'CALL' if d else 'JMP'} [r{rt} + {4 * r}]", 1
        if base == "v1bx" and op == 0xF and 9 <= r <= 14:
            return f"{TAGGED[r - 9]}.T r{d}, r{m}", 1
        return b.disassemble(ws, pc, symbols)

    def kind(ws):
        w = ws[0]
        if base == "v1bx" and w >> 12 == 0xF and 9 <= (w & 15) <= 14:
            return "tagged"
        return b.kind(ws)

    mod.disassemble = disassemble
    mod.kind = kind
    sys.modules[modname] = mod
    isas.register(name, modname)
    return mod
