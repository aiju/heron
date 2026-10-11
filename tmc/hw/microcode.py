"""Microcode for the v0 implementation.

The control unit is 6 flash ROMs (SST39SF010A) addressed by

    A3..A0   step counter (74HCT163)
    A7..A4   IR[3:0]  (fn / offset nibble)
    A11..A8  IR[15:12] (opcode)
    A12      irq_pending (registered, = IRQ & I)
    A13      link (predecode register, loaded at fetch: IR[11:8] == 1111)
    A14      mode_irq   (this "instruction" is the interrupt entry sequence)
    A15      mode_reset (power-on sequence)

Each microinstruction is a dict of logical control signals; `pack` turns
it into the 48 physical ROM output bits (active-low signals inverted).
Every step that ends an instruction either fetches the next instruction
in the same cycle (when the datapath is free) or is followed by a fetch
step. When irq_pending is set at that point the fetch is skipped and the
next sequence is the interrupt entry.

See docs/hardware.md for the datapath these signals drive.
"""

import os

# --------------------------------------------------------------------------
# Control word layout: (name, width, active_low)
# Bit 0 of the word is ROM0 D0. Fields never straddle ROMs, so each ROM
# drives one area of the board.

FIELDS = [
    # ROM0: bus drivers
    ("ARF", 1, True),     # RF copy A drives A bus (SRAM /OE)
    ("APC", 1, True),     # PC drives A bus (/OE of 2x541)
    ("AR", 1, True),      # R drives A bus (/OE of 2x541)
    ("BSRC", 3, False),   # 74HCT138: 0 none 1 RF 2 IMM 3 MEM 4 T 5 R 6 FLAGS
    ("DRES", 1, True),    # result bus drives D bus (/OE of 2x541)
    ("DPC", 1, True),     # PC drives D bus (/OE of 2x541)
    # ROM1: register file, memory, end of instruction
    ("RFA", 2, False),    # RF-A address: 0 d, 1 s, 2 sp, 3 zero
    ("RFB", 2, False),    # RF-B address
    ("RFWE", 1, False),   # write R into both copies (gated by WE window, r0 inhibit)
    ("MEMRD", 1, True),   # memory /OE; a read at PC also increments PC
    ("MEMWR", 1, False),  # memory write (gated by WE window and byte lanes)
    ("END", 1, True),     # step counter synchronous clear, mode update
    # ROM2: ALU
    ("S", 4, False),      # 74181 S3..S0
    ("M", 1, False),      # 74181 M
    ("CSEL", 2, False),   # carry-in / shift-in: 0 (no carry, 0), 1 (carry, F15), 2 (C, C)
    ("HALT", 1, True),    # step counter count-enable low
    # ROM3: result mux and immediates
    ("LO", 2, False),     # low byte: 0 F lo, 1 F hi, 2 F>>1
    ("HI", 2, False),     # high byte: 0 F hi, 1 F lo, 2 F>>1, 3 sign of F lo
    ("HIZERO", 1, False),  # force high byte to 0 (153 strobe)
    ("BYTE", 1, False),   # byte access: low-byte lane chosen by MAR[0], write lane masking
    ("IMM8", 1, False),   # immediate = sign-extended IR[7:0] (else the nibble)
    ("SCALE", 1, False),  # immediate x2
    # ROM4: flags
    ("SETNZ", 1, False),  # N,Z <- result
    ("SETCV", 1, False),  # C <- ALU carry, V <- overflow   (with LDCV: C <- F[0], V <- 0)
    ("LDCV", 1, False),   # C,V <- result bits 1,0          (with SETCV: right shift)
    ("LOADF", 1, False),  # N,Z,I <- result bits 3,2,4
    ("IWR", 1, False),    # I <- IVAL
    ("IVAL", 1, False),
    ("NSEL", 2, False),   # immediate nibble: 0 IR[3:0], 1 const 1, 2 const 2, 3 const 4
    # ROM5: register loads
    ("LDR", 1, True),     # 377 /EN
    ("LDMAR", 1, True),
    ("MARSRC", 1, False),  # 0 result bus, 1 A bus
    ("LDT", 1, True),
    ("LDIR", 1, True),    # also loads the predecode register (link bit)
    ("ADDRMAR", 1, False),  # address bus: 0 PC, 1 MAR
    ("LDPC", 1, False),
    ("PCCOND", 1, False),  # gate LDPC with the branch condition
]

ROMS = 6
ROM_ADDR_BITS = 17      # SST39SF010A: 128K x 8 (A16 tied low)

_pos = {}
_bit = 0
_rom_used = [0] * ROMS
for _name, _w, _al in FIELDS:
    rom = _bit // 8
    if (_bit % 8) + _w > 8:      # don't straddle a ROM
        _bit = (rom + 1) * 8
    _pos[_name] = (_bit, _w, _al)
    _bit += _w
assert _bit <= ROMS * 8, f"control word needs {_bit} bits"
CONTROL_BITS = _bit

BSRC_CODES = {None: 0, "rf": 1, "imm": 2, "mem": 3, "t": 4, "r": 5, "flags": 6}
REG_SEL = {"d": 0, "s": 1, "sp": 2, "zero": 3}
LO_CODES = {"f": 0, "swap": 1, "shr": 2}
HI_CODES = {"f": 0, "swap": 1, "shr": 2, "sext": 3}
NSEL_CODES = {"ir": 0, "1": 1, "2": 2, "4": 3}

# 74181 functions, active-high data, with their carry-in. The V logic
# works out "is this a subtract" from S0 (add is S=1001, subtract S=0110).
ALU = {
    "add":   dict(S=0b1001, M=0, CSEL=0),
    "adc":   dict(S=0b1001, M=0, CSEL=2),
    "sub":   dict(S=0b0110, M=0, CSEL=1),
    "sbc":   dict(S=0b0110, M=0, CSEL=2),
    "and":   dict(S=0b1011, M=1),
    "or":    dict(S=0b1110, M=1),
    "xor":   dict(S=0b0110, M=1),
    "bic":   dict(S=0b0111, M=1),
    "passa": dict(S=0b1111, M=1),
    "passb": dict(S=0b1010, M=1),
    "notb":  dict(S=0b0101, M=1),
    "zero":  dict(S=0b0011, M=1),
}


def u(**kw):
    """A microinstruction: logical signal values."""
    return dict(kw)


def merge(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            if k in out and out[k] != v:
                raise ValueError(f"microcode conflict on {k}: {out[k]} vs {v}")
            out[k] = v
    return out


def pack(mi):
    """Logical microinstruction dict -> integer control word (physical levels)."""
    vals = {name: 0 for name, _, _ in FIELDS}
    alu = mi.get("alu")
    if alu:
        for k, v in ALU[alu].items():
            vals[k] = v
    for k, v in mi.items():
        if k == "alu":
            continue
        if k == "asrc":
            if v:
                vals[{"rf": "ARF", "pc": "APC", "r": "AR"}[v]] = 1
        elif k == "bsrc":
            vals["BSRC"] = BSRC_CODES[v]
        elif k == "dsrc":
            if v:
                vals[{"res": "DRES", "pc": "DPC"}[v]] = 1
        elif k in ("rfa", "rfb"):
            vals[k.upper()] = REG_SEL[v]
        elif k == "lo":
            vals["LO"] = LO_CODES[v]
        elif k == "hi":
            vals["HI"] = HI_CODES[v]
        elif k == "csel":
            vals["CSEL"] = {"0": 0, "f15": 1, "c": 2}[v]
        elif k == "nsel":
            vals["NSEL"] = NSEL_CODES[v]
        else:
            if k.upper() not in vals:
                raise KeyError(f"unknown control signal {k}")
            vals[k.upper()] = int(v)
    word = 0
    for name, (bit, w, al) in _pos.items():
        v = vals[name]
        assert 0 <= v < (1 << w), (name, v)
        if al:
            v ^= (1 << w) - 1
        word |= v << bit
    return word


def unpack(word):
    """Integer control word -> dict of logical field values (for listings/sims)."""
    out = {}
    for name, (bit, w, al) in _pos.items():
        v = (word >> bit) & ((1 << w) - 1)
        if al:
            v ^= (1 << w) - 1
        out[name] = v
    return out


# --------------------------------------------------------------------------
# Microinstruction building blocks

FETCH = u(ADDRMAR=0, MEMRD=1, LDIR=1)       # PC increments on any read at PC
END = u(END=1)

IMM_SEXT8 = u(bsrc="imm", nsel="ir", IMM8=1)
IMM_BRANCH = u(bsrc="imm", nsel="ir", IMM8=1, SCALE=1)
IMM_O2 = u(bsrc="imm", nsel="ir", SCALE=1)
IMM_O1 = u(bsrc="imm", nsel="ir")
IMM_1 = u(bsrc="imm", nsel="1")
IMM_2 = u(bsrc="imm", nsel="1", SCALE=1)
IMM_4 = u(bsrc="imm", nsel="2", SCALE=1)
IMM_8 = u(bsrc="imm", nsel="4", SCALE=1)

A_RD = u(asrc="rf", rfa="d")
A_RS = u(asrc="rf", rfa="s")
A_SP = u(asrc="rf", rfa="sp")
B_RS = u(bsrc="rf", rfb="s")
B_RD = u(bsrc="rf", rfb="d")


def WB(reg):
    """Write R into both register file copies."""
    return u(asrc="r", bsrc="r", rfa=reg, rfb=reg, RFWE=1)


EXT_READ = u(ADDRMAR=0, MEMRD=1)       # read the extension word at PC (PC += 2)
MAR_READ = u(ADDRMAR=1, MEMRD=1)
MAR_WRITE = u(ADDRMAR=1, MEMWR=1)
SP_MINUS_2 = merge(A_SP, IMM_2, u(alu="sub", LDR=1, LDMAR=1))
FLAGS_ALL = u(SETNZ=1, SETCV=1)
FLAGS_NZ = u(SETNZ=1)


class Seq:
    """A microcode sequence: list of steps plus how the instruction ends.

    merge_fetch: the fetch of the next instruction can share the last step
    (the last step doesn't use memory, IR or PC).
    """

    def __init__(self, steps, merge_fetch=True):
        self.steps = steps
        self.merge_fetch = merge_fetch

    def expand(self, irq):
        """Concrete step list for a given irq_pending value."""
        steps = [dict(s) for s in self.steps]
        if self.merge_fetch:
            steps[-1] = merge(steps[-1], END if irq else merge(FETCH, END))
        else:
            if irq:
                steps[-1] = merge(steps[-1], END)
            else:
                steps.append(merge(FETCH, END))
        return steps


def trap_seq(vector_imm):
    """Push PC, push flags, I <- 0, PC <- vector."""
    return Seq([
        SP_MINUS_2,
        merge(u(dsrc="pc"), MAR_WRITE, WB("sp")),
        SP_MINUS_2,
        merge(u(bsrc="flags", alu="passb", dsrc="res"), MAR_WRITE),
        WB("sp"),
        merge(vector_imm, u(alu="passb", LDPC=1, IWR=1, IVAL=0)),
    ], merge_fetch=False)


TRAP = trap_seq(IMM_8)
IRQ_ENTRY = trap_seq(IMM_4)

ALU_FN = ["add", "adc", "sub", "sbc", "and", "or", "xor", "bic"]
ALU_FLAGS = [FLAGS_ALL] * 4 + [FLAGS_NZ] * 4


def alu_seq(fn, imm16):
    """op 1 (rd, rs) and op 8 (rd, #imm16)."""
    src = merge(EXT_READ, u(bsrc="mem")) if imm16 else B_RS
    if fn < 8:
        return Seq([merge(A_RD, src, u(alu=ALU_FN[fn], LDR=1), ALU_FLAGS[fn]), WB("d")])
    if fn == 8:   # MOV
        return Seq([merge(src, u(alu="passb", LDR=1), FLAGS_NZ), WB("d")])
    if fn == 9:   # CMP
        return Seq([merge(A_RD, src, u(alu="sub"), FLAGS_ALL)], merge_fetch=not imm16)
    if fn == 10:  # TST
        return Seq([merge(A_RD, src, u(alu="and"), FLAGS_NZ)], merge_fetch=not imm16)
    return TRAP


def unary_seq(fn):
    load = u(LDR=1)
    if fn == 0:   # NOT
        s = merge(B_RS, u(alu="notb"), FLAGS_NZ)
    elif fn == 1:  # NEG: 0 - rs
        s = merge(u(asrc="rf", rfa="zero"), B_RS, u(alu="sub"), FLAGS_ALL)
    elif fn == 2:  # INC
        s = merge(A_RS, IMM_1, u(alu="add"), FLAGS_ALL)
    elif fn == 3:  # DEC
        s = merge(A_RS, IMM_1, u(alu="sub"), FLAGS_ALL)
    elif fn == 4:  # SHL = rs + rs
        s = merge(A_RS, B_RS, u(alu="add"), FLAGS_ALL)
    elif fn == 7:  # RLC = rs + rs + C
        s = merge(A_RS, B_RS, u(alu="adc"), FLAGS_ALL)
    elif fn in (5, 6, 8):  # SHR, ASR, RRC
        csel = {5: "0", 6: "f15", 8: "c"}[fn]
        s = merge(A_RS, u(alu="passa", lo="shr", hi="shr", csel=csel, LDCV=1), FLAGS_ALL)
    elif fn == 9:  # SWAB
        s = merge(A_RS, u(alu="passa", lo="swap", hi="swap"), FLAGS_NZ)
    elif fn == 10:  # SXT
        s = merge(A_RS, u(alu="passa", hi="sext"), FLAGS_NZ)
    elif fn == 11:  # ZXT
        s = merge(A_RS, u(alu="passa", HIZERO=1), FLAGS_NZ)
    else:
        return TRAP
    return Seq([merge(s, load), WB("d")])


def mem_seq(kind, addr_step):
    """Second half of loads/stores, after addr_step has loaded MAR."""
    if kind == "ld":
        return Seq([addr_step, merge(MAR_READ, u(bsrc="mem", alu="passb", LDR=1), FLAGS_NZ), WB("d")])
    if kind == "ldb":
        return Seq([addr_step, merge(MAR_READ, u(bsrc="mem", alu="passb", LDR=1, BYTE=1, HIZERO=1),
                                     FLAGS_NZ), WB("d")])
    if kind == "st":
        return Seq([addr_step, merge(B_RD, u(alu="passb", dsrc="res"), MAR_WRITE)], merge_fetch=False)
    if kind == "stb":
        return Seq([addr_step, merge(B_RD, u(alu="passb", lo="f", hi="swap", BYTE=1, dsrc="res"),
                                     MAR_WRITE)], merge_fetch=False)
    raise ValueError(kind)


def sys_seq(fn):
    if fn == 0:   # HALT: handled specially in build()
        return None
    if fn == 1:   # NOP
        return Seq([u()])
    if fn == 2:   # JMP rs
        return Seq([merge(B_RS, u(alu="passb", LDPC=1))], merge_fetch=False)
    if fn == 3:   # CALL rs
        return Seq([
            SP_MINUS_2,
            merge(u(dsrc="pc"), MAR_WRITE, B_RS, u(alu="passb", LDPC=1)),
            WB("sp"),
        ])
    if fn == 4:   # RET
        return Seq([
            merge(A_SP, u(LDMAR=1, MARSRC=1), IMM_2, u(alu="add", LDR=1)),
            merge(MAR_READ, u(bsrc="mem", alu="passb", LDPC=1)),
            WB("sp"),
        ])
    if fn == 5:   # PUSH rs
        return Seq([
            SP_MINUS_2,
            merge(B_RS, u(alu="passb", dsrc="res"), MAR_WRITE),
            WB("sp"),
        ])
    if fn == 6:   # POP rd
        return Seq([
            merge(A_SP, u(LDMAR=1, MARSRC=1), IMM_2, u(alu="add", LDR=1)),
            merge(WB("sp"), MAR_READ, u(LDT=1)),
            merge(u(bsrc="t", alu="passb", LDR=1), FLAGS_NZ),
            WB("d"),
        ])
    if fn == 7:   # RTI
        return Seq([
            merge(A_SP, u(LDMAR=1, MARSRC=1), IMM_2, u(alu="add", LDR=1)),
            merge(WB("sp"), MAR_READ, u(LDT=1)),
            merge(u(bsrc="t", alu="passb", LOADF=1, LDCV=1), A_SP, u(LDMAR=1, MARSRC=1)),
            merge(A_SP, IMM_2, u(alu="add", LDR=1)),
            merge(WB("sp"), MAR_READ, u(LDT=1)),
            merge(u(bsrc="t", alu="passb", LDPC=1)),
        ], merge_fetch=False)
    if fn == 8:   # EI
        return Seq([u(IWR=1, IVAL=1)])
    if fn == 9:   # DI
        return Seq([u(IWR=1, IVAL=0)])
    if fn == 10:  # MFF rd
        return Seq([u(bsrc="flags", alu="passb", LDR=1), WB("d")])
    if fn == 11:  # MTF rs
        return Seq([merge(B_RS, u(alu="passb", LOADF=1, LDCV=1))])
    return TRAP   # SWI (12) and reserved (13-15)


def instruction_seq(op, fn, link):
    """Microcode sequence for opcode op, IR[3:0] = fn, link predecode bit."""
    if op == 0x0:
        return sys_seq(fn)
    if op == 0x1:
        return alu_seq(fn, imm16=False)
    if op == 0x8:
        return alu_seq(fn, imm16=True)
    if op == 0x2:
        return unary_seq(fn)
    if op == 0x3:   # Bcc / BSR
        if link:
            return Seq([
                SP_MINUS_2,
                merge(u(dsrc="pc"), MAR_WRITE, u(asrc="pc"), IMM_BRANCH, u(alu="add", LDPC=1)),
                WB("sp"),
            ])
        return Seq([merge(u(asrc="pc"), IMM_BRANCH, u(alu="add", LDPC=1, PCCOND=1))],
                   merge_fetch=False)
    if op == 0x9:   # Jcc / CALL
        if link:
            return Seq([
                merge(SP_MINUS_2, EXT_READ, u(LDT=1)),
                merge(u(dsrc="pc"), MAR_WRITE, u(bsrc="t", alu="passb", LDPC=1)),
                WB("sp"),
            ])
        return Seq([merge(EXT_READ, u(bsrc="mem", alu="passb", LDPC=1, PCCOND=1))],
                   merge_fetch=False)
    if op in (0x4, 0x5, 0x6, 0x7):
        kind = ["ld", "st", "ldb", "stb"][op - 4]
        imm = IMM_O2 if op in (4, 5) else IMM_O1
        return mem_seq(kind, merge(A_RS, imm, u(alu="add", LDMAR=1)))
    if op == 0xA:
        addr = merge(EXT_READ, u(bsrc="mem"), A_RS, u(alu="add", LDMAR=1))
        if fn <= 3:
            return mem_seq(["ld", "st", "ldb", "stb"][fn], addr)
        if fn == 4:   # LEA
            return Seq([merge(EXT_READ, u(bsrc="mem"), A_RS, u(alu="add", LDR=1)), WB("d")])
        return TRAP
    if op == 0xC:   # MVI
        return Seq([merge(IMM_SEXT8, u(alu="passb", LDR=1), FLAGS_NZ), WB("d")])
    if op == 0xD:   # ADDI
        return Seq([merge(A_RD, IMM_SEXT8, u(alu="add", LDR=1), FLAGS_ALL), WB("d")])
    if op == 0xE:   # CMPI
        return Seq([merge(A_RD, IMM_SEXT8, u(alu="sub"), FLAGS_ALL)])
    return TRAP     # B, F


RESET = Seq([
    u(alu="zero", LDR=1),
    WB("zero"),         # r0 write inhibit is overridden in reset mode
], merge_fetch=True)

# Filler for unused ROM locations: do nothing and end (recovers to fetch-less END).
IDLE = pack(END)


def address(step, fn, op, irq, link, mode_irq, mode_reset):
    return (step | (fn << 4) | (op << 8) | (irq << 12) | (link << 13)
            | (mode_irq << 14) | (mode_reset << 15))


def build():
    """Return {address: control word} for every used ROM address,
    and {address: description} for listings."""
    rom = {}
    notes = {}

    def put(seq_steps, fn_vals, op_vals, irq, link_vals, mode_irq, mode_reset, label):
        if len(seq_steps) > 16:
            raise ValueError(f"{label}: {len(seq_steps)} steps")
        for step, mi in enumerate(seq_steps):
            w = pack(mi)
            for fn in fn_vals:
                for op in op_vals:
                    for link in link_vals:
                        a = address(step, fn, op, irq, link, mode_irq, mode_reset)
                        rom[a] = w
                        notes[a] = f"{label} s{step}"

    all16 = range(16)
    for irq in (0, 1):
        # reset (everything else ignored)
        for mi_irq in (0, 1):
            for op in all16:
                put(RESET.expand(irq=0), all16, [op], irq, (0, 1), mi_irq, 1, "reset")
        # interrupt entry (IR ignored)
        put(IRQ_ENTRY.expand(irq=0), all16, all16, irq, (0, 1), 1, 0, "irq-entry")
        # normal instructions
        for op in all16:
            for fn in all16:
                for link in (0, 1):
                    if op == 0 and fn == 0:
                        # HALT: hold until an interrupt is pending, then end
                        steps = [END] if irq else [u(HALT=1)]
                        put(steps, [fn], [op], irq, [link], 0, 0, "HALT")
                        continue
                    seq = instruction_seq(op, fn, link)
                    put(seq.expand(irq), [fn], [op], irq, [link], 0, 0, f"op{op:X} fn{fn:X} l{link}")
    return rom, notes


def rom_images(rom=None):
    if rom is None:
        rom, _ = build()
    size = 1 << ROM_ADDR_BITS
    imgs = [bytearray(size) for _ in range(ROMS)]
    for a in range(size):
        w = rom.get(a, IDLE)
        for k in range(ROMS):
            imgs[k][a] = (w >> (8 * k)) & 0xFF
    return imgs


_built = None


def built():
    global _built
    if _built is None:
        _built = build()
    return _built


def sequence_length(op, fn, link, irq=0):
    rom, _ = built()
    for step in range(16):
        w = rom[address(step, fn, op, irq, link, 0, 0)]
        if unpack(w)["END"]:
            return step + 1
    raise ValueError("no END")


def timing_function(isa_name="v0"):
    """cycles(word, taken) for the instruction-level simulator."""
    if isa_name != "v0":
        return None
    rom, _ = built()

    def cycles(w, taken):
        if w == "irq":
            for step in range(16):
                if unpack(rom[address(step, 0, 0, 0, 0, 1, 0)])["END"]:
                    return step + 1
        op, fn = w >> 12, w & 15
        link = int(((w >> 8) & 15) == 15)
        if op == 0 and fn == 0:
            return 1
        return sequence_length(op, fn, link)
    return cycles


def cycle_table():
    """Rows of (instruction, cycles) for documentation."""
    from ..isa import v0
    rows = []
    seen = set()
    for w in range(0x10000):
        k = v0.kind(w)
        op, fn = w >> 12, w & 15
        link = int(((w >> 8) & 15) == 15)
        key = (k, link if op in (3, 9) else 0)
        if key in seen or k == "illegal":
            continue
        seen.add(key)
        rows.append((k, 1 if (op, fn) == (0, 0) else sequence_length(op, fn, link)))
    return rows


def listing():
    rom, notes = built()
    lines = []
    for a in sorted(rom):
        if (a >> 12) & 1:          # skip irq=1 copies to keep it readable
            continue
        f = unpack(rom[a])
        active = []
        for name, (_, w, al) in _pos.items():
            v = f[name]
            if v:
                active.append(name if w == 1 else f"{name}={v}")
        lines.append(f"{a:05X} {rom[a]:014X} {notes[a]:<20} {' '.join(active)}")
    return "\n".join(lines) + "\n"


def cmd_ucode(args):
    out = args.o
    os.makedirs(out, exist_ok=True)
    rom, notes = build()
    for k, img in enumerate(rom_images(rom)):
        with open(os.path.join(out, f"ucode{k}.bin"), "wb") as f:
            f.write(img)
    with open(os.path.join(out, "ucode.lst"), "w") as f:
        f.write(listing())
    print(f"{CONTROL_BITS} control bits in {ROMS} ROMs, {len(rom)} used addresses -> {out}/")
    return 0


def describe():
    """Markdown listing of every instruction's microcode steps (normal path, no interrupt)."""
    from ..isa import v0
    rom, _ = built()
    seen = {}
    for op in range(16):
        for fn in range(16):
            for link in (0, 1):
                if op not in (3, 9) and link:
                    continue
                w = (op << 12) | (fn & 15) | (0xF00 if link else 0)
                name = v0.kind(w)
                if op in (3, 9) and not link:
                    name = {3: "Bcc / BRA", 9: "Jcc / JMP addr"}[op]
                if name in seen or name == "illegal" and "trap" in seen:
                    continue
                key = name if name != "illegal" else "trap"
                steps = []
                for step in range(16):
                    f = unpack(rom[address(step, fn, op, 0, link, 0, 0)])
                    steps.append(f)
                    if f["END"] or not f["HALT"] == 0 and step == 0 and (op, fn) == (0, 0):
                        break
                seen[key] = steps
    seen["interrupt entry"] = []
    for step in range(16):
        f = unpack(rom[address(step, 0, 0, 0, 0, 1, 0)])
        seen["interrupt entry"].append(f)
        if f["END"]:
            break

    def sig(f):
        out = []
        for name, (_, w, _) in _pos.items():
            v = f[name]
            if name in ("RFA", "RFB"):
                if (name == "RFA" and f["ARF"]) or (name == "RFB" and f["BSRC"] == 1) or f["RFWE"]:
                    out.append(f"{name}={['d', 's', 'sp', 'zero'][v]}")
                continue
            if not v or name == "M":
                continue
            if name == "BSRC":
                out.append("B←" + {1: "RF", 2: "IMM", 3: "MEM", 4: "T", 5: "R", 6: "FLAGS"}[v])
            elif name == "S":
                pass
            elif w == 1:
                out.append(name)
            else:
                out.append(f"{name}={v}")
        if f["ARF"] or f["APC"] or f["AR"] or f["BSRC"]:
            alu = next((k for k, d in ALU.items() if d["S"] == f["S"] and d["M"] == f["M"]
                        and (d.get("CSEL", 0) == f["CSEL"] or d["M"] == 1)), None)
            if alu:
                out.append(f"ALU={alu}")
        return " ".join(out)

    lines = ["# Microcode listing", "",
             "Generated by `python3 -c 'from tmc.hw import microcode; print(microcode.describe())'`.",
             "One line per clock cycle, normal path (no interrupt pending). The last step of",
             "each instruction usually also fetches the next one (`MEMRD LDIR`, address = PC).",
             "Field meanings are in [hardware.md](hardware.md) and `tmc/hw/microcode.py`.", ""]
    for name, steps in seen.items():
        lines.append(f"**{name}** ({len(steps)} cycle{'s' if len(steps) != 1 else ''})")
        lines.append("")
        lines.append("```")
        for i, f in enumerate(steps):
            lines.append(f"{i}: {sig(f)}")
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
