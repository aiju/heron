"""How long the draft 1b CPU's microcycles need to be with other parts:
static timing analysis (heron.infra.hw.sta) of the v1b_hw netlist, once
for every distinct microinstruction, as in report 0012.

From each microinstruction's requirement and how often it runs (the
program suite's profile on the RTL model, v1b_system's lengths.profile),
three times for the suite:

  fixed    every cycle as long as the slowest microinstruction needs
  ideal    every cycle exactly as long as its own microinstruction needs
  classes  four lengths on a 20 ns grid, chosen for the suite, each
           microinstruction in the shortest that fits (RFC 0007's
           variable-length cycles)

These are the CPU alone, with the write window at half to seven eighths
of the cycle as in report 0012; the system's own clock generator adds its
constraints (fastsys.py).
"""

import json
import math
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations

from heron import BUILD
from heron.infra.hw import sta
from heron.studies.v1b_hw import machine as v1b_machine
from heron.studies.v1b_system import lengths

from . import parts

OUT = os.path.join(BUILD, "v1b_tradeoffs")
TICK = 20.0
SETS = list(parts.DESCRIBE)


def requirements(variant, corner="max"):
    """{packed control word: period it needs (ns)}, the larger of with and
    without an interrupt pending; cached in build/v1b_tradeoffs."""
    path = os.path.join(OUT, f"sta-{variant}-{corner}.json")
    srcs = v1b_machine.sources() + [os.path.abspath(__file__), parts.__file__]
    if os.path.exists(path) and os.path.getmtime(path) > max(os.path.getmtime(p) for p in srcs):
        with open(path) as f:
            return {int(k): v for k, v in json.load(f).items()}
    _N, results = sta.analyse(v1b_machine, variant, corner)
    req = {}
    for T, w, _extra, _labels in results:
        req[w] = max(req.get(w, 0.0), T)
    os.makedirs(OUT, exist_ok=True)
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(req, f)
    os.replace(tmp, path)
    return req


def best_lengths(weight, n=4):
    """The n lengths (the longest requirement among them) that minimise
    sum(count * length): weight is {ticks needed: count}. Returns
    (lengths, total ticks)."""
    ks = sorted(weight)
    top = ks[-1]
    best = None
    for rest in combinations(ks[:-1], min(n - 1, len(ks) - 1)):
        lens = sorted(rest) + [top]
        t = sum(c * next(x for x in lens if x >= k) for k, c in weight.items())
        if best is None or t < best[1]:
            best = (lens, t)
    return best


def suite_times(req):
    """(fixed, ideal, (lengths, classes time)) for the program suite, in
    seconds, from per-word requirements in ns."""
    prof = lengths.profile()
    words = lengths.rom_words()
    n = sum(prof.values())
    tmax = max(req.values())
    ideal = sum(c * req[words[a]] for a, c in prof.items())
    w = Counter()
    for a, c in prof.items():
        w[math.ceil(req[words[a]] / TICK - 1e-9)] += c
    lens, ticks = best_lengths(w)
    return n * tmax * 1e-9, ideal * 1e-9, (lens, ticks * TICK * 1e-9)


def _job(args):
    v, corner = args
    return v, corner, requirements(v, corner)


def table(sets=None, corners=("max", "typ"), jobs=4):
    """[{set, corner, period, fixed, ideal, lengths, classes, hist}] for
    each set of parts and delay corner."""
    sets = sets or SETS
    todo = [(v, c) for v in sets for c in corners]
    lengths.profile()                      # cache it before the workers need it
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(_job, todo))
    rows = []
    for v, c, req in res:
        fixed, ideal, (lens, cls) = suite_times(req)
        hist = Counter(int(t // 20) * 20 for t in req.values())
        rows.append({"set": v, "corner": c, "period": max(req.values()), "fixed": fixed,
                     "ideal": ideal, "lengths": lens, "classes": cls, "hist": sorted(hist.items())})
    return rows


def critical_path(variant, corner="max"):
    """The slowest microinstruction and its path, as heron.infra.hw.sta
    reports it."""
    N, results = sta.analyse(v1b_machine, variant, corner)
    return sta.report(v1b_machine, N, results, paths=1)
