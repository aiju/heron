"""The Lisp interpreting a program: studies/lisp's runtime for draft 2
(rt_v2/), all hand-written assembly (reader, interpreter, primitives and
a copying garbage collector), running a program of the kinds of work
Lisp programs do (bench.lisp): symbolic differentiation, a merge sort of
a list, closures and higher-order procedures, property lists, a vector
sieve and a small evaluator.

It stands for interpreted dynamic languages on Heron (the Lisp, Egret's
desktop): their time goes to the interpreter's dispatch on forms,
environment lookups, calls through closures, consing and collection, with
many calls, returns and indirect jumps and little arithmetic.

The machine starts from a saved image, as Lisp systems do: the runtime
with its prelude and bench.lisp's definitions read, evaluated and
collected (made here on the instruction-level simulator; `%save-image`
leaves all of memory as it is). The run is what comes after "the run" in
bench.lisp, read from the console. Reading the prelude would cost
470,000 instructions before any work, more than the `test` size allows.

Each part's unit costs 50,000-90,000 instructions, so `test` (n = 1, every
part once) is larger than the suite's usual `test` size. The expected
output comes from the Lisp's reference interpreter in Python
(studies/lisp/reference.py), on the whole of bench.lisp."""

import functools
import os

TITLE = "the Lisp's interpreter and collector running a mixed program"
PART = "asm"
CATEGORY = "interpreters"
SIZES = {"test": {"N": 1}, "ref": {"N": 4}}
MAX_CYCLES = 400_000_000

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = "; ---- the run ----"


def _program():
    with open(os.path.join(HERE, "bench.lisp"), "rb") as f:
        text = f.read()
    defs, run = text.split(RUN.encode())
    return defs, RUN.encode() + run


class SavedImage:
    """All of memory as the runtime left it at (%save-image), with the
    runtime image's symbols, as the harness wants an image."""

    def __init__(self, data, runtime):
        self.mem = {a: b for a, b in enumerate(data) if b}
        self.symbols = runtime.symbols
        self._runtime = runtime

    def extent(self):
        return min(self.mem), max(self.mem) + 1

    def code_bytes(self):
        return self._runtime.code_bytes()


@functools.lru_cache(None)
def saved_image():
    from heron.studies.lisp import machine
    runtime = machine.image((), "v2")
    defs, _ = _program()
    m = machine.new_machine("v2", (), runtime, defs + b"\n(gc)\n(%save-image)\n")
    m.run(max_cycles=100_000_000)
    if m.traps or not m.halted or bytes(m.dev.out):
        raise RuntimeError("making the saved image failed: " + bytes(m.dev.out).decode(errors="replace"))
    return SavedImage(bytes(m.mem), runtime)


def input(p):
    return b"(define n %d)\n" % p["N"] + _program()[1]


def build(p):
    return saved_image(), input(p)


def reference(p):
    from heron.studies.lisp import reference
    defs, run = _program()
    return reference.run(b"(define n %d)\n" % p["N"] + defs + run)
