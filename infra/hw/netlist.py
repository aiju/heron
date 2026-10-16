"""Netlist description language.

    nl = Netlist()
    u = nl.add("157", "U12", S="SEL", G="GND", **{"1A": "X0", "1B": "Y0", "1Y": "Z0", ...})
    nl.gate("08", ["A", "B"], "AB")      # packs gates into 74xx08 packages

Nets are plain strings. "GND" and "VCC" are the supply rails. Every input
pin must be connected (tie unused inputs to a rail); outputs may be left
open. `check()` verifies that every net has a sensible set of drivers.

A chip's part number comes from the parts variant (chips.VARIANTS), unless
`add` names one with part=...; the cards on the system bus name theirs
(74ABT245, 74F163). `params` are settings of the part itself (an
oscillator's period); `nocheck` turns off a synchroniser's timing checks;
`extra` adds delay to some of a chip's arcs, for example the time a bus
line takes to settle after the chip drives it; `pin_extra` (add_pin_delay)
delays everything one output pin drives, for example its wiring on a
routed board (infra/pcb/wires.py).

`include` copies another netlist into this one under a prefix, joining
the nets it names to this netlist's: that is how cards go into slots of a
backplane.

`section(name)` names the part of the design that the chips and gates
added after it belong to, until the next call: the sheets of a schematic
(schematic.py). Gates are recorded one by one in `gates`, since a package
can serve several sections. Neither goes into the simulator's export.
"""

from collections import defaultdict

from . import chips

GATE_SECTIONS = {
    "00": (4, 2), "02": (4, 2), "04": (6, 1), "08": (4, 2), "10": (3, 3),
    "21": (2, 4), "30": (1, 8), "32": (4, 2), "86": (4, 2),
    "05": (6, 1), "11": (3, 3), "14": (6, 1), "20": (2, 4), "27": (3, 3), "132": (4, 2),
}
# spare inputs of AND and NAND gates tie high, of OR, NOR and XOR low
TIE_HIGH = {"00", "08", "10", "11", "20", "21", "30", "132"}


class Instance:
    def __init__(self, nl, typ, ref, role=None, part=None, params=None, nocheck=False):
        self.nl = nl
        self.type = chips.TYPES[typ]
        self.ref = ref
        self.role = role
        self.part = part
        self.params = dict(params or {})
        self.nocheck = nocheck
        self.extra = {}             # delay name -> extra ps
        self.pin_extra = {}         # output pin -> extra ps (the wiring)
        self.conn = {}
        self.section = nl.current_section if nl else None

    def part_number(self, variant=chips.DEFAULT_VARIANT):
        return chips.part_number(variant, self.type.name, self.role, self.part)

    def add_delay(self, name, ps):
        """Lengthen one of the chip's delays (by name) by ps."""
        self.extra[name] = self.extra.get(name, 0) + ps

    def add_pin_delay(self, pin, ps):
        """Delay everything one output pin drives by ps: its wiring."""
        if pin not in self.type.pin_index:
            raise KeyError(f"{self.ref} ({self.type.name}) has no pin {pin}")
        self.pin_extra[pin] = self.pin_extra.get(pin, 0) + ps

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


class Gate:
    """One gate of a package: the package's reference, the section number
    in it, the gate type, its input pins and output pin, and the part of
    the design it belongs to."""

    def __init__(self, ref, sec, typ, inputs, output, section):
        self.ref, self.sec, self.typ = ref, sec, typ
        self.inputs, self.output, self.section = list(inputs), output, section


class Netlist:
    def __init__(self):
        self.instances = []
        self.refs = {}
        self.gate_pool = defaultdict(list)   # type -> [(instance, next free section)]
        self.counters = defaultdict(int)
        self.current_section = None
        self.gates = []          # every gate placed: Gate (package, section, inputs, output)
        self.sections = []       # (prefix of an included netlist or "", name), in order

    def section(self, name):
        """What follows belongs to this part of the design."""
        self.current_section = name
        if ("", name) not in self.sections:
            self.sections.append(("", name))

    def add(self, typ, ref=None, role=None, part=None, params=None, nocheck=False, **pins):
        if ref is None:
            self.counters[typ] += 1
            ref = f"U{typ}_{self.counters[typ]}"
        if ref in self.refs:
            raise ValueError(f"duplicate reference {ref}")
        inst = Instance(self, typ, ref, role, part, params, nocheck)
        self.instances.append(inst)
        self.refs[ref] = inst
        inst.connect(**pins)
        return inst

    def gate(self, typ, inputs, output, part=None):
        """Place one gate of a 74xx package, reusing free sections of a
        package of the same part."""
        n_sec, n_in = GATE_SECTIONS[typ]
        inputs = list(inputs)
        if len(inputs) > n_in:
            raise ValueError(f"{typ} gate has {n_in} inputs, got {len(inputs)}")
        while len(inputs) < n_in:
            inputs.append("VCC" if typ in TIE_HIGH else "GND")
        pool = self.gate_pool[(typ, part)]
        if not pool or pool[-1][1] >= n_sec:
            pool.append([self.add(typ, part=part), 0])
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
        self.gates.append(Gate(inst.ref, sec, typ, names, out, self.current_section))
        return inst

    def finish(self):
        """Tie off unused gate sections so every input is driven."""
        for (typ, _), pool in self.gate_pool.items():
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
            for group in inst.type.tied:
                if len({inst.conn.get(p) for p in group}) > 1:
                    errors.append(f"{inst.ref} ({inst.type.name}): {', '.join(group)} "
                                  f"must be on one net")
        for net, conns in self.nets().items():
            drivers = [c for c in conns if c[2] in ("out", "tri", "io")]
            hard = [c for c in conns if c[2] == "out"]
            if net in ("GND", "VCC"):
                continue
            if not drivers and not any(c[2] == "pull" for c in conns):
                errors.append(f"net {net} has no driver (read by "
                              f"{', '.join(f'{i.ref}.{p}' for i, p, _ in conns)})")
            elif len(hard) > 1 or (hard and len(drivers) > 1):
                errors.append(f"net {net} has conflicting drivers: "
                              f"{', '.join(f'{i.ref}.{p}' for i, p, _ in drivers)}")
        if errors:
            raise ValueError("netlist errors:\n  " + "\n  ".join(errors[:40]))

    def export(self, variant=chips.DEFAULT_VARIANT, corner="max", extra=None):
        """JSON-able dict for the chip-level simulator (infra/hwsim)."""
        timing = chips.load_timing()
        net_ids = {}
        for inst in self.instances:
            for net in inst.conn.values():
                net_ids.setdefault(net, len(net_ids))
        out_chips = []
        for inst in self.instances:
            t = inst.type
            part = inst.part_number(variant)
            if t.family in chips.UNTIMED or (t.family == "device" and part not in timing):
                delays = {}
            else:
                delays = chips.delays_for(timing, part, corner)
            for name, ps in inst.extra.items():
                if name not in delays and chips.DELAY_FALLBACK.get(name) in delays:
                    delays[name] = delays[chips.DELAY_FALLBACK[name]]
                if name not in delays:
                    raise KeyError(f"{inst.ref} ({part}) has no delay {name!r} to lengthen")
                delays[name] += ps
            out_chips.append({
                "ref": inst.ref, "type": t.name, "model": t.model, "part": part,
                "pins": [p for p, _ in t.pins],
                "kinds": [k for _, k in t.pins],
                "nets": [net_ids.get(inst.conn.get(p), -1) for p, _ in t.pins],
                "delays": delays,
                "params": {k: int(v) for k, v in inst.params.items()},
                "nocheck": inst.nocheck,
                **({"pin_delays": [int(inst.pin_extra.get(p, 0)) for p, _ in t.pins]}
                   if inst.pin_extra else {}),
            })
        nets = [None] * len(net_ids)
        for n, i in net_ids.items():
            nets[i] = n
        d = {"nets": nets, "chips": out_chips, "variant": variant, "corner": corner}
        if extra:
            d.update(extra)
        return d

    def bom(self, variant=chips.DEFAULT_VARIANT, passives=False):
        """{part number: [references]}: the chips (and with passives=True
        the resistor networks too), without test fixtures. A part placed as
        halves lists each half."""
        counts = defaultdict(list)
        for inst in self.instances:
            if inst.type.family == "fixture" or (inst.type.family == "passive" and not passives):
                continue
            counts[inst.part_number(variant)].append(inst.ref)
        return dict(sorted(counts.items()))

    def packages(self, variant=chips.DEFAULT_VARIANT, passives=False):
        """{part number: packages}: bom()'s, with the halves of a part
        placed as halves paired up."""
        per = {}
        for inst in self.instances:
            per[inst.part_number(variant)] = inst.type.per_package
        return {p: -(-len(refs) // per[p]) for p, refs in self.bom(variant, passives).items()}

    # ---- composition ------------------------------------------------------

    def include(self, other, prefix, connect):
        """Copy `other` into this netlist: its chips become prefix.REF and
        its nets prefix.NET, except the rails and the nets in `connect`,
        which become connect[net] (this netlist's net). Returns the copies
        by their original reference."""
        def rename(net):
            if net in ("GND", "VCC"):
                return net
            if net in connect:
                return connect[net]
            return f"{prefix}.{net}"
        copies = {}
        for inst in other.instances:
            ref = f"{prefix}.{inst.ref}"
            if ref in self.refs:
                raise ValueError(f"duplicate reference {ref}")
            new = Instance(self, inst.type.name, ref, inst.role, inst.part, inst.params,
                           inst.nocheck)
            new.extra = dict(inst.extra)
            new.pin_extra = dict(inst.pin_extra)
            new.conn = {p: rename(n) for p, n in inst.conn.items()}
            new.section = inst.section
            new.card = prefix
            self.instances.append(new)
            self.refs[ref] = new
            copies[inst.ref] = new
        for g in other.gates:
            self.gates.append(Gate(f"{prefix}.{g.ref}", g.sec, g.typ, g.inputs, g.output,
                                   g.section))
        for p, name in other.sections:
            key = (f"{prefix}.{p}" if p else prefix, name)
            if key not in self.sections:
                self.sections.append(key)
        return copies
