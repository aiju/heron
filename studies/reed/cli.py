"""Reed's command line: heron reed <command> ...

  boards             each board's packages, area and parts
  check              build the whole machine and check it: the netlist's
                     own checks, and each control line driven by its board
                     alone
  estimate           a rough time an instruction (estimate.py): front ends
                     and cycle lengths on the napkin's mix, not a measurement
  ucode              the microcode's listing (ucode.py)
  hw smoke [--trace A:B]
                     the whole machine at chip level running a small program
                     (hw.py), against the draft 2 simulator
  hw check           programs at both corners (max, min) and three seeds,
                     with the wires: the chip-level gate
  hw lockstep        the cycle-level model (model.py) against the chip level,
                     its µPC and PC every cycle
  fuzz [FAMILY...] [--n N] [--seed S]
                     random instructions of each family on the model against
                     draft 2's simulator (fuzz.py)
  sta [--word W]     static timing of each kind of microcycle (sta.WORDS):
                     the shortest length at which nothing a length can fix
                     fails worse than at the longest, and what still fails
                     (--no-wires: sta.py)
"""

import argparse

from . import system


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron reed", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("boards")
    sub.add_parser("check")
    sub.add_parser("estimate")
    sub.add_parser("ucode")
    h = sub.add_parser("hw")
    h.add_argument("what", choices=("smoke", "check", "lockstep"))
    h.add_argument("--trace")
    z = sub.add_parser("fuzz")
    z.add_argument("families", nargs="*")
    z.add_argument("--n", type=int, default=200)
    z.add_argument("--seed", type=int, default=1)
    q = sub.add_parser("sta")
    q.add_argument("--word")
    q.add_argument("--paths", type=int, default=2)
    q.add_argument("--no-wires", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "boards":
        print(system.report())
    elif a.cmd == "check":
        nl = system.machine(sim=True)
        system.check(nl)
        print(f"ok: {len(nl.instances)} instances, every control line driven by its board alone")
    elif a.cmd == "ucode":
        from . import ucode
        print(ucode.listing())
    elif a.cmd == "hw":
        from . import hw
        if a.what == "check":
            ok, lines = hw.check()
            print("\n".join(lines))
            return 0 if ok else 1
        if a.what == "lockstep":
            res = hw.lockstep()
            for name, n, bad in res:
                print(f"{name:<10} {n} cycles, {len(bad)} differ" + (f" (the first {bad[0]})" if bad else ""))
            return 0 if all(not b for _, _, b in res) else 1
        trace = tuple(int(x) for x in a.trace.split(":")) if a.trace else None
        ok, rep = hw.smoke(trace)
        print(rep)
        return 0 if ok else 1
    elif a.cmd == "fuzz":
        from . import fuzz
        fuzz.main(a.families or None, a.n, a.seed)
    elif a.cmd == "estimate":
        from . import estimate
        estimate.main()
    elif a.cmd == "sta":
        from . import sta
        sta.main(a.word, a.paths, not a.no_wires)
    return 0
