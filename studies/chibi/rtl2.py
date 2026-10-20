"""The two-halves machine's register-transfer model: what board2's netlist
does, a microinstruction at a time, from the control store's words
(ucode2.py has the cycle). It counts the master clock's ticks too, as the
clock generator gives them, for the machine's time.
"""

from . import routines2, ucode2 as uc
from .rtl import Halted, alu181, rmux  # noqa: F401
from .system2 import System2

FLAG_NAMES = ("N", "Z", "C", "V", "I", "IC", "ST", "B", "BI", "INIT", "IRQP")


class Word:
    __slots__ = [n for n, _ in uc.FIELDS] + ["aop", "flop", "flop_h", "cnd", "two", "nds", "RS",
                                            "KR", "WS", "KW", "WEN"]

    def __init__(self, w):
        f = uc.unpack(w)
        for n, v in f.items():
            setattr(self, n, v)
        self.aop = uc.AOP_NAME.get(self.AOP, "A")
        self.flop = uc.FL_NAME.get(self.FL, "NONE")
        self.flop_h = uc.FL_HIGH.get(self.flop, "NONE")
        self.cnd = uc.CONDS[self.CND]
        self.two = self.HLEN != 0
        self.RS, self.KR = uc.reg_sel(self.RK)
        self.WEN = int(self.WK != uc.WK_NONE)
        self.WS, self.KW = uc.reg_sel(self.WK) if self.WEN else (uc.SEL_K, 0)


class RTL2:
    IO_TICKS = 6            # a half that accesses the I/O space

    def __init__(self, sysm=None, cs=None):
        self.sys = sysm or System2()
        self.cs = cs or routines2.control_store()
        self.words = {}
        self.rf = {}                 # (half, task, bank, n) -> 16 bits
        self.L = [0, 0]              # the low half's latch and the high half's
        self.Y = [0, 0]
        self.Dhold = 0
        self.wa = (0, 0, 0)          # (task, bank, n) of the result's write
        self.wenq = self.wenbq = self.hwq = 0
        self.pc = 0
        self.mar = 0
        self.mar30 = 0
        self.d = self.s = 0
        self.upc = 0                 # reset: the interrupt's entry
        self.task = 0
        self.tupc = 0
        self.f = {k: 0 for k in FLAG_NAMES}
        self.hc = 0
        self.cycles = 0
        self.ticks = 0
        self.instructions = 0
        self.halted = False
        self.ucount = None
        self.decodes = None
        self.decode_ticks = []          # with decodes: the ticks at each

    def word(self, a):
        w = self.words.get(a)
        if w is None:
            w = self.words[a] = Word(self.cs.words[a])
        return w

    # ---- registers as the program sees them (bank 0)

    def reg(self, n, bank=0):
        return self.rf.get((0, 0, bank, n), 0) | self.rf.get((1, 0, bank, n), 0) << 16

    def set_reg(self, n, v, bank=0):
        self.rf[(0, 0, bank, n)] = v & 0xFFFF
        self.rf[(1, 0, bank, n)] = v >> 16 & 0xFFFF

    def regsel(self, sel, k):
        n = {uc.SEL_K: k, uc.SEL_D: self.d, uc.SEL_S: self.s}[sel]
        bank = self.f["B"] if n < 16 else 0
        return (self.task, bank, n)

    @property
    def flags_word(self):
        f = self.f
        return (f["V"] | f["C"] << 1 | f["Z"] << 2 | f["N"] << 3 | f["I"] << 4 | f["B"] << 5
                | f["BI"] << 6)

    # ---- one microinstruction

    def address(self):
        if self.task:
            return uc.TASK_BASE | self.tupc
        return self.upc

    def cycle(self):
        a = self.address()
        w = self.word(a)
        if self.ucount is not None:
            self.ucount[a] = self.ucount.get(a, 0) + 1
        f = self.f
        # phase F: the cycle before's results into the register file
        t, b, n = self.wa
        if self.wenq:
            self.rf[(self.hwq, t, b, n)] = self.Y[0]
            self.Dhold = self.Y[0]
        if self.wenbq:
            self.rf[(1 - self.hwq, t, b, n)] = self.Y[1]
            self.Dhold = self.Y[1]
        ticks = 3 + self.sys.f_stretch(self)
        md_last = None
        ct = None
        last = 1 if w.two else 0
        for h in range(last + 1):
            if h == last:
                # the condition: the flags as the last half starts
                ne = int(self.d != self.s)
                ct = uc.cond_value(w.cnd, f, ne, odt=self.sys.odt_req())
            md, n_ticks = self.half(w, h, last)
            ticks += n_ticks
            if md is not None:
                md_last = md
        if w.cnd == "A0":
            ct = self.bus_a & 1
        self.ticks += ticks
        # ---- the cycle's end: the sequencer
        if w.flop in uc.SYS_FLOPS:
            z = self.z_last
            if w.flop == "BNZ":
                f["B"] = 1 - z
            elif w.flop == "BINZ":
                f["BI"] = 1 - z
            elif w.flop == "ENTRY":
                f["B"] |= f["BI"]
            elif w.flop == "SETINIT":
                f["INIT"] = 1
        irqp = (self.sys.irq() & f["I"]) | self.sys.odt_req()
        self.wenq = w.WEN
        self.wenbq = w.WEN & w.two
        self.hwq = w.HW
        self.wa = self.regsel(w.WS, w.KW)
        nib = (self.d, self.s, (md_last or 0) >> 8 & 15)[w.CND & 3] if w.SEQ == uc.HSEQ_MW \
            else 0
        op = None
        if w.MOP in (uc.MOP_FETCH, uc.MOP_LDIRM) and not self.task:
            md = md_last
            self.d, self.s = md >> 12, md >> 8 & 15
            op = md & 0xFF
            if w.MOP == uc.MOP_FETCH:
                if self.decodes is not None:
                    self.decodes.append((self.cycles, self.fetch_pc, md))
                    self.decode_ticks.append(self.ticks)
                self.instructions += 1
        elif not self.task:
            irn = w.IRN
            if irn == uc.HIRN_INCD:
                self.d = (self.d + 1) & 15
            elif irn == uc.HIRN_DECS:
                self.s = (self.s - 1) & 15
            elif irn == uc.HIRN_IDX:
                self.s = md_last >> 12
        # the next address
        a = self.address()
        tp = w.SEQ in (uc.HSEQ_END, uc.HSEQ_JUMPT)
        if w.SEQ == uc.HSEQ_END:
            nxt = None
        elif w.SEQ == uc.HSEQ_MW:
            nxt = w.JT | nib
        else:
            nxt = w.JT ^ int(bool(ct))
        if self.task:
            if nxt is None:
                self.task = 0
            else:
                self.tupc = nxt & 31
        else:
            if nxt is None:
                if op is None:
                    raise ValueError(f"a decode without a fetch at {a:04X}")
                chk = not w.JT & uc.NOCHK
                nxt = op if (chk and f["IRQP"]) else uc.ENTRY_BASE | op
            self.upc = nxt
            if tp and self.sys.copreq(self):
                self.task = 1
                self.tupc = 0
        f["IRQP"] = irqp
        self.sys.tick(self, ticks)
        self.cycles += 1
        if a in self.cs.halt:
            self.halted = True

    def half(self, w, h, last):
        """One half: (the memory's data if it read, its ticks)."""
        f = self.f
        hx = w.HX if h else uc.HX_NAT
        mop = w.MOP
        if h and hx != uc.HX_NAT and mop in (uc.MOP_RDM, uc.MOP_WRM, uc.MOP_RDP):
            mop = uc.MOP_NONE            # a variant's high half reads and writes nothing
        if mop == uc.MOP_FETCH and h != last:
            mop = uc.MOP_NONE            # a fetch is the last half's
        ds = w.DS
        if h and hx in (uc.HX_ZERO, uc.HX_FILL):
            ds = uc.DS_NONE
        elif h and hx == uc.HX_IMMH:
            ds = uc.DS_IMM
        at_pc = mop in (uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS) or \
            (w.MOP == uc.MOP_FETCH and h != last)
        A = self.pc if at_pc else self.mar
        self.bus_a = A
        io = (not at_pc) and bool(self.mar30)
        if mop == uc.MOP_FETCH:
            self.fetch_pc = self.pc
        md = None
        if mop in (uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_RDM, uc.MOP_LDIRM):
            md = self.sys.read16(A, io, self.cycles)
        # the D bus
        if ds == uc.DS_RF:
            t, b, n = self.regsel(w.RS, w.KR)
            D = self.rf.get((w.HR ^ h, t, b, n), 0)
        elif ds == uc.DS_MEM:
            if md is None:
                raise ValueError(f"D from memory without a read at {self.address():05X}")
            D = ((md >> 8 if A & 1 else md) & 0xFF) if w.SZ else md
        elif ds == uc.DS_IMM:
            D = uc.imm_value(list(uc.IMMS)[w.IMMF], self.d, self.s, h, f["ST"])
        elif ds == uc.DS_ADR:
            D = (self.pc >> 16 & 0x1F) if h else A & 0xFFFF
        elif ds == uc.DS_PCH:
            D = self.pc >> 16 & 0x1F
        elif ds == uc.DS_FLW:
            D = self.flags_word
        else:
            D = self.Dhold
        self.Dhold = D
        # the ALU
        s_, m_, carry = uc.aop_resolve(w.aop, f["ST"])
        if h:
            cin = self.hc
        else:
            cin = {"0": 0, "1": 1, "C": f["C"], "IC": f["IC"]}[carry]
        Lh = self.L[h]
        F, co = alu181(D, Lh, s_, m_, cin)
        if m_:
            co = 0
        si = (0, f["C"], D >> 15, co)[w.SISEL]
        R = rmux(w.RM, F, si)
        if hx == uc.HX_ZERO:
            res = 0
        elif hx == uc.HX_FILL:
            res = 0xFFFF if f["ST"] else 0
        else:
            res = R
        # memory and I/O writes
        if mop == uc.MOP_WRM:
            if w.SZ:
                self.sys.write(A, (D & 0xFF) * 0x101, 2 if A & 1 else 1, io)
            elif not A & 1:
                self.sys.write(A, D, 3, io)
        if md is not None and mop in (uc.MOP_RDM, uc.MOP_LDIRM):
            self.sys.read_edge(A, io, self.cycles)
        # the half's length
        if mop in (uc.MOP_RDM, uc.MOP_WRM, uc.MOP_LDIRM) and io:
            n_ticks = self.sys.io_ticks(A, mop, self)
        else:
            n_ticks = (w.HLEN if h else w.LEN + 1)
        # ---- the half's end
        self.flags(w.flop_h if h else w.flop, R, F, co, D, Lh)
        self.z_last = int(R == 0)
        if not h:
            self.hc = co
        if w.LDL:
            self.L[h] = D
        self.Y[h] = res
        # PC and MAR from the ALU
        axp = w.AXP
        axm = w.AXM
        if h:
            axp = uc.AXP_HI if axp == uc.AXP_LO else uc.AXP_NONE
            axm = uc.AXM_HI if axm == uc.AXM_LO else (uc.AXM_INC if axm == uc.AXM_INC
                                                      else uc.AXM_NONE)
        if axp == uc.AXP_LO:
            self.pc = (self.pc & ~0xFFFF) | (F & 0xFFFE)
        elif axp == uc.AXP_HI:
            self.pc = (self.pc & 0xFFFF) | (F & 0x1F) << 16
        elif mop in (uc.MOP_RDP, uc.MOP_FETCH):
            self.pc = (self.pc + 2) & 0x1FFFFF
        if axm == uc.AXM_LO:
            self.mar = (self.mar & ~0xFFFF) | F
        elif axm == uc.AXM_HI:
            self.mar = (self.mar & 0xFFFF) | (F & 0x1F) << 16
            self.mar30 = F >> 14 & 1
        elif axm == uc.AXM_INC:
            self.mar = (self.mar & 1) | ((self.mar & 0x1FFFFE) + 2) & 0x1FFFFE
        return md, n_ticks

    def flags(self, op, R, F, co, D, L):
        if op == "ENTRY":
            self.f["I"] = 0              # U_FLG's part; B is U_SYS's, at the cycle's end
            return
        if op == "NONE" or op in uc.SYS_FLOPS:
            return
        f = self.f
        z = int(R == 0)
        n15, n7, f0, f1 = R >> 15, R >> 7 & 1, F & 1, F >> 1 & 1
        a15, b15 = D >> 15, L >> 15

        def v(sub):
            if sub:
                return int(a15 != b15 and n15 != a15)
            return int(a15 == b15 and n15 != a15)
        if op in ("ADDLO", "SUBLO"):
            f["C"], f["Z"] = co, z
        elif op in ("ADCLO", "SBCLO"):
            f["C"], f["Z"] = co, f["Z"] & z
        elif op in ("ADDHI", "SUBHI"):
            f["C"], f["Z"], f["N"], f["V"] = co, f["Z"] & z, n15, v(op == "SUBHI")
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
        elif op == "SHR":
            f["C"], f["V"] = f0, 0
        elif op == "SHL":
            f["C"], f["V"] = co, 0
        elif op == "STN":
            f["ST"] = n15
        elif op == "STZ":
            f["ST"] = z
        elif op == "STZ32":
            f["ST"] = f["ST"] & z
        elif op == "STF0":
            f["ST"] = f0
        elif op == "STA4":
            f["ST"] = f0 | f1
        elif op == "STC":
            f["ST"] = f["C"]
        elif op in ("CNZ", "VNZ", "ZNZ", "NNZ", "INZ"):
            f[op[0]] = 1 - z
        elif op == "SETI":
            f["I"] = 1
        elif op == "CLRI":
            f["I"] = 0
        else:
            raise ValueError(op)

    def run(self, max_cycles=50_000_000):
        while not self.halted:
            self.cycle()
            if self.cycles > max_cycles:
                raise RuntimeError(f"cycle limit of {max_cycles} reached at pc={self.pc:06X}")
        return self
