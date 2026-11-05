"""Helpers the boards share: sums of products for the 22V10s, a board's
slice of the control store, its clock buffer, gated clocks."""

from heron.infra.hw import gal as G

from . import fields as F
from .bus import UPCN

ZERO, ONE = G.ZERO, G.ONE
AND, OR, lit, table = G.AND, G.OR, G.lit, G.table


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def eq(nets, value):
    """The term: the nets (LSB first) read value."""
    return [{n: (value >> i) & 1 for i, n in enumerate(nets)}]


def anyof(nets, values):
    return OR(*[eq(nets, v) for v in values])


def negate(f):
    """The complement of a sum of products (De Morgan, then tidied)."""
    out = ONE
    for t in f:
        out = AND(out, [{n: 1 - v} for n, v in t.items()])
    return out


def clock_buffer(nl, ref="U_CK", src="CYC", prefix="CK"):
    """The board's copies of a backplane clock (a CDC341): CK1-CK8."""
    nl.add("clkdrv", ref, A=src, **{f"Y{i}": f"{prefix}{i}" for i in range(1, 9)})
    return [f"{prefix}{i}" for i in range(1, 9)]


def control_slice(nl, board, clk, direct=(), rename=None, clear=None):
    """The board's slice of the control store: its own µPC (two 574s, from
    the backplane's UPCN), a part per byte on it, and a 74ABT574 for each
    byte (but `direct` fields, which go straight from the parts to their
    nets). The µPC and the 574s load at the cycle's start, on the one clock
    net (clk), so that the word under the 574s can't change before they
    have loaded it: the parts' output hold is 0. rename: {field net: net}
    for bits that drive a line of the backplane themselves. clear: an
    active-low net that empties the word (every field 0, which is "nothing"
    in each): its registers are then 823s, cleared by it at once."""
    upc = [f"UPC{i}" for i in range(F.ADDR_BITS)]
    for k in range(2):
        lo = 8 * k
        n = min(8, F.ADDR_BITS - lo)
        nl.add("574", f"U_UPC{k}", OE="GND", CLK=clk,
               **{f"D{i + 1}": UPCN[lo + i] if i < n else "GND" for i in range(8)},
               **{f"Q{i + 1}": upc[lo + i] if i < n else f"UPC_NC{lo + i}" for i in range(8)})
    bits = {b: (rename or {}).get(n, n) for b, n in F.word_bits(board).items()}
    direct_bits = {b for name in direct for b in range(*_span(board, name))}
    for k in range(F.PARTS[board]):
        raw = []
        for i in range(8):
            b = 8 * k + i
            net = bits.get(b, f"u{board}_SPARE{b}")
            raw.append(net if b in direct_bits else f"cs{board}_{b}")
        addr = {f"A{i}": upc[i] for i in range(F.ADDR_BITS)}
        addr.update({f"A{i}": "GND" for i in range(F.ADDR_BITS, 17)})
        nl.add("flash", f"U_CS{k}", CE="GND", OE="GND", WE="VCC", **addr,
               **{f"D{i}": raw[i] for i in range(8)})
        if not all(8 * k + i in direct_bits for i in range(8)):
            q = {f"Q{i + 1}": bits.get(8 * k + i, f"u{board}_SPARE{8 * k + i}") for i in range(8)}
            if clear:
                nl.add("823", f"U_MIR{k}", OE="GND", CLK=clk, EN="GND", CLR=clear,
                       **{f"D{i + 1}": raw[i] for i in range(8)}, D9="GND", **q, Q9=f"MIR{k}_NC")
            else:
                nl.add("574", f"U_MIR{k}", OE="GND", CLK=clk,
                       **{f"D{i + 1}": raw[i] for i in range(8)}, **q)


def _span(board, name):
    b, w = F.positions(board)[name]
    return (b, b + w)


def gated_clock(outs, name, enable, clk="CK1", wph="WPH", late=True):
    """A clock that rises with the cycle's start (clk) only at the end of a
    cycle whose `enable` (a sum of products, steady through the cycle) is
    true: ARM, registered on the master clock, is set through the write
    phase (the cycle's last three ticks) and clears two ticks into the next
    cycle (ARMD, a tick after the write phase, ends it), so it is steady
    around clk's rise, which comes about a tick after the edge. Adds the
    outputs to a GAL's output dict, whose clock must be MCLK. late=False:
    ARM clears a tick in, racing clk's rise (open: VIDEO's, whose GAL has
    no room for ARMD). wph=None: ARM is the enable itself, registered (a
    clock at the master clock's next edge)."""
    arm = f"ARM_{name}"
    if wph and not late:
        outs[arm] = (AND(lit(wph), enable), True, False)
    elif wph:
        armd = f"ARMD_{name}"
        outs[arm] = (OR(AND(lit(wph), enable), AND(lit(arm), lit(wph, 0), lit(armd, 0))), True, False)
        outs[armd] = (AND(lit(arm), lit(wph, 0)), True, False)
    else:
        outs[arm] = (enable, True, False)
    outs[name] = (AND(lit(clk), lit(arm)), False, False)
    return name
