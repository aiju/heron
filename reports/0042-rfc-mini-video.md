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

Heron Mini's video ([RFC 0041, 9](0041-rfc-heron-mini.md#9-video)) began
as one mode, 640 × 480 at 4 bits a pixel, with line descriptors and the
CPU's block instructions. This RFC lists what else it could do: more
modes, other ways of laying pixels out in memory, a hardware cursor, the
descriptors and the blitting as options, each with what it would cost in
chips. Emily has since had most of it built ([1](#1-overview)): seven
modes in two timing families, VGA and XGA, the cursor, the beam's
position and cycle stealing, all in the netlist and checked at chip
level; M7, the planar layout, T15 and X1's microcode are not. Every
option but X1's microcode, M7 and T15 is in the study's software
simulator ([12](#12-the-simulator)), and a program picks them with
registers, as the hardware would, so graphics software can still try
the ones not built.

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

Bank 1 of the RAM (0x0020_0000–0x003F_FFFF, 2 MB) is the video's, read
in its slots without holding the CPU; a 256-entry palette of RGB 5:6:5;
the control register, the interrupt and its acknowledge. The options,
and which the netlist has (`studies/mini/board.py`, checked on the
chip-level simulator, [12](#12-the-simulator)):

| Option | What | Chips | |
|---|---|---:|---|
| **M0** | 640 × 480 × 4 | | built |
| **M1** | 320 × 480 × 8 | | built |
| **M2** | 640 × 480 × 8 | | built |
| **M3**, **M4** | 640 × 480 × 2, × 1 | | built |
| **M5**, **M6** | 1024 × 768 × 2, × 1 | | built: the master clock at 65 MHz while shown |
| **M7** | 640 × 480 × 3, a palette of 8 colours chosen per 8 pixels from 256 | +2–3 | not built (Later) |
| **L0** | the chunky layout, with 1- and 2-bit pixels linear (F1) | | built |
| **L1** | the planar layout | 0, instead of L0 | not built |
| **D0** | line descriptors | | built; **chosen** |
| **D1** | no descriptors: a frame base register | −4 | not taken |
| **C1** | a 32 × 32 cursor of 2 bits a pixel, its rows in memory | 14 | built; **chosen** |
| **P1** | the beam's position, readable | 3 | built |
| **B1** | cycle stealing, a second holding register | 5 | built |
| **B2** | bank 1 64 bits wide | +16 | not built |
| **K2** | the clock chip | | built ([RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock)) |
| **T15** | a 15 kHz family for RGB monitors (a Sony PVM) | 0–2 and a timing table | **open** |
| **X0** | `FILL`, `COPY`, `EXPAND`, `BLIT k` | | built (microcode) |
| **X1** | their variants for 8-, 2- and 1-bit pixels, and more | microcode only | whichever the software uses |

All of it is 87 chips with bank 1's RAM and its buffers (the first
netlist's one mode was 53); [13](#13-what-each-option-costs) has where
they go.

### 2. Timing

Two families, each a timing table in the timing flash (a 512K × 8, by
the family, the line and the character):

| | VGA (M0–M4) | XGA (M5, M6) |
|---|---|---|
| Pixel clock | 25.175 MHz, two ticks of the 50.35 MHz master clock | 65 MHz: the master clock itself, switched to 65 MHz while an XGA mode is shown |
| A line | 100 characters of 8 pixels: 0–79 the picture, 80–81 the front porch, 82–93 the sync, 94–99 the back porch | 168: 0–127 the picture, 128–130 the front porch, 131–147 the sync, 148–167 the back porch |
| A frame | 525 lines: 0–9 the front porch, 10–11 the sync, 12–44 the back porch, 45–524 the picture | 806: 0–2 the front porch, 3–8 the sync, 9–37 the back porch, 38–805 the picture |
| The rates | 31.47 kHz, 59.94 Hz (16.68 ms a frame) | 48.36 kHz, 60.0 Hz (16.67 ms) |

The syncs are active low in both. The picture's lines come last, so the
picture's end is the frame's.

While an XGA mode is shown the whole machine runs on the 65 MHz clock:
the CPU too, its microinstructions in their own length classes at that
tick ([RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock)), about as fast
as at 50.35 MHz. So the video is synchronous to one clock in both
families, with no hand-over between clock domains. The family changes as
a frame starts; the clock switches during its first, blank, line.

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
(74F299s, 8 bits each) are loaded and read. Pixel 0 is the leftmost;
bit 0 is the word's least significant.

**L0** (as built): shifter k holds bit k of the word's eight nibbles,
nibble 0 first out, so the four shifters' outputs are a nibble at a
time. The pixel registers (three 22V10s) take a pixel from them by the
mode: a nibble; two nibbles, the low one first through a nibble
register; the outputs in pairs (bits 0–1 of the nibble, then 2–3); or
one at a time. So in every mode a word's pixels are linear, pixel 0 in
the low bits:

| Bits | Pixels a word | Pixel p is |
|---:|---:|---|
| 4 | 8 | bits 4p…4p+3 |
| 8 | 4 | byte p |
| 2 | 16 | bits 2p and 2p+1 |
| 1 | 32 | bit p |

This is F1's layout, without F1's multiplexers: picking among the
shifters' outputs is the pixel registers' doing, so the 1- and 2-bit
modes need no other chips, and there is no F1 bit to set.

(The first netlist's chunky 1- and 2-bit layout, an 8-pixel character
cell at bit c of every nibble, isn't built.)

**L1, planar** (instead of L0, not built): shifter k holds byte k, bit 0
first out, so byte k is bit plane k of the word's eight pixels:

| Bits | Pixels a word | Pixel p is |
|---:|---:|---|
| 4 | 8 | bit k at 8k + p |
| 8 | 4 | bit i at 8i + 2p for i < 4, 8(i − 4) + 2p + 1 for i ≥ 4 |
| 2 | 16 | low bit p, high bit 16 + p |
| 1 | 32 | bit p |

In M7 (not built) L0's pixel p would be bits 4p…4p+2 and the attribute
bit i bit 4i + 3; L1's pixel p bits p, 8 + p and 16 + p, the attribute
byte 3.

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
line before, as character 85 ends in VGA (the sync's fourth), 133 in XGA,
after the cursor's two words ([7](#7-the-cursor)); so a write to either
shows from the first line whose descriptor is read after it, within the
frame being shown.

**D1, a frame base** (instead of D0; not taken): the frame base register gives the
first line's word and the palette bank, the lines follow each other in
memory, and there is no line interrupt. The register is taken as the
frame starts, so a write shows from the next frame.

### 6. The palette

256 entries of RGB 5:6:5 at 0xF000_0400 + 4n, written, not read; M7's
2,048 (not built) would be at 0xF000_2000 + 4n. Outside the picture the
output is black. A pixel's colour is looked up as it's shown, so a write
shows at once, from the pixel the beam is at: written in the picture, it
splits its line. While the CPU writes it, the palette's address is the
CPU's, so the few pixels shown then have the written entry's colour.

The palette is two copies of the 256 entries, which the CPU writes at
once: E's, which VGA's pixels and XGA's even ones look up, and O's,
XGA's odd ones. So each lookup has two ticks, where XGA's 15.4 ns pixel
is too short for a 22V10, a 12 ns SRAM and a register one after another
(about 19 ns).

### 7. The cursor

**C1** (built): 32 pixels wide, 2 bits a pixel: 0 is transparent, 1–3
are palette entries 253–255 (bank 15's last three in the 4-, 2- and
1-bit modes, the top three pixel values in the 8-bit ones). Each line has
its own row of it, in two tables in bank 1 laid out as the descriptors'
are: picture line y's pixels 0–15 at word 2048 + T + y, 16–31 at word
3072 + T + y (pixel k at bits 2k and 2k + 1 of the pair), read in the
line before's blanking, before its descriptor. Software writes the
cursor's rows into the tables of the lines it covers and zeros
elsewhere: moving it up or down is 64 words written (the old rows
cleared, the new written). Its height is any: each line's row is its
own, so the 32 pixels at the cursor's X can show something different on
every line.

Its left edge is the X register's, a beam position: the cursor's first
pixel is XSTART pixels after the pixel the register names (VGA 1, XGA 4),
the pixel counted from the line's start (0–799 in VGA, 0–1343 in XGA), so
for a cursor at x the register is (x − XSTART) mod the line's pixels,
from −32 to the picture's width: the cursor can hang off either edge. In
XGA x is even (the register's bit 0 is ignored). The position is in the
family's own pixels (640 or 1024 wide), whatever the mode's pixel width.

The hotspot is the software's business. The X register and the tables
are read line by line, so a move while the picture is shown splits it
for a frame: software moves it at the frame's interrupt.

### 8. Registers

Region 7, on the data bus ([RFC 0041, 7](0041-rfc-heron-mini.md#7-the-io-space)):

| Address | | |
|---|---|---|
| 0xF000_0000 | control, written | bit 0 the picture on, 1 `TSEL`, 2 the interrupt on, 6–4 the mode (0–7: M0–M6; 7 is black), 8 the cursor on |
| 0xF000_0004 | the interrupt's acknowledge, written | any value |
| 0xF000_0008 | the beam, read (P1) | bits 9–0 the line (0–524, 0–805), 23–16 the character (0–99, 0–167): the line a half read at 0xF000_0008, the character a byte read at 0xF000_000A (a word read's bits 31–24 aren't driven) |
| 0xF000_0010 | the cursor's X, written | bits 10–0, a beam position ([7](#7-the-cursor)) |
| 0xF000_0400 + 4n | palette entry n, written | RGB 5:6:5 |
| 0xF000_0800 | the interrupt status, read | bit 4 the video's interrupt |

A mode's change takes effect at the next frame, its family too (and the
master clock with it); the picture's, the interrupt's and the cursor's
bits at once. So a write that turns the picture on and changes the mode
shows a frame in the old mode first: software sets the mode a frame
before it turns the picture on, or blanks that frame. The layout and the bandwidth (B1) are the board's,
not registers.

The interrupt is set as the picture ends, whether bit 2 is set or not,
and by a line whose descriptor asks; it's seen when the control
register's bit 2 is set, and cleared by the acknowledge (so software
acknowledges before setting bit 2). A line's interrupt comes as its
descriptor is read, 14 characters (224 ticks) before the line starts in
VGA, 34 in XGA: a handler in C writes the palette about 30 characters
into a VGA line, so a change meant for a line's start is asked for by
the line before's descriptor. The frame's interrupt and the lines' share
the status bit and the acknowledge (tentatively decided); the beam's
position (P1) tells them apart.

### 9. Bandwidth and the CPU

The video reads a word in every CPU cycle's tail (T2 and the next H0) and
all through an I/O access's hold, into one of two holding registers if
one is free; the shifters take the older at each word's end. Outside an
I/O access's hold a cycle is 5–7 ticks as the microcode stands (VGA's
length classes; XGA's are 6–8 ticks of the faster clock), so slots come
at least every 7 ticks (8 in XGA): every mode, M2's word every 8 ticks
included, with no help (**B0**).

**B1, cycle stealing** (built): when a picture's line finds both holding
registers empty as a cycle's T1 starts, the clock generator holds T2 two
ticks more: the video's slot is four ticks and brings two words. The
CPU's cycle is two ticks longer; nothing else about it changes. So the
microcode isn't bound to short cycles: M2 is fed whatever the cycles'
length. With the length classes as they are no steal happens.

**B2, a 64-bit bank** (not built): bank 1 as eight 256K × 8 SRAMs, two
words a slot into a 64-bit holding register and eight shifters: every
mode within the slots, none stolen. The CPU still sees 32 bits.

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

**A line buffer, for sprites** (a sketch; estimates, nothing measured).
A Neo Geo-like game mode, sprites and no background or sprites over
one, rests on a line buffer: two small fast SRAMs, ping-ponged, one
shown while the next line is drawn into the other, each line's pixels (8
bits: a sprite's 4-bit palette and its 4-bit pixel) cleared as they're
shown (a read and a write in a pixel's time: 80 ns at 320 wide), so each
line starts empty. About 10–12 chips with their address multiplexers,
buffers and a 22V10. What it gives:

- **Sprites without a framebuffer's redraw:** only the sprites are drawn,
  a line at a time, into a buffer that clears itself; no erasing, no
  double buffering, no tearing, and bank 1's picture isn't touched.
- **Sprites over a background,** for 2–3 chips more: the line buffer's
  pixel where it isn't 0, else the framebuffer's (M1 at 320 × 240 × 8,
  say); a palette per sprite.
- **The display apart from bank 1's bandwidth:** fine horizontal scroll
  (the read starting at an offset), a line stretched, a floor rotated and
  scaled a line at a time (the SNES's mode 7) drawn by microcode.

Who fills it, in three strengths:

1. **Microcode,** about 10–14 chips with the buffers: a write port on
   the data bus at memory speed, its byte enables from the pixels so that
   a transparent one isn't written. A block instruction draws a sprite's
   row: two words of 4-bit pixels read, expanded to bytes with the
   sprite's palette, aligned, four words written; about 15–20 cycles a
   16-pixel row. At 320 × 240 a buffer line lasts two VGA lines, about
   500 cycles: some 25–30 sprites a line with all of the CPU, half that
   with half. A microcode task ([RFC 0041, 21](0041-rfc-heron-mini.md#21-microcode-tasks))
   woken as the buffers swap would fill it.
2. **Microcode and helpers:** the write address counting itself, the X,
   flip and palette in registers, the 4-to-8-bit expansion in hardware;
   perhaps twice the rate for 6–10 chips more.
3. **A sprite engine** (the Neo Geo's, small): a sprite attribute RAM
   walked each line against its Y, a pattern RAM of its own (not bank 1),
   the pixels written into the line buffer at 25 MHz: about 48 sprites of
   16 pixels a VGA line (96 with 16-bit writes), as report 0043's games
   wanted; shrinking by skip tables, 5–10 chips more. About 45–60 chips
   with the buffers: a board of its own. The CPU writes tables.

The first is the cheap experiment, and its line buffer is most of what
the third needs, so the engine could follow behind the same buffers if
microcode proves too slow.

### 12. The simulator

Two simulations check this RFC: the netlist on the chip-level simulator,
and a faster model for software.

**The netlist** (`heron mini hw video --modes`): `sw/hw/modes.s` in each
of M0–M6, sixteen rows of pseudo-random words under 480 or 768
descriptors with all sixteen palette banks, 256 palette colours and the
cursor's 32 rows (in XGA hanging off the right edge), its frames captured
from the netlist's outputs and compared pixel for pixel with what the
memory and the registers make (`studies/mini/video.py`'s `render`): every
mode as the memory makes it, the clock switching to 65 MHz for M5 and
M6, no timing violation, at the datasheets' worst-case delays. With the
length classes made longer (9–12 ticks, `--lengths`), M2 needs the
steals, and still shows as it should.

**The software's simulator** (`heron mini sim`, [studies/mini/sim.py](../studies/mini/sim.py)
on the Rust engine in [studies/mini/engine](../studies/mini/engine))
runs the microcode on a register-transfer model of the CPU, a port of
the study's Python model (`rtl.py`) that matches it cycle for cycle and
tick for tick, with the board and the options here but X1, M7 and T15. A
program picks the mode, the cursor and the descriptors with the
registers of [8](#8-registers); the board's choices (L0 or L1, B0–B2,
D1) are the simulator's. It runs 10–14 million cycles a second, about
one and a half times the real machine, and writes frames as PNG files
and where the time went. The rules it follows:

- The video starts with the CPU, in M0; a frame's mode is latched as it
  starts.
- A line's pixels are read as it starts, from the memory and the
  registers as they are then (the cursor's tables and X too), and
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
  two ticks with B1.

Where it differs from the netlist: XGA's CPU runs at 50.35 MHz in the
model (a 65 MHz pixel as 1007/1300 of a tick), where the netlist runs the
whole machine at 65 MHz with XGA's length classes, so the model's CPU
is a little slower there than the machine; a line's words are read when
the line starts (the hardware reads them across the line); a palette
write takes effect as its cycle's hold ends, to within a pixel or two,
without the written colour on the pixels shown during it; B1's stealing
is counted per cycle, not per tick; and the descriptor is read one
character earlier in VGA.

### 13. What each option costs

As built, the video is 87 chips with bank 1's RAM (53 for the first
netlist's one mode):

| Part | Chips | |
|---|---:|---|
| Timing | 9 | the pixel and character counters (22V10), the line and character counters (five 74ACT163), the timing flash (512K × 8) and its register, the slot and line controls (22V10) |
| Registers | 8 | the control register and the frame's mode (two 22V10s), their decode (22V10), the cursor's X (two 74ABT377), the beam (three 74ABT541: P1) |
| Fetch | 19 | VAD (five 74ACT163) and its multiplexer (three 74F157), two holding registers (eight 74ABT823: B1 is four of them), the queue's control and the steal (22V10), the events (22V10), the line's bank (74ABT377) |
| Output | 23 | the shifters (four 74F299), the sequencer and the pixel registers (four 22V10s), the palette's two copies (four 12 ns SRAMs), their address multiplexers (four 74F157) and write buffers (four 74ABT541), the colour register (three 22V10s) |
| Cursor | 13 | its lanes (eight 74F299), the X compare (two 74F521), its control (two 22V10s) and a gate package |
| Bank 1 | 15 | four 512K × 8 SRAMs, their address buffers (six 74ABT541) and data transceivers (four 74ABT245), the fast write strobe's flip-flops |

Against the first netlist's one mode: the modes and the linear pixels
cost the sequencer, the pixel registers and LN (four 22V10s in place of
nothing) and the timing flash's family; XGA the palette's second copy
(two SRAMs, two multiplexers, two buffers) and the colour register's
22V10s in place of two 74ABT823s, and the clock chip's switch
([RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock), five chips, not
counted here); B1 five (the second holding register, the queue's
22V10); the cursor 13 and its X register two; P1 three.

What the options not built would cost, as estimated before:

- **M7, +2–3:** an 8-bit register that takes the attribute (shifter 3's
  byte) as the shifters load the word, and holds it for the word's 8
  pixels; the palette's address 11 bits (8 × attribute + pixel) where
  M0's is 8; the larger palette window in the on-board registers' decode.
  The palette SRAMs are 32K × 8, so the room is there. Memory and
  bandwidth are M0's. Granularity 8 × 1 pixels: finer than the NES's 16
  × 16 attributes, with 8 colours a cell where it has 4, from 256
  palettes where it has 4. `FILL` and `COPY` work as they are; `BLIT k`
  carries the attribute bits along with the pixels, so a copy shifted by
  other than whole words mixes its cells' palettes. The alternative, an
  attribute map apart from the pixels (16 colours a cell, the attributes
  fetched in each line's blanking into a line buffer, as the Spectrum's
  and the C64's colour memory), would be about 5–8 chips and an eighth
  more bandwidth.
- **L1, 0:** the holding register's bits reach the shifters in another
  order; the same chips, but the pixel registers' selections for 1 and 2
  bits change.
- **D1, −4:** the table address multiplexers, the line mode register,
  the descriptor loads, for a frame base register.
- **Other cursor sizes:** the lanes grow with the cursor's width and its
  bits a pixel, the rest stays: 16 × 2 bits four 74F299s fewer, 64 × 2
  bits eight more, 64 × 1 bit the same as now (its height is the
  software's, from the tables).
- **B2, +16:** four more SRAMs (eight 256K × 8 in place of four 512K ×
  8), four more 74ABT823s, four more shifters, four transceivers so the
  CPU reads and writes either half.
- **A RAMDAC** (a Bt476/ADV476/IMSG176-class palette and DACs in one
  chip, 66 MHz or faster, the early-1990s SVGA cards' way): in place of
  the palette's two copies, their multiplexers and buffers and the colour
  register, about −13 chips; but RGB 6:6:6 written through an index
  register and three bytes, not RGB 5:6:5 in one word, and from surplus
  stock. **Open.**
- **T15, 0–2:** a third timing table; the pixel phase every four master
  ticks (V1's equations and a mode bit); the composite sync from the
  table; an interlaced frame's half lines in the table's 525 lines.

### 14. Open questions

Decided, by Emily:

- **Modes:** M0, M1, M2, M5 and M6; M3 and M4 as well, as they come
  free with M5 and M6. **Built.**
- **D0,** the descriptors. **Built.**
- **A cursor** (C1), 32 × 32 × 2. **Built.**
- **The clock chip** (K2), which [RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock)
  has. **Built.**
- **X1:** microcode is free, so whichever block instructions the
  software uses.
- **Tentatively:** the cursor's position and image read line by line
  (as built); one status bit for the frame's interrupt and the lines'
  (as built).

Resolved in the netlist, for Emily to confirm:

1. **L0, with F1's linear 1- and 2-bit pixels,** at no cost: the pixel
   registers pick among the shifters' outputs ([4](#4-pixel-layouts)).
   Every mode's pixels are linear, pixel 0 in the low bits.
2. **B1 built,** so the microcode isn't bound to cycles of 7 ticks or
   fewer ([9](#9-bandwidth-and-the-cpu)).
3. **XGA with the whole machine at 65 MHz,** not a synchronised
   hand-over between clocks: the CPU is as fast there, and the video is
   on one clock ([2](#2-timing)).
4. **The palette in two copies,** for XGA's 15.4 ns pixel; a RAMDAC is
   the other way ([13](#13-what-each-option-costs)).
5. **The cursor's rows from tables in memory,** a line's row in two
   words beside its descriptor, in place of a Y register and an image
   address: fewer chips (no Y compare, no row counter, no image
   register), any height, and a different shape on every line if the
   software likes; moving it up or down is 64 words written. The X
   register is a beam position (XSTART pixels before the cursor).

Open:

1. The descriptors' bits 31–24: a pixel offset or a repeat count, as the
   software asks.
2. T15, the 15 kHz family for a PVM ([2](#2-timing)); not in the
   simulator yet.
3. M7, palettes chosen per 8 pixels ([3](#3-modes)); not built.
4. A RAMDAC in place of the palette's copies.

[Report 0043](0043-report-mini-graphics.md) wrote graphics software
against this RFC on the simulator, and answers these from what it
measured. The open tasks (the chosen options in the netlist, the layouts
measured there) are [RFC 0041, 31](0041-rfc-heron-mini.md#31-open-tasks)'s.
