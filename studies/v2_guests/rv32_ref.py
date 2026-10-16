"""A reference interpreter for RV32IM, to check the RV32 microcode against
instruction by instruction (`heron v2_guests run rv32 NAME --lockstep`).

The machine is the one the guest sees on the draft 2 CPU: memory from
address 0, the console at 0xFFFFFF00 (draft 1's I/O page: a word or byte
written to it is output, a read returns the next input byte or -1),
EBREAK halts.
"""

M32 = 0xFFFFFFFF
CONSOLE = 0xFFFFFF00


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class RV32:
    def __init__(self, data, inp=b"", mem_size=0x100000):
        self.mem = bytearray(mem_size)
        self.mem[:len(data)] = data
        self.x = [0] * 32
        self.pc = 0
        self.inp = bytearray(inp)
        self.inpos = 0
        self.out = bytearray()
        self.halted = False
        self.instructions = 0

    # ---- memory
    def load(self, a, n, signed=False):
        a &= M32
        if a >= 0xFFFFFF00:
            if (a & 0xFF) == 0:
                if self.inpos < len(self.inp):
                    self.inpos += 1
                    v = self.inp[self.inpos - 1]
                else:
                    v = M32
                return v & ((1 << (8 * n)) - 1)
            return 0
        if a % n:
            raise RuntimeError(f"misaligned load at {a:08X}, pc {self.pc:08X}")
        v = int.from_bytes(self.mem[a:a + n], "little")
        return sext(v, 8 * n) & M32 if signed else v

    def store(self, a, n, v):
        a &= M32
        if a >= 0xFFFFFF00:
            if (a & 0xFF) == 0:
                self.out.append(v & 0xFF)
            return
        if a % n:
            raise RuntimeError(f"misaligned store at {a:08X}, pc {self.pc:08X}")
        self.mem[a:a + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    # ---- one instruction
    def step(self):
        pc = self.pc
        i = int.from_bytes(self.mem[pc:pc + 4], "little")
        op, rd, f3 = i & 0x7F, (i >> 7) & 31, (i >> 12) & 7
        rs1, rs2, f7 = (i >> 15) & 31, (i >> 20) & 31, i >> 25
        x = self.x
        a, b = x[rs1], x[rs2]
        imm_i = sext(i >> 20, 12)
        nxt = (pc + 4) & M32
        val = None
        if op == 0x37:                                   # LUI
            val = i & 0xFFFFF000
        elif op == 0x17:                                 # AUIPC
            val = (pc + (i & 0xFFFFF000)) & M32
        elif op == 0x6F:                                 # JAL
            imm = sext(((i >> 31) << 20) | (((i >> 12) & 0xFF) << 12)
                       | (((i >> 20) & 1) << 11) | (((i >> 21) & 0x3FF) << 1), 21)
            val, nxt = nxt, (pc + imm) & M32
        elif op == 0x67:                                 # JALR
            val, nxt = nxt, (a + imm_i) & M32 & ~1
        elif op == 0x63:                                 # branches
            imm = sext(((i >> 31) << 12) | (((i >> 7) & 1) << 11)
                       | (((i >> 25) & 0x3F) << 5) | (((i >> 8) & 15) << 1), 13)
            sa, sb = sext(a, 32), sext(b, 32)
            take = {0: a == b, 1: a != b, 4: sa < sb, 5: sa >= sb, 6: a < b, 7: a >= b}[f3]
            if take:
                nxt = (pc + imm) & M32
        elif op == 0x03:                                 # loads
            n, signed = {0: (1, True), 1: (2, True), 2: (4, False), 4: (1, False),
                         5: (2, False)}[f3]
            val = self.load(a + imm_i, n, signed)
        elif op == 0x23:                                 # stores
            imm = sext(((i >> 25) << 5) | rd, 12)
            self.store(a + imm, {0: 1, 1: 2, 2: 4}[f3], b)
        elif op in (0x13, 0x33):                         # ALU
            if op == 0x13:
                b = imm_i & M32
                if f3 == 5:
                    b &= 31
            if op == 0x33 and f7 == 1:
                sa, sb = sext(a, 32), sext(b, 32)
                if f3 == 0:
                    val = a * b
                elif f3 == 1:
                    val = (sa * sb) >> 32
                elif f3 == 2:
                    val = (sa * b) >> 32
                elif f3 == 3:
                    val = (a * b) >> 32
                elif f3 == 4:
                    val = M32 if sb == 0 else (sa if (sa == -2**31 and sb == -1)
                                                else int(sa / sb))
                elif f3 == 5:
                    val = M32 if b == 0 else a // b
                elif f3 == 6:
                    val = sa if sb == 0 else (0 if (sa == -2**31 and sb == -1)
                                              else sa - int(sa / sb) * sb)
                else:
                    val = a if b == 0 else a % b
            else:
                alt = (f7 == 0x20)
                if f3 == 0:
                    val = a - b if (op == 0x33 and alt) else a + b
                elif f3 == 1:
                    val = a << (b & 31)
                elif f3 == 2:
                    val = int(sext(a, 32) < sext(b, 32))
                elif f3 == 3:
                    val = int(a < b)
                elif f3 == 4:
                    val = a ^ b
                elif f3 == 5:
                    val = (sext(a, 32) >> (b & 31)) if (i >> 30) & 1 else a >> (b & 31)
                elif f3 == 6:
                    val = a | b
                else:
                    val = a & b
        elif op == 0x73 and i == 0x00100073:             # EBREAK
            self.halted = True
        elif op == 0x0F:                                 # FENCE
            pass
        else:
            raise RuntimeError(f"illegal instruction {i:08X} at {pc:08X}")
        if val is not None and rd:
            x[rd] = val & M32
        self.pc = nxt
        self.instructions += 1

    def state(self):
        return {"x": list(self.x), "pc": self.pc}

    def run(self, max_instructions=50_000_000):
        while not self.halted:
            self.step()
            if self.instructions > max_instructions:
                raise RuntimeError("instruction limit")
        return self
