# Notes: sieve, sort, fib, crc and bignum in draft 1a and 1b

A first-hand log of writing five of the draft 0 benchmark programs for both
draft 1 candidates (`programs/v1a/NAME.s`, `programs/v1b/NAME.s`). Each
program was written fresh for each ISA from the reference function in
`programs/reference.py` (and the draft 0 version, for the algorithm), using
the shared libraries in `programs/v1?/lib/`. I alternated which ISA came
first. Cycle numbers are `D16-overlap` (the reference configuration) unless I
say otherwise; they come from `run --stats` and a small scratch profiler that
sums the simulator's per-instruction timing keys by label.

The timing model changed while I was working (1b auto-increment now costs
the same as a plain `[r]` access). All numbers here are from the new model;
1a's numbers didn't change, and 1b's moved by 0.1-4% (sieve the most). I
re-measured the two places where I had chosen between variants by cycle
count (see sort and fib) and both choices still stand.

## Results

| Program | ISA | Instructions | Cycles D16-overlap | Cycles D32-wide | Code bytes (with libs) | Code bytes (program only) |
|---|---|---:|---:|---:|---:|---:|
| sieve | 1a | 82,869 | 221,285 | 159,988 | 682 | 144 |
| sieve | 1b | 72,090 | 205,353 | 146,602 | 608 | 134 |
| sort | 1a | 40,679 | 123,099 | 83,237 | 668 | 380 |
| sort | 1b | 35,665 | 109,147 | 72,955 | 654 | 368 |
| fib | 1a | 99,029 | 363,326 | 243,369 | 364 | 118 |
| fib | 1b | 94,443 | 358,072 | 234,160 | 364 | 120 |
| crc | 1a | 77,903 | 217,018 | 159,384 | 480 | 192 |
| crc | 1b | 72,392 | 205,386 | 151,437 | 464 | 178 |
| bignum | 1a | 5,676 | 33,760 | 20,501 | 724 | 186 |
| bignum | 1b | 5,345 | 33,003 | 19,705 | 660 | 186 |
| **total** | 1a | 306,156 | 958,488 | 666,479 | | 1,020 |
| **total** | 1b | 279,935 | 910,961 | 624,859 | | 986 |

1b relative to 1a, D16-overlap: sieve −7.2%, sort −11.3%, fib −1.4%,
crc −5.4%, bignum −2.2%; over the five, −5.0% cycles, −8.6% instructions,
−3.3% program code. "Code bytes (with libs)" is what `run --stats` prints
(every instruction in the image); "program only" counts just the
instructions in `NAME.s`, which is the fairer size comparison for my code.

**Mistakes: none that reached a run.** All ten programs assembled and gave
the right output on the first run: no assembler errors, no wrong output, no
traps. I worked the pointer invariants of the two sorts out on paper first
(that was the hard part, see sort), and stress-tested both sorts on 50 extra
inputs per ISA (duplicates, sizes 1-80, sorted, reversed, all equal, with
guard words around the array); all passed. The slips I did make were about
performance or consistency, caught by reading profiles:

- sieve (both): I wrote `CALL` for library calls, then switched to `BSR`
  like the other programs (the assembler relaxes it to `CALL` when out of
  range anyway); that moved the `flags` array, which was only `.align 2`, so
  `memset` started doing head and tail bytes (18 more instructions). Fixed
  with `.align 4`.
- sort 1a: the first draft of `isort` closed its outer loop with a
  two-parcel `LEA r1, [r3 + 4]` / `CMP`; restructured before running to the
  plain `ADDI r3, 4` / `CMP` / `BLO` at the bottom.

## Log

### sieve (1b first)

Sieve of Eratosthenes over an 8192-byte flag array, `memset` to 1 first;
each prime i crosses off i², i² + i, ...; i² is kept up to date by adding
2i + 1. Then a count pass and a downward scan for the last ten primes.

- **The hot loop is identical in both ISAs.** The cross-off loop (62-67% of
  the time) is four one-parcel instructions in both, 10 cycles per flag:

  ```
  .cross: STB  r0, [r10]          ; 1b: ST r0, byte [r10]
          ADD  r10, r8
          CMP  r10, r11
          BLO  .cross
  ```

  3 registers (step, pointer, end). Neither ISA's special features apply to
  a store-only loop with no offset.
- **The count pass is where they differ.** 1b adds a byte straight from
  memory and steps the pointer in one instruction; 1a uses its free short
  offsets and unrolls by four (I unrolled both by four):

  ```
  ; 1a: 11 instructions, 31 cycles per 4 flags     ; 1b: 6 instructions, 24 cycles
  .count: LDB  r1, [r10]                           .count: ADD  r9, byte [r10]+
          ADD  r9, r1                                      ADD  r9, byte [r10]+
          LDB  r1, [r10 + 1]                               ADD  r9, byte [r10]+
          ... (+2, +3)                                     ADD  r9, byte [r10]+
          ADDI r10, 4                                      CMP  r10, r11
          CMP  r10, r11                                    BLO  .count
          BLO  .count
  ```

  `ADD r9, byte [r10]+` costs 5 cycles against 3 + 3 for `LDB` + `ADD`. 1b
  also needs one register fewer (no temporary). This loop is the whole
  sieve difference: 1b 49K vs 1a 63K cycles; 1b's `memset` (library) is
  also 1.5K cycles cheaper thanks to `ST r2, [r1]+`.
- **The last ten primes** are pushed on the stack while scanning down, so
  the smallest ends up on top and they pop in printing order. 1b has no byte
  pre-decrement mode (`-[r]` is words only), so the scan uses an indexed
  byte load `MOV r1, byte [flags + r10]` (mode 9, 2 parcels), the same size
  as 1a's long-form `LDB r1, [flags + r10]`.
- Clearing flags 0 and 1 with one half store (`STH r0, [flags]` /
  `ST r0, half [flags]`) is 2 parcels in both: 1a has no short half forms.

### sort (1a first)

256 random 16-bit numbers (lib/rand.s, seed 12345) quicksorted (Hoare
partition around the middle element, recursing into the smaller part and
looping on the larger one), 64 more insertion-sorted, then a sortedness check
and Fletcher checksum, and a few values. I stored the numbers one per 32-bit
word (the natural element size: one-parcel `LD [r + 4o]` in 1a, `[r]+` and
`-[r]` in 1b; 1b has no half auto-increment and 1a no short half load).
The checksums are mod 2^16, but sums in 32 bits have the same low 16 bits
and `print_hex` with 4 digits prints only those, so no masking is needed.

- **The partition scans are the clearest 1b win in this set.** 1a:

  ```
  .nexti: ADDI r1, 4              ; 4 instructions, about 10.5 cycles per step
  .si:    LD   r3, [r1]
          CMP  r3, r10
          BLO  .nexti
  ```

  1b, with the pointer step folded into the load:

  ```
  .si:    MOV  r3, [r1]+          ; 3 instructions, about 7.5 cycles per step
          CMP  r3, r10
          BLO  .si
  ```

  qsort: 1a 60.1K cycles, 1b 52.0K.
- **But the auto-increment convention cost real thought.** After the scans,
  `[r1]+` has overshot a[i] by one word while `-[r2]` points exactly at
  a[j], so i <= j is not simply `CMP r1, r2`. I settled on: during the
  partition r1 = &a[i] and r2 = &a[j] + 4; after the i scan a `SUB r1, #4`
  fix-up; the swap's store `ST r4, [r1]+` does i++ for free and the next
  `-[r2]` does j--; then "i <= j" is `CMP r1, r2` / `BLO`, and the
  fall-through exit needs another `SUB r2, #4` so that both exits leave
  r1 = &a[i], r2 = &a[j] for the split. Working that out (and convincing
  myself the i = j case still does the swap-and-step of the original
  algorithm) took longer than the whole 1a qsort. In 1a the pointers simply
  are &a[i] and &a[j] all the time.
- **The memory-operand compare lost.** My first 1b version compared the
  pivot straight with memory, `CMP r10, [r1]+` / `BHI .si`: 2 instructions,
  about 6.5 cycles per step. But then the values aren't in registers, so the
  swap has to load both again. Measured over the whole program the
  load-into-register version above is 1.3% faster on D16-overlap and faster
  on 4 of the 6 configurations (the memory-compare version wins only on the
  two `separate`-fetch ones), so I kept it. Memory operands only pay when
  the value isn't needed again.
- Also note the operand order: in 1b the memory operand must be the second
  one, so "a[i] < pivot" becomes `CMP r10, [r1]+` with `BHI`: the condition
  turns round. Easy to get wrong; I had to write it down.
- **Insertion sort.** 1b walks two pointers down together with `-[r]`:
  r4 reads the element below the hole and r1 writes the hole. All accesses
  are one parcel, and both exits from the inner loop leave the hole at
  `-[r1]`, so a single `ST r6, -[r1]` places the value. 1a uses its free
  `[r4 + 4]` offset for the hole instead:

  ```
  ; 1a: 7 instructions, 18 cycles per move    ; 1b: 6 instructions, 15 cycles per move
  .inner: LD   r7, [r4]                       .inner: MOV  r7, -[r4]
          CMP  r7, r6                                 CMP  r7, r6
          BLS  .place                                 BLS  .place
          ST   r7, [r4 + 4]                           ST   r7, -[r1]
          ADDI r4, -4                                 CMP  r4, r5
          CMP  r4, r5                                 BHI  .inner
          BHS  .inner
  ```

  1b uses one register more (5 vs 4). isort: 1a 21.9K, 1b 18.3K.
- **Sortedness check without a branch, in both:** `CMP r7, r5` then
  `SBC r6, r0` subtracts the borrow, so r6 counts the out-of-order pairs
  (negated). One instruction; `SETcc` + `OR` would have been two.
- **Small constants:** the pivot offset is rounded to a word with
  `AND r3, #-4` in 1b (a quick constant, 1 parcel) but `BIC r3, #3` in 1a
  (op 8, 2 parcels: 1a has no one-parcel `AND`/`BIC` immediate).
- **Indexed mode:** `show` prints a[i] for a list of indices; 1b loads it
  with `MOV r1, [r8 + r1*4]`, 1a needs `LSL r1, #2` / `ADD r1, r8` /
  `LD r1, [r1]`. Not hot, but typical.
- Registers in the partition loop: 5 in both (i, j, two values, pivot),
  plus lo and hi in callee-saved registers across it.

### fib (1b first)

Recursive fib(18) counting the calls in a memory word (the reference's
global counter), then fib(0..46) iteratively; fib(46) < 2^31, so this is
plain 32-bit `ADD` and `print_u32` now (draft 0 needed register pairs and
`ADC`).

- **Both ISAs ended up with the same stack-slot idiom.** I wrote 1b first
  keeping n − 1 in a stack slot across the first call, swapping it with
  fib(n − 1) for the second call, and popping it straight into the final
  add:

  ```
  ; 1b                                    ; 1a
          DEC  r1                                 ADDI r1, -1
          PUSH r1          ; [sp] = n - 1         PUSH r1
          BSR  fib                                BSR  fib
          MOV  r2, r1                             LD   r2, [sp]
          MOV  r1, [sp]                           ST   r1, [sp]
          ST   r2, [sp]                           MOV  r1, r2
          DEC  r1                                 ADDI r1, -1
          BSR  fib                                BSR  fib
          ADD  r1, [sp]+   ; + fib(n - 1), pop    POP  r2
          RET                                     ADD  r1, r2
                                                  RET
  ```

  I wrote 1a first with the RISC-normal `SAVE r8-r9` / `RESTORE r8-r9`
  (callee-saved registers), then measured both idioms on both ISAs: the
  stack slot wins on both (1a 363,326 vs 371,686; 1b 358,072 vs 370,612), so
  both programs use it. The only ISA difference left is `ADD r1, [sp]+`
  (6 cycles) against `POP r2` + `ADD r1, r2` (4 + 3): fib is a tie within
  1.4%.
- **The call counter costs 30% of fib in both ISAs.** `LD r2, [calls]` /
  `ADDI r2, 1` / `ST r2, [calls]` (1b: `MOV` / `INC` / `ST`) is 5 + 3 + 5
  cycles per call with 2-parcel absolute addresses, 109K of 363K cycles.
  Neither ISA has a memory increment; 1b being "CISC" doesn't help, because
  its ALU instructions only ever write a register. An `INC [mem]` (or `ADD
  [mem], #q`) is the one read-modify-write I missed in this set. (Keeping
  the counter in a register would be faster, but then fib wouldn't be the
  ordinary callee-saves-preserving function the reference describes.)
- Draft 1 is *slower* than draft 0 here at the configuration the timing
  document calls closest to draft 0 (D32-overlap: 1a 316,603, 1b 311,755,
  draft 0 288,164): absolute loads and stores are 5 cycles (the extension
  parcel takes its own bus cycle) against 3, and `BSR`/`RET` are 4 each
  against 3. Calls and absolute variables got dearer in the 32-bit model.
- 1b `CMP r10, #47` needs an extension parcel (quick constants stop at 15);
  1a's `CMPI r10, 47` is one parcel. Not hot here.

### crc (1a first)

CRC-16/CCITT-FALSE over "123456789" and 1 KB of xorshift output, bit by bit
and table-driven, with the table built at start-up.

- **32-bit registers make the bitwise CRC tidy in both:** keep the CRC in
  the top half of a register, so `LSL r3, #1` drops bit 15 into C, the
  polynomial is `0x10210000` in a register, and nothing ever needs masking.
  The bit loop is identical in both ISAs and is 52% of the run (11-12
  cycles per bit, 6 registers):

  ```
  .bit:   LSL  r3, #1
          BCC  .nopoly
          XOR  r3, r7
  .nopoly: ADDI r6, -1            ; 1b: DEC r6
          BNE  .bit
  ```

  `mktable` uses the same loop and fills the table from the top down with
  the index register doubling as the loop counter (`ADDI r1, -1` / `BPL`;
  1b `DEC` / `BPL`), so there's no compare.
- **The table loop is where 1b's memory operands paid off most.** The CRC
  is kept in the low half and never masked: the junk above bit 15 only moves
  further up, and the index takes just the low byte of `crc >> 8`.

  ```
  ; 1a: 12 instructions, 35 cycles per byte  ; 1b: 8 instructions, 28 cycles per byte
  .byte:  LDB  r4, [r1]                      .byte:  MOV  r4, r3
          MOV  r5, r3                                LSR  r4, #8
          LSR  r5, #8                                XOR  r4, byte [r1]+
          XOR  r4, r5                                ZXB  r4
          ZXB  r4                                    LSL  r3, #8
          LSL  r4, #1                                XOR  r3, half [r6 + r4*2]
          LSL  r3, #8                        .next:  CMP  r1, r2
          LDH  r5, [table + r4]                      BLO  .byte
          XOR  r3, r5
          ADDI r1, 1
  .next:  CMP  r1, r2
          BLO  .byte
  ```

  Two memory-operand `XOR`s: one with auto-increment, one indexed with a
  scale of 2 (which saves 1a's `LSL r4, #1`). The indexed mode's
  displacement is only 8 bits, so the table address has to live in a
  register (r6); a `[label + r4*2]` form would have saved that register.
  1a's `LDH` exists only in the 2-parcel long form.
- **Test driver.** The four tests are a table of (label, data, length,
  routine). 1b walks it entirely with `[r8]+`, including the call:
  `CALL [r8]+` reads the routine's address and steps the pointer. 1a:
  `LD r4, [r8 + 12]` / `CALL r4` and an `ADDI r8, 16` at the end. Not hot,
  but it's the kind of code where 1b reads very naturally.
- Filling the buffer with 512 16-bit values: 1b has no `half [r]+`, so it is
  `ST r1, half [r8]` / `ADD r8, #2` there; 1a is `STH r1, [r8]` (2 parcels)
  / `ADDI r8, 2`.

### bignum (1b first)

Exact factorials up to 52!, printing 10!, 20!, 30!, 40! and 52!.

- **Changed representation, on purpose.** Draft 0 used base-10000 limbs so
  that printing needed no big division, because it had only a software
  32/16 divide. With hardware `MULU` and `DIVUL` the natural design is
  binary 32-bit limbs: multiplying by k is one `MULU` per limb (HI = carry
  out), and printing divides a copy by 10^9 with a chain of `DIVUL`s from
  the top limb down (the remainder of each stays in HI as the top half of
  the next dividend); the last remainder is the next 9-digit group, pushed
  on the stack and printed most significant first (`print_u32`, then
  `print_u32z` with 9 digits). Same algorithm in both ISAs.
- **The arithmetic core is the same in both** and short:

  ```
  .limb:  LD   r6, [r3]           ; 1b: MOV r6, [r3]
          MULU r6, r1             ; HI:r6 = limb * k  (k second: few multiplier bits)
          ADD  r6, r5             ; + carry in
          MFHI r5                 ; MFHI leaves the flags alone...
          ADC  r5, r0             ; ...so this picks up the add's carry
          ST   r6, [r3]           ; 1b: ST r6, [r3]+
          ADDI r3, 4              ; (1b: not needed)
          CMP  r3, r4
          BNE  .limb
  ```

  and the division chain is `ADDI` / `LD` / `DIVUL` / `ST` (1b: `MOV r1,
  -[r3]` / `DIVUL` / `ST r1, [r3]`). 5 registers in the multiply loop, 4 in
  the divide loop. `MTHI r0` before each chain, `MFHI` after.
- **Dividing by less than 2^32 empties at most the top limb**, so one
  check per division keeps the length right (`LD r1, [r9 - 4]` / `BNE`; the
  negative offset is 2 parcels in both ISAs).
- **The ISAs hardly differ (−2.2%)**: the time goes to `MULU` (13 cycles
  with a 6-bit multiplier), `DIVUL` (67 cycles on D16) and above all the
  library's decimal printing (48-49%: one 67-cycle `DIVU` per digit). The
  one 1b advantage is the pointer step folded into `ST [r3]+` / `-[r3]`.
- **Against draft 0:** 147,257 cycles there (60.9% in the software 32/16
  divide, 19.2% in the software multiply) vs 22,277 (1a) / 21,734 (1b) on
  D32-overlap: 6.6-6.8 times faster. This is where the 32-bit machine and
  hardware MUL/DIV pay off most.
- Spec point (since clarified in `isa-v1.md`): the multiply time depends on
  the *second* operand's bit length. I put k there from the start after
  reading `alu_timing` in `tmc/isa/v1common.py`, because the timing document
  said "multiplier" without saying which operand that is.

## Which features got used

Executed instructions in my five programs (libraries excluded): 1a 280,574,
1b 255,522.

- **1a short forms were used everywhere they could be.** One-parcel
  `LD`/`ST`/`LDB`/`STB [r + small offset]`: 34 static, 40K executions;
  `MVI`/`ADDI`/`CMPI`: 69 static. `ADDI` alone is **13.8%** of executed 1a
  instructions, and nearly all of those are pointer steps that 1b folds into
  `[r]+`/`-[r]`. The long forms that remained: absolute `LD`/`ST` (the fib
  counter), `LDH`/`STH` (crc; no short half forms), `LDB [label + r]`,
  `LEA` (35 static `LEA rd, label`, PC-relative, all 2 parcels, outside
  loops), and `BIC #3`/`CMP #8192` (no one-parcel ALU immediates other than
  `MOV`/`ADD`/`CMP`).
- **1b auto-increment/decrement did the real work**: 30 static uses
  (`MOV/ST/ADD/XOR` with `[r]+`, `-[r]`, `byte [r]+`, `CALL [r8]+`), about
  25K executions. **ALU instructions with a memory operand were used only 8
  times statically** (`ADD byte [r]+` ×4 in the sieve count, `ADD [sp]+` in
  fib, `XOR byte [r]+` and `XOR half [r + x*2]` in crc, `CMP r8, byte [r10]`
  in bignum), 5.7% of executions. Indexed mode: 4 static. The stack-slot mode
  (`[sp + 4n]`) never came up: fib's `[sp]` has offset 0 and assembles as a
  plain `[r]`. Quick constants: 29 static `MOV`/`ADD`/`SUB`/`AND`
  `#q`.
- Each 1b memory-operand ALU instruction costs about what 1a's load + ALU
  pair costs (`ADD r9, byte [r10]+` 5 cycles vs `LDB` 3 + `ADD` 3 on
  D16-overlap; `XOR r3, half [r6 + r4*2]` 7 vs `LDH` 4 + `XOR` 3); the
  saving comes from the pointer step and the fetch of one parcel fewer.
- Register pressure was never an issue: the busiest hot loop (CRC bitwise)
  uses 6 registers; most use 3-5. 14 general registers are plenty for this
  kind of code in both ISAs; nothing spilled.

## The five most important observations

1. **1b wins every program, but modestly**: −5.0% cycles (D16-overlap),
   −6.2% (D32-wide), −8.6% instructions, −3.3% program code over the five.
   The biggest gaps are in pointer-walking loops (sort −11.3%, sieve −7.2%,
   crc −5.4%); call-heavy fib and multiply/divide-bound bignum are within
   about 2%.
2. **The 1b advantage is auto-increment, not memory operands.** `ADDI`
   pointer steps are 13.8% of executed 1a instructions; 1b absorbs them into
   `[r]+`/`-[r]`. ALU-with-memory instructions were rarely the right choice
   (8 static uses), and where the loaded value is needed again (qsort's
   swap) loading into a register beat `CMP reg, [mem]+` (measured: 1.3%
   faster). A 1a with post-increment loads and stores would likely close
   most of the gap.
3. **Register-only hot loops are identical in both ISAs**: the sieve
   cross-off (10 cycles per flag), the CRC bit loop, the `MULU`/`DIVUL`
   chains. The big wins of draft 1 over draft 0 (32-bit registers,
   `MULU`/`DIVUL` with HI, `SAVE`/`RESTORE`, shifts by n, `ADC`/`SBC`
   tricks) are all in the common part: bignum is 6.6× faster than draft 0
   in both.
4. **1b was harder to get right.** Post-increment overshoot and the
   asymmetric conventions it forces (qsort's r2 = &a[j] + 4 and its two
   `SUB #4` fix-ups), and the reversed operand order of `CMP reg, [mem]`
   (`BHI` where you mean "a[i] < pivot"), were the only places in this set
   where I had to stop and work things out on paper. 1a code is longer but
   each line is obviously right.
5. **Each ISA has small, awkward gaps.** 1b: no `half [r]+`, no byte or
   half `-[r]`, an 8-bit displacement in the indexed mode (so a table needs
   a base register), and quick constants only reach 15 (`CMP r, #47`,
   `#52`, `#255` cost a parcel where 1a's 8-bit `CMPI`/`MVI` don't). 1a: no
   short half loads/stores, no one-parcel `AND`/`BIC`/`XOR` immediates
   (`BIC r3, #3` is 2 parcels where 1b has `AND r3, #-4` in one). Neither
   has a memory increment, which cost fib's call counter 30% of its time in
   both.

## Wished for

- 1a: post-increment (or pre-decrement) loads and stores; short `LDH`/`STH`.
- 1b: `half [r]+`, byte/half `-[r]`, and a `[label + rx*scale]` indexed form
  with a 16-bit displacement.
- Both: a memory increment (`INC [abs]`), for counters.

## Tool and library notes

- No assembler, simulator or library bugs found. I spot-checked the library
  routines I used at their edges on both ISAs: `print_u32`/`print_u32z`
  (0, 2^32 − 1, widths 0, 1 and 9), `print_hex` (1, 3, 4 and 8 digits), and
  `memset`/`memcpy` at every dst/src alignment with lengths 0-22, with guard
  bytes around them. All correct.
- `run --stats` "bytes of code" counts every instruction in the image,
  libraries included, so it mostly measures which libraries a program pulls
  in. For comparing my code I also counted the instructions from `NAME.s`
  alone (table above).
- The scratchpad directory is shared between concurrent agents: my
  profiler script there was overwritten by another agent's file with the
  same name within minutes, and I moved mine to a subdirectory. Worth
  telling agents to use their own subdirectory.
