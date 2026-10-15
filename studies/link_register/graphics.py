"""The graphics library's 1b kernels (studies/graphics/asm/v1b) for v1bl.

Each is edited from its 1b source here, as text, rather than copied: an
edit has to match exactly once, so a change to a kernel shows up as an
error instead of a stale copy.

- blit, fill, line, ramp: leaves that use r7 as data. They save it with
  the callee-saved registers they already save (SAVE r7-rN), as a compiler
  would.
- span: the same, and its stack arguments are 4 bytes nearer before the
  SAVE, with no return address on the stack. After SAVE r7-r10 they are
  where they were after SAVE r8-r10 and the return address.
- expand: every register is in use, and the general path calls an emit
  routine for the depth (CALL [sp + EMIT]) with the depth's table in r7.
  The table goes in the general path's frame, and the emit routines that
  use it push the return address and load the table; emit0, which doesn't
  use it, returns through r7.
"""

import os

from heron import ROOT

GFX_ASM = os.path.join(ROOT, "studies", "graphics", "asm", "v1b")

EDITS = {
    "blit": [("        SAVE r8-r14", "        SAVE r7-r14"),
             (".done:  RESTORE r8-r14", ".done:  RESTORE r7-r14")],
    "fill": [("        SAVE r8-r14", "        SAVE r7-r14"),
             (".done:  RESTORE r8-r14", ".done:  RESTORE r7-r14")],
    "line": [("        SAVE r8-r14", "        SAVE r7-r14"),
             (".done:  RESTORE r8-r14", ".done:  RESTORE r7-r14")],
    "ramp": [("        SAVE r8-r12", "        SAVE r7-r12"),
             (".bout:  RESTORE r8-r12", ".bout:  RESTORE r7-r12"),
             ("        SAVE r8-r14", "        SAVE r7-r14"),
             ("        RESTORE r8-r14", "        RESTORE r7-r14")],
    "span": [("        MOV  r5, [sp + 8]       ; the rop",
              "        MOV  r5, [sp + 4]       ; the rop (v1bl: no return address below it)"),
             ("        SAVE r8-r10", "        SAVE r7-r10"),
             (".done:  RESTORE r8-r10", ".done:  RESTORE r7-r10")],
    "expand": [
        ("FRAME   = 32", "TABLE   = 32                    ; v1bl: the table, for the emit routines\n"
                         "FRAME   = 36"),
        ("        SAVE r8-r14", "        SAVE r7-r14"),
        (".out:   RESTORE r8-r14", ".out:   RESTORE r7-r14"),
        (".general:\n        SUB  sp, #FRAME",
         ".general:\n        SUB  sp, #FRAME\n        ST   r7, [sp + TABLE]"),
        ("; The emit routines: chunk r11 (not 0), destination r14.",
         "; The emit routines: chunk r11 (not 0), destination r14. Those that\n"
         "; need the table push the return address (v1bl: it's in r7) and load\n"
         "; the table from the frame, just above it."),
        (".emit1: ZXB  r13, r11", ".emit1: PUSH r7\n        MOV  r7, [sp + 4 + TABLE]\n"
                                  ".e1l:   ZXB  r13, r11"),
        ("        BNE  .emit1\n        RET", "        BNE  .e1l\n        JMP  [sp]+"),
        (".emit2: ZXB  r13, r11", ".emit2: PUSH r7\n        MOV  r7, [sp + 4 + TABLE]\n"
                                  ".e2l:   ZXB  r13, r11"),
        ("        BNE  .emit2\n        RET", "        BNE  .e2l\n        JMP  [sp]+"),
        (".emit3: ZXB  r13, r11", ".emit3: PUSH r7\n        MOV  r7, [sp + 4 + TABLE]\n"
                                  ".e3l:   ZXB  r13, r11"),
        ("        BNE  .emit3\n        RET", "        BNE  .e3l\n        JMP  [sp]+"),
    ],
}


def kernel(name):
    """The v1bl source of the kernel name (blit, expand, ...)."""
    with open(os.path.join(GFX_ASM, name + ".s")) as f:
        src = f.read()
    for old, new in EDITS[name]:
        if src.count(old) != 1:
            raise RuntimeError(f"graphics/asm/v1b/{name}.s has changed: {old!r} "
                               f"is there {src.count(old)} times")
        src = src.replace(old, new)
    return f"; {name}.s for v1bl, edited by studies/link_register/graphics.py\n" + src





_images = {}


def image(isa, kernels):
    """The graphics program (studies/graphics/build.py's image) for isa,
    with the C kernels or the assembly ones; for v1bl, the edited kernels.
    mark.s (a HALT and a RET) is 1b's on both."""
    from heron.studies.graphics import build
    if isa == "v1b":
        return build.image("v1b", kernels)
    if kernels not in _images:
        from heron.infra.objtools import assemble_object
        from heron.studies.c_compiler.cc import driver
        from heron.studies.graphics import fonts
        p = driver.Program("v1bl")
        defines = {"GFX_ASM": "1"} if kernels else {}
        for path in [os.path.join(build.SRC, "main.c")] + build.lib_sources():
            p.add_file(path, [build.SRC], defines)
        p.add_object(assemble_object("v1bl", os.path.join(GFX_ASM, "mark.s")))
        if kernels:
            for name in sorted(EDITS):
                p.add_object(driver.assemble("v1bl", kernel(name), name + ".o"))
        p.add_object(driver.assemble("v1bl", fonts.data_asm(), "fonts.o"))
        p.add_library()
        _images[kernels] = p.link()
    return _images[kernels]


def run(isa, kernels, scene, depth):
    """A scene at a depth: (the phases match the host's, {"instructions",
    "cycles": {config: n}, "keys": Counter of (pc, key)}) over its phases,
    the set-up phases (named _...) left out, as the graphics bench does."""
    from collections import Counter
    from heron.studies.graphics import run as runmod
    phases = runmod.run(image(isa, kernels), isa, scene, depth, profile=True)
    ok = not runmod.check(phases, scene, depth)
    tot = {"instructions": 0, "cycles": Counter(), "keys": Counter()}
    for p in phases:
        if p.name.startswith("_"):
            continue
        tot["instructions"] += p.instructions
        tot["cycles"].update(p.cycles)
        tot["keys"].update(p.keys)
    return ok, tot
