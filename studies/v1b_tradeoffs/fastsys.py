"""The system with fast parts on the CPU card (parts.py: "fast", with the
control store in SRAM, or "fast-flash", with it in flash) and the card's
clock generator for short cycles (fastcard.py): the backplane, the memory
card and the I/O card are v1b_system's, unchanged.

The length classes are chosen as v1b_system's lengths.py chooses them,
with this card's write window and K_BUS; the run, the preloads and the
checks against the instruction-level model are v1b_system's.

  heron v1b_tradeoffs fast [--parts SET] lengths      the classes and the suite's time
  heron v1b_tradeoffs fast [--parts SET] run PROG.s   one program on the fast system
  heron v1b_tradeoffs fast [--parts SET] test [NAMES] the suite at chip level (~10 min)
"""

import json
import os
from concurrent.futures import ProcessPoolExecutor

from heron import BUILD, native
from heron.infra.hw import chips, sta
from heron.studies.v1b_hw import cpu
from heron.studies.v1b_hw import machine as v1b_machine
from heron.studies.v1b_system import backplane, bus, iocard, lengths, machine, memcard, programs

from . import fastcard, parts

VARIANT = "fast"
SETS = ("fast", "fast-flash")


def out_dir(variant):
    return os.path.join(BUILD, "v1b_tradeoffs", f"system-{variant}")

TICK = fastcard.TICK_PS / 1000


def sources():
    here = os.path.dirname(os.path.abspath(__file__))
    return machine.sources() + [os.path.join(here, f) for f in ("fastcard.py", "fastsys.py", "parts.py")]


def _fresh(path):
    return os.path.exists(path) and os.path.getmtime(path) > max(os.path.getmtime(p) for p in sources())


def clock_offset(corner):
    """The window's edges come from 74F109s through a 74F08, the CPU
    clock's from a 74F175 (as on v1b_system's card)."""
    t = chips.load_timing()
    d = lambda p, a: t[p]["delays"][a][corner]  # noqa: E731
    return d("74F109", "CLK->Q") + d("74F08", "A->Y") - d("74F175", "CLK->Q")


def requirements(variant=VARIANT, corner="max"):
    """{packed control word: ticks it needs} with this card's write window
    (from tick 2 to the tail) and K_BUS for a microinstruction that can
    reach the bus: v1b_system's lengths.requirements, for this card."""
    N = sta.Netlist(cpu.build(card=True, stub=True), variant, corner)
    off = clock_offset(corner)
    out = {}
    for (w, extra), labels in v1b_machine.sta_words().items():
        case = sta.Case(N, sta.constants_for(v1b_machine, w, dict(extra)), 0.0, 0.0)
        chk = sta.checks(case, N, 0.0)
        setup = max([c for k, c, _, _ in chk if k == "setup"] + [0.0])
        writes = [c for k, c, _, _ in chk if k == "write"]
        need = None
        for k in range(fastcard.K_MIN, fastcard.K_MAX + 1):
            if setup > TICK * k:
                continue
            t_open = TICK * fastcard.WINDOW_OPEN + off
            t_close = TICK * (k - fastcard.TAIL) + off
            if all(lengths.write_slack(x, t_open, t_close) >= 0 for x in writes):
                need = k
                break
        if need is None:
            raise ValueError(f"microinstruction {labels[0]} needs more than {fastcard.K_MAX} ticks")
        if lengths.bus_capable(w):
            need = max(need, fastcard.K_BUS)
        out[w] = max(out.get(w, 0), need)
    return out


def classes(variant=VARIANT):
    """(class of each packed word, {lengths, ticks, fixed_ticks}): cached."""
    path = os.path.join(out_dir(variant), "classes.json")
    if not _fresh(path):
        req = requirements(variant)
        words, prof = lengths.rom_words(), lengths.profile()
        lens, t = lengths.choose(req, words, prof)
        cls = {w: next(i for i, x in enumerate(lens) if x >= k) for w, k in req.items()}
        fixed = sum(prof.values()) * max(lens)
        os.makedirs(out_dir(variant), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"lengths": lens, "ticks": t, "fixed_ticks": fixed,
                       "classes": {str(w): c for w, c in cls.items()}}, f)
    with open(path) as f:
        d = json.load(f)
    return {int(w): c for w, c in d["classes"].items()}, d


def build(lengths_, n_simple=machine.N_SIMPLE, bus_div=3):
    cards = {machine.SLOTS["CPU"]: fastcard.build(lengths_, bus_div),
             machine.SLOTS["MEM"]: memcard.build(), machine.SLOTS["IO"]: iocard.build()}
    return bus.compose(backplane.build(n_simple), cards)


def netlist(variant=VARIANT, corner="max", lengths_=None):
    lengths_ = lengths_ or tuple(classes(variant)[1]["lengths"])
    path = os.path.join(out_dir(variant), f"netlist-{corner}-{'-'.join(map(str, lengths_))}.json")
    if not _fresh(path):
        os.makedirs(out_dir(variant), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(build(lengths_).export(variant=variant, corner=corner), f)
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


def class_rom(cls):
    """v1b_system's class ROM, with the longest class wherever FAULT is set.
    The first microinstruction of a trap after a bus error starts with
    FAULT still high (BUSERR is the last access's BUSACC and the bus
    side's EQ); it falls about 40 ns in, when this microinstruction's
    BUSACC does, and only then can the next address settle. Static timing
    doesn't see that path (its CPU ties BUSERR to 0), so the fault pages
    are made as long as the longest microinstruction. They run once per
    trap."""
    from heron.studies.v1b_hw import ucode as uc
    rom = bytearray(lengths.class_rom(cls))
    for a in range(len(rom)):
        if a >> uc.FAULT_BIT & 1:
            rom[a] = 3
    return bytes(rom)


def preloads(img, inp=b"", cls=None, variant=VARIANT):
    """v1b_system's preloads, with this system's class ROM."""
    pre = machine.preloads(img, inp)
    pre["CPU.U_UC15"] = class_rom(cls if cls is not None else classes(variant)[0])
    return pre


def run(path, max_cycles=20_000_000, lengths_=None, cls=None, corner="max", variant=VARIANT):
    """A program on the fast system at chip level, decoded as
    v1b_system's machine.run decodes it. lengths_ and cls override the
    jumpers and the class ROM (a test runs with every class 6 ticks long)."""
    img = programs.assemble(path)
    inp = programs.metadata(path)["input"]
    hw = native.hwsim.run_system(netlist(variant, corner, lengths_), machine.config(max_cycles),
                                 preloads(img, inp, cls, variant))
    return img, machine.decode(hw)


def check(path, **kw):
    from heron.studies.v1b_system import cli
    _img, hw = run(path, **kw)
    return cli.check(path, hw)


def _job(args):
    path, variant = args
    try:
        diffs, hw, _m = check(path, variant=variant)
    except Exception as e:  # noqa: BLE001  (reported per program)
        return path, [f"{type(e).__name__}: {e}"], None
    return path, diffs, {k: hw[k] for k in ("cycles", "time_ps", "wall_seconds", "violation_total",
                                            "violation_summary", "contention")}


def test(names=None, jobs=4, variant=VARIANT):
    """The suite at chip level: {program: (diffs, summary)}."""
    paths = programs.program_paths(names or None)
    classes(variant)                       # before the workers need it
    out = {}
    with ProcessPoolExecutor(jobs) as ex:
        for path, diffs, hw in ex.map(_job, [(p, variant) for p in paths]):
            out[os.path.basename(path)[:-2]] = (diffs, hw)
    return out
