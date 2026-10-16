---
status: active
depends-on: [v1_isa, v2_isa, c_compiler]
reports: [19]
---

# Graphics on draft 1

How well drafts 1a and 1b suit graphics software: a graphics library for
screens of 1, 2, 4 and 8 bits per pixel, bitmap and TrueType fonts, and
the graphics side of a window manager, in C with the inner loops in
assembly for each draft, measured on the instruction-level simulator.
The results are in [report 0019](../../reports/0019-report-graphics.md).

It depends on `v1_isa` for the ISAs, the simulator and the timing model
(and `v2_isa` for draft 2's, which the kernels were later ported to),
and on `c_compiler` for the C compiler and its library.

| File | What's in it |
|---|---|
| `src/gfx.h` | The library's interface, and the kernels' jobs |
| `src/gfx.c`, `line.c`, `ellipse.c`, `raster.c`, `blit.c`, `expand.c` | Surfaces, fills and patterns, lines, ellipses, scan conversion (polygons, glyph outlines, anti-aliasing), copies, 1-bit images in colour, coverage through a ramp |
| `src/font.c`, `src/ttf.c` | Bitmap fonts; TrueType read on the machine, rasterised and cached |
| `src/wm.c`, `src/wm.h` | The window manager: regions, frames, moving, raising, scrolling, the cursor |
| `src/theme.c` | Palettes, colours, the desktop pattern, the icon and cursor |
| `src/scenes.c` | The benchmark scenes: `prims`, `text` and `wm` |
| `src/main.c`, `src/host.c` | Their mains on the machine, and on the host with gcc (the reference) |
| `src/selftest.c` | The word-level code against pixel-at-a-time references |
| `asm/v1a/`, `asm/v1b/`, `asm/v2/` | The kernels in assembly; `asm/v1b/stm/` is the store-multiple experiment. Draft 2's are 1b's, translated as the program suite was (stores written `MOV`, `MOVS` where a branch reads a load's flags, `r0` for `r7`, the link register, and stack arguments a word nearer), for studies/egret_gui |
| `fonts/` | The fonts, made from DejaVu by `make_fonts.py` (license: `fonts/LICENSE.txt`) |
| `build.py`, `fonts.py`, `run.py`, `png.py` | Building the programs, the fonts as data, running a scene phase by phase, screens as PNG |
| `bench.py` | Report 0019's tables (`reports/0019-report-graphics/performance.md`) |
| `expected/` | Every phase's screen checksum from the host build |

```sh
heron graphics run wm --depth 3 --asm          # a scene, phase by phase (--isa v1a; --stm; --png DIR; --profile)
heron graphics test                            # every scene and depth, both ISAs, C and assembly
heron graphics selftest                        # the kernels against pixel references (host with gcc, and simulator)
heron graphics expected                        # rewrite expected/ from the host build (needs gcc)
heron graphics bench [--write]                 # report 0019's tables (--write: the file, and its screenshots)
heron test graphics                            # the unit tests: all of the above but expected
python3 studies/graphics/fonts/make_fonts.py   # make the fonts again (needs DejaVu and Pillow)
```

## How it works

**The screen** is 640 x 480 in a static array (`fb_mem`); whatever is
written there is taken to be on the screen. A surface is rows of pixels
`pitch` bytes apart, each row starting on a word. Pixel x is bits
`x * bpp` up of its row, counting from bit 0 of the first byte, so a
32-bit word holds 32/bpp pixels in order, the first in the low bits: the
machine is little-endian, and with this order shifting a word moves its
pixels, which the copies and the glyph drawing rely on. (The draft 1
`lines` program puts the first pixel in bit 7 of a byte instead; on a
little-endian machine that order can't be shifted a word at a time.)

**The palettes** are black and white at 1 bit, four greys at 2, the VGA's
16 colours at 4, and xterm's 256 at 8. Anti-aliased text goes through a
ramp of 65 pixel values from the background to the text colour, the
nearest the palette has.

**Kernels.** The library is C. Its inner loops are separate functions,
the kernels, which take a job: a small struct with everything the loop
needs, already clipped and worked out (`FillJob`, `BlitJob`, `ExpandJob`,
`RampJob`, `LineJob`), plus `gfx_span` for the rows of polygons and
ellipses. Every kernel is written in C (`NAME_c`, always built) and in
assembly for each draft. Built with `GFX_ASM`, the library calls the
assembly kernels, which may hand cases they don't cover back to C (blits
other than COPY, opaque expansion, AND). The assembly uses the same
algorithms as the C, except the anti-aliased ramp at 2 and 4 bits, where
it rotates the destination word through the pixels.

**The scenes** call `mark_n(name, count)` at the end of each phase. On the
machine that is a `HALT`; the harness reads the cycles so far in every
configuration, the instructions and the screen's CRC-32, and resumes
(`Machine.resume`, in the bindings). A phase's cost is the difference
from the previous mark. Phases whose names start with `_` are set-up.

**Checking.** The same C, built with gcc on the host, prints every
phase's screen checksum (`expected/`). Every scene at every depth matches
it for 1a, 1b and 2, compiled C and with the assembly kernels. The kernels
are also checked against pixel-at-a-time references at random sizes and
alignments, on the host and on the simulator.

**Fonts.** `sans12` and `mono12` are bitmap fonts rendered from DejaVu
Sans and DejaVu Sans Mono at 12 pixels by FreeType (`fonts/*.txt`, a text
format described at the top of each file); each glyph starts on a word of
the strike. `sans.ttf` is DejaVu Sans cut down to printable ASCII. The
machine parses the TrueType file itself: `cmap` format 4, `loca`, `glyf`
and `hmtx`, the quadratic curves flattened by forward differences, then
filled by the scan converter. Hinting, kerning and composite glyphs are
left out.

**The window manager** keeps no backing store. Each window is drawn
through its visible region, a list of rectangles; moving the top window
copies it and paints what it uncovered; raising paints what was hidden;
scrolling copies what's visible before and after and paints the rest.
The `wm` scene ends with a full repaint, which must come out the same as
the incremental updates before it.

**The store-multiple experiment** (`asm/v1b/stm/`, the `1b stm` build):
the fill and copy kernels with long rows moved 8 words at a time by
`SAVE` and `RESTORE`, with `sp` pointed into the screen. It stands in for
a load- and store-multiple through any register, which neither draft
has. Interrupts must be off; they are in the scenes.
