"""Bus-functional models: scripted masters and slaves on the backplane, for
testing the backplane and the cards without a CPU (tests/test_bus.py).

A BFM card is a `vector` fixture (infra/hw/chips.py) clocked from its
slot's BCLK through a clock buffer, as a real card's logic would be. Its
script is a list of steps: what it drives in the clock after an edge, and
what it must have seen at an edge to move on (all of it at the same edge).
Its record is what it saw at every edge. Outputs come `DELAY_PS` after the
edge: a register, a driver and the bus's settling.

    m = Master("M7", slot=7)
    m.wait_reset()
    m.request()                       # REQ until GNT is seen
    m.read(0x10000010)                # an address clock and the data phase
    m.write(0x10000012, 0xBEEF)
    m.release()                       # REQ off; let go once GNT has gone
    out = run([m, Master("M0", 0, clock=True)], clocks=200)
    out.record("M7")                  # [{signal: value}] per edge
"""

from heron import native
from heron.infra.hw.netlist import Netlist

from . import backplane, bus, iocard, memcard

DELAY_PS = 20_000                     # register 7 ns, settling 13 ns
PERIOD_PS = 60_000                    # the bus clock

M_OUT = (["REQ_n", "START_n", "WRITE_n", "LOCK_n"] + [f"BE{i}_n" for i in range(4)]
         + [f"A{i}" for i in range(1, 32)] + [f"D{i}" for i in range(16)])
M_IN = (["GNT_n", "DPH_n", "RDY_n", "WAIT_n", "BERR_n", "W32_n", "RESET_n", "START_n", "LOCK_n",
         "REQ_n"] + [f"D{i}" for i in range(16)])
S_OUT = ["WAIT_n"]
S_IN = ["START_n", "A28", "A29", "A30", "A31", "SEL", "BERR_n", "RESET_n", "DPH_n"]
CONDS = 6
Z = None                              # a released pin


class Script:
    """A vector fixture's script and the card around it."""

    def __init__(self, name, slot, outs, ins, kind):
        self.name, self.slot, self.outs, self.ins, self.kind = name, slot, outs, ins, kind
        self.steps = []
        self.drive = {s: Z for s in outs}

    def step(self, until=None, **drive):
        """One step: change what's driven (signal=value, or Z to let go),
        and stay until every `until` {input: value} was seen at an edge."""
        self.drive.update(drive)
        conds = [1 + 2 * self.ins.index(s) + v for s, v in (until or {}).items()]
        if len(conds) > CONDS:
            raise ValueError("too many conditions in one step")
        self.steps.append(([2 if self.drive[s] is Z else self.drive[s] for s in self.outs],
                           conds + [0] * (CONDS - len(conds))))

    def wait_reset(self):
        self.step(until={"RESET_n": 1})

    def image(self):
        return bytes(b for outs, conds in self.steps for b in outs + conds)

    def card(self, clock=False):
        nl = Netlist()
        nl.add("const", "X_RAIL", LO="GND", HI="VCC")
        bus.strap_class(nl, self.kind)
        nl.add("clkdrv", "U_CK", part="CDC341", A="BUS.BCLK", Y1="MCK")
        v = nl.add("vector", "X_V", CLK="MCK",
                   params={"outs": len(self.outs), "ins": len(self.ins), "conds": CONDS,
                           "delay_ps": DELAY_PS})
        for i, s in enumerate(self.outs):
            v[f"O{i}"] = f"BUS.{s}"
        for i in range(48):
            v[f"I{i}"] = f"BUS.{self.ins[i]}" if i < len(self.ins) else "GND"
        if clock:
            nl.add("osc", "U_OSC", part="oscillator", OUT="BUS.CLKSRC",
                   params={"period_ps": PERIOD_PS})
        return bus.Card(self.name, nl)


class Master(Script):
    """A 16-bit master. Halfwords travel on D0-D15 with A1 picking the
    half; bytes on D0-D7 (even) or D8-D15 (odd)."""

    def __init__(self, name, slot, clock=False):
        super().__init__(name, slot, M_OUT, M_IN, "empty")
        self.clock = clock
        self.drive.update(REQ_n=1)

    def card(self):
        return super().card(clock=self.clock)

    def own(self):
        """Drive the owner's lines, idle."""
        d = dict(START_n=1, WRITE_n=1, LOCK_n=1, **{f"BE{i}_n": 1 for i in range(4)})
        d.update({f"A{i}": 0 for i in range(1, 32)})
        return d

    def request(self):
        """REQ until GNT is seen at an edge, with the owner's lines let go
        (a master that lost GNT mustn't drive them; one that kept it lets
        go for that clock, which the pull-ups cover). The next step drives
        them: a transfer's address clock, or an idle clock."""
        self.step(until={"GNT_n": 0}, REQ_n=0, **{s: Z for s in self.outs if s != "REQ_n"})

    def lock(self):
        """An idle clock with LOCK asserted, before a locked sequence (RFC
        0014 section 7.3)."""
        d = self.own()
        d["LOCK_n"] = 0
        self.step(**d)

    def transfer(self, addr, write=False, data=0, size=2, end="rdy", lock=False):
        """An address clock, then the data phase until it ends: RDY without
        WAIT (end="rdy"), or BERR (end="berr")."""
        a = {f"A{i}": (addr >> i) & 1 for i in range(1, 32)}
        if size == 2:
            be = [0, 0, 1, 1]
        else:
            be = [addr & 1, (addr & 1) ^ 1, 1, 1]
        d = dict(self.own(), **a)
        d.update(WRITE_n=0 if write else 1, LOCK_n=0 if lock else 1,
                 **{f"BE{i}_n": be[i] for i in range(4)})
        d["START_n"] = 0
        self.step(**d)
        dd = {f"D{i}": (data >> i) & 1 if write else Z for i in range(16)}
        until = {"RDY_n": 0, "WAIT_n": 1} if end == "rdy" else {"BERR_n": 0}
        self.step(until=until, START_n=1, **dd)
        # D is let go just after the end
        self.drive.update({f"D{i}": Z for i in range(16)})

    def read(self, addr, **kw):
        self.transfer(addr, **kw)

    def write(self, addr, data, **kw):
        self.transfer(addr, write=True, data=data, **kw)

    def idle(self, clocks=1, **drive):
        for _ in range(clocks):
            self.step(**drive)

    def release(self):
        """REQ off; keep the owner's lines until GNT is seen gone, then let
        go of them."""
        self.step(until={"GNT_n": 1}, REQ_n=1, LOCK_n=1)
        self.step(**{s: Z for s in self.outs if s != "REQ_n"})


class WaitSlave(Script):
    """A fast card that holds WAIT from its first data clock until BERR:
    a broken card, for the bus monitor."""

    def __init__(self, name, slot):
        super().__init__(name, slot, S_OUT, S_IN, "fast16")
        mine = {f"A{28 + i}": (slot >> i) & 1 for i in range(4)}
        self.wait_reset()
        self.step(until=dict(START_n=0, **mine))
        self.step(until={"BERR_n": 0}, WAIT_n=0)
        self.step(WAIT_n=1)
        self.step(WAIT_n=Z)


class Outcome:
    def __init__(self, scripts, hw):
        self.hw = hw
        self._scripts = {s.name: s for s in scripts}

    def record(self, name):
        """What a BFM saw at each edge: [{signal: value}]."""
        s = self._scripts[name]
        raw = self.hw["dumps"][f"{name}.X_V"]
        n = len(s.ins)
        return [dict(zip(s.ins, raw[i:i + n])) for i in range(0, len(raw), n)]

    def probe(self):
        return self.hw["probe"]


def system(scripts, cards=("MEM", "IO"), n_simple=6):
    """The backplane with the BFMs and the real cards (the memory card in
    slot 1, the I/O card in slot 15)."""
    slots = {s.slot: s.card() for s in scripts}
    if "MEM" in cards:
        slots[1] = memcard.build()
    if "IO" in cards:
        slots[15] = iocard.build()
    return bus.compose(backplane.build(n_simple, por_ps=300_000), slots)


def run(scripts, clocks, probe=(), cards=("MEM", "IO"), n_simple=6, seed=1):
    """Run the BFMs for some bus clocks after reset."""
    nl = system(scripts, cards, n_simple)
    cfg = {"seed": seed, "max_cycles": clocks, "clock_net": "BP.CK", "reset_net": "RESET_n",
           "fetch_net": "VCC", "fetch_level": 1,
           "dump": [f"{s.name}.X_V" for s in scripts]}
    if probe:
        cfg.update(probe=list(probe), probe_from_ps=0, probe_to_ps=10**15)
    pre = {f"{s.name}.X_V": s.image() for s in scripts}
    if "IO" in cards:
        pre["IO.U_UART"] = b""
        pre["IO.U_CF"] = bytes(512 * 2048)
    return Outcome(scripts, native.hwsim.run_system(nl.export(), cfg, pre))
