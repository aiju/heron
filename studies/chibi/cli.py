"""Chibi Heron's command line: heron chibi <command> ...

  check [NAMES]                  the register-transfer model against the
                                 instruction-level simulator (the suite)
  run FILE.s [--profile]         one program on the model
  report [--write]               RFC 0047's performance.md (report.py)
  hw ...                         the chip-level netlist (hw.py)
"""

import argparse
import sys


def cmd_run(args):
    from collections import Counter
    from heron.infra.programs import metadata
    from . import check
    img = check.assemble(args.file)
    meta = metadata(args.file)
    m = check.run_rtl(img, meta["input"], profile=args.profile)
    sys.stdout.write(m.sys.console.out.decode("latin-1"))
    print(f"\n{m.instructions} instructions, {m.cycles} cycles "
          f"(CPI {m.cycles / max(m.instructions, 1):.2f})")
    if args.profile:
        ops = Counter()
        for a, n in m.ucount.items():
            ops[(a >> 17, a >> 5 & 0xFF)] += n
        for (page, op), n in ops.most_common(25):
            print(f"  {n:9d} {100 * n / m.cycles:5.1f}%  page {page} op {op:02X}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron chibi")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("names", nargs="*")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--profile", action="store_true")
    w = sub.add_parser("report")
    w.add_argument("--write", action="store_true")
    h = sub.add_parser("hw")
    h.add_argument("rest", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    if args.cmd == "check":
        from . import check
        return check.cmd_check(args)
    if args.cmd == "report":
        from . import report
        return report.cmd_report(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "hw":
        from . import hw
        return hw.main(args.rest)
    return 2
