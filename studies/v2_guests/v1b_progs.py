"""Programs for the draft 1b guest: draft 1b's own binaries, unchanged.

- the hand-written program suite (studies/v1_isa/programs/v1b), assembled
  with draft 1b's assembler;
- the C programs compiled for 1b by the c_compiler study (`c-NAME`).

Both are checked against the suite's expected output. The reference is
the v1_isa study's instruction-level simulator.
"""

import os

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.v1_isa import testing
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v1_isa.v1common import RAM_SIZE


def _bytes(img):
    """An assembled image as one block of memory from address 0."""
    top = max(img.mem) + 1 if img.mem else 0
    out = bytearray(top)
    for a, b in img.mem.items():
        out[a] = b
    return bytes(out)


class _Image:
    def __init__(self, data):
        self.mem = {a: b for a, b in enumerate(data) if b}


class V1bRef:
    """Draft 1b's simulator with the interface the lockstep runs use."""

    def __init__(self, image, inp=b""):
        assert len(image) <= RAM_SIZE
        self.m = Machine32(isas.get("v1b"), _Image(image), inp)

    @property
    def instructions(self):
        return self.m.instructions

    def step(self):
        self.m.step()

    def state(self):
        m = self.m
        return {"r": list(m.r[1:16]), "hi": m.hi, "pc": m.pc,
                "nzcv": m.n << 3 | m.z << 2 | m.c << 1 | m.v}


def asm_program(path):
    meta = testing.metadata(path)
    img = asmcore.assemble_file(isas.get("v1b"), path)
    name = os.path.basename(path)[:-2]
    return _bytes(img), meta["input"], testing.expected_output(name)


def c_program(path):
    from heron.studies.c_compiler.cc import driver
    name = os.path.basename(path)[:-2]
    asm = os.path.join(testing.program_dir("v1b"), name + ".s")
    inp = testing.metadata(asm)["input"] if os.path.exists(asm) else b""
    _, img, _ = driver.build([path], "v1b", program=driver.Program("v1b"))
    return _bytes(img), inp, testing.expected_output(name)


def guest_programs(isa):
    from . import toolchain
    progs = {}
    for path in testing.program_paths(isa_name="v1b"):
        name = os.path.basename(path)[:-2]
        progs[name] = lambda path=path: asm_program(path)
    for name in toolchain.program_names():
        path = os.path.join(toolchain.PROGRAMS, name + ".c")
        progs["c-" + name] = lambda path=path: c_program(path)
    return progs
