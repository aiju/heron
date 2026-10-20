"""Chibi Heron's measurements, as RFC 0047's performance.md has them: the
program suite on the two-halves machine's model (rtl2.py), each
microinstruction as long as static timing analysis's ticks table says
(ticks.json), against the full Heron's times (RFC 0031's performance.md)
and the first cut's (one cycle of 158.9 ns); where the time goes by
instruction; the parts; and static timing analysis of the netlist.

  heron chibi report [--write]
"""

import os
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from heron import ROOT

from . import check

DOC = os.path.join(ROOT, "reports", "0047-rfc-chibi-heron")
FULL = os.path.join(ROOT, "reports", "0031-rfc-draft-2-cpu", "performance.md")
# not compared, as RFC 0031 has it: hello does no work, and interrupts'
# timer counts cycles
SKIP = ("hello", "interrupts")
TICK_NS = 1e3 / 50.35
FIRST_NS = 158.9                # the first cut's cycle, four of VGA's pixels


def mnemonic(parcels):
    from heron.studies.v2_isa import v2
    text = v2.disassemble(parcels)[0]
    return "illegal" if text.startswith(".half") else text.split()[0]


def run_one(path):
    """(name, instructions, ticks, microinstructions, {mnemonic: (count,
    ticks)}, the first cut's cycles, the model's differences from the
    simulator)."""
    import heron.studies.v2_isa  # noqa: F401
    from heron.infra.programs import metadata
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    img = check.assemble(path)
    ref = check.run_isa(img, meta["input"])
    m = check.run_rtl(img, meta["input"], max_cycles=40 * ref.cycles + 100_000, log=True)
    diffs = check.compare(ref, m) if name not in check.TIMED else []
    first = check.run_rtl(img, meta["input"], max_cycles=40 * ref.cycles + 100_000, first=True)
    by = {}
    ram = m.sys.ram
    ds = list(zip(m.decodes, m.decode_ticks)) + [((None, None, None), m.ticks)]
    for ((_c, pc, md), t0), (_d, t1) in zip(ds, ds[1:]):
        ext = [ram[(pc + k) % len(ram)] | ram[(pc + k + 1) % len(ram)] << 8 for k in (2, 4)]
        k = mnemonic([md] + ext)
        n, t = by.get(k, (0, 0))
        by[k] = (n + 1, t + t1 - t0)
    return name, m.instructions, m.ticks, m.cycles, by, first.cycles, diffs


def full_heron():
    """{program: ms} from RFC 0031's table of the suite."""
    out = {}
    if not os.path.exists(FULL):
        return out
    with open(FULL) as f:
        for line in f:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) > 4 and cells[4].endswith(" ms"):
                name = re.sub(r" \(.*\)$", "", cells[0])
                if "/" not in name and not name.startswith("**"):
                    out[name] = float(cells[4][:-3])
    return out


def table(header, rows, right=()):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---:" if i in right else "---" for i in range(len(header))) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def suite_section(runs):
    full = full_heron()
    rows, tot = [], [0, 0, 0, 0.0, 0.0, 0.0]
    for name, ins, ticks, uops, _by, first, diffs in runs:
        ms = ticks * TICK_NS / 1e6
        fms = first * FIRST_NS / 1e6
        f = full.get(name)
        slower = f"{ms / f:.1f}x" if f and name not in SKIP else ""
        note = " (fails)" if diffs else ""
        rows.append([name + note, ins, uops, f"{ticks / max(uops, 1):.2f}", f"{ms:.2f} ms",
                     f"{1e6 * ms / max(ins, 1):.0f} ns", f"{f:.2f} ms" if f else "", slower,
                     f"{fms / ms:.2f}x"])
        if f and name not in SKIP and not diffs:
            tot[0] += ins
            tot[1] += uops
            tot[2] += ticks
            tot[3] += ms
            tot[4] += f
            tot[5] += fms
    rows.append(["**total, against the full Heron**", tot[0], tot[1],
                 f"{tot[2] / max(tot[1], 1):.2f}", f"{tot[3]:.2f} ms",
                 f"{1e6 * tot[3] / max(tot[0], 1):.0f} ns", f"{tot[4]:.2f} ms",
                 f"{tot[3] / tot[4]:.1f}x" if tot[4] else "",
                 f"{tot[5] / tot[3]:.2f}x" if tot[3] else ""])
    head = ("The program suite on the two-halves machine's register-transfer model, "
            "which the netlist matches cycle for cycle (`heron chibi hw test`); each "
            f"microinstruction as many ticks of {TICK_NS:.2f} ns as the timing analysis's "
            "table gives it. *Microinstructions*: the cycles; *ticks each*: their average "
            "length. *Full Heron*: [RFC 0031's](../0031-rfc-draft-2-cpu/performance.md) time "
            "for the same program; *slower* is this one's time over it. *Over the first "
            f"cut*: the first cut's time (one cycle of {FIRST_NS} ns) over this one's. The "
            "total leaves out hello and interrupts, as RFC 0031's does. Times count from "
            "reset.")
    return "## The suite\n\n" + head + "\n\n" + table(
        ["Program", "Instructions", "Microinstructions", "Ticks each", "Time",
         "Per instruction", "Full Heron", "Slower", "Over the first cut"], rows,
        right=range(1, 9))


def by_instruction(runs, top=24):
    total = Counter()
    count = Counter()
    for _n, _i, _t, _u, by, _f, _d in runs:
        for k, (n, t) in by.items():
            total[k] += t
            count[k] += n
    allt = sum(total.values())
    rows, acc = [], 0
    for k, t in total.most_common(top):
        acc += t
        rows.append([k, count[k], t, f"{t / count[k]:.1f}", f"{100 * t / allt:.1f}%",
                     f"{100 * acc / allt:.1f}%"])
    head = ("The suite's ticks by instruction, all programs together: each instruction's "
            "ticks from its decode to the next one's (an interrupt's entry counts to the "
            "instruction it interrupted).")
    return "## Where the time goes\n\n" + head + "\n\n" + table(
        ["Instruction", "Executed", "Ticks", "Ticks each", "Share", "Cumulative"], rows,
        right=range(1, 6))


SIM_ONLY = ("S_BTNX",)          # the simulation's interrupt button (a connector on the board)


def parts_section():
    from . import board2, parts
    nl = board2.build(sim=True)
    bom = nl.bom(parts.VARIANT, passives=False)
    rows = []
    total = 0
    for p, refs in sorted(bom.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        refs = [r for r in refs if r not in SIM_ONLY]
        if refs:
            total += len(refs)
            rows.append([p, len(refs)])
    by = Counter()
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive") or inst.ref in SIM_ONLY:
            continue
        by[inst.section] += 1
    secs = [[s, n] for s, n in by.items()]
    return ("## Parts\n\nThe board's packages (the simulation's netlist without its "
            "fixtures), not counting resistors, capacitors and connectors.\n\n"
            + table(["Part", "Packages"], rows + [["**total**", total]], right=(1,))
            + "\n\n" + table(["Section", "Packages"], secs, right=(1,)))


def sta_section():
    from . import sta2
    res, fbad = sta2.analyse()
    head = ("Static timing analysis of the netlist (`heron chibi hw sta`), worst-case "
            "datasheet delays: every distinct microinstruction's low and high halves, in "
            "whole ticks, and phase F. The ticks table it writes (ticks.json) is what the "
            "control store's length fields are filled from.")
    return "## Timing\n\n" + head + "\n\n```\n" + sta2.report(res, fbad, paths=2) + "\n```"


def build(jobs=4):
    from heron.studies.v2_isa import testing
    paths = testing.program_paths()
    with ProcessPoolExecutor(jobs) as ex:
        runs = list(ex.map(run_one, paths))
    out = ["# Performance for RFC 0047", "",
           "Generated by `heron chibi report --write`; don't edit by hand. The study is "
           "[studies/chibi](../../studies/chibi/README.md).", "",
           suite_section(runs), "", by_instruction(runs), "", parts_section(), "",
           sta_section(), ""]
    return "\n".join(out), runs


def cmd_report(args):
    text, runs = build()
    bad = [r[0] for r in runs if r[6]]
    if args.write:
        os.makedirs(DOC, exist_ok=True)
        with open(os.path.join(DOC, "performance.md"), "w") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(os.path.join(DOC, 'performance.md'), ROOT)}")
    else:
        print(text)
    if bad:
        print(f"the model fails: {' '.join(bad)}")
    return 1 if bad else 0
