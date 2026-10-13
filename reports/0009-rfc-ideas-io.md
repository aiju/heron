---
number: 9
type: rfc
title: I/O, DMA, video and networking ideas
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw]
  commit: e494b0c
---

# RFC 0009: I/O, DMA, video and networking ideas

An ideas RFC: a scratchpad of ideas for one area, each with its own status
([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). It was split out of
`docs/proposals.md` in the restructure, so the items keep the statuses they
had there:

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | Evaluated with numbers ([report 0001](0001-report-draft-0-evaluation.md), [report 0004](0004-report-draft-1-evaluation.md)) |
| **recommended** | Suggested for the next draft or hardware round |
| **decided** | Emily chose it for the next hardware round; not built yet |
| **open** | Discussed, not decided |
| **rejected** | Decided against, with the reason, so it doesn't get re-proposed without new evidence |

Chip counts are rough estimates, scaled from the 98-chip draft 0 design.

## 6. I/O

- **Memory-mapped I/O page** at the top of memory. **adopted.**
  - In draft 1 it's at `0xFFFFFF00`, reachable with a sign-extended 16-bit
    absolute address.
  - A side effect of load/store: no accidental read-modify-write of device
    registers.
- **16 slots of 16 bytes**, one 74HCT154 on address bits 7–4. Each slot
  gets a select line, a shared IRQ and reset (Apple II / RC2014 style).
  **rejected** in favour of slots on the system bus, selected by A31–A28
  ([section 5](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses)). The device list below is
  still the plan for what the system needs.

  | Slot | Device |
  |---|---|
  | 0 | console UART (16C550) |
  | 1 | CF card (8-bit IDE) |
  | 2 | RTC (DS12887) |
  | 3–13 | free |
  | 14 | MMU registers |
  | 15 | system: timer, interrupt controller, front panel, boot-ROM disable |

- **Interrupts:** one level-triggered IRQ plus polling to start. Later,
  PDP-11-style vectored priorities: a 74HCT148 encoder, a priority field in
  the flags compared against the request level, and a 74HCT541 putting the
  vector on the bus (~3–4 chips). That gives nesting. **open**; reserve the
  priority field in the flags now.
- **Read strobes gated with a clock phase**, like writes. **recommended.**
  One gate. Otherwise a decode glitch is a phantom read, e.g. a lost UART
  character.
- **Automatic wait states for I/O** by stretching the clock, decoded early
  from MAR. **recommended.** On the system bus the backplane does this,
  from class straps on each card ([section 5](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses)). Every device gets ~2 µs; I/O is rare, so the
  cost is invisible. A per-device READY line is the more fiddly
  alternative. With variable-length cycles
  ([section 4](0007-rfc-ideas-microarchitecture.md#4-microarchitecture)) this comes for free, and the system
  bus adds WAIT.
- **8-bit peripherals on the low byte lane**, one register per even
  address. **adopted.**
- **74HCT245 transceivers** between the CPU board and a backplane (~20 ns):
  **rejected** for the CPU board. 74HCT is too slow for a one-clock bus path
  and is only for simple slaves. The CPU board uses registered 74ABT
  transceivers (74ABT652), which also give posted writes
  ([section 5](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses)).
- **Front panel:**
  - **Through the microcode** (PDP-8 style): the switch register is a B-bus
    source, and a panel-mode bit on a spare microcode address line selects
    LOAD ADDRESS / DEPOSIT / EXAMINE sequences. Single-stepping instructions
    or micro-cycles falls out. **recommended.**
  - **As a bus master:** shares the bus-release mechanism. **open.**
- **Storage:** a CompactFlash card in 8-bit IDE mode (~300 KB/s by polled
  I/O). **open.** File system: FAT (swap cards with a PC) or a small
  Unix-style one plus a host tool to build images.
- **Console:** a serial terminal first (a VT100 or an emulator), with a
  16C550 UART with FIFO. **recommended.** At 9600 baud, character-by-
  character interrupts cost ~5% of the CPU per busy terminal.
- **Keyboard:** PS/2, a shift register, bit counter and interrupt (~4
  chips). **open.**

## 7. Channels and DMA

Background: a CF sector by software loop is ~12–15 cycles per word, ~3,500
cycles per 512-byte sector. Terminals cost ~5% of the CPU each.

| Option | Cost | CPU cost per word | Status |
|---|---|---:|---|
| Block I/O instruction in microcode | microcode | ~5–6 cycles | **open**, a good first step |
| **Microcoded channel** (like the integrated channels of the small System/360s): a device request runs a microcode sequence between instructions; address, count and command live in spare register-file SRAM | ~5 chips | ~5–7 cycles | **recommended first** for a timesharing system |
| **Cycle-stealing DMA**, optionally following descriptor chains ("channel lite") | ~15–20 chips per channel, plus bus release | ~1 stolen cycle | **recommended** once the OS swaps or multitasks for real: disk first, then terminal output (DH11-style output DMA) |
| DMA in its own memory time slot | memory-timing redesign | 0 | **open**; the recommended tick-level RAM sharing ([section 5](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses)) gets most of the way: DMA into the CPU's RAM at near bus speed, rarely delaying the CPU |
| Intelligent terminal multiplexer: 4–8 lines with buffers, one interrupt per line or buffer | a lot in TTL; one chip with a microcontroller | turns ~1000 interrupts/s per terminal into ~10 | **open**: is a microcontroller in a peripheral OK? 1980s minis did it |
| CDC 6600-style peripheral processor "barrel": one shared datapath, 8 virtual I/O processors with registers in SRAM | ~60–100 chips | – | **open**, a project of its own |
| 82C37 off-the-shelf DMA chip | 1 chip | – | **rejected**: 8-bit, 8085-style timing |

**Software side:**
- "Start channel" is a store to a command register; no new instructions.
- I/O becomes asynchronous: request queues, completion interrupts.
- DMA uses physical addresses, so buffers must be pinned and contiguous.

## 8. Video

**First question: what's the screen for?** A console (~30 chips) or
graphics (address space and drawing speed bite). Minicomputers mostly used
serial terminals; built-in video is home-computer territory. **open.**

**Text-mode VGA card** (~30 chips). **open**; recommended after the serial
terminal.
- 80×30 characters, 8×16 font, 640×480 at 60 Hz (25.175 MHz pixel clock,
  3.15 MHz character clock).
- Character plus attribute per 16-bit word, 16 foreground/background
  colours, 2-bit-per-channel resistor DAC.
- A 128-word row stride, so the address comes straight off the counters.
- Hardware scroll (a start-row register through two 74HCT283) and cursor
  (two 74HCT688 plus blink).
- Redefinable font in SRAM; posted writes so the CPU never waits.
- A 6845 CRTC could replace the timing and addressing (less authentic).

**Where screen memory lives:**

| Option | Notes |
|---|---|
| Video RAM in a window of the CPU's address space | best for text |
| Behind I/O ports with an auto-incrementing address (TMS9918 style) | best for bitmaps; zero address space |
| Dual-port SRAM | expensive |
| Main memory, interleaved | needs the memory redesign |
| Physical pages mapped by the MMU | the clean long-term answer |

**Graphics options:** **open.**
1. A bitmap plus a blitter on the card that fills and copies rectangles:
   a screen clear drops from ~65 ms to ~1 ms.
2. **Display lists** (below).
3. A vector display on an oscilloscope (two DACs, a line walker; GT40 and
   Spacewar style).

Avoid software-generated video (ZX81, Gigatron): it would eat a microcoded
CPU. **rejected.**

**Display-list processor** (ANTIC bands plus copper-style register writes;
the DEC GT40 was the minicomputer precedent). **open**, 40–60 chips (~35
minimal).
- **Instruction set**, nibble-aligned:

  | Word | Instruction |
  |---|---|
  | `1 m nn` | BAND mode `m` for `nn+1` units |
  | `2 m nn` + addr | BAND with a new data pointer |
  | `3 r vv` | PALETTE |
  | `4 r 00` + value | SET control register |
  | `5 0 nn` | BLANK |
  | `6 0 00` | IRQ |
  | `8 0 00` + addr | JMP |
  | `9 0 00` + addr | JVB (jump and wait for vertical blank) |

- **Modes:** 80- and 40-column text; 640-wide bitmaps at 1 and 2 bits per
  pixel; 320-wide at 4 bits per pixel. Bit 3 of the mode doubles lines.
- **Hardware:**
  - 64K×16 of video RAM on the card;
  - four fixed ~80 ns slots per character time (display data, font, CPU,
    display-list processor);
  - an EEPROM-sequenced processor running in horizontal blank (~20 memory
    slots per line);
  - a stride counter for virtual screens;
  - a 25 MHz pixel pipeline in 74AC/F with a 16-entry palette and fine
    scroll;
  - CPU access through a window or a data port; vertical-blank and
    display-list interrupts.
- **What it gives software:** scrolling by one store, split screens,
  tear-free double buffering, raster effects. A `FILL`/`COPY` blitter
  instruction could come later.
- **Vector variant:** `MOVETO`/`LINETO`/`POINT`/`TEXT` with a
  Bresenham-style engine and X/Y DACs.
- **Prototype first:** a Python model of the card in the simulator that
  renders PNGs.

## 9. Networking

Ethernet, for the main CPU and its OS: a fast link to a PC for development
first, TCP/IP later.

- **10 Mbit/s.** **recommended.**
  - 10BASE-T carries 1.25 MB/s. A word-copy loop on the draft 1b hardware
    moves about 1 MB/s at 3 MHz (~12 cycles per 32-bit word), so the CPU can
    roughly keep up. At 100 Mbit/s the link would mostly wait for the CPU.
  - It's a small fraction of a 16-bit system bus, so the card needs nothing
    special from the bus.
  - 100 Mbit/s would only pay for moving bulk data to and from a fast
    coprocessor, and then only with DMA.
- **Full duplex only.** **recommended.** Connected to a switch, the PHY
  negotiates full duplex, so there are no collisions: no carrier sense,
  collision detection or backoff. Those were the hardest part of a 1980s
  Ethernet controller.
- **No hardware address filter.** **recommended.** A switch only forwards
  this machine's frames and broadcasts, so software can drop the rest.

**Controller options:**

| Option | Chips | Notes | Status |
|---|---:|---|---|
| **TTL MAC with a PHY chip** | ~40–60 | Design below | **recommended** |
| WIZnet W5100 | ~2 | 8-bit parallel bus, 16 KB buffers; hardware TCP/IP or a raw-frame mode; still made | **open**, as a quick bring-up path |
| Realtek RTL8019AS (NE2000-compatible) | ~3 | 5 V, 8/16-bit ISA-style bus, 16 KB buffer, 10 Mbit/s only; obsolete but easy to find and documented everywhere | **open** |
| 16-bit 10/100 controllers (Davicom DM9000-class, Microchip LAN9221) | ~4 | 3.3 V; 5 V tolerance needs checking, may need level shifters | **open** |

**The TTL MAC:**

- **The PHY chip** does the analog side: line drivers and receivers, and
  Manchester or 4B/5B coding. The isolation transformer comes built into
  the RJ45 jack. 1980s boards used a serial-interface chip for the same job.
  The PHY's MII interface at 10 Mbit/s is 4 bits at 2.5 MHz each way,
  clocked by the PHY: slow enough for 74HCT.
- **Levels.** The PHY runs at 3.3 V. Its outputs drive 74HCT inputs directly
  (TTL thresholds); signals into it go through a 74LVC buffer.
- **Receive:** find the preamble and the start-of-frame nibble, assemble
  nibbles into 16-bit words, write them into the packet buffer, check the
  CRC-32 four bits at a time, and post each frame's length and status to a
  ring of receive descriptors.
- **Transmit:** read a frame from the buffer, send the preamble and
  start-of-frame, then the data, then the CRC.
- **Packet buffer:** a 32K × 16 SRAM on the card, holding a ring for
  received frames and space for frames to send. The CPU reaches it through
  a window in the card's address space.
- **CRC-32 by nibble:** a 32-bit register and an XOR network (or a 16-entry
  table), ~8–12 chips.
- **Interrupts** for frame received and frame sent.
- **Later: DMA** straight into main memory as a bus master, following
  descriptor rings like AMD's LANCE did (see [section 7](#7-channels-and-dma)).
  It would be the first real test of bus mastering. **open.**
- **Simulate first:** the MAC as a netlist in the chip-level simulator, with
  a PHY fixture that plays recorded frames (pcap files) in and captures what
  it sends.

**Software:**

- **Raw frames to a PC-side tool first:** loading programs in a fraction of
  a second instead of over serial, a remote console, network boot.
  **recommended.** That's a reason to build Ethernet early: it speeds up
  all the development after it.
- **CPU cost:** at ~1 MB/s, copying a full-size frame takes ~1.5 ms. A block
  I/O instruction (~5–6 cycles per word, [section 7](#7-channels-and-dma))
  roughly halves that; DMA removes it.
- **TCP/IP** (a uIP- or lwIP-sized stack) once there's a C compiler and an
  OS. **open.** Telnet into a timesharing system would give the OS ladder
  in [section 1](0005-rfc-ideas-direction.md#1-direction-and-ambition) a concrete goal.
