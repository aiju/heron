"""Programs for the 6502 guest.

- `functional`: Klaus Dormann's 6502 functional test (GPL-3.0, github.com/
  Klaus2m5/6502_65C02_functional_tests), every documented instruction and
  mode with their flags, decimal mode included. Fetched into
  build/v2_guests/6502/ the first time; its success loop is patched to
  JAM (which halts), and RESET to its start, 0x0400. A failure is a
  branch or jump to itself, which the harness stops at.
- the C programs, compiled with cc65 (`cl65`, if installed): int is 16
  bits there, so the programs that need 32-bit ints print something else;
  their output is checked against the reference interpreter's.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request

from heron import BUILD

from . import toolchain

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.join(HERE, "sw", "m6502")
# the programs whose output with 16-bit ints is the suite's expected output
SUITE_OK = ("hello", "sieve", "queens", "sort", "life", "bst", "wordfreq", "crc")

OUT = os.path.join(BUILD, "v2_guests", "6502")
URL = ("https://raw.githubusercontent.com/Klaus2m5/6502_65C02_functional_tests/master/"
       "bin_files/6502_functional_test.bin")
SUCCESS = 0x3469


def functional():
    path = os.path.join(OUT, "6502_functional_test.bin")
    if not os.path.exists(path):
        os.makedirs(OUT, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    d = bytearray(open(path, "rb").read())
    d[SUCCESS] = 0x02
    d[0xFFFC], d[0xFFFD] = 0x00, 0x04
    return bytes(d)


def cc65_available():
    return shutil.which("cl65") is not None


def build_c(name):
    """A C program compiled with cc65 for the guest: a 64 KB image."""
    src = os.path.join(toolchain.PROGRAMS, name + ".c")
    files = [os.path.join(SW, f) for f in ("crt0.s", "io.c", "link.cfg")] + [src]
    h = hashlib.sha1()
    for f in files:
        h.update(open(f, "rb").read())
    out = os.path.join(OUT, f"{name}-{h.hexdigest()[:12]}.bin")
    if not os.path.exists(out):
        os.makedirs(OUT, exist_ok=True)
        # cl65 leaves its object files next to the sources: compile copies
        with tempfile.TemporaryDirectory(dir=OUT) as tmp:
            for f in files:
                shutil.copy(f, tmp)
            r = subprocess.run(["cl65", "-t", "none", "-O", "-C", "link.cfg", "-o", out,
                                "crt0.s", "io.c", name + ".c", "none.lib"],
                               capture_output=True, text=True, cwd=tmp)
        if r.returncode:
            raise RuntimeError(f"cl65 {name}: {r.stdout}{r.stderr}")
    with open(out, "rb") as f:
        return f.read()


def expected_c(name, image, inp):
    """The suite's expected output where 16-bit ints give it, else the
    reference interpreter's."""
    if name in SUITE_OK:
        return toolchain.expected(name)[1]
    from .m6502_ref import M6502
    return bytes(M6502(image, inp).run().out)


def guest_programs(isa):
    progs = {"functional": lambda: (functional(), b"", None)}
    if cc65_available():
        def one(name):
            def get():
                img = build_c(name)
                inp = toolchain.expected(name)[0]
                return img, inp, expected_c(name, img, inp)
            return get
        for name in toolchain.program_names():
            progs[name] = one(name)
    return progs
