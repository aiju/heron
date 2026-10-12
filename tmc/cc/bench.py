"""Compiled C against hand-written assembly: every programs/c/NAME.c is
compiled for drafts 1a and 1b, checked against programs/expected/NAME.txt,
and costed next to programs/v1a/NAME.s and programs/v1b/NAME.s.

    python3 -m tmc ccbench            print the tables
    python3 -m tmc ccbench --write    also write docs/compiler-performance.md
"""

import bisect
import glob
import math
import os
import sys

from .. import testing
from .. import isa as isas
from . import driver

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CDIR = os.path.join(ROOT, "programs", "c")
CONFIGS = ["D16-overlap", "D32-overlap", "D32-wide"]


def functions(img):
    """[(address, name)] of the global labels, sorted."""
    return sorted((st.addr, st.label) for st in img.stmts
                  if st.kind == "label" and "." not in st.label)


def split_cycles(m, img, lib_names, config):
    """Cycles spent in the C library vs the program's own functions."""
    labels = functions(img)
    starts = [a for a, _ in labels]
    lib = own = 0
    for pc, cyc in m.pc_cycles(config).items():
        if pc is None:
            continue
        k = bisect.bisect_right(starts, pc) - 1
        name = labels[k][1] if k >= 0 else "?"
        if name.startswith("_") and name[1:] in lib_names:
            lib += cyc
        else:
            own += cyc
    return own, lib


def kinds(m, img, isa, keep):
    """Executed instruction kinds (isa.kind) at the addresses keep(pc) allows."""
    from collections import Counter
    mod = isas.get(isa)
    labels = functions(img)
    starts = [a for a, _ in labels]
    out = Counter()
    for pc, n in m.pc_counts.items():
        k = bisect.bisect_right(starts, pc) - 1
        if k >= 0 and keep(labels[k][1]):
            out[mod.kind([m.parcel(pc), m.parcel(pc + 2), m.parcel(pc + 4)])] += n
    return out


def code_sizes(img, lib_names, own_names):
    """Bytes of code in the program's own functions and in the C library
    (a function runs to the next global label)."""
    labels = functions(img)
    own = lib = 0
    for k, (a, name) in enumerate(labels):
        if k + 1 >= len(labels):
            break
        size = labels[k + 1][0] - a
        if name.startswith("_") and name[1:] in lib_names:
            lib += size
        elif name.startswith("_") and name[1:] in own_names:
            own += size
    return own, lib


def run_c(path, isa):
    name = os.path.basename(path)[:-2]
    meta = testing.metadata(os.path.join(ROOT, "programs", isa, name + ".s")) \
        if os.path.exists(os.path.join(ROOT, "programs", isa, name + ".s")) else {"input": b""}
    prog = driver.Program(isa)
    text, img, _ = driver.build([path], isa, program=prog)
    m = driver.run_image(img, isa, inp=meta["input"])
    out = bytes(m.dev.out)
    exp = testing.expected_output(name)
    ok = m.error is None and not m.traps and out == exp
    res = {"ok": ok, "instructions": m.instructions, "cycles": m.all_cycles(), "image": img,
           "lib": prog.lib_functions}
    res["split"] = {c: split_cycles(m, img, prog.lib_functions, c) for c in CONFIGS}
    res["kinds"] = kinds(m, img, isa, lambda n: not (n.startswith("_") and n[1:] in prog.lib_functions)
                         and not n.startswith("__"))
    own_names = {f.name for u in prog.units if not getattr(u, "library", False)
                 for f in u.module.functions}
    res["code"] = code_sizes(img, prog.lib_functions, own_names)
    return res


def run_asm(name, isa):
    path = os.path.join(ROOT, "programs", isa, name + ".s")
    if not os.path.exists(path):
        return None
    r = testing.run_program(path, isa)
    m = r.get("machine")
    if not r["ok"]:
        return None
    return {"cycles": m.all_cycles(), "instructions": m.instructions, "code": r["code_bytes"],
            "kinds": kinds(m, r["image"], isa, lambda n: True)}


def geomean(xs):
    xs = [x for x in xs if x]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def collect():
    rows = []
    for path in sorted(glob.glob(os.path.join(CDIR, "*.c"))):
        name = os.path.basename(path)[:-2]
        row = {"name": name}
        for isa in ("v1a", "v1b"):
            row["c_" + isa] = run_c(path, isa)
            row["asm_" + isa] = run_asm(name, isa)
        rows.append(row)
    return rows


def fmt(n):
    return f"{n:,.0f}"


def report(rows):
    out = []
    cfg = "D16-overlap"
    out.append(f"### Cycles ({cfg})\n")
    out.append("| Program | 1a asm | 1a C | C / asm | 1b asm | 1b C | C / asm | C: 1b / 1a |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    ratios = {"v1a": [], "v1b": [], "ab": []}
    for r in rows:
        cells = [r["name"]]
        for isa in ("v1a", "v1b"):
            c, a = r["c_" + isa], r["asm_" + isa]
            if not c["ok"]:
                cells += [fmt(a["cycles"][cfg]) if a else "–", "FAIL", "–"]
                continue
            cc = c["cycles"][cfg]
            if a:
                ac = a["cycles"][cfg]
                cells += [fmt(ac), fmt(cc), f"{cc / ac:.2f}"]
                ratios[isa].append(cc / ac)
            else:
                cells += ["–", fmt(cc), "–"]
        ca, cb = r["c_v1a"], r["c_v1b"]
        if ca["ok"] and cb["ok"]:
            x = cb["cycles"][cfg] / ca["cycles"][cfg]
            ratios["ab"].append(x)
            cells.append(f"{x:.3f}")
        else:
            cells.append("–")
        out.append("| " + " | ".join(cells) + " |")
    out.append(f"| **geometric mean** | | | **{geomean(ratios['v1a']):.2f}** | | | "
               f"**{geomean(ratios['v1b']):.2f}** | **{geomean(ratios['ab']):.3f}** |")
    out.append("")
    out.append("### Cycles in the program's own code, without the C library (D16-overlap)\n")
    out.append("The C versions print with printf; the assembly versions call small "
               "special-purpose routines. This table leaves the C library (printf, "
               "strcmp, memcpy, ...) out of the C side, so it compares only the code "
               "the compiler made from the program itself, against the whole of the "
               "assembly version. The mean only counts the programs that spend less "
               "than half their time in the C library (the others mostly measure "
               "printf against the assembly versions' printing).\n")
    out.append("| Program | 1a C own | C own / asm | 1b C own | C own / asm | library share 1a / 1b |")
    out.append("|---|---:|---:|---:|---:|---:|")
    own_r = {"v1a": [], "v1b": []}
    for r in rows:
        cells = [r["name"]]
        shares = []
        for isa in ("v1a", "v1b"):
            c, a = r["c_" + isa], r["asm_" + isa]
            if not c["ok"]:
                cells += ["FAIL", "–"]
                continue
            own, lib = c["split"][cfg]
            shares.append(f"{100 * lib / (own + lib):.0f}%")
            if a:
                x = own / a["cycles"][cfg]
                if lib < own:
                    own_r[isa].append(x)
                cells += [fmt(own), f"{x:.2f}"]
            else:
                cells += [fmt(own), "–"]
        cells.append(" / ".join(shares))
        out.append("| " + " | ".join(cells) + " |")
    out.append(f"| **geometric mean** | | **{geomean(own_r['v1a']):.2f}** | | "
               f"**{geomean(own_r['v1b']):.2f}** | |")
    out.append("")
    out.append("### Other configurations\n")
    out.append("Geometric means of C / asm cycles (whole programs), and of 1b / 1a for "
               "the compiled programs:\n")
    out.append("| Configuration | 1a C / asm | 1b C / asm | C: 1b / 1a | asm: 1b / 1a |")
    out.append("|---|---:|---:|---:|---:|")
    for cfg2 in ["D16-separate", "D16-overlap", "D16-wide", "D32-separate", "D32-overlap", "D32-wide"]:
        ra, rb, ab, asm_ab = [], [], [], []
        for r in rows:
            ca, cb, aa, ab_ = r["c_v1a"], r["c_v1b"], r["asm_v1a"], r["asm_v1b"]
            if ca["ok"] and aa:
                ra.append(ca["cycles"][cfg2] / aa["cycles"][cfg2])
            if cb["ok"] and ab_:
                rb.append(cb["cycles"][cfg2] / ab_["cycles"][cfg2])
            if ca["ok"] and cb["ok"]:
                ab.append(cb["cycles"][cfg2] / ca["cycles"][cfg2])
            if aa and ab_:
                asm_ab.append(ab_["cycles"][cfg2] / aa["cycles"][cfg2])
        out.append(f"| {cfg2} | {geomean(ra):.2f} | {geomean(rb):.2f} | {geomean(ab):.3f} | "
                   f"{geomean(asm_ab):.3f} |")
    out.append("")
    out.append("### How the 1b code uses its operands\n")
    out.append("Executed instructions of the main group (MOV, ST, LEA, the ALU operations, "
               "JMP/CALL through an operand) by the kind of operand, summed over all programs: "
               "the program's own code for C, the whole program for assembly.\n")
    from collections import Counter
    tot = {"C": Counter(), "asm": Counter()}
    for r in rows:
        if r["c_v1b"]["ok"]:
            tot["C"].update(r["c_v1b"]["kinds"])
        if r["asm_v1b"]:
            tot["asm"].update(r["asm_v1b"]["kinds"])
    groups = [("register", ("r",)), ("constant -16..15", ("#q",)),
              ("16- or 32-bit constant", ("#i16", "#i32")),
              ("[r]", ("[r]", "b[r]", "h[r]")),
              ("[r + d16]", ("[r+d]", "b[r+d]", "h[r+d]")),
              ("[sp + n]", ("[sp+n]",)),
              ("auto-increment/decrement", ("[r]+", "b[r]+", "-[r]")),
              ("indexed [r + r*s + d8]", ("[r+x]", "b[r+x]", "h[r+x]")),
              ("absolute or PC-relative", ("[abs]", "b[abs]", "h[abs]", "[pc+d]", "b[pc+d]", "h[pc+d]"))]

    def share(counter, names, ops=None):
        total = sum(n for k, n in counter.items() if " " in k and (ops is None or k.split()[0] in ops))
        part = sum(n for k, n in counter.items() if " " in k and k.split(" ", 1)[1] in names
                   and (ops is None or k.split()[0] in ops))
        return 100 * part / total if total else 0
    out.append("| Operand | C | asm |")
    out.append("|---|---:|---:|")
    for label, names in groups:
        out.append(f"| {label} | {share(tot['C'], names):.1f}% | {share(tot['asm'], names):.1f}% |")
    mem = [n for _, ns in groups[3:] for n in ns]
    alu = ("ADD", "SUB", "CMP", "AND", "OR", "XOR")
    out.append(f"| *ALU instructions with a memory operand* | {share(tot['C'], mem, alu):.1f}% | "
               f"{share(tot['asm'], mem, alu):.1f}% |")
    out.append("")
    out.append("### Code size (bytes)\n")
    out.append("The program's own functions (C) against the whole assembly version "
               "including its library routines; the C library comes on top.\n")
    out.append("| Program | 1a asm | 1a C own | 1b asm | 1b C own | C library 1a / 1b |")
    out.append("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        cells = [r["name"]]
        libs = []
        for isa in ("v1a", "v1b"):
            c, a = r["c_" + isa], r["asm_" + isa]
            own, lib = c["code"]
            libs.append(str(lib))
            cells += [str(a["code"]) if a else "–", str(own)]
        cells.append(" / ".join(libs))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


HEADER = """# Compiled C against hand-written assembly

Generated by `python3 -m tmc ccbench --write`; see [compiler.md](compiler.md)
for the compiler. Each program in `programs/c/` is a plain C version of the
assembly program of the same name (same output, checked against
`programs/expected/`), written the way one would write it in C rather than
tuned for this compiler.

"""


def main(argv):
    rows = collect()
    text = report(rows)
    print(text)
    if "--write" in argv:
        with open(os.path.join(ROOT, "docs", "compiler-performance.md"), "w") as f:
            f.write(HEADER + text)
    return 0 if all(r["c_v1a"]["ok"] and r["c_v1b"]["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
