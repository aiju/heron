"""Generate the generated part of report 0001 (draft 0's performance).

    heron v0_hw report [--hw] [--jobs N]

Runs every program on the instruction-level simulator (cycle counts come
from the microcode), runs static timing analysis for each parts variant and
delay corner, and with --hw also runs every program on the chip-level timing
simulator at the guaranteed clock period with worst-case delays, checking
the results against the instruction-level simulator.
"""

import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from heron import BUILD, ROOT
from heron.infra.hw import runner
from . import isa as v0
from . import machine
from .testing import program_paths, run_program, fmt_time

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(ROOT, "reports", "0001-report-draft-0-evaluation", "performance.md")
CACHE = os.path.join(BUILD, "hw-results.json")

CLASSES = {
    "load/store": {"LD", "ST", "LDB", "STB", "LD long", "ST long", "LDB long", "STB long", "LEA long"},
    "ALU": {"ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "BIC", "NOT", "NEG", "INC", "DEC", "SHL",
            "SHR", "ASR", "RLC", "RRC", "SWAB", "SXT", "ZXT", "ADDI"},
    "compare/test": {"CMP", "TST", "CMPI", "CMP #imm16", "TST #imm16"},
    "move/immediate": {"MOV", "MVI", "MOV #imm16"},
    "branch/jump": {"Bcc", "BRA", "Jcc", "JMP"},
    "call/return/stack": {"BSR", "CALL", "RET", "PUSH", "POP"},
}


def classify(kind):
    for c, ks in CLASSES.items():
        if kind in ks:
            return c
    if kind.endswith("#imm16"):
        return "ALU"
    return "other"


def label_name(label):
    """'op8 fn9 l0 s0' -> 'CMP #imm16, step 0'."""
    parts = label.split()
    if not parts[0].startswith("op"):
        return label
    op, fn, link = int(parts[0][2:], 16), int(parts[1][2:], 16), int(parts[2][1:])
    w = (op << 12) | fn | (0xF00 if link else 0)
    name = v0.kind(w)
    if op in (3, 9) and not link:
        name = {3: "Bcc", 9: "Jcc"}[op]
    return f"{name}, step {parts[3][1:]}"


def sta_table():
    from heron.infra.hw import sta, chips
    rows = []
    for variant in chips.VARIANTS:
        row = {"variant": variant}
        for corner in ("max", "typ"):
            N, res = sta.analyse(machine, variant, corner)
            row[corner] = res[0][0]
            row[corner + "_what"] = res[0][3][0]
        rows.append(row)
    return rows


def sim_sweep(variant, corner, path=os.path.join(HERE, "exercise.s")):
    """Shortest period at which the exercise program still works in the timing simulator."""
    inp = b""
    img, m = machine.run_isa(path, inp)
    lo, hi = 50.0, 800.0
    while hi - lo > 1.0:
        mid = (lo + hi) / 2
        ok, _, _ = runner.passes(machine, img, m, inp, mid, variant, corner)
        if ok:
            hi = mid
        else:
            lo = mid
    return hi


def hw_job(args):
    path, period, variant, corner = args
    inp = runner.program_input(path)
    img, m = machine.run_isa(path, inp)
    hw = runner.run_hw(machine, img, period, variant, corner, 1, inp, max_cycles=m.cycles + 1000,
                       fetch_trace=200_000)
    diffs = machine.compare(m, hw, check_cycles=m.irqs == 0)
    return {"name": os.path.basename(path)[:-2], "cycles": hw["cycles"], "isa_cycles": m.cycles,
            "diffs": diffs, "violations": hw["violation_total"], "irqs": m.irqs,
            "contention_max_ns": hw["contention"]["max_ps"] / 1000, "wall": hw["wall_seconds"],
            "period": period, "variant": variant, "corner": corner}


def run_hw_suite(paths, period, variant="hct-ls181", corner="max", jobs=4):
    with ProcessPoolExecutor(jobs) as ex:
        return list(ex.map(hw_job, [(p, period, variant, corner) for p in paths]))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="heron v0_hw report")
    ap.add_argument("--hw", action="store_true", help="also run every program on the chip-level simulator")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=DOC)
    args = ap.parse_args(argv)

    paths = program_paths()
    results = [run_program(p) for p in paths]
    bad = [r["name"] for r in results if not r["ok"]]
    if bad:
        print(f"warning: programs failing on the ISA simulator: {bad}", file=sys.stderr)

    sta_rows = sta_table()
    for r in sta_rows:
        for corner in ("max", "typ"):
            r["sim_" + corner] = sim_sweep(r["variant"], corner)
    guaranteed = {r["variant"]: r["max"] for r in sta_rows}
    typical = {r["variant"]: r["typ"] for r in sta_rows}

    hw_rows = None
    if args.hw:
        period = round(guaranteed["hct-ls181"] + 0.5, 0)
        hw_rows = run_hw_suite(paths, period, jobs=args.jobs)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump(hw_rows, f, indent=1)
    elif os.path.exists(CACHE):
        with open(CACHE) as f:
            hw_rows = json.load(f)
    hw_by_name = {h["name"]: h for h in hw_rows} if hw_rows else {}

    clocks = [
        ("1 MHz", 1e6),
        ("HCT+LS181 worst", 1e9 / guaranteed["hct-ls181"]),
        ("HCT+LS181 typ", 1e9 / typical["hct-ls181"]),
        ("ACT+F181 worst", 1e9 / guaranteed["act-f181"]),
        ("ACT+F181 typ", 1e9 / typical["act-f181"]),
    ]

    L = []
    L.append("# Performance of ISA draft 0 on the first hardware implementation")
    L.append("")
    L.append("> **Draft 0 is superseded.** This is the 16-bit first draft, kept as a record. Draft 1 "
             "replaced it: see [report 0004](../0004-report-draft-1-evaluation/README.md) and "
             "[the draft 1b hardware](../../studies/v1b_hw/hardware.md).")
    L.append("")
    L.append("Generated by `heron v0_hw report" + (" --hw" if args.hw else "") + "`; don't edit by hand.")
    L.append("")
    L.append("## Clock speed")
    L.append("")
    L.append("Minimum clock period from static timing analysis over every microinstruction "
             "(guaranteed for all data values). *Worst case* uses datasheet maximum delays "
             "(−40…85 °C, 4.5 V, 50 pF); *typical* uses 25 °C typical delays.")
    L.append("")
    L.append("| Parts | Worst case | Typical | Slowest microinstruction | Simulation, worst / typical |")
    L.append("|---|---:|---:|---|---:|")
    names = {"hct-ls181": "74HCT + 74LS181/74S182", "hct-f181": "74HCT + 74F181/74F182",
             "act-f181": "74ACT + 74F181/74F182"}
    for r in sta_rows:
        L.append(f"| {names.get(r['variant'], r['variant'])} | {r['max']:.0f} ns ({1000 / r['max']:.2f} MHz) "
                 f"| {r['typ']:.0f} ns ({1000 / r['typ']:.2f} MHz) | `{label_name(r['max_what'])}` "
                 f"| {r['sim_max']:.0f} / {r['sim_typ']:.0f} ns |")
    L.append("")
    L.append("The last column is the shortest period at which `studies/v0_hw/exercise.s` (every instruction "
             "class) still runs correctly in the event-driven chip simulation. It's a little faster than "
             "the static bound because the program doesn't hit the worst-case data patterns (long carry "
             "chains) at the worst moments.")
    L.append("")
    L.append("## Programs")
    L.append("")
    L.append("Cycle counts are exact for this implementation: they come from the microcode and "
             "are confirmed by the chip-level simulator (last column).")
    L.append("")
    head = "| Program | Instructions | Cycles | CPI | Code bytes | " + " | ".join(c for c, _ in clocks)
    head += " | Chip-level check |" if hw_by_name else " |"
    L.append(head)
    L.append("|---|---:|---:|---:|---:|" + "---:|" * len(clocks) + ("---|" if hw_by_name else ""))
    tot_i = tot_c = 0
    for r in results:
        if r.get("instructions") is None:
            continue
        tot_i += r["instructions"]
        tot_c += r["cycles"]
        cpi = r["cycles"] / max(1, r["instructions"])
        times = [fmt_time(r["cycles"] / hz) for _, hz in clocks]
        row = (f"| {r['name']} | {r['instructions']:,} | {r['cycles']:,} | {cpi:.2f} | {r['code_bytes']:,} | "
               + " | ".join(times) + " |")
        if hw_by_name:
            h = hw_by_name.get(r["name"])
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
    L.append(f"| **total** | {tot_i:,} | {tot_c:,} | {tot_c / max(1, tot_i):.2f} | | " +
             " | ".join(fmt_time(tot_c / hz) for _, hz in clocks) + " |" + (" |" if hw_by_name else ""))
    L.append("")
    if hw_by_name:
        h0 = next(iter(hw_by_name.values()))
        worst_cont = max(h["contention_max_ns"] for h in hw_by_name.values())
        L.append(f"Chip-level runs: every program at {h0['period']:.0f} ns ({1000 / h0['period']:.2f} MHz) "
                 f"with worst-case delays ({h0['variant']}), comparing console output, registers, flags, "
                 f"PC, all of RAM and (for programs without interrupts) the cycle of every instruction "
                 f"fetch with the instruction-level simulator. Longest bus contention seen: "
                 f"{worst_cont:.0f} ns (see [hardware.md](../../studies/v0_hw/hardware.md#known-issues-and-what-a-second-iteration-would-change)).")
        L.append("")

    # instruction mix across all programs
    kinds, kcycles = Counter(), Counter()
    eq_n, eq_c = Counter(), Counter()     # each program weighted equally
    progs = [r for r in results if r.get("kinds") and r["name"] != "hello"]
    for r in results:
        if r.get("kinds"):
            kinds.update(r["kinds"])
            kcycles.update(r["kind_cycles"])
    for r in progs:
        pn, pc = sum(r["kinds"].values()), sum(r["kind_cycles"].values())
        for k, n in r["kinds"].items():
            eq_n[classify(k)] += n / pn / len(progs)
            eq_c[classify(k)] += r["kind_cycles"][k] / pc / len(progs)
    total_n, total_c = sum(kinds.values()), sum(kcycles.values())
    cls_n, cls_c = Counter(), Counter()
    for k, n in kinds.items():
        cls_n[classify(k)] += n
        cls_c[classify(k)] += kcycles[k]
    L.append("## Where the cycles go")
    L.append("")
    L.append("Dynamic instruction mix by class. *Pooled* adds up all programs, so long runs like "
             "`mandel` (half of all cycles) dominate; *per program* averages each program's shares.")
    L.append("")
    L.append("| Class | Instructions, pooled | Cycles, pooled | Instructions, per program | "
             "Cycles, per program | Cycles per instruction |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for c, n in cls_c.most_common():
        L.append(f"| {c} | {100 * cls_n[c] / total_n:.1f}% | {100 * n / total_c:.1f}% | "
                 f"{100 * eq_n[c]:.1f}% | {100 * eq_c[c]:.1f}% | {n / max(1, cls_n[c]):.2f} |")
    L.append("")
    L.append("Most frequent instructions:")
    L.append("")
    L.append("| Instruction | Share of instructions | Share of cycles |")
    L.append("|---|---:|---:|")
    for k, n in kinds.most_common(20):
        L.append(f"| `{k}` | {100 * n / total_n:.1f}% | {100 * kcycles[k] / total_c:.1f}% |")
    L.append("")

    # static code statistics
    isa = v0
    stat_kinds = Counter()
    two = Counter()
    two_word = one_word = 0
    seen_lines = set()
    for r in results:
        img = r.get("image")
        if img is None:
            continue
        for st in img.stmts:
            if st.kind == "insn" and st.where not in seen_lines:
                seen_lines.add(st.where)       # library code counts once, not once per program
                stat_kinds[isa.kind(st.words[0])] += 1
                if len(st.words) == 2:
                    two_word += 1
                    two[isa.kind(st.words[0])] += 1
                else:
                    one_word += 1
    L.append("## Code size")
    L.append("")
    L.append(f"Across all programs and the library (each source line counted once): "
             f"{one_word + two_word:,} instructions, "
             f"{100 * two_word / max(1, one_word + two_word):.1f}% of them two-word, "
             f"{2 * (one_word + 2 * two_word) / max(1, one_word + two_word):.2f} bytes per instruction on average.")
    L.append("")
    L.append("Most common two-word forms in the source:")
    L.append("")
    L.append("| Form | Count |")
    L.append("|---|---:|")
    for k, v in two.most_common(10):
        L.append(f"| `{k}` | {v} |")
    L.append("")
    from . import analyze
    L.append(analyze.markdown(analyze.run_all()))
    with open(args.out, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"wrote {args.out}")
    return 0
