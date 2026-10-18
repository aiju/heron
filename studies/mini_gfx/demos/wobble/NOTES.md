# Wobble

## What it is

A block logo (drawn in code from the sans font) bent, stretched, flipped
and zoomed by the line descriptors alone, at no cost a pixel; a
vertical scroller of credits; a split screen of three regions with
their own palettes (the wobbling logo over a sky, a smooth horizontal
text scroller in rainbow lines, a 3D starfield drawn by the CPU); a
benchmark of how many 3D stars the CPU moves in a frame; and a
starfield made by the descriptors instead.

```sh
heron mini_gfx run demos/wobble                 # C; about 1200 frames (the copies take 1.5 s)
heron mini_gfx run demos/wobble --variant asm   # the stars in assembly
heron mini_gfx run demos/wobble --variant blk --layout L1
```

## How it uses the video

- **M0** (640 × 480 × 4), every part through the descriptors, both
  tables flipped with `TSEL` in the blanking.
- **Per-line start addresses**: a line shows 80 consecutive words from
  anywhere in bank 1, so a line can be any row of any picture, from any
  word of it. Horizontal offsets are whole words: **8 pixels in M0**.
- **Eight shifted copies** for pixel offsets: copy *k* holds the
  picture shifted *k* pixels right (made once with `gfx_blit`); a line
  that should start at pixel *X* takes copy *k* = −*X* mod 8 from word
  (*X* + *k*)/8. The logo (768 × 136) is 52 KB, its copies 418 KB; the
  scroller's strip and the star rows are done the same way.
- **Repeated and skipped lines**: a stretch to *h* lines steps through
  the rows by LH/*h* (16.16); a flip takes them backwards; a zoom is a
  stretch past 1. Only vertically: nothing in a descriptor scales a
  line.
- **Palette banks**: a sky of 7 bands behind the logo (colour 0 in
  banks 0–6, the logo's colours the same in each); the credits' 16
  brightnesses, so the lines fade in and out at the screen's edges; the
  split screen's regions (sky banks 0–6, stars bank 7, the scroller's
  lines in banks 8–15, each a hue); the descriptor stars' brightness
  (bank = speed).
- **Layouts**: everything works in L0 and L1 (the library draws and
  shifts the copies in either); only the time to make the copies
  changes.
- **Block instructions**: only through the library (the blk variant's
  `BLIT` makes the shifted copies 8 times faster than C).

## Implementations and measurements

Ticks are 19.86 ns, a frame 840,000. The descriptors are written in C
in every variant (a table of 480 words a frame); "used" is the CPU
taken in a frame, from the idle work left (`fx_idle`), including the
descriptors.

| Part | What a frame costs | Ticks a frame | Used |
|---|---|---:|---:|
| 1 wave by whole words | 480 descriptors (C) | 95,500 | 11.6% |
| 2 smooth wave, 8 copies | 480 descriptors (C) | 128,700 | 15.5% |
| 3 stretch, flip, zoom, with the wave | 480 descriptors (C) | 138,000 | 15.5% |
| 4 vertical scroller, faded edges | 480 descriptors (C) | 96,500 | 12.2% |
| 5 split screen | 480 descriptors (C) | 118,200 | 14% |
| | and 300 3D stars (asm) | 238,800 | (42.8% in all) |
| 6 descriptor starfield, 120 rows of stars, the logo bouncing | 480 descriptors (C) | 153,300 | 18.4% |

**3D stars by the CPU** (erase, move, project with a table of
reciprocals and two multiplies, draw a pixel through the format's
masks):

| Stars | c | asm | Of a frame (asm) |
|---:|---:|---:|---:|
| a star | 899 ticks | 794 ticks | |
| 250 | 225K | 199K | 23.7% |
| 500 | 450K | 397K | 47.3% |
| 1,000 | 904K | 794K | 94.4% |
| 2,000 | 1.80M | 1.59M | 189% |

**Making the logo's 7 shifted copies** (768 × 136, once):

| Variant | L0 | L1 |
|---|---:|---:|
| c | 78.1M ticks (1.55 s) | |
| asm | 14.9M (0.30 s) | 16.8M (0.33 s) |
| blk | 9.8M (0.20 s) | |

**Memory in bank 1**: the logo and its copies 418 KB (52 KB a copy), the
credits 307 KB (30 lines of 32 rows), the scroller's strip in 8 copies
159 KB, the stars' framebuffer 74 KB, the star rows in 8 copies 614 KB:
1.58 MB of the 2 MB.

**How the coarse wave looks** (part 1): a sine of ±53 pixels becomes a
staircase of 8-pixel steps; the logo's vertical strokes turn into
sawtooth edges and, moving, the steps crawl up and down. Fine for big,
fast waves; ugly for small ones (under 8 pixels it is a stutter). The
smooth wave (part 2) costs 8 times the memory and 35% more C a line
(choosing the copy).

## What worked well

- **The descriptors are a whole effects engine**: waves, squash and
  stretch, flips, zooms, scrolling, split screens, all for one word a
  line, with no pixel touched. The cost is the C that writes 480 words:
  12–18% of a frame (200–300 ticks a line); in assembly it would be a
  third of that.
- **Eight shifted copies** make every horizontal effect smooth, and
  memory is plentiful (bank 1 is 2 MB): the logo, a text strip and 120
  rows of stars in 8 copies each fit with room to spare.
- **The vertical scroller** is free: the credits drawn once (307 KB),
  the descriptors move down them, and the palette banks fade the lines
  at the edges (16 brightnesses, a bank a line) without a palette
  write.
- **Split screens with their own palettes**: each region's lines use
  their own banks, so the logo's sky, the stars' greys and the
  scroller's eight hues never meet.
- **The descriptor starfield**: 120 stars (it could be 480, one a line)
  scrolling sideways at their own speeds, with their brightness by
  speed through the banks, for 18% of a frame whatever their number;
  the CPU manages 250 3D stars in 24%.

## What was hard or didn't work

- **Horizontal offsets are whole words** (8 pixels in M0, 4 in M1, 16 or
  32 in M3/M4): every smooth horizontal effect needs 8 copies of its
  picture (or 16, 32 at 2 and 1 bits a pixel, with F1 or L1), made
  once at a cost (1.55 s in C here) and kept in 8 times the memory.
  Big pictures can't be copied 8 times: a 2,048 × 480 M0 map is 480 KB,
  its copies 3.9 MB, more than bank 1.
- **Nothing scales or mirrors a line**: horizontal zoom, horizontal flip
  and rotation need the CPU (or another copy, for a mirror).
- **A line is all one thing**: the logo's lines can't also show the
  starfield behind it (each line is one picture's row); the regions of
  a split screen have to share lines' worth of margins.
- **The bank field next to the interrupt bit**: a bank number of 16 (the
  first version of part 6 computed bank = speed / 8, up to 16) set bit 23
  on random lines; the runtime then counted those lines' interrupts as
  frames and the part ran wild ("1,839,712 ticks a frame"). Masking the
  bank fixed it.
- **C per line**: the first version spent 700 ticks a line on a divide
  by 480, two multiplies and a call; tables brought it to 200–270.
- **The 3D stars are instruction-bound**, not multiply-bound: making both
  multiplies take the microcode's 16-step path (operands under 2^15)
  saved 3%; the ~45 instructions a star, a dozen of them memory accesses,
  are the cost.

## What would have helped

- **A pixel offset in the descriptor** (3 of the free bits 31–24 in M0,
  2 in M1, 4–5 for 2 and 1 bits a pixel): every smooth horizontal effect
  from one copy: the logo's 418 KB would be 52 KB, the star rows' 614 KB
  77 KB, no 1.5 s of making copies, and smooth scrolling of pictures too
  big to copy (any game map). In hardware the line's first shifter load
  waits *k* pixels and the video fetches one word more (81): a latch for
  the bits and a few terms in the video's GALs, about 2–3 chips.
- **A table base register** (a few bits choosing where in bank 1 the
  descriptor table is, instead of `TSEL`'s two): a periodic effect could
  be precomputed as a ring of tables (64 tables of the wave are 123 KB)
  and played by writing one register a frame: the 12–18% of a frame for
  480 descriptors would go to nearly nothing. About 1–2 chips (a
  9-bit register in place of `TSEL`'s bit).
- **A line's start in pixels with a step** (a horizontal DDA) would give
  zooms and mirrors, but that is a different video: not worth its
  chips for this.

## Issues found

- **The bank field and bit 23** (above): `video_desc(addr, bank)` doesn't
  mask the bank, so `video_desc(p, 16)` asks for a line interrupt.
  *Repro:* part 6 with `(s_v[r] >> 3) << 19` unmasked (speeds up to 135).
  See `../rasterbars/NOTES.md` for the runtime's side.
- **The study's `gfx_blit` makes the 7 shifted copies 5–8 times faster in
  asm/blk than in C** (78M against 15M and 10M ticks), as expected; no
  errors in any format (the copies line up in L0 and L1).

## Screenshots

`heron mini_gfx run demos/wobble` writes them to
`build/mini_gfx/shots/demos-wobble/`:

- `wave_coarse.png`: the wave by whole words: 8-pixel steps, sawtooth
  edges.
- `wave_fine.png`: the same wave from the 8 copies: smooth.
- `bounce.png`: the logo squashed as it lands (repeated and skipped
  lines), a small wave on it.
- `flip.png`: half way through turning over: upside down (rows in
  reverse).
- `zoom.png`: stretched 3.5 times, waving: the vertical zoom.
- `vscroll.png`: the credits scrolling up, the lines near the top and
  bottom dimmed by their banks.
- `split.png`: the split screen: the logo over a banded sky, the smooth
  rainbow scroller, 300 stars.
- `lstars.png`: the descriptor starfield, 120 rows sliding at their own
  speeds, the logo bouncing over them.
