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

# the current path through a mated contact: about 8.5 mm of backplane
# connector above a 3.2 mm backplane, the mated pin, and 6-10 mm of
# right-angle pin to the card. Rows differ by a few mm; one length for all.
LENGTH = 20e-3
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
