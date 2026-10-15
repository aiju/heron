"""Instruction selection for draft 1a (load/store).

What it tries to use: base + displacement and [label + r] addresses (the
assembler then picks the one-parcel short forms), immediate operands for
every ALU function (8-bit MVI/ADDI/CMPI where they fit), INC/DEC and LEA as
three-address adds, sign-extending loads, and a table jump for dense
switches.
"""

from heron.studies.c_compiler.ir.ir import Const, SymAddr
from .mir import R0, SP, VReg, Imm, Mem, Frame, Label, MInstr
from .target import Target, COND, SWAP
from .addr import decompose, fits

ALU = {"add": "ADD", "sub": "SUB", "and": "AND", "or": "OR", "xor": "XOR", "mul": "MULS"}
SHIFT = {"shl": "LSL", "shr": "LSR", "sar": "ASR", "rotr": "ROR"}
UNARY = {"neg": "NEG", "not": "NOT", "sext8": "SXB", "zext8": "ZXB", "sext16": "SXH",
         "zext16": "ZXH"}
LOADS = {(1, False): "LDB", (1, True): "LDSB", (2, False): "LDH", (2, True): "LDSH",
         (4, False): "LD", (4, True): "LD"}
STORES = {1: "STB", 2: "STH", 4: "ST"}


class V1A(Target):
    FOLD_LOADS = False      # load/store: no memory operands
    IMM_OPS = ("ADD", "SUB", "CMP", "AND", "OR", "XOR", "BIC", "TST", "MULU", "MULS",
               "DIVU", "DIVS", "ADC", "SBC")
    SMALL_ADD = (-128, 127)

    @staticmethod
    def free_imm(op, c, i=None):
        """Can instruction op take constant c without costing more than a
        register operand would? (MVI, ADDI and CMPI take 8 bits; the rest
        need an extension parcel.)"""
        if not hasattr(c, "signed"):
            return False
        v = c.signed
        if op in ("add", "sub") or op in ("eq", "ne", "lt", "le", "gt", "ge", "ltu", "leu", "gtu", "geu"):
            return -128 <= v <= 127
        return False

    # ---- operands ------------------------------------------------------

    def imm_or_reg(self, v):
        if isinstance(v, Const):
            return Imm(v.signed)
        if isinstance(v, SymAddr):
            return Imm(self.sym_expr(v))
        return self.reg(v)

    def move_into(self, d, v):
        if isinstance(v, (Const, SymAddr)):
            self.emit("MOV", [d, self.imm_or_reg(v)], defs=[d], flags="nz")
        else:
            self.copy(d, self.reg(v))

    load_value = move_into

    def load_word(self, d, mem):
        self.emit("LD", [d, mem], defs=[d], flags="nz")

    def store_word(self, v, mem):
        r = self.reg(v)
        self.emit("ST", [r, mem], uses=[r])

    def spill_load(self, t, slot):
        return MInstr("LD", [t, slot], defs=[t], uses=[SP], flags="nz")

    def spill_store(self, t, slot):
        return MInstr("ST", [t, slot], uses=[t, SP])

    def mem_for(self, i):
        addr = i.args[0] if i.op == "load" else i.args[1]
        long_ok = i.size == 1 and not i.signed or i.size == 4
        if i.op == "store":
            long_ok = i.size in (1, 4)
        return self.encode(decompose(self, addr), long_ok)

    def encode(self, p, long_ok=True):
        """One 1a memory operand: [r + disp], [label + disp], [label + r]."""
        disp = p.disp
        frame = Frame("local", p.slot) if p.slot is not None else None
        terms = list(p.terms)
        # fold all register terms into one register
        base = None
        fresh = False                   # base is a temporary we may change
        for x, s in sorted(terms, key=lambda t: t[1] == 1):
            r = self.reg(x)
            scaled = s != 1
            if scaled:
                t = VReg()
                self.copy(t, r)
                self.emit("LSL", [t, Imm(s.bit_length() - 1)], defs=[t], uses=[t], flags="nz")
                r = t
            if base is None:
                base, fresh = r, scaled
            elif fresh:
                self.emit("ADD", [base, r], defs=[base], uses=[base, r], flags="nz")
            elif scaled:
                self.emit("ADD", [r, base], defs=[r], uses=[r, base], flags="nz")
                base, fresh = r, True
            else:
                t = VReg()
                self.copy(t, base)
                self.emit("ADD", [t, r], defs=[t], uses=[t, r], flags="nz")
                base, fresh = t, True
        if p.slot is not None:
            if base is None:
                return Mem(SP, disp=disp, frame=frame)
            t = VReg()
            self.copy(t, base)
            self.emit("ADD", [t, SP], defs=[t], uses=[t], flags="nz")
            return Mem(t, disp=disp, frame=frame)
        if p.sym is not None:
            if long_ok or self.near(p.sym, disp):
                return Mem(base, disp=disp, sym=self.symname(p.sym))
            b = self.const_reg(self.sym_expr(SymAddr(p.sym, disp)))
            if base is None:
                return Mem(b)
            t = VReg()
            self.copy(t, b)
            self.emit("ADD", [t, base], defs=[t], uses=[t, base], flags="nz")
            return Mem(t)
        if base is None:
            if fits(disp, 16) or long_ok:
                return Mem(None, disp=disp)
            return Mem(self.const_reg(disp))
        if not fits(disp, 16) and not long_ok:
            t = VReg()
            self.copy(t, base)
            self.emit("ADD", [t, Imm(disp)], defs=[t], uses=[t], flags="nz")
            return Mem(t)
        return Mem(base, disp=disp)

    def fmt_mem(self, m):
        d = self.mem_disp(m)
        if m.sym is not None:
            s = m.sym + (f"{d:+d}" if d else "")
            if m.base is not None:
                return f"[{s} + {self.fmt(m.base)}]"
            return f"[{s}]"
        if m.base is None:
            return f"[{d}]"
        ds = f" + {d}" if d > 0 else (f" - {-d}" if d < 0 else "")
        return f"[{self.fmt(m.base)}{ds}]"

    def adjust_sp(self, n):
        if -128 <= n <= 127:
            return [f"        ADDI sp, {n}"]
        return [f"        LEA  sp, [sp {'+' if n > 0 else '-'} {abs(n)}]"]

    # ---- selection -------------------------------------------------------

    def sel_load(self, i):
        d = self.def_reg(i)
        m = self.mem_for(i)
        self.emit(LOADS[(i.size, i.signed)], [d, m], defs=[d], flags="nz")

    def sel_store(self, i):
        r = self.reg(i.args[0])
        m = self.mem_for(i)
        self.emit(STORES[i.size], [r, m], uses=[r])

    def sel_binop(self, i):
        op = i.op
        a, b = i.args
        d = self.def_reg(i)
        if op == "add":
            if isinstance(b, Const) and b.signed in (1, -1) and not isinstance(a, Const):
                r = self.reg(a)
                self.emit("INC" if b.signed == 1 else "DEC", [d, r], defs=[d], uses=[r], flags="nz")
                return
            if self.try_lea(i, d):
                return
        if op in ("divs", "divu"):
            self.sel_divmod(i)
            return
        if op in ALU:
            if op in ("add", "and", "or", "xor", "mul"):
                if isinstance(a, (Const, SymAddr)) and not isinstance(b, (Const, SymAddr)):
                    a, b = b, a
                elif not isinstance(b, (Const, SymAddr)) and self.prefer_second(a, b, i):
                    a, b = b, a
            self.move_into(d, a)
            if op == "add" and isinstance(b, Const) and -128 <= b.signed <= 127:
                self.emit("ADDI", [d, str(b.signed)], defs=[d], uses=[d], flags="nz")
                return
            e = self.imm_or_reg(b)
            self.emit(ALU[op], [d, e], defs=[d], uses=[d] + ([] if isinstance(e, Imm) else [e]),
                      flags="nz")
            return
        if op in SHIFT:
            self.move_into(d, a)
            if isinstance(b, Const):
                self.emit(SHIFT[op], [d, Imm(b.value & 31)], defs=[d], uses=[d], flags="nz")
            else:
                r = self.reg(b)
                self.emit(SHIFT[op], [d, r], defs=[d], uses=[d, r], flags="nz")
            return
        if op in ("rems", "remu"):
            self.sel_divmod(i)
            return
        raise AssertionError(op)

    def sel_divmod(self, i):
        partner = self.divmod_partner(i)
        q, r = (i, partner) if i.op in ("divs", "divu") else (partner, i)
        a, b = i.args
        t = self.def_reg(q) if q is not None else VReg()
        self.move_into(t, a)
        e = self.imm_or_reg(b)
        self.emit("DIVS" if i.op in ("divs", "rems") else "DIVU", [t, e], defs=[t],
                  uses=[t] + ([] if isinstance(e, Imm) else [e]), flags="nz")
        if r is not None:
            d = self.def_reg(r)
            self.emit("MFHI", [d], defs=[d])

    def try_lea(self, i, d):
        p = decompose(self, i, root=True)
        terms = p.terms
        if any(s != 1 for _, s in terms) or len(terms) > 1:
            return False
        if p.slot is not None:
            if terms:
                return False
            self.emit("LEA", [d, Mem(SP, disp=p.disp, frame=Frame("local", p.slot))], defs=[d])
            return True
        if p.sym is not None:
            m = Mem(self.reg(terms[0][0]) if terms else None, disp=p.disp, sym=self.symname(p.sym))
            self.emit("LEA", [d, m], defs=[d])
            return True
        if not terms:
            return False
        x = terms[0][0]
        lo, hi = self.SMALL_ADD
        if lo <= p.disp <= hi and self.dies_here(x, i):
            return False
        if not fits(p.disp, 16):
            return False
        r = self.reg(x)
        self.emit("LEA", [d, Mem(r, disp=p.disp)], defs=[d])
        return True

    def sel_unop(self, i):
        a = i.args[0]
        d = self.def_reg(i)
        if i.op == "copy":
            self.move_into(d, a)
            if isinstance(a, (Const, SymAddr)):
                mi = self.blk.instrs[-1]
                d.remat, mi.remat_of = mi, d
            return
        r = self.reg(a)
        self.emit(UNARY[i.op], [d, r], defs=[d], uses=[r], flags="nz")

    def compare(self, op, a, b):
        cc = COND[op]
        if isinstance(a, (Const, SymAddr)) and not isinstance(b, (Const, SymAddr)):
            a, b, cc = b, a, SWAP[cc]
        r = self.reg(a)
        e = self.imm_or_reg(b)
        self.emit("CMP", [r, e], uses=[r] + ([] if isinstance(e, Imm) else [e]), flags="cmp")
        return cc

    def test(self, a, b):
        if isinstance(a, Const):
            a, b = b, a
        ra = self.reg(a)
        e = self.imm_or_reg(b)
        self.emit("TST", [ra, e], uses=[ra] + ([] if isinstance(e, Imm) else [e]), flags="cmp")
        return "NE"

    def jump_table(self, r, lo, span, label, default, table):
        t = VReg()
        if lo:
            self.emit("LEA", [t, Mem(r, disp=-lo)], defs=[t])
        else:
            self.copy(t, r)
        self.emit("CMP", [t, Imm(span)], uses=[t], flags="cmp")
        self.emit("BCC", [Label(default)], cond="HS", targets=[default])
        self.emit("LSL", [t, Imm(2)], defs=[t], uses=[t], flags="nz")
        self.emit("LD", [t, Mem(t, sym=label)], defs=[t], uses=[t], flags="nz")
        self.emit("JMPR", [t], uses=[t], targets=list(dict.fromkeys(table)))

    def inline_copy(self, dst, src, size, align):
        unit = 4 if align >= 4 and size % 4 == 0 else (2 if align >= 2 and size % 2 == 0 else 1)
        ld = {4: "LD", 2: "LDH", 1: "LDB"}[unit]
        st = {4: "ST", 2: "STH", 1: "STB"}[unit]
        for k in range(size // unit):
            t = VReg()
            self.emit(ld, [t, Mem(src, disp=unit * k)], defs=[t], flags="nz")
            self.emit(st, [t, Mem(dst, disp=unit * k)], uses=[t])

    # ---- after allocation ------------------------------------------------

    def emit_text(self):
        # A jump table is read as [t + table]: declared .far, the table gets
        # a 32-bit displacement, which reaches it wherever the function goes
        far = "".join(f"        .far {label}\n" for label, _ in self.mf.consts)
        return far + super().emit_text()

    def format_instr(self, i):
        if i.op == "JMPR":
            return [f"        JMP  {self.fmt(i.ops[0])}"]
        return super().format_instr(i)

    def peephole(self):
        for b in self.mf.blocks:
            out = []
            for i in b.instrs:
                prev = out[-1] if out else None
                # MOV rd, rs; ADDI rd, c  ->  LEA rd, [rs + c]
                if (prev is not None and prev.op == "COPY" and i.op in ("ADDI", "ADD")
                        and i.ops[0] is prev.ops[0] and prev.ops[1] is not R0
                        and not self.flags_used_after(b, i)):
                    x = i.ops[1]
                    c = int(x) if isinstance(x, str) else (x.value if isinstance(x, Imm) else None)
                    if isinstance(c, int) and fits(c, 16):
                        rd, rs = prev.ops[0], prev.ops[1]
                        out[-1] = MInstr("LEA", [rd, Mem(rs, disp=c)], defs=[rd], uses=[rs])
                        continue
                out.append(i)
            b.instrs = out
        super().peephole()

    def flags_used_after(self, b, i):
        k = b.instrs.index(i)
        for j in b.instrs[k + 1:]:
            if j.op == "BCC" or j.op.startswith("SET"):
                return True
            if j.flags in ("cmp", "nz") or j.op in ("BSR", "CALL", "JMP", "RET", "JMPR"):
                return False
        return False
