---
status: active
depends-on: [mini, c_compiler, v2_isa, graphics]
reports: [43]
---

# Graphics software on Heron Mini's video

Software written against the video options of
[RFC 0042](../../reports/0042-rfc-mini-video.md), on the mini's
simulator ([studies/mini](../mini/README.md)), to find out which options
earn their chips: a graphics library for every pixel layout, a window
manager with a text editor, a forms application and a schematic editor
in it, and games and demos from simple to ambitious, each in C, with
assembly kernels, and with the mini's block instructions. What it found:
[report 0043](../../reports/0043-report-mini-graphics.md).

It depends on `mini` for the simulator and the video, on `c_compiler`
for the C compiler and its library, on `v2_isa` for the assembler, and on
`graphics` for its bitmap fonts.

```sh
heron mini_gfx list                              # the programs
heron mini_gfx run games/snake                   # one, with its script: output, timings, screenshots
heron mini_gfx run games/snake --variant blk --layout L1 --png-dir out/
heron mini_gfx run demos/testcard --profile 500  # where the time goes, by function
heron mini_gfx check                             # the library against references, in every format
heron test mini_gfx                              # the unit tests
```

## The pieces

| Folder | What's in it |
|---|---|
| `rt/` | The runtime: the start code and the interrupt into C (`start.s`, `rt.c`), the video (`video.c`: modes, descriptor tables, page flips, palette, cursor, bank 1's memory, the beam as a clock), the keyboard and mouse (`input.c`), timing (`perf.c`), default palettes |
| `gfx/` | The graphics library: pixel formats (`format.c`), fills, pixels and patterns (`gfx.c`), lines and circles (`line.c`), copies, 1-bit expansion and sprites (`blit.c`), fonts (`font.c`); the kernels in C, in draft 2 assembly (`asm/`) and with the block instructions (`blk/`) |
| `wm/` | The window manager |
| `check/`, `demos/`, `games/`, `apps/` | The programs, a folder each with a `prog.toml` |
| `build.py`, `run.py`, `programs.py` | Building a program, running it frame by frame with scripted input, the programs' descriptions |
| `fonts.py` | The fonts as data: the graphics study's `sans12` and `mono12`, and `cell8`, mono12 in 8 x 16 cells |

## Writing a program

A program is a folder under `demos/`, `games/` or `apps/` with C (and
assembly, if it wants) and a `prog.toml` (`programs.py` has its fields).
It's linked with the runtime, the library and the C library; the linker
keeps only what it reaches.

**The machine.** Draft 2's user level at about 7 million cycles a second
(cycles of 5–11 ticks of 19.86 ns): a frame (59.94 Hz, 16.68 ms) is
about 840,000 ticks, 110,000–130,000 cycles. Bank 0 (0–2 MB) holds the
program, its data, the heap (`malloc`, up to 0xF0000) and the stack
(from 0x200000 down); bank 1 (0x200000–0x3FFFFF) is the video's: its two
descriptor tables in the first 8 KB, then whatever `vram_alloc` hands
out. Shifts by a register cost a cycle a bit (2 + n cycles) and shifts by
a constant up to 10, a rotation by a constant at most 4; multiplies and
divides are microcoded loops (tens of cycles). Compiled C's `x >> n` with
a variable `n` is the slow kind.

**The video** (`rt/video.h`, RFC 0042 Part I is the reference):

```c
video_init(0, VC_CURSOR);           /* M0, the cursor on; from the next frame */
video_default_palette();
fb = vram_alloc(vid.words * 4 * vid.h);
video_lines(0, 0, vid.h, fb, vid.words * 4, 0);   /* table 0: the lines from fb, bank 0 */
gfx_screen(&s, fb, vid.words);      /* a Surface over it, in the mode's pixel format */
...
video_wait();                       /* until the frame's end (the interrupt; HALT meanwhile) */
video_show(1);                      /* table 1 from the next frame: a page flip */
```

`vid` has the mode's size, bits a pixel and a line's words. The
descriptors are words in bank 1 (`video_table(t)[y]`): a line's start
(a word address in bank 1, `video_word`), its palette bank, bit 23 for
an interrupt (`video_line_irq`, `rt_line_hook`). `rt_frame_hook` runs in
the interrupt at each frame's end. `video_ticks()` is the time in ticks
from the frame count and the beam (P1). The board's choices, the layout
(L0, L1) and the bandwidth (B0–B2), are the run's (`--layout`,
`--bandwidth`); the library reads the layout from `board_layout`, which
the harness sets.

**The library** (`gfx/gfx.h`): a `Surface` is rows of words in one of
nine pixel formats (`gfx_screen` picks the screen's from the mode, the
layout and F1); every drawing call clips to its clip rectangle and works
in any format: `gfx_fill`, `gfx_pixel`, `gfx_line`, `gfx_blit` (any
alignment, overlapping), `gfx_expand` (1-bit images and glyphs),
`gfx_masked` (sprites with a mask), `font_draw` and `font_cells`. The
fonts: `font_init()`, then `font_sans`, `font_mono` and `font_cell`
(8 x 16 cells; `font_cells` draws a string's rows as 1-bit rows, the
fast way). The kernels are the inner loops; the variant decides which:
`c` (C), `asm` (gfx/asm), `blk` (gfx/blk, the block instructions). A
program's own C can test `GFX_ASM` and `GFX_BLK`, and in the blk variant
call `blk_fill`, `blk_copy`, `blk_expand` and `blk_blit` directly.

**Input** (`rt/input.h`): `input_init()`, then `input_next(&e)` for
events (keys with their characters, the mouse), `key_down(k)` for a
key's state, `mouse_x`, `mouse_y`, `mouse_buttons`. In the simulations
they come over UART 1 from the run's script (`run.py` has the format):

```
30 mouse 320 240
32 click 100 120
40 type hello
50 key enter
60 keydown right
90 keyup right
```

**Measuring** (`rt/perf.h`): `perf_start()` and `perf_end("name")`
print a span in ticks; `perf_frame_begin()`/`perf_frame_end()` around a
game's work each frame and `perf_frames("name")` print the average and
the worst. `rt_shot("name")` takes a screenshot of the next frame
(the program waits for it); a script's `shot NAME` takes one of a
frame. `printf` goes to the simulations' console; a line `@done` ends
the run.

**C and assembly.** The compiler is studies/c_compiler (C89 and some
C99; no floating point, `long long` or bit fields; `char` is unsigned).
C names get a `_` in the assembly. Arguments in `r1`–`r4`, then the
stack; the result in `r1`; `r0`–`r7` are the caller's, `r8`–`r14` the
callee's to save; calls leave the return address in `r7`, so a routine
that calls saves it (`SAVE r7-r14` ... `RESTORE r7-r14`, `RET`). Calls
reach ±64 KB. Interrupt handlers are C functions on the runtime's hooks.
The block instructions are written `.half 0x01FD` (FILL), `0x02FD`
(COPY), `0x03FD` (EXPAND), `0x10FD + 0x100 * k` (BLIT k), each after
`MOV rX, #-1; CLZ rX, rX`: the microcode tests its count's condition
latch a microinstruction before it loads it, so without that a block
instruction does nothing if the latch was left set (reported to the
mini study; `gfx/blk/blk.s`).

## How the library works

**Pixel formats.** RFC 0042's layouts make nine: pixel p's bit i at
`p * bpp + i` (the linear ones: L0 at 4 and 8 bits, F1 at 1 and 2, L1
at 1); L0's chunky 1 and 2 bits without F1 (bit `4(p mod 8) + p/8`); L1's
planes at 2, 4 and 8. Each is one function, `gfx_bitpos`, and everything
else is worked out from it when a format is first used: each pixel's
mask, each colour's word, the edge masks, the tables that expand 1-bit
pixels.

**Shifted copies.** A copy whose source and destination differ in their
pixels' phase in a word makes each destination word from two source
words; which bits come from where, and by what shift, depends only on
the format and the phase, so `shift_terms` works it out from
`gfx_bitpos` as a few (word, shift, mask) terms: two for the linear
formats and the planes, four for L0's chunky 1 and 2 bits. The kernels
take the terms.

**The kernels' variants.** The assembly kernels patch their shifts as
constants into their loops (a jump between, so the prefetch queue holds
no stale copy); the linear shifted copy rotates each source word once
and `MERGE`s it with the one before. The block variant uses FILL and
COPY for whole words, BLIT k for the linear formats' shifted copies at 4
and 8 bits, and EXPAND for opaque expansion at 8 pixels a word (L0 and
L1 at 4 bits: EXPAND's table makes it work for either). Each passes the
self-test (`check/selftest`) in all nine formats.
