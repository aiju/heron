"""The draft 1b hardware (studies/v1b_hw) under symbolic simulation.

The netlist, its ROM images, a model of the I/O page fixture, and the
machine's state by name: the registers as the nets their flip-flops
drive, the register file and the RAM as memories.
"""

import time
from collections import defaultdict

import z3

from heron.studies.v1b_hw import cpu, rtl
from heron.studies.v1b_hw import ucode as uc

from . import spec2 as S
from . import symsim
from .logic import AND, ITE, NOT, OR, bits, bits_value, boolterm, word

_cache = {}


def netlist():
    if "nl" not in _cache:
        _cache["nl"] = cpu.build()
    return _cache["nl"]


def microcode():
    if "mc" not in _cache:
        _cache["mc"] = uc.built()
    return _cache["mc"]


def roms():
    if "roms" not in _cache:
        uimgs, dimgs = uc.rom_images()
        r = {f"U_UC{k}": bytes(img) for k, img in enumerate(uimgs)}
        r.update({"U_DEC0": bytes(dimgs[0]), "U_DEC1": bytes(dimgs[1])})
        _cache["roms"] = r
    return _cache["roms"]


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


# The machine's registers, by the nets their flip-flops drive (least
# significant bit first). MQ lives in the 74HCT299s, whose pins aren't nets.
REGS = {
    "R": bus("RQ", 32), "T": bus("TQ", 32), "IR": bus("IR", 16),
    "MAR": bus("MAR", 20) + ["MAR31"], "PC": bus("PC", 31, 1), "LC": bus("LC", 8),
    "SX": bus("SX", 4), "LEN": ["LEN0", "LEN1"],
    "N": ["NFLAG"], "Z": ["ZFLAG"], "C": ["CFLAG"], "V": ["VFLAG"], "I": ["IFLAG"],
    "CL": ["CLQ"], "SGN": ["SGNQ"], "S33": ["S33Q"], "IRQS": ["IRQS"], "IRQP": ["IRQP"],
}
RF_CHIPS = {"A": [f"U_RFA{k}" for k in range(4)], "B": [f"U_RFB{k}" for k in range(4)]}
RAM_CHIPS = ("U_RAML", "U_RAMH")


def uir_nets():
    """The microinstruction register's outputs, by control word bit."""
    return cpu.control_nets()


def mq_bits(sim):
    """MQ's 32 bits from the 299s' state (chip k, I/O n = bit 8k + 7 - n)."""
    out = [None] * 32
    for k in range(4):
        q = sim.models[f"U_MQ{k}"].q
        for n in range(8):
            out[8 * k + 7 - n] = q[f"IO{n}"]
    return out


def set_mq(sim, mq):
    for k in range(4):
        sim.models[f"U_MQ{k}"].q.update({f"IO{n}": mq[8 * k + 7 - n] for n in range(8)})


def control_state(addr):
    """{uIR net: bit} for the control word at microcode ROM address addr."""
    nets = uir_nets()
    r = roms()
    out = {}
    for k in range(uc.ROMS):
        byte = r[f"U_UC{k}"][addr]
        for i in range(8):
            bit = 8 * k + i
            if bit in nets:
                out[nets[bit]] = bool((byte >> i) & 1)
    return out


# ---------------------------------------------------------------- the I/O page

class IoPage(symsim.Model):
    """The iodev32 fixture: the I/O page on the data bus. With a device
    (rtl.IODev) it plays it; without, reads are unknown, writes and IRQ
    nothing, and any access an obligation (the specification leaves the I/O
    page out)."""

    seq = True
    STATE = ()

    def __init__(self, sim, inst):
        super().__init__(sim, inst)
        self.dev = None
        self.q = {}
        self._read = (None, None)

    def init_state(self, q):
        pass

    def selected(self):
        return NOT(self.get("IOSEL"))

    def enable(self, pin):
        if pin == "IRQ":
            return True
        return AND(self.selected(), NOT(self.get("RD")))

    def addr(self):
        return [self.get(f"A{i}") for i in range(8)]

    def drive(self, pin):
        if pin == "IRQ":
            return bool(self.dev.flag) if self.dev else False
        if self.dev is None:
            return self.sim.fresh(f"io.{pin}.{self.sim.cycle}")
        if self._read[0] != self.sim.cycle:
            a = bits_value(self.addr())
            self._read = (self.sim.cycle, self.dev.read(a, self.sim.cycle))
        return bool((self._read[1] >> int(pin[1:])) & 1)

    def write_phase(self):
        lanes = (NOT(self.get("WEL")), NOT(self.get("WEH")))
        sel = self.selected()
        if self.dev is None:
            acc = AND(sel, OR(lanes[0], lanes[1], NOT(self.get("RD"))))
            if acc is not False:
                self.sim.obligations.append((f"I/O page access in cycle {self.sim.cycle}", acc))
            return
        if sel is True and (lanes[0] or lanes[1]):
            d = bits_value([self.get(f"D{i}") for i in range(16)])
            self._write = (bits_value(self.addr()), d, lanes[0] | lanes[1] << 1)
        else:
            self._write = None

    def commit_write(self):
        if self.dev is not None and getattr(self, "_write", None):
            self.dev.write(*self._write)
        self._write = None

    def next(self):
        if self.dev is None:
            return None
        return self.dev.tick


FIXTURES = {"iodev32": IoPage}


def new_sim():
    return symsim.Sim(netlist(), roms(), FIXTURES)


# ---------------------------------------------------------------- a concrete machine

def concrete(img, inp=b""):
    """The netlist at the start of the reset routine, with known values: a
    program image in RAM, the registers cleared, the I/O page played by the
    RTL model's device. As rtl.RTL starts."""
    sim = new_sim()
    ctl = control_state(0)
    state = {net: False for nets in REGS.values() for net in nets}
    state.update(ctl)
    sim.set_nets(state)
    for m in sim.seq:                       # anything left over: cleared
        for p in list(m.q):
            if not isinstance(m.q[p], bool):
                m.q[p] = False
    for chips in RF_CHIPS.values():
        for ref in chips:
            sim.models[ref].mem = symsim.ConcMem(bytearray(1 << 15))
    lo, hi = bytearray(1 << 19), bytearray(1 << 19)
    for a, b in img.mem.items():
        if a < (1 << 20):
            (hi if a & 1 else lo)[a >> 1] = b
    sim.models["U_RAML"].mem = symsim.ConcMem(lo)
    sim.models["U_RAMH"].mem = symsim.ConcMem(hi)
    sim.models["X_IO"].dev = rtl.IODev(inp)
    return sim


def read_regs(sim):
    """The registers' current values as ints (known state only)."""
    out = {}
    for name, nets in REGS.items():
        st = sim.state_nets(nets)
        out[name] = bits_value([st[n] for n in nets])
    out["PC"] = out["PC"] << 1
    mar = out["MAR"]
    out["MAR"] = (mar & 0xFFFFF) | ((mar >> 20) << 31)
    out["MQ"] = bits_value(mq_bits(sim))
    return out


def read_rf(sim, side="A"):
    mems = [sim.models[r].mem for r in RF_CHIPS[side]]
    return [sum(m.data[i] << (8 * k) for k, m in enumerate(mems)) for i in range(32)]


def read_symbolic_rf(sim, side="A"):
    """The register file's 32 entries as 32-bit terms."""
    mems = [sim.models[r].mem for r in RF_CHIPS[side]]
    out = []
    for i in range(32):
        lanes = [m.read(bits(i, 15)) for m in mems]
        out.append(word([b for lane in lanes for b in lane]))
    return out



# ================================================================ the proof
#
# The commuting diagram, one instruction at a time. The abstraction of
# the hardware's state at an instruction boundary, just after the clock
# edge that ends a decode cycle (SEQ = decode, LDIR):
#
#   - uIR holds the control word at the routine the decode ROM gave for
#     IR, LEN its length, SX = IR[7:4];
#   - IR is the parcel at the specification's pc, the hardware's PC is
#     pc + 2;
#   - register file entries 0-15 are r0-r15 (r0 = 0), 16 is HI, 24 and 25
#     hold the loop counts 0xE1 and 0xE0 (sign-extended), in both copies;
#   - the flags are the specification's, no interrupt is pending;
#   - the RAM is the specification's memory (mirrored every 1 MB);
#   - R, T, MAR, MQ, LC, CL, SGN, S33 and the other register file entries
#     are anything.
#
# From such a state, with everything symbolic, the hardware runs to the
# next decode edge, splitting where a symbolic bit reaches the control
# store's address; the specification runs one instruction. Each path must
# end in a state the abstraction maps to the specification's.

BV = z3.BitVecSort
# The loop counts in register file entries 24 and 25, as the reset routine
# writes them: as signed bytes, so sign-extended (only the low byte is used).
RF_CONSTS = {loc: (val - 256 if val > 127 else val) & 0xFFFFFFFF
             for loc, val in uc.RF_CONSTS.items()}


class Case:
    """A routine of the decode ROM and the first parcels that select it: a
    cube (mask, value), and if the routine's parcels aren't all of the cube,
    the list of them."""

    def __init__(self, y, length, key, mask, value, members, sub=None):
        self.y, self.length, self.key = y, length, key
        self.mask, self.value, self.members = mask, value, members
        self.sub = sub               # for part of a routine's parcels: the opcode

    def by_opcode(self):
        """The case split by the parcel's top four bits, the major opcode:
        the parts that have parcels, each with its own membership."""
        out = []
        for op in range(16):
            ws = [w for w in (self.members or []) if w >> 12 == op]
            if not ws:
                continue
            a, o = 0xFFFF, 0
            for w in ws:
                a &= w
                o |= w
            mask = ~(a ^ o) & 0xFFFF
            exact = len(ws) == 1 << bin(~mask & 0xFFFF).count("1")
            out.append(Case(self.y, self.length, self.key, mask, a & mask,
                            None if exact else ws, sub=op))
        return out

    @property
    def free(self):
        return bin(~self.mask & 0xFFFF).count("1")

    def example(self):
        return self.value if self.members is None else self.members[0]

    def name(self):
        base = " ".join(str(k) for k in self.key)
        return base if self.sub is None else f"{base} op {self.sub:X}"


def cases():
    """Every decode case, in the order of the decode ROM's routines."""
    if "cases" in _cache:
        return _cache["cases"]
    mc = microcode()
    dec = mc.decode_rom()
    groups = defaultdict(list)
    for w in range(0x10000):
        groups[dec[w]].append(w)
    key_of = {mc.entry[k].addr: k for k in mc.entry}
    out = []
    for v, ws in sorted(groups.items()):
        a, o = 0xFFFF, 0
        for w in ws:
            a &= w
            o |= w
        mask = ~(a ^ o) & 0xFFFF
        exact = len(ws) == 1 << bin(~mask & 0xFFFF).count("1")
        y = v & ((1 << uc.Y_BITS) - 1)
        c = Case(y, v >> uc.Y_BITS, key_of[y], mask, a & mask, None if exact else ws)
        # the illegal routine serves parcels of every opcode: the
        # specification decodes those far more cheaply an opcode at a time
        out += c.by_opcode() if c.key == ("illegal",) else [c]
    _cache["cases"] = out
    return out


def member_term(ws, pbits):
    """The Boolean function 'the parcel is one of ws' over the parcel's bits
    (known ones fold away), by Shannon expansion with shared sub-tables."""
    table = 0
    for w in ws:
        table |= 1 << w
    memo = {}

    def build(level, t):
        if t == 0:
            return False
        if t == (1 << (1 << level)) - 1:
            return True
        key = (level, t)
        if key not in memo:
            half = 1 << (level - 1)
            memo[key] = ITE(pbits[level - 1], build(level - 1, t >> half),
                            build(level - 1, t & ((1 << half) - 1)))
        return memo[key]
    return build(16, table)


class SpecRegs:
    """The specification's r[0..15] on arrays shaped as the hardware's
    register file is (four byte lanes, 15-bit addresses), so that a register
    read on either side is the same term. Entry 0 holds 0 and is never
    written, which is how r0 reads as 0."""

    def __init__(self, lanes):
        self.lanes = list(lanes)

    @staticmethod
    def _index(i):
        if isinstance(i, int):
            return z3.BitVecVal(i, 15)
        return z3.simplify(z3.ZeroExt(15 - i.w, S.term(i)))

    def read(self, i):
        idx = self._index(i)
        return S.mk(32, z3.simplify(z3.Concat(*[z3.Select(a, idx) for a in reversed(self.lanes)])))

    def write(self, i, v, g):
        if g is False:
            return
        idx = self._index(i)
        cond = z3.simplify(z3.And(boolterm(g), idx != 0))
        if z3.is_false(cond):
            return
        x = S.term(v)
        for k, a in enumerate(self.lanes):
            d = z3.Extract(8 * k + 7, 8 * k, x)
            new = d if z3.is_true(cond) else z3.If(cond, d, z3.Select(a, idx))
            self.lanes[k] = z3.Store(a, idx, new)


def mar_form(t):
    """A 32-bit address as MAR holds it: bits 0-19 and 31, simplified."""
    return z3.simplify(z3.Concat(z3.Extract(31, 31, t), z3.Extract(19, 0, t)))


class SpecMem:
    """The specification's byte memory on the hardware's two RAM chips
    (even bytes in L, odd in H, at address bits 19-1)."""

    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi
        self.addrs = {}              # every address used, as MAR would hold it

    def _split(self, a):
        t = S.term(a)
        m = mar_form(t)
        if not z3.is_bv_value(m):
            self.addrs.setdefault(m.get_id(), m)
        return z3.simplify(z3.Extract(19, 1, m)), z3.simplify(z3.Extract(0, 0, m))

    def read(self, a):
        idx, lane = self._split(a)
        if z3.is_bv_value(lane):
            arr = self.hi if lane.as_long() else self.lo
            return S.mk(8, z3.simplify(z3.Select(arr, idx)))
        return S.mk(8, z3.simplify(z3.If(lane == 1, z3.Select(self.hi, idx),
                                           z3.Select(self.lo, idx))))

    def write(self, a, v, g):
        if g is False:
            return
        idx, lane = self._split(a)
        d = S.term(v)
        g = boolterm(g)
        for which, bit in (("lo", 0), ("hi", 1)):
            arr = getattr(self, which)
            cond = z3.simplify(z3.And(g, lane == bit))
            if z3.is_false(cond):
                continue
            new = d if z3.is_true(cond) else z3.If(cond, d, z3.Select(arr, idx))
            setattr(self, which, z3.Store(arr, idx, new))


def control_word(sim):
    """The uIR's control word (fields by name), from its state."""
    nets = uir_nets()
    st = sim.state_nets(list(nets.values()))
    word_ = 0
    for bit, net in nets.items():
        v = st[net]
        if v is not True and v is not False:
            raise symsim.SimError(f"uIR bit {net} is symbolic")
        word_ |= int(v) << bit
    return uc.unpack(word_)


UIR_REFS = tuple(f"U_UIR{k}" for k in range(uc.ROMS)) + ("U_IRX",)


class Result:
    def __init__(self, case):
        self.case = case
        self.paths = []          # (status, cycles, detail)
        self.seconds = 0.0
        self.error = None

    @property
    def status(self):
        if self.error:
            return "error"
        st = {p[0] for p in self.paths}
        for s in ("fail", "unknown", "limit"):
            if s in st:
                return s
        return "proved" if self.paths else "error"


class Prover:
    """One decode case: set up both sides, explore the hardware's paths,
    prove each."""

    def __init__(self, case, timeout_ms=120_000, max_cycles=400, verbose=False, cutpoints=True,
                 solve=True):
        self.case, self.timeout, self.max_cycles = case, timeout_ms, max_cycles
        self.cutpoints = cutpoints
        self.solve = solve           # False: explore the paths, prove nothing at their ends
        self.cuts = 0                # MAR values replaced by the specification's address
        self.verbose = verbose
        self.spec = S.load("v1b_new.isa")
        self.timings = []            # (goal, seconds, result) of every solver call at a path's end

    # ---- the starting state

    def setup(self):
        c = self.case
        pbits = [bool((c.value >> i) & 1) if (c.mask >> i) & 1 else z3.Bool(f"p{i}")
                 for i in range(16)]
        self.pbits = pbits
        self.hyps = []
        if c.members is not None:
            self.hyps.append(boolterm(member_term(c.members, pbits)))
        pc_hi = z3.BitVec("pc_hi", 31)
        self.pc0 = z3.Concat(pc_hi, z3.BitVecVal(0, 1))
        P = word(pbits)
        lo0 = z3.Array("ram_lo", BV(19), BV(8))
        hi0 = z3.Array("ram_hi", BV(19), BV(8))
        idx = z3.Extract(19, 1, self.pc0)
        self.lo0 = z3.Store(lo0, idx, z3.Extract(7, 0, P))
        self.hi0 = z3.Store(hi0, idx, z3.Extract(15, 8, P))
        self.r0 = [z3.BitVecVal(0, 32)] + [z3.BitVec(f"r{i}", 32) for i in range(1, 16)]
        self.hi_reg = z3.BitVec("hi", 32)
        self.flags0 = {f: z3.Bool(f) for f in "NZCVI"}

        lanes = []
        for k in range(4):
            arr = z3.Array(f"rf_junk{k}", BV(15), BV(8))
            entries = {i: self.r0[i] for i in range(16)}
            entries[uc.HI] = self.hi_reg
            entries.update({i: z3.BitVecVal(v, 32) for i, v in RF_CONSTS.items()})
            for i, v in entries.items():
                arr = z3.Store(arr, z3.BitVecVal(i, 15), z3.Extract(8 * k + 7, 8 * k, v))
            lanes.append(arr)

        # the specification
        self.sregs = SpecRegs(lanes)
        regs = {"r": self.sregs, "hi": S.mk(32, self.hi_reg), "pc": S.mk(32, self.pc0)}
        regs.update(self.flags0)
        self.smem = SpecMem(self.lo0, self.hi0)
        self.sst = S.State(self.spec, regs, {"mem": self.smem})
        self.run = self.spec.step(self.sst)
        self.hyps += [a for a, _ in self.run.assumptions]

        # the hardware
        sim = new_sim()
        state = control_state(c.y)
        state.update(zip(REGS["IR"], pbits))
        state.update(zip(REGS["SX"], pbits[4:8]))
        state.update(zip(REGS["LEN"], bits(c.length, 2)))
        pc2 = bits(z3.simplify(self.pc0 + 2))
        state.update(zip(REGS["PC"], pc2[1:]))
        for f in "NZCVI":
            state[REGS[f][0]] = self.flags0[f]
        state["IRQS"] = state["IRQP"] = False
        sim.set_nets(state)
        for k in range(4):
            for side in "AB":
                sim.models[RF_CHIPS[side][k]].mem = symsim.SymMem(lanes[k])
        sim.models["U_RAML"].mem = symsim.SymMem(self.lo0)
        sim.models["U_RAMH"].mem = symsim.SymMem(self.hi0)
        self.sim = sim

    # ---- solving

    def solver(self, path):
        s = z3.Solver()
        s.set("timeout", self.timeout)
        s.add(*self.hyps)
        s.add(*path)
        return s

    def possible(self, path, bit):
        s = self.solver(path)
        s.add(bit)
        r = s.check()
        return r != z3.unsat

    # ---- exploring

    def prove(self):
        res = Result(self.case)
        t0 = time.time()
        try:
            self.setup()
            self.explore(res)
        except (symsim.SimError, S.SpecError) as e:
            res.error = f"{type(e).__name__}: {e}"
        res.seconds = time.time() - t0
        return res

    def snapshot(self):
        sim = self.sim
        return (sim.cycle, {m.inst.ref: dict(m.q) for m in sim.seq},
                {m.inst.ref: m.mem for m in sim.models.values() if isinstance(m, symsim.Sram)},
                list(sim.obligations))

    def restore(self, snap):
        sim = self.sim
        sim.cycle = snap[0]
        for ref, q in snap[1].items():
            sim.models[ref].q = dict(q)
        for ref, mem in snap[2].items():
            sim.models[ref].mem = mem
        sim.obligations = list(snap[3])

    def explore(self, res):
        sim = self.sim
        stack = [(self.snapshot(), {}, [])]
        self._last_mar = None
        while stack:
            snap, facts, path = stack.pop()
            self.restore(snap)
            sim.facts = dict(facts)
            path = list(path)
            start = 0                   # the instruction began in cycle 0
            while True:
                if sim.cycle - start > self.max_cycles:
                    res.paths.append(("limit", sim.cycle - start, "no decode edge"))
                    break
                f = control_word(sim)
                ending = f["SEQ"] == uc.SEQ_DECODE and f["LDIR"] and not f["GOIRQ"]
                if f["HALT"]:
                    res.paths.append(self.check(path, sim.cycle - start, None, halted=True)
                                     if self.solve else ("explored", sim.cycle - start, ""))
                    break
                seen = {}
                try:
                    if ending:
                        sim.step(skip=UIR_REFS, observe=lambda s: seen.update(
                            fault=s.value("FAULT"), dbus=s.bus("DBUS", 16)))
                    else:
                        sim.step()
                except symsim.Split as sp:
                    bit = sp.bit
                    can1, can0 = self.possible(path, bit), self.possible(path, z3.Not(bit))
                    if can1 and can0:
                        alt = dict(sim.facts)
                        alt[bit.get_id()] = False
                        stack.append((self.snapshot(), alt, path + [z3.Not(bit)]))
                        sim.facts[bit.get_id()] = True
                        path.append(bit)
                        if self.verbose:
                            print(f"    split in cycle {sim.cycle - start}: {sp.why}")
                    elif can1 or can0:
                        sim.facts[bit.get_id()] = can1
                    else:
                        res.paths.append(("fail", sim.cycle - start, "a path with no way on"))
                        break
                    continue
                if ending:
                    res.paths.append(self.check(path, sim.cycle - start, seen) if self.solve
                                     else ("explored", sim.cycle - start, ""))
                    if self.verbose:
                        print(f"  path {len(res.paths)}: {res.paths[-1]}", flush=True)
                    break
                if self.cutpoints:
                    self.cut_mar(path)

    def cut_mar(self, path):
        """A cut-point: if MAR now holds a symbolic address the specification
        also uses, and the solver proves the two equal on this path, MAR
        takes the specification's term. Memory reads on both sides then
        index with the same term, and the solver needn't prove the ALU's
        address adder equal to the specification's for every access."""
        sim = self.sim
        nets = REGS["MAR"]
        st = sim.state_nets(nets)
        mbits = [st[n] for n in nets]
        if all(b is True or b is False for b in mbits):
            return
        hw = z3.simplify(word(mbits))          # bits 0-19 and 31, as mar_form
        if self._last_mar is not None and hw.eq(self._last_mar):
            return
        self._last_mar = hw
        for cand in self.smem.addrs.values():
            if cand.eq(hw):
                return
            s = self.solver(path)
            s.add(cand != hw)
            if s.check() == z3.unsat:
                for n, b in zip(nets, bits(cand)):
                    ref, pin = sim.driver_of[n]
                    sim.models[ref].q[pin] = b
                self._last_mar = z3.simplify(word(bits(cand)))
                self.cuts += 1
                return

    # ---- the end of a path

    def check(self, path, cycles, seen, halted=False):
        sim, st, run = self.sim, self.sst, self.run
        goals = []                   # (group, what, term)
        rf = {side: read_symbolic_rf(sim, side) for side in "AB"}
        for i in range(32):
            goals.append(("copies", f"register file copies differ at {i}", rf["A"][i] == rf["B"][i]))
        for i in range(1, 16):
            goals.append(("registers", f"r{i}", rf["A"][i] == S.term(self.sregs.read(i))))
        goals.append(("registers", "r0 = 0", rf["A"][0] == 0))
        goals.append(("registers", "HI", rf["A"][uc.HI] == S.term(st.regs["hi"])))
        for i, v in RF_CONSTS.items():
            goals.append(("registers", f"register file entry {i} = {v:#x}", rf["A"][i] == v))
        hw = sim.state_nets([REGS[f][0] for f in "NZCVI"])
        for f in "NZCVI":
            goals.append(("flags", f"flag {f}",
                          boolterm(hw[REGS[f][0]]) == boolterm(S.guard(st.regs[f]))))
        pc = S.term(st.regs["pc"])
        hpc = word([False] + [sim.state_nets([n])[n] for n in REGS["PC"]])
        lo, hi = sim.models["U_RAML"].mem.array, sim.models["U_RAMH"].mem.array
        goals.append(("memory", "RAM (even bytes)", lo == self.smem.lo))
        goals.append(("memory", "RAM (odd bytes)", hi == self.smem.hi))
        halt_g = boolterm(run.halt_g)
        if halted:
            goals.append(("control", "PC", hpc == pc))
            goals.append(("control", "the specification halts too", halt_g))
        else:
            goals.append(("control", "PC = pc + 2", hpc == pc + 2))
            ir = word([sim.state_nets([n])[n] for n in REGS["IR"]])
            idx = z3.Extract(19, 1, pc)
            goals.append(("control", "IR = the parcel at pc",
                          ir == z3.Concat(z3.Select(hi, idx), z3.Select(lo, idx))))
            goals.append(("control", "no address error in the decode cycle",
                          z3.Not(boolterm(seen["fault"]))))
            goals.append(("control", "the specification doesn't halt", z3.Not(halt_g)))
        seen_ob = set()
        for what, t in sim.obligations:
            if t.get_id() in seen_ob:
                continue
            seen_ob.add(t.get_id())
            goals.append(("obligations", what, z3.Not(boolterm(t))))
        return self.solve_goals(path, cycles, goals)

    def solve_goals(self, path, cycles, goals):
        """Prove the goals under the path, a group at a time (one query for
        all the registers lets the solver share the work); for a group that
        fails, the model says which of its goals do."""
        groups = {}
        for grp, what, g in goals:
            g = z3.simplify(g)
            if not z3.is_true(g):
                groups.setdefault(grp, []).append((what, g))
        s = None
        bad, unknown = [], []
        for grp, items in groups.items():
            if s is None:
                s = self.solver(path)
            s.push()
            s.add(z3.Not(z3.And(*[g for _, g in items])))
            t = time.time()
            r = s.check()
            self.timings.append((grp, time.time() - t, str(r)))
            if r == z3.sat:
                m = s.model()
                bad += [w for w, g in items if z3.is_false(m.eval(g, model_completion=True))]
            elif r == z3.unknown:
                unknown.append(grp)
            s.pop()
        if bad:
            return ("fail", cycles, "; ".join(bad[:6]))
        if unknown:
            return ("unknown", cycles, "; ".join(unknown))
        return ("proved", cycles, "")


def prove_case(case, **kw):
    return Prover(case, **kw).prove()


def pins_read(case, **kw):
    """The (part, input pin) pairs the hardware reads on any of a case's
    paths, unmutated. A change to the netlist that leaves all of them alone
    can't change the case: up to the first read of a changed pin the run is
    the same."""
    p = Prover(case, solve=False, cutpoints=False, **kw)
    p.setup()
    p.sim.reads = set()
    res = Result(case)
    p.explore(res)
    return p.sim.reads, res


# ---------------------------------------------------------------- reset

class ResetProver(Prover):
    """The base case: from reset to the first instruction boundary.

    The start is as the RTL model has it: reset just released, the reset
    routine's first control word in uIR, PC, I and the interrupt
    synchronisers cleared (they have RESET on their clears), and everything
    else anything at all, except that the register file's two copies hold
    the same (as the chip-level runs' cleared register files do; reset
    writes only r0, HI and the loop counts). The goal is the abstraction's
    invariant at the first decode edge, for the state the instruction-level
    simulator starts in: pc 0, flags 0, r0 and HI 0, r1-r15 whatever the
    register file held."""

    def __init__(self, **kw):
        super().__init__(None, cutpoints=False, **kw)        # no specification to cut to

    def setup(self):
        self.hyps = []
        sim = new_sim()
        state = control_state(0)
        state.update({n: False for n in REGS["PC"]})
        state.update({"IFLAG": False, "IRQS": False, "IRQP": False})
        sim.set_nets(state)
        self.lanes0 = [z3.Array(f"rf{k}", BV(15), BV(8)) for k in range(4)]
        for k in range(4):
            for side in "AB":
                sim.models[RF_CHIPS[side][k]].mem = symsim.SymMem(self.lanes0[k])
        self.lo0 = z3.Array("ram_lo", BV(19), BV(8))
        self.hi0 = z3.Array("ram_hi", BV(19), BV(8))
        sim.models["U_RAML"].mem = symsim.SymMem(self.lo0)
        sim.models["U_RAMH"].mem = symsim.SymMem(self.hi0)
        self.sim = sim

    def prove(self):
        res = Result(None)
        t0 = time.time()
        try:
            self.setup()
            self.explore(res)
        except (symsim.SimError, S.SpecError) as e:
            res.error = f"{type(e).__name__}: {e}"
        res.seconds = time.time() - t0
        return res

    def check(self, path, cycles, seen, halted=False):
        sim = self.sim
        goals = []
        rf = {side: read_symbolic_rf(sim, side) for side in "AB"}
        before = [z3.Concat(*[z3.Select(a, z3.BitVecVal(i, 15)) for a in reversed(self.lanes0)])
                  for i in range(32)]
        for i in range(32):
            goals.append((f"register file copies differ at {i}", rf["A"][i] == rf["B"][i]))
        want = {0: 0, uc.HI: 0, **RF_CONSTS}
        for i in range(32):
            if i in want:
                goals.append((f"register file entry {i} = {want[i]:#x}", rf["A"][i] == want[i]))
            elif i < 16:
                goals.append((f"r{i} kept", rf["A"][i] == before[i]))
        hw = sim.state_nets([REGS[f][0] for f in "NZCVI"])
        for f in "NZCVI":
            goals.append((f"flag {f} = 0", z3.Not(boolterm(hw[REGS[f][0]]))))
        hpc = word([False] + [sim.state_nets([n])[n] for n in REGS["PC"]])
        lo, hi = sim.models["U_RAML"].mem.array, sim.models["U_RAMH"].mem.array
        goals.append(("RAM unchanged (even bytes)", lo == self.lo0))
        goals.append(("RAM unchanged (odd bytes)", hi == self.hi0))
        if halted:
            goals.append(("no HALT", z3.BoolVal(False)))
        else:
            goals.append(("PC = 2", hpc == 2))
            ir = word([sim.state_nets([n])[n] for n in REGS["IR"]])
            zero = z3.BitVecVal(0, 19)
            goals.append(("IR = the parcel at 0", ir == z3.Concat(z3.Select(hi, zero), z3.Select(lo, zero))))
            goals.append(("no address error in the decode cycle", z3.Not(boolterm(seen["fault"]))))
        for what, t in sim.obligations:
            goals.append((what, z3.Not(boolterm(t))))
        return self.solve_goals(path, cycles, [("reset", w, g) for w, g in goals])


def prove_reset(**kw):
    return ResetProver(**kw).prove()
