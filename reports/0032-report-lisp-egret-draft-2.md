---
number: 32
type: report
title: The Lisp and Egret on draft 2
status: current
date: 2026-10-16
context:
  studies: [lisp, egret, v2_isa, c_compiler]
  commit: bddf7f1
---

# Report 0032: The Lisp and Egret on draft 2

The Lisp ([report 0018](0018-report-lisp.md)) and Egret
([report 0017](0017-report-egret.md)) ported to draft 2 as
[RFC 0028](0028-rfc-draft-2-isa.md) specifies it and the v2_isa study
implements it, link register included, and measured against draft 1b:
the Lisp's runtime and its compiler, and Egret's VM (compiled by the C
compiler's draft 2 backend, [report 0030](0030-report-c-compiler-draft-2.md)),
its hand-written interpreter loop and its JIT. Both ports use draft 2's
new instructions where they fit, as RFC 0028 asks of software. The
per-program tables are generated: [lisp.md](0032-report-lisp-egret-draft-2/lisp.md)
by `heron lisp report --isa v2 --write`, [egret.md](0032-report-lisp-egret-draft-2/egret.md)
by `heron egret bench --isa v2 --write`.

Cycles are the timing model's for D32-separate, the configuration of the
built 1b hardware ([report 0012](0012-report-draft-1b-hardware.md)), with
draft 2 costed as if it were built the same way; D16-overlap moves every
figure here by less than 0.7 points. Changes are draft 2 against 1b, as
geometric means over the programs: the Lisp's 12 benchmarks and Egret's
17 programs.

> **Erratum (2026-10-16).** The [three bugs carried over from 1b](#three-bugs-carried-over-from-1b)
> are now fixed on 1b as well, the same way, so the drafts are compared
> with the fixes on both. That moves 1b's numbers a little, and
> lisp.md and egret.md are regenerated. In the text:
>
> - the Lisp compiled takes 1.0% fewer cycles on draft 2, not 0.9%
>   (0.990 of 1b's, not 0.991), and with no leaf functions its mutator
>   takes 1.004 of 1b's, not 1.005;
> - where the compiled cycles moved, the runtime's routines take 709,494
>   fewer (−0.32%), not 646,862, and the collector 323,394 fewer
>   (−0.14%), not 329,223.
>
> None of Egret's figures in the text move. Where the report says the port leaves 1b
> as it was (compiler.lisp byte for byte, report 0017's and 0018's
> tables, the bugs still there on 1b), that was true of the port: the
> fixes since changed compiler.lisp and those tables.

> **Erratum (2026-10-16), the constant copier.** A bug in both drafts'
> runtime left part of the compiler interpreted: every top-level form
> that quotes a 0 (report 0018's erratum before its
> [summary](0018-report-lisp.md#summary) has the details). On draft 2
> that included `cc:g-function` and `cc:many-args` as well. With it
> fixed, the compiler compiles more of itself, so the heap holds much
> less when a program starts and the collections fall elsewhere again.
> Code space now ends at `0x2A000` on both drafts, and the heap halves
> are 374 KB. lisp.md is regenerated. The mutator's figures don't move,
> but the collector's do. In the text:
>
> - the Lisp compiled takes 0.2% fewer cycles on draft 2 (0.998 of
>   1b's), not the 1.0% of the erratum above. Draft 2's collector now
>   takes 1,288,185 more cycles than 1b's (+0.60% of 1b's compiled
>   cycles), not 323,394 fewer, and the runtime's routines take 709,201
>   fewer (−0.33%);
> - 1b's compiled cycles are 3.5% fewer, so the other changes are a
>   larger share of them: the entries +1.43%, the integer checks
>   −1.05%. `TST` still saves 1.0%, and the link register costs about
>   1.3%, not 1.2%;
> - the Lisp's compiled code is 1.6% bigger on draft 2, not 1.7%;
> - code space is no longer 4 KB larger on draft 2: the 1b compiler
>   grew as well, and both drafts have the same memory map.

## Summary

- **Everything runs on draft 2:** the Lisp's 22 programs and tests,
  interpreted and compiled, with and without the tagged operations, and
  Egret's 17 programs on all three builds of its VM.
- **The Lisp interpreted takes 2.3% fewer cycles** (every program between
  −1.7% and −2.6%), and 0.5% fewer again with the tagged operations in its
  arithmetic primitives.
- **The Lisp compiled takes 0.9% fewer** (0.3% fewer leaving out the
  collector, whose collections fall elsewhere). Two features pull
  against each other: `TST r, #1` for the integer checks saves 1.0% of
  the compiled cycles, and the link register costs about 1.2%, because
  nearly every compiled function calls and so pushes `r7`, the push 1b's
  call made for it ([below](#the-link-register-and-the-compiled-lisp)).
- **The tagged operations** save the compiled Lisp 5.6% on draft 2,
  where v1bx's tagged register mode saved 6.4% on 1b. Draft 2 with them is
  0.6% slower than v1bx.
- **Egret takes 1.7% fewer cycles with the hand-written interpreter loop,
  7.4% fewer with the loop in C and 2.3% fewer with the JIT.** The C loop's
  gain is the C compiler's (report 0030's −2.8%, and more for an
  interpreter's switch); its compiler (C) is 3.6% faster, start-up 4.2%.
- **Mode E pays for Egret:** with its frame record as the current object
  in `r14`, the JIT gains 0.9 points, and the interpreter loop 0.6 with
  `DBNZ` in two of its loops.
- **Code:** the Lisp's compiled code is 1.7% bigger and its runtime 2.2%;
  Egret's VM image is 1.0% smaller (0.4% with the JIT), and the JIT writes
  4.5% less native code.
- **One porting hazard needs care:** 1b's `MOV` set N and Z, and code
  that read them breaks quietly on draft 2. A dataflow over the sources
  finds it in hand-written code (10 places in the Lisp's runtime, 7 in
  Egret's interpreter loop and start code); in generated code it has to
  be found by reading the generator (5 of the JIT's templates).

## How they were ported

**Where the draft 2 versions live.** In the same study folders, chosen
with `--isa v2` as the C compiler does, with 1b the default: the Lisp's
runtime in `rt_v2/` beside `rt/`, Egret's assembly in `vm/*_v2.s` beside
`vm/*_v1b.s`. Each study shares everything that isn't ISA code between the
drafts (Egret's whole C VM, both studies' programs, tests, expected
output, the Lisp's reference interpreter), and 1b's numbers don't move:
report 0017's and 0018's tables regenerate as they are. A separate
`v1b_lisp` and `v1b_egret` would have duplicated all of it, and moved
two folders that three open pull requests build on.

**The method,** for each assembly file:

1. A mechanical translation: stores become `MOV [address], rs`,
   `ST r0, ea` becomes `CLR ea`, 1b's `LI` a `MOV`.
2. Every `MOV` (and `POP`) whose N or Z a branch can read becomes `MOVS`,
   found by a reaching-definitions dataflow over the sources that follows
   calls (a routine passes on whatever flags reach its `RET`s). The places
   where 1b read `r0` as zero are rewritten.
3. The link register, routine by routine: a routine that calls nothing
   returns with `RET`; one that calls pushes `r7` on entry, where 1b's call
   pushed the return address, so its stack and every `[sp + k]` in it are
   as on 1b, and returns with `JMP [sp]+`. A tail branch from such a
   routine restores `r7` first or goes to an entry past the target's push.
   A second checker follows the return address (in `r7`, or how deep on
   the stack) through every path and flags a `RET`, a `JMP [sp]+` or a
   tail branch that gets it wrong.

The translator and both checkers were one-off scripts for this port and
aren't in the repository; the method above is what they did.

### The Lisp

- **The calling convention** loses `r7` to the link: arguments 1–6 are in
  `r3`, `r4`, `r5`, `r6`, `r8` and `r0`, and the collector takes `r0`–`r8`
  as roots ([implementation.md](../studies/lisp/implementation.md#on-draft-2)).
- **The interpreter** keeps 1b's layout: the special forms run with the
  return address on the stack, and `apply_stack` pops it into `r7` as it
  jumps to a procedure. An atom is a leaf: `eval` returns a constant or a
  variable without touching the stack. Ported faithfully, with `eval`
  pushing `r7` on entry as 1b's call did, the interpreter was 1.5% slower
  than 1b; evaluating atoms as leaves made it 2.1% faster (at commit
  `5ec1d8f`), and `TST r, #1` in the primitives 2.3%.
- **The traps** decode draft 2's encoding to name the failed check (`car`
  of a non-pair is a word access at `[R − 1]`, a call of a non-procedure
  one at `[R + 1]` through a `CALL`'s register byte).
- **The compiler's draft 2 backend** is `compiler_v2.lisp`, whose
  definitions replace compiler.lisp's of the same names when the build
  puts the draft 2 compiler together. The compiler compiles itself from
  that text, so it can't keep a 1b definition to install over a draft 2
  one, and compiler.lisp, the 1b compiler, stays byte for byte as it was
  ([compiler.md](../studies/lisp/compiler.md#on-draft-2)).
- **Leaf functions:** a function's entry, returns and tail calls are
  placeholders until its code is done; then a function that calls pushes
  `r7` on entry and a leaf keeps it. When an inline `cons` finds the heap
  full, it calls the runtime from a stub that saves `r7` itself, so
  consing doesn't make a function a caller; and a tail call to itself
  jumps past the push.
- **Code space** is 4 KB larger on draft 2: the draft 2 compiler is a
  bigger program than the 1b one, and with it compiled into code space the
  errors test ran out.

### Egret

- **The VM's C** is compiled by the C compiler's draft 2 backend, which
  defines `__V2__`. Nothing in the C changed but the JIT.
- **The interpreter loop** (`interp_v2.s`) needed little beyond the
  translation: its handlers end in jumps, and the send path's argument
  count, in `r7`, is never live across a call to C. `asm_run` saves `r7`
  with `r8`–`r14`.
- **The JIT** got a draft 2 encoder beside the 1b one, and the link
  register's changes as the link_register study made them for v1bl
  ([pull request #39](https://github.com/aiju/heron/pull/39), not yet
  merged): the
  method prologue stores `r7` into the caller's frame record, the stubs
  that call C keep `r7` on the stack meanwhile, and a send through the
  method cache passes its bytecode in `r5`. Five templates read the flags
  of a `MOV` (a global's undefined check, a return's frame flags, three
  native-entry checks); they now use `MOVS`, which is `MOV` on 1b. The
  1b JIT compiles to the same assembly as before.
- **The frame record is the current object** on draft 2: the interpreter
  loop and the JIT keep it in `r14` and nil in `r11`, the other way round
  from 1b, so its fields (the saved `ip`, `bp`, the method, the flags, the
  native return address) are one-parcel operands in the send, the
  prologue and the return. RFC 0028 names Egret's frame record as a use of
  mode E.

### Three bugs carried over from 1b

A review of the port found three bugs in the 1b code it started from.
Each is fixed on draft 2 and left as it is on 1b, where fixing it would
move report 0017's and 0018's numbers:

- **Egret's `new` when the frame stack is full:** the interpreter loop's
  fast path for `new` doesn't keep `r5`, the send's length in bytecode,
  across its call to `alloc_obj`. When the frame stack then turns out to
  be full, it hands the send back to C at the wrong place in the
  bytecode: a program that recurses too deep through `new` reports
  "internal: bad bytecode" on 1b, not the stack overflow. Draft 2 keeps
  `r5` with `SAVE r3-r5`.
- **The compiled Lisp's inline `cons` when the heap is full:** its stub
  collects and goes back to the stores without checking the limit again,
  so a collection that frees too little writes the pair past the end of
  the heap. On 1b a program that fills the heap fails with a wrong error
  ("not a number") rather than "heap full". On draft 2 the stub calls the
  runtime's `cons`, which checks again.
- **`apply` with a long list:** it moves the stack pointer down by the
  list's length without checking the stack limit, so a list longer than
  the stack has room for (about 15,800 elements) runs it past its limit
  and into the heap; on 1b the program stops without a word. On draft 2
  it's a stack overflow.

The fixes cost the compiled Lisp 0.03 points, nearly all of it in
`meta`, which applies its primitives to argument lists and gets 0.4%
slower from the check in every `apply`. Egret's `SAVE` is cheaper than
the two pushes and pops it replaces.

> **Erratum (2026-10-16).** 1b now has the same fixes (the erratum
> before the [summary](#summary)).

## The Lisp

| | 1b | Draft 2 |
|---|---:|---:|
| Interpreted | 1 | 0.977 |
| Interpreted, tagged primitives | – | 0.972 |
| Compiled | 1 | 0.991 |
| Compiled, the mutator alone | 1 | 0.997 |
| Compiled with tagged operations (v1bx on 1b), mutator | 0.936 | 0.941 |
| Compiled, no leaf functions, mutator | – | 1.005 |

Where the compiled programs' own cycles moved, summed over the programs
(the compiler's categories, [lisp.md](0032-report-lisp-egret-draft-2/lisp.md#where-the-compiled-cycles-moved)):

| | Change | Share of 1b's compiled cycles |
|---|---:|---:|
| function entries (`entry`) | +3,087,336 | +1.38% |
| integer checks (`type`) | −2,262,247 | −1.01% |
| runtime routines | −646,862 | −0.29% |
| collector | −329,223 | −0.15% |
| calls (`call`) | −222,989 | −0.10% |
| returns (`return`) | −160,480 | −0.07% |
| the rest | −72,994 | −0.03% |

The integer checks are `TST r, #1` instead of a copy and an `AND`. The
interpreter gains in every routine that is a leaf, and in `eval` for
atoms.

### The link register and the compiled Lisp

A Lisp function nearly always calls: of the benchmarks' hot functions
only small loops are leaves, and named-let loops are already jumps. On
1b the call pushed the return address; on draft 2 the function pushes
`r7` on entry (a store, 4 cycles on D32-separate) and returns with
`JMP [sp]+`, which costs what 1b's `RET` did. So each call of a function
that calls costs about 3 cycles more, and each call of a leaf about 5
fewer. Over the benchmarks the entries cost 1.4% more and the calls and
returns 0.2% less; compiled with every function pushing `r7`, as if none
were a leaf, the programs take 0.8% more, which is what the leaves save.

Most of the push could go into the `SAVE` that every function makes of
its arguments on entry: a `SAVE` of one more register costs 2 cycles,
against 4 for the push. That needs the arguments in the registers just
below `r7`, so that `SAVE r(7−n)-r7` saves n arguments and the return
address in one instruction (`r6` for the first argument, `r5` for the
second, and so on), and with them a new calling convention for the whole
runtime. It would take back about half the entry cost, 0.7% of the
compiled cycles. It isn't done here.

### The tagged operations

The compiled checks are `TTST r, r` for one operand, `TCMP` for two
(also the comparison), and `TADD` and `TSUB` for the arithmetic; the
interpreter's `+ - * = < > <= >= zero?` use them too. A failed check is
the tag trap, whose handler names the operand that isn't an integer, so
the errors are the software checks' to the letter (the errors test
passes either way). They save 5.6% of the compiled mutator's cycles on
draft 2 and 0.5% of the interpreter's; v1bx's mode saved 6.4% on 1b. The
gap is mostly the integer checks: draft 2 without the tagged operations
already makes each one a single `TST`, so there is less left to save.

## Egret

| Configuration | Interpreter | C loop | JIT | Compiling Egret |
|---|---:|---:|---:|---:|
| D32-separate | −1.7% | −7.4% | −2.3% | −3.6% |
| D16-overlap | −1.8% | −6.8% | −2.2% | −3.6% |

- **The interpreter loop** gains in the send path's frame (−2.1M cycles
  summed over the programs) and the return (−1.9M): the frame record's
  fields in mode E, and `CLR` for the frame's serial and flags. The
  primitives and the C library gain the C compiler's 3–10%.
- **The C loop** gains 7.4%, 0.9 points more than the C compiler's own
  programs. Its bytecode switch dispatches with one
  `JMP [pc + table + r*4]`, where 1b loads the table's address first, after
  a one-parcel compare of the opcode with 65: the dispatch takes 37M
  cycles fewer summed over the programs, 3.7% of the C loop's 986M. Report
  0030 found no hot code for the PC-relative table; an interpreter's
  switch is some. The send path takes 22M fewer.
- **The JIT** gains in the method prologue (−5.9M cycles: it stores `r7`
  where 1b popped the return address and stored it), the return (−1.9M)
  and the send (−1.6M). It loses in the shared stubs (+1.4M): a
  primitive's or a `new`'s stub calls C, and keeps `r7` on the stack
  around the call. The JIT itself compiles as fast as on 1b once its
  encoder writes rows inline, as 1b's does (a function call per
  instruction made it slower: the C compiler doesn't inline).
- **Step by step,** at the commits of the port: ported faithfully
  (`e237bdd`), the interpreter loop was 1.1% faster and the JIT 0.2%
  slower; the encoder inline made the JIT 1.4% faster (`6987d4b`), and
  the frame record in `r14` with `DBNZ` for the interpreter's two counted
  loops 1.7% and 2.3% (`4b36f64`).
- **Instructions** fall 1.0% in the interpreter loop and 7.7% in the C
  loop; the JIT runs as many instructions as on 1b, and its native code
  is 4.5% smaller.

## What each of draft 2's features did here

| Feature | The Lisp | Egret |
|---|---|---|
| The link register | interpreter: leaves (atoms, most primitives) gain; compiled: +1.2%, leaves save 0.8% of it | the JIT's prologue and returns gain; the stubs that call C pay a push |
| `MOV` without flags, `MOVS` | 10 `MOVS` in the runtime | 7 in the interpreter loop and start code, 5 in the JIT's templates; one `MOVS` saves a `TST` |
| `TST` with a constant | the integer checks, compiled and interpreted: −1.0% compiled | – |
| The tagged operations | −5.6% compiled, −0.5% interpreted (feature `tagged`) | can't be used: Egret tags a SmallInt as 2n + 1 |
| Mode E, `[r14 + 4R]` | nothing: `r14` is the heap pointer, and the tagged pointers put fields at 4k ± 1 (as RFC 0028 found) | the frame record: −0.6 points interpreted, −0.9 JIT |
| `CLR` | zero stores | the frame's serial and flags |
| The 7-bit constants | characters and type bytes, compiled and in the runtime | throughout |
| `DBNZ` | – | two counted loops in the interpreter |
| `INC` on memory | the collections and `gensym` counters | – |
| The tables without a base register | – (its jump tables sit in the first 32 KB, where `[r + table]` reaches them) | the C loop's switch: `JMP [pc + table + r*4]` |
| `r0` a general register | the sixth argument | caller-saved in the C |

Not used: `LDM` and `STM`, and the other tentative instructions.

## Open questions

- **The Lisp's calling convention on draft 2:** arguments below `r7`, so
  that one `SAVE` keeps them and the return address
  ([above](#the-link-register-and-the-compiled-lisp)), is worth about 0.7%
  of the compiled cycles, for a rewrite of the runtime's argument
  registers. It also bears on the link register's case in RFC 0028
  (9.5): call-heavy compiled code is where it costs.
- **Egret and the tagged operations:** they check RFC 0028's tag (bit 0
  clear), the Lisp's. Egret tags a SmallInt 2n + 1 and so can't use them;
  measuring it would mean flipping Egret's tagging, in the C and both
  drafts' assembly. Whether the tag should be selectable is RFC 0028's
  open question.
- **The three bugs in 1b's code**
  ([above](#three-bugs-carried-over-from-1b)) are still there on 1b.
