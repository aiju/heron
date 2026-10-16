"""The specification language's two versions, compared on draft 1b: the
spec as first written, in the first language (both read from git at
FIRST), and as it is now, run on the same symbolic inputs one
instruction at a time (an EA instruction one mode at a time, mode F one
n at a time). The solver proves they make the same assumptions, and
under them give the same next state: registers, flags, PC, faults,
halts, and the same writes to memory in the same order.

    heron formal versions [instruction]

Same writes in the same order is more than the same memory needs, but far
easier for the solver than comparing the two memories as arrays, and it
holds: both versions push and store in the same order.
"""

import argparse
import subprocess
import sys
import time
import types

import z3

from heron import ROOT

from . import isagen, spec as B

FIRST = "adb5fad"           # the last commit with the first language


def first_version():
    """The first language's interpreter as a module, and 1b in it."""
    def show(path):
        return subprocess.run(["git", "show", f"{FIRST}:{path}"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout
    mod = types.ModuleType("first_spec")
    mod.__file__ = __file__
    exec(compile(show("studies/formal/spec.py"), "first_spec.py", "exec"), mod.__dict__)
    return mod, mod.Spec(show("studies/formal/v1b.isa"))


class Mem:
    """Memory in two lanes, as isagen keeps it, logging every write."""

    def __init__(self, M, lanes):
        self.M, self.lanes = M, list(lanes)
        self.log = []               # (address, data, guard) of every write, in order

    def _split(self, a):
        t = self.M.term(a)
        return z3.simplify(z3.Extract(31, 1, t)), z3.simplify(z3.Extract(0, 0, t))

    def read(self, a):
        idx, lane = self._split(a)
        if z3.is_bv_value(lane):
            return self.M.mk(8, z3.simplify(z3.Select(self.lanes[lane.as_long()], idx)))
        return self.M.mk(8, z3.simplify(z3.If(lane == 1, z3.Select(self.lanes[1], idx),
                                              z3.Select(self.lanes[0], idx))))

    def write(self, a, v, g):
        if g is False:
            return
        self.log.append((self.M.term(a), self.M.term(v), _bool(g)))
        idx, lane = self._split(a)
        d = self.M.term(v)
        for k in (0, 1):
            cond = z3.simplify(z3.And(_bool(g), lane == k))
            if z3.is_false(cond):
                continue
            arr = self.lanes[k]
            self.lanes[k] = z3.Store(arr, idx, d if z3.is_true(cond) else
                                     z3.If(cond, d, z3.Select(arr, idx)))


def _bool(x):
    return z3.BoolVal(x) if isinstance(x, bool) else x


def _bit(b):
    return z3.If(b, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))


def variants(ins):
    if "m" not in ins.fields:
        return [{}]
    return [{"m": m} for m in range(15)] + [{"m": 15, "n": n} for n in range(16)]


def compare(A, sa, sb, ia, ib, fixed, timeout_ms=300_000):
    """What differs between the two versions of one instruction (with the
    fields in `fixed` set): [] if nothing."""
    def flag(x):
        return _bool(A.guard(x) if isinstance(x, A.Bits) else x)

    inp = isagen.Inputs(ib, 0)
    for f, v in fixed.items():
        hi, lo = ib.fields[f]
        for i in range(lo, hi + 1):
            inp.pbits[i] = bool((v >> (i - lo)) & 1)
    p = inp.parcel()
    lanes = [z3.Store(inp.mem[0], inp.pc_hi, z3.Extract(7, 0, p)),
             z3.Store(inp.mem[1], inp.pc_hi, z3.Extract(15, 8, p))]
    ma, mb = Mem(A, lanes), Mem(B, lanes)
    ra = {"r": [A.mk(32, x) for x in inp.r], "hi": A.mk(32, inp.hi), "pc": A.mk(32, inp.pc)}
    ra.update({f: A.mk(1, _bit(v)) for f, v in inp.flags.items()})
    rb = {"r": [B.mk(32, x) for x in inp.r], "hi": B.mk(32, inp.hi), "pc": B.mk(32, inp.pc)}
    rb.update(inp.flags)
    sta, stb = A.State(sa, ra, {"mem": ma}), B.State(sb, rb, {"mem": mb})
    runa, runb = sa.step(sta), sb.step(stb)
    hyp = z3.And(*[a for a, _ in runa.assumptions]) if runa.assumptions else z3.BoolVal(True)
    hyp_b = z3.And(*[a for a, _ in runb.assumptions]) if runb.assumptions else z3.BoolVal(True)
    goals = [("assumptions", hyp == hyp_b)]
    goals += [(f"r{i}", A.term(sta.regs["r"][i]) == B.term(stb.regs["r"][i])) for i in range(1, 16)]
    goals += [(r, A.term(sta.regs[r]) == B.term(stb.regs[r])) for r in ("hi", "pc")]
    goals += [(f, flag(sta.regs[f]) == flag(stb.regs[f])) for f in "NZCVI"]
    goals += [("faults", flag(runa.fault_g) == flag(runb.fault_g)),
              ("halts", flag(runa.halt_g) == flag(runb.halt_g))]
    if len(ma.log) != len(mb.log):
        return [f"memory: {len(ma.log)} writes against {len(mb.log)}"]
    for i, ((aa, da, ga), (ab, db, gb)) in enumerate(zip(ma.log, mb.log)):
        goals.append((f"write {i}: when", ga == gb))
        goals.append((f"write {i}: where and what", z3.Implies(ga, z3.And(aa == ab, da == db))))
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    wrong = []
    for name, g in goals:
        s.push()
        if name != "assumptions":
            s.add(hyp)
        s.add(z3.Not(g))
        r = s.check()
        if r != z3.unsat:
            wrong.append(f"{name}: {'differs' if r == z3.sat else r}")
        s.pop()
    return wrong


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron formal versions")
    p.add_argument("only", nargs="?", help="instructions whose syntax starts with this")
    args = p.parse_args(argv)
    A, sa = first_version()
    sb = B.load("v1b.isa")
    if [(i.syntax, i.mask, i.value) for i in sa.instructions] != \
            [(i.syntax, i.mask, i.value) for i in sb.instructions]:
        print("the two versions don't list the same instructions", file=sys.stderr)
        return 1
    n = bad = 0
    t0 = time.time()
    for ia, ib in zip(sa.instructions, sb.instructions):
        if args.only and not ia.syntax.startswith(args.only):
            continue
        for fixed in variants(ib):
            wrong = compare(A, sa, sb, ia, ib, fixed)
            n += 1
            if wrong:
                bad += 1
                where = " ".join(f"{k}={v:X}" for k, v in fixed.items())
                print(f"{ia.syntax} {where}: {'; '.join(wrong)}", flush=True)
    print(f"{n} comparisons in {time.time() - t0:.0f} s: {bad} differ")
    return 1 if bad else 0
