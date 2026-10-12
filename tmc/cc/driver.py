"""Compile C files into one assembly file for draft 1a or 1b.

There's no linker yet: every translation unit (the program's and the C
library's) is compiled to IR, statics are renamed apart, everything not
reachable from main is dropped, and the backend writes a single .s file
that the existing assembler (tmc.asm) turns into an image.

Layout of the output: the start code and vectors, then all data (small
objects first, so most globals sit below 32 KB where 16-bit absolute
addresses reach them), then the code, then `__end` (where the heap starts).
"""

import os

from ..ir import ir as I
from ..ir.passes import optimize
from ..ir.cfg import verify
from .lex import CompileError
from .cpp import Preprocessor
from .parse import parse
from .irgen import IRGen

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(HERE, "lib")
LIB_SOURCES = ["stdio.c", "string.c", "stdlib.c", "ctype.c"]
START_BOUND = 0x100          # the start code ends below this
ASM_SYMBOLS = {"exit", "abort", "_end"}   # defined by the start code (lib/start_*.s)
NEAR_LIMIT = 0x8000


def target_for(isa):
    if isa == "v1a":
        from ..codegen.v1a import V1A
        return V1A
    if isa == "v1b":
        from ..codegen.v1b import V1B
        return V1B
    raise CompileError(f"no C compiler backend for ISA {isa} (use v1a or v1b)")


class Unit:
    def __init__(self, path, module, warnings):
        self.path = path
        self.module = module
        self.warnings = warnings


def compile_unit(path, isa, include=(), defines=None, text=None):
    d = {"__TMC__": "1", "__STDC__": "1", "__" + isa.upper() + "__": "1",
         "__CHAR_UNSIGNED__": "1"}
    d.update(defines or {})
    pp = Preprocessor(include_paths=include, defines=d)
    toks = pp.run(text, path) if text is not None else pp.run_file(path)
    tu = parse(toks)
    module = IRGen(tu).run()
    return Unit(path, module, tu.warnings)


def rename_symbols(module, mapping):
    """Rename global symbols in a module (SymAddr operands, data, names)."""
    if not mapping:
        return

    def fix(v):
        if isinstance(v, I.SymAddr) and v.name in mapping:
            return I.SymAddr(mapping[v.name], v.offset)
        return v
    for f in module.functions:
        if f.name in mapping:
            f.name = mapping[f.name]
        for i in f.instructions():
            i.args = [fix(a) for a in i.args]
    for d in module.data:
        if d.name in mapping:
            d.name = mapping[d.name]
        d.items = [(k, fix(v)) if k == "word" else (k, v) for k, v in d.items]


class Program:
    def __init__(self, isa, opt=1, verify_ir=False, need_main=True):
        self.isa = isa
        self.opt = opt
        self.verify_ir = verify_ir
        self.need_main = need_main      # False: keep every function of the program's own files
        self.units = []
        self.warnings = []

    def add_file(self, path, include=(), defines=None, text=None):
        u = compile_unit(path, self.isa, include, defines, text)
        self.units.append(u)
        self.warnings.extend(u.warnings)
        return u

    def add_library(self):
        for name in LIB_SOURCES:
            u = self.add_file(os.path.join(LIB_DIR, name))
            u.library = True

    def link(self):
        """Resolve symbols across units; returns (functions, data) by name."""
        defined = {}
        statics = []
        for n, u in enumerate(self.units):
            for obj in u.module.functions + u.module.data:
                if obj.static:
                    statics.append((n, obj))
                    continue
                if obj.name in defined:
                    other = defined[obj.name][0]
                    lib = getattr(self.units[other], "library", False)
                    if lib and not getattr(u, "library", False):
                        # the program's own definition replaces the library's
                        defined[obj.name] = (n, obj)
                        continue
                    if not lib or getattr(u, "library", False):
                        raise CompileError(f"{obj.name} is defined in both "
                                           f"{self.units[other].path} and {u.path}")
                    continue
                defined[obj.name] = (n, obj)
        taken = set(defined)
        renames = [dict() for _ in self.units]
        for n, obj in statics:
            name = obj.name
            new = name
            k = 1
            while new in taken:
                k += 1
                new = f"{name}_{k}"
            taken.add(new)
            if new != name:
                renames[n][name] = new
        for n, u in enumerate(self.units):
            rename_symbols(u.module, renames[n])
        objs = {}
        for n, u in enumerate(self.units):
            for obj in u.module.functions + u.module.data:
                if obj.static or defined.get(obj.name, (None, None))[1] is obj:
                    objs[obj.name] = obj
        return objs

    def compile(self):
        free_imm = target_for(self.isa).free_imm if self.opt > 0 else None
        for u in self.units:
            for f in u.module.functions:
                if self.verify_ir:
                    verify(f)
                optimize(f, self.opt, verify=self.verify_ir, free_imm=free_imm)
        objs = self.link()
        if self.need_main:
            if "main" not in objs:
                raise CompileError("no main function")
            roots = ["main"]
        else:
            roots = [f.name for u in self.units if not getattr(u, "library", False)
                     for f in u.module.functions]
        # keep what the roots can reach
        for u in self.units:
            for f in u.module.functions:
                for i in f.instructions():
                    if i.op == "memcpy" and i.size > 64:
                        roots.append("memcpy")
        live = set()
        work = [r for r in roots if r in objs]
        while work:
            name = work.pop()
            if name in live:
                continue
            live.add(name)
            obj = objs[name]
            refs = []
            if isinstance(obj, I.Function):
                for i in obj.instructions():
                    refs += [a.name for a in i.args if isinstance(a, I.SymAddr)]
            else:
                refs += [v.name for k, v in obj.items if k == "word" and isinstance(v, I.SymAddr)]
            for r in refs:
                if r in ASM_SYMBOLS:
                    continue
                if r not in objs:
                    raise CompileError(f"undefined reference to {r} (from {name})")
                if r not in live:
                    work.append(r)
        self.lib_functions = {f.name for u in self.units if getattr(u, "library", False)
                              for f in u.module.functions}
        funcs = [o for o in objs.values() if isinstance(o, I.Function) and o.name in live]
        data = [o for o in objs.values() if isinstance(o, I.GlobalData) and o.name in live]
        return funcs, data

    def assembly(self):
        funcs, data = self.compile()
        # data layout: small objects first
        data.sort(key=lambda d: (d.size > 256, d.size > 4096, 0))
        addr = START_BOUND
        ends = {}
        for d in data:
            addr = (addr + d.align - 1) // d.align * d.align
            ends[d.name] = (addr, addr + d.size)
            addr += d.size

        def near(name, off=0):
            if name not in ends:
                return False
            lo, hi = ends[name]
            return 0 <= lo + min(off, 0) and hi + max(off, 0) < NEAR_LIMIT

        def symname(n):
            return "_" + n

        T = target_for(self.isa)
        target = T(symname=symname, near=near)
        out = [f"; generated by the tmc C compiler for draft {self.isa[1:]}", ""]
        if self.need_main:
            with open(os.path.join(LIB_DIR, f"start_{self.isa}.s")) as f:
                out.append(f.read())
        else:
            out.append(f"        .org {START_BOUND}          ; no start code: not a whole program")
        out.append("; ---- data ----")
        for d in data:
            out.append(format_data(d, symname))
        out.append("")
        out.append("; ---- code ----")
        out.append("        .align 2")
        order = {"main": 0}
        funcs.sort(key=lambda f: order.get(f.name, 1))
        for f in funcs:
            out.append(target.compile_function(f))
        out.append("        .align 4")
        out.append("__end:")
        return "\n".join(out) + "\n"


def format_data(d, symname):
    lines = []
    if d.align > 1:
        lines.append(f"        .align {d.align}")
    lines.append(f"{symname(d.name)}:")
    for kind, v in d.items:
        if kind == "zero":
            lines.append(f"        .space {v}")
        elif kind == "word":
            s = symname(v.name) + (f"{v.offset:+d}" if v.offset else "")
            lines.append(f"        .word {s}")
        elif kind == "bytes":
            data = bytes(v)
            for k in range(0, len(data), 16):
                chunk = data[k:k + 16]
                lines.append("        .byte " + ", ".join(str(b) for b in chunk))
        else:
            lines.append(f"        .{kind} {v}")
    return "\n".join(lines)


def compile_files(paths, isa, opt=1, include=(), defines=None, library=True, verify_ir=False,
                  program=None):
    p = program or Program(isa, opt, verify_ir)
    for path in paths:
        p.add_file(path, include, defines)
    if library:
        p.add_library()
    return p.assembly(), p.warnings


def compile_to_ir(paths, isa, opt=1, include=(), defines=None):
    p = Program(isa, opt)
    for path in paths:
        p.add_file(path, include, defines)
    for u in p.units:
        for f in u.module.functions:
            optimize(f, opt)
    return "\n".join(str(u.module) for u in p.units)


def build(paths, isa, opt=1, include=(), defines=None, library=True, verify_ir=False,
          program=None):
    """Compile and assemble: returns (assembly text, image, warnings)."""
    from .. import asm as asmcore
    from .. import isa as isas
    text, warnings = compile_files(paths, isa, opt, include, defines, library, verify_ir,
                                   program)
    try:
        img = asmcore.assemble_text(isas.get(isa), text, "<compiled>")
    except asmcore.AsmError as e:
        raise CompileError(f"assembler: {e}")
    return text, img, warnings


def run_image(img, isa, inp=b"", max_cycles=200_000_000):
    """Run on the instruction-level simulator; returns the machine."""
    from .. import isa as isas
    from ..sim32 import Machine32, SimError
    m = Machine32(isas.get(isa), img, inp=inp)
    try:
        m.run(max_cycles=max_cycles)
    except SimError as e:
        m.error = str(e)
    else:
        m.error = None
    return m
