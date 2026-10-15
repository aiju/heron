"""The report's generated tables (results.md next to it).

    heron link_register report            print them
    heron link_register report --write    write the report's results.md

Everything comes from measure.py's cached runs; the first run takes about
half an hour on four cores (the Lisp's estimate, stepping every
instruction, is most of it).
"""

import os

from heron import ROOT
from . import estimate, hw, measure as M

DOC = os.path.join(ROOT, "reports", "0030-report-link-register", "results.md")
CFG = ["D16-overlap", "D32-separate", "D32-wide"]


def pct(x):
    return f"{100 * x:+.2f}%"


def fmt(n):
    return f"{n:,.0f}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" if i == 0 else "---:" for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def geo(pairs):
    """Geometric mean of b/a, minus 1."""
    pairs = list(pairs)
    return M.geomean(b / a for a, b in pairs) - 1


# ---- the costs ---------------------------------------------------------------------

COSTS = [
    ("`BSR`", (1, 0, "call", "rel", 0), (1, 0, "link", "rel", 0)),
    ("`CALL label` (16-bit relative)", (2, 0, "call", "rel", 0), (2, 0, "link", "rel", 0)),
    ("`CALL #label` (32-bit)", (3, 0, "call", "abs", 0), (3, 0, "link", "abs", 0)),
    ("`CALL r9`", (1, 0, "call", "reg", 0), (1, 0, "link", "reg", 0)),
    ("`CALL [r9]`", (1, 0, "callm", "r", 0), (1, 0, "linkm", "r", 0)),
    ("`CALL [r9 + 8]`", (2, 0, "callm", "rd", 0), (2, 0, "linkm", "rd", 0)),
    ("`CALL [r2 + r3*4]`", (2, 0, "callm", "idx", 0), (2, 0, "linkm", "idx", 0)),
    ("`RET`", (1, 0, "ret"), (1, 0, "jmp", "reg", 0)),
]


def costs():
    rows = [(name, hw.cycles(a), hw.cycles(b), f"{hw.cycles(b) - hw.cycles(a):+d}")
            for name, a, b in COSTS]
    c = estimate.Costs(hw.cycles)
    rows.append(("`PUSH r7` (`ST r7, -[sp]`)", "", c.push, f"+{c.push}"))
    rows.append(("`JMP [sp]+`, a return that pops", hw.cycles((1, 0, "ret")),
                 hw.cycles((1, 0, "jmpm", "pi", 0)), f"{c.ret_pop:+d}"))
    for n in (1, 3):
        rows.append((f"one register more in `SAVE` and `RESTORE` (of {n})", "", c.fold(n),
                     f"+{c.fold(n)}"))
    out = table(["Instruction", "1b: pushes", "v1bl: r7", "Change"], rows)
    bsr = c.call(("call", "rel", 1))
    out += ["", "A call with `BSR` and its return, by what the callee does:", ""]
    out += table(["Callee", "1b", "v1bl", "Change"], [
        ("a leaf: `BSR`, `RET`", 10, 10 + bsr + c.ret_r7, f"{bsr + c.ret_r7:+d}"),
        ("saves r8–rN: r7 joins the `SAVE` and the `RESTORE`", "10 + SAVE",
         f"{10 + bsr + c.fold(3) + c.ret_r7} + SAVE", f"{bsr + c.fold(3) + c.ret_r7:+d}"),
        ("saves nothing: `PUSH r7`, then `JMP [sp]+`", 10, 10 + bsr + c.push + c.ret_pop,
         f"{bsr + c.push + c.ret_pop:+d}")])
    return out


# ---- the ported workloads ----------------------------------------------------------

def suite_rows(res, est):
    rows = []
    for name in sorted(res):
        a, b = res[name]["v1b"], res[name]["v1bl"]
        ca = a["calls"]["calls"]
        e = est.get(name, {}).get("delta")
        rows.append((name + ("" if name not in M.SKIP else " (not in the means)"),
                     fmt(a["rtl"]), fmt(b["rtl"]), pct(b["rtl"] / a["rtl"] - 1),
                     pct(e / a["rtl"]) if e is not None else "",
                     pct(b["instructions"] / a["instructions"] - 1),
                     f"{b['code'] - a['code']:+d}",
                     f"{1000 * ca / a['instructions']:.1f}",
                     f"{b['calls']['pushes'] / ca:.2f}" if ca else ""))
    names = [n for n in res if n not in M.SKIP]
    rows.append(("**geometric mean**", "", "",
                 "**" + pct(geo((res[n]["v1b"]["rtl"], res[n]["v1bl"]["rtl"]) for n in names)) + "**",
                 pct(M.geomean(1 + est[n]["delta"] / res[n]["v1b"]["rtl"] for n in names) - 1)
                 if est else "",
                 pct(geo((res[n]["v1b"]["instructions"], res[n]["v1bl"]["instructions"])
                         for n in names)),
                 f"{sum(res[n]['v1bl']['code'] - res[n]['v1b']['code'] for n in res):+d} in all",
                 "", ""))
    return table(["Program", "1b cycles", "v1bl cycles", "Change", "Estimate", "Instructions",
                  "Code bytes", "Calls per 1,000 instructions", "Link saves per call"], rows)


def egret_rows(res):
    rows = []
    names = [n for n in sorted(res, key=lambda n: (n is not None, n or "")) if n != "hello"]
    for name in names:
        r = res[name]
        row = [name or "start-up (the empty program)"]
        for v in ("c", "asm", "jit"):
            a, b = r[("v1b", v)], r[("v1bl", v)]
            row.append(pct(b["hw"] / a["hw"] - 1))
        row.append(fmt(r[("v1b", "jit")]["hw"]))
        rows.append(row)
    progs = [n for n in names if n is not None]
    rows.append(["**geometric mean**"] + [
        "**" + pct(geo((res[n][("v1b", v)]["hw"], res[n][("v1bl", v)]["hw"]) for n in progs)) + "**"
        for v in ("c", "asm", "jit")] + [""])
    return table(["Program", "C interpreter", "Assembly interpreter", "JIT",
                  "1b cycles with the JIT"], rows)


def graphics_rows(res):
    rows = []
    for name in sorted(res):
        r = res[name]
        rows.append([name] + [pct(r[("v1bl", k)]["hw"] / r[("v1b", k)]["hw"] - 1)
                              for k in ("c", "asm")] + [fmt(r[("v1b", "asm")]["hw"])])
    rows.append(["**geometric mean**"] + [
        "**" + pct(geo((res[n][("v1b", k)]["hw"], res[n][("v1bl", k)]["hw"]) for n in res)) + "**"
        for k in ("c", "asm")] + [""])
    return table(["Scene and depth", "C kernels", "Assembly kernels",
                  "1b cycles, assembly kernels"], rows)


# ---- the estimates -----------------------------------------------------------------

def calls_text(c):
    return ", ".join(f"{k} {fmt(v)}" for k, v in sorted(c.items()) if v)


def lisp_rows(res):
    rows = []
    for name in sorted(res):
        row = [name]
        for mode in ("interpreted", "compiled"):
            e = res[name][mode]
            row += [pct(e["delta"] / e["hw"]), calls_text(e["calls"])]
        rows.append(row)
    rows.append(["**geometric mean**"] + sum(
        [["**" + pct(M.geomean(1 + res[n][m]["delta"] / res[n][m]["hw"] for n in res) - 1) + "**",
          ""] for m in ("interpreted", "compiled")], []))
    return table(["Program", "Interpreted", "Calls", "Compiled", "Calls"], rows)


def kernel_rows(res):
    from heron.studies.kernel import build as kb
    rows = []
    for name in res:
        r = res[name]
        rows.append([name, fmt(r["none"]["hw"])] +
                    [pct(r[b]["delta"] / r[b]["hw"]) for b in kb.BANKS] +
                    [calls_text(r["none"]["calls"])])
    return table(["Scenario", "1b cycles per operation (no banks)"] +
                 [f"Banks: {b}" for b in kb.BANKS] + ["Calls per operation"], rows)


# ---- the configurations ------------------------------------------------------------

def config_rows(asm, c, egret, graphics):
    def g(res, get):
        return pct(M.geomean(get(res[n], "v1bl") / get(res[n], "v1b") for n in res) - 1)
    keep = lambda res: {n: r for n, r in res.items() if n not in M.SKIP and n is not None}
    work = [("the suite by hand", keep(asm), lambda r, i, k: r[i]["cycles"][k] if k != "hw" else r[i]["rtl"]),
            ("the C versions", keep(c), lambda r, i, k: r[i]["cycles"][k] if k != "hw" else r[i]["rtl"])]
    for v, name in (("c", "C interpreter"), ("asm", "assembly interpreter"), ("jit", "JIT")):
        work.append((f"Egret, {name}", keep(egret),
                     lambda r, i, k, v=v: r[(i, v)]["cycles"][k] if k != "hw" else r[(i, v)]["hw"]))
    for v, name in (("c", "C kernels"), ("asm", "assembly kernels")):
        work.append((f"graphics, {name}", graphics,
                     lambda r, i, k, v=v: r[(i, v)]["cycles"][k] if k != "hw" else r[(i, v)]["hw"]))
    rows = []
    for name, res, get in work:
        rows.append([name] + [g(res, lambda r, i, k=k: get(r, i, k)) for k in ["hw"] + M.configs()])
    return table(["Workload", "1b hardware"] + M.configs(), rows)


def text():
    asm, c, egret, graphics = M.asm(), M.c(), M.egret(), M.graphics()
    est_asm, est_c = M.estimates("asm"), M.estimates("c")
    lisp, kernel = M.lisp(), M.kernel()
    out = ["# Report 0030: generated tables", "",
           "Generated by `heron link_register report --write` "
           "([studies/link_register](../../studies/link_register/README.md)); don't edit by hand.",
           "", "## Calls and returns on the 1b hardware", "",
           "Cycles of each instruction's microcode routine, the fetch of the next "
           "instruction included, with 1b's microcode and with v1bl's "
           "(`ucode.built(link=True)`).", ""]
    out += costs()
    out += ["", "## The suite by hand", "",
            "On the 1b hardware: the RTL model running each ISA's microcode. "
            "Estimate: the estimator on the 1b program (estimate.py). Link saves "
            "per call: `SAVE r7-rN` and `PUSH r7` per call executed.", ""]
    out += suite_rows(asm, est_asm)
    out += ["", "## The C versions", "",
            "As above, the C library included, with data objects aligned to 4 in "
            "both (`driver.MIN_DATA_ALIGN`).", ""]
    out += suite_rows(c, est_c)
    out += ["", "## Egret", "",
            "Change in cycles on the 1b hardware (hw.py) for each build of the VM, the "
            "empty program's start-up taken off each program.", ""]
    out += egret_rows(egret)
    out += ["", "## Graphics", "",
            "The graphics study's scenes, set-up phases left out, on the 1b hardware "
            "(hw.py).", ""]
    out += graphics_rows(graphics)
    out += ["", "## The Lisp, estimated", "",
            "Not ported: the estimator, with a frame built on entry taking r7 "
            "(lisp.py). Compiled: only the compiled code's running.", ""]
    out += lisp_rows(lisp)
    out += ["", "## The nucleus, estimated", "",
            "The kernel study's scenarios, per operation, on the 1b hardware "
            "(kernel.py).", ""]
    out += kernel_rows(kernel)
    out += ["", "## The configurations", "",
            "Geometric means of the change in cycles: on the 1b hardware, and in "
            "the six configurations of draft 1's timing model.", ""]
    out += config_rows(asm, c, egret, graphics)
    return "\n".join(out) + "\n"


def main(write=False):
    t = text()
    print(t)
    if write:
        os.makedirs(os.path.dirname(DOC), exist_ok=True)
        with open(DOC, "w") as f:
            f.write(t)
        print(f"wrote {DOC}")
    return 0
