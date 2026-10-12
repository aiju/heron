# Notes: the draft 1 library and first programs, in 1a and 1b

A first-hand log of writing the shared library (`programs/v1a/lib/`,
`programs/v1b/lib/`) and the programs `hello`, `arith` and `strings` for both
draft 1 candidates. It records what happened while writing them, including
the mistakes, as evidence for choosing between the two encodings. For each
file I alternated which ISA I wrote first, so neither always got the benefit
of a second attempt.

Cycle numbers are from `python3 -m tmc --isa ... run --stats` (the
instruction-level simulator with the `timing32` model, described in
`docs/timing-model-v1.md`); I quote `D16-overlap` (the simulator's reference
configuration, the one in the `tmc test` cycles column: a 16-bit datapath
and bus like draft 0's) and `D32-wide` (the fastest). The two bracket the
range, so where the ISAs' ranking differs between them I say so.

## Summary

- **Everything worked first time, in both ISAs.** Over 4 library files and
  3 programs per ISA I had no assembler errors, no wrong output and no
  traps. The one behaviour change came from my own test: `gets` now leaves
  an empty string at the end of input. Scratch tests (not committed)
  covered far more than the three programs: 5,728 `memcpy`/`memmove`/`memset`
  cases, `str*` at every alignment, `gets` with buffers of 1, 2, 3 and 8
  bytes, all
  number printers at their edge values, and `rand` against `XorShift16`
  including the full period.
- **Most of the library is ISA-neutral.** Hardware `MUL`/`DIV`/`DIVUL`,
  32-bit registers, shifts by n, `SETcc`, `SAVE`/`RESTORE` and unary ops
  with a separate source make the code much shorter than draft 0's, and
  they're the same in both drafts. `print.s`, `rand.s` and `arith` are
  nearly token-for-token identical between 1a and 1b; code sizes are within
  2 bytes for `console`, `print` and `rand`.
- **1b's advantage is concentrated in byte-pointer loops.** Auto-increment
  plus memory operands cut the byte loops by 25-42% in instructions
  (`strcpy` 3 per byte against 5, `strcmp` 4 against 7) and `string.s` is
  21% smaller (230 vs 292 bytes). Whole programs: `strings` runs 19% fewer
  instructions in 1b, `arith` 7%.
- **The cycle advantage is much smaller than the instruction advantage, and
  can reverse.** In the timing model an auto-increment access costs one
  cycle more than a plain `[r + d]` access on the 32-bit configurations, so
  1a's unrolled `LD r4, [r2 + 4]` blocks beat 1b's `[r2]+` for aligned
  `memcpy` and `memset` on D32-wide. And 1b's 4-bit constants make every
  character constant a 2-parcel instruction, so `upcase` is slower in 1b
  on D16-overlap despite fewer instructions. `strings` is 12% faster in 1b
  on D16-overlap and 6% on D32-wide; `arith` 3% on both.
- **Each ISA has a characteristic gap.** 1a: `ADDI` sets Z, so a pointer
  step can't sit between a load and the branch testing it (I used a
  pre-increment idiom; `LEA` is flag-free but 2 parcels), and there's no
  register+register addressing. 1b: no byte/half auto-decrement (backwards
  byte loops), no half auto-increment, no `TST`/`BIC`/`MUL`/`DIV` with an
  immediate, and `[label + r]` only reaches 16-bit labels. Both: `INC`,
  `DEC`, `ADDI` and `TST` leave V alone, so signed branches after them test
  a stale V.

## Log

### lib/console.s (1a first)

Both versions assembled and passed a scratch test (lines that fit, an
over-long line, an empty line, high bytes 0x80/0xFF, a last line without
`\n`, then `getc` at the end) on the first run, apart from one thing I hadn't
decided: what `gets` leaves in the buffer at the end of input. My test
expected an empty string, the code (like draft 0's) left the previous line
there. I made both versions store a NUL first, which is one instruction and
safer for callers that print the buffer without checking for -1.

- **End of input is now a sign test in both.** The console register reads as
  a 32-bit word, 0-255 or -1, so `LD r4, [r5]` / `MOV r4, [r5]` sets N
  exactly at the end of input and `BMI` replaces draft 0's `CMPI r4, -1`.
  (A byte load would give 0xFF for both, so input must use word loads; worth
  a sentence in the spec.)
- **The I/O page at the top of memory works as promised**: `STB r1,
  [0xFFFFFF00]` (1a, `r0 + disp16`) and `ST r1, byte [0xFFFFFF00]` (1b,
  mode F5) are both 2 parcels, and the assembler picks the short form from
  the 32-bit value without help. In loops I put the address in a register
  so the store is one parcel in both.
- **`puts` is where auto-increment first shows**: 4 one-parcel instructions
  per character in 1a, 3 in 1b.

  ```
  ; 1a                              ; 1b
  .loop:  STB  r2, [r3]             .loop:  ST   r2, byte [r3]
          ADDI r1, 1                .next:  MOV  r2, byte [r1]+
  .next:  LDB  r2, [r1]                     BNE  .loop
          BNE  .loop
  ```
- **Small constants cut the other way.** `MOV r1, #' '` and `CMP r4, #10`
  fit 1a's 8-bit `MVI`/`CMPI` (1 parcel); in 1b `#10` fits the 4-bit
  constant mode but `#' '` (32) needs a second parcel. Characters are
  mostly above 15, so 1b pays a parcel for nearly every character constant.
- `gets` has the same structure in both and is one instruction shorter in
  1b (21 vs 22), where `ST r4, byte [r3]+` saves the `ADDI`. The inner loop
  is not where the time goes anyway: each character costs a word load from
  the I/O register and two compares in both. Both store `r0` directly to
  write the NUL (`STB r0, [r3]` /
  `ST r0, byte [r3]`), which is a nice side effect of `r0` being a real
  register number in both encodings.

### lib/print.s (1b first)

Both versions passed a scratch test on the first run (u32 edge values, s32
including -2^31, zero padding wider and narrower than the number, u64 up to
2^64-1 and around 10^10 and 10^19, hex with 1-8 digits).

- **Hardware divide makes this trivial** compared with draft 0's
  power-of-ten subtraction tables: `DIVU r1, r5` / `MFHI r3` gives the next
  digit, and the whole decimal printer (u32, s32 and zero padding) is 25
  instructions in both ISAs. The digits are pushed and popped, which needs
  no buffer and no reversal. The price is time: `DIVU` is 35 cycles on
  D32-overlap and 67 on D16-overlap, so `print_u32` of a 10-digit
  number costs about 560-960 cycles, and printing is the biggest cost in
  `arith` (44% of its cycles). A reciprocal multiply wouldn't help with
  this timing model: `MULU` by `0xCCCCCCCD` takes 33 iterations, as long
  as the divide.
- **`DIVUL` makes 64-bit printing as natural as the spec promises**: two
  instructions per digit while the high word is non-zero, then the 32-bit
  loop takes over.

  ```
  .div:   DIVU  r2, r5            ; high word / 10, remainder in HI...
          DIVUL r1, r5            ; ...on top of the low word: (HI:low) / 10
          MFHI  r3                ; the digit
  ```
  Only a 64-by-32 divide with a 32-bit quotient would need care; here `HI`
  is always a remainder (< 10), so `DIVUL` can't overflow.
- **Flag trap avoided, but only by thinking about it**: `DEC`, `INC`,
  `ADDI` and `TST` set N and Z but leave V alone, so `BGT`/`BLE`/`BGE`/`BLT`
  after them test a stale V. My first sketch of the padding loop was
  `DEC r2; BGT .loop`, which happens to work only because the `DIVU` before it
  cleared V. I rewrote it with `BMI`, which only needs N. Rule of thumb for
  both ISAs: after `INC`/`DEC`/`ADDI`/`TST` use only `EQ NE MI PL`. Worth a
  line in the spec next to the flags table.
- The code is almost token-for-token the same in both ISAs: `MVI` vs `MOV
  #`, `STB` vs `ST byte`, `LDB r3, [__pr_hexdigits + r3]` vs `MOV r3, byte
  [__pr_hexdigits + r3]`. Differences: `AND r3, #15` is 1 parcel in 1b
  (4-bit constant) but 2 in 1a (op 8); `MOV r2, #'-'` is 2 parcels in 1b and
  1 in 1a. `POP` in 1b sets NZ (it is `MOV r, [sp]+`), in 1a it doesn't
  (`RESTORE`); it didn't matter here.
- Test harness totals (all of the above plus the console tests): 1a 3,651
  instructions / 25,689 cycles (D16-overlap) / 15,314 (D32-wide); 1b 3,611 /
  25,593 / 15,417. A dead heat: the divide (35-67 cycles each) dominates.

### lib/string.s (1a first)

Both versions passed on the first run: a scratch test of 5,728 cases
(`memcpy` for every dst/src alignment 0-7 and lengths 0-20, 31-33, 40;
overlapping `memmove` in both directions; `memset` at every alignment with
junk above the fill byte) compared byte for byte with Python. `strlen`,
`strcpy` and `strcmp` are covered by `strings`.

Per-call cost, measured as the difference between a run with two calls and
one with one call (scratch benchmark):

| Routine | 1a instr | 1a D16-overlap | 1a D32-wide | 1b instr | 1b D16-overlap | 1b D32-wide |
|---|---:|---:|---:|---:|---:|---:|
| `strlen` (100 chars) | 309 | 828 | 720 | 208 | 627 | 621 |
| `strcpy` (100) | 511 | 1,435 | 1,125 | 308 | 928 | 923 |
| `strcmp` (100, equal) | 708 | 1,827 | 1,520 | 408 | 1,329 | 1,224 |
| `puts` (100) | 407 | 1,122 | 916 | 307 | 924 | 820 |
| `memcpy` 1000, aligned | 780 | 2,782 | 1,810 | 652 | 2,395 | 2,058 |
| `memcpy` 1000, misaligned (bytes) | 6,013 | 17,040 | 13,024 | 4,013 | 12,040 | 11,029 |
| `memmove` 1000, backwards | 6,013 | 17,041 | 13,025 | 4,009 | 15,029 | 13,021 |
| `memset` 1000 | 479 | 1,670 | 982 | 413 | 1,470 | 1,104 |

- **Byte-pointer loops are 1b's home ground.** `strlen`, `strcpy` and
  `strcmp` run 33-42% fewer instructions in 1b (`puts` 25%), and the code
  reads like C:

  ```
  ; strcpy, 1a: 5 per byte                ; strcpy, 1b: 3 per byte
          LEA  r3, [r1 - 1]                       MOV  r3, r1
          ADDI r2, -1                     .loop:  MOV  r4, byte [r2]+
  .loop:  ADDI r2, 1                              ST   r4, byte [r3]+
          ADDI r3, 1                              BNE  .loop
          LDB  r4, [r2]
          STB  r4, [r3]
          BNE  .loop

  ; strcmp, 1b: a memory operand *and* auto-increment in one instruction
  strcmp: MOV  r3, byte [r1]+
          BEQ  .end
          SUB  r3, byte [r2]+
          BEQ  strcmp
  ```
- **But the cycle gap is much smaller than the instruction gap,** and on the
  32-bit configurations it can reverse. In the timing model an
  auto-increment access costs one cycle more than a plain `[r + d]` access
  (the base register write-back competes for the register port): on
  D32-wide `MOV r4, [r2]+` is 4 cycles and `ST r4, [r1]+` 3, against 3 and 2
  for 1a's `LD r4, [r2 + 4]` / `ST r4, [r1 + 4]`. So 1a's unrolled block
  (four `LD`/`ST` pairs with offsets 0/4/8/12, then two `ADDI`s) beats 1b's
  four `[r]+` pairs: aligned `memcpy` is 1,810 vs 2,058 cycles and `memset`
  982 vs 1,104 on D32-wide, while 1b still wins on D16-overlap. For byte
  loops 1b stays ahead, by 12-35% on D16-overlap and 0-20% on D32-wide
  (the 0% is the backwards `memmove`, see below).
- **1a's flag-preserving pointer step is in the wrong place for loops.**
  `ADDI` sets N and Z, so it can't sit between a load and the branch that
  tests it; `LEA r, [r + 1]` (which leaves flags alone) is two parcels in
  1a. The idiom I settled on is to advance the pointer *before* the load
  (pre-increment, starting at `p - 1`), which keeps every instruction in the
  loop one parcel. It works but is the kind of thing you have to think of.
- **1a's one-parcel `[r + 4o]` and `[r + o]` offsets make unrolling cheap,**
  which is the RISC answer to auto-increment, and it pays for word copies.
  For byte copies the 0-15 byte offset could also unroll `strcpy`, but each
  byte still needs a load, a store and a test.
- **1b has no byte (or half) auto-*decrement*.** Word pre-decrement exists
  (it's the push), but a backwards byte loop can't use it. In `memmove` I
  used the indexed mode with the count as the index instead, so the
  pointers never move:

  ```
  .back:  MOV  r4, byte [r2 + r3 - 1]
          ST   r4, byte [r1 + r3 - 1]
          DEC  r3
          BNE  .back
  ```
  Four instructions against 1a's six, but the two indexed accesses are 2
  parcels and 4-5 cycles each, so the cycle counts end up equal on D32-wide
  (13,021 vs 13,025) and 1b is only 12% ahead on D16-overlap.
- **Missing immediate forms in 1b show up in small ways.** 1b has no `TST`
  with an immediate, so the "both pointers equally aligned?" check is `AND
  r4, #3` on a scratch copy (fine here, since r4 was a copy anyway). 1a's
  `TST r4, #3` is 2 parcels; 1b's `AND r4, #3` is 1 parcel thanks to the
  4-bit constant. Replicating the fill byte: 1a can `MULU r2, #0x01010101`
  in one 3-parcel instruction; 1b needs `MOV r4, #0x01010101` and `MULU r2,
  r4` (MUL/DIV are register-only in 1b).
- One unsigned compare decides `memmove`'s direction in both: `dst - src >=
  n` (wrapping) means forward is safe. Same code in both ISAs.
- No mistakes in this file in either ISA; I had worked out the alignment
  logic (bytes until `dst` is aligned, only if `(dst ^ src) & 3 == 0`;
  16-byte blocks, then words, then bytes) before writing either version.

### lib/rand.s (1b first)

Identical code in both ISAs apart from three mnemonics (`MOV r1, #1` / `MVI
r1, 1`, and the load of the state), so I wrote 1b and derived 1a by hand.
Both reproduce `XorShift16` for eight seeds including 0, 0x10000 (low half
0, so it becomes 1) and 0xFFFF, and the period from seed 1 is 65535.

- With 32-bit registers the 16-bit generator needs care: the left shifts
  push bits above bit 15, and the following `x >> 9` would pull them back
  down. So the first step is cut back with `ZXH`, and the last step only
  shifts the low byte (`ZXB r2, r1` / `LSL r2, #8`), which can't overflow.
  The unary ops' separate source register (`ZXB r2, r1`) saves a `MOV` in
  both ISAs. 12 instructions, against 14 in draft 0 where the shifts by 7
  and 9 had to be built from `SWAB` and single-bit shifts.
- Neither ISA has a 3-operand shift (`rd ← rs << n`), so every
  `x ^= x << k` is `MOV`, shift, `XOR` in both.

### hello.s (1a first)

Trivial in both: `LEA r1, msg` / `LEA r1, [msg]`, then a tail call `BRA
puts` (the assembler relaxes it to a jump if needed). 67 instructions in
1a, 53 in 1b, all of the difference in `puts`. Both assemblers accept both
`LEA` spellings: in 1a `LEA r1, msg` is PC-relative and `LEA r1, [msg]` the
absolute `r0 + disp16` form; in 1b both are the 16-bit absolute mode. One
oddity: in 1a, `LI r1, #msg` assembles to a one-parcel `MVI` when the label
happens to be below 128.

### strings.s (1a first)

Both versions passed on the first run.

| | instr | D16-overlap | D32-wide | code bytes |
|---|---:|---:|---:|---:|
| 1a | 7,058 | 21,103 | 16,004 | 1,090 |
| 1b | 5,748 | 18,658 | 15,057 | 1,036 |

1b runs 19% fewer instructions, 12% fewer cycles on D16-overlap and 6% fewer
on D32-wide. `puts` is the biggest single cost in both (36-38% of cycles).

- **Walking tables**: in 1b `MOV r9, [r8]+` / `BEQ .done` loads, steps and
  tests in one instruction; in 1a it's `LD r9, [r8]` / `BEQ` plus an `ADDI
  r8, 4` at the bottom of the loop. Three-byte records read naturally with
  `MOV r9, byte [r8]+` three times in 1b; 1a uses its one-parcel offsets
  `LDB r9, [r8]`, `LDB r10, [r8 + 1]`, `LDB r11, [r8 + 2]` and one `ADDI`.
  Neither is awkward.
- `LEA r1, [buf + r9]` (a static array plus a register) is one 2-parcel
  instruction in both and was handy for "buffer + offset from a table".
- **`upcase` is the clearest case of 1b's constants costing more than
  auto-increment saves.** 1b executes fewer instructions (325 vs 379) but
  takes more cycles on D16-overlap (932 vs 883), because three of the loop's
  constants are 2 parcels:

  ```
  ; 1a: all one parcel                    ; 1b
  .loop:  LDB  r2, [r1]                   .loop:  MOV  r2, byte [r1]+
          BEQ  .done                              BEQ  .done
          ADDI r2, -'a'                           SUB  r2, #'a'     ; 2 parcels
          CMPI r2, 26                             CMP  r2, #26      ; 2 parcels
          BHS  .next                              BHS  .loop
          ADDI r2, 'A'                            ADD  r2, #'A'     ; 2 parcels
          STB  r2, [r1]                           ST   r2, byte [r1 - 1]  ; 2 parcels
  .next:  ADDI r1, 1                              BRA  .loop
          BRA  .loop
  ```
  It also shows a small cost of post-increment in read-modify-write loops:
  by the time 1b stores the byte back, the pointer has moved on, so the
  store needs a `- 1` displacement (2 parcels).
- In `wordcount` I kept `' '` in a register in 1b so the two compares are
  one parcel; in 1a `CMPI r2, ' '` is one parcel anyway. With more live
  values this workaround would cost a register.
- `reverse` needs a byte pointer moving down, which 1b can't
  auto-decrement: `ST r4, byte [r1]+` moves the front pointer, but the back
  one needs a separate `DEC r2`.
- In 1a, `ADDI` setting Z decided the shape of every byte loop: `strlen`
  and `reverse` step the pointer *before* the load (pre-increment), while
  `strcmp`, `upcase` and `wordcount` step it after the test of the loaded
  byte, which is fine there only because a compare follows anyway. This is
  the one thing I'd change in 1a: an `ADDI` that left Z alone (or a
  one-parcel `LEA`) would allow the natural order, load, step, branch, as
  in draft 0's `strlen`. (The spec calls `ADDI` "flag-preserving" in the
  sense that it leaves C and V alone, which is what loop counters need, but
  for pointer steps it is Z that matters.)

### arith.s (1b first)

Both versions passed on the first run.

| | instr | D16-overlap | D32-wide | code bytes |
|---|---:|---:|---:|---:|
| 1a | 18,876 | 94,408 | 62,524 | 646 |
| 1b | 17,622 | 91,602 | 60,431 | 638 |

The program is almost all calls to `puts` and the number printers, so it
hardly distinguishes the ISAs: `main` itself is 1,748 vs 1,728
instructions. I wrote 1b first; the 1a version differs only in the table
loads (`LDH`/`LD` with offsets and an `ADDI` per record, against 1b's
`half [r8]` and `[r8]+`), `MVI` for `MOV #`, and the `LEA` spelling.

- **16-bit arithmetic on a 32-bit machine is easy with the extend ops.**
  The 16-bit operands are loaded zero-extended (`LDH` / `MOV r, half [..]`)
  for the unsigned operations, and `SXH r1, r9` makes the signed copy
  without disturbing the original. Then the 32-bit `MULU`/`MULS` give the
  exact 16 x 16 products and `DIVU`/`DIVS` the exact quotients. To print
  the 16-bit signed quotient the reference expects, one `SXH r1` after
  `DIVS` turns 32768 (from -32768 / -1) into -32768. 1a's sign-extending
  loads (`LDSH`) weren't needed: `SXH` from a register is one parcel, the
  long-form `LDSH` two.
- **Three-way compares with `SETcc`**: `CMP r9, r10` / `SETHI r1` / `SETLO
  r2` / `SUB r1, r2` gives -1, 0 or 1 with no branches, which then indexes
  `"<=>"`. Same four instructions in both ISAs, and the signed version just
  swaps in `SETGT`/`SETLT`. Draft 0 needed two compare subroutines of ~10
  instructions each for the 32-bit compares.
- **Division by zero is now a trap**, so the program must test the divisor
  first (draft 0's software divide returned an all-ones quotient instead).
  Natural enough.
- **1b has no half auto-increment**, so the 16-bit table is read with
  `MOV r9, half [r8]` and `MOV r10, half [r8 + 2]` (2 parcels) and an `ADD
  r8, #4`. Exactly what 1a does with `LDH`.
- Printing dominates: `__pr_digits` (the `DIVU` loop) is 44% of the cycles
  and `print_hex` another 25%. Compared with draft 0's arith (42,306
  instructions), both drafts run less than half the instructions, but the
  cycle counts are of the same order because every decimal digit now costs
  a 67-cycle divide on a 16-bit datapath (draft 0 printed 16-bit numbers by
  subtracting powers of ten, which was cheap for small values). Different
  timing models, so only a rough comparison.

## Things in the specs that were unclear or worth stating

- **`DIVUL` overflow**: the spec says it "sets V and leaves `rd` and `HI`
  unchanged" but not what happens to N, Z and C (the flags table says "NZ
  from the quotient; C = 0", and there is no quotient). The simulator leaves
  them unchanged. Not a problem for the library, which never lets `DIVUL`
  overflow.
- **Console input must be read as a word.** The I/O section says byte
  accesses work on the low byte, so a byte read at the end of input gives
  0xFF, indistinguishable from a real 0xFF byte. Worth saying explicitly.
- **V after `INC`/`DEC`/`ADDI`/`TST`**: these leave V unchanged, so `GT`,
  `GE`, `LT`, `LE` after them test whatever an earlier instruction left. A
  warning next to the flags table would save someone a bug. (I avoided it in
  `print.s` by using `BMI`, see above.)
- **1b's `[label + r]` is limited to a 16-bit label**: `MOV r1, byte [tab +
  r2]` with `tab` at 0x9000 is an assembly error ("displacement doesn't fit
  in 16 bits: compute the address in a register"); 1a quietly uses its
  32-bit-displacement form (`A12C 9000 0000`). So in 1b, static tables
  indexed by a register must live in the low (or top) 32 KB. Not a problem
  for these programs, but a real difference in a 1 MB address space, and
  the 1b document only implies it.
- **Which operand is the multiplier?** `docs/timing-model-v1.md` says a
  multiply takes one step per multiplier bit and stops when the rest of the
  multiplier is zero, but not which operand that is; the code
  (`alu_timing`) uses the *source* (second) operand. So operand order
  matters for speed: `MULU r2, #0x01010101` in `memset` costs 25 steps,
  while `MULU r4, r2` with r4 = 0x01010101 and r2 = the byte would cost 8.
  Worth stating, since a programmer would put the small value second. I
  kept the natural form in `memset`, where it runs once per call. (I first
  missed the timing document: it wasn't in `docs/` when I listed it at the
  start.)

## Tool bugs and quirks

- **`tmc run` re-encodes output bytes above 0x7F as UTF-8.** `run32` in
  `tmc/__main__.py` writes `m.dev.out.decode("latin-1")` to a UTF-8
  `sys.stdout`, so a program printing 0xE9 produces `C3 A9`. Reproduce:
  `python3 -m tmc --isa v1a run programs/v1a/strings.s | cmp -
  programs/expected/strings.txt` reports a difference at byte 325 (the
  `strcmp("\xE9t\xE9", ...)` line), although `tmc test strings` passes.
  Workaround: `PYTHONIOENCODING=latin-1`. (Fix: write the bytes to
  `sys.stdout.buffer`.)
- No assembler or simulator bugs found otherwise: every encoding I checked
  in the listings matched the specs, and the shortest-form selection
  (absolute I/O addresses, `[r2 + 0]`, constants 0-15, `MVI` vs op 8) did
  what the documents say.
- Process note: the scratchpad directory is shared with the agents writing
  the other programs, and one of them overwrote a scratch script of mine
  (`prof.py`) with its own. Harmless, but parallel agents should use
  separate subdirectories.
