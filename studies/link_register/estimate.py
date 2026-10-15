"""What a link register would change in a 1b run, without porting it.

The program runs on 1b, an instruction at a time, with a shadow stack of
the calls in progress. Each call is costed as v1bl would run it, from its
callee's behaviour on that run:

  leaf      the callee made no call before returning, and saved nothing
            from r8: v1bl's call and a return through r7 (RET), instead of
            the push and the pop
  fold      the callee saved a range next to r7 or holding it (r8-rN; the
            Lisp's r3-rN) before any call, whether or not it then called:
            v1bl's call, one more register in that SAVE and its RESTORE,
            and a return through r7
  push      the callee called and saved nothing from r8: v1bl's call, a
            push of r7 and a return that pops it (JMP [sp]+)
  lost      the return address never came back to a RET (a longjmp, a
            JIT's prologue that pops it into a frame, a return made by a
            jump): only the call itself is costed

A callee is a leaf for the calls in which it made no call, so a path that
returns early counts as a leaf, as a port would write it (fib's); but a
SAVE keeps r7 company, as the ports do. It assumes r7 is free in a leaf,
which the ports found nearly always true or fixable by renaming. measure.py's workloads,
ported for real, check how close it comes (report.py prints both).

The costs are a timing key's cycles: hw.cycles for the 1b hardware, or
any configuration of draft 1's timing model.
"""

from collections import Counter

from heron.studies.v1_isa import timing32
from . import hw

# first parcel -> what it is, for the instructions that matter here
_MODE_EA = {2: "r", 3: "rd", 4: "rd", 5: "idx", 6: "pi", 7: "pd"}


def classify(w):
    """("call", key shape) | ("ret",) | ("save", first, count) |
    ("restore", first, count) | None for a first parcel w."""
    op, d, m, r = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
    if op == 0:
        if r == 3:
            return ("call", ("call", "reg", 1))
        if r == 4:
            return ("ret",)
        if r in (5, 6) and 1 <= d <= m <= 14:
            return ("save" if r == 5 else "restore", d, m - d + 1)
        return None
    if op == 0xE and d == 15:
        return ("call", ("call", "rel", 1))
    if op == 0xA and d == 15:
        return ("call", ("call", "rel", 2) if m == 0 else ("call", "abs", 3))
    if op == 0xB and d == 1:
        if m == 0:
            return ("call", ("call", "reg", 1))
        if m == 0xF:
            if r <= 3:
                return ("call", ("call", "abs", 3 if r == 3 else 2))
            if r in (4, 7):
                return ("call", ("callm", "abs", 2 if r == 4 else 3))
            return ("call", ("callm", "pc", 2))
        if m in _MODE_EA:
            n = 2 if m in (3, 5) else 1
            return ("call", ("callm", _MODE_EA[m], n))
    return None


def _key(shape, link=False):
    kind, how, n = shape
    if link:
        kind = {"call": "link", "callm": "linkm"}[kind]
    return (n, 0, kind, how, 0)


class Costs:
    """The cycle differences, for a cost function key -> cycles."""

    def __init__(self, cost):
        self.cost = cost
        self.ret_r7 = cost((1, 0, "jmp", "reg", 0)) - cost((1, 0, "ret"))
        self.ret_pop = cost((1, 0, "jmpm", "pi", 0)) - cost((1, 0, "ret"))
        self.push = cost((1, 0, "st", "pd", 4, 0))

    def call(self, shape):
        return self.cost(_key(shape, True)) - self.cost(_key(shape))

    def fold(self, n):
        return (self.cost((1, 0, "save", n + 1)) - self.cost((1, 0, "save", n))
                + self.cost((1, 0, "restore", n + 1)) - self.cost((1, 0, "restore", n)))


def cost_function(config):
    """hw.cycles for "hw", else the timing model's configuration."""
    if config == "hw":
        return hw.cycles
    return lambda key: timing32.cycles(key, config)


class Frame:
    __slots__ = ("slot", "shape", "called", "save", "counted")

    def __init__(self, slot, shape, counted):
        self.slot = slot            # where the return address was pushed
        self.shape = shape
        self.called = False
        self.save = None            # (first, count) of the callee's first SAVE
        self.counted = counted


def trace(m, max_steps=2_000_000_000, active=None, frames=False, context=None):
    """Run machine m (1b) to the end, tracking its calls. Returns a Counter
    of (class, call shape, saved registers) -> calls. With active (a
    function of the machine), only the calls made while it's true count.
    With frames, a callee that saved any registers before its first call
    keeps r7 with them even if it then returns without calling, as a
    compiler that builds the frame on entry would (the Lisp's). With
    context (a function of the machine), a shadow stack per context: the
    kernel's processes have their own stacks, at the same addresses."""
    raw = m._m
    out = Counter()
    stacks = {}
    kinds = {}
    steps = 0

    def lose(f):
        if f.counted:
            out["lost", f.shape, 0] += 1

    while not raw.halted and steps < max_steps:
        pc = raw.pc
        try:
            w = raw.parcel(pc)
        except Exception:           # not mapped (v1bs): the step takes the fault
            raw.step()
            steps += 1
            continue
        k = kinds.get(w, 0)
        if k == 0:
            k = kinds[w] = classify(w)
        if k is None or k[0] == "restore":
            raw.step()
            steps += 1
            continue
        stack = stacks.setdefault(context(raw) if context else None, [])
        what = k[0]
        if what == "ret":
            sp = raw.r[15]
            raw.step()
            steps += 1
            i = len(stack) - 1
            while i >= 0 and stack[i].slot != sp:
                i -= 1
            if i < 0:
                continue
            for f in stack[i + 1:]:
                lose(f)
            f = stack[i]
            del stack[i:]
            if not f.counted:
                continue
            if f.save and f.save[0] <= 8 and f.save[0] + f.save[1] > 6:
                out["fold", f.shape, f.save[1]] += 1
            elif not f.called and not (frames and f.save):
                out["leaf", f.shape, 0] += 1
            else:
                out["push", f.shape, 0] += 1
            continue
        if what == "save":
            if stack and not stack[-1].called and stack[-1].save is None:
                stack[-1].save = (k[1], k[2])
            raw.step()
            steps += 1
            continue
        # a call: the return address is pushed at the new sp
        raw.step()
        steps += 1
        if stack:
            stack[-1].called = True
        sp = raw.r[15]
        # frames whose return address is now below sp are gone
        while stack and stack[-1].slot < sp:
            lose(stack.pop())
        stack.append(Frame(sp, k[1], active is None or active(raw)))
    for stack in stacks.values():
        for f in stack:
            lose(f)
    return out


def kernel_context(raw):
    """v1bs: supervisor or user, and the address space."""
    s = raw.sys
    return (s["s"], s["ctx"])


def delta(counts, config="hw"):
    """The cycles v1bl would take more (negative: fewer), by class."""
    c = Costs(cost_function(config))
    by = Counter()
    for (cls, shape, n), calls in counts.items():
        d = c.call(shape)
        if cls == "leaf":
            d += c.ret_r7
        elif cls == "fold":
            d += c.fold(n) + c.ret_r7
        elif cls == "push":
            d += c.push + c.ret_pop
        by[cls] += d * calls
    return by


def summary(counts):
    """Calls by class."""
    out = Counter()
    for (cls, _shape, _n), calls in counts.items():
        out[cls] += calls
    return out
