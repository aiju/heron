"""Register-transfer model of the draft 2 CPU (RFC 0031).

Runs the control store image from ucode.py cycle by cycle on a model of
the datapath (buses, registers, the 74181 ALU, the result multiplexer,
flags, the sequencer), the prefetch queue, the page map and the register
banks, and the memory system behind them (system.py): the card's own RAM,
and the system bus with its cards. It checks the rules the microcode must
follow (one driver per bus lane, nothing floating used) and stops with
RTLError when one is broken.

Time is kept in master-clock ticks of 20 ns: each microcycle takes its
length class's ticks, plus however long a bus transfer holds it.

    m = RTL(system.System(...))
    m.run()
    m.cycles, m.ticks, m.out
"""

from collections import Counter

from . import ucode as uc
from .system import Fault

M32 = 0xFFFFFFFF


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


GLB = 0x2000          # register file address of the G locations (each bank has its own)
MSGR = 0x4000         # the message level's registers (RFC 0040, 2.6): their own sixteen


class RTL:
    """rom, decode: the control store's contents ({address: word}) and the
    decode table (64K entries), as the I/O processor wrote them at boot;
    by default, the microcode as built."""

    def __init__(self, system, mc=None, check=True, lengths=None, rom=None, decode=None):
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
        self.idle = uc.unpack(uc.IDLE)
        self.decode = list(decode) if decode is not None else self.mc.decode_table()
        self.lengths = tuple(lengths or self.mc.lengths)
        self.check = check
        self.rf = [0] * (MSGR + 32)
        self.R = self.T = self.TL = self.MAR = self.PC = self.FPC = 0
        self.Q0 = self.Q1 = self.V0 = self.V1 = 0
        self.FOK = self.FPPN = 0     # the fetch's translation: FPC's page, if valid
        self.IR = self.LEN = self.SX = self.EX = 0
        self.LC = self.MQ = self.S33 = self.SGN = self.CL = 0
        self.n = self.z = self.c = self.v = self.i = self.t = 0
        self.s = 1
        self.m = self.ipl = 0
        self.TS = 0
        # interrupts (RFC 0040, 2): the card's levels sampled at every edge
        # (RQ, MSGQ, NMIQ); from them, a cycle later, the decision PEND
        # with the level LT (0: the NMI) and MSGT, level 7 with a message
        self.RQ = self.MSGQ = self.NMIQ = 0
        self.PEND = self.LT = self.MSGT = 0
        self.UBRD = 0                # UBR of the cycle before: this cycle reads the user bank
        self.CTX = self.BANK = 0
        self.FSR = self.FAR = self.FK = 0
        self.uaddr = 0
        self.uir = self.rom[0]
        self.cycles = 0              # microcycles
        self.ticks = 0               # master clock ticks (20 ns)
        self.hold_ticks = 0          # of which bus transfers held the cycle
        self.instructions = 0
        self.halted = False
        self.ucount = None           # microaddress -> executions, if wanted
        self.refill_from = None      # (after a jump?, routine) -> refills, if wanted
        self.fetch_words = 0
        self.fetch_wasted = 0
        self.refills = 0
        self.trace = None            # called with the machine at every decode
        self.reason = None

    # ---- helpers -----------------------------------------------------

    def err(self, msg):
        raise RTLError(f"cycle {self.cycles} uaddr {self.uaddr:04X} "
                       f"({self._uname()}) PC {self.PC:08X}: {msg}")

    def _uname(self):
        n = self.mc.by_addr.get(self.uaddr)
        return n.name if n else "?"

    def flags_word(self):
        """sr (RFC 0029, 2)."""
        return (self.v | (self.c << 1) | (self.z << 2) | (self.n << 3) | (self.ipl << 24)
                | (self.m << 28) | (self.t << 29) | (self.i << 30) | (self.s << 31))

    def rf_addr(self, sel, k, user):
        """Register file address for a source (0 d, 1 r, 2 SX, 3 constant)."""
        if sel == 0:
            reg = (self.IR >> 12) & 15
        elif sel == 1:
            reg = (self.IR >> 8) & 15
        elif sel == 2:
            reg = self.SX
        else:
            reg = k
        bank = self.BANK if (user or not self.s) else 0
        if reg >= uc.G:
            return GLB | (bank << 5) | (reg - uc.G)
        if self.m and self.s and not user:
            return MSGR | reg        # the message level's registers
        return (bank << 5) | reg

    def queue_words(self):
        out = []
        if self.V0:
            out.append(self.Q0)
            if self.V1:
                out.append(self.Q1)
        return out

    @staticmethod
    def parcels_in(words, pc1):
        return 2 * len(words) - (1 if (words and pc1) else 0)

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
            A = self.rf[self.rf_addr(f["RFA"], rfk, self.UBRD)]
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
        if f["AMAR"]:
            A = MAR
            drv += 1
        if drv > 1:
            self.err("A bus contention")

        # ---- the memory port: a data access, or a fetch
        mem = f["MEM"]
        size = f["SIZE"]
        fault = None                 # (kind 0 page / 1 misaligned / 2 bus, fsr, far)
        D = None                     # the memory data bus (32 bits)
        fetched = None               # the word a fetch brings
        itlb = None                  # the fetch's translation, if this cycle makes one
        fetch_fault = None
        data_access = mem in (1, 2, 4, 5, 6)
        reading = mem in (1, 6)
        VA = MAR
        if mem == 6:
            # a read whose address comes from the A bus, not MAR
            if A is None:
                self.err("a read at the A bus with nothing on it")
            VA = A
        if data_access:
            if mem in (1, 2, 6):
                if (size == 3 and VA & 3) or (size == 2 and VA & 1):
                    fault = (1, 0, VA)
                else:
                    try:
                        pa = sysm.translate(VA, "write" if mem == 2 else "read", self)
                    except Fault as e:
                        fault = (0, e.fsr, VA)
                        pa = None
            elif not self.s:
                self.err("a map access in user mode")
        elif mem == 3:
            # a refill: the word at FPC, translated by the map, into the
            # queue (if Q1 is free); the translation is kept for the fetches
            # that follow
            try:
                pa_f = sysm.translate(self.FPC, "fetch", self)
                itlb = (1, pa_f & ~0xFFF)
                if not self.V1:
                    fetched, h = sysm.fetch(pa_f, self)
                    hold += h
            except Fault as e:
                itlb = (0, 0)
                if not self.V1:
                    fetch_fault = (0, e.fsr, self.FPC)
        elif self.FOK:
            # a prefetch, with the kept translation: into the queue if Q1 is
            # free and the word is fast to reach
            itlb = None
            pa_f = self.FPPN | (self.FPC & 0xFFF)
            if not self.V1 and (sysm.fetch_is_fast(pa_f) or sysm.prefetch_bus):
                fetched, h = sysm.fetch(pa_f, self)
                hold += h
        else:
            # no translation kept: the map translates FPC, for the next
            # cycles' fetches
            try:
                itlb = (1, sysm.translate(self.FPC, "fetch", self) & ~0xFFF)
            except Fault:
                itlb = (0, 0)

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
        elif fsel == 2:
            fill = (IR >> 15) & 1
        elif fsel == 3:
            fill = None if QH is None else (QH >> 15) & 1
        elif fsel == 4:
            fill = None if QH is None else (QH >> 7) & 1
        elif fsel == 5:
            fill = None if A is None else (A >> 31) & 1
        elif fsel == 6:
            fill = None if A is None else (A >> 15) & 1
        else:
            fill = self.SGN
        v8sel = f["V8"]
        q = (IR >> 8) & 15
        if v8sel == 0:
            v8 = (IR >> 7) & 0xFE
        elif v8sel == 1:
            v8 = f["KONST"]
        elif v8sel == 2:
            v8 = None if fill is None else (0xFF if fill else 0)
        elif v8sel == 3:
            v8 = self.LC
        elif v8sel == 4:
            v8 = q
        elif v8sel == 5:
            v8 = 0xF0 | (q ^ 15)
        elif v8sel == 6:
            v8 = (q << 3) | (IR & 7)
        else:
            v8 = q << 2
        fill8 = None if fill is None else (0xFF if fill else 0)

        # B bus, by byte lane
        lanes = [[], [], [], []]

        def put32(x):
            for k in range(4):
                lanes[k].append(None if x is None else (x >> (8 * k)) & 0xFF)
        if f["BRF"]:
            put32(self.rf[self.rf_addr(f["RFB"], rfk, self.UBRD)])
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
            fw = self.flags_word()
            lanes[0].append(fw & 0xFF)
            lanes[2].append(0)
            lanes[3].append(fw >> 24)
        elif bx == 6:
            lanes[0].append(4 if self.LT == 0 else 0x40 + 4 * (self.LT - 1))
        elif bx == 7:
            put32(sysm.msg_word())
        elif bx == 3:
            lanes[0].append(self.FSR)
        elif bx == 4:
            put32(self.FAR)
        elif bx == 5:
            if mem != 4:
                self.err("the map on B without a map read")
            put32(sysm.map_read(MAR))

        # ---- memory data, now that the address side is known
        if data_access and fault is None:
            if reading:
                D, h = sysm.read(pa, size, VA, self)
                hold += h
            elif mem == 2:
                pass                       # after the A bus has the store data
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
        if mem == 2 and fault is None:
            if A is None:
                self.err("a store with nothing on the A bus")
            hold += sysm.write(pa, size, MAR, A, self)
        if mem == 5:
            if chk and not bfull:
                self.err("map write from a floating B bus")
            sysm.map_write(MAR, B)

        # demand fetch faults count only if the decode needs the word
        LEN_next = None
        seq = f["SEQ"]
        if seq == uc.SEQ_DECODE and QH is not None:
            dec = self.decode[QH]
            LEN_next = dec >> uc.Y_BITS
        if fetch_fault is not None and mem == 3:
            have = self.parcels_in(qwords, pc1)
            need = LEN_next if (LEN_next and qwords) else 1
            if have < need or not qwords:
                fault = fetch_fault

        FAULT = fault is not None

        # ---- sequencer
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
        if FAULT:
            ln = 0 if mem == 3 else self.LEN
            y = uc.fault_addr(ln)
        elif seq == uc.SEQ_NEXT:
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
            if self.TS:
                forced, y = "trace", uc.TRACE_ADDR
            elif self.PEND:
                forced, y = "irq", uc.IRQ_ADDR
            else:
                # the instruction's first parcel in the queue, but for a
                # refill, which decodes from the word it fetches
                complete = False
                if view and not jump and (qwords or mem == 3):
                    complete = self.parcels_in(view, pc1) >= LEN_next
                if not complete:
                    forced, y = "refill", uc.REFILL_ADDR
                else:
                    decode_ok = True
                    y = dec & ((1 << uc.Y_BITS) - 1)

        # ---- clock edge ----------------------------------------------------
        if FAULT:
            kind, fsr, far = fault
            self.FK, self.FAR = kind, far
            if kind == 0:
                self.FSR = fsr
        commit = not FAULT
        i_now, ipl_now = self.i, self.ipl
        if commit:
            if f["RFWE"]:
                if chk and not alu_ok:
                    self.err("register write from a floating bus")
                self.rf[self.rf_addr(f["RFW"], f["RFKW"], f["UBW"])] = RES
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
                self.SX = (IR >> 8) & 15
            elif ldsx == 3:
                self.SX = (QH >> 12) & 15
            elif f["SXINC"]:
                self.SX = (self.SX + 1) & 15
            ldex = f["LDEX"]
            if ldex == 1:
                self.EX = (IR >> 8) & 15
            elif ldex == 2:
                self.EX = (QH >> 12) & 15
            if f["LDCTX"]:
                self.CTX = RES & 0x7F
            if f["LDBANK"]:
                self.BANK = RES & 0xFF
            self._flags(f, RES, F, C32, OVF, zero, A, B, fill)
            # the PC and the queue; the kept translation goes with a jump
            # and when FPC leaves the page
            if itlb is not None:
                self.FOK, self.FPPN = itlb
            if jump:
                if chk and not alu_ok:
                    self.err("PC loaded from a floating bus")
                self.PC = RES & 0xFFFFFFFE
                self.FPC = RES & 0xFFFFFFFC
                self.V0 = self.V1 = 0
                self.FOK = 0
                if fetched is not None:
                    self.fetch_wasted += 1
            else:
                consume = 1 if (f["CONSUME"] or decode_ok) else 0
                if f["CONSUME"] and not qwords:
                    self.err("a parcel consumed from an empty queue")
                words = view
                if fetched is not None:
                    self.FPC = (self.FPC + 4) & M32
                    self.fetch_words += 1
                    if not self.FPC & 0xFFF:
                        self.FOK = 0
                if consume:
                    if pc1:
                        words = words[1:]
                    self.PC = (PC + 2) & M32
                if len(words) > 2:
                    self.err("the queue overflowed")
                self.V0 = 1 if words else 0
                self.V1 = 1 if len(words) > 1 else 0
                if words:
                    self.Q0 = words[0]
                    if len(words) > 1:
                        self.Q1 = words[1]
            if decode_ok:
                self.IR = QH
                self.LEN = LEN_next
                self.TS = self.t
                self.instructions += 1
            if forced == "refill":
                self.refills += 1
                if self.refill_from is not None:
                    self.refill_from[(jump, self.mc.by_addr[self.uaddr].name)] += 1
        self.UBRD = f["UBR"]
        # interrupts: the decision from the levels sampled at the last edge,
        # IPL and I as they are in this cycle; LT and MSGT hold from the
        # interrupt entry's first cycle (SSET) until I is set again or an
        # NMI comes, so that the entry sees the level it was taken for
        L = self.RQ.bit_length() - 1 if self.RQ & 0x1FE else 0
        if not f["SSET"] and (i_now or self.NMIQ):
            self.LT = 0 if self.NMIQ else L
            self.MSGT = int(L == 7 and self.MSGQ and not self.NMIQ)
        self.PEND = int(bool(self.NMIQ or (i_now and L > ipl_now)))
        # the levels as the edge samples them, and only after it the card's
        # changes at this edge: the CPU's writes to its registers, the
        # message register released, the NMI acknowledged, the timer
        self.RQ = sysm.levels() & 0x1FE
        self.MSGQ = int(sysm.msg_full())
        self.NMIQ = int(sysm.nmi())
        sysm.edge()
        if commit and f["BX"] == 7:
            sysm.msg_release()
        if commit and f["SSET"] and f["LFM"] == 1 and not self.LT:
            sysm.nmi_ack()

        if seq == uc.SEQ_HALT and forced is None and not FAULT:
            if not (self.i or self.NMIQ) or not sysm.can_interrupt():
                self.halted = True
                self.reason = "HALT"
        k = self.lengths[f["LCL"]]
        self.ticks += k + hold
        self.hold_ticks += hold
        sysm.tick(self, k + hold)
        self.cycles += 1
        self.uaddr = y
        if self.ucount is not None:
            self.ucount[y] += 1
        w = self.rom.get(y)
        if w is None:
            self.err(f"jump to an empty control store word {y:04X}")
        self.uir = w
        if decode_ok and self.trace is not None:
            self.trace(self)

    def _flags(self, f, RES, F, C32, OVF, zero, A, B, fill):
        fnz = f["FNZ"]
        lfm = f["LFM"]
        if fnz == 3:
            # a flags load from the A bus, masked by LFM
            if A is None:
                self.err("flags loaded from a floating A bus")
            if f["SSET"]:
                self.err("a flags load in an exception's entry")
            self.n, self.z = (A >> 3) & 1, (A >> 2) & 1
            self.c, self.v = (A >> 1) & 1, A & 1
            if lfm >= 1:
                self.i = (A >> 30) & 1
                self.t = (A >> 29) & 1
                self.m = (A >> 28) & 1
                self.ipl = (A >> 24) & 15
            if lfm == 2:
                self.s = A >> 31
        elif lfm == 1 and not f["SSET"]:
            # SPL: IPL from A[27:24], nothing else
            if A is None:
                self.err("IPL loaded from a floating A bus")
            self.ipl = (A >> 24) & 15
        elif fnz:
            nbit = (31, 15, 7)[f["NSEL"]]
            n = (RES >> nbit) & 1
            if fnz == 1:
                self.n, self.z = n, zero
            else:
                self.n, self.z = n, self.z & zero
        if fnz != 3:
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
        if f["SSET"]:
            # exception entry: supervisor mode, interrupts and tracing off,
            # and no trace pending for the instruction that trapped; out of
            # the message level's registers, or into them; an interrupt's
            # IPL (the NMI is acknowledged at the edge)
            self.s, self.i, self.t, self.TS = 1, 0, 0, 0
            self.m = self.MSGT if lfm == 1 else 0
            if lfm == 1 and self.LT:
                self.ipl = self.LT

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
            return self.s
        if cnd == 9:
            return int(self.SX == self.EX)
        if cnd == 10:
            return self.FK & 1
        if cnd == 11:
            return (self.FK >> 1) & 1
        if cnd == 12:
            return int(self.SX == 15)
        if cnd == 13:
            return self.MQ & 1
        if cnd == 14:
            return self.R & 1
        if cnd == 15:
            return self.MSGT
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

    def reg(self, i, bank=None):
        b = (0 if self.s else self.BANK) if bank is None else bank
        return self.rf[(b << 5) | i]

    @property
    def r(self):
        return [self.reg(i) for i in range(16)]

    @property
    def pc(self):
        """The address of the instruction the next decode starts."""
        return self.PC

    @property
    def out(self):
        return self.sys.output()
