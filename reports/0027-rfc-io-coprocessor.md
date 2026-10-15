---
number: 27
type: rfc
title: An I/O coprocessor
status: open
date: 2026-10-15
context:
  studies: [v1b_system, v1b_tradeoffs, v1b_hw, kernel]
  commit: d81b207
depends-on: [9, 14, 24, 25]
---

# RFC 0027: An I/O coprocessor

A proposal for an I/O processor, the IOP: a small microcoded machine on
a card of its own, a master on the system bus
([RFC 0014](0014-rfc-system-bus.md)). It boots the main CPU, a writable
control store included, and runs the console, the disk and the terminal
lines. This RFC also asks whether it should be the system's DMA engine
(yes, for four more chips: [section 5](#5-should-it-be-the-dma-engine)),
and lists other work it could take on. It starts from the channel and DMA
ideas of [RFC 0009, section 2](0009-rfc-ideas-io.md#2-channels-and-dma).

The goals, in order:

1. as few chips as possible;
2. boot the main CPU, including filling a writable control store;
3. compute speed doesn't matter; copy speed might, if it is also the DMA
   engine, which is to be evaluated rather than assumed;
4. other jobs it could do.

Statuses: **recommended**, **open** (a real choice either way),
**optional** (an add-on that can come later without changing the rest)
and **not recommended**. Nothing here is decided.

Chip counts are estimates from a block diagram, not from a netlist: give
or take a quarter, as in [RFC 0016](0016-rfc-video.md). They assume 16-bit
"Widebus" registers and transceivers (74ABT16823, 16245, 16652), which
[RFC 0024](0024-rfc-faster-smaller.md#8-smaller-packages-and-plds)
recommends if their TSSOP packages are allowed; with octal parts the core
is about 13 chips bigger. No PLDs. Delays are worst-case datasheet figures
from the repository's timing data (`infra/hw/timing.json`), at the bus's
working period of 60 ns. Rates on the bus use the bus as
[report 0025](0025-report-draft-1b-system.md) built it.

## Contents

1. [Summary](#1-summary)
2. [What it's for](#2-what-its-for)
3. [The design](#3-the-design)
4. [Booting the CPU](#4-booting-the-cpu)
5. [Should it be the DMA engine?](#5-should-it-be-the-dma-engine)
6. [Other uses](#6-other-uses)
7. [What else goes on the card](#7-what-else-goes-on-the-card)
8. [What it saves and what it costs](#8-what-it-saves-and-what-it-costs)
9. [Alternatives](#9-alternatives)
10. [The interface to the CPU](#10-the-interface-to-the-cpu)
11. [Stages, and simulate first](#11-stages-and-simulate-first)
12. [Against RFC 0009](#12-against-rfc-0009)
13. [Open questions](#13-open-questions)

## 1. Summary

- **What it is:** a horizontally microcoded 16-bit machine, synchronous
  to the bus clock. A 48-bit microinstruction from six flash ROMs runs
  every two bus clocks (120 ns). It has a 74F181 ALU and one 64K × 16 SRAM
  that is both its register file, in banks of 64 registers, and its data
  memory. In one microinstruction it can step a register through the ALU
  and write it back, make one bus transfer, move data between the bus and
  a device on the card, count a loop and branch. Its microcode is its
  only instruction set: no decoder, no macroinstructions.
- **Chips:** about 47 for the core (60 with octal parts), and about 60
  for the whole card: the core, 1 MB of flash for the CPU's images, a quad
  UART, a CF socket, a timer, a clock chip and two PS/2 ports. With 16-bit
  EPROMs for its microcode, 3 fewer.
- **Booting the CPU:** the CPU card holds its CPU while the IOP writes
  the control store and a boot program through the card's slave port,
  then lets it run. The CPU card needs a control register, the slave port
  RFC 0014 already recommends for DMA, and for an SRAM control store a
  write port into it: about 14 chips, against about 24 for the loader
  and its flash that RFC 0024 estimated on the CPU card. The part of the
  1b's control store in use loads in about 35 ms, all 1.25 MB of it in
  0.17 s.
- **The DMA engine: recommended.** Booting already needs a bus master, a
  sequencer and address arithmetic. Four more chips make copies keep pace
  with the bus: a second segment register, a loop counter, a bridge that
  gives transfers a bus of their own, and a register that lets AH0 and
  AH1 share the address lines. Copies run at 5–6 MB/s at 16 bits, about
  12 MB/s between 32-bit cards (one chip more), and fills at 10–14 MB/s.
  The CPU copies at 1–2 MB/s and is busy while it does. One bus master
  then serves every device, and its firmware can check every request
  against windows the supervisor sets. Against it: one engine does
  everything in turn; a request costs the CPU a few hundred cycles, so
  copies under about 100–300 bytes stay with the CPU; and it is no blitter
  for VRAM-to-VRAM copies.
- **Other uses** ([section 6](#6-other-uses)), the best of them:
  - a console monitor that works with the CPU halted: examine, deposit,
    load, step, and new CPU microcode from the PC in a few seconds;
  - four terminal lines with their line discipline, so the CPU sees a
    line and not a character;
  - the CF card at 3–6 MB/s instead of about 0.3;
  - pages zeroed in the background, so a demand-zero page fault costs
    about 130 cycles instead of 4,753;
  - PS/2, the clock chip and the front panel by firmware, which saves
    their chips;
  - text on the screen before the CPU runs.
- **What it saves:** in a system that would have had an SRAM control
  store, DMA and these devices anyway, the IOP about pays for itself:
  about 75 chips against about 95. In a minimal system, with the control
  store in flash and no DMA, it costs about 30 more
  ([section 8](#8-what-it-saves-and-what-it-costs)).

The goals, answered:

| Goal | Answer |
|---|---|
| 1. Few chips | About 47 for the core. The bus interface (10) and the control store with its register (9) are 40% of it; the rest is a datapath with one register-file port and one ALU. A loader with no ALU would be about 25 but could only boot ([section 9](#9-alternatives)) |
| 2. Boot the CPU, with a writable control store | Yes: images from its own flash, the CF card or the serial line, written into the control store and RAM through the CPU card's slot ([section 4](#4-booting-the-cpu)) |
| 3. Copies, if it's the DMA engine | 5–6 MB/s at 16 bits, the bus's own pace, for four chips; 2.5–4 MB/s without them. **Recommended** as the DMA engine ([section 5](#5-should-it-be-the-dma-engine)) |
| 4. Other jobs | About 25, from the console to page zeroing ([section 6](#6-other-uses)) |

**Recommended:** build the IOP as section 3 describes, with its DMA
parts. Put the console UART, the CF card and the timer on its card.
Give the CPU card a control register, a slave port and, if the control
store is SRAM, a write port into it. Simulate it before any netlist
([section 11](#11-stages-and-simulate-first)).

## 2. What it's for

### 2.1 The jobs

- **Booting.** An SRAM control store is empty at power-up
  ([RFC 0024, section 5](0024-rfc-faster-smaller.md#5-faster-parts)), so
  the CPU can't start itself: something must fill up to 1.25 MB of
  microcode and decode table, load a program and start it. A flash
  control store needs only the program, and the boot ROM that RFC 0010
  overlays on low memory at reset
  ([RFC 0010, section 2](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system))
  could go.
- **I/O.** Every access the CPU makes to a simple card holds its
  microcycle for 880–960 ns
  ([report 0025, section 5](0025-report-draft-1b-system.md#5-what-a-bus-transfer-costs)),
  and every interrupt handed to a user-level driver costs 500–640 cycles
  ([report 0020](0020-report-operating-system.md#interrupts-and-devices)).
  Characters and polled disk sectors are where that adds up.
- **Copies,** if it is the DMA engine: disk sectors, network frames,
  pages for the operating system (zeroing is 4,619 of a demand-zero
  fault's 4,753 cycles,
  [report 0020](0020-report-operating-system.md#zeroing-and-copying)),
  graphics.
- **Everything else:** [section 6](#6-other-uses).

### 2.2 Precedents

| Machine | Year | The other processor | What it did |
|---|---|---|---|
| CDC 6600 | 1964 | Ten peripheral processors sharing one datapath (the barrel) | All I/O, and the operating system's monitor; the CPU had no I/O instructions |
| IBM System/360 | 1964 | Channels | Ran channel programs, lists of commands, from main memory |
| Xerox Alto | 1973 | None: device tasks in the CPU's own microcode | The opposite way: one machine switching between microcode tasks |
| DEC KL10 | 1975 | A PDP-11 front end | Loaded the microcode, booted the machine, ran the console and slow devices |
| VAX-11/780 | 1977 | An LSI-11 console processor with a floppy drive | Loaded microcode into the control store, booted, gave the console |
| Intel 8089 | 1979 | An I/O processor chip beside the 8086 | Two DMA channels running channel programs from memory |
| Symbolics 3600 | 1983 | A 68000 front-end processor | Booted the machine, loaded its microcode, slow I/O and diagnostics |

The IOP is the KL10's and the VAX's front end in its boot and console
jobs, and the 8089 in its DMA job. It is built from TTL, since there are
to be no microcontrollers in peripherals ([docs](../docs/README.md)); the
front ends above were off-the-shelf computers.

## 3. The design

### 3.1 Overview

```
                            system bus, P1
     A1–A15        A16–A31            D0–D15            START WRITE BE REQ
  ======|=============|==================|=========================|=========
        |             |                  |                         |
    AL (16823)   AHOUT (16823)     16652: BA takes reads,     control register,
        |             |            AB drives writes           bus state
        |     AH0 or AH1 (16823 x2)      |
        |             |                  +------ T bus -----+------------+
        |             |                  |                  |            |
        |             |            bridge (16245)     image flash     devices:
        |             |                  |            2 x 512K x 8    UARTs, CF,
        |             |                  |                            timer, ports
  ------+-------------+------------------+----- R bus --+----------------+----
     |              |              |                |                  |
  SRAM 64K x 16  K <-> R        ALU: A from R,    F (16823): the     loaded from R:
  registers      (16245)        B from AC         result, onto R     AC, X, BANK,
  and data          |           4 x 181 + 182     in the 2nd half    LC, control
     |              |                 |                ^
  address:       K field              +----------------+
  BANK:REG or X     |
                    +--> uPC (4 x 161) --> microcode, 6 x flash --> uIR (3 x 16823)
```

Three buses on the card:

- **R** (16 bits), the register bus: the SRAM, the microinstruction's
  constant, the ALU's A input, and the result register F, which drives R
  in the second half of every microcycle. Everything that loads, loads
  from R.
- **T** (16 bits), the transfer bus: the A side of the bus data
  transceiver, the devices on the card and the flash for the CPU's
  images. A bridge joins it to R. Copies move across T while R does the
  address arithmetic.
- **K** (16 bits): the microinstruction's constant field, onto R through
  a transceiver and into the microprogram counter as a branch target. A
  jump to a computed address turns the transceiver round.

### 3.2 The microcycle

Two bus clocks, from edge E0 through E1 to E2:

| | First half, E0–E1 | Second half, E1–E2 |
|---|---|---|
| R bus | The source: a register, memory at X, the constant or T | F |
| SRAM | Read | F written back, if asked, from E1 until BCLK falls |
| ALU | A from R, B from AC; F and the carry latched at E1 | – |
| System bus | The previous transfer's data clock | This microinstruction's address clock: AL loaded from R at E1, AHOUT from AH0 or AH1 |
| T bus | Read data, or a device, onto R if asked | A move into AB (write data), taken at E2 |
| At E2 | | The next microinstruction; AC, X, BANK, AH0, AH1, LC or the control register loaded from R if asked |

- **One register a microcycle,** read and written back: `src ← src + AC`
  is one microinstruction, and writing the result somewhere else is a
  second. The SRAM's address can't change at E1, where the write strobe
  starts, and the next microinstruction changes it at E2, so the strobe
  ends when BCLK falls. That needs BCLK high for at least about 15 ns of
  each period and low for about 10, which RFC 0014 doesn't promise yet
  ([open question 8](#13-open-questions)).
- **Transfers overlap microinstructions.** The address clock is the
  second half; the data clock is the first half of the next
  microinstruction. So back-to-back transfers take their 2 clocks each.
  A transfer that runs longer (WAIT, a simple card's N clocks) or a bus
  the IOP doesn't hold yet stalls the next transfer's microinstruction at
  E1 until it can go.
- **Read data** is in BA when its transfer ends, during the next
  microinstruction. That one can move it into AB in its second half, for
  a copy; the one after can put it on R.
- **Devices on the card stretch the microcycle** by clocks set with
  jumpers for each device select: an address-setup clock where a device
  needs one (the CF card in PIO mode 0) and a strobe of 1–8 clocks. A
  bit in the control register switches the CF card to a second, faster
  set once the firmware has set its PIO mode.
- **One branch delay slot.** The microprogram counter addresses the flash
  a microcycle ahead, so the microinstruction after a branch always runs.
  Every loop below puts its second microinstruction there.

### 3.3 The microinstruction

48 bits, six flash ROMs wide:

| Field | Bits | Meaning |
|---|---:|---|
| K | 16 | A constant onto R, or a branch target |
| REG | 6 | A register in the current bank (SRAM address bits 0–5, BANK gives 6–13), or a device and its register (bits 5–3, 2–0) |
| RS | 2 | R in the first half: the register, memory at X, K, or T |
| ALU | 6 | The 74181's S0–S3 and M, and the carry in |
| WB | 1 | Write F back in the second half: to the register, or to memory at X if RS chose memory |
| LD | 3 | Load from R at the end: none, AC, X, BANK, AH0, AH1, LC, the control register |
| BUS | 2 | None, read, write; the fourth value is kept for a locked read |
| SEG | 1 | AH0 or AH1 onto A16–A31 |
| SZ | 2 | Byte lanes: byte 0, byte 1, halfword, word |
| T | 3 | None; AB ← BA (a copy); AB ← F; AB ← a device; a device ← BA; a device ← F; T ← a device (for RS = T); AB ← the image flash at X |
| SEQ | 2 | Next, branch if the condition holds, branch if it doesn't, jump to F |
| COND | 3 | Always, carry, F's bit 15, LC not done (and count), attention, doorbell, bus error, spare |
| spare | 1 | |

- **The all-zero microinstruction does nothing,** so reset clears the
  uIR and the counter and the IOP starts at address 0.
- **Conditions:** no zero flag. A register is tested for zero by
  decrementing it and branching on the borrow, and for equality with a
  XOR first. Bit 15 is on R in the second half, where the branch samples
  it. *Attention* is the OR of every device's interrupt, the PS/2 edge
  flags and the doorbell; a computed jump on the input port then
  dispatches.
- **AC** holds the step for pointers: 2 for halfwords, 4 for words, 0 for
  a device's register.

### 3.4 Registers and memory

One 64K × 16 SRAM (IS61C6416AL-12):

- **Registers** are at {BANK, REG}: 64 to a bank. Each job gets a bank of
  its own (the loader, each terminal line, the disk, the ring service),
  so changing job is one load of BANK.
- **Data memory** is everything else, at X: line buffers, a sector
  buffer, a font, tables. X loads from R, usually in the microinstruction
  that steps the register that shadows it (`xr, X ← xr + AC`).

### 3.5 The bus interface

**As a master** (RFC 0014 [section 7](0014-rfc-system-bus.md#7-bus-mastering),
with report 0025's registered REQ, so a request on an idle bus takes 4
clocks):

- **Addresses:** AL drives A1–A15 from its bits 1–15 (SZ picks the byte
  lanes, so bit 0 is ignored), and AHOUT drives A16–A31. AH0 and AH1 are two segments, so a copy
  between slots changes its upper address on every transfer at no cost.
  AHOUT exists so that each bused line sees one output, as
  [the loading rule](0014-rfc-system-bus.md#9-electrical-rules) asks,
  rather than AH0 and AH1 both.
- **Data:** one 74ABT16652 registered transceiver. BA takes read data at
  the end of every data clock with DPH and without WAIT; AB drives write
  data. A copy moves BA to AB across T without using R.
- **Control:** START, WRITE, BE and LOCK come from a 74ABT574 loaded at
  E1. REQ follows a session bit in the control register, which the
  firmware clears after every 16 transfers, RFC 0014's courtesy rule; it
  checks for other work then.
- **32 bits (optional, +1 chip):** a second 16652 on D16–D31, on P2. Word
  transfers go only to cards the firmware knows are 32-bit; a missing W32
  is an error. Copies between 32-bit cards (the memory card, video)
  double in speed. The CPU card's slave port is 16 bits
  ([RFC 0014, section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus)),
  so copies to and from its RAM don't gain.
- **LOCK** isn't needed: the rings of [section 10](#10-the-interface-to-the-cpu)
  have one writer per index.

**As a slave,** the card straps itself as a simple card with nothing to
read or write:

- **The doorbell:** any write to the IOP's slot sets a flip-flop,
  through the Schmitt NAND every simple card has. The IOP sees it as a
  condition and clears it. The data is ignored.
- **The ID:** a read returns what AB holds, and the firmware leaves the
  card's ID and a status byte there whenever it lets go of the bus. The
  slot can only be read while another master owns the bus, so AB is free
  then. That
  saves the 74HCT541 an ID would need, which would also be a second load
  on D8–D15 beside the 16652. The status byte counts while the firmware
  runs, so the CPU can tell a live IOP from a dead one. The card ID's
  format is still open ([RFC 0014, 8.2](0014-rfc-system-bus.md#82-card-ids)).

### 3.6 Devices on the card

All on T, each with a device select (REG bits 5–3) and a register (bits
2–0), with strobes from the timing logic. They are listed in
[section 7](#7-what-else-goes-on-the-card). The image flash (two
SST39SF040, 1 MB as 512K × 16) is addressed by X and three page bits in
the control register. Bulk reads go straight into AB (the last T
operation), which leaves REG free for the pointer being stepped; record
headers come onto R as device 7, and writes to device 7 program it. So
images that arrive over the serial line can stay.

### 3.7 Chips

| Block | Parts | Chips | With octal parts |
|---|---|---:|---:|
| Microcode | 6 × SST39SF010A (64K × 48 bits) | 6 | 6 |
| Microinstruction register | 3 × 74ABT16823 | 3 | 6 |
| Sequencer | 4 × 74F161 (uPC), 74F151 (condition), gates | 6 | 6 |
| Field decoders | 74F139, 2 × 74F138 | 3 | 3 |
| Timing: phase, stretch counter, write strobe, device strobes | 74ABT74, 74F161, gates | 3 | 3 |
| ALU | 4 × 74F181, 74F182 | 5 | 5 |
| F and AC | 2 × 74ABT16823 | 2 | 4 |
| Constants, K ↔ R | 74ABT16245 | 1 | 2 |
| Carry | 74F74 | 1 | 1 |
| Registers and data memory | IS61C6416AL-12, BANK (74ABT574), X (74ABT16823) | 3 | 4 |
| Loop counter | 74F161 | 1 | 1 |
| Control register: session, interrupt out, doorbell clear, CF speed, flash page | 74ABT273 | 1 | 1 |
| Bus addresses | AL, AHOUT, AH0, AH1: 4 × 74ABT16823 | 4 | 8 |
| Bus data | 74ABT16652 | 1 | 2 |
| Bridge, R ↔ T | 74ABT16245 | 1 | 2 |
| Bus control and state | 74ABT574, 2 for REQ, GNT and the transfer's state | 3 | 3 |
| Clock buffer | One part with specified skew (CDC341 class), as every card has | 1 | 1 |
| Slave side: doorbell, ID read | 74HCT132, 74HCT74 | 2 | 2 |
| **Core** | | **47** | **60** |
| Image flash | 2 × SST39SF040 | 2 | 2 |
| Devices ([section 7](#7-what-else-goes-on-the-card)) | | about 10 | about 10 |
| **The card** | | **about 60** | **about 72** |

Where it could shrink:

- **16-bit EPROMs** for the microcode, three 64K × 16 one-time
  programmable parts such as the AT27C1024: −3. A new chip for every
  firmware change, so only once the firmware settles.
- **No image flash,** with the CPU's images on the CF card: −2. Booting
  then depends on a removable card.
- **GALs** for the timing, decode and bus state: perhaps −6 to −8. Emily
  would rather not use them ([RFC 0014, open question 4](0014-rfc-system-bus.md#14-open-questions)).
- **The ALU from parts still made** costs more, not less: 74F283 adders
  with XOR gates and multiplexers for the logic operations, about 12–16
  chips against 5. The 74F181 is new-old stock, the same question the CPU
  has ([RFC 0007, section 3](0007-rfc-ideas-microarchitecture.md#3-parts)).

### 3.8 Timing

| Path | Steps, worst case (ns) | Total | Budget |
|---|---|---:|---:|
| A register through the ALU into F | phase flip-flop (74ABT74) 4.7, decoder enable 9, SRAM output enable 6 (or its address: uIR 6.8, 12), 74F181/182 with lookahead 29.5, setup 2.1 | 51 | 60 |
| Bus read data from BA, across the bridge, through the ALU | phase 4.7, decoder 9, 16245 enable 6.4, bridge 4.2, ALU 29.5, setup 2.1 | 56 | 60 |
| The carry into its flip-flop | uIR 6.8, SRAM 12, 74F181 to the 182 10.5, 182 9.5, last 181's carry out 9.5, setup 3 | 51 | 60 |
| Microcode fetch | uPC 11, flash 55, uIR setup 2.1 | 68 | 120 |
| Branch | phase 4.7, F onto R 6.5, condition 7.5, gate 6, 74F161 load setup 11.5 | 36 | 60 |
| Bus outputs at the card's edge | clock buffer 4.9, 74ABT16823 6.8 | 12 | 16 ([RFC 0014, 4](0014-rfc-system-bus.md#4-clock-and-timing)) |
| SRAM write strobe | from the phase flip-flop (4.7) to BCLK's fall, against the SRAM's 9 ns minimum; it must end before the next address, after E2 | | BCLK high ≥ ~15 ns, low ≥ ~10 ns |

- **The path from T is the tightest.** Decoding the R bus's source ahead
  of the uIR, as one-hot bits, would give back the decoder's 9 ns for
  two more microinstruction bits.
- **A 50 ns bus clock** (RFC 0014's floor) leaves no room in the first
  half: the IOP would need three bus clocks a microcycle, or a faster ALU.

### 3.9 Microcode

The loops that matter, in a notation for this RFC: each line is one
microinstruction; `r ← r + AC` reads register `r` and writes it back; a
bus address in brackets is the register's value before the step; `if lc
goto` branches while the loop counter isn't done, and counts it; the line
after a branch is its delay slot and always runs.

A copy, 16 transfers at a time:

```
copy:  misc ← SESSION                               ; ask for the bus
       lc ← 7                                       ; 8 pairs, 16 transfers
loop:  src ← src + AC; read [AH0:src]; if lc goto loop
       dst ← dst + AC; write [AH1:dst] ← BA         ; the delay slot
       AB ← idstat                                  ; the ID for slave reads
       misc ← 0                                     ; let go: the courtesy rule
       ...                                          ; count blocks, look at attention
```

| Loop | Microinstructions per transfer | Clocks per halfword, on the bus as built |
|---|---:|---|
| Copy | 1: a read and a write per pair | read + write: 2 + 3 for the memory card |
| Fill: AB loaded once, then writes | 1 | the write's: 3 for the memory card or the slave port |
| Image flash to the bus (`AB ← flash[X]; xr, X ← xr + AC`, then the write) | 2 | 4 |
| CF card to memory (`AB ← cf.data`, then the write) | 2 | 5 at PIO mode 4, 10 at mode 0 |
| A descriptor into registers (read, then `r ← BA`) | 2 | 4–6 |
| A character from a UART, with echo and line editing | 10–20 (*estimate*) | – |

## 4. Booting the CPU

### 4.1 What the CPU card provides

| | Chips | |
|---|---:|---|
| **A control register** in its slot: RUN, RESET (runs the reset routine), STEP (one microcycle, or to the end of the instruction), NMI; status: running, halted, at an instruction boundary | ~2 | RFC 0014 [8.3](0014-rfc-system-bus.md#83-interrupts-and-synchronisation) proposes one for every CPU. At power-up RUN is off if the control store is SRAM, on if it's flash (a jumper). Its RESET is the warm reset of the reset levels in [RFC 0009](0009-rfc-ideas-io.md#1-io), taken when the CPU's current transfer ends |
| **A slave port** into its RAM | (~12–15) | Recommended by RFC 0014 [section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus) for any DMA, so not counted here. The IOP loads the boot program through it |
| **A write port into an SRAM control store** | ~14 | Each 64K × 16 SRAM is a 16-bit lane in a window of the card's slot, written (and read back, to verify) while RUN is off |

The write port, for the 1b's control store in SRAM (eight SRAMs for the
120-bit microinstruction and its length class, one for the decode table;
RFC 0024 counts about ten):

- a 16-bit transceiver onto each SRAM's data pins: 9;
- the load address onto the microcode SRAMs' address, and onto the
  decode SRAM's (which the opcode on the CPU's data bus addresses): 2.
  The next-address multiplexers become 74F253s, with three-state
  outputs, for the same count;
- the write strobes: 2;
- the window's decode: 1.

That's about 14 chips, against RFC 0024's loader of about 22 plus 1–3
flash chips for the images, which now live on the IOP card. The control
register is there either way. So an SRAM control store would cost about
6 chips more than the flash one (10 SRAMs and the port's 14, against 18
flash ROMs), not about 15. In return: 1.2 times the speed at chip level
(0.82 s for the suite against 0.99 s) and a writable control store
([RFC 0024, open question 2](0024-rfc-faster-smaller.md#15-open-questions)).

### 4.2 The sequence

1. **Power-up:** the backplane resets everything. The bus parks on slot
   0, where the CPU card holds its CPU.
2. **The IOP starts** at microaddress 0: it tests its SRAM, sets up its
   devices, puts its ID in AB and prints a banner on the console.
3. **The slots:** it reads every slot's ID (BERR: empty) and prints the
   map.
4. **The control store:** it plays records of {bus address, count,
   halfwords} from its flash into the CPU card's window. Records skip
   what isn't used. The 1b's microcode is 3,507 microinstructions in
   4,096 slots, with a copy in the interrupt half of the address space
   and the fault entries: about 8K microinstructions in 8 lanes, plus the
   64K-entry decode table, about 130K halfwords. That takes about 35 ms
   at 7.6 MB/s, and all 640K halfwords 0.17 s.
5. **Verify,** if asked: read it back, the same time again.
6. **The boot program** goes into the CPU's RAM the same way, from the
   same kind of records.
7. **Start:** RESET, then RUN.
8. **Service:** the IOP's main loop ([section 10](#10-the-interface-to-the-cpu)).

### 4.3 Where the images come from

- **Its flash:** 1 MB, the control store and a boot program or a small
  operating system.
- **The CF card:** any size, read at 3–6 MB/s.
- **The serial line:** the monitor takes an image from the PC at
  921,600 baud, about 90 KB/s. The 1b's microcode and decode table, about
  260 KB, take about 3 s, and can be written into the flash.
- **Ethernet,** later ([RFC 0009, section 4](0009-rfc-ideas-io.md#4-networking)).

### 4.4 Without a slave port

If the first CPU card has no slave port, the IOP puts the boot program
on a memory card instead. The reset routine in the control store it just
wrote copies the program into the CPU's RAM before the first fetch. That
takes no chips, only a few microinstructions of the CPU's reset routine.

### 4.5 With a flash control store

The IOP isn't needed to boot. It can still load the boot program, and
the CPU card's own boot ROM and its overlay at reset (about 3 chips)
can go.

## 5. Should it be the DMA engine?

### 5.1 What there is to move

- **Devices:** disk sectors, Ethernet frames, terminal output (DH11-style
  output DMA, [RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)).
- **The operating system's pages:** zeroing, copy-on-write, swapping
  ([report 0020](0020-report-operating-system.md#zeroing-and-copying)).
- **Graphics:** fills and text in VRAM, from a stage-1 video card without
  a blitter ([RFC 0016, section 7](0016-rfc-video.md#7-blitter)).

### 5.2 What the IOP does on the bus

Assumptions:

- a 60 ns bus clock;
- the memory card reads in 2 clocks and writes in 3
  ([report 0025](0025-report-draft-1b-system.md#5-what-a-bus-transfer-costs));
- the CPU card's slave port takes 3 clocks either way, one WAIT with
  55 ns RAM (RFC 0014, section 10), longer when it collides with the CPU;
- every 16 transfers the IOP lets go of the bus and takes about 6 clocks
  to have it back (REQ is registered: a request on an idle bus takes 4).

| Transfer | Clocks per 16 transfers | Rate |
|---|---|---:|
| Copy, memory card to memory card, 16 bits | 8 × (2 + 3) + 6 = 46, per 16 bytes | 5.8 MB/s |
| Copy, memory card to the CPU's RAM | 8 × (2 + 3) + 6 = 46 | 5.8 MB/s |
| Copy, the CPU's RAM to its RAM or to the memory card | 8 × (3 + 3) + 6 = 54 | 4.9 MB/s |
| Fill, the CPU's RAM or the memory card | 16 × 3 + 6 = 54, per 32 bytes | 9.9 MB/s |
| Fill, a card without WAIT (VRAM's posted writes, when a slot is free) | 16 × 2 + 6 = 38 | 14 MB/s |
| Copy, 32-bit card to 32-bit card (+1 chip) | 46, per 32 bytes | 11.6 MB/s |
| Fill, 32 bits | 54, per 64 bytes | 19.8 MB/s |
| The image flash to the bus | 16 × 4 + 6 = 70, per 32 bytes | 7.6 MB/s |
| The CF card to memory, PIO mode 4 / mode 0 | 16 × 5 + 6 = 86 / 16 × 10 + 6 = 166 | 6.2 / 3.2 MB/s, less the card's own wait per sector |

**Without the DMA parts** (one segment register driving the bus, no loop
counter, one bus for R and T): a copy between slots changes the segment
twice per halfword and moves the data across R, about 6 microinstructions
a halfword: 2.5–4 MB/s (*estimate*). The four chips buy about twice that.

### 5.3 Against the CPU and the other ways

| How | Chips | Copy within the CPU's RAM | Copy across the bus | CPU time to copy a 4 KB page |
|---|---:|---:|---:|---:|
| The CPU, unrolled loop (report 0020's count, report 0025's 304 ns microcycle) | 0 | 1.4 MB/s | ~1 MB/s | 9,746 cycles |
| The CPU, `SAVE`/`RESTORE` through any register | microcode | 2.2 MB/s | ~1.2 MB/s | 6,184 cycles |
| The fast CPU of RFC 0024 (*estimate*) | 0 | ~3.5–5.5 MB/s | ~2 MB/s | the same cycles, ~2.5 times shorter |
| A microcoded channel in the CPU ([RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)) | ~5 | – | as fast as the device | for devices only: 5–7 cycles a word |
| RFC 0014's DMA card ([section 12](0014-rfc-system-bus.md#12-example-cards)) | ~34 | – | ~3–5 MB/s from the CF card | a request |
| Bus mastering on each device card | ~15–25 per device | – | – | a request |
| **The IOP** | **4 more** | **4.9 MB/s** | **5.8 MB/s (11.6 at 32 bits)** | **a request, ~200–700 cycles** |

Across the bus the IOP is 5–6 times the CPU as built (10 times at 32
bits), and about 3 times the fast CPU. Within the CPU's own RAM it is
2–3.5 times the CPU as built and about level with the fast one. What it
always gives is the CPU's time back.

### 5.4 What a request costs the CPU

- **Writing a descriptor:** about 8 stores, 20 cycles.
- **The doorbell:** one write to a simple card, about 1 µs.
- **The completion:** an interrupt, 150–250 cycles into the nucleus
  (like a preemption) or 500–640 to a user-level driver
  ([report 0020](0020-report-operating-system.md#interrupts-and-devices)).
  A completion can answer several requests.

So 200–700 cycles. The CPU copies at about 2.4 cycles a byte, so a
request pays from about 100–300 bytes up; smaller copies stay with the
CPU. **Latency:** the IOP sees the doorbell within about 3 µs (at its
next slice), reads a 16-byte descriptor in about 2 µs and posts the
completion in about 1 µs, so about 5 µs on top of the transfer.

### 5.5 What it costs

- **Four chips** (above), and the overlapped bus timing of section 3.2,
  which is logic the IOP's stall control has anyway.
- **One engine for everything.** A device waits for the current 16
  transfers (about 3 µs) before the IOP looks at it, and throughput is
  shared between jobs.
- **The bus.** The IOP holds it for up to 16 transfers at a time, so the
  CPU's own bus accesses (devices, the memory card) can wait about 3 µs.
  Its instruction fetches are local and never wait.
- **The slave port** limits copies into and out of the CPU's RAM. With
  fast parts the CPU uses its RAM more of the time, and the slave port
  waits more (*estimate*; nothing measures it yet).
- **Its firmware is trusted:** a bug writes anywhere. The other side of
  that is protection in firmware: the IOP can check each request against
  windows the supervisor set ([section 10](#10-the-interface-to-the-cpu)).
  As long as the IOP and the CPUs are the only bus masters, that does
  the job of the DMA window in the slave port, two comparators that
  [RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory) recommends
  (~3–4 chips).
- **No blitter.** Reading VRAM over the bus holds WAIT for 0.4–0.6 µs
  ([RFC 0016, 4.5](0016-rfc-video.md#45-how-the-cpu-reaches-it)), so a
  copy inside VRAM runs at about 3 MB/s at 16 bits and 6 at 32, against
  the blitter's 16–48. Fills and text work well enough
  ([section 6](#6-other-uses)).

### 5.6 Verdict

**Recommended:** make the IOP the system's DMA engine, with the four DMA
parts and the optional 32-bit path once there are 32-bit cards to copy
between. The reasons, in order:

1. It's nearly free. Booting needs a bus master, a sequencer and address
   arithmetic, and four chips make copies keep pace with the bus.
2. It's fastest where the CPU is slowest: across the bus, to devices,
   the memory card and VRAM.
3. One bus master for every device. The disk, Ethernet and video cards
   need no DMA logic of their own; their buffers are slave memory.
4. Rings are already the interface report 0020 recommends for DMA
   ([report 0020](0020-report-operating-system.md#asynchrony-rings-against-traps)),
   and the firmware can check every request.

What stays with the CPU: copies under a few hundred bytes, and copies
inside VRAM, which want RFC 0016's blitter if they matter.

## 6. Other uses

Ranked by value for the effort, highest first. "Firmware" means no chips
beyond the card's.

| Use | What it takes | What it gives |
|---|---|---|
| **Boot** the CPU, a writable control store included | Firmware, the CPU card's ports | Goal 2 |
| **A console monitor**, after the PDP-11's ODT and the VAX's console: examine and deposit anywhere on the bus, load images (binary, S-records), start, halt, step, dump and patch the control store. A key sequence returns the console from the CPU to the monitor, as ^P did on the VAX | Firmware | Bring-up and debugging, with the CPU halted or broken |
| **Microcode development:** new CPU microcode from the PC, loaded and restarted in a few seconds, without a programmer | Firmware | Makes RFC 0005's user-defined instructions and every microcode experiment cheap |
| **Power-on self test:** its own SRAM, every card's ID, memory tests, the slot map | Firmware | A machine that says what's wrong with it |
| **Terminal lines,** up to four, with line discipline: echo, erase, line editing, ^C, flow control; the CPU gets a line per interrupt | A quad UART | At 9,600 baud an interrupt per character takes 17% of the machine per line (report 0020); per line, under 1% for four busy lines. RFC 0009's intelligent terminal multiplexer, without the microcontroller it rejected |
| **The disk:** CF sectors to memory at 3–6 MB/s, queued, with read-ahead | The CF socket | 10–20 times the CPU's polled rate, and none of its time |
| **Pages for the operating system:** zero free pages in the background, copy for copy-on-write and spawn, swap to the CF card | Firmware | A demand-zero fault in ~130 cycles instead of 4,753; a 64 KB copy in 13 ms of the IOP's time instead of 52 ms of the CPU's |
| **Timers:** the microsecond clock, and the CPU's one-shot deadline as an interrupt; the time of day at boot | A timer and a clock chip | Replaces the CPU card's tickless timer (~4–6 chips, RFC 0009); a few µs of latency |
| **Keyboard and mouse:** PS/2 by firmware, scan codes turned into characters or events | 2 chips | RFC 0009 counts about 4 chips per port in hardware |
| **The front panel:** lights and switches through shift registers on the panel; examine, deposit, halt, run and step through the bus and the control register | A few port bits | Works when the CPU is wedged; the alternative to RFC 0009's panel through the CPU's microcode |
| **Ethernet frames:** copied between the MAC card's packet buffer and memory, the descriptor rings run by firmware | Firmware, with the MAC card | The MAC card needs no bus mastering (RFC 0009 planned LANCE-style DMA for it); a full frame in ~0.3 ms instead of ~1.2 ms of the CPU's |
| **Text on the screen:** glyphs from a font in its SRAM drawn into VRAM, about 30 µs each at 8 bits (the CPU: ~130 µs, the blitter: ~12 µs); with the PS/2 keyboard, a terminal built in | Firmware, with a video card | Boot messages and a console before the CPU runs; a stage-1 video card serves the console without a blitter |
| **Fills in VRAM:** clearing 640 × 480 at 8 bits in ~25 ms (~15 at 32 bits; the CPU: 154 ms, the blitter: 10 ms) | Firmware | A colour GUI's fills without the blitter |
| **Copy and checksum** in one pass, for TCP/IP | Firmware: a third microinstruction per halfword | About 4 MB/s, checksummed |
| **Watchdog:** NMI or reset the CPU if the operating system stops checking in | Firmware | |
| **Boot the other CPUs** of a multiprocessor: load their RAM, release their resets | Firmware | The system controller's job, RFC 0014 [8.3](0014-rfc-system-bus.md#83-interrupts-and-synchronisation) |
| **Network boot,** once Ethernet works | Firmware | Images from the PC without the serial line |
| **Sound:** samples from a ring in memory to an 8-bit DAC, 8–22 kHz | 1 chip and resistors | A few microinstructions a sample |
| **A parallel port** for a printer or a fast link to the PC | 2 chips | 100 KB/s or more before Ethernet |
| **Profiling the CPU:** sample the PC at, say, 10 kHz into a histogram | A PC sample register on the CPU card, ~2 chips | Where the time goes, without instrumenting |
| **A flight recorder:** bus errors, interrupts and console output in a ring in its SRAM, kept after a crash | Firmware | |
| **Test runs on the CPU:** load a program, run it, compare memory | Firmware | A hardware regression harness |
| **Memory testing** in idle time | Firmware | Bad memory found before it corrupts anything |
| **Semaphores and doorbells for several CPUs** on its card ([RFC 0014, open question 8](0014-rfc-system-bus.md#14-open-questions)) | ~3–4 chips, and a slave side with registers | A fixed home for them |

## 7. What else goes on the card

On T, and so only the IOP reaches them:

| What | Parts | Chips | Status |
|---|---|---:|---|
| Four serial lines | A quad UART with FIFOs (TL16C554 or XR16C554 class) and its 14.7456 MHz oscillator | 2 | **recommended**; plus line drivers |
| CF card, True IDE, 16 bits | The socket | 0 | **recommended** |
| Timer | 82C54 and a 1 MHz oscillator | 2 | **recommended** |
| Time of day | A battery-backed clock chip on three wires (DS1302 class), by firmware | 1 | **recommended** |
| Two PS/2 ports | Open-collector drivers, and two flip-flops that catch the clocks' falling edges; a spare driver is the IOP's interrupt line to the CPU | 2 | **recommended** |
| Attention and an input port | OR gates, 74HCT541 | 2 | **recommended** |
| An output port: panel shift chain, clock chip, LEDs | 74HCT574 | 1 | **recommended** |
| Sound | A latch and an R-2R ladder | 1 | **optional** |
| Parallel port | A latch and a buffer | 2 | **optional** |
| Semaphores for several CPUs | A register and test-and-set logic, a slave side with registers | 3–4 | **optional** |

**Not on it:** the Ethernet MAC (40–60 chips, a card of its own) and
video (RFC 0016's card). Both work with the IOP as slaves on the bus.

**The channel model.** With the console, the disk and the timer on the
IOP's card, the CPU touches no device itself: everything goes through
the IOP, as on the CDC 6600. The CPU never waits 880–960 ns for a
device register, and gets an interrupt per buffer or line. But a kernel
panic can only print through a working IOP. A one-UART simple card
(about 5 chips) would keep a direct path. **open**
([open question 2](#13-open-questions)).

**Board space.** About 60 chips, most of them small, fit a full 6U
Eurocard with room to spare. The card size isn't decided
([RFC 0014, open question 3](0014-rfc-system-bus.md#14-open-questions)).
The card needs only P1, and P2 for the 32-bit path.

## 8. What it saves and what it costs

Against a system that has the same things without an IOP (*estimates*):

| | Without the IOP | With it | From |
|---|---:|---:|---|
| The CPU card's boot ROM and its overlay at reset | ~3 | – | [RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system) |
| Filling an SRAM control store | ~22 and 1–3 flash | ~14 (the write port) | [RFC 0024](0024-rfc-faster-smaller.md#5-faster-parts) |
| The CPU card's control register | ~2 | ~2 | RFC 0014 |
| The I/O card: UART, timer, CF and its bus glue | 16 | – (on the IOP's card) | [report 0025](0025-report-draft-1b-system.md#3-chips) |
| DMA: RFC 0014's card, or bus mastering on the disk and Ethernet cards | ~34 | – | [RFC 0014](0014-rfc-system-bus.md#12-example-cards) |
| The DMA window in the slave port | ~3–4 | – | [RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory) |
| PS/2 keyboard and mouse | ~8 | – (on the IOP's card) | [RFC 0009](0009-rfc-ideas-io.md#1-io) |
| A tickless timer on the CPU card | ~4–6 | – | [RFC 0009](0009-rfc-ideas-io.md#1-io) |
| The IOP's card | – | ~60 | |
| **Total** | **~95** | **~76** | |

- **A system that would have had these anyway:** the IOP about pays for
  itself, and adds the monitor, the line discipline and the rest of
  section 6.
- **A minimal system,** with the control store in flash and no DMA: it
  replaces the boot ROM, the I/O card, the timer and the PS/2 logic
  (about 30 chips) with its card (about 60): **about 30 more**.
- **The slave port** (~12–15) isn't in either column: any DMA into the
  CPU's RAM needs it.

## 9. Alternatives

| Design | Chips | Boots a WCS | Programmable | Copies | Status |
|---|---:|---|---|---:|---|
| A loader on the CPU card ([RFC 0024](0024-rfc-faster-smaller.md#5-faster-parts)) | ~24, on the CPU card | yes | no | – | the alternative for booting alone |
| A boot sequencer card: plays records of bus writes from flash, no ALU | ~25 | yes | no | from flash only | **not recommended**: a card for one job |
| **The IOP without its DMA parts** | ~43 | yes | yes | 2.5–4 MB/s | **open**, if DMA is to live elsewhere |
| **The IOP** | ~47 + devices | yes | yes | 5–6 MB/s | **recommended** |
| A microprocessor (a 68000) with a bus bridge, flash and RAM ([RFC 0014, section 11](0014-rfc-system-bus.md#11-other-cpus-as-masters)) | ~20–25 | yes | yes | ~2–3 MB/s | **not recommended**: it is what the decision against microcontrollers in peripherals rules out in spirit; listed for its chip count |
| A barrel of 8 virtual I/O processors (RFC 0009, the CDC 6600's) | ~60–100 | yes | yes | – | **not recommended** for now: hardware tasks, next, get most of it |
| **Hardware tasks** in the IOP, as the Alto's microcode tasks: a uPC per task and a bank per task, a priority encoder of task requests, a switch between microinstructions | +~6 | | | | **open**, later: devices served at once, without polling between slices |
| **A one-clock microcycle,** with the microcode copied into fast SRAM at reset | +~4 | | | the same: copies are bound by the bus | **not recommended**: a register read through the ALU takes 51–56 ns, nearly the whole 60 ns clock, so it would also need the register file pipelined |
| **A Gigatron-style 8-bit core** (one ROM word per instruction, a decoder of a few gates) with the same bus interface | ~40 | yes | yes | ~1.4 MB/s | **not recommended**: 16-bit address arithmetic in 8-bit steps makes it no faster at copying than the CPU |

Two smaller choices inside the design:

- **The ALU:** the 74F181 (5 chips, new-old stock) against adders still
  made (12–16). **open**, with the CPU's.
- **The register file in flip-flops** (four 74ABT16823 registers with
  their outputs on R) instead of the SRAM: no strobe timing and no need
  for BCLK's falling edge, for 4 more chips and 4 registers instead of
  64 per bank. **not recommended**, unless BCLK's duty cycle can't be
  promised.

## 10. The interface to the CPU

- **Rings** in the CPU's RAM, as report 0020 recommends: a ring of
  requests the CPU writes and a ring of completions the IOP writes, each
  index with one writer. One pair per client: the kernel, and each
  user-level driver.
- **The doorbell:** a write to the IOP's slot after adding requests.
  **The completion interrupt:** the IOP's line, one of IRQ0–7 by jumper,
  held until the CPU rings again.
- **Requests:** copy, fill, read and write disk blocks, send and receive
  on a terminal line (raw or a line at a time), a timer deadline, frames,
  console and panel operations, and, on the kernel's ring only, setting
  up rings and their windows.
- **Windows:** each ring has a list of physical address ranges its
  requests may touch, set through the kernel's ring. The IOP checks every
  request against them, about 6 microinstructions.
- **A request** is 16 bytes: an operation, flags, two addresses, a length
  and a tag the completion returns.
- **The firmware's shape:** one main loop that branches on attention and
  dispatches; each job in a bank of its own; long jobs in slices of 16
  transfers, between which the loop looks at attention again. About 2–4K
  microinstructions (*estimate*): the loader and monitor about 1K, the
  drivers and rings the rest, against 64K the microprogram counter
  reaches.
- **Tools:** a microassembler in Python, as the 1b's microcode generator
  is (`studies/v1b_hw/ucode.py`); an image builder that turns the CPU's
  microcode, decode table and boot program into records; and a simulator,
  in Rust as RFC 0015 asks of engines. The IOP's flash is socketed:
  without buffers onto its data pins it can't reprogram its own
  microcode, so its firmware is written in simulation first and
  programmed off the board.

## 11. Stages, and simulate first

| Stage | The IOP's card | It gives | The CPU card needs |
|---|---|---|---|
| 1 | The core, the console UART, the image flash; firmware: self test, slot map, monitor, loader | Booting from flash or serial; examine, deposit, step | The control register; a slave port, or section 4.4's way round it; the write port for an SRAM control store |
| 2 | The CF card, timer, clock chip; rings, copies and fills | The operating system's disk, timers and pages | The slave port |
| 3 | Four lines with line discipline; PS/2; the front panel; sound | Terminals, keyboard, mouse, panel | |
| 4 | Frames for the Ethernet card; text and fills for the video card | The network and the screen | |
| Later | Hardware tasks, semaphores | | |

**Simulate first, recommended:**

1. **A model of the IOP** at microinstruction level, clocked by the bus
   clock, in the system model of `studies/v1b_system` (`model/`), with
   the device models `infra/devices` already has: the UART, the CF card
   and the timer.
2. **Firmware against it:** the loader and the monitor first, then the
   rings, copies and the CF card.
3. **Measure** what this RFC estimates: the copy rates on a model of the
   bus, the request costs with the kernel study's nucleus, the firmware's
   size.
4. **Then the netlist:** the IOP's card in the chip-level simulator on
   the v1b_system backplane, booting the 1b CPU card with a control
   register, a slave port and a write port into an SRAM control store
   added.

## 12. Against RFC 0009

How this RFC stands to the ideas in
[RFC 0009, section 2](0009-rfc-ideas-io.md#2-channels-and-dma) and
section 1:

| RFC 0009 | Here |
|---|---|
| A block I/O instruction in microcode (open) | Still worth having for the small copies that stay with the CPU |
| A microcoded channel in the CPU, recommended first (~5 chips) | The IOP does that job without the CPU's cycles; the channel stays the choice if there's no IOP |
| Cycle-stealing DMA, ~15–20 chips per channel | Replaced: the IOP is every device's DMA |
| A DMA card, 8 channels, ~34 chips | The IOP is that card, programmable, for about 13 more (core, no devices) |
| An intelligent terminal multiplexer: hardly needed with FIFO UARTs; with a microcontroller, rejected | The IOP does it in TTL, for the price of a quad UART |
| A CDC 6600-style barrel, ~60–100 chips | The IOP is one of its processors; hardware tasks are the cheap step towards the rest |
| PS/2, ~4 chips per port | By firmware, 2 chips for both |
| A timer for a tickless kernel on the CPU card, ~4–6 chips | On the IOP's card |
| The front panel through the CPU's microcode, recommended | An alternative: the panel on the IOP |
| Ethernet: later, DMA as a bus master with LANCE-style rings | The MAC card stays a slave; the IOP runs the rings |
| The 82C37, rejected | Stays rejected |

## 13. Open questions

For Emily:

1. **Build the IOP?** A card of about 60 chips that boots the CPU and
   runs its I/O, against a loader of about 24 chips on the CPU card for an
   SRAM control store, and the CPU doing its own I/O.
2. **The channel model:** the console, disk and timer on the IOP's card,
   so the CPU touches no device itself (recommended)? Or devices on a
   simple card the CPU drives, with the IOP as loader and DMA engine?
   And a one-UART simple card for the kernel's panics?
3. **DMA in the IOP** (recommended), rather than on each device card or
   on RFC 0014's DMA card?
4. **The control store in SRAM:** with the IOP it costs about 6 chips
   more on the CPU card than flash, instead of about 15 (RFC 0024, open
   question 2).
5. **The IOP's ALU:** the 74F181 (new-old stock) or adders still made, 7–11
   chips more? The CPU has the same question.
6. **Its microcode** in 8-bit flash, reprogrammable, or in 16-bit
   one-time-programmable EPROMs, 3 chips fewer?
7. **32-bit transfers,** one chip more?
8. **BCLK's duty cycle:** the IOP's register file needs BCLK high for at
   least about 15 ns of each period and low for about 10. RFC 0014
   doesn't say; the CPU card's divide-by-three ring gives 20 and 40 ns.
9. **Firmware for PS/2, the clock chip and the front panel** rather than
   hardware for each?
10. **A quad UART chip** for four lines, as the 16C550 is for one?
11. **The CPU's timer** from the IOP, with microsecond resolution and a
    few microseconds' latency, or on the CPU card?
12. **The IOP's card ID from firmware,** through its data transceiver,
    rather than from straps?
