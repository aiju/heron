"""The kernel study's nucleus (studies/kernel) under the estimator.

The nucleus is 1b assembly on v1bs, and isn't ported. Its scenarios run
as `heron kernel bench` runs them, twice (n and 2n operations), and the
difference is one operation's worth. The estimator keeps a shadow stack
per mode and address space (estimate.kernel_context).

Not in the estimate: a handler that calls a routine with the user's r7
live must save r7 too (pagefault's zero_page in the none variant saves
r1-r6), a store and a load more per such trap.
"""

from collections import Counter

from heron.studies.kernel import bench, build
from . import estimate, hw


def _counts(features, procs, timer):
    boot = build.Boot(features, procs, timer=timer)
    m = boot.machine()
    counts = estimate.trace(m, context=estimate.kernel_context)
    keys = Counter({(pc, k): n for pc, k, n in m._m.pc_keys()})
    if m.traps:
        raise RuntimeError(f"traps: {m.traps[:3]}")
    return counts, keys, m, boot


def scenario(name, banks="none"):
    """(estimated cycles more on v1bl per operation, 1b hardware cycles per
    operation, calls by class per operation)."""
    s = bench.BY_NAME[name]
    features = (banks,) + s.extra
    timer = 3000 if s.name in ("preempt", "irqdrv") else 0
    (ca, ka, ma, boot), (cb, kb, mb, _) = (_counts(features, s.procs(n), timer)
                                           for n in (s.n, 2 * s.n))
    if s.name in ("preempt", "irqdrv"):
        ops = mb.irqs - ma.irqs
    elif s.name == "refill":
        ops = mb._m.sys["page_faults"] - ma._m.sys["page_faults"]
    else:
        ops = s.n * s.per
    dk = kb - ka
    if s.kernel_only:
        dk = Counter({(pc, k): n for (pc, k), n in dk.items()
                      if pc is None or not boot.symbol_at(pc).startswith("user:")})
    base = hw.total(dk) / ops
    d = (sum(estimate.delta(cb).values()) - sum(estimate.delta(ca).values())) / ops
    calls = {k: v / ops for k, v in (estimate.summary(cb) - estimate.summary(ca)).items()}
    return d, base, calls


def names():
    return [s.name for s in bench.SCENARIOS]
