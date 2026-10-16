"""The C programs compiled for a guest instruction set with clang and
linked with ld.lld into a flat image from address 0.

The programs are the C compiler study's (studies/c_compiler/programs),
with its C library (cc/lib), so the same source runs natively and on
every guest, and the output is checked against the program suite's
expected output. Only stdarg.h is replaced (sw/include), since the
library's is the Heron compiler's own. Each target adds its start-up code
(sw/<target>/crt0.s) and whatever helpers clang calls for it (rt.c).

Images are cached in build/v2_guests/cc/ by everything they're made from.
"""

import hashlib
import os
import shutil
import subprocess
from types import SimpleNamespace

from heron import BUILD, ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.join(ROOT, "studies", "c_compiler")
PROGRAMS = os.path.join(CC, "programs")
LIB = ["stdio.c", "stdlib.c", "string.c", "ctype.c"]
OUT = os.path.join(BUILD, "v2_guests", "cc")

# target: clang's triple and flags
TARGETS = {
    "rv32": ["--target=riscv32-unknown-elf", "-march=rv32im", "-mabi=ilp32", "-mno-relax"],
    "thumb": ["--target=thumbv6m-none-eabi", "-mcpu=cortex-m0"],
}
# a user process under mixed.py's kernel: its own start-up (exit is SVC #0)
# and console (a page of its own address space, not the supervisor's I/O
# window); the rest from the plain target
TARGETS["thumb-user"] = TARGETS["thumb"]
# sw/ files and include directories, for a target that isn't just sw/<target>
SW_FILES = {"thumb-user": ["mixed/crt0_thumb.s", "thumb/rt.c"]}
SW_INCLUDE = {"thumb-user": ["mixed/include"]}
CFLAGS = ["-O2", "-ffreestanding", "-nostdinc", "-fno-pic", "-ffunction-sections",
          "-fdata-sections"]


def available():
    """Whether clang, ld.lld and llvm-objcopy are on the path."""
    return all(shutil.which(t) for t in ("clang", "ld.lld", "llvm-objcopy", "llvm-nm"))


def program_names():
    return sorted(f[:-2] for f in os.listdir(PROGRAMS) if f.endswith(".c"))


def _sources(target, name):
    srcs = [os.path.join(PROGRAMS, name + ".c")]
    srcs += [os.path.join(CC, "cc", "lib", f) for f in LIB]
    if target in SW_FILES:
        return srcs + [os.path.join(HERE, "sw", f) for f in SW_FILES[target]]
    tdir = os.path.join(HERE, "sw", target)
    for f in sorted(os.listdir(tdir)):
        if f.endswith((".c", ".s", ".S")):
            srcs.append(os.path.join(tdir, f))
    return srcs


def _includes(target):
    own = [os.path.join(HERE, "sw", d) for d in SW_INCLUDE.get(target, [target + "/include"])]
    inc = [d for d in own if os.path.isdir(d)]
    return inc + [os.path.join(HERE, "sw", "include"), os.path.join(CC, "cc", "include")]


def _tag(target, name):
    h = hashlib.sha1()
    h.update(repr((TARGETS[target], CFLAGS)).encode())
    files = _sources(target, name) + [os.path.join(HERE, "sw", "link.ld")]
    for d in _includes(target):
        files += [os.path.join(d, f) for f in sorted(os.listdir(d))]
    for f in files:
        h.update(f.encode())
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r.stdout


def build(target, name):
    """Compile and link program `name` for `target`. Returns an image:
    .data (bytes from address 0), .symbols {name: address}, .path (the ELF)."""
    flags = TARGETS[target]
    tag = _tag(target, name)
    odir = os.path.join(OUT, target)
    elf = os.path.join(odir, f"{name}-{tag}.elf")
    binf = elf[:-4] + ".bin"
    if not os.path.exists(binf):
        os.makedirs(odir, exist_ok=True)
        objs = []
        for src in _sources(target, name):
            obj = os.path.join(odir, f"{name}-{tag}-{os.path.basename(src)}.o")
            inc = [f"-I{d}" for d in _includes(target)]
            _run(["clang", *flags, *CFLAGS, *inc, "-c", src, "-o", obj])
            objs.append(obj)
        _run(["ld.lld", "-T", os.path.join(HERE, "sw", "link.ld"), "--gc-sections",
              "-o", elf, *objs])
        _run(["llvm-objcopy", "-O", "binary", elf, binf])
        for o in objs:
            os.remove(o)
    with open(binf, "rb") as f:
        data = f.read()
    syms = {}
    for line in _run(["llvm-nm", "--defined-only", elf]).splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return SimpleNamespace(data=data, symbols=syms, path=elf, end=syms.get("_end", len(data)))


def disassemble(target, name):
    """The program's disassembly, for debugging."""
    img = build(target, name)
    return _run(["llvm-objdump", "-d", "--no-show-raw-insn", img.path])


def expected(name):
    """(input, expected output) of a program, from the suite's."""
    from heron.studies.v1_isa import testing
    asm = os.path.join(testing.program_dir("v1b"), name + ".s")
    inp = testing.metadata(asm)["input"] if os.path.exists(asm) else b""
    return inp, testing.expected_output(name)


def guest_programs(isa):
    """{name: () -> (image, input, expected output)} for the C programs."""
    def one(name):
        def get():
            inp, exp = expected(name)
            return build(isa, name).data, inp, exp
        return get
    return {name: one(name) for name in program_names()}
