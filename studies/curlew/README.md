---
status: active
depends-on: [v2_isa]
reports: [35]
---

# Curlew: a lazy, typed language for draft 2

Curlew is a small lazy functional language with Hindley–Milner types and
type classes, in the spirit of Haskell and Miranda, compiled on the host
into draft 2 code ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)). It's
an experiment, not a product: the point is to see what lazy evaluation
asks of the instruction set, and in particular whether draft 2's tagged
operations, which the Lisp put there, help a language whose checks are
for evaluation rather than for types. The findings are in
[report 0035](../../reports/0035-report-curlew.md).

A program is a function from its input to its output, both lazy strings,
as in Miranda. The compiler is Python and runs on the host: a front end
with layout, type inference and dictionary-passing type classes, an
optimiser over a small core language (inlining, specialisation,
case-of-case, strictness analysis), and a code generator in the style of
the STG machine. The runtime (start-up, the general apply, the update of
thunks, a copying collector, the tag trap) is draft 2 assembly, and the
programs run on the draft 2 instruction-level simulator.

| File | What's in it |
|---|---|
| [language.md](language.md) | The language: syntax, types and classes, the prelude, input and output, errors |
| [implementation.md](implementation.md) | How it runs: values and objects, the compiler's passes, the code, the calling convention, the runtime and the collector |
| `lexer.py`, `parse.py`, `surface.py`, `sugar.py`, `derive.py` | The front end: tokens and layout, the parser, the syntax tree, the sugar's removal, deriving |
| `typesys.py`, `typecheck.py`, `frontend.py` | Type inference and the classes |
| `core.py`, `desugar.py` | The core language, and the translation into it: pattern matching, dictionaries |
| `reference.py` | An interpreter for the core language, which writes the expected output |
| `simplify.py`, `strictness.py`, `lift.py` | The optimiser, the strictness analysis, lambda lifting and join points |
| `stg.py`, `codegen.py` | Lowering to an STG-like form, and the code generator for draft 2 |
| `rt/` | The runtime, in draft 2 assembly: `start.s` (memory map, start-up, output, errors), `apply.s` (the general apply and the tag trap), `gc.s` |
| `build.py`, `machine.py` | Compiling and assembling a program, with the features that switch the experiments on; running it on the simulator |
| `prelude.cw` | The prelude, compiled with every program |
| `profile.py`, `measure.py`, `report.py` | Where the cycles go, the experiments, and report 0035's tables |
| `programs/` | Benchmarks, their input and expected output |
| `tests/cw/` | Tests of the language and of its errors, with expected output |

```sh
heron curlew run studies/curlew/programs/queens.cw --stats      # compile, run on the draft 2 simulator
heron curlew run studies/curlew/programs/queens.cw --profile    # ... and where the cycles went
heron curlew run studies/curlew/programs/tak.cw --features tagged --stats  # an experiment (build.FEATURES)
heron curlew ref studies/curlew/programs/queens.cw              # run on the reference interpreter
heron curlew asm studies/curlew/programs/queens.cw              # the generated assembly
heron curlew core studies/curlew/programs/queens.cw             # the program after the optimiser
heron curlew test [--features tagged]                           # every program and test against its expected output
heron curlew report --write                                     # report 0035's tables (about 10 minutes on 4 cores)
heron test curlew                                               # the study's unit tests
python3 studies/curlew/reference.py --write-expected            # rewrite the expected output
```

The features (`--features a,b`) are the experiments: `tagged` (the
evaluation checks are `TTST`, and the tag trap evaluates; the arithmetic
uses `TADD`, `TSUB` and `TCMP`), `tagarith` (just the arithmetic),
`onereg` (`TST r, r11` with `r11` = 1), `nostackcheck`, `noindcheck`,
`noupdtail`, and the optimiser's `nostrict`, `nospec` and `noinline`.
`report.py` and `measure.py` keep their runs in `build/curlew/`, keyed by
the sources, and run again only what changed.
