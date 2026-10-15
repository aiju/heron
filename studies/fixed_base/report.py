"""The tables of report 0029: Egret, the Lisp and the nucleus on 1b with
[rT + 4R]. `heron fixed_base report` prints them (about 15 minutes);
--write puts them in the report's results.md."""

import os
import sys

from heron import ROOT

from . import experiments as X

REPORT_DIR = os.path.join(ROOT, "reports", "0029-report-fixed-base-mode")
SEP, WIDE = X.CONFIGS
MOVST = {"MOV", "ST"}
SHORT = range(4, 17, 4)         # RFC 0028 10.1's MOV/ST [R + 4k], k = 1-4


def pct(x):
    return f"{x:+.2f}%"


def change(row, rt, c):
    return 100 * (row[rt][c] / row[None][c] - 1)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] + ["---:"] * (len(head) - 1)) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def egret_section(runs):
    """runs: {variant: X.egret(...)}"""
    asm, jit, c = runs["asm"], runs["jit"], runs["c"]
    names = list(asm)
    s = ["## Egret\n\n",
         "Each program's own cycles (less start-up and compiling it, as report 0017 counts them), "
         "with the whole VM assembled for 1b with `[rT + 4R]` and the JIT emitting it, against "
         "plain 1b. `r11` is the frame record in the hand-written interpreter and the JIT, `r9` "
         "the frame's slots. D32-separate, then the geometric means on D32-wide too.\n\n"]
    rows = []
    for n in names:
        ok = all(r[k]["ok"] for r in (asm[n], jit[n], c[n]) for k in r if k != "scan")
        rows.append([n + ("" if ok else " (wrong output)"), pct(change(asm[n], 11, SEP)),
                     pct(change(jit[n], 11, SEP)), pct(change(jit[n], 9, SEP)),
                     pct(change(c[n], 11, SEP))])
    for cfg in (SEP, WIDE):
        rows.append([f"**geomean, {cfg}**"] + [
            f"**{pct(100 * (X.geomean(r[n][rt][cfg] / r[n][None][cfg] for n in names) - 1))}**"
            for r, rt in ((asm, 11), (jit, 11), (jit, 9), (c, 11))])
    s.append(table(["Program", "Interpreter, rT = r11", "JIT, rT = r11", "JIT, rT = r9",
                    "C loop, rT = r11"], rows))
    s.append("\nFrom the scans of the baseline runs: the cycles each one-parcel form would save, "
             "as the mean over the programs, D32-separate / D32-wide. *rT: MOV, ST* is the loads "
             "and stores, three cells of draft 2's map (`MOV`, `MOVS` and the store), *+ LEA* a "
             "fourth; *every operation* adds the ALU operations and `JMP [rT + 4R]`. *[R + 4k]* is RFC 0028 10.1's other option, `MOV` and `ST` "
             "with k = 1–4 and any base; *every [R + 4..60]* is 1a's short offsets, any base and "
             "operation.\n\n")
    rows = []
    for label, runs_, rt in (("Interpreter, r11", asm, 11), ("JIT, r11", jit, 11), ("JIT, r9", jit, 9),
                             ("C loop, r11", c, 11)):
        sc = [runs_[n]["scan"] for n in names]

        def both(**kw):
            return " / ".join(f"{mean(x.pct(x.saves(**kw), cfg) for x in sc):.2f}%" for cfg in (SEP, WIDE))
        rows.append([label, both(bases={rt}, ops=MOVST), both(bases={rt}, ops=MOVST | {"LEA"}),
                     both(bases={rt}), both(disps=SHORT, ops=MOVST), both()])
    s.append(table(["Build, rT", "rT: MOV, ST", "rT: + LEA", "rT: every operation",
                    "MOV/ST [R + 4k], k = 1–4", "Every [R + 4..60] word"], rows))
    s.append("\nWhich operations the accesses through rT are. *MOVS* is a load a branch on N or Z "
             "follows directly, which reads its flags: in draft 2, where `MOV` leaves the flags "
             "alone, it would be `MOVS`.\n\n")
    rows = []
    for label, runs_, rt in (("Interpreter, r11", asm, 11), ("JIT, r11", jit, 11), ("JIT, r9", jit, 9),
                             ("C loop, r11", c, 11)):
        tot = {}
        for n in names:
            for op, k in runs_[n]["scan"].ops(rt).items():
                tot[op] = tot.get(op, 0) + k
        t = sum(tot.values()) or 1
        rows.append([label, ", ".join(f"{op} {100 * k / t:.0f}%" for op, k in
                                      sorted(tot.items(), key=lambda kv: -kv[1]) if k / t >= 0.005)])
    s.append(table(["Build, rT", "Operations"], rows))
    return "".join(s)


def lisp_section(runs):
    s = ["\n## The Lisp\n\n",
         "Compiled, with v1bx's tagged operations, over the compiled forms' running. "
         "*Fields at 4..60:* executed word accesses `[R + 4k]` through the best single register, "
         "which `[rT + 4R]` as it is would make one parcel. *Closure in rT:* what keeping the "
         "current closure in rT would save, net of setting it on entry (an estimate, "
         "experiments.lisp). *Runtime variables:* executed accesses to the words at "
         "0x100–0x13F, which a globals pointer in rT would reach.\n\n"]
    rows = []
    for n, r in runs.items():
        sc = r["scan"]
        bb = sc.by_base()
        best = bb.most_common(1)[0] if bb else (None, 0)
        rows.append([n, f"{100 * best[1] / sc.cycles[SEP]:.2f}%",
                     f"{100 * r['reads'] / sc.instr:.2f}%",
                     f"{100 * r['closures'][SEP] / sc.cycles[SEP]:.2f}%",
                     f"{100 * r['closures'][WIDE] / sc.cycles[WIDE]:.2f}%",
                     f"{100 * r['runtime_vars'] / sc.instr:.2f}%"])
    rows.append(["**mean**"] + [f"**{mean(float(r[i][:-1]) for r in rows):.2f}%**" for i in range(1, 6)])
    s.append(table(["Program", "Fields at 4..60, best register: cycles saved",
                    "Free-variable reads, of instructions", "Closure in rT, D32-separate",
                    "Closure in rT, D32-wide", "Runtime variables, of instructions"], rows))
    return "".join(s)


def kernel_section(runs, sizes):
    s = ["\n## The nucleus\n\n",
         "Cycles per operation on D32-separate (the nucleus's own, for the scenarios that only "
         "keep it busy), and the change with the nucleus assembled for `[rT + 4R]` as it is. In "
         "the IPC paths `r6` is the other thread's TCB, `r8` the current thread's (copied from "
         "`r14` with banks), and `r14` the current thread between traps with banks. The last "
         "two columns are from the scans: the cycles a short form would save, per "
         "operation.\n\n"]
    rows = []
    for (name, b), r in runs.items():
        sc, ops = r["scan"], r["ops"]
        po = r[None][SEP]
        rows.append([f"{name}, {b}", f"{po:.0f}", pct(change(r, 6, SEP)), pct(change(r, 8, SEP)),
                     pct(change(r, 14, SEP)),
                     f"{sc.saves(disps=SHORT, ops=MOVST)[SEP] / ops:.0f} ({100 * sc.saves(disps=SHORT, ops=MOVST)[SEP] / ops / po:.1f}%)",
                     f"{sc.saves()[SEP] / ops:.0f} ({100 * sc.saves()[SEP] / ops / po:.1f}%)"])
    s.append(table(["Scenario, banks", "Cycles", "rT = r6", "rT = r8", "rT = r14",
                    "MOV/ST [R + 4k], k = 1–4", "Every [R + 4..60] word"], rows))
    s.append("\nThe nucleus's code, in bytes:\n\n")
    s.append(table(["Banks", "1b", "rT = r6", "rT = r8", "rT = r14"],
                   [[b, v[None]] + [f"{v[rt]} ({100 * (v[rt] / v[None] - 1):+.1f}%)" for rt in (6, 8, 14)]
                    for b, v in sizes.items()]))
    tot = {}
    for r in runs.values():
        for op, k in r["scan"].ops(6).items():
            tot[op] = tot.get(op, 0) + k
    t = sum(tot.values()) or 1
    s.append("\nThe accesses through `r6` are (*MOVS* as for Egret) " + ", ".join(
        f"{op} {100 * k / t:.0f}%" for op, k in sorted(tot.items(), key=lambda kv: -kv[1])) + ".\n")
    return "".join(s)


def generate(log=None):
    egret = {v: X.egret(v, [11, 9] if v == "jit" else [11], log=log) for v in ("asm", "jit", "c")}
    lisp = X.lisp(log=log)
    kernel = X.kernel([6, 8, 14], log=log)
    sizes = X.nucleus_size([6, 8, 14])
    head = ("# Report 0029: generated tables\n\n"
            "Written by `heron fixed_base report --write` "
            "([studies/fixed_base](../../studies/fixed_base/README.md)); "
            "don't edit by hand.\n\n")
    return head + egret_section(egret) + lisp_section(lisp) + kernel_section(kernel, sizes)


def main(write=False):
    text = generate(log=lambda m: print(m, file=sys.stderr, flush=True))
    if write:
        os.makedirs(REPORT_DIR, exist_ok=True)
        with open(os.path.join(REPORT_DIR, "results.md"), "w") as f:
            f.write(text)
    print(text)
