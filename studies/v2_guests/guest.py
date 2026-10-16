"""Guest instruction sets on the draft 2 CPU: what a guest's microcode is
made of, and the machine it runs on.

A guest is a Python object that writes microcode with the draft 2
microcode assembler (studies/v2_hw/ucode.py: mi(), chain(), branch(), the
placement and the decode table) and gives:

    name              short name ("rv32")
    reset()           the routine at control store address 0
    fixed()           {address: node} for the forced entries the hardware
                      jumps to: the refill (it must fetch and decode, like
                      draft 2's), the interrupt and trace entries, the fault
                      entries; default: the refill, and a stop for the rest
    classify(w)       the decode table's view of first parcel w:
                      (routine key, length in parcels)
    routine(key)      the microcode for a key
    preload(sys)      what the I/O processor writes to RAM besides the
                      program (tables the reset routine copies)
    state(m)          the guest's registers as a dict, from the RTL model,
                      for lockstep checks against a reference interpreter

GuestMicrocode places it exactly as draft 2's own microcode is placed: the
same control word, the same 8K reachable words, the same decode table of
16-bit entries, the same length classes (the jumpers stay as draft 2's
profile set them). Nothing about the hardware changes unless a variant
in rtlx.py says so.
"""

from collections import Counter

from heron.studies.v2_hw import timing, ucode as uc
from heron.studies.v2_hw.rtl import RTL, RTLError
from heron.studies.v2_hw.system import ConsoleCard, MemoryCard, System

M32 = 0xFFFFFFFF


def native_lengths():
    """The length classes the jumpers are set to: draft 2's own."""
    return uc.built().lengths


_stops = {}


def stop(name):
    """A microinstruction that halts the machine (with interrupts off, the
    model stops; on the hardware it would wait for one). Each name gets its
    own code in the constant field, so that stops stay apart and the uIR
    says which one it was."""
    code = _stops.setdefault(name, len(_stops) + 1)
    n = uc.Node(uc.mi(k=code & 0xFF), None, name)
    n.succ = ("halt",)
    return n


class GuestMicrocode(uc.Microcode):
    """A guest's microcode, placed in the control store, with its decode
    table. Shares draft 2's placement, checks and timing."""

    def __init__(self, guest, lengths=None):
        uc._trap_cache.clear()
        _stops.clear()          # a guest's microcode doesn't depend on what was built before
        self.guest = guest
        self.reset = guest.reset()
        self.reset.fixed = 0
        self.fixed = guest.fixed()
        for a, n in self.fixed.items():
            n.fixed = a
        self.keys, self.lens, self.entry = {}, {}, {}
        for w in range(0x10000):
            k, ln = guest.classify(w)
            self.keys[w], self.lens[w] = k, ln
            if k not in self.entry:
                self.entry[k] = guest.routine(k)
        if hasattr(guest, "xlat"):
            # [D1] the decode table's other halves: the IR to load, and the
            # immediate (16 bits, sign-extended onto the B bus)
            self.xir, self.ximm = [0] * 0x10000, [0] * 0x10000
            for w in range(0x10000):
                xir, ximm = guest.xlat(w)
                self.xir[w] = xir & 0xFFFF
                self.ximm[w] = (ximm & 0xFFFF) - (0x10000 if ximm & 0x8000 else 0) & M32
        roots = [self.reset, *self.fixed.values(), *self.entry.values()]
        self.groups = uc._assign_slots(roots)
        uc._dedup(uc._reachable(roots), {id(n) for n in roots})
        self.nodes = uc._reachable(roots)
        self._place()
        self._check()
        timing.assign_classes(self, lengths or native_lengths())

    def summary(self):
        return (f"{self.guest.name}: {len(self.nodes)} microinstructions of {1 << uc.Y_BITS}, "
                f"{len(self.entry)} routines")


def default_fixed(name):
    """The refill as draft 2 has it, and stops for the other entries."""
    out = {uc.REFILL_ADDR: uc.end("refill", mem="fetch"),
           uc.IRQ_ADDR: uc.chain("interrupt", {}, stop(f"{name}: interrupt")),
           uc.TRACE_ADDR: uc.chain("trace", {}, stop(f"{name}: trace"))}
    for ln in range(4):
        out[uc.fault_addr(ln)] = uc.chain("fault", {}, stop(f"{name}: fault"))
    return out


# --------------------------------------------------------------------------
# The machine


def make_system(image, inp=b"", pages=256, base=0, preload=()):
    """Draft 2's system as the suite runs on it (studies/v2_hw/check.py): the
    CPU card's 2 MB, a memory card in slot 1, draft 1's I/O page in slot
    15; the guest's image at physical `base`, mapped from virtual 0 in
    context 0. preload: (physical address, bytes) the I/O processor also
    writes."""
    s = System()
    s.add(1, MemoryCard())
    s.add(15, ConsoleCard(inp))
    s.ram[base:base + len(image)] = image
    for pa, data in preload:
        s.ram[pa:pa + len(data)] = data
    s.identity_map(0, pages, base=base)
    return s


class Run:
    """A guest program on the RTL model."""

    def __init__(self, mc, image, inp=b"", rtl=None, profile=False, **sysopts):
        self.mc = mc
        guest = mc.guest
        if rtl is None:
            # a guest that needs a design change runs on the model that has it
            from .rtlx import RTLX
            rtl = RTLX if getattr(guest, "needs", ()) else RTL
        if hasattr(guest, "setup"):
            # the guest lays out its memory and map itself
            self.sys = make_system(b"", inp, pages=0, preload=guest.preload(), **sysopts)
            guest.setup(self.sys, image)
        else:
            self.sys = make_system(image, inp, preload=guest.preload(), **sysopts)
        self.m = rtl(self.sys, mc=mc)
        if profile:
            self.m.ucount = Counter()

    def boot(self, max_cycles=100_000):
        """The reset routine, up to its jump into the program (the first
        refill); its cycles are kept apart from the program's."""
        m = self.m
        while m.uaddr != uc.REFILL_ADDR:
            m.step()
            if m.cycles > max_cycles:
                raise RTLError("the reset routine didn't finish")
        self.reset_cycles, self.reset_ticks = m.cycles, m.ticks
        m.cycles = m.ticks = m.hold_ticks = m.instructions = 0
        if m.ucount is not None:
            m.ucount.clear()
        return self

    def run(self, max_cycles=200_000_000, trace=None):
        m = self.m
        if not hasattr(self, "reset_cycles"):
            self.boot()
        m.trace = trace
        try:
            m.run(max_cycles)
        except RTLError as e:
            self.error = str(e)
            return self
        self.error = None
        stop_name = m._uname()
        if "fault" in stop_name or "illegal" in stop_name or "interrupt" in stop_name:
            self.error = f"stopped in '{stop_name}' at PC {m.PC:08X}"
        return self

    @property
    def out(self):
        return self.m.out


def run_program(mc, image, inp=b"", **kw):
    r = Run(mc, image, inp, **kw)
    return r.run()
