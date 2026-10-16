---
status: active
depends-on: [v1_isa, v2_isa]
reports: [18, 32]
---

# A Lisp for drafts 1b and 2

A small Lisp that runs on the draft 1b machine (the instruction-level
simulator): a reader, a printer, an interpreter and a copying garbage
collector, written in 1b assembly, and a compiler to 1b code, written in
the Lisp and running on the machine. It's an experiment, not a product:
the point is to see what a Lisp needs from the instruction set and the
system, and what changes would help it. The findings are in
[report 0018](../../reports/0018-report-lisp.md), and its appendix
specifies v1bx, 1b with a tagged register mode, the study's ISA
experiment.

It runs on draft 2 as well ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)),
with `--isa v2`: the runtime ported to draft 2 in `rt_v2/`, and the
compiler with a draft 2 backend. [Report 0032](../../reports/0032-report-lisp-egret-draft-2.md)
has the port and the measurements; implementation.md and compiler.md
say what's different on draft 2. 1b stays the default.

| File | What's in it |
|---|---|
| [language.md](language.md) | The language: data, special forms, procedures, errors |
| [implementation.md](implementation.md) | How it runs on 1b: values, memory, the collector, the interpreter, the calling convention |
| [compiler.md](compiler.md) | The compiler, and the saved image the compiled runs start from |
| `rt/` | The runtime, in 1b assembly: `start.s` (memory map, top level, traps), `gc.s`, `read.s`, `print.s`, `eval.s` (the interpreter), `prims.s`, `code.s` (support for compiled code) |
| `rt_v2/` | The same runtime in draft 2 assembly |
| `prelude.lisp` | The parts of the language written in Lisp, read at start-up |
| `compiler.lisp` | The compiler (for 1b) |
| `compiler_v2.lisp` | Its draft 2 backend: definitions that replace compiler.lisp's of the same names when the compiler is built for draft 2 |
| `build.py` | Assembles the runtime, with the tables it generates (static symbols, primitives) |
| `machine.py` | Runs programs on the simulator; makes the saved images; puts the draft 2 compiler together |
| `measure.py`, `whatif.py`, `report.py` | Measurements: cycles, profiles, what ISA and system changes would save, the tables of report 0018 |
| `report_v2.py` | Draft 2 against 1b: the tables of report 0032 |
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
heron lisp report --write                                         # the tables of report 0018 (about 2 minutes)
heron lisp test --isa v2 [-c] [--features tagged]                 # the same on draft 2 (tagged: its TADD and friends)
heron lisp run --isa v2 -c studies/lisp/programs/tak.lisp --stats # compile and run on draft 2
heron lisp report --isa v2 --write                                # draft 2 against 1b: report 0032's tables (about 15 minutes)
heron test lisp                                                   # the study's unit tests
python3 studies/lisp/reference.py --write-expected                # rewrite the expected output
```

The first compiled run makes the saved image, which takes about 20 seconds;
it's kept in `build/lisp/` (one per ISA and set of features) and made
again when the runtime or the compiler changes.
