"""Chibi Heron's measurements, as RFC 0047's performance.md has them: the
program suite on the register-transfer model at the machine's one cycle
length (158.9 ns, four of VGA's pixels) against the full Heron's times
(RFC 0031's performance.md), where the cycles go by instruction, the parts
and static timing analysis of the netlist.

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


def period():
    from .sta import VGA_PERIOD
    return VGA_PERIOD


def mnemonic(parcels):
    from heron.studies.v2_isa import v2
    text = v2.disassemble(parcels)[0]
    return "illegal" if text.startswith(".half") else text.split()[0]


def run_one(path):
    """(name, instructions, cycles, {mnemonic: (count, cycles)}, the
    model's differences from the simulator)."""
    import heron.studies.v2_isa  # noqa: F401
    from heron.infra.programs import metadata
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    img = check.assemble(path)
    ref = check.run_isa(img, meta["input"])
    m = check.run_rtl(img, meta["input"], max_cycles=40 * ref.cycles + 100_000, log=True)
    diffs = check.compare(ref, m) if name not in check.TIMED else []
    by = {}
    ram = m.sys.ram
    ds = m.decodes + [(m.cycles, None, None)]
    for (c0, pc, md), (c1, *_r) in zip(ds, ds[1:]):
        ext = [ram[(pc + k) % len(ram)] | ram[(pc + k + 1) % len(ram)] << 8 for k in (2, 4)]
        k = mnemonic([md] + ext)
        n, c = by.get(k, (0, 0))
        by[k] = (n + 1, c + c1 - c0)
    return name, m.instructions, m.cycles, by, diffs


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


def suite_section(runs, T):
    full = full_heron()
    rows, tot = [], [0, 0, 0.0, 0.0]
    for name, ins, cyc, _by, diffs in runs:
        ms = cyc * T / 1e6
        f = full.get(name)
        slower = f"{ms / f:.1f}x" if f and name not in SKIP else ""
        note = " (fails)" if diffs else ""
        rows.append([name + note, ins, cyc, f"{cyc / max(ins, 1):.2f}", f"{ms:.2f} ms",
                     f"{1e6 * ms / max(ins, 1):.0f} ns", f"{f:.2f} ms" if f else "", slower])
        if f and name not in SKIP and not diffs:
            tot[0] += ins
            tot[1] += cyc
            tot[2] += ms
            tot[3] += f
    rows.append(["**total, against the full Heron**", tot[0], tot[1],
                 f"{tot[1] / max(tot[0], 1):.2f}", f"{tot[2]:.2f} ms",
                 f"{1e6 * tot[2] / max(tot[0], 1):.0f} ns", f"{tot[3]:.2f} ms",
                 f"{tot[2] / tot[3]:.1f}x" if tot[3] else ""])
    head = (f"The program suite on the register-transfer model, which the netlist "
            f"matches cycle for cycle (`heron chibi hw test`), every cycle {T:.1f} ns. "
            f"*Full Heron*: [RFC 0031's](../0031-rfc-draft-2-cpu/performance.md) time for the "
            f"same program; *slower* is this one's time over it. The total leaves out hello "
            f"and interrupts, as RFC 0031's does. Cycles count from reset.")
    return "## The suite\n\n" + head + "\n\n" + table(
        ["Program", "Instructions", "Cycles", "CPI", "Time", "Per instruction", "Full Heron",
         "Slower"], rows, right=range(1, 8))


def by_instruction(runs, top=24):
    total = Counter()
    count = Counter()
    for _n, _i, _c, by, _d in runs:
        for k, (n, c) in by.items():
            total[k] += c
            count[k] += n
    allc = sum(total.values())
    rows, acc = [], 0
    for k, c in total.most_common(top):
        acc += c
        rows.append([k, count[k], c, f"{c / count[k]:.1f}", f"{100 * c / allc:.1f}%",
                     f"{100 * acc / allc:.1f}%"])
    head = ("The suite's cycles by instruction, all programs together: each instruction's "
            "cycles from its decode to the next one's (an interrupt's entry counts to the "
            "instruction it interrupted).")
    return "## Where the cycles go\n\n" + head + "\n\n" + table(
        ["Instruction", "Executed", "Cycles", "Cycles each", "Share", "Cumulative"], rows,
        right=range(1, 6))


def parts_section():
    from . import board, parts
    nl = board.build(sim=True)
    bom = nl.bom(parts.VARIANT, passives=False)
    rows = []
    total = 0
    for p, refs in sorted(bom.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        total += len(refs)
        rows.append([p, len(refs)])
    by = Counter()
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive"):
            continue
        by[inst.section] += 1
    secs = [[s, n] for s, n in by.items()]
    return ("## Parts\n\nThe netlist's packages, not counting resistors, capacitors and "
            "connectors.\n\n" + table(["Part", "Packages"], rows + [["**total**", total]],
                                     right=(1,))
            + "\n\n" + table(["Section", "Packages"], secs, right=(1,)))


def sta_section():
    from . import sta
    res, w = sta.analyse()
    T = max(res[0][0], w[0])
    head = (f"Static timing analysis of the netlist (`heron chibi hw sta`), worst-case "
            f"datasheet delays: every distinct microinstruction's phase R, and phase W. "
            f"The machine needs {T:.1f} ns; it runs at {sta.VGA_PERIOD:.1f} ns, four of "
            f"VGA's pixels, so that the video's timing comes from the CPU's clock.")
    return "## Timing\n\n" + head + "\n\n```\n" + sta.report(res, w, paths=2) + "\n```"


def build(jobs=4):
    from heron.studies.v2_isa import testing
    paths = testing.program_paths()
    with ProcessPoolExecutor(jobs) as ex:
        runs = list(ex.map(run_one, paths))
    T = period()
    out = ["# Performance for RFC 0047", "",
           "Generated by `heron chibi report --write`; don't edit by hand. The study is "
           "[studies/chibi](../../studies/chibi/README.md).", "",
           suite_section(runs, T), "", by_instruction(runs), "", parts_section(), "",
           sta_section(), ""]
    return "\n".join(out), runs


def cmd_report(args):
    text, runs = build()
    bad = [r[0] for r in runs if r[4]]
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
