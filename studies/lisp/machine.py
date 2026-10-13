"""Running Lisp programs on the draft 1b simulator.

A program is the console input; the runtime reads and evaluates it form
by form (language.md). The image is built once per set of features and
kept for the process.
"""

from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32, SimError
from heron.studies.v1_isa.timing32 import REFERENCE

import hashlib
import os

from . import build

_IMAGES = {}
COMPILER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compiler.lisp")


# Switching the top level to the compiler; it compiles the prelude again.
ACTIVATE = b"\n(define %toplevel cc:toplevel)\n"
RELOAD = b"\n(%reload-prelude)\n"


def compiler_text(bootstrap=False, features=()):
    """What a program is preceded by to be compiled: the compiler's options
    (the features), its source, then the switch to it. bootstrap: the
    compiler's source once more after that, so the compiler compiles
    itself before anything else."""
    with open(COMPILER, "rb") as f:
        src = f.read()
    options = b"(define cc:*options* '(" + " ".join(sorted(features)).encode() + b"))\n"
    return options + src + ACTIVATE + (src if bootstrap else b"") + RELOAD


# Features that need the extended instruction set (v1bx, isa.md)
ISA_FEATURES = {"tagged"}


def isa_name(features):
    return "v1bx" if ISA_FEATURES & set(features) else build.ISA


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
            "allocated": (self.word("gc_alloc") + hp - cur) & 0xFFFFFFFF,
            "copied": self.word("gc_copied"),
            "symbols": (self.word("sym_free") - self.image.symbols["sym_static"]) // 32,
        }


class Core:
    """A saved image: all of memory, as the machine left it at (%save-image).
    Booting from it skips start-up; the runtime goes on where it was."""

    def __init__(self, data):
        self.mem = {a: b for a, b in enumerate(data) if b}


_CORES = {}


def core(features=()):
    """The saved image with the compiler compiled by itself and the prelude
    compiled: a machine booted from it compiles a program straight away.
    Made once per set of features and kept in build/lisp/ (it takes 20
    seconds to make), named by a hash of what it was made from."""
    key = tuple(sorted(features))
    if key in _CORES:
        return _CORES[key]
    img = image(features)
    h = hashlib.sha256(repr(sorted(img.mem.items())).encode()
                       + compiler_text(True, features)).hexdigest()[:16]
    path = os.path.join(build.BUILD, f"core-{'-'.join(key) or 'base'}-{h}.bin")
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
    else:
        m = Machine32(isas.get(isa_name(features)), img,
                      inp=compiler_text(True, features) + b"\n(gc)\n(%save-image)\n")
        m.run(max_cycles=20_000_000_000)
        if m.traps or b"error" in bytes(m.dev.out):
            raise RuntimeError("making the image failed: " + bytes(m.dev.out).decode(errors="replace"))
        data = bytes(m.mem)
        os.makedirs(build.BUILD, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    _CORES[key] = Core(data)
    return _CORES[key]


def start(text, features=(), compiled=False, reference=REFERENCE):
    """A machine about to run a program (bytes): the image's symbols, and the
    machine. compiled: compile the program, starting from the saved image
    with the compiler (core). reference: the configuration whose cycles the
    machine's cycle counter counts."""
    img = image(features)
    boot = core(features) if compiled else img
    return img, Machine32(isas.get(isa_name(features)), boot, inp=text, reference=reference)


def run(text, features=(), max_cycles=4_000_000_000, trace=None, compiled=False,
        reference=REFERENCE):
    """Run a program (bytes) to the end: a Run."""
    img, m = start(text, features, compiled, reference)
    if trace is not None:
        m.trace = trace
    err = None
    try:
        m.run(max_cycles=max_cycles)
    except SimError as e:
        err = str(e)
    if err is None and m.traps:
        # Address errors and tag traps are the runtime's type checks;
        # anything else is a bug.
        for pc, what in m.traps:
            if not ("misaligned" in what or what in ("tag check", "tagged overflow")):
                err = f"trap at {pc:X}: {what}"
                break
    return Run(img, m, err)
