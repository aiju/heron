"""A reference interpreter for ARMv6-M Thumb (what clang emits for
-mcpu=cortex-m0), to check the Thumb microcode against
(`heron v2_guests run thumb NAME --lockstep`).

The machine is the one the guest sees on the draft 2 CPU: memory from 0,
the console at 0xFFFFFF00 (draft 1's I/O page, as for RV32), BKPT halts,
SVC stops. Execution starts at 0 in Thumb state (no vector table: the
start-up code sets the stack). BL's 32-bit form is taken for offsets
within 4 MB (J1 = J2 = 1), which is all a small program has.
"""

M32 = 0xFFFFFFFF
CONSOLE = 0xFFFFFF00


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Thumb:
    def __init__(self, data, inp=b"", mem_size=0x100000):
        self.mem = bytearray(mem_size)
        self.mem[:len(data)] = data
        self.r = [0] * 16
        self.pc = 0
        self.n = self.z = self.c = self.v = 0
        self.inp = bytearray(inp)
        self.inpos = 0
        self.out = bytearray()
        self.halted = False
        self.instructions = 0

    # ---- memory (the RV32 reference's console)
    def load(self, a, n):
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
        return int.from_bytes(self.mem[a:a + n], "little")

    def store(self, a, n, v):
        a &= M32
        if a >= 0xFFFFFF00:
            if (a & 0xFF) == 0:
                self.out.append(v & 0xFF)
            return
        if a % n:
            raise RuntimeError(f"misaligned store at {a:08X}, pc {self.pc:08X}")
        self.mem[a:a + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    def half(self, a):
        return self.mem[a] | (self.mem[a + 1] << 8)

    # ---- flags
    def nz(self, v):
        v &= M32
        self.n, self.z = v >> 31, int(v == 0)
        return v

    def addc(self, a, b, c):
        r = a + b + c
        self.c = int(r > M32)
        self.v = int(((a ^ r) & (b ^ r)) >> 31 & 1)
        return self.nz(r)

    def sub(self, a, b):
        return self.addc(a, b ^ M32, 1)

    def cond(self, cc):
        n, z, c, v = self.n, self.z, self.c, self.v
        t = [z, c, n, v, c and not z, n == v, (not z) and n == v, True][cc >> 1]
        return bool(t) ^ bool(cc & 1)

    def rd(self, i):
        """A register as an operand: PC reads as the instruction + 4."""
        return (self.pc + 4) & M32 if i == 15 else self.r[i]

    def shift(self, kind, x, n, setc=True):
        """kind 0 LSL, 1 LSR, 2 ASR, 3 ROR, by n (a register's low byte)."""
        if n == 0:
            return x
        if kind == 0:
            if n > 32:
                c, r = 0, 0
            else:
                c, r = (x >> (32 - n)) & 1, (x << n) & M32
        elif kind == 1:
            if n > 32:
                c, r = 0, 0
            else:
                c, r = (x >> (n - 1)) & 1, x >> n
        elif kind == 2:
            if n >= 32:
                c = x >> 31
                r = M32 if c else 0
            else:
                c, r = (x >> (n - 1)) & 1, (sext(x, 32) >> n) & M32
        else:
            m = n & 31
            r = ((x >> m) | (x << (32 - m))) & M32 if m else x
            c = r >> 31
        if setc:
            self.c = c
        return r

    def step(self):
        pc = self.pc
        i = self.half(pc)
        nxt = pc + 2
        r = self.r
        top5 = i >> 11
        if top5 <= 2:                                          # LSLS/LSRS/ASRS #imm5
            op, imm, m, d = top5, (i >> 6) & 31, (i >> 3) & 7, i & 7
            x = r[m]
            if op == 0:
                res = self.shift(0, x, imm) if imm else x
            else:
                res = self.shift(op, x, imm if imm else 32)
            r[d] = self.nz(res)
        elif top5 == 3:                                        # ADDS/SUBS reg, imm3
            sub, immf, mm, n, d = (i >> 9) & 1, (i >> 10) & 1, (i >> 6) & 7, (i >> 3) & 7, i & 7
            b = mm if immf else r[mm]
            r[d] = self.sub(r[n], b) if sub else self.addc(r[n], b, 0)
        elif i >> 13 == 1:                                     # MOVS/CMP/ADDS/SUBS #imm8
            op, d, imm = (i >> 11) & 3, (i >> 8) & 7, i & 0xFF
            if op == 0:
                r[d] = self.nz(imm)
            elif op == 1:
                self.sub(r[d], imm)
            elif op == 2:
                r[d] = self.addc(r[d], imm, 0)
            else:
                r[d] = self.sub(r[d], imm)
        elif i >> 10 == 0x10:                                  # ALU
            op, m, d = (i >> 6) & 15, (i >> 3) & 7, i & 7
            a, b = r[d], r[m]
            if op == 0:
                r[d] = self.nz(a & b)
            elif op == 1:
                r[d] = self.nz(a ^ b)
            elif op in (2, 3, 4, 7):
                kind = {2: 0, 3: 1, 4: 2, 7: 3}[op]
                r[d] = self.nz(self.shift(kind, a, b & 0xFF))
            elif op == 5:
                r[d] = self.addc(a, b, self.c)
            elif op == 6:
                r[d] = self.addc(a, b ^ M32, self.c)
            elif op == 8:
                self.nz(a & b)
            elif op == 9:
                r[d] = self.sub(0, b)
            elif op == 10:
                self.sub(a, b)
            elif op == 11:
                self.addc(a, b, 0)
            elif op == 12:
                r[d] = self.nz(a | b)
            elif op == 13:
                r[d] = self.nz(a * b)
            elif op == 14:
                r[d] = self.nz(a & ~b)
            else:
                r[d] = self.nz(~b)
        elif i >> 10 == 0x11:                                  # hi registers, BX
            op, m, d = (i >> 8) & 3, (i >> 3) & 15, (i & 7) | ((i >> 4) & 8)
            if op == 0:
                v = (self.rd(d) + self.rd(m)) & M32
                if d == 15:
                    nxt = v & ~1
                else:
                    r[d] = v
            elif op == 1:
                self.sub(self.rd(d), self.rd(m))
            elif op == 2:
                v = self.rd(m)
                if d == 15:
                    nxt = v & ~1
                else:
                    r[d] = v
            else:
                v = self.rd(m)
                if i & 0x80:                                   # BLX
                    r[14] = (pc + 2) | 1
                nxt = v & ~1
        elif top5 == 9:                                        # LDR literal
            t, imm = (i >> 8) & 7, (i & 0xFF) * 4
            r[t] = self.load(((pc + 4) & ~3) + imm, 4)
        elif i >> 12 == 5:                                     # register offset
            op, m, n, t = (i >> 9) & 7, (i >> 6) & 7, (i >> 3) & 7, i & 7
            a = (r[n] + r[m]) & M32
            if op == 0:
                self.store(a, 4, r[t])
            elif op == 1:
                self.store(a, 2, r[t])
            elif op == 2:
                self.store(a, 1, r[t])
            elif op == 3:
                r[t] = sext(self.load(a, 1), 8) & M32
            elif op == 4:
                r[t] = self.load(a, 4)
            elif op == 5:
                r[t] = self.load(a, 2)
            elif op == 6:
                r[t] = self.load(a, 1)
            else:
                r[t] = sext(self.load(a, 2), 16) & M32
        elif i >> 13 == 3 or i >> 12 == 8:                     # imm5 offsets
            if i >> 12 == 8:
                size = 2
            else:
                size = 1 if (i >> 12) & 1 else 4
            load, imm, n, t = (i >> 11) & 1, ((i >> 6) & 31) * size, (i >> 3) & 7, i & 7
            a = (r[n] + imm) & M32
            if load:
                r[t] = self.load(a, size)
            else:
                self.store(a, size, r[t])
        elif i >> 12 == 9:                                     # SP-relative
            load, t, imm = (i >> 11) & 1, (i >> 8) & 7, (i & 0xFF) * 4
            a = (r[13] + imm) & M32
            if load:
                r[t] = self.load(a, 4)
            else:
                self.store(a, 4, r[t])
        elif i >> 12 == 10:                                    # ADR, ADD Rd, SP
            d, imm = (i >> 8) & 7, (i & 0xFF) * 4
            base = r[13] if (i >> 11) & 1 else (pc + 4) & ~3
            r[d] = (base + imm) & M32
        elif i >> 12 == 11:                                    # misc
            if i >> 8 == 0xB0:
                imm = (i & 0x7F) * 4
                r[13] = (r[13] - imm if i & 0x80 else r[13] + imm) & M32
            elif i >> 8 == 0xB2:
                op, m, d = (i >> 6) & 3, (i >> 3) & 7, i & 7
                x = r[m]
                r[d] = [sext(x, 16) & M32, sext(x, 8) & M32, x & 0xFFFF, x & 0xFF][op]
            elif (i >> 9) & 7 == 2 and not (i >> 11) & 1:      # PUSH
                regs = [k for k in range(8) if i >> k & 1] + ([14] if i & 0x100 else [])
                a = (r[13] - 4 * len(regs)) & M32
                r[13] = a
                for k in regs:
                    self.store(a, 4, r[k])
                    a += 4
            elif (i >> 9) & 7 == 6:                            # POP
                regs = [k for k in range(8) if i >> k & 1]
                a = r[13]
                for k in regs:
                    r[k] = self.load(a, 4)
                    a += 4
                if i & 0x100:
                    nxt = self.load(a, 4) & ~1
                    a += 4
                r[13] = a & M32
            elif i >> 8 == 0xBA:
                op, m, d = (i >> 6) & 3, (i >> 3) & 7, i & 7
                x = r[m]
                if op == 0:
                    r[d] = int.from_bytes(x.to_bytes(4, "little"), "big")
                elif op == 1:
                    r[d] = ((x & 0x00FF00FF) << 8 | (x >> 8) & 0x00FF00FF) & M32
                elif op == 3:
                    r[d] = sext(((x & 0xFF) << 8) | ((x >> 8) & 0xFF), 16) & M32
                else:
                    raise RuntimeError(f"undefined {i:04X} at {pc:08X}")
            elif i >> 8 == 0xBE:                               # BKPT
                self.halted = True
                return
            elif i >> 8 == 0xBF or i & 0xFFEF == 0xB662:       # hints, CPS
                pass
            else:
                raise RuntimeError(f"undefined {i:04X} at {pc:08X}")
        elif i >> 12 == 12:                                    # STM, LDM
            load, n, lst = (i >> 11) & 1, (i >> 8) & 7, i & 0xFF
            regs = [k for k in range(8) if lst >> k & 1]
            a = r[n]
            for k in regs:
                if load:
                    r[k] = self.load(a, 4)
                else:
                    self.store(a, 4, r[k])
                a = (a + 4) & M32
            if not (load and lst >> n & 1):
                r[n] = a
        elif i >> 12 == 13:                                    # B<cond>, SVC
            cc = (i >> 8) & 15
            if cc == 15:
                self.halted = True
                self.svc = i & 0xFF
                return
            if cc == 14:
                raise RuntimeError(f"UDF at {pc:08X}")
            if self.cond(cc):
                nxt = pc + 4 + 2 * sext(i, 8)
        elif top5 == 0x1C:                                     # B
            nxt = pc + 4 + 2 * sext(i, 11)
        elif top5 == 0x1E:                                     # BL (32 bits)
            j = self.half(pc + 2)
            if j >> 14 != 3 or not (j >> 12) & 1 or (j >> 11) & 5 != 5:
                raise RuntimeError(f"32-bit {i:04X} {j:04X} at {pc:08X}")
            off = (sext((i & 0x7FF), 11) << 12) | ((j & 0x7FF) << 1)
            r[14] = (pc + 4) | 1
            nxt = pc + 4 + off
        else:
            raise RuntimeError(f"undefined {i:04X} at {pc:08X}")
        self.pc = nxt & M32
        self.instructions += 1

    def state(self):
        return {"r": [self.r[k] for k in range(15)], "pc": self.pc,
                "nzcv": (self.n << 3) | (self.z << 2) | (self.c << 1) | self.v}

    def run(self, max_instructions=50_000_000):
        while not self.halted:
            self.step()
            if self.instructions > max_instructions:
                raise RuntimeError("instruction limit")
        return self
