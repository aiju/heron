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
"""

from . import obj as O
from .asm import Image

ORDER = [(".data", ".rodata"), (".bss",), (".text",), None, (".fardata",), (".farbss",)]
LINKER_SYMBOLS = ("__end",)


class LinkError(Exception):
    def __init__(self, msgs):
        msgs = [msgs] if isinstance(msgs, str) else msgs
        super().__init__("\n".join(msgs[:20]) + (f"\n... and {len(msgs) - 20} more" if len(msgs) > 20 else ""))
        self.msgs = msgs


def section_class(name):
    other = None
    for k, prefixes in enumerate(ORDER):
        if prefixes is None:
            other = k
            continue
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            return k
    return other


def align_up(a, n):
    return (a + n - 1) // n * n


class Input:
    def __init__(self, obj, library=False):
        self.obj = obj
        self.library = library
        self.addr = [None] * len(obj.sections)
        self.live = [False] * len(obj.sections)


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
    def __init__(self, isa=None, base=None, gc=True, entry=None):
        self.isa = isa
        self.base = base
        self.gc = gc
        self.entry = entry
        self.inputs = []
        self.archives = []      # [[(name, ObjectFile), ...], ...]

    def add(self, obj):
        self.check_isa(obj)
        if obj.executable:
            raise LinkError(f"{obj.name} is an executable, not an object file")
        self.inputs.append(Input(obj))

    def add_library(self, members):
        for _, o in members:
            self.check_isa(o)
        self.archives.append(list(members))

    def check_isa(self, obj):
        if self.isa is None:
            self.isa = obj.isa
        elif obj.isa != self.isa:
            raise LinkError(f"{obj.name} is for {obj.isa}, not {self.isa}")

    # ---- symbols ---------------------------------------------------------

    def define_globals(self, inp, errors):
        for k, s in enumerate(inp.obj.symbols):
            if not s.is_global or not s.defined:
                continue
            prev = self.defs.get(s.name)
            if prev is None:
                self.defs[s.name] = (inp, k)
            elif prev[0].library and not inp.library:
                self.defs[s.name] = (inp, k)        # the program's own replaces the library's
            elif inp.library and not prev[0].library:
                pass
            else:
                errors.append(f"{s.name} is defined in both {prev[0].obj.name} and {inp.obj.name}")

    def resolve(self):
        errors = []
        self.defs = {}
        for inp in self.inputs:
            self.define_globals(inp, errors)
        loaded = set()
        while True:
            wanted = {s.name for inp in self.inputs for s in inp.obj.symbols
                      if not s.defined and s.name not in self.defs}
            member = None
            for ai, members in enumerate(self.archives):
                for mi, (_, o) in enumerate(members):
                    if (ai, mi) in loaded:
                        continue
                    if any(s.is_global and s.defined and s.name in wanted for s in o.symbols):
                        member = (ai, mi, o)
                        break
                if member:
                    break
            if member is None:
                break
            loaded.add(member[:2])
            inp = Input(member[2], library=True)
            self.inputs.append(inp)
            self.define_globals(inp, errors)
        if errors:
            raise LinkError(errors)

    def target_of(self, inp, k):
        """(input, symbol index) a reference resolves to; None if undefined."""
        s = inp.obj.symbols[k]
        if s.is_global or not s.defined:
            return self.defs.get(s.name)
        return inp, k

    # ---- garbage collection -----------------------------------------------

    def mark(self):
        work = []

        def keep(inp, k):
            if not inp.live[k]:
                inp.live[k] = True
                work.append((inp, k))
        roots = False
        for inp in self.inputs:
            for k, sec in enumerate(inp.obj.sections):
                if sec.absolute:
                    keep(inp, k)
                    roots = True
        if self.entry is not None:
            t = self.defs.get(self.entry)
            if t is None:
                raise LinkError(f"entry symbol {self.entry} isn't defined")
            sec = t[0].obj.symbols[t[1]].section
            if sec not in (O.UNDEF, O.ABS):
                keep(t[0], sec - 1)
            roots = True
        if not roots or not self.gc:
            for inp in self.inputs:
                if not inp.library or not self.gc:
                    for k in range(len(inp.obj.sections)):
                        keep(inp, k)
        by_section = {}
        for inp in self.inputs:
            for r in inp.obj.relocs:
                by_section.setdefault((id(inp), r.section - 1), []).append(r)
        while work:
            inp, k = work.pop()
            for r in by_section.get((id(inp), k), ()):
                t = self.target_of(inp, r.symbol)
                if t is None:
                    continue
                sec = t[0].obj.symbols[t[1]].section
                if sec not in (O.UNDEF, O.ABS):
                    keep(t[0], sec - 1)

    # ---- layout ----------------------------------------------------------

    def layout(self):
        from . import isas
        mem_top = getattr(isas.get(self.isa), "MEM_TOP", 0x10000)
        placed = []
        for inp in self.inputs:
            for k, sec in enumerate(inp.obj.sections):
                if inp.live[k] and sec.absolute:
                    inp.addr[k] = sec.addr
                    placed.append((sec.addr, sec.addr + sec.size, inp, k))
        placed.sort(key=lambda p: (p[0], p[1]))
        errors = []
        for a, b in zip(placed, placed[1:]):
            if b[0] < a[1]:
                errors.append(f"{a[2].obj.name}({a[2].obj.sections[a[3]].name}) at "
                              f"{a[0]:#x}-{a[1] - 1:#x} overlaps {b[2].obj.name}"
                              f"({b[2].obj.sections[b[3]].name}) at {b[0]:#x}")
        if errors:
            raise LinkError(errors)
        addr = self.base if self.base is not None else align_up(max((p[1] for p in placed), default=0), 4)
        order = []
        for inp in self.inputs:
            for k, sec in enumerate(inp.obj.sections):
                if inp.live[k] and not sec.absolute:
                    order.append((section_class(sec.name), inp, k))
        order.sort(key=lambda t: t[0])         # stable: input order within a class
        for _, inp, k in order:
            sec = inp.obj.sections[k]
            addr = align_up(addr, max(sec.align, 1))
            inp.addr[k] = addr
            addr += sec.size
        self.end = align_up(max([addr] + [p[1] for p in placed]), 4)
        if self.end > mem_top:
            raise LinkError(f"the program needs {self.end:#x} bytes, more than the "
                            f"{mem_top:#x} of memory")

    def address(self, inp, k):
        s = inp.obj.symbols[k]
        if s.section == O.ABS:
            return s.value
        return inp.addr[s.section - 1] + s.value

    # ---- the whole thing ---------------------------------------------------

    def link(self):
        if not self.inputs:
            raise LinkError("nothing to link")
        self.resolve()
        self.mark()
        self.layout()
        errors = []
        contents = {}
        for inp in self.inputs:
            for k, sec in enumerate(inp.obj.sections):
                if inp.live[k]:
                    contents[(id(inp), k)] = bytearray(bytes(sec.size) if sec.nobits else sec.data)
        for inp in self.inputs:
            for r in inp.obj.relocs:
                k = r.section - 1
                if not inp.live[k]:
                    continue
                sym = inp.obj.symbols[r.symbol]
                sec = inp.obj.sections[k]
                where = f"{inp.obj.name}({sec.name}+{r.offset:#x})"
                t = self.target_of(inp, r.symbol)
                if t is None:
                    if sym.name in LINKER_SYMBOLS:
                        s = self.end
                    else:
                        errors.append(f"{where}: undefined symbol {sym.name}")
                        continue
                else:
                    s = self.address(*t)
                p = inp.addr[k] + r.offset
                try:
                    data = O.reloc_value(r.kind, s, r.addend, p)
                except ValueError as e:
                    what = sym.name + (f"{r.addend:+d}" if r.addend and r.kind not in (O.PC16, O.PC16H) else "")
                    hint = ""
                    if r.kind == O.ABS16S:
                        hint = "; declare it .far to use 32-bit addresses"
                    errors.append(f"{where}: {O.RELOC_NAMES[r.kind]} reference to {what}: {e}{hint}")
                    continue
                contents[(id(inp), k)][r.offset:r.offset + len(data)] = data
        if errors:
            raise LinkError(errors)
        return self.output(contents)

    def output(self, contents):
        mem = {}
        exe = O.ObjectFile(self.isa, O.EXEC, 0, "a.out")
        code = 0
        secs = []
        for inp in self.inputs:
            for k, sec in enumerate(inp.obj.sections):
                if inp.live[k]:
                    secs.append((inp.addr[k], inp, k, sec))
        secs.sort(key=lambda t: t[0])
        for addr, inp, k, sec in secs:
            data = bytes(contents[(id(inp), k)])
            for i, b in enumerate(data):
                mem[addr + i] = b
            code += sec.code
            exe.sections.append(O.Section(sec.name, O.SEC_ABS | (sec.flags & O.SEC_NOBITS),
                                          addr, sec.size, sec.align,
                                          b"" if sec.nobits else data, sec.code))
        symbols = {}
        labels = []
        for inp in self.inputs:
            for k, s in enumerate(inp.obj.symbols):
                if not s.defined or s.flags & O.SYM_SECTION or s.name == "*ABS*":
                    continue
                if s.section != O.ABS and not inp.live[s.section - 1]:
                    continue
                if s.is_global and self.defs.get(s.name) != (inp, k):
                    continue
                a = self.address(inp, k)
                if s.section != O.ABS:
                    labels.append(Label(s.name, a))
                if s.is_global or s.name not in symbols:
                    symbols[s.name] = a
                exe.symbols.append(O.Symbol(s.name, O.ABS, a, s.flags & ~O.SYM_SECTION))
        if "__end" not in symbols:
            symbols["__end"] = self.end
            exe.symbols.append(O.Symbol("__end", O.ABS, self.end, O.SYM_GLOBAL))
        labels.sort(key=lambda l: l.addr)
        return LinkedImage(mem, symbols, labels, code, exe)

    def map(self):
        """The layout, as text (after link())."""
        lines = []
        rows = []
        for inp in self.inputs:
            for k, sec in enumerate(inp.obj.sections):
                if inp.live[k]:
                    rows.append((inp.addr[k], sec, inp))
        rows.sort(key=lambda r: r[0])
        for addr, sec, inp in rows:
            lines.append(f"{addr:06X}-{addr + max(sec.size, 1) - 1:06X}  {sec.size:6d}  "
                         f"{sec.name:<24} {inp.obj.name}")
        dropped = [(inp.obj.name, sec.name) for inp in self.inputs
                   for k, sec in enumerate(inp.obj.sections) if not inp.live[k]]
        if dropped:
            lines.append(f"({len(dropped)} unused sections left out)")
        lines.append(f"end {self.end:06X}")
        return "\n".join(lines) + "\n"


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
