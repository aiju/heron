"""ISA v1bl: draft 1b with a link register. `BSR` and `CALL` (every form)
put the return address in r7 instead of pushing it, and `RET` jumps to r7.
Everything else, the encoding included, is draft 1b's; interrupts and
traps still push the PC and the flags. The simulator runs it
(studies/v1_isa/isa, Isa::V1bl)."""

from heron.studies.v1_isa.v1b import *  # noqa: F401,F403

NAME = "v1bl"
DESCRIPTION = "draft 1b with a link register: BSR and CALL put the return address in r7"
LINK = 7
