"""Running Lisp programs on the draft 1b simulator.

A program is the console input; the runtime reads and evaluates it form
by form (language.md). The image is built once per set of features and
kept for the process.
"""

from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32, SimError

import os

from . import build

_IMAGES = {}
COMPILER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compiler.lisp")


def compiler_text():
    """The compiler's source: a program that starts with it is compiled."""
    with open(COMPILER, "rb") as f:
        return f.read()


def image(features=()):
    key = tuple(sorted(features))
    if key not in _IMAGES:
        _IMAGES[key] = build.build(key)
    return _IMAGES[key]


class Run:
    """A finished run: the machine, its output and how it ended."""

    def __init__(self, img, m, error):
        self.image = img
        self.machine = m
        self.output = bytes(m.dev.out)
        self.error = error

    def word(self, name):
        """The 32-bit variable at a runtime symbol."""
        a = self.image.symbols[name]
        return int.from_bytes(self.machine.mem[a:a + 4], "little")

    def stats(self):
        """The runtime's own counters: collections, bytes allocated and copied."""
        hp = self.machine.r[14]
        cur = self.word("cur_start")
        return {
            "gc_count": self.word("gc_count"),
            "allocated": self.word("gc_alloc") + hp - cur,
            "copied": self.word("gc_copied"),
            "symbols": (self.word("sym_free") - self.image.symbols["sym_static"]) // 32,
        }


def run(text, features=(), max_cycles=4_000_000_000, trace=None, compiled=False):
    """Run a program (bytes) to the end: a Run. compiled: load the compiler
    first, so the program is compiled form by form."""
    if compiled:
        text = compiler_text() + b"\n" + text
    img = image(features)
    m = Machine32(isas.get(build.ISA), img, inp=text)
    if trace is not None:
        m.trace = trace
    err = None
    try:
        m.run(max_cycles=max_cycles)
    except SimError as e:
        err = str(e)
    if err is None and m.traps:
        pc, what = m.traps[0]
        # Address errors are the runtime's type checks; anything else is a bug.
        if "misaligned" not in what:
            err = f"trap at {pc:X}: {what}"
    return Run(img, m, err)
