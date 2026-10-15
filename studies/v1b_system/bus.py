"""The system bus as the netlists see it (RFC 0014): its signals, where a
card's connector pins go in each slot, and the composer that puts cards
into the backplane's slots.

A card's netlist names its connector pins BUS.<signal>: BUS.D0,
BUS.SEL, BUS.BCLK. In slot k a bused signal joins the backplane's net of
the same name, a radial one the backplane's <signal>.<k> (SEL.3), and a
slot-number strap (GA0-GA3) a rail. Active-low signals end in _n, as the
RFC's "active low on the backplane" says, except SEL: it is active high,
so that a simple card's strobes are one Schmitt NAND from it (RFC 0014
section 6 needs that; its signal table says active low).

Wiring has no delay in the chip-level simulator, so the composer adds the
time a line takes to settle to every driver on it: report 0022's 13 ns
for bused lines at 16 slots with 12 pF cards, and a few ns for the short
radial lines from the backplane's logic in the middle.
"""

from heron.infra.hw.netlist import Netlist

SLOTS = 16

# P1 and P2, bused: every slot has the same net.
BUSED = ([f"D{i}" for i in range(32)] + [f"A{i}" for i in range(1, 32)]
         + [f"BE{i}_n" for i in range(4)]
         + ["START_n", "WRITE_n", "LOCK_n", "DPH_n", "RDY_n", "WAIT_n", "BERR_n", "W32_n",
            "RESET_n"]
         + [f"IRQ{i}_n" for i in range(8)])
# radial: each slot has its own line to the backplane's logic
RADIAL = ["CLASS0", "CLASS1", "REQ_n", "GNT_n", "SEL", "BCLK"]
# strapped on the backplane: the slot number, for cards that want it
STRAPPED = ["GA0", "GA1", "GA2", "GA3"]
# slot 0 only: the bus clock from the main CPU board to the clock driver
SLOT0 = ["CLKSRC"]

# settling after a driver's output changes (ps): report 0022, and RFC 0014
# section 17's suggestion of 13 ns for bused lines in the budgets
SETTLE_BUSED = 13_000
SETTLE_RADIAL = 4_000

# the class straps, by what a card is (CLASS1, CLASS0; 0 = tied to ground)
CLASSES = {"empty": (1, 1), "simple": (1, 0), "fast16": (0, 1), "fast32": (0, 0)}


def slot_net(signal, slot):
    """The system's net for a card's connector pin BUS.<signal> in a slot."""
    if signal in BUSED:
        return signal
    if signal in RADIAL:
        return f"{signal}.{slot}"
    if signal in STRAPPED:
        return "VCC" if (slot >> int(signal[2])) & 1 else "GND"
    if signal in SLOT0:
        if slot != 0:
            raise ValueError(f"BUS.{signal} is only wired at slot 0")
        return signal
    raise ValueError(f"no bus signal {signal}")


def strap_class(nl, kind):
    """Tie a card's class pins for what it is ("simple", "fast16",
    "fast32"): a pin to ground is a strap, an open one the backplane pulls
    up."""
    c1, c0 = CLASSES[kind]
    pins = {}
    if c1 == 0:
        pins["LO"] = "BUS.CLASS1"
    if c0 == 0:
        if pins:
            nl.add("const", "X_STRAP0", LO="BUS.CLASS0")
        else:
            pins["LO"] = "BUS.CLASS0"
    if pins:
        nl.add("const", "X_STRAP", **pins)


class Card:
    """A card: its netlist (with BUS.* nets for its connector pins) and a
    name for its slot's prefix."""

    def __init__(self, name, netlist):
        self.name = name
        self.netlist = netlist

    def connector(self):
        return sorted({n[4:] for i in self.netlist.instances for n in i.conn.values()
                       if n.startswith("BUS.")})


def compose(backplane, cards, settle=True):
    """The system's netlist: the backplane, with each card of `cards`
    ({slot: Card}) included as <name>.<ref>, its connector joined to the
    slot's nets. With settle, every output on a bus line takes the line's
    settling time longer."""
    nl = Netlist()
    nl.include(backplane, "BP", {n: n for n in _bus_nets(backplane)})
    for slot, card in sorted(cards.items()):
        connect = {f"BUS.{s}": slot_net(s, slot) for s in card.connector()}
        nl.include(card.netlist, card.name, connect)
    if settle:
        add_settling(nl)
    nl.check()
    return nl


def _bus_nets(backplane):
    """The backplane's nets that are bus lines keep their names."""
    out = set()
    for inst in backplane.instances:
        for n in inst.conn.values():
            base = n.rsplit(".", 1)[0]
            if n in BUSED or n in SLOT0 or base in RADIAL:
                out.add(n)
    return out


def line_kind(net):
    if net in BUSED:
        return "bused"
    if net.rsplit(".", 1)[0] in RADIAL:
        return "radial"
    return None


def add_settling(nl):
    """Lengthen, on every chip that drives a bus line, the delays of the
    arcs that end at that line's pin."""
    for inst in nl.instances:
        if inst.type.family == "fixture":
            continue
        extra = {}
        for pin, net in inst.conn.items():
            if inst.type.kind(pin) not in ("out", "tri", "io"):
                continue
            kind = line_kind(net)
            if kind is None:
                continue
            ps = SETTLE_BUSED if kind == "bused" else SETTLE_RADIAL
            for frm, to, name in inst.type.arcs:
                if pin in to:
                    extra[name] = max(extra.get(name, 0), ps)
        for name, ps in extra.items():
            inst.add_delay(name, ps)
