"""Measuring the Lisp: how many cycles a program takes, interpreted and
compiled, and where they go.

Compiled, a program is the compiler (interpreted at first) plus the
program, compiled and run form by form, so the cycles of running the
program are separated from the compiler's: the runtime logs the cycle
counter where each compiled form starts and stops running (%run-begin and
%run-end, in mark_log). The machine's cycle counter counts the
configuration used for the measurements, D32-separate.

A profile of the running alone takes a second, identical run that stops
at each logged boundary (the cycle limit is the breakpoint) and takes a
snapshot of the simulator's per-instruction counts; the differences
across the windows are the running's own. Compiled code's cycles are
broken down by what each instruction is for: the compiler records a
category for every parcel it writes in the category map (CATMAP), in the
order of cc:cat-names in compiler.lisp.
"""

import bisect
from collections import Counter

from heron.studies.v1_isa import timing32
from heron.studies.v2_isa import sim as sim2

from . import machine

CONFIG = "D32-separate"         # the 1b hardware's configuration (report 0012)
CATEGORIES = ["other", "var", "global", "unbound", "const", "call", "entry", "return",
              "temp", "type", "pred", "arith", "overflow", "test", "alloc", "access",
              "bounds", "stub"]

# the collector's routines: its cycles are reported apart from the program's
GC_ROUTINES = {"rt:gc", "rt:fwd", "rt:fwd_range", "rt:objsize"}

_EMPTY = {}


def cycles_of(isa):
    """The timing model's cycles for a timing key, for the ISA's machine."""
    return sim2.cycles if isa == "v2" else timing32.cycles


def empty_cycles(features=(), isa="v1b"):
    """The cycles of an empty program: start-up and the prelude."""
    key = (isa,) + tuple(sorted(features))
    if key not in _EMPTY:
        r = machine.run(b"", features, reference=CONFIG, isa=isa)
        _EMPTY[key] = r.machine.cycles_for(CONFIG)
    return _EMPTY[key]


def windows(run):
    """[(begin, end)]: the cycle counter where compiled forms started and
    stopped running."""
    m, sym = run.machine.mem, run.image.symbols
    n = run.word("marks") // 4
    base = sym["mark_log"]
    words = [int.from_bytes(m[base + 4 * k:base + 4 * k + 4], "little") for k in range(n)]
    out, begin = [], None
    for w in words:
        if w & 1:
            begin = w & ~1
        elif begin is not None:
            out.append((begin, w))
            begin = None
    return out


def split(prof):
    """(mutator, collector) cycles of a profile."""
    gc = sum(v for k, v in prof.items() if k in GC_ROUTINES)
    return sum(prof.values()) - gc, gc


def measure(text, features=(), compiled=False, isa="v1b"):
    """Cycles to run a program: {'cycles', 'total', 'run'}. Interpreted,
    'cycles' leaves out start-up and the prelude; compiled, it is the
    compiled forms' running alone, and 'total' includes compiling them."""
    r = machine.run(text, features, compiled=compiled, reference=CONFIG, isa=isa)
    if r.error:
        raise RuntimeError(r.error)
    total = r.machine.cycles_for(CONFIG)
    if compiled:
        cycles = sum(e - b for b, e in windows(r))
    else:
        cycles = total - empty_cycles(features, isa)
    return {"cycles": cycles, "total": total, "run": r}


def window_counts(text, features, run, isa="v1b"):
    """Counter of (pc, timing key) -> executions inside the windows of a
    compiled run, by rerunning it with breakpoints at their edges."""
    img, m = machine.start(text, features, compiled=True, reference=CONFIG, isa=isa)
    total = Counter()
    snap = None

    def counts():
        return Counter({(pc, k): n for pc, k, n in m._m.pc_keys()})

    for b, e in windows(run):
        for edge, sign in ((b, -1), (e, 1)):
            try:
                m._m.run(edge)
            except machine.SimErrors:
                pass        # the breakpoint
            c = counts()
            for key, n in c.items():
                total[key] += sign * n
    return total


def run_counts(run):
    """Counter of (pc, timing key) -> executions over a whole run."""
    return Counter({(pc, k): n for pc, k, n in run.machine._m.pc_keys()})


def profile(text, features=(), compiled=True, run=None, counts=None, isa="v1b"):
    """Where the cycles go: Counter of category -> cycles. Compiled code by
    its category ('code:var', ...), the runtime by routine ('rt:cons', ...).
    Compiled programs: over their windows; interpreted ones: over the whole
    run. counts: the run's counts, if they have been taken already."""
    if run is None:
        run = machine.run(text, features, compiled=compiled, reference=CONFIG, isa=isa)
    if counts is None:
        counts = window_counts(text, features, run, isa) if compiled else run_counts(run)
    cycles = cycles_of(isa)
    img = run.image
    labels = sorted((st.addr, st.label) for st in img.stmts
                    if st.kind == "label" and "." not in st.label)
    starts = [a for a, _ in labels]
    code_base = img.symbols["gen_end"]
    catmap = img.symbols["CATMAP"]
    mem = run.machine.mem
    out = Counter()
    for (pc, key), n in counts.items():
        if n == 0:
            continue
        cyc = n * cycles(key, CONFIG)
        if pc is None:
            name = "rt:(interrupts)"
        elif pc >= code_base:
            cat = mem[catmap + (pc - code_base) // 2]
            name = "code:" + (CATEGORIES[cat] if cat < len(CATEGORIES) else "?")
        else:
            k = bisect.bisect_right(starts, pc) - 1
            name = "rt:" + (labels[k][1] if k >= 0 else "?")
        out[name] += cyc
    return out

