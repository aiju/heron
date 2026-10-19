"""The program suite on the register-transfer model, profiled: how often
each microinstruction runs (to pick the length classes by, and for the
static timing analysis's report), the time with the microcode's length
classes, where it goes. Profiles are cached in build/mini by the sources.

    heron mini perf [--c]
"""

import json
import os
from collections import Counter

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata
from heron.infra.hw import runner

from . import hw, ucode as uc
from .timing import TICK

# programs left out of the totals: the timer's interrupts, whose number
# depends on the machine's own speed
SKIP = ("interrupts",)


def _run(name, img, inp):
    from . import check
    m = check.run_rtl(img, inp, profile=True)
    return {"name": name, "instructions": m.instructions, "cycles": m.cycles,
            "ticks": m.ticks, "hold": m.hold_ticks, "refills": m.refills,
            "ucount": {str(a): n for a, n in m.ucount.items()}}


def profile(c=True, force=False):
    """[{name, instructions, cycles, ticks, hold, refills, ucount}] for the
    suite (and the compiled C programs), cached."""
    path = os.path.join(hw.OUT, "profile.json")
    if not force and os.path.exists(path) and \
            os.path.getmtime(path) >= runner.newest(hw.sources()):
        with open(path) as f:
            rows = json.load(f)
    else:
        from . import check
        rows = []
        for p in check.program_paths():
            name = os.path.basename(p)[:-2]
            meta = metadata(p)
            img = asmcore.assemble_file(isas.get("v2"), p)
            rows.append(_run(name, img, meta["input"]))
        for name, img, inp in check.c_programs():
            rows.append(_run(name, img, inp))
        os.makedirs(hw.OUT, exist_ok=True)
        with open(path, "w") as f:
            json.dump(rows, f)
    for r in rows:
        r["ucount"] = {int(a): n for a, n in r["ucount"].items()}
    if not c:
        rows = [r for r in rows if not r["name"].startswith("c/")]
    return rows


def counts(rows):
    """{control store address: executions} over the rows (SKIP left out)."""
    out = Counter()
    for r in rows:
        if r["name"] in SKIP:
            continue
        for a, n in r["ucount"].items():
            out[a] += n
    return out


def node_profile(rows, mc=None):
    """{node id: executions}, for timing.assign_classes()."""
    mc = mc or uc.built()
    out = Counter()
    for a, n in counts(rows).items():
        node = mc.by_addr.get(a)
        if node is not None:
            out[id(node)] += n
    return out


def suite_time(rows, mc=None):
    """The rows' time in ms with the microcode's length classes (and the
    I/O holds), from their profiles."""
    mc = mc or uc.built()
    total = 0
    for a, n in counts(rows).items():
        node = mc.by_addr[a]
        total += n * mc.lengths[node.f["LCL"]]
    hold = sum(r["hold"] for r in rows if r["name"] not in SKIP)
    return (total + hold) * TICK / 1e6


def main(args):
    rows = profile(force=args.force)
    mc = uc.built()
    print(f"length classes {mc.lengths}")
    print(f"{'program':12s} {'instr':>9s} {'cycles':>9s} {'CPI':>5s} {'ms':>8s}")
    for r in rows:
        ms = r["ticks"] * TICK / 1e6
        print(f"{r['name']:12s} {r['instructions']:9d} {r['cycles']:9d} "
              f"{r['cycles'] / r['instructions']:5.2f} {ms:8.2f}")
    asm = [r for r in rows if not r["name"].startswith("c/")]
    cc = [r for r in rows if r["name"].startswith("c/")]
    print(f"suite: {suite_time(asm, mc):.1f} ms hand-written, {suite_time(cc, mc):.1f} ms compiled C")
    return 0
