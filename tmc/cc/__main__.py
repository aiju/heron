"""C compiler command line. Also reachable as `python3 -m tmc --isa v1b cc ...`.

    python3 -m tmc.cc [--isa v1a|v1b] FILE... [-o OUT] [-c | -S | --run] [--stats]
                      [--emit-ir] [-O0] [-I DIR] [-D NAME[=VALUE]] [--input TEXT]

FILEs are C (.c), assembly (.s), object files (.o) and libraries (.a). Without
-c, -S or --run, everything is compiled and linked with the start code and
the C library into an executable (FIRST.out, or -o), which `tmc run` runs.
"""

import argparse
import os
import sys

from .lex import CompileError


def add_arguments(p):
    p.add_argument("files", nargs="+", help=".c, .s, .o and .a files")
    p.add_argument("-o", help="the output file (default: FIRST.out, or FILE.o/.s with -c/-S)")
    p.add_argument("-c", action="store_true", help="only compile (and assemble) into object files")
    p.add_argument("-S", action="store_true", help="only compile into assembly")
    p.add_argument("--run", action="store_true", help="link and run on the simulator")
    p.add_argument("--stats", action="store_true", help="with --run: cycles, code size, profile")
    p.add_argument("--map", action="store_true", help="print where the linker put everything")
    p.add_argument("--input", help="with --run: console input (escapes allowed)")
    p.add_argument("--input-file")
    p.add_argument("--max-cycles", type=int, default=500_000_000)
    p.add_argument("--emit-ir", action="store_true", help="print the optimised IR and stop")
    p.add_argument("-O", dest="opt", type=int, default=1, help="0: only mem2reg, 1: optimise (default)")
    p.add_argument("-I", dest="include", action="append", default=[])
    p.add_argument("-D", dest="define", action="append", default=[])
    p.add_argument("--no-lib", action="store_true", help="don't link the C library")
    p.add_argument("--no-start", action="store_true",
                   help="no start code: the program brings its own vectors")
    p.add_argument("--verify", action="store_true", help="check the IR after every pass")
    p.add_argument("-W", dest="warnings", action="store_true", help="show warnings")


def output_name(args, path, ext):
    if args.o:
        return args.o
    return os.path.splitext(path)[0] + ext


def file_kind(path):
    from .. import obj as O
    if path.endswith(".c"):
        return "c"
    with open(path, "rb") as f:
        head = f.read(4)
    return {O.MAGIC: "object", O.AR_MAGIC: "library"}.get(head, "asm")


def run(args, isa):
    from . import driver
    from .. import obj as O
    from ..tools import assemble_object
    from .. import asm as asmcore
    defines = {}
    for d in args.define:
        k, _, v = d.partition("=")
        defines[k] = v or "1"
    c_files = [f for f in args.files if f.endswith(".c")]
    if (args.c or args.S) and args.o and len(args.files) > 1:
        print("error: -o with -c or -S needs a single input file", file=sys.stderr)
        return 1
    try:
        if args.emit_ir:
            print(driver.compile_to_ir(c_files, isa, args.opt, args.include, defines))
            return 0
        p = driver.Program(isa, args.opt, args.verify, need_main=not args.no_start)
        units = {}
        for path in args.files:
            kind = file_kind(path)
            if kind == "c":
                units[path] = p.add_file(path, args.include, defines)
            elif kind == "object":
                o = O.read_object(path)
                if o.isa != isa:
                    raise CompileError(f"{path} is for {o.isa}, not {isa}")
                p.add_object(o)
            elif kind == "library":
                p.add_archive(O.read_archive(path))
            else:
                if args.S:
                    continue
                o = assemble_object(isa, path)
                if args.c:
                    o.write(output_name(args, path, ".o"))
                    continue
                p.add_object(o)
        if args.warnings:
            for w in p.warnings:
                print(w, file=sys.stderr)
        if args.S or args.c:
            for path, u in units.items():
                text = driver.unit_assembly(u, isa, args.opt, args.verify)
                if args.S:
                    with open(output_name(args, path, ".s"), "w") as f:
                        f.write(text)
                else:
                    name = os.path.basename(path)[:-2] + ".o"
                    driver.assemble(isa, text, name).write(output_name(args, path, ".o"))
            return 0
        if not args.no_lib:
            p.add_library()
        if not units and not p.objects_in:
            raise CompileError("nothing to compile")
        img = p.link()
    except CompileError as e:
        print(e, file=sys.stderr)
        return 1
    except (O.ObjError, asmcore.AsmError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.map:
        sys.stdout.write(img.linker.map())
    if not args.run or args.o:
        img.obj.write(output_name(args, args.files[0], ".out"))
    if not args.run:
        return 0
    from .. import isa as isas
    from ..__main__ import run32
    inp = args.input.encode().decode("unicode_escape").encode("latin-1") if args.input else b""
    if args.input_file:
        with open(args.input_file, "rb") as f:
            inp = f.read()
    ns = argparse.Namespace(file=args.files[0], input=args.input if args.input is not None else "",
                            input_file=args.input_file,
                            trace=False, stats=args.stats, regs=False,
                            max_cycles=args.max_cycles)
    return run32(ns, isas.get(isa), img, inp)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tmc.cc", description="C compiler for the TTL minicomputer")
    p.add_argument("--isa", default="v1b")
    add_arguments(p)
    args = p.parse_args(argv)
    return run(args, args.isa)


if __name__ == "__main__":
    sys.exit(main())
