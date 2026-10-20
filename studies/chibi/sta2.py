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
5 ticks whatever, and is checked against them.

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
GAL = sta.GAL
IO_TICKS = 5
TICKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticks.json")
CPU = {f"CLK{i}" for i in range(9)}
HALF_END = {"L": {"HCK1", "HCK2", "HCK3", "HCK4", "HCKA1", "HCKA2"},
            "H": {"HCK1", "HCK2", "HCK3", "HCK4", "HCKB1", "HCKB2"}}
# the devices' own GALs, on their own clocks: only their outputs onto the
# CPU's buses are timed
DEVICE_GALS = {"U_SLOW", "U_PSGC", "U_VQ", "U_VC", "U_SLOWD", "U_ODT", "U_VS", "U_LREQ",
               "U_LCMP", "U_LINE", "U_VH", "U_VV", "U_VF", "U_SHA", "U_SHB", "U_KBD", "U_MOUSE",
               "U_KBDF", "U_MOUSEF", "U_KBDC", "U_MOUSEC"}


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
        microinstruction may make them active, else inactive (ADS from the
        third)."""
        if self.phase == "F":
            return (1, TCO, True, (inst.ref, "TC0", "tick 0"))
        start = 3 * K if self.phase == "L" else 0.0
        mop = sum(self.const.get(n, 0) << i for i, n in enumerate(board2.MOP))
        if self.phase == "H" and self.const.get("SUPH") == 1:
            return (1, NEG, True, None)
        a31 = self.const.get("A31")
        net = inst.conn[pin]
        rd = mop in (uc.MOP_RDM, uc.MOP_LDIRM)
        io = (mop == uc.MOP_WRM or rd) and a31 != 0
        active = {"WEL_n": mop == uc.MOP_WRM and a31 != 1, "WEH_n": mop == uc.MOP_WRM and a31 != 1,
                  "IOWR_n": mop == uc.MOP_WRM and a31 != 0,
                  "IORD_n": rd and a31 != 0, "ADS": io}[net]
        if net == "ADS":                # the I/O strobes a tick later
            if not active:
                return (0, NEG, True, None)
            return (None, start + 2 * K + TCO, True, (inst.ref, "TC0", "the half's third tick"))
        if not active:
            return (1, NEG, True, None)
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
    c.update(TASK=0, TCHG=0, HALFD=int(phase == "H"))
    if phase != "F":
        nat = c.get(board2.HXF[0], 0) == 0 and c.get(board2.HXF[1], 0) == 0
        c["SUPH"] = int(phase == "H" and not nat)
    return c


def case_for(word, extra, phase, two):
    c = Case3(netlist(), constants(word, extra, phase, two), 400.0, 0.5, None, sta.TURNOFF,
              sta.SHARP)
    c.phase, c.two = phase, two
    return c


def requirements(c):
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
            for p in sorted(pins):
                ta = c.pin(inst, p)[1]
                if ta == NEG:
                    continue
                need = ta + GAL["setup"]
                if fixed is None:
                    end.append((need, f"{inst.ref}.{p} setup", inst.conn[p]))
                elif need > fixed + 0.05:
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
                addr = max(c.pin(inst, p)[1] for p in hsta.address_pins(inst))
                data = max(c.pin(inst, f"IO{i}")[1] for i in range(8))
                for late, desc in ((addr + d["tAS"] - (k * K + TCO), "address (tAS)"),
                                   (data + d["tDW"] - ((k + 1) * K + TCO), "data (tDW)")):
                    if late > 0.05:
                        bad.append((late, f"{inst.ref} {desc}"))
            elif ph != "F" and c.net(inst.conn["WE"])[0] != 1:
                addr = max(c.pin(inst, p)[1] for p in hsta.address_pins(inst))
                data = max(c.pin(inst, f"IO{i}")[1] for i in range(8))
                if addr + d["tAS"] > strobe + 0.05:
                    bad.append((addr + d["tAS"] - strobe, f"{inst.ref} address before its write"))
                end.append((data + d["tDW"] - TCO, f"{inst.ref} data before its write ends",
                            inst.conn["IO0"]))
        elif t.model == "uart16550" and ph != "F":
            mop = sum(c.const.get(n, 0) << i for i, n in enumerate(board2.MOP))
            if mop not in (uc.MOP_RDM, uc.MOP_WRM) or c.const.get("A31") != 1:
                continue
            dd = chips.load_timing()["TL16C550C"]["checks"]
            a = max(c.pin(inst, p)[1] for p in ("A0", "A1", "A2", "CS2"))
            if a + dd["tAS"] > strobe + 0.05:
                bad.append((a + dd["tAS"] - strobe, f"{inst.ref} address before its strobe"))
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
        page, n, op, step = a >> 17, a >> 13 & 15, a >> 5 & 0xFF, a & 31
        label = f"{op:02X} p{page} n{n:X} s{step}"
        if f["MOP"] in (uc.MOP_RDM, uc.MOP_WRM, uc.MOP_LDIRM):
            for a31 in (0, 1):
                lst = out[(key, two, (("A31", a31),))]
                if len(lst) < 8:
                    lst.append(label + (" I/O" if a31 else " RAM"))
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
        io = dict(extra).get("A31") == 1
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
    lines.append(f"halves over their field's most (or I/O's 5 ticks): {len(over)}" +
                 (f", e.g. a {over[0][1]} half of {over[0][0]} ticks: {sta_describe(over[0][2])}"
                  if over else ""))
    lines.append(f"phase F: {len(fbad)} failing" +
                 (f", worst {fbad[0][1]} {fbad[0][0]:.1f} ns late" if fbad else ""))
    lines.append("")
    for ph, idx, start in (("low", 1, 3 * K), ("high", 2, 0.0)):
        rs = sorted((r for r in res if r[idx] and dict(r[0][2]).get("A31") != 1),
                    key=lambda r: -r[idx][0])
        for r in rs[:paths]:
            (w, two, extra), x = r[0], r[idx]
            lines.append(f"slowest {ph} half: {x[0] - start:.1f} ns from its start "
                         f"({ticks_for(x[0], start)} ticks), {sta_describe(w)} {dict(extra)}: "
                         f"{x[1][1]}")
            lines += path(w, extra, "L" if idx == 1 else "H", two, x[1])
            lines.append("")
    return "\n".join(lines)


def cmd_sta(args):
    res, fbad = analyse()
    print(f"static timing analysis (the two-halves machine): {sta.VARIANT}, {sta.CORNER} delays")
    print(report(res, fbad, args.paths))
    if args.write:
        tab, _ = table(res)
        write_ticks(tab)
        print(f"wrote {os.path.relpath(TICKS_PATH)} ({len(tab)} words)")
    return 0
