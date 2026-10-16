"""The DIN 41612 connector as a pin field.

Each contact is a conductor from the backplane's planes to the card's:
the backplane connector's press-fit pin and body, the mated pin, and the
card connector's right-angle pin. Every contact of a slot is one inductor
in the netlist, all mutually coupled (infra/si/pins.py), with the ground
and power pins as the return paths. That gives each signal its loop
inductance and its coupling to its neighbours from where the ground pins
are, and the card's ground bounce from the return current they share.

The pin assignment of RFC 0014 is still to do. `p1_map` is a reference
assignment for simulation that follows its rules: BCLK, SEL, WRITE and
RESET each have a ground pin on both sides, in the row and across rows,
and the power and ground pins are spread along the connector.
"""

import numpy as np

from heron.infra.si import pins

PITCH = 2.54e-3
ROWS = "abc"
POSITIONS = 32

# the current path through a mated contact: the backplane connector
# (11.5 mm), the mated pin and the card's right-angle pin (10 mm body), and
# the plated holes at both ends. Rows differ by a few mm; one length for
# all. 25 mm makes the model match the one crosstalk measurement found
# (TE's Eurocard catalog: 23% near end, 20% far end on a quiet row-b pin,
# with A1-A8 and C1-C8 driven by 2 ns edges); 20 mm gives 16% and 15%.
LENGTH = 25e-3
# the contacts are 0.6 mm square pins in sockets about 1 mm across
RADIUS = 0.4e-3
# capacitance of one contact to its surroundings, with the plated holes at
# both ends (report 0013's estimate), and the housing's permittivity
C_CONTACT = 2e-12
ER_HOUSING = 3.5


def xy(pin):
    """Position (m) of a pin such as 'b12'."""
    row, pos = pin[0], int(pin[1:])
    return ROWS.index(row) * PITCH, (pos - 1) * PITCH


def _fill(assigned, names):
    """Put `names` on the free pins in order, positions first."""
    free = [f"{r}{p}" for p in range(1, POSITIONS + 1) for r in ROWS if f"{r}{p}" not in assigned]
    for name, pin in zip(names, free):
        assigned[pin] = name
    return assigned


def p1_map(guard=True):
    """A reference P1 assignment: {pin: signal}. Ground pins are 'GND',
    power pins 'VCC'. With guard=False, the ground pins around BCLK, SEL,
    WRITE and RESET carry data lines instead (and the spare ground pins go
    to the end of the connector), to see what they're worth."""
    m = {}
    guarded = {"BCLK": 4, "SEL": 12, "WRITE": 20, "RESET": 28}
    for name, pos in guarded.items():
        m[f"b{pos}"] = name
        for pin in (f"a{pos}", f"c{pos}", f"b{pos - 1}", f"b{pos + 1}"):
            m[pin] = "GND" if guard else None
    for pin in ("a1", "c1", "a8", "c8", "a16", "c16", "a24", "c24", "a32", "c32"):
        m[pin] = "VCC" if pin[1:] in ("1", "16", "32") else "GND"
    # 16 + 10 power and ground pins: two more than RFC 0014's 24, so trade
    # two grounds back for signals
    m["a8"] = m["c24"] = None
    signals = ([f"D{i}" for i in range(16)] + [f"A{i}" for i in range(1, 32)]
               + ["BE0", "BE1", "START", "LOCK", "DPH", "RDY", "WAIT", "BERR", "CLASS0", "CLASS1",
                  "REQ", "GNT"] + [f"IRQ{i}" for i in range(4)] + [f"RSV{i}" for i in range(5)])
    m = {k: v for k, v in m.items() if v is not None}
    _fill(m, signals)
    if not guard:
        # the 16 pins freed around the guarded signals took signals; give
        # the leftover names nothing, and make the last free pins grounds
        pass
    free = [f"{r}{p}" for p in range(1, POSITIONS + 1) for r in ROWS if f"{r}{p}" not in m]
    for pin in free:
        m[pin] = "GND"
    return m


def p2_map():
    """A reference P2 assignment: the upper data half and the extras, with
    16 power and ground pins spread along it (RFC 0014: about 16) and the
    user-defined pins left out (they carry nothing here)."""
    m = {}
    for pos in range(1, POSITIONS + 1, 4):
        m[f"a{pos}"] = "GND"
        m[f"c{pos + 2}"] = "GND" if pos % 8 == 1 else "VCC"
    signals = ([f"D{i}" for i in range(16, 32)] + ["BE2", "BE3", "W32"] + [f"IRQ{i}" for i in range(4, 8)]
               + [f"GA{i}" for i in range(4)] + ["CLKSRC"])
    _fill(m, signals)
    return m


def victim_map(guard=True, victims={"SEL": 12, "WRITE": 20}, aggressors=16):
    """A P1 map for crosstalk: each victim in row b with, if `guard`, the
    ground pins RFC 0014 asks for on all four sides, and the data lines
    D0.. on the free pins nearest the victims, so that the victims' worst
    neighbours are switching. The other power and ground pins (24 in all)
    are spread over the rest of the connector."""
    m = {}
    for name, pos in victims.items():
        m[f"b{pos}"] = name
        if guard:
            for pin in (f"a{pos}", f"c{pos}", f"b{pos - 1}", f"b{pos + 1}"):
                m[pin] = "GND"
    vxy = [xy(f"b{pos}") for pos in victims.values()]
    free = [f"{r}{p}" for p in range(1, POSITIONS + 1) for r in ROWS if f"{r}{p}" not in m]
    free.sort(key=lambda pin: min(np.hypot(*(np.array(xy(pin)) - np.array(v))) for v in vxy))
    for i, pin in enumerate(free[:aggressors]):
        m[pin] = f"D{i}"
    rest = [p for p in free[aggressors:]]
    n_ret = 24 - sum(1 for v in m.values() if v == "GND")
    # spread the remaining returns evenly over the pins left, far side first
    rest.sort(key=lambda pin: (int(pin[1:]), pin[0]))
    for k in range(n_ret):
        m[rest[(k * len(rest)) // n_ret]] = "GND" if k % 3 else "VCC"
    return m


def netlist(m, tag, bp, card, card_gnd, card_vcc, signals, bp_vcc="vcc", length=LENGTH, radius=RADIUS):
    """Netlist lines for one connector as coupled inductors: the named
    signals from their backplane node bp[s] to their card node card[s],
    and every power and ground pin from the backplane's plane to the
    card's (GND: node 0 to card_gnd; VCC: bp_vcc to card_vcc). Each
    contact also has half of C_CONTACT at each end. Pins of other signals
    are left out: they carry no current."""
    order, lp = partial(m, length, radius)
    sig = by_signal(m)
    use = [sig[s] for s in signals] + returns(m)
    idx = [order.index(p) for p in use]
    sub = lp[np.ix_(idx, idx)]
    out = []
    names = []
    for i, pin in enumerate(use):
        name = m[pin]
        if name == "GND":
            a, b, ga, gb = "0", card_gnd, "0", card_gnd
        elif name == "VCC":
            a, b, ga, gb = bp_vcc, card_vcc, "0", card_gnd
        else:
            a, b, ga, gb = bp[name], card[name], "0", card_gnd
        ln = f"L{tag}_{pin}"
        names.append(ln)
        out.append(f"{ln} {a} {b} {sub[i, i]:.5g}")
        if name not in ("GND", "VCC"):
            out += [f"C{tag}_{pin}a {a} {ga} {C_CONTACT / 2:.4g}", f"C{tag}_{pin}b {b} {gb} {C_CONTACT / 2:.4g}"]
    for i in range(len(use)):
        for j in range(i + 1, len(use)):
            k = sub[i, j] / np.sqrt(sub[i, i] * sub[j, j])
            out.append(f"K{tag}_{use[i]}_{use[j]} {names[i]} {names[j]} {k:.5f}")
    return out


def returns(m):
    return [p for p, s in m.items() if s in ("GND", "VCC")]


def by_signal(m):
    return {s: p for p, s in m.items() if s not in ("GND", "VCC")}


def partial(m, length=LENGTH, radius=RADIUS):
    """(pins in order, partial inductance matrix) for a whole connector."""
    order = sorted(m, key=lambda p: (int(p[1:]), p[0]))
    return order, pins.partial_matrix([xy(p) for p in order], length, radius)


def loop(m, signals, length=LENGTH, radius=RADIUS):
    """Loop inductance matrix (H) of the named signals, returning through
    every power and ground pin, the other signal pins carrying nothing."""
    order, lp = partial(m, length, radius)
    sig = by_signal(m)
    s_idx = [order.index(sig[s]) for s in signals]
    g_idx = [order.index(p) for p in returns(m)]
    return pins.loop_matrix(lp, s_idx, g_idx)


def mutual_c(m, signals, length=LENGTH):
    """Mutual capacitance (F) between the named signals, from the 2D field
    of the pin field with the power and ground pins at 0 V, scaled so the
    pins' own capacitance matches C_CONTACT."""
    order = sorted(m, key=lambda p: (int(p[1:]), p[0]))
    g = [order.index(p) for p in returns(m)]
    c, sig_idx = pins.capacitance_matrix([xy(p) for p in order], RADIUS, g, ER_HOUSING)
    sig = by_signal(m)
    rows = [sig_idx.index(order.index(sig[s])) for s in signals]
    sub = c[np.ix_(rows, rows)] * length
    return sub


def describe(m=None):
    """Loop inductance of each signal pin, and its largest coupling."""
    m = m or p1_map()
    names = list(by_signal(m))
    lm = loop(m, names)
    k = pins.coupling(lm)
    out = {}
    for i, s in enumerate(names):
        kk = np.abs(k[i]).copy()
        kk[i] = 0
        j = int(np.argmax(kk))
        out[s] = {"pin": by_signal(m)[s], "L": float(lm[i, i]), "k_max": float(kk[j]), "k_with": names[j]}
    return out


def te_check(length=LENGTH, victim="B4"):
    """The connector model against TE's measured crosstalk (Eurocard
    catalog 82721, p. 11): VME's P1 pinout, A1-A8 and C1-C8 driven with a
    0-3 V, 2 ns ramp, a quiet row-b pin watched at both ends. The catalog
    doesn't describe the fixture; here every line has 50 ohm at both ends,
    and the returns are VME P1's ground and +5 V pins. Measured: 700 mV
    (23.3%) at the near end, -600 mV (20.0%) at the far end. Returns the
    model's (near, far) peaks in volts."""
    from heron.infra.si import engine
    m = {pin: "GND" for pin in ("a9", "a11", "a15", "a17", "a19", "b20", "b23", "c9")}
    m.update({pin: "VCC" for pin in ("a32", "b32", "c32")})
    for i in range(1, 9):
        m[f"a{i}"], m[f"b{i}"], m[f"c{i}"] = f"A{i}", f"B{i}", f"C{i}"
    aggr = [f"A{i}" for i in range(1, 9)] + [f"C{i}" for i in range(1, 9)]
    sigs = aggr + [victim]
    bp = {s: f"n_{s}" for s in sigs}
    cd = {s: f"f_{s}" for s in sigs}
    lines = ["Vcc vcc 0 5"] + netlist(m, "K", bp, cd, "0", "0", sigs, length=length)
    c = mutual_c(m, sigs, length)
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            if -c[i, j] > 1e-15:
                lines += [f"Cm{i}_{j} {bp[sigs[i]]} {bp[sigs[j]]} {-c[i, j] / 2:.4g}",
                          f"Cn{i}_{j} {cd[sigs[i]]} {cd[sigs[j]]} {-c[i, j] / 2:.4g}"]
    lines.append("Vdrv drv 0 PWL(0 0 1n 0 3n 3)")
    for s in aggr:
        lines += [f"Rs_{s} drv {bp[s]} 50", f"Rl_{s} {cd[s]} 0 50"]
    lines += [f"Rs_v {bp[victim]} 0 50", f"Rl_v {cd[victim]} 0 50"]
    r = engine.run_native(lines, [f"v({bp[victim]})", f"v({cd[victim]})"], 10e-9, dt=1e-12)

    def peak(x):
        return float(x[np.argmax(np.abs(x))])
    return peak(r[f"v({bp[victim]})"]), peak(r[f"v({cd[victim]})"])
