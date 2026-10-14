"""Egret's programs on draft 1b: what they cost, against the same programs
in hand-written assembly and compiled C, and where the cycles go.

    heron egret bench [NAME...]        print the tables
    heron egret bench --write          also write the report's generated part

Every program runs on three builds of the VM: the hand-written interpreter
loop ("interpreter"), the loop in C ("C loop"), and the template JIT
("JIT"). A program's cycles are its run's minus the empty program's
(start-up: the VM compiles its prelude) and minus compiling the program
(what a run with `#!check`, compile and don't run, costs over start-up),
which is the compile column.
"""

import math
import os
import sys

from heron import ROOT
from . import build, isa, profile
from .programs import catalogue

REPORT_DIR = os.path.join(ROOT, "reports", "0017-report-egret")
CONFIGS = ["D16-overlap", "D32-separate", "D32-wide"]
MAIN = "D32-separate"
MHZ = 3.0
VARIANTS = ["asm", "c", "jit"]


def geomean(xs):
    xs = [x for x in xs if x]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


_base = {}


def baseline(variant):
    """cycles of the empty program"""
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
            out["assembly"] = {c: r["machine"].cycles_avg(c) for c in CONFIGS}
    cpath = os.path.join(ROOT, "studies", "c_compiler", "programs", name + ".c")
    if os.path.exists(cpath):
        from heron.studies.c_compiler import bench as cb
        r = cb.run_c(cpath, "v1b")
        if r["ok"]:
            out["C"] = r["cycles"]
    return out


# ---- what each run is used for (worked out as it goes, so the machines can go) ------

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

NATIVE_PARTS = [
    ("calls", ["prologue", "SEND", "SEND_SUPER", "RETURN"]),
    ("out of line", ["stubs"]),
    ("shared stubs", ["shared stubs"]),
] + [(p, k) for p, k in PARTS[2:] if p not in ("sends",)]
JIT_GROUPS = ["JIT compiler", "JIT glue", "interpreter"] + C_PARTS


def interp_parts(m, chk, layout):
    groups, details = profile.breakdown(m, MAIN, layout, chk)
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


def jit_parts(m, chk, layout):
    groups, details = profile.breakdown(m, MAIN, layout, chk)
    out = {}
    named = set()
    for part, keys in NATIVE_PARTS:
        out[part] = sum(details.get(("native code", k), 0) for k in keys)
        named.update(keys)
    out["other bytecodes"] = sum(c for (g, d), c in details.items() if g == "native code" and d not in named)
    for g in JIT_GROUPS:
        out[g] = groups.get(g, 0)
    return out


def interp_isa(m, chk, layout):
    """{proposal: {config: cycles saved}}"""
    inst, pcc, cyc = isa.instances(m, chk)
    out = {}
    for p in isa.PROPOSALS:
        out[p.name] = {c: p.saving(inst, c) for c in CONFIGS}
    out["direct threading"] = {c: isa.dispatch_saving(m, layout, cyc, pcc, c) for c in CONFIGS}
    return out


def native_isa(m, layout):
    code = isa.native_code(m, layout)
    syms = m.image.symbols
    out = {ch.name: {c: ch.saving(code, c, syms) for c in CONFIGS} for ch in isa.NATIVE_CHANGES}
    kinds = isa.native_kinds(code, MAIN)
    return out, kinds


def collect(names=None):
    rows = []
    for name in names or catalogue.names():
        prog = catalogue.program(name)
        row = {"name": name, "suite": not prog.own_expected, "vm": {}}
        for v in VARIANTS:
            r = run_egret(prog, v)
            m, chk = r.pop("machine"), r.pop("check")
            if v == "asm":
                layout = profile.Layout(m.image)
                r["parts"] = interp_parts(m, chk, layout)
                r["isa"] = interp_isa(m, chk, layout)
            elif v == "jit":
                layout = profile.Layout(m.image, m)
                r["parts"] = jit_parts(m, chk, layout)
                r["isa"], r["kinds"] = native_isa(m, layout)
                r["code"] = {"methods": layout.native_methods, "native": layout.native_bytes,
                             "bytecode": layout.native_bc_bytes}
            row["vm"][v] = r
        if row["suite"]:
            row.update(run_suite_versions(name))
        rows.append(row)
        print(f"  {name}", file=sys.stderr)
    return rows


# ---- tables ------------------------------------------------------------------------------

def fmt(n):
    return f"{n:,.0f}"


def ms(cycles):
    return f"{cycles / (MHZ * 1000):,.1f}"


def ok_name(r):
    bad = [v for v in VARIANTS if not r["vm"][v]["ok"]]
    return r["name"] + (f" (WRONG OUTPUT: {', '.join(bad)})" if bad else "")


def table_costs(rows, cfg):
    out = ["| Program | interpreter | C loop | JIT | compile | C | assembly | interpreter / C "
           "| JIT / C | interpreter / JIT |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    gm = {"ic": [], "jc": [], "ij": []}
    for r in rows:
        vm = r["vm"]
        i, j = vm["asm"]["run"][cfg], vm["jit"]["run"][cfg]
        cells = [ok_name(r), fmt(i), fmt(vm["c"]["run"][cfg]), fmt(j), fmt(vm["asm"]["compile"][cfg])]
        cells += [fmt(r[k][cfg]) if k in r else "–" for k in ("C", "assembly")]
        if "C" in r:
            gm["ic"].append(i / r["C"][cfg])
            gm["jc"].append(j / r["C"][cfg])
            cells += [f"{i / r['C'][cfg]:.1f}", f"{j / r['C'][cfg]:.1f}"]
        else:
            cells += ["–", "–"]
        gm["ij"].append(i / j)
        cells.append(f"{i / j:.2f}")
        out.append("| " + " | ".join(cells) + " |")
    out.append(f"| **geometric mean** | | | | | | | **{geomean(gm['ic']):.1f}** | "
               f"**{geomean(gm['jc']):.1f}** | **{geomean(gm['ij']):.2f}** |")
    return "\n".join(out)


def table_summary(rows):
    out = ["| Configuration | interpreter / C | interpreter / assembly | C loop / interpreter "
           "| interpreter / JIT | JIT / C |",
           "|---|---:|---:|---:|---:|---:|"]
    for cfg in CONFIGS:
        ic, ia, ci, ij, jc = [], [], [], [], []
        for r in rows:
            vm = r["vm"]
            i, j = vm["asm"]["run"][cfg], vm["jit"]["run"][cfg]
            ci.append(vm["c"]["run"][cfg] / i)
            ij.append(i / j)
            if "C" in r:
                ic.append(i / r["C"][cfg])
                jc.append(j / r["C"][cfg])
            if "assembly" in r:
                ia.append(i / r["assembly"][cfg])
        out.append(f"| {cfg} | {geomean(ic):.1f} | {geomean(ia):.1f} | {geomean(ci):.2f} | "
                   f"{geomean(ij):.2f} | {geomean(jc):.1f} |")
    return "\n".join(out)


def pct(x):
    return f"{0 if abs(x) < 0.5 else x:.0f}"


def table_shares(rows, variant, keys):
    out = ["| Program | " + " | ".join(keys) + " |", "|---|" + "---:|" * len(keys)]
    tot = {k: 0 for k in keys}
    for r in rows:
        p = r["vm"][variant]["parts"]
        total = sum(p.values()) or 1
        out.append("| " + " | ".join([r["name"]] + [pct(100 * p[k] / total) for k in keys]) + " |")
        for k in keys:
            tot[k] += p[k] / total
    out.append("| **mean** | " + " | ".join(f"**{pct(100 * tot[k] / len(rows))}**" for k in keys) + " |")
    return "\n".join(out)


def table_kinds(rows):
    keys = ["the value stack", "frames", "registers", "other loads, stores", "branches, calls"]
    out = ["| Program | native code, % of the run | " + " | ".join(keys) + " |",
           "|---|---:|" + "---:|" * len(keys)]
    for r in rows:
        j = r["vm"]["jit"]
        k = j["kinds"]
        nat = sum(k.values()) or 1
        share = 100 * nat / j["run"][MAIN]
        out.append("| " + " | ".join([r["name"], f"{share:.0f}"] + [f"{100 * k.get(x, 0) / nat:.0f}" for x in keys]) + " |")
    return "\n".join(out)


def table_savings(rows, variant, names, cfg):
    out = ["| Program | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    tot = {n: 0 for n in names}
    for r in rows:
        v = r["vm"][variant]
        run = v["run"][cfg]
        cells = [r["name"]]
        for n in names:
            x = 100 * v["isa"][n][cfg] / run
            tot[n] += x
            cells.append(f"{x:.1f}")
        out.append("| " + " | ".join(cells) + " |")
    out.append("| **mean** | " + " | ".join(f"**{tot[n] / len(rows):.1f}**" for n in names) + " |")
    return "\n".join(out)


def table_code(rows):
    out = ["| Program | methods compiled | bytecode bytes | native bytes | native / bytecode "
           "| JIT compiler cycles | cycles per bytecode byte | JIT compiler, % of the run |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        j = r["vm"]["jit"]
        c = j["code"]
        jc = j["parts"]["JIT compiler"]
        out.append("| " + " | ".join([
            r["name"], fmt(c["methods"]), fmt(c["bytecode"]), fmt(c["native"]),
            f"{c['native'] / max(1, c['bytecode']):.1f}", fmt(jc),
            f"{jc / max(1, c['bytecode']):,.0f}", f"{100 * jc / j['run'][MAIN]:.0f}"]) + " |")
    return "\n".join(out)


def report(rows):
    base = baseline("asm")
    out = ["<!-- generated by heron egret bench --write; don't edit -->", "",
           "# Egret on draft 1b: generated tables", "",
           "Cycles of each program's run: its run less the empty program's (start-up, "
           "the VM compiling its prelude) and less compiling the program, which is the "
           "\"compile\" column (the same source compiler in every build). \"interpreter\" "
           "is the VM with the hand-written interpreter loop, \"C loop\" the same VM with "
           "the loop in C, \"JIT\" the VM compiling methods to machine code as they are "
           "first called (compiling counts in its run). C and assembly are the draft 1 "
           "suite's versions of the same program (c_compiler and v1_isa), with the same "
           "output.", "",
           f"Start-up: {fmt(base[MAIN])} cycles on {MAIN}, {ms(base[MAIN])} ms at {MHZ:g} MHz.", "",
           "## Summary, geometric means of the programs", "", table_summary(rows), ""]
    for cfg in ["D32-separate", "D16-overlap", "D32-wide"]:
        out += [f"## Cycles, {cfg}", "", table_costs(rows, cfg), ""]
    ikeys = [p for p, _ in PARTS] + ["other bytecodes", "to C and back"] + C_PARTS
    out += [f"## Where the interpreter's cycles go ({MAIN}, % of each program's run)", "",
            "The interpreter's part by what the hand-written loop was doing (\"sends\": "
            "the method cache, frames, returns, primitive calls; \"to C and back\": "
            "saving and reloading the registers around the C slow path), then the C "
            "functions by group.", "", table_shares(rows, "asm", ikeys), ""]
    jkeys = [p for p, _ in NATIVE_PARTS] + ["other bytecodes"] + JIT_GROUPS
    out += [f"## Where the JIT's cycles go ({MAIN}, % of each program's run)", "",
            "Native code by the bytecode it was compiled from (\"calls\": the sends' inline "
            "caches, the methods' prologues and the returns; \"out of line\": a method's "
            "slow paths, operator sends and inline cache misses; \"shared stubs\": the "
            "sends through the method cache, primitives', blocks' and new's), then compiling, the "
            "glue between native code and C, and the C functions by group.", "",
            table_shares(rows, "jit", jkeys), ""]
    out += [f"## The JIT's native code by what its instructions touch ({MAIN}, % of native cycles)", "",
            "\"the value stack\": instructions with an operand through r9 or r10 (locals, "
            "self, the expression stack); \"frames\": through r11 or sp; then other memory "
            "operands, branches and calls, and register-only instructions.", "",
            table_kinds(rows), ""]
    out += ["## The JIT's code", "",
            "Over the methods the run compiled (the prelude's included, as they are "
            "compiled when first called).", "", table_code(rows), ""]
    names = [p.name for p in isa.PROPOSALS] + ["direct threading"]
    for cfg in ["D32-separate", "D16-overlap"]:
        out += [f"## ISA changes for the interpreter ({cfg}, % of each program's run saved)", "",
                table_savings(rows, "asm", names, cfg), ""]
    nnames = [c.name for c in isa.NATIVE_CHANGES]
    for cfg in ["D32-separate", "D16-overlap"]:
        out += [f"## Changes for the JIT's code ({cfg}, % of each program's run saved)", "",
                table_savings(rows, "jit", nnames, cfg), ""]
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
