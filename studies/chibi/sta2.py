"""Static timing analysis of the two-halves variant (board.build(halves=True)),
an exploration: a microinstruction does both halves of a 32-bit operation,
phase F (ticks 0-2, the control store settling, the last cycle's results
written back), then the low half and the high half, with ticks of fixed
length (19.86 ns) and each half as long as it needs. The variant's netlist
is for timing only: nothing simulates it, and its microcode is the first
cut's, each distinct microinstruction timed as a low half and as a high
half.

  L case   phase F's signals at their ticks, the control store's outputs when
           it gives them, the low half from tick 3: what the low half's
           registers (Y's first, L's low half, the flags, MAR and PC, and
           the sequencer for a one-half cycle) need at the half's end
  H case   the same microinstruction as the high half, from the low half's
           end at L_END: HALF and the registers the low half loaded change
           a 22V10's clock-to-output after it
  F case   the cycle's start: the register file's two writes (Y's first half
           at tick 1, its second at tick 2), the video's read

  heron chibi hw sta2 [--paths N] [--suite]
"""

import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from heron.infra.hw import sta as hsta

from . import board, sta, ucode as uc

NEG = hsta.NEG
K = 1e3 / 50.35                 # a tick, ns
L_START = 3 * K
L_END = 6 * K                   # the low half's end as the H case takes it
TCO = sta.TCO
GAL = sta.GAL
CPU_CLOCKS = sta.CPU_CLOCKS


class Case2(sta.Case):
    phase = "L"

    def m_chibiclk2(self, inst, pin, d):
        if pin in ("MCLK", "PIX"):
            return (None, NEG, True, None)
        if pin == "RESET":
            return (1, NEG, True, None)
        h = self.phase == "H"
        if pin in ("CLK", "HCKB"):
            return (None, 0.0, True, None)
        if pin in ("HCK", "HCKA"):
            return (None, L_END if h else 0.0, True, None)
        if self.phase == "F":
            fixed = {"PHW": (1, 0.0), "YOE": (1, K), "YBOE": (0, NEG), "RWS": (None, K),
                     "VLD": (None, K), "HALF": (0, NEG), "T0": (None, 0.0), "T1": (None, 0.0),
                     "T2": (None, 0.0)}
        else:
            fixed = {"PHW": (0, L_START), "YOE": (0, L_START), "YBOE": (0, L_START),
                     "RWS": (0, L_START), "VLD": (0, L_START),
                     "HALF": (1, L_END) if h else (0, NEG),
                     "T0": (None, NEG), "T1": (None, NEG), "T2": (None, NEG)}
        v, t = fixed[pin]
        if t == NEG:
            return (v, NEG, True, None)
        return (v, t + TCO, True, (inst.ref, pin, f"{pin} at {t / K:.0f} ticks"))

    def m_gal(self, inst, pin, d):
        if inst.conn.get(pin) in ("BTNQ", "HLTQ", "TRACE") or \
                inst.ref in ("U_KBDF", "U_MOUSEF") and inst.conn.get(pin) in ("KCLK", "MSCLK"):
            return (None, NEG, True, None)      # latches and the PS/2 hold: asynchronous, untimed
        if inst.ref == "U_SLOW" and inst.conn.get(pin) == "CFOE_n":
            mop = sum(self.const.get(n, 0) << i for i, n in enumerate(board.MOP))
            if self.phase == "F" or self.const.get("A31") != 1 or \
                    mop not in (uc.MOP_RDM, uc.MOP_WRM):
                return (1, NEG, True, None)     # off but in a slow access (registered)
        out = super().m_gal(inst, pin, d)
        # the immediate unit's high half: HALF selects it (a 22V10's tPD), as a
        # built variant would have it
        if self.phase == "H" and inst.ref in ("U_IMML", "U_IMMH") and out[1] != NEG:
            t = max(out[1], L_END + TCO + GAL["tPD"])
            return (out[0], t, out[2], out[3] if t == out[1] else ("X_CLK", "HALF", "the high half"))
        return out

    # the draft's slow devices (timed by U_SLOW's wait states, not here),
    # its passives and the button's debouncer: nothing they drive is timed
    def m_i8254(self, inst, pin, d): return (None, NEG, False, None)
    def m_cf(self, inst, pin, d): return (None, NEG, False, None)
    def m_ramdac(self, inst, pin, d): return (None, NEG, False, None)
    def m_passive(self, inst, pin, d): return (None, NEG, True, None)
    def m_por(self, inst, pin, d): return (None, NEG, True, None)

    def strobe(self, inst, pin):
        """The strobes: from the half's second tick."""
        start = L_END if self.phase == "H" else L_START
        if self.phase == "F":
            return (1, TCO, True, (inst.ref, "T0", "tick 0"))
        mop = sum(self.const.get(n, 0) << i for i, n in enumerate(board.MOP))
        a31 = self.const.get("A31")
        net = inst.conn[pin]
        active = {"WEL_n": mop == uc.MOP_WRM and a31 != 1, "WEH_n": mop == uc.MOP_WRM and a31 != 1,
                  "IOWR_n": mop == uc.MOP_WRM and a31 != 0,
                  "IORD_n": mop == uc.MOP_RDM and a31 != 0}[net]
        if not active:
            return (1, NEG, True, None)
        return (None, start + K + TCO, True, (inst.ref, "T0", "the half's second tick"))


_N = None


def netlist():
    global _N
    if _N is None:
        _N = hsta.Netlist(board.build(sim=False, halves=True), sta.VARIANT, sta.CORNER)
    return _N


def case_for(word, extra, phase):
    const = hsta.constants_for(sta.sys_module(), word, dict(extra)) if phase != "F" else {}
    c = Case2(netlist(), const, 400.0, 0.5, None, sta.TURNOFF, sta.SHARP)
    c.phase = phase
    return c


def requirements(c):
    """[(time, description, net)]: when the half (or for F, the phase) must
    end for each requirement to be met; and the fixed-tick requirements that
    fail [(late by, description)]."""
    N = netlist()
    h = c.phase == "H"
    start = L_END if h else L_START
    strobe = start + K + TCO
    end, bad = [], []
    for inst in N.insts:
        t, d = inst.type, N.delay[inst.ref]
        if t.model == "gal":
            ck = sta.clock_of(inst)
            regs = [o for o in inst.gal if o[1]]
            if not regs:
                continue
            fixed = None
            if c.phase == "F":
                if inst.ref not in ("U_SHA", "U_SHB"):
                    continue
                fixed = 2 * K + TCO
            elif inst.ref == "U_MEMC":
                fixed = strobe - TCO
            elif ck == "HCKA" and h or ck == "HCKB" and not h:
                continue
            elif ck not in CPU_CLOCKS | {"HCK", "HCKA", "HCKB"}:
                continue
            if inst.ref.startswith(("U_YLO", "U_YHI", "U_YB")) and not sta.result_used(c):
                continue
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
        elif t.model == "sram":
            if c.net(inst.conn["WE"])[0] == 1:
                continue
            addr = max(c.pin(inst, p)[1] for p in hsta.address_pins(inst))
            data = max(c.pin(inst, f"IO{i}")[1] for i in range(8))
            if inst.ref.startswith("U_RF"):
                if c.phase != "F":
                    continue
                for late, desc in ((addr + d["tAS"] - (K + TCO + GAL["tPD"]), "address (tAS)"),
                                   (data + d["tDW"] - (2 * K + TCO + GAL["tPD"]), "data (tDW)")):
                    if late > 0.05:
                        bad.append((late, f"{inst.ref} {desc}"))
            elif c.phase != "F":
                if addr + d["tAS"] > strobe + 0.05:
                    bad.append((addr + d["tAS"] - strobe, f"{inst.ref} address before its write"))
                end.append((data + d["tDW"] - TCO, f"{inst.ref} data before its write ends",
                            inst.conn["IO0"]))
        elif t.model == "uart16550" and c.phase == "L":
            mop = sum(c.const.get(n, 0) << i for i, n in enumerate(board.MOP))
            if mop not in (uc.MOP_RDM, uc.MOP_WRM) or c.const.get("A31") != 1:
                continue
            from heron.infra.hw import chips
            dd = chips.load_timing()["TL16C550C"]["checks"]
            a = max(c.pin(inst, p)[1] for p in ("A0", "A1", "A2", "CS2"))
            if a + dd["tAS"] > strobe + 0.05:
                bad.append((a + dd["tAS"] - strobe, f"{inst.ref} address before its strobe"))
            if mop == uc.MOP_WRM:
                dt = max(c.pin(inst, f"D{i}")[1] for i in range(8))
                end.append((dt + dd["tDS"] - TCO, f"{inst.ref} data before its strobe ends",
                            inst.conn["D0"]))
    return end, bad


def time_case(item):
    """(key, L: (need, worst, bad), H: (need, worst, bad))."""
    (w, extra), _labels = item
    out = []
    for ph in ("L", "H"):
        if ph == "H" and dict(extra).get("A31") == 1:
            out.append(None)            # an I/O access is one long half
            continue
        end, bad = requirements(case_for(w, extra, ph))
        worst = max(end, key=lambda r: r[0]) if end else None
        out.append((worst[0] if worst else 0.0, worst, sorted(bad, reverse=True)))
    return (w, extra), out[0], out[1]


def ticks(t, start):
    return max(1, math.ceil((t - start) / K - 1e-6))


def analyse(jobs=4):
    items = list(sta.sta_words().items())
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(time_case, items, chunksize=8))
    end, bad = requirements(case_for(0, (), "F"))
    return res, (max(end, key=lambda r: r[0]) if end else None, bad)


def path(word, extra, phase, worst):
    c = case_for(word, extra, phase)
    return [f"    {t:7.1f} ns  {net:<14} {ref:<10} {dn}" for net, t, ref, dn in c.path(worst[2])]


def suite_estimate(res):
    """The suite's time: each microinstruction a low half (phase F and its
    ticks), but a first cut's microinstruction that is a 32-bit operation's
    high half (studies of the first cut's profile: it reads or writes a high
    half, or loads PC's or MAR's) a high half of the one before it."""
    from heron.studies.v2_isa import testing
    from . import check, routines
    from heron.infra.programs import metadata
    cs = routines.control_store()
    mask = 0
    for name in sta.UNTIMED:
        b, wd, _ = uc._pos[name]
        mask |= ((1 << wd) - 1) << b
    need = {key: (lo, hi) for key, lo, hi in res}
    total = Counter()
    for p in testing.program_paths():
        img = check.assemble(p)
        m = check.run_rtl(img, metadata(p)["input"], profile=True)
        for a, n in m.ucount.items():
            f = uc.unpack(cs.words[a])
            mem = f["MOP"] in (uc.MOP_RDM, uc.MOP_WRM)
            key = (cs.words[a] & ~mask, (("A31", 0),) if mem else ())
            if key not in need:
                continue
            lo, hi = need[key]
            high = ((f["DS"] == uc.DS_RF and f["HR"]) or (f["WEN"] and f["HW"])
                    or f["AXM"] == 2 or f["AXP"] == 2)
            total["cycles now"] += n
            total["ticks"] += n * (ticks(hi[0], L_END) if high and hi else
                                   3 + max(3, ticks(lo[0], L_START)))
            total["microinstructions"] += 0 if high else n
    return total


def report(res, fw, paths=2, suite=False):
    lines = []
    lo = Counter(ticks(r[1][0], L_START) for r in res)
    hi = Counter(ticks(r[2][0], L_END) for r in res if r[2])
    bad = [(r[0], ph, b) for r in res for ph, x in (("L", r[1]), ("H", r[2])) if x for b in x[2]]
    lines.append(f"ticks of {K:.2f} ns; phase F ticks 0-2, the low half from tick 3")
    lines.append(f"low half's ticks over {len(res)} cases:  " +
                 ", ".join(f"{k}: {v}" for k, v in sorted(lo.items())))
    lines.append(f"high half's ticks over {sum(hi.values())} cases: " +
                 ", ".join(f"{k}: {v}" for k, v in sorted(hi.items())))
    lines.append(f"fixed-tick requirements failing: {len(bad)}" +
                 (f" (worst {max(b[2][0] for b in bad):.1f} ns late: {max(bad, key=lambda b: b[2][0])[2][1]})"
                  if bad else ""))
    fe, fb = fw
    lines.append(f"phase F: {len(fb)} failing" + (f", e.g. {fb[0][1]} {fb[0][0]:.1f} ns late" if fb else ""))
    lines.append("")
    for ph, idx, start in (("low", 1, L_START), ("high", 2, L_END)):
        rs = sorted((r for r in res if r[idx]), key=lambda r: -r[idx][0])
        for r in rs[:paths]:
            (w, extra), x = r[0], r[idx]
            lines.append(f"slowest {ph} half: {x[0] - start:.1f} ns from its start "
                         f"({ticks(x[0], start)} ticks), {sta.describe(w)} {dict(extra)}: {x[1][1]}")
            lines += path(w, extra, "L" if idx == 1 else "H", x[1])
            lines.append("")
    if suite:
        t = suite_estimate(res)
        now = t["cycles now"] * sta.VGA_PERIOD
        new = t["ticks"] * K
        lines.append(f"the suite: {t['cycles now']} cycles of {sta.VGA_PERIOD:.1f} ns now, "
                     f"{now / 1e6:.0f} ms; {t['microinstructions']} microinstructions here, "
                     f"{new / 1e6:.0f} ms: x{now / new:.2f}")
    return "\n".join(lines)


def cmd_sta2(args):
    res, fw = analyse()
    print(report(res, fw, args.paths, args.suite))
    return 0


del defaultdict, os
