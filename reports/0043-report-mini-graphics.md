---
number: 43
type: report
title: Graphics software on Heron Mini's video
status: current
date: 2026-10-18
context:
  studies: [mini_gfx, mini, websim]
  commit: efa0498
---

# Report 0043: Graphics software on Heron Mini's video

[RFC 0042](0042-rfc-mini-video.md) proposes Heron Mini's video: seven
modes, three pixel layouts, line descriptors or a frame base, a hardware
cursor, a beam register, three bandwidth options and block instructions.
To find out which of them software needs, [studies/mini_gfx](../studies/mini_gfx/README.md)
wrote a graphics library, a window manager, applications, games and
demos against the mini's simulator ([studies/mini](../studies/mini/README.md)).
Every program builds with the library's kernels in three styles: C alone
(`c`), draft 2 assembly (`asm`), and the assembly using RFC 0042's block
instructions (`blk`).
A fourth, `wif`, adds what-if block instructions to a copy of the
microcode, among them X1. This report answers the RFC's open questions
from that software.

All times are on the simulator, at the RFC's timing; a frame is 16.7 ms
(840,000 ticks). The library's and the window manager's tables are in
[performance.md](0043-report-mini-graphics/performance.md); each
program's own measurements are in the `NOTES.md` in its folder. Most of
the interactive programs also run at the machine's speed in the browser
([studies/websim](../studies/websim/README.md), group "Heron Mini").

## Summary

- **The line descriptors (D0) are the feature that paid most.** Every
  game and half the tools used them for something a frame base can't do:
  scrolling, parallax and split screens for nearly nothing, a racing
  game's road, fixed status lines, a schematic's pan 70× faster, and a
  palette bank per line. Keep D0.
- **Software sprites are what limits the games.** Scrolling and
  backgrounds became cheap; drawing, erasing and copying under moving
  objects took most of every game's frame. Either a sprite mode, or a
  masked copy and a 2-D copy in microcode, would buy the most.
- **The descriptors want a pixel offset and a repeat count in bits
  31–24** (open question 7). Fine scrolling now costs pre-shifted copies
  of everything that scrolls, and every descriptor is written a line at a
  time.
- **B0 is enough.** No program saw an underrun or a stolen cycle in M2 or
  M5 on B0, with the microcode keeping every cycle within 7 ticks.
- **Layouts:** at 1 and 2 bits, L1 is as fast as F1 for everything we
  wrote and L0's chunky order costs up to 3× on shifted copies; at 4 and
  8 bits L0 is right and L1 makes per-pixel work 3.8× slower. F1 bought
  nothing L1 doesn't.
- **The block instructions are worth having:** fills and copies 1.3–2.4×
  faster than assembly, though whole programs gained 15–20% (the window
  manager's composite, the racer's frame), as per-call overhead and
  other work remain. Of X1, EXPAND at 1 and 2 bits (2×) and
  at 8 bits (3.5×) were the most wanted.
- **C1 and P1 are worth their chips.** The cursor moves for 3 µs a frame
  against 1–6 ms for a software one; the beam tells a frame's interrupt
  from a line's and times everything.

## What was written

| Program | Mode | What it explores |
|---|---|---|
| [wm](../studies/mini_gfx/wm/) and [apps/desktop](../studies/mini_gfx/apps/desktop/) | M0, M3–M6 | A window manager: backing stores, a damage list, menus, widgets |
| [apps/editor](../studies/mini_gfx/apps/editor/NOTES.md) | M0, M3–M6 | A text editor in two windows: C's colours, selection, clipboard, search |
| [apps/fsedit](../studies/mini_gfx/apps/fsedit/NOTES.md) | M6 | The same editor full screen, scrolling by descriptors |
| [apps/forms](../studies/mini_gfx/apps/forms/NOTES.md) | M0, M3–M6 | A parts inventory: a sortable, searchable list, forms, a dialog, a chart |
| [apps/schematic](../studies/mini_gfx/apps/schematic/NOTES.md) | M0, M3, M5 | A schematic editor: parts, wires, rubber bands, zoom, pan |
| [games/snake](../studies/mini_gfx/games/snake/NOTES.md), [snake_asm](../studies/mini_gfx/games/snake_asm/) | M1 | Incremental drawing, palette cycling, banners by descriptors; the same game in assembly |
| [games/mines](../studies/mini_gfx/games/mines/NOTES.md) | M0, M3–M6 | Minesweeper with the hardware cursor |
| [games/breakout](../studies/mini_gfx/games/breakout/NOTES.md) | M1 | Small moving objects |
| [games/rocks](../studies/mini_gfx/games/rocks/NOTES.md) | M5, M6 | A vector game: lines only, at 1024 × 768 |
| [games/platformer](../studies/mini_gfx/games/platformer/NOTES.md) | M1 | A side-scroller: parallax bands, fine scrolling four ways |
| [games/racer](../studies/mini_gfx/games/racer/NOTES.md) | M1, M0 | A pseudo-3D road drawn by descriptors, scaled sprites |
| [games/rts](../studies/mini_gfx/games/rts/NOTES.md) | M0, M1 | A strategy game's map: many small units, a scrolling viewport, a HUD |
| [demos/](../studies/mini_gfx/demos/) | M0, M1 | Raster bars, plasma, wobble, rotozoom, bobs, a test card of every mode |

The library ([gfx](../studies/mini_gfx/gfx/)) draws in all nine pixel
formats the modes and layouts make (1, 2, 4 and 8 bits; L0, L1 and F1),
checked against the simulator's decoder in every combination. Its README
says how to write a program.

## The open questions

### 1. Which modes

- **M0 (640 × 480 × 4)** is the general one: the window manager, the
  tools and the strategy game. 16 colours and 16 palette banks were
  enough for every tool, and the spare colours let the forms and the
  editor recolour a selection through a bank, 0.19 ms instead of 4.3 ms.
- **M1 (320 × 480 × 8)** is the games' mode, as 320 × 240 with every
  line shown twice by the descriptors. It was pleasant to program: a byte
  a pixel, 256 colours, half the memory of M2.
- **M2 (640 × 480 × 8)** was used by nothing but the test card. At
  300 KB a screen, a full redraw costs twice M1's, and the games had no
  time to spare.
- **M3 and M4 (640 × 480 × 2 and 1)** worked for the tools but were
  harder: EXPAND covers only 4 bits, so text at 1 and 2 bits is slower
  per pixel than at 4, and the forms wrote their own aligned expansion,
  7× faster than the library's there. X1's EXPAND would have made that
  unnecessary.
- **M5 and M6 (1024 × 768 × 2 and 1)** work for tools and for vector
  graphics. A full redraw is 2.5× M0's pixels, so programs there must
  redraw only what changes; the editor, the forms and the vector game all
  did, and the vector game ran at 60 Hz in both. M6's single colour was
  the tightest limit: palette banks per line gave the editor its caret
  line and status line in colour.

Hardest to program: the 1- and 2-bit modes in L0's chunky order (every
shifted copy and expansion needs four terms rather than two) and the
8-bit modes in L1 (a pixel spread over eight planes).

### 2. L0 or L1, and F1

Shifting a whole screen by a pixel, assembly, ms
([performance.md](0043-report-mini-graphics/performance.md)):

| Bits | linear (F1 at 1 and 2) | L0 | L1 |
|---|---:|---:|---:|
| 1 | 21.3 | 65.0 | 21.3 |
| 2 | 38.8 | 116 | 52.3 |
| 4 | 75.7 | (L0 is linear) | 94.9 |
| 8 | 138 | (L0 is linear) | 184 |

The window manager's composites follow: in M6, L0 takes 1.06× F1's or
L1's time for a full composite, 1.5× for a window moved a pixel. Lines cost the same in
every format (the masks come from tables), and so did the editor's text
and the forms' widgets, once their fonts were arranged for the format.
Per-pixel work at 8 bits is 3.8× slower in L1 (the plasma).

So F1's 8–12 chips buy at most 1.35× over L1 at 2 bits, and nothing at 1
bit. The best of the three would be L0's order at 4 and 8 bits and L1's
at 1 and 2; if that costs no more chips than L1, it's the choice.

### 3. D0 or D1

D0, clearly. What the descriptors did:

| Use | Program | Cost with descriptors | Without |
|---|---|---:|---:|
| Pan a sheet | schematic | 0.96 ms | 66 ms |
| Scroll a line of text | fsedit | 5.3 ms | 9–24 ms (estimated) |
| Fine-scroll a playfield and three parallax bands | platformer | 24% of a frame, all its work | 59% (BLIT k every frame), 76% (redrawn) |
| A pseudo-3D road with hills and curves | racer | 25.4 ms a frame, all its work | 38.7 ms |
| A banner over the playfield | snake | 65 µs | 5–13 ms |
| Scroll a strategy map's viewport | rts | 2% of a frame | a full redraw |
| Line doubling for 320 × 240 | every M1 game | 0 | — |

They also gave fixed status lines and HUDs (their own descriptors and
palette bank), double buffering by TSEL, and per-line palette banks:
raster bars, a sky gradient, the caret's line in M6.

Their cost is the writes: 480 a frame for the platformer (5.3% of a
frame, and assembly is no faster than C), 752 for a scroll in fsedit.

### 4. The cursor

C1 is worth it. Moving it costs 2.9 µs; a software cursor costs
1.1–6 ms a frame and flickers unless it's composed with the screen (the
window manager does, at +0.8 ms a composite). The games used it too: a bird in the platformer (3% of a frame saved), the
vector game's ship, the RTS's pointer. The schematic editor wanted a bigger one, for a
crosshair across the sheet.

### 5. Bandwidth

B0. The bandwidth benchmark, the vector game and the tools saw no
underruns and no stolen cycles in M2 and M5, with the microcode's cycles
all within 7 ticks. B1 and B2 changed no timing in the programs that
tried them.

### 6. X1's block instructions

From the what-if microcode (their lengths estimated, not from static
timing analysis):

| Instruction | Use | Speed-up |
|---|---|---:|
| EXPAND at 8 bits | text at 8 bits (a cell: 154 → 55 µs) | 2.8–3.5× |
| EXPAND at 1 and 2 bits | text in M3–M6 | 1.25–2× |
| BLIT by a bit count | shifted copies at 1 and 2 bits | 1.5–1.7× |
| FILLX (XOR fill, not in X1) | rubber bands, carets | 2.2× |
| EXPANDT (transparent, not in X1) | text over pictures | 1.4× |

The window manager gained least (M5 composite 56 → 52 ms), as its time is
in copies without a shift. EXPAND at 1, 2 and 8 bits is the part of
X1 to keep; it's microcode, so it costs no chips.

### 7. The descriptors' bits 31–24

Four programs asked for the same thing:

- **A pixel offset (bits 26–24 or more):** the line starts that many
  pixels into its first word. The platformer would keep one ring buffer
  instead of four pre-shifted ones, the racer's road and background 8×
  fewer copies; estimated 2–3 chips.
- **A repeat count:** one descriptor for a band of identical or
  consecutive lines (a 16-line text row, a doubled M1 line). fsedit's
  scroll would be 47 writes instead of 752, the platformer's 480 mostly
  gone.

The two compete for the 8 bits: an offset needs 3 bits at 4 bits a
pixel and 5 at 1 bit.

## What else would help, most valuable first

1. **A sprite mode** (the coming "Neo Geo" mode). The bobs demo drew up
   to 187 16 × 16 sprites at 60 Hz in M1 with compiled sprites, 7 with
   the library's masked copy; past ~190 only hardware helps. What the games
   would need from it: about 256 16 × 16 sprites, 48 or more on a line,
   a palette per sprite, X flip (the RTS); scaling (the racer, whose
   sprite art is 738 KB pre-scaled and would be ~20 KB). Hardware sprites
   would save the platformer 13% of a frame on average, 25% at worst.
2. **A masked copy in microcode:** sprites from ~75 to ~30 ticks a word
   (platformer); the RTS's drawing of a unit to ~1200 ticks, of ~5100
   for a unit now.
3. **A 2-D FILL and COPY:** erasing boxes is mostly per-row overhead
   (the vector game estimates 4–6×, the RTS's erase ~800 ticks a unit).
4. **A faster COPY or RFC 0041's copy register:** copies were the
   largest single cost in the window manager, the editor's scroll and the
   racer's scratch lines. The bobs demo estimates up to 43% more sprites
   with the copy register; the platformer, its spare-line copies from 21
   to 14 ticks a word with a 2-cycle COPY.
5. **A sprite window in a descriptor** (a split column with a second
   start address): a window narrower than the screen could scroll by
   descriptors (forms, editor), and the racer's per-line copies under
   sprites would fall from 10 to ~2 ms.
6. **A LINE instruction:** about 3× (800 lines a frame instead of 268).
7. **Interrupts:** a frame's and a line's interrupt have one status bit,
   so a late line handler can swallow a frame; the line interrupt arrives
   ~240 ticks before its line, too late for a palette change before the
   line on hardware. Separate status bits, and an earlier or programmable
   line interrupt, would fix both.
8. **A fifth palette-bank bit** (0–1 chips): the racer and the raster
   bars ran out of banks.

Not needed: a hardware caret (a blink costs 0.3 ms), a character
generator (text costs 40–80 µs a character, and full-page redraws are
rare), B1 or B2.

## Notes for RFC 0042

Sent to its design study as well:

- Does C1 latch its X and Y once a frame? The simulator reads them per
  line, so moving it mid-frame splits it. Latching at the frame's start
  is what software wants.
- C1's colours, 253–255, are bank 15's last three in the 4-bit modes and
  the top three pixel values at 8 bits; the RFC could say so.
- When a TSEL or descriptor change takes effect (the next frame? the next
  line?) isn't specified.
- A line interrupt comes ~240 ticks before its line: a palette written in
  the handler changes mid-line on hardware, though the simulator, which
  draws a line at its start, shows it clean. The simulator also can't
  show tearing.
- The frame's and the lines' interrupts share a status bit (item 7
  above).
- A 256-word COPY holds off interrupts for up to three lines.

## The software

Things found in the software, to fix outside this study:

- **The compiler** multiplies by constants that aren't powers of two with
  `MULS` (a microcoded loop, ~160 ticks) rather than shifts and adds, in
  every indexed loop over a struct; most programs worked around it.
- **C against assembly:** the C kernels are 1.4–8× slower than assembly
  (8× for shifted copies, where the microcode's variable shifts cost a
  cycle a bit and the assembly patches constant shifts into its code). A
  game's logic in C was fine; its kernels weren't. Compiled C was within
  5% of assembly for simple loops (the vector game).
- **The library:** `gfx_line` divides in its setup (4.5K ticks a line),
  `font_cells` at 8 bits uses the C kernel in every variant, `memmove`
  copies overlaps a byte at a time, and the window manager handles every
  queued event before composing, so a fast drag stalls the screen. These
  are noted in the programs' `NOTES.md`.
- **LDM/STM** copies are slower than loads and stores (54 against 34.5
  ticks a word).
