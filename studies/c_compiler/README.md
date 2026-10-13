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

How it works, what it supports and how to use it: [compiler.md](compiler.md).
How good its code is: [report 0011](../../reports/0011-report-c-compiler.md).
Object files and linking C with assembly: [infra/linking.md](../../infra/linking.md).

```sh
heron c_compiler cc studies/c_compiler/programs/life.c --run --stats   # compile for 1b (or --isa v1a) and run
heron c_compiler cc main.c studies/v1_isa/programs/v1b/lib/print.s --run   # C and assembly linked together
heron c_compiler bench [--write]          # compiled C against the hand-written programs (--write: report 0011's tables)
python3 studies/c_compiler/tests/cc/fuzz.py   # random programs against gcc
```
