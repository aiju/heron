"""Egret (studies/egret) on draft 1b and on v1bl.

The VM is C, so the C compiler's v1bl backend ports most of it. The rest:

- vm/rt_v1bl.s: the start code, with setjmp and longjmp keeping the return
  address the call left in r7;
- the hand-written interpreter loop, from interp_v1b.s as build.py puts it
  together, with the one change it needs: _asm_run calls C, so it saves r7
  with r8-r14. Sends don't use CALL at all (frames are in memory and the
  loop dispatches with JMP); r7 is a send's argument count, never live
  across a call to C;
- the JIT (variant jit): egret's jit.c has the changes under __V1BL__, which the
  C compiler defines for v1bl. A method's prologue stores r7 into its
  frame, where the return goes through, instead of popping the return
  address; the stubs that call C keep r7 on the stack meanwhile; and a
  send through the method cache passes its bytecode in r5, not r7.
  vm/jit_v1bl.s is the glue, from jit_v1b.s.

Programs run as egret's bench runs them: the VM compiles the prelude and
the program from the console input, then runs it. The empty program's
cycles (start-up and the prelude) are taken off.
"""

import os

from heron.infra import isas
from heron.studies.egret import build
from heron.studies.egret.programs import catalogue
from heron.studies.v1_isa.sim32 import Machine32

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ("c", "asm", "jit")
_images = {}


def interp_v1bl():
    """The hand-written interpreter for v1bl, from interp_v1b.s."""
    src = build.asm_interpreter("v1b")
    for a, b in (("_asm_run:\n        SAVE r8-r14", "_asm_run:\n        SAVE r7-r14"),
                 ("        RESTORE r8-r14\n        RET", "        RESTORE r7-r14\n        RET")):
        assert src.count(a) == 1, a
        src = src.replace(a, b)
    return src


def compile_v1bl(variant):
    """The VM for v1bl, as build.compile_heron builds it for 1b."""
    from heron.infra import link as L
    from heron.studies.c_compiler.cc import driver
    pre = build.prelude_c()
    p = driver.Program("v1bl")
    defs = {} if variant == "c" else {"EGRET_ASM": "1"}
    if variant == "jit":
        defs["EGRET_JIT"] = "1"
    for s in build.SOURCES:
        p.add_file(os.path.join(build.VM, s), [build.VM], defs)
    p.add_file(pre, [build.VM])
    objs = [driver.assemble("v1bl", driver.unit_assembly(u, "v1bl"),
                            os.path.basename(u.path)[:-2] + ".o") for u in p.units]
    if variant in ("asm", "jit"):
        objs.append(driver.assemble("v1bl", interp_v1bl(), "interp_v1bl.o"))
    if variant == "jit":
        with open(os.path.join(HERE, "vm", "jit_v1bl.s")) as f:
            objs.append(driver.assemble("v1bl", build.asm_layout() + f.read(), "jit_v1bl.o"))
    with open(os.path.join(HERE, "vm", "rt_v1bl.s")) as f:
        objs.insert(0, driver.assemble("v1bl", f.read(), "rt_v1bl.o"))
    return L.link(objs, [driver.library("v1bl")[0]], "v1bl")


def image(isa, variant):
    """The VM's image (1b: egret's own build, cached by it)."""
    if (isa, variant) not in _images:
        _images[isa, variant] = (build.heron("v1b", None, variant) if isa == "v1b"
                                 else compile_v1bl(variant))
    return _images[isa, variant]


def machine(isa, variant, source, inp=b""):
    data = source if isinstance(source, bytes) else source.encode()
    if inp:
        data += b"\n__END__\n" + inp
    m = Machine32(isas.get(isa), image(isa, variant), inp=data)
    m.run(max_cycles=build.MAX_CYCLES)
    return m


def programs():
    return catalogue.names()
