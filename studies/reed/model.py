"""Reed's cycle-level model: the microcode's images (ucode.py) executed a
microcycle at a time with the netlist's semantics, register for register
(ctrl.py, alu.py, mem.py), fast enough for whole programs. It is checked
against the chip-level simulator (hw.py) on small programs and against
draft 2's instruction-level simulator on whole ones.

What it keeps, at a cycle's start (a cycle is one microinstruction):

  CTRL   µPC (the next word's address: its direct fields JT, SEQ, CND and
         LEN are read during this cycle), the executing word, the queue
         (four parcels, their valid bits PV, the bits AV of those still to
         decode, DP, NXP, EP, FFQ), the decoded
         and the executing instruction's opcode and register byte, PNL, PC
         (bits 21-1 and 31), ILEN, H, IFLAG, the interrupt's synchroniser
  ALU    the register file (both copies hold the same) by bank, EB, the
         flags (N, C, V, ZL, ZH, ZB, ZPEND, ZSZ, FZH, ST) and QIN
  MEM    MAR (with AL, IOSP, M31 and MRANGE), FPC (with F31 and FRANGE),
         MQ, S, KILLQ, FAR and FSR, CTX and the page map, the RAM
  IO     the interrupt controller, UART 0 and the timer's counter 0, as
         far as software sees them (io_board)

A cycle that faults (FAULT: misaligned, z 3, the page map's) is cancelled
as the netlist cancels it: CTRL's and ALU's fields read 0 for it and the
next (KILL), MEM's strobes don't come, and the next address is 0.

A result is written into the register file as the next cycle starts (in
the netlist it is written in the next cycle's write phase, and that
cycle's reads of it take Y through the bypass, which is the same), and
taken back if that cycle faults: the write strobe doesn't come then. A bus that
two drivers drive, or that something reads while nothing drives it, is
a microcode error.

The I/O space (A30 of the physical address) holds the benchmark's console
at 0xFFFFFF00 (a byte written goes out; a read gives the next input byte,
or -1), and the IO board's devices that io_board models; the rest read 0.
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


ZERO_WORD = None


def _zero_board(w, boards):
    """w with the fields of `boards` 0 (a cancelled word: CTRL's and ALU's)."""
    out = Word.__new__(Word)
    for name in Word.__slots__:
        setattr(out, name, getattr(w, name))
    for b in boards:
        for name, _ in F.SLICES[b]:
            setattr(out, name, 0)
    return out


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


UCLK_PS = 542535                # the UARTs' and the timer's clock, 1.8432 MHz
TICK_PS = 19861


class IOBoard:
    """The IO board as software sees it (io.py): the interrupt controller
    (levels, IPL, its two registers), UART 0 (a TL16C550C without its
    timing: a byte written to THR goes out at once, RBR gives the input's
    next byte) and the timer's counter 0 in mode 0 (OUT0, TINT, rises at
    the count's end and stays until the count is written again). Time is
    the model's ticks."""

    LEVELS = {"VIRQ": 7, "TINT": 6, "UINT0": 5, "UINT1": 4, "KIRQ": 3, "MIRQ": 2, "CFINT": 1}

    def __init__(self, model):
        self.m = model
        self.ipl = 0
        # UART 0
        self.ier = self.lcr = self.mcr = self.scr = 0
        self.thre_irq = 0
        # timer counter 0: (count loaded, the time it was loaded at in ps, mode)
        self.t_ctl = 0
        self.t_lsb = None
        self.t_count = 0
        self.t_start = None
        self.t_latched = None
        self.out = model.out

    def now_ps(self):
        return self.m.ticks * TICK_PS

    def tint(self):
        if self.t_start is None:
            return 0
        return int((self.now_ps() - self.t_start) // UCLK_PS >= self.t_count)

    def rx_ready(self):
        return self.m.inp_pos < len(self.m.inp)

    def sources(self):
        u0 = int((self.ier & 1 and self.rx_ready()) or (self.ier & 2 and self.thre_irq))
        return {"TINT": self.tint(), "UINT0": u0}

    def highest(self):
        return max([self.LEVELS[k] for k, v in self.sources().items() if v], default=0)

    def irq(self):
        return int(self.highest() > self.ipl)

    def read(self, a, size):
        """A read at physical address a (A30 set): B's value."""
        if (a >> 29) & 1 or (a >> 28) & 1:
            return 0
        slot = (a >> 12) & 15
        if slot == 0:
            v = self._uart_read((a >> 1) & 7)
        elif slot == 2:
            v = self._timer_read((a >> 1) & 3)
        elif slot == 5 and (a >> 10) & 3 == 2:
            m = self.m
            if a & 4:
                fz = m._znow() if m.zpend else m.fzh
                return m.fv | m.fc << 1 | fz << 2 | m.fn << 3 | self.ipl << 24 | 0xFF00 * (size != 0)
            lv = self.highest()
            return (0x3C + 4 * lv) | lv << 24 | 0xFF00 * (size != 0)
        else:
            v = 0xFF
        # (IOD15-8 pulled up; a byte's read gives 0 there)
        return (v & 0xFF) | (0xFF00 if size != 0 else 0)

    def write(self, a, v):
        if (a >> 29) & 1 or (a >> 28) & 1:
            return
        slot = (a >> 12) & 15
        if slot == 0:
            self._uart_write((a >> 1) & 7, v & 0xFF)
        elif slot == 2:
            self._timer_write((a >> 1) & 3, v & 0xFF)
        elif slot == 5 and (a >> 10) & 3 == 2:
            self.ipl = (v & 15) if a & 4 else (v >> 24) & 15

    def _uart_read(self, r):
        m = self.m
        if r == 0 and not self.lcr & 0x80:
            if self.rx_ready():
                m.inp_pos += 1
                return m.inp[m.inp_pos - 1]
            return 0
        if r == 1:
            return self.ier
        if r == 2:
            if self.ier & 1 and self.rx_ready():
                return 0xC4
            if self.ier & 2 and self.thre_irq:
                self.thre_irq = 0
                return 0xC2
            return 0xC1
        if r == 3:
            return self.lcr
        if r == 4:
            return self.mcr
        if r == 5:
            return 0x60 | int(self.rx_ready())
        if r == 7:
            return self.scr
        return 0

    def _uart_write(self, r, v):
        if r == 0 and not self.lcr & 0x80:
            self.out.append(v)
            self.thre_irq = 1
        elif r == 1 and not self.lcr & 0x80:
            if v & 2 and not self.ier & 2:
                self.thre_irq = 1
            self.ier = v & 15
        elif r == 3:
            self.lcr = v
        elif r == 4:
            self.mcr = v
        elif r == 7:
            self.scr = v

    def _timer_write(self, r, v):
        if r == 3:
            if (v >> 6) == 0:
                if (v >> 4) & 3 == 0:
                    self.t_latched = self._timer_value()
                else:
                    self.t_ctl = v
                    self.t_lsb = None
                    self.t_start = None
            return
        if r != 0:
            return
        rw = (self.t_ctl >> 4) & 3
        if rw == 3 and self.t_lsb is None:
            self.t_lsb = v
            self.t_start = None
            return
        n = (v << 8 | self.t_lsb) if rw == 3 else (v if rw == 1 else v << 8)
        self.t_lsb = None
        self.t_count = n or 0x10000
        self.t_start = self.now_ps()

    def _timer_value(self):
        if self.t_start is None:
            return self.t_count
        return max(0, self.t_count - int((self.now_ps() - self.t_start) // UCLK_PS))

    def _timer_read(self, r):
        if r != 0:
            return 0
        v = self.t_latched if self.t_latched is not None else self._timer_value()
        self.t_latched = None
        return v & 0xFF


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
        self.ilen = 0
        self.pending = None
        self.irq1 = self.irqs = 0
        self.ffq = 0
        # ALU (the register file by bank: EB picks one; 0x100 the system's)
        self.banks = {}
        self.eb = 0
        self.rf = self.bank(0)
        self.fn = self.fc = self.fv = self.zl = self.zh = self.zb = self.zpend = self.fzh = self.fst = 0
        self.zsz = 2
        self.qin = 0
        # MEM
        self.mar = self.al = self.iosp = self.m31 = self.mrange = 0
        self.io_a = 0
        self.fpc, self.f31, self.frange, self.mq = 0, 0, 0, 0
        self.s, self.killq = 1, 0
        self.far = 0
        self.ctx = 0
        self.map = [0] * (1 << 17)
        self.io = IOBoard(self)
        # counts
        self.cycles = self.ticks = self.instructions = 0
        self.ucount = None

    def bank(self, n):
        self._apply_pending()
        b = self.banks.get(n)
        if b is None:
            b = self.banks[n] = [0] * 32
        return b

    # ---- memory -------------------------------------------------------------

    def _va(self):
        """The data access's virtual address, as MAR holds it (bits 25-2,
        AL, M31; MRANGE for bits 30-22 not all 0)."""
        return self.m31 << 31 | (self.mar << 2) | self.al

    def translate(self, va31, rng, low, store, fetch):
        """(physical address bits 21-0, I/O space, fsr's page-map bits 0-4)
        for an access, as U_PF and U_MAPC have them: low is the address's
        bits 21-0. The page map translates while CTX's bit 7 is set and the
        address's bit 31 is clear (the context CTX); bit 31 set is the
        supervisor's window, which a user's access faults on. I/O space:
        None (A30 as MAR has it), False (translated: never)."""
        en = self.ctx & 0x80
        if not en:
            return low, None, 0
        if va31:
            return low, None, (0 if self.s else 1 << 4)
        e = self.map[(self.ctx & 0x7F) << 10 | (low >> 12) & 0x3FF]
        why = (not e & 1) | (bool(store and not e & 2)) << 1 | (bool(fetch and not e & 4)) << 2 | bool(rng) << 3
        return (e & 0x3FF000) | (low & 0xFFF), False, why

    def _ram_addr(self):
        return self.pa & (RAM_BYTES - 1)

    def _load(self, size):
        if self.io_space:
            return self._io_read(size)
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
        if self.io_space:
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

    def _io_read(self, size):
        a = self.io_a
        if a & 0x7FFFFFFF == CONSOLE & 0x7FFFFFFF:
            if self.inp_pos < len(self.inp):
                self.inp_pos += 1
                return self.inp[self.inp_pos - 1]
            return MASK
        return self.io.read(a & 0x7FFFFFFF, size)

    def _io_write(self, data):
        a = self.io_a
        if a & 0x7FFFFFFF == CONSOLE & 0x7FFFFFFF:
            self.out.append(data & 255)
            return
        self.io.write(a & 0x7FFFFFFF, data)

    # ---- a microcycle -----------------------------------------------------------

    def _apply_pending(self):
        """The last cycle's result into its register: (the undo, or None)."""
        p = self.pending
        if p is None:
            return None
        lst, i, v = p
        self.pending = None
        old = lst[i]
        lst[i] = v
        return (lst, i, old)

    def step(self):
        undo = self._apply_pending()
        w, n = self.mir, self.cs[self.upc]
        q, pv, rf = self.q, self.pv, self.rf
        op, rb = self.op, self.rb
        rs, rd = rb & 15, rb >> 4
        fn, fc, fv = self.fn, self.fc, self.fv
        fz = self._znow() if self.zpend else self.fzh
        mq0 = self.mq & 1
        pe = q[self.ep]
        # the access's size (U_SZ): the word's MSZ, or for INDEX the index
        # parcel's z
        sz = w.MSZ if w.MSZ != 3 else (pe >> 8) & 3
        # MEM's fault (U_SYS, and the page map's): the cycle, and the
        # next, cancelled (KILL)
        mop = w.MOP
        acc = mop in (F.MOP["LOAD"], F.MOP["STORE"])
        killq = self.killq
        fault = False
        self.io_space = bool(self.iosp)
        self.pa = self._va()
        if acc and not killq:
            align = (sz == 2 and self.al) or (sz == 1 and self.al & 1)
            z3 = sz == 3
            low, io, why = self.translate(self.m31, self.mrange, self._va() & 0x3FFFFF, mop == F.MOP["STORE"], False)
            if io is False:
                self.io_space = False
            self.pa = low
            if align or z3 or why:
                fault = True
                fsr = why | (mop == F.MOP["STORE"]) << 5 | bool(align) << 7 | z3 << 8
                self.far = (self._va() & 0x3FFFFF) | fsr << 22 | self.m31 << 31
        elif acc:
            low, io, why = self.translate(self.m31, self.mrange, self._va() & 0x3FFFFF, mop == F.MOP["STORE"], False)
            if io is False:
                self.io_space = False
            self.pa = low
        kill = fault or killq
        if kill:
            w = _zero_board(w, ("CTRL", "ALU"))
            if undo is not None:
                lst, i, old = undo
                lst[i] = old
        # the executing instruction's condition, and FLUSH
        cc = rd if (op >> 6) & 1 else op & 15
        taken = taken_of(cc, fn, fz, fc, fv)
        flush = w.PCOP == F.PCOP_LOAD or (w.TK and taken)
        A = B = None
        # CTRL onto A (PC through the branch adder) and B (the immediates)
        if w.PCOP in (F.PCOP_DRIVE, F.PCOP_BRANCH):
            t = (self.pc >> 1) + (sext(rb, 8) if w.PCOP == F.PCOP_BRANCH else 0)
            A = (t & 0x1FFFFF) << 1 | (self.pc & 0x80000000)
        if w.IMM != F.IMM["NONE"]:
            B = self._imm(w.IMM, pe, op, rs, rd, rb)
        # the fetch
        dp = self.dp
        d1 = dp >> 1
        fs = (1 if (pv[2 * d1] or pv[2 * d1 + 1]) else 0) ^ d1
        fetch = (not pv[2 * fs] and not pv[2 * fs + 1]) and w.BFREE and not w.DACC and not self.ffq
        ffl = False
        if fetch:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: a fetch onto a driven B")
            low, _, why = self.translate(self.f31, self.frange, (self.fpc << 2) & 0x3FFFFF, False, True)
            if why:
                ffl = True
                self.far = ((self.fpc << 2) & 0x3FFFFF) | self.al | (why | 1 << 6) << 22 | self.f31 << 31
                B = 0
            else:
                a = low & (RAM_BYTES - 1)
                r = self.ram
                B = r[a] | r[a + 1] << 8 | r[a + 2] << 16 | r[a + 3] << 24
        # MEM onto B
        if w.MOP == F.MOP["LOAD"]:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: a load onto a driven B")
            if fault or killq:
                B = 0
            else:
                B = self._load(sz)
        elif w.MOP == F.MOP["FARR"]:
            if B is not None:
                raise ModelError(f"µ{w.addr:04X}: FAR onto a driven B")
            B = self.far
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
        # MEM: a store's data comes on A (no strobe in a cancelled cycle)
        if w.MOP == F.MOP["STORE"] and not kill:
            if A is None:
                raise ModelError(f"µ{w.addr:04X}: a store from an undriven A")
            self._store(sz, A)
        if not kill:
            if w.MOP == F.MOP["SYSW"]:
                if B is None:
                    raise ModelError(f"µ{w.addr:04X}: S from an undriven B")
                self.s = B >> 31
            elif w.MOP == F.MOP["CTXW"]:
                if B is None:
                    raise ModelError(f"µ{w.addr:04X}: CTX from an undriven B")
                self.ctx = (B & 0x7F) | (B >> 31) << 7
            elif w.MOP == F.MOP["MAPW"]:
                if B is None:
                    raise ModelError(f"µ{w.addr:04X}: the page map from an undriven B")
                self.map[(self.ctx & 0x7F) << 10 | (self.mar >> 10) & 0x3FF] = B & 0x3FF007
        # ---- the cycle's end ----------------------------------------------------
        # the sequencer: the word after the next, from the next's direct fields
        seq = n.SEQ
        dec = seq in (F.SEQ_DECODE, F.SEQ_DECODE_NOIRQ) or (seq == F.SEQ_BRDEC and not flush)
        pd = q[dp]
        dlen = self.dt_len[pd]
        decoding = False
        self._kill = kill
        if seq == F.SEQ_JUMP:
            nxt = n.JT ^ self._cond(n.CND, fn, fz, fc, fv, mq0, op, rd)
        elif not dec:
            nxt = n.JT
        else:
            av = self.av
            ready = all(av[(dp + k) & 3] for k in range(max(1, dlen)))
            dec_irq = seq == F.SEQ_DECODE or (seq == F.SEQ_BRDEC and not flush)
            if dec_irq and ((self.irqs and self.iflag) or (self.ffq and not ready)):
                nxt = ucode.IVEC
            elif ready:
                nxt, decoding = self.dt_entry[pd], True
            else:
                nxt = ucode.WAITD
        if fault:
            nxt = 0
        # flags (U_ZL, U_ZH, U_FLA, U_FLB)
        fl = w.FL
        load_fl = w.NSZ == F.NSZ["LOAD"]
        setnz, setcv = fl in (1, 2, 3) and not load_fl, fl == 3 and not load_fl
        f31 = f >> 31
        if load_fl:
            self.fv, self.fc, self.fn = f & 1, (f >> 1) & 1, (f >> 3) & 1
        elif setcv:
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
            nz_sz = sz if w.NSZ == 1 else 2
            self.fn = (f >> 7) & 1 if nz_sz == 0 else (f >> 15) & 1 if nz_sz == 1 else f31
        if load_fl:
            self.fzh = (f >> 2) & 1
        else:
            self.fzh = self._znow() if self.zpend else self.fzh
        self.zl, self.zh, self.zb = int(f & 0xFFFF == 0), int(f >> 16 == 0), int(f & 0xFF == 0)
        self.zpend, self.zsz = int(setnz), (sz if w.NSZ == 1 else 2)
        stop = w.STOP
        if stop == F.STOP["F31"]:
            self.fst = f31
        elif stop == F.STOP["C32"]:
            self.fst = c32
        elif stop == F.STOP["Z"]:
            self.fst = 0
        old_qin, self.qin = self.qin, f & 1
        # the bank (EB, from B), and the register file: the result is
        # written in the next cycle's write phase, so into the bank EB has
        # then
        if w.EBLD:
            if B is None:
                raise ModelError(f"µ{w.addr:04X}: EB from an undriven B")
            self.eb = B & 0x1FF
            self.rf = rf = self.bank(self.eb)
        ws = w.WS
        if ws:
            self.pending = (rf, rd if ws == 1 else rs if ws == 2 else w.K, f)
        # MEM (MAR and MQ load in a cancelled cycle too: from whatever A
        # and B have)
        if w.MARLD:
            if A is None and not kill:
                raise ModelError(f"µ{w.addr:04X}: MAR from an undriven A")
            A_ = A or 0
            self.mar, self.al, self.iosp = (A_ >> 2) & 0xFFFFFF, A_ & 3, (A_ >> 30) & 1
            self.m31, self.mrange, self.io_a = A_ >> 31, int(A_ & 0x7FC00000 != 0), A_
        mqf = w.MQ
        if mqf == F.MQ["LOAD"]:
            if B is None and not kill:
                raise ModelError(f"µ{w.addr:04X}: MQ from an undriven B")
            self.mq = B or 0
        elif mqf == F.MQ["SHIFT"]:
            self.mq = (self.mq >> 1) | old_qin << 31
        if flush:
            if A is None:
                raise ModelError(f"µ{w.addr:04X}: PC from an undriven A")
            self.fpc = (A >> 2) & 0xFFFFF
            self.f31, self.frange = A >> 31, int(A & 0x7FC00000 != 0)
        elif fetch:
            self.fpc = (self.fpc + 1) & 0xFFFFF
        self.killq = int(fault)
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
        elif fetch and not ffl:
            q[2 * fs], q[2 * fs + 1] = B & 0xFFFF, B >> 16
            pv[2 * fs + 1] = av[2 * fs + 1] = 1
            if dp != 2 * fs + 1:
                pv[2 * fs] = av[2 * fs] = 1
        if flush:
            self.ffq = 0
        elif fetch and ffl:
            self.ffq = 1
        if w.IQC in (F.IQC_NEXT, F.IQC_H):
            pv[self.ep] = 0
        if w.IQC == F.IQC_H:
            self.h = pe
        if dec1:
            self.op, self.rb = self.nop, self.nrb
            self.ep = (self.nxp + 1) & 3
            if not kill:
                # (DEC1K: a cancelled cycle's instruction keeps its PC and length)
                self.pc = (self.pc & 0x80000000) | ((self.pc + 2 * self.pnl) & 0x3FFFFE)
                self.ilen = self.pnl
                self.instructions += 1
        elif w.IQC in (F.IQC_NEXT, F.IQC_H):
            self.ep = (self.ep + 1) & 3
        if flush:
            self.pc = A & 0x803FFFFE
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
        # the interrupt request, through U_IRQS's two flip-flops
        self.irqs, self.irq1 = self.irq1, self.io.irq()
        self.cycles += 1
        # (LEN: the executing word's, which a cancelled word keeps: the
        # clock card had it a cycle early)
        self.ticks += F.LEN_BASE + self.mir.LEN
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
        if cnd == C["KILL"]:
            return int(self._kill)
        if cnd == C["FFQ"]:
            av, dp = self.av, self.dp
            ready = all(av[(dp + k) & 3] for k in range(max(1, self.dt_len[self.q[dp]])))
            return int(self.ffq and not ready)
        if cnd == C["ILEN0"]:
            return self.ilen & 1
        if cnd == C["ILEN1"]:
            return (self.ilen >> 1) & 1
        if cnd == C["IRQP"]:
            return int(self.irqs and self.iflag)
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
                self._apply_pending()
                return s
        self._apply_pending()
        return None

    def regs(self):
        self._apply_pending()
        return list(self.rf[:16])

    def sysregs(self):
        """The system bank's r0-r15 (the special registers the microcode
        keeps: ucode.SYS)."""
        return list(self.bank(0x100)[:16])


def run_image(img, inp=b"", max_cycles=50_000_000, prog=None):
    """A Model with an assembled image in RAM, run to its stop."""
    ram = bytearray(RAM_BYTES)
    for a, b in img.mem.items():
        ram[a] = b
    m = Model(ram, inp, prog)
    m.stopped = m.run(max_cycles)
    return m
