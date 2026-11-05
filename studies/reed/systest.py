"""Reed's system half against draft 2's system simulator (RFC 0029): a
program (sw/systest.s) run on the model (model.py) and on the reference
(heron.native.v2.SysMachine), its output, its exception log, the user's
pages and the registers of banks 0 and 1 compared.

  heron reed systest [--chip]

The program is assembled with its supervisor's half in the window
(0x8000_0000 up); its image goes into RAM by physical address (bit 31
dropped). The reference starts at 0x8000_0000, Reed at 0 with the map off:
the program's first jump takes both into the window.
"""

import os

from heron import native
from heron.infra import asm as asmcore, isas
import heron.studies.v2_isa  # noqa: F401 (registers the ISA)

from . import model

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "sw", "systest.s")
RAM_BYTES = 4 << 20
LOG = 0x10000
# the physical pages the user's tests use, compared byte for byte
PAGES = (0x9000, 0xA000, 0xB000, 0xC000, 0x10000)


def image(path=PROGRAM):
    img = asmcore.assemble_file(isas.get("v2"), path)
    ram = bytearray(RAM_BYTES)
    for a, b in img.mem.items():
        ram[a & 0x7FFFFFFF] = b
    return img, ram


def run_reference(ram, steps=2_000_000):
    m = native.v2.SysMachine(RAM_BYTES)
    m.load(0, bytes(ram))
    status = m.run(steps)
    return m, status


def run_model(ram, max_cycles=20_000_000, prog=None):
    m = model.Model(bytes(ram), prog=prog)
    m.stopped = m.run(max_cycles)
    return m


def compare(ref, m):
    """Differences, as text lines."""
    out = []
    got, exp = bytes(m.out), bytes(ref.out())
    if got != exp:
        out.append(f"output differs:\n  Reed:      {got.decode(errors='replace')!r}\n"
                   f"  reference: {exp.decode(errors='replace')!r}")
    rm = ref.mem()
    for base in PAGES:
        a = next((i for i in range(base, base + 0x1000) if m.ram[i] != rm[i]), None)
        if a is not None:
            out.append(f"RAM differs at {a:06X}: Reed {m.ram[a]:02X}, the reference {rm[a]:02X}")
    for bank in (0, 1):
        mine = m.bank(bank)[:16]
        theirs = ref.bank_regs(bank)
        for i in range(16):
            if mine[i] != theirs[i]:
                out.append(f"bank {bank} r{i}: Reed {mine[i]:08X}, the reference {theirs[i]:08X}")
    return out


def log_lines(mem, n):
    out = []
    for k in range(n):
        a = LOG + 20 * k
        v = [int.from_bytes(mem[a + 4 * i:a + 4 * i + 4], "little") for i in range(5)]
        out.append("  vector %03X  pc %08X  sr %08X  far %08X  fsr %08X" % tuple(v))
    return out


def main(argv=()):
    img, ram = image()
    ref, status = run_reference(ram)
    m = run_model(ram)
    lines = [f"reference: {status}, {ref.instructions} instructions; "
             f"Reed's model: {m.stopped}, {m.instructions} instructions, {m.cycles} cycles"]
    lines.append(bytes(m.out).decode(errors="replace").rstrip())
    diffs = compare(ref, m)
    lines += diffs or ["the same as the reference: output, log, pages, banks 0 and 1"]
    print("\n".join(lines))
    return 1 if diffs or m.stopped != "halt" else 0
