"""The system on the chip-level simulator (infra/hwsim's run_system): the
backplane with the CPU card in slot 0, the memory card in slot 1 and the
I/O card in slot 15, run from power-up.

The composed netlist, the length classes and the ROM images are built
into build/system/ and rebuilt when their sources change.
"""

import glob
import json
import os

from heron import BUILD, native
from heron.infra.hw import chips, runner
from heron.studies.v1b_hw import machine as v1b_machine
from heron.studies.v1b_hw import ucode as uc

from . import backplane, bus, cpucard, iocard, lengths, memcard, programs

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BUILD, "system")
SLOTS = {"CPU": 0, "MEM": 1, "IO": 15}
N_SIMPLE = 6            # data clocks for a simple card: the CF card sets it


def sources():
    return (v1b_machine.sources() + runner.infra_sources()
            + glob.glob(os.path.join(HERE, "*.py")))


def _fresh(path, srcs=None):
    srcs = srcs or sources()
    return os.path.exists(path) and os.path.getmtime(path) > max(os.path.getmtime(p) for p in srcs)


def default_lengths():
    """The length classes' ticks for the default parts at worst case
    (lengths.py)."""
    return tuple(classes()[1]["lengths"])


def build(lengths_=None, n_simple=N_SIMPLE, bus_div=3, settle=True):
    lengths_ = lengths_ or default_lengths()
    cards = {SLOTS["CPU"]: cpucard.build(lengths_, bus_div), SLOTS["MEM"]: memcard.build(),
             SLOTS["IO"]: iocard.build()}
    return bus.compose(backplane.build(n_simple), cards, settle=settle)


def netlist(variant=chips.DEFAULT_VARIANT, corner="max", lengths_=None,
            n_simple=N_SIMPLE, bus_div=3):
    """The exported netlist (a dict), cached."""
    lengths_ = lengths_ or default_lengths()
    key = f"{variant}-{corner}-{'-'.join(map(str, lengths_))}-n{n_simple}-d{bus_div}"
    path = os.path.join(OUT, f"netlist-{key}.json")
    if not _fresh(path):
        os.makedirs(OUT, exist_ok=True)
        d = build(lengths_, n_simple, bus_div).export(variant=variant, corner=corner)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


def classes():
    """The length class of every microinstruction (packed word -> class),
    and the lengths chosen for the default parts: cached, since the timing
    analysis takes minutes."""
    path = os.path.join(OUT, "classes.json")
    if not _fresh(path):
        cls, lens, t, fixed = lengths.assign()
        os.makedirs(OUT, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"lengths": lens, "ticks": t, "fixed_ticks": fixed,
                       "classes": {str(w): c for w, c in cls.items()}}, f)
    with open(path) as f:
        d = json.load(f)
    return {int(w): c for w, c in d["classes"].items()}, d


def rom_images():
    """{chip reference: image} for the CPU card's ROMs."""
    imgs = {f"CPU.{k}": v for k, v in v1b_machine.rom_images().items()}
    cls, _ = classes()
    imgs["CPU.U_UC15"] = lengths.class_rom(cls)
    return imgs


def preloads(img, inp=b"", cf_image=None):
    """What the chips start with: the ROMs, the program in the CPU card's
    RAM (even bytes in U_RAML, odd in U_RAMH), cleared register files and
    memory card, the terminal's input and the disk."""
    pre = rom_images()
    ram = programs.ram_image(img)
    pre["CPU.U_RAML"], pre["CPU.U_RAMH"] = ram[0::2], ram[1::2]
    for side in "AB":
        for k in range(4):
            pre[f"CPU.U_RF{side}{k}"] = bytes(32768)
    for k in range(4):
        pre[f"MEM.U_RAM{k}"] = bytes(512 * 1024)
    pre["IO.U_UART"] = inp + programs.EOT
    pre["IO.U_CF"] = cf_image if cf_image is not None else programs.cf_disk()
    return {k: bytes(v) for k, v in pre.items()}


def config(max_cycles=10_000_000, trace=None, fetch_trace=0, seed=1, probe=None):
    cpu = "CPU."
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "clock_net": cpu + "CLK", "reset_net": cpu + "RESET_n",
        "fetch_net": cpu + "uLDIR_n", "fetch_level": 0,
        "addr_nets": [f"{cpu}ADDR{i}" for i in range(20)],
        "data_nets": [f"{cpu}DBUS{i}" for i in range(16)],
        "fetch_trace": fetch_trace,
        # HALT with interrupts off stops the machine
        "stop_when": [[(cpu + "uHALT", 1), (cpu + "IFLAG", 0)]],
        "dump": ["IO.U_UART", "IO.U_CF"] + [f"MEM.U_RAM{k}" for k in range(4)]
        + [cpu + "U_RAML", cpu + "U_RAMH"] + [f"{cpu}U_RFA{k}" for k in range(4)]
        + [f"{cpu}U_RFB{k}" for k in range(4)],
        "observe": [cpu + f for f in ("NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG")]
        + [f"{cpu}PC{i}" for i in range(1, 32)],
    }
    if probe:
        nets, t0, t1 = probe
        cfg.update(probe=list(nets), probe_from_ps=int(t0), probe_to_ps=int(t1))
    if trace:
        tb = {k: [n if n in ("GND", "VCC") else cpu + n for n in v]
              for k, v in v1b_machine.trace_buses().items() if k not in ("U", "MAR")}
        tb["MAR"] = [f"{cpu}MAR{i}" for i in range(32)]
        tb["A"] = [f"A{i}" for i in range(1, 32)]
        tb["D"] = [f"D{i}" for i in range(16)]
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses=tb)
    return cfg


def run(path, max_cycles=10_000_000, trace=None, cf_image=None, probe=None, **kw):
    """Run a program on the system at chip level: the outcome, with the
    registers, RAM and flags decoded."""
    img = programs.assemble(path)
    inp = programs.metadata(path)["input"]
    hw = native.hwsim.run_system(netlist(**kw), config(max_cycles, trace, probe=probe),
                                 preloads(img, inp, cf_image))
    d = hw["dumps"]
    hw["output"] = bytes(d["IO.U_UART"])
    hw["cf"] = bytes(d["IO.U_CF"])
    lo, hi = d["CPU.U_RAML"], d["CPU.U_RAMH"]
    ram = bytearray(2 * len(lo))
    ram[0::2], ram[1::2] = lo, hi
    hw["ram"] = bytes(ram)
    mem = bytearray(4 * len(d["MEM.U_RAM0"]))
    for k in range(4):
        mem[k::4] = d[f"MEM.U_RAM{k}"]
    hw["mem"] = bytes(mem)
    for side in "AB":
        hw[f"regs_{side.lower()}"] = [sum(d[f"CPU.U_RF{side}{k}"][i] << (8 * k) for k in range(4))
                                      for i in range(32)]
    n = hw["nets"]
    hw["pc"] = sum(n[f"CPU.PC{i}"] << i for i in range(1, 32))
    hw["flags"] = {f: n[f"CPU.{f}"] for f in ("NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG")}
    return img, hw
