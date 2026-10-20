"""The register-transfer model of Chibi Heron's CPU: what the netlist does,
a cycle at a time, from the control store's words.

A cycle (ucode.py): phase W writes the register file from Y (WA, WENQ
from the cycle before) and loads PC and MAR (their deferred operations);
phase R puts a source on D, computes D op L in the ALU and the result
multiplexer, and reads or writes memory; the cycle's end loads Y, L, the
flags, the instruction register, the dispatch nibble, the step and page,
and the deferred operations.
"""

from . import routines, ucode as uc
from .system import System


class Word:
    """A control word, unpacked once."""
    __slots__ = [n for n, _ in uc.FIELDS] + ["sel", "wsel", "aop", "flop", "cnd"]

    def __init__(self, w):
        f = uc.unpack(w)
        for n, v in f.items():
            setattr(self, n, v)
        self.aop = uc.AOP_NAME.get(self.AOP, "A")
        self.flop = uc.FL_NAME.get(self.FL)
        self.cnd = uc.CONDS[self.CND & 15]


def alu181(a, b, s, m, c):
    """The 74181s and 74182 as one 16-bit ALU: (F, carry out). Each bit's
    u (A, B as S0 and S1 pick) and v (as S2 and S3 pick) have v <= u, so
    in arithmetic mode F is u + v + carry."""
    nb = ~b & 0xFFFF
    u_ = a | (b if s & 1 else 0) | (nb if s & 2 else 0)
    v_ = (a & nb if s & 4 else 0) | (a & b if s & 8 else 0)
    if m:
        return ~(u_ & ~v_) & 0xFFFF, 0
    t = u_ + v_ + c
    return t & 0xFFFF, t >> 16


def rmux(rm, f, si):
    if rm == uc.RM_PASS:
        return f
    if rm == uc.RM_SHR:
        return f >> 1 | si << 15
    if rm == uc.RM_ZXB:
        return f & 0xFF
    return (f & 0xFF) | (0xFF00 if f & 0x80 else 0)


class Halted(Exception):
    pass


class RTL:
    def __init__(self, sysm=None, cs=None):
        self.sys = sysm or System()
        self.cs = cs or routines.control_store()
        self.words = {}
        self.rf = [0] * 64           # half << 5 | bank << 4 | n
        self.L = self.Y = 0
        self.WA = 0
        self.WENQ = 0
        self.pc = 0                  # bits 20-1 (bit 0 is 0)
        self.mar = 0                 # bits 20-0
        self.mar31 = 0
        self.op = self.d = self.s = 0
        self.N = 0
        self.page, self.step = 3, 0           # reset
        self.f = {k: 0 for k in ("N", "Z", "C", "V", "I", "IC", "ST", "INIT", "IRQP")}
        self.defer = (0, 0, 0)       # (PC op, PC + 2, MAR op)
        self.cycles = 0
        self.instructions = 0
        self.halted = False
        self.ucount = None           # address -> cycles, when profiling
        self.decodes = None          # [(cycle, PC, parcel)] when logging

    def word(self, a):
        w = self.words.get(a)
        if w is None:
            w = self.words[a] = Word(self.cs.words[a])
        return w

    # ---- registers as the program sees them

    def reg(self, n):
        return self.rf[n] | self.rf[32 | n] << 16

    def set_reg(self, n, v):
        self.rf[n] = v & 0xFFFF
        self.rf[32 | n] = v >> 16 & 0xFFFF

    def rfaddr(self, sel, k, half):
        n = {uc.SEL_K: k, uc.SEL_D: self.d, uc.SEL_S: self.s}[sel]
        return half << 5 | n

    # ---- one cycle

    def cycle(self):
        a = uc.addr(self.page, self.N, self.op, self.step)
        w = self.word(a)
        if self.ucount is not None:
            self.ucount[a] = self.ucount.get(a, 0) + 1
        f = self.f
        # phase W
        if self.WENQ:
            self.rf[self.WA] = self.Y
        pop, pinc, mop = self.defer
        if pop == uc.AXP_LO:
            self.pc = (self.pc & ~0xFFFF) | (self.Y & 0xFFFE)
        elif pop == uc.AXP_HI:
            self.pc = (self.pc & 0xFFFF) | (self.Y & 0x1F) << 16
        elif pinc:
            self.pc = (self.pc + 2) & 0x1FFFFF
        if mop == uc.AXM_LO:
            self.mar = (self.mar & ~0xFFFF) | self.Y
        elif mop == uc.AXM_HI:
            self.mar = (self.mar & 0xFFFF) | (self.Y & 0x1F) << 16
            self.mar31 = self.Y >> 15
        elif mop == uc.AXM_INC:
            self.mar = (self.mar & 1) | ((self.mar & 0x1FFFFE) + 2) & 0x1FFFFE
        # phase R: the address bus
        at_pc = w.MOP in (uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS)
        A = self.pc if at_pc else self.mar
        io = (not at_pc) and self.mar31
        md = None
        if w.MOP in (uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_RDM):
            md = self.sys.read16(A, io, self.cycles)
        # the D bus
        ds = w.DS
        if ds == uc.DS_RF:
            D = self.rf[self.rfaddr(w.RS, w.KR, w.HR)]
        elif ds == uc.DS_MEM:
            if md is None:
                raise ValueError(f"D from memory without a read at {a:05X}")
            if w.SZ:
                D = (md >> 8 if A & 1 else md) & 0xFF
            else:
                D = md
        elif ds == uc.DS_IMM:
            D = uc.imm_value(list(uc.IMMS)[w.IMMF], self.d, self.s)
        elif ds == uc.DS_ADR:
            D = A & 0xFFFF
        elif ds == uc.DS_PCH:
            D = self.pc >> 16 & 0x1F
        else:
            D = self.Y              # nothing drives D: it holds what Y put there in phase W
        # the ALU
        s_, m_, carry = uc.aop_resolve(w.aop, f["ST"])
        cin = {"0": 0, "1": 1, "C": f["C"], "IC": f["IC"]}[carry]
        F, co = alu181(D, self.L, s_, m_, cin)
        if m_:
            co = 0
        si = (0, f["C"], D >> 15, co)[w.SISEL]
        R = rmux(w.RM, F, si)
        # memory and I/O writes
        if w.MOP == uc.MOP_WRM:
            if w.SZ:
                lanes = 2 if A & 1 else 1
                v = (D & 0xFF) * 0x101
                self.sys.write(A, v, lanes, io)
            elif not A & 1:
                self.sys.write(A, D, 3, io)
        # the condition
        ne = int(self.d != self.s)
        ct = uc.cond_value(w.cnd, f, A & 1, A >> 1 & 1, ne) ^ (w.CND >> 4)
        # ---- the cycle's end
        if md is not None and w.MOP == uc.MOP_RDM:
            self.sys.read_edge(A, io, self.cycles)
        self.flags(w.flop, R, F, co, D, self.L)
        f["INIT"] |= int(w.flop == "SETINIT")
        irqp = self.sys.irq() & f["I"]
        if w.LDL:
            self.L = D
        self.Y = R
        self.WA = self.rfaddr(w.WS, w.KW, w.HW)
        self.WENQ = w.WEN
        old_s = self.s
        if w.MOP == uc.MOP_FETCH:
            self.op, self.d, self.s = md & 0xFF, md >> 12, md >> 8 & 15
            self.N = self.d
            if self.decodes is not None:
                self.decodes.append((self.cycles, self.pc, md))
            self.instructions += 1
        else:
            if w.IROP == uc.IR_INCD:
                self.d = (self.d + 1) & 15
            elif w.IROP == uc.IR_DECS:
                self.s = (self.s - 1) & 15
            elif w.IROP == uc.IR_LDX:
                self.s = md >> 12
            if w.NOP == uc.N_S:
                self.N = old_s
            elif w.NOP == uc.N_MDZ:
                self.N = md >> 8 & 15
        if w.SEQ == uc.SEQ_NEXT:
            self.step = (self.step + 1) & 31
        elif w.SEQ == uc.SEQ_JUMP:
            if ct:
                self.step, self.page = w.JT, w.PT
            else:
                self.step = (self.step + 1) & 31
        else:
            self.step = 0
            self.page = 3 if f["IRQP"] else 0
        f["IRQP"] = irqp
        self.defer = (w.AXP, int(w.MOP in (uc.MOP_RDP, uc.MOP_FETCH)), w.AXM)
        self.sys.tick()
        self.cycles += 1
        if w.HALT:
            self.halted = True

    def flags(self, op, R, F, co, D, L):
        if op == "NONE":
            return
        f = self.f
        z = int(R == 0)
        n15, n7, f0 = R >> 15, R >> 7 & 1, F & 1
        a15, b15 = D >> 15, L >> 15

        def v(sub, b=b15):
            if sub:
                return int(a15 != b and n15 != a15)
            return int(a15 == b and n15 != a15)
        if op == "ADDLO":
            f["C"], f["Z"] = co, z
        elif op in ("ADDHI", "SUBHI", "ADDHIZ", "SUBHIZ"):
            b = 0 if op.endswith("Z") else b15
            f["C"], f["Z"], f["N"], f["V"] = co, f["Z"] & z, n15, v(op.startswith("SUB"), b)
        elif op == "ADCLO":
            f["C"], f["Z"] = co, f["Z"] & z
        elif op == "ICLO":
            f["IC"] = co
        elif op == "ICLOZ":
            f["IC"], f["Z"] = co, z
        elif op == "ICSTZ":
            f["IC"], f["ST"] = co, z
        elif op == "LOGLO":
            f["Z"] = z
        elif op == "LOGHI":
            f["Z"], f["N"] = f["Z"] & z, n15
        elif op == "NZ16":
            f["N"], f["Z"] = n15, z
        elif op == "NZ8":
            f["N"], f["Z"] = n7, z
        elif op == "SHR":
            f["C"], f["V"] = f0, 0
        elif op == "SHL":
            f["C"], f["V"] = co, 0
        elif op == "STN":
            f["ST"] = n15
        elif op == "STZ":
            f["ST"] = z
        elif op.startswith("IC") and len(op) == 3:
            f["IC"] = f[op[2]]
        elif op in ("CNZ", "VNZ", "ZNZ", "NNZ", "INZ"):
            f[op[0]] = 1 - z
        elif op == "SETI":
            f["I"] = 1
        elif op == "CLRI":
            f["I"] = 0
        elif op == "SETINIT":
            pass
        else:
            raise ValueError(op)

    def run(self, max_cycles=50_000_000):
        while not self.halted:
            self.cycle()
            if self.cycles > max_cycles:
                raise RuntimeError(f"cycle limit of {max_cycles} reached at pc={self.pc:06X}")
        return self

    @property
    def flags_word(self):
        f = self.f
        return f["V"] | f["C"] << 1 | f["Z"] << 2 | f["N"] << 3 | f["I"] << 4
