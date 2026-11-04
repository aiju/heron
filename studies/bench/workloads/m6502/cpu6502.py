"""The m6502 workload's reference: a 6502 emulator in plain Python.

    cpu = Cpu(mem)              # mem: 64 KB, the vectors at $FFFA
    cpu.run()                   # until the program writes DONE, or jams
    cpu.a, cpu.x, cpu.y, cpu.s, cpu.p, cpu.cycles, cpu.instructions, cpu.out

It is written to be obviously right rather than fast, and on purpose
unlike the Heron emulator it checks (emu.s and the ops_*.s files): it
decodes each opcode from its bit fields (aaabbbcc) instead of a table of
handlers, computes addresses and cycle counts from the addressing mode by
the datasheet's rules instead of per opcode, and keeps the status register
P as its eight bits, updated as each instruction says.

The machine around the CPU is the workload's: RAM below $C000, the I/O
page at $C000 (OUT appends a byte to the output, DONE stops the run),
and ROM from $D000 up, where writes are ignored. Reads see memory.
An undocumented opcode jams the CPU, as some NMOS ones do; the run stops
there with `jammed` set.

`python3 -m heron.studies.bench.workloads.m6502.cpu6502` runs the
self-test: the decoder against the assembler's table, decimal mode
against a second formulation for every input, small programs with known
results, and the workload's program at both sizes against its results
computed in Python (program_results).
"""

OUT, DONE = 0xC000, 0xC001
IO, ROM = 0xC000, 0xD000

C, Z, I, D, B, U, V, N = (1 << k for k in range(8))

_GROUP1 = ["ORA", "AND", "EOR", "ADC", "STA", "LDA", "CMP", "SBC"]
_GROUP1_MODES = ["izx", "zp", "imm", "abs", "izy", "zpx", "aby", "abx"]
_GROUP2 = ["ASL", "ROL", "LSR", "ROR", "STX", "LDX", "DEC", "INC"]
_GROUP2_MODES = ["imm", "zp", "imp", "abs", None, "zpx", None, "abx"]
_GROUP3 = [None, "BIT", "JMP", "JMP", "STY", "LDY", "CPY", "CPX"]
_SINGLE = {
    0x00: "BRK", 0x20: "JSR", 0x40: "RTI", 0x60: "RTS",
    0x08: "PHP", 0x28: "PLP", 0x48: "PHA", 0x68: "PLA",
    0x88: "DEY", 0xA8: "TAY", 0xC8: "INY", 0xE8: "INX",
    0x18: "CLC", 0x38: "SEC", 0x58: "CLI", 0x78: "SEI",
    0x98: "TYA", 0xB8: "CLV", 0xD8: "CLD", 0xF8: "SED",
    0x8A: "TXA", 0x9A: "TXS", 0xAA: "TAX", 0xBA: "TSX", 0xCA: "DEX", 0xEA: "NOP",
}
_BRANCH = {0: ("BPL", "BMI"), 1: ("BVC", "BVS"), 2: ("BCC", "BCS"), 3: ("BNE", "BEQ")}


def decode(op):
    """(mnemonic, mode) of a documented opcode, else None."""
    aaa, bbb, cc = op >> 5, (op >> 2) & 7, op & 3
    if op in _SINGLE:
        mode = "abs" if op == 0x20 else "imp"
        return _SINGLE[op], mode
    if cc == 1:
        if op == 0x89:                          # STA #imm doesn't exist
            return None
        return _GROUP1[aaa], _GROUP1_MODES[bbb]
    if cc == 2:
        mn, mode = _GROUP2[aaa], _GROUP2_MODES[bbb]
        if mode is None or mode == "imm" and mn != "LDX":
            return None
        if mode == "imp" and mn not in ("ASL", "ROL", "LSR", "ROR"):
            return None
        if mn in ("STX", "LDX"):                # ,X becomes ,Y
            mode = {"zpx": "zpy", "abx": "aby"}.get(mode, mode)
            if mn == "STX" and mode == "aby":
                return None
        return mn, mode
    if cc == 0:
        if bbb == 4:
            return _BRANCH[aaa >> 1][aaa & 1], "rel"
        mn = _GROUP3[aaa]
        if mn is None:
            return None
        allowed = {"BIT": "zp abs", "JMP": "abs", "STY": "zp abs zpx",
                   "LDY": "imm zp abs zpx abx", "CPY": "imm zp abs",
                   "CPX": "imm zp abs"}[mn].split()
        mode = {0: "imm", 1: "zp", 3: "abs", 5: "zpx", 7: "abx"}.get(bbb)
        if mode not in allowed:
            return None
        if op == 0x6C:
            mode = "ind"
        return mn, mode
    return None


_READS = {"ORA", "AND", "EOR", "ADC", "LDA", "CMP", "SBC", "LDX", "LDY", "CPX", "CPY", "BIT"}
_RMW = {"ASL", "ROL", "LSR", "ROR", "INC", "DEC"}
_STORES = {"STA", "STX", "STY"}


def cycles(mn, mode):
    """The base cycle count, by the datasheet's rules: a read pays one more
    when abs,X, abs,Y or (zp),Y crosses a page, a taken branch one more and
    one again when it lands on another page (Cpu adds those)."""
    if mode == "imp":
        return {"BRK": 7, "RTI": 6, "RTS": 6, "PHA": 3, "PHP": 3,
                "PLA": 4, "PLP": 4}.get(mn, 2)
    if mn == "JSR":
        return 6
    if mn == "JMP":
        return 3 if mode == "abs" else 5
    if mode == "rel":
        return 2
    base = {"imm": 2, "zp": 3, "zpx": 4, "zpy": 4, "abs": 4, "abx": 4, "aby": 4,
            "izx": 6, "izy": 5}[mode]
    if mn in _RMW:
        return base + 2 + (mode == "abx")
    if mn in _STORES and mode in ("abx", "aby", "izy"):
        return base + 1
    return base


class Jam(Exception):
    pass


class Cpu:
    def __init__(self, mem):
        self.mem = bytearray(mem)
        self.a = self.x = self.y = 0
        self.s = 0xFD                       # as after reset's three dummy pushes
        self.p = U | I
        self.pc = self.word(0xFFFC)
        self.cycles = 7                     # reset takes seven cycles
        self.instructions = 0
        self.out = bytearray()
        self.done = False
        self.jammed = False

    # ---- memory ----

    def read(self, addr):
        return self.mem[addr & 0xFFFF]

    def word(self, addr):
        return self.read(addr) | self.read(addr + 1) << 8

    def write(self, addr, v):
        addr &= 0xFFFF
        if addr < IO:
            self.mem[addr] = v & 0xFF
        elif addr == OUT:
            self.out.append(v & 0xFF)
        elif addr == DONE:
            self.done = True
        # the rest of the I/O page, and ROM, ignore writes

    def push(self, v):
        self.mem[0x100 + self.s] = v & 0xFF
        self.s = (self.s - 1) & 0xFF

    def pull(self):
        self.s = (self.s + 1) & 0xFF
        return self.mem[0x100 + self.s]

    def fetch(self):
        v = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    # ---- flags ----

    def flag(self, f, on):
        self.p = self.p | f if on else self.p & ~f

    def nz(self, v):
        v &= 0xFF
        self.flag(Z, v == 0)
        self.flag(N, v & 0x80)
        return v

    # ---- addressing ----

    def address(self, mode, read):
        """The operand's address; a read across a page costs a cycle."""
        if mode == "zp":
            return self.fetch()
        if mode == "zpx":
            return (self.fetch() + self.x) & 0xFF
        if mode == "zpy":
            return (self.fetch() + self.y) & 0xFF
        if mode in ("abs", "abx", "aby", "ind"):
            base = self.fetch() | self.fetch() << 8
            if mode == "abs":
                return base
            if mode == "ind":                   # the NMOS bug: the high byte
                hi = (base & 0xFF00) | ((base + 1) & 0xFF)   # stays in the page
                return self.read(base) | self.read(hi) << 8
            addr = (base + (self.x if mode == "abx" else self.y)) & 0xFFFF
            if read and (addr ^ base) & 0xFF00:
                self.cycles += 1
            return addr
        if mode == "izx":
            zp = (self.fetch() + self.x) & 0xFF
            return self.read(zp) | self.read((zp + 1) & 0xFF) << 8
        if mode == "izy":
            zp = self.fetch()
            base = self.read(zp) | self.read((zp + 1) & 0xFF) << 8
            addr = (base + self.y) & 0xFFFF
            if read and (addr ^ base) & 0xFF00:
                self.cycles += 1
            return addr
        raise ValueError(mode)

    # ---- arithmetic ----

    def adc(self, m):
        a, c = self.a, self.p & C
        binary = a + m + c
        if not self.p & D:
            self.flag(C, binary > 0xFF)
            self.flag(V, ~(a ^ m) & (a ^ binary) & 0x80)
            self.a = self.nz(binary)
            return
        # decimal, as an NMOS 6502 does it (Bruce Clark, "Decimal Mode",
        # appendix A): Z from the binary sum, N and V from the sum with
        # only the low digit adjusted
        lo = (a & 0x0F) + (m & 0x0F) + c
        if lo >= 0x0A:
            lo = ((lo + 0x06) & 0x0F) + 0x10
        s = (a & 0xF0) + (m & 0xF0) + lo
        signed = _sx(a & 0xF0) + _sx(m & 0xF0) + lo
        self.flag(N, signed & 0x80)
        self.flag(V, not -128 <= signed <= 127)
        self.flag(Z, binary & 0xFF == 0)
        if s >= 0xA0:
            s += 0x60
        self.flag(C, s >= 0x100)
        self.a = s & 0xFF

    def sbc(self, m):
        a, c = self.a, self.p & C
        binary = a - m - (1 - c)
        # every flag comes from the binary difference, in either mode
        self.flag(C, binary >= 0)
        self.flag(V, (a ^ m) & (a ^ binary) & 0x80)
        self.nz(binary)
        if not self.p & D:
            self.a = binary & 0xFF
            return
        lo = (a & 0x0F) - (m & 0x0F) + c - 1
        if lo < 0:
            lo = ((lo - 0x06) & 0x0F) - 0x10
        r = (a & 0xF0) - (m & 0xF0) + lo
        if r < 0:
            r -= 0x60
        self.a = r & 0xFF

    def compare(self, reg, m):
        self.flag(C, reg >= m)
        self.nz(reg - m)

    def shift(self, mn, v):
        if mn == "ASL":
            self.flag(C, v & 0x80)
            v <<= 1
        elif mn == "LSR":
            self.flag(C, v & 1)
            v >>= 1
        elif mn == "ROL":
            v = v << 1 | (self.p & C)
            self.flag(C, v & 0x100)
        else:
            v |= (self.p & C) << 8
            self.flag(C, v & 1)
            v >>= 1
        return self.nz(v)

    # ---- running ----

    def run(self, max_instructions=50_000_000):
        while not (self.done or self.jammed):
            if self.instructions >= max_instructions:
                raise RuntimeError("the 6502 program ran too long")
            self.step()
        return self

    def step(self):
        op = self.fetch()
        d = decode(op)
        if d is None:
            self.jammed = True
            self.pc = (self.pc - 1) & 0xFFFF
            return
        mn, mode = d
        self.instructions += 1
        self.cycles += cycles(mn, mode)
        if mode == "rel":
            self.branch(mn)
        elif mode == "imp":
            self.implied(mn)
        elif mn in ("JMP", "JSR"):
            target = self.address(mode, False)
            if mn == "JSR":
                ret = (self.pc - 1) & 0xFFFF
                self.push(ret >> 8)
                self.push(ret)
            self.pc = target
        elif mn in _STORES:
            v = {"STA": self.a, "STX": self.x, "STY": self.y}[mn]
            self.write(self.address(mode, False), v)
        elif mn in _RMW:
            addr = self.address(mode, False)
            v = self.read(addr)
            if mn == "INC":
                v = self.nz(v + 1)
            elif mn == "DEC":
                v = self.nz(v - 1)
            else:
                v = self.shift(mn, v)
            self.write(addr, v)
        else:
            m = self.fetch() if mode == "imm" else self.read(self.address(mode, True))
            self.operate(mn, m)

    def operate(self, mn, m):
        if mn == "LDA":
            self.a = self.nz(m)
        elif mn == "LDX":
            self.x = self.nz(m)
        elif mn == "LDY":
            self.y = self.nz(m)
        elif mn == "ORA":
            self.a = self.nz(self.a | m)
        elif mn == "AND":
            self.a = self.nz(self.a & m)
        elif mn == "EOR":
            self.a = self.nz(self.a ^ m)
        elif mn == "ADC":
            self.adc(m)
        elif mn == "SBC":
            self.sbc(m)
        elif mn == "CMP":
            self.compare(self.a, m)
        elif mn == "CPX":
            self.compare(self.x, m)
        elif mn == "CPY":
            self.compare(self.y, m)
        elif mn == "BIT":
            self.flag(Z, self.a & m == 0)
            self.flag(N, m & 0x80)
            self.flag(V, m & 0x40)
        else:
            raise ValueError(mn)

    def branch(self, mn):
        d = self.fetch()
        flag = {"BPL": N, "BMI": N, "BVC": V, "BVS": V,
                "BCC": C, "BCS": C, "BNE": Z, "BEQ": Z}[mn]
        want = mn in ("BMI", "BVS", "BCS", "BEQ")
        if bool(self.p & flag) == want:
            target = (self.pc + (d - 256 if d & 0x80 else d)) & 0xFFFF
            self.cycles += 1 + ((target ^ self.pc) & 0xFF00 != 0)
            self.pc = target

    def implied(self, mn):
        if mn in ("ASL", "ROL", "LSR", "ROR"):
            self.a = self.shift(mn, self.a)
        elif mn == "BRK":
            ret = (self.pc + 1) & 0xFFFF        # BRK skips a signature byte
            self.push(ret >> 8)
            self.push(ret)
            self.push(self.p | B | U)
            self.p |= I
            self.pc = self.word(0xFFFE)
        elif mn == "RTI":
            self.p = self.pull() | U
            self.p &= ~B
            self.pc = self.pull() | self.pull() << 8
        elif mn == "RTS":
            self.pc = ((self.pull() | self.pull() << 8) + 1) & 0xFFFF
        elif mn == "PHA":
            self.push(self.a)
        elif mn == "PHP":
            self.push(self.p | B | U)
        elif mn == "PLA":
            self.a = self.nz(self.pull())
        elif mn == "PLP":
            self.p = (self.pull() | U) & ~B
        elif mn in ("INX", "DEX"):
            self.x = self.nz(self.x + (1 if mn == "INX" else -1))
        elif mn in ("INY", "DEY"):
            self.y = self.nz(self.y + (1 if mn == "INY" else -1))
        elif mn in ("TAX", "TAY", "TXA", "TYA", "TSX"):
            src = {"A": self.a, "X": self.x, "Y": self.y, "S": self.s}[mn[1]]
            setattr(self, mn[2].lower(), self.nz(src))
        elif mn == "TXS":
            self.s = self.x
        elif mn in ("CLC", "SEC", "CLI", "SEI", "CLV", "CLD", "SED"):
            self.flag({"C": C, "I": I, "V": V, "D": D}[mn[2]], mn[0] == "S")
        elif mn == "NOP":
            pass
        else:
            raise ValueError(mn)


def _sx(v):
    return v - 256 if v & 0x80 else v


# ---- the self-test ----------------------------------------------------------------

def _decimal_vice(a, m, c, subtract):
    """Decimal ADC and SBC as VICE's 6510 core writes them, a second
    formulation to check the one above: (A, the flags N V Z C)."""
    if not subtract:
        tmp = (a & 0x0F) + (m & 0x0F) + c
        if tmp > 0x09:
            tmp += 6
        if tmp <= 0x0F:
            tmp = (tmp & 0x0F) + (a & 0xF0) + (m & 0xF0)
        else:
            tmp = (tmp & 0x0F) + (a & 0xF0) + (m & 0xF0) + 0x10
        z = (a + m + c) & 0xFF == 0
        n = bool(tmp & 0x80)
        v = bool((a ^ tmp) & 0x80) and not (a ^ m) & 0x80
        if (tmp & 0x1F0) > 0x90:
            tmp += 0x60
        return tmp & 0xFF, (n, v, z, (tmp & 0xFF0) > 0xF0)
    binary = a - m - (1 - c)
    lo = (a & 0x0F) - (m & 0x0F) - (1 - c)
    hi = (a & 0xF0) - (m & 0xF0)
    if lo & 0x10:
        lo -= 6
        hi -= 0x10
    if hi & 0x100:
        hi -= 0x60
    flags = (bool(binary & 0x80), bool((a ^ m) & (a ^ binary) & 0x80),
             binary & 0xFF == 0, binary >= 0)
    return (lo & 0x0F | hi) & 0xFF, flags


def _run(source, **defines):
    from .asm6502 import assemble
    cpu = Cpu(assemble(source, defines).mem)
    return cpu.run(100_000)


def selftest():
    from .asm6502 import OPCODES
    # the decoder against the assembler's table, both ways
    table = {op: (mn, mode) for mn, modes in OPCODES.items() for mode, op in modes.items()}
    for op in range(256):
        assert decode(op) == table.get(op), (hex(op), decode(op), table.get(op))
    assert len(table) == 151
    # decimal mode, every input, against VICE's formulation
    cpu = Cpu(bytearray(0x10000))
    for subtract in (False, True):
        for a in range(256):
            for m in range(256):
                for c in (0, 1):
                    cpu.a, cpu.p = a, D | c
                    (cpu.sbc if subtract else cpu.adc)(m)
                    got = (cpu.a, (bool(cpu.p & N), bool(cpu.p & V), bool(cpu.p & Z),
                                   bool(cpu.p & C)))
                    assert got == _decimal_vice(a, m, c, subtract), (subtract, a, m, c, got)
    # small programs with known results
    head = "        .org $F000\nreset:\n"
    tail = "\n        STA $C001\n        .org $FFFC\n        .word reset, reset\n"
    cpu = _run(head + """
        SED
        CLC
        LDA #$58
        ADC #$46          ; 58 + 46 = 104 in BCD
        STA $10
        LDA #$00
        ADC #$00          ; the carry
        STA $11
        SEC
        LDA #$12
        SBC #$21          ; 12 - 21 = 91, borrow
        STA $12
        CLD""" + tail)
    assert (cpu.mem[0x10], cpu.mem[0x11], cpu.mem[0x12]) == (0x04, 0x01, 0x91)
    assert not cpu.p & C
    cpu = _run(head + """
        LDX #0            ; sum 1..100 in 16 bits
        LDA #0
        STA $10
        STA $11
        LDY #100
@loop:  TYA
        CLC
        ADC $10
        STA $10
        BCC @nc
        INC $11
@nc:    DEY
        BNE @loop
        LDA #'A'
        STA $C000
        JSR sub
        LDA $11""" + """
        STA $C001
sub:    LDA #'B'
        STA $C000
        RTS
        .org $FFFC
        .word reset, reset
""")
    assert cpu.mem[0x10] | cpu.mem[0x11] << 8 == 5050
    assert bytes(cpu.out) == b"AB" and cpu.a == 5050 >> 8
    # the indirect jump's page bug, and (zp),Y crossing a page
    cpu = _run(head + """
        LDA #<t1
        STA $02FF
        LDA #>t1
        STA $0200         ; the bug reads the high byte from $0200
        LDA #>t2
        STA $0300
        JMP ($02FF)
t2:     LDA #2
        STA $C001
t1:     LDA #$F0
        STA $20
        LDA #$02
        STA $21
        LDY #$20
        LDA ($20),Y       ; $02F0 + $20 = $0310: crosses a page
        LDA #1""" + tail)
    assert cpu.a == 1 and cpu.cycles == 7 + 2 + 4 + 2 + 4 + 2 + 4 + 5 + 2 + 3 + 2 + 3 + 2 + 6 + 2 + 4
    # the workload's program, at both sizes, against its results worked
    # out here directly
    from .workload import SIZES, _assemble
    for size, params in SIZES.items():
        a = _assemble(tuple(sorted(params.items())))
        cpu = Cpu(a.mem).run()
        assert cpu.done and not cpu.jammed
        assert bytes(cpu.out) == program_results(params, a), (size, bytes(cpu.out))
    print("cpu6502 self-test passed")


def program_results(p, assembly):
    """What program.a65 prints, computed in Python: the primes counted,
    the CRC of the sorted words, the sum of the quotients, the text's
    words and CRC, the Fibonacci number, the Collatz chains, BRK's sum."""
    import binascii
    import re
    seed = [0x5AA5]

    def rand():                     # Metcalf's xorshift, as the 6502 does it
        x = seed[0]
        x ^= (x << 7) & 0xFFFF
        x ^= x >> 9
        x ^= (x << 8) & 0xFFFF
        seed[0] = x
        return x

    for _ in range(p["REPS"]):
        words = [rand() for _ in range(p["SORTN"])]
        divsum = 0
        for _ in range(p["DIVN"]):
            x = rand()
            r = rand()
            y = ((r >> 11) << 8) | (r & 0xFF) | 1
            divsum = (divsum + x // y) & 0xFFFF
    words.sort(key=lambda w: w - 0x10000 if w & 0x8000 else w)
    sort_crc = binascii.crc_hqx(b"".join(w.to_bytes(2, "little") for w in words), 0xFFFF)
    primes = sum(all(n % d for d in range(3, int(n ** 0.5) + 1, 2))
                 for n in range(3, 2 * p["SIEVE"] + 2, 2))
    start = assembly.symbols["text"]
    text = bytes(assembly.mem[start:start + p["TEXTN"]]).decode()
    text_crc = binascii.crc_hqx(text.upper()[::-1].encode(), 0xFFFF)
    fib = [0, 1]
    while len(fib) < p["FIBN"] + 2:
        fib.append(fib[-1] + fib[-2])

    def collatz(n):
        k = 0
        while n != 1:
            n = 3 * n + 1 if n & 1 else n // 2
            k += 1
        return k

    return (f"primes {primes:05d}\nsort {sort_crc:04X} 00\ndiv {divsum:05d} 00\n"
            f"text {len(re.findall('[A-Za-z]+', text)):05d} FF {text_crc:04X}\n"
            f"fib {fib[-1]:012d} 00\nvm {sum(map(collatz, range(1, p['VMN'] + 1))):05d}\n"
            f"brk {3 * p['REPS']:02X}\n").encode()


if __name__ == "__main__":
    selftest()
