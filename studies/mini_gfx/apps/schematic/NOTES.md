# Schematic: notes

A schematic editor on the window manager, for M5 (1024 × 768 × 2) above
all. Times are ms (a frame is 16.7) or ticks of 19.86 ns, measured with
`bench.c`: the `asm` variant at M5 in L0 unless it says otherwise.
`measure.py --write` runs the whole matrix (variants × M5/M6/M0 × L0/F1/L1)
into `results.md`; it takes about half an hour, and wasn't run to the end
here.

## What it is

```sh
heron mini_gfx run apps/schematic [--variant c|asm|blk] [--layout L1]   # M5, the script
heron mini_gfx run apps/schematic --poke sch_mode=6                    # M6, same script
heron mini_gfx run apps/schematic --poke sch_mode=0 --frames 130 --script studies/mini_gfx/apps/schematic/m0.script
heron mini_gfx run apps/schematic --poke bench=1 --script /dev/null    # the measurements
```

A **Parts** window (Select, Wire, Net, zoom, Grid; resistor, capacitor,
NAND, NOR, inverter, DIP-14 with pin numbers, connector, LED, ground,
supply) and a **canvas** with a dot grid and a status line. It starts with
an original blinker: a 74HC132 Schmitt-NAND RC oscillator buffered into an
LED, the package with its decoupling capacitor, a power connector (17
parts, 25 wires). Symbols are lines, arcs (circle inside a box), circles
and pins in quarter grid steps, drawn once per zoom and rotation into 1-bit
sprites; labels are sans12 (zoom 3–4) or a 3 × 5 font of its own, put
together as one cached bitmap each. Place (ghost follows the grid; R
rotates), wires across-then-down with a rubber band, junction dots,
select by click or XOR rectangle, move with the wires on the moved pins
stretching and made orthogonal on the drop, Del, net highlight (status
line lists its pins), pan (arrows, right drag), zoom 1–4 (4–16 px a grid
step), and F: the **sheet view**, the whole sheet in bank 1 panned by the
descriptors. Keys B, V, G, C switch the overlay's drawing, sprites/lines,
grid, cursor ghost. Files: `schematic.c` (UI), `sheet.c` (model),
`symbols.c`, `view.c` (canvas, overlay, pan, zoom), `xpand.c`/`.s` (1-bit
expansion into 1/2-bit pixels, lines down), `spfill.s` (SAVE/RESTORE
experiment), `sheetview.c`, `sch_wm.c` (wm.c + `wm_cursor`), `bench.c`,
`measure.py`.

## How it uses the video

- **Modes:** M5 is the CAD mode: paper, grid, ink, selection (also the
  highlighted net: only four colours). M6: selection in reverse, nets
  thick. M0: 16 colours but a small view (zoom 2).
- **Palette:** the editor's four colours in all banks at 2 bits; the
  cursor's colour 255 is the selection's blue (a blue ghost even in M6).
  Palette banks unused: they are per line, a schematic's colours per thing.
- **Layouts** matter only for shifted copies (L0 chunky: C, 4 terms) and
  for 1-bit expansion (PL2 needs no table). Fills and lines are equal.
  Pans in whole words and a word-aligned canvas avoid the shifted copies.
- **Descriptors:** the WM uses one table; the sheet view a split (top 22
  lines from the WM's framebuffer, the rest from a 1920 × 1440 bitmap) and
  both tables, flipped with TSEL.
- **Cursor (C1):** arrow, crosshair (centre hotspot), and the placed part
  itself when it fits 32 × 32, its hotspot moved each frame to snap it.
- **P1** for timing only. **B0:** no underruns or steals anywhere.
- **Block instructions:** FILL clears, COPY composes; EXPAND and BLIT k are
  4-bit only, useless for 2- and 1-bit sprites, labels, ghosts.

## Implementations and measurements

| Operation | c | asm | blk |
|---|---:|---:|---:|
| full canvas redraw (860 × 727, 17 parts) | 82.0 | 46.4 | 37.0 |
| the sheet view's whole sheet (1920 × 1440) | 199 | 115 | 68 |

Redraw at asm: clearing 17.4, parts 16.5, labels 9.6, grid 2.6, wires
1.9, dots 1.4. In blk my 2-bit expansion is 45% of it, the fill 19%.

| asm, M5 L0 | ms |
|---|---:|
| the whole canvas to the screen (WM) | 29.2 |
| wire band a frame: XOR in store + WM copy / on screen / redrawn | 0.4 + 1.6 / 0.6 + 0.1 / 3.9 + 1.6 |
| dragging 3 parts a frame (XOR ghost + bands) / the drop | 4.0 + 1.0 / 23–29 |
| pan by 48 px in the window: copy + strips / WM | 36.8 / 29.3 |
| pan by 12 px (shifted copy, L0 chunky: C kernel) | 822 |
| pan in the sheet view (descriptors rewritten) | 0.96 |
| zoom (sprites 6–16 ms + redraw) | 41–85 |
| 100 lines of 200 px: across / down (library fill) / diagonal | 4.7 / 59.6 / 58.2 |
| "74HC132": glyph by glyph / put together / cached / 3 × 5 | 2.17 / 1.99 / 1.26 / 0.65 |
| 4 copies (68 parts, 100 wires): junctions / a net / redraw zoom 2 | 120 / 261 / 78 |

A part from its sprite vs its lines (µs): NAND 1396 vs 2003, NOR 1453 vs
5286, DIP-14 3341 vs 6219, ground 701 vs 318. The library's C expansion
took the NAND 3365 (≈970 ticks a word), mine ≈400.

Ticks a word: fill C 37.8, asm 21.7, **SAVE with sp borrowed 13.9**, FILL
8.6; copy C 50, asm 36.8, **RESTORE+SAVE 23.7**, COPY 20.6.

## What worked well

Sprites per zoom and rotation; labels as cached bitmaps; regions redrawn
from the model and damaged (the grid one copy with a pitch-0 source);
XOR overlays in the store (2 ms a frame); the hardware cursor as the
placing ghost (free); the sheet view (pans 0.96 ms against 66); words
everywhere (aligned canvas, word pans).

## What was hard or didn't work

Memory-bound basics: a clear is 17 ms, a composition 29 ms, so any full
redraw or window pan is 3–4 frames. 1-bit expansion into 2/1-bit pixels
is C in the library and no XOR. L0's chunky shifted copies (822 ms). Four
colours: selection = highlight. XOR artefacts. Lines down through the
fill: 3 µs a pixel. O(n²) junctions and nets (not video). The WM can't
set the cursor, gives no hover, has no hook after compose.

## What would have helped

- **EXPAND for 2 and 1 bits (X1):** parts+labels are ~26 of 46 ms of a
  redraw (45% in blk); a microcoded 2-bit EXPAND (~60 ticks for 16 px
  against ~400) would take ~20 ms off.
- **Descriptors (D0):** pans 70× cheaper with a big bitmap; D1 can't (no
  pitch, no split). A **pixel offset** in bits 31–24 would make them
  smooth across.
- **FILL/COPY:** clear 17 → ~7 ms, compose 29 → ~16; but SAVE/RESTORE in
  plain code gets 1.6× and 1.55× over today's asm, within 15% of COPY.
- **A bit-shift BLIT (X1)** only for pans by pixels and one-image ghosts;
  word pans make it unnecessary here.
- **A 64 × 64 cursor:** most parts' ghosts at zoom 3 for free; a
  crosshair mode in C1 (a GAL) for the CAD crosshair.
- **More colours at XGA:** wanted (selection ≠ highlight), but a 4-bit
  XGA mode doubles every clear and copy and needs B2.
- **LINE in microcode, XOR FILL:** little here (sprites cached, band
  calls dominated by set-up); a fast vertical line in the library: yes.

## Issues found

1. `build.py`'s object cache ignores the program's own headers: change
   `sch.h`, and unchanged `.c` files keep stale struct layouts silently
   (here the redraw time read 0). Hash every include directory's headers.
2. The WM can't set the cursor's image or hotspot; `sch_wm.c` adds
   `wm_cursor(img, hx, hy)` (3 lines in wm_init/wm_frame) to fold in.
3. The WM gives windows no mouse moves without a button (hover needs
   `mouse_x` in the tick), and no hook after composition (screen overlays
   must pause a frame when damage covers them).
4. The library: 1-bit expansion at 1–2 bits is C (~970 ticks a word), no
   XOR; L0 chunky shifted copies and all XOR copies are C; a line down is
   a 1-pixel fill (~150 ticks a row); fills/copies could use SAVE/RESTORE.
5. RFC 0042: TSEL's timing is unspecified; the simulator reads it per
   descriptor, so a flip after the frame interrupt races line T. Latch it
   at the frame start.
6. `vram_alloc` can't free; `video_ticks` divides at XGA.

## Screenshots

The script's shots (M5): `start`; `place_ghost` (XOR ghost under the
crosshair); `place_rotated`; `place_cursor` (ground as the hardware
cursor); `wire_band`; `wired`; `select_rect`; `selected`; `moving` (ghost
and stretching wire); `moved`; `net` (OSC lit, pins listed); `deleted`;
`panned`; `zoom2`, `overview`, `zoom4`, `back`; `sheet_view`,
`sheet_panned`, `sheet_band` (descriptor-panned sheet, WM strip on top);
`back_from_sheet`. M6: the same in 1 bit (reverse selection, thick
nets). `m0.script`: `m0_start`, `m0_net`, `m0_selected` in 16 colours.
