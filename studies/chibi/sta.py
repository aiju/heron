"""Static timing analysis of Chibi Heron's netlist: infra/hw/sta.py's case
analysis on board.build(sim=False), whose clock generator is a fixture
(`chibiclk`) giving its phases at their ticks, an eighth of the period T
apart, a 22V10's clock-to-output after them.

Two kinds of case:

  phase R   one per distinct microinstruction (and, for a memory access at
            MAR, with A31 0 and 1: the RAM and the I/O space): the control
            store's outputs held at the word's values, arriving when the
            flash gives them; PHW and YOE low from tick 3, CLKW rising at
            tick 3 (PC and MAR change), the memory's strobes (U_MEMC, on
            the master clock) active from tick 4: the RAM's and the devices'
            write enables to tick 7, IORD_n to the cycle's end. What the
            cycle's end loads must be there its setup before T; U_MEMC's
            inputs before tick 4; a write's address before its strobe and
            its data its setup before the strobe's end.
  phase W   one for the cycle's start, the control store's outputs unknown:
            the register file's write (RA from WA, Y on D from tick 1, the
            strobe in tick 1), PC's and MAR's loads at CLKW, the video's
            read of the RAM, loaded at the pixel clock's edge in tick 2.

The machine's period is the largest T any requirement asks for. The
video wants it to be four pixels of VGA's 25.175 MHz, 158.9 ns.
"""

import math
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from heron.infra.hw import chips, sta as hsta

from . import board, parts, routines, ucode as uc

NEG = hsta.NEG
VARIANT = parts.VARIANT
CORNER = "max"
TURNOFF = True
SHARP = True
VGA_PERIOD = 4 * 1e3 / 25.175          # four pixels, ns

# the fields that don't change a microinstruction's paths
UNTIMED = ("JT", "PT", "HALT", "KR", "KW")


def _gal_delays():
    tm = chips.load_timing()
    return {k: v / 1000.0 for k, v in chips.delays_for(tm, "ATF22V10C-5", CORNER).items()}


GAL = _gal_delays()
TCO = GAL["CLK->Q"]
CPU_CLOCKS = {f"CLK{i}" for i in range(1, 9)} | {"CLK0"}


class Case(hsta.Case):
    """A case in phase R (phase='R') or the phase W case (phase='W')."""

    phase = "R"

    def m_chibiclk(self, inst, pin, d):
        k = self.T / 8
        if self.phase == "R":
            # T2-T0, the master clock's tick, as U_MEMC's registers see it: there a
            # tick before each edge
            fixed = {"PHW": (0, 3 * k), "YOE": (0, 3 * k), "RWS": (0, 2 * k), "VLD": (0, 3 * k),
                     "CLKW": (None, 3 * k), "T0": (None, NEG), "T1": (None, NEG),
                     "T2": (None, NEG)}
        else:
            fixed = {"PHW": (1, 0.0), "YOE": (1, k), "RWS": (None, k), "VLD": (None, k),
                     "CLKW": (None, NEG), "T0": (None, 0.0), "T1": (None, 0.0), "T2": (None, 0.0)}
        if pin == "CLK":
            return (None, 0.0, True, None)
        if pin == "RESET":
            return (1, NEG, True, None)
        if pin in ("MCLK", "PIX"):
            return (None, NEG, True, None)
        v, t = fixed[pin]
        if t == NEG:
            return (v, NEG, True, None)
        return (v, t + TCO, True, (inst.ref, pin, f"{pin} at tick {round(t / k)}"))

    def m_gal(self, inst, pin, d):
        if inst.ref == "U_MEMC" and any(o[0] == pin and o[1] for o in inst.gal):
            return self.strobe(inst, pin)
        return super().m_gal(inst, pin, d)

    def strobe(self, inst, pin):
        """The memory's strobes, registered on the master clock: in phase R
        active from tick 4 if this microinstruction may make them so, else
        inactive (1); in phase W inactive."""
        net = inst.conn[pin]
        k = self.T / 8
        if self.phase == "W":
            # inactive, since tick 0 if the cycle before was an access
            return (1, TCO, True, (inst.ref, "T0", "tick 0"))
        mop = sum(self.const.get(n, 0) << i for i, n in enumerate(board.MOP))
        a31 = self.const.get("A31")
        active = {"WEL_n": mop == uc.MOP_WRM and a31 != 1, "WEH_n": mop == uc.MOP_WRM and a31 != 1,
                  "IOWR_n": mop == uc.MOP_WRM and a31 != 0,
                  "IORD_n": mop == uc.MOP_RDM and a31 != 0}[net]
        if not active:
            return (1, NEG, True, None)
        return (None, 4 * k + TCO, True, (inst.ref, "T0", "tick 4"))


def build():
    return board.build(sim=False)


def control_nets():
    return board.control_nets()


def sta_words():
    """{(word, extra constants): [labels]}: the distinct microinstructions
    (the untimed fields cleared), a memory access at MAR twice."""
    cs = routines.control_store()
    mask = 0
    for name in UNTIMED:
        b, w, _ = uc._pos[name]
        mask |= ((1 << w) - 1) << b
    out = defaultdict(list)
    for a, w in enumerate(cs.words):
        f = uc.unpack(w)
        if f["HALT"]:
            continue
        key = w & ~mask
        page, n, op, step = a >> 17, a >> 13 & 15, a >> 5 & 0xFF, a & 31
        label = f"{op:02X} p{page} n{n:X} s{step}"
        if f["MOP"] in (uc.MOP_RDM, uc.MOP_WRM):
            for a31 in (0, 1):
                lst = out[(key, (("A31", a31),))]
                if len(lst) < 8:
                    lst.append(label + (" I/O" if a31 else " RAM"))
        else:
            lst = out[(key, ())]
            if len(lst) < 8:
                lst.append(label)
    return dict(out)


def result_used(case):
    """Whether the cycle's result goes anywhere: the register file or PC or
    MAR (in the next cycle's phase W)."""
    def val(name):
        return sum(case.const.get(n, 0) << i for i, n in enumerate(board.field(name)))
    return bool(val("WEN") or val("AXP") or val("AXM"))


def clock_of(inst):
    return inst.conn.get("CLK")


def requirements(case, N):
    """The case's requirements: (T >= value, description, endpoint net),
    each a function of T as the case was computed at case.T."""
    k = case.T / 8
    out = []
    for inst in N.insts:
        t = inst.type
        d = N.delay[inst.ref]
        if t.model == "reg377":
            if case.phase != "R":
                continue
            en = case.pin(inst, "EN")[0]
            pins = [("EN", d["setup EN"])] + ([] if en == 1 else
                                               [(f"D{i}", d["setup D"]) for i in range(1, 9)])
            for p, su in pins:
                ta = case.pin(inst, p)[1]
                if ta != NEG:
                    out.append((ta + su, f"{inst.ref}.{p} setup", inst.conn[p]))
        elif t.model == "gal":
            ck = clock_of(inst)
            regs = [o for o in inst.gal if o[1]]
            if not regs:
                continue
            if ck in CPU_CLOCKS:
                if case.phase != "R":
                    continue
                if inst.ref in ("U_YLO", "U_YHI") and not result_used(case):
                    continue        # Y loads every cycle; only a write or a load uses it
                edge = lambda ta, su: ta + su                       # noqa: E731
            elif ck == "CLKW" and case.phase == "W":
                # T >= the time PC and MAR load, 3T/8 + tCO, as their inputs ask
                edge = lambda ta, su: (ta + su - TCO) * 8 / 3       # noqa: E731
            elif inst.ref == "U_MEMC" and case.phase == "R":
                edge = lambda ta, su: (ta + su) * 8 / 4             # noqa: E731
            elif inst.ref in ("U_SHA", "U_SHB") and case.phase == "W":
                edge = lambda ta, su: (ta + su - TCO) * 8 / 2       # noqa: E731
            else:
                continue
            # the inputs that time each register's next value (a term another
            # covers doesn't: infra's rule for the combinatorial outputs)
            pins = set()
            for _pin, _reg, _inv, terms in regs:
                pins |= case._gal_sop(inst, terms)[1]
            for p in sorted(pins):
                ta = case.pin(inst, p)[1]
                if ta != NEG:
                    out.append((edge(ta, GAL["setup"]), f"{inst.ref}.{p} setup", inst.conn[p]))
        elif t.model == "sram":
            we, wv = inst.conn["WE"], case.net(inst.conn["WE"])[0]
            if wv == 1:
                continue
            addr = max(case.pin(inst, p)[1] for p in hsta.address_pins(inst))
            data = max(case.pin(inst, f"IO{i}")[1] for i in range(8))
            if inst.ref.startswith("U_RF"):
                # the strobe: RWS (tick 1) through U_RFA2
                fall, rise = k + TCO + GAL["tPD"], 2 * k + TCO + GAL["tPD"]
                out.append((-1, "", we)) if False else None
                out.append((8 * (addr + d["tAS"] - TCO - GAL["tPD"]), f"{inst.ref} address "
                            "before its write (tAS)", inst.conn["A0"]))
                out.append((8 * (data + d["tDW"] - TCO - GAL["tPD"]) / 2, f"{inst.ref} data "
                            "before its write ends (tDW)", inst.conn["IO0"]))
                del fall, rise
            else:
                # the RAM: WEL_n/WEH_n, ticks 4-6
                out.append((8 * (addr + d["tAS"] - TCO) / 4, f"{inst.ref} address before its "
                            "write (tAS)", "A1"))
                out.append((8 * (data + d["tDW"] - TCO) / 7, f"{inst.ref} data before its "
                            "write ends (tDW)", inst.conn["IO0"]))
        elif t.model == "uart16550" and case.phase == "R":
            mop = sum(case.const.get(n, 0) << i for i, n in enumerate(board.MOP))
            if mop not in (uc.MOP_RDM, uc.MOP_WRM) or case.const.get("A31") != 1:
                continue
            dd = chips.load_timing()["TL16C550C"]["checks"]
            a = max(case.pin(inst, p)[1] for p in ("A0", "A1", "A2", "CS2"))
            out.append((8 * (a + dd["tAS"] - TCO) / 4, f"{inst.ref} address before its strobe",
                        inst.conn["A0"]))
            if mop == uc.MOP_WRM:
                dt = max(case.pin(inst, f"D{i}")[1] for i in range(8))
                out.append((8 * (dt + dd["tDS"] - TCO) / 7, f"{inst.ref} data before its write "
                            "strobe ends", inst.conn["D0"]))
    return out


_N = None


def netlist():
    global _N
    if _N is None:
        _N = hsta.Netlist(build(), VARIANT, CORNER)
    return _N


def case_for(word, extra, T, phase="R"):
    N = netlist()
    if phase == "R":
        const = hsta.constants_for(sys_module(), word, dict(extra))
    else:
        const = {}
    c = Case(N, const, T, 0.5, None, TURNOFF, SHARP)
    c.phase = phase
    return c


def sys_module():
    import sys
    return sys.modules[__name__]


def need(word, extra, phase="R", T0=VGA_PERIOD):
    """The shortest period this case meets: requirements recomputed at the
    period they ask for until they agree (the phases move with T)."""
    T = T0
    for _ in range(12):
        c = case_for(word, extra, T, phase)
        req = requirements(c, netlist())
        if not req:
            return 0.0, None
        worst = max(req, key=lambda r: r[0])
        if abs(worst[0] - T) < 0.05:
            return worst[0], worst
        T = max(worst[0], 1.0)
    return T, worst


def _work(item):
    (w, extra), labels = item
    T, worst = need(w, extra)
    return T, w, extra, labels, worst


def analyse(jobs=None):
    """[(period, word, extra, labels, worst requirement)], slowest first, and
    the phase W case's."""
    items = list(sta_words().items())
    jobs = jobs or min(8, os.cpu_count() or 1)
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(_work, items, chunksize=8))
    res.sort(key=lambda r: -r[0])
    wT, wworst = need(0, (), phase="W")
    return res, (wT, wworst)


def describe(word):
    f = uc.unpack(word)
    out = []
    for name, (b, w, _) in uc._pos.items():
        v = f[name]
        if not v or name in UNTIMED:
            continue
        if name == "AOP":
            out.append(f"AOP={uc.AOP_NAME.get(v, v)}")
        elif name == "FL":
            out.append(f"FL={uc.FL_NAME.get(v, v)}")
        else:
            out.append(f"{name}={v}")
    return " ".join(out)


def report(res, w, paths=3):
    lines = []
    T = max(res[0][0], w[0])
    lines.append(f"minimum period {T:.1f} ns ({1000 / T:.2f} MHz); VGA wants {VGA_PERIOD:.1f} ns "
                 f"({'met' if T <= VGA_PERIOD else 'NOT met'}, slack {VGA_PERIOD - T:.1f} ns)")
    lines.append(f"  phase W (register write, PC and MAR, the video's read): {w[0]:.1f} ns, "
                 f"{w[1][1] if w[1] else '-'}")
    lines.append("")
    lines.append("slowest microinstructions (phase R):")
    for T_, wd, extra, labels, worst in res[:12]:
        lines.append(f"  {T_:6.1f} ns  {labels[0]:<22} {worst[1] if worst else ''}")
    lines.append("")
    N = netlist()
    for T_, wd, extra, labels, worst in res[:paths]:
        c = case_for(wd, extra, T_)
        lines.append(f"critical path of {labels[0]} ({describe(wd)}) at {T_:.1f} ns: {worst[1]}")
        for net, t, ref, dn in c.path(worst[2]):
            lines.append(f"    {t:7.1f} ns  {net:<14} {ref:<10} {dn}")
        lines.append("")
    if w[1]:
        c = case_for(0, (), w[0], "W")
        lines.append(f"critical path of phase W at {w[0]:.1f} ns: {w[1][1]}")
        for net, t, ref, dn in c.path(w[1][2]):
            lines.append(f"    {t:7.1f} ns  {net:<14} {ref:<10} {dn}")
        lines.append("")
    hist = defaultdict(int)
    for T_, *_r in res:
        hist[int(T_ // 10) * 10] += 1
    lines.append(f"required periods over {len(res)} distinct cases:")
    for b in sorted(hist):
        lines.append(f"  {b:4d}-{b + 9:<4d} ns: {hist[b]}")
    del N
    return "\n".join(lines)


def cmd_sta(args):
    res, w = analyse()
    print(f"static timing analysis (chibi): {VARIANT}, {CORNER} delays")
    print(report(res, w, paths=args.paths))
    return 0


del math
