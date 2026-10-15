"""Register-transfer model of the draft 1b implementation.

Runs the microcode ROM images from ucode.py cycle by cycle on a
functional model of the datapath (buses, registers, 74181 ALU, result
multiplexer, flags, sequencer). It is the reference for the chip-level
netlist: the netlist must do what this model does, cycle for cycle. The
model checks the rules the microcode must follow (one driver per bus lane,
no floating value consumed, matching register-file write addresses) and
stops with RTLError when one is broken.

    m = RTL(image, inp=b"...")
    m.run()
    m.r, m.hi, m.mem, m.out, m.cycles
"""

from . import ucode as uc
from heron.studies.v1_isa.v1common import M32, RAM_SIZE, cond_true

IO_SIZE = 256


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


class IODev:
    """The I/O page seen from a 16-bit bus. Registers are 32 bits, read and
    written a half at a time (RFC 0004)."""

    def __init__(self, inp=b""):
        self.inp = bytearray(inp)
        self.pos = 0
        self.out = bytearray()
        self.period = 0
        self.count = 0
        self.flag = 0
        self.last_empty = False
        self.cyc_hi = 0

    def read(self, off, cycle):
        off &= 0xFE
        if off == 0x00:
            if self.pos < len(self.inp):
                self.pos += 1
                self.last_empty = False
                return self.inp[self.pos - 1]
            self.last_empty = True
            return 0xFFFF
        if off == 0x02:
            return 0xFFFF if self.last_empty else 0
        if off == 0x04:
            return 1 if self.pos < len(self.inp) else 2
        if off == 0x08:
            return self.period & 0xFFFF
        if off == 0x0A:
            return self.period >> 16
        if off == 0x0C:
            return self.flag
        if off == 0x10:
            self.cyc_hi = (cycle >> 16) & 0xFFFF
            return cycle & 0xFFFF
        if off == 0x12:
            return self.cyc_hi
        return 0

    def write(self, off, v, lanes):
        off &= 0xFE
        if off == 0x00 and lanes & 1:
            self.out.append(v & 0xFF)
        elif off == 0x08:
            self.period, self.count = v, 0
            if v == 0:
                self.flag = 0
        elif off == 0x0A:
            self.period = (self.period & 0xFFFF) | (v << 16)
            self.count = 0
            if self.period == 0:
                self.flag = 0
        elif off in (0x0C, 0x0E):
            self.flag = 0

    def tick(self):
        if self.period:
            self.count += 1
            if self.count >= self.period:
                self.flag = 1
                self.count = 0


class RTL:
    def __init__(self, image=None, inp=b"", mc=None, check=True):
        self.mc = mc or uc.built()
        rom = self.mc.rom()
        idle = uc.unpack(uc.IDLE)
        self.rom = [None] * (1 << (uc.FAULT_BIT + 3))
        cache = {}
        for a in range(len(self.rom)):
            w = rom.get(a)
            if w is None:
                self.rom[a] = idle
            else:
                if w not in cache:
                    cache[w] = uc.unpack(w)
                self.rom[a] = cache[w]
        self.decode = self.mc.decode_rom()
        self.mem = bytearray(RAM_SIZE)
        if image is not None:
            for a, b in image.mem.items():
                self.mem[a] = b
        self.dev = IODev(inp)
        self.check = check
        self.rf = [0] * 32
        self.R = self.T = self.MAR = self.PC = self.IR = 0
        self.LEN = self.LC = self.MQ = self.SX = 0
        self.S33 = self.SGN = self.CL = 0
        self.n = self.z = self.c = self.v = self.i = 0
        self.irqs = self.irqp = 0
        self.uir = self.rom[0]
        self.reset_cycles = 2
        self.cycles = 0              # cycles since the reset routine's fetch
        self.total = 0
        self.started = False
        self.halted = False
        self.fetches = []            # (cycle, address, parcel) of opcode fetches
        self.fetch_log = None
        self.uaddr = 0
        self.ucount = None           # microaddress -> executions, if wanted
        self.reg_written = [False] * 32

    # ---- helpers -----------------------------------------------------

    def err(self, msg):
        raise RTLError(f"cycle {self.cycles} uaddr {self.uaddr:04X}: {msg}")

    def flags_byte(self):
        return self.v | (self.c << 1) | (self.z << 2) | (self.n << 3) | (self.i << 4)

    def mem_read(self, addr, io, fault):
        if io:
            if fault:
                return 0
            return self.dev.read(addr & 0xFF, self.cycles) & 0xFFFF
        a = addr & 0xFFFFE
        return self.mem[a] | (self.mem[a + 1] << 8)

    # ---- one clock cycle ---------------------------------------------

    def step(self):
        f = self.uir
        IR, T, R, MAR, PC = self.IR, self.T, self.R, self.MAR, self.PC
        chk = self.check

        # register file addresses
        rfk = f["RFK"]
        srcs = ((IR >> 8) & 15, IR & 15, self.SX, rfk & 15)
        rfa = srcs[f["RFA"]] | (rfk & 16 if f["RFA"] == 3 else 0)
        rfb = srcs[f["RFB"]] | (rfk & 16 if f["RFB"] == 3 else 0)

        # A bus (unless bridged from B), then B bus
        bridge = f["ABR"]
        A = None
        if not bridge:
            drv = []
            if f["ARF"]:
                drv.append(self.rf[rfa])
            if f["APC"]:
                drv.append(PC)
            if f["AR"]:
                drv.append(R)
            if f["AR2"]:
                sina = (0, R >> 31, self.c, self.MQ >> 31)[f["SINA"]]
                drv.append(((R << 1) | sina) & M32)
            if len(drv) > 1:
                self.err("A bus contention")
            if drv:
                A = drv[0]
        fsel = f["FSEL"]
        if fsel in (5, 6) and A is None:
            fill = None
        else:
            fill = (0, 1, (IR >> 7) & 1, (T >> 7) & 1, (T >> 15) & 1,
                    (A or 0) >> 31 & 1, (A or 0) >> 15 & 1, self.SGN)[fsel]
        v8sel = f["V8"]
        if v8sel == 0:
            v8 = (IR << 1) & 0xFE
        elif v8sel == 1:
            v8 = f["KONST"]
        elif v8sel == 2:
            v8 = 0xFF if fill else 0
        else:
            v8 = self.LC
        fill8 = 0xFF if fill else 0
        lanes = [[], [], [], []]
        if f["BRF"]:
            x = self.rf[rfb]
            for k in range(4):
                lanes[k].append((x >> (8 * k)) & 0xFF)
        if f["BR"]:
            for k in range(4):
                lanes[k].append((R >> (8 * k)) & 0xFF)
        if f["BMQ"]:
            for k in range(4):
                lanes[k].append((self.MQ >> (8 * k)) & 0xFF)
        if f["BT0"]:
            lanes[0].append((T >> 8) & 0xFF if (f["TLANE"] and MAR & 1) else T & 0xFF)
        if f["BT1"]:
            lanes[1].append((T >> 8) & 0xFF)
        if f["BT23"]:
            lanes[2].append((T >> 16) & 0xFF)
            lanes[3].append((T >> 24) & 0xFF)
        if f["BT2"]:
            t2 = (T << 1) & 0xFFFF
            lanes[0].append(t2 & 0xFF)
            lanes[1].append(t2 >> 8)
        if f["BS0"]:
            lanes[0].append(v8)
        if f["BFL"]:
            lanes[0].append(self.flags_byte())
        if f["BF1"]:
            lanes[1].append(fill8)
        if f["BF23"]:
            lanes[2].append(fill8)
            lanes[3].append(fill8)
        B = 0
        bfull = True
        for k in range(4):
            ln = lanes[k]
            if len(ln) > 1:
                self.err(f"B bus contention on byte {k}")
            if ln:
                if ln[0] is None or (fill is None and (f["BF1"] or f["BF23"] or v8sel == 2)):
                    self.err("fill from a floating A bus")
                B |= ln[0] << (8 * k)
            else:
                bfull = False
        if bridge:
            if f["ARF"] or f["APC"] or f["AR"] or f["AR2"]:
                self.err("A bus contention with the bridge")
            if fsel in (5, 6) and (f["BF1"] or f["BF23"] or v8sel == 2):
                self.err("fill from the A bus while bridged")
            A = B if bfull else None
            if fsel in (5, 6):
                fill = (A >> (31 if fsel == 5 else 15)) & 1

        # ALU
        mqm, ms = f["MQM"], f["MS"]
        cin = (0, 1, self.c, (A or 0) >> 31, self.MQ >> 31, self.SGN, self.MQ & 1,
               self.S33 ^ 1)[f["CIN"]]
        gs = 0
        if ms:
            if ms == 1:                 # add X if the multiplier bit is 1
                ga, gs = self.MQ & 1, 0
            elif ms == 2:               # subtract X if it is 1 (signed: the top bit)
                ga, gs = 0, self.MQ & 1
            elif mqm == 2:              # non-restoring divide step
                ga, gs = self.S33, self.S33 ^ 1
            else:                       # fix-up: add B if negative
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
        s0 = s & 1
        # V = (A31 ^ (B31 ^ S0)) & (A31 ^ F31): S0 tells adding from subtracting
        vt2 = ((Av >> 31) ^ (B >> 31) ^ s0) & 1
        OVF = vt2 & ((Av >> 31) ^ (F >> 31)) & 1
        alu_ok = (A is not None or not uses_a) and (bfull or not uses_b)

        # result multiplexer
        rms = f["RMS"]
        if rms == 0:
            RES = F
        elif rms == 1:
            # 74HCT151: SIN field, plus 4 in multiply steps (MD = x01). The
            # sign of a Booth step's 33-bit sum, F31 ^ OVF, is A31 when the
            # operands' signs agree and F31 when they don't (a 74HCT157)
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

        # memory and the data bus
        addrmar = f["ADDRMAR"]
        memrd, memwr = f["MEMRD"], f["MEMWR"]
        if addrmar:
            addr = MAR | (2 if f["HIWORD"] else 0)
            io = (MAR >> 31) & 1
        else:
            addr = PC
            io = 0
        size = f["SIZE"]
        fault = bool(addrmar and (memrd or memwr)
                     and ((size == 3 and MAR & 3) or (size == 2 and MAR & 1)))
        D = None
        if memrd:
            D = self.mem_read(addr, io, fault)
        dsrc = f["DSRC"]
        if dsrc:
            if D is not None:
                self.err("data bus contention")
            if chk and not alu_ok:
                self.err("store data from a floating bus")
            if dsrc == 3:
                D = RES & 0xFFFF
            elif dsrc == 2:
                D = RES >> 16
            else:
                D = (RES & 0xFF) * 0x101

        # sequencer
        seq = f["SEQ"]
        if fault:
            y = 0
            dec = 0
        elif seq == 0:
            cnd = f["COND"]
            if cnd == 0:
                cv = 0
            elif cnd == 1:
                cv = int(self.LC == 255)
            elif cnd == 2:
                cv = R >> 31
            elif cnd == 3:
                cv = self.CL
            elif cnd in (4, 7):
                # the test before the polarity bit (cc0): the routine was
                # chosen by the decode ROM for this polarity
                cc = (IR >> 4) & 15 if f["CCB"] else (IR >> 8) & 15
                if chk and (cnd == 7) != (cc & 1):
                    self.err("condition polarity doesn't match the instruction")
                cv = self.bcond(cc & 14) ^ (cnd == 7)
            elif cnd == 5:
                cv = self.MQ >> 31
            else:
                cv = int(self.LC & 15 == 15)
            if cnd:
                if chk and f["NEXT"] & 1:
                    self.err("branch with NEXT[0] set")
                y = (f["NEXT"] & ~1) | cv
            else:
                y = f["NEXT"]
        elif seq == 1:
            if not f["GOIRQ"] and D is None:
                self.err("decode with nothing on the data bus")
            dec = self.decode[(f["GOIRQ"] << 16) | (D or 0)]
            y = dec & ((1 << uc.Y_BITS) - 1)
        elif seq == 2:
            if D is None:
                self.err("dispatch with nothing on the data bus")
            y = (f["NEXT"] & ~31) | (((D >> 8) & 15) << 1) | int(D & 0xFF != 0)
        else:
            self.err("bad SEQ")

        # ---- clock edge -------------------------------------------------
        if memwr and not fault:
            if D is None:
                self.err("write with nothing on the data bus")
            if size == 1:
                ln = 2 if addr & 1 else 1
            else:
                ln = 3
            if io:
                self.dev.write(addr & 0xFF, D, ln)
            else:
                a = addr & 0xFFFFE
                if ln & 1:
                    self.mem[a] = D & 0xFF
                if ln & 2:
                    self.mem[a + 1] = D >> 8
        if f["RFWE"]:
            if rfa != rfb:
                self.err("register file copies written at different addresses")
            if chk and not bfull:
                self.err("register write from a floating bus")
            if rfa or f["WR0"]:
                self.rf[rfa] = B
                self.reg_written[rfa] = True
        if f["LDR"]:
            if chk and not alu_ok:
                self.err("R loaded from a floating bus")
            self.R = RES
        if f["LDMAR"]:
            src = A if f["MARSRC"] else RES
            if chk and (src is None or (not f["MARSRC"] and not alu_ok)):
                self.err("MAR loaded from a floating bus")
            self.MAR = src & 0x800FFFFF
        if f["LDTL"]:
            self.T = (self.T & 0xFFFF0000) | D
        if f["LDTH"]:
            self.T = (self.T & 0xFFFF) | (D << 16)
        if f["LDX"]:
            if chk and (D is None or f["LDIR"]):
                self.err("SX loaded without an extension parcel")
            self.SX = (D >> 12) & 15
        if f["LDIR"]:
            self.IR = D
            self.SX = (D >> 4) & 15
            self.LEN = self.decode[D] >> uc.Y_BITS
            if self.fetch_log is not None:
                self.fetch_log.append((self.cycles if self.started else -1, addr, D))
        if f["LDPC"]:
            if chk and not alu_ok:
                self.err("PC loaded from a floating bus")
            if not f["PCCOND"] or self.bcond((IR >> 8) & 15):
                self.PC = RES & 0xFFFFFFFE
        elif memrd and not addrmar:
            self.PC = (PC + 2) & M32
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
                self.CL = int(B == 0)
            elif cls == 1:
                self.CL = C32
            else:
                hz = int(B >> (16 if cls in (2, 4) else 15) == 0)
                self.CL = hz if cls in (2, 3) else self.CL & hz
        # flags
        fnz = f["FNZ"]
        if fnz:
            if chk and not bfull:
                self.err("flags from a floating bus")
            if fnz == 1:
                self.n, self.z = B >> 31, int(B == 0)
            elif fnz == 2:
                self.n, self.z = B >> 31, self.z & int(B == 0)
            else:
                self.n, self.z = (B >> 3) & 1, (B >> 2) & 1
        fc = f["FC"]
        if f["CZERO"]:
            self.c = 0
        elif fc == 1:
            cs = f["CSRC"]
            if cs == 0:
                self.c = (B >> 1) & 1
            elif cs == 1:
                self.c = F & 1
            elif cs == 2:
                self.c = (F >> 7) & 1
            elif cs == 3:
                self.c = (F >> 8) & 1
            elif cs == 4:
                self.c = (F >> 15) & 1
            elif cs == 5:
                self.c = F >> 31
            elif cs == 6:
                self.c = ((F >> 7) ^ fill) & 1
            else:
                self.c = ((F >> 15) ^ fill) & 1
        elif fc == 2:
            self.c = C32
        elif fc == 3:
            self.c = self.CL ^ 1
        fv = f["FV"]
        if fv == 7:
            self.v = OVF
        elif fv == 2:
            self.v = 0
        elif fv == 3:
            self.v = B & 1
        elif fv == 4:
            self.v = self.CL ^ 1
        elif fv == 5:
            self.v = 1
        fi = f["FI"]
        if fi == 1:
            self.i = 1
        elif fi == 2:
            self.i = 0
        elif fi == 3:
            self.i = (B >> 4) & 1
        # interrupt request: synchronise, then pending = request & I (next)
        irqp = self.irqp
        self.irqp = self.irqs & self.i
        self.irqs = self.dev.flag
        self.dev.tick()

        if f["HALT"]:
            if not self.i or not self.dev.period:
                self.halted = True
        self.uaddr = (irqp << uc.IRQP_BIT) | y
        if fault:
            self.uaddr |= uc.fault_page(self.LEN)
        if self.ucount is not None:
            self.ucount[self.uaddr] += 1
        self.uir = self.rom[self.uaddr]
        self.total += 1
        if self.started:
            self.cycles += 1
        elif seq == 1 and f["LDIR"]:
            self.started = True             # the reset routine fetched address 0

    def bcond(self, cc):
        if cc == 15:
            return 0
        return cond_true(self, cc)

    def run(self, max_cycles=50_000_000):
        while not self.halted:
            self.step()
            if self.cycles > max_cycles:
                raise RTLError(f"cycle limit reached at PC {self.PC:08X}")
        return self

    @property
    def r(self):
        return self.rf[:16]

    @property
    def hi(self):
        return self.rf[uc.HI]

    @property
    def out(self):
        return bytes(self.dev.out)
