# Snake

```sh
heron mini_gfx run games/snake                          # c: the library's C kernels
heron mini_gfx run games/snake --variant asm            # its assembly kernels
heron mini_gfx run games/snake --variant blk            # and the block instructions
heron mini_gfx run games/snake --layout L1              # the planar layout: the same pictures
```

## What it is

Snake in M1 used as 320 × 240 × 8 ([snake.c](snake.c), all drawing
through the library): a grid of 8 × 8 cells (40 × 27, the outer ring
brick walls) on a chequered lawn, the arrow keys (up to four turns typed
ahead), a berry to eat, three cells' growth and a little more speed every
third berry, the score, the length and the best in the cell font, and a
title screen whose letters are made of snake segments. `p` pauses, `a`
hands the snake to an autopilot (greedy for the berry, with a bounded
flood fill so it doesn't wall itself in). The script plays a game: a few
turns by hand, the autopilot, a pause, the autopilot off and a crash into
the wall. After the game the program measures each way of drawing.

The snake is drawn the way the cells change: a step draws the new head,
turns the old head into body (a 6 × 6 square and a 2-pixel bridge to the
head) and gives the tail's cell back to the grass, about ten small fills.
Colour comes from the palette, not from drawing.

[../snake_asm](../snake_asm/NOTES.md) is the same game in assembly; the
two play exactly the same game from the same script (their game
screenshots are identical, pixel for pixel, below the bar).

## How it uses the video

- **Mode:** M1, every framebuffer row on two lines (two descriptors
  with the same address, as RFC 0042 says): a 76.8 KB framebuffer in bank
  1. Pixels are bytes in L0 (PF_LIN8); in L1 (PF_PL8) the library hides
  the scattering and the pictures are the same.
- **Descriptors:** besides the line doubling,
  - **banners** (READY, PAUSED, GAME OVER): 48 rows drawn once into
    buffers of their own, shown by pointing 96 lines at them and back.
    Nothing under them is touched, so nothing is saved or restored;
  - **a shake** when the snake crashes: all 480 descriptors moved a few
    rows up or down for 16 frames;
  - **a ripple** through the title: each of its 144 lines shows a row up
    to two above or below its own, by a sine running down the band.
- **Palette:** the body's 16 entries rotated a step every two frames run
  a wave of colour down the snake (each segment keeps the entry of its
  place in the ring) and through the title's letters; one entry makes
  the berry glint, one blinks "press space", two flash the lawn when the
  snake eats. On the title, a sky gradient of 30 bands from **line
  interrupts** (descriptor bit 23 every 16 lines; the hook writes the
  background's palette entry).
- **Palette banks:** not used: in M1 the palette index is the pixel.
- **Cursor, beam:** no cursor. The beam (P1) is the clock for every
  measurement (`video_ticks`).
- **Bandwidth:** B0, no underruns; B1 changes nothing.
- **Block instructions:** through the library in the blk variant (FILL
  and COPY in the big fills and copies).

## Implementations and measurements

A frame is 840,000 ticks, 16.68 ms. Microseconds, in the three variants of
the library's kernels; the last column is
[snake_asm](../snake_asm/NOTES.md) (asm variant; FILL and COPY in its blk
variant in brackets). The snake was 29 long.

| Technique | c | asm | blk | snake_asm |
|---|---:|---:|---:|---:|
| A game frame, average (% of a frame) | 591 (3.5%) | 577 (3.5%) | 579 (3.5%) | 238 (1.4%) |
| A game frame, worst (a berry: the digits) | 13,281 | 13,274 | 13,353 | 2,144 |
| A step's drawing (about 10 fills, 4 pixels) | 425 | 368 | 376 | 170 |
| One 8 × 8 cell, `gfx_fill` | 82.6 | 64.9 | 66.6 | 31.1 (own fill) |
| One 8 × 8 cell, its 16 words written in C | 17.0 | 16.8 | 16.8 | |
| `gfx_pixel` | 14.8 | 14.8 | 14.8 | |
| The berry, 8 × 8 `gfx_masked` | 415 | 416 | 415 | |
| The bar's 13 digits, `font_cells` | 10,243 | 10,295 | 10,366 | 808 (own) |
| The same, sans font (`font_draw`) | 4,928 | 4,784 | 4,724 | |
| The same, C with a table of 16 nibble masks | 857 | 856 | 857 | |
| The walls, `gfx_fill_pat` (130 cells) | 77,412 | 74,933 | 78,445 | 41,197 (walls and lawn, own) |
| The lawn, 950 cell fills | 79,304 | 62,463 | 64,066 | |
| The title screen | 57,962 | 50,257 | 46,026 | 15,361 (10,961) |
| The playfield filled (320 × 216) | 12,936 | 7,439 | 3,400 | 6,553 (2,583) |
| The playfield copied from the empty board | 19,251 | 12,618 | 7,520 | 11,858 (6,710) |
| **A full redraw:** the copy, 29 segments, the berry | 23,790 (143%) | 16,543 (99%) | 11,555 (69%) | 13,433 (8,263) |
| Redrawing the 29 segments | 4,151 | 3,527 | 3,627 | 1,551 |
| **Recolouring** them by redrawing | 4,038 | 3,417 | 3,525 | |
| **Recolouring by the palette:** 16 entries and 3 more | 52 | 52 | 52 | 31 |
| All 256 palette entries (a fade's step) | 296 | 296 | 296 | |
| A line interrupt (entry, dispatch, hook, palette write, return) | 14.9 | 14.9 | 14.9 | |
| The title's 29 a frame | 432 (2.6%) | | | |
| All 480 descriptors (the shake, a frame) | 294 | 294 | 294 | 290 |
| The ripple, 144 descriptors a frame | 1,401 | 1,400 | 1,401 | 238 |
| A banner by descriptors (96 lines) | 64.7 | 64.7 | 64.7 | |
| A banner saved under, copied in, restored | 12,963 | 8,530 | 5,140 | |
| A banner drawn (once per message) | 24,312 | 22,087 | 21,564 | |

- **Incremental drawing makes the game cheap:** 3.5% of a frame in C,
  whatever the kernels. A full redraw doesn't fit in a frame with the C
  kernels, just fits with the assembly ones and takes 69% with the block
  instructions; the incremental step is 30–55 times cheaper.
- **The palette recolours for 1/80 of a redraw** (52 µs against 4 ms for
  29 segments, and the redraw grows with the snake: about 140 µs a
  segment). A whole palette is 296 µs, so fades are cheap too.
- **The descriptors** show a banner for 65 µs against 5–13 ms to save,
  copy and restore what's under it, and the banner is drawn only once.
- **What the variants change:** the game's frame hardly moves (the step's
  small fills are the library's per-call overhead, not its loops); the big
  fills and copies get 1.5–3.8 times faster (FILL most).
- **Text at 8 bits** is the library's C kernel in every variant: 0.79 ms a
  character, so a score update costs 13 ms (the worst frame). A table of
  16 masks, one per nibble of a glyph's row, does the same 12 times
  faster in plain C (`text8` in the measurements).

## What worked well

- **M1 is pleasant.** A pixel is a byte (in L0), a colour is a palette
  index with no banks to think about, and 256 entries leave room for
  every palette trick at once. The 320 × 240 picture costs nothing but
  480 descriptors written once.
- **Palette tricks** replace drawing: the colour wave, the glint, the
  blink and the flash cost about 50 µs a frame together.
- **Descriptors** give overlays, shakes and ripples for the price of
  writing words: 0.6 µs a descriptor in C.
- **The library** draws everything in both layouts with the same calls;
  L1 changed nothing in the pictures or the timings.

## What was hard or didn't work

- **The library's per-call cost** dominates small drawing: 65–83 µs for an
  8 × 8 fill whose 16 words take 17 µs when written directly, 15 µs for a
  pixel. A tile game's step is a few small fills, so the assembly and
  block kernels hardly help it.
- **Text at 8 bits:** see above; this game draws only the digits that
  change, and still spends 80% of a frame on them at every berry.
- **`gfx_fill_pat` at 8 bits** makes one fill job per word (77 ms for the
  130 wall cells); **`gfx_masked`** is C only (415 µs for an 8 × 8 sprite).
- **Line interrupts for raster effects** come in the line before, at the
  descriptor's fetch (character 85), 15 characters (240 ticks, about 30
  cycles) before the line starts; the whole interrupt takes 750 ticks, so
  the handler's palette write lands a few hundred ticks into the line it
  was meant for. The simulator renders a line at its start, so the colour
  changes a line late and cleanly; real hardware would change it
  mid-line (x ≈ 120–250 of 640). For a smooth gradient that's a small step
  on each band's first line.
- **Horizontal movement:** a descriptor's start is a word, 4 pixels (8
  screen pixels) in M1, so the ripple can only move rows up and down.
- **Keeping two programs in step:** drawing the board takes 10 frames in C
  and 2 in assembly, so the game counts time in frames
  (`video_wait`'s count, `rt_frames` for the colours) and starts a fixed
  time after the key, not after the drawing.

## What would have helped

- **An 8-bit `EXPAND` (X1), or the library's 8-bit text through a nibble
  table:** the score's 13 digits from 10.2 ms to about 0.8 ms (the table,
  in C or assembly), likely about 0.2 ms with a microcoded EXPAND. This is
  the one thing that makes the game's worst frame 80% full.
- **Palette banks in the 8-bit modes**, e.g. the line's bank XORed into
  the index's high nibble: per-line colours (skies, water, a bar of its
  own colours) without line interrupts (0.43 ms a frame for 29 bands now,
  and mid-line on hardware). A few XOR gates in the palette's address.
- **A pixel offset in the descriptor** (2 bits at 8 bits a pixel, in the
  open bits 31–24): smooth horizontal ripples and scrolling, which a word
  address can't give.
- **A raster interrupt a line earlier, or a palette write latched to the
  next line's start:** clean per-line colour changes on hardware.
- **For the Neo Geo-like mode:** the grid is a tile map. With 8 × 8 tiles
  a step is three tile indices (head, old head, tail), about 1 µs; the
  colour wave stays a palette rotation; the berry and a smooth-moving head
  would be sprites. The body itself (up to 950 cells) is too long for
  sprites, so a tile layer under the sprites is what such a game needs.

## Issues found

- **The library's 8-bit expansion has no assembly or block kernel**
  (`gfx/asm/expand.s` takes only 8 pixels a word): `digits_font_cells` is
  the same 10.2 ms in all three variants. `font_cells` at 8 bits is
  0.79 ms a character.
- **`gfx_fill_pat` at 4 pixels a word** goes a word at a time through
  `fill_rows` (`walls_fill_pat`: 77 ms for 130 cells). A fill with two
  alternating pattern words a row would do it.
- **`gfx_masked`** has no assembly kernel (415 µs for 8 × 8 at 8 bits).
- **A run whose `main` returns after `@done` ends as "halted"**, not
  "done": `run.py` checks `m.halted` before the `@done` it has just read
  (the test card does this). This program waits after `@done` instead.
- **`heron mini_gfx run` prints every `@perf` value as microseconds**,
  counts too; this program prints counts with `printf`.
- **`video_wait` returns at once if a frame has passed since the last
  call**, so a measurement that starts with one wait after long drawing
  starts mid-frame (documented, but easy to trip over: `idle()` waits
  twice).

## The brief's questions, for the three programs

- **Is M1 pleasant for simple games?** Yes: a byte a pixel, 256 colours
  with no banks, 320 × 240 for 480 descriptors. The costs are its 77 KB a
  screen (a clear is 3.4–12.9 ms, a full redraw doesn't fit a frame in
  C) and the library's slow 8-bit text; a game that draws what changes
  uses 1.4–3.5% of a frame.
- **Palette tricks?** The best value here: a colour wave down the snake
  for 52 µs a frame against 4 ms (and growing) to redraw it, plus glints,
  blinks and flashes for a write each, a full fade step for 296 µs, and a
  29-band gradient from line interrupts for 0.43 ms a frame.
- **The hardware cursor and the descriptors?** C1 moves for 3 µs against
  1.1–6 ms for a software cursor, never flickers, keeps the drawing code
  ignorant of it, and in the two-bit modes has colours no software cursor
  can have ([mines](../mines/NOTES.md)). The descriptors give line
  doubling, overlays for 65 µs (against 5–13 ms with a save-under), shakes,
  ripples, per-line palette banks at 2 bits, and a flicker-free software
  cursor in a band of lines.
- **What did the assembly kernels and block instructions buy?** Little
  for tile games: their drawing is many small calls whose cost is the
  library's per-call work (a step 425 → 368 µs; a tile 172 → 137–139 µs).
  A lot for whole-screen work: FILL 3.8 times, COPY 2.6 times, and only
  with them does a full redraw fit in a frame (69%). Writing the whole game
  in assembly ([snake_asm](../snake_asm/NOTES.md)) gave 2.5 times a frame
  and 3.8 times the board, in two thirds of the code; much of that the C
  gets too by picking the right method (a nibble table for text, direct
  stores for a cell).
- **What was hardest?** Finding where the time went in small drawing (the
  library's overhead, and its missing 8-bit text and masked-sprite
  kernels); the saved-under cursor's hide-and-show discipline; and making
  scripted games of chance reproducible (fixed seeds, time counted in
  frames, scripts computed from a replica of the game).

## Screenshots

`heron mini_gfx run games/snake` writes them to
`build/mini_gfx/shots/games-snake/`:

- **title:** the title, its letters snake segments in the rotating
  colours, the sky gradient from line interrupts (the ripple doesn't show
  in a still).
- **game:** step 200 under the autopilot: the snake 24 long in its colour
  wave, the berry, the bar with the score, length, CPU share and best.
- **paused:** the PAUSED banner shown by 96 descriptors over the board.
- **game_over:** after the crash's shake: the GAME OVER banner, the head
  red against the wall.
