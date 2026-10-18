# Heron Bricks: a brick breaker

## What it is

A small brick breaker in M1 used as 320 × 240 × 8: a title screen with
bouncing balls, two levels (13 × 8 bricks; steel bricks take two hits,
gold ones drop a capsule that gives two more balls), a paddle on the
arrow keys or the mouse, particles from every broken brick, a score, and
a game-over screen with fireworks. A turns on an autopilot (the paddle
follows the lowest falling ball, hitting it off-centre), Esc gives up.
The art, names and levels are the program's own.

It's built the way [demos/bobs](../../demos/bobs/NOTES.md) found
fastest, and draws only what moves:

- the backdrop and the bricks are a background buffer, drawn once; a
  broken brick is copied out of it (from a backdrop without bricks) and
  its rectangle restored in each screen buffer the next time that buffer
  is drawn;
- the ball, the paddle and the capsules are bobs' compiled sprites with
  byte stores (`sprite.c`, `jit.c` and `draw.s` from demos/bobs, built
  from there), erased by their compiled restores; two buffers flipped
  with TSEL;
- the particles are 2 × 2 pixels, two half-word stores each, erased by
  two half-word copies from the background.

```sh
heron mini_gfx run games/breakout                       # the script: title, a game, game over
heron mini_gfx run games/breakout --poke burst=160      # 160 particles a brick
heron mini_gfx run games/breakout -D SLOW_FRAMES=60000  # print the frames that take longer
```

## How it uses the video

- **M1, lines doubled** by the descriptors (320 × 240 × 8), in L0 (L1
  works too, more slowly: below).
- **Line descriptors (D0):**
  - guard bands of 32 pixels and rows round each buffer (96 words a row),
    so sprites never clip;
  - **the status line** (score, level, lives) is a buffer of its own on
    the top 16 rows, through its own descriptors in both tables: never
    erased, never in the sprites' way, redrawn only where it changes;
  - **the wobble:** when a capsule is caught or a level cleared, each
    picture line's start moves by a wave of up to ±3 words for 40 frames
    (the descriptors of the buffer about to be shown, rewritten in the
    blank): the picture ripples sideways, in steps of a word (4 pixels).
- **TSEL** flips the two buffers.
- **The palette (256 entries):** the stars twinkle (8 entries) and the
  title's letters run through the colours (16 entries) by cycling, 25
  writes a frame and no pixels; the status line's AUTO is shown or hidden
  by setting its entry's colour; blinking text the same way.
- **The beam (P1)** times everything (`video_ticks`).
- **Block instructions:** `COPY` through the library's `gfx_blit` (the
  brick rectangles, the scene changes) in the blk variant; nothing else
  needs them.
- No cursor (the mouse moves the paddle), B0.

## Implementations and measurements

The scripted game (autopilot for 900 frames, then the mouse, then Esc):
work a frame, from after the flip to before the next, ticks of 19.86 ns
(a frame is 840,000):

| Variant, layout | Erase | Logic | Draw | A frame | % of a frame | Worst frame | Missed |
|---|---:|---:|---:|---:|---:|---:|---:|
| blk, L0 | 6,620 | 10,129 | 7,116 | 25,266 | 3.0 % | 105,344 | 0 |
| asm, L0 | 7,372 | 12,419 | 8,122 | 29,314 | 3.5 % | 107,040 | 0 |
| c, L0 | 7,865 | 14,025 | 8,701 | 31,993 | 3.8 % | 113,008 | 0 |
| blk, L1 | 6,559 | 10,143 | 9,183 | 27,287 | 3.2 % | 113,248 | 0 |

(about 9–14 particles and 1–3 balls on average; the variants play
slightly different games, as the autopilot's aim depends on the frame
count when the game starts.) The variant only changes the library's
kernels (the brick rectangles, the scene changes); the sprites are the
same machine code in all three.

The costs of the pieces (blk, L0):

| What | Ticks |
|---|---:|
| a brick broken: out of the background (`gfx_blit`, 24 × 10) | 6,700 |
| its 12 particles made | 5,500 |
| the status line's changed digits | 6,900 |
| its rectangle restored in each screen buffer, a frame later | 7,000 each |
| a particle, a frame: moved (C), drawn, erased | about 755 (470, 190, 100) |
| the palette's cycling, a frame (in the blank) | 5,100 |
| the wobble's descriptors, a frame (448 words, in the blank) | 28,800 |
| the status line with the library's text (the first version) | 559,000 |

With more particles (blk): 48 a brick, 38 on average and 188 at most:
47,300 ticks a frame (5.6 %), the worst 206,000; 160 a brick, 128 on
average and 628 at most: 115,300 (13.7 %), the worst 539,000 (64 %),
still without a missed frame. In L1 the particles cost more to draw
(48 a brick: 18,412 ticks a frame drawing against 12,592 in L0).

## What worked well

- **Bobs' techniques carried straight over:** the whole game is 3 % of a
  frame; the CPU is in `HALT` about 90 % of the time (`--profile`).
- **Drawing only what moves**, with the bricks in the background: a
  broken brick is three small copies (into the background, then into
  each buffer when it's next drawn), not a redraw.
- **The status line through its own descriptors** is the cheapest
  overlay there is: no erase, no clipping, no redraw but its digits.
- **Palette tricks** animate at no cost in pixels: twinkling stars, the
  rainbow title, blinking text, AUTO shown or hidden.
- **The descriptor wobble** is a striking effect for 3.4 % of a frame.
- **Byte pixels (L0's 8 bits):** a particle is two half-word stores, and
  the sprites' edges byte stores.

## What was hard or didn't work

- **Text through the library is far too slow at 8 bits:** the first
  status line (two `font_draw` calls, 37 glyphs) took 559,000 ticks, two
  thirds of a frame, at every brick: about 15,000 ticks a glyph. The
  digits are now rendered once at start-up into 8 × 16 cells and copied
  as words (two a row), and only the digits that change.
- **Arithmetic is costly in game code:** a multiply or divide is a
  microcoded loop of tens of cycles, a constant shift up to 10 cycles.
  Particles first cost 1,600 ticks each to make (a multiply by the
  structure's size in `&part[npart++]`, a divide in the random numbers,
  three shifts in xorshift); now a table of random numbers made at
  start-up and a moving pointer: 455. The score is kept as decimal
  digits (no divides to show it); the palette cycling and the wobble
  read tables made at start-up (the wobble first cost 96,000 ticks a
  frame with a multiply and a divide a line).
- **Word-sized descriptor steps:** the wobble moves lines by 4 pixels at
  a time; finer would need a pixel offset in the descriptor.
- **L1:** the particles' half-word stores and the sprites' byte stores
  need a pixel to be a byte; in L1 the particles are read-modify-writes
  with a pair's mask and the sprites lose the byte stores (draw 29 % more
  at the default particles, 46 % at 48 a brick).
- **The pending rectangles** for a broken brick go through `gfx_blit`
  (7,000 ticks for 24 × 10 pixels): the library's set-up is most of it.

## What would have helped

- **A glyph cache or an 8-bit `EXPAND`** (X1): text at 8 bits a pixel is
  the one thing the game can't afford; 15,000 ticks a glyph against
  about 1,500 for a copied 8 × 16 digit cell.
- **A pixel offset in the descriptor** (RFC 0042's "Later"): smooth
  sideways wobbles and scrolls instead of 4-pixel steps.
- **A cheaper multiply and divide**, or a compiler that avoids them
  (pointer walks instead of index multiplies): the game's logic, not its
  graphics, is now its largest part (10,000 of 25,000 ticks a frame).
- **For a bigger game,** the sprite mode bobs describes: this one has at
  most a dozen objects and could have hundreds of particles before it
  ran out of frame (with 160 a brick, up to 628 alive, its worst frame
  was 64 % of one).

## Issues found

1. **`font_draw` at 8 bits a pixel costs about 15,000 ticks a glyph** (a
   status line of 37 glyphs: 559,000 ticks). Reproduce: time
   `font_draw(&s, font_sans, 4, 12, "SCORE 000000", c, -1)` on an M1
   surface. Also in bobs' notes.
2. **The library has no `video_lines` for doubled lines** (M1 as
   320 × 240): programs call it once a line (the test card too), about
   500 ticks a call; a tight loop is 50 ticks a line. Not a bug; worth an
   argument for the line's repeat.
3. **A missed frame after a scene change:** `video_wait` counts the
   frames since it was last called, so the first flip after a long
   set-up (a level's `present`, 840,000 ticks) reports the set-up's
   frames as missed; calling `video_wait()` once after the set-up
   clears it. Not a bug, but easy to trip over when measuring.
4. Nothing wrong was found in the simulator or RFC 0042.

## Screenshots

`heron mini_gfx run games/breakout` writes them to
`build/mini_gfx/shots/games-breakout/`; the program takes them itself,
at the events:

| Shot | What it shows |
|---|---|
| `title` | the title: big letters drawn from `font_sans` three to five times over, coloured by rows whose palette entries cycle; three balls bouncing behind |
| `play` | 300 frames into the game: the bricks, the ball, the paddle, a broken brick's particles, the status line with AUTO lit |
| `multiball` | ten frames after a capsule is caught: three balls, and the picture wobbling (each line's start moved by the descriptors; the guard band shows at the edges) |
| `gameover` | the game-over panel over the field, the final score, particles bursting |
