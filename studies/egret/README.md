---
status: active
depends-on: [c_compiler, v1_isa]
reports: []
---

# Egret: a small object language on draft 1b

Egret is a friendly object language in the space between Smalltalk, Ruby
and Python, made up for this study: everything is an object, every
operation is a message, blocks are closures with non-local return, and
integers grow into big integers when they need to. Its compiler and its
bytecode interpreter are C, and run *on* the machine: the C compiler study
compiles the VM for draft 1b, and the VM compiles Egret source it reads
from the console, prelude and program alike.

The point is not the language but the machine: what an implementation of
a language like this spends its cycles on, and which changes to the
instruction set or the system would help it.

| File | What's in it |
|---|---|
| `vm/` | The VM in C: objects and memory (`mem.c`, `object.c`, `map.c`, `bigint.c`), the compiler (`lex.c`, `parse.c`, `compile.c`), the interpreter (`interp.c`), primitives (`prims.c`), start-up (`main.c`), and `rt_v1b.s`, the start code for draft 1b |
| `lib/prelude.eg` | The core library, in Egret |
| `programs/` | Programs: twelve ported from the draft 1 suite (same output, so they compare with the assembly and C versions), and Egret's own |
| `build.py` | Builds the VM for the host (gcc) and for draft 1b (the C compiler study), and runs programs on either |

```sh
heron egret run studies/egret/programs/queens.eg          # on the simulated draft 1b machine
heron egret run --host studies/egret/programs/queens.eg   # on the host build of the VM
heron egret test [--heron]                                # every program against its expected output
```
