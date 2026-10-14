"""The program suite on the system: the v1_isa study's draft 1b programs,
assembled against the system's runtime library (sw/v1b/lib: the console is
the I/O card's UART), plus the system's own programs in sw/v1b.

A program in sw/v1b replaces the v1_isa study's program of the same name
(the ones that use the console register directly, and `interrupts`, whose
timer is now the 82C54); the others are assembled as they are, with
`.include "lib/..."` finding the system's library.

The terminal's input ends with ^D (EOT), which the console library takes as
the end of the input.
"""

import os

from heron import native
from heron.infra import asm as asmcore
from heron.infra.programs import metadata as _metadata
from heron.studies.v1_isa import v1b
from heron.studies.v1_isa.testing import EXPECTED, program_paths as v1_paths
from heron.studies.v1_isa.timing32 import REFERENCE
from heron.studies.v1_isa.v1common import RAM_SIZE

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.join(HERE, "sw", "v1b")
EOT = b"\x04"


def program_paths(names=None):
    """The suite: the v1_isa programs and the system's own, by name."""
    paths = {os.path.basename(p)[:-2]: p for p in v1_paths()}
    for f in sorted(os.listdir(SW)):
        if f.endswith(".s"):
            paths[f[:-2]] = os.path.join(SW, f)
    out = [paths[n] for n in sorted(paths)]
    if names:
        out = [p for p in out if os.path.basename(p)[:-2] in names]
    return out


def source(path):
    """The file a program is assembled from: the system's version if it
    has one."""
    mine = os.path.join(SW, os.path.basename(path))
    return mine if os.path.exists(mine) else path


def metadata(path):
    return _metadata(source(path))


def assemble(path):
    """Assemble a program as if it were in sw/v1b, so that its includes
    find the system's library."""
    src = source(path)
    a = asmcore.Assembler(v1b)
    with open(src) as f:
        a.load(os.path.join(SW, os.path.basename(src)), text=f.read())
    return a.assemble()


def expected(name):
    p = os.path.join(EXPECTED, name + ".txt")
    if not os.path.exists(p):
        p = os.path.join(SW, "expected", name + ".txt")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def ram_image(img):
    mem = bytearray(RAM_SIZE)
    for addr, b in img.mem.items():
        mem[addr] = b
    return bytes(mem)


def run_isa(path, cf_image=None, ns_per_cycle=300.0, max_cycles=200_000_000):
    """Run a program on the instruction-level model of the system:
    (image, machine). The machine's bus_dump("uart") is what the
    terminal got."""
    img = assemble(path)
    m = native.v1.Machine("v1b", ram_image(img), b"", REFERENCE,
                          system={"uart_in": metadata(path)["input"] + EOT,
                                  "cf_image": cf_image if cf_image is not None
                                  else bytes(512 * 2048),
                                  "ns_per_cycle": ns_per_cycle})
    m.run(max_cycles)
    return img, m
