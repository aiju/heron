# Notes: four new 32-bit programs on drafts 1a and 1b

Programs: `sha256`, `wordfreq`, `vm`, `lines` (no draft 0 versions exist).
Each is written twice, `programs/v1a/NAME.s` and `programs/v1b/NAME.s`, with
the same algorithm and data structures but idiomatic code for each ISA.

Cycle counts are D16-overlap (the simulator's reference configuration)
unless stated otherwise, measured after the timing-model change that made
1b's auto-increment cost the same as a plain `[r]` access. (That change
only moved the 1b numbers: vm by -5.4%, wordfreq by -2.2%, sha256 by
-0.4%.) "Program-only" code bytes leave out the included library
code (`start.s` is in both totals).

## Summary

| program | ISA | written | instructions | D16-overlap cycles | code bytes | program-only |
|---|---|---|---:|---:|---:|---:|
| sha256 | 1a | first | 98,454 | 369,105 | 628 | 488 |
| sha256 | 1b | second | 89,417 | 350,347 | 602 | 466 |
| wordfreq | 1a | second | 82,013 | 234,796 | 796 | 258 |
| wordfreq | 1b | first | 66,303 | 206,233 | 738 | 264 |
| vm | 1a | first | 970,495 | 3,965,030 | 658 | 412 |
| vm | 1b | second | 597,389 | 2,884,730 | 542 | 298 |
| lines | 1a | second | 27,880 | 79,352 | 704 | 458 |
| lines | 1b | first | 26,296 | 76,003 | 690 | 446 |

1b vs 1a, cycles, on all six configurations:

| | D16-separate | D16-overlap | D16-wide | D32-separate | D32-overlap | D32-wide |
|---|---:|---:|---:|---:|---:|---:|
| sha256 | -6.0% | -5.1% | -5.1% | -6.4% | -5.2% | -5.1% |
| wordfreq | -14.8% | -12.2% | -15.6% | -12.9% | -9.1% | -12.8% |
| vm | -30.8% | -27.2% | -31.5% | -27.3% | -22.2% | -26.9% |
| lines | -5.0% | -4.2% | -6.7% | -3.3% | -1.9% | -4.9% |

1a does relatively best with overlapped fetch: separate fetch charges a
cycle per instruction, which hurts the draft with more instructions, and
overlap hides most of that cycle. The wide fetch favours 1b a little, since
many of its extension parcels then come free from the prefetch buffer.

Bugs: 1 wrong-output bug (1a `lines`, a register clash), 2 assembler
errors (1a `sha256`), no traps. Every other version was correct on its
first run. Both ISAs were pleasant to write; the differences are mostly in
how many instructions a job takes, much less in how hard it was to get
right.

What decided the differences:

1. **Table dispatch and stack code is where 1b wins**, by a lot. The
   interpreter's dispatch is `MOV r1, byte [r8]+ / JMP [r13 + r1*4]`: two
   instructions, three parcels, 9 cycles. In 1a it's `LDB / ADDI / LSL #2 /
   LD [optable + r1] / JMP r1`: five instructions, six parcels, 18 cycles.
   Add `ADD r9, [sp]+` for binary operators and 1b runs the VM in 27% fewer
   cycles with 38% fewer instructions and 28% less code.
2. **Register-heavy compute code comes out nearly even** (sha256 -5%,
   lines -4%). The hot loops are register-register ALU operations and
   shifts, which are the same instructions with the same cost in both
   drafts. Where 1b folds a load into an ALU operation (`ADD r8, [r11]+`),
   it saves an instruction and a parcel but only about one cycle: a
   memory-operand ADD costs about what a load plus a register ADD does.
3. **Code size is closer than the instruction counts suggest.** 1b's quick
   constants only cover -16..15, so `CMP r1, #64`, `MOV r1, #'.'`,
   `AND r13, #255` take an extension parcel where 1a's `CMPI`/`MVI`/`ADDI`
   (8-bit) are one parcel; and 1b's scaled-index and `[r + d16]` operands
   are two parcels where 1a's short `[r + 0..60]` loads are one. On
   wordfreq 1a's program code is actually 6 bytes smaller.
4. **Registers were never short** (14 was always enough, no spills), but
   both drafts spend a lot of `MOV`s because shifts and ALU operations are
   destructive: MOV is 25-27% of all sha256 instructions in both. 1b needs
   extra registers for things 1a has as immediates or absolute addresses
   (the constant for `MULU`, the base of a scaled-index table); 1a needs
   extra temporaries where 1b uses a memory operand (my one real bug).
5. **Flag side effects of moves bite in both, differently.** In 1a, `POP`
   (`RESTORE`) leaves the flags alone, so the VM's `JZ` is `TST r9, r9 /
   POP r9 / BEQ jump`. In 1b, `POP` is `MOV r9, [sp]+` and sets N and Z,
   so it has to branch first and pop on both paths. In both, `MOV`/`MVI`
   set N and Z, so you can't load a constant between a compare and its
   branch (Bresenham's `sx = x0 < x1 ? 1 : -1` has to branch first).

## sha256

**Written first: 1a.** Both versions use the same structure: a..h in r1-r8,
two temporaries (r9, r10), the round loop not unrolled, and the eight
working variables rotated with eight `MOV`s at the end of each round.

### Common to both

- **Rotate chains.** Shifts are the expensive part (one microcode step per
  16, per 8, then per bit; 2 cycles a step on D16), so the order of the three
  rotates in each Sigma matters. Each rotate starts from the previous result:

  | function | rotates | chained as | steps |
  |---|---|---|---:|
  | Sigma0(a) | 2, 13, 22 | ROR 2, ROR 11, ROR 9 | 8 (vs 15 separately) |
  | Sigma1(e) | 6, 11, 25 | ROR 25, ROR 18, ROR 27 | 11 (vs 18 in the obvious order 6, 5, 14) |
  | sigma0(x) | 7, 18 (+ SHR 3) | ROR 18, ROR 21 | 9 + 3 |
  | sigma1(x) | 17, 19 (+ SHR 10) | ROR 17, ROR 2 | 4 + 3 |

  It's worth about a third of the rotate cost, the same in both ISAs.
  `ROR r10, #27` still takes 11 cycles and `ROR r9, #25` 7 on D16-overlap;
  a rotate-left would make ROR 27 (= ROL 5) cheaper, but ROL n is ROR 32-n
  in both drafts and the microcode cost follows the ROR count.
- **Register pressure.** No spills in either version. The round loop needs
  8 + 2 temporaries + the K/W addressing: **11 registers in 1a** (one index
  register, `r12`, counts from -256 to 0 and indexes both `K_end` and
  `W_end`), **13 in 1b** (`r11` and `r12` auto-increment through K and W,
  `r14` holds the end of K for the loop test). 14 is enough; a 12-register
  machine would have been tight for 1b.
- **MOV is a quarter of all instructions in both** (24.6k of 98k in 1a,
  24.6k of 89k in 1b): the 8-MOV rotation per round plus 5 copies per round because
  every shift and ALU operation destroys its first operand (`MOV r9, r5 /
  ROR r9, #25`). A non-destructive shift (`ROR rd, rs, #n`) would remove 4
  MOVs per round and 3 per schedule step. Unrolling the round loop 8 times
  (renaming instead of moving) would remove the other 8, about 15% of the
  round time in either ISA; there are no macros in the assembler, so I
  didn't. (Wish: `.macro` or `.rept`.)
- **Idea that didn't pay:** the 8-register rotation can be done with
  `SAVE r1-r8 / RESTORE r2-r9` (push, then pop one register up): two
  instructions instead of eight, but on a 16-bit bus that's ~16 + 16 cycles
  vs 24 for the MOVs. It would win on the wide (32-bit bus) configurations.

### 1a

- One-parcel loads covered the whole message schedule: `W[t-16]`, `W[t-15]`,
  `W[t-7]`, `W[t-2]` are at offsets 0, 4, 36, 56 from one pointer. Only the
  store of `W[t]` at offset 64 needs the long form (the short form stops at
  60).
- `LD r9, [K_end + r12]` with a negative index: the loop counter doubles as
  the index and `ADDI r12, 4` sets Z on the last round, so the loop test is
  free. **But** on D16 each of those loads costs 6 cycles instead of 5: the
  base register is negative (0xFFFFFFxx), so `base + disp` changes the upper
  16 bits and the model charges the "page-crossing" cycle. Counting up from
  0 with a `CMP` would cost the same in total. Not obvious from the spec;
  it's a property of the D16 address adder in the timing model.
- Reading the big-endian words: `LDB` short forms at offsets 0-3, three
  `LSL #8`/`OR` pairs, 15 instructions per word (1b: 10).
- **Mistakes (2 assembler errors):** (1) `MVI r2, 0x80` for the padding
  marker: the assembler rejects 128 as an 8-bit signed immediate. Correct,
  but surprising when the value is only going to be stored with `STB`; I
  wrote `MVI r2, -128`. (2) I defined `CONSOLE = 0xFFFFFF00` in the program
  and got "CONSOLE is already defined" from `lib/console.s`, which defines
  the same name with the same value. The library's constants share the
  program's namespace, and the header comments don't list them. I used the
  library's `CONSOLE`. The first run after fixing these was correct.

### 1b

- K[t] and W[t] are added straight from memory with auto-increment:
  `ADD r8, [r11]+` / `ADD r8, [r12]+`, 6 cycles each, versus 1a's
  `LD r9, [K_end + r12]` (6) + `ADD r8, r9` (3). That and the loop test are
  the whole round-loop difference: 154.5 cycles per round in 1b vs 161.7 in
  1a.
- The message schedule: `ADD r1, [r9 + 36]`, then `ADD r1, [r9]+` adds
  W[t-16] and steps the pointer, so there's no separate pointer increment.
  104.1 cycles per step vs 105.8 in 1a: the memory operands save
  instructions (22 vs 25 per step) but hardly any time.
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
  left 8, big-endian, auto-increment): there's no byte auto-decrement mode,
  which would have let me store from the low byte up.
- **Mistakes:** none; correct on the first run. (Afterwards I replaced a
  `MOV r9, r9` used to set flags with `TST r9, r9`, which has no write-back
  cycle.)

The round loop is ~59% of the time and the schedule ~29-30% in both.

## wordfreq

**Written first: 1b.** Same design in both: the input is read straight from
the console register (a word load gives -1 at the end, so `BMI` catches
it); a 256-byte table `lower[]` maps letters to lower case and everything
else to 0, so classifying and folding is one indexed byte load; each word is
written in lower case straight into a string pool and hashed on the way
(`h = h*31 + c`); open addressing with 256 entries of `{word, count}`; on a
hit the pool pointer isn't advanced, so the copy is simply overwritten by
the next word; the number of words is the sum of the counts (no counter
in the read loop); then insertion sort of the 116 entry pointers by
(count descending, word ascending), with the library `strcmp` for ties.

The read loop has two states (between words / inside a word), so the end of
the input inside a word needs no special case: it ends the word, and the
next read returns -1 again.

The insertion sort is the hot loop (about half the time, with its
`strcmp` calls): the entries come out of the hash table in random order, so it
makes ~3,560 steps for 116 entries. Keeping only a top-15 list would be
much faster, but the spec asks for sorting and it's a good pointer-chasing
benchmark, so I left it.

### 1b

- The hash-table entry is reached with the scaled-index mode, which fits
  8-byte entries exactly: `MOV r1, [r14 + r13*8]`, and the count with
  `[r14 + r13*8 + 4]`. Incrementing the count is still three instructions
  (`MOV`/`ADD`/`ST`): no read-modify-write to memory.
- The sort loop uses a memory-operand compare and an auto-decrement load:

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
- The 1b `strcmp` in the library is tighter (`MOV r3, byte [r1]+` /
  `SUB r3, byte [r2]+`): 32.9k cycles in strcmp vs 48.2k in 1a.
- **Mistakes:** none; correct on the first run. Afterwards changed two
  `MOV r1, r1` (flag tests after `strcmp`) to `TST r1, r1`: same size, one
  cycle cheaper. (Wish: library routines whose result sets the flags, or a
  documented promise either way.)

### 1a

- `MULU r11, #31`: the immediate form (two parcels) saves the register that
  1b needs. I spent it on the end-of-table pointer for the probe wrap-round,
  so 1a probes with an entry pointer (`ADDI r13, 8` / `CMP r13, r12`) and
  reaches the fields with one-parcel `LD r1, [r13]` / `LD r1, [r13 + 4]`.
- The sort loop is two instructions longer per step (`LD r3, [r2 + 4]` +
  `CMP` instead of a memory compare, and `ADDI r12, -4` instead of the
  auto-decrement): 36.1k instructions in the loop vs 29.0k in 1b, but only
  about 31 vs 29 cycles per step.
- **Mistakes:** none; correct on the first run.

1b executes 19% fewer instructions but takes only 12% fewer cycles, and its
program code is 6 bytes *larger*: what 1b saves in instructions it pays in
extension parcels (`MOV r1, #s_words` is two parcels, like 1a's PC-relative
`LEA`; every `[r14 + r13*8 + 4]` is two parcels; `AND r13, #255` is two).

## vm

**Written first: 1a.** Same design in both: the VM's data stack is the
machine stack with the top of stack cached in r9 (so `DUP` is one `PUSH`);
the return stack is a separate array of absolute return addresses; every
handler ends with its own copy of the dispatch (the textbook
"replicated dispatch" of threaded interpreters). 121,528 VM instructions
are executed.

### 1a

- The dispatch, at the end of every handler, with `n` = the length of the
  current VM instruction (r8 points at its opcode, so operands are
  one-parcel `LDB r1, [r8 + 1]` and one `ADDI` per VM instruction steps
  over opcode and operands together):

  ```
          LDB  r1, [r8 + n]       ; 3 cycles
          ADDI r8, n              ; 3
          LSL  r1, #2             ; 5: two shift steps
          LD   r1, [optable + r1] ; 5 (two parcels)
          JMP  r1                 ; 2
  ```

  18 cycles and 12 bytes per copy. `LSL #2` is surprisingly expensive (no
  barrel shifter); a table of halfwords with `LSL #1` + `LDH` would save
  2 cycles but needs the handlers below 64 KB.
- `PUSH`/`POP` are `SAVE`/`RESTORE` of one register (4 cycles each), and
  `RESTORE` keeps the flags, so the conditional jumps are tidy:

  ```
  op_jz:  TST  r9, r9
          POP  r9
          BEQ  jump
  ```
- `LDSB r9, [r8 + 1]` for `PUSHB` (sign-extending loads are 1a-only, long
  form).
- Globals, the jump table and the bytecode base are all reached as
  `[label + reg]` long forms, so 1a needs only four registers: VM pc, TOS,
  return-stack pointer, and the saved `sp`.
- **Mistakes:** none; correct on the first run.

### 1b

- The dispatch is two instructions, three parcels, **9 cycles**:

  ```
          MOV  r1, byte [r8]+     ; 3 cycles
          JMP  [r13 + r1*4]       ; 6
  ```
  The scaled-index mode needs the table base in a register (its
  displacement is only 8 bits), so `optable` lives in r13, and the globals
  base in r11 for `MOV r9, [r11 + r1*4]`.
- Binary operators take their left operand straight off the stack:

  ```
  op_add: ADD  r9, [sp]+          ; a b -> a + b
  op_sub: NEG  r9                 ; a - b = -b + a
          ADD  r9, [sp]+
  op_lt:  CMP  r9, [sp]+          ; flags of b - a, so a < b is GT
          SETGT r9
  ```
  Only `MUL`/`DIV`/`MOD` need an explicit `POP r1`, because those are
  register-only in 1b.
- `POP` sets N and Z in 1b, so `JZ`/`JNZ` branch first and pop on each path
  (two more instructions of code than 1a, no extra time).
- **Mistakes:** none; correct on the first run.

### Numbers and a dispatch experiment

1b runs the VM in 27% fewer cycles (2.88M vs 3.97M), 38% fewer
instructions, with 28% less program code (298 vs 412 bytes). This is the
biggest difference among the four programs. The 7,350 `DIVS` instructions
for `MOD`/`DIV` (69 cycles each) alone are 13% of 1a's time and 18% of
1b's.

To check that replicating the dispatch isn't what makes the difference, I
also measured both with a single shared dispatch (`BRA next` at the end of
each handler):

| | replicated dispatch | shared dispatch |
|---|---|---|
| 1a | 3,965,030 cycles, 658 bytes | 4,208,084 cycles, 508 bytes |
| 1b | 2,884,730 cycles, 542 bytes | 3,127,784 cycles, 468 bytes |

Replicating costs 1a 150 bytes for 6% (12 bytes per copy) and 1b 74 bytes
for 8% (6 bytes per copy). 1b is ~26% faster either way.

## lines

**Written first: 1b.** Same design in both: `plot` clips with two unsigned
compares (negative coordinates are huge unsigned numbers) and ORs in a bit
mask from an 8-byte table; Bresenham and the midpoint circle exactly as the
spec says (`line` keeps 10 values in r4-r6 and r8-r14; `plot` clobbers only
r1-r3); a `plot4` helper plots the four (xc +- a, yc +- b) points; XOR
rectangles are flipped a byte at a time with left/right edge masks from
tables; the printing loop shifts each byte left through C and stores '#' or
'.' (held in registers) to the console, counting set pixels on the way.

The program is small (~80k cycles); printing the 2,048 pixels is ~40% of
it and identical in both ISAs, so the totals differ by only 4%.

### 1b

- `plot` uses the scaled index to avoid the 7-cycle `LSL r2, #3`:

  ```
          LSR  r1, #3
          ADD  r1, #fb
          OR   r3, byte [r1 + r2*8]
          ST   r3, byte [r1 + r2*8]
  ```
  38 cycles per call vs 41.5 in 1a.
- `LEA r1, [r8 + r4]` works as a three-operand add in `plot4` (one
  instruction instead of `MOV`/`ADD`); there's no three-operand subtract.
- `CMP r1, #64` / `CMP r2, #32` are two parcels each (1a: one-parcel
  `CMPI`).
- `XOR r7, byte [r2]` / `ST r7, byte [r2]+` in the rectangle fill: no
  temporary register, and the pointer steps itself.
- **Mistakes:** none; correct on the first run. Afterwards I changed
  `MOV r7, #0xFF` (two parcels) to `MOV r7, #-1` (a quick constant; only
  the low byte is stored).

### 1a

- **Mistake (wrong output):** in `xor_rect` I used r8 both as the counter of
  middle bytes and as the temporary for the loaded byte, and decremented r3
  instead of the counter. In 1b the byte is XORed straight from memory, so
  the 1b register plan had no temporary; carrying the plan over to 1a, I
  grabbed a register that was already taken. Fixed with a second saved
  register (`SAVE r8-r9`). It's the one place in these programs where the
  load/store style cost a register.
- Everything else is the 1b code with loads split out; the shape tables
  are read with one-parcel `LD r3, [r8 + 4]` etc. and one `ADDI r8, 16`
  instead of 1b's `MOV r3, [r8]+`.

## Things in the specs and tools worth noting

- **isa-v1b.md** lists "a flag-preserving `ADDI`" among 1a's advantages, but
  1a's `ADDI` sets N and Z (only C and V are preserved, as isa-v1a.md and
  the flags table say). The 1a library has a comment about exactly this
  (`LDB` then `ADDI` loses the load's Z). The wording in 1b's list should
  say "C/V-preserving".
- `[label + reg]` uses a *signed* 16-bit displacement in both drafts, so
  tables reached that way must be below 0x8000. Fine for these programs,
  but a program with more than 32 KB of code and data would hit it.
- 1b's indexed mode has only an 8-bit displacement, so `[table + r1*4]`
  isn't possible; the table base needs a register (or `LSL` + `[table + r1]`).
- 1b has no byte auto-decrement and no halfword auto-increment.
- D16 page crossing: `[r12 + K_end]` with a negative r12 costs an extra
  cycle every time (see sha256 1a).
- The library's internal constants (`CONSOLE`, `PR_OUT`) and labels are
  global; redefining `CONSOLE` in a program is an error.
- The assembler has no `.macro`/`.rept`, which is what kept me from
  unrolling the SHA-256 rounds.
- No assembler or simulator bugs found.
