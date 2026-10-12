"""C compiler command line. Also reachable as `python3 -m tmc --isa v1b cc ...`.

    python3 -m tmc.cc [--isa v1a|v1b] FILE.c... [-o OUT.s] [--run] [--stats]
                      [--emit-ir] [-O0] [-I DIR] [-D NAME[=VALUE]] [--input TEXT]
"""

import argparse
import sys

from .lex import CompileError


def add_arguments(p):
    p.add_argument("files", nargs="+")
    p.add_argument("-o", help="write the assembly here (default: FILE.s next to the first file)")
    p.add_argument("-S", action="store_true", help="only write the assembly (the default unless --run)")
    p.add_argument("--run", action="store_true", help="assemble and run on the simulator")
    p.add_argument("--stats", action="store_true", help="with --run: cycles, code size, profile")
    p.add_argument("--input", help="with --run: console input (escapes allowed)")
    p.add_argument("--input-file")
    p.add_argument("--max-cycles", type=int, default=500_000_000)
    p.add_argument("--emit-ir", action="store_true", help="print the optimised IR and stop")
    p.add_argument("-O", dest="opt", type=int, default=1, help="0: only mem2reg, 1: optimise (default)")
    p.add_argument("-I", dest="include", action="append", default=[])
    p.add_argument("-D", dest="define", action="append", default=[])
    p.add_argument("--no-lib", action="store_true", help="don't link the C library")
    p.add_argument("--verify", action="store_true", help="check the IR after every pass")
    p.add_argument("-W", dest="warnings", action="store_true", help="show warnings")


def run(args, isa):
    from . import driver
    defines = {}
    for d in args.define:
        k, _, v = d.partition("=")
        defines[k] = v or "1"
    try:
        if args.emit_ir:
            print(driver.compile_to_ir(args.files, isa, args.opt, args.include, defines))
            return 0
        text, warnings = driver.compile_files(args.files, isa, args.opt, args.include, defines,
                                              library=not args.no_lib, verify_ir=args.verify)
    except CompileError as e:
        print(e, file=sys.stderr)
        return 1
    if args.warnings:
        for w in warnings:
            print(w, file=sys.stderr)
    out = args.o or args.files[0].rsplit(".", 1)[0] + ".s"
    if not args.run or args.o:
        with open(out, "w") as f:
            f.write(text)
    if not args.run:
        return 0
    from .. import asm as asmcore
    from .. import isa as isas
    from ..__main__ import run32
    isa_mod = isas.get(isa)
    try:
        img = asmcore.assemble_text(isa_mod, text, out)
    except asmcore.AsmError as e:
        print(f"assembler: {e}", file=sys.stderr)
        return 1
    inp = args.input.encode().decode("unicode_escape").encode("latin-1") if args.input else b""
    if args.input_file:
        with open(args.input_file, "rb") as f:
            inp = f.read()
    ns = argparse.Namespace(file=out, input=args.input if args.input is not None else "",
                            input_file=args.input_file,
                            trace=False, stats=args.stats, regs=False,
                            max_cycles=args.max_cycles)
    return run32(ns, isa_mod, img, inp)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tmc.cc", description="C compiler for the TTL minicomputer")
    p.add_argument("--isa", default="v1b")
    add_arguments(p)
    args = p.parse_args(argv)
    return run(args, args.isa)


if __name__ == "__main__":
    sys.exit(main())
