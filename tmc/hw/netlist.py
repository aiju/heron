"""Netlist description language.

    nl = Netlist()
    u = nl.add("157", "U12", S="SEL", G="GND", **{"1A": "X0", "1B": "Y0", "1Y": "Z0", ...})
    nl.gate("08", ["A", "B"], "AB")      # packs gates into 74xx08 packages

Nets are plain strings. "GND" and "VCC" are the supply rails. Every input
pin must be connected (tie unused inputs to a rail); outputs may be left
open. `check()` verifies that every net has a sensible set of drivers.
"""

from collections import defaultdict

from . import chips

GATE_SECTIONS = {
    "00": (4, 2), "02": (4, 2), "04": (6, 1), "08": (4, 2), "10": (3, 3),
    "21": (2, 4), "30": (1, 8), "32": (4, 2), "86": (4, 2),
}


class Instance:
    def __init__(self, nl, typ, ref, role=None):
        self.nl = nl
        self.type = chips.TYPES[typ]
        self.ref = ref
        self.role = role
        self.conn = {}

    def __setitem__(self, pin, net):
        if pin not in self.type.pin_index:
            raise KeyError(f"{self.ref} ({self.type.name}) has no pin {pin}")
        if pin in self.conn:
            raise ValueError(f"{self.ref}.{pin} connected twice")
        self.conn[pin] = net

    def connect(self, **pins):
        for p, n in pins.items():
            self[p] = n
        return self


class Netlist:
    def __init__(self):
        self.instances = []
        self.refs = {}
        self.gate_pool = defaultdict(list)   # type -> [(instance, next free section)]
        self.counters = defaultdict(int)

    def add(self, typ, ref=None, role=None, **pins):
        if ref is None:
            self.counters[typ] += 1
            ref = f"U{typ}_{self.counters[typ]}"
        if ref in self.refs:
            raise ValueError(f"duplicate reference {ref}")
        inst = Instance(self, typ, ref, role)
        self.instances.append(inst)
        self.refs[ref] = inst
        inst.connect(**pins)
        return inst

    def gate(self, typ, inputs, output):
        """Place one gate of a 74xx package, reusing free sections."""
        n_sec, n_in = GATE_SECTIONS[typ]
        inputs = list(inputs)
        if len(inputs) > n_in:
            raise ValueError(f"{typ} gate has {n_in} inputs, got {len(inputs)}")
        while len(inputs) < n_in:          # spare inputs of AND/NAND tie high, OR/NOR/XOR low
            inputs.append("VCC" if typ in ("00", "08", "10", "21", "30") else "GND")
        pool = self.gate_pool[typ]
        if not pool or pool[-1][1] >= n_sec:
            pool.append([self.add(typ), 0])
        inst, sec = pool[-1]
        pool[-1][1] += 1
        letters = "ABCDEFGH"
        if n_sec == 1:
            names, out = [letters[i] for i in range(n_in)], "Y"
        else:
            names, out = [f"{sec + 1}{letters[i]}" for i in range(n_in)], f"{sec + 1}Y"
        for p, n in zip(names, inputs):
            inst[p] = n
        inst[out] = output
        return inst

    def finish(self):
        """Tie off unused gate sections so every input is driven."""
        for typ, pool in self.gate_pool.items():
            n_sec, n_in = GATE_SECTIONS[typ]
            for inst, used in pool:
                for sec in range(used, n_sec):
                    for i in range(n_in):
                        p = f"{sec + 1}{'ABCDEFGH'[i]}" if n_sec > 1 else "ABCDEFGH"[i]
                        inst[p] = "GND"

    # ---- checks and export ----------------------------------------------

    def nets(self):
        """net -> list of (instance, pin, kind)."""
        out = defaultdict(list)
        for inst in self.instances:
            for pin, net in inst.conn.items():
                out[net].append((inst, pin, inst.type.kind(pin)))
        return out

    def check(self):
        errors = []
        for inst in self.instances:
            for pin, kind in inst.type.pins:
                if kind == "in" and pin not in inst.conn:
                    errors.append(f"{inst.ref}.{pin} ({inst.type.name}) is unconnected")
        for net, conns in self.nets().items():
            drivers = [c for c in conns if c[2] in ("out", "tri", "io")]
            hard = [c for c in conns if c[2] == "out"]
            if net in ("GND", "VCC"):
                continue
            if not drivers:
                errors.append(f"net {net} has no driver (read by "
                              f"{', '.join(f'{i.ref}.{p}' for i, p, _ in conns)})")
            elif len(hard) > 1 or (hard and len(drivers) > 1):
                errors.append(f"net {net} has conflicting drivers: "
                              f"{', '.join(f'{i.ref}.{p}' for i, p, _ in drivers)}")
        if errors:
            raise ValueError("netlist errors:\n  " + "\n  ".join(errors[:40]))

    def export(self, variant=chips.DEFAULT_VARIANT, corner="max", extra=None):
        """JSON-able dict for the Go simulator."""
        timing = chips.load_timing()
        net_ids = {}
        for inst in self.instances:
            for net in inst.conn.values():
                net_ids.setdefault(net, len(net_ids))
        out_chips = []
        for inst in self.instances:
            t = inst.type
            part = chips.part_number(variant, t.name, inst.role)
            delays = chips.delays_for(timing, part, corner) if t.family != "fixture" else {}
            out_chips.append({
                "ref": inst.ref, "type": t.name, "model": t.model, "part": part,
                "pins": [p for p, _ in t.pins],
                "kinds": [k for _, k in t.pins],
                "nets": [net_ids.get(inst.conn.get(p), -1) for p, _ in t.pins],
                "delays": delays,
            })
        nets = [None] * len(net_ids)
        for n, i in net_ids.items():
            nets[i] = n
        d = {"nets": nets, "chips": out_chips, "variant": variant, "corner": corner}
        if extra:
            d.update(extra)
        return d

    def bom(self, variant=chips.DEFAULT_VARIANT):
        counts = defaultdict(list)
        for inst in self.instances:
            if inst.type.family == "fixture":
                continue
            counts[chips.part_number(variant, inst.type.name, inst.role)].append(inst.ref)
        return dict(sorted(counts.items()))
