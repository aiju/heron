"""The Lisp (studies/lisp) under the estimator (estimate.py), not ported.

Its calling convention passes argument 5 in r7 and keeps every register
but r13 and r14 caller-saved, and compiled code tail-calls with JMP after
popping its frame, so a port would move argument 5 and the frame code with
it. The estimate takes the port as the estimator does with frames: a
compiled function builds its frame on entry (SAVE r3-rN of its
arguments), and a port would save r7 there too, with the arguments when
the range reaches it and pushed otherwise, whether or not the call then
calls anything.

Interpreted, a program's calls are those of its run less the empty
program's (start-up and the prelude). Compiled, only the calls made while
compiled code runs count (the windows of studies/lisp/measure.py), with
the compiling left out.
"""

import bisect
import os

from heron.studies.lisp import machine, measure
from . import estimate, hw

PROGRAMS = os.path.join(os.path.dirname(machine.__file__), "programs")


def names():
    return sorted(f[:-5] for f in os.listdir(PROGRAMS) if f.endswith(".lisp"))


def text(name):
    with open(os.path.join(PROGRAMS, name + ".lisp"), "rb") as f:
        return f.read()


def interpreted(name):
    """(estimated cycles more on v1bl, 1b hardware cycles, calls by class)."""
    _img, m = machine.start(text(name))
    counts = estimate.trace(m, frames=True)
    _img, m0 = machine.start(b"")
    empty = estimate.trace(m0, frames=True)
    r = machine.run(text(name))
    r0 = machine.run(b"")
    base = hw.total(measure.run_counts(r)) - hw.total(measure.run_counts(r0))
    d = sum(estimate.delta(counts).values()) - sum(estimate.delta(empty).values())
    return d, base, estimate.summary(counts) - estimate.summary(empty)


def compiled(name):
    """The same for the compiled program, inside its windows."""
    r = measure.measure(text(name), compiled=True)["run"]
    wins = measure.windows(r)
    starts = [b for b, _ in wins]

    def active(raw):
        c = raw.cycles
        i = bisect.bisect_right(starts, c) - 1
        return i >= 0 and c < wins[i][1]
    _img, m = machine.start(text(name), compiled=True, reference=measure.CONFIG)
    counts = estimate.trace(m, active=active, frames=True)
    base = hw.total(measure.window_counts(text(name), (), r))
    return sum(estimate.delta(counts).values()), base, estimate.summary(counts)
