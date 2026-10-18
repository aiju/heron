# Plasma and fire

## What it is

How many pixels the CPU can touch in a frame at 8 bits a pixel, and
what the palette and the descriptors do instead for nothing: a plasma
computed pixel by pixel at three resolutions, the same plasma by
palette cycling only, a full-resolution plasma made by the descriptors
alone, and a fire (each pixel the average of four below it) with a
burning logo. Each in C and in assembly, in L0 and L1.

```sh
heron mini_gfx run demos/plasma                         # C, L0; about 600 frames
heron mini_gfx run demos/plasma --variant asm
heron mini_gfx run demos/plasma --variant asm --layout L1
```

## How it uses the video

- **M1** (320 × 480 × 8): 80 words a line, 4 pixels a word.
- **Lines repeated by the descriptors** for lower resolutions: 320 ×
  240, × 120 and × 60 are 240, 120 and 60 rows of 80 words, each line
  of a row's descriptor pointing at the same words (2, 4 or 8 times).
  No 320 × 240 mode is needed: the descriptors give it for 480 words a
  frame.
- **Double buffering with `TSEL`**: two pictures, two tables; the
  table switches in the blanking after the frame's interrupt.
- **The palette**: every part cycles a cyclic 256-colour palette
  (entry *i* gets colour *i* + *t*); the fire has a black-red-yellow-
  white ramp.
- **The descriptor plasma** (part 4): the lines point into 340
  precomputed rows (85 brightness offsets × 4 byte phases) in bank 1.
- **Layouts**: in L0 a pixel is a byte (linear). In L1, M1's pixel *p*
  has bit *i* at 8*i* + 2*p* (*i* < 4) or 8(*i* − 4) + 2*p* + 1, so every
  computed word goes through a table: a byte's bits where pixel 0's go,
  shifted 2*p* (`plasma_row_l1`, `plasma_row_l1_asm`).
- **Bandwidth**: M1 needs a word every 16 ticks; B0, B1 and B2 give
  identical results, no steals or underruns.
- No block instructions: they have nothing for per-pixel arithmetic, so
  the variants are c and asm.

The plasma is p(*x*, *y*) = A[*x* + a(*y*)] + B[*x* + b(*y*)] + c(*y*):
A and B are fixed rows of bytes (sines, each term under 85 so that the
sum is under 256), kept in four copies a byte apart, so any byte offset
is a word's load; a(*y*), b(*y*) and c(*y*) are sines of the line and the
time. Four pixels a word with a plain 32-bit add: the bytes never carry
into each other. The inner loop is three memory accesses and two adds
a word:

```
.l:     MOV  r0, [r2]+
        ADD  r0, [r3]+
        ADD  r0, r4
        MOV  [r1]+, r0          ; four times, then DEC r5; BNE .l
```

The fire averages bytes four at a time without carries,
(x & y) + ((x ^ y) >> 1 & 0x7F7F7F7F), the left and right neighbours
built from the words beside with shifts; about 38 instructions a word.

## Implementations and measurements

Ticks are 19.86 ns, a frame 840,000. "Updates a second" counts the
frames between flips; each part's count includes a screenshot, which
stops the program for 3 frames (so 56 is 60 and 28 is 30).

**The plasma computed per pixel** (each update: all its rows, then the
palette cycled):

| Resolution | Variant | Layout | Ticks a word | An update | Of a frame | Updates a second |
|---|---|---|---:|---:|---:|---:|
| 320 × 240 | c | L0 | 95 | 36.4 ms | 219% | 20 |
| | asm | L0 | 79 | 30.1 ms | 181% | 30 |
| | c | L1 | 382 | 145.8 ms | 874% | 6–7 |
| | asm | L1 | 302 | 115.4 ms | 692% | 8 |
| 320 × 120 | c | L0 | 95 | 18.2 ms | 109% | 30 |
| | asm | L0 | 79 | 15.0 ms | 91% | **60** |
| | c | L1 | 382 | 72.9 ms | 437% | 12 |
| | asm | L1 | 302 | 57.7 ms | 346% | 15 |
| 320 × 60 | c | L0 | 95 | 9.1 ms | 55% | 60 |
| | asm | L0 | 79 | 7.5 ms | 45% | 60 |
| | c | L1 | 382 | 36.4 ms | 219% | 20 |
| | asm | L1 | 302 | 28.8 ms | 173% | 30 |

**What the palette and the descriptors do instead** (each frame; the
same in every variant and layout):

| Technique | Ticks a frame | Of a frame | Pixels touched |
|---|---:|---:|---:|
| Palette cycling, 256 entries (C, unrolled by four) | 9,600 | 1.1% | 0 |
| Descriptor plasma at 320 × 480: 480 descriptors (C) | 113,000 | 13.5% | 0 |
| (its rows, once: 85 × 4 rows of 144 words) | | | 196 KB of bank 1 |

**The fire** (an update: the fuel seeded, the kernel over all rows, the
logo's pixels heated; the kernel alone in the last column):

| Resolution | Variant | Layout | An update | Of a frame | Updates a second | Kernel, ticks a word |
|---|---|---|---:|---:|---:|---:|
| 320 × 120 | c | L0 | 70.0 ms | 420% | 12 | 348 |
| | asm | L0 | 61.9 ms | 371% | 15 | 306 |
| | asm | L1 | 115.1 ms | 690% | 8 | 306 (+ the conversion) |
| 320 × 60 | c | L0 | 36.9 ms | 221% | 20 | 348 |
| | asm | L0 | 32.7 ms | 196% | 30 | 306 |
| | asm | L1 | 59.3 ms | 356% | 15 | 306 (+ the conversion) |

**How many pixels the CPU can touch in a frame** (all of it, L0):

| Work a pixel | asm | C | At 60 Hz, at most |
|---|---:|---:|---|
| plasma: 2 loads, 2 adds, a store a word | 42,500 | 35,400 | 320 × 133 |
| fire: 4 neighbours averaged, cooled | 11,000 | 9,700 | 320 × 34 |
| plasma in L1 (through the table) | 11,100 | 8,800 | 320 × 34 |

## What worked well

- **Lines repeated by the descriptors** trade resolution for frame rate
  at no cost: the same plasma at 320 × 120 runs at 60 Hz in assembly
  and 30 in C, at 320 × 240 at 30 and 20.
- **Four pixels a word with a plain add** (terms under 85): no `ADD.B4`
  needed, and C does it as well as assembly does.
- **Palette cycling** is the cheapest animation there is: 1% of a frame
  for all 256 entries, the whole picture moving.
- **The descriptor plasma**: with one table term, p = A[*x* + a(*y*)] +
  c(*y*), every line is a row of A + c from some byte on, so 340
  precomputed rows and a descriptor a line give an animated plasma at
  the full 320 × 480 for 13.5% of a frame (in C; most of it the C's per
  line), against 181% for a quarter of the resolution computed. Less
  rich (one wave across, bands down), but alive.
- **The burning logo**: a mask ORed with random heat over the logo's
  rows only; cheap and convincing.

## What was hard or didn't work

- **Memory accesses dominate**: the plasma's assembly loop is four
  instructions a word, three of them memory accesses, and costs 79
  ticks; the compiled C 95. Hand-written assembly buys 17%; nothing
  more is to be had without fewer accesses.
- **M1 in L1** costs 3.8–4 times as much for anything computed a pixel
  at a time: a word's four bytes go through four table lookups and
  shifts (302 against 79 ticks a word in assembly). The fire in L1 is
  computed in L0 buffers and converted, nearly doubling it.
  Precomputed pictures (the descriptor plasma's rows, converted once)
  and palette effects don't care.
- **C's divides and multiplies in per-line loops**: the first version of
  the descriptor plasma took 974 ticks a line (a `%`, two multiplies,
  three divides by constants), the table version 235.
- **The fire is expensive**: 77 ticks a pixel; 320 × 60 at 30 Hz is what
  it gets.

## What would have helped

- **A microcoded "add rows" block instruction** (d[i] = a[i] + b[i] + c
  over *n* words): three accesses a word as `COPY` does two (19.3 ticks a
  word), about 28 ticks a word against 79: the 320 × 240 plasma in 538K
  ticks (64% of a frame, 60 Hz) instead of 30 Hz.
- **A microcoded byte-average** (the fire's four-neighbour average and
  cooling over *n* words, ~6 cycles a word): ~42 ticks a word against
  306, the 320 × 120 fire at 60 Hz.
- **L0 for M1.** If one layout must be chosen for 8-bit effects, L0: L1
  makes per-pixel work four times dearer.
- **No 320 × 240 × 8 mode with half the bandwidth is needed** while there
  are descriptors: they repeat lines for 480 words a frame, the memory is
  already halved (the picture is 240 rows), and with B0 the video never
  holds the CPU, so fewer fetches would give the CPU nothing. With D1
  (a frame base, no descriptors) it would be the only way to double
  lines.
- **A pixel offset in the descriptor** (2 bits in M1) would let the
  descriptor plasma use one row per brightness instead of four phases
  (49 KB instead of 196 KB).

## Issues found

- None in the video or the library here; the runtime issues (the frame's
  interrupt swallowed, `rt_line_hook`'s line, `video_ticks()` with
  interrupts off) are in `../rasterbars/NOTES.md`.
- **C pitfalls worth a line in the study's guide**: a signed `/ 256` is a
  five-instruction shift sequence, `%` a `DIVS`, `* 144` a multiply
  (tens of cycles); in per-line loops they cost more than the work.

## Screenshots

`heron mini_gfx run demos/plasma` writes them to
`build/mini_gfx/shots/demos-plasma/`:

- `plasma_240.png`, `plasma_120.png`, `plasma_60.png`: the per-pixel
  plasma at 320 × 240, 120 and 60, rows repeated 2, 4 and 8 times:
  the same picture, coarser down.
- `cycle.png`: the plasma drawn once, the palette cycled.
- `desc.png`: the descriptor plasma at the full 320 × 480: waving bands,
  no pixel touched.
- `fire_120.png`, `fire_60.png`: the fire at 320 × 120 and 60, the logo
  burning in the middle.
