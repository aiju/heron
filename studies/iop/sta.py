"""Static timing analysis of the IOP's card (card.py): infra/hw/sta.py's
case analysis, once for each distinct microinstruction in each half of the
microcycle, at the slow corner, at RFC 0037's 60 ns.

  heron iop hw sta [--paths N]     the worst slacks and their paths

A case holds uIR's fields, its predecoded bits (computed from the word, as
the predecoding does from the flash) and PH constant; every other state
(the I/O side's, the slave side's, the window's, the data) is unknown, so
a case covers whatever the rest of the card is doing.

What a case's clock is: BCLK rises at 0 and falls at T/2 (the clock
fixture, card.build(sim=False)). A register that can't load at the end of
the other half (uIR and uPC load at E2 only, F, AC and X at E1) last
changed a clock before this one began, so it launches at -T: the 2-clock
paths, uPC through the microcode flash into uIR, come out as such. The
two flip-flops on BCLK's fall (PHD, STAKEF) capture at it. The bus's
lines come from the other cards at EDGE_PS (RFC 0037, 4).

The checks: every register's setup (infra's), the SRAMs' writes (strobes
from a rising edge to BCLK's fall: tWP, tAS, tAW, tDW), and the card's
own outputs onto the bus, valid 16 ns after BCLK at the pin.

Not covered: hold times (the minimum corner), the I/O bus's devices
(their strobes are the timing table's, in clocks), the transparent
latches' own timing beyond their data's flow, and the asynchronous parts
(the doorbells' set from the slave side, the tick's and COLD's
synchronisers, the watchdog)."""

import argparse
from collections import Counter

from heron.infra.hw import chips, sta as hsta

from . import build as bld, card, uasm

NEG = hsta.NEG
T = card.BCLK_PS / 1000.0
TCO_PS = 16_000                 # RFC 0037, 4: outputs valid at the card's pins
CLKBUF_MAX_PS = 4_900           # the CDC341's delay, BCLK's pin to the registers


def _late_offset():
    """BCLK_n's delay after BCLK's fall: the inverter the simulator's
    netlist has."""
    return chips.delays_for(chips.load_timing(), chips.part_number(card.VARIANT, "04"), "max")["A->Y"] / 1000.0


WINDOWS = {"LATE": (0.5, _late_offset(), 0.0, 0.0)}


# Nets that change only clocks before anything times on them: the I/O
# bus's data (what a device drives is there by the strobe's end, what the
# IOP drives from its setup, as the timing table has them in clocks; the
# read and write latches between it and T would otherwise make a loop that
# only the I/O side's state cuts), and the window's copy of the timing
# table's address (the window's register, set a clock before its access
# starts; a table write, which moves it, waits for the window's access)
STEADY = frozenset(card.IOD + [f"WTA{i}" for i in range(4)])


class Case(hsta.Case):
    """infra's Case, with the registers in `late` launching at -T, the
    STEADY nets steady, and the `frozen` ones at their one value: a net
    with the same value in every case, for every microinstruction in each
    half, never changes while this microcode runs."""

    def __init__(self, N, constants, late, frozen=None, quiet=None, **kw):
        super().__init__(N, constants, T, 0.5, WINDOWS, turnoff=True, sharp=True, **kw)
        self.late = late
        self.frozen = dict(frozen or {}, **(quiet or {}))

    def net(self, n):
        if n in STEADY:
            return (None, NEG, None)
        if n in self.frozen:
            return (self.frozen[n], NEG, None)
        return super().net(n)

    def _seq(self, inst, pin, dname):
        v, t, en, cause = super()._seq(inst, pin, dname)
        if inst.ref in self.late:
            t -= self.T
        return v, t, en, cause


class Analysis:
    def __init__(self, b=None):
        self.b = b or bld.Build(bld.DEFAULT_PROGRAM, quick=True)
        self.nl = card.build(sim=False)
        self.N = hsta.Netlist(self.nl, card.VARIANT, "max")
        by = {i.ref: i for i in self.nl.instances}
        # the predecoded bits: PD_x registered as uIR's p-bits
        self.pd = {}
        for ref in ("U_IR5", "U_IR6", "U_IR7"):
            inst = by[ref]
            for p, n in inst.conn.items():
                if p.startswith("D") and n.startswith("PD_"):
                    self.pd[n] = inst.conn["Q" + p[1:]]
        self.fixed = {"RESET_n": 1, "RESET": 0, "COLDS_n": 1}
        self.late = {ph: self._late(ph) for ph in (0, 1)}
        self.falling = {(i.ref, p.replace("CLK", "D")) for i in self.nl.instances for p, n in i.conn.items()
                        if n == "BCLK_n" and p.endswith("CLK")}
        self.outputs = self._outputs()
        # NANDs with the other half's phase: inactive (1) all through the
        # clock before a case's, which was the other half
        self.halfgates = {ph: [i.conn[p] for i in self.nl.instances if i.type.model == "nand"
                               for p, n in i.conn.items() if i.type.kind(p) == "out"
                               and ("PH_n" if ph == 0 else "PH") in
                               [i.conn[q] for q in hsta.gate_inputs(i, p)]]
                          for ph in (0, 1)}
        self.frozen = {}
        self.frozen = self._frozen()

    def _phase_case(self, ph):
        return Case(self.N, dict(self.fixed, PH=ph, PH_n=1 - ph), frozenset())

    def _late(self, ph):
        """The registers that launch at -T in a half `ph` case: those that
        can't load at the end of the other half."""
        c = self._phase_case(1 - ph)
        out = set()
        for inst in self.nl.instances:
            m = inst.type.model
            if m == "dreg" and "EN" in inst.conn:
                if c.pin(inst, "EN")[0] == 1:
                    out.add(inst.ref)
            elif m == "cnt161":
                load, enp, ent = (c.pin(inst, p)[0] for p in ("LOAD", "ENP", "ENT"))
                if load == 1 and (enp == 0 or ent == 0):
                    out.add(inst.ref)
        return frozenset(out)

    def _outputs(self):
        """The bus's lines the card drives (not RESET and COLD, which are
        open collector and slow by RFC 0037, 7)."""
        lines = set(card.SBA[1:] + card.SBD + ["SB_START_n", "SB_WRITE_n", "SB_BE0_n", "SB_BE1_n",
                                               "SB_WAIT_n", "SB_REQ3_n", "SB_LOCK_n"])
        out = set()
        for inst in self.nl.instances:
            if inst.ref == "X_EDGE":
                continue
            for p, n in inst.conn.items():
                if n in lines and inst.type.kind(p) in ("out", "tri"):
                    out.add(n)
        return sorted(out)

    def _frozen(self):
        """{net: value} for the nets with one value in every case."""
        nets = set(self.N.drivers)
        seen = {}
        for w in self.words():
            for ph in (0, 1):
                c = self.case(w, ph)
                for n in list(nets):
                    v = c.net(n)[0]
                    if v is None or seen.setdefault(n, v) != v:
                        nets.discard(n)
        # not the case's own constants, which differ between words
        return {n: seen[n] for n in nets if n not in card.U.values() and n not in ("PH", "PH_n")}

    def words(self):
        """{word: [microaddresses]}"""
        out = {0: []}                   # uIR as reset clears it
        for a, w in sorted(self.b.mc.words.items()):
            out.setdefault(w, []).append(a)
        return out

    def constants(self, w, ph):
        c = dict(self.fixed, PH=ph, PH_n=1 - ph)
        for bit, name in card.U.items():
            c[name] = (w >> bit) & 1
        # the predecoded bits, as the predecoding computes them from the word
        pre = Case(self.N, {f"UD{b}": (w >> b) & 1 for b in range(48)}, frozenset())
        for pdn, q in self.pd.items():
            v = pre.net(pdn)[0]
            if v is not None:
                c[q] = v
        # the slave side takes T at E2 for the next clock alone, when
        # neither this microinstruction nor the next uses it: STAKE is 0
        # in a second half, and in a first half that uses T (quiet())
        if ph == 1:
            c.update(STAKE=0, STAKE_n=1)
        # a timing table write's second half comes after TTWS has seen the
        # I/O side idle and kept the window's accesses from starting: no
        # access is under way. TTWS is set only in a table write
        if c.get("pTTW") == 1:
            if ph == 1:
                c.update(STB=0, STB_n=1, HLD=0, HLD_n=1, WSEL=0, WSEL_n=1, TTWS=1, TTWS_n=0)
        else:
            c.update(TTWS=0, TTWS_n=1)
        return c

    def quiet(self, w, ph):
        """Nets that can't have changed at the edge that began this case:
        a gate enabled only in the other half that is off now; in a first
        half that reads T onto R, no device or BA left on T by the second
        half before (uasm's t_handovers rule); STAKE (constants()); TTWS
        in a second half, and the I/O side's start in a table write's."""
        out = {}
        c = Case(self.N, self.constants(w, ph), frozenset())
        for n in self.halfgates[ph]:
            if c.net(n)[0] == 1:
                out[n] = 1
        if ph == 0 and uasm.field(w, "RS") == uasm.RS_T:
            out.update({f"DRDY{k}B": 0 for k in range(3)}, BAOB_n=1)
        # STAKE is 0 in every second half, and the slave side never takes T
        # in a microinstruction that uses it: so in one that does, STAKE
        # stays 0 all through
        if c.net("TNONE")[0] == 0:
            out.update(STAKE=0, STAKE_n=1)
        # TTWS changes only at the end of a table write's first half's
        # clocks but the last, and at its E2
        if ph == 1:
            out.update(TTWS=c.net("TTWS")[0], TTWS_n=c.net("TTWS_n")[0])
        # and in a table write's second half the I/O side is idle (above),
        # in S0 with CNT at 0, as it counts in S0 only while an access's
        # setup goes on: T on the tables' data reaches the comparators,
        # but no access starts and CNT stays
        if ph == 1 and c.net("pTTW")[0] == 1:
            out.update(CZC=0, GOSTB=0)
        return out

    def case(self, w, ph):
        return Case(self.N, self.constants(w, ph), self.late[ph], self.frozen, self.quiet(w, ph))

    def checks(self, c):
        """[(slack ns, what, endpoint net)] for a case."""
        out = []
        for kind, x, desc, net in hsta.checks(c, self.N, 0.875):
            if kind != "setup":
                continue
            ref, pin = desc.split(" ")[0].split(".")
            if (ref, pin) in self.falling:
                edge = c.net("BCLK_n")[1]
                out.append((edge - x, desc + " (BCLK's fall)", net))
            else:
                out.append((T - x, desc, net))
        out += self.write_checks(c)
        out += self.output_checks(c)
        return out

    def write_checks(self, c):
        """The SRAMs' writes: each strobe is a NAND of an opening term, a
        flip-flop that rose at an edge, and a closing one, a flip-flop on
        BCLK's fall (PHD_n, STAKEF_n), perhaps through an AND with another
        strobe."""
        out = []
        for inst in self.nl.instances:
            if inst.type.model != "sram" or inst.ref.startswith("X_"):
                continue
            we = inst.conn["WE"]
            if not self.N.drivers.get(we):
                continue
            if c.net(we)[0] == 1:
                continue                    # no write in this case
            d = self.N.delay[inst.ref]
            strobes = [(we, 0.0)]
            drv, pin = self.N.drivers[we][0]
            if drv.type.model == "and":
                gd = self.N.delay[drv.ref]["A->Y"]
                strobes = [(drv.conn[p], gd) for p in hsta.gate_inputs(drv, pin)]
            addr = max(c.pin(inst, p)[1] for p in hsta.address_pins(inst))
            data = max(c.pin(inst, f"IO{i}")[1] for i in range(8))
            for s, extra in strobes:
                if c.net(s)[0] == 1:
                    continue
                g, gp = self.N.drivers[s][0]
                ins = [g.conn[p] for p in hsta.gate_inputs(g, gp)]
                gd = self.N.delay[g.ref]["A->Y"] + extra
                closing = [n for n in ins if n in ("PHD_n", "STAKEF_n")]
                if not closing:
                    continue
                t_rise = c.net(closing[0])[1] + gd
                t_fall = max(c.net(n)[1] for n in ins if n not in closing) + gd
                for sl, what in ((t_rise - t_fall - d["tWP"], "write pulse width (tWP)"),
                                 (t_fall - addr - d["tAS"], "address setup to write (tAS)"),
                                 (t_rise - addr - d["tAW"], "address to end of write (tAW)"),
                                 (t_rise - data - d["tDW"], "data setup to end of write (tDW)")):
                    out.append((sl, f"{inst.ref} write by {s}: {what}", s if "tWP" in what else inst.conn["A0"]))
        return out

    def output_checks(self, c):
        lim = (TCO_PS - CLKBUF_MAX_PS) / 1000.0
        out = []
        for n in self.outputs:
            t = max((c.output(i, p)[1] for i, p in self.N.drivers[n] if i.ref != "X_EDGE"), default=NEG)
            if t != NEG:
                out.append((lim - t, f"{n} valid at the card's pin (RFC 0037's 16 ns)", n))
        return out

    def run(self, limit=None):
        """{check: (worst slack, net, word, phase, addresses, cases)} for
        every check, over every case: its worst case, and how many cases
        it fails in."""
        out = {}
        for w, addrs in list(self.words().items())[:limit]:
            for ph in (0, 1):
                for sl, what, net in self.checks(self.case(w, ph)):
                    prev = out.get(what)
                    n = (prev[5] if prev else 0) + (sl < 0)
                    if prev is None or sl < prev[0]:
                        out[what] = (sl, net, w, ph, addrs, n)
                    else:
                        out[what] = prev[:5] + (n,)
        return out

    def path(self, w, ph, net):
        c = self.case(w, ph)
        if net in self.outputs:
            # the card's own driver, not the other cards'
            t, inst, pin = max((c.output(i, p)[1], i, p) for i, p in self.N.drivers[net] if i.ref != "X_EDGE")
            cause = c.output(inst, pin)[3]
            src = cause[1] if cause and cause[1] in inst.conn.values() else None
            return (c.path(src) if src else []) + [(net, t, inst.ref, cause[2] if cause else "")]
        return c.path(net)


def report(a, res, paths=6):
    where = a.b.mc.where
    rows = sorted(res.items(), key=lambda kv: kv[1][0])
    lines = [f"static timing analysis of the IOP's card at {T:.0f} ns, the slow corner: "
             f"{len(a.words())} distinct microinstructions, each half; {len(rows)} checks"]
    late = [r for r in rows if r[1][0] < 0]
    lines.append(f"worst slack {rows[0][1][0]:.1f} ns; {len(late)} checks late in some case")
    for what, (sl, net, w, ph, addrs, n) in late[:40]:
        lines.append(f"  {sl:6.1f} ns  {what}  ({n} cases)")
    lines.append("")
    for what, (sl, net, w, ph, addrs, n) in rows[:paths]:
        at = f"{where(addrs[0])} and {len(addrs) - 1} more" if addrs else "uIR cleared"
        lines.append(f"{sl:6.1f} ns  {what}  (at the {'E2' if ph else 'E1'} half's end; {at})")
        for n_, t, ref, dn in a.path(w, ph, net):
            lines.append(f"    {t:7.1f} ns  {n_:<14} {ref:<10} {dn}")
        lines.append("")
    return "\n".join(lines)


def main(argv):
    p = argparse.ArgumentParser(prog="heron iop hw sta")
    p.add_argument("--paths", type=int, default=6, help="critical paths to show, one per kind of check")
    p.add_argument("--limit", type=int, help="only the first N distinct microinstructions")
    args = p.parse_args(argv)
    a = Analysis()
    res = a.run(args.limit)
    print(report(a, res, args.paths))
    return 0 if min(r[0] for r in res.values()) >= 0 else 1
