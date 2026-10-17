"""The IOP's card at chip level (card.py), on the chip-level simulator
(infra/hwsim), checked against the microinstruction-level model (sim/):
every E2, the microaddress uIR takes and the bus clock it takes it at,
must be the model's.

    heron iop hw run [--ms N] [--seed S]   power up, print what the console prints
    heron iop hw test [--ms N]             the same, against the model, clock for clock
    heron iop hw bom                       the parts

Both start from the microcode's quick build (build.py's `quick`: the
SRAM's self test only of its top cells), with the SRAMs holding what the
model's hold at power-up, so that a run is the model's from the first
clock.
"""

import argparse
import glob
import json
import os
import sys

from heron import BUILD, native
from heron.infra.hw import runner

from . import build as bld, card
from .run import Session

OUT = os.path.join(BUILD, "iop")
HERE = os.path.dirname(os.path.abspath(__file__))
UPC = [f"UPC{i}" for i in range(16)]


def sources():
    from heron.studies.v2_hw import parts
    return runner.infra_sources() + [os.path.join(HERE, "card.py"), parts.__file__]


def netlist():
    """The simulation netlist, exported (cached in build/iop)."""
    path = os.path.join(OUT, "netlist.json")
    if not os.path.exists(path) or os.path.getmtime(path) < runner.newest(sources()):
        os.makedirs(OUT, exist_ok=True)
        nl = card.build(sim=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=card.VARIANT, corner="max"), f)
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


def model(b, inp=b""):
    """The model, powered up on the same build, logging its E2s."""
    s = Session(b)
    s.s.log_start()
    if inp:
        s.s.uart_send(inp)
    return s


def preloads(b, s, inp=b""):
    """The chips' contents at the end of reset: the microcode ROMs, the
    image flash, the SRAM and the shared RAM as the model's power up, and
    what the console's terminal types."""
    pre = {}
    rom = b.ucode_bytes()
    for k in range(6):
        pre[f"U_UC{k}"] = bytes(rom[k::6])
    flash = b.flash[:2 << 17]
    pre["U_FL0"], pre["U_FL1"] = bytes(flash[0::2]), bytes(flash[1::2])
    sram = s.s.sram(0, 0x10000)
    pre["U_RAML"] = bytes(h & 0xFF for h in sram)
    pre["U_RAMH"] = bytes(h >> 8 for h in sram)
    shared = s.s.shared(0, 1 << 20)
    for k in range(2):
        half = shared[k << 19:(k + 1) << 19]
        pre[f"U_SR{k}L"] = bytes(h & 0xFF for h in half)
        pre[f"U_SR{k}H"] = bytes(h >> 8 for h in half)
    pre["U_UART"] = bytes(inp)
    return pre


def config(max_cycles, fetch_trace, seed=1, trace=None):
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "clock_net": "BCLK", "reset_net": "RESET_n",
        "fetch_net": "E2EN", "fetch_level": 1,
        "addr_nets": UPC, "data_nets": card.ACQ,
        "fetch_trace": fetch_trace,
        "dump": ["U_UART", "U_RAML", "U_RAMH"],
        "observe": [f"LED{i}" for i in range(8)],
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses={
            "UPC": UPC, "R": card.R, "T": card.T, "AC": card.ACQ, "X": card.XQ,
            "PH": ["PH", "E1EN", "E2EN", "STALL1", "STALL2"],
            "IO": ["STB", "HLD", "IOREQ", "IODONE"], "CNT": [f"CNT{i}" for i in range(8)],
            "IOD": card.IOD})
    return cfg


def run(b, ms, inp=b"", seed=1, fetch_trace=0, s=None, trace=None):
    """Power up the card and run it for `ms` of simulated time."""
    s = s or model(b, inp)
    cycles = int(ms * 1e9 / card.BCLK_PS)
    hw = native.hwsim.run_system(netlist(), config(cycles, fetch_trace, seed, trace),
                                 preloads(b, s, inp))
    hw["output"] = bytes(hw["dumps"]["U_UART"])
    return hw


def compare(hw, ref):
    """The first E2 where the card and the model differ, or None: (index,
    the card's (clock, address, AC), the model's), clocks from the first
    E2. The card's AC is the one before the edge, so the model's from the
    E2 before."""
    got = hw["fetches"]
    if not got or not ref:
        return (0, got[:1], ref[:1])
    c0, r0 = got[0][0], ref[0][0]
    same = False                # AC powers up anything: from when it first agrees
    for i, ((c, a, ac), (rc, ra, _)) in enumerate(zip(got, ref)):
        rac = ref[i - 1][2] if i else None
        same = same or ac == rac
        if (c - c0, a) != (rc - r0, ra) or (same and ac != rac):
            return (i, (c - c0, a, hex(ac)), (rc - r0, ra, rac and hex(rac)))
    return None


def check(ms=2.0, inp=b"", seed=1, quiet=False):
    """Run the card and the model for `ms`; (the outcome, the first
    difference or None, E2s compared)."""
    b = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
    s = model(b, inp)
    hw = run(b, ms, inp, seed, fetch_trace=10_000_000, s=s)
    s.run_ms(ms)
    ref = s.s.log_take()
    n = min(len(hw["fetches"]), len(ref))
    hw["model_output"] = s.out
    return hw, compare(hw, ref[:n]), n


def where(b, a):
    return b.mc.where(a)


def report(hw):
    print(f"{hw['cycles']:,} clocks, {hw['fetch_count']:,} microinstructions, {hw['events']:,} events, "
          f"{hw['wall_seconds']:.1f} s ({hw['reason']})")
    print(f"timing violations: {hw['violation_total']}")
    for v in hw["violation_summary"][:12]:
        print(f"  {v['count']:6} x {v['what']} (worst slack {v['worst_slack_ps']} ps)")
    c = hw["contention"]
    print(f"bus contention: {c['count']} episodes, the longest {c['max_ps']} ps")


def main(argv):
    p = argparse.ArgumentParser(prog="heron iop hw")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--ms", type=float, default=30.0)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--type", default="", help="what the console's terminal types")
    t = sub.add_parser("test")
    t.add_argument("--ms", type=float, default=2.0)
    t.add_argument("--seed", type=int, default=1)
    sub.add_parser("bom")
    a = p.parse_args(argv)
    if a.cmd == "run":
        b = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
        hw = run(b, a.ms, a.type.encode().replace(b"\\r", b"\r"), a.seed)
        sys.stdout.write(hw["output"].decode("latin-1"))
        print()
        report(hw)
    elif a.cmd == "test":
        hw, diff, n = check(a.ms, seed=a.seed)
        report(hw)
        b = bld.Build(bld.DEFAULT_PROGRAM, quick=True)
        if diff:
            i, got, want = diff
            print(f"E2 {i} of {n}: the card {got}, the model {want}")
            if got and want:
                print(f"  the card at {where(b, got[1])}, the model at {where(b, want[1])}")
            return 1
        print(f"the same as the model for {n:,} microinstructions")
        print(f"console: card {hw['output']!r}, model {hw['model_output']!r}")
        return 0
    elif a.cmd == "bom":
        nl = card.build()
        pk = nl.packages(card.VARIANT)
        total = 0
        for part, refs in sorted(pk.items()):
            print(f"{len(refs):4}  {part}")
            total += len(refs)
        print(f"{total:4}  in all")
        print("substitutes:")
        for want, used in card.SUBSTITUTES:
            print(f"  {want}: {used}")
    return 0
