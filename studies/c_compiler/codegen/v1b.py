"""Instruction selection for draft 1b (register + addressing mode).

What it tries to use:
- memory operands for MOV/ADD/SUB/CMP/AND/OR/XOR when a load has one user;
- every addressing mode: [r + d16], [r + rx*s + d8] (also with r0 or sp as
  the base), absolute and [label + r], stack slots;
- auto-increment ([r]+, byte [r]+) when a pointer is stepped by the access
  size right where it's used, as in *p++;
- the one-parcel constants -16..15, INC/DEC, and LEA as a three-address add;
- CALL/JMP through memory, and JMP [table + r*4] for dense switches.
"""

from heron.studies.c_compiler.ir.ir import Instr, Const, SymAddr, Param
from .mir import R0, SP, VReg, Imm, Mem, Frame, Label, MInstr
from .target import Target, COND, SWAP, CALLER_SAVED
from .addr import decompose, fits

ALU = {"add": "ADD", "sub": "SUB", "and": "AND", "or": "OR", "xor": "XOR"}
SHIFT = {"shl": "LSL", "shr": "LSR", "sar": "ASR", "rotr": "ROR"}
UNARY = {"neg": "NEG", "not": "NOT", "sext8": "SXB", "zext8": "ZXB", "sext16": "SXH",
         "zext16": "ZXH"}
SIZE_KW = {1: "byte ", 2: "half ", 4: ""}


class V1B(Target):
    SMALL_ADD = (-16, 15)
    IMM_OPS = ("ADD", "SUB", "CMP", "AND", "OR", "XOR")

    @staticmethod
    def free_imm(op, c):
        """Can instruction op take constant c without costing more than a
        register operand would?"""
        if not hasattr(c, "signed"):
            return False                    # an address: one or two extension parcels
        v = c.signed
        if op in ("mul", "divs", "divu", "rems", "remu"):
            return False                    # register operands only
        if op == "add" and v in (1, -1):
            return True                     # INC / DEC
        return -16 <= v <= 15

    # ---- operands ------------------------------------------------------

    def mem_load_ok(self, v):
        """v is a load that can be an operand of an ALU instruction."""
        return self.is_folded(v, ("load",)) and (v.size == 4 or not v.signed)

    def ea(self, v):
        if isinstance(v, Const):
            return Imm(v.signed)
        if isinstance(v, SymAddr):
            return Imm(self.sym_expr(v))
        if self.mem_load_ok(v):
            return self.mem_for(v)
        return self.reg(v)

    def move_into(self, d, v):
        if isinstance(v, Const) and v.value == 0:
            self.emit("MOV", [d, Imm(0)], defs=[d], flags="nz")
            return
        e = self.ea(v)
        if isinstance(e, (Imm, Mem)):
            self.emit("MOV", [d, e], defs=[d], flags="nz")
        else:
            self.copy(d, e)

    load_value = move_into

    def load_word(self, d, mem):
        self.emit("MOV", [d, mem], defs=[d], flags="nz")

    def store_word(self, v, mem):
        r = self.reg(v)
        self.emit("ST", [r, mem], uses=[r])

    def spill_load(self, t, slot):
        return MInstr("MOV", [t, slot], defs=[t], uses=[SP], flags="nz")

    def spill_store(self, t, slot):
        return MInstr("ST", [t, slot], uses=[t, SP])

    def mem_for(self, i):
        """The memory operand for load or store i (doing its pointer step
        if it absorbed one)."""
        addr = i.args[0] if i.op == "load" else i.args[1]
        if i in self.postinc:
            a = self.postinc[i]
            va = self.def_reg(a)
            self.copy(va, self.reg(addr))
            return Mem(va, size=i.size, postinc=True)
        return self.encode(decompose(self, addr), i.size)

    def encode(self, p, size):
        """Turn an Addr into one 1b memory operand, computing what doesn't fit."""
        terms = list(p.terms)
        disp = p.disp
        frame = Frame("local", p.slot) if p.slot is not None else None
        if not terms:
            if p.slot is not None:
                return Mem(SP, disp=disp, frame=frame, size=size)
            if p.sym is not None:
                return Mem(None, disp=disp, sym=self.symname(p.sym), size=size)
            return Mem(None, disp=disp, size=size)
        if len(terms) == 1:
            x, s = terms[0]
            if p.slot is not None:
                off = self.mf.local_offset_known(p.slot) + disp
                if fits(off, 8):
                    return Mem(SP, index=self.reg(x), scale=s, disp=disp, frame=frame, size=size)
            elif p.sym is not None:
                if s == 1 and self.near(p.sym, disp):
                    return Mem(self.reg(x), disp=disp, sym=self.symname(p.sym), size=size)
                b = self.const_reg(self.sym_expr(SymAddr(p.sym, disp)))
                return Mem(b, index=self.reg(x), scale=s, size=size)
            elif s == 1:
                if fits(disp, 16):
                    return Mem(self.reg(x), disp=disp, size=size)
            elif fits(disp, 8):
                return Mem(R0, index=self.reg(x), scale=s, disp=disp, size=size)
        elif len(terms) == 2 and p.slot is None and p.sym is None and fits(disp, 8):
            (x, sx), (y, sy) = terms
            if sx != 1 and sy == 1:
                (x, sx), (y, sy) = (y, sy), (x, sx)
            if sx == 1:
                return Mem(self.reg(x), index=self.reg(y), scale=sy, disp=disp, size=size)
        # compute the address (all but a 16-bit displacement) into a register
        base = None
        if p.slot is not None:
            base = VReg()
            self.emit("LEA", [base, Mem(SP, frame=frame)], defs=[base])
        elif p.sym is not None:
            base = self.const_reg(self.sym_expr(SymAddr(p.sym, 0)))
        for x, s in terms:
            r = self.reg(x)
            if base is None and s == 1:
                base = r
                continue
            t = VReg()
            if base is None:
                self.copy(t, r)
                self.emit("LSL", [t, Imm(s.bit_length() - 1)], defs=[t], uses=[t], flags="nz")
            else:
                self.emit("LEA", [t, Mem(base, index=r, scale=s)], defs=[t])
            base = t
        if not fits(disp, 16):
            t = VReg()
            self.copy(t, base)
            self.emit("ADD", [t, Imm(disp)], defs=[t], uses=[t], flags="nz")
            base, disp = t, 0
        return Mem(base, disp=disp, size=size)

    def fmt_mem(self, m):
        kw = SIZE_KW[m.size]
        if m.postinc:
            return f"{kw}[{self.fmt(m.base)}]+"
        d = self.mem_disp(m)
        if m.index is not None:
            ds = f" + {d}" if d > 0 else (f" - {-d}" if d < 0 else "")
            return f"{kw}[{self.fmt(m.base)} + {self.fmt(m.index)}*{m.scale}{ds}]"
        if m.sym is not None:
            s = m.sym + (f"{d:+d}" if d else "")
            if m.base is not None:
                return f"{kw}[{s} + {self.fmt(m.base)}]"
            return f"{kw}[{s}]"
        if m.base is None:
            return f"{kw}[{d}]"
        ds = f" + {d}" if d > 0 else (f" - {-d}" if d < 0 else "")
        return f"{kw}[{self.fmt(m.base)}{ds}]"

    def adjust_sp(self, n):
        if 0 < n <= 15:
            return [f"        ADD  sp, #{n}"]
        if -15 <= n < 0:
            return [f"        SUB  sp, #{-n}"]
        return [f"        LEA  sp, [sp {'+' if n > 0 else '-'} {abs(n)}]"]

    # ---- auto-increment --------------------------------------------------

    def find_postinc(self, b):
        """Pair a load or store through p with `p + size` in the same block,
        when those are p's only uses: the access becomes [p]+."""
        for i in b.instrs:
            if i.op not in ("load", "store") or i.size == 2:
                continue
            p = i.args[0] if i.op == "load" else i.args[1]
            if not isinstance(p, (Instr, Param)) or self.ucount.get(p, 0) != 2:
                continue
            if i.op == "store" and i.args[0] is p:
                continue
            adds = [u for u in self.users.get(p, []) if u is not i]
            if len(adds) != 1:
                continue
            a = adds[0]
            if (a.op != "add" or a.block is not b or a.args[0] is not p
                    or not isinstance(a.args[1], Const) or a.args[1].value != i.size
                    or a in self.foldable or a in self.absorbed):
                continue
            # every use of the stepped pointer comes after the access
            at = self.ep.get(i, self.pos[i])
            if any(u.block is b and u.op != "phi" and self.ep.get(u, self.pos[u]) <= at
                   for u in self.users.get(a, [])):
                continue
            self.absorbed[a] = i
            self.postinc[i] = a

    # ---- selection -------------------------------------------------------

    def sel_load(self, i):
        d = self.def_reg(i)
        m = self.mem_for(i)
        self.emit("MOV", [d, m], defs=[d], flags="nz")
        if i.signed:
            self.emit("SXB" if i.size == 1 else "SXH", [d, d], defs=[d], uses=[d], flags="nz")

    def sel_store(self, i):
        v = i.args[0]
        r = self.reg(v)
        m = self.mem_for(i)
        self.emit("ST", [r, m], uses=[r])

    def sel_binop(self, i):
        op = i.op
        a, b = i.args
        d = self.def_reg(i)
        if op in ALU:
            if op == "add":
                if isinstance(b, Const) and b.signed in (1, -1) and not isinstance(a, Const):
                    r = self.reg(a)
                    self.emit("INC" if b.signed == 1 else "DEC", [d, r], defs=[d], uses=[r],
                              flags="nz")
                    return
                if self.try_lea(i, d):
                    return
            if op in ("add", "and", "or", "xor"):
                if (isinstance(a, (Const, SymAddr)) or self.mem_load_ok(a)) and \
                        not (isinstance(b, (Const, SymAddr)) or self.mem_load_ok(b)):
                    a, b = b, a
                elif (not isinstance(b, (Const, SymAddr)) and not self.mem_load_ok(b)
                      and self.prefer_second(a, b, i)):
                    a, b = b, a
            self.move_into(d, a)
            e = self.ea(b)
            self.emit(ALU[op], [d, e], defs=[d], uses=[d] + ([e] if not isinstance(e, (Imm, Mem)) else []),
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
        if op == "mul":
            if isinstance(a, Const) and not isinstance(b, Const):
                a, b = b, a
            self.move_into(d, a)
            r = self.reg(b)
            self.emit("MULS", [d, r], defs=[d], uses=[d, r], flags="nz")
            return
        if op in ("divs", "divu", "rems", "remu"):
            self.sel_divmod(i)
            return
        raise AssertionError(op)

    def sel_divmod(self, i):
        partner = self.divmod_partner(i)
        q, r = (i, partner) if i.op in ("divs", "divu") else (partner, i)
        a, b = i.args
        t = self.def_reg(q) if q is not None else VReg()
        self.move_into(t, a)
        rb = self.reg(b)
        self.emit("DIVS" if i.op in ("divs", "rems") else "DIVU", [t, rb], defs=[t],
                  uses=[t, rb], flags="nz")
        if r is not None:
            d = self.def_reg(r)
            self.emit("MFHI", [d], defs=[d])

    def encodable(self, p):
        """p fits one addressing mode (what encode() can do without
        computing part of the address first)."""
        terms, disp = p.terms, p.disp
        if not terms:
            return True
        if len(terms) == 1:
            x, s = terms[0]
            if p.slot is not None:
                return fits(self.mf.local_offset_known(p.slot) + disp, 8)
            if p.sym is not None:
                return s == 1 and self.near(p.sym, disp) or s != 1
            return fits(disp, 16) if s == 1 else fits(disp, 8)
        if len(terms) == 2 and p.slot is None and p.sym is None and fits(disp, 8):
            return any(s == 1 for _, s in terms)
        return False

    def try_lea(self, i, d):
        """An add that one LEA can do, without a copy: [r + d16],
        [r + rx*s + d8], [sp + slot], [label + r]. Returns False, having
        emitted nothing, when another instruction does it better."""
        a, b = i.args
        if self.mem_load_ok(a) or self.mem_load_ok(b):
            return False
        p = decompose(self, i, root=True)
        terms = p.terms
        if p.slot is None and p.sym is None:
            if len(terms) == 1 and terms[0][1] == 1:
                lo, hi = self.SMALL_ADD
                if lo <= p.disp <= hi and self.dies_here(terms[0][0], i):
                    return False
            if len(terms) == 2 and all(s == 1 for _, s in terms) and p.disp == 0:
                if self.dies_here(terms[0][0], i) or self.dies_here(terms[1][0], i):
                    return False
            if not terms:
                return False
        if p.sym is not None and not terms:
            return False
        if not self.encodable(p):
            return False
        m = self.encode(p, 4)
        self.emit("LEA", [d, m], defs=[d])
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
        elif self.mem_load_ok(a) and not self.mem_load_ok(b) and not isinstance(b, (Const, SymAddr)):
            a, b, cc = b, a, SWAP[cc]
        r = self.reg(a)
        e = self.ea(b)
        self.emit("CMP", [r, e], uses=[r] + ([e] if not isinstance(e, (Imm, Mem)) else []),
                  flags="cmp")
        return cc

    def test(self, a, b):
        ra = self.reg(a)
        rb = self.reg(b)
        self.emit("TST", [ra, rb], uses=[ra, rb], flags="cmp")
        return "NE"

    def call_target(self, callee):
        if self.is_folded(callee, ("load",)) and callee.size == 4:
            return self.mem_for(callee)
        return super().call_target(callee)

    def emit_call(self, target, uses):
        if isinstance(target, Mem):
            self.emit("CALL", [target], defs=list(CALLER_SAVED), uses=uses)
            return
        super().emit_call(target, uses)

    def jump_table(self, r, lo, span, label, default, table):
        t = r
        if lo:
            t = VReg()
            self.emit("LEA", [t, Mem(r, disp=-lo)], defs=[t])
        self.emit("CMP", [t, Imm(span)], uses=[t], flags="cmp")
        self.emit("BCC", [Label(default)], cond="HS", targets=[default])
        # PC-relative: the table is in the function's own section, so it is
        # in reach wherever the linker puts the function
        base = VReg()
        self.emit("LEA", [base, f"[pc + {label}]"], defs=[base])
        self.emit("JMPM", [Mem(base, index=t, scale=4)], targets=list(dict.fromkeys(table)))

    def inline_copy(self, dst, src, size, align):
        unit = 4 if align >= 4 and size % 4 == 0 else (2 if align >= 2 and size % 2 == 0 else 1)
        ps, pd = VReg(), VReg()
        self.copy(ps, src)
        self.copy(pd, dst)
        for k in range(size // unit):
            t = VReg()
            if unit == 2:
                self.emit("MOV", [t, Mem(ps, disp=2 * k, size=2)], defs=[t], flags="nz")
                self.emit("ST", [t, Mem(pd, disp=2 * k, size=2)], uses=[t])
            else:
                self.emit("MOV", [t, Mem(ps, size=unit, postinc=True)], defs=[t], flags="nz")
                self.emit("ST", [t, Mem(pd, size=unit, postinc=True)], uses=[t])

    # ---- after allocation ------------------------------------------------

    def format_instr(self, i):
        if i.op == "JMPM":
            return [f"        JMP  {self.fmt(i.ops[0])}"]
        return super().format_instr(i)

    def peephole(self):
        for b in self.mf.blocks:
            out = []
            for i in b.instrs:
                prev = out[-1] if out else None
                # MOV rd, rs; ADD rd, x  ->  LEA rd, [rs + x]
                if (prev is not None and prev.op == "COPY" and i.op == "ADD"
                        and i.ops[0] is prev.ops[0] and prev.ops[1] is not SP
                        and prev.ops[1] is not R0 and not self.flags_used_after(b, i)):
                    rd, rs, x = prev.ops[0], prev.ops[1], i.ops[1]
                    m = None
                    if isinstance(x, Imm) and isinstance(x.value, int) and fits(x.value, 16):
                        m = Mem(rs, disp=x.value)
                    elif x.__class__.__name__ == "PReg" and x is not rd:
                        m = Mem(rs, index=x, scale=1)
                    if m is not None:
                        out[-1] = MInstr("LEA", [rd, m], defs=[rd], uses=m.regs())
                        continue
                out.append(i)
            b.instrs = out
        super().peephole()

    def flags_used_after(self, b, i):
        k = b.instrs.index(i)
        for j in b.instrs[k + 1:]:
            if j.op == "BCC" or j.op.startswith("SET"):
                return True
            if j.flags in ("cmp", "nz") or j.op in ("BSR", "CALL", "JMP", "RET", "JMPM"):
                return False
        return False
