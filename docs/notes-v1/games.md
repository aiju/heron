# Notes: mandel, life, queens, matmul and bst in draft 1a and 1b

A first-hand log of writing five of the draft 0 benchmark programs for both
draft 1 candidates (`programs/v1a/NAME.s`, `programs/v1b/NAME.s`). Each
program was written from the reference function in `programs/reference.py`
and the draft 0 version, fresh for each ISA. I alternated which ISA came
first. Cycle numbers are from `run --stats` and a small profiler over the
simulator's per-instruction timing keys; I quote `D16-overlap` (the
reference configuration) unless I say otherwise.

(Summary and comparison table at the end.)

## Log

### mandel (1a first)

**Both versions passed on the first run, no assembler errors.**

The 32-bit registers and `MULS` remove everything that made draft 0's
mandel hard: there, 73% of the time went into the `umul16`/`smul16`
subroutines, the `>> 8` was four instructions on a register pair, and the
row and column counters lived in memory for lack of registers. Now a
product is `MOV`, `MULS`, `LSR #8` (three one-parcel instructions), and
everything fits in r8-r13 with r1-r3 as temporaries: 9 registers in the hot
loop, no spills, no subroutine.

Three things I did the same way in both:

- **The 16-bit semantics of the reference are vacuous here.** The reference
  wraps x and y to 16 bits, but |x|, |y| < 512 whenever they are multiplied,
  so |xx - yy + cx| < 1600 and |2xy + cy| < 2400: no wrap ever happens and
  32-bit arithmetic gives the same bits. `ASR #8` on the 32-bit product is
  exactly Python's flooring `>> 8`.
- **The |x| >= 2.0 tests are folded into the squares.** |x| >= 512 exactly
  when xx = (x*x) >> 8 >= 1024, so all three escape tests become
  "xx + yy > 1024, or xx + yy = 1024 with one of them the whole 1024". The
  `= 1024` side path runs once in the whole picture and doesn't change the
  output there, but it is needed for exactness. This saves the two absolute
  values per iteration that draft 0 needed (it also needed them for the
  unsigned multiply).
- **Iteration counter from -16 up to 0**, so `ADDI`/`INC` sets Z at the end
  and the palette lookup absorbs the bias:
  `LDB r1, [palette + MAXIT + r12]` (1a) / `MOV r1, byte [palette + MAXIT + r12]` (1b).

The kernel is pure register arithmetic, so **1a and 1b come out almost the
same**, which is itself a finding: the only differences are

- 1b's `LEA` with the indexed mode works as a three-operand add:
  `LEA r3, [r1 + r2]` (xx + yy without a `MOV`), `LEA r9, [r11 + r9*2]`
  (y = cy + 2xy in one instruction), `LEA r8, [r10 + r1]`. Seven
  one-parcel ALU instructions become three two-parcel `LEA`s and a `SUB`
  (same code size, three fewer instructions). That is 5% faster on
  D16-overlap (652K vs 689K cycles; the version with plain `MOV`/`ADD` gave
  688.5K, the same as 1a) but **exactly 0% on D32-overlap** (457.0K both).
  The gain is a property of the timing model: on a 16-bit datapath an ALU
  op costs two passes, while the address adder is charged one cycle unless
  the upper half changes. So LEA-as-arithmetic is cheap only where the
  model thinks 32-bit adds are expensive.
- Constants: 1a's `ADDI r10, 16` and `ADDI r11, 31` are one parcel; in 1b
  `#16` and `#31` don't fit the 4-bit quick constant. `SUB r10, #-16` does
  (mode D covers -1..-16), so I used it with a comment. `ADD r11, #31`
  stays two parcels. The assembler can't do the `SUB #-16` rewrite itself
  because C comes out different.
- `MOV r12, #-16` in 1b vs `MVI r12, -16` in 1a: both one parcel.

Cost structure (D16-overlap): `MULS` is 50% of all cycles (21,350 multiplies
at 16 cycles average: 1 + 2 per multiplier bit + 2 for the sign). The
loop overhead is small. Multiplying by the smaller-magnitude operand would
help a little, but which one is smaller isn't known.

| | instructions | D16-ovl | D32-ovl | code (program only) |
|---|---:|---:|---:|---:|
| 1a | 149,684 | 688,533 | 457,012 | 98 B |
| 1b | 129,061 | 652,419 | 457,032 | 100 B |

### life (1b first)

**Both passed on the first run.** The draft 0 design carries over: byte
cells, a grid with a one-cell border refilled from the opposite edges each
generation, and the rule `(neighbours | self) == 3`. With `SETcc` the rule
is now `CMP r1, #3` / `SETEQ r1` instead of draft 0's `NEG`/`MVI`/`ADC r0`
trick. I also count the population in the step loop (`ADD r6, r1` after the
`SETEQ`) instead of a separate pass, and count the initial cells while
placing them; same output, one instruction per cell instead of a 4-instruction
pass.

**This is the program where 1b's memory operands pay off most directly.**
The neighbour count in 1b is one instruction per neighbour, and with the
first load auto-incrementing, the pointer step is free and two of the
operands become the zero-displacement one-parcel form:

```
; 1b: 15 instructions, 22 parcels per cell
.cell:  MOV  r1, byte [r2]+     ; top left; r2 moves on to the top neighbour
        ADD  r1, byte [r2]      ; top
        ADD  r1, byte [r2 + 1]  ; top right
        ADD  r1, byte [r2 + W2 - 1]       ; left
        ...                               ; 4 more ADDs
        OR   r1, byte [r2 + W2]           ; the cell itself
        CMP  r1, #3
        SETEQ r1
        ADD  r6, r1             ; population
        ST   r1, byte [r3]+
        CMP  r2, r5
        BNE  .cell
```

In 1a every neighbour is a load plus an `ADD`, and the short `LDB` only
reaches 0-15 bytes past the base, so with one pointer six of the nine
loads are two-parcel long forms:

```
; 1a: 25 instructions, 31 parcels per cell
.cell:  LDB  r1, [r2]           ; top left
        LDB  r5, [r2 + 1]       ; top
        ADD  r1, r5
        LDB  r5, [r2 + 2]
        ADD  r1, r5
        LDB  r5, [r2 + W2]      ; long form from here on
        ADD  r1, r5
        ...
```

For 1a I tried the obvious alternative, one pointer per row so all nine
loads are one-parcel `[rN + 0..2]`: it needs four pointer increments per
cell instead of two and two more registers (so `SAVE r8-r9` in a routine
that was a leaf). Result: 841,090 vs 838,690 cycles on D16-overlap (+0.3%),
better on D32-overlap (670K vs 689K), worse on D16-wide (826K vs 793K). A
wash, so I kept the simpler single-pointer leaf. The long forms cost one
extra bus cycle each, the extra `ADDI`s cost three cycles each; it comes out
even.

Per-instruction costs here (D16-overlap): 1b `ADD r1, byte [r2 + d]` is 6
cycles, 1a `LDB` long (4) + `ADD` (3) is 7; 1b `ADD r1, byte [r2]` is 5,
1a short `LDB` (3) + `ADD` (3) is 6. So the memory operand saves one cycle
per neighbour, and the auto-increments (`MOV r1, byte [r2]+` and
`ST r1, byte [r3]+`, 3 cycles each) replace the two `ADDI`s (3 cycles
each) outright.

Registers in the hot loop: 1b 6 (sum, read pointer, write pointer, row end,
population, row counter), 1a 7 (plus the load temporary). Neither needed
r8 or up.

Smaller things:

- The pattern list is words read with `MOV r3, [r1]+` in 1b; I first wanted
  halves (offsets are < 612) but **1b has no `half [r]+` mode**, so words it
  is in both. `BMI` on the loaded `-1` ends the list with no compare, in
  both ISAs (loads set N).
- Placing a cell, `STB r2, [grid_a + r3]` / `ST r2, byte [grid_a + r3]`, is
  the same two-parcel "label + register" form in both.
- 1b's `ADD r2, #2` (quick constant) and 1a's `ADDI r2, 2` are both one
  parcel; 1b's `MOV r3, #ROWS` (16) is two parcels where 1a's `MVI` is one.
- `wrap` copies the two rows with the library `memcpy`; the column copy is
  the same two loads and two stores in both. Two of the four are one parcel
  in 1a (`STB r4, [r2]`, `LDB r4, [r2 + 1]`), only one in 1b
  (`ST r4, byte [r2]`): 1b's `byte [r2 + 1]` needs a displacement parcel.

| | instructions | D16-ovl | D32-ovl | code (program only) |
|---|---:|---:|---:|---:|
| 1a | 267,941 | 838,570 | 689,210 | 272 B |
| 1b | 164,674 | 703,493 | 575,480 | 266 B |

95% of the time is in `step` in both. 1b takes 16% fewer cycles on
D16-overlap (17% on D32-overlap) and runs 39% fewer instructions. (Before
the timing model was changed to make `[r]+` as cheap as `[r]`, 1b was at
714,417; the step loop has two auto-increment accesses per cell.)

### queens (1a first)

**Both versions passed on the first run.** Bitmask backtracking as in draft
0, with two changes that suit 32-bit registers equally in both ISAs:

- The column mask is kept as *free* columns (starting at 0xFF) instead of
  attacked ones, so the free squares in a row are `MOV`/`BIC`/`BIC`, and
  "no free column left" is the solution test (`TST r2, r2` / `BEQ`), which
  replaces draft 0's row counter. The diagonal masks are never trimmed: a
  32-bit register has room for the bits that shift out past column 7.
- The column number for printing is `32 - CLZ(bit)`, and the board is
  printed by shifting the queen's bit out into C (`LSR r10, #1` / `BCC`).
  Draft 0 needed a bit-number loop for the first and a mask compare for
  the second.

The first solution is copied with a tail call to the library `memcpy`
(`BRA memcpy` from the solution path, after counting).

**The two versions are the same program.** The hot path is register
arithmetic, the `SAVE`/`RESTORE` of five registers per call, and one store
per placed queen. Nothing in it is a memory operand in 1b, and nothing
needs a long form in 1a except `LEA r1, [r8 + 4]` (2 parcels in both; I
used it instead of `MOV`+`ADDI` because it is 3 cycles against 6 on D16).
Cycle counts differ by 0.03% on D16-overlap.

```
.try:   NEG  r1, r12            ; the lowest free square: x & -x
        AND  r1, r12
        BIC  r12, r1
        ST   r1, [r8]
        MOV  r2, r9             ; next row: that column is taken,
        BIC  r2, r1
        MOV  r3, r10            ; and its diagonals move one column each way
        OR   r3, r1
        LSL  r3, #1
        MOV  r4, r11
        OR   r4, r1
        LSR  r4, #1
        LEA  r1, [r8 + 4]
        BSR  solve
```

Where the time goes (D16-overlap, both ISAs): register `MOV`s 23% (four on
entry to copy the arguments into callee-saved registers, three per try to
build the next masks: the two-operand format again, as in draft 0), `SAVE`
plus `RESTORE` 23% (12 cycles each for five registers), `BIC` 12%. A
three-operand `BIC`/`OR`, or an `OR rd, rs, rt`, would remove a third of
the instructions in the loop; neither ISA has one, and 1b's `LEA [r + x]`
trick only covers addition.

I considered a version that keeps the masks in a stack frame instead of
callee-saved registers (`SAVE r1-r5` on entry, then `MOV r2, [sp + 4]` per
try; one parcel in both ISAs, since 1a's short `LD` takes `sp` as a base
too). It trades four entry `MOV`s per call for five loads and a store per
try, which is worse here because there are as many tries as calls.

Registers: r1-r4 (arguments), r8-r12 (saved state), r13 (global solution
count): 10. Code sizes differ by the constants: 1b pays a parcel for
`MOV r1, #'.'`, `#'Q'`, `#32` and the two `CMP r8, #first + 4 * N`; 1a pays
for the `ADDI r8, 4` that 1b's `MOV r2, [r8]+` makes unnecessary.

| | instructions | D16-ovl | D32-ovl | code (program only) |
|---|---:|---:|---:|---:|
| 1a | 60,288 | 208,134 | 166,664 | 186 B |
| 1b | 60,250 | 208,195 | 166,762 | 192 B |

### matmul (1b first)

**Both versions passed on the first run.** Before measuring, I noticed I had
written the 1a dot product with A's element as the multiplier (`src`) and
1b's with B's. Multiply time depends on the bit length of `src`, so I
swapped the 1a loads to match before taking any numbers. (The values are
uniformly random, so neither choice is better; they just have to be the
same.)

Every number is a word (draft 0 stored 16-bit values). **B is stored
transposed as it is generated**, so C[i][j] is a dot product of two
contiguous runs of words. This helps both ISAs equally and is what I'd do on
either: 1a can then reach all sixteen operands with one-parcel
`LD r, [r4 + 4k]` / `[r5 + 4k]` (offsets 0-28; with B in row order the
column offsets 0-224 would need long forms past 60), and 1b walks both with
`[r]+`. The k loop is unrolled in both (as in draft 0).

```
; 1a: no pointer moves inside       ; 1b: two auto-increment walkers
        LD   r1, [r4 + 4]                   MOV  r1, [r6]+
        LD   r2, [r5 + 4]                   MOV  r2, [r5]+
        MULS r1, r2                         MULS r1, r2
        ADD  r3, r1                         ADD  r3, r1
```

Per element the two are identical in cost (`LD [r + 4k]` and `MOV [r]+`
are both 4 cycles on D16-overlap); 1b needs a `MOV r6, r4` per column to
restart the row walker but gets the next row of A for free at the end of
the column loop (`MOV r4, r6`), and 1a needs `ADDI` for the C pointer and
the bt row. The multiply phase uses only scratch registers (no calls):
7 in 1b, 6 in 1a.

The checksum loop is where 1b's memory operands show, with half-word
operands reading the two halves directly:

```
; 1b: 7 instructions per word       ; 1a: 11
.sum:   ADD  r10, half [r8]         .sum:   LD   r1, [r7]
        ADD  r11, r10                       ADD  r9, r1
        ADD  r10, half [r8 + 2]             ZXH  r2, r1
        ADD  r11, r10                       ADD  r10, r2
        ADD  r9, [r8]+                      ADD  r11, r10
        CMP  r8, #mat_c + ROW * N           LSR  r1, #16
        BNE  .sum                           ADD  r10, r1
                                            ADD  r11, r10
                                            ADDI r7, 4
                                            CMP  r7, r6
                                            BNE  .sum
```

The Fletcher sums are kept unmasked in 32 bits in both and printed with
`print_hex` at 4 digits: sums mod 2^16 are the low halves of the 32-bit
sums, so the reference's per-step `& 0xFFFF` is unnecessary.

`MULS` is 32% of the cycles (512 multiplies, 12-bit multipliers, 24.6
cycles each on D16), `rand` 19% (its `LSL #7` alone is 7 shift steps:
there's no barrel shifter) and decimal printing 14% (`DIVU`, 67 cycles per
digit on D16). By phase (cycles in `main` only): the multiply is 19,093 in
1a and 18,886 in 1b (the dot products are identical; 1b's per-column
bookkeeping is a little cheaper), the checksum and report 2,444 vs 2,173,
the fill 3,903 vs 3,839.

| | instructions | D16-ovl | D32-ovl | code (program only) |
|---|---:|---:|---:|---:|
| 1a | 6,741 | 39,661 | 27,597 | 284 B |
| 1b | 6,316 | 39,057 | 27,345 | 274 B |

### bst (1a first)

**1a: one assembler error** ("undefined symbol s_height": I left out the
string when writing the data, nothing to do with the ISA). **1b passed on
the first run.**

The design follows draft 0: nodes come from a zero-filled static pool (so
the links of a fresh node are already 0 and need no stores), insertion
follows a pointer to the link being replaced so attaching is one store, the
in-order walk keeps its state (countdown, count, previous key, order flag)
in r10-r13, and `height` is plainly recursive. Two small improvements, the
same in both ISAs: the walk tests a left child for 0 *before* calling
(`LD r1, [r8 + LEFT]` / `BEQ`, since the load sets Z), and the right
subtree is a loop in the same frame (`LD r8, [r8 + RIGHT]` / `BNE .node`)
rather than draft 0's pop-and-tail-call.

**The node layout differs, deliberately, to suit each ISA's insert walk.**
Both rely on `MOV` leaving C alone between the compare and the branch:

```
; 1a: left link first (LEFT = 0, KEY = 8)
.walk:  LD   r4, [r3]           ; the node at this link, or 0
        BEQ  .link
        LD   r5, [r4 + KEY]
        CMP  r1, r5
        MOV  r3, r4             ; = its left link; MOV leaves C alone
        BLO  .walk
        ADDI r3, RIGHT
        BRA  .walk

; 1b: key first (KEY = 0, LEFT = 4)
.walk:  MOV  r4, [r3]
        BEQ  .link
        CMP  r1, [r4]+          ; its key; r4 moves on to its left link
        MOV  r3, r4
        BLO  .walk
        ADD  r3, #RIGHT - LEFT
        BRA  .walk
```

1b's `CMP r1, [r4]+` does a load, a compare and the step to the left link
in one parcel: insert is 5% faster in 1b (12,746 vs 13,372 cycles).

**Struct fields at small offsets favour 1a**, though: in `inorder` and
`height` every field other than offset 0 is a one-parcel `LD r1, [r8 + 4]`
in 1a and a two-parcel `MOV r1, [r8 + 4]` in 1b (5 cycles against 4), so
1b is 3.5-5% slower in those two routines. With the timing model's cheaper
`[r]+` I checked whether 1b should use 1a's layout (left first, then
`MOV r1, [r8]+` for left, key, right in walk order). Measured: it saves 300
cycles in the walks and loses 726 in the insert loop (37,226 vs 36,800 in
total), so I kept the key first.

Registers: insert uses r1-r5 (key, new node, link pointer, node, key
temporary in 1a); the walk r8 plus the four globals.

| | instructions | D16-ovl | D32-ovl | code (program only) |
|---|---:|---:|---:|---:|
| 1a | 10,989 | 37,093 | 30,354 | 208 B |
| 1b | 10,300 | 36,800 | 30,123 | 212 B |

`rand` (16%) and decimal printing (14%) are a third of this small program
in both.

## Summary

All ten programs pass `tmc test` (`python3 -m tmc --isa v1a test mandel life
queens matmul bst`, and the same for v1b). Order written: mandel 1a first,
life 1b first, queens 1a first, matmul 1b first, bst 1a first.

### Numbers

`run --stats` cycle counts for every configuration. "Code (total)" is what
`run`/`test` report, libraries included; "code (program)" counts only the
instructions in the program file.

| program | ISA | instructions | D16-sep | D16-ovl | D16-wide | D32-sep | D32-ovl | D32-wide | code (total) | code (program) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mandel | 1a | 149,684 | 827,186 | 688,533 | 685,514 | 595,665 | 457,012 | 453,993 | 238 | 98 |
| mandel | 1b | 129,061 | 770,449 | 652,419 | 640,123 | 575,062 | 457,032 | 444,736 | 236 | 100 |
| life | 1a | 267,941 | 1,081,919 | 838,570 | 792,689 | 932,559 | 689,210 | 643,329 | 810 | 272 |
| life | 1b | 164,674 | 843,575 | 703,493 | 616,276 | 715,562 | 575,480 | 488,263 | 740 | 266 |
| queens | 1a | 60,288 | 258,161 | 208,134 | 177,578 | 216,691 | 166,664 | 136,108 | 724 | 186 |
| queens | 1b | 60,250 | 258,184 | 208,195 | 179,562 | 216,751 | 166,762 | 138,129 | 666 | 192 |
| matmul | 1a | 6,741 | 45,169 | 39,661 | 36,703 | 33,105 | 27,597 | 24,639 | 572 | 284 |
| matmul | 1b | 6,316 | 44,140 | 39,057 | 35,914 | 32,428 | 27,345 | 24,202 | 560 | 274 |
| bst | 1a | 10,989 | 45,037 | 37,093 | 32,702 | 38,298 | 30,354 | 25,963 | 496 | 208 |
| bst | 1b | 10,300 | 44,055 | 36,800 | 31,902 | 37,378 | 30,123 | 25,225 | 498 | 212 |
| **total** | 1a | 495,643 | 2,257,472 | 1,811,991 | 1,725,186 | 1,816,318 | 1,370,837 | 1,284,032 | 2,840 | 1,048 |
| **total** | 1b | 370,601 | 1,960,403 | 1,639,964 | 1,503,777 | 1,577,181 | 1,256,742 | 1,120,555 | 2,700 | 1,044 |

Over the five programs 1b runs 25% fewer instructions and takes 9.5% fewer
cycles on D16-overlap (8.3% on D32-overlap, 13% on the wide and separate
configurations). The program code is the same size (1,044 vs 1,048 bytes):
1b has fewer instructions (410 vs 440 statically) but more of them are
two or three parcels (112 vs 84). **Almost all of the cycle difference is one
program**: life accounts for 135K of the 172K cycles 1b saves on
D16-overlap, mandel's `LEA` trick for 36K, and the other three are within
1.6% of each other.

**Caution on the wide-fetch numbers:** they depend on loop alignment, and
much more so for 1b. Shifting the code by one parcel (one `NOP` before
`step`) moves 1b life on D16-wide from 616K to 688K cycles (+12%), because
its cell loop is a run of seven two-parcel instructions whose extension
parcels are either all free (opcode at a word boundary) or all need their
own fetch. The same shift moves 1a life by 0.05% (its two-parcel loads
alternate with one-parcel `ADD`s) and leaves D16-overlap unchanged in both.
None of my code is deliberately aligned; the table shows whatever alignment
the code happened to get. (Aligning a loop head would need NOP padding:
`.align` fills with zero bytes, which are `HALT`.)

### Observations, most important first

1. **Memory operands decide the comparison, and they only help in one kind
   of loop**: one that combines many values from memory into a register.
   life's neighbour count is that loop, and there 1b is 16% faster with 39%
   fewer instructions (one `ADD r1, byte [r2 + d]` per neighbour against a
   load plus an `ADD`). The same pattern gave smaller wins in matmul's
   checksum (`ADD r10, half [r8]`: 7 instructions per word against 11) and
   bst's insert (`CMP r1, [r4]+`: load, compare and step in one parcel).
   Everywhere else the operands were already in registers: mandel, queens
   and matmul's dot products have no use for a memory operand. (`MULS`
   can't take one in 1b anyway.)
2. **Walking arrays is a draw.** 1a's one-parcel `[reg + small offset]`
   and 1b's `[r]+` cost the same (on D16-overlap 4 cycles for a word and 3
   for a byte, in both), and both remove pointer increments, 1a by
   unrolling with constant offsets, 1b by auto-increment. matmul's
   dot product is equal to the cycle. What decides it is the offset range:
   1a's 0-15 byte / 0-60 word reach is too short for a 34-byte grid row (six
   of life's nine loads are long forms), while 1b's only one-parcel
   displacement is 0, so every struct field but the first costs it a parcel
   (bst's `inorder` and `height` are 3.5-5% slower in 1b, and I chose bst's
   node layout in each ISA around this).
3. **Two-operand code costs both ISAs the same, and it's the largest
   overhead in register-bound code.** In queens, register `MOV`s are 23% of
   the cycles in both ISAs (copying arguments into callee-saved registers,
   and `MOV r2, r9` / `BIC r2, r1` to build each child mask), and
   `SAVE`/`RESTORE` another 23%. 1b's `LEA r, [rA + rB*s]` is the only
   three-operand form either ISA has, and only for addition: in mandel it
   folds seven one-parcel instructions into three `LEA`s and a `SUB`. That
   is 5% on D16 but exactly 0% on D32-overlap, because it only exploits the
   timing model charging an address add one cycle where a 16-bit datapath
   charges a data add two.
4. **The multiplier, not the ISA, is now the cost in the numeric programs.**
   `MULS` is 50% of mandel's cycles and 32% of matmul's in both ISAs (16 and
   25 cycles per multiply on D16; one step per bit of the second operand).
   Decimal printing is a `DIVU` per digit (67 cycles on D16), 14% of bst
   and matmul. These dwarf any encoding difference in those programs.
   The 32-bit registers, `MULS` and `SETcc` made every program simpler than
   in draft 0: mandel lost its multiply subroutines and its memory-resident
   loop counters, life's rule lost the `NEG`/`ADC r0` trick, queens' column
   number is `32 - CLZ`.
5. **Constants: 1a's 8-bit immediates fit what these programs use, 1b's
   4-bit ones often don't.** 16, 31, 32, 34, 35, 2048 and every character
   except control codes are two parcels in 1b (`ADD r11, #31`,
   `MOV r1, #'Q'`, `MOV r4, #ROWS`), one in 1a (`ADDI`, `MVI`, `CMPI`).
   1b's mode D gives -1..-16, so `SUB r10, #-16` adds 16 in one parcel,
   but the assembler can't substitute it for `ADD #16` because C differs.
   This is why 1b's code is no smaller despite having fewer instructions.

Smaller points:

- **`MOV` leaving C alone (both ISAs) and 1a's flag-preserving `ADDI`** are
  what make bst's "compare, then compute the link, then branch" walk work
  with no extra instructions. 1b's `INC`/`DEC` and 1a's `ADDI` setting N
  and Z (not C or V) were exactly right for counters ending in `BNE`/`BMI`.
- **1b's missing mode**: no `half [r]+` (life's pattern list became words).
  I never needed the immediate forms 1b lacks (`TST`, `BIC`, `MUL` are
  register-only there) in these five programs.
- **Registers were never short.** The most any hot loop needed was 10
  (queens: four arguments, five saved, one global); mandel 9, life 6-7,
  matmul 6-7 (scratch registers only), bst 5 plus 5. Draft 0's mandel had
  to keep counters in memory; nothing here did.
- **Choosing between alternatives needed measurement in 1a more than in 1b.**
  life's one-pointer vs three-pointer step and LEA vs `MOV`+`ADDI` for a
  pointer copy (3 vs 6 cycles on D16) are trade-offs between parcels and
  instructions that the timing model resolves in non-obvious ways. In 1b
  the two alternatives I measured (bst's node layout, plain `MOV`/`ADD`
  instead of `LEA` in mandel) both confirmed the first, obvious choice.

### Mistakes

- bst 1a: assembler error "undefined symbol s_height" (I left the string
  out of the data). Not ISA-related.
- life 1a: my first draft of the three-pointer step ran out of scratch
  registers and kept the row end on the stack (`LD r1, [sp]` / `CMP r2, r1`
  per cell); I replaced it with `SAVE r8-r9` before running it, and later
  dropped that variant for the single-pointer one.
- matmul 1a: I wrote the dot product with the other factor as the
  multiplier than in 1b; fixed before measuring (multiply time depends on
  the second operand).
- No wrong output and no traps in any program, in either ISA.

### Specs and tools

- **The multiply operand**: when I started, the timing document didn't say
  which operand's bit length sets the multiply time; the spec now says it
  (the second). Mid-way the model also changed `[r]+` to cost the same as
  `[r]`; my 1b numbers above are with the new model (life went from 714K
  to 703K on D16-overlap). I hadn't avoided `[r]+` anywhere because of its
  cost, so no code changed.
- **`run --stats` for draft 1 gives instruction counts by kind but no
  cycles by kind or by routine** (draft 0's did). I wrote a small profiler
  over `Machine32.pc_keys` and `timing32.cycles` to get the breakdowns
  quoted here; it would be worth adding to `run --stats`.
- **Wide-fetch results depend on alignment** (see the caution above), and
  there is no way to align a loop head without executing padding, since
  `.align` pads code with zero bytes (`HALT`). An `.align` that pads code
  with `NOP`s, or a note in the timing document, would help.
- No assembler or simulator bugs found in what these programs exercise
  (`[label + r]` in both ISAs, 1b's indexed `LEA`, mode D constants,
  `SETcc`, `CLZ`, shifts by 1-16, `SAVE`/`RESTORE` ranges, branch
  relaxation to `CALL`/`Jcc`). No library bugs found either; the programs
  use `puts`, `putc`, `space`, `newline`, `print_u32`, `print_s32`,
  `print_hex`, `memcpy`, `srand` and `rand`.
