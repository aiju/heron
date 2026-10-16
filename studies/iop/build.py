"""Building the IOP's firmware: the microcode (ucode/), the Forth's
dictionary (forth/), and the image flash that holds the dictionary and
the CPU's images (RFC 0027, 6.7 and 8.3).

The image flash, in halfwords:

    0x00000       the header (layout.py): its magic, the dictionary's
                  length in pages, the cold start, and where images 0-3
                  start (0 for none)
    0x00100       the dictionary, which the microcode copies into the SRAM
                  at reset, up to 32K cells
    0x10000 on    the images: records of {bus address (low, high), n, n
                  halfwords}, ended by one with n = 0. Image 0 is the CPU's
                  control store and decode table, image 1 its boot
                  program

The control store image comes from studies/v2_hw's microcode, which takes
a minute or so to build, so it is cached in build/iop/ and only made when
asked for.
"""

import os
import pickle

from heron import BUILD

from . import layout, meta, uasm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BUILD, "iop")
UCODE = ["core.uc", "prims.uc"]
FORTH = ["kernel.fs", "monitor.fs"]
IMAGES_AT = 0x10000
FLASH_HALFWORDS = 512 * 1024

# The CPU card's control store window (studies/iop/sim/src/system.rs)
CS_BASE = 0x7040_0000
CS_LANE = 0x2_0000
CS_LANES = 9                # draft 2's 144-bit microinstruction
DEC_LANE = 9


class BuildError(Exception):
    pass


def read(*parts):
    with open(os.path.join(HERE, *parts)) as f:
        return f.read()


def microcode():
    """The assembled microcode (uasm.Microcode)."""
    try:
        return uasm.assemble([(n, read("ucode", n)) for n in UCODE])
    except uasm.AsmError as e:
        raise BuildError(str(e)) from None


def forth(mc, extra=()):
    """The metacompiled dictionary (meta.Meta), over `mc`'s primitives.
    `extra` is more [(name, text)] to compile after the kernel."""
    try:
        return meta.metacompile([(n, read("forth", n)) for n in FORTH] + list(extra), mc.prims, mc.labels)
    except meta.MetaError as e:
        raise BuildError(str(e)) from None


def records(runs):
    """Halfwords for [(bus address, [halfwords])], the end record after."""
    out = []
    for addr, halves in runs:
        for i in range(0, len(halves), 0x7FFF):
            part = halves[i:i + 0x7FFF]
            a = addr + 2 * i
            out += [a & 0xFFFF, a >> 16, len(part)] + list(part)
    return out + [0, 0, 0]


def ram_runs(mem, base=0):
    """{byte address: byte} as runs of halfwords on the bus at base +
    address."""
    addrs = sorted({a & ~1 for a in mem})
    runs = []
    for a in addrs:
        h = mem.get(a, 0) | mem.get(a + 1, 0) << 8
        if runs and runs[-1][0] + 2 * len(runs[-1][1]) == base + a:
            runs[-1][1].append(h)
        else:
            runs.append((base + a, [h]))
    return runs


def cpu_program(path):
    """A draft 2 program, assembled, as {physical address: byte}: it runs
    from the reset vector, physical 0, in the supervisor's window, so it
    is assembled at 0x8000_0000 and loaded at its address less bit 31."""
    import heron.studies.v2_isa
    from heron.infra import asm as asmcore
    from heron.infra import isas
    try:
        img = asmcore.assemble_file(isas.get("v2"), path)
    except Exception as e:
        raise BuildError(f"{path}: {e}") from None
    return {a & 0x7FFF_FFFF: v for a, v in img.mem.items()}


def control_store():
    """Records of draft 2's control store and decode table (studies/v2_hw)
    for the CPU card's window: each 16-bit lane's used words, in runs, and
    the whole decode table. Cached in build/iop/."""
    path = os.path.join(OUT, "control-store.pickle")
    from heron.studies import v2_hw
    src = os.path.join(os.path.dirname(v2_hw.__file__), "ucode.py")
    if os.path.exists(path) and os.path.getmtime(path) > os.path.getmtime(src):
        with open(path, "rb") as f:
            return pickle.load(f)
    import heron.studies.v2_isa
    from heron.studies.v2_hw import ucode as uc
    mc = uc.built()
    rom = mc.rom()
    used = sorted(rom)
    runs = []
    for k in range(CS_LANES):
        lane_runs = []
        for a in used:
            h = (rom[a] >> (16 * k)) & 0xFFFF
            if lane_runs and lane_runs[-1][0] + 2 * len(lane_runs[-1][1]) == CS_BASE + CS_LANE * k + 2 * a:
                lane_runs[-1][1].append(h)
            else:
                lane_runs.append((CS_BASE + CS_LANE * k + 2 * a, [h]))
        runs += lane_runs
    runs.append((CS_BASE + CS_LANE * DEC_LANE, list(mc.decode_table())))
    out = {"runs": runs, "rom": rom, "decode": list(mc.decode_table())}
    os.makedirs(OUT, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(out, f)
    return out


def flash_image(m, images=()):
    """The image flash's contents (bytes) for the dictionary `m` (a
    finished Meta) and up to four images, each a list of halfwords or
    None."""
    cells = m.image
    pages = (len(cells) + 255) // 256
    hw = [0xFFFF] * (layout.FL_DICT + 256 * pages)
    hw[:16] = [0] * 16
    hw[layout.FL_MAGIC] = layout.FLASH_MAGIC
    hw[layout.FL_VERSION] = 1
    hw[layout.FL_PAGES] = pages
    hw[layout.FL_COLD] = m.cold
    hw[layout.FL_HERE] = m.here
    hw[layout.FL_LATEST] = m.latest
    hw[layout.FL_DICT:layout.FL_DICT + len(cells)] = cells
    if len(hw) > IMAGES_AT:
        raise BuildError("the dictionary runs into the images")
    at = IMAGES_AT
    for n, img in enumerate(images):
        if img is None:
            continue
        hw += [0xFFFF] * (at - len(hw))
        hw[layout.FL_IMAGES + 2 * n] = at & 0xFFFF
        hw[layout.FL_IMAGES + 2 * n + 1] = at >> 16
        hw += img
        at = len(hw)
    if len(hw) > FLASH_HALFWORDS:
        raise BuildError(f"the image flash holds {FLASH_HALFWORDS} halfwords, not {len(hw)}")
    return b"".join(h.to_bytes(2, "little") for h in hw)


class Build:
    """Everything a run needs: the microcode, the dictionary, the flash."""

    def __init__(self, program=None, wcs=False, extra=()):
        self.mc = microcode()
        self.meta = forth(self.mc, extra)
        images = [None, None]
        self.cs = None
        if wcs:
            self.cs = control_store()
            images[0] = records(self.cs["runs"])
        self.program = None
        if program:
            self.program = cpu_program(program)
            images[1] = records(ram_runs(self.program))
        self.flash = flash_image(self.meta, images)

    def ucode_bytes(self):
        return self.mc.rom_bytes()


DEFAULT_PROGRAM = os.path.join(HERE, "sw", "hello.s")
