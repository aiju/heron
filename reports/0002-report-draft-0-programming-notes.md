---
number: 2
type: report
title: Writing the draft 0 programs
status: obsolete
date: 2026-10-11
context:
  studies: [v0_hw]
  commit: e494b0c
superseded-by: 3
---

# Report 0002: Programming notes: a program suite for ISA draft 0

> **Draft 0 is superseded.** This is the 16-bit first draft, kept as a record. Draft 1 replaced it: see [RFC 0004](0004-rfc-draft-1-isa.md) and [report 0012](0012-report-draft-1b-hardware.md).

This is a first-hand log of writing the library and the 15 test programs in
`programs/v0/` for ISA draft 0 (`docs/isa-v0.md`). It's meant as evidence for
deciding what to change in the ISA, so it records what actually happened,
including where things went fine.

All cycle counts come from the instruction-level simulator with the microcode
timing (`python3 -m tmc run --stats` / `tmc test`). Shares of time spent in
particular routines come from a small profiler that attributes each
instruction's cycles to the enclosing label.

## Summary

- **Getting code right was easy, getting it fast was not.** Nearly every
  program produced correct output the first time it assembled. The encoding
  is regular, the conditions are complete (all of ARM's), and the simulator
  behaves as the document says. Over the whole suite I hit **4 assembler
  errors** (3 branch-range, 1 missing addressing mode), **1 ordinary
  output-format bug**, **1 carry-flag bug caught on review before running**,
  and **2 test-design mistakes**. In fairness: I worked out the tricky parts
  (the multiply loop, fixed-point ranges, the interrupt race) on paper and in
  Python before writing assembly, so the bug count understates how easy the
  flag rules are to trip over. The near misses below matter more than the
  count.
- **The dominant cost is the lack of multiply and divide.** In the four
  programs that multiply or divide in earnest, 61-80% of all cycles are spent
  inside the software routines (`mandel` 73%, `matmul` 79%, `bignum` 80%,
  `interrupts` 61%). A 16x16 multiply costs 72-157 cycles, a 32/16 divide
  about 220.
- **Call overhead is second.** One-register `PUSH`/`POP` (3 and 4 cycles)
  is 34% of all cycles in `queens` and 21% in `fib`.
- **Branch range is an assembler problem more than an ISA problem.** Long
  forms cost no extra cycles (`Jcc` = `Bcc` = 2, `CALL` = `BSR` = 3), but the
  assembler relaxes `LD`/`MOV` forms and not branches, so every out-of-range
  `BSR` is a hard error and I ended up writing `CALL` for every library call.
- **`INC`/`DEC`/`ADDI` write the carry**, so a loop counter can't coexist
  with a carry that has to live across iterations. This shaped the multiply
  routine and caused my one real flag bug.
- Things that worked well: loads setting Z, `LEA` not touching flags,
  `[label + reg]` addressing, unary ops with a separate source register, `r0`
  as zero, `SWAB`, long forms at no cycle cost, `CALL rs`, and an interrupt
  model simple enough to write a race-free sleep in ten lines.

## What was written

Library (`programs/v0/lib/`), each file self-contained (no file includes or
calls another, so any subset can be included without duplicate labels):

| File | Routines |
|---|---|
| `console.s` | `putc`, `getc` (-1 at end of input), `puts`, `newline`, `space`, `gets` |
| `print.s` | `print_u16`, `print_u16z` (zero-padded), `print_s16`, `print_u32`, `print_s32`, `print_hex32/16/8` |
| `mul.s` | `umul16`, `smul16` (16x16 -> 32) |
| `div.s` | `udiv16`, `sdiv16`, `udiv32_16` (32/16 -> 16, like a hardware DIV), `udiv32` (32/16 -> 32) |
| `string.s` | `strlen`, `strcpy`, `strcmp`, `memcpy`, `memmove`, `memset` |
| `rand.s` | `srand`, `rand` (xorshift16, shifts 7/9/8, period 65535) |

Programs (all pass `python3 -m tmc test`; expected output comes from
`programs/reference.py`, which reimplements each program in Python):

| Program | Instructions | Cycles | CPI | Code bytes |
|---|---:|---:|---:|---:|
| arith | 42,306 | 91,155 | 2.15 | 942 |
| bignum | 75,365 | 147,257 | 1.95 | 670 |
| bst | 13,629 | 31,447 | 2.31 | 636 |
| crc | 78,724 | 163,651 | 2.08 | 552 |
| fib | 117,896 | 288,164 | 2.44 | 514 |
| interrupts | 82,122 | 200,920 | 2.45 | 720 |
| life | 336,545 | 791,905 | 2.35 | 944 |
| mandel | 1,231,114 | 2,476,985 | 2.01 | 422 |
| matmul | 49,875 | 102,037 | 2.05 | 818 |
| monitor | 18,624 | 41,043 | 2.20 | 1,056 |
| queens | 85,167 | 202,841 | 2.38 | 582 |
| rpn | 18,993 | 39,473 | 2.08 | 820 |
| sieve | 87,376 | 185,274 | 2.12 | 776 |
| sort | 44,794 | 93,601 | 2.09 | 772 |
| strings | 8,936 | 20,045 | 2.24 | 1,162 |

Everything runs in under 2.5M cycles; only `mandel` comes close to the 3M
budget.

## Program by program

Difficulty is how hard the program was to write on this ISA, not how hard
the algorithm is in general.

### Library

**Difficulty: moderate (multiply and divide), easy (the rest). Bugs: none
found by tests.**

The interesting work was in `mul.s`. The textbook loop for a
shift-and-add multiply keeps a carry alive from the add to the shift, and
counts 16 iterations:

```
.loop:  BCC  .noadd
        ADD  r2, r1         ; C = carry out of the high half
.noadd: RRC  r2             ; ...shifted into the product
        RRC  r3             ; C = next multiplier bit
        DEC  r4             ; <- destroys C: DEC sets NZCV
        BNE  .loop
```

That doesn't work, because `DEC` (like `INC` and `ADDI`) sets C. There is
no counter instruction that leaves C alone (the PDP-11's `INC`/`DEC` leave
C alone for this exact reason). I used an early-exit loop instead: shift the
multiplier right and stop when `SHR` leaves it at zero (`SHR` sets C to the
bit shifted out *and* Z for the rest, which is what makes this work):

```
        SHR  r3                 ; C = this bit, Z = no 1 bits left after it
        BEQ  .last
.loop:  BCC  .skip
        ADD  r1, r4
        ADC  r2, r5
.skip:  SHL  r4                 ; 32-bit multiplicand shifts left
        RLC  r5
        SHR  r3
        BNE  .loop
```

That's about 10 cycles per multiplier bit plus 4 per 1 bit, and the routine
multiplies by the smaller operand. I also checked in Python that a fully
unrolled 16-step version (`BCC/ADD/RRC/RRC` per bit, no counter needed) is
correct; by instruction count it would take a fixed ~110-120 cycles. The
early-exit loop wins for operands
under about 10 bits, which covers most of what these programs multiply.
Measured costs per call:

| Routine | Operands | Cycles per call |
|---|---|---:|
| `umul16` | limb x k <= 52 (bignum) | 72 |
| `umul16` | < 512 (mandel) | 82 |
| `umul16` | i x i, i <= 1000 (interrupts) | 126 |
| `umul16` | 12-bit (matmul) | 133 |
| `smul16` | mandel / matmul | 100 / 157 |
| `udiv16` / `sdiv16` | arith table | 223 / 250 |
| `udiv32_16` | | 220 |
| `udiv32` (32/16 -> 32) | | 479 |

Division needed a 17-bit partial remainder case for divisors above 0x8000
(`RLC` carries out, `BCS` straight to the subtract). `udiv16` is just
`udiv32_16` entered with a zero high half.

Helpful ISA features here: 32-bit negate is three instructions because
`NEG` sets C exactly when the operand was 0, and `NOT` leaves C alone:

```
        NEG  r1                 ; negate r2:r1
        NOT  r2
        ADC  r2, r0
```

`print.s` avoids division altogether: digits come from repeated subtraction
of powers of ten (at most 9 per digit), which beats a 16- or 32-step
software division per digit. The hex printer shows the single-bit shift
cost (four `SHR`s per nibble, `SWAB` covering the 8-bit part):

```
print_hex16:
        SWAB r2, r1
        SHR  r2
        SHR  r2
        SHR  r2
        SHR  r2                 ; bits 15-12
```

`rand.s` does xorshift's `<< 7`, `>> 9` and `<< 8` with `SWAB` plus at most
one 1-bit shift each, 12 instructions in all. Without `SWAB` it would need
24 single-bit shifts.

Convention friction: `udiv32` has three results (32-bit quotient plus
remainder), so it returns the remainder in r3, outside the documented
r1/r2 result registers.

Library structure friction (tooling, not ISA): the assembler has no
include-once, conditional assembly or macros, and a duplicate label isn't
reported as such (see Tooling). So `print.s` writes to the console port
itself instead of calling `putc`, and helpers can't be shared between lib
files.

### arith

**Easy. Bugs: 0.** Mostly table plumbing. The ISA friction was 32-bit
comparison: `SBC` produces the right C and N/V for a 32-bit subtract, but Z
only reflects the high half, so "compare" is two compares and a branch:

```
ucmp32: CMP  r2, r4
        BNE  .decide            ; high halves differ: they decide
        CMP  r1, r3
        BEQ  .eq
.decide:
        BLO  .lt
```

I first wrote the table loop's back-branch as `JLO` assuming the body was
over 256 bytes; it wasn't (the final code uses `BLO`).

### strings

**Easy. Bugs: 1 assembler error.** `main` grew past 256 bytes, so the six
`BSR`s to helpers placed after it failed and became `CALL`. (The original
error message suggested a nonexistent `JSR`; that has since been fixed.)

`LEA` not touching flags made the string loops nicer: the pointer can be
advanced between the load that sets Z and the branch that tests it.
Seven cycles per character instead of nine:

```
strlen: MOV  r2, r1
.loop:  LDB  r3, [r2]
        LEA  r2, [r2 + 1]       ; flags from LDB survive
        BNE  .loop
```

`memcpy`/`memset` copy words when the alignment allows and unroll four
stores using the free 4-bit offsets. The unary ops' separate source register
saved copies all over (`SHR r5, r3` = "r5 = r3 / 2"). `SHR r0, rX` tests bit
0 into C without touching anything, since r0 discards the result.

### sieve

**Easy. Bugs: 0.** `[label + reg]` (16-bit displacement plus base register)
makes a static byte array a one-instruction access, so the cross-off loop is
four instructions and eight cycles per store:

```
.cross: STB  r0, [flags + r10]
        ADD  r10, r8
        CMP  r10, r11
        BLO  .cross
```

### sort

**Moderate (Hoare partition). Bugs: 1 assembler error.** Again a `BSR` out of
range from `main`, after which I switched every call in `main` to `CALL`
(about half of them would have reached). There are no negative short
offsets, so insertion sort keeps its pointer on the slot *before* the hole
and moves `[r4] -> [r4 + 2]` rather than `[r4 - 2] -> [r4]`. That's a
natural rewrite, and `[r4 - 2]` would only have cost one extra word.

### fib

**Easy. Bugs: 0.** Recursive `fib(18)` (8,361 calls) spends 21% of its
cycles in `PUSH`/`POP` and 15% of its instructions are `CALL`/`BSR`/`RET`.
For the 32-bit iteration, the two-operand `ADD` would need four `MOV`s per
term for `a, b = b, a + b`. Alternating roles (`a += b`, print, `b += a`)
avoids them.

### crc

**Easy. Bugs: 0.** CRC-16 suits the ISA: `SHL` puts the old bit 15 in C, so
each bit is `SHL / BCC / XOR #0x1021`. The table-driven version is 12
instructions, ~26 cycles per byte, using `SWAB` for the 8-bit shifts and
`[table + r4]` for the lookup. Bitwise vs. table: 87 vs. 26 cycles per byte.

### mandel

**Moderate to hard. Bugs: 0; one redesign for the cycle budget.** Most of
the work was choosing the number format and staying inside 3M cycles:

- **Format**: 8.8 rather than 4.12, purely because of shifts. Renormalising
  a product is `>> 8` (`SWAB`, `ZXT`, `SWAB`, `OR`: 4 instructions) versus
  `>> 12` (4 more single-bit shifts on each half).
- **Cost**: 73% of all cycles are inside `umul16`/`smul16`. Squares go to
  `umul16` on magnitudes (skipping `smul16`'s sign handling); only `x*y` uses
  `smul16`. My first view of the set (-2.0..0.5 by -1.1..1.1) needs 8,154
  iterations, 3.0M cycles when measured afterwards (about 370 cycles per
  iteration). I widened the view to cut the number of interior points: 6,673
  iterations, 2.48M cycles.
- **Register pressure**: x, y, cx, cy, the iteration count, xx, yy, |x| and
  |y| fill r6-r14, so the row and column counters live in memory, and `point`
  is a non-standard routine that clobbers r8/r9/r12-r14 (main saves them once
  instead of 960 times).

### life

**Moderate. Bugs: 1 ordinary (missing space in output); 1 test-design
mistake** (I first placed a blinker across the wrap seam right next to the
glider, so they collided on generation 1). Neither had anything to do with
the ISA.

The bordered grid lets the eight neighbour loads use constant offsets 0, 1,
2, 34, 36, 68, 69, 70 from one pointer. Only the first three fit the 4-bit
field; the rest are long forms. That costs code words but no cycles, which
is the right trade. The rule is branchless thanks to `NEG`'s carry and
`MVI` not touching C:

```
        OR   r1, r2             ; (neighbours | self) == 3 is exactly the rule
        ADDI r1, -3
        NEG  r1                 ; C = (r1 == 0)
        MVI  r1, 0
        ADC  r1, r0             ; 0 or 1, no branch
```

There's no "set on condition"; this idiom works but isn't obvious.

### queens

**Easy to moderate. Bugs: 0.** Bitmask backtracking. `NEG rd, rs` with a
separate source gives "lowest set bit" in two instructions
(`NEG r1, r12` / `AND r1, r12`). This is where the two-operand ALU shows
most: building the three masks for the next row is `MOV`+`OR`(+shift) per
mask, and MOV is 21% of executed instructions (12% are `MOV` immediately
followed by an ALU op on the same register, which a three-operand form would
fold). Each recursive call also saves five registers: `PUSH`/`POP` are 34%
of all cycles.

### bst

**Easy. Bugs: 0.** Insertion follows a pointer to the link field, so linking
the new node is one store, and again `LEA` sits between the compare and the
branch:

```
.walk:  LD   r4, [r3]           ; the node at this link, or 0
        BEQ  .link
        LD   r5, [r4]
        CMP  r1, r5
        LEA  r3, [r4 + 2]       ; LEA keeps the flags from the CMP:
        BLO  .walk              ; smaller keys go left...
        ADDI r3, 2              ; ...the rest right
        BRA  .walk
```

### bignum

**Easy (given the library). Bugs: 0.** Base-10000 limbs: `limb * k + carry`
fits in 32 bits with a high word below 10000, so one `udiv32_16` yields both
the new limb and the carry, and printing needs no big division. 80% of the
cycles are in multiply/divide, and `udiv32_16` alone is 61%.

### rpn

**Moderate (parsing). Bugs: 0.** Times ten is `(4x + x) * 2` with shifts
because there's no multiply. All branches stayed in range.

### monitor

**Moderate. Bugs: 2 assembler errors, 1 test-design issue.**

1. `BSR` from `command` to the parsing helpers was 366 bytes. I moved the
   helpers between `command` and the handlers, so the source layout is
   dictated by branch range.
2. I wrote `LDB r1, [r9 + r12]` out of habit. There's no register+register
   addressing; the assembler said "undefined symbol r12". I rewrote the dump
   loop to walk a pointer. `[label + reg]` covers static arrays, but a
   dynamic base plus an index needs an `ADD` into a temporary.
3. A dump of never-written memory relied on the simulator's zero-filled RAM;
   I changed the test input to fill first.

`CALL r3` through a command table and a longjmp-style bail-out
(`LD sp, [errsp]`) were both easy. Hex parsing again needs four `SHL`s per
digit.

### interrupts

**Moderate. Bugs: 0.** The program needs its own vector table and an ISR
that saves what it uses and acknowledges the timer. A race-free `sleep`
depends on the EI shadow: an interrupt can't be taken between `EI` and
`HALT`. That rule is in a comment in `tmc/sim.py`, **not in
`docs/isa-v0.md`**:

```
.wait:  LD   r2, [ticks]        ; interrupts off: the test can't race a tick
        CMP  r2, r1
        BHS  .done
        EI
        HALT                    ; EI shadow: the IRQ can only arrive here
        DI
        BRA  .wait
```

I checked that the output is timing-independent by running copies with
timer periods from 97 to 7,919 cycles (52 to 2,273 interrupts): the output
was identical every time.

`SWI` and illegal instructions share one vector, so the trap handler has to
look at the instruction before the saved PC (`LD r2, [r2 - 2]`, a long form
because the offset is negative) and compare it with `000C`. Saving seven
registers in the handler costs 49 cycles of `PUSH`/`POP`.

### matmul

**Easy. Bugs: 1, caught on review before running.** My first checksum loop
alternated low and high words, with the `ADD` of a low word and the `ADC` of
the high word one iteration apart. The Fletcher `ADD`s and the loop's
`ADDI`/`DEC` in between would have overwritten C. It's the same root cause as
the multiply loop: every add, `ADDI`, `INC` and `DEC` writes C. The k loop
is unrolled with constant offsets (`[r11 + 2*N*k]`, long forms past 30) so
there's no counter or pointer stepping. I guessed the unrolled body was too
long for `BNE` and wrote `JNE`. It was 122 bytes, so the final code uses
`BNE`.

## Measurements

### Dynamic instruction mix

| Program | MOV % | MOV+op % | shifts % | branches % | PUSH/POP cycles % | mul/div cycles % |
|---|---:|---:|---:|---:|---:|---:|
| arith | 1.8 | 0.5 | 9.6 | 26.7 | 0.5 | 21.0 |
| bignum | 2.4 | 0.0 | 23.9 | 35.2 | 1.0 | 80.1 |
| bst | 2.4 | 0.0 | 2.2 | 22.7 | 6.7 | 0 |
| crc | 0.0 | 0.0 | 16.4 | 30.0 | 0.0 | 0 |
| fib | 10.8 | 3.5 | 0.0 | 11.1 | 20.7 | 0 |
| interrupts | 4.9 | 0.0 | 30.4 | 31.1 | 0.7 | 61.0 |
| life | 0.1 | 0.0 | 0.1 | 7.2 | 0.1 | 0 |
| mandel | 11.0 | 1.1 | 25.3 | 25.5 | 0.0 | 73.1 |
| matmul | 4.3 | 1.0 | 30.0 | 25.9 | 0.1 | 78.5 |
| monitor | 3.7 | 2.2 | 7.1 | 25.0 | 2.4 | 0 |
| queens | 21.2 | 12.0 | 4.9 | 10.2 | 34.3 | 0 |
| rpn | 3.5 | 0.7 | 3.4 | 32.2 | 1.8 | 5.4 |
| sieve | 0.0 | 0.0 | 0.0 | 20.2 | 0.0 | 0 |
| sort | 5.8 | 1.6 | 2.7 | 26.3 | 5.0 | 0 |
| strings | 1.1 | 0.1 | 0.7 | 32.7 | 0.9 | 0 |

"MOV+op" is a register `MOV rd, rs` immediately followed by a two-operand
ALU op writing `rd`: the instructions a three-operand ALU would remove
outright. Most of the remaining MOVs move arguments into r1-r4 for calls.
Shifts are mostly inside the multiply/divide loops, and only 0-5% of
instructions are the second-or-later shift of a multi-bit shift sequence.

### Static code (program code, libraries excluded)

1,883 instructions take 2,432 words: **549 extension words, 23% of the code**.
Where the second words come from:

| Long form | Count | Why |
|---|---:|---|
| `CALL addr` | 258 | 192 genuinely out of `BSR` range (mostly library calls, which sit after the program); 66 would have reached but were written defensively |
| `MOV rd, #imm16` | 168 | almost all are addresses of strings and arrays |
| `LD/ST/LDB/STB` absolute | 57 | globals (52) and the I/O page (5) |
| `LD/ST/LDB/STB` with base register | 33 | 18 `[label + reg]` array accesses, 14 offsets just past the 4-bit field (life's neighbours, matmul's column), 1 negative offset |
| other ALU `#imm16` | 21 | `CMP` > 127 (11), `ADD` (5), `XOR` (2), `AND` (1); `OR`/`BIC` with values that fit in 8 bits but have no short form (2; the library has 5 more, e.g. `AND r2, #15`) |
| `JMP addr` | 9 | tail calls into the library, vector table |
| `LEA` | 3 | always long |

Branches: 160 conditional `Bcc`, 52 `BRA`, 61 `BSR`. **No conditional branch
needed the long `Jcc` form** in the final code. The three I wrote
defensively all turned out to be unnecessary.

## Problems, ranked by what they cost

1. **No multiply or divide.** 61-80% of cycles in `mandel`, `matmul`,
   `bignum` and `interrupts`; 21% in `arith`. A multiply costs 72-157 cycles,
   a 32/16 divide ~220, a 32/16 -> 32 divide ~480. It also drives other costs:
   most of the shift instructions in the table above are inside these loops,
   and the fixed-point format in `mandel` was chosen to make renormalisation
   cheap.
2. **Call and register-save overhead.** `PUSH` is 3 cycles and `POP` 4, one
   register at a time. 34% of `queens`, 21% of `fib`, 5-7% of `sort`/`bst`.
   The trap handler spends 49 cycles saving and restoring seven registers.
3. **Branch range, as handled by the assembler.** ±256 bytes is enough for
   every conditional branch I wrote. But `BSR` to anything outside the
   current function, especially the library, is out of range, and the
   assembler reports an error instead of relaxing to `CALL` (it does relax
   `LD`/`MOV`). Cost: 3 of my 4 assembler errors, one source file reordered
   to fit (monitor), a policy of writing `CALL` everywhere (+1 word per call,
   0 cycles), and 3 defensive long jumps that weren't needed.
4. **`INC`/`DEC`/`ADDI` write C.** No loop counter can coexist with a carry
   that must survive an iteration. It forced the shape of the multiply loop,
   caused my one real flag bug (matmul, caught before running), and would
   matter for any multi-word add/shift loop. `LEA` is a flag-free way to
   bump a pointer, but there's none for a counter you have to test.
5. **Single-bit shifts.** Inherent in software multiply and divide (24-30% of
   instructions in those programs). Outside them they cost little: hex
   printing and parsing (4 shifts per nibble), and 8.8 vs 4.12 fixed point.
   `SWAB` removes most of the pain for 8-bit shifts.
6. **Two-operand ALU.** Directly foldable `MOV`+op pairs are 12% of
   instructions in `queens`, 3.5% in `fib`, and 2% or less elsewhere. The
   unary group already takes a separate source register, which covers the
   most common case (`SWAB r2, r1`, `NEG r1, r12`, `SHR r5, r3`). I don't
   think a three-operand ALU is worth the encoding pressure on this evidence.
7. **Addressing modes.** No register+register mode (one error, monitor). No
   negative short offsets (one rewrite in isort, one long form in the trap
   handler). 4-bit offsets forced 14 long forms. The offset limits cost code
   size only, never cycles, because long forms are free in time; the missing
   register+register mode costs an `ADD` into a temporary where it's needed.
8. **Immediates.** `CMP` with values outside -128..127 takes the 2-word form
   *and* 2 cycles instead of 1 (`CMPI` merges with the next fetch; the long
   `CMP` can't). In `mandel` the `CMP #imm16`s (the |x|, |y| < 2.0 and
   xx + yy > 4.0 checks) are 1.7% of all cycles, half of which a 1-cycle form
   would save.
   `AND`/`OR`/`BIC` with small masks have no short form (7 static cases).
   Loading addresses is the biggest single source of extension words (168),
   but that's inherent in 16-bit addresses.
9. **Multi-word compare.** `SBC` gives C and N/V for the full width but Z only
   for the high half, so 32-bit compares branch on the high half first
   (`ucmp32`/`scmp32` in arith, the leading-zero skip in `print_u32`).
10. **Interrupts and traps.** Mostly fine; the issues are documentation (EI
    shadow, see below) and one shared vector for `SWI` and illegal
    instructions, which makes the handler decode `[PC - 2]`.

Things that did **not** cause trouble: byte handling (`LDB` zero-extends
and sets flags, `STB`, `SXT`/`ZXT`, `SWAB`), the condition codes, stack
addressing (`LD rd, [sp + 2o]` reaches the top 16 words), and the absence of
`SEC`/`CLC` (never needed). `POP` setting N and Z means a routine can't
return a status in the flags past its epilogue; none of mine wanted to.

## Things that worked well

- **Loads, `MOV` and `POP` set N and Z.** String loops need no `TST`
  (`LDB` / `BEQ`), and `LD r2, [x]` / `BNE` tests a variable directly.
- **`LEA` doesn't touch the flags**, so it serves as a flag-free add
  (strlen, strcpy, bst).
- **`[label + reg]`**: a 16-bit displacement plus a base register indexes a
  static array in one instruction (sieve, crc table, bignum limbs, rpn stack,
  palette and hex-digit lookups).
- **Long forms cost no extra cycles** (except `CMP #imm16`). The 4-bit offset
  field and the short branch range are code-size trade-offs, not speed ones.
- **Unary ops with a separate source** (`rd <- f(rs)`), plus `SWAB`, `ZXT`,
  `SXT`.
- **`r0` reads as zero**: `ADC r2, r0` propagates a carry, `STB r0, [...]`
  stores zero, `SHR r0, rX` tests bit 0 into C without changing anything.
- **Logic ops, `MOV` and `MVI` leave C alone**, which makes the 3-instruction
  32-bit negate and the branchless life rule possible.
- **`SHR` sets C and Z together**, which makes an early-exit multiply loop
  cheap.
- **`CMPI` is 1 cycle** and the 8-bit range covers characters and small
  constants.
- **`CALL rs`** for dispatch tables (crc's test list, monitor's commands).
- **Interrupt model**: `RTI` restores flags, the `EI` shadow makes
  `EI; HALT` atomic, and the level-triggered timer is simple to acknowledge.
  The interrupt test's output didn't change across an 80x range of timer
  periods.

## Suggested changes

In rough order of benefit per unit of hardware.

1. **Multiply and divide in the reserved op B.** Suggested: `MULU`/`MULS`
   (16x16 -> 32 into a register pair) and `DIVU` (32/16 -> 16 quotient and
   remainder, the `udiv32_16` contract). At roughly one cycle per bit
   (~20 cycles multiply, ~40 divide), my estimates from the measured
   profiles are: `mandel` 2.48M -> ~1.0M cycles (2.4x), `matmul` 102k ->
   ~31k (3.3x), `bignum` 147k -> ~51k (2.9x). At two cycles per bit, `mandel`
   would still drop to ~1.35M (1.8x). I can't judge the hardware cost: as far
   as I can tell from `tmc/hw/microcode.py`, the sequencer can only make the
   PC load conditional, so a microcoded shift-and-add needs a way to make
   each step's add depend on a multiplier bit. A one-bit multiply-step or
   divide-step instruction (2-3 cycles per step, 16 of them in a row) would
   need the same conditional add but no microcode loop, and would still
   roughly halve the current routines.
2. **Fix the assembler before the ISA for branches**: relax `Bcc` -> `Jcc`
   (or an inverted `Bcc` over a `JMP`) and `BSR` -> `CALL` automatically,
   like the `LD`/`MOV` relaxation already does. No hardware cost; it removes
   3 of the 4 assembler errors I hit and recovers up to 66 words of
   defensively long calls. I would not widen the branch offset.
3. **Make `INC` and `DEC` leave C (and V) alone**, as on the PDP-11. This is a
   microcode-only change: they would set N and Z only. None of my code used
   the C or V output of `INC`/`DEC` (`ADDI` remains for when you want them).
   It enables counted loops around carry chains and removes the trap I nearly
   fell into in matmul.
4. **Multi-register save/restore**, e.g. two of the free system-group
   functions as `SAVE n` / `RESTORE n` (push or pop r8..r(7+n)), and
   `RESTORE` could also return. At about n+2 cycles each instead of 3n and
   4n: `queens` -20% of cycles, `fib` -9%, the trap handler's save cost
   -60%. This needs a register-number counter in the microcode, so it isn't
   free.
5. **Document the interrupt timing rules** in `isa-v0.md` (see below). Free,
   and needed to write correct interrupt code.
6. Lower priority, based on the evidence here: a nibble shift
   (`SHL4`/`SHR4` in the free unary slots C-F) would help hex conversion
   only; a short `AND` immediate, a register+register addressing mode and a
   three-operand ALU would each save a few percent at most in these
   programs. A trap-cause register (or a separate `SWI` vector) would
   simplify trap handlers but matters only to system code.

## Documentation issues in `isa-v0.md`

*Since fixed: `isa-v0.md` now documents the interrupt timing rules, `HALT`,
the console's end-of-input bit (`FF02` bit 1), `[label + reg]`, `lo16`/`hi16`
and a third result register. The list below is what the programmer had to
work with.*

- **The EI shadow isn't documented.** `tmc/sim.py` says an interrupt can't be
  taken right after `EI`, can still be taken right after `DI`, and is taken
  right after `RTI` if the restored flags enable it. Race-free
  `EI; HALT` depends on the first rule. The ISA document should state all
  three.
- **HALT with interrupts enabled**: the document doesn't say what happens if
  an interrupt is already pending (the microcode ends `HALT` immediately) or
  if no interrupt source is enabled (the hardware would wait forever; the
  simulator stops).
- **Console end of input**: `FF00` returns `FFFF` "if none", which on real
  hardware means "nothing waiting yet", not end of file. `getc`'s "-1 on EOF"
  relies on the simulator preloading all input. A distinct EOF indication
  (e.g. `FF02` reading 2 at end of input) would make that well defined.
- The assembler accepts `[label + reg]` (register last); the syntax section
  only shows `[reg + offset]` and `[label]`. `lo()`/`hi()` are byte
  functions; the document doesn't say so, and there is nothing for the
  16-bit halves of a 32-bit constant (I used `x & 0xFFFF` and `x >> 16`).
- The calling convention has no rule for routines with more than two
  results (`udiv32` returns its remainder in r3).

## Tooling issues

*Since fixed: duplicate labels and conflicting `.equ`s are reported with
both locations; `Bcc` and `BSR` relax to `Jcc` and `CALL` when out of range;
`[reg + reg]` gets a proper error; and `HALT` with an interrupt already
pending takes it at once in the simulator. Macros, conditional assembly and
include-once are still missing.*

- **Duplicate labels** make the assembler fail with "assembly did not
  converge" and no file or line. `one_pass` in `tmc/asm.py` never checks for
  redefinition, so the label alternates between two addresses on every pass.
  `.equ` redefinition is silently accepted.
- **No branch relaxation** for `Bcc`/`BSR` (see above).
- **`[r9 + r12]` reports "undefined symbol r12"**. It should say that
  register+register addressing doesn't exist.
- **No macros, conditional assembly or include-once.** Every lib file has to
  be self-contained, and repeated idioms (`LI r1, #msg` / `CALL puts`) can't be
  abbreviated.
- **Simulator `HALT` with a pending interrupt**: `Machine.step` advances the
  clock to `timer_next` even if the timer flag is already set, so an
  interrupt that is already pending is taken one period late. The microcode
  ends `HALT` at once in that case. Measured with a small test: 112 cycles
  from `EI; HALT` to the end of the ISR instead of ~20. The timer event in
  between merges with the pending one, so over that span the simulated
  program also counts one tick fewer than the hardware would. Cycle counts
  will differ from the chip-level simulator. The `interrupts` test isn't
  affected: it prints only differences in ISR counts.
