---
number: 41
type: rfc
title: "Heron Mini: draft 2 without a system bus"
status: open
date: 2026-10-17
context:
  studies: [mini, v2_isa, v2_hw, v1b_hw, v1b_tradeoffs, v1b_system, c_compiler, lisp]
  commit: 3d43d93
depends-on: [16, 23, 24, 28, 29, 31]
---

# RFC 0041: Heron Mini: draft 2 without a system bus

A small Heron beside the full one, as the 360/20 was beside the 360/40:
draft 2's user instruction set ([RFC 0028](0028-rfc-draft-2-isa.md)) with
its RAM wired to the CPU and no system bus, a few devices in an I/O space,
and a framebuffer, for Egret's desktop and for games. Compatibility with
the full Heron is not a goal; running draft 2's programs is. Part I
specifies the machine as built; Part II is what it measures, what it
costs, what could be left out or added, and what's left for Emily to
decide. The video's modes and features are
[RFC 0042](0042-rfc-mini-video.md)'s.

The study is [studies/mini](../studies/mini/README.md): the microcode, a
register-transfer model checked against draft 2's instruction-level
simulator, a fast simulator for software, and a chip-level netlist of the
whole machine: CPU, RAM, I/O devices and video. On the chip-level
simulator the netlist runs the program suite exactly as the model does,
cycle for cycle, with no timing violation, at cycle lengths that static
timing analysis of the netlist measures; the devices and the video are
checked against what their programs should give. The tables are in
[performance.md](0041-rfc-heron-mini/performance.md).

As Emily asked, the netlist was first **overbuilt**: every feature that
seemed useful, built in full, with what could be left out estimated by
taking chips out of it rather than by guessing what adding a feature
costs ([15](#15-what-could-be-left-out)). Since then 22V10s have taken
the place of most of its gates, decoders and small multiplexers.

## Summary

- **It works, at chip level.** 334 packages. The suite and the compiled C
  programs run on the netlist exactly as on the model, at three cycle
  lengths, 5, 6 and 7 ticks of 19.86 ns (half the VGA pixel clock); the
  UARTs, the 82C54, the CF card and the boot flash do what a test program
  expects of them; the video sends the frame its memory describes.
- **Fast:** the suite and the C programs take 1.05 times the full
  Heron's time ([RFC 0031](0031-rfc-draft-2-cpu.md)), what the
  instruction-level simulator's reference timing would take at about
  13 MHz. Egret's desktop would type a character in under 5 ms and open
  its class browser in about 160 ms ([13](#13-how-fast)).
- **Draft 2's CPU, cut down,** is the CPU: Emily's choice over a draft
  1b-like core ([16](#16-the-cpu-and-the-smaller-ones-considered)). The
  CPU is 237 packages, 266 with its memory; which of the reductions to
  take is open ([15](#15-what-could-be-left-out)).
- **Two stacked boards for the core,** A4, at most about 190 chips each;
  whether the video and the I/O go on them or a third board is open, and
  so is how the microcode gets updated without taking the stack apart
  ([28](#28-the-boards)).
- **A programmable clock chip** is to replace the oscillator: the CPU at
  any speed down to single steps, the video's clocks in step with it
  ([20](#20-the-clock)).
- **Multiply and divide stay in hardware:** without the MQ register
  (6 chips) the suite would take half as long again ([17](#17-isa-features-and-what-they-cost)).
- **So does the address error** (3 packages, no time): the Lisp's `car`,
  `cdr` and calls check their operand's type with it; without it its
  programs would take 17–19% longer ([17](#17-isa-features-and-what-they-cost)).
- **The video costs the CPU nothing.** It has the RAM's second bank to
  itself through buffers, takes its words in cycles' tails and in I/O
  waits, and never holds the CPU ([9](#9-video), [18](#18-the-video)).
- **Blitting in microcode** gains 1.7 to 3.9 times over draft 2 code for
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
  - [16. The CPU, and the smaller ones considered](#16-the-cpu-and-the-smaller-ones-considered)
  - [17. ISA features and what they cost](#17-isa-features-and-what-they-cost)
  - [18. The video](#18-the-video)
  - [19. Blitting in microcode](#19-blitting-in-microcode)
  - [20. The clock](#20-the-clock)
  - [21. Microcode tasks](#21-microcode-tasks)
  - [22. Keyboard and mouse](#22-keyboard-and-mouse)
  - [23. A fast link](#23-a-fast-link)
  - [24. Sound](#24-sound)
  - [25. More RAM](#25-more-ram)
  - [26. A 74HCT mini](#26-a-74hct-mini)
  - [27. Software to try](#27-software-to-try)
  - [28. The boards](#28-the-boards)
  - [29. How it was checked](#29-how-it-was-checked)
  - [30. Open questions](#30-open-questions)
  - [31. Open tasks](#31-open-tasks)

## Part I: Specification

### 1. Overview

A microcoded 32-bit CPU, its 4 MB of RAM, an I/O space and a video
generator, with no bus between them. The parts are
[RFC 0024](0024-rfc-faster-smaller.md)'s fast set in packages for hand
soldering: 74F and 74ABT logic in DIP (74ACT only for counters whose
enables 74F can't set up in time, and 74HCT for the power-on reset's
Schmitt trigger), ATF22V10C-5 programmable logic (5 ns, 22 of them),
74F181 ALUs, SST39SF010A flash (55 ns, DIP-32), and 12 ns SRAM in SOJ,
the only surface-mount chips: AS7C256A-12 for the register file and the
palette, AS7C4096A-12 for the RAM.

- **Clock:** a 50.35 MHz oscillator, twice VGA's pixel clock; a cycle is
  5, 6 or 7 of its ticks (19.86 ns), as the microinstruction's length
  class says, plus two when a parcel must be fetched in the cycle that
  reads it, plus an I/O access's wait states ([4](#4-clock-and-cycles)).
  A programmable clock chip is to take the oscillator's place
  ([20](#20-the-clock)).
- **CPU:** draft 2's CPU ([RFC 0031](0031-rfc-draft-2-cpu.md)) without
  its system half: the same datapath and prefetch queue, a 128-bit
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
  per line and a palette of 256 RGB 5:6:5 entries ([9](#9-video)); more
  modes are [RFC 0042](0042-rfc-mini-video.md)'s.

### 2. Instruction set

The user level of draft 2 ([RFC 0028](0028-rfc-draft-2-isa.md)) with
draft 2's *plain machine*, the one draft 2's instruction-level simulator
runs without a supervisor:

- **Traps and the interrupt:** vectors are code addresses from 0: reset 0,
  the interrupt 4, an illegal instruction 8, `SWI` 0x0C, a divide error
  0x10, an address error 0x14, a tag check 0x18. Taking one pushes the
  flags word and then the PC (`sp − 8` and `sp − 4`), clears I and jumps
  to the vector; `RTI` undoes it.
- **The address error:** a half at an odd address, or a word at one that
  isn't a multiple of 4, traps with the instruction's own address, and
  the instruction changes nothing: no register, flag, memory or device.
  The Lisp's `car`, `cdr` and calls check their operand's type with it
  ([17](#17-isa-features-and-what-they-cost)). A misaligned `sp` as a trap
  is taken faults again, without end (draft 2's simulator stops).
  Jumps ignore bit 0 of the target, as on draft 2.
- **One interrupt line,** level-sensitive, taken at an instruction's end
  when I is set ([7](#7-the-io-space) has its sources). `EI` and `DI` set
  and clear I; `HALT` waits for an interrupt if I is set and stops the
  machine otherwise.
- **`ccr`** holds the flags word (V C Z N I in bits 0–4) for `MFSR` and
  `MTSR`. There are no other special registers.
- **Left out:** RFC 0029's modes, register banks (`MFUR` and `MTUR` are
  illegal), address translation and the other special registers.
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

[RFC 0042, 10](0042-rfc-mini-video.md#10-block-instructions) has their
variants for other pixel sizes, microcode only.

### 3. Address map

| Address | What |
|---|---|
| 0x0000_0000–0x001F_FFFF | RAM bank 0, 2 MB |
| 0x0020_0000–0x003F_FFFF | RAM bank 1, 2 MB, also the video's ([9](#9-video)) |
| 0x0040_0000–0x7FFF_FFFF | the RAM again, every 4 MB |
| 0x8000_0000 + r × 0x1000_0000 | I/O region r, 0–7 ([7](#7-the-io-space)) |

### 4. Clock and cycles

RFC 0024's clock generator for short cycles, as draft 2's CPU has it
([RFC 0031, 2](0031-rfc-draft-2-cpu.md#2-clock-and-cycles)), in two
22V10s on the master clock, with two tail ticks: a cycle of K ticks runs
H0 and H1, a 4-bit count from a preload to 15, then T1 and T2; the CPU's
clock rises entering H0. The register file is read in the cycle's first
part, its latches transparent, and written in T2; RW (T1 or T2) switches
its address to the write address once its latches have closed, and its
SRAMs drive their outputs until T2, so that a read has until the latches
close. The memory's write window is from tick 2 to T1.

- **Length classes:** up to four, chosen to minimise the suite's time over
  what static timing analysis measures each microinstruction to need
  (`ticks.json`): 5, 6 and 7 ticks, as the netlist stands. A
  microinstruction's 2-bit field picks one; the preloads are the clock
  generator's equations, so the classes are its program.
- **Data accesses take 7 ticks or more** (K_DATA): the I/O hold below
  must start before the count ends.
- **A demand fetch** (a parcel read from the queue's head when the queue
  is empty, so from the word the cycle fetches) lengthens its cycle by two
  ticks, through the preload. Every microinstruction that may make one is
  in the 5-tick class as the microcode stands, so no cycle outside an I/O
  hold is longer than 7 ticks ([RFC 0042, 9](0042-rfc-mini-video.md#9-bandwidth-and-the-cpu)
  depends on it).
- **The I/O hold:** an access to the I/O space stops the count from tick 4
  for the region's wait states ([7](#7-the-io-space)).

### 5. CPU

The datapath and the fetch are draft 2's CPU's
([RFC 0031, 3–4](0031-rfc-draft-2-cpu.md#3-datapath)), with 8-bit parts
where it has 16-bit ones, without the system half, and with the
differences below. In brief:

- **Register file:** 32 registers (r0–r15 and the microcode's own) in one
  copy of four 32K × 8 SRAMs, read twice in a cycle that reads both ports
  from it: the A address until the late phase (H0 and H1 over), its
  74ABT573 latches closing then, the B address after, its own latches
  closing as RW rises; written through 74ABT541 buffers in T2. The
  addresses (from the instruction, a counter SX or the microinstruction)
  and the A latches' enable come from three 22V10s.
- **Buses:** an A bus (a register, PC, R, R × 2) and a B bus (a register,
  R, the loaded word T by byte lanes, the queue's head parcel four ways,
  the immediate unit, MQ, the flags word), 74ABT541 drivers.
- **ALU and result:** eight 74F181 with their carry lookahead in a 22V10;
  a result multiplexer (74F153 × 16) that passes, shifts right by one,
  rotates by 8 or 16 and clears bytes; MQ (four 74F299) for multiply and
  divide steps.
- **Registers:** R, T (a latch on the data bus, by lanes), MAR (a counter
  for 22 bits and the top four), the loop counter LC, SX and EX, the
  flags (N, Z as four bytes' worth, C, V, I, in two 22V10s) and the
  condition latch CL (a 22V10 with the divide step's sign).
- **Fetch:** PC, a fetch counter FPC and a prefetch queue of two 32-bit
  words, filled in cycles that don't use memory; the decode reads the
  queue's head parcel; a parcel needed when the queue is empty comes from
  the word the cycle fetches. The queue's control is two 22V10s.
- **Control store:** 128K words of 128 bits (124 used) in sixteen
  SST39SF010A, pipelined: addressed with the next microinstruction's
  address, clocked into a microinstruction register of sixteen 74ABT574
  at every edge. Its upper half holds every instruction's first
  microinstruction at the address of its first parcel, so a decode is the
  queue's head parcel on the address lines: there's no decode table. The
  refill, the interrupt entry and the address error's entries fill their
  own pages, so that forcing one changes only the address's top bits.
  The next address's condition, the decode's glue and the branch
  condition are a 22V10 each. The flags' seven fields are one 5-bit code
  in a fixed table of 32 behaviours (`ucode.FLAG_TABLE`), not the
  combinations the microcode happens to use.
- **The address error:** a misaligned data access (decoded with the
  memory's write enables, in a 22V10) turns off the cycle's memory
  write, device strobe (an I/O access still holds the cycle),
  register-file write, flags load, and the PC's and the IR's part of a
  jump or a decode, and forces the next address to one of four pages:
  by the number of parcels the instruction has consumed, which each
  microinstruction that accesses data carries in two of the control
  word's spare bits, so that the fault's microcode can wind the PC back
  to the instruction. The prefetch queue goes on as if there were no
  fault: the fault's microcode reads nothing from it, and its jump to
  the vector empties it.

Different from draft 2's CPU: no page map or window, no register banks or
special registers but `ccr`, no message level or interrupt levels, no
trace, one register-file copy, and the control store in flash (so no
boot through an I/O processor: the microcode is programmed like a ROM;
[28](#28-the-boards) is about updating it).

### 6. Memory

One access a cycle, a fetch or a data access, at an address from MAR,
FPC or the A bus (74F153 × 13, bits 21–0 and 31–28; 27–22 aren't
decoded), 32 bits wide with byte enables; a store's data is the A bus,
replicated by size. The decode and the write enables are three 22V10s.

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
  strobe ends within T1, before the video's slot changes the address.

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
| 4 | 0xC000_0000 | 8 | 179 ns | **open** (free; the keyboard and mouse, [22](#22-keyboard-and-mouse)) |
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
porch, 45–524 the picture). The syncs are active low. The other modes,
layouts, the cursor and the rest are options in
[RFC 0042](0042-rfc-mini-video.md), which this section's design is the
base of.

- **Timing:** a pixel counter, a character counter (0–99) and a line
  counter (0–524), and a timing ROM (an SST39SF010A addressed by the
  character and the line) whose byte is registered at each character's
  end: the syncs, the picture, when the shifters load, when a line's
  descriptor is read, the line's and the frame's ends. Three 22V10s make
  the pixel phase, the slots and the registers.
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
  the CPU (they can't be read); a 74ABT823 per colour byte, on the master
  clock, registers each pixel, its outputs off (black, the monitor's
  75 Ω pulling the resistor DACs down) outside the picture.
- **Registers** ([7](#7-the-io-space)): the control register (bit 0 the
  picture on, 1 `TSEL`, 2 the interrupt on) and the interrupt's
  acknowledge. The interrupt is set as the picture ends (the frame's last
  line) and by a line whose descriptor asks; it is bit 4 of the interrupt
  status.
- **Fetching:** the video reads bank 1 in its slots (the end of every
  cycle and an I/O access's hold), always the word at its address
  counter, into a holding register; the counter steps as the shifters
  (four 74F299) take that word, at each character's end. A slot comes at
  least every 7 ticks (the longest cycle outside an I/O hold, whose ticks
  are all slots) and a word is needed every 16, so the video never waits
  and never holds the CPU.

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

334 packages as built, of which 237 are the CPU (266 with its memory
interface and bank 0); by area (the full list is in
[performance.md](0041-rfc-heron-mini/performance.md#parts)):

| Area | Packages |
|---|---:|
| CPU: control store, sequencer, conditions | 48 |
| CPU: clock, reset, hold | 8 |
| CPU: register file | 20 |
| CPU: buses, immediate unit | 53 |
| CPU: ALU, result multiplexer, MQ | 36 |
| CPU: R, T, MAR, LC, SX, EX | 27 |
| CPU: flags | 8 |
| CPU: PC, FPC, queue | 37 |
| Memory: address, decode, store data, bank 0 | 30 |
| Video RAM: bank 1, its buffers | 16 |
| I/O | 16 |
| Video | 37 |

The most numerous parts: 66 74ABT541 (the buses' drivers), 41 74F153,
23 74ABT573, 23 74F161, 22 ATF22V10C-5, 18 SST39SF010A (the control
store, the video's timing and the boot flash).

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
carries draft 2's CPU's speed features along (the queue, reads at the A
bus, short variable cycles), and with them most of its chips. The first
netlist was 430 packages; 22V10s in place of gates, decoders, small
multiplexers and the carry lookahead, and one register-file copy read
twice a cycle in place of two, took it to 334, and the timing that came
with them made it faster rather than slower (the suite went from 523.5
to 495.2 ms). Emily has since chosen to keep this CPU
([16](#16-the-cpu-and-the-smaller-ones-considered)), A4 boards of at most
about 190 chips, and two of them stacked for the core
([28](#28-the-boards)).

### 13. How fast

| | Mini | Full Heron (RFC 0031) | |
|---|---:|---:|---:|
| The suite, hand-written | 495.2 ms | 465.3 ms | 1.06× |
| Compiled C | 295.9 ms | 287.8 ms | 1.03× |
| Both | 791.2 ms | 753.1 ms | 1.05× |

The per-program table is in
[performance.md](0041-rfc-heron-mini/performance.md#the-suite). The mini
is a little slower than draft 2's CPU for three reasons: its control store
is flash, so the microinstruction register's outputs come later; its data
accesses take at least 7 ticks, for the I/O hold; and its parts are 8-bit
(a 74ABT574 clocks out later than a 74ABT16374).

Against the instruction-level simulator's reference timing (D16-overlap,
the one report 0021 quotes "at 3 MHz"), the mini takes on the suite what
the reference would at about 12.8 MHz, and on the C programs at 13.9:
over four times that report's speeds. So Egret's desktop ([report
0021](0021-report-egret-gui.md), on draft 2 at 3 MHz in its *On draft 2*
table) would, on the mini, type a character in under 5 ms, open the
Browser in about 160 ms, compile itself at boot in about 4.2 s, and run
Gadgets' table at its full 30 frames a second. Multiplication-heavy work
gains less: `mandel` runs at a 7 MHz reference's speed. The block
instructions ([19](#19-blitting-in-microcode)) would take a little more
off drawing, which is 10–40% of the desktop's time in report 0021's
breakdown.

15% of the cycles need 7 ticks, most of them memory operands through T's
byte-lane latches: the late phase (LATE), T's latch enable, its lanes,
the ALU, the flags. The register file's reads had the same chain until
its address logic took the clock generator's H0 and H1 itself, a 22V10
sooner, which brought register-to-register `ADD` and `CMP` back to 6
ticks; the same for T might do the same for these (an open task,
[31](#31-open-tasks)).

### 14. Chips

Where the 334 go ([11](#11-parts)): the CPU is 237, four fifths with its
memory interface. Against draft 2's CPU (394 for its core with 16-bit
parts, about 460 with its bus interface), the mini drops the system half
(the page map, the window, the banks, the interrupt levels, the bus) and
the second register-file copy, but keeps the datapath and the fetch,
which are most of it. Against draft 1b's CPU (213 chips with its memory
interface, report 0012) it has a prefetch queue and fetch counter, reads
at the A bus, a 32-bit memory (16-bit on 1b) and the fast clock
generator: what makes draft 2's CPU 1.35 times as fast as 1b's fast
system on the same programs ([RFC 0031](0031-rfc-draft-2-cpu.md#12-how-fast)),
and the mini within 5% of draft 2's CPU.

The buses' drivers and the multiplexers are now most of the CPU: 66
74ABT541 and 41 74F153, the A and B buses' sources, the address
multiplexer, the result multiplexer. 16-bit parts (74ABT16541) would halve
them, but only in fine-pitch packages; a 22V10 is no help with a 32-bit
bus.

The microinstruction is dense: its fields need 124 of their 128 bits one
by one, the flags' seven fields already one code. Grouped further (the A
bus's sources, the B bus's, the ALU's), 56 bits would do, but only with
decode memories as fast as the SRAM, which would cost more chips than the
flash and latch pairs they'd save; decoding the few one-hot groups with
74F138s would save two or three pairs for a gate's delay in their paths.

### 15. What could be left out

Each taken out of the netlist, with what it adds back, and its time on the
suite and the C programs: measured on the model's variant where the model
has one, otherwise estimated from the profile (the rule is in
`reduce.py`). From [performance.md](0041-rfc-heron-mini/performance.md#what-could-be-left-out):

| Reduction | Chips | Suite | C | What's lost |
|---|---:|---:|---:|---|
| A prefetch queue of one word | 8 | +9.7% | +11.0% | measured |
| No reads at the A bus (MAR and FPC only) | 6 | +6.8% | +1.7% | a load at `[R]` takes a cycle more |
| No MQ | 6 | +56.6% | +55.9% | multiply and divide steps take three cycles more |
| Byte and half lanes in microcode | 13 | +25.9% | +18.9% | a byte or half load or store takes three cycles more |
| No rotations by 8 and 16 | 8 | +19.0% | +26.3% | a rotation becomes 8 or 16 shifts |
| The video in the one RAM | 10 | | | the video can be starved by long I/O accesses |
| No line descriptors | 4 | | | per-line addresses, palette banks and interrupts |
| An 8-bit palette | 3 | | | 256 of 65,536 colours become 256 of 256 |
| No latch for the devices' address | 2 | | | 12 ns of address hold where the 16C550 and the CF card want 20 |
| No interrupt status, no control register, one UART | 3 | | | |

The second register-file copy, the first version's largest reduction (13
chips for about 5%), is taken: the netlist has one copy, read twice a
cycle, and the early register-file phase won its time back
([13](#13-how-fast)).

Which to take is **open**; the case for each, now that the core is two
A4 boards of at most about 190 chips ([28](#28-the-boards)) and chips
matter by the board rather than by the total:

- **MQ, the byte lanes and the rotations:** worth their chips by a wide
  margin (19–57%). Keep.
- **The queue's second word** (8 chips, 10–11%) and **the reads at the A
  bus** (6 chips, 7% on the suite, 2% on C): the cheapest time in the
  machine; the first to go if a board is over, the last otherwise. The C
  programs barely use `[R]` loads in one cycle, so the reads at the A bus
  are the better one to lose.
- **The video's own bank** (10 chips): what lets the video read through
  I/O accesses, and what [RFC 0042](0042-rfc-mini-video.md)'s bandwidth
  (B0, no stealing) rests on. Keep.
- **The descriptors** (4 chips): kept, as Emily chose (RFC 0042's D0).
- **The 8-bit palette** (3 chips): the graphics software uses the 16-bit
  colours and the per-line banks. Keep.
- **The devices' address latch** (2 chips): the 16C550's and the CF
  card's datasheet hold times. Keep.
- **The interrupt status, the control register, the second UART** (3):
  small conveniences; the interrupt status becomes more useful with the
  keyboard and mouse ([22](#22-keyboard-and-mouse)).

So the likely reductions are the reads at the A bus and perhaps the
queue's second word, 6–14 chips for 7–17%, and only if a board needs
them; the board split decides ([31](#31-open-tasks)).

### 16. The CPU, and the smaller ones considered

Emily's choice is this CPU: draft 2's, cut down, with the 22V10s. The
first version of this RFC asked whether to build a smaller one instead,
when the board was 430 and the target 200–300; these were the options,
kept here as considered:

1. **A draft 1b-like core for draft 2:** one register-file access a
   phase, no prefetch queue, a 16-bit memory and a simpler clock; perhaps
   200–230 chips with its memory interface, perhaps 1.2–1.4 times this
   one's time. Draft 1b's fast system took 1.35 times draft 2's CPU's
   time on draft 1's programs.
2. **A 16-bit datapath** for draft 2's 32-bit registers: about 75 chips
   fewer, about 1.7–2 times the time; a 16-bit datapath suits a 16-bit
   ISA better.
3. **Both,** for the smallest machine: perhaps 230–250 chips for the
   board, about three times slower: about draft 1b's speed.

Not proposed: SMD logic (16-bit 74ABT16xxx would save about 50 packages,
but only in fine-pitch packages).

### 17. ISA features and what they cost

In a microcoded machine most of an ISA costs only microcode, which is free
in the flash. What costs chips is datapath, and the features that need it
are few:

- **Multiply and divide:** MQ and its step logic, 6 chips. Without them
  the suite would take +57% (21% of its cycles are multiply and divide
  steps, `mandel`'s most of all). **Keep.**
- **Bytes and halves:** the lanes that move a loaded byte or half down
  and replicate a stored one, 13 chips, +19–26% without them. **Keep.**
- **Rotations by 8 and 16** in the result path, 8 chips: the byte and
  half work and the constants use them; +19–26% without. **Keep.**
- **Reads at the A bus** (`[R]` loads in one cycle): 6 chips, +6.8% on
  the suite. A candidate ([15](#15-what-could-be-left-out)).
- **The address error:** 3 packages and no time: the suite's
  microinstructions keep their lengths. The fault reaches the register
  file, the flags, the IR, the PC and the next address, but not the
  queue, whose paths are the tightest: the queue does as it would, and
  the fault's microcode empties it with its jump. The first version of
  this RFC left it out, but the Lisp relies on it: `car` is `MOV r,
  [p − 1]`, aligned only if `p` is a pair, and a call jumps through
  `[p + 1]`, aligned only for an object with a call slot (a procedure's,
  or an error routine's), so its type checks cost nothing. Without the
  trap they'd be instructions: report 0018 estimates its programs 17%
  slower compiled and 19% interpreted
  ([its what-if costings](0018-report-lisp/performance.md#what-if-costings),
  on draft 1b). **Keep.**
- **The tagged operations, `MULA`, `MULFX`, `ADD.B4`, `MERGE`, `LDM` and
  `STM`:** microcode only, nothing to gain.
- **Flags by size** (N from bits 7 or 15, Z by bytes): used by 0.2% of
  cycles; dropping them would save perhaps 3 chips and change the ISA.
  Not worth it.

And for draft 2's ISA as a whole, which the mini only follows:

- **Addressing modes** ([aiju/heron#81](https://github.com/aiju/heron/issues/81)):
  Emily's review finds abs16, abs24 + x × s and abs32 luxurious, and
  they tie the memory map to the ISA. On the mini they cost microcode
  only, so it neither gains nor loses chips by any outcome; their
  encodings would free parcels for other instructions.
- **`LDM` and `STM` with increments** ([aiju/heron#82](https://github.com/aiju/heron/issues/82)):
  autoincrement and autodecrement forms; microcode only on the mini.
- **Floating point in microcode:** draft 2 has none. Single-precision
  add, multiply, divide, compare and conversions as instructions would be
  microcode only: the ALU for exponents and mantissas, MQ for the
  mantissa's multiply and divide steps, LC loops for the shifts that
  align and normalise. Faster than the same in draft 2 code by what the
  block instructions gain (no fetches and decodes, a shift planned per
  instruction), but an ISA question first: which encodings, and whether
  the full Heron would follow.

### 18. The video

[RFC 0042](0042-rfc-mini-video.md) has the video's options: more modes,
layouts, the cursor, the bandwidth, and a 15 kHz family for a Sony PVM
(**open**); its report, [report 0043](0043-report-mini-graphics.md), is
graphics software written against them. Two things from building it:

- **Its own bank.** The first plan had the video read the one RAM in the
  CPU's tail ticks. That shares the data bus with the I/O space: during a
  long I/O access (the CF card's 16 wait states) or several in a row the
  bus is the I/O's, and the video, which needs a word every 16 ticks,
  starves. With bank 1 on its own buses (10 chips) the video reads in
  every cycle's tail and all through an I/O access, and a read of bank 1
  costs the CPU no time ([6](#6-memory)).
- **Line descriptors** give, for 4 chips, what a copper would most often
  be used for: per-line start addresses (scrolling, split screens, a line
  repeated), per-line palette banks (16 of 16 colours from 65,536), and a
  line interrupt for the rest. The graphics software used them more than
  anything else.

### 19. Blitting in microcode

From [performance.md](0041-rfc-heron-mini/performance.md#the-block-instructions),
ticks a word, on the model:

| Kernel | Draft 2 code | Block instruction | |
|---|---:|---:|---:|
| Fill | 19.0 | 7.3 | 2.6× |
| Copy | 33.0 | 19.3 | 1.7× |
| Copy shifted 4 bits | 93.1 | 54.4 | 1.7× |
| Copy shifted 12 bits | 133.1 | 54.5 | 2.4× |
| Copy shifted 28 bits | 213.2 | 54.6 | 3.9× |
| Expand a glyph | 81.0 | 47.3 | 1.7× |

A screen fill takes 5.5 ms, a screen copy 15 ms, a shifted one 42 ms
whatever the shift. What the microcode gains: no instruction fetches and
decodes, and a rotation planned per instruction from the byte and half
rotations (draft 2's `ROR` by a register goes a bit a cycle). What it
can't: the datapath does one ALU operation and one memory access a cycle,
and a store's data must come over the A bus, so a copy is still three
cycles a word. A copy register on the data bus (4 chips) would make it
two; a nibble rotator (about 16 chips) would make a shifted copy as fast
as an aligned one. Neither is in the netlist.

### 20. The clock

**Decided:** a programmable clock chip takes the oscillators' place, so
that the video's pixel clocks come from it and the CPU can later run at
other speeds. **Tentatively the CY22393** (or a CDCE913), in TSSOP on a
small adapter. **Built** in the netlist:

- **The chip** (`U_CLK`, its stored configuration): CLKA 50.35 MHz, the
  master clock for VGA (its pixel clock twice); CLKB 65 MHz, XGA's pixel
  clock; CLKC 1.8432 MHz for the UARTs and the 82C54. Each from its own
  PLL. Its serial port (SCLK, SDAT) is pulled up, for a programmer on a
  header: reprogramming it from the CPU, and the debugging speeds, are
  **open** (Emily: not yet).
- **The master clock is CLKB while an XGA mode is shown,** so the whole
  machine runs at 65 MHz then and the video stays synchronous to one
  clock in both families ([RFC 0042, 2](0042-rfc-mini-video.md#2-timing)).
  The CPU's timing analysis at the 15.4 ns tick finds every
  microinstruction within 6–8 ticks (92–123 ns, against 5–7 ticks,
  99–139 ns, at 19.9 ns), so the CPU is no slower: the fixed parts of a
  cycle (the register file's read in H0 and H1, the write window from
  tick 2) still fit, with less slack (the fixed requirements' 3.4 ns at
  the least). The clock generator has a table of length classes for each
  clock (`ticks.json`, `ticks-xga.json`); the length class field's four
  classes are pairs, (5, 6), (6, 8), (7, 8) and (5, 7) ticks at the two
  clocks, the spare fourth class splitting the 5-tick one by what its
  members need at 65 MHz.
- **The switch** (`U_CKN`, `U_CKA`, `U_CKO`, `U_CKFA`, `U_CKFB`: five
  chips): each clock's enable from two flip-flops on its own falling
  edge, set only once the other's enable is off, so the master clock
  never has a short pulse; a tick is stretched as it changes. The video
  asks for the XGA clock (CLKSEL) as an XGA frame starts, but only once
  the clock generator has taken XGA's longer lengths (at an H1, as it
  loads the count), and drops it at once on the way back, so no cycle
  is ever shorter than its class at the clock it runs on.
- **A clock at power-up:** the chip's stored configuration; the switch's
  flip-flops are cleared by the power-on reset and start on CLKA.

What remains of the options, should the CY22393 not do:

| Kind | Examples | Outputs | Power-up | Notes |
|---|---|---|---|---|
| Multi-output PLL, I²C, non-volatile | CY22393 (3 PLLs, 6 outputs), CDCE913 / CDCE925 (1–2 PLLs, 3–5 outputs) | master, pixel, UART, sound | its stored configuration | 3.3 V, TSSOP: modern, on a small adapter; the outputs from one PLL in phase |
| Multi-output PLL, I²C, volatile | Si5351A (2 PLLs, 3 or 8 outputs) | as above | nothing: needs the power-up oscillator | the most common, cheap, modules everywhere; 3.3 V |
| Period dual-PLL graphics clock | ICD2061A, ICS9161A (the early-1990s SVGA cards') | two (a pixel clock and a memory clock) | VGA's frequencies | 5 V, DIP-16, serially programmed; obsolete, from surplus; its two PLLs aren't in phase, so XGA would still want RFC 0042's synchroniser |
| Pin-configured PLL | ICS525 | one | the register's reset value | the dividers from pins, so a register the CPU writes (three 8-bit registers) sets it, no protocol; one output, so the CPU's clock only |
| Programmable oscillator | DS1085, LTC6903 | one (and a reference) | stored, or set at power-up | 8–10 pins; the CPU's clock only |

The multi-output PLLs do everything asked; the period part is the one
that fits the machine's age; the single-output ones change the CPU's
speed only. None comes in PLCC.

Since the CPU is as fast at 65 MHz, a faster master clock for VGA too
(75.5 MHz, three ticks a pixel) might make it faster still; the timing
analysis at that tick would tell (**open**).

### 21. Microcode tasks

The Xerox Alto ran its devices in microcode: sixteen tasks, each with its
own microprogram counter, the hardware switching to the highest-priority
task asking for service at points its microcode marks, the instruction
set's emulator the lowest. The disk, the display and the Ethernet were
microcode with a few registers each. A limited version on the mini
would let microcode do per-line video work (a copper, sprites drawn per
line, RFC 0042's later ideas), keyboard and serial service, sound
samples or a disk's data, without an interrupt's entry and exit. What it
would take, in two strengths:

**A. Tasks at instruction boundaries** (microcode interrupts). A device
asks for its task with a wakeup line; at the next decode the decode's
glue (a 22V10) forces the task's entry page, as it forces the interrupt
entry's now, instead of the instruction's. The task's microcode runs and
ends with a decode, which starts the next instruction from the queue as
if nothing had happened. At a decode the ISA's state is the register
file's r0–r15, the PC, the queue and the flags; everything else (R, T,
MAR, LC, MQ, SX, EX, CL, the microcode's own registers) is dead, so the
task may use all of it, and the rules are few and checkable: no jumps
(the queue), the flags saved and restored if it touches them (the flags
word to the B bus and back, two cycles), nothing of r0–r15 but what it
owns by convention. Cost: the wakeup lines into the decode's glue, a
page for the tasks' entries (one of the control store's eight pages is
free: the forced entries use the refill's, the interrupt's and the
address error's four; the tasks would share it, by a wakeup number on its
low address bits), an acknowledge per task (a spare control-word bit or a
decoded strobe): **0–2 chips**. The catch is latency: a task waits for the instruction to
end, a 256-word `COPY` for three lines, a 32-bit `MULU` for about 40
cycles; the block
instructions would need switch points in their loops, where a task saves
and restores MAR, R and LC in the microcode's own registers, about six
cycles each way.

**B. Tasks at microinstructions** (the Alto's). A switch at any
microinstruction its microcode marks (a control-word bit), saving the
emulator's next address in a register (three 74ABT574) and taking it
back when the task ends (a fifth source for the next address's
multiplexers, or the forced-entry path with the saved address): **about
5–8 chips**. The latency is a few cycles. The cost is a discipline: at a
switch point the emulator's live transient registers (R, T, MAR, LC, MQ,
CL, SX, EX) must not be the task's to change, and the queue must not
move. Statically checkable: the microcode is a graph in `ucode.py`, and a
liveness pass over it gives, at each marked point, what the emulator
reads later before writing; the task's microcode may write only what's
dead at every point it can switch in, and its own registers. A task that
needs MAR or R saves and restores them. The queue keeps fetching in the
emulator's cycles only (the task's cycles don't fetch), which the queue's
control would need to know: a task bit into its 22V10s.

Either is microcode's to fill: per-line palette changes, a sprite
compositor, a PS/2 port sampled ([22](#22-keyboard-and-mouse)), a UART's
FIFO emptied into memory. **Open:** whether either is wanted, A or B, and
which tasks; A is nearly free and worth trying first in the model.

### 22. Keyboard and mouse

USB is out. **Built** (Emily: "cheap but acceptable for now"): two PS/2
ports in region 4, the keyboard's and the mouse's, seven chips for both:

- **Receiving** is a 22V10 a port (`U_PS0`, `U_PS1`), clocked by the
  port's clock through a Schmitt inverter: the data, inverted, shifts in
  at each falling edge, the start bit's 1 reaching the last register
  after ten; that register then holds the frame (through its stop bit)
  and the clock low through an open-collector inverter, so the device
  waits. The byte's eight registers drive the I/O bus as the port is
  read (the 22V10's output enables); a write to the port clears it (the
  22V10's asynchronous reset).
- **Sending** (the keyboard's LEDs, the mouse's "enable data
  reporting", which it needs before it sends anything) is software's: a
  control register (a 74ABT175) pulls each port's lines low, the status
  register reads them (a 74ABT541), and a program clocks the bits out on
  the device's clock (`sw/hw/ps2.s` sends 0xF4).
- **The registers,** by the address's bits 3–2: 0 the keyboard's byte
  (read, inverted; a write clears it), 1 the mouse's, 2 the status (read:
  bits 0–1 a byte waiting, 2–5 the lines) and the control register
  (written: bits 0–1 the keyboard's clock and data low, 2–3 the mouse's).
  A waiting byte raises the interrupt line (KIRQ); the interrupt status
  has no bit of its own for it (its eight are taken), the PS/2 status
  says which.
- **Chips:** the two 22V10s, a 74F14, a 74F05 (open collector), the
  175, the 541, and a 22V10 (`U_KBD`) for the status and control
  decode, the interrupt and the suite's I/O page's select, which moved
  there from `U_ONB` to make room for the PS/2 interrupt.

The other options, still possible: an 8042-type keyboard controller
(the PC/AT's, VT82C42 or 8742, one or two chips, period-correct, its
firmware not ours); a serial mouse on UART 1 (no chips); a
microcontroller on an expansion port (the fewest chips, the least
period-correct); or, with microcode tasks ([21](#21-microcode-tasks)), a
register of the lines sampled by a task.

#### 22.1 The debug button

**Built** (Emily: a push button that enters a microcode routine, for
now): a push button to ground, through a Schmitt inverter and a
flip-flop on CLK, sets DBGQ (`U_DBG`, a 22V10) on its press; DBGQ raises
PEND whatever the I flag, so the next instruction boundary (or a HALT)
takes the interrupt entry; the entry's first microinstruction branches on
DBGQ (a free condition code, 10) to the debug entry: the flags word and
the PC pushed as for an interrupt, interrupts off, and a jump to vector
0x1C. DBGQ clears once the interrupt entry has run. So a program stuck
in a loop with interrupts off can be broken into, and the microcode
routine can be made to do anything later (a monitor in the boot flash,
single steps). Two chips with the button (the 22V10 takes the place of
PEND's gate; the Schmitt inverter is the PS/2 ports' spare).

### 23. A fast link

What's cheapest, from no chips up:

- **The UART:** SLIP or PPP to a PC through a USB-serial adapter: 11
  KB/s at 115,200 baud; 90 KB/s at 921,600 with 14.7456 MHz (the
  TL16C550C takes up to 16 MHz), from the clock chip
  ([20](#20-the-clock)) or a crystal, the 82C54 then clocked from
  elsewhere.
- **A USB FIFO on an expansion port:** an FTDI UM245R module (DIP-24, an
  FT245R) on D0–D7 with its RD and WR from the port's strobes: about 1
  MB/s to a PC, no other chips. The hackiest fast link that works.
- **Ethernet on an expansion port:** an ENC28J60 (DIP-28, SPI, 10BASE-T)
  behind a few chips of SPI shift register, raw frames to a PC or a small
  TCP/IP in software; or a WIZnet W5100 module on the parallel bus, which
  does TCP/IP itself. Or, hackiest, an NE2000 ISA card on an adapter: the
  port's strobes are about ISA's, but its address is 8 bits.

### 24. Sound

The 82C54's counter 2 drives a speaker (a transistor), as on a PC. For
music, an FM synthesiser on an expansion port: a YM3812 (OPL2, DIP-24)
with its YM3014B DAC (DIP-8) and an op-amp, its 3.58 MHz from its own
oscillator or the clock chip; its write timing fits the ports' strobes,
and the waits it needs between writes (3.3 µs and 23 µs) are software's.
A YM2151 (OPM) the same way. On the board itself it would be about 4
chips; **open**.

### 25. More RAM

**Open,** perhaps as sockets left empty at first. The address map leaves
0x0040_0000–0x7FFF_FFFF to the RAM, which now repeats every 4 MB. More
needs the memory's address multiplexer to carry bits 22 up (27–22 aren't
decoded now: another 74F153 or two), a bank decode in its 22V10s, and
four more 512K × 8 SRAMs for each 2 MB. Each bank adds load to the CPU's
address and data buses, which the timing analysis would need to see; and
board space, which the board split decides ([28](#28-the-boards)).

### 26. A 74HCT mini

**Open:** the same machine in 74HCT, much slower, with a few exceptions
where speed is the point (the video's pixel path). The flash, the SRAMs
and the 22V10s (in slower grades) stay. The netlist names its parts by a
variant (`parts.py`), so the timing analysis can measure it rather than
guess: a variant with 74HCT's delays and the length classes it gives.

### 27. Software to try

- **A preemptively multitasking OS** in one big address space, its
  programs position-independent (draft 2's PC-relative addressing), the
  82C54's interrupt slicing time; no protection, as there's no address
  translation. A test of how far draft 2's user level goes without its
  system level; Fen ([report 0036](0036-report-fen.md)) has the parts.
- **Egret's desktop:** its display through the video's registers and
  descriptors, its kernels as block instructions.
- **Doom.** We're going to have to port Doom. RFC 0042's M1 (320 × 240 ×
  8, lines doubled by the descriptors), the C compiler, fixed point on
  `MUL`, and perhaps a textured column as a block instruction.

### 28. The boards

- **Decided:** A4 boards (297 × 210 mm) of at most about 190 chips each,
  and the CPU core on **two stacked boards**: the CPU (237) and its
  memory interface and bank 0 (30), 133 a board. **Open:** whether the
  video (37), its RAM (16) and the I/O (16) go on them too (168 a board,
  near the limit) or on a third.
- **Density:** at RFC 0023's DIP CPU card's 630 mm² a chip (269 chips on
  490 × 345 mm, four layers) an A4 board holds about 100; 190 needs about
  330 mm² a chip, so PLCC and SOIC where there's a choice, and perhaps
  more layers. The PCB study will tell ([31](#31-open-tasks)).
- **The cut:** where the two core boards part decides the connector. The
  microinstruction's 124 lines are the widest bundle; a cut that leaves
  them on one board crosses the buses instead (about 100 signals between
  the CPU and the memory, video and I/O). Board-to-board delays go into
  the timing analysis once the PCB study gives them.
- **Stacked or a backplane:** stacked boards with board-to-board
  connectors are simpler mechanically and need no extra board; a
  backplane makes each board removable, at the cost of the backplane and
  its connectors and about a nanosecond more for each signal through
  them.
- **Stacked on standoffs, joined by ribbon cables** (Emily's idea, a
  third way): the boards stacked vertically on threaded hex standoffs for
  the mechanics, the signals between them on short IDC ribbon cables, so
  that the stack comes apart one cable at a time rather than by prying a
  few hundred pins of stacking connector apart. What it takes:
  - **Grounds in the ribbon.** The edges are fast (74F, 74ABT, 22V10s),
    so a ribbon wants a ground beside each signal, or one ground for every
    two signals at most; a 64-way cable then carries 32 to 42 signals,
    and a cut of 100–150 signals between two boards is three to five
    cables.
  - **Delay.** 5–10 cm of ribbon is half a nanosecond; with the two
    headers about 1–2 ns a crossing, which the timing analysis can carry
    as a fixed delay on each crossing signal (the board split's rough
    timing does).
  - **Clocks.** The master clock and CLK should not run over a ribbon if
    it can be helped: series-terminated at the driver with grounds on
    both sides if they must, or each board makes its own phases from one
    clock.
  - **Microcode updates** get easier: the control store's board comes off
    once its cables are unplugged.
  - **Room:** shrouded headers take board edge or area, and the pinouts
    should be planned so each cable runs straight from one board to the
    next, without a twist.
- **Updating the microcode** shouldn't mean taking the stack apart:
  1. **The control store on the top board, in sockets:** the sixteen
     flashes (PLCC-32 sockets) pulled, programmed and put back. No chips;
     sixteen chips to handle each time.
  2. **A backplane,** the control store's board pulled out.
  3. **In-system programming:** each flash's data pins switched onto a
     programming bus (sixteen 74CBT3245 bus switches, or 74ABT245s), its
     address from a counter, the machine held in reset while a programmer
     on a header (a USB FIFO module, [23](#23-a-fast-link)) writes them:
     about 18–20 chips, 40 s or so for the whole store.
  4. **The control store in SRAM, loaded at reset** from one large flash,
     as draft 2's CPU loads its own through its I/O processor: the SRAMs
     in place of the flashes, a loader (a counter and the flash) and the
     same sixteen switches; the flash written by the CPU itself, as the
     boot flash is now. About 20 chips; updates from software, and an
     SRAM's 12 ns in place of the flash's 55 for the microinstruction.
  **Open:** which.
- **Power:** roughly 8–10 A at 5 V for the first netlist, from the
  datasheets' supply currents (the 74F counters, ALUs and multiplexers
  and the SRAMs most of it); not redone for the 22V10s, which draw about
  0.1 A each.
- **SMD:** the SRAMs (fourteen in SOJ), as no fast SRAM is made in DIP;
  the CF card's socket; and the clock chip ([20](#20-the-clock)).

### 29. How it was checked

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
- **The address error:** a program (`sw/hw/addrerr.s`) with 22 misaligned
  accesses (word and half loads and stores at every kind of address,
  arithmetic on memory, jumps and calls through memory, `LDM` and `STM`,
  the console) and two accesses that mustn't trap: the same output,
  registers and memory as draft 2's simulator, on the model (`heron mini
  check addrerr`) and at chip level (`heron mini hw test addrerr`).
- **The Lisp** ([studies/lisp](../studies/lisp/README.md), built for
  draft 2), whose type checks are address errors: its short tests
  interpreted (among them the two that take address errors, 23 in all),
  and `errors` compiled, on the model against draft 2's simulator
  (`heron mini check --lisp [--compiled]`), the log of each machine's own
  cycle counts left out. Its benchmarks take no address errors and would
  take hours on the model.
- **Static timing analysis** of every microinstruction in every queue and
  interrupt state, and the I/O hold's deadline (`heron mini hw sta`).

What the chip-level runs found that the analysis hadn't:

- The queue slots' J-K flip-flops are on the master clock, which the
  analysis held constant; a conditional jump that consumed a parcel
  reached them from the flags through 17 gates. `sha256`'s inner loop
  missed their setup by 0.2 ns. The analysis now checks them, and the
  consume is no longer masked by the jump.
- The register file's second read lost to its own output enable: the
  SRAMs turned off at RW, as the B latches closed, before a 5-tick
  cycle's B data was there, so multiplies and divides that read two
  registers went wrong. The analysis's netlist made RW_n with an
  inverter, 6 ns the real one (a 22V10's output, as RW is) hasn't. The
  SRAMs now drive until T2, and the analysis's RW_n is the real one.
- The colour register, clocked by a 22V10's output, broke its hold as the
  shifters shifted on the master clock; it's on the master clock now.

**Contention:** the buses' drivers overlap by up to 6 ns as they hand
over, as on draft 2's CPU, between drivers built for it: most on the B
bus between cycles, the longest between T's byte lanes as an I/O byte
read's lane select settles. Nothing samples the bus then, but a
break-before-make look at the worst of them is an open task.

### 30. Open questions

For Emily:

1. **The reductions:** which of [15](#15-what-could-be-left-out)'s, if
   any; likely none unless a board is over.
2. **The boards:** whether the video and the I/O go on the two core
   boards or a third; stacked or a backplane; how the microcode is
   updated ([28](#28-the-boards)).
3. **The clock chip:** which ([20](#20-the-clock)).
4. **The block instructions:** a copy register for faster copies; counts
   over 256 ([19](#19-blitting-in-microcode)).
5. **The I/O map:** the regions, the free region 4, the expansion ports'
   pinout and number, an FM synthesiser on the board ([7](#7-the-io-space),
   [8](#8-expansion-ports), [24](#24-sound)).
6. **The UARTs' clock:** 1.8432 MHz (as built, the 82C54 shares it) or
   14.7456 MHz (921,600 baud), from the clock chip either way
   ([23](#23-a-fast-link)).
7. **Keyboard and mouse:** which of [22](#22-keyboard-and-mouse)'s.
8. **Microcode tasks:** whether, A or B, and for what ([21](#21-microcode-tasks)).
9. **More RAM** ([25](#25-more-ram)) and **a 74HCT mini**
   ([26](#26-a-74hct-mini)).
10. **The name:** Heron Mini or mini-heron.

The video's questions are [RFC 0042, 14](0042-rfc-mini-video.md#14-open-questions)'s.

### 31. Open tasks

- **The board split and a PCB study:** where the core boards part, the
  connectors, the density; then the boards' delays fed back into the
  timing analysis.
- **The clock chip in the netlist,** once chosen, with its glitch-free
  switch, and the CPU's speed at other master clocks.
- **T's path to 6 ticks:** the 7-tick memory-operand microinstructions
  through T's latches, as the register file's was ([13](#13-how-fast)).
- **Contention:** a break-before-make look at the worst hand-overs
  ([29](#29-how-it-was-checked)).
- **The video's options in the netlist** as RFC 0042's questions are
  decided, and the pixel layout measured on a netlist (its open question
  2).
- **Microcode tasks, A, in the model** if wanted ([21](#21-microcode-tasks)).
- **A 74HCT variant's timing** ([26](#26-a-74hct-mini)).
- **Software:** the multitasking OS, Egret's desktop, Doom
  ([27](#27-software-to-try)).
