"""Reed's cycle-level model: the microcode's images (ucode.py) executed a
microcycle at a time with the netlist's semantics, register for register
(ctrl.py, alu.py, mem.py), fast enough for whole programs. It is checked
against the chip-level simulator (hw.py) on small programs and against
draft 2's instruction-level simulator on whole ones.

What it keeps, at a cycle's start (a cycle is one microinstruction):

  CTRL   µPC (the next word's address: its direct fields JT, SEQ, CND and
         LEN are read during this cycle), the executing word, the queue
         (four parcels, their valid bits PV, the bits AV of those still to
         decode, DP, NXP, EP), the decoded
         and the executing instruction's opcode and register byte, PNL, PC,
         H, IFLAG
  ALU    the register file (both copies hold the same), the flags (N, C,
         V, ZL, ZH, ZB, ZPEND, ZSZ, FZH, ST) and QIN
  MEM    MAR (with AL and IOSP), FPC, MQ, the RAM

A result is written into the register file at the cycle's end: in the
netlist it is written in the next cycle's write phase, and that cycle's
reads of it take Y through the bypass, which is the same. A bus that
two drivers drive, or that something reads while nothing drives it, is
a microcode error.

The I/O space (A30) holds only the benchmark's console at 0xFFFFFF00 (a
byte written goes out; a read gives the next input byte, or -1): the
IO board's devices aren't modelled.
"""

from . import fields as F, ucode

MASK = 0xFFFFFFFF
RAM_BYTES = 4 << 20
CONSOLE = 0xFFFFFF00

# the 181's select and mode for each AOP (alu.py's U_ALUF)
FUN = {"ADD": (0b1001, 0), "SUB": (0b0110, 0), "AND": (0b1011, 1), "OR": (0b1110, 1),
       "XOR": (0b0110, 1), "PASSA": (0b1111, 1), "PASSB": (0b1010, 1), "INCA": (0b0000, 0),
       "DECA": (0b1111, 0), "SHL": (0b1100, 0), "BIC": (0b0111, 1), "NOTA": (0b0000, 1),
       "ZERO": (0b0011, 1), "ONES": (0b1100, 1)}
AOP_NAME = {v: k for k, v in F.AOP.items()}
AOP_SM = {}
for _code, _name in AOP_NAME.items():
    _n = "PASSB" if _name == "RES" else _name
    AOP_SM[_code] = FUN.get(_n)          # MQSTEP: chosen by MQ0 each cycle


class ModelError(Exception):
    pass


def alu181x32(a, b, sel, m, cin):
    """The eight 181s and their lookahead as one: (F, carry out). Per bit
    u = A | B&S0 | ~B&S1, v = A&~B&S2 | A&B&S3, carries c(i+1) = v | u&c(i)
    (models.rs's alu181); since v is within u, the carries are those of
    the sum u + v."""
    nb = ~b & MASK
    u = a | (b if sel & 1 else 0) | (nb if sel & 2 else 0)
    v = (a & nb if sel & 4 else 0) | (a & b if sel & 8 else 0)
    h = u & ~v & MASK
    s = u + v + cin
    if m:
        return ~h & MASK, s >> 32
    carries = (s ^ u ^ v) & MASK
    return h ^ carries, s >> 32


def base_cond(code, n, z, c, v):
    """A cc's base condition (its bits 3-1), ctrl.py's base()."""
    return (z, c, n, v, c & (1 - z), int(n == v), int(z == 0 and n == v), 1)[code]


def taken_of(cc, n, z, c, v):
    """U_TKN's condition: the base XORed with bit 0, but cc 15 always."""
    b = base_cond(cc >> 1, n, z, c, v)
    if cc >> 1 == 7:
        return 1
    return b ^ (cc & 1)


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Word:
    """A control-store word's fields, unpacked from the images."""
    __slots__ = tuple(n for b in F.SLICES for n, _ in F.SLICES[b]) + ("addr",)

    def __init__(self, addr, values):
        self.addr = addr
        for board, val in values.items():
            for name, (b, w) in F.positions(board).items():
                setattr(self, name, (val >> b) & ((1 << w) - 1))


class Model:
    def __init__(self, ram=None, inp=b"", prog=None):
        self.prog = prog or ucode.build()
        cache = getattr(self.prog, "_model_cache", None)
        if cache is None:
            imgs = self.prog.images()
            cs = [Word(a, {b: imgs[b][a] for b in imgs}) for a in range(ucode.WORDS)]
            lo, hi = ucode.decode_table(self.prog)
            cache = (cs, [lo[p] | (hi[p] & 0x3F) << 8 for p in range(1 << 16)], [hi[p] >> 6 for p in range(1 << 16)])
            self.prog._model_cache = cache
        self.cs, self.dt_entry, self.dt_len = cache
        self.ram = bytearray(RAM_BYTES)
        if ram is not None:
            self.ram[:len(ram)] = ram
        self.inp, self.inp_pos, self.out = bytes(inp), 0, bytearray()
        self.stops = {self.prog.addr("halted"): "halt", self.prog.addr("unimpl"): "unimpl"}
        # CTRL
        self.upc, self.mir = 0, Word(-1, {b: 0 for b in F.SLICES})
        self.q, self.pv, self.av = [0] * 4, [0] * 4, [0] * 4
        self.dp = self.nxp = self.ep = 0
        self.dec1 = 0
        self.nop = self.nrb = self.op = self.rb = 0
        self.pnl, self.pc, self.h, self.iflag = 0, 0, 0, 0
        # ALU
        self.rf = [0] * 32
        self.fn = self.fc = self.fv = self.zl = self.zh = self.zb = self.zpend = self.fzh = self.fst = 0
        self.zsz = 2
        self.qin = 0
        # MEM
        self.mar = self.al = self.iosp = 0
        self.fpc, self.mq = 0, 0
        # counts
        self.cycles = self.ticks = self.instructions = 0
        self.ucount = None

    # ---- memory -------------------------------------------------------------

    def _ram_addr(self):
        return ((self.mar << 2) | self.al) & (RAM_BYTES - 1)

    def _load(self, size):
        if self.iosp:
            return self._io_read()
        a = self._ram_addr()
        r = self.ram
        if size == F.MSZ["WORD"]:
            if a & 3:
                raise ModelError(f"misaligned word load at {a:06X}")
            return r[a] | r[a + 1] << 8 | r[a + 2] << 16 | r[a + 3] << 24
        if size == F.MSZ["HALF"]:
            if a & 1:
                raise ModelError(f"misaligned half load at {a:06X}")
            return r[a] | r[a + 1] << 8
        return r[a]

    def _store(self, size, data):
        if self.iosp:
            return self._io_write(data)
        a = self._ram_addr()
        r = self.ram
        if size == F.MSZ["WORD"]:
            if a & 3:
                raise ModelError(f"misaligned word store at {a:06X}")
            r[a], r[a + 1], r[a + 2], r[a + 3] = data & 255, data >> 8 & 255, data >> 16 & 255, data >> 24
        elif size == F.MSZ["HALF"]:
            if a & 1:
                raise ModelError(f"misaligned half store at {a:06X}")
            r[a], r[a + 1] = data & 255, data >> 8 & 255
        else:
            r[a] = data & 255

    def _io_addr(self):
        """The address's bits 25-0 (MAR's, and AL)."""
        return (self.mar << 2) | self.al

    def _io_read(self):
        if self._io_addr() != CONSOLE & 0x3FFFFFF:
            raise ModelError(f"I/O read at {self._io_addr():08X}")
        if self.inp_pos < len(self.inp):
            self.inp_pos += 1
            return self.inp[self.inp_pos - 1]
        return MASK

    def _io_write(self, data):
        if self._io_addr() != CONSOLE & 0x3FFFFFF:
            raise ModelError(f"I/O write at {self._io_addr():08X}")
        self.out.append(data & 255)

    # ---- a microcycle -----------------------------------------------------------

    def step(self):
        w, n = self.mir, self.cs[self.upc]
        q, pv, rf = self.q, self.pv, self.rf
        op, rb = self.op, self.rb
        rs, rd = rb & 15, rb >> 4
        fn, fc, fv = self.fn, self.fc, self.fv
        fz = self._znow() if self.zpend else self.fzh
        mq0 = self.mq & 1
        # the executing instruction's condition, and FLUSH
        cc = rd if (op >> 6) & 1 else op & 15
        taken = taken_of(cc, fn, fz, fc, fv)
        flush = w.PCOP == F.PCOP_LOAD or (w.TK and taken)
        pe = q[self.ep]
        # the access's size (U_SZ): the word's MSZ, or for INDEX the index
        # parcel's z (its 3, which should trap, isn't caught)
        sz = w.MSZ if w.MSZ != 3 else (pe >> 8) & 3
        A = B = None
        # CTRL onto A (PC through the branch adder) and B (the immediates)
        if w.PCOP in (F.PCOP_DRIVE, F.PCOP_BRANCH):
            t = (self.pc >> 1) + (sext(rb, 8) if w.PCOP == F.PCOP_BRANCH else 0)
            A = (t & 0x1FFFFF) << 1
        if w.IMM != F.IMM["NONE"]:
            B = self._imm(w.IMM, pe, op, rs, rd, rb)
        # the fetch
        dp = self.dp
        d1 = dp >> 1
        fs = (1 if (pv[2 * d1] or pv[2 * d1 + 1]) else 0) ^ d1
        fetch = (not pv[2 * fs] and not pv[2 * fs + 1]) and w.BFREE and not w.DACC
        if fetch:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: a fetch onto a driven B")
            a = (self.fpc << 2) & (RAM_BYTES - 1)
            r = self.ram
            B = r[a] | r[a + 1] << 8 | r[a + 2] << 16 | r[a + 3] << 24
        # MEM onto B
        if w.MOP == F.MOP["LOAD"]:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: a load onto a driven B")
            B = self._load(sz)
        if w.MQ == F.MQ["DRIVE"]:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: MQ onto a driven B")
            B = self.mq
        # the ALU
        if w.AIN:
            if A is None:
                raise ModelError(f"µ{w.addr:04X}: OA from an undriven A")
            if w.AOUT != F.AOUT["NONE"]:
                raise ModelError(f"µ{w.addr:04X}: OA from A and onto it")
            oa = A
        else:
            ras = w.RAS
            oa = rf[rd if ras == 0 else rs if ras == 1 else w.K if ras == 2 else 0]
        bin_ = w.BIN
        if bin_ == F.BIN["RF"]:
            rbs = w.RBS
            ob = rf[rs if rbs == 0 else (pe >> 12) if rbs == 1 else w.K if rbs == 2 else 0]
        elif bin_ == F.BIN["BUS"]:
            if w.BOUT:
                raise ModelError(f"µ{w.addr:04X}: OB from B and onto it")
            if B is None:
                raise ModelError(f"µ{w.addr:04X}: OB from an undriven B")
            ob = B
        elif bin_ == F.BIN["SHIFT"]:
            si = w.SI
            sin = 0 if si == 0 else fc if si == 1 else (oa >> 31) if si == 2 else oa & 1
            ob = (oa >> 1) | sin << 31
        else:
            ob = None
        if w.BOUT:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: OB onto a driven B")
            if ob is None:
                raise ModelError(f"µ{w.addr:04X}: OB onto B, OB undriven")
            B = ob
        aop = w.AOP
        if aop == F.AOP["MQSTEP"]:
            sel, m = FUN["ADD"] if mq0 else FUN["INCA"]
        else:
            sel, m = AOP_SM[aop]
        ci = w.CI
        cin = 1 if ci == 1 else fc if ci == 2 else (1 if ci == 3 and aop in (F.AOP["SUB"], F.AOP["INCA"]) else 0)
        if ob is None:
            # (an undriven B matters only where F is used)
            if sel not in (0b1111, 0b0000, 0b0011, 0b1100) and (
                    w.WS or w.FL in (2, 3) or w.AOUT == F.AOUT["F"] or w.STOP in (2, 3)):
                raise ModelError(f"µ{w.addr:04X}: the ALU's B undriven")
            obv = 0
        else:
            obv = ob
        f, c32 = alu181x32(oa, obv, sel, m, cin)
        aout = w.AOUT
        if aout != F.AOUT["NONE"]:
            if A is not None:
                raise ModelError(f"µ{w.addr:04X}: ALU onto a driven A")
            A = oa if aout == F.AOUT["OA"] else f
        # MEM: a store's data comes on A
        if w.MOP == F.MOP["STORE"]:
            if A is None:
                raise ModelError(f"µ{w.addr:04X}: a store from an undriven A")
            self._store(sz, A)
        # ---- the cycle's end ----------------------------------------------------
        # the sequencer: the word after the next, from the next's direct fields
        seq = n.SEQ
        dec = seq in (F.SEQ_DECODE, F.SEQ_DECODE_NOIRQ) or (seq == F.SEQ_BRDEC and not flush)
        pd = q[dp]
        dlen = self.dt_len[pd]
        decoding = False
        if seq == F.SEQ_JUMP:
            nxt = n.JT ^ self._cond(n.CND, fn, fz, fc, fv, mq0, op, rd)
        elif not dec:
            nxt = n.JT
        else:
            av = self.av
            ready = all(av[(dp + k) & 3] for k in range(max(1, dlen)))
            if ready:
                nxt, decoding = self.dt_entry[pd], True
            else:
                nxt = ucode.WAITD
        # flags (U_ZL, U_ZH, U_FLA, U_FLB)
        fl = w.FL
        setnz, setcv = fl in (1, 2, 3), fl == 3
        f31 = f >> 31
        if setcv:
            self.fc = c32
            a31, b31 = oa >> 31, obv >> 31
            if aop == F.AOP["SUB"]:
                self.fv = int(a31 != b31 and f31 != a31)
            else:
                self.fv = int(a31 == b31 and f31 != a31)
        elif fl == F.FL["SH"]:
            self.fc = (oa & 1) if bin_ == F.BIN["SHIFT"] else c32
            self.fv = 0
        if setnz:
            nz_sz = sz if w.NSZ else 2
            self.fn = (f >> 7) & 1 if nz_sz == 0 else (f >> 15) & 1 if nz_sz == 1 else f31
        self.fzh = self._znow() if self.zpend else self.fzh
        self.zl, self.zh, self.zb = int(f & 0xFFFF == 0), int(f >> 16 == 0), int(f & 0xFF == 0)
        self.zpend, self.zsz = int(setnz), (sz if w.NSZ else 2)
        stop = w.STOP
        if stop == F.STOP["F31"]:
            self.fst = f31
        elif stop == F.STOP["C32"]:
            self.fst = c32
        elif stop == F.STOP["Z"]:
            self.fst = 0
        old_qin, self.qin = self.qin, f & 1
        # the register file
        ws = w.WS
        if ws:
            rf[rd if ws == 1 else rs if ws == 2 else w.K] = f
        # MEM
        if w.MARLD:
            if A is None:
                raise ModelError(f"µ{w.addr:04X}: MAR from an undriven A")
            self.mar, self.al, self.iosp = (A >> 2) & 0xFFFFFF, A & 3, (A >> 30) & 1
        mqf = w.MQ
        if mqf == F.MQ["LOAD"]:
            if B is None:
                raise ModelError(f"µ{w.addr:04X}: MQ from an undriven B")
            self.mq = B
        elif mqf == F.MQ["SHIFT"]:
            self.mq = (self.mq >> 1) | old_qin << 31
        if flush:
            if A is None:
                raise ModelError(f"µ{w.addr:04X}: PC from an undriven A")
            self.fpc = (A >> 2) & 0xFFFFF
        elif fetch:
            self.fpc = (self.fpc + 1) & 0xFFFFF
        # the queue
        dec1 = self.dec1
        av = self.av
        if decoding:
            pv[dp] = 0
            for k in range(max(1, dlen)):
                av[(dp + k) & 3] = 0
        if flush:
            pv[0] = pv[1] = pv[2] = pv[3] = 0
            av[0] = av[1] = av[2] = av[3] = 0
        elif fetch:
            q[2 * fs], q[2 * fs + 1] = B & 0xFFFF, B >> 16
            pv[2 * fs + 1] = av[2 * fs + 1] = 1
            if dp != 2 * fs + 1:
                pv[2 * fs] = av[2 * fs] = 1
        if w.IQC in (F.IQC_NEXT, F.IQC_H):
            pv[self.ep] = 0
        if w.IQC == F.IQC_H:
            self.h = pe
        if dec1:
            self.op, self.rb = self.nop, self.nrb
            self.ep = (self.nxp + 1) & 3
            self.pc = (self.pc + 2 * self.pnl) & 0x3FFFFE
            self.instructions += 1
        elif w.IQC in (F.IQC_NEXT, F.IQC_H):
            self.ep = (self.ep + 1) & 3
        if flush:
            self.pc = A & 0x3FFFFE
            self.dp = (A >> 1) & 1
        elif decoding:
            self.dp = (dp + dlen) & 3
        if decoding:
            self.nxp = dp
            self.nop, self.nrb = pd & 0xFF, pd >> 8
            self.pnl = dlen
        self.dec1 = int(decoding and not flush)
        if w.IFL == F.IFL_SET:
            self.iflag = 1
        elif w.IFL == F.IFL_CLEAR:
            self.iflag = 0
        self.cycles += 1
        self.ticks += F.LEN_BASE + w.LEN
        if self.ucount is not None:
            self.ucount[w.addr] = self.ucount.get(w.addr, 0) + 1
        self.mir, self.upc = n, nxt

    def _znow(self):
        """Z from ZL, ZH and ZB as the size registered with them says."""
        z = self.zsz           # SZ's code: 0 byte, 1 half, 2 (or 3) word
        return self.zb if z == 0 else self.zl if z == 1 else (self.zl & self.zh)

    def _imm(self, imm, pe, op, rs, rd, rb):
        I = F.IMM
        if imm == I["PE_SX"]:
            return sext(pe, 16) & MASK
        if imm == I["PE_ZX"]:
            return pe
        if imm == I["PE_HI"]:
            return pe << 16
        if imm == I["H_PE"]:
            return pe << 16 | self.h
        if imm == I["Q"]:
            return rs
        if imm == I["NQ"]:
            return ~rs & MASK
        if imm == I["U7"]:
            return (op & 7) | rs << 3
        if imm == I["S8X2"]:
            return (sext(rb, 8) << 1) & MASK
        if imm == I["R4"]:
            return rs << 2
        if imm == I["ZERO"]:
            return 0
        if imm == I["ONE"]:
            return 1
        if imm == I["FOUR"]:
            return 4
        if imm == I["VEC"]:
            return 0x40
        if imm == I["D8"]:
            return sext(pe, 8) & MASK
        raise ModelError(f"IMM {imm}")

    def _cond(self, cnd, fn, fz, fc, fv, mq0, op, rd):
        C = F.CND
        if cnd == C["NONE"]:
            return 0
        if cnd == C["Z"]:
            return fz
        if cnd == C["N"]:
            return fn
        if cnd == C["C"]:
            return fc
        if cnd == C["V"]:
            return fv
        if cnd == C["ST"]:
            return self.fst
        if cnd == C["MQ0"]:
            return mq0
        if cnd in (C["CC_OP"], C["CC_D"]):
            cc = op & 15 if cnd == C["CC_OP"] else rd
            return base_cond(cc >> 1, fn, fz, fc, fv) ^ (cc & 1)
        raise ModelError(f"CND {cnd}")

    # ---- runs ---------------------------------------------------------------------

    def run(self, max_cycles=10_000_000):
        """Until the microcode stops (HALT, or an unimplemented instruction):
        "halt" or "unimpl"; or None at max_cycles."""
        stops = self.stops
        step = self.step
        for _ in range(max_cycles):
            step()
            s = stops.get(self.mir.addr)
            if s:
                return s
        return None

    def regs(self):
        return list(self.rf[:16])


def run_image(img, inp=b"", max_cycles=50_000_000, prog=None):
    """A Model with an assembled image in RAM, run to its stop."""
    ram = bytearray(RAM_BYTES)
    for a, b in img.mem.items():
        ram[a] = b
    m = Model(ram, inp, prog)
    m.stopped = m.run(max_cycles)
    return m
