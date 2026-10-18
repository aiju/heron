# Minesweeper

```sh
heron mini_gfx run games/mines                                   # M0, the hardware cursor
heron mini_gfx run games/mines --poke mode=3                     # M3, 640 x 480 x 2
heron mini_gfx run games/mines --poke mode=5 --script studies/mini_gfx/games/mines/m5.script
heron mini_gfx run games/mines --poke swcursor=1                 # software cursor, saved under
heron mini_gfx run games/mines --poke swcursor=2                 # software cursor in a band of lines
heron mini_gfx run games/mines --poke swcursor=1 --poke fastcur=1   # ... pre-shifted
python3 studies/mini_gfx/games/mines/make_scripts.py             # the scripts again
```

Each runs in the c, asm and blk variants; M5 also with `--poke f1=1`
and `--layout L1`.

## What it is

Minesweeper ([mines.c](mines.c)) with the mouse: left click reveals (a
flood fill opens the areas with no mines around), right click flags, a
left click on a number with all its flags placed opens its other
neighbours, numbers in colours, a bar with a seven-segment mine counter,
a timer and a button (NEW, WON, LOST; a click starts again), keys 1–4 for
the boards (9 × 9, 16 × 16, 30 × 16, and 60 × 40 where it fits). The first
click is always safe: the mines are placed after it, away from it.

The tiles (hidden, open, 1–8, flag, mine, exploded, wrong flag; my own
pixel art) are drawn once with the library into a sheet in the screen's
format; the board is word-aligned, so a tile on the board is a copy of
its words (`gfx_blit`).

The scripts are worked out by [make_scripts.py](make_scripts.py), which
replicates the C's board geometry, random mines and flood fill: it picks
the first click that opens most, flags mines and opens safe cells on the
edge, chords a number, clicks a mine (lost), then wins the beginner's
board, and presses Esc, after which the program measures every cursor
technique and the tiles.

## How it uses the video

- **Modes:** M0 640 × 480 × 4 (16 colours, the default); M3 640 × 480 × 2
  and M5 1024 × 768 × 2 (four greys; M5 with a 60 × 40 board). In the
  two-bit modes the numbers, flags and mines are all black: they differ
  by shape only.
- **Layouts:** L0 and L1 at 4 bits; at 2 bits L0's chunky layout, F1's
  linear one and L1's planes. The library draws all of them; the tiles
  are word copies, so the game's timings are the same in every layout
  (only `gfx_masked` differs, 3.9–4.5 ms at M5).
- **Descriptors:** a plain frame; in the two-bit modes the bar's lines
  take **palette bank 1**, whose colour 3 is red, so the counters are red
  LEDs over a grey board. A bank covers a whole line, so bank 1's colour 0
  has to be the board's background grey (otherwise the bar's lines show a
  coloured band across the screen). And the **band cursor** (below).
- **Cursor (C1):** an arrow, and a probe over the board (a crosshair with
  a yellow centre: all three colours); changing shape is one register
  write. Its position is in the mode's own pixels in M0, M3 and M5, so the
  mouse's coordinates go straight in, less the hotspot.
- **Beam (P1):** the clock, and the test of whether a cursor's update
  overlapped the beam on the cursor's lines.
- **Bandwidth:** M5 runs with **no underruns and no steals at B0** in this
  simulator; B1 and B2 change nothing.
- **Block instructions:** through the library (COPY in the tiles' and the
  band's copies, FILL in the clears).

## Implementations and measurements

Microseconds (a frame is 16,683 µs), M0 with the hardware cursor unless
said; the expert board (480 tiles) and its first click (68 cells).

| Technique | c | asm | blk |
|---|---:|---:|---:|
| A frame's work, average | 499 (3.0%) | 400 (2.4%) | 381 (2.3%) |
| ... the worst (a new board) | 67,960 | 44,511 | 36,528 |
| A tile (16 × 16, 32 words, `gfx_blit`) | 172 | 137 | 139 |
| The expert board, 480 tiles | 80,835 (4.8 frames) | 64,248 | 65,078 |
| The beginner's board, 81 tiles | 13,770 | 10,929 | 11,069 |
| A new expert screen | 137,755 | 99,527 | 90,822 |
| Placing the mines (C's `%` and `/`), 480 cells | 24,983 | 24,989 | 24,978 |
| The same, 2,400 cells (M5) | 122,610 | | 122,669 |
| A click on a number (one tile) | 195 | 160 | 162 |
| The first click's flood fill, 68 cells | 13,130 | 10,754 | 10,872 |
| M5's first flood fill, 180 cells | 31,718 | | 24,132 |
| The timer (three LED digits, 24 fills) | 2,628 | 2,070 | 2,111 |
| M3: a tile; the expert board | 151; 70,338 | | 109; 50,269 |
| M5: a tile; the 60 × 40 board (2,400 tiles) | 151; 352,018 (21 frames) | | 109; 251,293 |

**The cursors,** a frame in which the mouse moves (the measurement at the
end; in brackets, the updates during the game that overlapped the beam on
the cursor's lines, out of about 240):

| Cursor | c | asm | blk | % of a frame |
|---|---:|---:|---:|---:|
| C1: move (two register writes) | 2.9 [1/207] | 2.9 [0/207] | 2.9 [1/207] | 0.02% |
| C1: change shape | 3.9 | 3.9 | 3.9 | |
| Saved under, `gfx_masked`: restore, save, draw | 6,096 [8] | 5,925 [6] | 5,875 [7] | 35–37% |
| ... of which the draw | 5,336 | 5,336 | 5,336 | |
| ... restore; save (40 × 32 pixels, word-aligned copies) | 408; 377 | 323; 292 | 298; 267 | |
| Saved under, pre-shifted | 1,352 [0] | 1,182 [0] | 1,132 [0] | 6.8–8.1% |
| ... of which the draw | 592 | 593 | 593 | |
| Band of lines, `gfx_masked` | 8,206 [39] | 7,513 [13] | 6,760 [8] | 41–49% |
| Band of lines, pre-shifted | 3,470 [0] | 2,778 [0] | 2,024 [1] | 12–21% |
| ... of which the 32 lines' copy (2,560 words) | 2,606 | 1,913 | 1,160 | |

In the game, the frames' average work with a moving software cursor is
3.4–3.7 ms with `gfx_masked` and 1.0–1.2 ms pre-shifted, against
0.4–0.5 ms with C1. In M3 and M5 the software cursors cost a little less
(2 bits: fewer words): 4.5 ms saved under, 1.0–1.1 ms pre-shifted.

## The hardware cursor against a software one

- **Cost:** C1 is 3 µs a move; a software cursor drawn the way the
  library draws sprites is 6 ms (more than a third of a frame), 1.1–1.4 ms
  pre-shifted. A software cursor also costs something every time anything
  is drawn: with the saved-under one, the cursor has to come off first
  (265–408 µs) and go back on.
- **Complexity:** C1 is a 32 × 32 image made once and two register writes.
  Saved under is about 40 lines, but invasive: every drawing anywhere in
  the program must call `begin_draw()` first, or the saved rectangle goes
  stale and the cursor leaves a trail or erases what was drawn. The band is
  about 35 lines and not invasive (draw anywhere, any time), but needs two
  32-line buffers (2 × 10 KB in M0), each line's normal descriptor kept
  (with its palette bank), and a copy of 32 whole lines per update.
- **Flicker and tearing:** a saved-under cursor is missing from the
  screen between restore and draw; with `gfx_masked` the update took long
  enough for the beam to cross the cursor's lines in 3% of updates (a
  flickering frame). The band never flickers: the cursor is always drawn,
  in the buffer not shown, and only the descriptor switch can be caught
  by the beam (a cursor split between two positions for a frame). Done
  quickly (pre-shifted) both stayed clear of the beam. C1 can split too
  if moved while the beam is on its lines (its registers are read line by
  line); it happened once in about 200 moves, at the end of a frame's
  work; moving it right after `video_wait` would avoid it.
- **Colours:** three and transparent are enough for a pointer (black
  outline, white, a yellow accent) and for the probe; a coloured icon
  (a flag in its colours, say) would want more. They are palette entries
  253–255: in M0 bank 15's last three, so a program has 15 banks to itself;
  at 2 and 1 bits no pixel reaches them; at 8 bits they are the top three
  pixel values. In the two-bit modes C1 is better than a software cursor
  in another way: it has its own colours, while a software cursor has only
  the line's four (no yellow in M3).

## What worked well

- **Tiles as word copies:** with the board aligned to words, any layout and
  depth costs the same and the library's copies need no shifting.
- **C1:** nearly free, flicker-free, and it keeps the drawing code
  ignorant of the pointer. Changing its shape with the context (arrow,
  probe) is one register write.
- **The band cursor** is a good use of the descriptors: a software cursor
  with no save-under protocol and no flicker.
- **Palette banks in the two-bit modes:** red counters on a grey board
  for nothing, from the bar's descriptors.
- **Four colours** still make a readable Minesweeper (M3, M5): bevels in
  three greys, black numbers.

## What was hard or didn't work

- **The library's per-call cost:** a 32-word tile copy takes 109–172 µs
  (the words alone would be about 10 µs), so the expert board is 4–5
  frames to draw, M5's 2,400 tiles 15–21 frames, and a 180-cell flood
  fill 1.5–2 frames. COPY hardly helps a copy two words wide; the
  per-row overhead dominates.
- **`gfx_masked` is C only** (5.3 ms for a 32 × 32 cursor in every
  variant), so the first software cursors were a third of a frame; the
  pre-shifted one (my own, in this program) is 9 times faster.
- **Division:** the first click on M5's board takes 123 ms placing the
  mines, mostly `c % cols` and `c / cols` (each a microcoded divide); a
  game written for this machine keeps x and y apart.
- **Colours at two bits:** the numbers can't be coloured (the palette bank
  is per line, the board's numbers vary along it).
- **Scripting a game of chance:** the scripts had to be computed from a
  replica of the C's random mines and flood fill.

## What would have helped

- **A tile (character) mode**, or the Neo Geo-like mode's fixed layer: a
  16 × 16 tile map over a tile sheet would make a board a matter of
  writing 480 (or 2,400) bytes: about 0.2–1 ms in assembly in place of
  65–81 ms (or 250–350 ms at M5), and a flood fill a byte a cell. With C1 (or one
  sprite) for the pointer, a game like this would need no drawing at all.
- **A rectangle COPY** (rows of n words with source and destination
  pitches, in microcode): a tile copy from about 140 µs to about 15 µs,
  the expert board from 65 ms to about 7 ms; the saved-under cursor's
  restore and save from 300 µs to about 30 µs each.
- **A masked BLIT (X1)**, or a masked kernel in the library: the software
  cursor's draw from 5.3 ms to the pre-shifted 0.6 ms or less.
- **Keep C1.** At 12–14 chips it saves 1–6 ms of CPU a frame whenever the
  mouse moves, removes the invasive hide/show code, and in the two-bit
  modes it's the only way to have a pointer in colours of its own. A
  16 × 16 one (about 8 chips) would do for these pointers.
- **A colour per 16-pixel column at two bits** (RFC 0042, 11's "a bank
  per 8-pixel column"): coloured numbers in M3 and M5.

## Issues found

- **`gfx_masked` has no assembly or block kernel:** `sw_draw_masked` is
  5,336 µs in all three variants (32 × 32 at 4 bits).
- **Narrow copies are dominated by per-row setup** even with COPY: a
  40 × 32-pixel restore (5 words × 32 rows) is 298 µs in blk, 408 µs in c.
- **C1's position is read line by line** (the simulator renders a line
  from "the registers as they are then"), so a move while the beam is on
  the cursor's lines splits it for a frame. RFC 0042, 7 could say whether
  the hardware latches the position once a frame (it would cost a
  register pair) or programs should move it in the blanking.
- **C1's colours, entries 253–255, are bank 15's colours 13–15 in M0** and
  the top three pixel values at 8 bits; RFC 0042, 7 doesn't say so, and a
  program using bank 15 (or those values) shares them with the cursor.
- **M5 shows no underruns at B0** in the simulator, while RFC 0042, 9 says
  M5 wants B1; the model's cycles (at most 9 ticks) keep up, so the
  question is the hardware's margin, as the RFC says.

## Screenshots

`heron mini_gfx run games/mines` writes them to
`build/mini_gfx/shots/games-mines/` (the same names in every mode and
cursor):

- **opened:** the expert board after the first click's flood fill (68
  cells), the probe cursor.
- **playing:** after six flags, eight safe cells and a chord: numbers in
  colours, flags, the counter at 93, the timer running.
- **lost:** a mine clicked: every mine shown, the exploded one on red, the
  button LOST, the timer stopped.
- **won:** the beginner's board won: the remaining mines flagged, the
  counter at 0, the button WON.

With `--poke mode=3` the same in four greys with red counters (bank 1);
with `mode=5` and `m5.script`, the 60 × 40 board (its first click opens
180 cells) in 1024 × 768. With `swcursor=1` or `2` the cursor in the
pictures is the software one (the same shapes; its yellow drawn red).
