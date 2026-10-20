"""Symbolic simulation of a chip-level netlist, a clock cycle at a time.

The netlist is the one the chip-level simulator runs (infra/hw/netlist.py);
this runs it with values that may be symbolic (logic.py), at the level of
clock cycles rather than events: no delays, every edge-triggered part
clocked by CLK. A cycle has two phases:

  - the write window (the clock fixture's WEWIN high): a static RAM whose
    write enable is low writes what its data pins carry;
  - the end of the cycle (WEWIN low again, the RAMs' new contents showing):
    every edge-triggered part takes its next state from its inputs.

Nets are evaluated on demand, and the models ask for an input only when
they need it: a multiplexer with a known select reads only the input it
selects, a three-state driver's data is read only if it may be enabled. So
the control signals, which come from ROMs with known contents, stay known,
and a loop in the netlist that the control signals break is never entered.

A ROM's address must be known. When a symbolic bit reaches one, the cycle
stops with Split(bit): the caller decides the bit (adds a fact) and runs the
cycle again. That is where a symbolic run branches.

A net with several three-state drivers takes the value of the one that is
enabled. Two that may be enabled at once are a contention: known, it's an
error; symbolic, it's an obligation for the caller to prove impossible.
No driver enabled leaves the net floating: a fresh variable each time,
so whatever depends on it can't be proven (or 1, with a pull-up).
"""

import z3

from .logic import AND, ITE, NOT, OR, XOR, bits, bits_value, const_value, is_known, word


class SimError(Exception):
    pass


class Split(Exception):
    """A symbolic bit where a known one is needed."""

    def __init__(self, bit, why):
        super().__init__(why)
        self.bit, self.why = bit, why


class CombLoop(SimError):
    pass


# ---------------------------------------------------------------- memories

class ConcMem:
    """A memory with known contents: a bytearray, and the writes of the
    cycle in progress on top of it."""

    def __init__(self, data, width=8, pending=None):
        self.data, self.width = data, width
        self.pending = pending or {}

    def read(self, addr):
        a = bits_value([const_value(b) for b in addr])
        if a is None:
            raise SimError("symbolic address into a memory with known contents")
        v = self.pending.get(a)
        if v is None:
            v = self.data[a]
        return bits(v, self.width)

    def write(self, addr, data, cond):
        if cond is False:
            return self
        cond = const_value(cond)
        if cond is False:
            return self
        a = bits_value([const_value(b) for b in addr])
        v = bits_value([const_value(b) for b in data])
        if cond is not True or a is None or v is None:
            raise SimError("symbolic write into a memory with known contents")
        return ConcMem(self.data, self.width, {**self.pending, a: v})

    def commit(self):
        for a, v in self.pending.items():
            self.data[a] = v
        return ConcMem(self.data, self.width)


class SymMem:
    """A memory as a z3 array from addresses to words."""

    def __init__(self, array):
        self.array = array

    def read(self, addr):
        a = word(addr)
        return bits(z3.simplify(z3.Select(self.array, a)))

    def write(self, addr, data, cond):
        if cond is False:
            return self
        a, d = word(addr), word(data)
        if cond is not True:
            d = z3.If(cond, d, z3.Select(self.array, a))
        return SymMem(z3.Store(self.array, a, d))

    def commit(self):
        return self


# ---------------------------------------------------------------- the models

class Model:
    """A chip. `drive(pin)` is an output's value; `enable(pin)` whether a
    three-state output drives (True for the others). Sequential parts
    have `next()`, which reads the inputs at the end of the cycle and
    returns a function that makes the new state current."""

    seq = False

    def __init__(self, sim, inst):
        self.sim, self.inst, self.conn = sim, inst, inst.conn

    def get(self, pin):
        net = self.conn.get(pin)
        if net is None:
            raise SimError(f"{self.inst.ref}.{pin} is unconnected")
        if self.sim.reads is not None:
            self.sim.reads.add((self.inst.ref, pin))
        return self.sim.value(net)

    def enable(self, pin):
        return True

    def drive(self, pin):
        raise NotImplementedError(f"{self.inst.type.model}.{pin}")

    def concrete(self, x, why):
        return self.sim.concrete(x, f"{self.inst.ref}: {why}")

    def init_state(self, q):
        """Initial state from {output pin: bit}; missing pins are fresh."""


class Gate(Model):
    FN = {
        "nand": lambda xs: NOT(AND(*xs)), "and": lambda xs: AND(*xs),
        "nor": lambda xs: NOT(OR(*xs)), "or": lambda xs: OR(*xs),
        "xor": lambda xs: XOR(xs[0], xs[1]),
    }

    def __init__(self, sim, inst):
        super().__init__(sim, inst)
        self.fn = self.FN[inst.type.model]
        pins = inst.type.pins
        self.ins = {}
        for p, k in pins:
            if k in ("out", "tri"):
                pre = p[:-1]                 # "1Y" -> "1", "Y" -> ""
                self.ins[p] = [q for q, kq in pins if kq == "in" and q[:len(pre)] == pre
                               and (pre or True)]

    def drive(self, pin):
        ins = self.ins[pin]
        # a NAND/AND with a known 0 input (or OR/NOR with a 1) needn't read the rest
        model = self.inst.type.model
        dom = False if model in ("nand", "and") else True if model in ("nor", "or") else None
        vals = []
        if dom is not None:
            for p in ins:
                v = self.get(p)
                if v is dom:
                    return self.fn([v])
                vals.append(v)
            return self.fn(vals)
        return self.fn([self.get(p) for p in ins])


def _sel(model, pins):
    """A select value from pins, all of which must be known."""
    v = 0
    for i, p in enumerate(pins):
        b = model.get(p)
        if not is_known(b):
            return None
        v |= b << i
    return v


def _mux(model, sel_pins, choose):
    """Multiplex: choose(i) gives input i's value. A symbolic select reads
    every input it might select."""
    s = _sel(model, sel_pins)
    if s is not None:
        return choose(s)
    sel = [model.get(p) for p in sel_pins]
    out = None
    for i in range(1 << len(sel_pins)):
        cond = AND(*[sel[k] if (i >> k) & 1 else NOT(sel[k]) for k in range(len(sel))])
        if cond is False:
            continue
        v = choose(i)
        out = v if out is None else ITE(cond, v, out)
    return out


class Mux151(Model):
    def drive(self, pin):
        g = self.get("G")
        y = AND(NOT(g), _mux(self, ("A", "B", "C"), lambda i: self.get(f"D{i}"))) \
            if g is not True else False
        return y if pin == "Y" else NOT(y)


class Mux153(Model):
    def drive(self, pin):
        sec = pin[0]
        g = self.get(f"{sec}G")
        if g is True:
            return False
        return AND(NOT(g), _mux(self, ("A", "B"), lambda i: self.get(f"{sec}C{i}")))


class Mux157(Model):
    def drive(self, pin):
        g = self.get("G")
        if g is True:
            return False
        n = pin[0]
        return AND(NOT(g), _mux(self, ("S",), lambda i: self.get(f"{n}{'AB'[i]}")))


class Dec138(Model):
    def drive(self, pin):
        i = int(pin[1:])
        en = AND(self.get("G1"), NOT(self.get("G2A")), NOT(self.get("G2B")))
        if en is False:
            return True
        hit = AND(*[self.get(p) if (i >> k) & 1 else NOT(self.get(p))
                    for k, p in enumerate(("A", "B", "C"))])
        return NOT(AND(en, hit))


class Cmp688(Model):
    def drive(self, pin):
        g = self.get("G")
        if g is True:
            return True
        eq = AND(*[XOR(self.get(f"P{i}"), NOT(self.get(f"Q{i}"))) for i in range(8)])
        return NOT(AND(NOT(g), eq))


class Buf541(Model):
    """541 (and the inverting 540): OE1 and OE2 low enable."""

    def enable(self, pin):
        return AND(NOT(self.get("OE1")), NOT(self.get("OE2")))

    def drive(self, pin):
        v = self.get("A" + pin[1:])
        return NOT(v) if self.inst.type.model == "buf540" else v


class Alu181(Model):
    """The 74181 with active-high data; CN and CN4 are active-low carries,
    P and G active low."""

    def _uv(self):
        if not hasattr(self, "_cache") or self._cache[0] != self.sim.stamp:
            s = [self.get(f"S{i}") for i in range(4)]
            u, v = [], []
            for i in range(4):
                a, b = self.get(f"A{i}"), self.get(f"B{i}")
                u.append(OR(a, AND(b, s[0]), AND(NOT(b), s[1])))
                v.append(OR(AND(a, NOT(b), s[2]), AND(a, b, s[3])))
            self._cache = (self.sim.stamp, u, v)
        return self._cache[1], self._cache[2]

    def drive(self, pin):
        u, v = self._uv()
        if pin == "P":
            return NOT(AND(*u))
        if pin == "G":
            return NOT(OR(v[3], AND(u[3], v[2]), AND(u[3], u[2], v[1]),
                          AND(u[3], u[2], u[1], v[0])))
        m = self.get("M")
        if pin.startswith("F") and m is True:
            i = int(pin[1:])
            return NOT(AND(u[i], NOT(v[i])))
        carry = NOT(self.get("CN"))
        f = []
        for i in range(4):
            h = AND(u[i], NOT(v[i]))
            f.append(ITE(m, NOT(h), XOR(h, carry)))
            carry = OR(v[i], AND(u[i], carry))
        if pin == "CN4":
            return NOT(carry)
        if pin == "AEQB":
            return AND(*f)
        return f[int(pin[1:])]


class Cla182(Model):
    def drive(self, pin):
        p = [NOT(self.get(f"P{i}")) for i in range(4)]
        g = [NOT(self.get(f"G{i}")) for i in range(4)]
        if pin == "P":
            return NOT(AND(*p))
        if pin == "G":
            return NOT(OR(g[3], AND(p[3], g[2]), AND(p[3], p[2], g[1]),
                          AND(p[3], p[2], p[1], g[0])))
        c = NOT(self.get("CN"))
        for i, name in enumerate(("CNX", "CNY", "CNZ")):
            c = OR(g[i], AND(p[i], c))
            if pin == name:
                return NOT(c)
        raise SimError(pin)


class Const(Model):
    def drive(self, pin):
        return pin == "HI"


class Rom(Model):
    """A ROM with known contents (bytes). Its address must be known."""

    def __init__(self, sim, inst):
        super().__init__(sim, inst)
        self.data = sim.roms.get(inst.ref)
        if self.data is None:
            raise SimError(f"no contents for ROM {inst.ref}")
        self.na = sum(1 for p, _ in inst.type.pins if p.startswith("A") and p[1:].isdigit())

    def enable(self, pin):
        return AND(NOT(self.get("CE")), NOT(self.get("OE")))

    def drive(self, pin):
        stamp = self.sim.stamp
        if getattr(self, "_at", None) != stamp:
            a = 0
            for i in range(self.na):
                a |= self.concrete(self.get(f"A{i}"), f"address bit {i}") << i
            self._at, self._val = stamp, self.data[a]
        return bool((self._val >> int(pin[1:])) & 1)


class Sram(Model):
    """A static RAM: reads while CE and OE are low and WE high; writes the
    data pins at the end of the write window if WE and CE are low."""

    def __init__(self, sim, inst):
        super().__init__(sim, inst)
        self.na = sum(1 for p, _ in inst.type.pins if p.startswith("A") and p[1:].isdigit())
        self.mem = None              # set by the caller: ConcMem or SymMem
        self.next_mem = None

    def addr(self):
        return [self.get(f"A{i}") for i in range(self.na)]

    def enable(self, pin):
        return AND(NOT(self.get("CE")), NOT(self.get("OE")), self.get("WE"))

    def drive(self, pin):
        stamp = self.sim.stamp
        if getattr(self, "_at", None) != stamp:
            mem = self.next_mem if self.sim.phase == "end" and self.next_mem else self.mem
            self._at, self._val = stamp, mem.read(self.addr())
        return self._val[int(pin[2:])]

    def write_phase(self):
        we = AND(NOT(self.get("WE")), NOT(self.get("CE")))
        if we is False:
            self.next_mem = self.mem
            return
        data = [self.get(f"IO{i}") for i in range(8)]
        self.next_mem = self.mem.write(self.addr(), data, we)

    def commit_write(self):
        if self.next_mem is not None:
            self.mem = self.next_mem.commit()
        self.next_mem = None


class Seq(Model):
    """An edge-triggered part: state is {output pin: bit}."""
    seq = True
    STATE = ()

    def __init__(self, sim, inst):
        super().__init__(sim, inst)
        self.q = {}

    def init_state(self, q):
        for p in self.STATE:
            if p in q:
                self.q[p] = q[p]
            else:
                self.q[p] = self.sim.fresh(f"{self.inst.ref}.{p}")

    def drive(self, pin):
        return self.q[pin]


class Reg377(Seq):
    STATE = tuple(f"Q{i}" for i in range(1, 9))

    def next(self):
        en = NOT(self.get("EN"))
        if en is False:
            return None
        new = {f"Q{i}": ITE(en, self.get(f"D{i}"), self.q[f"Q{i}"])
               for i in range(1, 9) if f"Q{i}" in self.conn}
        return lambda: self.q.update(new)


class Dff175(Seq):
    STATE = tuple(f"{i}Q" for i in range(1, 5))

    def drive(self, pin):
        clr = self.get("CLR")
        q = AND(self.q[pin[0] + "Q"], clr)
        return NOT(q) if pin.endswith("QN") else q

    def next(self):
        clr = self.get("CLR")
        new = {f"{i}Q": AND(clr, self.get(f"{i}D")) for i in range(1, 5)
               if f"{i}Q" in self.conn or f"{i}QN" in self.conn}
        return lambda: self.q.update(new)


class Dff74(Seq):
    STATE = ("1Q", "2Q")

    def drive(self, pin):
        s = pin[0]
        pre, clr = self.get(f"{s}PRE"), self.get(f"{s}CLR")
        q = ITE(AND(NOT(pre), NOT(clr)), True, OR(NOT(pre), AND(clr, self.q[s + "Q"])))
        if pin.endswith("QN"):
            return ITE(AND(NOT(pre), NOT(clr)), True, NOT(q))
        return q

    def next(self):
        new = {}
        for s in "12":
            if self.conn.get(f"{s}CLK") != "CLK":
                continue
            if f"{s}Q" not in self.conn and f"{s}QN" not in self.conn:
                continue
            pre, clr = self.get(f"{s}PRE"), self.get(f"{s}CLR")
            new[s + "Q"] = ITE(NOT(clr), False, ITE(NOT(pre), True, self.get(f"{s}D")))
        return lambda: self.q.update(new)


class Counter(Seq):
    """161 (asynchronous clear) and 163 (synchronous clear)."""
    STATE = ("QA", "QB", "QC", "QD")

    def drive(self, pin):
        if pin == "RCO":
            return AND(self.get("ENT"), *[self.q[p] for p in self.STATE])
        q = self.q[pin]
        if self.inst.type.model == "cnt161":
            q = AND(self.get("CLR"), q)
        return q

    def next(self):
        clr, load = self.get("CLR"), self.get("LOAD")
        if clr is True and load is True:
            en = AND(self.get("ENP"), self.get("ENT"))
            if en is False:
                return None
        else:
            en = AND(self.get("ENP"), self.get("ENT")) if load is not False else False
        q = [self.q[p] for p in self.STATE]
        inc, carry = [], True
        for b in q:
            inc.append(XOR(b, carry))
            carry = AND(carry, b)
        new = {}
        for i, (p, d) in enumerate(zip(self.STATE, "ABCD")):
            v = ITE(en, inc[i], q[i])
            if load is not True:
                v = ITE(NOT(load), self.get(d), v)
            new[p] = AND(clr, v)
        return lambda: self.q.update(new)


class Sr299(Seq):
    """74x299: S1 S0 = 00 hold, 01 shift toward Q7 (DS0 in), 10 toward Q0
    (DS7 in), 11 load from the I/O pins (which then don't drive)."""
    STATE = tuple(f"IO{i}" for i in range(8))

    def enable(self, pin):
        if pin.startswith("IO"):
            return AND(NOT(self.get("OE1")), NOT(self.get("OE2")),
                       NOT(AND(self.get("S0"), self.get("S1"))))
        return True

    def drive(self, pin):
        if pin == "Q0S":
            return self.q["IO0"]
        if pin == "Q7S":
            return self.q["IO7"]
        return self.q[pin]

    def next(self):
        s0, s1 = self.get("S0"), self.get("S1")
        if s0 is False and s1 is False:
            return None
        cur = [self.q[f"IO{i}"] for i in range(8)]

        def mode(m):
            if m == 0:
                return cur
            if m == 1:
                return [self.get("DS0")] + cur[:7]
            if m == 2:
                return cur[1:] + [self.get("DS7")]
            return [self.get(f"IO{i}") for i in range(8)]
        m = _sel(self, ("S0", "S1"))
        if m is not None:
            nx = mode(m)
        else:
            nx = [_mux(self, ("S0", "S1"), lambda k, i=i: mode(k)[i]) for i in range(8)]
        new = {f"IO{i}": AND(self.get("MR"), nx[i]) for i in range(8)}
        return lambda: self.q.update(new)


class ClockGen(Model):
    def drive(self, pin):
        if pin == "WEWIN":
            return self.sim.phase == "write"
        if pin == "RESET":
            return not self.sim.reset
        return True                         # CLK: the edge is implicit


MODELS = {
    "nand": Gate, "and": Gate, "nor": Gate, "or": Gate, "xor": Gate,
    "mux151": Mux151, "mux153": Mux153, "mux157": Mux157, "dec138": Dec138,
    "cmp688": Cmp688, "buf541": Buf541, "buf540": Buf541, "alu181": Alu181,
    "cla182": Cla182, "const": Const, "rom": Rom, "sram": Sram,
    "reg377": Reg377, "dff175": Dff175, "dff74": Dff74, "cnt161": Counter,
    "cnt163": Counter, "sr299": Sr299, "clockgen": ClockGen,
}


# ---------------------------------------------------------------- the simulator

_MISSING = object()


class Sim:
    """A netlist, its state, and one cycle at a time.

    roms: {ROM reference: bytes}; fixtures: {model name: class} for parts
    this module doesn't know (a design's I/O fixture). Before the first
    cycle, give every sequential part its state (init_state, or
    `set_nets`) and every RAM its memory (`mem`)."""

    def __init__(self, nl, roms, fixtures=None):
        self.nl, self.roms = nl, roms
        self.models = {}
        kinds = dict(MODELS, **(fixtures or {}))
        for inst in nl.instances:
            cls = kinds.get(inst.type.model)
            if cls is None:
                raise SimError(f"no model for {inst.type.model} ({inst.ref})")
            self.models[inst.ref] = cls(self, inst)
        self.drivers, self.pulled, self.driver_of = {}, set(), {}
        for net, conns in nl.nets().items():
            ds = []
            for inst, pin, kind in conns:
                if kind in ("out", "tri", "io"):
                    ds.append((self.models[inst.ref], pin, kind))
                    self.driver_of[net] = (inst.ref, pin)
                elif kind == "pull":
                    self.pulled.add(net)
            self.drivers[net] = ds
        self.seq = [m for m in self.models.values() if m.seq]
        self.writers = [m for m in self.models.values() if hasattr(m, "write_phase")]
        self.cycle = 0
        self.phase = None
        self.reset = False
        self.stamp = 0
        self.facts = {}              # z3 term id -> bool: decided splits
        self.reads = None            # if a set: every (part, input pin) read
        self.obligations = []        # (what, term that must be false)
        self.fresh_count = 0

    # ---- values -------------------------------------------------------

    def fresh(self, name):
        return z3.Bool(name)

    def concrete(self, x, why):
        if is_known(x):
            return x
        v = self.facts.get(x.get_id())
        if v is not None:
            return v
        raise Split(x, why)

    def value(self, net):
        if net == "GND":
            return False
        if net == "VCC":
            return True
        v = self.memo.get(net, _MISSING)
        if v is not _MISSING:
            if v is _BUSY:
                raise CombLoop(f"combinational loop through {net} in cycle {self.cycle}")
            return v
        self.memo[net] = _BUSY
        v = self.resolve(net)
        self.memo[net] = v
        return v

    def resolve(self, net):
        ds = self.drivers.get(net)
        if not ds:
            raise SimError(f"net {net} has no driver")
        if len(ds) == 1 and ds[0][2] == "out":
            return ds[0][0].drive(ds[0][1])
        live = []
        for m, pin, _ in ds:
            en = m.enable(pin)
            if en is not False:
                live.append((m, pin, en))
        for i in range(len(live)):
            for j in range(i + 1, len(live)):
                both = AND(live[i][2], live[j][2])
                if both is not False:
                    what = (f"contention on {net} in cycle {self.cycle} ({self.phase}): "
                            f"{live[i][0].inst.ref}.{live[i][1]} and "
                            f"{live[j][0].inst.ref}.{live[j][1]}")
                    if both is True:
                        raise SimError(what)
                    self.obligations.append((what, both))
        if len(live) == 1 and live[0][2] is True:
            return live[0][0].drive(live[0][1])
        out = True if net in self.pulled else self.fresh(f"float.{net}.{self.cycle}.{self.phase}")
        for m, pin, en in reversed(live):
            out = ITE(en, m.drive(pin), out)
        return out

    def bus(self, name, n, start=0):
        return [self.value(f"{name}{i}") for i in range(start, start + n)]

    # ---- state --------------------------------------------------------

    def set_nets(self, values):
        """Initial state of sequential parts by the nets their outputs
        drive: {net: bit}. Parts not named get fresh variables."""
        per = {}
        for net, v in values.items():
            ref, pin = self.driver_of[net]
            m = self.models[ref]
            if isinstance(m, (Dff175, Dff74)) and pin.endswith("QN"):
                pin, v = pin[:-1], NOT(v)
            per.setdefault(ref, {})[pin] = v
        for m in self.seq:
            m.init_state(per.get(m.inst.ref, {}))

    def state_nets(self, nets):
        """The current value of nets driven by sequential parts' state."""
        out = {}
        for net in nets:
            ref, pin = self.driver_of[net]
            out[net] = self.models[ref].q[pin]
        return out

    # ---- a cycle ------------------------------------------------------

    def _phase(self, name):
        self.phase = name
        self.stamp += 1
        self.memo = {}

    def step(self, skip=(), observe=None):
        """One clock cycle. `skip`: references of sequential parts that keep
        their state (the caller doesn't need it). `observe(sim)` is called
        at the end of the cycle, before the edge, to read nets. A Split
        leaves the state as it was, so the cycle can be run again."""
        self._phase("write")
        for m in self.writers:
            m.write_phase()
        self._phase("end")
        if observe is not None:
            observe(self)
        commits = []
        for m in self.seq:
            if m.inst.ref in skip:
                continue
            c = m.next()
            if c is not None:
                commits.append(c)
        for c in commits:
            c()
        for m in self.writers:
            m.commit_write()
        self.cycle += 1
        self.phase = None


_BUSY = object()
