"""Draft 2's command line: heron v2_isa <command> ...

  asm     FILE.s [-o FILE.bin] [-l FILE.lst]   assemble
  asm     -c FILE.s [-o FILE.o]                assemble into an object file
  ld      FILE.o... [-o PROG.out]              link (see heron.infra.link)
  objdump FILE.o [-d]                          show an object file, executable or library
  ar      -o LIB.a FILE.o... | -t LIB.a        make a library, or list one
  run     FILE.s [--input TEXT] [--trace] [--stats]   (or an executable, or object files)
  dis     FILE.bin [--from ADDR] [--to ADDR]   disassemble a binary image
  test    [NAME...]                            the program suite against its expected output
  bench   [--markdown]                         instructions, cycles and run times per program

The commands are draft 1's (heron v1_isa), for draft 2 only.

run takes console input from a .s file's `;! input:` line unless --input or
--input-file is given. It exits with 1 unless the program halts normally:
on a simulator error, at the cycle limit, or when it halts in a trap handler.
"""

import argparse
import sys

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import halt_status

ISA = "v2"


def cmd_asm(args):
    from heron.infra.objtools import assemble_object, write_binary
    isa = isas.get(ISA)
    if args.c:
        try:
            o = assemble_object(ISA, args.file)
        except (asmcore.AsmError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for w in o.warnings:
            print(f"warning: {w}", file=sys.stderr)
        o.write(args.o or args.file.rsplit(".", 1)[0] + ".o")
        return 0
    try:
        img = asmcore.assemble_file(isa, args.file)
    except (asmcore.AsmError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in img.warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = args.o or args.file.rsplit(".", 1)[0] + ".bin"
    write_binary(img, isa, out)
    if args.l:
        with open(args.l, "w") as f:
            f.write(img.listing())
    lo, hi = img.extent()
    print(f"{args.file}: {img.code_bytes()} bytes of code, image {lo:04X}-{hi - 1:04X} -> {out}")
    return 0


def parcels_at(read, pc, n=3):
    return [read(pc + 2 * i) for i in range(n)]


def cmd_run(args):
    from heron.infra.link import LinkError
    from heron.infra.obj import ObjError
    from heron.infra.objtools import load_program
    try:
        img, _ = load_program(ISA, args.files, ISA)
    except (asmcore.AsmError, LinkError, ObjError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    path = args.files[0]
    if args.input_file:
        with open(args.input_file, "rb") as f:
            inp = f.read()
    elif args.input is not None:
        inp = args.input.encode().decode("unicode_escape").encode("latin-1")
    elif path.endswith(".s"):
        from heron.infra.programs import metadata
        inp = metadata(path)["input"]      # the program's own ;! input: line, if any
    else:
        inp = b""
    return run(args, img, inp)


def run(args, img, inp):
    from collections import Counter
    import bisect
    from . import sim
    isa = isas.get(ISA)
    m = sim.Machine(img, inp=inp)
    syms = {v: k for k, v in img.symbols.items() if "." not in k}
    if args.trace:
        def tr(m):
            try:
                ws = parcels_at(m.parcel, m.pc)
                text, _ = isa.disassemble(ws, m.pc, syms)
            except sim.SimError:
                text = "?"
            name = syms.get(m.pc)
            label = f"{name}:" if name else ""
            print(f"{m.cycles:>9} {m.pc:06X} {label:<10} {text:<34} {m.regs_str()}", file=sys.stderr)
        m.trace = tr
    err = None
    try:
        m.run(max_cycles=args.max_cycles)
    except sim.SimError as e:
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
    status = halt_status(m)
    if args.stats or args.regs:
        print(f"\n--- halted at {m.pc:X}: {m.instructions} instructions, "
              f"{img.code_bytes()} bytes of code, lowest sp {m.min_sp:X}", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
    if args.stats:
        allc = m.all_cycles()
        print("cycles by configuration (wide fetch: average of the two code alignments):", file=sys.stderr)
        for cfg in sim.CONFIG_NAMES:
            print(f"  {cfg:<14} {allc[cfg]:>10}  CPI {allc[cfg] / max(1, m.instructions):.2f}",
                  file=sys.stderr)
        ref = sim.REFERENCE
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
    return status


def cmd_dis(args):
    isa = isas.get(ISA)
    with open(args.file, "rb") as f:
        data = f.read() + bytes(6)
    rd = lambda a: data[a] | (data[a + 1] << 8)
    a = int(args.start, 0)
    end = int(args.end, 0) if args.end else len(data) - 6
    while a < end - 1:
        ws = parcels_at(rd, a)
        text, n = isa.disassemble(ws, a)
        print(f"{a:06X}  {isa.hex_parcels(ws[:n]):<15} {text}")
        a += 2 * n
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron v2_isa", description="Draft 2 (RFC 0028)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("asm", help="assemble a source file")
    a.add_argument("file")
    a.add_argument("-o")
    a.add_argument("-l", help="write a listing")
    a.add_argument("-c", action="store_true", help="write an object file to link later")
    a.set_defaults(fn=cmd_asm)

    from heron.infra import objtools as tools
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
    r.add_argument("--input", help="console input (escapes allowed; default: the program's "
                                   "';! input:' line)")
    r.add_argument("--input-file")
    r.add_argument("--trace", action="store_true")
    r.add_argument("--stats", action="store_true")
    r.add_argument("--regs", action="store_true")
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
    t.set_defaults(fn=lambda args: __import__("heron.studies.v2_isa.testing", fromlist=["x"]).cmd_test(args))

    b = sub.add_parser("bench", help="instruction-level benchmark table")
    b.add_argument("--markdown", action="store_true")
    b.set_defaults(fn=lambda args: __import__("heron.studies.v2_isa.testing", fromlist=["x"]).cmd_bench(args))

    args = p.parse_args(argv)
    # ld takes the ISA from the object files; this one is the only one
    args.isa, args.isa_given = ISA, True
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
