"""Object files, executables and libraries (archives of object files).

The assembler writes object files (`tmc asm -c`), the linker (tmc.link)
combines them into an executable. All three formats are little-endian.

Object file / executable:

    "TMO1"
    u32 flags          1 = executable (every section placed, no relocations)
    u32 isa            string: "v1a", "v1b"
    u32 entry          start address (executables; 0 = the reset vector)
    u32 nsections, nsymbols, nrelocs, strtab size
    sections   nsections x {u32 name, u32 flags, u32 addr, u32 size, u32 align, u32 code}
    symbols    nsymbols  x {u32 name, u32 section, u32 value, u32 flags}
    relocs     nrelocs   x {u32 section, u32 offset, u32 kind, u32 symbol, s32 addend}
    strtab     NUL-terminated names; offset 0 is the empty string
    data       the contents of every section without NOBITS, in section order

A section is either absolute (placed at `addr`) or relocatable (the linker
picks the address; `addr` is 0). `code` counts the bytes of instructions in
it, for statistics. A symbol's `section` is 1-based, 0 for undefined (an
external reference) and ABS for an absolute value; `value` is the offset in
the section. Relocation `symbol` is an index into the symbol table.

Archive:

    "TMA1", u32 count, count x {u32 name length, name, u32 size, object file}
"""

import struct

MAGIC = b"TMO1"
AR_MAGIC = b"TMA1"

# file flags
EXEC = 1

# section flags
SEC_ABS = 1         # fixed address
SEC_NOBITS = 2      # zero-filled, no contents in the file (.bss)

# symbol section numbers
UNDEF = 0
ABS = 0xFFFFFFFF

# symbol flags
SYM_GLOBAL = 1
SYM_FAR = 2         # may lie anywhere: references use 32-bit forms
SYM_SECTION = 4     # stands for the start of its section

# Relocation kinds. S = the symbol's address, A = the addend, P = the
# address of the field being patched.
ABS32 = 1           # 32 bits (two parcels, or a data word): S + A
ABS16 = 2           # 16 bits of data: S + A in -32768..65535
ABS16S = 3          # 16 bits the CPU sign-extends: S + A in -32768..32767
PC16 = 4            # 16 bits, PC-relative: S + A - P in -32768..32767
PC16H = 5           # 16 bits, PC-relative in parcels: (S + A - P) / 2, even, ±64 KB

RELOC_NAMES = {ABS32: "abs32", ABS16: "abs16", ABS16S: "abs16s", PC16: "pc16", PC16H: "pc16h"}
RELOC_SIZE = {ABS32: 4, ABS16: 2, ABS16S: 2, PC16: 2, PC16H: 2}

M32 = 0xFFFFFFFF


class ObjError(Exception):
    pass


def s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def reloc_value(kind, s, a, p):
    """The bytes to store for a relocation, or raise ValueError with the
    reason it doesn't fit."""
    v = s + a
    if kind == ABS32:
        return (v & M32).to_bytes(4, "little")
    if kind == ABS16:
        if not (-32768 <= s32(v) <= 32767 or 0 <= (v & M32) <= 0xFFFF):
            raise ValueError(f"{v & M32:#x} doesn't fit in 16 bits")
        return (v & 0xFFFF).to_bytes(2, "little")
    if kind == ABS16S:
        if not -32768 <= s32(v) <= 32767:
            raise ValueError(f"{v & M32:#x} is out of reach of 16-bit addresses (0-0x7FFF)")
        return (v & 0xFFFF).to_bytes(2, "little")
    off = s32(v - p)
    if kind == PC16:
        if not -32768 <= off <= 32767:
            raise ValueError(f"{v & M32:#x} is {off:+d} bytes away, more than ±32 KB")
        return (off & 0xFFFF).to_bytes(2, "little")
    if kind == PC16H:
        if off & 1:
            raise ValueError(f"{v & M32:#x} is at an odd address")
        if not -65536 <= off <= 65534:
            raise ValueError(f"{v & M32:#x} is {off:+d} bytes away, more than ±64 KB")
        return ((off >> 1) & 0xFFFF).to_bytes(2, "little")
    raise ValueError(f"unknown relocation kind {kind}")


class Section:
    def __init__(self, name, flags=0, addr=0, size=0, align=1, data=b"", code=0):
        self.name = name
        self.flags = flags
        self.addr = addr
        self.size = size
        self.align = align
        self.data = data            # bytes (empty for NOBITS)
        self.code = code

    @property
    def absolute(self):
        return bool(self.flags & SEC_ABS)

    @property
    def nobits(self):
        return bool(self.flags & SEC_NOBITS)

    def __repr__(self):
        return f"Section({self.name}, {self.size} bytes)"


class Symbol:
    def __init__(self, name, section=UNDEF, value=0, flags=0):
        self.name = name
        self.section = section      # 1-based index, UNDEF or ABS
        self.value = value
        self.flags = flags

    @property
    def is_global(self):
        return bool(self.flags & SYM_GLOBAL)

    @property
    def defined(self):
        return self.section != UNDEF

    def __repr__(self):
        return f"Symbol({self.name}, {self.section}, {self.value:#x})"


class Reloc:
    def __init__(self, section, offset, kind, symbol, addend=0):
        self.section = section      # 1-based section index
        self.offset = offset
        self.kind = kind
        self.symbol = symbol        # index into the symbol table
        self.addend = addend

    def __repr__(self):
        return f"Reloc({self.section}, {self.offset:#x}, {RELOC_NAMES[self.kind]}, {self.symbol}, {self.addend})"


class ObjectFile:
    def __init__(self, isa, flags=0, entry=0, name="?"):
        self.isa = isa
        self.flags = flags
        self.entry = entry
        self.sections = []
        self.symbols = []
        self.relocs = []
        self.name = name            # for messages: the file it came from

    @property
    def executable(self):
        return bool(self.flags & EXEC)

    def section_of(self, sym):
        if sym.section in (UNDEF, ABS):
            return None
        return self.sections[sym.section - 1]

    def to_bytes(self):
        strtab = bytearray(b"\0")
        offsets = {"": 0}

        def s(name):
            if name not in offsets:
                offsets[name] = len(strtab)
                strtab.extend(name.encode("utf-8") + b"\0")
            return offsets[name]
        isa = s(self.isa)
        secs = b"".join(struct.pack("<6I", s(x.name), x.flags, x.addr, x.size, x.align, x.code)
                        for x in self.sections)
        syms = b"".join(struct.pack("<4I", s(x.name), x.section, x.value & M32, x.flags)
                        for x in self.symbols)
        rels = b"".join(struct.pack("<4Ii", r.section, r.offset, r.kind, r.symbol, r.addend)
                        for r in self.relocs)
        head = MAGIC + struct.pack("<7I", self.flags, isa, self.entry, len(self.sections),
                                   len(self.symbols), len(self.relocs), len(strtab))
        data = b"".join(x.data for x in self.sections if not x.nobits)
        return head + secs + syms + rels + bytes(strtab) + data

    @classmethod
    def from_bytes(cls, buf, name="?"):
        if buf[:4] != MAGIC:
            raise ObjError(f"{name}: not an object file")
        try:
            flags, isa, entry, ns, nsym, nrel, nstr = struct.unpack_from("<7I", buf, 4)
            pos = 32
            raw_secs = [struct.unpack_from("<6I", buf, pos + 24 * k) for k in range(ns)]
            pos += 24 * ns
            raw_syms = [struct.unpack_from("<4I", buf, pos + 16 * k) for k in range(nsym)]
            pos += 16 * nsym
            raw_rels = [struct.unpack_from("<4Ii", buf, pos + 20 * k) for k in range(nrel)]
            pos += 20 * nrel
            strtab = bytes(buf[pos:pos + nstr])
            pos += nstr
        except struct.error:
            raise ObjError(f"{name}: truncated object file")

        def s(off):
            return strtab[off:strtab.index(b"\0", off)].decode("utf-8")
        o = cls(s(isa), flags, entry, name)
        for nm, fl, addr, size, align, code in raw_secs:
            sec = Section(s(nm), fl, addr, size, align, b"", code)
            if not sec.nobits:
                sec.data = bytes(buf[pos:pos + size])
                if len(sec.data) != size:
                    raise ObjError(f"{name}: truncated object file")
                pos += size
            o.sections.append(sec)
        o.symbols = [Symbol(s(nm), sec, val, fl) for nm, sec, val, fl in raw_syms]
        o.relocs = [Reloc(*r) for r in raw_rels]
        for r in o.relocs:
            if not 1 <= r.section <= ns or not 0 <= r.symbol < nsym or r.kind not in RELOC_NAMES:
                raise ObjError(f"{name}: bad relocation")
        return o

    def write(self, path):
        with open(path, "wb") as f:
            f.write(self.to_bytes())


def is_object(path):
    with open(path, "rb") as f:
        return f.read(4) == MAGIC


def is_archive(path):
    with open(path, "rb") as f:
        return f.read(4) == AR_MAGIC


def read_object(path):
    with open(path, "rb") as f:
        return ObjectFile.from_bytes(f.read(), path)


def archive_bytes(members):
    """members: [(name, ObjectFile)]"""
    out = bytearray(AR_MAGIC + struct.pack("<I", len(members)))
    for name, o in members:
        nm = name.encode("utf-8")
        data = o.to_bytes()
        out += struct.pack("<I", len(nm)) + nm + struct.pack("<I", len(data)) + data
    return bytes(out)


def read_archive(path):
    """[(member name, ObjectFile)]"""
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:4] != AR_MAGIC:
        raise ObjError(f"{path}: not a library")
    (n,) = struct.unpack_from("<I", buf, 4)
    pos = 8
    out = []
    for _ in range(n):
        (ln,) = struct.unpack_from("<I", buf, pos)
        name = buf[pos + 4:pos + 4 + ln].decode("utf-8")
        pos += 4 + ln
        (size,) = struct.unpack_from("<I", buf, pos)
        pos += 4
        out.append((name, ObjectFile.from_bytes(buf[pos:pos + size], f"{path}({name})")))
        pos += size
    return out
