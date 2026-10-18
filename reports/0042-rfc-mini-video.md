---
number: 42
type: rfc
title: Heron Mini's video modes and features
status: open
date: 2026-10-18
context:
  studies: [mini]
  commit: 6a51876
depends-on: [41]
---

# RFC 0042: Heron Mini's video modes and features

Heron Mini's video ([RFC 0041, 9](0041-rfc-heron-mini.md#9-video)) is
one mode, 640 × 480 at 4 bits a pixel, with line descriptors and the
CPU's block instructions. This RFC lists what else it could do: more
modes, other ways of laying pixels out in memory, a hardware cursor, the
descriptors and the blitting as options, each with what it would cost in
chips. None of it is decided. The point is to write graphics software
against all of it and find out which options earn their chips, so every
option here but X1's microcode, M7 and T15 is in the study's simulator
([12](#12-the-simulator)), and a program picks them with registers, as
the hardware would.

Part I specifies the options as a programmer sees them; Part II is what
each costs, where it comes from, and what's left open. The fancier ideas
(a microcode copper, sprites drawn by microcode, a Neo Geo-like game mode,
palette changes within a line) are left for later
([11](#11-later)): they're harder to specify, and the software can start
without them.

## Contents

- [Part I: Specification](#part-i-specification)
  - [1. Overview](#1-overview)
  - [2. Timing](#2-timing)
  - [3. Modes](#3-modes)
  - [4. Pixel layouts](#4-pixel-layouts)
  - [5. Lines: descriptors or a frame base](#5-lines-descriptors-or-a-frame-base)
  - [6. The palette](#6-the-palette)
  - [7. The cursor](#7-the-cursor)
  - [8. Registers](#8-registers)
  - [9. Bandwidth and the CPU](#9-bandwidth-and-the-cpu)
  - [10. Block instructions](#10-block-instructions)
- [Part II: Discussion](#part-ii-discussion)
  - [11. Later](#11-later)
  - [12. The simulator](#12-the-simulator)
  - [13. What each option costs](#13-what-each-option-costs)
  - [14. Open questions](#14-open-questions)

## Part I: Specification

### 1. Overview

Everything as built stays: bank 1 of the RAM (0x0020_0000–0x003F_FFFF,
2 MB) is the video's, read in its slots without holding the CPU; a
256-entry palette of RGB 5:6:5; the control register, the interrupt and
its acknowledge. The options:

| Option | What | Chips (estimate) |
|---|---|---:|
| **M0** | 640 × 480 × 4 | built |
| **M1** | 320 × 480 × 8 | +1–2 |
| **M2** | 640 × 480 × 8 | +1–2 (B0 while cycles stay within 7 ticks, else B1 or B2) |
| **M3**, **M4** | 640 × 480 × 2, × 1 | +1, or nothing with M5 and M6 (the same shifters' chaining) |
| **M5**, **M6** | 1024 × 768 × 2, × 1 | +5–9 and the clock chip (K2) |
| **M7** | 640 × 480 × 3, a palette of 8 colours chosen per 8 pixels from 256 | +2–3 |
| **L0** | the chunky layout | built |
| **L1** | the planar layout | 0 (other wiring), instead of L0 |
| **F1** | 1- and 2-bit pixels linear in L0 | +8–12 |
| **D0** | line descriptors | built (4 chips of RFC 0041's); **chosen** |
| **D1** | no descriptors: a frame base register | −4; not taken |
| **C1** | a 32 × 32 cursor of 2 bits a pixel | +12–14 (other sizes: [13](#13-what-each-option-costs)); **chosen**, its size open |
| **P1** | the beam's position, readable | +2 |
| **B1** | cycle stealing, a second holding register | +5–7 |
| **B2** | bank 1 64 bits wide | +16 |
| **K1**, **K2** | a 65 MHz pixel clock: an oscillator, or a clock chip | K2 **chosen**: the clock chip in place of the oscillators ([RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock)) |
| **T15** | a 15 kHz family for RGB monitors (a Sony PVM) | 0–2 and a timing table; **open** |
| **X0** | `FILL`, `COPY`, `EXPAND`, `BLIT k` | built (microcode) |
| **X1** | their variants for 8-, 2- and 1-bit pixels, and more | microcode only: whichever the software uses |

The modes' mode register and the new registers' decode are another 2
chips, shared by all of them. [13](#13-what-each-option-costs) has where
the numbers come from.

### 2. Timing

Two families, each with a timing table in the timing flash (a 512K part
in the 128K's place holds four):

| | VGA (M0–M4) | XGA (M5, M6) |
|---|---|---|
| Pixel clock | 25.175 MHz, two master ticks | 65 MHz, from the clock chip (K2) |
| A line | 100 characters of 8 pixels: 0–79 the picture, 80–81 the front porch, 82–93 the sync, 94–99 the back porch | 168: 0–127 the picture, 128–130 the front porch, 131–147 the sync, 148–167 the back porch |
| A frame | 525 lines: 0–9 the front porch, 10–11 the sync, 12–44 the back porch, 45–524 the picture | 806: 0–2 the front porch, 3–8 the sync, 9–37 the back porch, 38–805 the picture |
| The rates | 31.47 kHz, 59.94 Hz (16.68 ms a frame) | 48.36 kHz, 60.0 Hz (16.67 ms) |

The syncs are active low in both. The picture's lines come last, so the
picture's end is the frame's.

**T15** (an option, **open**), for a 15 kHz RGB monitor such as a Sony
PVM: the same 100 characters of 8 pixels at half VGA's pixel clock
(12.59 MHz, four master ticks: a line of 63.6 µs, 15.73 kHz), 262 lines
with 240 in the picture (60.05 Hz, progressive), or 525 in two fields for
480 interlaced; the sync composite, which the table's HSYNC bit carries
in this family, active low. Its modes are M0's and M1's with half the
lines: 640 × 240 × 4 and 320 × 240 × 8. The RGB outputs are VGA's
(0.7 V into 75 Ω) as they are; the cable is BNC (R, G, B, sync) or
SCART (with its RGB-select pin held high).

### 3. Modes

A mode is the timing family, the bits a pixel and how wide a pixel is:

| Mode | Picture | Bits | A line's words | The palette index |
|---|---|---:|---:|---|
| **M0** | 640 × 480 | 4 | 80 | 16 × bank + pixel |
| **M1** | 320 × 480 (a pixel two wide) | 8 | 80 | the pixel |
| **M2** | 640 × 480 | 8 | 160 | the pixel |
| **M3** | 640 × 480 | 2 | 40 | 16 × bank + pixel |
| **M4** | 640 × 480 | 1 | 20 | 16 × bank + pixel |
| **M5** | 1024 × 768 | 2 | 64 | 16 × bank + pixel |
| **M6** | 1024 × 768 | 1 | 32 | 16 × bank + pixel |
| **M7** | 640 × 480 | 3, and an 8-bit attribute a word | 80 | 8 × attribute + pixel |

`bank` is the line's palette bank ([5](#5-lines-descriptors-or-a-frame-base)).
M7's `attribute` is the word's own, so each 8 pixels of a line choose one
of 256 palettes of 8 colours (2,048 entries); the line's bank isn't used.
320 × 240 × 8 is M1 with every line shown twice, two descriptors pointing
at the same words.

### 4. Pixel layouts

How a word's bits become pixels follows from how the four shifters
(74F299s, 8 bits each) are loaded and chained. Pixel 0 is the leftmost;
bit 0 is the word's least significant.

**L0, chunky** (as built): shifter k holds bit k of the word's eight
nibbles, nibble 0 first out. Chained for fewer bits a pixel (0 ← 1 ← 2 ← 3
for 1 bit, 0 ← 1 and 2 ← 3 for 2), the rest falls out:

| Bits | Pixels a word | Pixel p is |
|---:|---:|---|
| 4 | 8 | bits 4p…4p+3 |
| 8 | 4 | byte p |
| 2 | 16 | low bit 4·(p mod 8) + ⌊p/8⌋, high bit that + 2 |
| 1 | 32 | bit 4·(p mod 8) + ⌊p/8⌋ |

In M7 shifter 3's byte is the word's attribute: pixel p is bits 4p…4p+2,
and the attribute's bit i is bit 4i + 3 (`w & 0x88888888`, spread out).

At 1 bit, an 8-pixel character cell c is bit c of every nibble, so a
font stored spread out (a row's bits at 0, 4, 8, …) draws with a shift
and a mask: `w = (w & ~(0x11111111 << c)) | (row << c)`. At 2 bits, cell
c is bits c and c + 2 of every nibble.

**F1, linear** (an option on top of L0): at 2 bits pixel p is bits 2p and
2p + 1; at 1 bit, bit p. Multiplexers reorder the holding register's bits
into the shifters by mode.

**L1, planar** (instead of L0): shifter k holds byte k, bit 0 first out,
so byte k is bit plane k of the word's eight pixels:

| Bits | Pixels a word | Pixel p is |
|---:|---:|---|
| 4 | 8 | bit k at 8k + p |
| 8 | 4 | bit i at 8i + 2p for i < 4, 8(i − 4) + 2p + 1 for i ≥ 4 |
| 2 | 16 | low bit p, high bit 16 + p |
| 1 | 32 | bit p |

In M7 pixel p is bits p, 8 + p and 16 + p, and the attribute is byte 3
(`w >> 24`).

L1 makes the 1- and 2-bit modes plain and the 8-bit one scattered; L0
the other way round. They're different wiring of the same chips, so one
or the other, not both (both would be F1's multiplexers again).

### 5. Lines: descriptors or a frame base

**D0, descriptors** (as built, and chosen): picture line y's descriptor is word
T + y of a table at bank 1's word 0, or word 1024 with `TSEL`, read in the
line before's blanking; T is 44 (VGA) or 37 (XGA), the line before the
picture's first.

| Bits | |
|---|---|
| 18–0 | the line's first word, a word address in bank 1 |
| 22–19 | the line's palette bank |
| 23 | an interrupt as the line is set up |
| 31–24 | 0 (**open**) |

The line is the mode's words from there, each word from the next address
(bank 1 wraps at its 2 MB). A descriptor, and `TSEL`, are read in the
line before, as the sync's third character ends (character 84 in VGA,
133 in XGA), so a write to either shows from the first line whose
descriptor is read after it, within the frame being shown.

**D1, a frame base** (instead of D0; not taken): the frame base register gives the
first line's word and the palette bank, the lines follow each other in
memory, and there is no line interrupt. The register is taken as the
frame starts, so a write shows from the next frame.

### 6. The palette

256 entries of RGB 5:6:5 at 0xF000_0400 + 4n, written, not read, as
built; M7's 2,048 at 0xF000_2000 + 4n (the first 256 at both). Outside
the picture the output is black. A pixel's colour is
looked up as it's shown, so a write shows at once, from the pixel the
beam is at: written in the picture, it splits its line. While the CPU
writes it, the palette's address is the CPU's, so the few pixels shown
then have the written entry's colour.

### 7. The cursor

**C1**: a 32 × 32 picture over the frame, 2 bits a pixel: 0 is
transparent, 1–3 are palette entries 253–255 (bank 15's last three in
the 4-, 2- and 1-bit modes, the top three pixel values in the 8-bit
ones, attribute 31's last three in M7). Its rows are 2 words each
(64 bits, pixel p at bits 2p and 2p + 1 of the pair, the first word
pixels 0–15), 32 rows from the cursor base register's word in bank 1,
read in each line's blanking. Its position is its top left corner in the
timing family's own pixels (640 × 480 or 1024 × 768, whatever the mode's
pixel width), a signed 12-bit number in each of the X and Y registers, so
it can hang off any edge. The hotspot is the software's business. Its
position and image are read line by line, with each line's row, so a
move while the picture is shown splits it for a frame: software moves it
at the frame's interrupt (**open**: taking them as the frame starts, a
few chips more).

### 8. Registers

Region 7, on the data bus ([RFC 0041, 7](0041-rfc-heron-mini.md#7-the-io-space)):

| Address | | |
|---|---|---|
| 0xF000_0000 | control, written | bit 0 the picture on, 1 `TSEL`, 2 the interrupt on (as built); 6–4 the mode (0–7: M0–M7); 7 F1; 8 the cursor on (C1); 9 D1 |
| 0xF000_0004 | the interrupt's acknowledge, written | as built |
| 0xF000_0008 | the beam, read (P1) | bits 9–0 the line (0–524, 0–805), 23–16 the character (0–99, 0–167) |
| 0xF000_000C | the frame base, written (D1) | bits 18–0 the first line's word in bank 1, 22–19 the palette bank |
| 0xF000_0010 | the cursor's X, written (C1) | bits 11–0, signed |
| 0xF000_0014 | the cursor's Y, written (C1) | bits 11–0, signed |
| 0xF000_0018 | the cursor's image, written (C1) | bits 18–0, a word address in bank 1 |
| 0xF000_0400 + 4n | palette entry n, written | as built |
| 0xF000_0800 | the interrupt status, read | bit 4 the video's interrupt, as built |

A mode's change takes effect at the next frame. The layout (L0 or L1),
the bandwidth (B0–B2) and the clock chip's (K2) are the board's, not
registers.

The interrupt is set as the picture ends, whether bit 2 is set or not,
and by a line whose descriptor asks; it's seen when the control
register's bit 2 is set, and cleared by the acknowledge (so software
acknowledges before setting bit 2). A line's interrupt comes as its
descriptor is read, 15 characters (240 ticks) before the line starts in
VGA, 34 in XGA: a handler in C writes the palette about 30 characters
into a VGA line, so a change meant for a line's start is asked for by
the line before's descriptor. The frame's interrupt and the lines' share the
status bit and the acknowledge; the beam's position (P1) tells them
apart (**open**: a bit each).

### 9. Bandwidth and the CPU

**B0** (as built): the video reads one word in every CPU cycle's tail
(T2 and the next H0) and all through an I/O access's hold, into a
holding register; the shifters take a word at each word's end. Outside
an I/O access's hold a cycle is 5–7 ticks as the microcode stands (its
length classes are 5, 6 and 7, and every microinstruction that may fetch
a parcel on demand, two ticks more, is in the 5-tick class), so slots
come at least every 7 ticks: every mode, M2's word every 8 ticks
included. That is the microcode's to keep (**open**,
[14](#14-open-questions)): a cycle of 9 ticks or more starves M2. The
CPU never waits.

**B1, cycle stealing:** a second holding register, and when both run low
before a slot comes, the video holds the CPU for two ticks (the hold an
I/O access uses) and reads. It's needed by M2 (a word every 8 ticks) if
cycles may be longer than 7 ticks. The CPU loses the stolen ticks,
none when its cycles are short and the slots keep up.

**B2, a 64-bit bank:** bank 1 as eight 256K × 8 SRAMs, two words a slot
into a 64-bit holding register and eight shifters: every mode within the
slots, none stolen. The CPU still sees 32 bits.

### 10. Block instructions

**X0** (as built, [RFC 0041, 2.1](0041-rfc-heron-mini.md#21-block-instructions)):
`FILL`, `COPY`, `EXPAND` and `BLIT k` in cell `FD`. `FILL` and `COPY`
work on words, so in any mode. They aren't interrupted: an interrupt
waits for the instruction's end, about three lines for a 256-word
`COPY`, 125 characters for a 256-word `FILL`. `BLIT k` rotates by 4k bits: k pixels at 4
bits, k/2 at 8 bits (k even). `EXPAND` writes 4-bit pixels.

**X1** (microcode only, **not in the simulator yet**): `EXPAND` for 8,
2 and 1 bits a pixel, and a `BLIT` shifting by a bit count, so 1- and
2-bit modes can be scrolled and copied at any pixel. Which are worth
writing is for the software to show.

## Part II: Discussion

### 11. Later

Left out until the software here shows what's wanted: a microcode copper
(a microcode task per line, rewriting descriptors or the palette), sprites
composited per line by microcode, a 320 × 240 × 8 game mode redrawn every
frame, palette changes within a line (a split column in the descriptor,
or a bank per 8-pixel column), smooth horizontal scrolling (a pixel
offset in the descriptor), a hardware cursor of other sizes.

### 12. The simulator

The study's simulator (`heron mini sim`, [studies/mini/sim.py](../studies/mini/sim.py)
on the Rust engine in [studies/mini/engine](../studies/mini/engine))
runs the microcode on a register-transfer model of the CPU, a port of
the study's Python model (`rtl.py`) that matches it cycle for cycle and
tick for tick, with the board and every option here except X1, M7 and
T15. A
program picks the mode, the cursor and the descriptors with the
registers of [8](#8-registers); the board's choices (L0 or L1, B0–B2,
the XGA clock) are the simulator's. It runs 10–14 million cycles a
second, about one and a half times the real machine, and writes frames
as PNG files and where the time went. The rules it follows:

- The video starts with the CPU, in M0; a frame's mode, F1, D1 and
  frame base are latched as it starts.
- A line's pixels are read as it starts, from the memory and the
  registers as they are then (the cursor's position and image too), and
  their colours looked up as they're shown: a palette write changes the
  line from the beam's pixel on. Its descriptor (or, with D1, its
  address) is read in the line before, at the end of the sync's third
  character (character 84 in VGA, 133 in XGA).
- The frame's interrupt is set at every frame's end, enabled or not, so a
  program that enables it acknowledges first.
- With the picture off, the lines are black and nothing is read but the
  descriptors, whose interrupts still come. Mode 7 is black.
- The bandwidth: the shifters take a word (two with B2) at fixed times
  through the line, a word's pixels apart; slots come at each CPU
  cycle's end and every two ticks through an I/O access's hold; a line's
  first words are in the holding registers as it starts. A load with no
  word is an underrun with B0 and B2 (counted: the picture would glitch,
  though the simulator still shows the line as it should be), a steal of
  two ticks with B1. With cycles of at most 7 ticks outside I/O holds
  (the microcode as it stands, [9](#9-bandwidth-and-the-cpu)), B0 keeps
  up with every mode in this model, M2 included; the hardware's margins
  (the slot's two ticks, the shifters' load) are a netlist's question.

The simplifications: a line's words are read when the line starts (the
hardware reads them across the line); a palette write takes effect as
its cycle's hold ends, to within a pixel or two, without the written
colour on the pixels shown during it; B1's stealing is counted per
cycle, not per tick.

### 13. What each option costs

- **The register and decode, 2:** the control register as built is three
  bits in a 22V10; the mode bits, the flags and the new registers'
  decode (VA[4:2]) are a register and a GAL, or a second GAL.
- **M1, M2, +1–2:** the shifters still give a nibble a step; a 4-bit
  latch holds a pixel's first nibble, and the palette's address takes it
  where the line's bank goes now. M1 steps once a VGA pixel and takes a
  pixel every two; M2 steps every tick. The video GALs' equations change;
  a 74F299 at 50 MHz is near its limit (74ACT299 if not).
- **M3, M4, +1:** the shifters' serial pins chain them; in 4-bit modes
  the bits shifted in are thrown away at the next load anyway, so only
  the link between shifters 1 and 2 depends on the mode. A GAL or a
  multiplexer forms the palette index's low bits. The fetch rate is the
  timing table's. M5 and M6 need the same chaining and palette index,
  so with them M3 and M4 cost nothing but their timing table.
- **M5, M6, +5–9 and a clock:** a 65 MHz pixel clock (K2 chosen; K1: an oscillator
  and a synchroniser for the hand-over between the clocks, 2–3; K2: a
  programmable clock chip whose outputs, from one PLL, stay in a fixed
  phase, so the hand-over is a schedule and no synchroniser), a pipeline
  register before the palette (15 ns a pixel is too short for the
  multiplexer, the SRAM and the colour register in one), 8–10 ns palette
  SRAMs, faster shifters, and the timing table. M5 needs a word every
  ~12.4 ticks against slots every 7.
- **M7, +2–3:** an 8-bit register that takes the attribute (shifter 3's
  byte) from the holding register as the shifters load the word, and
  holds it for the word's 8 pixels; the palette's address 11 bits (8 ×
  attribute + pixel) where M0's is 8, one more 74F157; the larger palette
  window in the on-board registers' decode; a mode bit. The palette SRAMs
  are 32K × 8, so the room is there. Memory and bandwidth are M0's.
  Granularity 8 × 1 pixels: finer than the NES's 16 × 16 attributes, with
  8 colours a cell where it has 4, from 256 palettes where it has 4.
  `FILL` and `COPY` work as they are; `BLIT k` carries the attribute bits
  along with the pixels, so a copy shifted by other than whole words mixes
  its cells' palettes (copies of whole cells, or the attributes fixed
  after). The alternative, an attribute map apart from the pixels (16
  colours a cell, the attributes fetched in each line's blanking into a
  line buffer, as the Spectrum's and the C64's colour memory), would be
  about 5–8 chips and an eighth more bandwidth.
- **L1, 0:** the holding register's bits reach the shifters in another
  order; the same chips.
- **F1, +8–12:** a 3-way reordering of 32 bits into the shifters (4, 2
  and 1 bit), 16 dual 4-to-1 multiplexers, or fewer with GALs.
- **D1, −4:** RFC 0041's reduction (the table address multiplexers, the
  line mode register, the descriptor loads), for a frame base register.
- **C1, +12–14:** 64 bits of shift register (eight 8-bit shift
  registers), the X compare and the Y count (two GALs), the X, Y and
  image registers (two or three), the row fetch in blanking (the video
  GALs), and the palette index's override (a GAL). The shift registers
  grow with the cursor's width and its bits a pixel; the rest stays
  about 5–6 chips (the Y count a bit wider), and a row is fetched in the
  line's blanking whatever its size:

  | Cursor | A row | Shift registers | Chips |
  |---|---:|---:|---:|
  | 16 × 16, 2 bits | 1 word | 4 | about 9 |
  | 32 × 32, 2 bits | 2 words | 8 | 12–14 |
  | 32 × 32, 1 bit and a mask | 2 words | 8 | 12–14 |
  | 64 × 64, 2 bits | 4 words | 16 | about 22 |
  | 64 × 64, 1 bit | 2 words | 8 | 12–14 |

  The graphics software found 16 × 16 enough for a pointer; a schematic
  editor wanted a larger crosshair, which 1 bit a pixel at 64 × 64 gives
  for the cost of 32 × 32 at 2.
- **T15, 0–2:** a fourth timing table in the timing flash; the pixel
  phase every four master ticks (the video 22V10's equations and a mode
  bit); the composite sync from the table, no gate; an interlaced
  frame's half lines in the table's 525 lines.
- **P1, +2:** two 74541s put the line and character counters on the data
  bus.
- **B1, +5–7:** a second holding register (four 74823s), the steal
  request (a GAL, a term in the clock GAL's hold).
- **B2, +16:** four more SRAMs (eight 256K × 8 in place of four 512K × 8),
  four more 74823s for the holding register, four more shifters, and
  four transceivers so the CPU reads and writes either half.

### 14. Open questions

Decided, by Emily:

- **Modes:** M0, M1, M2, M5 and M6; M3 and M4 as well, as they come
  free with M5 and M6 ([13](#13-what-each-option-costs)).
- **D0,** the descriptors.
- **A cursor** (C1), its size open.
- **The clock chip** (K2), which [RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock)
  has the options for.
- **X1:** microcode is free, so whichever block instructions the
  software uses.

Open:

1. L0 or L1, and whether F1 is worth its chips: to be measured on a
   netlist.
2. B1 or B2 for M2, or a rule that the microcode keeps every cycle
   outside an I/O hold within 7 ticks (as it does now), so that B0
   suffices. The rule binds all future microcode, and breaks silently: a
   microinstruction that fetches on demand in a 6- or 7-tick cycle, or a
   longer length class, starves M2. The microcode's build could check it;
   B1 (5–7 chips) removes it.
3. The cursor's size ([13](#13-what-each-option-costs) has the costs).
4. The descriptors' bits 31–24: a pixel offset or a repeat count, as the
   software asks.
5. The cursor's position and image: read line by line, or taken as the
   frame starts.
6. A status bit for the frame's interrupt and another for the lines'.
7. T15, the 15 kHz family for a PVM ([2](#2-timing)); not in the
   simulator yet.
8. M7, palettes chosen per 8 pixels ([3](#3-modes)); not in the
   simulator yet.

[Report 0043](0043-report-mini-graphics.md) wrote graphics software
against this RFC on the simulator, and answers these from what it
measured. The open tasks (the chosen options in the netlist, the layouts
measured there) are [RFC 0041, 31](0041-rfc-heron-mini.md#31-open-tasks)'s.
