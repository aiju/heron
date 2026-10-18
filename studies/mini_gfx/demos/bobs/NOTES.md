# Bobs: software sprites

## What it is

A benchmark of software sprites ("bobs", blitter objects): how many
masked sprites of 16 × 16 and 32 × 32 can be erased, moved and drawn
every frame over a busy background, at 60 Hz and at 30 Hz, in M1 used as
320 × 240 × 8 and in M0 (640 × 480 × 4), by each way of drawing and of
erasing them, in the c, asm and blk variants and both layouts. Four
designs of each size: a shaded ball, a ring (transparent in its middle),
a cut gem and a critter, all drawn in code (`art.c`).

For each configuration the program runs 24 bobs (6 for the slowest) for
four frames, measuring what a bob costs to erase, move and draw and what
a frame costs without them, predicts how many fit a frame at 60 and at
30 Hz, and checks the 60 Hz prediction by running that many for ten
frames, taking 6 % off until no frame is missed. At start-up it checks
every fast kind of drawing against the library's `gfx_masked`, every
sprite at every phase, word for word (0 words differ in every variant,
mode and layout).

```sh
heron mini_gfx run demos/bobs                       # M1, blk: the table's lines, the screenshots
heron mini_gfx run demos/bobs --poke mode_sel=0     # M0
heron mini_gfx run demos/bobs --poke showcase=1     # only the screenshots' scenes
python3 studies/mini_gfx/demos/bobs/bench.py --write   # every variant, mode and layout: results.md
```

The drawing (`sprite.h` has the details):

| Kind | What |
|---|---|
| generic | the library's `gfx_masked`: any phase, any format, clipped |
| shifted | pre-shifted: each phase's rows as whole words, pairs of (~mask, image); every word `d = (d & ~mask) \| image` |
| spans | pre-shifted, a row a header (its first word, then counts of masked, opaque, masked words): transparent words skipped, opaque ones stored without reading the screen; blk: `COPY` for opaque runs of 3 words or more |
| compiled | machine code made at start-up from the pre-shifted rows (`jit.c`): a store for an opaque word, load, AND, OR, store for a masked one, nothing for a transparent one; the ten constants used most in registers |
| bytes | compiled, with byte and half stores for edge words whose pixels are whole bytes (8 bits in L0): no read at all |

The erasing:

| Erase | What |
|---|---|
| full | the whole picture copied from the background (the library's `gfx_blit`: `COPY` in blk) |
| dirty | each sprite's rectangle of words copied from the background |
| save | each rectangle saved before the sprite is drawn, put back the next time (save-under), the last first |
| exact | compiled (`jit_restore`): exactly the words the sprite drew, copied from the background, no per-row set-up |

Pre-shifting is done once with the library (`gfx_masked` and
`gfx_expand` into a cleared surface at each phase, the mask expanded in
the colour whose bits are all set), so it works in every pixel format;
after that, drawing is the same word operations whatever the layout.

## How it uses the video

- **M1 as 320 × 240 × 8** (two descriptors a buffer row) and **M0**, a
  poke picks. The picture's format is the library's (`PF_LIN8` in L0,
  `PF_PL8` in L1; `PF_LIN4`, `PF_PL4`).
- **Line descriptors (D0)** for three things a frame base can't do:
  - **guard bands:** the buffers are 96 words a row (M1; 88 in M0) and 304
    rows, the picture 80 words of it from word 8 and row 32, so a sprite
    hangs off any edge with no clipping: the bobs go half off the
    picture, and no kind of drawing but the generic one clips;
  - **a status line** from a buffer of its own on the top 16 rows (32
    lines), through its own descriptors in both tables: the bobs never
    avoid it, erase it or redraw it;
  - **the doubled lines** of 320 × 240.
- **TSEL** for double buffering: a page flip is one write of the control
  register. Rewriting the picture's descriptors instead (a tight loop, a
  word a line) takes 23,600 ticks in M1 and 44,000 in M0, 2.8 % and 5.2 %
  of a frame.
- **The beam (P1)** through `video_ticks()`, for every measurement.
- **Block instructions (X0):** `COPY` for the full redraw (through the
  library), for the rectangles' rows (dirty, save) and for long opaque
  runs in spans; `FILL`, `EXPAND` and `BLIT` aren't used: nothing here is
  a fill, a 1-bit expansion or an unmasked shifted copy.
- **Bandwidth:** B0 throughout; no steals and no underruns, as M0 and M1
  are within B0's slots whatever the CPU does.
- No palette banks (M1 has none; M0 uses bank 0), no cursor.

## Implementations and measurements

Ticks are 19.86 ns; a frame is 840,000. [results.md](results.md) has
every table (`bench.py`); these are its main lines.

**Bobs a frame** in M1 (320 × 240 × 8, L0): *n / m* is the number run at
60 Hz without missing a frame / the number predicted at 30 Hz (the
program stops at 512).

| Drawing | Erase | 16 c | 16 asm | 16 blk | 32 c | 32 asm | 32 blk |
|---|---|---:|---:|---:|---:|---:|---:|
| generic | dirty | 7 / 14 | 7 / 14 | 7 / 14 | 2 / 4 | 2 / 4 | 2 / 4 |
| shifted | dirty | 70 / 141 | 73 / 148 | 84 / 170 | 21 / 44 | 22 / 45 | 27 / 55 |
| spans | dirty | 72 / 146 | 77 / 155 | 87 / 175 | 25 / 51 | 26 / 52 | 36 / 72 |
| spans | exact | 93 / 187 | 99 / 201 | 97 / 197 | 34 / 70 | 36 / 73 | 40 / 80 |
| compiled | full | 0 / 198 | 50 / 332 | 136 / 419 | 0 / 86 | 21 / 144 | 59 / 181 |
| compiled | dirty | 110 / 222 | 110 / 222 | 136 / 274 | 38 / 77 | 37 / 74 | 53 / 108 |
| compiled | save | 67 / 135 | 73 / 148 | 93 / 188 | 21 / 43 | 23 / 48 | 35 / 71 |
| compiled | exact | 164 / 332 | 165 / 332 | 165 / 332 | 62 / 126 | 62 / 126 | 62 / 126 |
| bytes | full | 0 / 248 | 62 / 415 | **170 / 512** | 0 / 105 | 26 / 176 | **72 / 222** |
| bytes | exact | **187 / 377** | **187 / 377** | **187 / 377** | 69 / 139 | 69 / 139 | 69 / 139 |

In M0 (640 × 480 × 4, L0), the best: compiled with exact restores, 208
bobs of 16 × 16 and 89 of 32 × 32 at 60 Hz in every variant (419 and 180
at 30 Hz); the full redraw can't run at 60 Hz in any variant (the screen
is 38,400 words: 838,700 ticks with `COPY`), and gives 331 bobs of
16 × 16 at 30 Hz with blk.

**Where the time goes**, M1, blk, ticks a bob (the full redraw is a
frame's 421,000 ticks, half of it, whatever the number of bobs):

| Drawing | Erase | Size | Draw | Erase | Save | Move | A bob | % of a frame for 32 bobs |
|---|---|---|---:|---:|---:|---:|---:|---:|
| generic | dirty | 16 | 111,242 | 3,223 | | 984 | 115,449 | 440 % |
| shifted | dirty | 16 | 5,924 | 3,095 | | 783 | 9,802 | 37 % |
| spans | dirty | 16 | 5,617 | 3,095 | | 792 | 9,504 | 36 % |
| spans | save | 16 | 5,617 | 2,890 | 2,976 | 798 | 12,281 | 47 % |
| compiled | dirty | 16 | 2,227 | 3,096 | | 746 | 6,069 | 23 % |
| compiled | exact | 16 | 2,227 | 2,027 | | 758 | 5,012 | 19 % |
| bytes | exact | 16 | 1,611 | 2,028 | | 781 | 4,420 | 17 % |
| bytes | full | 16 | 1,611 | (421,252) | | 769 | 2,380 | 59 % |
| compiled | exact | 32 | 6,116 | 6,291 | | 758 | 13,165 | 50 % |
| bytes | exact | 32 | 4,843 | 6,291 | | 781 | 11,915 | 45 % |

Per variant, the kinds written in each differ only in their kernels:
compiled and bytes are machine code in every variant, so only the erase
changes. The dirty rectangles' restore of a 16 × 16 bob in M1 is 4,526
ticks in C, 4,508 in assembly and 3,096 with `COPY` a row; the full
redraw 1,077,000, 679,000 and 421,000 (C can't redraw M1 at 60 Hz at all).

**The inner loops**, ticks a word, measured on straight-line code:

| Sequence | Ticks a word |
|---|---:|
| masked: `MOV r0,[r1]`; `AND r0,[r2]+`; `OR r0,[r2]+`; `MOV [r1]+,r0` | 50.8 |
| masked, mask and image in registers | 38.8 |
| masked, mask and image as 32-bit constants in the instructions | 56.8 |
| opaque: `MOV [r1]+,rK` | 19.8 |
| opaque, the constant in the instruction | 34.8 |
| a byte or half store with a displacement, beside an ALU instruction | 12–13 |
| two byte stores (an edge word with two opaque pixels) | 31.8 |
| copy: `MOV r0,[r2]+`; `MOV [r1]+,r0` | 31.8 |
| copy with `LDM`/`STM` of four registers | 54.7 |
| `COPY` | 19.3, and about 100 a row of set-up |

**Layouts.** L1 against L0 (blk, a bob, ticks): spans the same, compiled
1.6 % more in M1 (5,092 against 5,012, other mask constants), bytes
impossible (an 8-bit pixel in L1 is spread over its word): 162 bobs of
16 × 16 at 60 Hz in L1 against 187 in L0. M0: 202 against 208.

**Single buffer.** Drawn at once after the frame's end with one buffer,
the bobs must be done in the vertical blank (45 lines, 72,000 ticks): 16
bobs of 16 × 16 (bytes, exact), against 187 double-buffered. Drawing 187
with one buffer, the beam overtakes the work: the top half's bobs are
erased or half drawn (`m1_single`).

**Set-up:** making the 8 sprites in every form and phase takes 59 million
ticks (1.2 s; the library's pre-shifting and the compiler); their code
is 78,760 bytes in M1 (plain, byte-store and restore code, 4 phases each)
and 81,648 in M0 (8 phases), the pre-shifted rows 45,568 and 51,712.

## What worked well

- **Pre-shifting takes the format out of drawing.** With every phase's
  rows as (~mask, image) words, the inner loop is the same in all nine
  formats; the layouts cost nothing (spans: identical in L0 and L1). The
  library made the pre-shifting easy: `gfx_masked` and `gfx_expand` into
  a cleared surface, the mask in the all-ones colour.
- **Compiled sprites: 2.5 × faster than the pre-shifted loops** (2,227
  against 5,617 ticks a 16 × 16 bob in M1). On this machine instruction
  fetches and data loads share the memory, so a constant in the
  instruction stream costs about what loading it would; the gain is no
  loop, no per-row headers, nothing for transparent words, a store
  without a read for opaque ones, and registers for the constants used
  most. The compiler is under 300 lines of C, the encodings from RFC 0028
  (checked against the assembler's).
- **Byte stores (8 bits, L0):** a pixel is a byte, so an edge word whose
  opaque pixels are whole bytes is one or two narrow stores and never
  read: drawing 28 % faster (1,611 against 2,227).
- **The exact restore** (compiled: only the words drawn, no per-row
  set-up) beat `COPY` a row for small sprites (2,028 against 3,096 a
  16 × 16 bob) and is the same in every variant.
- **Choosing the erase by the numbers:** at 60 Hz the exact restore wins
  for 16 × 16; at 30 Hz, or with 32 × 32 bobs in M1, the full redraw with
  `COPY` (half a frame, whatever the count) wins; save-under is always
  the worst (two copies a bob), only for when there is no background
  copy.
- **Predicting from a few bobs:** the per-bob costs are linear, and every
  prediction ran without missing a frame.
- **Guard bands and a status line through the descriptors** made the
  clipping and the overlay problems disappear for nothing.

## What was hard or didn't work

- **The library's sprites are far too slow:** `gfx_masked` costs 111,000
  ticks for a 16 × 16 sprite in M1 (about 1,460 a word), 7 bobs a frame.
  It's generic C: per word it shifts through the format's terms, looks up
  the 1-bit mask's expansion tables and tests the edges.
- **The erase is now most of the work:** 46 % of a bob's time with exact
  restores, half a frame for a full redraw in M1, more than a frame in M0
  (M0's full redraw can't run at 60 Hz in any variant).
- **`COPY`'s set-up** (about 100 ticks a row, with the latch-clearing
  `MOV`/`CLZ` and the pointer steps) eats its gain on sprite-sized rows:
  a 16 × 16 rectangle's 16 rows of 4–5 words gain little over plain
  loads and stores, and the exact compiled restore beats it.
- **4-bit pixels can't use the byte-store trick:** two pixels to a byte,
  and the RAM has no nibble enables, so M0's edge words are always read,
  masked and written.
- **The game logic in C is expensive:** moving a bob and listing its
  draw and erase is about 770 ticks, 18 % of the best bob. The compiler
  reloads a global at every use and spills under register pressure;
  copying the globals to locals helped little.
- **`LDM`/`STM` are slower than loads and stores** for copying (54.7
  ticks a word against 31.8), so they're no use for runs of words.
- **Single buffering** needs the work in the vertical blank (16 bobs) or
  racing the beam (sorted by y, each bob updated once the beam has passed
  it; overlapping bobs then erase each other's pixels), which this
  program doesn't do.
- **Start-up:** 1.2 s to make the sprites, mostly the library's generic
  pre-shifting and the compiler; a game with many sprites would want
  them made at build time (a generator) or the compiler in assembly.

## What would have helped

- **A Neo Geo-like sprite mode is the only way to a wide margin.**
  Software tops out at about 187 bobs of 16 × 16 (69–72 of 32 × 32) at
  60 Hz in M1 with the whole CPU and no game; a game that gives sprites
  half a frame gets about 90 and 30. To beat that by a wide margin, the
  mode should draw at least 256 sprites of 16 × 16 at 60 Hz, 32 or more on
  a line, any pixel position, at no CPU cost but writing their table (x,
  y, tile, palette bank: 3 words a sprite, 256 × 3 stores, about 15,000
  ticks, 2 % of a frame), leaving the whole frame for the game. What
  that takes, roughly: 4-bit sprite pixels (index 0 transparent) with a
  palette bank each (16 of the 256, like the descriptors' banks), so a
  16-pixel sprite line is two words; 32 sprites a line is then 64 words
  of pixels and 32 of attributes a line (1,600 ticks), on top of the
  picture's 80 words: too much for bank 1's B0 slots, so the sprites'
  pixels want a memory of their own (like the Neo Geo's sprite ROM); two
  line buffers (one composited while the other is shown); vertical
  chaining for big objects; priority by order; clipping at the edges for
  free (the line buffer). Something like 20–30 chips.
- **A microcoded masked blit would not beat compiled sprites.** On this
  datapath (one memory access and one ALU operation a cycle, about 6.4
  ticks a microinstruction from `COPY`'s 19.3 ticks for three), `d = (d &
  ~mask) | image` from a stream is about seven microinstructions (read
  the mask, move it, read d, AND, read the image, OR, write): about 45
  ticks a word, the same as the compiled code's masked words with their
  constants in registers (38.8) and slower than its opaque words (19.8)
  and byte stores (12–13). With tests to skip transparent words and store
  opaque ones without reading, a 16 × 16 ball would be about 2,700 ticks
  against 1,611 compiled. What it would buy is memory (78 KB of code for
  eight sprites), start-up time and sprites that change at run time. A
  `BLIT` that skips a colour key, from an unshifted image, needs a zero
  detector per pixel (4–6 chips at 8 bits) and does the rotation as well:
  about 12 microinstructions, 75 ticks a word: it saves the pre-shifted
  copies, not time.
- **A two-dimensional `COPY`** (rows of `r3` words, pitches in two more
  registers, no set-up a row), microcode only: a 16 × 16 rectangle in M1
  about 1,570 ticks against 3,096 a row at a time and 2,028 compiled: 209
  bobs of 16 × 16 at 60 Hz (+12 %); the full redraw 370,000 against
  421,000.
- **The copy register** (RFC 0041's 4 chips: `COPY` in two cycles a word,
  about 13 ticks): the full redraw about 250,000 ticks, bytes with full
  redraw about 243 bobs of 16 × 16 (+43 %), and with a two-dimensional
  `COPY` for the rectangles about 238 (+27 %).
- **L0 for 8-bit modes:** the byte stores (28 % off drawing) need a pixel
  to be a byte; L1's 8-bit pixels can't have them. Everything else here
  is the same in either layout.
- **A store with byte enables from a register** (any subset of a word's
  bytes in one store) would make every 8-bit edge word one store, where
  now it's up to three narrow stores or a read-modify-write: an estimated
  15–20 % off the drawing in M1. For 4-bit pixels it would take nibble
  write enables, which the byte-wide RAM doesn't have.
- **The library:** pre-shifted sprites and a sprite compiler belong in
  `gfx/` (a `gfx_sprite_prepare` and kernels), and `gfx_masked` wants at
  least an assembly kernel. `sprite.c`, `jit.c` and `draw.s` are written
  to be lifted: games/breakout already builds them from here.

## Issues found

1. **`gfx_masked` is about 1,460 ticks a word** (111,242 ticks for a
   16 × 16 sprite at 8 bits, 80,192 at 4 bits): no assembly or block
   kernel, and the per-word work is the generic shift terms and mask
   tables. Reproduce: the `generic` lines of `results.md`.
2. **`gfx_masked` reads outside its image and mask.** When the
   destination's pixel phase is ahead of the source's (`base` < 0, e.g.
   `gfx_masked(&s, 5, 0, &img, &mask, 0, 0, 16, 16)` at 8 bits), it reads
   the word before each row of the image (`s[0]` with `sw` = -1) and of
   the mask (`mb[-1]`), and at the right edge the word after the row
   (`s[k + 1]`). The words are masked out, so the picture is right, but
   the first row's reads are before the arrays.
3. **Text at 8 bits a pixel is slow:** `font_draw` costs about 15,000
   ticks a glyph in M1 (games/breakout measured its status line: 559,000
   ticks for 37 glyphs); `EXPAND` handles only 4-bit pixels, and the C
   path is generic. Workaround there: digits rendered once and copied.
4. **`heron mini_gfx run` prints every `@perf` value's first two numbers
   as microseconds**, also counts and bytes (`code_bytes 633.3 us`).
5. **`rt_shot` stops the program for three frames,** so it can't show a
   single-buffered program drawing; printing `@shot NAME` directly does
   (the harness saves the frame two after).
6. **The C compiler and game logic:** globals reloaded at every use,
   `&a[i]` of a 24-byte structure multiplies (a microcoded loop),
   constant shifts up to 10 cycles. Copying globals to locals and walking
   pointers helps; it's the compiler study's business.
7. **`COPY`'s count latch:** every block instruction still needs `MOV rX,
   #-1; CLZ rX, rX` before it (the README's known issue); it's part of the
   ~100 ticks of set-up a row.

Nothing wrong was found in the simulator or RFC 0042: every prediction
held when run, B0 never underran, and the descriptors, TSEL and P1
behaved as specified.

## Screenshots

`heron mini_gfx run demos/bobs` writes them to
`build/mini_gfx/shots/demos-bobs/` (M0's with `--poke mode_sel=0`):

| Shot | What it shows |
|---|---|
| `m1_16` | 187 bobs of 16 × 16 at 60 Hz (byte-store compiled, exact restores) over the busy background, the status line on top |
| `m1_32` | 72 bobs of 32 × 32 at 60 Hz (byte-store compiled, full redraw) |
| `m1_16_30hz` | 512 bobs of 16 × 16 at 30 Hz (full redraw), the program's limit |
| `m1_generic` | the library's `gfx_masked`: 7 bobs at 60 Hz |
| `m1_single` | one buffer, 187 bobs drawn while the beam shows them: the top half's bobs are missing or torn |
| `m0_16`, `m0_32` | M0: 208 bobs of 16 × 16 and 89 of 32 × 32 at 60 Hz |
