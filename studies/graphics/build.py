"""Building the graphics programs.

For the machine: the C sources in src/ through the C compiler, the
assembly in asm/ISA/ (mark.s always; the kernels with asm=True, which also
compiles the C with GFX_ASM so that it leaves its own kernels out), and
the fonts as data (fonts.py), linked with the C library, for draft 1a or
1b. For the host: the same C with gcc, as the reference (host.c).
"""

import functools
import glob
import os
import shutil
import subprocess

from heron import ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
ASM = os.path.join(HERE, "asm")
OUT = os.path.join(ROOT, "build", "graphics")

# the library and the scenes; main.c (machine) or host.c (gcc) is added
LIB = ["scenes.c", "theme.c", "gfx.c", "line.c", "ellipse.c", "raster.c", "blit.c",
       "expand.c", "font.c", "ttf.c", "wm.c"]
ISAS = ("v1a", "v1b")


class BuildError(Exception):
    pass


def lib_sources():
    return [os.path.join(SRC, f) for f in LIB if os.path.exists(os.path.join(SRC, f))]


def asm_files(isa, kernels, stm=False):
    """mark.s, and with kernels every other .s in asm/ISA/; with stm also
    the store-multiple experiment in asm/ISA/stm/."""
    files = sorted(glob.glob(os.path.join(ASM, isa, "*.s")))
    files = [f for f in files if kernels or os.path.basename(f) == "mark.s"]
    if stm:
        files += sorted(glob.glob(os.path.join(ASM, isa, "stm", "*.s")))
    return files


@functools.lru_cache(maxsize=None)
def image(isa, kernels=False, stm=False):
    """The linked program for an ISA (heron.infra.link.LinkedImage); with
    kernels, the hand-written assembly kernels instead of the C ones; with
    stm (1b only), the store-multiple experiment on top."""
    from heron.studies.c_compiler.cc import driver
    from heron.studies.c_compiler.cc.lex import CompileError
    from heron.infra.objtools import assemble_object
    from heron.infra import asm as asmcore
    from . import fonts
    defines = {"GFX_ASM": "1"} if kernels or stm else {}
    if stm:
        defines["GFX_STM"] = "1"
    try:
        p = driver.Program(isa)
        for path in [os.path.join(SRC, "main.c")] + lib_sources():
            p.add_file(path, [SRC], defines)
        for path in asm_files(isa, kernels or stm, stm):
            p.add_object(assemble_object(isa, path))
        p.add_object(driver.assemble(isa, fonts.data_asm(), "fonts.o"))
        p.add_library()
        return p.link()
    except (CompileError, asmcore.AsmError) as e:
        raise BuildError(f"{isa}{' with kernels' if kernels else ''}{' and stm' if stm else ''}: {e}") from None


@functools.lru_cache(maxsize=None)
def selftest_image(isa, iters=200, stm=False):
    """src/selftest.c with the assembly kernels, for the machine (and with
    stm, the store-multiple experiment)."""
    from heron.studies.c_compiler.cc import driver
    from heron.studies.c_compiler.cc.lex import CompileError
    from heron.infra.objtools import assemble_object
    from heron.infra import asm as asmcore
    defines = {"GFX_ASM": "1", "ITERS": str(iters)}
    if stm:
        defines["GFX_STM"] = "1"
    try:
        p = driver.Program(isa)
        for f in ("selftest.c", "gfx.c", "blit.c", "expand.c", "line.c"):
            p.add_file(os.path.join(SRC, f), [SRC], defines)
        for path in asm_files(isa, True, stm):
            p.add_object(assemble_object(isa, path))
        p.add_library()
        return p.link()
    except (CompileError, asmcore.AsmError) as e:
        raise BuildError(f"selftest for {isa}: {e}") from None


def host_binary():
    """Build the host reference with gcc; returns its path."""
    gcc = shutil.which("gcc")
    if not gcc:
        raise BuildError("the host reference needs gcc")
    from . import fonts
    os.makedirs(OUT, exist_ok=True)
    data = os.path.join(OUT, "fonts.c")
    with open(data, "w") as f:
        f.write(fonts.data_c())
    exe = os.path.join(OUT, "host")
    cmd = [gcc, "-O2", "-funsigned-char", "-fwrapv", "-w", "-I", SRC, "-o", exe,
           os.path.join(SRC, "host.c"), data] + lib_sources()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise BuildError("gcc:\n" + r.stderr)
    return exe


def selftest_binary():
    gcc = shutil.which("gcc")
    if not gcc:
        raise BuildError("the self-test needs gcc")
    os.makedirs(OUT, exist_ok=True)
    exe = os.path.join(OUT, "selftest")
    srcs = [os.path.join(SRC, f) for f in ("selftest.c", "gfx.c", "blit.c", "expand.c", "line.c")]
    r = subprocess.run([gcc, "-O1", "-funsigned-char", "-fwrapv", "-w", "-I", SRC, "-o", exe] + srcs,
                       capture_output=True, text=True)
    if r.returncode:
        raise BuildError("gcc:\n" + r.stderr)
    return exe
