"""Register-transfer model of Heron Mini's CPU (RFC 0041).

Runs the control store image from ucode.py cycle by cycle on a model of
the datapath (buses, registers, the 74181 ALU, the result multiplexer,
flags, the sequencer) and the prefetch queue, with the board behind it
(system.py): the RAM, the I/O regions and their wait states, the
interrupt line, the video's slots. It checks the rules the microcode must
follow (one driver per bus lane, nothing floating used) and stops with
RTLError when one is broken.

Time is kept in master-clock ticks of 19.86 ns: each microcycle takes its
length class's ticks, plus the wait states of an I/O access.

    m = RTL(system.System(...))
    m.run()
    m.cycles, m.ticks, m.out

`queue_words` is the prefetch queue's depth: 2 as built, 1 to measure a
queue of one word.
"""

from . import ucode as uc

M32 = 0xFFFFFFFF


DEMAND_HOLD = 2


class RTLError(Exception):
    pass


# 74181 per nibble: (S, M, a, b, carry_in) -> (F, carry_out), true carries
def _alu181(a, b, s, m, cin):
    s0, s1, s2, s3 = s & 1, (s >> 1) & 1, (s >> 2) & 1, (s >> 3) & 1
    f, carry = 0, cin
    for i in range(4):
        ai, bi = (a >> i) & 1, (b >> i) & 1
        u = ai | (bi & s0) | ((bi ^ 1) & s1)
        v = (ai & (bi ^ 1) & s2) | (ai & bi & s3)
        h = u & (v ^ 1)
        fi = (h ^ 1) if m else (h ^ carry)
        f |= fi << i
        carry = v | (u & carry)
    return f, carry


_ALU_TABLE = {}
for _s in range(16):
    for _m in range(2):
        t = [None] * 512
        for _a in range(16):
            for _b in range(16):
                for _c in range(2):
                    t[(_a << 5) | (_b << 1) | _c] = _alu181(_a, _b, _s, _m, _c)
        _ALU_TABLE[(_s, _m)] = t


def alu32(a, b, s, m, cin):
    """32-bit 74181 array: (F, carry out)."""
    t = _ALU_TABLE[(s, m)]
    f, c = 0, cin
    for k in range(8):
        r = t[(((a >> (4 * k)) & 15) << 5) | (((b >> (4 * k)) & 15) << 1) | c]
        f |= r[0] << (4 * k)
        c = r[1]
    return f, c


def cond_true(n, z, c, v, cc):
    base = cc >> 1
    if base == 0:
        t = z
    elif base == 1:
        t = c
    elif base == 2:
        t = n
    elif base == 3:
        t = v
    elif base == 4:
        t = c & (z ^ 1)
    elif base == 5:
        t = int(n == v)
    elif base == 6:
        t = (z ^ 1) & int(n == v)
    else:
        t = 1
    return t ^ (cc & 1)


class RTL:
    """rom: the control store's contents ({address: word}); by default, the
    microcode as built."""

    def __init__(self, system, mc=None, check=True, lengths=None, rom=None, queue_words=2,
                 jump_decodes=False):
        self.mc = mc or uc.built()
        self.sys = system
        if rom is None:
            rom = self.mc.rom()
        self.rom = {}
        cache = {}
        for a, w in rom.items():
            if w not in cache:
                cache[w] = uc.unpack(w)
            self.rom[a] = cache[w]
        self.lengths = tuple(lengths or self.mc.lengths)
        self.check = check
        self.depth = queue_words
        # a decode in a cycle that may jump (LDPC) goes to the refill
        # whether it jumps or not, so that the jump's condition isn't on
        # the control store's address; jump_decodes: as draft 2's CPU,
        # a decode that doesn't jump goes ahead
        self.jump_decodes = jump_decodes
        self.rf = [0] * 32
        self.R = self.T = self.TL = self.MAR = self.PC = self.FPC = 0
        self.Q0 = self.Q1 = self.V0 = self.V1 = 0
        self.IR = self.SX = self.EX = 0
        self.LC = self.MQ = self.S33 = self.SGN = self.CL = 0
        self.n = self.z = self.c = self.v = self.i = 0
        self.IRQQ = self.PEND = 0
        self.uaddr = 0
        self.uir = self.rom[0]
        self.cycles = 0              # microcycles
        self.ticks = 0               # master clock ticks
        self.hold_ticks = 0          # of which I/O accesses held the cycle
        self.instructions = 0
        self.halted = False
        self.ucount = None           # microaddress -> executions, if wanted
        self.fetch_words = 0
        self.fetch_wasted = 0
        self.refills = 0
        self.demand = 0              # parcels consumed from the word the cycle fetched
        self.trace = None            # called with the machine at every decode
        self.reason = None

    # ---- helpers -----------------------------------------------------

    def err(self, msg):
        raise RTLError(f"cycle {self.cycles} uaddr {self.uaddr:05X} "
                       f"({self._uname()}) PC {self.PC:08X}: {msg}")

    def _uname(self):
        n = self.mc.by_addr.get(self.uaddr)
        return n.name if n else "?"

    def flags_word(self):
        """The plain machine's flags word: V C Z N I in bits 0-4."""
        return self.v | (self.c << 1) | (self.z << 2) | (self.n << 3) | (self.i << 4)

    def rf_addr(self, sel, k):
        """Register file address for a source (0 d, 1 r, 2 SX, 3 constant)."""
        if sel == 0:
            return (self.IR >> 12) & 15
        if sel == 1:
            return (self.IR >> 8) & 15
        if sel == 2:
            return self.SX
        return k

    def queue_words(self):
        out = []
        if self.V0:
            out.append(self.Q0)
            if self.V1:
                out.append(self.Q1)
        return out

    # ---- one clock cycle ---------------------------------------------

    def step(self):
        f = self.uir
        IR, R, MAR, PC = self.IR, self.R, self.MAR, self.PC
        chk = self.check
        sysm = self.sys
        hold = 0

        # ---- register file reads
        rfk = f["RFK"]
        A = None
        if f["ARF"]:
            A = self.rf[self.rf_addr(f["RFA"], rfk)]
        drv = 1 if f["ARF"] else 0
        if f["APC"]:
            A = (PC | f["PCK"]) & M32
            drv += 1
        if f["AR"]:
            A = R
            drv += 1
        if f["AR2"]:
            sina = (0, R >> 31, self.c, self.MQ >> 31)[f["SINA"]]
            A = ((R << 1) | sina) & M32
            drv += 1
        if drv > 1:
            self.err("A bus contention")

        # ---- the memory port: a data access, or a fetch
        mem = f["MEM"]
        size = f["SIZE"]
        D = None                     # the memory data bus (32 bits)
        fetched = None               # the word a fetch brings
        data_access = mem in (1, 2, 6)
        reading = mem in (1, 6)
        VA = MAR
        if mem == 6:
            if A is None:
                self.err("a read at the A bus with nothing on it")
            VA = A
        # an address error: a half at an odd address, a word at one that
        # isn't a multiple of 4. The access holds the cycle as any I/O
        # access does, but reads and writes nothing; the cycle changes no
        # register or flag (its decode and jump: below)
        fault = data_access and size >= 2 and VA & (1 if size == 2 else 3) != 0
        full = len(self.queue_words()) >= self.depth
        if mem == 3:
            # a refill: the word at FPC, into the queue
            if not full:
                fetched = sysm.fetch(self.FPC)
        elif not data_access and not full:
            # a prefetch, in any cycle that doesn't use the memory port
            fetched = sysm.fetch(self.FPC)

        # ---- the queue as the decode sees it (with a fetch's word)
        qwords = self.queue_words()
        view = qwords + ([fetched] if fetched is not None else [])
        pc1 = (PC >> 1) & 1
        QH = None
        if view:
            QH = (view[0] >> 16) if pc1 else (view[0] & 0xFFFF)

        # immediate unit
        fsel = f["FSEL"]
        if fsel == 0:
            fill = 0
        elif fsel == 1:
            fill = 1
        elif fsel == 3:
            fill = None if QH is None else (QH >> 15) & 1
        elif fsel == 4:
            fill = None if QH is None else (QH >> 7) & 1
        elif fsel == 5:
            fill = None if A is None else (A >> 31) & 1
        elif fsel == 6:
            fill = None if A is None else (A >> 15) & 1
        elif fsel == 7:
            fill = self.SGN
        else:
            fill = None
        v8sel = f["V8"]
        if v8sel == 2:
            v8 = None if fill is None else (0xFF if fill else 0)
        elif v8sel == 3:
            v8 = self.LC
        else:
            v8 = f["KONST"]
        fill8 = None if fill is None else (0xFF if fill else 0)

        # B bus, by byte lane
        lanes = [[], [], [], []]

        def put32(x):
            for k in range(4):
                lanes[k].append(None if x is None else (x >> (8 * k)) & 0xFF)
        if f["BRF"]:
            put32(self.rf[self.rf_addr(f["RFB"], rfk)])
        if f["BR"]:
            put32(R)
        bl = f["BL"]
        if bl:
            if bl <= 3:
                # T is transparent while memory is read into it this cycle
                if reading:
                    tv, tl = "pending", VA & 3     # filled in below, once D is known
                else:
                    tv, tl = self.T, self.TL
                lanes_t = (bl, tl, tv)
            else:
                lanes_t = None
                if QH is None:
                    self.err("the queue's head parcel used while the queue is empty")
                if bl == 4:
                    lanes[0].append(QH & 0xFF)
                    lanes[1].append(QH >> 8)
                elif bl == 5:
                    q2 = (QH << 1) & 0xFFFF
                    lanes[0].append(q2 & 0xFF)
                    lanes[1].append(q2 >> 8)
                elif bl == 6:
                    lanes[2].append(QH & 0xFF)
                    lanes[3].append(QH >> 8)
                else:
                    lanes[0].append(QH & 0xFF)
        else:
            lanes_t = None
        if f["BS0"]:
            lanes[0].append(v8)
        if f["BF1"]:
            lanes[1].append(fill8)
        if f["BF23"]:
            lanes[2].append(fill8)
            lanes[3].append(fill8)
        bx = f["BX"]
        if bx == 1:
            put32(self.MQ)
        elif bx == 2:
            lanes[0].append(self.flags_word())

        # ---- memory data, now that the address side is known
        if reading and fault:
            D, hold = self._faulted(VA)
        elif reading:
            D, h = sysm.read(VA, size, self.cycles)
            hold += h
        if lanes_t is not None:
            bl_, tl, tv = lanes_t
            if tv == "pending":
                tv = D if D is not None else 0
            if bl_ == 1:
                for k in range(4):
                    lanes[k].append((tv >> (8 * k)) & 0xFF)
            elif bl_ == 2:
                h16 = (tv >> 16) & 0xFFFF if tl & 2 else tv & 0xFFFF
                lanes[0].append(h16 & 0xFF)
                lanes[1].append(h16 >> 8)
            else:
                lanes[0].append((tv >> (8 * tl)) & 0xFF)

        B = 0
        bfull = True
        for k in range(4):
            ln = lanes[k]
            if len(ln) > 1:
                self.err(f"B bus contention on byte {k}")
            if ln:
                if ln[0] is None:
                    self.err(f"B bus byte {k} from a floating source")
                B |= ln[0] << (8 * k)
            else:
                bfull = False

        # ---- ALU
        mqm, ms = f["MQM"], f["MS"]
        cin = (0, 1, self.c, 0 if A is None else A >> 31, self.MQ >> 31, self.SGN,
               self.MQ & 1, self.S33 ^ 1)[f["CIN"]]
        gs = 0
        if ms:
            if ms == 1:
                ga, gs = self.MQ & 1, 0
            elif ms == 2:
                ga, gs = 0, self.MQ & 1
            elif mqm == 2:
                ga, gs = self.S33, self.S33 ^ 1
            else:
                ga, gs = self.S33, 0
            s = (ga << 3) | (gs << 2) | (gs << 1) | ga
            m = f["M"]
            if chk and (m or cin != gs):
                self.err("step with M set or the wrong carry in")
        else:
            s, m = f["S"], f["M"]
        uses_a = not (m == 1 and s in (0b1010, 0b0011, 0b1100, 0b0101))
        uses_b = not ((m == 1 and s in (0b1111, 0b0000, 0b0011, 0b1100))
                      or (m == 0 and s in (0b0000, 0b1111, 0b1100)))
        Av = A if A is not None else 0
        F, C32 = alu32(Av, B, s, m, cin)
        vt2 = ((Av >> 31) ^ (B >> 31) ^ (s & 1)) & 1
        OVF = vt2 & ((Av >> 31) ^ (F >> 31)) & 1
        alu_ok = (A is not None or not uses_a) and (bfull or not uses_b)

        # result multiplexer
        rms = f["RMS"]
        if rms == 0:
            RES = F
        elif rms == 1:
            mulstep = mqm == 1
            sign = (Av >> 31) & 1 if vt2 else (F >> 31) & 1
            sin = (0, F >> 31, self.c, F & 1, C32, sign, 0, 0)[f["SIN"] | (mulstep << 2)]
            RES = (F >> 1) | (sin << 31)
        elif rms == 2:
            RES = ((F >> 8) | (F << 24)) & M32
        else:
            RES = ((F >> 16) | (F << 16)) & M32
        rz = f["RZ"]
        if rz:
            for k in range(4):
                if rz >> k & 1:
                    RES &= ~(0xFF << (8 * k)) & M32
        zero = int(RES == 0)

        # ---- stores: the A bus onto the memory data bus, by size
        if mem == 2:
            if A is None:
                self.err("a store with nothing on the A bus")
            if fault:
                hold += self._faulted(MAR)[1]
            else:
                hold += sysm.write(MAR, size, A, self.cycles)

        # a parcel consumed with the queue empty comes from the word this
        # cycle fetches: the cycle is two ticks longer for it
        extra = DEMAND_HOLD if f["CONSUME"] and not self.V0 else 0
        # ---- sequencer
        seq = f["SEQ"]
        jump = False
        if f["LDPC"]:
            pcc = f["PCCOND"]
            if pcc == 0:
                jump = True
            elif pcc == 1:
                jump = bool(self.bcond(f["CCB"]))
            else:
                jump = not self.CL
        forced = None
        decode_ok = False
        if seq == uc.SEQ_NEXT:
            cnd = f["COND"]
            if cnd:
                if chk and f["NEXT"] & 1:
                    self.err("branch with NEXT[0] set")
                y = (f["NEXT"] & ~1) | self.ucond(cnd)
            else:
                y = f["NEXT"]
        elif seq == uc.SEQ_DISPATCH:
            if QH is None:
                self.err("dispatch with the queue empty")
            y = (f["NEXT"] & ~15) | ((QH >> 8) & 15)
        elif seq == uc.SEQ_HALT:
            y = f["NEXT"]
            if self.PEND:
                forced = "irq"
                y = uc.IRQ_ADDR
        else:
            if self.PEND:
                forced, y = "irq", uc.IRQ_ADDR
            elif view and not jump and (qwords or mem == 3) and \
                    (self.jump_decodes or not f["LDPC"]):
                # the instruction's first parcel in the queue (or, for a
                # refill, in the word it fetches): its first microinstruction
                # is at that parcel's address in the upper half
                decode_ok = True
                y = uc.ENTRY + QH
            else:
                forced, y = "refill", uc.REFILL_ADDR

        # an address error: the fault's page; the decode doesn't go ahead
        # and the jump isn't taken, for the IR and the PC, but the queue
        # (and FPC) does as it would, as the hardware's does: the fault's
        # microcode ends in a jump, which empties it
        queue_decode = decode_ok
        if fault:
            forced, y = "fault", uc.FAULT_ADDRS[f["LL"]]
            decode_ok = False

        # ---- clock edge ----------------------------------------------------
        i_now = self.i
        if f["RFWE"] and not fault:
            if chk and not alu_ok:
                self.err("register write from a floating bus")
            self.rf[self.rf_addr(f["RFW"], f["RFKW"])] = RES
        if f["LDR"]:
            if chk and not alu_ok:
                self.err("R loaded from a floating bus")
            self.R = RES
        if f["LDMAR"]:
            if chk and not alu_ok:
                self.err("MAR loaded from a floating bus")
            self.MAR = RES
        elif f["MARINC"]:
            self.MAR = (MAR + 4) & M32
        if reading:
            self.T, self.TL = D, VA & 3
        if f["LDLC"]:
            self.LC = RES & 0xFF
        elif f["LCINC"]:
            self.LC = (self.LC + 1) & 0xFF
        if mqm == 3:
            if chk and not bfull:
                self.err("MQ loaded from a floating bus")
            self.MQ = B
            self.S33 = 0
        elif mqm == 1:
            self.MQ = ((F & 1) << 31) | (self.MQ >> 1)
        elif mqm == 2:
            s33 = ((R >> 31) ^ C32 ^ gs) & 1
            self.MQ = ((self.MQ << 1) | (s33 ^ 1)) & M32
            self.S33 = s33
        if f["LDSGN"]:
            self.SGN = fill
        if f["LDCL"]:
            cls = f["CLSRC"]
            if cls == 0:
                self.CL = zero
            elif cls == 1:
                self.CL = C32
            else:
                hz = int(RES >> (16 if cls in (2, 4) else 15) == 0)
                self.CL = hz if cls in (2, 3) else self.CL & hz
        ldsx = f["LDSX"]
        if ldsx == 1:
            self.SX = (IR >> 12) & 15
        elif ldsx == 2:
            self.SX = (self.SX + 1) & 15
        elif ldsx == 3:
            self.SX = (QH >> 12) & 15
        ldex = f["LDEX"]
        if ldex == 1:
            self.EX = (IR >> 8) & 15
        elif ldex == 2:
            self.EX = (QH >> 12) & 15
        if not fault:
            self._flags(f, RES, F, C32, OVF, zero, A, fill)
        # the PC and the queue
        if jump:
            if chk and not alu_ok:
                self.err("PC loaded from a floating bus")
            if not fault:
                self.PC = RES & 0xFFFFFFFE
            self.FPC = RES & 0xFFFFFFFC
            self.V0 = self.V1 = 0
            if fetched is not None:
                self.fetch_wasted += 1
        else:
            consume = 1 if (f["CONSUME"] or queue_decode) else 0
            if f["CONSUME"] and not qwords:
                if fetched is None:
                    self.err("a parcel consumed from an empty queue, without a fetch")
                self.demand += 1
            words = view
            if fetched is not None:
                self.FPC = (self.FPC + 4) & M32
                self.fetch_words += 1
            if consume:
                if pc1:
                    words = words[1:]
                if not fault:
                    self.PC = (PC + 2) & M32
            if len(words) > self.depth:
                self.err("the queue overflowed")
            self.V0 = 1 if words else 0
            self.V1 = 1 if len(words) > 1 else 0
            if words:
                self.Q0 = words[0]
                if len(words) > 1:
                    self.Q1 = words[1]
        if decode_ok:
            self.IR = QH
            self.instructions += 1
        if forced == "refill":
            self.refills += 1
        # the interrupt: the line sampled at every edge (IRQQ), the decision
        # (PEND) a cycle later from it and I as it is in this cycle
        self.PEND = int(bool(self.IRQQ and i_now))
        self.IRQQ = int(sysm.irq())

        if seq == uc.SEQ_HALT and forced is None:
            if not self.i or not sysm.can_interrupt():
                self.halted = True
                self.reason = "HALT"
        k = self.lengths[f["LCL"]] + extra + hold
        self.ticks += k
        self.hold_ticks += hold
        sysm.cycle(k, hold)
        self.cycles += 1
        self.uaddr = y
        if self.ucount is not None:
            self.ucount[y] += 1
        w = self.rom.get(y)
        if w is None:
            self.err(f"jump to an empty control store word {y:05X}")
        self.uir = w
        if decode_ok and self.trace is not None:
            self.trace(self)

    def _faulted(self, pa):
        """A misaligned access: (what the data bus carries, the hold)."""
        sysm = self.sys
        if not sysm.is_io(pa):
            a = pa & sysm.mask & ~3
            return int.from_bytes(sysm.ram[a:a + 4], "little"), 0
        hold = sysm.io_hold[(pa >> 28) & 7]
        sysm.io_ticks += hold
        return 0, hold

    def _flags(self, f, RES, F, C32, OVF, zero, A, fill):
        fnz = f["FNZ"]
        if fnz == 3:
            # the flags word from the A bus: N Z C V, and I
            if A is None:
                self.err("flags loaded from a floating A bus")
            self.n, self.z = (A >> 3) & 1, (A >> 2) & 1
            self.c, self.v = (A >> 1) & 1, A & 1
            self.i = (A >> 4) & 1
            return
        if fnz:
            nbit = (31, 15, 7)[f["NSEL"]]
            n = (RES >> nbit) & 1
            if fnz == 1:
                self.n, self.z = n, zero
            else:
                self.n, self.z = n, self.z & zero
        fc = f["FC"]
        if f["CZERO"]:
            self.c = 0
        elif fc == 1:
            cs = f["CSRC"]
            fl = fill or 0
            self.c = [(A or 0) >> 1 & 1, F & 1, (F >> 7) & 1, (F >> 8) & 1, (F >> 15) & 1,
                      F >> 31, ((F >> 7) ^ fl) & 1, ((F >> 15) ^ fl) & 1][cs]
        elif fc == 2:
            self.c = C32
        elif fc == 3:
            self.c = self.CL ^ 1
        fv = f["FV"]
        if fv == 7:
            self.v = OVF
        elif fv == 2:
            self.v = 0
        elif fv == 4:
            self.v = self.CL ^ 1
        elif fv == 5:
            self.v = 1
        fi = f["FI"]
        if fi == 1:
            self.i = 1
        elif fi == 2:
            self.i = 0

    def ucond(self, cnd):
        """A microcode branch condition."""
        if cnd == 1:
            return int(self.LC == 255)
        if cnd == 2:
            return self.R >> 31
        if cnd == 3:
            return self.CL
        if cnd in (4, 7):
            ccb = self.uir["CCB"]
            cc = self.cc_of(ccb)
            if self.check and (cnd == 7) != (cc & 1):
                self.err("condition polarity doesn't match the instruction")
            return cond_true(self.n, self.z, self.c, self.v, cc & 14) ^ (cnd == 7)
        if cnd == 5:
            return self.MQ >> 31
        if cnd == 6:
            return int(self.LC & 15 == 15)
        if cnd == 8:
            return self.PEND
        if cnd == 9:
            return int(self.SX == self.EX)
        if cnd == 12:
            return int(self.SX == 15)
        if cnd == 13:
            return self.MQ & 1
        if cnd == 14:
            return self.R & 1
        self.err(f"unknown condition {cnd}")

    def cc_of(self, ccb):
        if ccb == 0:
            return (self.IR >> 12) & 15
        if ccb == 1:
            return self.IR & 15
        return (self.IR >> 8) & 15

    def bcond(self, ccb):
        cc = self.cc_of(ccb)
        if cc == 15:
            return 0
        return cond_true(self.n, self.z, self.c, self.v, cc)

    def run(self, max_cycles=50_000_000):
        while not self.halted:
            self.step()
            if self.cycles > max_cycles:
                raise RTLError(f"cycle limit reached at PC {self.PC:08X}")
        return self

    # ---- state as the instruction-level simulator shows it ------------

    def reg(self, i):
        return self.rf[i]

    @property
    def r(self):
        return [self.rf[i] for i in range(16)]

    @property
    def pc(self):
        """The address of the instruction the next decode starts."""
        return self.PC

    @property
    def out(self):
        return self.sys.output()
