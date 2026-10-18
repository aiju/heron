# Snake in assembly

```sh
heron mini_gfx run games/snake_asm                      # asm (any variant but blk is the same code)
heron mini_gfx run games/snake_asm --variant blk        # FILL and COPY for the big fills and copies
heron mini_gfx run games/snake_asm --layout L1
```

## What it is

[../snake](../snake/NOTES.md)'s game written again in draft 2 assembly
([snake.s](snake.s)), with the graphics library left out: the same M1 at
320 × 240, grid, walls, lawn, segments with bridges, eyes, berry, bar,
block letters, READY, PAUSED and GAME OVER banners, crash shake, title
ripple, colour wave, autopilot and measurements. Only the title's sky
gradient (line interrupts, whose hook is a C function pointer) is left
out. [main.c](main.c) is 17 lines: it calls `snake_main` and tells it
whether this is the blk build.

The assembly calls the runtime's C functions by the C convention
(`video_init`, `video_wait`, `input_init`, `input_next`, `video_ticks`,
`rt_shot`, `perf_frame_begin`, `perf_frame_end`, `perf_frames`,
`perf_value`) and does everything else itself: its own rectangle fill,
pixel, text (from the cell font's data, `font_cell8`), digits, block
letters, palette and descriptor writes. It's a faithful port: run with the
same script, it plays the same game as the C one, and the `game`
screenshots of the two are identical pixel for pixel below the bar.

## How it uses the video

As [../snake](../snake/NOTES.md#how-it-uses-the-video): M1 with two
descriptors a row, banners, shake and ripple by descriptors, the body's
16 palette entries rotated with the glint, blink and flash, no cursor, the
beam as the clock, B0. Three things are its own:

- **Both layouts from tables.** At start it builds, for the board's
  layout (`board_layout`): each pixel's mask in a word, the masks of the
  pixels from p on (a rectangle's edges), the 16 masks of a glyph row's
  nibble, and the word of each colour (from the 8 planes: bit i of every
  pixel). All the drawing goes through them, so L0 and L1 draw the same
  picture (checked: identical screenshots) at the same speed.
- **Fixed addresses in bank 1** for the framebuffer, the two banners and
  the empty board, and the descriptor table written directly at
  0x2000B0.
- **The block instructions** only where they fit: `FILL` for whole rows
  (the title's clear, the banners, the measured field fill) and `COPY` for
  the field copy, in the blk variant; everything else is small and goes
  through the `MERGE` loop.

## Implementations and measurements

Microseconds (a frame is 16,683 µs); the C game with the library's C
kernels and with its block kernels, against this one.

| Technique | C game, c | C game, blk | asm | asm, blk |
|---|---:|---:|---:|---:|
| A game frame, average | 591 (3.5%) | 579 (3.5%) | 238 (1.4%) | 238 (1.4%) |
| A game frame, worst (a berry) | 13,281 | 13,353 | 2,144 | 2,144 |
| A step's drawing | 425 | 376 | 170 | 170 |
| One 8 × 8 cell | 82.6 (`gfx_fill`), 17.0 (16 stores in C) | 66.6 | 31.1 (`fill_rect`) | 31.1 |
| The bar's 13 digits | 10,243 (`font_cells`), 857 (nibble table in C) | 10,366 | 808 | 807 |
| Walls and lawn (the empty board) | 156,716 | 142,511 | 41,197 | 41,197 |
| The title screen | 57,962 | 46,026 | 15,361 | 10,961 |
| The playfield filled | 12,936 | 3,400 | 6,553 | 2,583 |
| The playfield copied | 19,251 | 7,520 | 11,858 | 6,710 |
| A full redraw (copy, 29 segments, berry) | 23,790 | 11,555 | 13,433 | 8,263 |
| Redrawing 29 segments | 4,151 | 3,627 | 1,551 | 1,551 |
| The palette's frame (19 entries) | 52 | 52 | 31 | 32 |
| The ripple (144 descriptors) | 1,401 | 1,401 | 238 | 238 |
| All 480 descriptors | 294 | 294 | 290 | 290 |

| Size | C game | asm game |
|---|---:|---:|
| Source lines | 978 (snake.c) | 2,025 (snake.s, about 1,400 instructions) + 17 |
| The program's code, bytes | 7,556 (1,882 of it measuring) | 4,132 (374 measuring) |
| Its data | 1,440 + 23.6 KB bss | 1,388 + 8.2 KB bss |
| Linked image's code, bytes (runtime, C library, graphics library) | 17,760 | 7,104 |

- **2.5 times faster a frame and a step, 3.8 times for the board and
  the title**, 6 for the ripple; the worst frame (a berry) 6 times better.
- **The text is the algorithm, not the language:** the assembly's digits
  (808 µs) are the C nibble table's (857 µs); the library's `font_cells`
  takes 10,243.
- **And specialisation beats both:** an 8 × 8 cell written as 16 stores
  in C (17 µs) is faster than this game's general rectangle fill in
  assembly (31 µs), which handles any edge with masks.
- **FILL and COPY** halve the big fills and copies here too (6.6 → 2.6 ms,
  11.9 → 6.7 ms); the game's frame doesn't use them.
- **Two thirds of the code, two fifths of the image:** the game's code is
  3.8 KB against 5.7 KB of C, which also reaches into the library (the
  image: 7.1 KB against 17.8 KB of code). The source is twice as long.

## What worked well

- **Writing graphics in draft 2 is pleasant.** `MERGE` (`d & ~m | s & m`
  in one instruction) is exactly a masked pixel write; auto-increment
  stores make fill loops of one instruction a word; `DBNZ` closes small
  loops; `SAVE`/`RESTORE` ranges make prologues one line.
- **Addressing modes fit tables:** `[label + r*4]` reads a colour's word,
  a mask or a direction straight from a table (two extension parcels);
  `[r14 + 4R]` (mode E) made the game's 16 hottest variables one-parcel
  operands all through the program (`r14` survives C calls).
- **Tail calls:** the cell routines (grass, block, bridge, unstub) set up
  a rectangle and `BRA fill_rect`, which returns for them.
- **Calling the C runtime** by its convention was simple: arguments in
  `r1`–`r4`, the result in `r1`, save `r7` around calls.
- **It ran correctly the first time it assembled**, and the identical
  screenshots against the C game were a strong check that it plays the
  same game.

## What was hard or didn't work

- **`DBNZ` reaches only 16 parcels back:** three loops (the shake, the
  ripple, the text's rows) had to become `DEC`/`BNE`, and counting parcels
  by hand (an immediate over 15 or an indexed table operand adds one or
  two) is tedious.
- **Registers run out in nested drawing loops:** the block-letter routine
  keeps its column, inset and colour in memory, since `r0`–`r6` go to each
  `fill_rect` call and `r8`–`r13` hold the loop's state.
- **Byte loads zero-extend:** the ripple's sine table became words
  (pre-multiplied into descriptor offsets) rather than signed bytes.
- **No byte pre-decrement mode:** writing a number's digits backwards
  takes `DEC` and a plain store.
- **Constants over 15** (row pitches of 320, steps of 80) cost an
  extension parcel in `ADD`/`SUB`.
- **The layouts:** writing pixels directly means knowing L1 too; the
  tables make it free at run time but were the part needing most thought.

## What would have helped

- **A longer `DBNZ`** (a two-parcel form with a 16-bit displacement), or
  the assembler relaxing `DBNZ` into `DEC`/`BNE` when out of reach.
- **A sign-extending byte load** (`MOVS` that sign-extends, or `SXB` folded
  into a load) for signed tables.
- **For graphics:** nothing as much as the X1 `EXPAND` at 8 bits for text
  (808 µs for 13 digits now; perhaps 200 µs microcoded), and a rectangle
  `FILL` with a pitch and a row count (each 6 × 6 or 8 × 8 fill is 8 rows of
  per-row setup).
- **For the Neo Geo-like mode:** see [../snake](../snake/NOTES.md#what-would-have-helped):
  a tile layer would make each step three stores.

## Issues found

- None in the hardware or the simulator. The library's gaps that the C
  game hits (8-bit text, `gfx_fill_pat` and `gfx_masked`) are what this
  version avoids by drawing its own way; see
  [../snake](../snake/NOTES.md#issues-found).
- **The C hooks for line interrupts** (`rt_line_hook`) are C function
  pointers called from `rt_irq`; an assembly hook has to follow the C
  convention too. That's fine, but it's why this version has no sky.

## Screenshots

`heron mini_gfx run games/snake_asm` writes them to
`build/mini_gfx/shots/games-snake_asm/`:

- **title:** the block letters in the rotating colours, no sky gradient.
- **game:** step 200, identical to the C game's below the bar (the bar
  has no CPU share).
- **paused:** the PAUSED banner (its small line in the cell font).
- **game_over:** the GAME OVER banner after the shake.
