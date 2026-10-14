"""Building the GUI: one image for draft 1b with Egret's VM (its
hand-written interpreter loop), the graphics library with its 1b
kernels and fonts, and this study's C (src/), started by src/rt_v1b.s.
And the desktop's source (lib/*.eg), which the VM reads from the console
and compiles at start-up, as it would any program.

The image goes to build/egret_gui/, named by a hash of everything it's
made from, as Egret's own builds are.
"""

import glob
import os
import re

from heron import ROOT
from heron.studies.egret import build as egret

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
LIB = os.path.join(HERE, "lib")
GFX = os.path.join(ROOT, "studies", "graphics")
GFX_SRC = os.path.join(GFX, "src")
GFX_ASM = os.path.join(GFX, "asm", "v1b")
BUILD = os.path.join(ROOT, "build", "egret_gui")
ISA = "v1b"

OURS = ["gui_prims.c", "gwm.c"]
GFX_LIB = ["theme.c", "gfx.c", "line.c", "ellipse.c", "raster.c", "blit.c", "expand.c",
           "font.c", "ttf.c"]
# the desktop, in the order it's compiled
DESKTOP = ["gui.eg", "widgets.eg", "apps.eg", "desktop.eg"]


def _inputs():
    files = [os.path.join(SRC, f) for f in os.listdir(SRC)] + [os.path.abspath(__file__)]
    files += [os.path.join(GFX_SRC, f) for f in GFX_LIB + ["gfx.h", "theme.h"]]
    files += glob.glob(os.path.join(GFX_ASM, "*.s"))
    files += glob.glob(os.path.join(GFX, "fonts", "*"))
    return files + egret._vm_files() + egret._compiler_files()


def image():
    """The linked image (heron.infra.link.LinkedImage), built if needed."""
    from heron.infra import obj as O
    from heron.infra.link import load_executable
    key = egret._digest(_inputs(), ISA)
    path = os.path.join(BUILD, f"egret-gui-{key}.out")
    if not os.path.exists(path):
        os.makedirs(BUILD, exist_ok=True)
        img = compile_image()
        img.obj.write(path + ".tmp")
        os.replace(path + ".tmp", path)
    return load_executable(O.read_object(path))


def _assemble_units(p):
    from heron.studies.c_compiler.cc import driver
    objs = []
    for u in p.units:
        text = driver.unit_assembly(u, ISA)
        # as studies/egret/build.py does: switch tables past 32 KB need .far
        tables = re.findall(r"^(\w+_jt\d+):", text, re.M)
        if tables:
            text = "        .far " + ", ".join(tables) + "\n" + text
        objs.append(driver.assemble(ISA, text, os.path.basename(u.path)[:-2] + ".o"))
    return objs


# The scan converter's edge tables are 52 KB each, for polygons and for
# glyphs; that much RAM is Egret's heap here, and the desktop's polygons
# and glyphs need far fewer edges.
SHRINK = {"raster.c": [("#define MAXE 1024", "#define MAXE 256")],
          "ttf.c": [("glyph_edges[1024]", "glyph_edges[512]"),
                    ("rs_init(&r, glyph_edges, 1024)", "rs_init(&r, glyph_edges, 512)")]}


def _shrunk(path):
    with open(path) as f:
        text = f.read()
    for old, new in SHRINK.get(os.path.basename(path), []):
        if old not in text:
            raise RuntimeError(f"{path} has changed: no {old!r} to shrink")
        text = text.replace(old, new)
    return text


def compile_image():
    from heron.infra import link as L
    from heron.infra.objtools import assemble_object
    from heron.studies.c_compiler.cc import driver
    from heron.studies.graphics import fonts
    p = driver.Program(ISA)
    vm = {"EGRET_ASM": "1", "EGRET_GUI": "1"}
    inc = [SRC, egret.VM, GFX_SRC]
    for s in egret.SOURCES:
        p.add_file(os.path.join(egret.VM, s), inc, vm)
    p.add_file(egret.prelude_c(), [egret.VM])
    for s in OURS:
        p.add_file(os.path.join(SRC, s), inc, vm)
    # the font cache goes in VRAM (gui_alloc), not the C heap, which would
    # grow into Egret's memory
    gfx = {"GFX_ASM": "1", "malloc": "gui_alloc", "calloc": "gui_calloc"}
    for s in GFX_LIB:
        path = os.path.join(GFX_SRC, s)
        p.add_file(path, [GFX_SRC], gfx, text=_shrunk(path))
    objs = _assemble_units(p)
    with open(os.path.join(SRC, "rt_v1b.s")) as f:
        objs.insert(0, driver.assemble(ISA, f.read(), "rt_v1b.o"))
    objs.append(driver.assemble(ISA, egret.asm_interpreter(ISA), "interp_v1b.o"))
    for path in sorted(glob.glob(os.path.join(GFX_ASM, "*.s"))):
        if os.path.basename(path) != "mark.s":
            objs.append(assemble_object(ISA, path))
    objs.append(driver.assemble(ISA, fonts.data_asm(), "fonts.o"))
    return L.link(objs, [driver.library(ISA)[0]], ISA)


def desktop_source():
    """The desktop's Egret source, as the console input."""
    out = []
    for name in DESKTOP:
        path = os.path.join(LIB, name)
        if os.path.exists(path):
            with open(path) as f:
                out.append(f.read())
    return "\n".join(out).encode()
