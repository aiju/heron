"""Egret's programs on draft 1b: what they cost, against the same programs
in hand-written assembly and compiled C, and where the cycles go.

    heron egret bench [NAME...]        print the tables
    heron egret bench --write          also write the report's generated part

A program's cycles are its run's minus the empty program's (start-up: the
VM compiles its prelude), so they include compiling the program itself;
the compile column is what a run with `#!check` (compile, don't run)
costs over start-up.
"""

import math
import os
import sys

from heron import ROOT
from . import build, profile
from .programs import catalogue

REPORT_DIR = os.path.join(ROOT, "reports", "0016-report-egret")
CONFIGS = ["D16-overlap", "D32-separate", "D32-wide"]
MHZ = 3.0


def geomean(xs):
    xs = [x for x in xs if x]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


_base = {}


def baseline(variant):
    """cycles of the empty program, and of compiling nothing"""
    if variant not in _base:
        m = build.machine(b"", variant=variant)
        _base[variant] = {c: m.cycles_avg(c) for c in CONFIGS}
    return _base[variant]


def run_egret(prog, variant):
    m = build.machine(prog.source, prog.input, variant=variant)
    ok = bytes(m.dev.out) == prog.expected()
    base = baseline(variant)
    total = {c: m.cycles_avg(c) - base[c] for c in CONFIGS}
    chk = build.machine(b"#!check\n" + prog.source, b"", variant=variant)
    compile_ = {c: chk.cycles_avg(c) - base[c] for c in CONFIGS}
    return {"ok": ok, "machine": m, "check": chk, "total": total, "compile": compile_,
            "run": {c: total[c] - compile_[c] for c in CONFIGS}}


def run_suite_versions(name):
    """cycles of the hand-written assembly and the compiled C versions"""
    from heron.studies.v1_isa import testing
    out = {}
    path = os.path.join(testing.program_dir("v1b"), name + ".s")
    if os.path.exists(path):
        r = testing.run_program(path, "v1b")
        if r["ok"]:
            out["asm"] = {c: r["machine"].cycles_avg(c) for c in CONFIGS}
    cpath = os.path.join(ROOT, "studies", "c_compiler", "programs", name + ".c")
    if os.path.exists(cpath):
        from heron.studies.c_compiler import bench as cb
        r = cb.run_c(cpath, "v1b")
        if r["ok"]:
            out["c"] = r["cycles"]
    return out


def collect(names=None):
    rows = []
    for name in names or catalogue.names():
        prog = catalogue.program(name)
        row = {"name": name, "suite": not prog.own_expected}
        row["asm_vm"] = run_egret(prog, "asm")
        row["c_vm"] = run_egret(prog, "c")
        if row["suite"]:
            row.update(run_suite_versions(name))
        rows.append(row)
        print(f"  {name}", file=sys.stderr)
    return rows


def fmt(n):
    return f"{n:,.0f}"


def ms(cycles):
    return f"{cycles / (MHZ * 1000):,.1f}"


def table_costs(rows, cfg):
    out = [f"| Program | Egret | Egret, C loop | compile | C | assembly | Egret / C | Egret / assembly |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    rc, ra = [], []
    for r in rows:
        e = r["asm_vm"]
        cells = [r["name"] + ("" if e["ok"] and r["c_vm"]["ok"] else " (WRONG OUTPUT)"),
                 fmt(e["run"][cfg]), fmt(r["c_vm"]["run"][cfg]), fmt(e["compile"][cfg])]
        for k in ("c", "asm"):
            cells.append(fmt(r[k][cfg]) if k in r else "–")
        for k, acc in (("c", rc), ("asm", ra)):
            if k in r:
                x = e["run"][cfg] / r[k][cfg]
                acc.append(x)
                cells.append(f"{x:.1f}")
            else:
                cells.append("–")
        out.append("| " + " | ".join(cells) + " |")
    out.append(f"| **geometric mean** | | | | | | **{geomean(rc):.1f}** | **{geomean(ra):.1f}** |")
    return "\n".join(out)


def table_loops(rows):
    out = ["| Program | " + " | ".join(f"{c}: C loop / assembly loop" for c in CONFIGS) + " |",
           "|---|" + "---:|" * len(CONFIGS)]
    gm = {c: [] for c in CONFIGS}
    for r in rows:
        cells = [r["name"]]
        for c in CONFIGS:
            x = r["c_vm"]["run"][c] / r["asm_vm"]["run"][c]
            gm[c].append(x)
            cells.append(f"{x:.2f}")
        out.append("| " + " | ".join(cells) + " |")
    out.append("| **geometric mean** | " + " | ".join(f"**{geomean(gm[c]):.2f}**" for c in CONFIGS) + " |")
    return "\n".join(out)


PARTS = [
    ("dispatch", ["dispatch"]),
    ("sends", ["SEND", "SEND_SUPER", "send: lookup", "send: frame", "send: primitive", "send: block",
               "send: new", "send: miss", "send: operator", "RETURN"]),
    ("pushes, stores", ["PUSH_NIL", "PUSH_TRUE", "PUSH_FALSE", "PUSH_SELF", "PUSH_BSELF", "PUSH_INT",
                        "PUSH_LIT", "PUSH_LOCAL", "STORE_LOCAL", "POP_LOCAL", "PUSH_BOXED",
                        "STORE_BOXED", "PUSH_CAPT", "STORE_CAPT", "PUSH_CAPT_BOXED",
                        "STORE_CAPT_BOXED", "PUSH_IVAR", "STORE_IVAR", "PUSH_BIVAR", "STORE_BIVAR",
                        "PUSH_GLOBAL", "STORE_GLOBAL", "POP", "DUP"]),
    ("arithmetic, compares", ["ADD", "SUB", "MUL", "DIV", "MOD", "LT", "LE", "GT", "GE", "EQ",
                              "BAND", "BOR", "BXOR", "SHL", "SHR", "NOT", "booleans", "INC_LOCAL"]),
    ("lists", ["AT", "AT_PUT"]),
    ("jumps, loops", ["JUMP", "JUMP_FALSE", "JUMP_TRUE", "JUMP_FALSE_OR_POP", "JUMP_TRUE_OR_POP",
                      "RANGE_NEXT", "ITER_NEXT"]),
    ("closures", ["CLOSURE"]),
]
C_PARTS = ["C slow path", "primitives", "allocation", "collector", "big integers", "maps",
           "method lookup", "C library", "compiler", "output", "other C"]


def parts_of(m, cfg, layout, chk=None):
    groups, details = profile.breakdown(m, cfg, layout, chk)
    out = {}
    named = set()
    for part, keys in PARTS:
        out[part] = sum(details.get(("interpreter", k), 0) for k in keys)
        named.update(keys)
    out["to C and back"] = details.get(("interpreter", "to C and back"), 0)
    named.add("to C and back")
    out["other bytecodes"] = sum(c for (g, d), c in details.items() if g == "interpreter" and d not in named)
    for g in C_PARTS:
        out[g] = groups.get(g, 0)
    return out


def table_parts(rows, cfg):
    layout = None
    keys = [p for p, _ in PARTS] + ["other bytecodes", "to C and back"] + C_PARTS
    out = ["| Program | " + " | ".join(keys) + " |", "|---|" + "---:|" * len(keys)]
    tot = {k: 0 for k in keys}
    for r in rows:
        m = r["asm_vm"]["machine"]
        layout = layout or profile.Layout(m.image)
        p = parts_of(m, cfg, layout, r["asm_vm"]["check"])
        total = sum(p.values())
        cells = [r["name"]] + [f"{100 * p[k] / total:.0f}" for k in keys]
        out.append("| " + " | ".join(cells) + " |")
        for k in keys:
            tot[k] += p[k] / total
    out.append("| **mean** | " + " | ".join(f"**{100 * tot[k] / len(rows):.0f}**" for k in keys) + " |")
    return "\n".join(out)


def report(rows):
    base = baseline("asm")
    out = ["<!-- generated by heron egret bench --write; don't edit -->", "",
           "# Egret on draft 1b: generated tables", "",
           "Cycles after start-up: a program's run, less the empty program's (the VM "
           "compiling its prelude). \"Egret\" is the VM with the hand-written interpreter "
           "loop, \"Egret, C loop\" the same VM with the loop in C. Egret's columns leave "
           "out compiling the program; \"compile\" is that, on the machine. C and assembly "
           "are the draft 1 suite's versions of the same program (c_compiler and v1_isa), "
           "with the same output.", "",
           f"Start-up: {fmt(base['D32-separate'])} cycles on D32-separate, "
           f"{ms(base['D32-separate'])} ms at {MHZ:g} MHz.", ""]
    for cfg in ["D32-separate", "D16-overlap"]:
        out += [f"## Cycles, {cfg}", "", table_costs(rows, cfg), ""]
    out += ["## The interpreter loop in C against by hand (whole runs, compile included)", "",
            table_loops(rows), ""]
    out += ["## Where Egret's cycles go (D32-separate, % of each program's run)", "",
            "The interpreter's part by what the hand-written loop was doing (\"sends\": "
            "the method cache, frames, returns, primitive calls; \"to C and back\": "
            "saving and reloading the registers around the C slow path), then the C "
            "functions by group.", "", table_parts(rows, "D32-separate"), ""]
    return "\n".join(out)


def main(args):
    rows = collect(args.names or None)
    text = report(rows)
    print(text)
    if args.write:
        os.makedirs(REPORT_DIR, exist_ok=True)
        with open(os.path.join(REPORT_DIR, "performance.md"), "w") as f:
            f.write(text)
    return 0
