"""User processes in different instruction sets on one draft 2 machine.

Draft 2's own microcode and a guest's (Thumb) share the control store; a
draft 2 kernel (sw/mixed/kernel.s) runs in supervisor mode and switches
between user processes on the timer, each with its own context and bank,
some in draft 2's code, some in Thumb. What it takes ([D5] and [D6] in
rtlx.py):

- **Decode pages:** two bits of the status word, ISA, extend the decode
  table's address (and D1's tables). RTI loads them with the rest of the
  word; exception entry clears them, so the supervisor always runs draft
  2. Nothing else in the CPU knows which instruction set it is running.
- **Room:** draft 2's microcode is 6,235 of the 8K words the sequencer
  reaches; Thumb's is some 4,700. With NEXT widened to 16 bits the whole
  64K store is reachable; decode entries stay 13 bits, so every routine
  starts in the first 8K, and their continuations go anywhere.
- **Sharing the register file:** a guest's registers must be locations
  0-15 of the bank (draft 2's, which the kernel's context switch and
  MFUR/MTUR already handle), its scratch draft 2's scratch, and its
  constants in the two global locations draft 2 leaves (or KONST).
- **Traps:** a guest's system call is draft 2's SWI, its undefined
  instructions draft 2's illegal instruction trap, and its faults draft
  2's: the fault entries save the instruction's own PC, so a guest
  instruction that faults must be restartable, writing no register before
  its last memory access.

The harness here plays the boot loader: it puts each process's image in
physical memory, maps it from VA 0 in the process's context, maps a
console card of the process's own at VA 0xFFF000 (slots 12-14), and
fills in the kernel's process table. The kernel's console is slot 15.
"""

import os

from heron.studies.v2_hw import timing, ucode as uc
from heron.studies.v2_hw.system import ConsoleCard, System

from . import guest as gm
from . import toolchain
from .rtlx import RTLX

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.join(HERE, "sw", "mixed")
KERNEL = os.path.join(SW, "kernel.s")
STORE = 1 << 16                 # [D6] the reachable control store
ENTRY_LIMIT = 1 << uc.Y_BITS    # decode entries are 13 bits

ISAS = {"v2": 0, "thumb": 1}
USER_CONSOLE = 0xFFF000
PROC_BASE = 0x40000             # process i's image at physical (i + 1) x this
P_SIZE = 32


# The draft 2 tools in this tree follow RFC 0028's new row 0 (LEA in its
# modes' columns 03-05, 0E, 0F; MFSR and MTSR at 06 and 07) and RFC 0029's
# special register numbers (FAR 9 ... BANK 14); the v2_hw study's
# microcode (PR #46) predates both. Page 0 of the decode table is RAM, so
# it maps them onto that microcode's routines while it does.
SR_OLD = {1: 1, 2: 2, 9: 8, 10: 9, 11: 10, 12: 11, 13: 12, 14: 13}
ROW0_OLD = uc.classify(0x0006)[0][0] != "mfsr"


def native_classify(w):
    if not ROW0_OLD:
        return uc.classify(w)
    op, hi, lo = w & 0xFF, w >> 12, (w >> 8) & 15
    ill = (("illegal",), 1)
    if op in (0x03, 0x04, 0x05, 0x0E, 0x0F):
        M = op & 15
        n = 1 + uc.ext_parcels(M, lo)
        if M == 0xF and (lo <= 3 or lo == 0xF):
            return ("illegal",), n
        return ("lea", M, lo if M in (4, 0xE, 0xF) else 0), n
    if op == 0x06:
        return (("mfsr", SR_OLD[lo]), 1) if lo in SR_OLD else ill
    if op == 0x07:
        return (("mtsr", SR_OLD[hi]), 1) if hi in SR_OLD else ill
    return uc.classify(w)


class MixedMicrocode(uc.Microcode):
    """Draft 2's microcode with guests' beside it: page 0 of the decode
    table is draft 2's, page i guests[i - 1]'s."""

    def __init__(self, guests, lengths=None):
        uc._trap_cache.clear()
        self.guests = guests
        # reset: the guests' constants, then draft 2's reset
        steps = []
        for g in guests:
            for loc, v in sorted(getattr(g, "consts", {}).items()):
                assert loc not in uc.CONSTS and loc not in (uc.TMP1, uc.TMP2, uc.TMP3)
                steps += _const(loc, v)
        self.reset = uc.chain("reset", *steps, uc.reset_routine()) if steps \
            else uc.reset_routine()
        self.reset.fixed = 0
        self.fixed = {uc.REFILL_ADDR: uc.end("refill", mem="fetch"),
                      uc.IRQ_ADDR: uc.trap("irq", 0, "interrupt"),
                      uc.TRACE_ADDR: uc.trap("trace", 0, "trace")}
        for ln in range(4):
            self.fixed[uc.fault_addr(ln)] = uc.fault_entry(ln)
        for a, n in self.fixed.items():
            n.fixed = a
        # the pages: (keys, lengths) per page; entry by (page, key)
        self.entry = {}
        self.page_keys = []
        self.xir_pages, self.ximm_pages = [None], [None]
        keys, lens = [None] * 0x10000, [0] * 0x10000
        for w in range(0x10000):
            k, ln = native_classify(w)
            keys[w], lens[w] = (0, k), ln
            if (0, k) not in self.entry:
                self.entry[(0, k)] = uc.routine(k)
        self.page_keys.append((keys, lens))
        for p, g in enumerate(guests, 1):
            keys, lens = [None] * 0x10000, [0] * 0x10000
            for w in range(0x10000):
                k, ln = g.classify(w)
                keys[w], lens[w] = (p, k), ln
                if (p, k) not in self.entry:
                    self.entry[(p, k)] = g.routine(k)
            self.page_keys.append((keys, lens))
            if hasattr(g, "xlat"):
                xir, ximm = [0] * 0x10000, [0] * 0x10000
                for w in range(0x10000):
                    a, b = g.xlat(w)
                    xir[w] = a & 0xFFFF
                    ximm[w] = ((b & 0xFFFF) - (0x10000 if b & 0x8000 else 0)) & 0xFFFFFFFF
                self.xir_pages.append(xir)
                self.ximm_pages.append(ximm)
            else:
                self.xir_pages.append(None)
                self.ximm_pages.append(None)
        # draft 2's own view, for what reads it (the RTL's page-less decode)
        self.keys = dict(enumerate(self.page_keys[0][0]))
        self.lens = dict(enumerate(self.page_keys[0][1]))
        roots = [self.reset, *self.fixed.values(), *self.entry.values()]
        self.groups = uc._assign_slots(roots)
        uc._dedup(uc._reachable(roots), {id(n) for n in roots})
        self.nodes = uc._reachable(roots)
        self._place()
        self._check()
        # the cycle lengths: NEXT isn't timed, so draft 2's 13-bit field does
        self._timing = True
        timing.assign_classes(self, lengths or gm.native_lengths())
        self._timing = False
        self.pages = [[self.entry[keys[w]].addr | (lens[w] << uc.Y_BITS)
                       for w in range(0x10000)] for keys, lens in self.page_keys]

    def _place(self):
        """[D6] Routines' first words in the first 8K, the rest anywhere in
        64K; dispatch tables and branch pairs aligned as draft 2's are."""
        used = [None] * STORE
        used[0] = self.reset
        self.reset.addr = 0
        for n in self.nodes:
            if n.fixed is not None:
                n.addr = n.fixed
                used[n.addr] = n
            elif n is not self.reset:
                n.addr = None
        entries = {id(n) for n in self.entry.values()}
        groups = {}
        for n in self.nodes:
            if n.slot is not None:
                groups.setdefault(n.slot[0], []).append(n)

        def free_run(start, stop, size, align):
            a = start + (-start) % align
            while a + size <= stop:
                if all(used[a + i] is None for i in range(size)):
                    return a
                a += align
            raise RuntimeError("microcode doesn't fit")

        # groups holding a routine's first word go low, the others high
        for gid, members in sorted(groups.items()):
            size = uc.TABLE if self.groups[gid] == "table" else 2
            low = any(id(m) in entries for m in members)
            a = free_run(0 if low else ENTRY_LIMIT, ENTRY_LIMIT if low else STORE, size, size)
            for m in members:
                m.addr = a + m.slot[1]
                used[m.addr] = m
        pos = {"low": 1, "high": ENTRY_LIMIT}
        for n in self.nodes:
            if n.addr is not None:
                continue
            where = "low" if id(n) in entries else "high"
            stop = ENTRY_LIMIT if where == "low" else STORE
            a = pos[where]
            while a < stop and used[a] is not None:
                a += 1
            if a >= stop:
                raise RuntimeError("microcode doesn't fit")
            n.addr = a
            used[a] = n
            pos[where] = a + 1
        self.used = len(self.nodes)
        self.by_addr = {n.addr: n for n in self.nodes}
        assert all(n.addr < ENTRY_LIMIT for n in self.entry.values())

    def word(self, n):
        """Field dict of node n: draft 2's, with NEXT 16 bits wide [D6]."""
        f = dict(n.f)
        f["VAS"] = uc.VAS_OF_MEM.get(f.get("MEM", 0), 0)
        f["MAPA"] = int(f.get("MEM", 0) in (uc.MEM["mapr"], uc.MEM["mapw"]))
        s = n.succ
        if s[0] == "next":
            f["SEQ"], f["NEXT"] = uc.SEQ_NEXT, s[1].addr
        elif s[0] == "branch":
            a0, a1 = s[2].addr, s[3].addr
            assert a0 % 2 == 0 and a1 == a0 + 1, n.name
            f["SEQ"], f["NEXT"], f["COND"] = uc.SEQ_NEXT, a0, s[1]
        elif s[0] == "decode":
            f["SEQ"] = uc.SEQ_DECODE
        elif s[0] == "dispatch":
            base = s[1][0].addr
            assert base % uc.TABLE == 0
            f["SEQ"], f["NEXT"] = uc.SEQ_DISPATCH, base
        elif s[0] == "halt":
            f["SEQ"], f["NEXT"] = uc.SEQ_HALT, n.addr
        if getattr(self, "_timing", False) and "NEXT" in f:
            f["NEXT"] &= ENTRY_LIMIT - 1
        return f

    def rom(self):
        # the RTL model's own control store holds draft 2's word format;
        # RTLX builds its own from word()
        return {0: uc.IDLE}

    def decode_table(self):
        return self.pages[0]

    def summary(self):
        names = ", ".join(["draft 2"] + [g.name for g in self.guests])
        top = max(n.addr for n in self.nodes)
        return (f"{names}: {len(self.nodes)} microinstructions (up to {top:04X}), "
                f"{len(self.entry)} routines")


def _const(loc, val):
    from .thumb import _const as const
    return const(loc, val)


_built = {}


def built():
    if "mc" not in _built:
        from .thumb import Thumb
        _built["mc"] = MixedMicrocode([Thumb(mixed=True)])
    return _built["mc"]


# --------------------------------------------------------------------------
# The processes

def user_image(name, isa):
    """(bytes from VA 0, entry). Draft 2's processes are hand-written
    (sw/mixed/NAME.s): this tree's C compiler follows main's draft 2,
    whose multiply and divide leave HI and LO in r0 and r1, and the v2_hw
    microcode doesn't yet."""
    if isa == "v2":
        import heron.studies.v2_isa  # noqa: F401
        from heron.infra import asm, isas
        img = asm.assemble_file(isas.get("v2"), os.path.join(SW, name + ".s"))
        data = bytearray(max(img.mem) + 1)
        for a, b in img.mem.items():
            data[a] = b
        return bytes(data), img.symbols["start"]
    img = toolchain.build("thumb-user", name)
    return img.data, img.symbols["_start"]


def kernel_image():
    import heron.studies.v2_isa  # noqa: F401
    from heron.infra import asm, isas
    return asm.assemble_file(isas.get("v2"), KERNEL)


def make_system(procs, period=20000):
    """procs: [(program name, isa)]. Returns (system, kernel image, the
    processes' consoles)."""
    assert len(procs) <= 3
    s = System()
    consoles = []
    for i, (name, isa) in enumerate(procs):
        inp, _ = toolchain.expected(name)
        c = ConsoleCard(inp)
        s.add(12 + i, c)
        consoles.append(c)
    s.add(15, ConsoleCard())        # the kernel's, with the timer: added last
    k = kernel_image()
    for a, b in k.mem.items():
        s.poke(a & 0x7FFFFFFF, b)
    sym = k.symbols

    def poke32(va, v):
        for j in range(4):
            s.poke((va & 0x7FFFFFFF) + j, (v >> (8 * j)) & 0xFF)
    poke32(sym["period"], period)
    poke32(sym["nproc"], len(procs))
    for i, (name, isa) in enumerate(procs):
        data, entry = user_image(name, isa)
        base = PROC_BASE * (i + 1)
        assert len(data) <= PROC_BASE, name
        s.ram[base:base + len(data)] = data
        ctx = i + 1
        s.identity_map(ctx, (len(data) + 0xFFF) >> 12, base=base)
        s.map[(ctx << 12) | (USER_CONSOLE >> 12)] = ((12 + i) << 27) | 0b011    # V, W
        e = sym["procs"] + P_SIZE * i
        for off, v in enumerate([ctx, ctx, entry, ISAS[isa] << 8 | 0x10, 1, 0, 0, 0]):
            poke32(e + 4 * off, v)
    return s, k, consoles


def run(procs, period=20000, max_cycles=400_000_000):
    """Run the kernel and its processes to the end. Returns a result dict."""
    mc = built()
    s, k, consoles = make_system(procs, period)
    m = RTLX(s, mc=mc)
    m.run(max_cycles)
    res = {"kernel": bytes(s.console.dev.out), "procs": [], "cycles": m.cycles,
           "ms": m.ticks * 20 / 1e6, "halted": m.halted}
    for (name, isa), c in zip(procs, consoles):
        out = bytes(c.dev.out)
        exp = toolchain.expected(name)[1]
        res["procs"].append({"name": name, "isa": isa, "out": out, "expected": exp,
                             "ok": out == exp})
    res["ok"] = m.halted and all(p["ok"] for p in res["procs"]) and \
        res["kernel"].count(b"exited") == len(procs)
    return res
