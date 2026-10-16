"""Draft 0's command line: heron v0_hw <command> ...

  asm    FILE.s [-o FILE.bin] [-l FILE.lst]   assemble
  run    FILE.s [--input TEXT] [--trace] [--stats]   assemble and run
  dis    FILE.bin [--from ADDR] [--to ADDR]   disassemble a binary image
  test   [NAME...]                            the test programs against their expected output
  bench  [--markdown]                         instructions, cycles and run times per program
  analyze                                     ISA usage statistics over all programs
  report [--hw]                               write the generated part of RFC 0001
  ucode  [-o DIR] [--doc]                     microcode ROM images (--doc: microcode.md)
  hw     ...                                  chip-level tools (see heron.infra.hw.runner)

run takes console input from the program's `;! input:` line unless --input
or --input-file is given. It exits with 1 unless the program halts
normally: on a simulator error, at the cycle limit, or when it halts in a
trap handler.
"""

import argparse
import sys

from heron.infra import asm as asmcore
from heron.infra.objtools import write_binary
from heron.infra.programs import halt_status, metadata

from . import isa as v0
from .sim import Machine, SimError


def cmd_asm(args):
    try:
        img = asmcore.assemble_file(v0, args.file)
    except (asmcore.AsmError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in img.warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = args.o or args.file.rsplit(".", 1)[0] + ".bin"
    write_binary(img, v0, out)
    if args.l:
        with open(args.l, "w") as f:
            f.write(img.listing())
    lo, hi = img.extent()
    print(f"{args.file}: {img.code_bytes()} bytes of code, image {lo:04X}-{hi - 1:04X} -> {out}")
    return 0


def cmd_run(args):
    from . import microcode
    try:
        img = asmcore.assemble_file(v0, args.file)
    except (asmcore.AsmError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.input_file:
        with open(args.input_file, "rb") as f:
            inp = f.read()
    elif args.input is not None:
        inp = args.input.encode().decode("unicode_escape").encode("latin-1")
    else:
        inp = metadata(args.file)["input"]      # the program's own ;! input: line, if any
    m = Machine(v0, img, inp=inp, timing=None if args.no_timing else microcode.timing_function("v0"))
    if args.trace:
        syms = {v: k for k, v in img.symbols.items()}

        def tr(m):
            w = m.rd16(m.pc) if m.pc < v0.IO_BASE else 0
            nxt = m.rd16(m.pc + 2) if m.pc + 2 < v0.IO_BASE else 0
            text, _ = v0.disassemble(w, nxt, m.pc, syms)
            print(f"{m.cycles:>9} {m.pc:04X}  {text:<26} {m.regs_str()}", file=sys.stderr)
        m.trace = tr
    err = None
    try:
        m.run(max_cycles=args.max_cycles)
    except SimError as e:
        err = e
    sys.stdout.flush()
    sys.stdout.buffer.write(bytes(m.dev.out))     # as bytes: the console is 8-bit
    sys.stdout.buffer.flush()
    if err is not None:
        print(f"\nerror: {err}", file=sys.stderr)
        return 1
    for pc, w in m.illegals[:5]:
        print(f"\nillegal instruction {w:04X} (trap returns to {pc:04X})", file=sys.stderr)
    status = halt_status(m)
    if args.stats or args.regs:
        print(f"\n--- halted at {m.pc:04X}: {m.instructions} instructions, {m.cycles} cycles"
              f" (CPI {m.cycles / max(1, m.instructions):.2f})", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
    if args.stats:
        print(f"code size {img.code_bytes()} bytes, lowest SP {m.min_sp:04X}", file=sys.stderr)
        for k, n in m.kinds.most_common():
            print(f"  {k:<14} {n:>9}  {100 * n / max(1, m.instructions):5.1f}%"
                  f"  {m.kind_cycles[k]:>10} cycles", file=sys.stderr)
    return status


def cmd_dis(args):
    with open(args.file, "rb") as f:
        data = f.read()
    a = int(args.start, 0)
    end = int(args.end, 0) if args.end else len(data)
    while a < end - 1:
        w = data[a] | (data[a + 1] << 8)
        nxt = data[a + 2] | (data[a + 3] << 8) if a + 3 < len(data) else 0
        text, n = v0.disassemble(w, nxt, a)
        words = " ".join(f"{data[a + 2*i] | (data[a + 2*i + 1] << 8):04X}" for i in range(n))
        print(f"{a:04X}  {words:<10} {text}")
        a += 2 * n
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron v0_hw", description="Draft 0: the 16-bit ISA and its hardware")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("asm", help="assemble a source file")
    a.add_argument("file")
    a.add_argument("-o")
    a.add_argument("-l", help="write a listing")
    a.set_defaults(fn=cmd_asm)

    r = sub.add_parser("run", help="assemble and run on the instruction-level simulator")
    r.add_argument("file")
    r.add_argument("--input", help="console input (escapes allowed; default: the program's "
                                   "';! input:' line)")
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

    t = sub.add_parser("test", help="run the test programs")
    t.add_argument("names", nargs="*")
    t.add_argument("-v", action="store_true")
    t.set_defaults(fn=lambda args: __import__("heron.studies.v0_hw.testing", fromlist=["x"]).cmd_test(args))

    b = sub.add_parser("bench", help="instruction-level benchmark table")
    b.add_argument("--markdown", action="store_true")
    b.set_defaults(fn=lambda args: __import__("heron.studies.v0_hw.testing", fromlist=["x"]).cmd_bench(args))

    an = sub.add_parser("analyze", help="ISA usage statistics over all programs")
    an.set_defaults(fn=lambda args: __import__("heron.studies.v0_hw.analyze", fromlist=["x"]).main())

    rp = sub.add_parser("report", help="write the generated part of RFC 0001")
    rp.add_argument("--hw", action="store_true", help="also run every program on the chip-level simulator")
    rp.add_argument("--jobs", type=int, default=4)
    rp.set_defaults(fn=lambda args: __import__("heron.studies.v0_hw.report", fromlist=["x"]).main(
        (["--hw"] if args.hw else []) + ["--jobs", str(args.jobs)]))

    u = sub.add_parser("ucode", help="build the microcode ROM images")
    u.add_argument("-o", metavar="DIR", help="output directory (default build/ucode)")
    u.add_argument("--doc", action="store_true", help="write microcode.md instead")
    u.set_defaults(fn=lambda args: __import__("heron.studies.v0_hw.microcode", fromlist=["x"]).cmd_ucode(args))

    h = sub.add_parser("hw", help="chip-level tools")
    h.add_argument("rest", nargs=argparse.REMAINDER)
    h.set_defaults(fn=lambda args: _hw(args.rest))

    args = p.parse_args(argv)
    return args.fn(args) or 0


def _hw(argv):
    from heron.infra.hw import runner
    from . import machine
    return runner.main(argv, machine)
