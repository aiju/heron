"""Instruction selection for draft 2 (RFC 0028; the v2_isa study's
isa-v2.md).

Draft 2 keeps 1b's addressing modes in its rows, so this is the 1b
selector (codegen.v1b) with what changed:
- r0 is a general register: allocated, caller-saved, and never read as
  zero. A zero store is CLR, any size and any mode; a zero operand is
  MOV rX, #0.
- MOV leaves the flags alone, loads and copies included. A MOV whose N and
  Z a compare with 0 or -1 would test becomes MOVS, and the compare goes.
- A store is written MOV [address], rs.
- The special mode's tables: [label + x*s] needs no base register, nor does
  [x*s + d], and a dense switch is one JMP [pc + table + r*4].
- INC and DEC on memory, for x++ and x-- on a variable in memory.
- TST and MULS with a constant.
- Calls leave the return address in r7, the link register (Target.LINK):
  a function that calls saves it with SAVE r7-rN, or pushes it, and a leaf
  that leaves r7 alone returns through it.
- MOV and CMP take 16..127 in one parcel (the assembler picks the form):
  free_imm knows, and keeps such a constant in a register only where CMP
  could then take a memory operand.
- DBNZ: loops whose counter only counts are counted down to zero
  (ir.passes.count_down), and DEC r; BNE back becomes DBNZ r when the loop
  fits its reach of 16 parcels.
"""

from heron.studies.c_compiler.ir import ir as I
from heron.studies.c_compiler.ir.ir import Instr, Const, SymAddr, Undef
from .mir import PHYS, SP, VReg, Imm, Mem, Label, MInstr
from .addr import fits
from .v1b import V1B, SIZE_KW


def is_zero(v):
    return v is Undef or isinstance(v, Const) and v.value == 0


class V2(V1B):
    # r0 is scratch like r1-r7; r7, the link register, comes last, since a
    # leaf that uses it has to save it
    ALLOC_ORDER = PHYS[1:7] + PHYS[0:1] + PHYS[7:15]
    CALLER_SAVED = PHYS[0:8]
    ZERO = None
    LINK = PHYS[7]
    IMM_OPS = V1B.IMM_OPS + ("TST", "MULS")
    COUNT_DOWN = True       # for DBNZ

    @staticmethod
    def free_imm(op, c, i=None):
        """Can instruction op (the IR instruction i) take constant c without
        costing more than a register operand would?"""
        if not hasattr(c, "signed"):
            return False                    # an address: one or two extension parcels
        v = c.signed
        if op in ("mul", "divs", "divu", "rems", "remu"):
            return False                    # a register, or a constant in an extension parcel
        if op == "add" and v in (1, -1):
            return True                     # INC / DEC
        if -16 <= v <= 15:
            return True                     # the quick constants
        if op in I.CMPOPS and 16 <= v <= 127:
            # CMP's 7-bit form; but against a load only it uses, a constant
            # in a register makes CMP rK, [address]: one instruction, not a
            # load and a CMP
            return i is None or not any(V2.memory_operand(a, i) for a in i.args)
        return False

    @staticmethod
    def memory_operand(a, i):
        """Could load a be a memory operand of instruction i?"""
        if not (isinstance(a, Instr) and a.op == "load" and a.block is i.block
                and (a.size == 4 or not a.signed)):
            return False
        return sum(x is a for j in i.block.func.instructions() for x in j.args) == 1

    def emit(self, op, ops=(), defs=(), uses=(), **kw):
        if op in ("MOV", "COPY"):
            kw["flags"] = None              # MOV leaves the flags alone
        return super().emit(op, ops, defs, uses, **kw)

    # ---- operands ------------------------------------------------------

    def spill_load(self, t, slot):
        return MInstr("MOV", [t, slot], defs=[t], uses=[SP])

    def store_word(self, v, mem):
        if is_zero(v):
            self.emit("CLR", [mem])
            return
        super().store_word(v, mem)

    def sym_indexed(self, sym, disp, x, s, size):
        """[label + r] is [R + d16] for a near label, and the special mode's
        [abs24 + x*s] for a far one (the assembler picks); a scaled index
        always takes the table form."""
        if s == 1:
            return Mem(self.reg(x), disp=disp, sym=self.symname(sym), size=size)
        return Mem(None, disp=disp, sym=self.symname(sym), index=self.reg(x), scale=s, size=size)

    def sym_index_ok(self, sym, disp, s):
        return True

    def fits_scaled(self, disp):
        return fits(disp, 24)

    def scaled(self, x, s, disp, size):
        """[x*s + disp]: the table form, with the displacement as the
        table's address."""
        return Mem(None, index=self.reg(x), scale=s, disp=disp, size=size)

    def fmt_mem(self, m):
        if m.index is not None and m.base is None:
            d = self.mem_disp(m)
            a = m.sym + (f"{d:+d}" if d else "") if m.sym is not None else str(d)
            return f"{SIZE_KW[m.size]}[{a} + {self.fmt(m.index)}*{m.scale}]"
        return super().fmt_mem(m)

    # ---- selection -------------------------------------------------------

    def sel_store(self, i):
        if is_zero(i.args[0]):
            self.emit("CLR", [self.mem_for(i)])
            return
        if self.sel_rmw(i):
            return
        super().sel_store(i)

    def rmw(self, i):
        """For store(load(p) + 1, p), and - 1: the load and the step, which
        INC [p] or DEC [p] does in one instruction (setting N and Z)."""
        if i.op != "store":
            return None
        v, addr = i.args
        if not self.is_folded(v, ("add",)) or v in self.absorbed:
            return None
        ld, c = v.args
        if (isinstance(c, Const) and c.signed in (1, -1) and self.is_folded(ld, ("load",))
                and ld.args[0] is addr and ld.size == i.size
                and ld not in self.postinc and i not in self.postinc):
            return ld, c.signed
        return None

    def analyse_block(self, b):
        super().analyse_block(b)
        # an address that only an INC or DEC uses goes into its operand:
        # INC [table + r1*4]
        for i in b.instrs:
            if self.rmw(i) is None:
                continue
            ld, a = self.rmw(i)[0], i.args[1]
            if (isinstance(a, Instr) and a.block is b and a.op in ("add", "sub")
                    and a not in self.foldable and a not in self.absorbed
                    and self.ucount.get(a) == 2 and set(self.users.get(a, ())) == {ld, i}):
                self.foldable.add(a)
                self.ep[a] = self.ep[i]

    def sel_rmw(self, i):
        r = self.rmw(i)
        if r is None:
            return False
        self.emit("INC" if r[1] == 1 else "DEC", [self.mem_for(i)], flags="set")
        return True

    def sel_binop(self, i):
        a, b = i.args
        if i.op == "mul" and (isinstance(a, Const) or isinstance(b, Const)) \
                and not (isinstance(a, Const) and isinstance(b, Const)):
            if isinstance(a, Const):
                a, b = b, a
            d = self.def_reg(i)
            self.move_into(d, a)
            self.emit("MULS", [d, Imm(b.signed)], defs=[d], uses=[d], flags="nz")
            return
        super().sel_binop(i)

    def test(self, a, b):
        if isinstance(a, Const):
            a, b = b, a
        if isinstance(b, Const):
            ra = self.reg(a)
            self.emit("TST", [ra, Imm(b.signed)], uses=[ra], flags="cmp")
            return "NE"
        return super().test(a, b)

    def jump_table(self, r, lo, span, label, default, table):
        t = r
        if lo:
            t = VReg()
            self.emit("LEA", [t, Mem(r, disp=-lo)], defs=[t])
        self.emit("CMP", [t, Imm(span)], uses=[t], flags="cmp")
        self.emit("BCC", [Label(default)], cond="HS", targets=[default])
        # PC-relative: the table is in the function's own section, so it is
        # in reach wherever the linker puts the function
        self.emit("JMPT", [t, label], uses=[t], targets=list(dict.fromkeys(table)))

    # ---- after allocation ------------------------------------------------

    def push(self, r):
        return f"        PUSH {self.fmt(r)}"

    def format_instr(self, i):
        if i.op == "ST":
            return [f"        MOV  {self.fmt(i.ops[1])}, {self.fmt(i.ops[0])}"]
        if i.op == "JMPT":
            return [f"        JMP  [pc + {i.ops[1]} + {self.fmt(i.ops[0])}*4]"]
        if i.op == "DBNZ":
            return [f"        DBNZ {self.fmt(i.ops[0])}, {i.targets[0].label}"]
        return super().format_instr(i)

    def final_layout(self, body):
        """DEC r; BNE back to a block that starts at most 16 parcels before
        it, the DBNZ included: DBNZ r. Nothing else may read the DEC's
        flags (and DBNZ leaves them alone)."""
        where = {b: n for n, (b, _) in enumerate(body)}
        for n, (b, instrs) in enumerate(body):
            for k in range(len(instrs) - 1):
                d, br = instrs[k], instrs[k + 1]
                if not (d.op == "DEC" and len(d.ops) == 2 and d.ops[0] is d.ops[1]
                        and br.op == "BCC" and br.cond == "NE"
                        and where.get(br.targets[0], n + 1) <= n):
                    continue
                if any(j.op == "BCC" or j.op.startswith("SET") for j in instrs[k + 2:]):
                    continue
                loop = body[where[br.targets[0]]:n + 1]
                inside = {lb for lb, _ in loop}
                size = sum(self.parcels(j, inside) for lb, li in loop
                           for j in (li[:k] if lb is b else li)) + 1
                if size <= 16:
                    instrs[k:k + 2] = [MInstr("DBNZ", [d.ops[0]], targets=br.targets)]
                    break

    def parcels(self, i, inside):
        """At most how many parcels instruction i takes; inside is the
        blocks a branch reaches with a one-parcel Bcc."""
        op = i.op
        if op == "RET":
            return 1 + 2 * len(self.epilogue())
        if op == "TAIL":
            return 3 + 2 * len(self.epilogue(tail=True))
        if op in ("BCC", "JMP"):
            return 1 if i.targets[0] in inside else 2
        if op in ("BSR", "CALL") and isinstance(i.ops[0], Label):
            return 3
        if op == "JMPT":
            return 3
        n = 1
        for x in i.ops:
            if isinstance(x, Mem):
                n += self.mem_parcels(x, op)
            elif isinstance(x, Imm):
                n += self.imm_parcels(x.value, op)
            elif isinstance(x, str):
                n += 2
        return n

    QUICK = ("MOV", "ADD", "SUB", "CMP", "AND", "OR", "XOR")

    def imm_parcels(self, v, op):
        if op in ("LSL", "LSR", "ASR", "ROR"):
            return 0
        if not isinstance(v, int):
            return 2                        # a symbol
        if op in self.QUICK and -16 <= v <= 15 or op in ("MOV", "CMP") and 16 <= v <= 127:
            return 0
        v &= 0xFFFFFFFF
        return 1 if v < 0x8000 or v >= 0xFFFF8000 or v <= 0xFFFF or not v & 0xFFFF else 2

    def mem_parcels(self, m, op):
        if m.postinc:
            return 0
        d = self.mem_disp(m)
        if m.base is None:
            return 2 if m.index is not None or m.sym is not None or not fits(d, 16) else 1
        if m.index is not None:
            return 1
        if m.sym is not None:
            return 2
        if d == 0 or m.size == 4 and d % 4 == 0 and 0 <= d <= 60 and (
                m.base is SP or m.base is PHYS[14] and op != "LEA"):
            return 0
        return 1 if fits(d, 16) else 2

    def peephole(self):
        self.drop_compares()
        super().peephole()

    # Every instruction selected here that changes the flags says so
    # (flags "cmp", "nz" or "set"), and only BCC and SETcc read them, so the
    # scans below look past the others: MOV, LEA, stores, CLR, MFHI.
    ENDS = ("JMP", "RET", "TAIL", "BSR", "CALL", "JMPM", "JMPT", "HALT", "DBNZ")

    def drop_compares(self):
        """CMP r, #0 (or #-1) goes when the instruction that last wrote r
        set N and Z from it, nothing in between touched the flags, and the
        branches after it only test N and Z. A MOV that wrote r becomes
        MOVS for it, so a load's flags reach past a store:
        MOVS r3, byte [r2]+; MOV byte [r1]+, r3; BNE."""
        for b in self.mf.blocks:
            out = []
            for k, c in enumerate(b.instrs):
                if c.op == "CMP" and isinstance(c.ops[1], Imm) and c.ops[1].value in self.NZ_CONDS:
                    r = c.ops[0]
                    d = next((i for i in reversed(out) if r in i.defs or i.flags is not None
                              or i.op in self.ENDS or i.op == "BCC" or i.op.startswith("SET")),
                             None)
                    users = self.flag_users(b, k)
                    conds = self.NZ_CONDS[c.ops[1].value]
                    if (d is not None and d.ops and d.ops[0] is r and r in d.defs
                            and (d.flags == "nz" or d.op in ("MOV", "COPY") and not isinstance(d.ops[1], Imm))
                            and users and all(self.cond_of(u) in conds for u in users)):
                        if d.flags != "nz":
                            d.op, d.flags = "MOVS", "nz"
                        for u in users:
                            self.set_cond(u, conds[self.cond_of(u)])
                        continue
                out.append(c)
            b.instrs = out

    def flag_users(self, b, k):
        out = []
        for i in b.instrs[k + 1:]:
            if i.op == "BCC" or i.op.startswith("SET"):
                out.append(i)
            elif i.flags is not None or i.op in self.ENDS:
                break
        return out

    def flags_used_after(self, b, i):
        return bool(self.flag_users(b, b.instrs.index(i)))
