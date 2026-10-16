"""Snapshots: a machine's whole state as bytes, for the browser to start
from (web/src/snapshot.rs has the layout and reads them).

`cold` is the machine before it has run an instruction, with the
desktop's source as its console input: starting from it, the browser
shows the boot, about half a minute of machine time at 3 MHz. `booted`
is the same machine once the desktop is up.
"""

import struct

from . import build, run

MAGIC = b"HERONSNP"


def snapshot(m, isa, inp=b""):
    """The bytes of a native machine's state (heron.native.v1.Machine, or
    v2's), with `inp` as the console input still to be read."""
    period, nxt, flag = m.timer
    ram, vram = m.mem, m.vram
    head = MAGIC + struct.pack("<I", 2)
    head += struct.pack("<3I", m.pc, getattr(m, "hi", 0), m.flags) + struct.pack("<16I", *m.r)
    head += struct.pack("<3Q", m.cycles, period, nxt)
    head += struct.pack("<6I", flag, m.depth, m.pointer, len(ram), len(vram), len(inp))
    head += struct.pack("<256I", *m.palette)
    head += struct.pack("<I", 2 if isa == "v2" else 1)
    assert len(head) == 1164
    return head + ram + vram + inp


def cold(depth=3, source=None, isa="v1b"):
    """The machine about to boot the desktop (or another program)."""
    src = build.console_input(depth, source)
    m = run.new_machine(isa, run.ram_image(build.image(isa)), b"")
    return snapshot(m, isa, src)


def booted(depth=3, source=None, isa="v1b"):
    """The machine with the desktop up, waiting for input."""
    s = run.Session(source, depth, isa=isa).boot()
    return snapshot(s.m, isa)
