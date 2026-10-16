---
number: 9
type: rfc
title: I/O, DMA, video and networking ideas
status: open
date: 2026-10-14
context:
  studies: [v1_isa, v1b_hw, graphics, kernel]
  commit: 2f81658
---

# RFC 0009: I/O, DMA, video and networking ideas

An ideas RFC: a scratchpad of ideas for the machine's devices, each with
its own status ([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)).
The evidence is in the reports each item links to.

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1, or the draft 1b hardware has it |
| **measured** | It has numbers behind it |
| **recommended** | Suggested for draft 2 or the next hardware |
| **decided** | Emily chose it; not built yet |
| **open** | Discussed, not decided |
| **not recommended** | The evidence is against it; Emily hasn't decided |
| **rejected** | Decided against, with the reason, so it isn't proposed again without new evidence |

Chip counts are rough estimates. Every device sits on the system bus
([RFC 0014](0014-rfc-system-bus.md)): simple peripherals as simple cards,
the rest as fast cards.

## 1. I/O

- **What the system needs:** a console UART (16C550), a CompactFlash card
  (8-bit IDE), a real-time clock (DS12887), a timer, an interrupt
  controller, the front panel, a way to switch the boot ROM out, Ethernet
  ([section 4](#4-networking)), video ([section 3](#3-video)), a keyboard
  and a mouse. The MMU's registers are
  special registers in the kernel study's v1bs, not devices
  ([report 0020's appendix](0020-report-operating-system.md#appendix-v1bs-draft-1b-with-system-extensions)).
- **Memory-mapped I/O.** **adopted.**
  - In draft 1 the I/O page is at `0xFFFFFF00`, reachable with a
    sign-extended 16-bit absolute address. The draft 1b hardware decodes
    it from MAR bit 31 alone, so everything from `0x80000000` up is I/O.
  - On the system bus, each card's registers are in its slot's region
    ([RFC 0014, 5.1](0014-rfc-system-bus.md#51-slots-and-card-classes));
    how the CPU board maps its own addresses onto the bus is its business.
  - Neither encoding has a read-modify-write instruction, so nothing
    reads and writes a device register by accident. A memory increment
    ([RFC 0006](0006-rfc-ideas-isa.md#32-1bs-gaps)) would be the first.
  - The kernel study maps the I/O page into a user process, for a
    user-level driver ([report 0020](0020-report-operating-system.md#a-message-passing-nucleus-with-servers)).
- **16 slots of 16 bytes** on the CPU board, one 74HCT154 on address bits
  7–4, each slot with a select line, a shared IRQ and reset (Apple II /
  RC2014 style). **rejected** in favour of slots on the system bus.
- **8-bit peripherals on the low byte lane.** **adopted.** Draft 1's I/O
  registers are 4 bytes apart and byte accesses use the low byte; on the
  bus a simple card puts 8-bit registers on D0–D7, 4 bytes apart
  ([RFC 0014, section 6](0014-rfc-system-bus.md#6-simple-cards)).
- **Interrupts:** one level-triggered IRQ plus polling to start. Then
  PDP-11-style vectored priorities: a 74HCT148 encoder, a priority field in
  the flags compared against the request level, and a 74HCT541 putting the
  vector on the bus (~3–4 chips), which gives nesting. **recommended**
  ([report 0020](0020-report-operating-system.md#interrupts-and-devices));
  reserve the priority field in the flags now. The bus has eight interrupt
  lines, and each CPU listens to its own subset through a priority encoder
  ([RFC 0014, 8.3](0014-rfc-system-bus.md#83-interrupts-and-synchronisation)).
  With register banks, each priority level could have a bank of its own,
  so a handler saves nothing ([RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)).
- **A timer for a tickless kernel:** a free-running counter in
  microseconds (32 bits last 71 minutes) and a compare register that
  interrupts once, instead of draft 1's periodic timer: timeouts without
  polling. ~4–6 chips. **recommended**
  ([report 0020](0020-report-operating-system.md#the-rest)). The timer and
  the cycle counter count real time ([docs/clocking.md](../docs/clocking.md)).
- **Clean strobes and wait states** for devices: on the bus, SEL is a
  registered strobe that never glitches, and the backplane times each card
  from its class straps ([RFC 0014](0014-rfc-system-bus.md#133-sel-as-the-strobe)).
  That replaced gating read strobes with a clock phase and stretching the
  clock from a decode of MAR. 74HCT parts are only for simple cards.
- **Front panel:**
  - **Through the microcode** (PDP-8 style): the switch register is a B-bus
    source, and a panel-mode bit on a spare microcode address line selects
    LOAD ADDRESS / DEPOSIT / EXAMINE sequences. Single-stepping instructions
    or micro-cycles falls out. **recommended.**
  - **As a bus master,** or as a simple card. **open.**
- **Reset levels,** nested, with the I/O processor of
  [RFC 0027](0027-rfc-io-coprocessor.md) as the system controller. At
  least a cold and a warm reset (Emily, 2026-10-15).
  - **Cold:** everything, the I/O processor included, as at power-up, but
    the power stays on and so do the RAMs' contents. From power-up, the
    reset button, or a watchdog on the I/O processor. **recommended.**
  - **System (bus) reset:** every card but the I/O processor: the
    peripherals, the CPU cards (held again, as at power-up) and the
    backplane's arbiter and monitor. The I/O processor, its console and
    the control stores' contents carry on. From the I/O processor, at the
    operating system's request or from its monitor. It's the PDP-11's
    `RESET`, which reset every device on the Unibus but not the CPU. It
    gives a reboot with no device left as the old system had it: a video
    card mid-blit, a network card receiving into a ring that's gone, an
    interrupt still asserted. **open**; recommended here.
  - **Warm:** one CPU runs its reset routine, through its card's control
    register (RFC 0027, 4.1); RAM, the control store and every device
    stay. From the I/O processor: its monitor, the CPU's own request, its
    watchdog on the CPU. **recommended.**
  - **Device:** one device, by a reset bit of its own where it has
    registers (the CF card's SRST, a network or video card), or by an
    output port bit on the I/O processor's card wired to a device's reset
    pin. **recommended** where it's free.
- **What the levels need:**
  - **A second reset line.** If the I/O processor took the bused RESET, a
    system reset would reset the card that asserts it. So COLD, an
    open-collector line driven by the backplane's power-on reset, the
    button and the I/O processor's watchdog, goes to the I/O processor;
    the backplane asserts RESET with it, and the I/O processor asserts
    RESET alone for a system reset. Every other card listens to RESET
    only. COLD could be on P2, which the I/O processor's card has for its
    32-bit path, rather than take a reserved P1 pin. **recommended.**
  - **RESET's drivers:** [RFC 0014, 8.1](0014-rfc-system-bus.md#81-reset)
    has the main CPU drive it. With an I/O processor, the CPU asks it
    instead, so a reset never cuts across one of its transfers. Without
    one, the CPU drives it as now. **open.**
  - **Never in the middle of a transfer:** a master reset mid-transfer
    lets go of the address while the backplane still times the data
    phase, and the card can be written with garbage. A CPU card takes a
    warm reset when its current transfer ends (a flip-flop); the I/O
    processor asserts RESET only between its transfers. **recommended.**
  - **The end of reset synchronised to BCLK** on every card, one
    flip-flop: RESET's edges are slow on purpose, so cards could leave it
    in different clocks. **recommended.**
  - **A watchdog on the I/O processor itself,** a retriggerable timer
    its firmware must keep restarting, pulling COLD: the I/O processor
    watches the CPU, and nothing else watches it. ~1 chip.
    **recommended.**
  - **A cold reset keeps RAM,** so a crash log or the I/O processor's
    flight recorder survives for the next boot to read. Its firmware can
    tell a cold reset from power-up by a signature it leaves in its SRAM,
    and keeps destructive memory tests for power-up.
- **Not resets, but beside them** in a CPU card's control register:
  halt (RUN off, state kept), single steps, and NMI, into a monitor
  without losing state (RFC 0027, 4.1).
- **A reset line to each slot** from the backplane, for a simple card
  that has no register to reset it by: a pin per slot, and a register on
  the backplane, which has no address of its own
  ([RFC 0014, open question 8](0014-rfc-system-bus.md#14-open-questions)).
  **not recommended** unless a card turns out to need it.
- **A power-fail warning** (the Unibus's AC LO, which gave the CPU
  milliseconds to save its state): **not recommended**. With static RAM
  and no battery, there's nowhere to save it.
- **Storage:** a CompactFlash card in 8-bit IDE mode (~300 KB/s by polled
  I/O). **open.**
  - On the bus, a CF card in PIO mode 0 wants 290 ns strobes: N = 5 for
    every simple card, or a slower simple class
    ([RFC 0014, 13.7](0014-rfc-system-bus.md#137-timing-budgets)).
  - File system: FAT (swap cards with a PC), or a small Unix-style one plus
    a host tool to build images. Or none at first: the PC's files over the
    network ([section 4](#4-networking)).
- **Console:** serial terminals and video, at least in the design; the
  first build might not have video. **decided** (Emily, 2026-10-15).
- **Serial ports:** a 16C550 UART with FIFO per line, and a VT100 or an
  emulator on the other end. **recommended.** Probably not more than 4
  ports (Emily, 2026-10-15). That's well within the machine:
  - without the FIFO, an interrupt per character at 9,600 baud, handed
    to a user-level driver, would take 17% of the machine per busy line
    ([report 0020](0020-report-operating-system.md#interrupts-and-devices));
  - with the FIFO interrupting every 8 characters, about 2% for the
    interrupts, and perhaps as much again to handle the characters (an
    estimate): four lines running flat out take under a quarter of
    the machine, and people typing much less.
- **Keyboard and mouse:** PS/2, a shift register, bit counter and
  interrupt each (~4 chips). **open.** The window manager of
  [report 0019](0019-report-graphics.md) would want the mouse.

## 2. Channels and DMA

Background: a CF sector by software loop is ~12–15 cycles per word,
~3,500 cycles per 512-byte sector. An interrupt handed to a user-level
driver costs 500–640 cycles
([report 0020](0020-report-operating-system.md#interrupts-and-devices)),
so devices should interrupt per buffer, not per byte.

| Option | Cost | CPU cost per word | Status |
|---|---|---:|---|
| Block I/O instruction in microcode ([RFC 0006](0006-rfc-ideas-isa.md#5-more-instruction-ideas)) | microcode | ~5–6 cycles | **open**, a good first step |
| **Microcoded channel** (like the integrated channels of the small System/360s): a device request runs a microcode sequence between instructions; address, count and command live in spare register-file SRAM | ~5 chips | ~5–7 cycles | **recommended first** for a timesharing system |
| **Cycle-stealing DMA**, optionally following descriptor chains ("channel lite") | ~15–20 chips per channel, plus bus mastering | ~1 stolen cycle | **recommended** once the OS swaps or multitasks for real: disk first, then terminal output (DH11-style output DMA) |
| A DMA card: 8 channels, microcoded, on the system bus | ~34 chips | – | **open**; about 3–5 MB/s from the CF card ([RFC 0014, section 12](0014-rfc-system-bus.md#12-example-cards)) |
| DMA in its own memory time slot | memory-timing redesign | 0 | **open**; the recommended tick-level RAM sharing ([RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory)) gets most of the way: DMA into the CPU's RAM at near bus speed, rarely delaying the CPU |
| Intelligent terminal multiplexer: 4–8 lines with buffers, one interrupt per line or buffer | a lot in TTL | turns ~1000 interrupts/s per terminal into ~10 | **open**, but hardly needed for up to 4 lines with FIFO UARTs. With a microcontroller, as 1980s minis did: **rejected** (Emily, 2026-10-15: no microcontrollers in peripherals) |
| CDC 6600-style peripheral processor "barrel": one shared datapath, 8 virtual I/O processors with registers in SRAM | ~60–100 chips | – | **open**, a project of its own. Register banks with their own PC, switched by interrupts, would be the same idea inside the CPU ([report 0020](0020-report-operating-system.md#further-ideas)) |
| **An I/O processor** on a card of its own: a microcoded 16-bit bus master that boots the CPU (a writable control store included), runs the console, disk and terminal lines in Forth, and is every device's DMA engine at 5–6 MB/s | ~46 for its core, ~95 for its card with RAM the CPUs share | a request, ~200–700 cycles | **decided** (Emily, 2026-10-16): in every Heron, and the DMA engine; the design is **open** in [RFC 0027](0027-rfc-io-coprocessor.md) |
| 82C37 off-the-shelf DMA chip | 1 chip | – | **rejected**: 8-bit, 8085-style timing |

**Software side:**
- "Start channel" is a store to a command register; no new instructions.
- I/O becomes asynchronous: request queues, completion interrupts. A DMA
  engine that takes descriptors from a ring and writes completions to
  another can have its rings mapped straight into a user-level driver
  ([report 0020](0020-report-operating-system.md#asynchrony-rings-against-traps)).
- DMA uses physical addresses, so buffers must be pinned and contiguous,
  and a bus master can reach all of the CPU's RAM unless the slave port
  confines it ([RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory)).

## 3. Video

[RFC 0016](0016-rfc-video.md) is the proposal: a bitmap card with 2 MB of
VRAM, a blitter and a copper, in stages, with sprites and tiles open, and
its own questions for Emily. [Report 0019](0019-report-graphics.md)
measured what the CPU does without help: fills at 1.7–2.4 MB/s and copies
at 0.9–1.2 MB/s with the screen in main memory, as RFC 0016 estimated.

What RFC 0016 adds or set aside, kept here:

- **The first pixel in a byte's low bits,** so a little-endian word holds
  its pixels in order and can be shifted as one; with the other order,
  every copy and glyph would need a byte swap. **recommended**
  ([report 0019](0019-report-graphics.md#where-the-cycles-go)).
- **Software-generated video** (ZX81, Gigatron): it would eat a microcoded
  CPU. **rejected**, here and in RFC 0016.
- **A text-mode VGA card first** (~30 chips). **open**; RFC 0016 prefers a
  bitmap card, which serves the console too, with a text mode only as part
  of a tile engine ([RFC 0016, 9.4](0016-rfc-video.md#94-tiles-and-text-mode-with-them)).
  - 80×30 characters, 8×16 font, 640×480 at 60 Hz, a character plus
    attribute per 16-bit word, 16 foreground/background colours.
  - A 128-word row stride, so the address comes straight off the counters.
  - Hardware scroll (a start-row register through two 74HCT283) and cursor
    (two 74HCT688 plus blink); a redefinable font in SRAM; posted writes.
- **A display-list processor** (ANTIC bands plus copper-style register
  writes; the DEC GT40 was the minicomputer precedent), 40–60 chips
  (~35 minimal). **open**; RFC 0016's copper
  ([section 8](0016-rfc-video.md#8-display-lists-a-copper)) is its cheap
  core, and the rest can come later if a use turns up. Its instruction
  set, nibble-aligned:

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

  It ran in horizontal blank from an EEPROM sequencer, with four fixed
  ~80 ns VRAM slots per character time (display data, font, CPU, display
  list) where RFC 0016 has slot owners per mode.
- **A vector display** on an oscilloscope or XY monitor (GT40 and
  Spacewar style): `MOVETO`/`LINETO`/`POINT`/`TEXT` with a Bresenham-style
  engine and X/Y DACs. **open**, as a card of its own
  ([RFC 0016, section 10](0016-rfc-video.md#10-small-extras)).

## 4. Networking

Ethernet, for the main CPU and its OS: a fast link to a PC for development
first, TCP/IP later. **decided**: Ethernet, preferably with a MAC built
from TTL ([docs/README.md](../docs/README.md)).

- **10 Mbit/s.** **recommended.**
  - 10BASE-T carries 1.25 MB/s. An unrolled word-copy loop moves about
    1.2 MB/s at 3 MHz in the draft 1b hardware's configuration (9.5 cycles
    per 32-bit word in the timing model,
    [report 0020](0020-report-operating-system.md#zeroing-and-copying)),
    so the CPU can roughly keep up. At 100 Mbit/s the link would mostly
    wait for the CPU.
  - It's a small fraction of the system bus, so the card needs nothing
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
| WIZnet W5100 | ~2 | 8-bit parallel bus, 16 KB buffers; hardware TCP/IP or a raw-frame mode; still made | **open**, as a quick bring-up path. Whether a single-chip controller is acceptable at all is to be decided (Emily, 2026-10-15) |
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
  descriptor rings like AMD's LANCE did ([section 2](#2-channels-and-dma)).
  It would be the first real test of bus mastering. **open.**
- **Simulate first:** the MAC as a netlist in the chip-level simulator, with
  a PHY fixture that plays recorded frames (pcap files) in and captures what
  it sends.

**Software:**

- **Raw frames to a PC-side tool first:** loading programs in a fraction of
  a second instead of over serial, a remote console, network boot.
  **recommended.** That's a reason to build Ethernet early: it speeds up
  all the development after it.
- **The PC as a file server:** mount its files over 9P, so the machine
  works with real files before it has a file system of its own; a 9P
  server on the PC is a few hundred lines of Python. **open**, part of
  the operating system report 0020 proposes
  ([RFC 0010](0010-rfc-ideas-os.md#1-the-operating-system)).
- **CPU cost:** copying a full-size frame takes about 1.2 ms. A block
  I/O instruction (~5–6 cycles per word, [section 2](#2-channels-and-dma))
  roughly halves that; DMA removes it. An interrupt per frame to a
  user-level driver costs 500–640 cycles more.
- **TCP/IP** (a uIP- or lwIP-sized stack) once there's a C compiler and an
  OS. **open.** Telnet into a timesharing system would give the operating
  system ([RFC 0010](0010-rfc-ideas-os.md#1-the-operating-system)) a
  concrete goal.
