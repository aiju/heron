---
number: 41
type: rfc
title: Heron Mini, draft 2 on one board
status: open
date: 2026-10-17
context:
  studies: [mini, v2_isa, v2_hw, v1b_hw, v1b_tradeoffs, v1b_system, c_compiler]
  commit: 3d43d93
depends-on: [16, 23, 24, 28, 29, 31]
---

# RFC 0041: Heron Mini, draft 2 on one board

A small Heron beside the full one, as the 360/20 was beside the 360/40:
draft 2's user instruction set ([RFC 0028](0028-rfc-draft-2-isa.md)) on
one board, with its RAM wired to the CPU and no system bus, a few devices
in an I/O space, and a 640 × 480 framebuffer, for Egret's desktop and for
games. Compatibility with the full Heron is not a goal; running draft 2's
programs is. Part I specifies the machine as built; Part II is what it
measures, what it costs, what could be left out, and what's left for Emily
to decide.

The study is [studies/mini](../studies/mini/README.md): the microcode, a
register-transfer model checked against draft 2's instruction-level
simulator, and a chip-level netlist of the whole board: CPU, RAM, I/O
devices and video. On the chip-level simulator the netlist runs the program
suite exactly as the model does, cycle for cycle, with no timing violation,
at cycle lengths that static timing analysis of the netlist measures; the
devices and the video are checked against what their programs should give.
The tables are in [performance.md](0041-rfc-heron-mini/performance.md).

As Emily asked, the netlist is **overbuilt**: it has every feature that
seemed useful, built in full, and what could be left out is estimated by
taking chips out of it rather than by guessing what adding a feature
costs ([15](#15-what-could-be-left-out)).

## Summary

- **It works, at chip level.** 427 packages. The suite and the compiled C
  programs run on the netlist exactly as on the model, at four cycle
  lengths from 5 to 9 ticks of 19.86 ns (half the VGA pixel clock); the
  UARTs, the 82C54, the CF card and the boot flash do what a test program
  expects of them; the video sends the frame its memory describes.
- **Fast:** the suite and the C programs take 1.11 times the full
  Heron's time ([RFC 0031](0031-rfc-draft-2-cpu.md)), about what the
  instruction-level simulator's reference timing would take at 12 MHz.
  Egret's desktop would type a character in about 5 ms and open its
  class browser in about 170 ms ([13](#13-how-fast)).
- **Too many chips.** The target was 200–300; the board is 427, the CPU
  305 of them. Taking chips out of the netlist finds about 50 that could
  go for about 20% in time; under 300 needs a slower CPU, built like
  draft 1b's 213-chip one rather than like draft 2's, and that is the
  main decision this RFC asks for ([16](#16-toward-250-chips)).
- **Multiply and divide stay in hardware:** without the MQ register
  (6 chips) the suite would take half as long again ([17](#17-isa-features-and-what-they-cost)).
- **The video costs the CPU nothing.** It has the RAM's second bank to
  itself through buffers, takes its words in cycles' tails and in I/O
  waits, and never holds the CPU ([9](#9-video), [18](#18-the-video)).
- **Blitting in microcode** gains 1.8 to 4.5 times over draft 2 code for
  fills, copies, shifted copies and glyphs ([19](#19-blitting-in-microcode)).

## Contents

- [Part I: Specification](#part-i-specification)
  - [1. Overview](#1-overview)
  - [2. Instruction set](#2-instruction-set)
  - [3. Address map](#3-address-map)
  - [4. Clock and cycles](#4-clock-and-cycles)
  - [5. CPU](#5-cpu)
  - [6. Memory](#6-memory)
  - [7. The I/O space](#7-the-io-space)
  - [8. Expansion ports](#8-expansion-ports)
  - [9. Video](#9-video)
  - [10. Reset and boot](#10-reset-and-boot)
  - [11. Parts](#11-parts)
- [Part II: Discussion](#part-ii-discussion)
  - [12. Where it comes from](#12-where-it-comes-from)
  - [13. How fast](#13-how-fast)
  - [14. Chips](#14-chips)
  - [15. What could be left out](#15-what-could-be-left-out)
  - [16. Toward 250 chips](#16-toward-250-chips)
  - [17. ISA features and what they cost](#17-isa-features-and-what-they-cost)
  - [18. The video](#18-the-video)
  - [19. Blitting in microcode](#19-blitting-in-microcode)
  - [20. A fast link](#20-a-fast-link)
  - [21. Sound](#21-sound)
  - [22. The board](#22-the-board)
  - [23. How it was checked](#23-how-it-was-checked)
  - [24. Open questions](#24-open-questions)
  - [25. Next steps](#25-next-steps)

## Part I: Specification

### 1. Overview

A microcoded 32-bit CPU, its 4 MB of RAM, an I/O space and a video
generator on one board, with no bus between them. The parts are
[RFC 0024](0024-rfc-faster-smaller.md)'s fast set in packages for hand
soldering: 74F and 74ABT logic in DIP (74ACT only for counters whose
enables 74F can't set up in time), 74F181 ALUs with 74F182 carry
lookahead, SST39SF010A flash (55 ns, DIP-32), and 12 ns SRAM in SOJ, the
only surface-mount chips besides none: AS7C256A-12 for the register file
and the palette, AS7C4096A-12 for the RAM.

- **Clock:** a 50.35 MHz oscillator, twice VGA's pixel clock; a cycle is
  5, 6, 7 or 9 of its ticks (19.86 ns), as the microinstruction's length
  class says, plus two when a parcel must be fetched in the cycle that
  reads it, plus an I/O access's wait states ([4](#4-clock-and-cycles)).
- **CPU:** draft 2's CPU ([RFC 0031](0031-rfc-draft-2-cpu.md)) without
  its system half: the same datapath and prefetch queue, a 136-bit
  microinstruction in flash, the first microinstruction of every
  instruction at the address of its first parcel, no decode table
  ([5](#5-cpu)).
- **Memory:** 4 MB in two banks of 512K × 32; bank 1 is also the video's,
  behind buffers ([6](#6-memory)).
- **I/O:** eight regions of 256 MB above 0x8000_0000, each with its own
  wait states; a CF card, two expansion ports, an 82C54, the boot flash,
  two 16C550 UARTs and the on-board registers; one interrupt line
  ([7](#7-the-io-space)).
- **Video:** 640 × 480 at 4 bits a pixel from bank 1, with a descriptor
  per line and a palette of 256 RGB 5:6:5 entries ([9](#9-video)).

### 2. Instruction set

The user level of draft 2 ([RFC 0028](0028-rfc-draft-2-isa.md)) with
draft 2's *plain machine*, the one draft 2's instruction-level simulator
runs without a supervisor:

- **Traps and the interrupt:** vectors are code addresses from 0: reset 0,
  the interrupt 4, an illegal instruction 8, `SWI` 0x0C, a divide error
  0x10, a tag check 0x18. Taking one pushes the flags word and then the PC
  (`sp − 8` and `sp − 4`), clears I and jumps to the vector; `RTI`
  undoes it.
- **One interrupt line,** level-sensitive, taken at an instruction's end
  when I is set ([7](#7-the-io-space) has its sources). `EI` and `DI` set
  and clear I; `HALT` waits for an interrupt if I is set and stops the
  machine otherwise.
- **`ccr`** holds the flags word (V C Z N I in bits 0–4) for `MFSR` and
  `MTSR`. There are no other special registers.
- **Left out:** RFC 0029's modes, register banks (`MFUR` and `MTUR` are
  illegal), address translation, the other special registers, and the
  address error: a misaligned access reaches the aligned word, half or
  byte.
- **Kept:** everything else, the tentative instructions (`MULA`, `MULFX`,
  `ADD.B4`, the tagged operations) included: in microcode they cost no
  chips ([17](#17-isa-features-and-what-they-cost)).

#### 2.1 Block instructions

Four instructions in cell `FD`'s free encodings (draft 2 uses only
`FD 00`, `MULFX`), for a 4-bit framebuffer's inner loops
([19](#19-blitting-in-microcode)). Each does `r3` words, 0 to 256 (0 does
nothing; more is **open**), from `r1` up, which ends past them; `r3`
doesn't change. They aren't interrupted, as `SAVE` and `LDM` aren't.

| Encoding | Name | Operation |
|---|---|---|
| `FD 01` | `FILL` | `r2` into each word |
| `FD 02` | `COPY` | the words from `r2` up (`r2` ends past them) |
| `FD 03` | `EXPAND` | from the bytes at `r2` up (`r2` ends past them), each byte's eight bits as eight pixels: `r6 ^ (m & r5)`, `m` the byte's entry in a table of 256 nibble masks at `r4`; with `r5 = fg ^ bg` and `r6 = bg`, a glyph in two colours |
| `FD 1k` | `BLIT k` | the words from `r2` up, each rotated right by 4k bits and merged with the one before (`lo`) under `r0`: `hi ^ ((lo ^ hi) & r0)`; with `r0 = ~0 >> 4k`, a copy shifted by k pixels. `lo` is `r5` on entry, and the last word rotated on exit |

### 3. Address map

| Address | What |
|---|---|
| 0x0000_0000–0x001F_FFFF | RAM bank 0, 2 MB |
| 0x0020_0000–0x003F_FFFF | RAM bank 1, 2 MB, also the video's ([9](#9-video)) |
| 0x0040_0000–0x7FFF_FFFF | the RAM again, every 4 MB |
| 0x8000_0000 + r × 0x1000_0000 | I/O region r, 0–7 ([7](#7-the-io-space)) |

### 4. Clock and cycles

RFC 0024's clock generator for short cycles, as draft 2's CPU has it
([RFC 0031, 2](0031-rfc-draft-2-cpu.md#2-clock-and-cycles)), with two
tail ticks: a cycle of K ticks runs H0 and H1, a 4-bit count from a
preload to 15, then T1 and T2; the CPU's clock rises entering H0. The
register file is read in the cycle's first part, its latches transparent,
and written in T2; RW (T1 or T2) switches its address to the write
address. The memory's write window is from tick 2 to T1.

- **Length classes:** four, chosen to minimise the suite's time over what
  static timing analysis measures each microinstruction to need
  (`ticks.json`): 5, 6, 7 and 9 ticks. A microinstruction's 2-bit field
  picks one.
- **Data accesses take 7 ticks or more** (K_DATA): the I/O hold below
  must start before the count ends.
- **A demand fetch** (a parcel read from the queue's head when the queue
  is empty, so from the word the cycle fetches) lengthens its cycle by two
  ticks, through the preload.
- **The I/O hold:** an access to the I/O space stops the count from tick 4
  for the region's wait states ([7](#7-the-io-space)).

### 5. CPU

The datapath and the fetch are draft 2's CPU's
([RFC 0031, 3–4](0031-rfc-draft-2-cpu.md#3-datapath)), with 8-bit parts
where it has 16-bit ones, without the system half, and with the
differences below. In brief:

- **Register file:** 32 registers (r0–r15 and the microcode's own) in two
  copies of four 32K × 8 SRAMs (one per read port), each read through
  74ABT573 latches and written through 74ABT541 buffers; the read
  addresses from the instruction, a counter (SX) or the microinstruction,
  a 74F151 per bit and copy.
- **Buses:** an A bus (a register, PC, R, R × 2) and a B bus (a register,
  R, the loaded word T by byte lanes, the queue's head parcel four ways,
  the immediate unit, MQ, the flags word), 74ABT541 drivers.
- **ALU and result:** eight 74F181 with three 74F182; a result multiplexer
  (74F153 × 16) that passes, shifts right by one, rotates by 8 or 16 and
  clears bytes; MQ (four 74F299) for multiply and divide steps.
- **Registers:** R, T (a latch on the data bus, by lanes), MAR (a counter
  for 22 bits and the top four), the loop counter LC, SX and EX, the
  flags (N, Z as four bytes' worth, C, V, I) and the condition latch CL.
- **Fetch:** PC, a fetch counter FPC and a prefetch queue of two 32-bit
  words, filled in cycles that don't use memory; the decode reads the
  queue's head parcel; a parcel needed when the queue is empty comes from
  the word the cycle fetches.
- **Control store:** 128K words of 136 bits in seventeen SST39SF010A,
  pipelined: addressed with the next microinstruction's address, clocked
  into a microinstruction register of seventeen 74ABT574 at every edge.
  Its upper half holds every instruction's first microinstruction at the
  address of its first parcel, so a decode is the queue's head parcel on
  the address lines: there's no decode table. The refill and the
  interrupt entry fill their own pages, so that forcing one changes only
  the address's top bits.

Different from draft 2's CPU: no page map or window, no register banks or
special registers but `ccr`, no message level or interrupt levels, no
trace, and the control store in flash (so no boot through an I/O
processor: the microcode is programmed like a ROM).

### 6. Memory

One access a cycle, a fetch or a data access, at an address from MAR,
FPC or the A bus (74F153 × 13, bits 21–0 and 31–28; 27–22 aren't
decoded), 32 bits wide with byte enables; a store's data is the A bus,
replicated by size.

- **Bank 0** (VA21 low): four AS7C4096A-12 on the CPU's address and data
  buses.
- **Bank 1** (VA21 high) is the video's: four more, on an address and a
  data bus of their own. The CPU reaches it through 74ABT541 address
  buffers and 74ABT245 transceivers; in the video's slots (every cycle's
  T2 and the next cycle's H0, and an I/O access's hold, all times the CPU
  doesn't use bank 1) the video's address goes on instead. Bank 1 is
  always enabled and its outputs are on but in the CPU's writes, so that
  neither its chip enable nor its output enable is on the CPU's read path:
  a read of bank 1 takes the CPU no longer than one of bank 0. Its write
  strobe ends within T1, through fast copies of T1 and T2, before the
  video's slot changes the address.

### 7. The I/O space

An access to 0x8000_0000 and up goes to region r = address bits 30–28.
It holds the cycle: from tick 4 the CPU's count stops for 16 − 2r ticks,
and the strobe (`IORD_n` or `IOWR_n`) runs from the hold's second tick to
T2, one tick past the read's data being latched (T1). So the slow devices
are in the low regions:

| Region | Address | Wait | Strobe | What |
|---:|---|---:|---:|---|
| 0 | 0x8000_0000 | 16 ticks | 298 ns | CF card, True IDE: the task file (CS0) at `+4n`, the control block (CS1) at `+0x20 + 4n`; its strobes start two ticks later than the others' (PIO mode 0's 70 ns of address setup) |
| 1 | 0x9000_0000 | 14 | 298 ns | expansion port 1 |
| 2 | 0xA000_0000 | 12 | 258 ns | expansion port 2 |
| 3 | 0xB000_0000 | 10 | 218 ns | 82C54 timer: counters 0–2 at `+0`, `+4`, `+8`, the control word at `+0xC` |
| 4 | 0xC000_0000 | 8 | 179 ns | **open** (free) |
| 5 | 0xD000_0000 | 6 | 139 ns | boot flash, 128K × 8, a byte a word: byte n at `+4n` |
| 6 | 0xE000_0000 | 4 | 99 ns | UART 0 (16C550) at `+4n`, UART 1 at `+0x20 + 4n` |
| 7 | 0xF000_0000 | 2 | 60 ns | the on-board registers, at addresses with bit 21 low |

- **The devices' bus:** 16 bits (`IOD`), through two 74ABT245 from the
  data bus's low half: driven from the data bus for the whole of a write,
  onto it for a read's strobe. The 8-bit devices are on its low byte, a
  register a word apart, so that word, half and byte loads all find them;
  the CF card's data register uses all 16 bits.
- **The devices' address** (bits 9–2, `IOA`) and the region selects are
  latched as the strobe starts until the next cycle's tick 1, so that they
  hold 20 ns past the strobe (the 16C550's and the CF card's address hold)
  and the expansion ports see them settled.
- **On-board registers** (region 7, bit 21 low), by bits 12–10:

  | Address | Read | Write |
  |---|---|---|
  | 0xF000_0000 | – | the video's control register ([9](#9-video)) |
  | 0xF000_0004 | – | the video's interrupt acknowledge |
  | 0xF000_0400 + 4n | – | palette entry n, RGB 5:6:5 |
  | 0xF000_0800 | the interrupt status: bit 0 UART 0, 1 UART 1, 2 the CF card, 3 the timer, 4 the video, 5 and 6 expansion ports 1 and 2 (their lines as they are, active low), 7 the interrupt line | acknowledges the timer |
  | 0xF000_0C00 | – | the control register: bit 0 the 82C54's GATE2, 1 the speaker's enable (OUT2 to the speaker), 2 and 3 two LEDs |

- **The interrupt line** is any of: either UART's INTR, the CF card's
  INTRQ, the timer's flag (set as the 82C54's OUT0 rises, cleared by a
  write to the interrupt status), the video's interrupt, either expansion
  port's `IRQ_n` (open collector, pulled up). Each device's own enables
  mask it; there's no mask register.
- **The 82C54** counts the UARTs' 1.8432 MHz on all three counters:
  counter 0 the periodic interrupt, counter 2 the speaker.
- **The UARTs:** two TL16C550C at 1.8432 MHz (115,200 baud at most).
- **Software's duty:** the 82C54 needs 165 ns between accesses (two I/O
  instructions in a row don't give it); the CF card needs 600 ns between
  accesses in PIO mode 0, until it is set to a faster mode.
- **In the simulations** a test card in region 7 with bit 21 high answers
  draft 1's I/O page at 0xFFFF_FF00 (the console, a timer, a cycle
  counter), which the program suite uses.

### 8. Expansion ports

Two ports, regions 1 and 2, each a 2 × 20 pin header (0.1 inch) for a
ribbon cable to a card:

| Pins | Signals |
|---|---|
| 1, 2 | GND, +5 V |
| 3–10, 12–19 | D0–D15 (the I/O bus) |
| 11, 20, 29, 36, 38, 40 | GND |
| 21–28 | A2–A9 (latched) |
| 30 | `SEL_n`, the port's region (latched) |
| 31, 32 | `RD_n`, `WR_n` |
| 33 | `RESET_n` |
| 34 | `IRQ_n` (open collector, pulled up on the board) |
| 35 | 1.8432 MHz |
| 37, 39 | +5 V |

A card has 256 word addresses in its region (repeated through it), a
strobe of about 290 ns (port 1) or 260 ns (port 2), data on D0–D7 or
D0–D15. The pinout is **open**; so are the ports' number and their
regions.

### 9. Video

640 × 480 at 4 bits a pixel, VGA timing from a 25.175 MHz pixel clock
(two master ticks). A line is 100 characters of 8 pixels (0–79 the
picture, 80–81 the front porch, 82–93 the sync, 94–99 the back porch); a
frame is 525 lines (0–9 the front porch, 10–11 the sync, 12–44 the back
porch, 45–524 the picture). The syncs are active low.

- **Timing:** a pixel counter, a character counter (0–99) and a line
  counter (0–524), and a timing ROM (an SST39SF010A addressed by the
  character and the line) whose byte is registered at each character's
  end: the syncs, the picture, when the shifters load, when a line's
  descriptor is read, the line's and the frame's ends.
- **Descriptors:** picture line y has a descriptor, word 44 + y of a table
  at bank 1's word 0 (or 1024, with `TSEL`), read in the line before's
  blanking:

  | Bits | |
  |---|---|
  | 18–0 | the line's first word, a word address in bank 1 |
  | 22–19 | its palette bank |
  | 23 | an interrupt as the line is set up |
  | 31–24 | 0 (**open**) |

  The line is the 80 words from there; a word is 8 pixels, the low nibble
  first. A pixel's colour is palette entry 16 × bank + pixel.
- **Palette:** 256 entries of RGB 5:6:5 in two 32K × 8 SRAMs, written by
  the CPU (they can't be read); a 74ABT574 per colour byte registers each
  pixel, its outputs off (black, the monitor's 75 Ω pulling the resistor
  DACs down) outside the picture.
- **Registers** ([7](#7-the-io-space)): the control register (bit 0 the
  picture on, 1 `TSEL`, 2 the interrupt on) and the interrupt's
  acknowledge. The interrupt is set as the picture ends (the frame's last
  line) and by a line whose descriptor asks; it is bit 4 of the interrupt
  status.
- **Fetching:** the video reads bank 1 in its slots (the end of every
  cycle and an I/O access's hold), always the word at its address
  counter, into a holding register; the counter steps as the shifters
  (four 74F299) take that word, at each character's end. A slot comes at
  least every 11 ticks and a word is needed every 16, so the video never
  waits and never holds the CPU.

### 10. Reset and boot

A TL7705A holds the machine in reset at power-up. Reset's microcode
clears the flags (I too), writes the microcode's constants into the
register file, copies the boot flash's image into RAM and jumps to 0.
The image is a word count (little-endian, bytes 0–3 of the flash), then
the words; a count of 0, or of 2³¹ or more (an erased flash), copies
nothing. The copy takes about 1.7 µs a word: 55 ms for the whole flash.
The flash can be written in place (its `WE` is the I/O write strobe), so
a program can update its own boot image.

### 11. Parts

427 packages as built, of which 305 are the CPU (341 with its memory
interface and bank 0); by area (the full list is in
[performance.md](0041-rfc-heron-mini/performance.md#parts)):

| Area | Packages |
|---|---:|
| CPU: control store, sequencer, conditions | 70 |
| CPU: clock, reset, hold | 18 |
| CPU: register file | 37 |
| CPU: buses, immediate unit | 52 |
| CPU: ALU, result multiplexer, MQ | 38 |
| CPU: R, T, MAR, LC, SX, EX | 27 |
| CPU: flags | 17 |
| CPU: PC, FPC, queue | 47 |
| Memory: address, decode, store data, bank 0 | 37 |
| Video RAM: bank 1, its buffers | 20 |
| I/O | 20 |
| Video | 46 |

## Part II: Discussion

### 12. Where it comes from

Emily asked for a small Heron: draft 2's user level, no system level but
one interrupt line, one board of 200–300 chips (perhaps stacked boards,
better no backplane), a 32-bit datapath for now, the RAM wired to the CPU,
the microcode in flash, a few devices, a 640 × 480 × 4 framebuffer with
blitting in microcode, an expansion port or two; DIP parts, 74F and 74ABT,
careful with risky lines such as 74AC. And, after the first estimates, a
netlist: chip-count estimates had been wrong before, by two thirds for
draft 2's CPU ([RFC 0031, 16](0031-rfc-draft-2-cpu.md#16-chips)).

The CPU is draft 2's CPU cut down rather than a new design: its datapath,
fetch and microcode were already checked against draft 2, and what the
system level costs could be taken out of it chip by chip. That choice
carries draft 2's CPU's speed features along (two register-file copies
with latches, the queue, reads at the A bus, short variable cycles), and
with them most of its chips: [16](#16-toward-250-chips) is about that.

### 13. How fast

| | Mini | Full Heron (RFC 0031) | |
|---|---:|---:|---:|
| The suite, hand-written | 523.5 ms | 465.3 ms | 1.13× |
| Compiled C | 316.1 ms | 287.8 ms | 1.10× |
| Both | 839.6 ms | 753.1 ms | 1.11× |

The per-program table is in
[performance.md](0041-rfc-heron-mini/performance.md#the-suite). The mini
is a little slower than draft 2's CPU for three reasons: its control store
is flash, so the microinstruction register's outputs come later; its data
accesses take at least 7 ticks, for the I/O hold; and its parts are 8-bit
(a 74ABT574 clocks out later than a 74ABT16374).

Against the instruction-level simulator's reference timing (D16-overlap,
the one report 0021 quotes "at 3 MHz"), the mini takes on the suite what
the reference would at about 12 MHz: about four times that report's
speeds. So Egret's desktop ([report 0021](0021-report-egret-gui.md), on
draft 2 at 3 MHz in its *On draft 2* table) would, on the mini, type a
character in about 5 ms, open the Browser in about 170 ms, compile itself
at boot in about 4.5 s, and run Gadgets' table at its full 30 frames a
second. Multiplication-heavy work gains less: `mandel` runs at a 6.7 MHz
reference's speed. The block instructions ([19](#19-blitting-in-microcode))
would take a little more off drawing, which is 10–40% of the desktop's
time in report 0021's breakdown.

### 14. Chips

Where the 427 go ([11](#11-parts)): the CPU is 305, four fifths with
its memory interface. Against
draft 2's CPU (394 for its core with 16-bit parts, about 460 with its bus
interface), the mini drops the system half (the page map, the window,
the banks, the interrupt levels, the bus) but keeps the datapath and the
fetch, which are most of it. Against draft 1b's CPU (213 chips, report
0012), it has two register-file copies with latches and write buffers (37
against 14), a prefetch queue and fetch counter (33 against none), a
three-way address multiplexer (13 against a 2-way), 32-bit memory
(16-bit on 1b), the fast clock generator, and wider flags and condition
logic (33 against 16). Those are what make it 2.4 times as fast as 1b on
the same programs ([RFC 0031, 12](0031-rfc-draft-2-cpu.md#12-how-fast)
against draft 1b's fast system), and what put it over the target.

The microinstruction is dense: its fields need 130 of their 132 bits one
by one. Grouped (the A bus's sources, the B bus's, the ALU's, the flags'),
56 bits would do, but only with decode memories as fast as the SRAM,
which would cost more chips than the nine flash and latch pairs they'd
save; decoding the few one-hot groups with 74F138s would save two or
three pairs for a gate's delay in their paths.

### 15. What could be left out

Each taken out of the netlist, with what it adds back, and its time on the
suite and the C programs: measured on the model's variant where the model
has one, otherwise estimated from the profile (the rule is in
`reduce.py`). From [performance.md](0041-rfc-heron-mini/performance.md#what-could-be-left-out):

| Reduction | Chips | Suite | C | What's lost |
|---|---:|---:|---:|---|
| A prefetch queue of one word | 8 | +9.2% | +10.3% | measured |
| No reads at the A bus (MAR and FPC only) | 6 | +6.5% | +1.6% | a load at `[R]` takes a cycle more |
| One register-file copy, read twice a cycle | 13 | +5.1% | +5.3% | a tick more where B comes from the register file (more where it's critical) |
| No MQ | 6 | +53.5% | +52.3% | multiply and divide steps take three cycles more |
| Byte and half lanes in microcode | 13 | +24.5% | +17.7% | a byte or half load or store takes three cycles more |
| No rotations by 8 and 16 | 8 | +17.9% | +24.6% | a rotation becomes 8 or 16 shifts |
| The video in the one RAM | 10 | | | the video can be starved by long I/O accesses |
| No line descriptors | 5 | | | per-line addresses, palette banks and interrupts |
| An 8-bit palette | 3 | | | 256 of 65,536 colours become 256 of 256 |
| No latch for the devices' address | 2 | | | 12 ns of address hold where the 16C550 and the CF card want 20 |
| The CF card on the others' strobes | 1 | | | PIO mode 0's address setup |
| No interrupt status, no control register, one UART | 3 | | | |

So: the queue, the reads at the A bus and the second register-file copy
(27 chips together) could be left out for about 20% on the suite and 17%
on the C programs, the I/O and video items (24 more) for features alone;
MQ, the byte lanes and the rotations are worth their chips. That takes the
board to about 375, still far from 300.

### 16. Toward 250 chips

The reductions above trim draft 2's CPU; reaching 250–300 needs a
different one. Three ways, roughly:

1. **A draft 1b-like core for draft 2.** Draft 1b's CPU was 213 chips with
   its memory interface: one register-file access a phase, no prefetch
   queue (a fetch cycle per instruction), a 16-bit memory and a simpler
   clock; on draft 1's programs RFC 0024's fast version of it took 1.35
   times draft 2's CPU's time (RFC 0031's performance.md). For draft 2,
   with a 32-bit memory and draft 2's denser encoding, perhaps 200–230
   chips in place of this mini's 341 (the CPU with its memory interface),
   perhaps 1.2–1.4 times its time: a board of about 290–320 as built
   here, 265–295 with the I/O and video reductions. These are guesses of
   the kind the netlist was built to replace. **Not built:** it is the
   main thing this RFC proposes doing next.
2. **A 16-bit datapath** for draft 2's 32-bit registers: the register
   file, buses, ALU, result multiplexer, R, T, MQ, store data and queue
   halve, about 75 chips fewer than this one; but nearly every 32-bit
   operation takes two microcycles, so about 1.7–2 times this mini's
   time. A 16-bit datapath suits a 16-bit ISA better; for draft 2 the
   first option gives more for less.
3. **Both,** for the smallest machine: perhaps 230–250 chips for the
   board, about three times slower than this one: about draft 1b's
   speed.

Not proposed: SMD parts (16-bit 74ABT16xxx would save about 50 packages
as on draft 2's CPU, but only in fine-pitch packages), or programmable
logic (a 22V10 would replace several gates and decoders each).

### 17. ISA features and what they cost

In a microcoded machine most of an ISA costs only microcode, which is free
in the flash. What costs chips is datapath, and the features that need it
are few:

- **Multiply and divide:** MQ and its step logic, 6 chips. Without them
  the suite would take +54% (21% of its cycles are multiply and divide
  steps, `mandel`'s most of all). **Keep.**
- **Bytes and halves:** the lanes that move a loaded byte or half down
  and replicate a stored one, 13 chips, +18–25% without them. **Keep.**
- **Rotations by 8 and 16** in the result path, 8 chips: the byte and
  half work and the constants use them; +18–25% without. **Keep.**
- **Reads at the A bus** (`[R]` loads in one cycle): 6 chips, +6.5% on
  the suite. A candidate.
- **The tagged operations, `MULA`, `MULFX`, `ADD.B4`, `MERGE`, `LDM` and
  `STM`:** microcode only, nothing to gain.
- **Flags by size** (N from bits 7 or 15, Z by bytes): used by 0.2% of
  cycles; dropping them would save perhaps 3 chips and change the ISA.
  Not worth it.

### 18. The video

- **Its own bank.** The first plan had the video read the one RAM in the
  CPU's tail ticks. That shares the data bus with the I/O space: during a
  long I/O access (the CF card's 16 wait states) or several in a row the
  bus is the I/O's, and the video, which needs a word every 16 ticks,
  starves. With bank 1 on its own buses (10 chips) the video reads in
  every cycle's tail and all through an I/O access, and a read of bank 1
  costs the CPU no time ([6](#6-memory)): the static timing analysis's
  suite time didn't change when it was added.
- **Line descriptors** give, for 5 chips, what a copper would most often
  be used for: per-line start addresses (scrolling, split screens, a line
  repeated), per-line palette banks (16 of 16 colours from 65,536), and a
  line interrupt for the rest (the CPU changes the palette or the table at
  a given line).
- **Higher resolutions.** 640 × 480 × 4 needs a word every 16 ticks; the
  slots come every 11 at most. 640 × 480 × 8, or 800 × 600 × 4 (a 40 MHz
  pixel clock, a word every 10 ticks), would need the video to take bank
  1 also in cycles that don't use it (most cycles): possible with this
  design, a few chips more, **not built**. 320 × 240 × 8 (pixels and lines
  doubled, a descriptor repeating a line) is within today's bandwidth and
  needs only another shifter arrangement. 1024 × 768 (65 MHz) is out of
  reach.

### 19. Blitting in microcode

From [performance.md](0041-rfc-heron-mini/performance.md#the-block-instructions),
ticks a word, on the model:

| Kernel | Draft 2 code | Block instruction | |
|---|---:|---:|---:|
| Fill | 20.3 | 7.3 | 2.8× |
| Copy | 35.5 | 19.3 | 1.8× |
| Copy shifted 4 bits | 102.1 | 54.5 | 1.9× |
| Copy shifted 12 bits | 150.1 | 54.5 | 2.8× |
| Copy shifted 28 bits | 246.2 | 54.6 | 4.5× |
| Expand a glyph | 85.0 | 47.3 | 1.8× |

A screen fill takes 5.6 ms, a screen copy 15 ms, a shifted one 42 ms
whatever the shift. What the microcode gains: no instruction fetches and
decodes, and a rotation planned per instruction from the byte and half
rotations (draft 2's `ROR` by a register goes a bit a cycle). What it
can't: the datapath does one ALU operation and one memory access a cycle,
and a store's data must come over the A bus, so a copy is still three
cycles a word. A copy register on the data bus (4 chips) would make it
two; a nibble rotator (about 16 chips) would make a shifted copy as fast
as an aligned one. Neither is in the netlist.

### 20. A fast link

What's cheapest, from no chips up:

- **The UART:** SLIP or PPP to a PC through a USB-serial adapter: 11
  KB/s at 115,200 baud; 90 KB/s at 921,600 with a 14.7456 MHz crystal (the
  TL16C550C takes up to 16 MHz) and the 82C54 then clocked from
  elsewhere.
- **A USB FIFO on an expansion port:** an FTDI UM245R module (DIP-24, an
  FT245R) on D0–D7 with its RD and WR from the port's strobes: about 1
  MB/s to a PC, no other chips. The hackiest fast link that works.
- **Ethernet on an expansion port:** an ENC28J60 (DIP-28, SPI, 10BASE-T)
  behind a few chips of SPI shift register, raw frames to a PC or a small
  TCP/IP in software; or a WIZnet W5100 module on the parallel bus, which
  does TCP/IP itself. Or, hackiest, an NE2000 ISA card on an adapter: the
  port's strobes are about ISA's, but its address is 8 bits.

### 21. Sound

The 82C54's counter 2 drives a speaker (a transistor), as on a PC. For
music, an FM synthesiser on an expansion port: a YM3812 (OPL2, DIP-24)
with its YM3014B DAC (DIP-8) and an op-amp, its 3.58 MHz from its own
oscillator; its write timing fits the ports' strobes, and the waits it
needs between writes (3.3 µs and 23 µs) are software's. A YM2151 (OPM)
the same way. On the board itself it would be about 4 chips; **open**.

### 22. The board

- **Size:** DIP boards take about 630 mm² a chip on four layers (RFC
  0023's DIP CPU card, 269 chips on 490 × 345 mm). 427 chips is about
  0.27 m² (600 × 450 mm), 300 about 0.19 m² (490 × 385 mm). One board of
  that size is possible (DEC's hex boards were 533 × 399 mm) but large;
  two stacked boards of half the size, the CPU on one and the RAM, video
  and I/O on the other, would need about 100 signals between them (the
  address and data buses, the video's bank, the strobes), two
  board-to-board connectors rather than a backplane. **Open.**
- **Power:** from the datasheets' supply currents, roughly 8–10 A at 5 V
  (the 74F counters, ALUs and multiplexers and the SRAMs most of it).
- **SMD:** the SRAMs only (eighteen in SOJ), as no fast SRAM is made in
  DIP; the CF card's socket.

### 23. How it was checked

- **The model against draft 2's simulator:** the suite and the compiled C
  programs, output, registers, flags and memory (`heron mini check
  [--c]`).
- **The netlist against the model,** on the chip-level simulator with the
  datasheets' worst-case delays: every program, cycle for cycle (each
  instruction fetch at the same cycle), with the same output, registers
  and memory, no timing violation, at the length classes static timing
  analysis gives (`heron mini hw test [--c]`, and `interrupts` by name);
  the boot copy; the block instructions (`heron mini hw blocks`).
- **The devices:** a program using both UARTs, the boot flash, the CF card
  (16-bit `READ SECTORS`) and the 82C54's interrupt, against its expected
  output, the device models checking their datasheets' strobe, address and
  data timing (`heron mini hw devices`).
- **The video:** a program setting up descriptors, palette and pixels,
  its frames captured from the netlist's outputs and compared pixel for
  pixel with what the memory describes (`heron mini hw video`).
- **Static timing analysis** of every microinstruction in every queue and
  interrupt state, and the I/O hold's deadline (`heron mini hw sta`).

The compiled C programs at chip level found one path the static timing
analysis didn't check: the queue slots' J-K flip-flops are on the master
clock, which the analysis held constant, and a conditional jump that
consumed a parcel reached them from the flags through 17 gates (its
condition masked the consume, which moved the queue's head, which decided
which slot would be empty). `sha256`'s inner loop missed their setup by
0.2 ns. The analysis now checks them, and the consume is no longer masked
by the jump (the PC loads and the queue empties whatever the head does),
which leaves the jump 6 ticks.

Contention: the B bus's drivers overlap by up to 6 ns as they hand over,
as on draft 2's CPU, between drivers built for it.

### 24. Open questions

For Emily:

1. **The CPU:** build a draft 1b-like core for draft 2 (fewer speed
   features, perhaps 110–140 chips fewer, perhaps 1.2–1.4 times slower),
   or keep draft 2's CPU with the reductions of [15](#15-what-could-be-left-out)
   (about 375 chips)? ([16](#16-toward-250-chips))
2. **The reductions:** which of [15](#15-what-could-be-left-out)'s, for a
   lean version of this one?
3. **One board or two stacked,** and how large ([22](#22-the-board)).
4. **The video:** its own bank (as built) or the one RAM; descriptors;
   the palette's width; an 8-bit or 800 × 600 mode ([18](#18-the-video)).
5. **The block instructions:** keep them; add a copy register for faster
   copies; allow counts over 256 ([19](#19-blitting-in-microcode)).
6. **The I/O map:** the regions, the free region 4, the expansion ports'
   pinout and number, an FM synthesiser on the board ([7](#7-the-io-space),
   [8](#8-expansion-ports), [21](#21-sound)).
7. **The UARTs' clock:** 1.8432 MHz (as built, the 82C54 shares it) or
   14.7456 MHz (921,600 baud) ([20](#20-a-fast-link)).
8. **The name:** Heron Mini, or a smaller heron: the bittern.

### 25. Next steps

- With Emily's answer to the first question, the leaner CPU as a netlist
  of its own, measured the same way.
- The video's 8-bit mode, if wanted.
- Egret's desktop on the mini: its display through the video's registers
  and descriptors, its kernels as block instructions, measured on the
  model.
