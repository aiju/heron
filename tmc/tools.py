"""Command-line tools for object files: ld, objdump, ar, and loading
programs for `run` (see tmc/__main__.py).
"""

import os
import sys

from . import asm as asmcore
from . import isa as isas
from . import obj as O
from . import link as L


def assemble_object(isa_name, path, text=None):
    a = asmcore.Assembler(isas.get(isa_name), relocatable=True)
    a.load(path, text=text)
    o = a.assemble_object(os.path.basename(path))
    o.warnings = a.warnings
    return o


def file_isa(path):
    """The ISA an object file, executable or library is for (None for source)."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head == O.MAGIC:
        return O.read_object(path).isa
    if head == O.AR_MAGIC:
        members = O.read_archive(path)
        return members[0][1].isa if members else None
    return None


def pick_isa(requested, paths):
    """The ISA for a set of inputs: what the object files say. `requested`
    is --isa, or None if it wasn't given; it only matters for assembly
    source, and must agree with the object files if given."""
    found = {i for i in (file_isa(p) for p in paths) if i}
    if len(found) > 1:
        raise L.LinkError(f"the files are for different ISAs: {', '.join(sorted(found))}")
    if found:
        isa = found.pop()
        if requested not in (None, isa):
            raise L.LinkError(f"the object files are for {isa}, not {requested}")
        return isa
    return requested or isas.DEFAULT


def link_files(isa_name, paths, **kw):
    """Link .o, .a and .s files (assembled as object files). Returns
    (LinkedImage, Linker)."""
    ln = L.Linker(isa_name, **kw)
    for p in paths:
        with open(p, "rb") as f:
            head = f.read(4)
        if head == O.MAGIC:
            o = O.read_object(p)
            if o.executable:
                raise L.LinkError(f"{p} is already linked")
            ln.add(o)
        elif head == O.AR_MAGIC:
            ln.add_library(O.read_archive(p))
        else:
            ln.add(assemble_object(isa_name, p))
    img = ln.link()
    return img, ln


def load_program(isa_name, paths):
    """What `run` runs: one .s file (assembled as an image, as always), an
    executable, or object files to link. isa_name is --isa, or None if it
    wasn't given (see pick_isa). Returns (image, isa name)."""
    if len(paths) == 1 and file_isa(paths[0]) is None:
        isa_name = isa_name or isas.DEFAULT
        return asmcore.assemble_file(isas.get(isa_name), paths[0]), isa_name
    isa_name = pick_isa(isa_name, paths)
    if len(paths) == 1:
        o = O.read_object(paths[0]) if O.is_object(paths[0]) else None
        if o is not None and o.executable:
            return L.load_executable(o), isa_name
    img, _ = link_files(isa_name, paths)
    return img, isa_name


def write_binary(img, isa, path):
    lo, hi = img.extent()
    with open(path, "wb") as f:
        f.write(img.to_bytes(max(hi, 0x10000) if getattr(isa, "WIDE", False) else 0x10000))


# ---- tmc ld ------------------------------------------------------------------


def cmd_ld(args):
    try:
        isa_name = pick_isa(args.isa if args.isa_given else None, args.files)
        img, ln = link_files(isa_name, args.files, base=args.base, gc=not args.no_gc,
                             entry=args.entry)
    except (L.LinkError, O.ObjError, asmcore.AsmError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = args.o or os.path.splitext(args.files[0])[0] + ".out"
    img.obj.write(out)
    if args.bin:
        write_binary(img, isas.get(isa_name), args.bin)
    if args.map:
        sys.stdout.write(ln.map())
    lo, hi = img.extent()
    print(f"{out}: {img.code_bytes()} bytes of code, {lo:04X}-{hi - 1:04X}", file=sys.stderr)
    return 0


def add_ld_arguments(p):
    p.add_argument("files", nargs="+", help="object files (.o), libraries (.a), assembly (.s)")
    p.add_argument("-o", help="the executable (default: FIRST.out)")
    p.add_argument("--bin", help="also write a raw memory image")
    p.add_argument("--map", action="store_true", help="print where everything went")
    p.add_argument("--base", type=lambda s: int(s, 0),
                   help="where the relocatable sections start (default: after the absolute ones)")
    p.add_argument("--entry", help="keep this symbol and what it uses (as well as the vectors)")
    p.add_argument("--no-gc", action="store_true", help="keep sections nothing refers to")


# ---- tmc ar ------------------------------------------------------------------


def cmd_ar(args):
    if args.t:
        try:
            members = O.read_archive(args.t)
        except (O.ObjError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for name, o in members:
            globs = [s.name for s in o.symbols if s.is_global and s.defined]
            print(f"{name}: {' '.join(globs)}")
        return 0
    if not args.o or not args.files:
        print("error: tmc ar -o LIB.a FILE.o ...  (or -t LIB.a)", file=sys.stderr)
        return 1
    members = []
    for p in args.files:
        try:
            o = O.read_object(p)
        except (O.ObjError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        members.append((os.path.basename(p), o))
    with open(args.o, "wb") as f:
        f.write(O.archive_bytes(members))
    return 0


def add_ar_arguments(p):
    p.add_argument("files", nargs="*")
    p.add_argument("-o", help="the library to write")
    p.add_argument("-t", metavar="LIB", help="list a library's members and what they define")


# ---- tmc objdump -----------------------------------------------------------------


def dump(o, disasm=False, out=None):
    w = (out or sys.stdout).write       # sys.stdout now, not when this module was imported
    kind = "executable" if o.executable else "object file"
    w(f"{o.name}: {kind} for {o.isa}\n\nsections:\n")
    for k, s in enumerate(o.sections, 1):
        where = f"at {s.addr:06X}" if s.absolute else "relocatable"
        extra = ", zero-filled" if s.nobits else (f", {s.code} bytes of code" if s.code else "")
        w(f"  {k:3d} {s.name:<24} {s.size:6d} bytes, align {s.align}, {where}{extra}\n")
    w("\nsymbols:\n")
    for k, s in enumerate(o.symbols):
        if s.section == O.UNDEF:
            where = "undefined"
        elif s.section == O.ABS:
            where = f"= {s.value:#x}"
        else:
            where = f"{o.sections[s.section - 1].name}+{s.value:#x}"
        flags = " ".join(n for f, n in ((O.SYM_GLOBAL, "global"), (O.SYM_FAR, "far"),
                                        (O.SYM_SECTION, "section")) if s.flags & f)
        w(f"  {k:4d} {s.name:<28} {where:<24} {flags}\n")
    if o.relocs:
        w("\nrelocations:\n")
        for r in o.relocs:
            s = o.symbols[r.symbol]
            w(f"  {o.sections[r.section - 1].name}+{r.offset:#06x}  {O.RELOC_NAMES[r.kind]:<7}"
              f" {s.name}{r.addend:+d}\n")
    if disasm:
        isa = isas.get(o.isa)
        if not getattr(isa, "WIDE", False):
            w("\n(disassembly only for the draft 1 ISAs)\n")
            return
        relocs = {}
        for r in o.relocs:
            relocs.setdefault(r.section, {})[r.offset] = r
        labels = {}
        for s in o.symbols:
            if s.section not in (O.UNDEF, O.ABS) and not s.flags & O.SYM_SECTION:
                labels.setdefault((s.section, s.value), s.name)
        for k, s in enumerate(o.sections, 1):
            if s.nobits or not s.code:
                continue
            w(f"\n{s.name}:\n")
            data = s.data + bytes(6)
            a = 0
            while a < s.size - 1:
                if (k, a) in labels:
                    w(f"{labels[(k, a)]}:\n")
                ws = [data[a + i] | (data[a + i + 1] << 8) for i in (0, 2, 4)]
                text, n = isa.disassemble(ws, s.addr + a)
                note = [f"{O.RELOC_NAMES[r.kind]} {o.symbols[r.symbol].name}{r.addend:+d}"
                        for off, r in relocs.get(k, {}).items() if a <= off < a + 2 * n]
                comment = f"  ; {', '.join(note)}" if note else ""
                w(f"  {s.addr + a:06X}  {' '.join(f'{x:04X}' for x in ws[:n]):<15} {text}{comment}\n")
                a += 2 * n


def cmd_objdump(args):
    try:
        if O.is_archive(args.file):
            for name, o in O.read_archive(args.file):
                dump(o, args.d)
                print()
            return 0
        dump(O.read_object(args.file), args.d)
    except (O.ObjError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def add_objdump_arguments(p):
    p.add_argument("file")
    p.add_argument("-d", action="store_true", help="disassemble")
