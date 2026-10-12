"""Command line: python3 -m tmc <command> ...

  asm   FILE.s [-o FILE.bin] [-l FILE.lst]   assemble
  asm   -c FILE.s [-o FILE.o]                assemble into an object file (draft 1)
  ld    FILE.o... [-o PROG.out]              link (see tmc/link.py)
  objdump FILE.o [-d]                        show an object file, executable or library
  ar    -o LIB.a FILE.o...                   make a library
  run   FILE.s [--input TEXT] [--trace] [--stats]   (or an executable, or object files)
  dis   FILE.bin [--from ADDR] [--to ADDR]   disassemble a binary image
  test  [NAME...]                            run the program test suite
  ucode [-o DIR] [--doc]                     build microcode ROM images (v1b --doc: listing)
  bench                                      instruction-level benchmark table
  report [--hw]                              write docs/performance.md
  report1                                    write docs/performance-v1.md (draft 1a vs 1b)
  report1b [--hw]                            write docs/performance-v1b.md (draft 1b hardware)
  cc    FILE.c... [--run]                    compile C (drafts 1a and 1b, see docs/compiler.md)
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
    if args.c:
        from .tools import assemble_object
        try:
            o = assemble_object(args.isa, args.file)
        except asmcore.AsmError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for w in o.warnings:
            print(f"warning: {w}", file=sys.stderr)
        out = args.o or args.file.rsplit(".", 1)[0] + ".o"
        o.write(out)
        return 0
    try:
        img = load_image(isa, args.file)
    except asmcore.AsmError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in img.warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = args.o or args.file.rsplit(".", 1)[0] + ".bin"
    with open(out, "wb") as f:
        lo, hi = img.extent()
        f.write(img.to_bytes(max(hi, 0x10000) if getattr(isa, "WIDE", False) else 0x10000))
    if args.l:
        with open(args.l, "w") as f:
            f.write(img.listing())
    lo, hi = img.extent()
    print(f"{args.file}: {img.code_bytes()} bytes of code, image {lo:04X}-{hi - 1:04X} -> {out}")
    return 0


def cmd_run(args):
    from .tools import load_program
    from .link import LinkError
    from .obj import ObjError
    try:
        img, args.isa = load_program(args.isa, args.files)
    except (asmcore.AsmError, LinkError, ObjError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    isa = isas.get(args.isa)
    args.file = args.files[0]
    inp = args.input.encode().decode("unicode_escape").encode("latin-1") if args.input else b""
    if args.input_file:
        with open(args.input_file, "rb") as f:
            inp = f.read()
    if getattr(isa, "WIDE", False):
        return run32(args, isa, img, inp)
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


def parcels_at(read, pc, n=3):
    return [read(pc + 2 * i) for i in range(n)]


def run32(args, isa, img, inp):
    """`run` for the 32-bit draft 1 ISAs."""
    from .sim32 import Machine32, SimError as SimError32
    from . import timing32
    from .isa.v1common import Trap
    if args.input_file is None and args.input is None and args.file.endswith(".s"):
        from .testing import metadata
        inp = metadata(args.file)["input"]
    m = Machine32(isa, img, inp=inp)
    syms = {v: k for k, v in img.symbols.items() if "." not in k}
    if args.trace:
        def tr(m):
            try:
                ws = parcels_at(m.parcel, m.pc)
                text, _ = isa.disassemble(ws, m.pc, syms)
            except (SimError32, Trap):
                text = "?"
            name = syms.get(m.pc)
            label = f"{name}:" if name else ""
            print(f"{m.cycles:>9} {m.pc:06X} {label:<10} {text:<34} {m.regs_str()}", file=sys.stderr)
        m.trace = tr
    err = None
    try:
        m.run(max_cycles=args.max_cycles)
    except SimError32 as e:
        err = e
    sys.stdout.flush()
    sys.stdout.buffer.write(bytes(m.dev.out))
    sys.stdout.buffer.flush()
    for pc, what in m.traps[:5]:
        near = max((a for a in syms if a <= pc), default=None)
        where = f" ({syms[near]}+{pc - near:#x})" if near is not None else ""
        print(f"\ntrap at pc {pc:X}{where}: {what}", file=sys.stderr)
    if err is not None:
        print(f"\nerror: {err}", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
        return 1
    if args.stats or args.regs:
        print(f"\n--- halted at {m.pc:X}: {m.instructions} instructions, "
              f"{img.code_bytes()} bytes of code, lowest sp {m.min_sp:X}", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
    if args.stats:
        allc = m.all_cycles()
        print("cycles by configuration (wide fetch: average of the two code alignments):", file=sys.stderr)
        for cfg in timing32.CONFIG_NAMES:
            print(f"  {cfg:<14} {allc[cfg]:>10}  CPI {allc[cfg] / max(1, m.instructions):.2f}",
                  file=sys.stderr)
        from collections import Counter
        import bisect
        ref = timing32.REFERENCE
        pcc = m.pc_cycles(ref)
        total = sum(pcc.values()) or 1
        kinds, kcyc = Counter(), Counter()
        for pc, n in m.pc_counts.items():
            k = isa.kind(parcels_at(m.parcel, pc))
            kinds[k] += n
            kcyc[k] += pcc[pc]
        print(f"instruction mix (count, share, share of {ref} cycles):", file=sys.stderr)
        for k, n in kinds.most_common():
            print(f"  {k:<18} {n:>9}  {100 * n / max(1, m.instructions):5.1f}%"
                  f"  {100 * kcyc[k] / total:5.1f}%", file=sys.stderr)
        labels = sorted((st.addr, st.label) for st in img.stmts
                        if st.kind == "label" and "." not in st.label)
        starts = [a for a, _ in labels]
        per = Counter()
        for pc, cyc in pcc.items():
            if pc is None:
                per["<interrupt entry>"] += cyc
                continue
            i = bisect.bisect_right(starts, pc) - 1
            per[labels[i][1] if i >= 0 else "?"] += cyc
        print(f"cycles by routine ({ref}):", file=sys.stderr)
        for k, c in per.most_common(12):
            print(f"  {k:<24} {c:>10}  {100 * c / total:5.1f}%", file=sys.stderr)
    return 0


def cmd_dis(args):
    isa = isas.get(args.isa)
    if getattr(isa, "WIDE", False):
        with open(args.file, "rb") as f:
            data = f.read() + bytes(6)
        rd = lambda a: data[a] | (data[a + 1] << 8)
        a = int(args.start, 0)
        end = int(args.end, 0) if args.end else len(data) - 6
        while a < end - 1:
            ws = parcels_at(rd, a)
            text, n = isa.disassemble(ws, a)
            print(f"{a:06X}  {' '.join(f'{w:04X}' for w in ws[:n]):<15} {text}")
            a += 2 * n
        return 0
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
    a.add_argument("-c", action="store_true", help="write an object file to link later")
    a.set_defaults(fn=cmd_asm)

    from . import tools
    ld = sub.add_parser("ld", help="link object files into an executable")
    tools.add_ld_arguments(ld)
    ld.set_defaults(fn=tools.cmd_ld)
    od = sub.add_parser("objdump", help="show an object file, executable or library")
    tools.add_objdump_arguments(od)
    od.set_defaults(fn=tools.cmd_objdump)
    ar = sub.add_parser("ar", help="make or list a library of object files")
    tools.add_ar_arguments(ar)
    ar.set_defaults(fn=tools.cmd_ar)

    r = sub.add_parser("run", help="assemble and run on the instruction-level simulator")
    r.add_argument("files", nargs="+", metavar="file",
                   help="a .s file, an executable, or object files to link")
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
    u.add_argument("--doc", action="store_true",
                   help="v1b: write docs/microcode-v1b.md (selected routines) instead")
    u.set_defaults(fn=lambda args: __import__(
        "tmc.hw.ucode_v1b" if args.isa == "v1b" else "tmc.hw.microcode", fromlist=["x"]).cmd_ucode(args))

    b = sub.add_parser("bench", help="instruction-level benchmark table")
    b.add_argument("--markdown", action="store_true")
    b.set_defaults(fn=lambda args: __import__("tmc.testing", fromlist=["x"]).cmd_bench(args))

    an = sub.add_parser("analyze", help="ISA usage statistics over all programs")
    an.set_defaults(fn=lambda args: __import__("tmc.analyze", fromlist=["x"]).main())

    rp = sub.add_parser("report", help="write docs/performance.md")
    rp.add_argument("--hw", action="store_true", help="also run every program on the chip-level simulator")
    rp.add_argument("--jobs", type=int, default=4)
    rp.set_defaults(fn=lambda args: __import__("tmc.report", fromlist=["x"]).main(
        (["--hw"] if args.hw else []) + ["--jobs", str(args.jobs)]))

    r1 = sub.add_parser("report1", help="write docs/performance-v1.md (draft 1a vs 1b)")
    r1.set_defaults(fn=lambda args: __import__("tmc.report1", fromlist=["x"]).main())
    r1b = sub.add_parser("report1b", help="write docs/performance-v1b.md (draft 1b hardware)")
    r1b.add_argument("--hw", action="store_true",
                     help="also run the chip-level simulator (programs and clock sweeps; about an hour)")
    r1b.add_argument("--jobs", type=int, default=4)
    r1b.set_defaults(fn=lambda args: __import__("tmc.report1b", fromlist=["x"]).main(
        (["--hw"] if args.hw else []) + ["--jobs", str(args.jobs)]))

    cc = sub.add_parser("cc", help="compile C for draft 1a/1b (see tmc/cc)")
    __import__("tmc.cc.__main__", fromlist=["x"]).add_arguments(cc)
    cc.set_defaults(fn=lambda args: __import__("tmc.cc.__main__", fromlist=["x"]).run(args, args.isa))

    cb = sub.add_parser("ccbench", help="compiled C against the hand-written programs")
    cb.add_argument("--write", action="store_true", help="write docs/compiler-performance.md")
    cb.set_defaults(fn=lambda args: __import__("tmc.cc.bench", fromlist=["x"]).main(
        ["--write"] if args.write else []))

    h = sub.add_parser("hw", help="chip-level tools")
    h.add_argument("rest", nargs=argparse.REMAINDER)
    h.set_defaults(fn=lambda args: __import__("tmc.hw.cli", fromlist=["x"]).main(args.rest, args.isa))

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
