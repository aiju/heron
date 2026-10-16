"""A reference interpreter for the NMOS 6502 (the documented instructions),
to check the 6502 microcode against (`heron v2_guests run m6502 NAME
--lockstep`).

The machine is the one the guest sees on the draft 2 CPU: 64 KB, the
console at 0xE000-0xE7FF (draft 1's I/O page through the page map): a byte
written to 0xE000 is output, a read of 0xE000 is the next input byte (0xFF
at the end), 0xE002 reads 1 while input is waiting. The opcode 0x02, one
of the NMOS 6502's JAM opcodes, halts. RESET jumps through 0xFFFC.

Where the microcode differs from the NMOS 6502, this does too: decimal
mode's result and C are BCD's (for valid BCD operands, as the NMOS
6502's), N, Z and V the binary operation's; a zero-page pointer at 0xFF
takes its high byte from 0x100, and JMP (ind) doesn't wrap in the page.
"""

IO_LO, IO_HI = 0xE000, 0xE800


class M6502:
    def __init__(self, image, inp=b"", start=None):
        self.mem = bytearray(65536)
        self.mem[:len(image)] = image
        self.a = self.x = self.y = 0
        self.s = 0xFD
        self.n = self.v = self.d = self.z = self.c = 0
        self.i = 1
        self.pc = start if start is not None else self.mem[0xFFFC] | (self.mem[0xFFFD] << 8)
        self.inp = bytearray(inp)
        self.inpos = 0
        self.out = bytearray()
        self.halted = False
        self.instructions = 0

    # ---- memory
    def rd(self, a):
        a &= 0xFFFF
        if IO_LO <= a < IO_HI:
            off = (2 * a) & 0xFF
            if off == 0:
                if self.inpos < len(self.inp):
                    self.inpos += 1
                    return self.inp[self.inpos - 1]
                return 0xFF
            if off == 4:
                return 1 if self.inpos < len(self.inp) else 2
            return 0
        return self.mem[a]

    def wr(self, a, v):
        a &= 0xFFFF
        if IO_LO <= a < IO_HI:
            if (2 * a) & 0xFF == 0:
                self.out.append(v & 0xFF)
            return
        self.mem[a] = v & 0xFF

    def rd16(self, a):
        return self.rd(a) | (self.rd((a + 1) & 0xFFFF) << 8)

    def push(self, v):
        self.wr(0x100 | self.s, v)
        self.s = (self.s - 1) & 0xFF

    def pull(self):
        self.s = (self.s + 1) & 0xFF
        return self.rd(0x100 | self.s)

    # ---- flags
    def nz(self, v):
        v &= 0xFF
        self.n, self.z = v >> 7, int(v == 0)
        return v

    def p(self, b=1):
        return ((self.n << 7) | (self.v << 6) | 0x20 | (b << 4) | (self.d << 3) | (self.i << 2)
                | (self.z << 1) | self.c)

    def setp(self, v):
        self.n, self.v, self.d = (v >> 7) & 1, (v >> 6) & 1, (v >> 3) & 1
        self.i, self.z, self.c = (v >> 2) & 1, (v >> 1) & 1, v & 1

    def adc(self, m):
        a, c = self.a, self.c
        r = a + m + c
        self.v = int(((a ^ r) & (m ^ r) & 0x80) != 0)
        self.nz(r)
        if self.d:
            lo = (a & 0x0F) + (m & 0x0F) + c
            if lo >= 0x0A:
                lo = ((lo + 0x06) & 0x0F) + 0x10
            r = (a & 0xF0) + (m & 0xF0) + lo
            if r >= 0xA0:
                r += 0x60
        self.c = int(r > 0xFF)
        self.a = r & 0xFF

    def sbc(self, m):
        a, c = self.a, self.c
        r = a - m - (1 - c)
        self.v = int(((a ^ m) & (a ^ r) & 0x80) != 0)
        self.nz(r)
        self.c = int(r >= 0)
        if self.d:
            lo = (a & 0x0F) - (m & 0x0F) + c - 1
            if lo < 0:
                lo = ((lo - 0x06) & 0x0F) - 0x10
            r = (a & 0xF0) - (m & 0xF0) + lo
            if r < 0:
                r -= 0x60
        self.a = r & 0xFF

    def cmp(self, reg, m):
        r = reg - m
        self.c = int(r >= 0)
        self.nz(r)

    # ---- addressing: returns the address (or None for A / implied / imm)
    def ea(self, mode):
        pc = self.pc
        if mode == "imm":
            self.pc += 1
            return pc
        if mode == "zp":
            self.pc += 1
            return self.rd(pc)
        if mode == "zpx":
            self.pc += 1
            return (self.rd(pc) + self.x) & 0xFF
        if mode == "zpy":
            self.pc += 1
            return (self.rd(pc) + self.y) & 0xFF
        if mode == "abs":
            self.pc += 2
            return self.rd16(pc)
        if mode == "abx":
            self.pc += 2
            return (self.rd16(pc) + self.x) & 0xFFFF
        if mode == "aby":
            self.pc += 2
            return (self.rd16(pc) + self.y) & 0xFFFF
        if mode == "izx":
            self.pc += 1
            z = (self.rd(pc) + self.x) & 0xFF
            return self.rd16(z)            # a pointer at 0xFF: its high byte from 0x100
        if mode == "izy":
            self.pc += 1
            z = self.rd(pc)
            return (self.rd16(z) + self.y) & 0xFFFF
        raise ValueError(mode)

    def step(self):
        op = self.rd(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        name, mode = OPS.get(op, (None, None))
        if name is None:
            raise RuntimeError(f"illegal opcode {op:02X} at {self.pc - 1:04X}")
        getattr(self, "op_" + name.lower())(mode)
        self.pc &= 0xFFFF
        self.instructions += 1

    def run(self, max_instructions=200_000_000):
        while not self.halted:
            self.step()
            if self.instructions > max_instructions:
                raise RuntimeError("instruction limit")
        return self

    def state(self):
        return {"a": self.a, "x": self.x, "y": self.y, "s": self.s, "pc": self.pc,
                "nzcv": (self.n << 3) | (self.z << 2) | (self.c << 1) | self.v,
                "d": self.d}

    # ---- instructions
    def _m(self, mode):
        return self.rd(self.ea(mode))

    def op_lda(self, m):
        self.a = self.nz(self._m(m))

    def op_ldx(self, m):
        self.x = self.nz(self._m(m))

    def op_ldy(self, m):
        self.y = self.nz(self._m(m))

    def op_sta(self, m):
        self.wr(self.ea(m), self.a)

    def op_stx(self, m):
        self.wr(self.ea(m), self.x)

    def op_sty(self, m):
        self.wr(self.ea(m), self.y)

    def op_adc(self, m):
        self.adc(self._m(m))

    def op_sbc(self, m):
        self.sbc(self._m(m))

    def op_and(self, m):
        self.a = self.nz(self.a & self._m(m))

    def op_ora(self, m):
        self.a = self.nz(self.a | self._m(m))

    def op_eor(self, m):
        self.a = self.nz(self.a ^ self._m(m))

    def op_cmp(self, m):
        self.cmp(self.a, self._m(m))

    def op_cpx(self, m):
        self.cmp(self.x, self._m(m))

    def op_cpy(self, m):
        self.cmp(self.y, self._m(m))

    def op_bit(self, m):
        v = self._m(m)
        self.z = int((self.a & v) == 0)
        self.n, self.v = v >> 7, (v >> 6) & 1

    def _rmw(self, m, f):
        if m == "acc":
            self.a = f(self.a)
        else:
            a = self.ea(m)
            self.wr(a, f(self.rd(a)))

    def op_asl(self, m):
        def f(v):
            self.c = v >> 7
            return self.nz(v << 1)
        self._rmw(m, f)

    def op_lsr(self, m):
        def f(v):
            self.c = v & 1
            return self.nz(v >> 1)
        self._rmw(m, f)

    def op_rol(self, m):
        def f(v):
            r = (v << 1) | self.c
            self.c = v >> 7
            return self.nz(r)
        self._rmw(m, f)

    def op_ror(self, m):
        def f(v):
            r = (v >> 1) | (self.c << 7)
            self.c = v & 1
            return self.nz(r)
        self._rmw(m, f)

    def op_inc(self, m):
        self._rmw(m, lambda v: self.nz(v + 1))

    def op_dec(self, m):
        self._rmw(m, lambda v: self.nz(v - 1))

    def op_inx(self, m):
        self.x = self.nz(self.x + 1)

    def op_iny(self, m):
        self.y = self.nz(self.y + 1)

    def op_dex(self, m):
        self.x = self.nz(self.x - 1)

    def op_dey(self, m):
        self.y = self.nz(self.y - 1)

    def op_tax(self, m):
        self.x = self.nz(self.a)

    def op_tay(self, m):
        self.y = self.nz(self.a)

    def op_txa(self, m):
        self.a = self.nz(self.x)

    def op_tya(self, m):
        self.a = self.nz(self.y)

    def op_tsx(self, m):
        self.x = self.nz(self.s)

    def op_txs(self, m):
        self.s = self.x

    def op_pha(self, m):
        self.push(self.a)

    def op_php(self, m):
        self.push(self.p(1))

    def op_pla(self, m):
        self.a = self.nz(self.pull())

    def op_plp(self, m):
        self.setp(self.pull())

    def _branch(self, take):
        off = self.rd(self.pc)
        self.pc += 1
        if take:
            self.pc = (self.pc + (off - 256 if off & 0x80 else off)) & 0xFFFF

    def op_bpl(self, m):
        self._branch(not self.n)

    def op_bmi(self, m):
        self._branch(self.n)

    def op_bvc(self, m):
        self._branch(not self.v)

    def op_bvs(self, m):
        self._branch(self.v)

    def op_bcc(self, m):
        self._branch(not self.c)

    def op_bcs(self, m):
        self._branch(self.c)

    def op_bne(self, m):
        self._branch(not self.z)

    def op_beq(self, m):
        self._branch(self.z)

    def op_jmp(self, m):
        a = self.rd16(self.pc)
        if m == "ind":                       # without the NMOS 6502's page wrap
            a = self.rd16(a)
        self.pc = a

    def op_jsr(self, m):
        a = self.rd16(self.pc)
        ret = (self.pc + 1) & 0xFFFF
        self.push(ret >> 8)
        self.push(ret & 0xFF)
        self.pc = a

    def op_rts(self, m):
        lo = self.pull()
        self.pc = ((self.pull() << 8) | lo) + 1

    def op_rti(self, m):
        self.setp(self.pull())
        lo = self.pull()
        self.pc = (self.pull() << 8) | lo

    def op_brk(self, m):
        ret = (self.pc + 1) & 0xFFFF
        self.push(ret >> 8)
        self.push(ret & 0xFF)
        self.push(self.p(1))
        self.i = 1
        self.pc = self.rd16(0xFFFE)

    def op_clc(self, m):
        self.c = 0

    def op_sec(self, m):
        self.c = 1

    def op_cli(self, m):
        self.i = 0

    def op_sei(self, m):
        self.i = 1

    def op_cld(self, m):
        self.d = 0

    def op_sed(self, m):
        self.d = 1

    def op_clv(self, m):
        self.v = 0

    def op_nop(self, m):
        pass

    def op_jam(self, m):
        self.halted = True
        self.pc = (self.pc - 1) & 0xFFFF


def _ops():
    t = {0x02: ("JAM", None)}
    alu = ["ORA", "AND", "EOR", "ADC", "STA", "LDA", "CMP", "SBC"]
    modes01 = ["izx", "zp", "imm", "abs", "izy", "zpx", "aby", "abx"]
    for i, name in enumerate(alu):
        for j, mode in enumerate(modes01):
            if name == "STA" and mode == "imm":
                continue
            t[(i << 5) | (j << 2) | 1] = (name, mode)
    rmw = ["ASL", "ROL", "LSR", "ROR"]
    for i, name in enumerate(rmw):
        base = i << 5
        t[base | 0x06] = (name, "zp")
        t[base | 0x0A] = (name, "acc")
        t[base | 0x0E] = (name, "abs")
        t[base | 0x16] = (name, "zpx")
        t[base | 0x1E] = (name, "abx")
    for op, mode in ((0xC6, "zp"), (0xCE, "abs"), (0xD6, "zpx"), (0xDE, "abx")):
        t[op] = ("DEC", mode)
        t[op + 0x20] = ("INC", mode)
    t.update({0x86: ("STX", "zp"), 0x8E: ("STX", "abs"), 0x96: ("STX", "zpy"),
              0xA2: ("LDX", "imm"), 0xA6: ("LDX", "zp"), 0xAE: ("LDX", "abs"),
              0xB6: ("LDX", "zpy"), 0xBE: ("LDX", "aby"),
              0x84: ("STY", "zp"), 0x8C: ("STY", "abs"), 0x94: ("STY", "zpx"),
              0xA0: ("LDY", "imm"), 0xA4: ("LDY", "zp"), 0xAC: ("LDY", "abs"),
              0xB4: ("LDY", "zpx"), 0xBC: ("LDY", "abx"),
              0xC0: ("CPY", "imm"), 0xC4: ("CPY", "zp"), 0xCC: ("CPY", "abs"),
              0xE0: ("CPX", "imm"), 0xE4: ("CPX", "zp"), 0xEC: ("CPX", "abs"),
              0x24: ("BIT", "zp"), 0x2C: ("BIT", "abs"),
              0x4C: ("JMP", "abs"), 0x6C: ("JMP", "ind"), 0x20: ("JSR", "abs"),
              0x60: ("RTS", None), 0x40: ("RTI", None), 0x00: ("BRK", None),
              0x10: ("BPL", None), 0x30: ("BMI", None), 0x50: ("BVC", None),
              0x70: ("BVS", None), 0x90: ("BCC", None), 0xB0: ("BCS", None),
              0xD0: ("BNE", None), 0xF0: ("BEQ", None),
              0x08: ("PHP", None), 0x28: ("PLP", None), 0x48: ("PHA", None),
              0x68: ("PLA", None), 0x18: ("CLC", None), 0x38: ("SEC", None),
              0x58: ("CLI", None), 0x78: ("SEI", None), 0xB8: ("CLV", None),
              0xD8: ("CLD", None), 0xF8: ("SED", None), 0xEA: ("NOP", None),
              0xAA: ("TAX", None), 0x8A: ("TXA", None), 0xA8: ("TAY", None),
              0x98: ("TYA", None), 0xBA: ("TSX", None), 0x9A: ("TXS", None),
              0xE8: ("INX", None), 0xC8: ("INY", None), 0xCA: ("DEX", None),
              0x88: ("DEY", None)})
    return t


OPS = _ops()
LENGTH = {"imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "izx": 2, "izy": 2, "abs": 3, "abx": 3,
          "aby": 3, "ind": 3, "acc": 1, None: 1}
