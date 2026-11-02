"""22V10s (GALs) in a netlist: each output a sum of products of nets or
their complements, combinatorial or registered on the GAL's CLK, fitted
to the 22V10's pins (CLK, I1-I11, IO0-IO9; any pin an output doesn't
take is an input) and to its macrocells' product terms. The chip-level
simulator and the static timing analysis read the same equations.

A sum of products is a list of terms, each a dict {net: the value it
must have}; [] is 0 and [{}] is 1.

An output may have an output enable (a sum of products: the pin drives
while it's true, else it's off), and the GAL an asynchronous reset (AR,
a sum of products clearing every register while it's true), as the
22V10's macrocells and its AR term have. Static timing analysis reads
neither (the GALs that use them are outside its netlists).
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


def add(nl, ref, outputs, clock=None, ar=None, pins=None):
    """A 22V10: outputs {net: (sum of products, registered, inverted[,
    output enable])}, the output the sum or, inverted, its complement;
    registered outputs load at clock's rising edge (an output's own net in
    a term is its pin, fed back); ar, the asynchronous reset. pins {net:
    pin} holds nets on the pins a board already has them on; the others
    go where they fit."""
    oes = {net: o[3] for net, o in outputs.items() if len(o) > 3}
    outputs = {net: o[:3] for net, o in outputs.items()}
    outs = sorted(outputs.items(), key=lambda kv: -len(kv[1][0]))
    if any(reg for _, (_, reg, _) in outs) and clock is None:
        raise ValueError(f"{ref}: registered outputs need a clock")
    held = dict(pins or {})
    cells = [i for i in sorted(range(10), key=lambda i: -TERMS[i])
             if f"IO{i}" not in held.values()]
    pins = {}
    for net, (terms, _reg, _inv) in outs:
        pin = held.get(net)
        if pin is None:
            if not cells:
                raise ValueError(f"{ref}: {len(outs)} outputs")
            pin = f"IO{cells.pop(0)}"
        if len(terms) > TERMS[int(pin[2:])]:
            raise ValueError(f"{ref}: {net} needs {len(terms)} product terms, "
                             f"its macrocell has {TERMS[int(pin[2:])]}")
        pins[net] = pin
    if len(outs) > 10:
        raise ValueError(f"{ref}: {len(outs)} outputs")
    extra = [t for f in list(oes.values()) + [ar or []] for t in f]
    ins = sorted(({n for _, (terms, _, _) in outs for t in terms for n in t}
                  | {n for t in extra for n in t}) - set(pins))
    taken = set(pins.values()) | {held[n] for n in ins if n in held}
    free = [p for p in ([] if clock else ["CLK"]) + INPUTS[1:] + [f"IO{i}" for i in range(10)]
            if p not in taken]
    loose = [n for n in ins if n not in held]
    if len(loose) > len(free):
        raise ValueError(f"{ref}: {len(ins)} inputs and {len(outs)} outputs don't fit")
    conn = {pins[n]: n for n in pins}
    for net in ins:
        if net in held:
            conn[held[net]] = net
            pins[net] = held[net]
    for net, pin in zip(loose, free):
        conn[pin] = net
        pins[net] = pin
    if clock:
        conn["CLK"] = clock
    inst = nl.add("22v10", ref, **conn)
    inst.gal = [(pins[net], reg, inv, [[(pins[n], v) for n, v in t.items()] for t in terms])
                for net, (terms, reg, inv) in outs]
    inst.gal_oe = {pins[net]: [[(pins[n], v) for n, v in t.items()] for t in f]
                   for net, f in oes.items()}
    inst.gal_ar = [[(pins[n], v) for n, v in t.items()] for t in ar] if ar else None
    index = inst.type.pin_index

    def sop(terms):
        out = [len(terms)]
        for t in terms:
            out.append(len(t))
            out += [index[p] * 2 + (1 - v) for p, v in t]
        return out
    prog = [len(inst.gal)]
    for pin, reg, inv, terms in inst.gal:
        oe = inst.gal_oe.get(pin)
        prog += [index[pin], int(reg) | int(inv) << 1 | int(oe is not None) << 2]
        prog += sop(terms)
        if oe is not None:
            prog += sop(oe)
    if inst.gal_ar:
        prog += sop(inst.gal_ar)
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


def minimise_qm(on, dc, n):
    """minimise() for more variables: the prime cubes by merging
    (Quine-McCluskey), then a greedy cover. Cubes are (care, value)."""
    on, ok = set(on), set(on) | set(dc)
    full = (1 << n) - 1
    level = {(full, m) for m in ok}
    primes = set()
    while level:
        merged, nxt = set(), set()
        for care, val in level:
            for i in range(n):
                b = 1 << i
                if care & b and not val & b and (care, val | b) in level:
                    nxt.add((care & ~b, val))
                    merged.add((care, val))
                    merged.add((care, val | b))
        primes |= level - merged
        level = nxt

    def covers(cube):
        care, val = cube
        free = [i for i in range(n) if not care >> i & 1]
        out = set()
        for k in range(1 << len(free)):
            m = val
            for j, i in enumerate(free):
                if k >> j & 1:
                    m |= 1 << i
            out.add(m)
        return out
    cubes = [(c, covers(c) & on) for c in primes]
    cubes = [c for c in cubes if c[1]]
    out, left = [], set(on)
    while left:
        (care, val), ms = max(cubes, key=lambda c: (len(c[1] & left),
                                                    -bin(c[0][0]).count("1")))
        out.append({i: (val >> i) & 1 for i in range(n) if care >> i & 1})
        left -= ms
    return out


def table(nets, f):
    """A sum of products over nets (LSB first) true where f(*bits) is,
    None where it doesn't care."""
    n = len(nets)
    on, dc = [], []
    for c in range(1 << n):
        v = f(*[(c >> i) & 1 for i in range(n)])
        if v is None:
            dc.append(c)
        elif v:
            on.append(c)
    return [{nets[i]: v for i, v in t.items()} for t in minimise_qm(on, dc, n)]


def when(nets, codes, used):
    """A sum of products over the code nets (LSB first) true for the codes
    `codes`, of the `used` ones (the others don't care)."""
    n = len(nets)
    dc = set(range(1 << n)) - set(used)
    return [{nets[i]: v for i, v in t.items()} for t in minimise(codes, dc, n)]
