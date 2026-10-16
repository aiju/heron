"""Where a running Fen's time goes: cycles by process and by function.

The simulator counts executions per physical instruction address. A
kernel address is below the kernel's end; any other is a page of some
process, which its page map (the context of its pid) says, and the
program's linked image names the function. Processes are read from the
kernel's process table (struct proc in kernel/kernel.h). A process that
has ended has no map any more, so its time shows as "?".
"""

import bisect
import collections
import struct

from heron import native
from heron.studies.fen import build

PROC_SIZE = 56          # struct proc
PROC_NAME = 24
MAX_PROCS = 128
P_LIVE = 1


class Symbols:
    def __init__(self, symbols):
        items = sorted((a, n) for n, a in symbols.items() if not n.startswith(".")
                       and not n.startswith("__text") and "$" not in n)
        self.addrs = [a for a, _ in items]
        self.names = [n for _, n in items]

    def name(self, addr):
        i = bisect.bisect_right(self.addrs, addr) - 1
        return self.names[i] if i >= 0 else "?"


_programs = {}


def program_symbols(name):
    if name not in _programs:
        try:
            _programs[name] = Symbols(build.program(name)[1].symbols)
        except (KeyError, build.BuildError):
            _programs[name] = None
    return _programs[name]


def processes(session):
    """{pid: name} of the live processes."""
    c = session.c
    base = session.kernel.symbols["_procs"] & 0x7FFFFFFF
    raw = c.read_phys(base, PROC_SIZE * MAX_PROCS)
    out = {}
    for pid in range(1, MAX_PROCS):
        rec = raw[pid * PROC_SIZE:(pid + 1) * PROC_SIZE]
        state = struct.unpack_from("<I", rec, 4)[0]
        if state == P_LIVE:
            out[pid] = rec[PROC_NAME:PROC_NAME + 16].split(b"\0")[0].decode(errors="replace")
    return out


class Profile:
    """Cycles since the profile started (or since `reset`)."""

    def __init__(self, session, config=None):
        self.s = session
        self.config = config or native.v2.reference()
        self.reset()

    def _now(self):
        return dict(self.s.c.pc_cycles(self.config))

    def reset(self):
        self.base = self._now()

    def by_function(self):
        """{(process, function): cycles}"""
        now = self._now()
        kend = self.s.kernel.symbols["__end"] & 0x7FFFFFFF
        ksyms = Symbols({n: a for n, a in self.s.kernel.symbols.items()
                         if a >= build.KERNEL_BASE})     # (not the .equ constants)
        procs = processes(self.s)
        owner = {}
        for pid, name in procs.items():
            for vpage, pte in self.s.c.page_map(pid):
                owner.setdefault(pte >> 12, (pid, name, vpage))
        out = collections.Counter()
        for pc, n in now.items():
            n -= self.base.get(pc, 0)
            if n <= 0 or pc is None:
                continue
            if pc < kend:
                out[("kernel", ksyms.name(pc | 0x80000000))] += n
                continue
            o = owner.get(pc >> 12)
            if o is None:
                out[("?", "?")] += n
                continue
            pid, name, vpage = o
            syms = program_symbols(name)
            va = vpage << 12 | (pc & 0xFFF)
            out[(name, syms.name(va) if syms else hex(va))] += n
        return out

    def report(self, top=30):
        f = self.by_function()
        total = sum(f.values()) or 1
        procs = collections.Counter()
        for (p, _), n in f.items():
            procs[p] += n
        lines = [f"{total} cycles"]
        for p, n in procs.most_common():
            lines.append(f"  {p:10} {n:12} {100 * n / total:5.1f}%")
        lines.append("")
        for (p, fn), n in f.most_common(top):
            lines.append(f"  {p:10} {fn:28} {n:12} {100 * n / total:5.1f}%")
        return "\n".join(lines)
