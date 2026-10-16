"""The measurements behind the report: every program in every
configuration, and what proposed changes to the instruction set would
save, costed from the counts of the runs as built.

A run's numbers are kept in build/curlew/measure-*.json, keyed by a hash
of the compiler and runtime sources and the program, so the report is
made again only for what changed.
"""

import hashlib
import json
import os
import re
from collections import Counter

from . import build, machine, testing
from .profile import Profile

CONFIGS = ["base", "tagged", "tagarith", "onereg", "nostackcheck", "noindcheck", "noupdtail",
           "nostrict", "nospec", "noinline"]
CONFIG = machine.CONFIG

# D32-separate cycles of the instructions the what-ifs change (measured
# with the timing model; see the report)
TST_IMM = 3         # TST r, #1 (two parcels)
TST_QUICK = 2       # TST r, rs: what a one-parcel TST r, #q would cost
BRANCH = 2          # Bcc, taken or not
ONE_INSN_CHECK = 2  # a test of bit 0 that branches, or a trap check (TTST)


def source_hash():
    h = hashlib.sha256()
    for root in (build.HERE, build.RT):
        for f in sorted(os.listdir(root)):
            if f.endswith((".py", ".s", ".cw")):
                with open(os.path.join(root, f), "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()[:16]


def features_of(config):
    return () if config == "base" else (config,)


def run_one(p, config):
    r = machine.run(p.text, p.input, features_of(config))
    if r.error or r.output != p.expected:
        raise RuntimeError(f"{p.name} ({config}): wrong output: {r.error or testing.diff(r.output, p.expected)}")
    m = r.machine
    st = r.stats()
    out = {
        "instructions": m.instructions,
        "cycles": m.cycles_for(CONFIG),
        "cycles_all": {c: m.cycles_avg(c) for c in ("D16-separate", "D32-separate", "D32-overlap", "D32-wide")},
        "allocated": st["allocated"],
        "gc_count": st["gc_count"],
        "copied": st["copied"],
        "tag_traps": st["tag_traps"],
        "code_bytes": r.image.symbols["code_end"] - r.image.symbols["code_start"],
    }
    if config in ("base", "tagged", "onereg", "tagarith"):
        prof = Profile(r)
        out["groups"] = dict(prof.groups())
        out["by_cat"] = dict(prof.by_cat)
        out["count_cat"] = dict(prof.count_cat)
        out["checks"] = prof.checks()
    if config == "base":
        out["mix"] = dict(prof.mix().most_common())
        out["sites"] = sites(r, prof)
        out["whatif"] = whatifs(r, prof)
        out["usage"] = usage(r, prof)
    if config == "tagged":
        out["trap_cycles"] = trap_cycles(r, prof)
    return out


def sites(r, prof):
    """Each evaluation check: [checks, values found unevaluated, of which
    indirections, category]."""
    syms = r.image.symbols
    out = []
    for site, slow, cat in r.compiled.check_sites:
        a, b = syms.get(site), syms.get(slow)
        if a is None or b is None:
            continue
        n = prof.counts.get(a, 0)
        if not n:
            continue
        hits = prof.counts.get(b, 0)
        # the indirection test's taken path: the instruction after the
        # slow path's compare and branch
        ind = 0
        pcs = sorted(pc for pc in prof.text if pc > b)[:4]
        for pc in pcs:
            if prof.cats.get(pc, "").endswith("ind"):
                ind = prof.counts.get(pc, 0)
                break
        out.append([n, hits, ind, cat])
    return out


LOAD_RE = re.compile(r"^MOV\s+(r\d+),\s*\[(r\d+)\s*([+-])\s*(\d+)\]")
STORE_RE = re.compile(r"^MOV\s+\[(r\d+)\s*([+-])\s*(\d+)\],")


def whatifs(r, prof):
    """Cycles each proposed change would save in the run as built."""
    counts, cats, text, cyc = prof.counts, prof.cats, prof.text, prof.cycles
    pcs = sorted(text)
    nxt = {a: b for a, b in zip(pcs, pcs[1:])}
    prev = {b: a for a, b in zip(pcs, pcs[1:])}
    out = Counter()
    for pc, n in counts.items():
        cat = cats.get(pc, "")
        t = text.get(pc, "")
        if cat in ("evalt", "entryt", "entert"):
            # a one-parcel TST r, #q
            if t.endswith("#1"):
                out["quick_tst"] += n * (TST_IMM - TST_QUICK)
            # a one-instruction test of the tag: TST and its branch in one
            out["one_insn_check"] += n * (TST_IMM + BRANCH - ONE_INSN_CHECK)
            # the sign bit as the mark, set by the load before: no TST
            p = prev.get(pc)
            m = LOAD_RE.match(text.get(p, "")) if p is not None else None
            reg = t.split()[1].rstrip(",") if len(t.split()) > 1 else ""
            if m and m.group(1) == reg and cat == "evalt":
                out["sign_tag_checks"] += n * TST_IMM
                out["checks_after_load"] += n
        if cat in ("heapchk",):
            out["guard_heap"] += cyc.get(pc, 0)
        if cat == "stkchk":
            out["guard_stack"] += cyc.get(pc, 0)
        # a store of a constant: MOV r12, #c then a store of r12
        if t.startswith("MOV  r12, #") and pc in nxt and STORE_RE.match(text.get(nxt[pc], "")) \
                and text[nxt[pc]].endswith("r12"):
            out["store_imm"] += cyc.get(pc, 0)
        # a field at a small offset from a tagged pointer: one parcel, 1 cycle less
        m = LOAD_RE.match(t)
        if m and m.group(2) not in ("r14", "sp") and int(m.group(4)) % 4 != 0 and int(m.group(4)) < 64:
            out["field_mode"] += n
            out["field_accesses"] += n
        m = STORE_RE.match(t)
        if m and m.group(1) not in ("r14", "sp") and int(m.group(3)) % 4 != 0 and int(m.group(3)) < 64:
            out["field_mode"] += n
            out["field_accesses"] += n
        if cat.endswith("hit"):
            out["hits"] += n
        if t.startswith("INC  r") and cat == "alloc":
            out["thunks_tagged"] += n
    # the sign bit as the mark costs a cycle-and-a-half more per thunk made
    # (setting bit 31) and per value evaluated through a slow path (clearing it)
    out["sign_tag"] = out["sign_tag_checks"] - 4 * out["thunks_tagged"] - 3 * out["hits"]
    return dict(out)


def usage(r, prof):
    """Executions of draft 2's instructions and modes the code uses."""
    out = Counter()
    for pc, n in prof.counts.items():
        t = prof.text.get(pc, "")
        op = t.split()[0] if t else ""
        out["all"] += n
        if op in ("SAVE", "RESTORE", "LDM", "STM", "DBNZ", "MOVS", "CLR", "LEA", "SETLT", "TMOV", "TTST",
                  "TADD", "TSUB", "TCMP", "DIVS", "MULS"):
            out[op] += n
        if re.search(r"\[r14 \+ (\d+)\]", t) and int(re.search(r"\[r14 \+ (\d+)\]", t).group(1)) % 4 == 0 \
                and int(re.search(r"\[r14 \+ (\d+)\]", t).group(1)) <= 60:
            out["mode E"] += n
        if t.startswith(("CALL [", "JMP  [r6")):
            out["call through memory"] += n
        if t.startswith("RET"):
            out["RET"] += n
        if t.startswith("CALL "):
            out["CALL"] += n
        if op == "SAVE" and "r7" in t or (t.startswith("MOV  -[sp], r7")):
            out["r7 saved"] += n
        if op == "SAVE":
            a, b = re.findall(r"r(\d+)", t)
            out["saved registers"] += n * (int(b) - int(a) + 1)
            out["saves"] += n
        if t.startswith("MOV  -[sp], r"):
            out["pushes"] += n
        if t.startswith("CLR  [sp +"):
            out["dead slots cleared"] += n
        if prof.cats.get(pc) in ("evalt", "entryt"):
            out["checks"] += n
    return dict(out)


def trap_cycles(r, prof):
    """In a run with trap checks: the cycles of the trap handler, and of
    entering it (the trapping checks' extra cycles)."""
    return {"handler": prof.by_cat.get("rt:trap", 0), "traps": r.stats()["tag_traps"]}


def measure(names=None, configs=CONFIGS, refresh=False, verbose=True):
    """{program: {config: numbers}}, from the cache where it's current."""
    os.makedirs(build.BUILD, exist_ok=True)
    key = source_hash()
    path = os.path.join(build.BUILD, f"measure-{key}.json")
    cache = {}
    if os.path.exists(path) and not refresh:
        with open(path) as f:
            cache = json.load(f)
    out = {}
    for p in testing.programs(names, tests=False):
        ph = hashlib.sha256((p.text + repr(p.input)).encode()).hexdigest()[:12]
        out[p.name] = {}
        for c in configs:
            k = f"{p.name}:{c}:{ph}"
            if k not in cache:
                if verbose:
                    print(f"  {p.name} ({c})", flush=True)
                cache[k] = run_one(p, c)
                with open(path, "w") as f:
                    json.dump(cache, f)
            out[p.name][c] = cache[k]
    return out
