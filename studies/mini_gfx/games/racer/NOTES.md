# Racer: notes

## What it is

A pseudo-3D road racer: a 512-segment lap with curves, climbs, crests and a
dip, six other cars, trees, bushes and chevron signs, and a HUD. When no
steering key is down, an autopilot keeps the car in a lane and steers
round slower cars. The script holds the throttle and steers by hand once.
It runs about 1,000 frames of racing after about 300 frames of init.

Options (`--poke NAME=V`, see `main.c`):

- `mode_sel=1`: M1.
- `soft=1`: every road line drawn by the CPU each frame.
- `soft=2`: every line drawn by the CPU each frame.
- `prep_copy=0`: sprite lines rendered instead of copied.
- `sky_irq=1`: the sky's gradient by line interrupts.
- `lookahead=N`: how many segments ahead roadside objects are placed.
- `bench=1`: time each kernel on its own, then stop.

## How it uses the video

- **Mode M0, the descriptors (D0) and the palette banks.**
  - **The road** is drawn once into 256 rows, 128 words each, wider than the screen. Row k is the road as flat ground shows it k + 1 lines below the horizon. Each row is stored 8 times, shifted 0–7 pixels, because a descriptor can only start on a word.
  - **Each frame**, the CPU picks for each line a row (repeated or skipped rows make the hills and crests), a start address (curves and steering, to the pixel) and a palette bank. Banks 0 and 1 are the light and dark stripes: the grass, the rumble strips and the lane dashes move with no pixel redrawn.
  - **The sky's gradient** comes from banks 2–15, dithered by line. With `sky_irq=1`, a line interrupt every 4 lines rewrites one sky entry in the bank not being shown, giving 56 steps.
  - **The background:** mountains and clouds are rows that wrap, also in 8 pixel phases. They scroll with the road's heading, the clouds at half the rate.
- **Sprites:** every line a sprite covers gets a scratch line from a pool, one pool per descriptor table. The line's source is copied into it with COPY, the sprites are drawn into it, and the line's descriptor is pointed there. The two tables, switched by TSEL from the frame interrupt, give double buffering.
  - Each sprite is pre-scaled to 10 sizes and pre-shifted to 8 phases, stored as runs of opaque and masked words: 738 KB in bank 0, above the heap.
- **M1:** the same game. There are no palette banks, so each road row is stored light and dark, in 4 phases each, for the same memory as M0's 8 phases. The sky is a free 64-step gradient (one line of each colour).
- **Other options:**
  - L1 works unchanged; only init is slower.
  - B0 suffices: 0 steals, 0 underruns.
  - P1 is used only for timing.
  - No cursor.
- **Block instructions:** COPY makes the scratch lines and the sprites' opaque runs, FILL the software road.

## Implementations and measurements

These are from the default run: M0, L0, B0, about 30 sprites and 234 scratch lines a frame. Times are in ms of work a frame (a frame is 16.7 ms); the fps are the frames actually built.

| Part | c | asm | blk |
|---|---:|---:|---:|
| Projection (251 steps, 2 multiplies each) | 6.9 | 6.2 | 6.2 |
| Background descriptors | 0.39 | 0.37 | 0.37 |
| Placing and sorting the sprites | 2.0 | 1.8 | 1.9 |
| Scratch lines (copied) | 22.3 | 14.4 | 10.0 |
| Drawing the sprites (~4,500 words) | 7.1 | 6.7 | 6.2 |
| HUD and logic | 0.8 | 0.7 | 0.7 |
| **Frame** | **39.5 (21 fps)** | **30.2 (27 fps)** | **25.4 (30 fps)** |
| Software road, `soft=1` | – | 53.8 (18 fps) | 38.7 (26 fps) |

The asm column was measured on a 600-frame run before the last small fixes.

- **The kernels on their own** (`bench=1`, blk / asm / c):
  - Copying a line: 34 / 53 / 77 µs.
  - Rendering a road line: 78 / 152 / 188 µs.
  - Drawing the player's car (51 rows of 16 words): 0.63 / 0.85 / 0.90 ms.
- **The line-interrupt sky** costs +1.5 ms a frame for 49 interrupts: about 30 µs (1,500 ticks) per interrupt, through the runtime's dispatch.
- **M1 (blk)** costs the same as M0: 24.7 ms a frame, because a sprite word holds half the pixels but the sprites are half as wide. Init takes 2.7 s against M0's 4.9 s.
- **Bank 1 in M0:** 2.07 MB of 2 MB used.
  - Road rows: 1,032 KB.
  - Background: 731 KB.
  - Scratch pools: 240 KB.

## What worked well

- **The road itself is almost free:** curves, hills, crests, stripes, the sky and the parallax are all descriptors. What remains for the CPU is the projection, 6 ms a frame.
- **Copying is cheaper than drawing:** a scratch line copied with COPY costs half as much as the road rendered into it, even with a dedicated renderer.
- **Pixel-exact positions without shifting at draw time:** the road and background in pixel phases, and the sprites pre-shifted.

## What was hard or didn't work

- **Sprites dominate the frame.** With objects on both sides of the road, almost every road line has a sprite. That takes 234 scratch lines plus the drawing: 16 ms of the 25 ms frame. So the descriptor road saves less than expected over the software road: 25 ms against 39 ms. 60 fps isn't reachable in software at this density.
- **The projection costs about 170 cycles a step:**
  - about 50 cycles in the two multiplies;
  - about 30 in constant right shifts, which cost a cycle a bit;
  - the rest is fetch-bound: the absolute-indexed operands are 3 parcels long.
- **The pixel phases fill bank 1:** the road and background phases take 1.7 MB of it, and init takes about 5 s, mostly pre-shifting sprites in C.

## What would help

- **A pixel offset in the descriptor (bits 26–24):**
  - The road rows shrink from 1,032 KB to 129 KB, and the background from 731 KB to about 91 KB.
  - The road part of init gets 8 times shorter.
  - Estimated cost: about 2–3 chips (a 3-bit latch, and the load timing).
- **A split column with a second address in the descriptor** (a window): a scratch line would then need only the sprite's 10–16 words, not 80. The scratch lines would drop from 10 ms to about 2 ms.
- **Scaled hardware sprites (the Neo Geo-like mode)** would remove the scratch lines and the drawing: 16 of the 25 ms, so 60 fps with room to spare, and 738 KB of pre-scaled art would become about 20 KB. For this game it needs:
  - about 32 sprites, 8 on a line;
  - up to 120 px wide, at any pixel x;
  - a shrink factor for each sprite;
  - 15 colours and transparency;
  - priority by list order;
  - about 40 more words of video bandwidth per line.
- **A microcode copper:** a palette write each line costs about 1,500 ticks by interrupt, against a few ticks in microcode. A per-line gradient (480 writes) would cost 14 ms a frame by interrupts.
- **More palette banks:** a 5th bank bit from bits 31–24 costs about 0–1 chips, since the palette SRAM already holds 512 entries. It would allow fog on the road and a smooth sky without interrupts.
- **A faster multiply or cheaper right shifts** would cut the projection by about a third.

## Issues found

1. **`build.py`'s object cache ignores a program's own headers.** It hashes only `rt/`, `gfx/` and `wm/`. After a struct in `racer.h` changed, `track.c`'s stale object made `seg_obj` garbage. Workaround: delete `build/mini_gfx/obj/<file>.c-*.o`.
2. **The runtime can count line interrupts as frames.** `video_irq` checks for line interrupts only while `line_irqs` (counted by `video_line_irq`) is nonzero.
   - A program that writes bit 23 into the tables itself must call `video_line_irq` once first.
   - A stray bit 23 makes `rt_frames` run hundreds of times too fast. Here it came from a garbage descriptor; it showed as `video_ticks` being wildly wrong.
   - Suggestion: always decide by the beam.
3. **`video_show` flips mid-frame after a missed frame:** `video_wait` returns at once, and TSEL changes mid-picture. Racer flips from `rt_frame_hook` instead.
4. **The C compiler multiplies by constants with `MULS #k`** (struct indexing, `n * 96`), a 16-step loop. Also, `MULS` with a negative operand takes 32 steps. Workarounds: power-of-two structs, pointers, `MULU` on absolute values.
5. **A line interrupt can't change the line it's for.** It arrives about 240 ticks before its line starts, and dispatch takes about 1,500. It can only change lines further down, so the sky alternates two banks. Block instructions add up to about 5,000 ticks of latency.

## Screenshots

The default run (`heron mini_gfx run games/racer`) takes these:

| Name | What it shows |
|---|---|
| `climb` | The road rising over the horizon and hiding the mountains (rows skipped) |
| `crest` | The road ending at a crest, with the grass beyond |
| `lean` | Steering by hand: the car leans, and the road shifts to the pixel |
| `bends` | The S bends, with chevrons, cars and trees at several sizes |
| `hill` | A long climb with roadside trees and an overtaking car |

With `--poke mode_sel=1`, `soft=1` or `sky_irq=1`, the same shots are named `m1_*`, `soft_*` and `irq_*`. The `irq_*` shots show the smooth 56-step sky.
