---
number: 33
type: report
title: The Lisp's arguments below the link register
status: current
date: 2026-10-16
context:
  studies: [lisp, v2_isa]
  commit: fcb3243
---

# Report 0033: The Lisp's arguments below the link register

[Report 0032](0032-report-lisp-egret-draft-2.md#the-link-register-and-the-compiled-lisp)
found that the link register costs draft 2's compiled Lisp about 1.2%: a
function that calls pushes `r7` on entry, where 1b's call pushed the return
address for it. It proposed putting the arguments in the registers just
below `r7`, so that one `SAVE r(7−n)-r7` keeps n arguments and the return
address together. This report tries it.

The Lisp on draft 2 now uses that convention. Report 0032's generated
tables ([lisp.md](0032-report-lisp-egret-draft-2/lisp.md)) follow the code,
so they measure it now; the figures here compare it with draft 2 as report
0032 left it (`main` at `fcb3243`). Cycles are the timing model's for
D32-separate, as geometric means over the Lisp's 12 benchmarks.

> **Erratum (2026-10-16).** The [constant copier](#the-constant-copier-and-0)
> is fixed: `static_copy` now fails with `UNB`, which is never a Lisp
> value. The list there also missed `cc:g-prim`, which ran interpreted on
> both drafts.
>
> With the copier fixed, the compiler and the prelude compile to 64,796
> bytes on draft 2 and 59,408 on 1b. So code space now ends at `0x2A000`
> on both drafts, and the heap halves are 374 KB (10 KB from each), not
> draft 2's `0x28000` and 380 KB. Report 0032's lisp.md is regenerated.
>
> The mutator's figures here don't move. The collector's do: the
> interpreted compiler functions were most of the data live when a
> program starts (22,624 bytes on draft 2, now 2,408), and every
> collection copied them. So against 1b, draft 2's compiled Lisp takes
> 1.4% fewer cycles with the collector, not 3.6%, and 0.1% fewer
> instructions, not 2.9%. Its function entries cost 0.52% of 1b's
> compiled cycles less than 1b's, not 0.50%.

## Summary

- **The compiled Lisp takes 2.2% fewer mutator cycles** (2.6% fewer with
  the collector). The interpreter's cycles are unchanged (+0.01%). Two
  changes make the 2.2%:
  - **The convention: 0.8%.** A function that calls saves its arguments
    and its return address with one `SAVE`, where before it pushed `r7`
    and then saved the arguments: 2 cycles fewer per call. That is the
    0.7% report 0032 estimated.
  - **Tail calls to themselves skip the stack check: 1.4%.** A loop's
    tail call saves its new arguments in place and jumps past the
    function's entry, stack check included, since the stack is no deeper.
    This doesn't need the new convention. Measured on report 0032's
    convention, it alone made draft 2 1.4% faster. 1b's compiler still
    checks on every iteration.
- **Against 1b,** draft 2's compiled Lisp now takes 2.5% fewer mutator
  cycles (0.3% fewer before) and 3.6% fewer with the collector (1.0%).
  Its function entries now cost 0.5% less than 1b's, where they cost 1.4%
  more. About 1.4 points of that lead is the tail-call change, which 1b's
  compiler could make too.
- **The link register now costs the compiled Lisp 0.7%,** half what it
  did. It's in the function entries, leaving out the tail-call change.
- **With the tagged operations,** draft 2's compiled Lisp is now 1.7%
  faster than v1bx; it was 0.6% slower. Leaf functions now save 0.6%,
  down from 0.8%, because a function that calls pays less to save `r7`.
- **Code:** the compiled code is 0.3% smaller, and the runtime 32 bytes
  bigger.
- **What it took:**
  - the runtime's registers renamed throughout;
  - the interpreter's arguments put on the stack in the other order;
  - code space 4 KB bigger, taken from the heap.
- **A bug found on the way:** the runtime's constant copier can't copy a
  constant that contains the integer 0. So several of the compiler's own
  functions have been running interpreted, on both drafts. No benchmark
  is affected ([below](#the-constant-copier-and-0)).

## The convention

Arguments 1–4 are in `r6`, `r5`, `r4` and `r3`: argument k in r(7 − k),
just below the link register. Arguments 5 and 6 are in `r8` and `r0`, as
before. With more than 6, `r6`–`r3` and `r8` hold 1–5 and `r0` a list of
the rest. Everything else is as before: `r1` is the procedure, `r2` the
count, `r7` the return address, and the result comes back in `r1`.

A compiled function with n parameters saves them on entry with the first
highest, the return address above them. Its parameters are numbered in
order from the top of the frame.

| | Report 0032 | Now |
|---|---|---|
| Calls something, n ≤ 4 | `PUSH r7`, stack check, `SAVE r3-r(2+n)` | stack check, `SAVE r(7−n)-r7` |
| A leaf, n ≤ 4 | stack check, `SAVE r3-r(2+n)` | stack check, `SAVE r(7−n)-r6` |
| 5 or 6 parameters | `PUSH r7`, stack check, (`PUSH r0`), `PUSH r8`, `SAVE r3-r6` | stack check, `SAVE r3-r7`, `PUSH r8`, (`PUSH r0`) |
| A tail call to itself | pop the frame, branch to the stack check, `SAVE` | pop the frame to `r7`, `SAVE r(7−n)-r6`, branch past the entry |

A `SAVE` costs 2 cycles per register plus 2, and a push costs 4. So a
function that calls saves 2 cycles per call, and a leaf costs what it did.
A loop no longer runs the stack check on every iteration: a `CMP` with a
memory operand, and a branch.

## What it took

- **The runtime's registers** are renamed throughout, `r3`↔`r6` and
  `r4`↔`r5`, mechanically, so every routine's convention follows the
  procedure call's: `cons`, for one, now takes the car in `r6` and the cdr
  in `r5`. Two routines that compiled code calls keep compiled code's
  registers:
  - `rt_num2`, with the operands in `r1` and `r3`;
  - a new `cons_c`, with the car in `r3` and the cdr in `r4`, for the
    inline `cons` when the heap is full. The build exports it as
    `%rt:cons` on draft 2.
- **The interpreter** keeps a call's arguments on the stack with the first
  highest, just below the procedure (1b's first argument is at `[sp]`). So
  `RESTORE r(7−n)-r6` loads n of them into their registers and
  `SAVE r(7−n)-r6` stores them, one instruction each, as before. For that:
  - `eval_into` fills the slots downward;
  - `apply_fun` and `let` bind from the top down;
  - `apply_list` pushes the arguments.

  My first try computed the arguments' address with an indexed `LEA`,
  which made the interpreter 0.4% slower. Taking `sp` before the slots are
  made costs what the old code did.
- **The compiler's draft 2 backend** (`compiler_v2.lisp`):
  - the argument registers and the frame's numbering;
  - `cc:save-args`, which `cc:link` uses to settle a function's entry once
    it knows whether the function is a leaf;
  - the tail call to itself.
- **Code space.** The compiled compiler is now 2.5 KB bigger: `cc:g-function`
  is compiled, where before it ran interpreted because it quoted
  `(st 0 (pdec 15))` (the [bug below](#the-constant-copier-and-0)). With
  that, the errors test ran out of code space. Code space now ends at
  `0x28000`, and the heap gives 4 KB of each half (1%), so that the
  category map still covers all of code space. That moved no mutator
  cycle. The collector's cycles moved, because collections fall elsewhere
  (+0.4% compiled, nearly all in `closures` and `sort`).
- **A test** (`tests/test_compiler.py`) passes arguments through every
  corner of the convention, compiled and interpreted, against the
  reference interpreter:
  - 0–6 parameters, in leaves and in functions that call;
  - tail calls to themselves with 5 and 6 parameters and with a rest
    parameter;
  - more than 6 arguments;
  - calls both ways between compiled code and an interpreted closure.

## Results

Step by step, at the branch's commits:

| Step | Commit | Interpreted | Compiled | Mutator |
|---|---|---:|---:|---:|
| Code space from the heap | `b185b05` | −0.00% | +0.36% | +0.00% |
| Tail calls to themselves skip the stack check | `68408f2` | +0.00% | −1.31% | −1.42% |
| Arguments below `r7` | `c2eb326` | +0.01% | −1.71% | −0.77% |
| **All three** | | **+0.01%** | **−2.65%** | **−2.18%** |

The compiled mutator's cycles, program by program:

| Program | Report 0032 | Now | Tail calls | Convention | Change | Draft 2 / 1b, before | Now |
|---|---:|---:|---:|---:|---:|---:|---:|
| boyer | 49,742,189 | 49,075,623 | −0.0% | −1.3% | −1.3% | +2.4% | +1.1% |
| closures | 11,680,375 | 11,502,694 | −0.6% | −0.9% | −1.5% | +0.0% | −1.5% |
| deriv | 14,717,879 | 14,537,733 | −0.1% | −1.1% | −1.2% | +1.9% | +0.6% |
| destruct | 11,600,536 | 11,062,497 | −4.6% | −0.0% | −4.6% | −4.1% | −8.5% |
| div | 7,961,254 | 7,653,504 | −3.1% | −0.8% | −3.9% | +0.7% | −3.2% |
| fib | 8,752,251 | 8,590,875 | −0.0% | −1.8% | −1.8% | −3.5% | −5.3% |
| meta | 15,230,341 | 15,044,177 | −0.1% | −1.1% | −1.2% | +2.6% | +1.4% |
| nqueens | 9,009,524 | 8,986,167 | −0.0% | −0.2% | −0.3% | −1.0% | −1.2% |
| sieve | 13,917,901 | 13,345,366 | −4.1% | −0.0% | −4.1% | −2.8% | −6.8% |
| sort | 44,979,680 | 43,842,627 | −2.4% | −0.1% | −2.5% | −2.5% | −4.9% |
| strings | 7,258,474 | 7,118,076 | −1.7% | −0.2% | −1.9% | +1.5% | −0.5% |
| tak | 8,620,146 | 8,489,436 | +0.0% | −1.5% | −1.5% | +1.1% | −0.4% |
| **geometric mean** | | | **−1.4%** | **−0.8%** | **−2.2%** | **−0.3%** | **−2.5%** |

Each change has its own kind of program:

- **The convention** helps programs whose functions call: `fib`, `tak`,
  `boyer`, `meta`, `deriv`.
- **The tail-call change** helps programs that loop: `destruct`, `sieve`,
  `div`, `sort`, `strings`.

Summed over the programs, the function entries take 4.2M cycles fewer:
2.7M from the tail-call change and 1.5M from the convention, 1.9% of the
compiled cycles. The collector's cycles are 2.7M fewer, because its
collections fall elsewhere. Nothing else moved by more than 0.01%.

Against 1b (with the three bugs report 0032 found fixed there too), from
report 0032's tables:

| | Before | Now |
|---|---:|---:|
| Interpreted | −2.3% | −2.2% |
| Compiled | −1.0% | −3.6% |
| Compiled, the mutator alone | −0.3% | −2.5% |
| Compiled with tagged operations, against v1bx (mutator) | +0.6% | −1.7% |
| No leaf functions, against draft 2 (mutator) | +0.8% | +0.6% |
| Instructions, compiled | +0.4% | −2.9% |
| Code bytes, compiled | +1.7% | +1.4% |
| Function entries (share of 1b's compiled cycles) | +1.38% | −0.50% |

## The constant copier and 0

`static_copy` copies a quoted constant into constant space so that
compiled code can refer to it. It returns 0 for "can't be copied". The
integer 0 is also the word 0, so any constant that contains a 0 counts as
uncopyable, and the compiler leaves the whole form to the interpreter.

On both drafts, that leaves these compiler functions interpreted:
`cc:ea`, `cc:g-lambda`, `cc:test-prim`, `cc:check-num-sw`,
`cc:check-num2-sw`, `cc:check-vector` and `cc:check-vector-index`. On
draft 2 it also leaves `cc:many-args` and `cc:save-args`, and before this
change `cc:g-function`.

It costs compile time, not the measured cycles: no benchmark quotes a 0.
A fix (a "can't" that isn't a value) would compile those functions. They
would take more code space.

## Open questions

- **The convention** is draft 2's Lisp convention now. It halves what
  the link register costs call-heavy code, which bears on the case for
  the link register in
  [RFC 0028](0028-rfc-draft-2-isa.md) (9.5).
- **1b's tail calls to themselves** still run the stack check. Skipping
  it there would likely save 1b about the same 1.4%, and keep the two
  drafts' compiled numbers comparable. I didn't do it, since it changes
  report 0018's numbers.
- **The constant copier** is broken the same way on both drafts. Fixing
  it changes which of the compiler's functions are compiled, and so the
  heap and code space when a program starts.
- **Arguments 5 and 6** stay in `r8` and `r0`. With the procedure and the
  count moved out of `r1` and `r2`, they could go in `r2` and `r1`, and
  `SAVE r1-r7` would save six arguments. Few functions have five or six
  parameters, so I haven't measured it.
