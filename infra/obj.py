"""Object files, executables and libraries (archives of object files).

The assembler writes object files (`asm -c`), the linker (heron.infra.link)
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

Reading and writing the files is Rust (infra/toolchain/src/obj.rs, through
heron.native.toolchain); the classes here hold their contents for Python.
"""

from heron import native

MAGIC = b"TMO1"
AR_MAGIC = b"TMA1"

# The constants are the file format's, as in infra/toolchain/src/obj.rs.

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

ObjError = native.toolchain.ObjError


def reloc_value(kind, s, a, p):
    """The bytes to store for a relocation, or raise ValueError with the
    reason it doesn't fit."""
    return native.toolchain.reloc_value(kind, s, a, p)


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

    def contents(self):
        """The object file as heron.native.toolchain passes it."""
        return (self.isa, self.flags, self.entry,
                [(s.name, s.flags, s.addr, s.size, s.align, bytes(s.data), s.code) for s in self.sections],
                [(s.name, s.section, s.value & M32, s.flags) for s in self.symbols],
                [(r.section, r.offset, r.kind, r.symbol, r.addend) for r in self.relocs])

    @classmethod
    def from_contents(cls, contents, name="?"):
        isa, flags, entry, secs, syms, rels = contents
        o = cls(isa, flags, entry, name)
        o.sections = [Section(n, fl, addr, size, align, bytes(data), code)
                      for n, fl, addr, size, align, data, code in secs]
        o.symbols = [Symbol(*s) for s in syms]
        o.relocs = [Reloc(*r) for r in rels]
        return o

    def to_bytes(self):
        return bytes(native.toolchain.write_object(self.contents()))

    @classmethod
    def from_bytes(cls, buf, name="?"):
        return cls.from_contents(native.toolchain.read_object(bytes(buf), name), name)

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
    return bytes(native.toolchain.write_archive([(name, o.to_bytes()) for name, o in members]))


def read_archive(path):
    """[(member name, ObjectFile)]"""
    with open(path, "rb") as f:
        buf = f.read()
    return [(name, ObjectFile.from_contents(c, f"{path}({name})"))
            for name, c in native.toolchain.read_archive(buf, path)]
