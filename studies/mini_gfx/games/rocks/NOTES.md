# Shards (games/rocks): notes

## What it is

A vector game drawn only with lines. A dart-shaped ship turns, thrusts and
fires. Jagged shards drift, spin and split in two. A hexagonal warden
crosses the screen and fires back. The score, the lives and a load meter
(the last frame's work against a frame) are vector strokes too. Files:
`rocks.c` (the game and its benchmarks), `vec.c`/`vec.h` (the vector
layer and the C line kernel), `vline.s` (the assembly line and polyline
kernel, and the box clear). Pokes: `mode` (6, 5, 4, 3, 0), `f1`,
`erase` (0 FILL, 1 redraw cleared, 2 XOR, 3 boxes with the library's fill,
4 boxes widened to words and cleared by stores, the default), `kernel`
(0 library, 1 C, 2 asm), `rocks`, `autopilot` (deterministic, frames
counted in game frames, for measuring), `hwship`, `bench=1` (lines and
fills in every mode and format, and a check of the kernels against
`gfx_line`), `bench=3` (cost by direction).

## How it uses the video

- **Modes:** M6 and M5, also M4, M3 and M0 at 5/8 scale (the same world).
- **Descriptors (D0):** two tables, and a page flip by `TSEL` at the
  frame's end. Each row starts anywhere, so a buffer's rows are 2–8 words
  wider than the picture. That makes a **guard band**: lines need no
  clipping, and a wrapped object is drawn twice (the band must be twice
  the largest radius). With D1 the rows would be contiguous and x would
  need clipping.
- **Palette banks per line:** the shards' colour shades through 12
  bands, and the score band is amber. This gives colour even in 1 bit.
- **Cursor (C1):** with `hwship=1` the ship is the cursor: 64 headings
  drawn once with `gfx_line` into 32×32 2-bit images (PF_LIN2), so the
  ship costs nothing a frame.
- **Bandwidth:** M5 with B0, B1 and B2 shows 0 underruns and 0 steals in
  every run, FILL included. The cycles are at most 11 ticks, against a
  word needed every 12.4 ticks.
- **Blocks:** FILL is used for the full-screen erase in the blk variant.
  No block instruction draws lines.

## Implementations and measurements

**Lines** (ticks a line, 32 px at random angles, M6/M5; `bench=1`):

| Kernel | c variant | asm/blk | lines/frame |
|---|---:|---:|---:|
| library `gfx_line` | 9,910 | 8,130 | 84–103 |
| ours in C, a call a line | 3,385 | 3,385 | 247 |
| ours in asm, a call a line | – | 3,338 | 251 |
| ours in asm, a polyline | – | 3,128 | 268 |

Each line costs about 960 ticks to set up, then each pixel costs 48
(horizontal), 74 (vertical) or about 102 (diagonal). The per-pixel mask
comes from a table, so **every layout costs exactly the same**: CHK1,
LIN1 (F1 or L1), CHK2, LIN2 and PL2 match to the tick. The kernels'
pixels match `gfx_line` in every format (checked).

**Clearing M6 / M5** (ticks): FILL of the picture as one span: c 948K /
1.89M, asm 518K / 1.03M, blk 206K / 407K. With a fill per row, blk takes
345K in M6. A 94-px box: library fill 22.9K, widened to words and stored
8.8K.

**The game** (autopilot, the same 600 frames, about 158 lines a frame;
ticks a frame; 840K is a frame):

| Mode | Erase | c | asm | blk |
|---|---|---:|---:|---:|
| M6 | FILL | 1.39M (36 fps) | 939K (53) | 622K (60) |
| M6 | redraw / XOR | 845K (57) | 805–817K (58) | = asm |
| M6 | boxes (library) | 758K (60) | 643K (60) | 657K (60) |
| M6 | word boxes | 587K (60) | **500K (60)** | = asm |
| M5 | FILL | 2.34M (21) | 1.46M (34) | 831K (59) |
| M5 | word boxes | 646K (60) | **526K (60)** | = asm |
| M4 / M3 / M0 | word boxes | – | 421K / 433K / 456K | – |
| M6 | library lines, FILL | 2.24M (22) | 1.68M (30) | – |

Drawing alone is about 400K in M6. At 640×480 it is still about 350K:
the per-line setup dominates, so the smaller modes save little. Under
stress (asm, word boxes) the game drops to 47 fps at 335 lines a frame
and to 33 fps at 460. At 60 Hz the limit is about 250 shard edges a
frame.

## What worked well

- Gathering a word's pixels in a register, with masks from a table: 2.5×
  the library, and the same speed in every layout.
- The guard band from D0 (no clipping), and recording polylines rather
  than lines.
- Widening the boxes to whole words and clearing them with an unrolled
  run of CLRs. Everything is redrawn anyway, so over-clearing does no
  harm. This was the best erase in every mode.
- Packed object arrays walked by pointers. `update` went from 135K to
  21K ticks: the compiler multiplies by a 36-byte stride (MULS, about 160
  ticks) on every pass of an indexed loop.
- Compiled C is within 5% of the assembly for these loops.

## What was hard or didn't work

- FILL in M5 takes half a frame even with blk, and C or asm can't clear
  M5 at all (1–2 M ticks).
- FILL a row at a time is 1.7× slower than one long span; for narrow
  boxes, blk is slower than asm.
- A multiply costs about 160 ticks, so the shards' 64 rotations are
  computed in advance.
- XOR erasing leaves holes where lines cross. It needs half-open lines,
  so a closed polyline's corners aren't drawn twice (vec_half).

## What would have helped

- **A LINE block instruction** (a Bresenham inner loop with a mask table
  like EXPAND's, or a rotate for linear formats): estimated at about 3
  cycles a pixel gathered and 5 for each RMW, which is 20–32 ticks
  against 48–74. With setup in microcode, a 32-px line takes about 1.1K
  ticks against 3.1K, roughly 3× (about 800 lines a frame). Linear 1- and
  2-bit layouts make its mask step a rotate.
- **A 2-D FILL** (rows, words and pitch): the box erase is per-row
  overhead (about 230 of the 265 ticks a row). Estimated 4–6× on boxes.
- **XOR FILL:** about 3 cycles a word (20 ticks) against 43 in asm. This
  helps flashes and XOR-filled shapes, not this game's erase.
- **X1's bit-BLIT:** it would let small shards be pre-drawn sprites,
  estimated 2–3× cheaper than their 11 lines.
- **F1 or L1:** worth nothing for table-driven lines. A rotate step would
  save at most about 7% on steep lines.
- **M5/M6:** a 1-bit XGA picture costs the same per line as VGA; only
  clearing grows. Vector games run fine at 60 Hz with word-box erase, so
  the XGA modes are usable for this software, but they don't need B1.

## Issues found

- `build.py`'s object cache writes a fixed `.tmp` name, so two runs
  compiling the same file at once fail (FileNotFoundError). Seen running
  four configurations in parallel.
- `gfx_line`'s setup always divides and multiplies (`mn = (2 t0 dy + dx)
  / 2dx`, even when t0 = 0), about 4.5K ticks a line.
- `fill_rows_blk` falls back to asm only below 2 words. For rows of 3–8
  words FILL's setup makes it slower than asm (box94: blk 24.9K, asm
  21.9K).
- Not a bug: a guard band for wrapped objects must be 2× the radius. My
  first try at 1× overwrote low memory.

## Screenshots

`heron mini_gfx run games/rocks` writes these to
`build/mini_gfx/shots/games-rocks/`: `play1` (the first wave and a stream
of shots), `play2` (shards splitting, debris), `play3` (later, with the
banded colours). With `--poke mode=5` the shards, ship and warden are in
three colours. With `--poke hwship=1` the ship is the hardware cursor.
