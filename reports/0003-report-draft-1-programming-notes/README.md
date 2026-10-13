---
number: 3
type: report
title: Writing the draft 1 programs
status: current
date: 2026-10-12
context:
  studies: [v1_isa]
  commit: e494b0c
---

# Report 0003: Writing the draft 1 programs

Five agents wrote the draft 1 program suite, each for both encodings, 1a
and 1b, alternating which came first. Each kept a first-hand log of what
writing the programs was like: what each ISA made easy or awkward, the
mistakes, and what they measured. The logs are the evidence behind the
programming sections of [report 0004](../0004-report-draft-1-evaluation/README.md).

| Notes | Programs |
|---|---|
| [library.md](library.md) | The shared library, and `hello`, `arith` and `strings` |
| [numeric.md](numeric.md) | `sieve`, `sort`, `fib`, `crc` and `bignum` |
| [games.md](games.md) | `mandel`, `life`, `queens`, `matmul` and `bst` |
| [interactive.md](interactive.md) | `rpn`, `monitor` and `interrupts` |
| [newprogs.md](newprogs.md) | The four new 32-bit programs: `sha256`, `wordfreq`, `vm` and `lines` |

They're logs, written while the tools and the timing model were still
changing: some numbers come from earlier versions of the model, and the
tool problems they mention have mostly been fixed since (marked where they
have). The programs are in `studies/v1_isa/programs/`.
