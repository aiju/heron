# RTS: notes

## What it is

A real-time strategy scene: a 96 x 64 tile map in M0 (64 x 40 in M1) of
grass, a river with fords, lakes with shores, forests, rocks and two
halls, made from a seed; 64 units (soldiers, workers walking between hall
and forest, enemy guards on patrol), up to 320 with `+`. Drag to select
(a white rectangle; selected units outlined in yellow, listed in the
HUD), right-click (map or minimap) to send them: a flow field (a
breadth-first search, 200 cells a frame) and a spiral formation. Edge
scrolling, a minimap, Stop/Scatter/Redraw buttons, a status line. All art
is original (rules drawn with the library, 12 x 12 string-art units).

```sh
heron mini_gfx run games/rts                       # M0, asm, session.script; --variant c|blk, --layout L1
heron mini_gfx run games/rts --poke mode=1 --script studies/mini_gfx/games/rts/m1.script
python3 studies/mini_gfx/games/rts/bench.py --write   # results.md: every strategy x variant x mode
```

Keys `1`-`5` pick the redraw strategy, `s` stop, `x` scatter, `+` 32
more soldiers. Pokes: `mode`, `strat`, `nunits`, `bench`.

## How it uses the video

- **D0 descriptors and a world bitmap**: the whole map is drawn once into
  bank 1 (1536 x 1024 x 4, 768 KB; M1 1024 x 640 x 8). The viewport's 400
  descriptors point into it, so scrolling rewrites 400 words (17,000
  ticks, 2 % of a frame) and moves no pixel: by lines vertically, by
  words horizontally (8 screen pixels in both modes), which is free;
  finer would mean shifting the viewport (1.7 M ticks with BLIT k).
- The descriptors also give the **HUD its own palette bank** (bank 1, 16
  colours; the map keeps bank 0's), **M1's doubled lines** with an
  undoubled 96-line HUD, **guard bands** round the full-redraw buffers (no
  clipping code), and **TSEL page flips**.
- **C1**: arrow and target-ring images, switched by one register write,
  moved in the frame interrupt: 60 Hz whatever the game's rate.
- **P1**: the `beam` strategy races it; it counts caught units; timing.
- **B0** suffices for M0 and M1 (no underruns; B1 changes nothing). **L1**
  gives identical pictures and times: sprites are pre-shifted into the
  screen's format at start-up, the kernels move words.
- **Block instructions**: COPY only pays from about 5 words a row (the
  viewport's 80-word rows); erasing (2-4 words) and tiles (2 or 4) are
  faster with plain moves; nothing does masked sprites.

## Implementations and measurements

Five strategies (`render.c`): `dirty` (one world: erase every unit from
a clean copy in bank 0, draw every unit), `beam` (the same in 32-line
bands, top to bottom, racing the beam), `double` (two worlds, TSEL),
`full` (copy the viewport from the clean world, draw units, flip),
`tiles` (build the viewport from the tile map: no world bitmap). Units
bounce round the viewport; units at which the average work fits 1, 2, 4
frames (60/30/15 fps); full tables in `results.md` (its `beam` rows
predate M1's bands becoming 32 screen lines: M1 then caught 16 bands at
64 units, none since):

| Strategy | M0 c | M0 asm | M0 blk | M1 c | M1 asm | M1 blk |
|---|---|---|---|---|---|---|
| dirty | 123/243/489 | 162/324/618 | 162/325/626 | 93/189/390 | 127/259/509 | 127/255/518 |
| beam | 100/204/415 | 130/268/523 | 129/266/520 | 81/168/343 | 107/216/438 | 107/215/437 |
| double | 121/242/494 | 163/323/628 | 163/321/627 | 93/189/380 | 128/255/502 | 128/255/517 |
| full | 0/47/441 | 0/172/663 | 55/300/809 | 22/174/481 | 71/263/664 | 122/324/752 |
| tiles | 0/0/137 | 0/0/470 | 0/0/462 | 0/128/433 | 41/239/591 | 39/236/607 |

Per unit (M0, asm, double, 64 units): sorting and picking sprites (C)
960 ticks, erasing 1,600, drawing 2,225, moving 310: 5,100 (a frame is
840,000). Fixed: 11,500 with a world bitmap; the viewport's background
1.09 M (asm) / 645,000 (COPY) in M0, 522,000 / 310,000 in M1; from tiles
1.73 M (M0), 664,000 (M1). Kernels: a 2-word, 12-row sprite 1,738 ticks
(72 a word), a 2 x 12 copy 1,383, a tile 1,678 (M0).

## What worked well

- The world bitmap behind descriptors: the map costs nothing a frame,
  scrolling 2 %; only units are drawn. `double` holds 160 units at 60
  fps in M0 with no flicker, for 768 KB more of bank 1.
- Racing the beam (`beam`): one world bitmap, no band caught up to about
  130 units (M0 asm), for 20 % more work a unit.
- HUD palette bank, hardware cursor, pre-shifted format-blind kernels.
- M1 halves a full redraw: `full` (blk) holds 60 fps with 122 units.

## What was hard or didn't work

- `dirty` flickers badly: with 160 units the top half of the screen
  showed no units in two frames running (`dirty`, `dirty2`): the beam
  passes between erase and draw. `beam` and `double` fix it.
- A full redraw at 640 x 480 is out of reach (55 units at 60 fps, blk);
  from tiles never 30 fps in M0.
- Bookkeeping in C (sorting by y, choosing sprites) is a fifth of the
  work and survives any sprite hardware.
- LDM/STM copies were 50 % slower than `MOV [r]+` pairs; COPY loses below
  ~5 words a row.
- The C compiler's constant multiplies (below): padding structs to 16/32/64
  bytes cut the frame by 13 %.
- M1's 256 colours went unused (shared art); M1 could do a fog of war by
  one index bit, M0 has no spare bit.

## What would have helped

- **A masked blit** (`d = (d & keep) | image`, rows and pitch in
  microcode): about 30-35 ticks a word against 65-72: a unit's drawing
  from 2,225 to about 1,200 ticks.
- **A 2D COPY** (n words x rows, both pitches): erasing from 1,600 to
  about 800, a tile from 1,678 to about 780; this is the tile instruction
  worth having. With the masked blit, `double` from 163 to about 250 units
  at 60 fps; `tiles` (no world bitmap) at ~0.8 M ticks, 30 fps in M0.
- **Sprites (Neo Geo-like)**: remove 3,800 of 5,100 ticks a unit (~600
  units at 60 fps). An RTS wants ~256 sprites of 16 x 16, 48 a line (a
  marching column of 144 put 35 on one line), a palette per sprite (team
  colour, selection) and an X flip (the 32 pre-rendered pictures, 57 KB,
  become 2), list-order priority; the D0 world bitmap is already the
  right background layer.
- **A pixel offset in the descriptor** (bits 31-24, open): smooth
  scrolling for free. P1 (2 chips) and C1: keep. D0 over D1: D1 loses
  every use above. More bandwidth: nothing here; a copy register (COPY in
  2 cycles) would cut `full`'s background by a third. M2: a 1.5 MB world,
  no double buffer.

## Issues found

1. `build.py`'s object cache ignores headers in a program's folder:
   changing `Sprite` in `rts.h` alone left `art.c`'s object stale and
   `k_sprite` trapped (address error). `bench.py` passes rts.h's hash as
   a define; fix: hash the program's headers.
2. The C compiler multiplies by constants with MULS (`x * 3`; indexing a
   36-byte struct), tens of cycles each.
3. The C library's heap stops at 0xF0000; bank 0's upper MB has no
   allocator (the clean world sits at 0x100000 by hand).
4. `video_wait` after an overrun returns with the beam mid-picture; beam
   racing needs a fresh frame end (`wait_fresh` in `render.c`).
5. RFC 0042: in 4-bit modes the cursor's 253-255 are bank 15's entries
   13-15; worth saying in 7.

## Screenshots

In `build/mini_gfx/shots/games-rts/` after a run: `start` (the hall, units
walking), `drag` (the rectangle), `selected` (yellow outlines, HUD icons,
target cursor), `move` (marching), `scroll` (edge-scrolled), `enemy` (via
the minimap), `dirty`/`dirty2` (160 units: the top half empty in both
frames), `beam`/`beam2` (all shown, one torn band in the first), `full`
(30 fps), `tiles` (21 fps), `double` (60 fps), `march` (144 units round
the lake), `scatter`; `m1_*` the same in M1.
