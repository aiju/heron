"""The unit tests' small guest programs, assembled once so that the tests
need no outside toolchain: the source is asm/NAME.s, the bytes are in
asm/bytes.json. After changing a source, rerun (needs clang, ld.lld,
llvm-objcopy and cc65's ca65 and ld65):

    python3 -m heron.studies.v2_guests.tests.asm_programs
"""

import json
import os
import subprocess
import tempfile

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "asm")
BYTES = os.path.join(HERE, "bytes.json")
CLANG = {"rv32": ["--target=riscv32-unknown-elf", "-march=rv32im", "-mabi=ilp32", "-mno-relax"],
         "thumb": ["--target=thumbv6m-none-eabi", "-mcpu=cortex-m0"],
         "thumb_user": ["--target=thumbv6m-none-eabi", "-mcpu=cortex-m0"]}
M6502_CFG = 'MEMORY { RAM: start = $0400, size = $1000, file = %O; }\n' \
            'SEGMENTS { CODE: load = RAM, type = rw; }\n'


def load(name):
    """A program's bytes (the 6502's from 0x400, the others from 0)."""
    with open(BYTES) as f:
        return bytes.fromhex(json.load(f)[name])


def assemble(name):
    src = os.path.join(HERE, name + ".s")
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out.bin")
        if name == "m6502":
            cfg = os.path.join(d, "link.cfg")
            with open(cfg, "w") as f:
                f.write(M6502_CFG)
            subprocess.run(["ca65", src, "-o", os.path.join(d, "m.o")], check=True)
            subprocess.run(["ld65", "-C", cfg, os.path.join(d, "m.o"), "-o", out], check=True)
        else:
            obj, elf = os.path.join(d, "p.o"), os.path.join(d, "p.elf")
            subprocess.run(["clang", *CLANG[name], "-c", src, "-o", obj], check=True)
            subprocess.run(["ld.lld", "-Ttext=0", "-e", "_start", "-o", elf, obj], check=True)
            subprocess.run(["llvm-objcopy", "-O", "binary", elf, out], check=True)
        with open(out, "rb") as f:
            return f.read()


def main():
    out = {name: assemble(name).hex() for name in ("rv32", "thumb", "thumb_user", "m6502")}
    with open(BYTES, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"wrote {BYTES}")


if __name__ == "__main__":
    main()
