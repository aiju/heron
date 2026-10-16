"""Other instruction sets on the draft 2 CPU: heron v2_guests <command> ...

  run ISA PROGRAM [--lockstep] [--profile]
                          one program on the RTL model with ISA's microcode:
                          output, cycles, time (--lockstep: against the
                          reference interpreter after every instruction;
                          --profile: the busiest routines)
  test ISA [PROGRAMS]     programs against their expected output
  ucode ISA [--list]      the microcode's size (--list: every word)
  bench [ISAS] [--write]  every guest's programs: time against native draft 2
"""

import argparse
import importlib
import sys
import time
from collections import Counter

# isa: (microcode module, reference interpreter "module.Class", programs module)
GUESTS = {
    "rv32": ("rv32", "rv32_ref.RV32", "toolchain"),
    "m6502": ("m6502", "m6502_ref.M6502", "m6502_progs"),
    "thumb": ("thumb", "thumb_ref.Thumb", "toolchain"),
    "v1b": ("v1b", "v1b_progs.V1bRef", "v1b_progs"),
}


def guest_module(isa):
    return importlib.import_module(f"heron.studies.v2_guests.{GUESTS[isa][0]}")


def reference(isa):
    mod, cls = GUESTS[isa][1].split(".")
    return getattr(importlib.import_module(f"heron.studies.v2_guests.{mod}"), cls)


def programs(isa):
    """The guest's programs: {name: callable returning (image, input,
    expected output or None)}."""
    mod = importlib.import_module(f"heron.studies.v2_guests.{GUESTS[isa][2]}")
    return mod.guest_programs(isa)


def compare_state(a, b):
    diffs = []
    for k in a:
        va, vb = a[k], b[k]
        if isinstance(va, list):
            for i, (x, y) in enumerate(zip(va, vb)):
                if x != y:
                    diffs.append(f"{k}{i}: RTL {x:08X} ref {y:08X}")
        elif va != vb:
            diffs.append(f"{k}: RTL {va:X} ref {vb:X}")
    return diffs


def run(isa, name, lockstep=False, profile=False, max_cycles=200_000_000):
    """Run one program; returns a result dict."""
    from . import guest as gm
    mod = guest_module(isa)
    mc = mod.built()
    image, inp, exp = programs(isa)[name]()
    r = gm.Run(mc, image, inp, profile=profile)
    trace = None
    info = {"lockstep": None}
    if lockstep and name in getattr(mc.guest, "no_lockstep", ()):
        lockstep = False    # interrupts arrive at other instructions than in the reference
    if lockstep:
        ref = reference(isa)(image, inp)
        g = mc.guest
        last = [None]

        def trace(m):
            if info["lockstep"]:
                return
            d = compare_state(g.state(m), ref.state())
            if d:
                info["lockstep"] = (f"after {ref.instructions} instructions (the last at "
                                    f"{last[0]:X}): " + "; ".join(d[:6]))
                m.halted = True
                return
            last[0] = ref.state()["pc"]
            ref.step()
    if trace is None and hasattr(mc.guest, "pc"):
        g = mc.guest
        prev = [None]

        def trace(m):
            pc = g.pc(m)
            if pc == prev[0]:
                info["lockstep"] = f"trapped at {pc:04X}"
                m.halted = True
            prev[0] = pc
    t0 = time.time()
    r.run(max_cycles=max_cycles, trace=trace)
    m = r.m
    res = {"isa": isa, "name": name, "error": r.error or info["lockstep"],
           "out": m.out, "expected": exp, "instructions": m.instructions, "cycles": m.cycles,
           "ticks": m.ticks, "ms": m.ticks * 20 / 1e6, "reset_cycles": r.reset_cycles,
           "seconds": time.time() - t0, "ucount": m.ucount, "mc": mc}
    res["ok"] = res["error"] is None and (exp is None or m.out == exp)
    return res


def show(res, verbose=True):
    status = "ok" if res["ok"] else "FAIL"
    cpi = res["cycles"] / max(1, res["instructions"])
    line = (f"{res['name']:10s} {status:4s} {res['instructions']:9d} instr {res['cycles']:10d} "
            f"cycles  CPI {cpi:5.2f}  {res['ms']:8.2f} ms  ({res['seconds']:.0f} s)")
    print(line)
    if not res["ok"] and verbose:
        if res["error"]:
            print("   ", res["error"])
        if res["expected"] is not None and res["out"] != res["expected"]:
            print(f"    output {res['out'][:120]!r}\n    wanted {res['expected'][:120]!r}")


def profile_table(res, n=25):
    mc = res["mc"]
    names = Counter()
    for a, c in res["ucount"].items():
        node = mc.by_addr.get(a)
        names[node.name if node else f"{a:04X}"] += c
    total = res["cycles"]
    for name, c in names.most_common(n):
        print(f"  {c:9d} {100 * c / total:5.1f}%  {name}")


def cmd_run(args):
    res = run(args.isa, args.program, lockstep=args.lockstep, profile=args.profile)
    sys.stdout.write(res["out"].decode("latin-1"))
    print()
    show(res)
    print(f"reset routine: {res['reset_cycles']} cycles")
    if args.profile:
        profile_table(res)
    return 0 if res["ok"] else 1


def cmd_test(args):
    names = args.programs or sorted(programs(args.isa))
    bad = 0
    for name in names:
        res = run(args.isa, name, lockstep=args.lockstep)
        show(res)
        bad += not res["ok"]
    return 1 if bad else 0


def cmd_ucode(args):
    from heron.studies.v2_hw import ucode as uc
    mc = guest_module(args.isa).built()
    print(mc.summary())
    print("microinstructions by ticks needed:", dict(sorted(Counter(mc.ticks.values()).items())))
    print(f"estimated (not in ticks.json): {len(mc.estimated)}")
    if args.list:
        for n in sorted(mc.nodes, key=lambda n: n.addr):
            print(f"{n.addr:04X} {mc.ticks[n.addr]:2d} {n.name:24s} {uc.explain(mc.word(n))}")
    return 0


def cmd_bench(args):
    from . import bench
    return bench.main(args.isas or list(GUESTS), write=args.write)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(prog="heron v2_guests",
                                description="Other instruction sets on the draft 2 CPU")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="one program on the RTL model")
    r.add_argument("isa", choices=sorted(GUESTS))
    r.add_argument("program")
    r.add_argument("--lockstep", action="store_true")
    r.add_argument("--profile", action="store_true")
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("test", help="programs against their expected output")
    t.add_argument("isa", choices=sorted(GUESTS))
    t.add_argument("programs", nargs="*")
    t.add_argument("--lockstep", action="store_true")
    t.set_defaults(fn=cmd_test)
    u = sub.add_parser("ucode", help="the microcode")
    u.add_argument("isa", choices=sorted(GUESTS))
    u.add_argument("--list", action="store_true")
    u.set_defaults(fn=cmd_ucode)
    b = sub.add_parser("bench", help="every guest's programs against native draft 2")
    b.add_argument("isas", nargs="*")
    b.add_argument("--write", action="store_true")
    b.set_defaults(fn=cmd_bench)
    args = p.parse_args(argv)
    return args.fn(args) or 0
