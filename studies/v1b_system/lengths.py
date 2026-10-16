"""Variable-length cycles (RFC 0007 section 4, decided): every
microinstruction says how long its own cycle is, as one of four length
classes in a 16th microcode ROM; jumpers on the CPU card map each class to
a number of 20 ns ticks.

For every distinct microinstruction, static timing analysis of the card's
CPU core (heron.infra.hw.sta, on cpu.build(card=True, stub=True)) finds
the fewest ticks that meet every setup time and every SRAM write, with the
write window the clock generator makes (cpucard.py): open from tick 10,
closed two ticks before the end. A write's control inputs must settle
before the window opens, so that its strobe can't glitch: the analysis
takes a strobe to start when its last input arrives, but a gate whose
inputs are still settling inside the window can pulse more than once.
That rule is why the window opens late. A microinstruction that can reach
the bus needs at least 12 ticks, for the clock generator's hold point.

The four lengths are chosen to minimise the time the program suite takes
on the RTL model's microinstruction counts (for the default parts at
worst case). The class of each microinstruction is fixed by that choice;
the jumpers for other parts and corners are the longest requirement in
each class.
"""

import json
import os
from collections import Counter
from itertools import combinations

from heron import BUILD
from heron.infra.hw import chips, sta
from heron.studies.v1b_hw import cpu, machine as v1b_machine
from heron.studies.v1b_hw import ucode as uc

from . import cpucard

TICK = cpucard.TICK_PS / 1000
# the window must be at least a tick long; the counter's range sets the most
K_MIN, K_MAX = cpucard.WINDOW_OPEN + cpucard.TAIL + 1, cpucard.HEAD + cpucard.TAIL + 16
K_BUS = 12
CACHE = os.path.join(BUILD, "v1b_system")


def window(k, off):
    """The write window of a k-tick cycle, from the CPU's clock edge (ns)."""
    return TICK * cpucard.WINDOW_OPEN + off, TICK * (k - cpucard.TAIL) + off


def write_slack(w, t_open, t_close):
    """The worst slack of an SRAM write in a window: its strobe's pulse
    width, address setup and hold to its end, data setup, and its controls
    settling before the window opens."""
    ctrl_t, dW, gd, addr_t, data_t, tWP, tAS, tAW, tDW = w[:9]
    t_fall = max(ctrl_t, t_open + dW) + gd
    t_rise = t_close + dW + gd
    return min(t_rise - t_fall - tWP, t_fall - addr_t - tAS, t_rise - addr_t - tAW,
               t_rise - data_t - tDW, t_open + dW - ctrl_t)


def clock_offset(corner):
    """The write window's edges come from two 74F109s through a 74F08, the
    CPU clock's from a 74F175: the difference in their delays."""
    t = chips.load_timing()
    d = lambda p, a: t[p]["delays"][a][corner]  # noqa: E731
    return d("74F109", "CLK->Q") + d("74F08", "A->Y") - d("74F175", "CLK->Q")


def requirements(variant=chips.DEFAULT_VARIANT, corner="max", wires=None):
    """{packed control word: ticks it needs}, over every distinct
    microinstruction (with and without an interrupt pending). `wires`:
    a routed board's wiring delays, from infra/pcb/wires.py's
    back_annotate()."""
    nl = cpu.build(card=True, stub=True)
    if wires:
        from heron.infra.pcb import wires as pcb_wires
        refs = {i.ref for i in nl.instances}
        pcb_wires.apply(nl, {k: v for k, v in wires.items() if k[0] in refs})
    N = sta.Netlist(nl, variant, corner)
    off = clock_offset(corner)
    out = {}
    for (w, extra), _labels in v1b_machine.sta_words().items():
        consts = sta.constants_for(v1b_machine, w, dict(extra))
        case = sta.Case(N, consts, 0.0, 0.0)
        chk = sta.checks(case, N, 0.0)
        setup = max([c for k, c, _, _ in chk if k == "setup"] + [0.0])
        writes = [c for k, c, _, _ in chk if k == "write"]
        need = None
        for k in range(K_MIN, K_MAX + 1):
            if setup > TICK * k:
                continue
            o, c = window(k, off)
            if all(write_slack(x, o, c) >= 0 for x in writes):
                need = k
                break
        if need is None:
            raise ValueError(f"microinstruction {_labels[0]} needs more than {K_MAX} ticks")
        if bus_capable(w):
            need = max(need, K_BUS)
        out[w] = max(out.get(w, 0), need)
    return out


def bus_capable(word):
    """A microinstruction that reads or writes at the MAR: it may reach the
    bus, so the clock generator may hold it."""
    f = uc.unpack(word)
    return bool(f["ADDRMAR"]) and (bool(f["MEMWR"]) or f["MEMRD"] == 1)


def rom_words():
    """{ROM address: packed control word}, from the 15 ROM images."""
    imgs, _ = uc.rom_images()
    n = len(imgs[0])
    out = {}
    for a in range(n):
        w = 0
        for k, img in enumerate(imgs):
            w |= img[a] << (8 * k)
        out[a] = w
    return out


def profile():
    """Executions of each ROM address over the program suite, on the RTL
    model (cached in build/v1b_system/profile.json)."""
    path = os.path.join(CACHE, "profile.json")
    srcs = v1b_machine.sources() + [os.path.abspath(__file__)]
    if os.path.exists(path) and os.path.getmtime(path) > max(os.path.getmtime(p) for p in srcs):
        with open(path) as f:
            return Counter({int(k): v for k, v in json.load(f).items()})
    from heron.infra import asm as asmcore
    from heron.infra.programs import metadata
    from heron.studies.v1_isa import v1b
    from heron.studies.v1b_hw.rtl import RTL
    total = Counter()
    for p in v1b_machine.program_paths():
        img = asmcore.assemble_file(v1b, p)
        r = RTL(img, inp=metadata(p)["input"])
        r.ucount = Counter()
        r.run(max_cycles=200_000_000)
        total.update(r.ucount)
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w") as f:
        json.dump(total, f)
    return total


def choose(req, words, prof, n=4):
    """The n lengths (the longest requirement among them) that minimise
    the suite's total time: (lengths, time in ticks)."""
    weight = Counter()
    for a, cnt in prof.items():
        weight[req[words[a]]] += cnt
    ks = sorted(set(req.values()))
    top = ks[-1]
    best = None
    for rest in combinations(ks[:-1], min(n - 1, len(ks) - 1)):
        lens = sorted(rest) + [top]
        t = sum(cnt * next(x for x in lens if x >= k) for k, cnt in weight.items())
        if best is None or t < best[1]:
            best = (lens, t)
    lens = best[0]
    while len(lens) < n:
        lens = [lens[0]] + lens
    return lens, best[1]


def assign(variant=chips.DEFAULT_VARIANT, corner="max", wires=None):
    """The length classes: (class of each packed word, jumper lengths for
    this variant and corner, the suite's ticks with them, its ticks at a
    fixed clock). `wires` as for requirements()."""
    req = requirements(variant, corner, wires)
    words = rom_words()
    prof = profile()
    lens, t = choose(req, words, prof)
    cls = {w: next(i for i, x in enumerate(lens) if x >= k) for w, k in req.items()}
    fixed = sum(prof.values()) * max(lens)
    return cls, lens, t, fixed


def jumpers(cls, variant, corner):
    """Lengths of the classes for other parts: the longest requirement in each."""
    req = requirements(variant, corner)
    out = [K_MIN] * 4
    for w, c in cls.items():
        out[c] = max(out[c], req.get(w, K_MIN))
    for i in range(1, 4):
        out[i] = max(out[i], out[i - 1])
    return out


def class_rom(cls):
    """The 16th microcode ROM: each address's class (unused addresses get
    the longest)."""
    words = rom_words()
    img = bytearray(len(words))
    for a, w in words.items():
        img[a] = cls.get(w, 3)
    return bytes(img)
