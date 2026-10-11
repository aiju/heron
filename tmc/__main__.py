"""Command line: python3 -m tmc <command> ...

  asm   FILE.s [-o FILE.bin] [-l FILE.lst]   assemble
  run   FILE.s [--input TEXT] [--trace] [--stats]
  dis   FILE.bin [--from ADDR] [--to ADDR]   disassemble a binary image
  test  [NAME...]                            run the program test suite
  ucode [-o DIR]                             build microcode ROM images
  bench                                      instruction-level benchmark table
  hw    ...                                  chip-level tools (see tmc.hw.cli)
"""

import argparse
import sys

from . import asm as asmcore
from . import isa as isas
from .sim import Machine, SimError


def load_image(isa, path):
    return asmcore.assemble_file(isa, path)


def get_timing(isa_name, enabled=True):
    if not enabled:
        return None
    from .hw import microcode
    return microcode.timing_function(isa_name)


def cmd_asm(args):
    isa = isas.get(args.isa)
    try:
        img = load_image(isa, args.file)
    except asmcore.AsmError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in img.warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = args.o or args.file.rsplit(".", 1)[0] + ".bin"
    with open(out, "wb") as f:
        f.write(img.to_bytes())
    if args.l:
        with open(args.l, "w") as f:
            f.write(img.listing())
    lo, hi = img.extent()
    print(f"{args.file}: {img.code_bytes()} bytes of code, image {lo:04X}-{hi - 1:04X} -> {out}")
    return 0


def cmd_run(args):
    isa = isas.get(args.isa)
    try:
        img = load_image(isa, args.file)
    except asmcore.AsmError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    inp = args.input.encode().decode("unicode_escape").encode("latin-1") if args.input else b""
    if args.input_file:
        with open(args.input_file, "rb") as f:
            inp = f.read()
    m = Machine(isa, img, inp=inp, timing=get_timing(args.isa, not args.no_timing))
    if args.trace:
        syms = {v: k for k, v in img.symbols.items()}

        def tr(m):
            w = m.rd16(m.pc) if m.pc < isa.IO_BASE else 0
            nxt = m.rd16(m.pc + 2) if m.pc + 2 < isa.IO_BASE else 0
            text, _ = isa.disassemble(w, nxt, m.pc, syms)
            print(f"{m.cycles:>9} {m.pc:04X}  {text:<26} {m.regs_str()}", file=sys.stderr)
        m.trace = tr
    try:
        m.run(max_cycles=args.max_cycles)
    except SimError as e:
        sys.stdout.write(m.dev.out.decode("latin-1"))
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(m.dev.out.decode("latin-1"))
    sys.stdout.flush()
    if args.stats or args.regs:
        print(f"\n--- halted at {m.pc:04X}: {m.instructions} instructions, {m.cycles} cycles"
              f" (CPI {m.cycles / max(1, m.instructions):.2f})", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
    if args.stats:
        print(f"code size {img.code_bytes()} bytes, lowest SP {m.min_sp:04X}", file=sys.stderr)
        for k, n in m.kinds.most_common():
            print(f"  {k:<14} {n:>9}  {100 * n / max(1, m.instructions):5.1f}%"
                  f"  {m.kind_cycles[k]:>10} cycles", file=sys.stderr)
    return 0


def cmd_dis(args):
    isa = isas.get(args.isa)
    with open(args.file, "rb") as f:
        data = f.read()
    a = int(args.start, 0)
    end = int(args.end, 0) if args.end else len(data)
    while a < end - 1:
        w = data[a] | (data[a + 1] << 8)
        nxt = data[a + 2] | (data[a + 3] << 8) if a + 3 < len(data) else 0
        text, n = isa.disassemble(w, nxt, a)
        words = " ".join(f"{data[a + 2*i] | (data[a + 2*i + 1] << 8):04X}" for i in range(n))
        print(f"{a:04X}  {words:<10} {text}")
        a += 2 * n
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="tmc", description="TTL minicomputer tools")
    p.add_argument("--isa", default=isas.DEFAULT, help="ISA revision (default %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("asm", help="assemble a source file")
    a.add_argument("file")
    a.add_argument("-o")
    a.add_argument("-l", help="write a listing")
    a.set_defaults(fn=cmd_asm)

    r = sub.add_parser("run", help="assemble and run on the instruction-level simulator")
    r.add_argument("file")
    r.add_argument("--input", help="console input (escapes allowed)")
    r.add_argument("--input-file")
    r.add_argument("--trace", action="store_true")
    r.add_argument("--stats", action="store_true")
    r.add_argument("--regs", action="store_true")
    r.add_argument("--no-timing", action="store_true", help="count 1 cycle per instruction")
    r.add_argument("--max-cycles", type=int, default=200_000_000)
    r.set_defaults(fn=cmd_run)

    d = sub.add_parser("dis", help="disassemble a binary image")
    d.add_argument("file")
    d.add_argument("--from", dest="start", default="0")
    d.add_argument("--to", dest="end")
    d.set_defaults(fn=cmd_dis)

    t = sub.add_parser("test", help="run the program test suite")
    t.add_argument("names", nargs="*")
    t.add_argument("-v", action="store_true")
    t.set_defaults(fn=lambda args: __import__("tmc.testing", fromlist=["x"]).cmd_test(args))

    u = sub.add_parser("ucode", help="build microcode ROM images")
    u.add_argument("-o", default="build/ucode")
    u.set_defaults(fn=lambda args: __import__("tmc.hw.microcode", fromlist=["x"]).cmd_ucode(args))

    b = sub.add_parser("bench", help="instruction-level benchmark table")
    b.add_argument("--markdown", action="store_true")
    b.set_defaults(fn=lambda args: __import__("tmc.testing", fromlist=["x"]).cmd_bench(args))

    h = sub.add_parser("hw", help="chip-level tools")
    h.add_argument("rest", nargs=argparse.REMAINDER)
    h.set_defaults(fn=lambda args: __import__("tmc.hw.cli", fromlist=["x"]).main(args.rest))

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
