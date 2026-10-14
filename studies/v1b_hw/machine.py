"""The draft 1b hardware as the chip-level tools see it (the machine
interface described in heron.infra.hw.runner)."""

import glob
import os
from collections import defaultdict

from heron.infra import asm as asmcore
from heron.infra.hw import runner
from heron.studies.v1_isa import v1b
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v1_isa.testing import program_paths as _program_paths

from . import cpu
from . import ucode as ucode_v1b

NAME = "v1b"
UCODE_DIR = "ucode-v1b"
NETLIST_TAG = "v1b-"
RAM_BYTES = 0x100000
CONFIG = cpu.CONFIG
ucode = ucode_v1b

HERE = os.path.dirname(os.path.abspath(__file__))
V1_ISA = os.path.dirname(os.path.abspath(v1b.__file__))


def program_paths(names=None):
    return _program_paths(names, "v1b")


def build():
    return cpu.build()


def control_nets():
    return cpu.control_nets()


def rom_names():
    names = {f"U_UC{k}": f"ucode{k}.bin" for k in range(ucode_v1b.ROMS)}
    names.update({"U_DEC0": "decode0.bin", "U_DEC1": "decode1.bin"})
    return names


def rom_images():
    uimgs, dimgs = ucode_v1b.rom_images()
    imgs = {f"U_UC{k}": img for k, img in enumerate(uimgs)}
    imgs.update({"U_DEC0": dimgs[0], "U_DEC1": dimgs[1]})
    return imgs


def sources():
    """What the ROM images and netlist are built from, including the ISA
    tables the microcode and the decode ROM use."""
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py")) + \
        [os.path.join(V1_ISA, "v1b.py"), os.path.join(V1_ISA, "v1common.py")]


def trace_buses():
    def bus(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    ctl = cpu.control_nets()
    return {
        "Y": bus("Y", ucode_v1b.Y_BITS), "IR": bus("IR", 16), "PC": ["GND"] + bus("PC", 31, 1),
        "ADDR": bus("ADDR", 20), "DBUS": bus("DBUS", 16), "ABUS": bus("ABUS", 32),
        "BBUS": bus("BBUS", 32), "F": bus("F", 32), "RES": bus("RES", 32), "R": bus("RQ", 32),
        "T": bus("TQ", 32), "MAR": bus("MAR", 20), "LC": bus("LC", 8),
        "NZCVI": ["IFLAG", "VFLAG", "CFLAG", "ZFLAG", "NFLAG"][::-1],
        "U": [ctl.get(i, "GND") for i in range(ucode_v1b.ROMS * 8)],
    }


class Reference:
    """What the hardware is checked against: the instruction-level
    simulator's run (`isa_run`: its console output and interrupts) and the
    RTL model's (`rtl`: registers, memory, and the cycle of every fetch)."""

    def __init__(self, m, r):
        self.isa_run, self.rtl = m, r
        self.dev, self.irqs = m.dev, m.irqs
        self.cycles = r.cycles
        self.fetch_log = [(c, a & 0xFFFFF, w) for c, a, w in r.fetch_log]


def run_isa(path, inp=b""):
    """Assemble and run on the instruction-level simulator and on the RTL
    model, which is the reference for cycle counts and fetches: returns
    (image, Reference)."""
    from .rtl import RTL
    img = asmcore.assemble_file(v1b, path)
    m = Machine32(v1b, img, inp=inp)
    m.run(max_cycles=200_000_000)
    r = RTL(img, inp=inp)
    r.fetch_log = []
    r.run(max_cycles=200_000_000)
    return img, Reference(m, r)


def compare(m, hw, check_cycles=True):
    """The hardware must match the RTL model exactly (registers, flags, PC,
    all of RAM, cycles, every fetch) and print what the instruction-level
    simulator printed."""
    r = m.rtl
    diffs = []
    if not hw["halted"]:
        diffs.append(f"hardware did not halt: {hw['reason']}")
    if hw["output"] != bytes(m.dev.out):
        diffs.append("console output differs from the ISA simulator")
    if check_cycles and hw["cycles"] != r.cycles:
        diffs.append(f"cycles: hardware {hw['cycles']}, RTL model {r.cycles}")
    for i in range(32):
        if hw["regs_a"][i] != r.rf[i]:
            diffs.append(f"RF[{i}]: hardware {hw['regs_a'][i]:08X}, RTL {r.rf[i]:08X}")
        if hw["regs_b"][i] != hw["regs_a"][i]:
            diffs.append(f"RF[{i}]: copies disagree ({hw['regs_a'][i]:08X} / {hw['regs_b'][i]:08X})")
    for f, attr in (("NFLAG", "n"), ("ZFLAG", "z"), ("CFLAG", "c"), ("VFLAG", "v"), ("IFLAG", "i")):
        if hw["flags"][f] != getattr(r, attr):
            diffs.append(f"flag {f[0]}: hardware {hw['flags'][f]}, RTL {getattr(r, attr)}")
    if hw["pc"] != r.PC:
        diffs.append(f"PC: hardware {hw['pc']:08X}, RTL {r.PC:08X}")
    ram = hw["ram"]
    if ram != bytes(r.mem):
        bad = [a for a in range(len(r.mem)) if ram[a] != r.mem[a]]
        a = bad[0]
        diffs.append(f"memory differs at {len(bad)} bytes, first {a:05X}: hardware {ram[a]:02X}, RTL {r.mem[a]:02X}")
    if check_cycles:
        for i, (h, s) in enumerate(zip(hw["fetches"], m.fetch_log)):
            if tuple(h) != tuple(s):
                diffs.append(f"fetch #{i}: hardware cycle {h[0]} addr {h[1]:05X} word {h[2]:04X}; "
                             f"RTL cycle {s[0]} addr {s[1]:05X} word {s[2]:04X}")
                break
    return diffs


def sta_words():
    """{(control word, extra constants): [labels]} for every distinct
    microinstruction, with and without an interrupt pending."""
    words = defaultdict(list)
    mc = ucode_v1b.built()
    for n in mc.nodes:
        for irq in (False, True):
            w = ucode_v1b.pack(mc.word(n, irq))
            words[(w, ())].append(f"{n.name} @{n.addr:04X}" + (" irq" if irq else ""))
    return words
