---
status: active
depends-on: [v1_isa]
reports: [16]
---

# A Lisp for draft 1b

A small Lisp that runs on the draft 1b machine (the instruction-level
simulator): a reader, a printer, an interpreter and a copying garbage
collector, written in 1b assembly, and a compiler to 1b code, written in
the Lisp and running on the machine. It's an experiment, not a product:
the point is to see what a Lisp needs from the instruction set and the
system, and what changes would help it. The findings are in
[report 0016](../../reports/0016-report-lisp.md).

| File | What's in it |
|---|---|
| [language.md](language.md) | The language: data, special forms, procedures, errors |
| [implementation.md](implementation.md) | How it runs on 1b: values, memory, the collector, the interpreter, the calling convention |
| [compiler.md](compiler.md) | The compiler, and the saved image the compiled runs start from |
| [isa.md](isa.md) | v1bx: 1b with a tagged register mode, the study's ISA experiment |
| `rt/` | The runtime, in 1b assembly: `start.s` (memory map, top level, traps), `gc.s`, `read.s`, `print.s`, `eval.s` (the interpreter), `prims.s`, `code.s` (support for compiled code) |
| `prelude.lisp` | The parts of the language written in Lisp, read at start-up |
| `compiler.lisp` | The compiler |
| `build.py` | Assembles the runtime, with the tables it generates (static symbols, primitives) |
| `machine.py` | Runs programs on the simulator; makes the saved images |
| `measure.py`, `whatif.py`, `report.py` | Measurements: cycles, profiles, what ISA and system changes would save, the tables of report 0016 |
| `reference.py` | An independent reference interpreter in Python, which writes the expected output |
| `programs/` | Benchmarks: Gabriel-style programs (tak, deriv, boyer, ...) and their expected output |
| `tests/lisp/` | Tests of every part of the language, with expected output |

```sh
heron lisp run studies/lisp/programs/tak.lisp --stats --profile   # interpret on the 1b simulator
heron lisp run -c studies/lisp/programs/tak.lisp --stats          # compile, then run
heron lisp run -c --features tagged studies/lisp/programs/tak.lisp  # ... with v1bx's tagged mode
heron lisp ref studies/lisp/programs/tak.lisp                     # run on the reference interpreter
heron lisp test                                                   # every program and test against its expected output
heron lisp test -c                                                # the same, compiled (also --features tagged)
heron lisp report --write                                         # the tables of report 0016 (about 2 minutes)
heron test lisp                                                   # the study's unit tests
python3 studies/lisp/reference.py --write-expected                # rewrite the expected output
```

The first compiled run makes the saved image, which takes about 20 seconds;
it's kept in `build/lisp/` and made again when the runtime or the compiler
changes.
