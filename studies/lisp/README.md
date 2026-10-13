---
status: active
depends-on: [v1_isa]
reports: []
---

# A Lisp for draft 1b

A small Lisp that runs on the draft 1b machine (the instruction-level
simulator): a reader, a printer, an interpreter and a copying garbage
collector, written in 1b assembly. It's an experiment, not a product: the
point is to see what a Lisp needs from the instruction set and the
system, and what changes would help it.

| File | What's in it |
|---|---|
| [language.md](language.md) | The language: data, special forms, procedures, errors |
| `rt/` | The runtime, in 1b assembly: `start.s` (memory map, top level, traps), `gc.s`, `read.s`, `print.s`, `eval.s` (the interpreter), `prims.s` |
| `prelude.lisp` | The parts of the language written in Lisp, read at start-up |
| `build.py` | Assembles the runtime, with the tables it generates (static symbols, primitives) |
| `reference.py` | An independent reference interpreter in Python, which writes the expected output |
| `programs/` | Benchmarks: Gabriel-style programs (tak, deriv, boyer, ...) and their expected output |
| `tests/lisp/` | Tests of every part of the language, with expected output |

```sh
heron lisp run studies/lisp/programs/tak.lisp --stats --profile   # run on the 1b simulator
heron lisp ref studies/lisp/programs/tak.lisp                     # run on the reference interpreter
heron lisp test                                                   # every program and test against its expected output
heron test lisp                                                   # the reference's unit tests
python3 studies/lisp/reference.py --write-expected                # rewrite the expected output
```
