"""Static timing analysis with case analysis per microinstruction.

For every distinct microinstruction the control nets have known values, so
we propagate 0/1/X values together with arrival times through the netlist.
Known values cut false paths: a disabled buffer drives nothing, an
unselected multiplexer input doesn't reach the output, an AND gate with a 0
input doesn't pass its other inputs. Data values stay X, so the result
holds for all data (carry chains included).

Arrival times are measured from the rising clock edge. A microinstruction
needs a clock period T such that
  - every register input that loads is stable `setup` before the next edge;
  - every SRAM write strobe (WEWIN gated by control) meets tAS, tAW, tWP, tDW,
    where the write window is [ws*T, we*T].
The machine's minimum period is the maximum over all microinstructions.
"""

import math
from collections import defaultdict

from . import chips, cpu_v0, microcode

NEG = -math.inf


class Netlist:
    def __init__(self, nl, variant, corner):
        timing = chips.load_timing()
        self.insts = nl.instances
        self.delay = {}
        for inst in self.insts:
            if inst.type.family == "fixture":
                self.delay[inst.ref] = {}
            else:
                part = chips.part_number(variant, inst.type.name, inst.role)
                self.delay[inst.ref] = {k: v / 1000.0 for k, v in chips.delays_for(timing, part, corner).items()}
        self.drivers = defaultdict(list)    # net -> [(inst, pin)]
        for inst in self.insts:
            for pin, net in inst.conn.items():
                if inst.type.kind(pin) in ("out", "tri", "io"):
                    self.drivers[net].append((inst, pin))
        self.by_ref = {i.ref: i for i in self.insts}


class Case:
    """Arrival/value analysis for one microinstruction at one period."""

    def __init__(self, N, constants, T, ws):
        self.N = N
        self.const = constants          # net -> value (from ROM word / mode)
        self.T = T
        self.ws = ws
        self.memo = {}
        self.busy = set()
        self.loops = set()

    # (value, arrival, cause) for a net; cause = (inst ref, input net, delay name) for path tracing
    def net(self, n):
        if n in self.memo:
            return self.memo[n]
        if n == "GND":
            return (0, NEG, None)
        if n == "VCC":
            return (1, NEG, None)
        if n in self.busy:
            self.loops.add(n)
            return (None, NEG, None)
        self.busy.add(n)
        drivers = self.N.drivers.get(n, [])
        best = None
        for inst, pin in drivers:
            v, t, en, cause = self.output(inst, pin)
            if en is False:
                continue
            if best is None:
                best = (v, t, cause, en)
            else:
                # several possibly-enabled drivers: value unknown, latest arrival
                bt = best[1]
                best = (None, max(bt, t), cause if t > bt else best[2], None)
        self.busy.discard(n)
        if best is None:
            res = (None, NEG, None)        # floating
        else:
            res = best[:3]
        if n in self.const:
            res = (self.const[n], res[1], res[2])
        self.memo[n] = res
        return res

    def pin(self, inst, p):
        return self.net(inst.conn[p]) if p in inst.conn else (0, NEG, None)

    def output(self, inst, pin):
        """(value, arrival, enabled, cause) of one output pin."""
        model = inst.type.model
        d = self.N.delay[inst.ref]
        f = getattr(self, "m_" + model)
        return f(inst, pin, d)

    # ---- helpers ----
    def latest(self, inst, terms):
        """terms: (pin, delay name). Returns (arrival, cause)."""
        t, cause = NEG, None
        for p, dn, dval in terms:
            _, ta, _ = self.pin(inst, p)
            if ta == NEG:
                continue
            if ta + dval > t:
                t, cause = ta + dval, (inst.ref, inst.conn[p], dn)
        return t, cause

    # ---- models ----
    def _gate(self, inst, pin, d, kind):
        ins = gate_inputs(inst, pin)
        vals = [self.pin(inst, p) for p in ins]
        dly = d["A->Y"]
        ctrl = {"and": 0, "nand": 0, "or": 1, "nor": 1}.get(kind)
        inv = kind in ("nand", "nor")
        if ctrl is not None:
            cs = [(t, p) for (v, t, _), p in zip(vals, ins) if v == ctrl]
            if cs:
                t, p = min(cs)
                out = ctrl ^ inv
                return (out, t + dly if t != NEG else NEG, True, (inst.ref, inst.conn[p], "A->Y"))
        t, cause = self.latest(inst, [(p, "A->Y", dly) for p in ins])
        if all(v is not None for v, _, _ in vals):
            if kind in ("and", "nand"):
                out = int(all(v for v, _, _ in vals))
            elif kind in ("or", "nor"):
                out = int(any(v for v, _, _ in vals))
            else:
                out = 0
                for v, _, _ in vals:
                    out ^= v
            out ^= inv
            return (out, t, True, cause)
        return (None, t, True, cause)

    def m_nand(self, inst, pin, d): return self._gate(inst, pin, d, "nand")
    def m_nor(self, inst, pin, d): return self._gate(inst, pin, d, "nor")
    def m_and(self, inst, pin, d): return self._gate(inst, pin, d, "and")
    def m_or(self, inst, pin, d): return self._gate(inst, pin, d, "or")
    def m_xor(self, inst, pin, d): return self._gate(inst, pin, d, "xor")

    def _seq(self, inst, pin, dname):
        """Register outputs launch at clock-to-output after the edge."""
        _, tc, _ = self.pin(inst, inst.type.name == "74" and pin[0] + "CLK" or "CLK")
        v = self.const.get(inst.conn.get(pin))
        return (v, max(tc, 0) + self.N.delay[inst.ref][dname], True, (inst.ref, "CLK", dname))

    def m_dff74(self, inst, pin, d): return self._seq(inst, pin, "CLK->Q")
    def m_dff175(self, inst, pin, d): return self._seq(inst, pin, "CLK->Q")
    def m_reg377(self, inst, pin, d): return self._seq(inst, pin, "CLK->Q")

    def _counter(self, inst, pin, d):
        if pin == "RCO":
            t1 = d["CLK->RCO"]
            _, te, _ = self.pin(inst, "ENT")
            t2 = te + d["ENT->RCO"] if te != NEG else NEG
            if t2 > t1:
                return (None, t2, True, (inst.ref, inst.conn["ENT"], "ENT->RCO"))
            return (None, t1, True, (inst.ref, "CLK", "CLK->RCO"))
        return self._seq(inst, pin, "CLK->Q")

    m_cnt161 = _counter
    m_cnt163 = _counter

    def _select(self, inst, sel_pins):
        vals = [self.pin(inst, p)[0] for p in sel_pins]
        if any(v is None for v in vals):
            return None
        return sum(v << i for i, v in enumerate(vals))

    def m_mux157(self, inst, pin, d):
        sec = pin[0]
        g = self.pin(inst, "G")[0]
        if g == 1:
            t, cause = self.latest(inst, [("G", "G->Y", d["G->Y"])])
            return (0, t, True, cause)
        s = self._select(inst, ["S"])
        data = [f"{sec}A", f"{sec}B"] if s is None else [f"{sec}{'AB'[s]}"]
        t, cause = self.latest(inst, [(p, "A->Y", d["A->Y"]) for p in data]
                               + [("S", "S->Y", d["S->Y"]), ("G", "G->Y", d["G->Y"])])
        v = self.pin(inst, data[0])[0] if len(data) == 1 and g == 0 else None
        return (v, t, True, cause)

    def m_mux153(self, inst, pin, d):
        sec = pin[0]
        g = self.pin(inst, f"{sec}G")[0]
        if g == 1:
            t, cause = self.latest(inst, [(f"{sec}G", "G->Y", d["G->Y"])])
            return (0, t, True, cause)
        s = self._select(inst, ["A", "B"])
        data = [f"{sec}C{i}" for i in range(4)] if s is None else [f"{sec}C{s}"]
        t, cause = self.latest(inst, [(p, "C->Y", d["C->Y"]) for p in data]
                               + [("A", "S->Y", d["S->Y"]), ("B", "S->Y", d["S->Y"]),
                                  (f"{sec}G", "G->Y", d["G->Y"])])
        v = self.pin(inst, data[0])[0] if len(data) == 1 and g == 0 else None
        return (v, t, True, cause)

    def m_mux151(self, inst, pin, d):
        g = self.pin(inst, "G")[0]
        dd, ds = (d["D->Y"], d["S->Y"]) if pin == "Y" else (d["D->W"], d["S->W"])
        if g == 1:
            t, cause = self.latest(inst, [("G", "G->Y", d["G->Y"])])
            return (int(pin == "W"), t, True, cause)
        s = self._select(inst, ["A", "B", "C"])
        data = [f"D{i}" for i in range(8)] if s is None else [f"D{s}"]
        t, cause = self.latest(inst, [(p, "D->Y", dd) for p in data]
                               + [(p, "S->Y", ds) for p in ("A", "B", "C")] + [("G", "G->Y", d["G->Y"])])
        v = None
        if len(data) == 1 and g == 0:
            v = self.pin(inst, data[0])[0]
            if v is not None and pin == "W":
                v ^= 1
        return (v, t, True, cause)

    def m_dec138(self, inst, pin, d):
        t, cause = self.latest(inst, [(p, "A->Y", d["A->Y"]) for p in ("A", "B", "C")]
                               + [(p, "G->Y", d["G->Y"]) for p in ("G1", "G2A", "G2B")])
        g1, g2a, g2b = (self.pin(inst, p)[0] for p in ("G1", "G2A", "G2B"))
        if g1 == 0 or g2a == 1 or g2b == 1:
            return (1, t, True, cause)
        s = self._select(inst, ["A", "B", "C"])
        if s is None or None in (g1, g2a, g2b):
            return (None, t, True, cause)
        return (int(s != int(pin[1:])), t, True, cause)

    def m_buf541(self, inst, pin, d):
        oe1, oe2 = self.pin(inst, "OE1")[0], self.pin(inst, "OE2")[0]
        if oe1 == 1 or oe2 == 1:
            return (None, NEG, False, None)
        en = True if (oe1 == 0 and oe2 == 0) else None
        a = "A" + pin[1:]
        t, cause = self.latest(inst, [(a, "A->Y", d["A->Y"]), ("OE1", "OE->Y en", d["OE->Y en"]),
                                      ("OE2", "OE->Y en", d["OE->Y en"])])
        return (self.pin(inst, a)[0], t, en, cause)

    def m_cmp688(self, inst, pin, d):
        g = self.pin(inst, "G")[0]
        if g == 1:
            t, cause = self.latest(inst, [("G", "G->PEQ", d["G->PEQ"])])
            return (1, t, True, cause)
        t, cause = self.latest(inst, [(f"{x}{i}", "P->PEQ", d["P->PEQ"]) for x in "PQ" for i in range(8)]
                               + [("G", "G->PEQ", d["G->PEQ"])])
        return (None, t, True, cause)

    def m_alu181(self, inst, pin, d):
        ab = [f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)]
        sm = [f"S{i}" for i in range(4)] + ["M"]
        logic = self.pin(inst, "M")[0] == 1
        if pin.startswith("F") or pin == "AEQB":
            terms = [(p, "AB->F logic" if logic else "AB->F", d["AB->F logic" if logic else "AB->F"]) for p in ab]
            if not logic:
                terms.append(("CN", "CN->F", d["CN->F"]))
            terms += [(p, "S->F", d["S->F"]) for p in sm]
        elif pin == "CN4":
            terms = [(p, "AB->CN4", d["AB->CN4"]) for p in ab] + [("CN", "CN->CN4", d["CN->CN4"])] \
                + [(p, "S->F", d["S->F"]) for p in sm]
        else:   # P, G
            dn = "AB->P" if pin == "P" else "AB->G"
            terms = [(p, dn, d[dn]) for p in ab] + [(p, "S->F", d["S->F"]) for p in sm]
        t, cause = self.latest(inst, terms)
        return (None, t, True, cause)

    def m_cla182(self, inst, pin, d):
        pg = [f"P{i}" for i in range(4)] + [f"G{i}" for i in range(4)]
        if pin.startswith("CN"):
            terms = [(p, "PG->CN", d["PG->CN"]) for p in pg] + [("CN", "CN->CN", d["CN->CN"])]
        elif pin == "P":
            terms = [(f"P{i}", "P->P", d["P->P"]) for i in range(4)]
        else:
            terms = [(p, "PG->G", d["PG->G"]) for p in pg]
        t, cause = self.latest(inst, terms)
        return (None, t, True, cause)

    def m_sram(self, inst, pin, d):
        ce, oe, we = (self.pin(inst, p)[0] for p in ("CE", "OE", "WE"))
        if ce == 1 or oe == 1 or we == 0:
            return (None, NEG, False, None)
        en = True if (ce == 0 and oe == 0 and we == 1) else None
        t, cause = self.latest(inst, [(f"A{i}", "tAA", d["tAA"]) for i in range(15)]
                               + [("CE", "tACE", d["tACE"]), ("OE", "tOE", d["tOE"])])
        return (None, t, en, cause)

    def m_rom(self, inst, pin, d):
        t, cause = self.latest(inst, [(f"A{i}", "tACC", d["tACC"]) for i in range(17)])
        return (self.const.get(inst.conn.get(pin)), t, True, cause)

    def m_const(self, inst, pin, d):
        return (int(pin == "HI"), NEG, True, None)

    def m_clockgen(self, inst, pin, d):
        if pin == "CLK":
            return (None, 0.0, True, None)
        if pin == "WEWIN":
            return (None, self.ws * self.T, True, ("X_CLK", "WEWIN", "write window opens"))
        return (1, NEG, True, None)             # RESET_n inactive

    def m_iodev(self, inst, pin, d):
        if pin == "IRQ":
            return (None, 5.0, True, None)
        t, cause = self.latest(inst, [(f"A{i}", "tACC", 20.0) for i in range(8)]
                               + [("IOSEL", "tACC", 20.0), ("RD", "tACC", 20.0)])
        return (None, t, None, cause)

    # ---- path tracing ----
    def path(self, net):
        out = []
        seen = set()
        while net and net not in seen:
            seen.add(net)
            v, t, cause = self.net(net)
            if cause is None:
                out.append((net, t, "", ""))
                break
            ref, src, dn = cause
            out.append((net, t, ref, dn))
            net = src if src not in ("CLK", "WEWIN") else None
            if src in ("CLK", "WEWIN"):
                out.append((src, 0.0 if src == "CLK" else self.ws * self.T, "", ""))
        return list(reversed(out))


# ---------------------------------------------------------------------------


def gate_inputs(inst, out_pin):
    """Input pins of the gate section that drives out_pin."""
    names = [p for p, _ in inst.type.pins]
    ins = []
    for p in reversed(names[:names.index(out_pin)]):
        if inst.type.kind(p) != "in":
            break
        ins.append(p)
    return ins


def constants_for(word, extra=None):
    """Control net values for a microcode word."""
    nets = cpu_v0.control_nets()
    c = {}
    for bit, name in nets.items():
        c[name] = (word >> bit) & 1
    if extra:
        c.update(extra)
    return c


def checks(case, N, we_frac):
    """List of (required margin, description, endpoint net) for this case.

    Each entry is a slack in ns (negative = violation)."""
    T = case.T
    out = []
    for inst in N.insts:
        t = inst.type
        d = N.delay[inst.ref]
        if t.model in ("reg377", "dff74", "dff175", "cnt161", "cnt163"):
            pins = []
            if t.model == "reg377":
                en = case.pin(inst, "EN")[0]
                pins.append(("EN", d["setup EN"]))
                if en != 1:
                    pins += [(f"D{i}", d["setup D"]) for i in range(1, 9)]
            elif t.model == "dff74":
                for s in "12":
                    if case.pin(inst, f"{s}CLK")[1] == NEG:
                        continue          # unused section (CLK tied to a rail)
                    pins.append((f"{s}D", d["setup D"]))
            elif t.model == "dff175":
                pins += [(f"{i}D", d["setup D"]) for i in range(1, 5)]
            else:
                load = case.pin(inst, "LOAD")[0]
                pins += [("LOAD", d["setup LOAD"]), ("ENP", d["setup EN"]), ("ENT", d["setup EN"])]
                if load != 1:
                    pins += [(p, d["setup data"]) for p in "ABCD"]
                if t.model == "cnt163":
                    pins.append(("CLR", d["setup CLR"]))
            for p, su in pins:
                if p not in inst.conn:
                    continue
                v, ta, _ = case.pin(inst, p)
                if ta == NEG:
                    continue
                out.append((T - (ta + su), f"{inst.ref}.{p} setup", inst.conn[p]))
        elif t.model == "sram":
            we_net = inst.conn["WE"]
            drv, out_pin = N.drivers[we_net][0]
            gate_ins = [drv.conn[p] for p in gate_inputs(drv, out_pin)]
            wv = case.net(we_net)[0]
            if wv == 1 or not any(n == "WEWIN" for n in gate_ins):
                continue                    # no write in this microinstruction
            gd = N.delay[drv.ref]["A->Y"]
            ctrl_t = max([case.net(n)[1] for n in gate_ins if n != "WEWIN"] + [case.ws * T])
            t_fall = ctrl_t + gd
            t_rise = we_frac * T + gd
            addr_t = max(case.pin(inst, f"A{i}")[1] for i in range(15))
            data_t = max(case.pin(inst, f"IO{i}")[1] for i in range(8))
            out.append((t_rise - t_fall - d["tWP"], f"{inst.ref} write pulse width (tWP)", we_net))
            out.append((t_fall - addr_t - d["tAS"], f"{inst.ref} address setup to write (tAS)",
                        inst.conn["A0"]))
            out.append((t_rise - addr_t - d["tAW"], f"{inst.ref} address to end of write (tAW)",
                        inst.conn["A0"]))
            worst_io = max(range(8), key=lambda i: case.pin(inst, f"IO{i}")[1])
            out.append((t_rise - data_t - d["tDW"], f"{inst.ref} data setup to end of write (tDW)",
                        inst.conn[f"IO{worst_io}"]))
    return out


def unique_words():
    rom, notes = microcode.built()
    words = defaultdict(list)
    for a, w in rom.items():
        mode_rst = (a >> 15) & 1
        words[(w, mode_rst)].append(notes[a])
    return words


def analyse(variant=chips.DEFAULT_VARIANT, corner="max", ws=0.5, we=0.875, lo=20.0, hi=2000.0):
    N = Netlist(cpu_v0.build(), variant, corner)
    results = []
    for (w, mrst), labels in unique_words().items():
        consts = constants_for(w, {"MODERST": mrst})

        def ok(T):
            c = Case(N, consts, T, ws)
            return min(s for s, _, _ in checks(c, N, we)) >= 0
        a, b = lo, hi
        if not ok(b):
            raise RuntimeError(f"microinstruction {w:012X} fails even at {hi} ns")
        while b - a > 0.25:
            mid = (a + b) / 2
            if ok(mid):
                b = mid
            else:
                a = mid
        results.append((b, w, mrst, labels))
    results.sort(reverse=True)
    return N, results


def report(N, results, ws=0.5, we=0.875, paths=3):
    lines = []
    T, w, mrst, labels = results[0]
    lines.append(f"minimum clock period: {T:.1f} ns ({1000 / T:.2f} MHz)")
    lines.append("")
    lines.append("slowest microinstructions:")
    seen = 0
    for T_, w_, m_, lab in results:
        names = sorted({l.split(' s')[0] for l in lab})
        lines.append(f"  {T_:7.1f} ns  {lab[0]:<22} ({len(lab)} ROM addresses; e.g. {', '.join(names[:3])})")
        seen += 1
        if seen >= 8:
            break
    lines.append("")
    for T_, w_, m_, lab in results[:paths]:
        c = Case(N, constants_for(w_, {"MODERST": m_}), T_, ws)
        worst = min(checks(c, N, we))
        lines.append(f"critical check for {lab[0]} at {T_:.1f} ns: {worst[1]} (slack {worst[0]:.1f} ns)")
        for net, t, ref, dn in c.path(worst[2]):
            lines.append(f"    {t:7.1f} ns  {net:<14} {ref:<10} {dn}")
        lines.append("")
    hist = defaultdict(int)
    for T_, *_rest in results:
        hist[int(T_ // 50) * 50] += 1
    lines.append("distribution of required periods over distinct microinstructions:")
    for k in sorted(hist):
        lines.append(f"  {k:4d}-{k + 49:<4d} ns: {hist[k]}")
    return "\n".join(lines)


def cmd_sta(args):
    N, results = analyse(args.variant, args.corner)
    print(f"static timing analysis: {args.variant}, {args.corner} delays, "
          f"{len(results)} distinct microinstructions")
    print(report(N, results, paths=args.paths))
    return 0
