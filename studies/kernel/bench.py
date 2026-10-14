"""The nucleus's hot paths, measured: cycles per operation for each
register-bank variant, and where they go.

Every scenario runs twice, with n and with 2n iterations, on the
instruction-level simulator; the difference over n is the cost of one
iteration, with booting and exiting cancelled out. Cycles are for
D32-separate, the configuration of the draft 1b hardware (report 0012),
unless asked otherwise.
"""

import os
from collections import Counter

from . import build
from .build import Proc, F_IO, F_SHARED, F_IRQ, USER

CONFIG = "D32-separate"
MHZ = 3.0                       # the draft 1b hardware, worst case (report 0012)


def batch(b, length):
    return (b << 16) | length


class Scenario:
    """procs(n): the processes for n iterations; per: operations per
    iteration (a round trip of two yields counts two); text: what one
    operation is; check(out, n): whether the console output is right."""

    def __init__(self, name, text, procs, per=1, n=40, extra=(), check=None, kernel_only=False,
                 exclude=()):
        self.name, self.text, self.procs, self.per, self.n = name, text, procs, per, n
        self.extra = tuple(extra)
        self.check = check
        # count only the nucleus's cycles, without these routines
        self.kernel_only = kernel_only
        self.exclude = set(exclude)


def _lines(length, count):
    """What `count` writes of the first `length` bytes of user/line.inc print."""
    with open(os.path.join(USER, "line.inc")) as f:
        text = f.read().split('"')[1].replace("\\n", "\n")
    return (text[:length].encode()) * count


def _check_writes(length, per_iter):
    return lambda out, n: out == _lines(length, n * per_iter)


SCENARIOS = [
    Scenario("null", "a null system call", lambda n: [Proc("null", n)]),
    Scenario("yield", "a yield to another process (a thread switch with its map context)",
             lambda n: [Proc("yield", n), Proc("yield", n)], per=2),
    Scenario("ipc", "a call and its reply between two processes (two switches)",
             lambda n: [Proc("server"), Proc("client", n)]),
    Scenario("fault", "a demand-zero page fault (with zeroing the 4 KB page)",
             lambda n: [Proc("touch", n)], n=8),
    Scenario("preempt", "a timer interrupt that preempts one process for another",
             lambda n: [Proc("spin", 2000 * n), Proc("spin", 2000 * n)], n=10, kernel_only=True),
    Scenario("irqdrv", "an interrupt handed to a user-level driver thread, which waits for the next",
             lambda n: [Proc("drv", prio=0, flags=F_IRQ), Proc("spin", 2000 * n)], n=10,
             kernel_only=True),
    Scenario("wmono", "write(16 bytes): one system call, the nucleus copies to the console",
             lambda n: [Proc("wmono", n, arg2=16)], check=_check_writes(16, 1)),
    Scenario("wipc", "write(16 bytes): a call to a user-level console server",
             lambda n: [Proc("conserver", flags=F_IO | F_SHARED),
                        Proc("wipc", n, arg2=16, flags=F_SHARED)], check=_check_writes(16, 1)),
    Scenario("wring", "write(16 bytes) through the nucleus's ring, 8 per system call",
             lambda n: [Proc("wring", n, arg2=batch(8, 16))], per=8, n=10,
             check=_check_writes(16, 8)),
    Scenario("wring32", "write(16 bytes) through the nucleus's ring, 32 per system call",
             lambda n: [Proc("wring", n, arg2=batch(32, 16))], per=32, n=4,
             check=_check_writes(16, 32)),
    Scenario("wserv1", "write(16 bytes) through a ring to a user-level server, 1 per notify",
             lambda n: [Proc("rserver", flags=F_IO | F_SHARED),
                        Proc("rclient", n, arg2=batch(1, 16), flags=F_SHARED)], n=20,
             check=_check_writes(16, 1)),
    Scenario("wserv", "write(16 bytes) through a ring to a user-level server, 8 per notify",
             lambda n: [Proc("rserver", flags=F_IO | F_SHARED),
                        Proc("rclient", n, arg2=batch(8, 16), flags=F_SHARED)], per=8, n=10,
             check=_check_writes(16, 8)),
    Scenario("wserv32", "write(16 bytes) through a ring to a user-level server, 32 per notify",
             lambda n: [Proc("rserver", flags=F_IO | F_SHARED),
                        Proc("rclient", n, arg2=batch(32, 16), flags=F_SHARED)], per=32, n=4,
             check=_check_writes(16, 32)),
    Scenario("wmono256", "write(256 bytes): one system call",
             lambda n: [Proc("wmono", n, arg2=256)], n=10, check=_check_writes(256, 1)),
    Scenario("wipc256", "write(256 bytes): a call to the console server",
             lambda n: [Proc("conserver", flags=F_IO | F_SHARED),
                        Proc("wipc", n, arg2=256, flags=F_SHARED)], n=10,
             check=_check_writes(256, 1)),
    Scenario("refill", "a map refill from the page table (softtlb), per page",
             lambda n: [Proc("softtlb", n, arg2=16)], per=16, n=8, extra=("softtlb",),
             kernel_only=True, exclude=("sys_mapflush", "swi")),
]

BY_NAME = {s.name: s for s in SCENARIOS}


class Run:
    def __init__(self, boot, m, error):
        self.boot, self.m, self.error = boot, m, error

    def word(self, name):
        a = self.boot.kernel.symbols[name]
        return int.from_bytes(self.m.mem[a:a + 4], "little")

    def problems(self):
        out = []
        if self.error:
            out.append(self.error)
        if self.m.traps:
            out.append(f"traps: {self.m.traps[:3]}")
        if self.word("n_segv"):
            out.append(f"{self.word('n_segv')} threads ended by a fault")
        return out


def run(features, procs, timer=0, max_cycles=200_000_000):
    boot = build.Boot(features, procs, timer=timer)
    m = boot.machine()
    err = None
    try:
        m.run(max_cycles)
    except Exception as e:  # SimError
        err = str(e)
    return Run(boot, m, err)


def profile(r, config=CONFIG):
    """Cycles by routine: nucleus symbols, user programs, and "(trap
    entry)" for taking traps and interrupts (whichever instruction trapped)."""
    from heron import native
    out = Counter()
    cost = {}
    for pc, key, n in r.m._m.pc_keys():
        if key not in cost:
            cost[key] = native.v1.cycles(key, config)
        where = "(trap entry)" if key[2] in ("trap", "irq") else r.boot.symbol_at(pc)
        out[where] += n * cost[key]
    return out


class Result:
    def __init__(self, scenario, features, per_op, by_routine, runs):
        self.scenario, self.features = scenario, features
        self.per_op = per_op            # cycles per operation, by config
        self.by_routine = by_routine    # cycles per operation, by routine (CONFIG)
        self.runs = runs


def measure(scenario, banks, configs=(CONFIG,)):
    s = BY_NAME[scenario] if isinstance(scenario, str) else scenario
    features = (banks,) + s.extra
    timer = 3000 if s.name in ("preempt", "irqdrv") else 0
    runs = []
    for n in (s.n, 2 * s.n):
        r = run(features, s.procs(n), timer=timer)
        p = r.problems()
        if p:
            raise RuntimeError(f"{s.name} ({banks}, n={n}): {'; '.join(p)}")
        if s.check and not s.check(bytes(r.m.dev.out), n):
            raise RuntimeError(f"{s.name} ({banks}, n={n}): wrong output {bytes(r.m.dev.out)[:80]!r}")
        runs.append(r)
    a, b = runs
    if s.name in ("preempt", "irqdrv"):
        ops = b.m.irqs - a.m.irqs
    elif s.name == "refill":
        ops = b.m._m.sys["page_faults"] - a.m._m.sys["page_faults"]
    else:
        ops = s.n * s.per
    pa, pb = profile(a), profile(b)
    by_routine = {k: (pb[k] - pa.get(k, 0)) / ops for k in pb if pb[k] != pa.get(k, 0)}
    if s.kernel_only:
        # only the nucleus's share: the user programs just keep it busy
        per_op = {}
        for c in configs:
            qa, qb = profile(a, c), profile(b, c)
            per_op[c] = sum(qb[k] - qa.get(k, 0) for k in qb
                            if not k.startswith("user:") and k not in s.exclude) / ops
    else:
        per_op = {c: (b.m.cycles_for(c) - a.m.cycles_for(c)) / ops for c in configs}
    return Result(s, features, per_op, by_routine, runs)


def table(scenarios=None, configs=(CONFIG,)):
    """{scenario: {banks: Result}}"""
    out = {}
    for s in SCENARIOS:
        if scenarios and s.name not in scenarios:
            continue
        out[s.name] = {b: measure(s, b, configs) for b in build.BANKS}
    return out
