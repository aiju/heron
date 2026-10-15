---
number: 30
type: report
title: The C compiler on draft 2
status: current
date: 2026-10-15
context:
  studies: [c_compiler, v2_isa, v1_isa]
  commit: 1b8e4d2
---

# Report 0030: The C compiler on draft 2

The C compiler ([compiler.md](../studies/c_compiler/compiler.md))
retargeted to draft 2 as [RFC 0028](0028-rfc-draft-2-isa.md) maps it and
the v2_isa study implements it, using draft 2's new instructions where
compiled C has a use for them: the step RFC 0028's next steps
([11](0028-rfc-draft-2-isa.md#11-next-steps)) name, and the list in
[RFC 0006](0006-rfc-ideas-isa.md) for the compiler on draft 2. The
per-program tables are in
[performance.md](0030-report-c-compiler-draft-2/performance.md), generated
by `heron c_compiler bench --isa v2 --write`.

## Summary

- **Compiled C takes 2.4% fewer cycles on draft 2 than on 1b** in the
  programs' own code, and 2.0% fewer in the C library (D16-overlap,
  geometric means over the 15 programs); 2.3–3.0% in the other
  configurations. The hand-written programs, as ported to draft 2, take
  1.0% fewer.
- **Its code is 3.9% smaller,** and the C library 6.5%.
- **Where it comes from,** each feature turned off in turn: `CLR` 1.3%
  (against a fresh `MOV rX, #0`), counting loops down and `DBNZ` 1.0%,
  `MOVS` 1.0% (2.0% in the library), `INC` and `DEC` on memory 0.7%, the
  tables without a base register 0.3%, `TST` and `MULS` with a constant
  0.1%.
- **Two of those are mostly the compiler's.** Counting loops down would
  give 1b 0.7% too, since its `DEC` sets Z; `DBNZ` itself is worth 0.3%.
  With 1b counting down as well, draft 2's lead would be about 1.7%.
- **Worth nothing measurable here:** `r0` as a 15th register (0.0%, 0.4%
  in the library), `CMPI` against keeping a constant in a register, and
  `JMP [pc + table + r*4]`, which no program's hot code reaches.
- **Not used at all:** mode E (`[r14 + 4R]`), `LDM` and `STM`, and the
  tentative instructions ([below](#what-the-compiler-doesnt-use)).
- **Compiled C against the hand-written draft 2 programs:** 1.19× in the
  programs' own code, against 1.22× on 1b (11 programs that spend less
  than half their time in the C library).

## What the compiler does on draft 2

Draft 2 keeps 1b's addressing modes in its rows, so the backend
(`codegen/v2.py`) is 1b's with what changed. The IR, the optimiser, the
register allocator and the rest of the backend are shared; draft 1's
code comes out byte for byte as before.

- **`r0` is a general register:** allocated after `r7`, and caller-saved.
  A zero store is `CLR` at any size and in any mode; a zero in a register
  is `MOV rX, #0`.
- **`MOV` leaves the flags alone.** Where a compare with 0 would read
  the flags of a load or a copy, the `MOV` becomes `MOVS` and the compare
  goes, also past instructions that leave the flags alone, so a string
  copy is the loop a person writes:

  ```
  .b3:    MOVS r4, byte [r2]+
          MOV  byte [r3]+, r4
          BNE  .b3
  ```

- **Stores are written `MOV [address], rs`.**
- **The special mode's tables:** `[label + r*s]` needs no base register
  (`MOV r1, [_t + r1*4]`), nor does `[x*s + d]`; `LEA` takes them too, as
  a three-operand table address.
- **`INC` and `DEC` on memory** for `x++` on a variable in memory, with
  the address in the operand: `INC [_calls]`, `INC [_n + r1*4]`.
- **`TST` and `MULS` with a constant:** `TST r3, #32768`, `MULS r13, #31`.
- **`MOV` and `CMP` with 16…127** take one parcel; the assembler picks the
  form. A constant compared in a loop with a load only the compare uses
  still goes in a register before the loop, as on 1b, so the compare can
  take the load as its memory operand.
- **Loops counted down to zero, and `DBNZ`.** An optimiser pass
  (`count_down` in `ir/passes.py`) turns a loop counter that only counts
  into a count of the runs left, stepped down to zero, when the trip
  count is known: for a `!=` test always (modulo 2³², as the original
  would wrap), and for `<`, `<=`, `>` and `>=` between constants. The
  loop then closes with `DEC r; BNE`, which becomes `DBNZ` when the loop
  fits the instruction's reach of 16 parcels, measured on the final code
  with an upper bound for each instruction's size (checked against the
  assembler's sizes on every instruction of the programs and the
  library).
- **A dense `switch`** is one `JMP [pc + table + r*4]`, PC-relative so the
  table is in reach wherever the linker puts the function.

## What each feature is worth

The draft 2 backend with one feature turned off, against the whole backend
(D16-overlap; above 1, the feature saves that much):

| Without | Own cycles | Library cycles | Own code | Most |
|---|---:|---:|---:|---|
| `CLR` (a `MOV #0` and a store instead) | 1.0128 | 1.0022 | 1.0048 | sieve 1.190 |
| counting down and `DBNZ` | 1.0097 | 1.0049 | 1.0061 | crc 1.151 |
| `DBNZ` (loops still counted down) | 1.0031 | 1.0017 | 1.0013 | crc 1.047 |
| `MOVS` | 1.0097 | 1.0195 | 1.0078 | strings 1.075 |
| `INC` and `DEC` on memory | 1.0066 | 1.0000 | 1.0039 | fib 1.093 |
| tables without a base register | 1.0026 | 1.0000 | 1.0069 | crc 1.017 |
| `JMP [pc + table + r*4]` | 1.0000 | 1.0000 | 1.0000 | – |
| `TST` and `MULS` with a constant | 1.0008 | 1.0002 | 1.0000 | wordfreq 1.008 |
| `CMP #16..127` in place of a register | 1.0002 | 1.0008 | 1.0004 | mandel 1.004 |
| `r0` as a 15th register | 1.0002 | 1.0036 | 0.9996 | sha256 1.003 |

The library column leaves out sieve: its byte array lands on or off a
word boundary depending on the library's size, which changes `memset`'s
time 3.6 times over ([RFC 0006,
3.3](0006-rfc-ideas-isa.md#33-r0-as-a-general-register)). For the same
reason sieve's whole-program cycles are 0.92 of 1b's, while its own code
is 0.998.

- **`CLR` is what replaces the zero register,** and it does so fully.
  Without it, a zero store needs a fresh `MOV rX, #0`, which costs 1.3%,
  as RFC 0006 measured for 1b without `r0`: sieve's inner loop stores a
  zero, and the compiler doesn't hoist the `MOV` out of it. With `CLR`,
  compiled C misses nothing of `r0 = 0`.
- **`r0` as a 15th register** gains nothing in the programs' own code and
  0.4% in the library, where printf's `format` is short of registers.
  RFC 0006's bound, from taking one of 1b's 14 away, was 0.5–0.7%
  (sha256 6–11%); adding a 15th is worth less.
- **`MOVS`:** a load followed by a test of what it loaded, mostly string
  loops (strings 7.5%, the library's `strlen`, `strcpy` and `format`
  2.0%). Half of the uses are `MOVS rd, rs`, the compiler's copy followed
  by a test: 0.25% of the executed instructions, which bears on
  [RFC 0028, 9.8](0028-rfc-draft-2-isa.md#9-open-questions).
- **Counting down is most of `DBNZ`'s gain.** On draft 2 it saves the
  compare (`DEC; BNE` against `INC; CMP; BLT`), and `DBNZ` then the
  decrement. Only crc has loops it applies to among the 15 programs:
  its bit loop, `for (k = 0; k < 8; k++)` around a test, a shift and an
  exclusive or, and its two `while (n--)` loops over the bytes, together
  15%. The other counted loops use their counter (fib, bst and mandel
  print it, others index with it), or are too long or test against a
  variable (life's generations). `DBNZ` is 1.2% of the executed
  instructions.
- **`INC` and `DEC` on memory:** fib's call counter (9%) and wordfreq's
  word counts (`INC [r13 + 4]`).
- **The tables without a base register** save a `MOV rX, #table` and its
  register: 0.7% of the code, 0.3% of the cycles (crc's `XOR r4, half
  [_table + r3*2]`).
- **`CMP` with 16…127 in one parcel** saves nothing over keeping the
  constant in a register across the loop, as the compiler does on 1b: in
  these programs, registers are not short where characters are compared.
  It saves the register. What it saves outside loops, against a 16-bit
  form, isn't measured: the assembler always picks the 7-bit form.
- **`JMP [pc + table + r*4]`** replaces 1b's `LEA` and `JMP` pair, but no
  program here runs a dense `switch`; printf's on the conversion letter is
  too sparse for a table.

## Against 1b, program by program

Own code, D16-overlap:

- **crc 0.856:** counting down and `DBNZ`, and the CRC table without a
  base register.
- **fib 0.915:** `INC [_calls]` in place of a load, an add and a store on
  every call.
- **wordfreq 0.963:** `INC [r13 + 4]` on a word's count, `MULS r13, #31`
  for the hash, and the tables without a base register.
- **bst 0.969:** `INC [_visited]` on every visit, `MOVS` for loads and
  copies that are tested, and `MULS r3, #12` and `LEA r4, [_pool + r3]`
  for a new node's address.
- **queens 0.981:** `MOVS` for a copy tested in the recursion.
- **The other ten:** 0.994–1.000.

## What the compiler doesn't use

- **Mode E, `[r14 + 4R]`.** The assembler picks it whenever the base is
  `r14`, but the allocator never puts a pointer there on purpose. `r14` is
  callee-saved, and C has no current object: a function that used it would
  save and restore `r8`–`r14`, more than the parcels it saves in all but
  loop-heavy code over one structure.
- **`LDM` and `STM`.** Copies of structures up to 64 bytes could use them,
  but they need consecutive registers, which the allocator doesn't give
  out.
- **The tentative instructions** (`ADD.B4`, `FFS`, `POPC`, `REV`, `MULA`,
  `MERGE`, `MULFX`): no C operator maps to them. They would need
  intrinsics, or idiom recognition (a byte swap, a population count).
- **The tagged operations, `SWI`, `MFUR` and `MTUR`:** for the Lisp,
  Egret and the kernel, not C.

## The link register

`CALL` may come to put the return address in `r7` instead of pushing it
(pending). For the backend that would change:

- **The stack arguments' offset** (`MFunction.frame_offset`), which counts
  the pushed return address.
- **The saved registers** (`Target.finish`): a function that calls saves
  `r7` with the callee-saved registers, and `SAVE r7-rN` does that in one
  range.
- **A leaf function's registers:** it keeps its return address in `r7`
  rather than allocating it, which leaves `r0`–`r6` as its scratch
  registers, seven as on draft 1.
- **`RET` and the start code,** with whatever the return becomes.

A call to a leaf function, such as the C library's string functions,
would then touch no memory to call and return. fib's and bst's calls that
return at once would still save `r7`, until the compiler saves registers
only on the paths that need them (shrink-wrapping, which it doesn't do).

## Next steps

- The link register, if `CALL` changes.
- Trip counts from the test that guards a loop's entry, for counted loops
  with a variable bound.
- 1b counting down too, for a fair comparison in report 0011's tables.
- The graphics library, the kernel, the Lisp and Egret on draft 2, which
  RFC 0028's next steps list after the compiler.
