---
number: 34
type: report
title: Optimising the C compiler
status: current
date: 2026-10-16
context:
  studies: [c_compiler, v1_isa, v2_isa, egret, graphics, kernel]
  commit: d541a32
---

# Report 0034: Optimising the C compiler

What a profile of compiled C on draft 2 said the C compiler
([compiler.md](../studies/c_compiler/compiler.md)) was missing, what was
added, and what each addition is worth on 1a, 1b and draft 2. The
optimisations are target-independent except where noted, so they change
the generated tables of every report that runs compiled C: report 0011's
and report 0030's (the compiler's own), and those of reports 0017, 0019,
0020 and 0032. The step-by-step numbers below are a snapshot, measured
after each commit on this report's branch.

## Summary

- **The programs' own code takes 7.6% fewer cycles on 1a, 7.4% on 1b and
  8.4% on draft 2,** and the C library 3.3%, 3.9% and 4.0% fewer
  (D16-overlap, geometric means over the 15 benchmark programs; the
  library without sieve). The code is 1.3% smaller on draft 2 and the
  library 3.5–4%.
- **Shrink-wrapping is worth most:** 2.7% on draft 1, 3.5% on draft 2,
  where a function that returns before it calls no longer saves the link
  register either. fib takes 25% fewer cycles on draft 2, queens 11%.
- **Inlining, with loads reused across blocks and jump threading,** 2.7–3.0%,
  most of it wordfreq's comparison function (23–25%), and 1.5% in the
  library.
- **Compiled C against the hand-written programs, in their own code:**
  1.11× on 1a and 1b (was 1.22×), 1.08× on draft 2 (was 1.20×). fib and
  queens now beat the hand-written draft 2 versions (0.86× and 0.92×).
- **Draft 2 against 1b for compiled C:** 3.8% fewer cycles in the
  programs' own code (was 2.8%); the link register gains from
  shrink-wrapping. **1b against 1a** is unchanged in the benchmarks, but
  in the graphics library compiled C now gains as much from 1b as the
  assembly kernels do (0.950 against 0.955), from a compare that 1b's
  `ADD r, #-1` makes unnecessary and 1a's `ADDI` doesn't.
- **For the hardware:** `DIVU` is 34% of the C library's cycles, nearly
  all printf dividing by 10. A divider that skips the dividend's leading
  zero bytes would take about 15% off the library; reciprocal
  multiplication can't, with this multiplier
  ([below](#what-the-profile-says-about-the-hardware)).

## Where the time went

A profile of every executed instruction of the 15 programs on draft 2
(the compiler as report 0030 left it), by what each instruction does:

- **Frames:** `SAVE` and `RESTORE` were 37% of fib's cycles and 30% of
  queens', mostly on calls that return at once (fib's base case, queens'
  two early exits), plus the copies of the arguments into callee-saved
  registers.
- **Calls to small functions:** wordfreq spent 36% of its cycles in a
  two-line comparison that its insertion sort calls 2,808 times; the
  call cost more than the comparison, which also loaded both counts twice.
- **Loops' back edges:** a copy and a `BRA` closed many loops, 2.7% of
  the cycles on the geometric mean if all were gone. The loop computed
  `i + 1` early and then addressed `a[i + 1]` through the old `i`, so old
  and new were both live; or a two-address chain ended in a register
  other than the loop's.
- **Loop invariants left in:** mandel added `-295` and `-563` on every
  iteration, crc loaded two constants per byte, and bignum loaded its
  loop bound, a global, on every iteration.
- **In the C library,** `DIVU` was 32% of the cycles.

## The optimisations

Each step against the one before (cycles; code size in bytes):

| Step | Own code: 1a | 1b | 2 | Library: 1a | 1b | 2 | Code, 2 | Most (on 2; last row 1a) |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Constants before the outermost loop | 0.998 | 0.997 | 0.997 | 1.001 | 0.994 | 0.994 | 1.000 | crc 0.96 |
| Invariant constants out of loops | 0.996 | 0.996 | 0.996 | 1.000 | 1.000 | 1.000 | 1.000 | mandel 0.94 |
| Loads of globals out of loops | 0.997 | 0.997 | 0.997 | 1.000 | 1.000 | 1.000 | 1.001 | bignum 0.96 |
| Flags of adds that can't overflow | 1.000 | 1.000 | 0.998 | 1.000 | 1.000 | 1.000 | 0.999 | wordfreq 0.98, sort 0.99 |
| Shrink-wrapping | 0.973 | 0.973 | 0.965 | 1.000 | 1.000 | 1.000 | 0.998 | fib 0.75, queens 0.89 |
| Inlining, loads across blocks, jump threading | 0.970 | 0.971 | 0.973 | 0.986 | 0.984 | 0.984 | 1.005 | wordfreq 0.76, bst 0.95 |
| Stepped addresses (1b, 2), two-address chains | 0.997 | 0.987 | 0.986 | 1.000 | 0.983 | 0.982 | 0.992 | sort 0.94, life 0.96 |
| Inlining only what doesn't grow the code | 1.002 | 1.002 | 1.001 | 1.000 | 1.000 | 1.000 | 0.993 | matmul 1.02 |
| Stepped addresses on 1a | 0.990 | 1.000 | 1.000 | 0.981 | 1.000 | 1.000 | 1.000 | wordfreq 0.96, sort 0.96 |
| **All** | **0.924** | **0.926** | **0.916** | **0.967** | **0.961** | **0.960** | **0.987** | |

- **Constants before the outermost loop.** A constant an instruction
  can't take as an immediate was loaded into a register before the
  innermost loop, so a loop around it loaded it again on every turn. It
  now goes before the outermost loop without a call, but a loop around
  other loops only takes constants if an estimate of its live values
  leaves registers for them: printf's big loop doesn't, and hoisting
  there cost the library 1% in spills.
- **Invariant constants out of loops.** The simplifier moves constants
  outward, `(x + y) + c`, so that an address's displacement can take them.
  In a loop, with `y` invariant and the result not an address, `c` cost
  an `ADD` per iteration; it becomes `x + (y + c)`, with `y + c` before
  the loop.
- **Loads of globals out of loops.** A load of a global or a stack slot
  can't trap, so it moves out of a loop with no call and no store that
  could overlap it. The alias test now knows that indexing an array can't
  reach another object, so bignum's stores into `num[i]` leave `len`
  alone.
- **Flags of adds that can't overflow.** C's signed arithmetic can't
  overflow, so after `ADD` or `SUB` on an `int`, V is 0 and the flags
  decide `j > 0` without a `CMP`. `INC` and `DEC` leave V as it was, so
  where a compare needs it they become `ADD #1` or `#-1`, which cost the
  same. In the benchmarks it only shows on draft 2, where loads in
  between leave the flags alone; but on 1b it takes 15–18% off the
  graphics' fills, whose inner loops are a store and `n--` with
  `n > 0` ([below](#1a-1b-and-draft-2)). 1a can't use it: its
  one-parcel `ADDI` leaves V too.
- **Shrink-wrapping.** The prologue goes where the region that needs the
  frame starts: the block that dominates every block that calls (on
  draft 2, which writes `r7`), touches a callee-saved register or the
  stack frame, and everything that block reaches. Returns before it
  don't unwind anything. For that to happen, a value made before the
  region that lives across a call in it is copied at the region's start,
  so only the copy needs a callee-saved register, and the allocator
  doesn't coalesce the two; a return block shared with the paths before
  the region gets a copy of its own; and a call in tail position doesn't
  count, since it becomes a jump. fib's base case is now
  `INC [_calls]; CMP r1, #2; BGE .b3; RET`.
- **Inlining.** After every function of a unit is optimised, a call to a
  function of the unit with at most 16 instructions and no loop becomes
  a copy of its body, and the caller is optimised again. Two smaller
  changes make the copies pay: loads are reused down chains of blocks
  with one predecessor, and a block that only branches on a phi is
  bypassed (jump threading), so an inlined predicate branches where the
  caller's `if` goes instead of making a 0 or 1; a compare that repeats
  the one that ended the only predecessor goes too.
- **Inlining only what doesn't grow the code.** Inlining every call to a
  small function grew Egret's VM, whose compiler and JIT call small
  helpers from dozens of places, from 49 KB of code to 67 KB, past the
  64 KB a call reaches, and its JIT builds no longer linked. A function is
  now inlined only if copying it into all its call sites adds at most 8
  instructions to the unit, counting the calls the copies replace and the
  static original that goes. Egret's VM is 0.4% bigger than before
  inlining; matmul's `next`, called from three places, is no longer
  inlined.
- **Stepped addresses.** Once `i + c` has been computed on the way to a
  memory access, the access addresses through it, with the displacement
  less `c` times the scale. The old `i` then usually dies at the step,
  which is done in place, and the loop closes with a conditional branch:
  `while (a[i] < v) i++` is `INC r9, r9; CMP r1, [r11 + r9*4]; BHI`.
- **Two-address chains.** A commutative two-address operation starts
  from the operand that is a loop's phi, also when its result reaches the
  phi through more two-address operations: bignum's
  `c = (n[i] * k + c) / 10000` adds into `c`, and the divide leaves the
  next `c` in the same register.

The fuzzer ran 2,100 random programs against gcc over the steps, all
three encodings, without a failure; every active study's tests pass.

## Against the hand-written programs

The programs' own code on draft 2, compiled C against the hand-written
version, before and after:

| Program | Before | After | |
|---|---:|---:|---|
| fib | 1.15 | 0.86 | nothing saved on the base case |
| queens | 1.07 | 0.92 | nor on the two early exits |
| wordfreq | 1.49 | 1.05 | the comparison inlined, its result branched on |
| bst | 1.49 | 1.32 | null nodes return before the frame |
| sort | 1.49 | 1.32 | the partition's scans close with one branch |
| bignum | 1.66 | 1.53 | the loop bound hoisted, no copy of the carry |
| mandel | 1.13 | 1.06 | `cy - 295` and `cx - 563` before the loop |
| crc | 1.23 | 1.18 | its constants before both loops |
| life | 1.09 | 1.05 | the cell pointer stepped in place |
| sha256 | 1.17 | 1.17 | |
| **geometric mean** | **1.20** | **1.08** | the 11 programs that spend less than half their time in the C library |

Over the whole programs, compiled C now takes 1.74× the hand-written
programs' cycles on 1b, against 1.87× (and 1.68× on 1a, against 1.83×, a
little of it sieve's layout, [below](#1a-1b-and-draft-2)); most of the
rest is printf.

## 1a, 1b and draft 2

- **Draft 2 against 1b** gains a point: 3.8% fewer cycles in the
  programs' own code (was 2.8%), 3.9% in the library (3.8%). Shrink-wrapping
  is worth more on draft 2 (3.5% against 2.7%), because a call that
  returns at once no longer saves the link register, which on 1b a call
  pushes anyway; and the flags of adds that can't overflow only help
  draft 2, where a `MOV` between them and the branch leaves them alone.
  fib on draft 2 now takes 0.84× its cycles on 1b (was 0.92×), wordfreq
  0.90× (0.96×).
- **1b against 1a** doesn't change: whole compiled programs take 0.949×
  their 1a cycles on 1b without sieve, against 0.950× before. With sieve,
  report 0011's mean moves from 0.943 to 0.957, but only because sieve's
  time in `memset` depends on where the linker puts its array, and its 1a
  build now happens to put it well (21% fewer cycles). Report 0011's
  finding, that compiled code gains less from 1b than hand-written code
  (0.925), stands for these programs. Not for the graphics library
  ([report 0019](0019-report-graphics.md)): its compiled C now takes
  0.950 of its 1a cycles on 1b, against 0.970, as much as with the
  assembly kernels (0.955). Its fill and line loops are a store and
  `n--` with `n > 0`; on 1b, `ADD r, #-1` sets the flags that test
  needs, C's signed arithmetic keeping V clear, and the `CMP` goes, which
  makes the fills 15–18% faster. 1a's `ADDI` leaves V alone, so the
  compare stays: it would need the compiler to know that `n` is never
  negative there, when `n > 0` is `n != 0`.

## What the profile says about the hardware

- **An early-out divider.** The timing model's `DIVU` always takes 32
  steps, 66 cycles on D16, but the C programs' dividends are small:
  printf's divisions by 10 average 11 bits, bignum's 17–19. With
  dividends of b bits, a divider that skips the dividend's leading zero
  bytes (a byte test per step, as RFC 0007's 8-step path for small
  multipliers does for multipliers) would take 2 + 8k·aw + (4 − k)·aw
  cycles for k = ⌈b/8⌉ bytes; one that skips leading zero bits about
  2 + (b + 2)·aw. Over the 4,092 divisions in the library (the 15
  programs), that's 46% or 57% fewer divide cycles, and **15% or 19% of
  the library's**; the programs' own code divides much less (1.3% of its
  cycles). It changes the microcode, not the encoding. Whether the
  divider's datapath can test a byte cheaply isn't checked here.
- **Not reciprocal multiplication.** A compiler usually turns a division
  by a constant into a multiply by its reciprocal. Here a multiply takes
  1 + 2b cycles for a second operand of b bits, so multiplying by a 32-bit
  reciprocal costs as much as dividing unless the dividend is the narrow
  operand, and the remainder needs a second multiply: about 48 cycles
  against `DIVU` and `MFHI`'s 69 for printf's 10-bit dividends, 92 for
  32-bit ones. The early-out divider would do better (about 41 for 10
  bits, `MFHI` included) and helps variable divisors too, so the
  compiler doesn't do it.
- **Multiply operand order.** With perfect knowledge of the values,
  putting the narrower operand second would save 1.1–1.4% on mandel,
  matmul and bignum; a static guess would save less.
- **Three-operand shifts and rotates.** The copies before a shift or a
  rotate are 1.4% of the programs' own cycles on average, but 9% of
  sha256's, which rotates copies of its working variables. That agrees
  with RFC 0028's decision against them for lack of room; only code like
  sha256 would want them.
- **Calls reach 64 KB.** A call on 1b and draft 2 is PC-relative with a
  16-bit offset in parcels, and nothing makes a far call. Egret's VM is
  49 KB of compiled code, plus the library and its assembly, so it is
  close to the limit: the first version of inlining crossed it.

## What's left

- **sha256's rotating variables:** 8% of its cycles are copies that move
  `a`…`h` along each round. Unrolling the round loop by 8 would make them
  renamings, for about 600 bytes more code.
- **mandel's new `x`:** `x = xx - yy + cx` ends in `xx`'s register and is
  copied into `x`'s (2.6%); computing `(xx + cx) - yy` with `LEA` for the
  first add would avoid it.
- **Type-based aliasing:** wordfreq's sort loads `e->count` on every
  step, because a store of a pointer into `sorted[]` might overlap it; an
  `int` load can't alias a pointer store.
- **printf:** the library is 34% `DIVU`, then the format parsing; a
  division-free decimal conversion for small values would help every
  program that prints, as the early-out divider would.
- **Larger differences from the hand-written versions** are their
  algorithms: crc keeps the CRC top-aligned so that the carry needs no
  test, and bignum uses 32-bit limbs with `MULU`'s high half.

## Changes to other reports

The generated tables of reports 0011, 0017, 0019, 0020, 0030 and 0032
(`egret.md`) are rerun with the new compiler, and each of those reports
gets an erratum for the numbers in its text that moved:

- [Report 0011](0011-report-c-compiler.md): compiled C against the
  hand-written programs; 1a against 1b doesn't move but for sieve.
- [Report 0017](0017-report-egret.md): Egret's interpreter against C,
  start-up and compiling, all a little faster with the VM's C.
- [Report 0019](0019-report-graphics.md): ellipses 10% faster and
  TrueType rasterising 4–5%; compiled C on 1b against 1a, above.
- [Report 0020](0020-report-operating-system.md): the page map's Egret
  and graphics rows, and the ready queue in C (88 cycles, was 99).
- [Report 0030](0030-report-c-compiler-draft-2.md): draft 2 against 1b,
  the code size and the features' worth.
- [Report 0032](0032-report-lisp-egret-draft-2.md): Egret's gains on
  draft 2 move by at most 0.1 points.

The graphics bench caches its runs under a hash of the graphics sources,
which leaves out the compiler; its tables here come from a fresh run.
