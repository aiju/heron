"""What a pipelined control store would buy the two-halves machine: an
estimate from the suite's microinstructions, as the model runs them
(RFC 0047's pipelining.md).

  heron chibi pipeline

Each microinstruction executed is costed as the model costs it today (phase
F's 3 ticks, then its halves) and as a pipelined machine would, where a
register holds the executing word while the flashes give the next. The
costs, in ticks:

- today: 3 + the low half + the high half;
- the floor: the flashes' word must reach the register in a cycle: 4 ticks
  with the SST39SF040's 55 ns, 3 with a 45 ns part (the SST39SF010A-45,
  128K words: only a flat layout fits), 4 for a conditional jump either
  way (its condition, on the flags the microinstruction before has just
  set, comes about 12 ns into the cycle);
- "writes in F": the register file's two writes still in a phase of their
  own, 2 ticks: max(floor, 2 + the halves);
- "writes overlapped": the low half's result written while the high half
  reads the other pair, the high half's while the next low half does, so
  only a one-half microinstruction pays a tick: max(floor, the halves, or
  1 + the low half);
- the decode: a fetch's parcel only gives the next address at the cycle's
  end, so each instruction pays a bubble of the floor's length, unless the
  parcel is prefetched;
- restructuring: a two-half microinstruction whose jump is on its own low
  half's flags, and an index dispatch (the branch on z, from the parcel
  being read), each take a microinstruction more (3 ticks).

(Written for the paged store, before the flat one; RFC 0047 has its
figures as they were.)

I/O halves, the slow devices and the video's stretches of phase F are left
out of all of them alike (they're under 0.1% of the ticks).
"""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor

VARIANTS = [
    # name, floor, conditional jump's floor, decode bubble, writes overlapped
    ("pipelined, writes in F, 55 ns flashes", 4, 4, 4, False),
    ("pipelined, writes overlapped, 55 ns", 4, 4, 4, True),
    ("pipelined, writes overlapped, 55 ns, prefetch", 4, 4, 0, True),
    ("pipelined, writes in F, 45 ns flashes", 3, 4, 3, False),
    ("pipelined, writes overlapped, 45 ns", 3, 4, 3, True),
    ("pipelined, writes overlapped, 45 ns, prefetch", 3, 4, 0, True),
]


def _profile(path):
    import heron.studies.v2_isa  # noqa: F401
    from heron.infra.programs import metadata
    from . import check
    m = check.run_rtl(check.assemble(path), metadata(path)["input"], profile=True)
    return m.ticks, dict(m.ucount)


def estimate(jobs=4):
    """({cost name: ticks}, {mix: count}, the model's ticks) over the suite."""
    from heron.studies.v2_isa import testing
    from . import routines2, ucode2 as uc
    cs = routines2.control_store()
    with ProcessPoolExecutor(jobs) as ex:
        runs = list(ex.map(_profile, testing.program_paths()))
    cost, mix, model = Counter(), Counter(), 0
    for ticks, counts in runs:
        model += ticks
        for a, n in counts.items():
            f = uc.unpack(cs.words[a])
            lo, hi = f["LEN"] + 1, f["HLEN"]
            two = hi > 0
            fetch = f["MOP"] == uc.MOP_FETCH
            cond = f["SEQ"] in (uc.HSEQ_JUMP, uc.HSEQ_JUMPT) and f["CND"] != 0
            extra = (two and cond and f["FL"] != 0) + (f["IRN"] == uc.HIRN_IDX)
            mix["microinstructions"] += n
            mix["one-half"] += n * (not two)
            mix["decodes"] += n * fetch
            mix["conditional jumps"] += n * cond
            mix["restructured"] += n * extra
            cost["today"] += n * (3 + lo + hi)
            for name, floor, cfloor, bubble, overlap in VARIANTS:
                body = (lo + hi if two else 1 + lo) if overlap else 2 + lo + hi
                cost[name] += n * (max(cfloor if cond else floor, body) + fetch * bubble
                                   + 3 * extra)
    return cost, mix, model


def table(cost, mix):
    n = mix["microinstructions"]
    rows = [f"| {k} | {cost[k] / n:.2f} | {cost['today'] / cost[k]:.2f}x |"
            for k in ["today"] + [v[0] for v in VARIANTS]]
    return "\n".join(["| | Ticks a microinstruction | Speed |", "|---|---:|---:|"] + rows)


def cmd_pipeline(args):
    cost, mix, model = estimate()
    n = mix["microinstructions"]
    print(f"{n:,} microinstructions; today's cost {cost['today']:,} ticks against the "
          f"model's {model:,}")
    print(", ".join(f"{k} {mix[k] / n:.1%}" for k in mix if k != "microinstructions"))
    print()
    print(table(cost, mix))
    return 0
