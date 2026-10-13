"""Generate docs/performance-v1b.md: the draft 1b hardware implementation.

    python3 -m tmc report1b [--hw] [--jobs N]

Cycle counts come from the register-transfer model (tmc.hw.rtl_v1b), which
runs the real microcode and is checked cycle for cycle against the
chip-level simulator. They are compared with the draft 1 timing model's
estimates (tmc.timing32), per program and per kind of instruction. Clock
speeds come from static timing analysis. With --hw the chip-level simulator
also runs every program at the guaranteed clock and sweeps the clock on the
exercise program for every parts variant and delay corner (about an hour);
the results are cached in build/hw-v1b-results.json for later runs without
--hw.
"""

import json
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from . import asm as asmcore
from . import isa as isas
from . import timing32
from .testing import program_paths, metadata, expected_output, run_program, fmt_time, ROOT

DOC = os.path.join(ROOT, "docs", "performance-v1b.md")
CACHE = os.path.join(ROOT, "build", "hw-v1b-results.json")
MODEL = "D32-separate"
VARIANT_NAMES = {"hct-ls181": "74HCT + 74LS181/74S182", "hct-f181": "74HCT + 74F181/74F182",
                 "act-f181": "74ACT + 74F181/74F182"}

# timing-model kinds -> classes for the tables
CLASSES = [
    ("register ALU, move, compare", {"alu"}),
    ("shift", {"shift"}),
    ("multiply", {"mul"}),
    ("divide", {"div"}),
    ("load", {"ld"}),
    ("ALU op with a memory operand", {"op"}),
    ("store", {"st"}),
    ("LEA", {"lea"}),
    ("branch", {"br"}),
    ("jump", {"jmp", "jmpm"}),
    ("call", {"call", "callm"}),
    ("return", {"ret", "rti"}),
    ("SAVE/RESTORE", {"save", "restore"}),
    ("system, trap, interrupt", {"sys", "trap", "irq"}),
]


def class_of(kind):
    for name, kinds in CLASSES:
        if kind in kinds:
            return name
    return "other"


def geomean(xs):
    xs = [x for x in xs if x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def program_job(path):
    """Run one program on the ISA simulator and the RTL model."""
    from .sim32 import Machine32
    from .hw.rtl_v1b import RTL
    from .hw.check_v1b import compare
    isa = isas.get("v1b")
    meta = metadata(path)
    img = asmcore.assemble_file(isa, path)
    m = Machine32(isa, img, inp=meta["input"])
    m.run(max_cycles=meta["max-cycles"])
    r = RTL(img, inp=meta["input"])
    r.fetch_log = []
    r.run(max_cycles=20 * meta["max-cycles"])
    name = os.path.basename(path)[:-2]
    # hardware cycles per instruction address: from one opcode fetch to the
    # next (an interrupt entry counts towards the instruction it follows)
    hw_pc = Counter()
    log = [f for f in r.fetch_log if f[0] >= 0]
    for (c0, a0, _), (c1, _, _) in zip(log, log[1:]):
        hw_pc[a0] += c1 - c0
    if log:
        hw_pc[log[-1][1]] += r.cycles - log[-1][0]
    model_pc = defaultdict(Counter)       # pc -> config -> cycles
    kind_pc = {}
    count_pc = Counter()
    for (pc, key), n in m.pc_keys.items():
        for c in timing32.CONFIG_NAMES:
            model_pc[pc][c] += n * timing32.cycles(key, c)
        count_pc[pc] += n
        kind_pc.setdefault(pc, key[2])
    return {
        "name": name, "instructions": m.instructions, "hw_cycles": r.cycles,
        "model": {c: m.cycles_avg(c) for c in timing32.CONFIG_NAMES},
        "code_bytes": img.code_bytes(), "irqs": m.irqs,
        "ok": bytes(m.dev.out) == expected_output(name) and not compare(m, r),
        "hw_pc": dict(hw_pc), "model_pc": {pc: dict(v) for pc, v in model_pc.items()},
        "kind_pc": kind_pc, "count_pc": dict(count_pc),
    }


def sta_job(args):
    from .hw import sta
    variant, corner = args
    N, res = sta.analyse(variant, corner, machine="v1b")
    T, _, _, labels = res[0]
    floor = next(t for t, _, _, lab in res if any(l.startswith("NOP") for l in lab))
    hist = Counter(int(t // 20) * 20 for t, _, _, _ in res)
    what = "the fetch" if T - floor < 0.05 else f"`{labels[0]}`"
    return {"variant": variant, "corner": corner, "period": T, "what": what,
            "fetch": floor, "hist": sorted(hist.items())}


def sweep_job(args):
    """Shortest period at which the exercise program still works in the
    chip-level simulator (bisection to 1 ns)."""
    from .hw import cli
    variant, corner, lo, hi = args
    cli.MACHINE = "v1b"
    path = os.path.join(ROOT, "build", "exercise_v1b.s")
    img, m = cli.run_isa(path, b"")
    while hi - lo > 1.0:
        mid = round((lo + hi) / 2, 1)
        ok, _, _ = cli.passes(img, m, b"", mid, variant, corner)
        if ok:
            hi = mid
        else:
            lo = mid
    return {"variant": variant, "corner": corner, "period": hi}


def hw_job(args):
    path, period, variant, corner = args
    from .hw import cli
    cli.MACHINE = "v1b"
    inp = cli.program_input(path)
    img, m = cli.run_isa(path, inp)
    hw = cli.run_hw(img, period, variant, corner, 1, inp, max_cycles=m.cycles + 1000,
                    fetch_trace=200_000)
    diffs = cli.compare(m, hw, check_cycles=m.irqs == 0)
    return {"name": os.path.basename(path)[:-2], "cycles": hw["cycles"], "diffs": diffs,
            "violations": hw["violation_total"], "irqs": m.irqs,
            "contention_max_ns": hw["contention"]["max_ps"] / 1000, "period": period,
            "variant": variant, "corner": corner}


def run_hw(sta_rows, jobs):
    from .hw import check_v1b
    check_v1b.exercise_path()                 # writes build/exercise_v1b.s
    guaranteed = next(r["period"] for r in sta_rows
                      if r["variant"] == "hct-ls181" and r["corner"] == "max")
    period = math.ceil(guaranteed)
    paths = program_paths(None, "v1b")
    with ProcessPoolExecutor(jobs) as ex:
        sweeps = list(ex.map(sweep_job, [(r["variant"], r["corner"], 0.5 * r["period"],
                                          1.2 * r["period"]) for r in sta_rows]))
        suite = list(ex.map(hw_job, [(p, period, "hct-ls181", "max") for p in paths]))
    return {"sweeps": sweeps, "suite": suite}


def v0_baseline():
    """Draft 0 hardware: cycles per program and its worst-case clock."""
    from .hw import sta
    out = {}
    for p in program_paths(None, "v0"):
        r = run_program(p, "v0")
        out[r["name"]] = r["cycles"]
    N, res = sta.analyse("hct-ls181", "max", machine="v0")
    return out, res[0][0]


def microcode_stats():
    from .hw import ucode_v1b as uc
    mc = uc.built()
    return {"words": len(mc.nodes), "slots": 1 << uc.Y_BITS, "bits": uc.CONTROL_BITS,
            "routines": len(mc.entry)}


def report(progs, sta_rows, hw, v0, mstats, args_hw):
    L = []
    L.append("# Performance of the draft 1b hardware implementation")
    L.append("")
    L.append("Generated by `python3 -m tmc report1b" + (" --hw" if args_hw else "") +
             "`; don't edit by hand. The design is described in [hardware-v1b.md](hardware-v1b.md).")
    L.append("")

    # ---- clock speed
    L.append("## Clock speed")
    L.append("")
    L.append("Minimum clock period from static timing analysis over every distinct microinstruction "
             "(guaranteed for all data values). *Worst case* uses datasheet maximum delays "
             "(−40…85 °C, 4.5 V, 50 pF); *typical* uses 25 °C typical delays where datasheets give "
             "them (memories only have maximum access times). *Fetch* is the period the "
             "instruction fetch alone needs (RAM, decode ROM and microcode ROM in a row): no "
             "microinstruction can be faster.")
    L.append("")
    sweeps = {(s["variant"], s["corner"]): s["period"] for s in (hw or {}).get("sweeps", [])}
    head = "| Parts | Delays | Period | Clock | Slowest microinstruction | Fetch |"
    if sweeps:
        head += " Simulation |"
    L.append(head)
    L.append("|---|---|---:|---:|---|---:|" + ("---:|" if sweeps else ""))
    for r in sta_rows:
        row = (f"| {VARIANT_NAMES[r['variant']]} | {'worst case' if r['corner'] == 'max' else 'typical'} "
               f"| {r['period']:.0f} ns | {1000 / r['period']:.2f} MHz | {r['what']} "
               f"| {r['fetch']:.0f} ns |")
        if sweeps:
            sp = sweeps.get((r["variant"], r["corner"]))
            row += f" {sp:.0f} ns |" if sp else " |"
        L.append(row)
    L.append("")
    if sweeps:
        L.append("*Simulation* is the shortest period at which the exercise program "
                 "(`tests/hw/exercise_v1b.py`: every instruction, mode and trap) still runs correctly in "
                 "the event-driven chip simulation, to the nearest nanosecond.")
        L.append("")
    worst = next(r for r in sta_rows if r["variant"] == "hct-ls181" and r["corner"] == "max")
    L.append(f"Required periods of all microinstructions ({VARIANT_NAMES['hct-ls181']}, worst case):")
    L.append("")
    L.append("| Period | Microinstructions |")
    L.append("|---|---:|")
    for lo, n in worst["hist"]:
        L.append(f"| {lo}–{lo + 19} ns | {n:,} |")
    L.append("")

    # ---- programs
    clock = 1e9 / worst["period"]
    typ = next(r for r in sta_rows if r["variant"] == "hct-ls181" and r["corner"] == "typ")
    act = next(r for r in sta_rows if r["variant"] == "act-f181" and r["corner"] == "max")
    clocks = [("HCT+LS181 worst", clock), ("HCT+LS181 typ", 1e9 / typ["period"]),
              ("ACT+F181 worst", 1e9 / act["period"])]
    suite = {h["name"]: h for h in (hw or {}).get("suite", [])}
    L.append("## Programs")
    L.append("")
    L.append("Cycles are exact for this implementation: they come from the register-transfer model "
             "running the microcode, and the chip-level simulator agrees cycle for cycle "
             "(last column). *Model* is the draft 1 timing model's estimate for the same "
             f"configuration ({MODEL}: 32-bit datapath, separate fetch cycle), from "
             "[performance-v1.md](performance-v1.md). `interrupts` spends most of its time "
             "halted, waiting for timer interrupts, which the hardware's count includes and the "
             "model's doesn't, so it's left out of the comparisons.")
    L.append("")
    head = ("| Program | Instructions | Cycles | CPI | Model | Cycles / model | "
            + " | ".join(c for c, _ in clocks) + " |")
    if suite:
        head += " Chip-level check |"
    L.append(head)
    L.append("|---|---:|---:|---:|---:|---:|" + "---:|" * len(clocks) + ("---|" if suite else ""))
    tot_i = tot_c = tot_m = 0
    for p in progs:
        tot_i += p["instructions"]
        tot_c += p["hw_cycles"]
        tot_m += p["model"][MODEL]
        ratio = "–" if p["irqs"] else f"{p['hw_cycles'] / p['model'][MODEL]:.2f}"
        row = (f"| {p['name']} | {p['instructions']:,} | {p['hw_cycles']:,} | "
               f"{p['hw_cycles'] / p['instructions']:.2f} | {p['model'][MODEL]:,.0f} | "
               f"{ratio} | "
               + " | ".join(fmt_time(p["hw_cycles"] / hz) for _, hz in clocks) + " |")
        if suite:
            h = suite.get(p["name"])
            if h is None:
                check = "not run"
            elif h["diffs"] or h["violations"]:
                check = f"**FAIL** ({len(h['diffs'])} differences, {h['violations']} violations)"
            elif h["irqs"]:
                check = "matches (results; uses interrupts)"
            else:
                check = "matches, cycle-exact"
            row += f" {check} |"
        L.append(row)
    compared = [p for p in progs if p["name"] != "hello" and not p["irqs"]]
    g = geomean([p["hw_cycles"] / p["model"][MODEL] for p in compared])
    cc = sum(p["hw_cycles"] for p in compared)
    cm = sum(p["model"][MODEL] for p in compared)
    L.append(f"| **total** | {tot_i:,} | {tot_c:,} | {tot_c / tot_i:.2f} | {tot_m:,.0f} | "
             f"{cc / cm:.2f} | " + " | ".join(fmt_time(tot_c / hz) for _, hz in clocks)
             + " |" + (" |" if suite else ""))
    L.append("")
    L.append(f"Geometric mean of cycles / model over the programs (without `hello` and "
             f"`interrupts`): **{g:.3f}**.")
    L.append("")
    others = [c for c in timing32.CONFIG_NAMES if c.startswith("D32")]
    L.append("The same programs against all three 32-bit configurations of the model "
             "(geometric mean of hardware cycles / estimate):")
    L.append("")
    L.append("| " + " | ".join(others) + " |")
    L.append("|" + "---:|" * len(others))
    L.append("| " + " | ".join(
        f"{geomean([p['hw_cycles'] / p['model'][c] for p in compared]):.3f}"
        for c in others) + " |")
    L.append("")
    if suite:
        h0 = next(iter(suite.values()))
        worst_cont = max(h["contention_max_ns"] for h in suite.values())
        L.append(f"Chip-level runs: every program at {h0['period']:.0f} ns "
                 f"({1000 / h0['period']:.2f} MHz) with worst-case delays ({h0['variant']}), comparing "
                 "console output, registers, flags, PC, all of RAM and (for programs without "
                 "interrupts) the cycle of every instruction fetch with the instruction-level "
                 f"simulator and the RTL model's cycle counts. Longest bus contention seen: "
                 f"{worst_cont:.0f} ns (see [hardware-v1b.md](hardware-v1b.md#known-issues-and-what-a-second-iteration-would-change)).")
        L.append("")

    # ---- per class
    L.append("## Where the hardware and the model differ")
    L.append("")
    L.append("Cycles per instruction by kind of instruction, pooled over all programs except "
             f"`interrupts`: what the hardware takes and what the model ({MODEL}) estimated. "
             "Hardware cycles are counted from one opcode fetch to the next.")
    L.append("")
    cnt, hwc, mdc = Counter(), Counter(), Counter()
    for p in progs:
        if p["irqs"]:
            continue
        for pc, kind in p["kind_pc"].items():
            if pc is None:
                continue
            cl = class_of(kind)
            cnt[cl] += p["count_pc"][pc]
            hwc[cl] += p["hw_pc"].get(pc, 0)
            mdc[cl] += p["model_pc"][pc][MODEL]
    total_n, total_hw = sum(cnt.values()), sum(hwc.values())
    L.append("| Kind | Share of instructions | Share of cycles | CPI | Model CPI | Difference |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for cl, _ in sorted(hwc.items(), key=lambda kv: -kv[1]):
        n = cnt[cl]
        L.append(f"| {cl} | {100 * n / total_n:.1f}% | {100 * hwc[cl] / total_hw:.1f}% | "
                 f"{hwc[cl] / n:.2f} | {mdc[cl] / n:.2f} | {(hwc[cl] - mdc[cl]) / n:+.2f} |")
    L.append("")

    # ---- against draft 0
    v0c, v0T = v0
    common = [p for p in progs if p["name"] in v0c and p["name"] != "hello" and not p["irqs"]]
    if common:
        L.append("## Against the draft 0 hardware")
        L.append("")
        L.append(f"Both at their worst-case clocks with 74HCT and 74LS181: draft 0 at {v0T:.0f} ns "
                 f"({1000 / v0T:.2f} MHz), draft 1b at {worst['period']:.0f} ns. The programs "
                 "compute the same things, written for each ISA (`interrupts` is left out: its "
                 "run time is set by its timer).")
        L.append("")
        L.append("| Program | Draft 0 cycles | Draft 1b cycles | Cycles, 0 / 1b | Draft 0 time | "
                 "Draft 1b time | Speed-up |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        sp = []
        for p in common:
            t0 = v0c[p["name"]] * v0T * 1e-9
            t1 = p["hw_cycles"] / clock
            sp.append(t0 / t1)
            L.append(f"| {p['name']} | {v0c[p['name']]:,} | {p['hw_cycles']:,} | "
                     f"{v0c[p['name']] / p['hw_cycles']:.2f} | {fmt_time(v0c[p['name']] * v0T * 1e-9)} | "
                     f"{fmt_time(t1)} | {t0 / t1:.2f}× |")
        L.append(f"| **geometric mean** | | | "
                 f"{geomean([v0c[p['name']] / p['hw_cycles'] for p in common]):.2f} | | | "
                 f"**{geomean(sp):.2f}×** |")
        L.append("")

    L.append("## Microcode")
    L.append("")
    L.append(f"{mstats['words']:,} microinstructions in {mstats['slots']:,} slots "
             f"({mstats['bits']}-bit words), {mstats['routines']:,} entry routines chosen by the decode ROM.")
    L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="tmc report1b")
    ap.add_argument("--hw", action="store_true",
                    help="also run the chip-level simulator (programs and clock sweeps; about an hour)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=DOC)
    args = ap.parse_args(argv)

    from .hw import chips
    paths = program_paths(None, "v1b")
    combos = [(v, c) for v in chips.VARIANTS for c in ("max", "typ")]
    with ProcessPoolExecutor(args.jobs) as ex:
        progs = list(ex.map(program_job, paths))
        sta_rows = list(ex.map(sta_job, combos))
    bad = [p["name"] for p in progs if not p["ok"]]
    if bad:
        print(f"warning: programs failing on the RTL model: {bad}", file=sys.stderr)

    hw = None
    if args.hw:
        hw = run_hw(sta_rows, args.jobs)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump(hw, f, indent=1)
    elif os.path.exists(CACHE):
        with open(CACHE) as f:
            hw = json.load(f)
    text = report(progs, sta_rows, hw, v0_baseline(), microcode_stats(), args.hw)
    with open(args.out, "w") as f:
        f.write(text)
    print(f"wrote {args.out}")
    return 0
