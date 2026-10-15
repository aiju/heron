---
status: active
depends-on: [v1_isa, v2_isa]
reports: [11]
---

# A C compiler for drafts 1a, 1b and 2

A compiler from a subset of C89 to draft 1a, 1b and 2 assembly, through an
ISA-independent SSA IR, with a small C library. It links with hand-written
assembly through the object files and linker in `infra/`.

It depends on `v1_isa` for draft 1, its simulator and the program suite,
and on `v2_isa` for draft 2 and its simulator.

How it works, what it supports and how to use it: [compiler.md](compiler.md).
How good its code is: [report 0011](../../reports/0011-report-c-compiler.md).
Object files and linking C with assembly: [infra/linking.md](../../infra/linking.md).

```sh
heron c_compiler cc studies/c_compiler/programs/life.c --run --stats   # compile for 1b (or --isa v1a, v2) and run
heron c_compiler cc main.c studies/v1_isa/programs/v1b/lib/print.s --run   # C and assembly linked together
heron c_compiler bench [--write]          # compiled C against the hand-written programs (--write: report 0011's tables)
heron c_compiler bench --isa v2           # draft 2's compiled C against 1b's and the hand-written draft 2 programs
python3 studies/c_compiler/tests/cc/fuzz.py   # random programs against gcc
```
