"""The linker: object files and libraries in, an executable out.

    heron v1_isa ld start.o prog.o libc.a -o prog.out

Symbols: every global symbol must be defined once. A library (archive) is
searched for symbols that are still undefined, and a member is loaded when
it defines one; a library's definition gives way to one in the program's
own objects, so a program can replace a library function.

Sections that nothing refers to are left out (unless --no-gc): the roots
are the absolute sections (the vectors), the entry symbol if one is given,
and, when there are neither, every section of the program's own objects.

Layout: absolute sections where they say; then, from the end of the last
absolute section (or --base), the others in this order:

    .data .rodata .bss      near data: 16-bit addresses reach it below 0x8000
    .text                   code
    (anything else)
    .fardata .farbss        far data, reached with 32-bit addresses

`__end` is defined as the first free address after everything (where the
C library's heap starts). Zero-filled sections are written out as zeros,
so a loader doesn't need to clear them.

The linker itself is Rust (infra/toolchain/src/link.rs, through
heron.native.toolchain); this module gives it the interface the tools use.
"""

from heron import native
from . import obj as O
from .asm import Image


class LinkError(Exception):
    def __init__(self, msgs):
        msgs = [msgs] if isinstance(msgs, str) else msgs
        super().__init__("\n".join(msgs[:20]) + (f"\n... and {len(msgs) - 20} more" if len(msgs) > 20 else ""))
        self.msgs = msgs


class Label:
    """A symbol, shaped like an assembler statement for the tools that list
    labels (profiles, statistics)."""
    kind = "label"

    def __init__(self, label, addr):
        self.label = label
        self.addr = addr


class LinkedImage(Image):
    def __init__(self, mem, symbols, labels, code_bytes, obj=None):
        super().__init__(mem, symbols, labels)
        self._code = code_bytes
        self.warnings = []
        self.obj = obj          # the executable (heron.infra.obj.ObjectFile)

    def code_bytes(self):
        return self._code


class Linker:
    """`mem_top` is the address the program must end below: by default the
    ISA's MEM_TOP. A kernel linked into the supervisor's window, at
    0x80000000 on draft 2, passes its own."""

    def __init__(self, isa=None, base=None, gc=True, entry=None, mem_top=None):
        self.isa = isa
        self.base = base
        self.gc = gc
        self.entry = entry
        self.mem_top = mem_top
        self.objects = []       # ObjectFiles
        self.archives = []      # [[(name, ObjectFile), ...], ...]
        self._map = None

    def add(self, obj):
        self.objects.append(obj)

    def add_library(self, members):
        self.archives.append(list(members))

    def link(self):
        from . import isas
        isa = self.isa
        if isa is None:
            first = self.objects + [o for lib in self.archives for _, o in lib]
            isa = first[0].isa if first else None
        mem_top = self.mem_top
        if mem_top is None:
            mem_top = getattr(isas.get(isa), "MEM_TOP", 0x10000) if isa else 0x10000
        try:
            out = native.toolchain.link(
                [(o.name, o.to_bytes()) for o in self.objects],
                [[(n, o.name, o.to_bytes()) for n, o in lib] for lib in self.archives],
                self.isa, self.base, self.gc, self.entry, mem_top)
        except native.toolchain.LinkFailed as e:
            raise LinkError(list(e.args[0])) from None
        self.isa = out["isa"]
        self._map = out["map"]
        mem = {}
        for addr, data in out["contents"]:
            for i, b in enumerate(data):
                mem[addr + i] = b
        labels = [Label(name, a) for name, a in out["labels"]]
        exe = O.ObjectFile.from_bytes(out["exe"], "a.out")
        return LinkedImage(mem, dict(out["symbols"]), labels, out["code"], exe)

    def map(self):
        """The layout, as text (after link())."""
        return self._map


def load_executable(obj):
    """A LinkedImage from an executable file (heron.infra.obj.ObjectFile)."""
    if not obj.executable:
        raise LinkError(f"{obj.name} isn't an executable (link it first)")
    mem = {}
    code = 0
    for sec in obj.sections:
        data = bytes(sec.size) if sec.nobits else sec.data
        for i, b in enumerate(data):
            mem[sec.addr + i] = b
        code += sec.code
    symbols = {}
    labels = []
    for s in obj.symbols:
        symbols.setdefault(s.name, s.value)
        if s.is_global:
            symbols[s.name] = s.value
        labels.append(Label(s.name, s.value))
    labels.sort(key=lambda l: l.addr)
    return LinkedImage(mem, symbols, labels, code, obj)


def link(objects, libraries=(), isa=None, **kw):
    """objects: [ObjectFile]; libraries: [[(name, ObjectFile)]]. Returns a LinkedImage."""
    ln = Linker(isa, **kw)
    for o in objects:
        ln.add(o)
    for lib in libraries:
        ln.add_library(lib)
    img = ln.link()
    img.linker = ln
    return img
