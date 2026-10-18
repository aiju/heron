# Fennec Run: notes

## What it is

A side-scrolling platformer on M1 shown as 320 × 240 × 8 (every line
twice by the descriptors). A fennec fox runs, jumps (fixed point 8.8,
variable height), bumps star blocks, collects coins and stomps beetles. A
bird crosses the sky. The run is a scripted pass through 150 of the
level's 240 columns (`run.script`, 1460 frames, 9 screenshots) that
finishes cleanly: 20 coins, 3 stomps, 3 blocks, no hits. The game logic
runs once per 60 Hz tick from the keys sampled at each frame's
interrupt, so every configuration plays the same run, whatever its frame
rate.

Options (`--poke`): `strategy` 0–3 (coarse, preshift (the default),
blit, redraw), `race=1`, `cursor_bird=1`, `bench=1` (kernel timings),
`trace=N`.

## How it uses the video

- **M1, L0**, bandwidth B0. Each logical line is two descriptors, so a
  frame writes 480 descriptors. Both tables are used: a frame is built
  into the hidden one, and TSEL is switched in the frame's interrupt.
- **Bands, one buffer each:** the HUD (16 lines), sky (48 lines, 1/8
  speed), mountains (32, 1/4), hills (16, 1/2) and the playfield (128
  lines, 8 rows of tiles). The three parallax bands are periodic,
  512 pixels wide plus a screen's width, pre-shifted at all 4 phases. They
  scroll smoothly for the cost of their descriptors alone.
- **Playfield:** ring buffers 96 + 84 words wide. A column in the first
  84 words is drawn twice, so 80 words from any start are contiguous. New
  columns are drawn at the seam, one column of one ring a frame ahead of
  the view.
- **Sprites:** pre-shifted to 4 phases as (keep-mask, image) pairs. They
  are drawn into lines the frame owns: either spare lines the shown line
  is copied into first (COPY), or in race mode the shared buffers
  themselves.
- **Cursor (C1):** optionally the bird (`cursor_bird=1`).
- **P1:** used for the timings and for race mode's deadline check.
- **Palette banks:** not used, since M1 ignores them.
- **Layout:** L1 works unchanged, because every word comes from
  `gfx_bitpos`. The pictures are pixel-identical and so are the timings.
  BLIT k only shifts L0.

## Implementations and measurements

Work per frame over the run, in ticks as % of a frame (840,000), with the
worst frame and the frames per second.

| Strategy | c | asm | blk | fps |
|---|---|---|---|---|
| coarse (descriptors only, 4-pixel steps) | 34.8 / 64.7 | 27.5 / 50.1 | 22.0 / 39.0 | 60 |
| preshift (4 rings, descriptors pick) | 36.5 / 69.7 | 29.1 / 54.7 | 23.7 / 43.7 | 60 |
| preshift + race (sprites in place) | 17.6 / 30.0 | 16.1 / 28.6 | 16.1 / 28.6 | 60 |
| blit (ring, shifted copy every frame) | 121 / 164 | 86 / 113 | 59 / 79 | 35 / 48 / 60 |
| redraw (all tiles every frame) | 87 / 103 | 77 / 90 | 76 / 84 | 59 / 60 / 60 |

Where the time goes (preshift, blk):

| Part | Share of a frame |
|---|---|
| copying the lines under sprites to spare lines | 10.7% (worst 22%) |
| descriptors and line setup | 5.3% |
| drawing the sprites | 2.4% |
| seam | 2.2% |
| HUD | 1.5% |
| logic | 1.4% |

Race mode replaces the line copies with save, draw and restore at 7%.
The cursor bird saves 3.0% (its 12 spare lines). B1 and B2 change
nothing: M1 has no steals and no underruns.

Kernels (`bench=1`), in ticks a word:

| Kernel | Ticks a word |
|---|---|
| Copy | C 52, asm 34.5, LDM/STM 54, COPY 21 |
| FILL | 9 |
| Shift at 8 bpp | C 92–102, ROR+MERGE 62–67, BLIT 2/4/6 40–45 |
| Masked sprite | C 125, asm 75 (AND/OR with memory operands; MERGE was 111) |
| Full redraw | C 53, asm 49 |
| A descriptor | 89 ticks a line in C or asm |
| The HUD's 34 characters | `font_cells` 22.2 ms, a nibble table 1.8 ms |

## What worked well

- The descriptors made parallax, the split HUD and coarse scrolling free.
  Pre-shifted rings made fine scrolling nearly free too: about 2% for the
  seam, at a memory cost of 4 rings of 90 KB.
- Racing the beam: just after the frame's interrupt, sprites are drawn
  into the shared buffers with save-under and restored the next frame.
  This takes 16% of a frame instead of 23.7%, and was never late (P1
  checks it).
- Pre-shifted, pre-masked data in a format-generic packer, so L1 cost
  nothing.

## What was hard or didn't work

- Sprites over shared, double-buffered line sources: every line under a
  sprite costs an 80-word copy (1,680 ticks), seven times the sprite's own
  drawing.
- BLIT k (59%) and full redraws (76%) fit 60 Hz only for a 128-line
  playfield; a full screen would not.
- LDM/STM copy slower than plain loads and stores: the register-range dry
  run costs about 3 cycles a register.

## What would have helped

- **A pixel offset in descriptor bits 31–24** (0–3 in M1, 0–7 in M0):
  fine scrolling with one ring instead of four. That saves 270 KB and
  three quarters of the seam (about 1.6% of a frame), and makes BLIT or
  redraw unnecessary (saving 37–60% of a frame).
- **Hardware sprites** (the planned Neo Geo-like mode) would save the
  spare lines and the drawing: 13% of a frame on average, 25% at worst,
  or 7% against race mode. What it should have:
  - 16 pixels wide at 8 bits, colour 0 transparent;
  - per-line composition from a list, at least 8–10 sprites a line;
  - the ability to cover the bands;
  - x in VGA pixels.

  C1 already shows the value: one 3-colour sprite saved 3%.
- **A masked copy instruction** `d = (d & s1) | s2` at about 4 cycles a
  word: sprites 75 → about 30 ticks a word.
- **A COPY at 2 cycles a word** (RFC 0041's copy register): spare lines
  21 → 14 ticks a word.
- **A line-repeat bit or a band descriptor** (base, pitch, offset for N
  lines): it would replace most of the 480 descriptor writes, saving
  about 5% of a frame.
- **Not needed:** more bandwidth.

## Issues found

- `font_cells` and `gfx_expand` at 8 bits a pixel run the C kernel
  (`expand_rows_c`) in every variant. The HUD's 34 characters take
  22.2 ms, against 1.8 ms with a nibble table (`hud_text` here).
  Reproduce with `bench=1`.
- No bugs found in RFC 0042 or the simulator. One unclear point:
  whether TSEL is latched per frame or read with each descriptor.

## Screenshots

From `heron mini_gfx run games/platformer`:

| Screenshot | What it shows |
|---|---|
| `start` | The first view: the parallax bands and the HUD |
| `bump` | A coin popping from a star block |
| `platform` | Coins on a brick platform |
| `pit` | The jump over a pit |
| `stomp` | A flattened beetle |
| `sky` | The fox high over the mountains and clouds, sprites in the bands |
| `blocks` | Three bumped blocks and a beetle |
| `bridge` | The plank bridge over spikes |
| `wall` | The end of the run |
