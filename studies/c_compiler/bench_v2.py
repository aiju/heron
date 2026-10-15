"""Compiled C on draft 2: every programs/NAME.c is compiled for drafts 1b
and 2, checked against the program suite's expected output, and costed
against each other and against the hand-written draft 2 programs (the
v2_isa study). Then the draft 2 backend runs again with each of the
draft 2 features it uses turned off in turn, to see what each is worth.

    heron c_compiler bench --isa v2            print the tables
    heron c_compiler bench --isa v2 --write    also write the generated part of report 0030
"""

import glob
import os
from collections import Counter

from heron import ROOT
from heron.studies.c_compiler.ir.ir import CMPOPS
from .bench import CDIR, collect, fmt, geomean, run_c
from .cc import driver
from .codegen.mir import PHYS
from .codegen.v1b import V1B
from .codegen.v2 import V2

DOC = os.path.join(ROOT, "reports", "0030-report-c-compiler-draft-2", "performance.md")
CFG = "D16-overlap"
CONFIGS = ["D16-separate", "D16-overlap", "D16-wide", "D32-separate", "D32-overlap", "D32-wide"]
# its byte array lands on or off a word boundary with the C library's size,
# which changes memset's time 3.6 times over (RFC 0006, 3.3)
LAYOUT = "sieve"


# ---- the backend without one feature ------------------------------------


class NoDBNZ(V2):
    """Loops still counted down, closing with DEC r; BNE."""

    def final_layout(self, body):
        pass


class NoCountdown(NoDBNZ):
    COUNT_DOWN = False


class NoMOVS(V2):
    """1b's peepholes: a compare goes only right after an instruction that
    set the flags, and no MOV becomes MOVS."""

    def peephole(self):
        V1B.peephole(self)


class NoCLR(V2):
    """A zero stored from a register, loaded with MOV rX, #0."""

    def store_word(self, v, mem):
        V1B.store_word(self, v, mem)

    def sel_store(self, i):
        if not self.sel_rmw(i):
            V1B.sel_store(self, i)


class NoRMW(V2):
    def rmw(self, i):
        return None


class NoTables(V2):
    """1b's way: [label + r*s] through the label's address in a register,
    and [x*s + d] computed."""
    sym_indexed = V1B.sym_indexed
    sym_index_ok = V1B.sym_index_ok

    def fits_scaled(self, disp):
        return False


class NoTableJump(V2):
    """1b's switch: LEA rt, [pc + table]; JMP [rt + r*4]."""
    jump_table = V1B.jump_table


class NoConstantOps(V2):
    """TST and MULS without constants."""
    IMM_OPS = V1B.IMM_OPS
    test = V1B.test

    def sel_binop(self, i):
        V1B.sel_binop(self, i)


class HoistCompares(V2):
    """Compare constants 16..127 kept in registers across loops, as on 1b."""

    @staticmethod
    def free_imm(op, c, i=None):
        if hasattr(c, "signed") and op in CMPOPS and 16 <= c.signed <= 127:
            return False
        return V2.free_imm(op, c, i)


class NoR0(V2):
    """r0 not allocated: 14 registers, as on draft 1."""
    ALLOC_ORDER = PHYS[1:15]


VARIANTS = [
    ("DBNZ (loops still counted down)", NoDBNZ),
    ("counting down and DBNZ", NoCountdown),
    ("MOVS", NoMOVS),
    ("CLR (a MOV #0 and a store instead)", NoCLR),
    ("INC and DEC on memory", NoRMW),
    ("tables without a base register", NoTables),
    ("JMP [pc + table + r*4]", NoTableJump),
    ("TST and MULS with a constant", NoConstantOps),
    ("CMP #16..127 in place of a register", HoistCompares),
    ("r0 as a 15th register", NoR0),
]


def programs():
    return sorted(glob.glob(os.path.join(CDIR, "*.c")))


def ablation():
    """{variant label: {program: run_c result}}, each compiled with a
    variant of the draft 2 backend (and its C library with it)."""
    real = driver.target_for
    out = {}
    try:
        for label, cls in VARIANTS:
            driver.target_for = lambda isa, cls=cls: cls if isa == "v2" else real(isa)
            driver._library.clear()
            rows = {}
            for path in programs():
                name = os.path.basename(path)[:-2]
                r = run_c(path, "v2")
                if not r["ok"]:
                    raise RuntimeError(f"{name} fails without {label}")
                rows[name] = r
            out[label] = rows
    finally:
        driver.target_for = real
        driver._library.clear()
    return out


# ---- the tables --------------------------------------------------------


def own(r, cfg=CFG):
    return r["split"][cfg][0]


def lib(r, cfg=CFG):
    return r["split"][cfg][1]


def report(rows, ablated):
    out = []
    ok = [r for r in rows if r["c_v1b"]["ok"] and r["c_v2"]["ok"]]
    out.append(f"### Cycles ({CFG})\n")
    out.append("The program's own code (own) and the C library's, compiled for 1b and for "
               "draft 2, and the hand-written draft 2 version (asm) from the v2_isa study. "
               f"The library mean leaves out {LAYOUT}, whose time in memset depends on where "
               "the linker puts its array.\n")
    out.append("| Program | 1b own | 2 own | own: 2 / 1b | library: 2 / 1b | whole: 2 / 1b "
               "| 2 asm | 2 own / asm |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    rat = {"own": [], "lib": [], "whole": [], "asm": []}
    for r in rows:
        b, c, a = r["c_v1b"], r["c_v2"], r["asm_v2"]
        if r not in ok:
            out.append(f"| {r['name']} | {'ok' if b['ok'] else 'FAIL'} | {'ok' if c['ok'] else 'FAIL'} "
                       "| – | – | – | – | – |")
            continue
        x_own = own(c) / own(b)
        x_whole = c["cycles"][CFG] / b["cycles"][CFG]
        rat["own"].append(x_own)
        rat["whole"].append(x_whole)
        cells = [r["name"], fmt(own(b)), fmt(own(c)), f"{x_own:.3f}"]
        if lib(b):
            x_lib = lib(c) / lib(b)
            if r["name"] != LAYOUT:
                rat["lib"].append(x_lib)
            cells.append(f"{x_lib:.3f}")
        else:
            cells.append("–")
        cells.append(f"{x_whole:.3f}")
        if a:
            cells += [fmt(a["cycles"][CFG]), f"{own(c) / a['cycles'][CFG]:.2f}"]
            if lib(c) < own(c):
                rat["asm"].append(own(c) / a["cycles"][CFG])
        else:
            cells += ["–", "–"]
        out.append("| " + " | ".join(cells) + " |")
    out.append(f"| **geometric mean** | | | **{geomean(rat['own']):.3f}** | **{geomean(rat['lib']):.3f}** "
               f"| **{geomean(rat['whole']):.3f}** | | **{geomean(rat['asm']):.2f}** |")
    out.append("")
    out.append("The own / asm mean counts only the programs that spend less than half their "
               "time in the C library, as report 0011 does.\n")

    out.append("### Other configurations\n")
    out.append("Geometric means of draft 2 / 1b: the compiled programs' own code, the C "
               f"library (without {LAYOUT}), and the hand-written programs for comparison.\n")
    out.append("| Configuration | C own | C library | asm |")
    out.append("|---|---:|---:|---:|")
    for cfg in CONFIGS:
        o, li, asm = [], [], []
        for r in ok:
            b, c = r["c_v1b"], r["c_v2"]
            o.append(own(c, cfg) / own(b, cfg))
            if lib(b, cfg) and r["name"] != LAYOUT:
                li.append(lib(c, cfg) / lib(b, cfg))
        for r in rows:
            if r["asm_v1b"] and r["asm_v2"]:
                asm.append(r["asm_v2"]["cycles"][cfg] / r["asm_v1b"]["cycles"][cfg])
        out.append(f"| {cfg} | {geomean(o):.3f} | {geomean(li):.3f} | {geomean(asm):.3f} |")
    out.append("")

    out.append("### Code size (bytes)\n")
    out.append("The program's own functions, and the C library linked with it.\n")
    out.append("| Program | 1b own | 2 own | 2 / 1b | C library 1b / 2 |")
    out.append("|---|---:|---:|---:|---:|")
    tb = tc = 0
    for r in rows:
        (ob, lb), (oc, lc) = r["c_v1b"]["code"], r["c_v2"]["code"]
        tb, tc = tb + ob, tc + oc
        out.append(f"| {r['name']} | {ob} | {oc} | {oc / ob:.3f} | {lb} / {lc} |")
    out.append(f"| **total** | **{tb}** | **{tc}** | **{tc / tb:.3f}** | |")
    out.append("")

    out.append(f"### What each draft 2 feature is worth ({CFG})\n")
    out.append("The draft 2 backend with one feature turned off, against the whole backend: "
               "geometric means of the ratio over the 15 programs (above 1: the feature "
               f"saves that much), the C library's without {LAYOUT}, the code's total, and "
               "the program that changes most.\n")
    out.append("| Without | Own cycles | Library cycles | Own code | Most |")
    out.append("|---|---:|---:|---:|---|")
    full = {r["name"]: r["c_v2"] for r in ok}
    for label, _ in VARIANTS:
        v = ablated[label]
        xo = [own(v[n]) / own(full[n]) for n in full]
        xl = [lib(v[n]) / lib(full[n]) for n in full if lib(full[n]) and n != LAYOUT]
        size = sum(v[n]["code"][0] for n in full) / sum(full[n]["code"][0] for n in full)
        most = max(full, key=lambda n: abs(own(v[n]) / own(full[n]) - 1))
        out.append(f"| {label} | {geomean(xo):.4f} | {geomean(xl):.4f} | {size:.4f} | "
                   f"{most} {own(v[most]) / own(full[most]):.3f} |")
    out.append("")

    out.append("### What the draft 2 code executes\n")
    out.append("Executed instructions in the programs' own code, summed over the 15 "
               "programs, by the v2_isa study's instruction kinds: the 20 most frequent, "
               "then all those draft 2 added.\n")
    tot = Counter()
    for r in ok:
        tot.update(r["c_v2"]["kinds"])
    n = sum(tot.values())

    def new(k):
        op = k.split()[0]
        return (op in ("MOVS", "CLR", "MVI", "CMPI", "DBNZ", "LDM", "STM", "MULA", "MULFX",
                       "REV", "FFS", "POPC", "MERGE", "ADD.B4") or op in ("INC", "DEC") and " " in k
                or "[abs+x]" in k or "[pc+x]" in k or "[r14+n]" in k)
    out.append("| Instruction | Share |")
    out.append("|---|---:|")
    for k, c in tot.most_common(20):
        out.append(f"| `{k}` | {100 * c / n:.2f}% |")
    out.append("| *new in draft 2:* | |")
    for k in sorted((k for k in tot if new(k)), key=lambda k: (-tot[k], k)):
        out.append(f"| `{k}` | {100 * tot[k] / n:.2f}% |")
    return "\n".join(out) + "\n"


HEADER = """# Compiled C on draft 2

Generated by `heron c_compiler bench --isa v2 --write`; see
[compiler.md](../../studies/c_compiler/compiler.md) for the compiler. The
programs are `studies/c_compiler/programs/`, report 0011's, each checked
against the program suite's expected output on both drafts.

"""


def main(argv):
    if argv[argv.index("--isa") + 1] != "v2":
        print("bench --isa: only v2 (without it, the bench compares 1a and 1b)")
        return 1
    rows = collect(("v1b", "v2"))
    ablated = ablation()
    text = report(rows, ablated)
    print(text)
    if "--write" in argv:
        os.makedirs(os.path.dirname(DOC), exist_ok=True)
        with open(DOC, "w") as f:
            f.write(HEADER + text)
    return 0 if all(r["c_v1b"]["ok"] and r["c_v2"]["ok"] for r in rows) else 1
