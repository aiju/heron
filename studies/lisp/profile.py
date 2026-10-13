"""Where a run's cycles went: by routine of the runtime (its global
labels), and for compiled code by the function it belongs to."""

import bisect
import sys
from collections import Counter


def routines(img):
    """[(address, name)] of the image's global labels, sorted."""
    return sorted((st.addr, st.label) for st in img.stmts
                  if st.kind == "label" and "." not in st.label)


def by_routine(run, config):
    """Counter: routine name -> cycles in it."""
    labels = routines(run.image)
    starts = [a for a, _ in labels]
    out = Counter()
    for pc, cyc in run.machine.pc_cycles(config).items():
        if pc is None:
            out["(interrupts)"] += cyc
            continue
        k = bisect.bisect_right(starts, pc) - 1
        name = labels[k][1] if k >= 0 else "?"
        if pc >= 0x20000:
            name = "(compiled code)"
        out[name] += cyc
    return out


def print_profile(run, config, top=30, out=sys.stderr):
    c = by_routine(run, config)
    total = sum(c.values()) or 1
    print(f"cycles by routine ({config}):", file=out)
    for name, cyc in c.most_common(top):
        print(f"  {name:<20} {cyc:>14,}  {100 * cyc / total:5.1f}%", file=out)
