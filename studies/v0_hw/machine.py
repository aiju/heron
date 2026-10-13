"""Draft 0's hardware as the chip-level tools see it (the machine interface
described in heron.infra.hw.runner)."""

import glob
import os
from collections import defaultdict

from heron.infra import asm as asmcore
from heron.infra.hw import runner

from . import cpu, microcode
from . import isa as v0
from .sim import Machine
from .testing import program_paths  # noqa: F401  (part of the interface)

NAME = "v0"
UCODE_DIR = "ucode"
NETLIST_TAG = ""
RAM_BYTES = 0x10000
CONFIG = {}                     # the Go simulator's defaults are draft 0's
ucode = microcode

HERE = os.path.dirname(os.path.abspath(__file__))


def build():
    return cpu.build()


def control_nets():
    return cpu.control_nets()


def rom_names():
    return {f"U_UC{k}": f"ucode{k}.bin" for k in range(microcode.ROMS)}


def rom_images():
    return {f"U_UC{k}": img for k, img in enumerate(microcode.rom_images())}


def sources():
    """What the ROM images and netlist are built from (the ROMs don't
    depend on the ISA module, only the listing does)."""
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py"))


def trace_buses():
    def bus(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    ctl = cpu.control_nets()
    return {
        "STEP": bus("STEP", 4), "IR": bus("IR", 16), "PC": ["GND"] + bus("PC", 15, 1),
        "ADDR": bus("ADDR", 16), "DBUS": bus("DBUS", 16), "ABUS": bus("ABUS", 16),
        "BBUS": bus("BBUS", 16), "F": bus("F", 16), "RES": bus("RES", 16), "R": bus("R", 16),
        "T": bus("T", 16), "MAR": bus("MAR", 16),
        "NZCVI": ["IFLAG", "VFLAG", "CFLAG", "ZFLAG", "NFLAG"][::-1],
        "MODE": ["MODERST", "MODEIRQ", "IRQP", "LINK"],
        "U": [ctl.get(i, "GND") for i in range(microcode.CONTROL_BITS)],
    }


def run_isa(path, inp=b""):
    """Assemble and run on the instruction-level simulator, with cycle
    counts and fetches from the microcode."""
    img = asmcore.assemble_file(v0, path)
    m = Machine(v0, img, inp=inp, timing=microcode.timing_function("v0"))
    m.fetch_log = []
    m.run(max_cycles=200_000_000)
    return img, m


def compare(m, hw, check_cycles=True):
    """Differences between the instruction-level run and the hardware."""
    diffs = []
    if not hw["halted"]:
        diffs.append(f"hardware did not halt: {hw['reason']}")
    if hw["output"] != bytes(m.dev.out):
        diffs.append("console output differs")
    if check_cycles and hw["cycles"] != m.cycles:
        diffs.append(f"cycles: hardware {hw['cycles']}, ISA sim {m.cycles}")
    for i in range(1, 16):
        if hw["regs_a"][i] != m.r[i] and m.reg_written[i]:
            diffs.append(f"r{i}: hardware {hw['regs_a'][i]:04X}, ISA sim {m.r[i]:04X}")
        if hw["regs_b"][i] != hw["regs_a"][i]:
            diffs.append(f"r{i}: register file copies disagree ({hw['regs_a'][i]:04X} / {hw['regs_b'][i]:04X})")
    if hw["regs_a"][0] != 0:
        diffs.append(f"r0 is {hw['regs_a'][0]:04X}")
    for f, attr in (("NFLAG", "n"), ("ZFLAG", "z"), ("CFLAG", "c"), ("VFLAG", "v"), ("IFLAG", "i")):
        if hw["flags"][f] != getattr(m, attr):
            diffs.append(f"flag {f[0]}: hardware {hw['flags'][f]}, ISA sim {getattr(m, attr)}")
    if hw["pc"] != m.pc:
        diffs.append(f"PC: hardware {hw['pc']:04X}, ISA sim {m.pc:04X}")
    ram = hw["ram"]
    bad = [a for a in range(0xFF00) if ram[a] != m.mem[a]]
    if bad:
        a = bad[0]
        diffs.append(f"memory differs at {len(bad)} bytes, first {a:04X}: hardware {ram[a]:02X}, ISA sim {m.mem[a]:02X}")
    if check_cycles and m.fetch_log is not None:
        for i, (h, s) in enumerate(zip(hw["fetches"], m.fetch_log)):
            if tuple(h) != tuple(s):
                diffs.append(f"fetch #{i}: hardware cycle {h[0]} addr {h[1]:04X} word {h[2]:04X}; "
                             f"ISA sim cycle {s[0]} addr {s[1]:04X} word {s[2]:04X}")
                break
    return diffs


def sta_words():
    """{(control word, extra constants): [labels]} for every distinct
    microinstruction; the ROM address's reset-mode bit is a constant too."""
    words = defaultdict(list)
    rom, notes = microcode.built()
    for a, w in rom.items():
        mode_rst = (a >> 15) & 1
        words[(w, (("MODERST", mode_rst),))].append(notes[a])
    return words
