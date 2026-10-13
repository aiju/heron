---
status: active
depends-on: [v1_isa]
reports: [11]
---

# A C compiler for drafts 1a and 1b

A compiler from a subset of C89 to draft 1a and 1b assembly, through an
ISA-independent SSA IR, with a small C library. It links with hand-written
assembly through the object files and linker in `infra/`.

It depends on `v1_isa` for the ISAs, the simulator and the program suite.
