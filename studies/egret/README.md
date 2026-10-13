---
status: active
depends-on: [c_compiler, v1_isa]
reports: [17]
---

# Egret: a small object language on draft 1b

Egret is a friendly object language in the space between Smalltalk, Ruby
and Python, made up for this study ([language.md](language.md)):
everything is an object, every operation is a message, blocks are
closures with non-local return, and integers grow into big integers when
they need to. Its compiler, its bytecode interpreter and a compiler from
bytecode to machine code all run *on* the machine: the C compiler study
compiles the VM for draft 1b, and the VM compiles Egret source it reads
from the console, prelude and program alike.

The point is not the language but the machine: what an implementation of
a language like this spends its cycles on, and which changes to the
instruction set or the system would help it. The findings are
[report 0017](../../reports/0017-report-egret.md).

The VM comes in three builds, which run the same programs to the same
output:

- **asm**, the default: the interpreter loop by hand in draft 1b assembly
  (`vm/interp_v1b.s`), with the C loop as its slow path for the rare
  bytecodes.
- **c**: the interpreter loop in C (`interpret` in `vm/interp.c`),
  compiled by the C compiler study.
- **jit**: a template compiler from bytecode to draft 1b machine code
  (`vm/jit.c`), which compiles each method when it's first called, with
  inline caches; anything it doesn't compile runs in C.

| File | What's in it |
|---|---|
| `language.md` | The language |
| `vm/` | The VM in C: objects and memory (`mem.c`, `object.c`, `map.c`, `bigint.c`), the compiler (`lex.c`, `parse.c`, `compile.c`), the interpreter (`interp.c`), primitives (`prims.c`), the JIT (`jit.c`), start-up (`main.c`) |
| `vm/*_v1b.s` | Draft 1b assembly: the start code (`rt_v1b.s`), the hand-written interpreter loop (`interp_v1b.s`), the JIT's glue to C (`jit_v1b.s`) |
| `lib/prelude.eg` | The core library, in Egret |
| `programs/` | Programs: twelve ported from the draft 1 suite (same output, so they compare with the assembly and C versions), and Egret's own (Richards, binary trees, JSON, shapes, closures) |
| `build.py` | Builds the VM for the host (gcc) and for draft 1b (the C compiler study), and runs programs on either |
| `profile.py` | Where a run's cycles go: C functions by group, the interpreter by bytecode, native code by bytecode |
| `isa.py` | What ISA and system changes would save, from the marked sequences in `interp_v1b.s` and the native code's disassembly |
| `bench.py` | Every program on every build, and the report's tables |

```sh
heron egret run studies/egret/programs/queens.eg          # on the simulated draft 1b machine
heron egret run --variant jit --stats studies/egret/programs/richards.eg   # with the JIT, and where the cycles go
heron egret run --host studies/egret/programs/queens.eg   # on the host build of the VM
heron egret test [--heron [--variant asm|c|jit|all]]      # every program against its expected output
heron egret bench [--write]                               # the report's tables (a few minutes)
heron test egret                                          # the unit tests
```

## Notes

- The VM image is about 140 KB (185 KB with the JIT) and sits below the
  console input buffer at 0x30000; the JIT build leaves 8 KB.
- Two C compiler bugs are worked around here rather than fixed: the C
  compiler addresses its switch tables with 16 bits, which fails once the
  code passes 32 KB, so `build.py` declares them `.far`; and it gives an
  array declared `extern T a[]` the size of that declaration rather than
  of its definition, so `egret.h` sizes `prim_table`.
- `EGRET_SLOWCOUNT` (a define for `build.machine`) counts the bytecodes the
  asm loop or the JIT hands to C, in `egret_slowcount`.
