"""Test cases for the specification against the simulator, chosen by the
specification itself.

    heron formal isagen [--trials 3] [--seed 1] [--only SYNTAX] [--random N]

For each instruction of the specification, its encoding's fields, the
registers, flags, PC and memory are made symbolic, and the instruction
runs once on them, noting every decision it meets (Run.note): each arm
of an `if` or `case`, every flag it sets, every fault. Each outcome of
each decision is a *goal*: the condition, over the inputs, under which
that outcome happens. For each goal:

  - the solver finds inputs that reach it inside the specification (its
    assumptions hold), `--trials` times; each time a random half of the
    inputs is first pinned to random values, mostly boundary values (0, 1,
    -1, the sign bit, small numbers), and fewer if that leaves no way to
    reach the goal, so the inputs the goal doesn't decide come out random;
  - each set of inputs becomes a concrete case, which runs on the
    simulator and the specification as `isacheck` runs one;
  - the case counts toward coverage only if the specification, run on it
    concretely, took that outcome.

A goal the solver proves impossible is reported: an outcome no input can
reach, which in a specification is dead or redundant text. With --random
N, N plain random cases (isacheck's) run too, and their coverage of the
same goals is reported beside the generated cases'.
"""

import argparse
import random
import time
from collections import defaultdict

import z3

from . import isacheck
from . import spec2 as S

RAM = 0x10_0000
BOUNDARY = [0, 1, 2, 0xFFFFFFFF, 0xFFFFFFFE, 0x7FFFFFFF, 0x80000000, 0x80000001,
            0x0000FFFF, 0xFFFF0000, 0x00008000, 0xFFFF8000, 31, 32, 33]


class SymMem:
    """The specification's memory as two z3 arrays of bytes, the even ones
    and the odd ones, at address bits 31-1: the instruction's own parcel,
    stored at pc, then reads back as itself, so the decode folds."""

    def __init__(self, lo, hi):
        self.lanes = [lo, hi]

    @staticmethod
    def _split(a):
        t = S.term(a)
        return z3.simplify(z3.Extract(31, 1, t)), z3.simplify(z3.Extract(0, 0, t))

    def read(self, a):
        idx, lane = self._split(a)
        if z3.is_bv_value(lane):
            return S.mk(8, z3.simplify(z3.Select(self.lanes[lane.as_long()], idx)))
        return S.mk(8, z3.simplify(z3.If(lane == 1, z3.Select(self.lanes[1], idx),
                                         z3.Select(self.lanes[0], idx))))

    def write(self, a, v, g):
        if g is False:
            return
        idx, lane = self._split(a)
        d = S.term(v)
        for k in (0, 1):
            cond = z3.simplify(z3.And(z3.BoolVal(g) if isinstance(g, bool) else g, lane == k))
            if z3.is_false(cond):
                continue
            arr = self.lanes[k]
            new = d if z3.is_true(cond) else z3.If(cond, d, z3.Select(arr, idx))
            self.lanes[k] = z3.Store(arr, idx, new)


class Inputs:
    """The symbolic inputs of one instruction's run."""

    def __init__(self, ins, k):
        self.ins = ins
        self.r = [z3.BitVec(f"r{i}", 32) for i in range(16)]
        self.hi = z3.BitVec("hi", 32)
        self.pc_hi = z3.BitVec("pc_hi", 31)
        self.flags = {f: z3.Bool(f) for f in "NZCVI"}
        self.mem = [z3.Array(f"mem{k}", z3.BitVecSort(31), z3.BitVecSort(8)) for k in (0, 1)]
        self.pbits = [bool((ins.value >> i) & 1) if (ins.mask >> i) & 1 else z3.Bool(f"p{i}")
                      for i in range(ins.width)]

    @property
    def pc(self):
        return z3.Concat(self.pc_hi, z3.BitVecVal(0, 1))

    def parcel(self):
        bs = [z3.BoolVal(b) if isinstance(b, bool) else b for b in self.pbits]
        return z3.Concat(*[z3.If(b, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1)) for b in reversed(bs)])

    def state(self, spec):
        p = self.parcel()
        lo = z3.Store(self.mem[0], self.pc_hi, z3.Extract(7, 0, p))
        hi = z3.Store(self.mem[1], self.pc_hi, z3.Extract(15, 8, p))
        regs = {"r": [S.mk(32, x) for x in self.r], "hi": S.mk(32, self.hi),
                "pc": S.mk(32, self.pc)}
        regs.update(self.flags)
        return S.State(spec, regs, {"mem": SymMem(lo, hi)})

    def scalars(self):
        """(variable, how to pick a random value for it)."""
        out = [(x, "word") for x in self.r[1:]] + [(self.hi, "word"), (self.pc_hi, "pc")]
        out += [(v, "bit") for v in self.flags.values()]
        out += [(b, "bit") for b in self.pbits if not isinstance(b, bool)]
        return out


def pick(rng, how):
    if how == "bit":
        return rng.random() < 0.5
    if how == "pc":
        return rng.randrange(0x80, RAM // 2 - 0x80)
    k = rng.random()
    if k < 0.4:
        return rng.choice(BOUNDARY)
    if k < 0.6:
        return rng.randrange(-64, 64) & 0xFFFFFFFF
    if k < 0.8:
        return rng.randrange(0x100, RAM)          # an address in RAM
    return rng.getrandbits(32)


def _eq(var, value):
    if z3.is_bool(var):
        return var == z3.BoolVal(value)
    return var == value


def concretize(inp, m, rng):
    """A model as a concrete case: (r, hi, flags, pc, RAM image)."""
    def val(x, how):
        v = m.eval(x, model_completion=False)
        if z3.is_bv_value(v):
            return v.as_long()
        if z3.is_true(v) or z3.is_false(v):
            return z3.is_true(v)
        return pick(rng, how)                     # not in the model: anything
    r = [0] + [val(x, "word") for x in inp.r[1:]]
    hi = val(inp.hi, "word")
    pc = val(inp.pc_hi, "pc") << 1
    fl = sum(int(val(inp.flags[f], "bit")) << i for i, f in enumerate("VCZNI"))
    image = bytearray(RAM)
    for k in (0, 1):
        entries, default = array_entries(m, inp.mem[k])
        image[k::2] = bytes([default]) * (RAM // 2)    # memory the model doesn't care about
        for i, v in entries:
            if 2 * i + k < RAM:
                image[2 * i + k] = v
    p = sum(int(val(b, "bit") if not isinstance(b, bool) else b) << i
            for i, b in enumerate(inp.pbits))
    image[pc] = p & 0xFF
    image[pc + 1] = p >> 8
    return r, hi, fl, pc, bytes(image)


def array_entries(m, arr):
    """The entries a model gives an array, as [(index, value)], and the
    value of every other entry."""
    v = m.eval(arr, model_completion=True)
    out, default = [], 0
    while z3.is_store(v):
        out.append((v.arg(1).as_long(), v.arg(2).as_long()))
        v = v.arg(0)
    if z3.is_as_array(v):
        f = m[z3.get_as_array_func(v)]
        for e in f.as_list()[:-1]:
            out.append((e[0].as_long(), e[1].as_long()))
        if z3.is_bv_value(f.else_value()):
            default = f.else_value().as_long()
    elif z3.is_const_array(v) and z3.is_bv_value(v.arg(0)):
        default = v.arg(0).as_long()
    out.reverse()                                 # the outermost store wins
    return out, default


def sites(spec):
    """Every decision in the specification's text, as Run.note names it,
    with the outcomes it can have: {(site, outcome)}."""
    return spec.decisions()


def owner_ok(spec, w):
    """Whether some instruction's encoding and `when` take parcel w."""
    return any(ins.matches(w) and spec.when_holds(ins, w) for ins in spec.instructions)


def goals(spec, ins):
    """One instruction's goals: {(site, outcome): condition}, and the
    hypotheses (its assumptions)."""
    inp = Inputs(ins, 0)
    st = inp.state(spec)
    run = spec.step(st, record=True)
    out = {}
    for site, yes, no in run.record:
        if site[0] == "assume":                  # its failing side is outside the specification
            continue
        for outcome, g in ((True, yes), (False, no)):
            if site[0] in ("fault", "trap", "halt") and not outcome:
                continue
            g = S.decided(g) if not isinstance(g, bool) else g
            if g is False:
                continue
            key = (site, outcome)
            out[key] = g if key not in out else z3.Or(out[key], g)
    hyps = [a for a, _ in run.assumptions]
    return inp, out, hyps


def generate(spec, ins, trials, rng, timeout_ms=20_000):
    """Cases aimed at every goal of one instruction: ({goal: status},
    [cases]). A status is 'reached' (some case reached it concretely),
    'missed' (the solver found inputs, but no case's concrete run took
    that outcome), 'impossible' or 'unknown'."""
    inp, gs, hyps = goals(spec, ins)
    status, cases = {}, []
    s = z3.Solver()
    s.set("timeout", timeout_ms)
    s.add(*hyps)
    scalars = inp.scalars()
    for key, g in gs.items():
        s.push()
        s.add(g if not isinstance(g, bool) else z3.BoolVal(g))
        r = s.check()
        if r != z3.sat:
            status[key] = "impossible" if r == z3.unsat else "unknown"
            s.pop()
            continue
        status[key] = "missed"
        for _ in range(trials):
            frac = 0.5
            while True:
                s.push()
                hints = [_eq(x, pick(rng, how)) for x, how in scalars if rng.random() < frac]
                s.add(*hints)
                ok = s.check() == z3.sat
                if ok or frac == 0:
                    break
                s.pop()
                frac = frac / 2 if frac > 0.1 else 0
            if not ok:
                s.pop()
                continue
            cases.append((key, concretize(inp, s.model(), rng)))
            s.pop()
        s.pop()
    return status, cases


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron formal isagen")
    p.add_argument("--trials", type=int, default=3, help="cases per goal")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--only", help="instructions whose syntax starts with this")
    p.add_argument("--random", type=int, default=0,
                   help="also run this many random cases (isacheck's) for comparison")
    p.add_argument("--show", type=int, default=10)
    p.add_argument("-v", action="store_true", help="every goal not reached")
    args = p.parse_args(argv)
    spec = S.load("v1b_new.isa")
    rng = random.Random(args.seed)
    lines = S.HERE and open(S.HERE + "/v1b_new.isa").read().split("\n")
    total = defaultdict(int)
    reached_all, all_goals = set(), set()
    bad = 0
    t0 = time.time()
    ncases = 0
    for ins in spec.instructions:
        if args.only and not ins.syntax.startswith(args.only):
            continue
        status, cases = generate(spec, ins, args.trials, rng)
        took = set()
        for key, (r, hi, fl, pc, image) in cases:
            ncases += 1
            res = isacheck.compare(spec, r, hi, fl, pc, image, record=took)
            if res is not None:
                bad += 1
                if bad <= args.show:
                    why, words, _ = res
                    print(f"  {ins.syntax}: {pc:08X}: {' '.join(f'{w:04X}' for w in words)}: {why}")
        mine = {(site, o) for (_, site, o) in took}        # all of them aimed at ins
        for key in status:
            if status[key] == "missed" and key in mine:
                status[key] = "reached"
            all_goals.add((ins.line, key))
            if status[key] == "reached":
                reached_all.add((ins.line, key))
        n = defaultdict(int)
        for v in status.values():
            n[v] += 1
            total[v] += 1
        print(f"{ins.syntax:<38} {len(status):4} goals: " + ", ".join(
            f"{k} {n[k]}" for k in ("reached", "missed", "impossible", "unknown") if n[k]), flush=True)
        if args.v:
            for (site, o), v in sorted(status.items(), key=lambda x: str(x[0])):
                if v != "reached":
                    print(f"      {v:<10} line {site[1]}: {lines[site[1] - 1].strip()[:60]} "
                          f"({site[0]}{' ' + str(site[2]) if len(site) > 2 else ''}: {o})")
    if not args.only:
        # encodings no instruction has: sampled, since no instruction aims at them
        took, n = set(), 0
        while n < 50:
            w = rng.getrandbits(16)
            if owner_ok(spec, w):
                continue
            r, hi, fl, pc = isacheck.random_state(rng)
            image = bytearray(isacheck.WINDOW)
            image[pc], image[pc + 1] = w & 0xFF, w >> 8
            res = isacheck.compare(spec, r, hi, fl, pc, bytes(image), record=took)
            n += 1
            ncases += 1
            bad += res is not None
        status = {(site, o): "reached" for (_, site, o) in took}
        for key in status:
            all_goals.add((0, key))
            reached_all.add((0, key))
        print(f"{'(no instruction: illegal)':<38} {len(status):4} goals: reached {len(status)}")
        every = sites(spec)
        reached_sites = {key for (_, key) in reached_all}
        dead = sorted(every - reached_sites, key=lambda x: (x[0][1], str(x)))
        print(f"the specification has {len(every)} decision outcomes; "
              f"{len(every) - len(dead)} reached by some instruction's cases, {len(dead)} by none:")
        for site, o in dead:
            print(f"      line {site[1]}: {lines[site[1] - 1].strip()[:60]} "
                  f"({site[0]}{' ' + str(site[2]) if len(site) > 2 else ''}: {o})")
    print(f"{ncases} generated cases in {time.time() - t0:.0f} s, {bad} disagree; goals: "
          + ", ".join(f"{k} {total[k]}" for k in ("reached", "missed", "impossible", "unknown")))
    if args.random:
        took = set()
        rbad = 0
        rr = random.Random(args.seed)
        for _ in range(args.random):
            rbad += isacheck.run_one(spec, rr, record=took) is not None
        hit = {(i, (site, o)) for (i, site, o) in took} & all_goals
        print(f"{args.random} random cases: {rbad} disagree; they reach {len(hit)} of the "
              f"{len(all_goals)} goals (generated cases: {len(reached_all)}; "
              f"possible: {len(all_goals) - total['impossible'] - total['unknown']})")
        if args.v:
            names = {i.line: i.syntax for i in spec.instructions}
            for i, (site, o) in sorted(reached_all - hit, key=lambda x: (x[0], str(x[1]))):
                print(f"      random missed: {names.get(i, '(illegal)')}: line {site[1]}: "
                      f"{lines[site[1] - 1].strip()[:50]} ({site[0]}"
                      f"{' ' + str(site[2]) if len(site) > 2 else ''}: {o})")
    return 1 if bad else 0
