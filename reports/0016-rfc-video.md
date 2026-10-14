---
number: 16
type: rfc
title: Video
status: open
date: 2026-10-13
context:
  studies: [v1b_hw]
  commit: a14eeb2
depends-on: [9, 14]
---

# RFC 0016: Video

A proposal for the machine's video: what the screen is for, which monitors
it drives, where its memory lives, and a menu of features with rough chip
costs to choose from. It starts from the video notes in
[RFC 0009, section 3](0009-rfc-ideas-io.md#3-video) but doesn't hold to
them; [section 13](#13-against-rfc-0009) lists where it differs.

Statuses: **recommended**, **open** (a real choice either way),
**optional** (an add-on that can come later without changing the rest) and
**not recommended**. Nothing here is decided.

Chip counts are rough estimates, give or take a quarter: 74AC, 74F and
74HCT logic plus SRAMs and flash ROMs, without PLDs. If GALs are allowed
(not decided), the control logic shrinks by roughly a third.

## Contents

1. [Summary](#1-summary)
2. [What the screen is for](#2-what-the-screen-is-for)
3. [Monitors and timing](#3-monitors-and-timing)
4. [Video memory](#4-video-memory)
5. [Pixels and colour](#5-pixels-and-colour)
6. [Scrolling, page flipping and interrupts](#6-scrolling-page-flipping-and-interrupts)
7. [Blitter](#7-blitter)
8. [Display lists: a copper](#8-display-lists-a-copper)
9. [Sprites and tiles](#9-sprites-and-tiles)
10. [Small extras](#10-small-extras)
11. [Cost, board space and stages](#11-cost-board-space-and-stages)
12. [Simulate first](#12-simulate-first)
13. [Against RFC 0009](#13-against-rfc-0009)
14. [Open questions](#14-open-questions)

## 1. Summary

One card with its own video memory, built in stages:

| Stage | What it adds | Chips | Status |
|---|---|---:|---|
| 1. Base card | 2 MB of 32-bit VRAM; 640×480 and 320×240 bitmaps at 1, 2, 4 or 8 bits per pixel through a 256-colour palette; VGA and 15 kHz (PVM) timing; hardware scrolling, page flipping, vertical-blank and line interrupts | ~70 | **recommended** |
| 2. Blitter | Rectangle fills and copies inside VRAM, with transparency and 1-bit-to-colour expansion, about 15 times the CPU's speed | ~50–55 | **recommended** |
| 3. Copper | A list in VRAM of register writes at chosen lines: split screens, mode bands, per-line palette and scroll | ~15–20 | **recommended** |
| Sprites | A line-buffer sprite engine for the 320-wide modes, 16–32 sprites per line | ~35–45 | **open** |
| Tiles and text | A scrolling tile layer, with a text mode as a special case | ~25–35 | **open** |
| Extras | Interlace, light pen or gun, 16-bit colour, composite out, high-resolution mono | 0–4 each | **optional** |

Stages 1–3 come to about 135–145 chips. Everything on the menu is about
200–220, as many as the draft 1b CPU (213).

The questions this RFC was asked, briefly:

| Question | Answer here |
|---|---|
| Resolution? | 640×480 at 60 Hz as the base, plus 320×240 for games: pixel- and line-doubled on a VGA monitor, native on a PVM. Higher-resolution monochrome modes are **open** ([3.5](#35-higher-resolutions)) |
| VRAM on the card? | Yes, and it's close to forced: the bus can't carry 18–25 MB/s of display data, and main RAM is private to the CPU board ([4.1](#41-on-the-card)) |
| Display lists? | Yes, as a copper: register writes at chosen lines, ~15–20 chips. Because the mode, start address, scroll and palette are all registers, it also does what ANTIC-style mode bands do ([section 8](#8-display-lists-a-copper)) |
| Blitter? | Yes. It's the one feature that helps both a GUI and games: the CPU moves 1–2 MB/s across the bus, the blitter 16–48 MB/s inside VRAM ([section 7](#7-blitter)) |
| Sprites? Tiles? | **Open.** With a blitter and hardware scrolling, games can be built Amiga-style from blitted objects. Sprites and tiles cost nothing per frame, and they're the console feel; ~60–80 chips for both ([section 9](#9-sprites-and-tiles)) |
| A Sony PVM? | Yes, for ~3–4 chips. VGA timing with the pixel clock halved is exactly the 15.734 kHz line rate of NTSC, so one timing generator does both ([3.2](#32-15-khz-for-a-pvm)) |

## 2. What the screen is for

Two workloads, with different needs:

| | A GUI | Games |
|---|---|---|
| Resolution | High: 640×480 or more | Low: 320×240; 256–320 wide was the norm |
| Colours | 1 bit is enough (Alto, Mac, Blit); 4–8 bits for colour | 4–8 bits through palettes |
| What changes per frame | Little, irregularly: a window moves, a list scrolls, some text appears | The whole screen, every frame, at 60 Hz |
| What helps | Fast rectangle copies and fills, text drawing | Scrolling, many moving objects, raster tricks |

There's also the console: text from the boot ROM and the OS. Every option
here can show it by drawing glyphs from a font in the boot ROM into a
bitmap, with hardware scrolling ([section 6](#6-scrolling-page-flipping-and-interrupts)).
A text mode falls out of tiles ([9.4](#94-tiles-and-text-mode-with-them)),
but the console doesn't need one.

### 2.1 What the CPU can do by itself

The draft 1b CPU runs about a million instructions a second: 3 MHz, 3–4
cycles per instruction ([report 0012](0012-report-draft-1b-hardware.md)).
Draft 2 will probably be similar. A word-copy loop moves about 1 MB/s
([RFC 0009, section 4](0009-rfc-ideas-io.md#4-networking)); a fill perhaps
2 MB/s (an estimate). Stores to the card are posted, so the bus isn't the
limit for writes, but every read of VRAM crosses the bus and takes about
half a microsecond.

| Screen | Size | CPU fill | CPU copy |
|---|---:|---:|---:|
| 640×480, 1 bit | 37.5 KB | 19 ms | 38 ms |
| 640×480, 4 bits | 150 KB | 77 ms | 154 ms |
| 640×480, 8 bits | 300 KB | 154 ms | 307 ms |
| 320×240, 4 bits | 37.5 KB | 19 ms | 38 ms |
| 320×240, 8 bits | 75 KB | 38 ms | 77 ms |

A frame at 60 Hz lasts 16.7 ms, so a CPU doing nothing else writes at most
about 33 KB per frame. So:

- **A 1-bit GUI works in software.** The Mac (a 68000 at 7.8 MHz, about the
  same speed), the Blit and the Alto did it. Redrawing a 200×100 window
  takes about 1.3 ms.
- **A colour GUI wants a blitter.** At 8 bits, moving a 300×200 window is
  60 KB: 60 ms or more by CPU, visibly slow.
- **Full-screen games need hardware.** Not even a 320×240 screen at 4 bits
  can be redrawn in a frame. The 1980s answers were tiles and sprites
  (arcade boards, the NES, the Mega Drive), or a blitter and a copper (the
  Amiga).

### 2.2 Precedents

| Machine | Year | Display | Drawing |
|---|---|---|---|
| Xerox Alto | 1973 | 606×808, 1 bit | BitBLT in the CPU's microcode |
| Atari 400/800 | 1979 | up to 320×192 | ANTIC display lists, GTIA sprites ("players") |
| Galaxian, Donkey Kong | 1979, 1981 | about 256×224 at 15 kHz | tiles and sprites from 74LS logic and PROMs, so TTL sprites are practical |
| Sun-1 | 1982 | 1024×800, 1 bit | RasterOp hardware on the frame buffer |
| Blit (Bell Labs) | 1982 | 800×1024, 1 bit | bitblt in 68000 software |
| NES | 1983 | 256×240 | tiles; 64 sprites, 8 per line |
| Macintosh | 1984 | 512×342, 1 bit | QuickDraw in 68000 software, cursor included |
| Amiga | 1985 | 320×256 to 640×512, up to 32 colours from 4096 | blitter, copper, 8 sprites, planar memory shared with the CPU |
| VGA | 1987 | 640×480 at 16 colours, 320×200 at 256 | none; a RAMDAC palette |

## 3. Monitors and timing

### 3.1 VGA: 640×480 at 60 Hz

- A 25.175 MHz pixel clock, 800 × 525 clocks in total: lines at
  31.47 kHz, frames at 59.94 Hz, negative syncs.
- Every VGA monitor and most LCDs with a VGA input take it.
  **recommended** as the base.
- The pixel clock comes from the card's own oscillator. The backplane
  doesn't carry the CPU's 50 MHz, and the card needs a synchroniser
  between the bus clock and its own anyway.

### 3.2 15 kHz for a PVM

VGA's line rate is exactly twice NTSC's. With the pixel clock halved and
the same 800 clocks per line:

$$\frac{25.175\ \text{MHz}}{2 \times 800} = 15.734\ \text{kHz}, \qquad
\frac{15.734\ \text{kHz}}{262\ \text{lines}} = 60.05\ \text{Hz}$$

That's the non-interlaced "240p" timing of the 1980s and 90s consoles. So
one timing generator drives both kinds of monitor: a ÷ 2 on the pixel
clock, and other line counts in its ROM.

| Mode | On a VGA monitor (31 kHz) | On a PVM (15 kHz) |
|---|---|---|
| 640×480 | native | interlaced (480i); thin horizontal lines flicker |
| 640×240 | each line shown twice | native: wide pixels, like the Amiga's Workbench |
| 320×240 | each pixel and line doubled | native: the console look |

What it takes:

- **Sync.** A PVM wants composite sync on its external-sync BNC (about
  4 Vp-p, negative, on the PVM-L2 series), or sync on green (0.3 Vp-p).
  Composite sync is H-sync XOR V-sync, or a properly serrated one from the
  timing ROM: a gate and a resistor.
- **RGB.** 0.7 Vp-p into 75 Ω, the same as VGA, so the DACs are shared. A
  PVM's RGB inputs are BNCs. A VGA-to-BNC cable with composite sync on the
  H-sync pin works, or the card gets its own connector.
- **Interlace,** for 480i: a field flip-flop and a half-line offset in the
  vertical timing, ~2 chips. **optional.**
- **50 Hz,** for PAL-only TVs: the same lines, 315 to a frame (49.95 Hz).
  Only ROM contents. **optional.**
- **SCART.** Most European CRT TVs take RGB at 15 kHz through SCART: pin 16
  at 1–3 V selects RGB, and pin 8 switches the TV to the input. It's the
  cheap way to a CRT in the UK.
- **Which PVMs.** Most are 15 kHz only. A few, such as the 14L5 and 20L5
  (15.6–45 kHz on their spec sheet), also take 31 kHz.
- **Both, switched by a mode bit,** with a jumper for the power-on default.
  A 15 kHz monitor shows nothing in the VGA modes, and most LCDs show
  nothing at 15 kHz, so whichever monitor is attached has to get a picture
  from the boot ROM.
- **HDMI,** if ever wanted: scan converters (OSSC, RetroTINK) take 15 kHz
  RGB.

Cost: about 3–4 chips (the ÷ 2 is shared with the 320-wide modes).
**recommended.**

### 3.3 The modes

| Mode | Bits per pixel | Size | VGA | 15 kHz |
|---|---|---:|---|---|
| 640×480 | 1, 2, 4, 8 | 37.5–300 KB | 25.175 MHz | 12.59 MHz, interlaced |
| 640×240 | 1, 2, 4, 8 | 19–150 KB | 25.175 MHz, lines doubled | 12.59 MHz |
| 320×240 | 1, 2, 4, 8 (16, [optional](#5-pixels-and-colour)) | 9.4–75 KB (150 KB) | 12.59 MHz, lines doubled | 6.29 MHz |

At 15 kHz the 640 visible pixels last 50.8 µs of the 63.6 µs line, a
little inside NTSC's 52.6 µs, so a PVM in underscan shows all of them with
a border.

### 3.4 The timing generator

- **Counters and ROMs.** **recommended.** Horizontal and vertical counters,
  with their counts and the mode bits as the addresses of flash ROMs. The
  ROMs' registered outputs are the syncs, the blanking, the fetch windows
  and the VRAM slot schedule ([4.3](#43-slots)). A new mode is new ROM
  contents. ~12 chips.
- **A 6845 CRTC** (or 6345, 6545). One chip for the counters and syncs, but
  it counts characters, not memory slots, so the slot schedule still needs
  logic. RFC 0009 called it less authentic. **not recommended**: the ROMs
  do more for about ten more chips.
- **Programmable registers and comparators** for every timing parameter,
  as on later VGA cards: any mode from software, ~15–20 more chips. **not
  recommended**: the ROMs cover every mode here.

### 3.5 Higher resolutions

**open**, for a workstation look (Sun-1, PERQ, Blit), on a VGA monitor:

- **800×600 at 60 Hz:** a 40 MHz pixel clock, 480 KB at 8 bits. A second
  oscillator and ROM contents, with VRAM slots of 3 pixels (75 ns).
- **1024×768 at 60 Hz, 1 bit:** 65 MHz, 96 KB. The pixel path at 15 ns per
  pixel is at the limit of 74AC and 74F parts and would bypass the palette.
- ~2–4 chips each, but only if a timing analysis of the pixel path says
  yes.

## 4. Video memory

```
            system bus (P1 + P2)
                    |
           +-----------------+
           |  bus interface  |  posted writes; WAIT on reads
           +-----------------+
                    |  CPU slots
+----------+  +-------------------------+  +------------+  +---------+
|  timing  |->|  VRAM: 4 x 512K x 8     |->| pixel path |->| palette |-> DACs -> VGA / PVM
|  ROMs    |  |  32 bits, 79 ns slots   |  +------------+  +---------+
+----------+  +-------------------------+        ^
  syncs, slot     ^          ^       ^           |
  owners          |          |       |      sprite line
               blitter    copper  sprites,  buffers (optional)
                                  tiles
```

### 4.1 On the card

**recommended**, and close to forced:

- 640×480 at 8 bits and 60 Hz is 18.4 MB/s on average and 25 MB/s during
  a line.
- The system bus moves 33 MB/s with 32-bit single transfers
  ([RFC 0014](0014-rfc-system-bus.md)), shared with everything else.
- Main RAM is private to the CPU board. Its slave port gives other masters
  a 16-bit transfer in 180–320 ns, 6–11 MB/s
  ([RFC 0014, section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus)),
  not enough even for 640×480 at 4 bits.
- Interleaving video into main memory was rejected along with fixed memory
  slots, since they don't fit variable-length cycles
  ([RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory)).

What it costs: the CPU reaches VRAM over the bus (writes are posted, reads
take about half a microsecond), and graphics such as fonts and sprite
sheets live in main memory and are copied into VRAM when loaded.

### 4.2 Size and width

- **Four 512K×8 SRAMs, 10–15 ns:** 2 MB, 32 bits wide. **recommended.**
  - 5 V parts this size are still made in SOJ and TSOP (IS61C5128,
    AS7C4096); fast SRAM no longer comes in DIP
    ([RFC 0007](0007-rfc-ideas-microarchitecture.md#3-parts)).
  - Each chip is a byte lane, so byte write enables come free. The blitter
    relies on them.
  - 2 MB is plenty: a 640×480 screen at 8 bits is 300 KB, so there's room
    for back buffers, fonts, sprite sheets and tiles. The memory is the
    cheap part; the logic around it costs.
- **16 bits wide** (two SRAMs, 1 MB): ~6 fewer chips, but half the
  bandwidth. 640×480 at 8 bits would need every slot during a line, so it
  tops out at 640×480 at 4 bits and 320×240 at 8. **open**; 32 bits is
  recommended.

### 4.3 Slots

- **The VRAM runs in slots of 2 pixel clocks:** 79 ns, 12.6 million a
  second, 50 MB/s at 32 bits. That's comfortable for 10–15 ns SRAM behind
  74AC buffers.
- **The timing ROMs say who owns each slot:** the display, the copper, the
  sprites or tiles, or nobody. The CPU and the blitter share the slots
  nobody owns, the CPU first.
- **At 15 kHz the memory still runs at the full rate,** so there are twice
  as many slots per pixel.

The display's share of the slots during a visible line:

| Mode | VGA | 15 kHz |
|---|---:|---:|
| 640 wide, 1 bit | 6% | 3% |
| 640 wide, 2 bits | 12.5% | 6% |
| 640 wide, 4 bits | 25% | 12.5% |
| 640 wide, 8 bits | 50% | 25% |
| 320 wide, 4 bits | 12.5% | 6% |
| 320 wide, 8 bits | 25% | 12.5% |
| 320 wide, 16 bits (optional) | 50% | 25% |

The 320-wide modes fetch each line again for its second scan line on VGA.
A line buffer would save that, but bandwidth isn't short.

What's left over a whole frame for the blitter and the CPU, before the
copper and sprites take their share (blanking is 27% of a frame):

| Mode | Free |
|---|---:|
| 640×480, 8 bits, VGA | 32 MB/s |
| 640×480, 4 bits, VGA | 41 MB/s |
| 640×480, 1 bit, VGA | 48 MB/s |
| 320×240, 8 bits, VGA | 41 MB/s |
| 320×240, 8 bits, 15 kHz | 46 MB/s |

### 4.4 Layout: chunky, with a power-of-two stride

- **Chunky pixels:** each pixel's bits together, 4 pixels to a word at 8
  bits, 8 at 4 bits, 32 at 1 bit. **recommended.** Plotting a pixel at 8
  bits is one byte store, and the blitter works on bytes.
- **Planar** (EGA, Amiga: one bit of every pixel in each plane): odd depths
  come cheap (5 bits for 32 colours) and 1-bit blits are simple, but every
  pixel write touches every plane, and the blitter runs once per plane.
  **not recommended.**
- **A fixed stride of 1024 bytes per line,** in every mode.
  **recommended.**
  - A pixel's address is $\text{base} + 1024y + x \cdot \text{bpp}/8$: a
    shift, never a multiply. The display, the blitter and software all
    count y and x separately, with counters and no adders.
  - The 2 MB become a canvas of 2048 lines of 1024 bytes. The screen is a
    window into it, and scrolling and page flipping move the window
    ([section 6](#6-scrolling-page-flipping-and-interrupts)). The rest of
    each line, and the lines below the screen, hold fonts, sprite sheets
    and back buffers for the blitter to copy from.
  - RFC 0009 proposed the same for text (a 128-word row stride).

### 4.5 How the CPU reaches it

- **Linear, in the card's part of the bus address space.** With 32-bit
  addresses a 2 MB window costs nothing, and the MMU can map VRAM pages
  into a process, such as a display server. **recommended.**
- **Behind an auto-incrementing data port** (the TMS9918's way): it saved
  address space on 16-bit machines, and the CPU has auto-increment
  addressing modes anyway. **not recommended.**
- **The card is a synchronous slave** on the bus
  ([RFC 0014, section 2](0014-rfc-system-bus.md#2-cards-and-the-backplane)), 32 bits
  wide.
  - **Writes are posted:** registered transceivers (74ABT652) take a
    write, and the card does it in the next free slot. The CPU only waits
    if it writes again before that.
  - **Reads hold WAIT** until a slot comes up and the data is back in the
    bus clock's domain: about 0.4–0.6 µs.
- **Bursts** into a small write FIFO would let a DMA master fill VRAM at
  bus speed. **optional**, ~3–4 chips.
- Any master can write VRAM: a DMA engine, or another CPU.

## 5. Pixels and colour

- **Depths:** 1, 2, 4 and 8 bits per pixel, indexed through the palette.
  Below 8 bits, a palette-bank register supplies the high bits of the
  index, so sixteen 16-colour palettes share the table. **recommended.**
- **The pixel path:** a 32-bit word latch whose byte outputs are enabled in
  turn, then nibble and bit selects for 4, 2 and 1 bits, in 74AC at
  25 MHz. ~9 chips, part of the base card.
- **The palette:** 256 entries of 16 bits (5 bits of red, 6 of green, 5 of
  blue), in two fast SRAMs, then a register and resistor-ladder DACs into
  75 Ω. ~8 chips. **recommended.**
  - The CPU writes it through the card's registers. A write during a
    visible line puts a speck of the wrong colour on the screen, so
    software writes it in blanking or through the copper.
  - 12-bit colour (4 bits each, like the Amiga's) is the same parts with
    fewer resistors. 24-bit colour needs a third SRAM and a real DAC chip.
- **A RAMDAC chip** instead (Brooktree Bt47x or INMOS G17x, as on VGA
  cards: 256 entries of 18 bits, DACs included): 1–2 chips instead of ~8,
  but new old stock only. **open**: it's period-correct for 1987, and
  whether it fits "7400 logic" is Emily's call.
- **16-bit direct colour** at 320×240, with no palette: 150 KB per screen
  and 25–50% of the slots. A 2:1 mux ahead of the DAC register, ~3 chips.
  **optional**, for photos and demos.
- **The border** shows palette entry 0, so a PVM's underscan shows a
  coloured border. Free.

## 6. Scrolling, page flipping and interrupts

Part of the base card. **recommended.**

- **A start position (y, x).** The display's y counter is loaded from a
  start-row register at the top of each frame, and its x counter from a
  start-column register at the start of each line. That gives:
  - **page flipping** in one register write, taking effect at the next
    frame, so nothing tears;
  - **vertical scrolling** that wraps around the 2048-line canvas: a text
    console scrolls by changing the start row and clearing one line,
    instead of copying the screen;
  - **horizontal scrolling** over the 1024-byte lines: a game draws only
    the column of tiles that scrolls into view.
- **Fine horizontal scrolling:** the start column's low bits preset the
  pixel select within the first word. ~1 chip.
- **Line doubling** for the 240-line modes on VGA: the y counter steps
  every other scan line. ~1 gate.
- **Interrupts:** vertical blank, from the timing ROM, and a line-compare
  interrupt, for split screens without a copper (a register and two
  comparators). ~5 chips.
- **A readable line counter,** so software can time raster effects. ~2
  chips.

## 7. Blitter

### 7.1 Why

It's the single feature that helps both workloads. It moves 16–48 MB/s
inside VRAM, against the CPU's 1–2 MB/s across the bus, and it works while
the CPU does something else.

| Job | Blitter | CPU |
|---|---:|---:|
| Clear 640×480 at 8 bits | 10 ms | 154 ms |
| Scroll 640×480 at 8 bits by copying | 19 ms | 300 ms or more |
| Clear 640×480 at 1 bit | 0.8 ms | 19 ms |
| Move a 300×200 window at 8 bits | 4 ms | 60 ms or more |
| Copy a 320×240 background at 8 bits | 4 ms | 77 ms or more |
| Draw a 16×16 sprite at 8 bits, with transparency | ~20 µs | ~1 ms |
| Draw an 8×16 glyph in colour from a 1-bit font | ~12 µs | ~130 µs |

The blitter's times use every free slot ([4.3](#43-slots)) and include
about 8 µs for the CPU to set up a blit. The CPU's are estimates: copies
are slower still when the CPU reads VRAM over the bus.

**For games,** at 320×240 and 8 bits, the blitter has about 680 KB of VRAM
traffic per frame at 60 Hz. Copying the whole background takes about
150 KB of it. That leaves room for several hundred sprite-sized objects,
more than the CPU can set up: a hundred blits cost it about 5% of a frame.
So the Amiga way works: copy or scroll the background, blit the objects on
top, flip the page at vertical blank.

**For a GUI,** the blitter makes 8-bit colour as quick as 1-bit is in
software: window moves, scrolling lists, filled rectangles, and text drawn
from a 1-bit font cached in off-screen VRAM. With it, a software cursor is
cheap too ([9.3](#93-a-hardware-cursor)).

### 7.2 What it does, in tiers

| Tier | What it adds | Chips, cumulative | Status |
|---|---|---:|---|
| Fill | Fill a rectangle with a colour: destination counters for x and y, width and height counters, edge masks through the byte enables | ~20–25 | part of the recommended tier |
| Copy | Copy a rectangle from anywhere in VRAM: source counters, and a byte rotator for any alignment. Overlapping copies run in either direction | ~40–45 | part of the recommended tier |
| Transparency and colour expansion | Skip source bytes that match a key colour (sprites, icons); turn a 1-bit source into bytes of a foreground colour (text, icons, cursors). Both go through the byte write enables, so neither reads the destination | ~50–55 | **recommended** |
| Logic operations | AND, OR and XOR with the destination, for XOR cursors and rubber-band outlines. They read the destination, so they run at half speed | ~60 | **optional** |
| Lines | Bresenham lines between two points | ~70–75 | **optional** |
| Command queue | The blitter reads its jobs from a list in VRAM, so the CPU queues them and carries on | +5–8 | **optional** |

- **Bytes are its unit.** That's a pixel at 8 bits, two at 4 bits, eight at
  1 bit. So 8 bits is the natural depth for a colour GUI and for games.
- **A bit-aligned blitter** (the Alto's BitBLT) would need a 32-bit funnel
  shifter, ~12–16 more chips. **open**, only worth it for a 1-bit GUI, and
  a 1-bit GUI runs well enough in software.

### 7.3 Other ways to get the same

- **A microcoded blitter on the card:** a small datapath (a register file
  in SRAM, a 16-bit adder, the byte rotator) and a microcode ROM, with
  every operation in microcode: lines, circles, colour expansion. About the
  same number of chips (~35–45), but several microcycles per word, so
  ~8–12 MB/s. **open.**
- **BitBLT in the CPU's microcode,** given a writable control store
  ([RFC 0005, section 3](0005-rfc-ideas-direction.md#3-big-ideas)), as
  on the Alto: no chips on the card, but limited by the CPU's bus writes,
  perhaps 2–4 times a software loop. **open**, and worth having anyway if
  the writable control store comes.
- **A display processor on the card,** a second small CPU (the GT40's
  approach) or a TMS34010: **not recommended**, as either another CPU's
  worth of chips or not TTL.

## 8. Display lists: a copper

**recommended**, ~15–20 chips.

A list in VRAM, run during horizontal blanking, with two instructions:

- `WAIT line`: wait until the display reaches that line;
- `MOVE register, value`: write one of the card's registers.

The list pointer reloads from a register at every vertical blank.

Because the mode, the start position, the scroll, the palette, the sprite
table's address and the interrupt request are all registers, this one
mechanism does:

- **split screens:** a status line in 640-wide text under a 320×240 game, a
  GUI's menu bar that stays put while the rest scrolls, two independently
  scrolled windows;
- **mode bands,** the ANTIC way: a mode write and a start-address write at
  chosen lines;
- **more colours:** palette entries rewritten every few lines, for sky
  gradients, raster bars, or 16 different colours per band;
- **parallax:** a different horizontal scroll for each band;
- **sprite reuse:** sprite entries reloaded further down the screen
  ([9.2](#92-sprites-a-line-buffer));
- **line interrupts** at any line, by writing the interrupt register.

| Part | Chips |
|---|---:|
| List pointer (a loadable counter) and its reload register | ~8 |
| Buffers onto the VRAM address bus | ~3 |
| Instruction latch, driving the card's internal register bus | ~4 |
| Line comparator | ~2 |
| Control | ~2 |

- **Limits:** a dozen or so writes per line, in horizontal blanking (80
  slots on VGA, 160 at 15 kHz), shared with sprite fetches.
- **Against RFC 0009's display-list processor** (40–60 chips, ~35
  minimal, with band, palette, jump and wait-for-vertical-blank
  instructions): this is its cheap core. Jumps and band instructions can
  come later if a use turns up.
- **Waiting for a horizontal position** too (the Amiga's copper can):
  writes in the middle of a line, which need a register path that doesn't
  disturb the pixels being shown. **not recommended** for now.

## 9. Sprites and tiles

### 9.1 Are they needed?

With a blitter, hardware scrolling, page flipping and a copper, games can
be built from blitted objects over a scrolling background, as on the Amiga
and most PC games. What sprites and tiles add:

- **nothing to do per frame:** moving an object is a register write.
  Nothing is redrawn, saved or restored, and it costs no VRAM bandwidth or
  CPU time;
- **no double buffering** for the objects, and no tearing;
- **the console feel,** including its limits (sprites per line, flicker
  when there are too many) and the tricks around them.

**open**: ~60–80 chips for both, useful only to games.
[Section 12](#12-simulate-first) proposes deciding after a game demo in
simulation.

### 9.2 Sprites: a line buffer

- **How it works:**
  - While one line is shown, the engine reads the sprite table, finds the
    sprites on the next line, fetches their rows from VRAM, and writes
    their non-transparent pixels into a line buffer at their x positions.
  - The display reads the buffer and puts sprite pixels over the
    background, then clears it for reuse.
  - Two buffers alternate.
- **What it gives,** in the 320-wide modes: sprites 16 pixels wide at 8
  bits (or 4 bits with a palette), any height, flips, a priority bit
  against the background; 64–128 in the table and 16–32 on a line (the
  NES had 8 on a line, the SNES 32).
- **Timing:** a 320-wide line lasts 63.6 µs on both kinds of monitor (two
  scan lines on VGA). A sprite's row is 4 VRAM reads and 16 buffer writes
  at 12.6 MHz, about 1.5 µs, so 32 sprites take about 50 µs.
- **Cost:**

  | Part | Chips |
  |---|---:|
  | Sprite table in a small SRAM, with its CPU path | ~4 |
  | Y range check | ~4 |
  | Fetch addressing | ~5 |
  | Two line-buffer SRAMs, with their address and data steering | ~10 |
  | Transparency and merging with the background | ~4 |
  | Sequencer | ~6 |
  | Registers | ~4 |
  | **Total** | **~35–45** |

- **Only in the 320-wide modes.** In the 640-wide ones the buffer would
  have to be written at 25 MHz in half the time: the same chips in faster
  parts, and not worth it for a GUI.
- **Per-sprite shift registers** instead (Atari, C64, Amiga): ~8–10 chips
  per sprite, so cheaper only below about four sprites. **not
  recommended**, except perhaps for a cursor.

### 9.3 A hardware cursor

- A 16×16 cursor at 2 bits per pixel (transparent, two colours, invert)
  over any mode, like the bigger ones on later VGA cards. ~10–12 chips.
- The Mac drew its cursor in software. With the blitter, saving, drawing
  and restoring a 16×16 cursor at 8 bits takes about 60 µs per mouse move.
- **not recommended**, unless the GUI turns out to need it.

### 9.4 Tiles, and text mode with them

- **Tiles:** the screen is a map of 8×8 tiles. Each map entry is 16 bits: a
  tile number (10 bits), a palette (4 bits), and horizontal and vertical
  flips. A tile is 4 bits per pixel, 32 bytes, through its 16-colour
  palette. The map is bigger than the screen (64×64 tiles, 512×512
  pixels) and wraps, so scrolling is two register writes. **open.**
- **Text mode is the same engine:** a map of character-and-attribute
  entries, 8×16 glyphs at 1 bit, foreground and background colours from
  the attribute. 80×30 characters in 640×480 is 4.7 KB per screen;
  changing a character is one 16-bit store, and a full-screen redraw by
  CPU takes about 5 ms.
- **Cost:**

  | Part | Chips |
  |---|---:|
  | Map and pattern addressing, with x and y scroll | ~10–12 |
  | Map-entry and attribute latches | ~4 |
  | Flips | ~2 |
  | Text attributes | ~2 |
  | Sequencing, in the timing ROMs; the bitmap's pixel path, shared | ~0–3 |
  | **One layer** | **~25–35** |

  A second layer (two-plane parallax, or text over a bitmap) adds ~15–20
  chips and a priority mux. **open.**
- **Bandwidth:** about 1.5 slots per 8 pixels, since a tile row is one
  32-bit read and two map entries share another. That's 19% of the slots
  at 320 wide on VGA, and 37.5% for 80-column text.
- **Without tiles,** the console draws glyphs into a bitmap (~12 µs each
  with the blitter's colour expansion), and games draw tiles with the
  blitter as they scroll into view. That's why tiles are **open** rather
  than recommended.

## 10. Small extras

| Feature | What | Chips | Status |
|---|---|---:|---|
| Interlace | 480i on a PVM ([3.2](#32-15-khz-for-a-pvm)) | ~2 | **optional** |
| 50 Hz | 315-line frames, for PAL-only TVs | 0 (ROM contents) | **optional** |
| 16-bit direct colour | 320×240 without the palette ([section 5](#5-pixels-and-colour)) | ~3 | **optional** |
| Light pen or light gun | Latch the beam's position when a photodiode sees it. CRTs only: Sketchpad, Duck Hunt, PVM vibes | ~4 | **optional** |
| Composite and S-video out | An RGB-to-NTSC/PAL encoder chip (AD725-style), for TVs without RGB | ~2 | **optional** |
| High-resolution mono | 800×600, or 1024×768 at 1 bit ([3.5](#35-higher-resolutions)) | ~2–4 | **open** |
| Sound | The Amiga fetched audio samples in horizontal-blanking slots. Four channels from VRAM into DACs, one sample per line each: not video, but the slots and the timing are here | ~10–15 | **open**; or a card of its own |
| Vector display | X and Y DACs and a line walker, on an oscilloscope or XY monitor (RFC 0009's GT40 and Spacewar idea) | ~25–40, very rough | **open**, as a card of its own |

## 11. Cost, board space and stages

| What | Chips |
|---|---:|
| Base card | ~70 |
| + blitter (fill, copy, transparency, colour expansion) | ~120–125 |
| + copper | ~135–145 |
| + sprites | ~170–190 |
| + tiles and text | ~200–220 |

The base card, block by block:

| Block | Parts | Chips |
|---|---|---:|
| Clocks | 25.175 MHz oscillator; ÷ 2 and ÷ 4 | 2 |
| Timing | horizontal and vertical counters (6), three flash ROMs, output registers (2), slot select (1) | 12 |
| Display addressing | y and x counters (5), start-position registers (3), buffers onto the VRAM address bus (3) | 11 |
| VRAM | four 512K×8 SRAMs; strobes and byte enables (2) | 6 |
| Pixel path | word latch (4); nibble and bit selects and the palette bank (5) | 9 |
| Palette and DACs | two SRAMs, address mux (2), CPU data path (2), output register (2), resistor ladders | 8 |
| Bus interface | address registers (3 × 74ABT574), registered data transceivers (4 × 74ABT652), decode, control and synchronisers (5) | 12 |
| Registers and interrupts | mode, palette bank, line compare, status, line-counter readback | 6 |
| Outputs | syncs, composite sync, interlace field | 3 |
| **Total** | | **~69** |

A minimal card (16-bit VRAM, 640×480 at 4 bits, VGA only, no line
interrupt) would be about 55.

- **Board space.** The card size, and how the system splits into cards,
  aren't decided. The base card alone is a full board. The blitter and
  copper need more room, and they can't easily go on a neighbouring card:
  they need the VRAM bus (32 data lines, 19 address lines, strobes and slot
  signals, about 60), more than P2's ~54 user-defined pins. So: one large
  card, SOIC parts, or a mezzanine on the base card. **open.**
- **PLDs.** GALs would absorb the timing decode, the slot arbitration, the
  sequencers and the glue: perhaps a third fewer chips, so a base card of
  about 50 and stages 1–3 in about 100. **open**; the same question comes
  up for the backplane.
- **Stages.** Build stage 1 first. A VGA monitor and a PVM both work from
  the first day, and the console works with glyphs drawn by software. The
  blitter and the copper are additions that don't change stage 1, so long
  as it reserves for them now: slot owners in the ROMs' schedule, and room
  in the register map. **recommended.**

## 12. Simulate first

**recommended**, before any netlist:

1. **A behavioural model of the card** in the instruction-level simulator
   (in Rust, [RFC 0015](0015-rfc-languages.md)): VRAM, the registers, the
   slot schedule, the blitter and the copper. It renders frames to PNG
   files or a window and counts slots and CPU time per frame.
2. **Software against it:**
   - a console driver: glyphs from the boot ROM's font, hardware scrolling;
   - a GUI demo: overlapping windows, text, a cursor;
   - a game demo: a scrolling background with 20–30 moving objects at
     60 Hz, through the blitter.
3. **Decide sprites and tiles from the game demo.** If the blitter version
   runs at 60 Hz with CPU time to spare, they stay optional.
4. **Then the netlist,** in the chip-level simulator, with a frame grabber
   on its RGB and sync outputs that writes PNG files, so the netlist is
   checked against the behavioural model frame by frame. Timing analysis
   covers the 25 MHz pixel path and the VRAM slot.

[RFC 0005, section 5](0005-rfc-ideas-direction.md#5-next-steps)
already offers a simulated display-list card rendering PNGs; this is that
offer, for this design.

## 13. Against RFC 0009

Where this RFC differs from RFC 0009's video notes. Since this RFC,
[RFC 0009, section 3](0009-rfc-ideas-io.md#3-video) keeps only the ones
set aside here, as alternatives:

| RFC 0009 | Here | Why |
|---|---|---|
| A text-mode card first, ~30 chips | A bitmap card first. Text is drawn by software; a text mode comes only with tiles | A bitmap card serves the console, a GUI and games; a text-only card would be replaced |
| 64K×16 of VRAM | 2 MB, 32 bits wide | 512K×8 SRAM is cheap; 32 bits doubles the bandwidth for the 8-bit modes and the blitter |
| Four fixed slots per character time | Slot owners from the timing ROMs, per mode | Each mode needs different shares |
| A display-list processor, 40–60 chips | A copper, ~15–20 | Registers do the work; a band is a mode write |
| VRAM in a window, or behind ports to save address space | Linear in the card's address range | With 32-bit addresses the window is free |
| A 16-entry palette, 2 bits per channel | 256 entries of 16 bits | The same SRAMs hold either |
| A screen clear from ~65 ms to ~1 ms with a blitter | 154 ms to 10 ms at 640×480 and 8 bits; 19 ms to 0.8 ms at 1 bit | It depends on the depth |

What RFC 0009 rejected stays rejected here: video generated by the CPU in
software (ZX81, Gigatron), which would eat a microcoded CPU.

## 14. Open questions

For Emily:

1. **What's the screen mainly for:** a GUI, games, or both? That decides
   sprites and tiles (~60–80 chips, for games only), and whether the GUI
   is 1-bit (software is enough) or colour (it needs the blitter).
2. **Resolution:** are 640×480 and 320×240 enough, or is a
   high-resolution monochrome mode (800×600 or 1024×768) wanted for a
   workstation look?
3. **VRAM width:** 32 bits (recommended) or 16?
4. **Palette:** fast SRAM and resistor DACs, or a RAMDAC chip?
5. **The PVM:** which model, a 15 kHz-only one or one that also takes
   31 kHz? Interlace and 50 Hz too?
6. **The blitter:** which tier, and byte-aligned (for 8-bit colour) or
   bit-aligned (for a 1-bit GUI)?
7. **The copper:** yes?
8. **Sprites and tiles:** both, one, or neither? Perhaps after the game
   demo in simulation.
9. **PLDs:** may the card use GALs?
10. **Board:** one large card, a card with a mezzanine, or SOIC parts? This
    waits on the card size.
11. **Sound:** on the video card, in the horizontal-blanking slots, or on a
    card of its own?
