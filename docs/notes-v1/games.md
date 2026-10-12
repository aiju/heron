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

Two things I did the same way in both:

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
| 1a | 267,981 | 838,690 | 689,250 | 272 B |
| 1b | 164,694 | 703,573 | 575,520 | 268 B |

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
cycles each on D16), `rand` 19% (its shifts by 7 and 9 cost 7-9 steps:
there's no barrel shifter) and decimal printing 14% (`DIVU`, 67 cycles per
digit on D16). The matrix product proper is the same in both ISAs; the 1.5%
difference comes from the checksum loop and the fill.

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
1b is 4-5% slower in those two routines. With the timing model's cheaper
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
