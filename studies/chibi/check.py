"""The register-transfer model against draft 2's instruction-level
simulator: the suite's programs, their output, registers and memory.

Both start from reset with the program's image at 0. The model's reset
microcode enters the program at 0 as the simulator's reset does; the
suite's programs set sp themselves. The simulator has 1 MB of RAM, the
board 2 MB that the programs don't reach beyond.
"""

import os

from heron.infra import asm as asmcore, isas
from heron.infra.programs import metadata
from heron.studies.v2_isa import testing
from heron.studies.v2_isa.sim import Machine

from .rtl import RTL
from .rtl2 import RTL2
from .system import System
from .system2 import System2

# programs whose output depends on the machine's timing (the timer's
# interrupts), compared on their run alone
TIMED = {"interrupts"}


def assemble(path):
    return asmcore.assemble_file(isas.get("v2"), path)


def run_isa(img, inp, max_cycles=200_000_000):
    m = Machine(img, inp=inp)
    m.run(max_cycles=max_cycles)
    return m


def run_rtl(img, inp=b"", max_cycles=100_000_000, profile=False, log=False, first=False):
    """The model: the two-halves machine's (rtl2), or the first cut's."""
    s = System(inp) if first else System2(inp)
    s.load(img)
    m = RTL(s) if first else RTL2(s)
    if profile:
        m.ucount = {}
    if log:
        m.decodes = []
    m.run(max_cycles)
    return m


def compare(ref, m, mem=True):
    """Differences between the simulator's run and the model's, as text."""
    out = []
    got = bytes(m.sys.console.out)
    exp = bytes(ref.dev.out)
    if got != exp:
        out.append(f"output differs: {got[:80]!r}... against {exp[:80]!r}...")
    for i in range(16):
        if m.reg(i) != ref.r[i]:
            out.append(f"r{i} = {m.reg(i):08X}, expected {ref.r[i]:08X}")
    for k in "NZCV":
        if m.f[k] != getattr(ref, k.lower()):
            out.append(f"{k} = {m.f[k]}, expected {getattr(ref, k.lower())}")
    if mem:
        rm = ref.mem
        bad = [a for a in range(len(rm)) if m.sys.ram[a] != rm[a]]
        if bad:
            out.append(f"{len(bad)} bytes of memory differ, the first at {bad[0]:06X}: "
                       f"{m.sys.ram[bad[0]]:02X}, expected {rm[bad[0]]:02X}")
    return out


def check_program(path, verbose=False, first=False):
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    img = assemble(path)
    ref = run_isa(img, meta["input"])
    try:
        m = run_rtl(img, meta["input"], max_cycles=40 * ref.cycles + 100_000, first=first)
    except Exception as e:      # noqa: BLE001  (a model error is the check's result)
        return name, None, [f"{type(e).__name__}: {e}"]
    diffs = compare(ref, m) if name not in TIMED else []
    return name, m, diffs


def cmd_check(args):
    if args.first:
        from .routines import control_store
    else:
        from .routines2 import control_store
    cs = control_store()
    if cs.missing:
        print(f"not in the microcode yet: {' '.join(f'{op:02X}' for op in sorted(cs.missing))}")
    paths = testing.program_paths(args.names or None)
    bad = 0
    for p in paths:
        name, m, diffs = check_program(p, first=args.first)
        if diffs:
            bad += 1
            print(f"{name:12} FAIL  {diffs[0]}")
            for d in diffs[1:6]:
                print(f"{'':18}{d}")
        else:
            t = "" if args.first else f" {m.ticks:11d} ticks"
            print(f"{name:12} ok    {m.instructions:9d} instructions {m.cycles:10d} cycles{t} "
                  f"(CPI {m.cycles / max(m.instructions, 1):.2f})")
    return 1 if bad else 0
