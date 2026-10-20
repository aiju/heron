"""Static timing analysis of the two-halves machine (board2.build(sim=False),
whose clock generator is a fixture, chibiclk3, giving U_CGA's and U_CGB's
outputs at their ticks): how many ticks each distinct microinstruction's
halves need, and whether phase F's fixed ticks are met.

  L case   the cycle from phase F's start (the master clock's edge at 0):
           the sequencer's registers load at CLK0, the control store gives
           its word, PHW falls at tick 3, the low half runs; what loads at
           the low half's end (HCK, HCKA, and for a microinstruction without
           a high half the sequencer at CLK0) must be there its setup before
           the edge that ends it, 3 + n ticks
  H case   the high half, from the low half's end at 0: HALF rises, the
           registers the low half loaded change, the control store's word
           steady; what loads at its end (HCK, HCKB, CLK0) likewise, n ticks
  F case   phase F's register file writes (the low pair in tick 1, the high
           pair in tick 2) against their strobes

A half's capture edge is taken as the clock generator's output (a 22V10's
clock-to-output after the master clock's edge), without the clock buffer's
delay that the launching registers see: a little pessimistic. The table of
ticks it finds (ticks.json) gives the control store its LEN and HLEN
(routines2.ControlStore), with the floors the clock generator wants: a
high half at least 2 ticks (HCK's pulse), a half with an access at MAR at
least 3 (it looks at IOACC from its third); an access to the I/O space has
6 ticks whatever, and is checked against them.

  heron chibi hw sta [--paths N] [--write]
"""

import json
import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from heron.infra.hw import chips, sta as hsta

from . import board2, routines2, sta, ucode2 as uc

NEG = hsta.NEG
K = 1e3 / 50.35                 # a tick, ns
TCO = sta.TCO
IO_TICKS = 6
TICKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticks.json")
CPU = {f"CLK{i}" for i in range(9)}
HALF_END = {"L": {"HCK1", "HCK2", "HCK3", "HCK4", "HCKA1", "HCKA2", "LCKA"},
            "H": {"HCK1", "HCK2", "HCK3", "HCK4", "HCKB1", "HCKB2", "LCKB"}}
# the devices' own GALs, on their own clocks: only their outputs onto the
# CPU's buses are timed
DEVICE_GALS = {"U_SLOW", "U_VQ", "U_VC", "U_SLOWD", "U_ODT", "U_VS", "U_LREQ", "U_LINE",
               "U_VH", "U_VV", "U_VF", "U_SHA", "U_SHB", "U_KBD", "U_MOUSE"}


class Case3(hsta.Case):
    phase = "L"
    two = False

    def m_chibiclk3(self, inst, pin, d):
        ph = self.phase
        if pin == "MCLK":
            return (None, NEG, True, None)
        if pin == "RESET":
            return (1, NEG, True, None)
        if pin in ("HLZ", "LASTH"):
            last = ph == "H" or not self.two
            return ({"HLZ": int(not self.two), "LASTH": int(last)}[pin], NEG, True, None)
        if pin in ("TC0", "TC1", "TC2", "PH0", "PH1", "END", "VEXTQ"):
            if ph != "F":
                v = {"PH0": int(ph == "L"), "PH1": int(ph == "H")}.get(pin)
                return (v, NEG, True, None)
            return (None, TCO, True, (inst.ref, pin, f"{pin} at tick 0"))
        if ph == "F":
            fixed = {"CLK0": (None, 0.0), "PHW": (1, 0.0), "HALF": (0, NEG),
                     "HCK": (None, NEG), "HCKA": (None, NEG), "HCKB": (None, NEG),
                     "RFWL_n": (None, K), "RFWH_n": (None, 2 * K), "YAOE": (None, K),
                     "YBOE": (None, K), "HWQ": (None, 0.0)}
        elif ph == "L":
            fixed = {"CLK0": (None, 0.0), "PHW": (0, 3 * K), "HALF": (0, NEG),
                     "HCK": (None, 0.0), "HCKA": (None, 0.0), "HCKB": (None, 0.0),
                     "RFWL_n": (1, NEG), "RFWH_n": (1, NEG), "YAOE": (0, 3 * K),
                     "YBOE": (0, 3 * K), "HWQ": (None, NEG)}
        else:
            fixed = {"CLK0": (None, NEG), "PHW": (0, NEG), "HALF": (1, 0.0),
                     "HCK": (None, 0.0), "HCKA": (None, 0.0), "HCKB": (None, NEG),
                     "RFWL_n": (1, NEG), "RFWH_n": (1, NEG), "YAOE": (0, NEG),
                     "YBOE": (0, NEG), "HWQ": (None, NEG)}
        v, t = fixed[pin]
        if t == NEG:
            return (v, NEG, True, None)
        return (v, t + TCO, True, (inst.ref, pin, f"{pin} at {t / K:.0f} ticks"))

    def m_gal(self, inst, pin, d):
        if inst.ref == "U_MEMC" and any(o[0] == pin and o[1] for o in inst.gal):
            return self.strobe(inst, pin)
        if inst.ref == "U_LCK":
            # LBOE_n: HALF's complement, from the clock generator's state as
            # U_CGB's HALF; the latch's clocks rise at the half's end (the
            # capture); the rest is the devices'
            net = inst.conn.get(pin)
            if net == "LBOE_n" and self.phase == "H":
                return (0, d["CLK->Q"], True, (inst.ref, pin, "LBOE_n at 0"))
            return ({"LBOE_n": 1, "LCKA": 0, "LCKB": 0}.get(net, self.const.get(net)), NEG, True,
                    None)
        out = next((o for o in inst.gal if o[0] == pin), None)
        if out is not None and out[1]:
            ck = inst.conn.get("CLK")
            net = inst.conn.get(pin)
            # registers that don't change in this case: steady (no task
            # starts or ends: TCHG's cycles have phase F a tick longer); in
            # the high half, those not loaded at the low half's end
            if net in ("TASK", "TCHG") or (self.phase == "H" and ck not in HALF_END["L"]):
                return (self.const.get(net), NEG, True, None)
        if inst.ref in DEVICE_GALS:
            net = inst.conn.get(pin, "")
            if not (net.startswith("MD") or net in ("HOLD", "VRD")):
                return (self.const.get(net), NEG, True, None)
        return super().m_gal(inst, pin, d)

    def strobe(self, inst, pin):
        """U_MEMC's strobes, from the half's second tick if this
        microinstruction may make them active, else inactive (the I/O
        strobes from the third, ADS from the fourth)."""
        if self.phase == "F":
            return (1, TCO, True, (inst.ref, "TC0", "tick 0"))
        start = 3 * K if self.phase == "L" else 0.0
        mop = sum(self.const.get(n, 0) << i for i, n in enumerate(board2.MOP))
        if self.phase == "H" and self.const.get("SUPH") == 1:
            return (1, NEG, True, None)
        aio = self.const.get("AIO")
        net = inst.conn[pin]
        rd = mop in (uc.MOP_RDM, uc.MOP_LDIRM)
        io = (mop == uc.MOP_WRM or rd) and aio != 0
        active = {"WEL_n": mop == uc.MOP_WRM and aio != 1, "WEH_n": mop == uc.MOP_WRM and aio != 1,
                  "IOWR_n": mop == uc.MOP_WRM and aio != 0,
                  "IORD_n": rd and aio != 0, "ADS": io, "IOQ": io}[net]
        if net == "IOQ":                # IOACC a tick late
            if not io:
                return (0, NEG, True, None)
            return (None, start + K + TCO, True, (inst.ref, "TC0", "the half's second tick"))
        if net == "ADS":                # the I/O strobes a tick later
            if not active:
                return (0, NEG, True, None)
            return (None, start + 3 * K + TCO, True, (inst.ref, "TC0", "the half's fourth tick"))
        if not active:
            return (1, NEG, True, None)
        if net in ("IORD_n", "IOWR_n"):     # from IOQ, a tick after the RAM's
            return (None, start + 2 * K + TCO, True, (inst.ref, "TC0", "the half's third tick"))
        return (None, start + K + TCO, True, (inst.ref, "TC0", "the half's second tick"))

    def m_i8254(self, inst, pin, d): return (None, NEG, False, None)
    def m_cf(self, inst, pin, d): return (None, NEG, False, None)
    def m_passive(self, inst, pin, d): return (None, NEG, True, None)
    def m_por(self, inst, pin, d): return (None, NEG, True, None)
    def m_osc(self, inst, pin, d): return (None, NEG, True, None)
    def m_button(self, inst, pin, d): return (1, NEG, True, None)


def control_nets():
    return board2.control_nets()


def sys_module():
    import sys
    return sys.modules[__name__]


_N = None


def netlist():
    global _N
    if _N is None:
        _N = hsta.Netlist(board2.build(sim=False), sta.VARIANT, sta.CORNER)
    return _N


def constants(word, extra, phase, two):
    c = hsta.constants_for(sys_module(), word, dict(extra)) if phase != "F" else {}
    # the registers whose values steer a case: no task; HALFD as the half
    c.update(TASK=0, TCHG=0, TASKP=0, DREQ=0, HALFD=int(phase == "H"))
    if phase != "F":
        nat = c.get(board2.HXF[0], 0) == 0 and c.get(board2.HXF[1], 0) == 0
        c["SUPH"] = int(phase == "H" and not nat)
    return c


def case_for(word, extra, phase, two):
    c = Case3(netlist(), constants(word, extra, phase, two), 400.0, 0.5, None, sta.TURNOFF,
              sta.SHARP)
    c.phase, c.two = phase, two
    return c


def _latest(c, inst, pins):
    """(the latest arrival among these pins, its net)."""
    return max((c.pin(inst, p)[1], inst.conn.get(p)) for p in pins)


def requirements(c, fixed_all=None):
    """[(time, description, net)]: when the half must end for each
    requirement, relative to the case's 0; and [(late by, description)] for
    the fixed-tick requirements that fail."""
    N = netlist()
    ph = c.phase
    start = 3 * K if ph == "L" else 0.0
    strobe = start + K + TCO
    last = ph == "H" or not c.two
    capture = HALF_END.get(ph, set()) | (CPU if last else set())
    end, bad = [], []
    for inst in N.insts:
        t, d = inst.type, N.delay[inst.ref]
        if t.model == "gal":
            ck = inst.conn.get("CLK")
            regs = [o for o in inst.gal if o[1]]
            if not regs or ph == "F" or inst.ref in DEVICE_GALS:
                continue
            if inst.ref == "U_MEMC":
                # the strobes start at the half's tick 1; ADS is them a tick
                # later (its inputs are theirs)
                regs = [o for o in regs if inst.conn.get(o[0]) != "ADS"]
                fixed = strobe - TCO
            elif ck in capture:
                fixed = None
            else:
                continue
            if inst.ref == "U_ALUC" and not carry_used(c):
                continue            # HC, for the high half's carry
            pins = set()
            for _p, _r, _i, terms in regs:
                pins |= c._gal_sop(inst, terms)[1]
            if inst.ref == "U_MEMC":        # IOQ, set at tick 1, gates the I/O strobes at tick 2
                pins = {p for p in pins if inst.conn.get(p) != "IOQ"}
            for p in sorted(pins):
                ta = c.pin(inst, p)[1]
                if ta == NEG:
                    continue
                need = ta + d["setup"]
                if fixed is None:
                    end.append((need, f"{inst.ref}.{p} setup", inst.conn[p]))
                else:
                    if fixed_all is not None:
                        fixed_all.append((fixed + 0.05 - need, f"{inst.ref}.{p} setup",
                                          inst.conn[p]))
                    if need > fixed + 0.05:
                        bad.append((need - fixed, f"{inst.ref}.{p} setup"))
        elif t.model == "dreg" and inst.conn.get("CLK") in capture and ph != "F":
            for i in range(1, 9):
                ta = c.pin(inst, f"D{i}")[1]
                if ta != NEG:
                    end.append((ta + d["setup D"], f"{inst.ref}.D{i} setup", inst.conn[f"D{i}"]))
        elif t.model == "sram":
            if inst.ref.startswith("U_RF"):
                if ph != "F":
                    continue
                k = 1 if inst.ref.startswith("U_RFL") else 2
                addr, an = _latest(c, inst, hsta.address_pins(inst))
                data, dn_ = _latest(c, inst, [f"IO{i}" for i in range(8)])
                for late, desc, net in ((addr + d["tAS"] - (k * K + TCO), "address (tAS)", an),
                                        (data + d["tDW"] - ((k + 1) * K + TCO), "data (tDW)",
                                         dn_)):
                    if fixed_all is not None and late != NEG:
                        fixed_all.append((0.05 - late, f"{inst.ref} {desc}", net))
                    if late > 0.05:
                        bad.append((late, f"{inst.ref} {desc}"))
            elif ph != "F" and c.net(inst.conn["WE"])[0] != 1:
                addr, an = _latest(c, inst, hsta.address_pins(inst))
                data = max(c.pin(inst, f"IO{i}")[1] for i in range(8))
                if fixed_all is not None and addr != NEG:
                    fixed_all.append((strobe + 0.05 - addr - d["tAS"],
                                      f"{inst.ref} address before its write", an))
                if addr + d["tAS"] > strobe + 0.05:
                    bad.append((addr + d["tAS"] - strobe, f"{inst.ref} address before its write"))
                end.append((data + d["tDW"] - TCO, f"{inst.ref} data before its write ends",
                            inst.conn["IO0"]))
        elif t.model == "uart16550" and ph != "F":
            mop = sum(c.const.get(n, 0) << i for i, n in enumerate(board2.MOP))
            if mop not in (uc.MOP_RDM, uc.MOP_WRM) or c.const.get("AIO") != 1:
                continue
            dd = chips.load_timing()["TL16C550C"]["checks"]
            # its address and select latched by ADS, a tick into the strobe
            a, an = _latest(c, inst, ("A0", "A1", "A2", "CS2"))
            if fixed_all is not None and a != NEG:
                fixed_all.append((strobe + K + 0.05 - a - dd["tAS"],
                                  f"{inst.ref} address before its strobe", an))
            if a + dd["tAS"] > strobe + K + 0.05:     # (its strobe a tick after the RAM's)
                bad.append((a + dd["tAS"] - strobe - K, f"{inst.ref} address before its strobe"))
            if mop == uc.MOP_WRM:
                dt = max(c.pin(inst, f"D{i}")[1] for i in range(8))
                end.append((dt + dd["tDS"] - TCO, f"{inst.ref} data before its strobe ends",
                            inst.conn["D0"]))
    return end, bad


def carry_used(c):
    """Whether the high half takes the low half's carry (HC): a 32-bit
    arithmetic operation's."""
    if c.phase != "L" or not c.two:
        return False
    f = {name: sum(c.const.get(n, 0) << i for i, n in enumerate(board2.field(name)))
         for name in ("AOP", "HX")}
    if f["HX"] != uc.HX_NAT or f["AOP"] not in uc.AOP_NAME:
        return False
    return any(uc.aop_resolve(uc.AOP_NAME[f["AOP"]], st)[1] == 0 for st in (0, 1))


def ticks_for(need, start):
    """A half's ticks: it ends at an edge n ticks after its start, captured
    a clock-to-output later."""
    return max(1, math.ceil((need - TCO - start) / K - 1e-6))


def sta_words():
    """{(word, two halves, extra constants): [labels]}: the distinct
    microinstructions, the untimed fields cleared; one at MAR twice, for the
    RAM and the I/O space."""
    cs = routines2.ControlStore(ticks={})
    mask = uc.untimed_mask()
    out = defaultdict(list)
    for a, w in enumerate(cs.words):
        f = uc.unpack(w)
        two = f["HLEN"] != 0
        key = w & ~mask
        label = f"{a:04X} {cs.where[a]}"
        if f["MOP"] in (uc.MOP_RDM, uc.MOP_WRM, uc.MOP_LDIRM):
            for aio in (0, 1):
                lst = out[(key, two, (("AIO", aio),))]
                if len(lst) < 8:
                    lst.append(label + (" I/O" if aio else " RAM"))
        else:
            lst = out[(key, two, ())]
            if len(lst) < 8:
                lst.append(label)
    return dict(out)


def floors(f, h):
    """The clock generator's least ticks for a half (h: the high half): a
    high half 2, so that HCK, high for the tick after the low half's end,
    falls before the high half's; a half with an access at MAR 3."""
    mop = f["MOP"]
    if h and f["HX"] != uc.HX_NAT and mop in (uc.MOP_RDM, uc.MOP_WRM, uc.MOP_RDP):
        mop = uc.MOP_NONE
    if mop in (uc.MOP_RDM, uc.MOP_WRM, uc.MOP_LDIRM):
        return 3
    return 2 if h else 1


def time_case(item):
    """(key, the low half's (need, worst, bad), the high half's or None)."""
    (w, two, extra), _labels = item
    out = []
    for ph in ("L", "H"):
        if ph == "H" and not two:
            out.append(None)
            continue
        end, bad = requirements(case_for(w, extra, ph, two))
        worst = max(end, key=lambda r: r[0]) if end else None
        out.append((worst[0] if worst else 0.0, worst, sorted(bad, reverse=True)))
    return (w, two, extra), out[0], out[1]


def analyse(jobs=4):
    items = list(sta_words().items())
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(time_case, items, chunksize=8))
    _fend, fbad = requirements(case_for(0, (), "F", True))
    return res, sorted(fbad, reverse=True)


def table(res):
    """{(word, two): (low ticks, high ticks)}, and the halves that don't fit
    (over the field's most, or an I/O half over 5 ticks)."""
    tab, over = {}, []
    for (w, two, extra), lo, hi in res:
        f = uc.unpack(w)
        io = dict(extra).get("AIO") == 1
        nl_ = max(ticks_for(lo[0], 3 * K), floors(f, 0))
        nh = max(ticks_for(hi[0], 0.0), floors(f, 1)) if hi else 0
        if io:
            if nl_ > IO_TICKS or (hi and floors(f, 1) == 3 and nh > IO_TICKS):
                over.append((max(nl_, nh), "I/O", w, extra))
            continue
        if nl_ > 4 or nh > 3:
            over.append((max(nl_, nh), "low" if nl_ > 4 else "high", w, extra))
        prev = tab.get((w, two), (0, 0))
        tab[(w, two)] = (min(4, max(prev[0], nl_)), min(3, max(prev[1], nh)) if two else 0)
    return tab, over


def write_ticks(tab):
    rows = [[f"{w:018X}", int(two), lo, hi] for (w, two), (lo, hi) in sorted(tab.items())]
    with open(TICKS_PATH, "w") as f:
        f.write("[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]\n")


def path(word, extra, phase, two, worst):
    c = case_for(word, extra, phase, two)
    return [f"    {t:7.1f} ns  {net:<14} {ref:<10} {dn}" for net, t, ref, dn in c.path(worst[2])]


def sta_describe(word):
    f = uc.unpack(word)
    out = []
    for name in uc._pos:
        v = f[name]
        if not v or name in uc.UNTIMED:
            continue
        if name == "AOP":
            out.append(f"AOP={uc.AOP_NAME.get(v, v)}")
        elif name == "FL":
            out.append(f"FL={uc.FL_NAME.get(v, v)}")
        else:
            out.append(f"{name}={v}")
    return " ".join(out)


def report(res, fbad, paths=2):
    tab, over = table(res)
    lines = [f"ticks of {K:.2f} ns; phase F ticks 0-2, the low half from tick 3"]
    lo = Counter(v[0] for v in tab.values())
    hi = Counter(v[1] for v in tab.values() if v[1])
    lines.append(f"low halves' ticks over {len(tab)} words:  " +
                 ", ".join(f"{k}: {v}" for k, v in sorted(lo.items())))
    lines.append(f"high halves' ticks over {sum(hi.values())} words: " +
                 ", ".join(f"{k}: {v}" for k, v in sorted(hi.items())))
    bad = [(b, ph) for r in res for ph, x in (("L", r[1]), ("H", r[2])) if x for b in x[2]]
    lines.append(f"fixed-tick requirements failing: {len(bad)}" +
                 (f" (worst {max(bad)[0][0]:.1f} ns late: {max(bad)[0][1]})" if bad else ""))
    lines.append(f"halves over their field's most (or I/O's 6 ticks): {len(over)}" +
                 (f", e.g. a {over[0][1]} half of {over[0][0]} ticks: {sta_describe(over[0][2])}"
                  if over else ""))
    lines.append(f"phase F: {len(fbad)} failing" +
                 (f", worst {fbad[0][1]} {fbad[0][0]:.1f} ns late" if fbad else ""))
    lines.append("")
    for ph, idx, start in (("low", 1, 3 * K), ("high", 2, 0.0)):
        rs = sorted((r for r in res if r[idx] and dict(r[0][2]).get("AIO") != 1),
                    key=lambda r: -r[idx][0])
        for r in rs[:paths]:
            (w, two, extra), x = r[0], r[idx]
            lines.append(f"slowest {ph} half: {x[0] - start:.1f} ns from its start "
                         f"({ticks_for(x[0], start)} ticks), {sta_describe(w)} {dict(extra)}: "
                         f"{x[1][1]}")
            lines += path(w, extra, "L" if idx == 1 else "H", two, x[1])
            lines.append("")
    return "\n".join(lines)


# the 22V10s' grades, slowest first (timing_bus.json): the zero-power
# CQZ-20, the -15, the -7 in DIP-24; the -5 in PLCC-28
GRADES = ["ATF22V10CQZ-20", "ATF22V10C-15", "ATF22V10C-7"]
# kept at the -5: the clock generator (its outputs are the analysis's
# fixture), the memory's strobes (fixed ticks) and the latch's clocks
GRADE_FIXED = {"U_CGA", "U_CGB", "U_MEMC", "U_LCK"}
# at least the -7: µPC's address in a task (U_TASK's) and the handover
# (U_LREQ's TASKD and TASKOR), which the analysis's cases (no task) don't
# time; the chip-level runs of the copper and the device task do
GRADE_FLOOR = {"U_TASK": "ATF22V10C-7", "U_LREQ": "ATF22V10C-7",
               # its strobes are the CF card's and the palette's, which
               # neither the analysis nor the simulation times
               "U_SLOWD": "ATF22V10C-7"}


def outcome(grades):
    """The analysis with these grades: (the ticks table, the halves over
    their fields, the fixed requirements failing, phase F's failing)."""
    global _N
    saved = board2.GAL_GRADES
    board2.GAL_GRADES = dict(grades)
    _N = None
    try:
        res, fbad = analyse()
    finally:
        board2.GAL_GRADES = saved
        _N = None
    tab, over = table(res)
    bad = sum(len(x[2]) for r in res for x in (r[1], r[2]) if x)
    return tab, (len(over), bad, len(fbad))


def _delta(grade):
    """A grade's delays over the -5's, ns: (tPD, tCO, setup)."""
    t = chips.load_timing()

    def get(part):
        d = chips.delays_for(t, part, sta.CORNER)
        return d["tPD"] / 1000, d["CLK->Q"] / 1000, d["setup"] / 1000
    g, f = get(grade), get("ATF22V10C-5")
    return tuple(x - y for x, y in zip(g, f))


def cones(c):
    """A case's fan-in counter: for a net, {GAL: (combinational passes,
    clocked passes)} at most on any path that times it, as the case has
    it (the inputs constants don't rule out; drivers that are on)."""
    memo = {}

    def merge(into, k):
        for g, (p, q) in k.items():
            a, b = into.get(g, (0, 0))
            into[g] = (max(a, p), max(b, q))

    def net(n):
        if n in memo:
            return memo[n]
        memo[n] = {}
        out = {}
        for inst, pin in c.N.drivers.get(n, []):
            _v, t, en, _cause = c.output(inst, pin)
            if en is False or t == NEG:
                continue
            k = {}
            if inst.type.model == "gal":
                o = next((o for o in inst.gal if o[0] == pin), None)
                if o is None:
                    continue
                if o[1]:
                    merge(k, net(inst.conn["CLK"]))
                    p_, q_ = k.get(inst.ref, (0, 0))
                    k[inst.ref] = (p_, q_ + 1)
                else:
                    for ip in c._gal_sop(inst, o[3])[1]:
                        merge(k, net(inst.conn[ip]))
                    p_, q_ = k.get(inst.ref, (0, 0))
                    k[inst.ref] = (p_ + 1, q_)
                oe = getattr(inst, "gal_oe", {}).get(pin)
                if oe is not None:
                    ko = {}
                    for ip in c._gal_sop(inst, oe)[1]:
                        merge(ko, net(inst.conn[ip]))
                    p_, q_ = ko.get(inst.ref, (0, 0))
                    ko[inst.ref] = (p_ + 1, q_)
                    merge(k, ko)
            elif inst.type.family != "fixture":
                for frm, to, _dn in inst.type.arcs:
                    if pin in to:
                        for ip in frm:
                            if ip in inst.conn:
                                merge(k, net(inst.conn[ip]))
            merge(out, k)
        memo[n] = out
        return out
    return net


def constraints_for(item):
    """A case's requirements as constraints on the GALs' grades: [(phase,
    "end" and the need, or "fixed" and the slack, the instance it ends at,
    {GAL: passes})]; an end requirement's slack is to its half's end, at
    the ticks the table gives."""
    (w, two, extra), _labels = item
    out = []
    for ph in ("L", "H") if two else ("L",):
        c = case_for(w, extra, ph, two)
        fixed = []
        end, _bad = requirements(c, fixed)
        cone = cones(c)
        for need, desc, n in end:
            out.append((ph, "end", need, desc.split(".")[0].split(" ")[0], cone(n)))
        for slack, desc, n in fixed:
            out.append((ph, "fixed", slack, desc.split(".")[0].split(" ")[0], cone(n)))
    return (w, two, extra), out


def grades(log=print, jobs=4):
    """{GAL: grade}, from one analysis: each requirement's slack (to its
    half's end at the ticks the table gives, or to its fixed tick) against
    the GALs that can time it, each its grade's extra delay as many times
    as a path passes it, and the setup's for the GAL it ends at. The
    22V10s go to DIP-24 first (the -7, the most of them), then to the
    -15 and the CQZ-20 for power, each step kept if every requirement
    still meets its slack: a bound, so the table stays the -5s'."""
    global _N
    _N = None
    items = list(sta_words().items())
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(time_case, items, chunksize=8))
        cons = list(ex.map(constraints_for, items, chunksize=8))
    tab, _over = table(res)
    fixed_f = []
    requirements(case_for(0, (), "F", True), fixed_f)
    cf = cones(case_for(0, (), "F", True))
    rows = [(s_, ref, cf(n)) for s_, desc, n in fixed_f
            for ref in [desc.split(".")[0].split(" ")[0]]]
    for (w, two, extra), lst in cons:
        f = uc.unpack(w)
        io = dict(extra).get("AIO") == 1
        for ph, kind, v, sink, k in lst:
            if kind == "fixed":
                rows.append((v, sink, k))
                continue
            lo, hi = tab[(w, two)]
            if ph == "L":
                n, start = (IO_TICKS if io else lo), 3 * K
            else:
                n = IO_TICKS if io and floors(f, 1) == 3 else hi
                start = 0.0
            rows.append((start + n * K + TCO - v, sink, k))
    rows = [r for r in rows if r[2] or r[1]]
    log(f"{len(rows)} requirements")
    nl = board2.build(sim=True)
    gals = [i for i in nl.instances if i.type.name == "22v10" and i.ref not in GRADE_FIXED]
    delta = {g: _delta(g) for g in GRADES}
    delta["ATF22V10C-5"] = (0.0, 0.0, 0.0)
    by = {}
    for i, (_s, sink, k) in enumerate(rows):
        for g in set(k) | {sink}:
            by.setdefault(g, []).append(i)
    used = [0.0] * len(rows)
    pick = {}

    def cost(i, ref, grade):
        _s, sink, k = rows[i]
        dp, dc, ds = delta[grade]
        p, q = k.get(ref, (0, 0))
        return p * dp + q * dc + (ds if sink == ref else 0.0)

    for grade in reversed(GRADES):                  # the -7, the -15, the CQZ-20
        for inst in gals:
            ref = inst.ref
            fast = inst.conn.get("CLK") == "MCLK" and any(o[1] for o in inst.gal)
            floor = GRADE_FLOOR.get(ref, GRADES[1] if fast else GRADES[0])
            if GRADES.index(grade) < GRADES.index(floor):
                continue
            cur = pick.get(ref, "ATF22V10C-5")
            extra = [(i, cost(i, ref, grade) - cost(i, ref, cur)) for i in by.get(ref, [])]
            if all(used[i] + e <= rows[i][0] + 1e-9 for i, e in extra):
                for i, e in extra:
                    used[i] += e
                pick[ref] = grade
    log(f"from the bound: {len(pick)} out of the -5")
    # the bound adds up every path's worst at once: try each -5 left as
    # the -7, the analysis run for it
    base = outcome({})
    for inst in gals:
        if inst.ref not in pick and outcome(dict(pick, **{inst.ref: GRADES[-1]})) == base:
            pick[inst.ref] = GRADES[-1]
            log(f"{inst.ref}: the -7 too")
    return pick


def cmd_grades(pick):
    print("GAL_GRADES = {")
    for ref, g in sorted(pick.items(), key=lambda kv: (GRADES[::-1].index(kv[1]), kv[0])):
        print(f'    "{ref}": "{g}",')
    print("}")
    return 0


def cmd_sta(args):
    res, fbad = analyse()
    print(f"static timing analysis (the two-halves machine): {sta.VARIANT}, {sta.CORNER} delays")
    print(report(res, fbad, args.paths))
    if args.write:
        tab, _ = table(res)
        write_ticks(tab)
        print(f"wrote {os.path.relpath(TICKS_PATH)} ({len(tab)} words)")
    return 0
