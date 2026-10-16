"""RFC 0031's measurements: `heron v2_hw report [--write]` prints them, or
writes reports/0031-rfc-draft-2-cpu/performance.md.

The suite (perf.suite(): the hand-written programs and the compiled C
ones) on the register-transfer model, profiled (perf.profile(), cached):
from the counts come the length classes, the time, where it goes, and what
some changes to the design would buy without building them.
"""

import os
import re
from collections import Counter

from heron import ROOT

from . import perf, timing, ucode as uc

OUT = os.path.join(ROOT, "reports", "0031-rfc-draft-2-cpu", "performance.md")
V1B = os.path.join(ROOT, "reports", "0024-rfc-faster-smaller", "results.md")
BUS_BASE = 0x08000000
ICACHES = (256, 4096)
NS = timing.TICK


def ms(ticks):
    return f"{ticks * NS / 1e6:.2f} ms"


def v1b_fast():
    """{program: ms} for draft 1b's fast system at chip level (RFC 0024's
    results)."""
    out = {}
    with open(V1B) as f:
        text = f.read()
    i = text.index("The program suite at chip level")
    for line in text[i:].splitlines():
        m = re.match(r"\| (\w+) \| [\d.]+ m?s \| ([\d.]+) (m?s) \|", line)
        if m:
            v = float(m.group(2)) * (1000 if m.group(3) == "s" else 1)
            out[m.group(1)] = v
    if not out:
        raise RuntimeError(f"no fast-system times in {V1B}")
    return out


# programs that print a lot: on draft 1b's system they wait for the UART;
# the models here have draft 1's I/O page, which never makes them wait. And
# the interrupt program, whose timer counts cycles here and time there
PRINTERS = ("arith", "lines", "monitor", "rpn", "strings", "hello")
TIMED = ("interrupts",)


def table(head, rows, align=None):
    align = align or ["---"] + ["---:"] * (len(head) - 1)
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def suite_section(rows, lens, times):
    fast = v1b_fast()
    body = []
    tot = Counter()
    for r in rows:
        name = r["name"]
        t = times[name]
        f = fast.get(name) if not name.startswith("c/") else None
        mark = " (prints)" if name in PRINTERS else " (timer)" if name in TIMED else ""
        sp = f"{f / (t * NS / 1e6):.2f}x" if f and not mark else ""
        body.append([f"{name}{mark}", r["instructions"], r["cycles"],
                     f"{r['cycles'] / r['instructions']:.2f}", ms(t),
                     f"{t * NS / r['instructions']:.0f} ns", f"{f:.2f} ms" if f else "", sp])
        if name not in perf.SKIP:
            part = "c" if name.startswith("c/") else "asm"
            tot[part, "i"] += r["instructions"]
            tot[part, "c"] += r["cycles"]
            tot[part, "t"] += t
            if f and not mark:
                tot["cmp", "v2"] += t
                tot["cmp", "v1b"] += f
    for part, label in (("asm", "hand-written"), ("c", "compiled C")):
        i, c, t = tot[part, "i"], tot[part, "c"], tot[part, "t"]
        body.append([f"**{label}, total**", i, c, f"{c / i:.2f}", ms(t), f"{t * NS / i:.0f} ns",
                     "", ""])
    sp = tot["cmp", "v1b"] / (tot["cmp", "v2"] * NS / 1e6)
    body.append(["**the programs that don't print, against 1b**", "", "", "",
                 ms(tot["cmp", "v2"]), "", f"{tot['cmp', 'v1b']:.1f} ms", f"{sp:.2f}x"])
    return "\n".join([
        "## The suite",
        "",
        f"The program suite on the register-transfer model, code and data in the CPU card's "
        f"RAM, with the length classes the profile picks ({', '.join(map(str, lens))} ticks of "
        f"20 ns). *1b fast*: draft 1b's fast system at chip level, worst case "
        f"([RFC 0024's results](../0024-rfc-faster-smaller/results.md#the-fast-system)), for "
        f"the same programs written for draft 1; *speed-up* is 1b fast's time over this one. "
        f"Programs marked *prints* print a lot: on 1b's system they wait for the UART, here "
        f"(draft 1's I/O page) they don't, so they aren't compared; nor is *interrupts*, "
        f"whose timer counts cycles here and microseconds there. The totals leave out "
        f"{' and '.join(perf.SKIP)}, as report 0012 does.",
        "",
        table(["Program", "Instructions", "Cycles", "CPI", "Time", "Per instruction",
               "1b fast", "Speed-up"], body),
    ])


def classes_section(rows, mc, lens):
    need = Counter()
    for r in rows:
        if r["name"] in perf.SKIP:
            continue
        for a, n in r["ucount"].items():
            need[mc.ticks[a]] += n
    tot = sum(need.values())
    static = Counter(mc.ticks[n.addr] for n in mc.nodes)
    body = [[t, static[t], need[t], f"{100 * need[t] / tot:.1f}%"] for t in sorted(static)]
    return "\n".join([
        "## Length classes",
        "",
        "Each microinstruction's need from static timing analysis of the netlist (`ticks.json`, "
        "worst-case datasheet delays), in ticks; *executed*: the suite's cycles. The four "
        f"classes that minimise the suite's time: {', '.join(map(str, lens))}.",
        "",
        table(["Ticks", "Microinstructions", "Executed", "Share"], body),
    ])


def kinds_section(rows, mc, lens):
    cyc, tks = Counter(), Counter()
    tot_t = 0
    for r in rows:
        if r["name"] in perf.SKIP:
            continue
        tot_t += r["hold"]
        for a, n in r["ucount"].items():
            k = perf.kind_of(mc.by_addr[a])
            L = min(x for x in lens if x >= mc.ticks[a])
            cyc[k] += n
            tks[k] += n * L
            tot_t += n * L
    tot_c = sum(cyc.values())
    hold = tot_t - sum(tks.values())
    body = [[k, cyc[k], f"{100 * cyc[k] / tot_c:.1f}%", f"{100 * tks[k] / tot_t:.1f}%"]
            for k, _ in tks.most_common()]
    body.append(["bus holds (the console)", "", "", f"{100 * hold / tot_t:.1f}%"])
    return "\n".join([
        "## Where the time goes",
        "",
        "The suite's microcycles by what they do, and their share of the time.",
        "",
        table(["Kind", "Cycles", "Of the cycles", "Of the time"], body,
              ["---", "---:", "---:", "---:"]),
    ])


def busiest_section(rows, mc, lens, n=20):
    tks, cyc = Counter(), Counter()
    tot = 0
    for r in rows:
        if r["name"] in perf.SKIP:
            continue
        tot += r["hold"]
        for a, k in r["ucount"].items():
            name = mc.by_addr[a].name
            L = min(x for x in lens if x >= mc.ticks[a])
            tks[name] += k * L
            cyc[name] += k
            tot += k * L
    body = [[f"`{name}`", cyc[name], f"{tks[name] / cyc[name]:.2f}", f"{100 * t / tot:.1f}%"]
            for name, t in tks.most_common(n)]
    return "\n".join([
        "## The busiest routines",
        "",
        "Microcode routines by their share of the suite's time. A routine is named by its "
        "instruction and mode (`m5`: mode 5; `mF/E`: the special mode's table E; `s2z2`: an "
        "index parcel's scale and size), so it covers all its cycles, not only the last.",
        "",
        table(["Routine", "Cycles", "Ticks a cycle", "Of the time"], body),
    ])


def is_short_branch(name):
    return name in ("BRA", "BSR", "DBNZ") or (name.startswith("B") and len(name) == 3
                                              and name not in ("BIC",))


def refill_section(rows, mc, lens):
    by = Counter()
    execs = Counter()
    tot = 0
    for r in rows:
        if r["name"] in perf.SKIP:
            continue
        for (jump, name), k in r["refill_from"].items():
            by[(jump, name)] += k
            tot += k
        for a, k in r["ucount"].items():
            node = mc.by_addr[a]
            if node.f.get("LDPC") and is_short_branch(node.name):
                execs[node.name] += k
    body = []
    for (jump, name), k in by.most_common(12):
        why = "the jump" if jump else "the queue short of the instruction"
        body.append([f"`{name}`", why, k, f"{100 * k / tot:.1f}%"])
    # a branch-target adder: the target of BRA, Bcc, BSR and DBNZ worked out
    # while the branch decodes, so the branch's own cycle fetches at the
    # target and decodes from it, as a refill does (K_BUS ticks)
    refill_ticks = min(x for x in lens if x >= mc.ticks[uc.REFILL_ADDR])
    taken = sum(k for (jump, name), k in by.items() if jump and is_short_branch(name))
    br_ticks = {}
    for n in mc.nodes:
        if n.f.get("LDPC") and is_short_branch(n.name):
            br_ticks[n.name] = min(x for x in lens if x >= mc.ticks[n.addr])
    longer = sum((execs[nm] - by[(True, nm)]) * max(0, refill_ticks - br_ticks[nm])
                 for nm in execs)
    saved = sum(by[(True, nm)] * br_ticks[nm] for nm in execs)
    all_t = 0
    for r in rows:
        if r["name"] in perf.SKIP:
            continue
        all_t += perf.time_with([r], lens)[r["name"]]
    net = saved - longer
    return "\n".join([
        "## Refills",
        "",
        f"A refill is a cycle that fetches the next instruction's first word and decodes "
        f"from it: after every jump, and when the queue doesn't hold the whole next "
        f"instruction. The suite's {tot} refills, by the instruction before them:",
        "",
        table(["Instruction", "Why", "Refills", "Share"], body,
              ["---", "---", "---:", "---:"]),
        "",
        f"**A branch-target adder** (not built): `BRA`, `Bcc`, `BSR` and `DBNZ` have their "
        f"target worked out while they are decoded, so a taken branch's own cycle fetches at "
        f"the target and decodes from it, as a refill does. Each taken one saves its first "
        f"cycle ({taken} of them); each one not taken gets a cycle as long as a refill's "
        f"({refill_ticks} ticks) unless the length class follows the condition. "
        f"Net: {100 * net / all_t:.1f}% of the suite's time "
        f"({100 * saved / all_t:.1f}% saved, {100 * longer / all_t:.1f}% lost).",
    ])


def bus_section(local, buses, lens):
    tl = perf.time_with(local, lens)
    tbs = [perf.time_with(rows, lens) for _, rows in buses]
    body = []
    tot = Counter()
    for i, r in enumerate(local):
        name = r["name"]
        if name in perf.SKIP:
            continue
        cells = [name, ms(tl[name])]
        tot["local"] += tl[name]
        for k, (label, rows) in enumerate(buses):
            t = tbs[k][name]
            cells.append(f"{ms(t)} ({t / tl[name]:.2f}x)")
            tot[label] += t
        body.append(cells)
    cells = ["**total**", ms(tot["local"])]
    for label, _ in buses:
        cells.append(f"{ms(tot[label])} ({tot[label] / tot['local']:.2f}x)")
    body.append(cells)
    head = ["Program", "CPU card's RAM"] + [label for label, _ in buses]
    return "\n".join([
        "## Code over the bus",
        "",
        "The same programs with code and data on a memory card in slot 1 (a 32-bit card, "
        "RFC 0014), so every fetch and data access is a bus transfer; with the same length "
        "classes. Fetches from bus space go out only when the queue is short of the next "
        "instruction (a refill), as the prefetch would otherwise hold the bus for words a "
        "jump throws away. *With N words of cache*: the instruction cache for bus space, "
        "direct mapped by physical address, a word a line.",
        "",
        table(head, body),
    ])


def what_if_section(rows, mc):
    base = None
    body = []
    variants = [((), "as estimated")] + [((k,), v) for k, v in timing.WHAT_IF.items()] + \
        [(tuple(timing.WHAT_IF), "both")]
    for v, label in variants:
        ticks = {n.addr: timing.estimate(mc.word(n), v)[1] for n in mc.nodes}
        need = Counter()
        for r in rows:
            if r["name"] in perf.SKIP:
                continue
            for a, n in r["ucount"].items():
                need[ticks[a]] += n
        lens = timing.best_lengths(need)
        t = sum(r["hold"] for r in rows if r["name"] not in perf.SKIP)
        t += sum(n * min(L for L in lens if L >= k) for k, n in need.items())
        base = base or t
        body.append([label, ", ".join(map(str, lens)), ms(t), f"{100 * (t - base) / base:+.1f}%"])
    return "\n".join([
        "## What some changes would buy",
        "",
        "From `timing.py`'s path estimate, not the netlist's timing that the rest of this page "
        "uses: the suite's time as the estimate has it, and with the estimate changed as if "
        "the design were, the same microcode and the length classes picked again "
        "(`timing.WHAT_IF`). The changes are the differences.",
        "",
        table(["Design", "Length classes", "Suite", "Change"], body,
              ["---", "---", "---:", "---:"]),
    ])


GROUPS = [
    ("instructions with a mode (rows 1-6, 8-A, ST, CLR, INC, DEC, LEA, JMP, CALL, BIC, TST)",
     ("MOV", "ST", "MOVS", "ADD", "SUB", "CMP", "AND", "OR", "XOR", "CLR", "INC", "DEC", "LEA",
      "JMP", "CALL", "BIC", "TST")),
    ("multiply and divide", ("MULU", "MULS", "DIVU", "DIVS", "DIVUL")),
    ("SAVE, RESTORE, LDM, STM", ("SAVE", "RESTORE", "LDM", "STM")),
    ("shifts", ("LSL", "LSR", "ASR", "ROR")),
    ("SWI (a routine per number)", ("SWI",)),
    ("the tentative instructions", ("ADD.B4", "FFS", "POPC", "REV", "MULA", "MERGE", "MULFX",
                                    "TMOV", "TTST", "TADD", "TSUB", "TCMP")),
    ("illegal instructions (unused slots in tables)", ("illegal",)),
    ("reset, traps, interrupts, refill", ("reset", "trap", "address", "fault", "page",
                                          "trace", "interrupt", "refill")),
]


def microcode_section(mc):
    words = Counter(n.name.split()[0] for n in mc.nodes)
    body = []
    left = dict(words)
    for label, names in GROUPS:
        k = sum(left.pop(n, 0) for n in names)
        body.append([label, k])
    body.append(["everything else", sum(left.values())])
    body.append(["**total**", len(mc.nodes)])
    tent = [[f"`{n}`", words[n]] for n in GROUPS[5][1]]
    return "\n".join([
        "## The microcode",
        "",
        f"{len(mc.nodes)} microinstructions of {uc.WORD_BITS} bits; the decode table maps "
        f"all 65,536 first parcels onto {len(set(mc.entry.values()))} entry points.",
        "",
        table(["Routines", "Microinstructions"], body),
        "",
        "The tentative instructions' share:",
        "",
        table(["Instruction", "Microinstructions"], tent),
    ])


def generate():
    mc = uc.built()
    local = perf.profile()
    lens, _ = perf.best_lengths(local)
    times = perf.time_with(local, lens)
    buses = [("over the bus", perf.profile(code_base=BUS_BASE))]
    for n in ICACHES:
        buses.append((f"with {n} words of cache", perf.profile(code_base=BUS_BASE, icache=n)))
    parts = [
        "# Performance for RFC 0031",
        "Generated by `heron v2_hw report --write`; don't edit by hand. The study is "
        "[studies/v2_hw](../../studies/v2_hw/README.md).",
        suite_section(local, lens, times),
        classes_section(local, mc, lens),
        kinds_section(local, mc, lens),
        busiest_section(local, mc, lens),
        refill_section(local, mc, lens),
        bus_section(local, buses, lens),
        what_if_section(local, mc),
        microcode_section(mc),
    ]
    return "\n\n".join(parts) + "\n"


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="heron v2_hw report")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    text = generate()
    if args.write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(OUT, ROOT)}")
    else:
        print(text)
    return 0
