"""Page references of the bigger programs the other studies run, for
sizing the MMU (report 0020): how many pages a program touches, how often
the PC moves to another page, and how often translation caches of
various sizes would miss.

Each workload runs on plain draft 1b, as its study runs it, with the
simulator's page statistics on (studies/v1_isa/isa/src/pages.rs): every
instruction fetch and every data access outside the I/O page, by 4 KB
virtual page. It is one program in one address space, so the misses are
those of a cache that is never flushed: what a tagged cache with enough
contexts would see.
"""

import os
from contextlib import contextmanager

from heron import ROOT
from heron.studies.v1_isa import sim32

SHIFT = 12                  # 4 KB pages
CONFIG = "D32-separate"
LRU_SIZES = [4, 8, 16, 32, 64, 128]


@contextmanager
def counting(shift=SHIFT):
    """Every Machine32 made inside counts page references."""
    made = []
    orig = sim32.Machine32.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self._m.start_page_stats(shift)
        made.append(self)
    sim32.Machine32.__init__ = init
    try:
        yield made
    finally:
        sim32.Machine32.__init__ = orig


def _lisp(name, compiled):
    def run():
        from heron.studies.lisp import machine
        path = os.path.join(ROOT, "studies", "lisp", "programs", name + ".lisp")
        with open(path, "rb") as f:
            text = f.read()
        r = machine.run(text, compiled=compiled)
        if r.error:
            raise RuntimeError(r.error)
        return r.machine
    return run


def _egret(name, variant):
    def run():
        from heron.studies.egret import build
        path = os.path.join(ROOT, "studies", "egret", "programs", name + ".eg")
        with open(path) as f:
            src = f.read()
        return build.machine(src, variant=variant)
    return run


def _graphics(scene, depth):
    def run():
        from heron.studies.graphics import build, run as grun
        img = build.image("v1b", kernels=True)
        with counting() as made:
            grun.run(img, "v1b", scene, depth)
        return made[-1]
    return run


def _c(name):
    def run():
        from heron.studies.c_compiler.cc import driver
        from heron.studies.v1_isa import testing
        path = os.path.join(ROOT, "studies", "c_compiler", "programs", name + ".c")
        _, img, _ = driver.build([path], "v1b")
        inp = testing.metadata(os.path.join(testing.program_dir("v1b"), name + ".s"))["input"]
        m = driver.run_image(img, "v1b", inp=inp, max_cycles=2_000_000_000)
        if m.error:
            raise RuntimeError(m.error)
        return m
    return run


def _asm(name):
    def run():
        from heron.studies.v1_isa import testing
        r = testing.run_program(os.path.join(testing.program_dir("v1b"), name + ".s"))
        if r["error"]:
            raise RuntimeError(r["error"])
        return r["machine"]
    return run


# name, what it is, how to run it
WORKLOADS = [
    ("lisp-boyer-c", "Lisp: compile boyer on the machine, then run it", _lisp("boyer", True)),
    ("lisp-meta-c", "Lisp: compile and run a metacircular interpreter", _lisp("meta", True)),
    ("lisp-boyer-i", "Lisp: boyer, interpreted", _lisp("boyer", False)),
    ("egret-richards-jit", "Egret: richards, compiled by the JIT", _egret("richards", "jit")),
    ("egret-json-i", "Egret: json, interpreted", _egret("json", "asm")),
    ("gfx-wm-8", "Graphics: the window manager scene at 8 bits per pixel", _graphics("wm", 3)),
    ("gfx-text-1", "Graphics: the text scene at 1 bit per pixel", _graphics("text", 0)),
    ("c-wordfreq", "C: word frequencies with a hash table", _c("wordfreq")),
    ("asm-vm", "Assembly: the bytecode interpreter", _asm("vm")),
]


class Stats:
    def __init__(self, name, text, m):
        self.name, self.text = name, text
        self.instructions = m.instructions
        self.cycles = m.cycles_for(CONFIG)
        self.p = m._m.page_stats()

    def lru_misses(self, stream, n):
        s = self.p[stream]
        return s["cold"] + sum(s["hist"][n:])

    def direct_misses(self, stream, size):
        return self.p[stream]["direct"][self.p["direct_sizes"].index(size)]

    def per_kilo(self, x):
        return 1000 * x / self.instructions


def measure(names=None):
    out = []
    for name, text, run in WORKLOADS:
        if names and name not in names:
            continue
        if name.startswith("gfx"):
            m = run()
        else:
            with counting() as made:
                run()
            m = made[-1]
        out.append(Stats(name, text, m))
    return out


def table(stats):
    lines = ["| Workload | Instructions | Pages: code / data | PC page changes per 1000 instr. |"
             + "".join(f" LRU {n} |" for n in LRU_SIZES) + " direct 64 | direct 256 |",
             "|---|---:|---:|---:|" + "---:|" * len(LRU_SIZES) + "---:|---:|"]
    for s in stats:
        row = (f"| {s.name} | {s.instructions / 1e6:.1f} M | {s.p['fetch']['pages']} / "
               f"{s.p['data']['pages']} | {s.per_kilo(s.p['fetch_page_changes']):.1f} |")
        for n in LRU_SIZES:
            row += f" {s.per_kilo(s.lru_misses('both', n)):.2f} |"
        row += (f" {s.per_kilo(s.direct_misses('both', 64)):.2f} |"
                f" {s.per_kilo(s.direct_misses('both', 256)):.2f} |")
        lines.append(row)
    return "\n".join(lines)
