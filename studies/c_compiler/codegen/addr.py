"""Address expressions: an IR address split into a constant displacement,
at most one base object (a global symbol or a stack slot) and register
terms with scales. Targets turn these into whatever their addressing modes
can express, and compute the rest with instructions."""

from heron.studies.c_compiler.ir.ir import Instr, Const, SymAddr, Slot


class Addr:
    __slots__ = ("disp", "sym", "slot", "terms")

    def __init__(self, disp=0, sym=None, slot=None, terms=None):
        self.disp = disp
        self.sym = sym          # IR symbol name
        self.slot = slot        # IR Slot
        self.terms = terms or []  # [(IR value, scale)]

    def merge(self, o):
        if (self.sym or self.slot) and (o.sym or o.slot):
            return None
        return Addr(self.disp + o.disp, self.sym or o.sym, self.slot or o.slot,
                    self.terms + o.terms)


def decompose(sel, a, root=False, depth=0):
    """Split address a into an Addr. Only values the selector may fold
    (sel.is_folded) are taken apart, except the root when root=True."""
    if isinstance(a, Const):
        return Addr(disp=a.signed)
    if isinstance(a, SymAddr):
        return Addr(sym=a.name, disp=a.offset)
    if isinstance(a, Slot):
        return Addr(slot=a)
    if isinstance(a, Instr) and depth < 4 and (root or sel.is_folded(a)) and a not in sel.absorbed:
        if a.op == "add":
            l = decompose(sel, a.args[0], False, depth + 1)
            r = decompose(sel, a.args[1], False, depth + 1)
            m = l.merge(r)
            if m is not None:
                return m
        elif a.op == "sub" and isinstance(a.args[1], Const):
            l = decompose(sel, a.args[0], False, depth + 1)
            l.disp -= a.args[1].signed
            return l
        elif a.op == "shl" and isinstance(a.args[1], Const) and a.args[1].value <= 3:
            return Addr(terms=[(a.args[0], 1 << a.args[1].value)])
    return Addr(terms=[(a, 1)])


def fits(v, bits):
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))
