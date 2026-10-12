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
  (y = cy + 2xy in one instruction), `LEA r8, [r10 + r1]`. Five one-parcel
  ALU instructions become three two-parcel `LEA`s. That is 5% faster on
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
per neighbour and one instruction fetch, and the auto-increment saves the
`ADDI`s.

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
  the same four loads/stores in both, all two-parcel except one in 1a and
  two in 1b.

| | instructions | D16-ovl | D32-ovl | code (program only) |
|---|---:|---:|---:|---:|
| 1a | 267,981 | 838,690 | 689,250 | 272 B |
| 1b | 164,694 | 714,417 | 586,364 | 268 B |

95% of the time is in `step` in both. 1b is 15% faster on D16-overlap and
runs 39% fewer instructions.
