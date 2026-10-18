# Rotozoomer

## What it is

A 256 × 256 texture (checkerboard, rings, the block logo; drawn with the
library as an 8-bit surface) turning and zooming, every texel looked up
each frame: a CPU benchmark. Fixed point: u and v (8.8) are the two
halves of one word, `uv = u << 16 | v`, one `ADD` steps both; the texel
is `tex[(uv >> 24) | (uv & 0xFF00)]`.

```sh
heron mini_gfx run demos/rotozoom [--variant asm] [--layout L1]
```

## How it uses the video

M1 (320 × 480 × 8). 160 × 120: each texel two pixels wide (the texture
holds it doubled, a half), rows shown 4 times by the descriptors. 80 ×
60: a texel a word, rows 8 times. Two pictures flipped with `TSEL`. In
L1 the texture holds each texel in L1's bits (converted once), so a word
costs one shift more. No block instructions (variants c and asm).

## Implementations and measurements

| Resolution | Variant | Layout | Ticks a texel | A frame | Of a frame | Frames a second |
|---|---|---|---:|---:|---:|---:|
| 160 × 120 | c | L0 | 99 | 38.1 ms | 228% | 20 |
| | asm | L0 | 88 | 33.9 ms | 203% | 20 |
| | c | L1 | 102 | 39.0 ms | 234% | 20 |
| | asm | L1 | 94 | 35.8 ms | 215% | 20 |
| 80 × 60 | c | L0/L1 | 101 | 9.7 ms | 58% | 60 |
| | asm | L0/L1 | 107 | 10.2 ms | 62% | 60 |

About 9,500 texels a frame at 60 Hz (160 × 60). Making the texture in C:
81M ticks (1.6 s, once).

## What worked well

- Two coordinates in one register: one add a texel for both.
- L1 costs ~6% here: the layout's conversion is baked into the texture.

## What was hard or didn't work

- **Assembly doesn't beat C**: the compiler emits the same ten
  instructions a texel (two memory accesses, a shift by 24, masks).
  The cost is instruction count, not the code's quality.

## What would have helped

- **A microcoded texture-mapping block instruction** (`d = tex[(uv >> 24)
  | (uv & 0xFF00)]; uv += duv` over *n* texels, ~4 cycles, ~28 ticks a
  texel): 160 × 120 at 60 Hz (538K ticks, 64% of a frame) instead of 20.
- A bit-field extract/insert instruction would cut the index to one or
  two operations.

## Issues found

None.

## Screenshots

`build/mini_gfx/shots/demos-rotozoom/`: `roto_160a.png`, `roto_160b.png`
(160 × 120, turning and zoomed in/out), `roto_80.png` (80 × 60).
