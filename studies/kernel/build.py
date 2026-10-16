"""Building the benchmark nucleus and its user programs, and a machine to
run them on.

The nucleus (nucleus/nucleus.s) comes in variants, chosen by features:
exactly one of the register-bank policies `none`, `half` and `full`
(report 0020's appendix), and optionally `softtlb` (the map as a cache of page tables
in memory). Its source has feature blocks:

    .if NAME            ; kept when feature NAME is on (also !NAME, A|B)
    ...
    .else
    ...
    .endif

Lines a block drops become empty lines, so the assembler's line numbers
still match the source.

User programs (user/*.s) are assembled on their own at virtual address 0.
A boot image is the nucleus at physical 0, each process's program copied
to its own physical pages, and the nucleus's boot table filled in.
"""

import os
import re

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v1_isa.timing32 import REFERENCE

HERE = os.path.dirname(os.path.abspath(__file__))
NUCLEUS = os.path.join(HERE, "nucleus", "nucleus.s")
USER = os.path.join(HERE, "user")
ISA = "v1bs"

BANKS = ("none", "half", "full")

PAGE = 4096
USER_BASE = 0x10000     # where the processes' programs are put, physically
SHARED_PHYS = 0x3C000   # the four shared pages (nucleus.s)
FREE_LO = 0x40000       # the nucleus's page pool
FREE_HI = 0x100000

# boot table flags (nucleus.s)
F_IO = 1                # map the I/O page at 0xFFF000
F_SHARED = 2            # map the shared pages at 0x400000
F_IRQ = 4               # the timer interrupt's user-level driver


def preprocess(text, features):
    out, stack = [], []
    for line in text.split("\n"):
        m = re.match(r"\s*\.(if|else|endif)\b\s*([^;]*)", line)
        if m:
            d, arg = m.group(1), m.group(2).strip()
            if d == "if":
                on = any(_term(t.strip(), features) for t in arg.split("|"))
                stack.append((on, all(s[0] for s in stack)))
            elif d == "else":
                on, outer = stack.pop()
                stack.append((not on, outer))
            else:
                stack.pop()
            out.append("")
            continue
        out.append(line if all(on for on, _ in stack) else "")
    if stack:
        raise ValueError("unbalanced .if")
    return "\n".join(out)


def _term(t, features):
    return t[1:] not in features if t.startswith("!") else t in features


def check_features(features):
    banks = [f for f in features if f in BANKS]
    if len(banks) != 1:
        raise ValueError(f"pick one of {BANKS}: {features}")
    unknown = set(features) - set(BANKS) - {"softtlb"}
    if unknown:
        raise ValueError(f"unknown features {sorted(unknown)}")


_KERNELS = {}


def kernel(features):
    """The nucleus assembled with these features: an asm Image."""
    features = tuple(sorted(features))
    check_features(features)
    if features not in _KERNELS:
        with open(NUCLEUS) as f:
            text = preprocess(f.read(), features)
        a = asmcore.Assembler(isas.get(ISA))
        a.load(NUCLEUS, text=text)
        _KERNELS[features] = a.assemble()
    return _KERNELS[features]


_USERS = {}


def user(name):
    """A user program, assembled at virtual address 0."""
    if name not in _USERS:
        _USERS[name] = asmcore.assemble_file(isas.get(ISA), os.path.join(USER, name + ".s"))
    return _USERS[name]


class Proc:
    """A process for the boot table: a user program, the argument its
    thread starts with in r1, its priority (0 is the highest) and flags."""

    def __init__(self, prog, arg=0, prio=8, flags=0, arg2=0):
        self.prog, self.arg, self.prio, self.flags, self.arg2 = prog, arg, prio, flags, arg2


class Boot:
    """A boot image: memory, and where things went."""

    def __init__(self, features, procs, timer=0):
        self.features = tuple(sorted(features))
        self.kernel = kernel(features)
        self.procs = procs
        mem = dict(self.kernel.mem)
        sym = self.kernel.symbols
        phys = USER_BASE
        self.bases = []
        table = [len(procs), timer, FREE_LO, FREE_HI]
        for p in procs:
            img = user(p.prog)
            lo, hi = 0, max(img.mem) + 1 if img.mem else 0
            npages = max(1, (hi + PAGE - 1) // PAGE)
            if phys + npages * PAGE > SHARED_PHYS:
                raise ValueError("the programs don't fit below the page pool")
            for a, b in img.mem.items():
                mem[phys + a] = b
            self.bases.append(phys)
            table += [phys, npages, img.symbols.get("start", 0), p.arg, p.prio * 4, p.flags, p.arg2, 0]
            phys += npages * PAGE
        base = sym["boot_table"]
        if len(table) * 4 > sym["boot_table_end"] - base:
            raise ValueError("too many processes for the boot table")
        for i, w in enumerate(table):
            for j in range(4):
                mem[base + 4 * i + j] = (w >> (8 * j)) & 0xFF
        self.mem = mem

    def machine(self, reference=REFERENCE):
        class _Img:
            pass
        img = _Img()
        img.mem = self.mem
        return Machine32(isas.get(ISA), img, reference=reference)

    def symbol_at(self, addr):
        """The nucleus symbol an address falls in, or the user program."""
        if addr is None:
            return "(irq entry)"
        if addr >= USER_BASE:
            for i, b in reversed(list(enumerate(self.bases))):
                if addr >= b:
                    return f"user:{self.procs[i].prog}"
        best = None
        for name, a in self.kernel.symbols.items():
            if a <= addr and not name.startswith(".") and "." not in name and name.islower():
                if best is None or a > best[1]:
                    best = (name, a)
        return best[0] if best else "?"
