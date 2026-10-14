"""Small routines an operating system leans on, on plain drafts 1a and 1b:
zeroing and copying a page, and the costs of the ways a linker can wire up
calls and globals (dynamic linking). Each is a loop run N and 2N times;
the difference over N is one iteration.

The programs are micro/<name>_<isa>.s, with variants in `.if V0` ...
blocks (build.preprocess).
"""

import os

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32

from .build import preprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MICRO = os.path.join(HERE, "micro")
CONFIGS = ("D32-separate", "D32-overlap", "D32-wide")

# name: (variants and what they are, the loop-only variant if any, N)
ROUTINES = {
    "zero": (["a loop of word stores", "unrolled by 8", "SAVE r1-r8 (store-multiple, 8 words)",
              "SAVE r1-r14 (store-multiple, 14 words)"], None, 2),
    "copy": (["a loop of word loads and stores", "unrolled by 8",
              "RESTORE/SAVE r1-r8 (load/store-multiple, 8 words)",
              "RESTORE/SAVE r1-r12 (12 words)"], None, 2),
    "calls": (["direct", "import table (IAT)", "PLT stub through the GOT",
               "table at a base register (Amiga library, COM)", "virtual call (object, table)",
               "no call"], 5, 50),
    "globals": (["absolute", "PC-relative", "through the GOT", "base register", "no load"], 4, 50),
    "coswitch": (["a switch between user-level threads, there and back", "a call and return"],
                 1, 50),
}


def cycles(name, isa, variant, n):
    path = os.path.join(MICRO, f"{name}_{isa}.s")
    with open(path) as f:
        text = f"N = {n}\n" + preprocess(f.read(), {f"V{variant}"})
    a = asmcore.Assembler(isas.get(isa))
    a.load(path, text=text)
    img = a.assemble()
    m = Machine32(isas.get(isa), img)
    m.run(max_cycles=500_000_000)
    if m.traps:
        raise RuntimeError(f"{name} {isa} V{variant}: {m.traps[0]}")
    return {c: m.cycles_for(c) for c in CONFIGS}


def per_iteration(name, isa, variant):
    texts, base, n = ROUTINES[name]
    a, b = cycles(name, isa, variant, n), cycles(name, isa, variant, 2 * n)
    out = {c: (b[c] - a[c]) / n for c in CONFIGS}
    if base is not None and variant != base:
        a, b = cycles(name, isa, base, n), cycles(name, isa, base, 2 * n)
        out = {c: out[c] - (b[c] - a[c]) / n for c in CONFIGS}
    return out


def table(names=None):
    """{name: {isa: [per-iteration cycles by config, per variant]}}"""
    out = {}
    for name, (texts, base, n) in ROUTINES.items():
        if names and name not in names:
            continue
        out[name] = {isa: [per_iteration(name, isa, v) for v in range(len(texts)) if v != base]
                     for isa in ("v1a", "v1b")}
    return out


# The ready queue in C (sched.c, through the C compiler, with CLZ as an
# assembly helper) against the same functions by hand (sched_v1b.s), and
# the loop and calls alone (sched_empty_v1b.s).
SCHED = {"C": ["sched_main.c", "sched.c", "clz_v1b.s"],
         "assembly": ["sched_main.c", "sched_v1b.s"],
         "empty": ["sched_main.c", "sched_empty_v1b.s"]}


def _c_cycles(files, n):
    from heron.studies.c_compiler.cc import driver
    p = driver.Program("v1b", 1, False)
    for f in files:
        path = os.path.join(MICRO, f)
        if f.endswith(".s"):
            with open(path) as fh:
                p.add_object(driver.assemble("v1b", fh.read(), path))
        else:
            p.add_file(path, (), {"N": str(n)})
    p.add_library()
    m = driver.run_image(p.link(), "v1b")
    if m.error:
        raise RuntimeError(m.error)
    return {c: m.cycles_for(c) for c in CONFIGS}


def sched():
    """Cycles of one enqueue and one dequeue, C and by hand, by config."""
    per = {}
    for k, files in SCHED.items():
        a, b = _c_cycles(files, 50), _c_cycles(files, 100)
        per[k] = {c: (b[c] - a[c]) / 50 for c in CONFIGS}
    return {k: {c: per[k][c] - per["empty"][c] for c in CONFIGS} for k in ("C", "assembly")}
