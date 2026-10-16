"""The draft 2 CPU with design changes: the register-transfer model of
studies/v2_hw/rtl.py, its step() copied here with the changes added where
they are marked [D1]..[D3]. With none of them it is the same machine (the
unit tests check cycle for cycle); each is an option.

[D1] The decode table is wider: besides the microaddress and the length,
     the first parcel gives the IR to load (`xir`, so that a guest's
     register fields are where draft 2's selectors look: IR[15:12] and
     IR[11:8]) and an immediate (`ximm`, 16 bits sign-extended, put on the
     B bus by BX = 6). Two more 64K x 16 SRAMs beside the decode table, a
     16-bit register for the immediate and its B-bus drivers.
[D2] Decode table pages: the decode table (and D1's halves) is addressed
     by {ISA, QH}, ISA two bits of the status word (bits 9-8). RTI loads
     them with the rest of the word; exception entry clears them, so that
     the supervisor always runs draft 2 (see mixed.py).
[D3] The control store is reachable to 64K words: NEXT is 16 bits. Decode
     table entries stay 13 bits, so routines start in the first 8K; the
     model needs no change for it, only the placement (mixed.py).

D3 takes the control word's three spare bits (141 of 144 used).
"""

from heron.studies.v2_hw import ucode as uc
from heron.studies.v2_hw.rtl import RTL, RTLError, alu32, cond_true, GLB  # noqa: F401
from heron.studies.v2_hw.system import BusError, Fault

M32 = 0xFFFFFFFF


class RTLX(RTL):
    """mc: a Microcode which may carry the tables: xir, ximm (D1, 64K
    entries each), pages (D2: a list of decode tables, and xir_pages,
    ximm_pages: D1's per page, None for draft 2's own)."""

    def __init__(self, system, mc=None, check=True, lengths=None):
        super().__init__(system, mc=mc, check=check, lengths=lengths)
        # the control store from the words themselves, so that the new
        # fields survive (pack() knows only draft 2's)
        idle = uc.unpack(uc.IDLE)
        self.rom = {}
        for n in self.mc.nodes:
            w = dict(idle)
            w.update(self.mc.word(n))
            self.rom[n.addr] = w
        self.uir = self.rom[0]
        self.xir = getattr(self.mc, "xir", None)
        self.ximm = getattr(self.mc, "ximm", None)
        self.pages = getattr(self.mc, "pages", None)
        self.xir_pages = getattr(self.mc, "xir_pages", None)
        self.ximm_pages = getattr(self.mc, "ximm_pages", None)
        self.IMM = 0
        self.isa = 0

    def flags_word(self):
        return super().flags_word() | (self.isa << 8)          # [D2]

    def _flags(self, f, RES, F, C32, OVF, zero, A, B, fill):
        super()._flags(f, RES, F, C32, OVF, zero, A, B, fill)
        if self.pages:
            # [D2] RTI loads ISA; exception entry clears it
            if f["FNZ"] == 3 and f["LFM"] == 2:
                self.isa = (A >> 8) & 3
            if f["SSET"]:
                self.isa = 0

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
            except BusError:
                fetch_fault = (2, 0, self.FPC)
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
            lanes[0].append(self.flags_word())
        elif bx == 3:
            lanes[0].append(self.FSR)
        elif bx == 4:
            put32(self.FAR)
        elif bx == 5:
            if mem != 4:
                self.err("the map on B without a map read")
            put32(sysm.map_read(MAR))
        elif bx == 6:
            # [D1] the predecoded immediate, sign-extended from 16 bits
            put32(self.IMM)

        # ---- memory data, now that the address side is known
        if data_access and fault is None:
            if reading:
                try:
                    D, h = sysm.read(pa, size, VA, self)
                    hold += h
                except BusError:
                    fault = (2, 0, VA)
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
            try:
                hold += sysm.write(pa, size, MAR, A, self)
            except BusError:
                fault = (2, 0, MAR)
        if mem == 5:
            if chk and not bfull:
                self.err("map write from a floating B bus")
            sysm.map_write(MAR, B)

        # demand fetch faults count only if the decode needs the word
        LEN_next = None
        seq = f["SEQ"]
        if seq == uc.SEQ_DECODE and QH is not None:
            dec = self.pages[self.isa][QH] if self.pages else self.decode[QH]
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
            if self.irqp:
                forced = "irq"
                y = uc.IRQ_ADDR
        else:
            if self.TS:
                forced, y = "trace", uc.TRACE_ADDR
            elif self.irqp:
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
                # [D1] IR translated, and the immediate formed, by the table
                xir, ximm = self.xir, self.ximm
                if self.xir_pages:
                    xir, ximm = self.xir_pages[self.isa], self.ximm_pages[self.isa]
                self.IR = xir[QH] if xir else QH
                if ximm:
                    self.IMM = ximm[QH]
                self.LEN = LEN_next
                self.TS = self.t
                self.instructions += 1
            if forced == "refill":
                self.refills += 1
                if self.refill_from is not None:
                    self.refill_from[(jump, self.mc.by_addr[self.uaddr].name)] += 1
        self.UBRD = f["UBR"]
        # interrupt request: synchronise, then pending = request & I (next)
        self.irqp = self.irqs & self.i
        self.irqs = sysm.irq(self)

        if seq == uc.SEQ_HALT and forced is None and not FAULT:
            if not self.i or not sysm.can_interrupt():
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

