# Notes: four new 32-bit programs on drafts 1a and 1b

Programs: `sha256`, `wordfreq`, `vm`, `lines` (no draft 0 versions exist).
Each is written twice, `programs/v1a/NAME.s` and `programs/v1b/NAME.s`, with
the same algorithm and data structures but idiomatic code for each ISA.
Cycle counts are D16-overlap (the simulator's reference configuration)
unless stated otherwise. "Program-only bytes" leaves out the library code
that the program includes.

## sha256

**Written first: 1a.** Both versions use the same structure: a..h in r1-r8,
two temporaries (r9, r10), the round loop not unrolled, and the eight
working variables rotated with eight `MOV`s at the end of each round.

### What went into it

- **Rotate chains.** Shifts are the expensive part (one microcode step per
  16, per 8, then per bit; 2 cycles a step on D16), so the order of the three
  rotates in each Sigma matters. Each rotate starts from the previous result:

  | function | rotates | chained as | steps |
  |---|---|---|---:|
  | Sigma0(a) | 2, 13, 22 | ROR 2, ROR 11, ROR 9 | 8 (vs 15 separately) |
  | Sigma1(e) | 6, 11, 25 | ROR 25, ROR 18, ROR 27 | 11 (vs 18 in the obvious order 6, 5, 14) |
  | sigma0(x) | 7, 18 (+ SHR 3) | ROR 18, ROR 21 | 9 + 3 |
  | sigma1(x) | 17, 19 (+ SHR 10) | ROR 17, ROR 2 | 4 + 3 |

  The same in both ISAs, of course; it's worth a third of the rotate cost.
- **Register pressure.** No spills in either version. The round loop needs
  8 + 2 temporaries + the K/W addressing: **11 registers in 1a** (one index
  register, `r12`, counts from -256 to 0 and indexes both `K_end` and
  `W_end`), **13 in 1b** (`r11` and `r12` auto-increment through K and W,
  `r14` holds the end of K for the loop test). 14 is enough; a 12-register
  machine would have been tight for 1b.
- **MOV is 25% of all instructions in both** (24.6k of 98k in 1a, 24.6k of
  89k in 1b): the 8-MOV rotation per round plus 5 copies per round because
  every shift and ALU operation destroys its first operand (`MOV r9, r5 /
  ROR r9, #25`). A three-operand or non-destructive shift (`ROR rd, rs, #n`)
  would remove 4 MOVs per round and 3 per schedule step. Unrolling the round
  loop 8 times (renaming instead of moving) would remove the other 8; there
  are no macros in the assembler, so I didn't. That would help both ISAs
  equally (it's ~15% of the round time).
- **Idea that didn't pay:** the 8-register rotation can be done with
  `SAVE r1-r8 / RESTORE r2-r9` (push, then pop one register up). Two
  instructions instead of eight, but on a 16-bit bus that's ~16+16 cycles vs
  24 for the MOVs. It would win on the wide (32-bit bus) configurations.

### 1a

- One-parcel loads covered the whole message schedule: `W[t-16]`, `W[t-15]`,
  `W[t-7]`, `W[t-2]` are at offsets 0, 4, 36, 56 from one pointer. Only the
  store of `W[t]` at offset 64 needs the long form (the short form stops at
  60) — four bytes of code, one cycle per step.
- `LD r9, [K_end + r12]` with a negative index: the loop counter doubles as
  the index and `ADDI r12, 4` sets Z on the last round, so the loop test is
  free. **But** on D16 each of those loads costs 6 cycles instead of 5: the
  base register is negative (0xFFFFFFxx), so `base + disp` changes the upper
  16 bits and the model charges the "page-crossing" cycle. Counting up from
  0 with a `CMP` would cost the same in total. Not obvious from the spec;
  it's a property of the timing model's D16 address adder.
- Reading the big-endian words: `LDB` short forms at offsets 0-3, three
  `LSL #8`/`OR` pairs, 15 instructions per word (1b: 10).
- **Mistakes:** (1) `MVI r2, 0x80` for the padding marker: the assembler
  rejects 128 as an 8-bit signed immediate. Correct, but surprising when the
  value is only going to be stored with `STB`; I wrote `MVI r2, -128`.
  (2) I defined `CONSOLE = 0xFFFFFF00` in the program and got "CONSOLE is
  already defined" from `lib/console.s`, which defines the same name with
  the same value. The library's constants share the program's namespace,
  and the header comments don't list them. I used the library's `CONSOLE`.
  Both were assembler errors; the first run after fixing them was correct.

### 1b

- K[t] and W[t] are added straight from memory with auto-increment:
  `ADD r8, [r11]+` / `ADD r8, [r12]+`, 6 cycles each, versus 1a's
  `LD r9, [K_end + r12]` (6) + `ADD r8, r9` (3). That, and the loop test, is
  the whole round-loop difference: 154.5 cycles per round in 1b vs 161.7 in
  1a.
- The message schedule: `ADD r1, [r9 + 36]`, then `ADD r1, [r9]+` adds
  W[t-16] and steps the pointer, so there's no separate pointer increment.
  104.1 cycles per step vs 105.8 in 1a: the memory operands save
  instructions (22 vs 25) but hardly any time, because a memory-operand ADD
  costs about what a load plus an ADD does.
- The big-endian load is the most CISC-like part and reads nicely:

  ```
  .load:  MOV  r4, byte [r1]+
          LSL  r4, #8
          OR   r4, byte [r1]+
          LSL  r4, #8
          OR   r4, byte [r1]+
          LSL  r4, #8
          OR   r4, byte [r1]+
          ST   r4, [r2]+
  ```
- `H += a..h`: there's no memory-destination ADD, so it's `ADD r1, [r13]` /
  `ST r1, [r13]+` per word (1a: `LD`/`ADD`/`ST`).
- Small irritations: `CMP r9, #64` and `MOV r2, #0x80` need an extension
  parcel (quick constants stop at 15; 1a has `CMPI`/`MVI` for 8 bits).
  The length bytes went out with `ROR r3, #24` / `ST r3, byte [r2]+` (rotate
  left 8, big-endian, auto-increment) — there's no byte auto-decrement mode,
  which would have let me store from the low byte up.
- **Mistakes:** none; correct on the first run. (Afterwards I replaced a
  `MOV r9, r9` used to set flags with `TST r9, r9`, which has no write-back
  cycle.)

### Numbers

| | instructions | cycles | code bytes (program only) |
|---|---:|---:|---:|
| 1a | 98,454 | 369,105 | 628 (488) |
| 1b | 89,417 | 351,833 | 602 (466) |

The round loop is ~59% of the time and the schedule ~29% in both.

## wordfreq

**Written first: 1b.** Same design in both: the input is read straight from
the console register (a word load gives -1 at the end, so `BMI` catches
it); a 256-byte table `lower[]` maps letters to lower case and everything
else to 0, so classifying and folding is one indexed byte load; each word is
written in lower case straight into a string pool and hashed on the way
(`h = h*31 + c`); open addressing with 256 entries of `{word, count}`; on a
hit the pool pointer isn't advanced, so the copy is simply overwritten by
the next word; the number of words is the sum of the counts (no counter
needed in the read loop); then insertion sort of the 116 entry pointers by
(count descending, word ascending), using the library `strcmp` for ties.

The two-state read loop (between words / inside a word) means the
end-of-input inside a word needs no special case: it ends the word, and the
next read returns -1 again.

### 1b

- The hash-table entry is reached with the scaled-index mode, which fits
  8-byte entries exactly: `MOV r1, [r14 + r13*8]`, and the count with
  `[r14 + r13*8 + 4]`. Incrementing the count is still three instructions
  (`MOV`/`ADD`/`ST`): no read-modify-write to memory.
- Insertion sort, the hot loop (it is 40% of the run time), uses a memory
  operand compare and an auto-decrement load:

  ```
  .inner: CMP  r12, r8
          BEQ  .place
          MOV  r2, -[r12]         ; y = the entry in front of the hole
          CMP  r13, [r2 + 4]      ; compare counts straight from y's entry
          BLO  .back
          BNE  .shift
          ...
  .shift: ST   r2, [r12 + 4]
          BRA  .inner
  ```
- `MULU` is register-only in 1b, so the constant 31 takes a register (r12)
  for the whole read loop. All seven callee-saved registers are in use in
  the read loop (console, word start, write pointer, hash, 31, probe index,
  table base).
- The 1b strcmp in the library is much tighter (`MOV r3, byte [r1]+` /
  `SUB r3, byte [r2]+`), so 1b's strcmp time is 37.5k cycles vs 48k for 1a.
- **Mistakes:** none; correct on the first run. Afterwards changed two
  `MOV r1, r1` (flag tests after `strcmp`) to `TST r1, r1`: same size, one
  cycle cheaper (no write-back).

### 1a

- `MULU r11, #31`: the immediate form (two parcels) saves the register that
  1b needs. I spent it on the end-of-table pointer for the probe wrap-round,
  so 1a probes with an entry pointer (`ADDI r13, 8` / `CMP r13, r12`) and
  reaches the fields with one-parcel `LD r1, [r13]` / `LD r1, [r13 + 4]`.
- The sort loop is two instructions longer per step (`LD r3, [r2 + 4]` +
  `CMP` instead of a memory compare, and `ADDI r12, -4` instead of the
  auto-decrement): 36.1k instructions in the loop vs 22.6k in 1b, but only
  about 25 vs 22 cycles per step.
- **Mistakes:** none; correct on the first run.

### Numbers

| | instructions | cycles | code bytes (program only) |
|---|---:|---:|---:|
| 1a | 82,013 | 234,796 | 796 (258) |
| 1b | 66,303 | 210,880 | 738 (264) |

1b executes 19% fewer instructions but takes only 10% fewer cycles. The
program-only code is the same size: what 1b saves in instructions it pays
in extension parcels (`MOV r1, #s_words` is two parcels like 1a's PC-relative
`LEA`, every `[r14 + r13*8 + 4]` is two parcels, `AND r13, #255` is two).
