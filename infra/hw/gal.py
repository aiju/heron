"""22V10s (GALs) in a netlist: each output a sum of products of nets or
their complements, combinatorial or registered on the GAL's CLK, fitted
to the 22V10's pins (CLK, I1-I11, IO0-IO9; any pin an output doesn't
take is an input) and to its macrocells' product terms. The chip-level
simulator and the static timing analysis read the same equations.

A sum of products is a list of terms, each a dict {net: the value it
must have}; [] is 0 and [{}] is 1.
"""

ZERO, ONE = [], [{}]
TERMS = [8, 10, 12, 14, 16, 16, 14, 12, 10, 8]     # IO0-IO9's macrocells
INPUTS = ["CLK"] + [f"I{i}" for i in range(1, 12)]


def lit(net, v=1):
    return [{net: v}]


def _tidy(f):
    out = []
    for t in f:
        if t not in out:
            out.append(t)
    # a term another term covers adds nothing
    return [t for t in out
            if not any(o is not t and len(o) < len(t) and all(t.get(k) == v for k, v in o.items())
                       for o in out)]


def AND(*fs):
    out = ONE
    for f in fs:
        out = [{**a, **b} for a in out for b in f
               if all(a.get(k, v) == v for k, v in b.items())]
    return _tidy(out)


def OR(*fs):
    return _tidy([t for f in fs for t in f])


def mux(sel, cases):
    """cases[i] (a sum of products, or 0 or 1): the function when the
    select nets, LSB first, read i."""
    out = []
    for i, f in enumerate(cases):
        f = ONE if f == 1 else ZERO if f == 0 else f
        out += AND([{n: (i >> k) & 1 for k, n in enumerate(sel)}], f)
    return _tidy(out)


def add(nl, ref, outputs, clock=None):
    """A 22V10: outputs {net: (sum of products, registered, inverted)}, the
    output the sum or, inverted, its complement; registered outputs load
    at clock's rising edge (an output's own net in a term is its pin, fed
    back)."""
    outs = sorted(outputs.items(), key=lambda kv: -len(kv[1][0]))
    if any(reg for _, (_, reg, _) in outs) and clock is None:
        raise ValueError(f"{ref}: registered outputs need a clock")
    cells = sorted(range(10), key=lambda i: -TERMS[i])
    pins = {}
    for (net, (terms, _reg, _inv)), cell in zip(outs, cells):
        if len(terms) > TERMS[cell]:
            raise ValueError(f"{ref}: {net} needs {len(terms)} product terms, "
                             f"its macrocell has {TERMS[cell]}")
        pins[net] = f"IO{cell}"
    if len(outs) > 10:
        raise ValueError(f"{ref}: {len(outs)} outputs")
    ins = sorted({n for _, (terms, _, _) in outs for t in terms for n in t} - set(pins))
    free = ([] if clock else ["CLK"]) + INPUTS[1:] + [f"IO{i}" for i in range(10)
                                                       if f"IO{i}" not in pins.values()]
    if len(ins) > len(free):
        raise ValueError(f"{ref}: {len(ins)} inputs and {len(outs)} outputs don't fit")
    conn = {pins[n]: n for n in pins}
    for net, pin in zip(ins, free[:len(ins)] if clock is None else free):
        conn[pin] = net
        pins[net] = pin
    if clock:
        conn["CLK"] = clock
    inst = nl.add("22v10", ref, **conn)
    inst.gal = [(pins[net], reg, inv, [[(pins[n], v) for n, v in t.items()] for t in terms])
                for net, (terms, reg, inv) in outs]
    index = inst.type.pin_index
    prog = [len(inst.gal)]
    for pin, reg, inv, terms in inst.gal:
        prog += [index[pin], int(reg) | int(inv) << 1, len(terms)]
        for t in terms:
            prog.append(len(t))
            prog += [index[p] * 2 + (1 - v) for p, v in t]
    inst.program = prog
    return inst


def equations(inst):
    """A 22V10's equations as text, by its nets: := for a registered
    output, / for a complement."""
    out = []
    for pin, reg, inv, terms in inst.gal:
        tt = " + ".join("·".join(("" if v else "/") + inst.conn[p] for p, v in t) or "1"
                        for t in terms) or "0"
        out.append(f"{'/' if inv else ''}{inst.conn[pin]} {':=' if reg else '='} {tt}")
    return "; ".join(out)


def minimise(on, dc, n):
    """A sum of products of n variables (as indices 0..n-1, LSB first) that
    is 1 on the minterms `on`, 0 off `on` and `dc`: prime cubes, greedily."""
    on, ok = set(on), set(on) | set(dc)
    cubes = []
    for care in range(1 << n):
        for val in range(1 << n):
            if val & ~care:
                continue
            ms = {m for m in range(1 << n) if m & care == val}
            if ms <= ok and ms & on:
                cubes.append((care, val, ms))
    out, left = [], set(on)
    while left:
        care, val, ms = max(cubes, key=lambda c: (len(c[2] & left), -bin(c[0]).count("1")))
        out.append({i: (val >> i) & 1 for i in range(n) if care >> i & 1})
        left -= ms
    return out


def when(nets, codes, used):
    """A sum of products over the code nets (LSB first) true for the codes
    `codes`, of the `used` ones (the others don't care)."""
    n = len(nets)
    dc = set(range(1 << n)) - set(used)
    return [{nets[i]: v for i, v in t.items()} for t in minimise(codes, dc, n)]
