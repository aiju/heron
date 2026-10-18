"""Building the programs: their C (studies/c_compiler, for draft 2) and
assembly, linked with the runtime (rt/), the graphics library (gfx/),
the window manager (wm/) when they use it, the fonts and the C library.

Every library file goes into every program; the linker keeps what the
program reaches (each function is a section of its own). The kernels
come in three variants:

    c     the C kernels
    asm   draft 2 assembly (gfx/asm/), the general instruction set
    blk   the same with the mini's block instructions (gfx/blk/): FILL,
          COPY, EXPAND and BLIT k (RFC 0041, 2.1)

C files compile to object files cached in build/mini_gfx/obj/, by their
text, the headers' and the defines.
"""

import glob
import hashlib
import os

from heron import BUILD
import heron.studies.v2_isa  # noqa: F401  (registers the ISA)
from heron.infra import obj as O
from heron.studies.c_compiler.cc import driver

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BUILD, "mini_gfx")
VARIANTS = ("c", "asm", "blk")
INCLUDE = [os.path.join(HERE, d) for d in ("rt", "gfx", "wm")]
LIBS = ["rt/rt.c", "rt/video.c", "rt/input.c", "rt/perf.c", "rt/palette.c"]
GFX = sorted(os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, "gfx", "*.c")))
WM = sorted(os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, "wm", "*.c")))
KERNELS = {v: sorted(os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, "gfx", v, "*.s")))
           for v in ("asm", "blk")}


def _headers():
    text = b""
    for d in INCLUDE:
        for p in sorted(glob.glob(os.path.join(d, "*.h"))):
            with open(p, "rb") as f:
                text += f.read()
    return text


def _key(path, defines, extra):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    h.update(extra)
    h.update(repr(sorted(defines.items())).encode())
    h.update(path.encode())
    return h.hexdigest()[:24]


def c_object(path, defines, include, headers):
    """A C file's object file, from the cache if it's there."""
    os.makedirs(os.path.join(OUT, "obj"), exist_ok=True)
    cache = os.path.join(OUT, "obj", f"{os.path.basename(path)}-{_key(path, defines, headers)}.o")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return O.ObjectFile.from_bytes(f.read(), os.path.basename(path)[:-2] + ".o")
    p = driver.Program("v2", need_main=False)
    p.add_file(path, include, defines)
    obj = p.objects()[0]
    with open(cache + ".tmp", "wb") as f:
        f.write(obj.to_bytes())
    os.replace(cache + ".tmp", cache)
    return obj


def asm_object(path, include=()):
    from heron.infra import asm as asmcore
    from heron.infra import isas
    a = asmcore.Assembler(isas.get("v2"), relocatable=True)
    with open(path) as f:
        text = f.read()
    a.load(path, text=text)
    return a.assemble_object(os.path.basename(path)[:-2] + ".o")


def text_object(name, text):
    from heron.infra import asm as asmcore
    from heron.infra import isas
    a = asmcore.Assembler(isas.get("v2"), relocatable=True)
    a.load(name, text=text)
    return a.assemble_object(name[:-2] + ".o")


_fonts = None


def fonts_object():
    global _fonts
    if _fonts is None:
        from . import fonts
        _fonts = text_object("fonts.s", fonts.data_asm())
    return _fonts


class Build:
    """A built program: the image, its symbols, and what it was built from."""

    def __init__(self, img, name, variant):
        self.img = img
        self.name = name
        self.variant = variant
        self.symbols = img.symbols
        # (address, name), for the profiler
        self.labels = sorted((a, n) for n, a in img.symbols.items() if not n.startswith("."))

    def code_size(self):
        return len(self.img.code_bytes()) if hasattr(self.img, "code_bytes") else 0


def build(sources, variant="c", defines=None, wm=False, name=None):
    """A program from its own files (paths relative to the study, .c and
    .s) with the runtime, the graphics library, the kernels of `variant`,
    the fonts and, with wm, the window manager."""
    if variant not in VARIANTS:
        raise ValueError(f"variant: one of {', '.join(VARIANTS)}")
    d = {"GFX_ASM": "1"} if variant in ("asm", "blk") else {}
    if variant == "blk":
        d["GFX_BLK"] = "1"
    d.update(defines or {})
    headers = _headers()
    include = INCLUDE + sorted({os.path.join(HERE, os.path.dirname(s)) for s in sources})
    p = driver.Program("v2", need_main=False)
    p.add_object(asm_object(os.path.join(HERE, "rt", "start.s")))
    files = LIBS + GFX + (WM if wm else []) + list(sources)
    for s in files:
        path = os.path.join(HERE, s)
        if s.endswith(".c"):
            p.add_object(c_object(path, d, include, headers))
        else:
            p.add_object(asm_object(path))
    if variant != "c":
        for s in KERNELS["asm"] + (KERNELS["blk"] if variant == "blk" else []):
            p.add_object(asm_object(os.path.join(HERE, s)))
    p.add_object(fonts_object())
    p.add_library()
    img = p.link()
    return Build(img, name or os.path.splitext(os.path.basename(sources[0]))[0], variant)
