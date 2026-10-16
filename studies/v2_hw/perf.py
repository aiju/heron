"""Where the draft 2 CPU's time goes: the program suite (the hand-written
programs and the compiled C ones) on the register-transfer model, with
the microinstructions' counts, from which the length classes are chosen
and the time is costed.

Results are cached in build/v2_hw/ by the sources they depend on.
"""

import hashlib
import json
import os
import pickle
from collections import Counter

from heron import BUILD

from . import check, timing, ucode as uc

OUT = os.path.join(BUILD, "v2_hw")
SKIP = ("hello", "interrupts")      # as report 0012: no work / mostly halted
BUS_SKIP = ("interrupts",)          # its vectors are at physical 0, in the CPU card's RAM
MAX_CYCLES = 50_000_000


# the sources a profile depends on
SOURCES = ("ucode.py", "rtl.py", "system.py", "check.py", "timing.py", "perf.py")


def _sources_tag():
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for f in SOURCES:
        with open(os.path.join(here, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


def suite(c=True, asm=True):
    """[(name, image, input)] for the suite: hand-written, then C."""
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.infra.programs import metadata
    out = []
    if asm:
        for p in check.program_paths():
            name = os.path.basename(p)[:-2]
            if name in ("systest", "isanotes"):
                continue
            img = asmcore.assemble_file(isas.get("v2"), p)
            out.append((name, img, metadata(p)["input"]))
    if c:
        out += check.c_programs()
    return out


def run_one(name, mem, inp, code_base=0, **opts):
    from types import SimpleNamespace
    m = check.run_rtl(SimpleNamespace(mem=mem), inp, code_base=code_base, profile=True,
                      max_cycles=MAX_CYCLES, **opts)
    return {
        "name": name, "instructions": m.instructions, "cycles": m.cycles, "ticks": m.ticks,
        "hold": m.hold_ticks, "refills": m.refills, "fetch_words": m.fetch_words,
        "wasted": m.fetch_wasted, "ucount": dict(m.ucount), "refill_from": dict(m.refill_from),
        "bus": (m.sys.bus_reads, m.sys.bus_writes, m.sys.bus_fetches),
        "icache_hits": m.sys.icache_hits,
    }


def profile(code_base=0, force=False, jobs=4, **opts):
    """Every program's counts, cached by the sources and the programs'
    images. With the code over the bus, without the interrupt program,
    whose vectors must be at physical 0."""
    progs = suite()
    if code_base:
        progs = [p for p in progs if p[0] not in BUS_SKIP]
    h = hashlib.sha1(_sources_tag().encode())
    for name, img, inp in progs:
        h.update(name.encode() + bytes(inp) + repr(sorted(img.mem.items())).encode())
    tag = h.hexdigest()[:12] + f"-{code_base:x}-" + \
        "-".join(f"{k}{v}" for k, v in sorted(opts.items()))
    path = os.path.join(OUT, f"profile-{tag}.pickle")
    if not force and os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(jobs) as ex:
        futs = [ex.submit(run_one, n, dict(i.mem), inp, code_base, **opts) for n, i, inp in progs]
        rows = [f.result() for f in futs]
    os.makedirs(OUT, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(rows, f)
    return rows


def best_lengths(rows, mc=None):
    """Four lengths that minimise the suite's time, given how often each
    microinstruction runs."""
    mc = mc or uc.built()
    need = Counter()
    for r in rows:
        for a, n in r["ucount"].items():
            need[mc.ticks[a]] += n
    return timing.best_lengths(need), need


def time_with(rows, lengths, mc=None):
    """{program: ticks} with these length classes (bus holds as measured)."""
    mc = mc or uc.built()
    out = {}
    for r in rows:
        t = r["hold"]
        for a, n in r["ucount"].items():
            need = mc.ticks[a]
            t += n * min(L for L in lengths if L >= need)
        out[r["name"]] = t
    return out


KINDS = [
    ("refill", lambda n: n.name == "refill"),
    ("trap entry", lambda n: n.name.startswith(("trap", "interrupt", "page fault", "address",
                                                 "SWI", "illegal", "fault"))),
    ("multiply, divide", lambda n: n.f.get("MQM") or n.f.get("MS")),
]


def kind_of(node):
    f = node.f
    if node.name == "refill":
        return "refill after a jump"
    mem = f.get("MEM", 0)
    if f.get("MQM") or f.get("MS"):
        return "multiply or divide step"
    if mem in (1, 6):
        return "data read"
    if mem == 2:
        return "data write"
    if mem in (4, 5):
        return "page map"
    if f.get("LDPC"):
        return "jump or branch"
    if f.get("CONSUME"):
        return "extension parcel"
    if node.succ[0] == "decode" and not (f.get("RFWE") or f.get("FNZ") or f.get("LDR")):
        return "decode only"
    return "ALU, address or shift"


def breakdown(rows, mc=None):
    mc = mc or uc.built()
    out = Counter()
    for r in rows:
        if r["name"] in SKIP:
            continue
        for a, n in r["ucount"].items():
            out[kind_of(mc.by_addr[a])] += n
    return out


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="heron v2_hw perf")
    p.add_argument("--bus", action="store_true")
    p.add_argument("--icache", type=int, default=0)
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    opts = {"icache": args.icache} if args.icache else {}
    rows = profile(code_base=0x08000000 if args.bus else 0, force=args.force, **opts)
    lens, need = best_lengths(rows)
    times = time_with(rows, lens)
    print(f"length classes from the profile: {lens} ticks")
    tot_i = tot_c = tot_t = 0
    for r in rows:
        t = times[r["name"]]
        print(f"{r['name']:12s} {r['instructions']:9d} instr {r['cycles']:9d} cycles "
              f"CPI {r['cycles'] / r['instructions']:5.2f} {t * 20 / 1e6:8.2f} ms "
              f"({t * 20 / r['instructions']:4.0f} ns an instruction) refills {r['refills']}")
        if r["name"] not in SKIP:
            tot_i += r["instructions"]
            tot_c += r["cycles"]
            tot_t += t
    print(f"total {tot_i} instr {tot_c} cycles CPI {tot_c / tot_i:.2f} {tot_t * 20 / 1e6:.1f} ms")
    for k, n in breakdown(rows).most_common():
        print(f"  {k:28s} {n:10d} {100 * n / tot_c:5.1f}%")
    return 0
