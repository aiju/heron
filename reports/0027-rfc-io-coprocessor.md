---
number: 27
type: rfc
title: The I/O processor
status: open
date: 2026-10-15
context:
  studies: [v1b_system, v1b_tradeoffs, v1b_hw, kernel, fen]
  commit: dc03e22
depends-on: [9, 24, 25, 29, 36, 37]
---

# RFC 0027: The I/O processor

A proposal for the I/O processor, the IOP: a small microcoded machine on
a card of its own. It boots the main CPU, a writable control store
included. It is the system's DMA engine, the only master of the I/O bus,
and the controller of every device's interrupts. It holds RAM that the
CPUs share. Its firmware is a Forth, which its microcode interprets. It
sits on the system bus and drives the I/O bus of
[RFC 0037](0037-rfc-system-and-io-bus.md).

**Decided** (Emily, 2026-10-16): the IOP is part of every Heron, and it
is the system's DMA engine. Asked for (Emily, 2026-10-16), and proposed
here:

- code from memory in an instruction set of the IOP's own, not Heron's:
  the Forth ([section 6](#6-the-forth));
- the CPU reaching the I/O bus through the IOP (RFC 0037's window);
- the IOP's RAM serving the CPUs as slow, shared RAM
  ([4.3](#43-the-shared-ram));
- the IOP as the interrupt controller, with fast and slow interrupts to
  the CPUs, vectored where it matters
  ([7.3](#73-interrupts-to-the-cpus));
- the I/O bus's timing per device, in a table (RFC 0037).

The original goals, in order:

1. as few chips as possible;
2. boot the main CPU, including filling a writable control store;
3. compute speed doesn't matter; copy speed might, if it is also the DMA
   engine (now decided);
4. other jobs it could do.

**This revision** (2026-10-16), against the first version of this RFC:

- RFC 0037's buses instead of RFC 0014's: the I/O bus side, a slave side
  with three ranges in the static map, and no card IDs, BERR or class
  straps;
- the shared RAM, 2 MB, which takes the memory card's place;
- the Forth, and four small changes to the core for it: a dispatch on
  bit 15, holding the result register, a byte-swap register, and the
  register banks at the top of the SRAM;
- the IOP as the interrupt controller, with slow interrupts batched into
  rings and fast ones one source to a level;
- the spare microinstruction bit reserved as TASK, for hardware tasks
  later;
- the devices moved to I/O cards, except the console UART, the image
  flash, a timer and ports;
- Part I is now the specification and Part II the discussion.

Statuses: **decided**, **recommended**, **open** (a real choice either
way), **optional** (an add-on that can come later without changing the
rest) and **not recommended**.

Chip counts are estimates from a block diagram, not from a netlist: give
or take a quarter, as in [RFC 0016](0016-rfc-video.md). They assume 16-bit
"Widebus" registers and transceivers (74ABT16823, 16245, 16652), which
[RFC 0024](0024-rfc-faster-smaller.md#8-smaller-packages-and-plds)
recommends if their TSSOP packages are allowed; with octal parts the core
is about 13 chips bigger. No PLDs. Delays are worst-case datasheet figures
from the repository's timing data (`infra/hw/timing.json`), at the bus's
working period of 60 ns. Rates on the bus use the transfer timings
[report 0025](0025-report-draft-1b-system.md) built, which RFC 0037
keeps.

## Contents

Part I: Specification

1. [Overview](#1-overview)
2. [The card](#2-the-card)
3. [The core](#3-the-core)
4. [The system bus side](#4-the-system-bus-side)
5. [The I/O bus side, and the devices on the card](#5-the-io-bus-side-and-the-devices-on-the-card)
6. [The Forth](#6-the-forth)
7. [The interface to the CPUs](#7-the-interface-to-the-cpus)
8. [Booting the CPU](#8-booting-the-cpu)
9. [Chips](#9-chips)

Part II: Discussion

10. [What it's for, and precedents](#10-what-its-for-and-precedents)
11. [The DMA engine](#11-the-dma-engine)
12. [Why Forth](#12-why-forth)
13. [Other uses](#13-other-uses)
14. [Alternatives](#14-alternatives)
15. [What it costs and saves](#15-what-it-costs-and-saves)
16. [Stages, and simulate first](#16-stages-and-simulate-first)
17. [Against RFC 0009](#17-against-rfc-0009)
18. [Open questions](#18-open-questions)

## Part I: Specification

### 1. Overview

- **What it is:** a horizontally microcoded 16-bit machine, synchronous
  to the bus clock. A 48-bit microinstruction from six flash ROMs runs
  every two bus clocks (120 ns). It has a 74F181 ALU and one 64K × 16 SRAM
  that is both its register file, in banks of 64 registers, and its
  working memory. In one microinstruction it can step a register through
  the ALU and write it back, make one bus transfer, move data between the
  system bus and the I/O bus or the shared RAM, count a loop and branch.
- **Two levels of program:**
  - **microcode,** for the Forth's inner interpreter and primitives, and
    for everything that moves data or has tight timing: copies and fills,
    the rings' fast path, routing interrupts;
  - **Forth,** threaded code in the SRAM, for everything else: the
    console monitor, booting the CPU, the device drivers, the line
    discipline, the rings' control.
- **The Forth:** 16-bit cells. A cell with bit 15 set names a primitive by
  its microaddress; one with bit 15 clear is a colon definition's
  address. The step to the next word is two microinstructions and a delay
  slot, so it runs about a million Forth words a second. Each task is a
  register bank, and switching tasks takes about 1 µs.
- **On the system bus** ([section 4](#4-the-system-bus-side)):
  - a master, the DMA engine: copies at 5–6 MB/s at 16 bits, 7–8 MB/s
    from its shared RAM;
  - a slave with three ranges: the shared RAM in region 4
    (`0x4000_0000`), its registers at `0x7400_0000`, and the I/O bus's
    window at `0x7F00_0000`.
- **On the I/O bus:** its only master, as RFC 0037 Part II specifies.
- **Interrupts:** every device's interrupt goes to the IOP. It forwards
  events to the CPUs' request registers, either slow or fast:
  - **slow** (levels 1–5): carried in rings, and possibly batched;
  - **fast** (levels 6–8): one source to a level, so the level's vector is
    that source's handler.
- **Chips:** about 46 for the core, and about 95 for the card. The card
  adds the shared RAM, the slave side, the I/O bus side, the image flash,
  the console UART, a timer and ports.
- **Booting the CPU:** the CPU card holds its CPU while the IOP writes the
  control store and a boot program, then lets it run. The part of the
  1b's control store in use loads in about 35 ms.

The goals, answered:

| Goal | Answer |
|---|---|
| 1. Few chips | About 46 for the core. The bus interface (10) and the control store with its register (9) are 40% of it; the rest is a datapath with one register-file port and one ALU. The card is bigger because it now holds the memory card's RAM and the I/O bus |
| 2. Boot the CPU, with a writable control store | Yes: images from its own flash, an I/O card's CF card or the serial line, written into the control store and RAM through the CPU card's ports ([section 8](#8-booting-the-cpu)) |
| 3. Copies, as the DMA engine | 5–6 MB/s at 16 bits, the bus's own pace; 7–8 MB/s between the shared RAM and a CPU's RAM ([section 11](#11-the-dma-engine)) |
| 4. Other jobs | About 25, from the console to page zeroing ([section 13](#13-other-uses)) |

**Recommended:** build the IOP as Part I describes, with Forth as its
firmware. Give the CPU card a control register, an interrupt request
register, a slave port and, if the control store is SRAM, a write port
into it. Simulate it before any netlist
([section 16](#16-stages-and-simulate-first)).

### 2. The card

```
                                 system bus
   A1–A31, BE, START, WRITE        D0–D15                 REQ, GNT, WAIT, ATN0–3
  ======|=============================|==========================|===============
        |                             |                          |
  master: AL, AHOUT, AH0, AH1    16652: BA takes reads,     bus state; slave side:
  (16823 x 4)                    AB drives writes; also     three ranges, address
        |                        the slave's data path      register, WAIT
        |                             |
        |    +------------------------+--- T bus ---+-------------+-----------+
        |    |              |                       |             |           |
        | bridge         shared RAM            I/O bus side     swap      event ports,
        | (16245)        2 MB, 4 x 512K x 8    (RFC 0037, 22)   register  doorbells
        |    |                                      |
        |    |                  I/O bus ============+==== D0–D15, A0–A7, SEL and INT x 16
  ------+----+-------------------- R bus -----+-----------------+---------------
     |              |              |                |                  |
  SRAM 64K x 16  K <-> R        ALU: A from R,    F (16823): the     loaded from R:
  registers      (16245)        B from AC         result, onto R     AC, X, BANK,
  and memory        |           4 x 181 + 182     in the 2nd half    AH0, AH1, LC,
     |              |                 |                ^             control
  address:       K field              +----------------+
  BANK:REG or X     |
                    +--> uPC (4 x 161) --> microcode, 6 x flash --> uIR (3 x 16823)
```

- **On the system bus** it sits in master position 3, the highest
  priority ([RFC 0037, 6.1](0037-rfc-system-and-io-bus.md#61-master-positions)).
  It needs only P1, plus P2 for the optional 32-bit path.
- **The I/O backplane** connects to it, as RFC 0037 leaves open (a cable,
  or a connector of its own).
- **Size:** about 95 chips, most of them small. That fills a 6U Eurocard;
  the card may take two positions, which RFC 0037 allows.

### 3. The core

#### 3.1 The datapath

Three buses on the card:

- **R** (16 bits), the register bus: the SRAM, the microinstruction's
  constant, the ALU's A input, and the result register F, which drives R
  in the second half of every microcycle. Everything that loads, loads
  from R.
- **T** (16 bits), the transfer bus: the A side of the system bus's data
  transceiver, the shared RAM, the I/O bus side and the other T units of
  [3.5](#35-t-units). A bridge joins it to R. Copies move across T
  while R does the address arithmetic.
- **K** (16 bits): the microinstruction's constant field, onto R through
  a transceiver, and into the microprogram counter as a branch target. A
  jump to a computed address turns the transceiver round.

#### 3.2 The microcycle

Two bus clocks, from edge E0 through E1 to E2:

| | First half, E0–E1 | Second half, E1–E2 |
|---|---|---|
| R bus | The source: a register, memory at X, the constant or T | F |
| SRAM | Read | F written back, if asked, from E1 until BCLK falls |
| ALU | A from R, B from AC; F and the carry latched at E1, unless HOLD | – |
| System bus | The previous transfer's data clock | This microinstruction's address clock: AL loaded from R at E1, AHOUT from AH0 or AH1 |
| T bus | Read data, or a T unit, onto R if asked | A move into AB (write data) or a T unit, taken at E2 |
| At E2 | | The next microinstruction; AC, X, BANK, AH0, AH1, LC or the control register loaded from R if asked |

- **One register a microcycle,** read and written back: `src ← src + AC`
  is one microinstruction, and writing the result somewhere else is a
  second. The SRAM's address can't change at E1, where the write strobe
  starts, and the next microinstruction changes it at E2, so the strobe
  ends when BCLK falls. That needs BCLK high for at least about 15 ns of
  each period and low for about 10, which RFC 0037 promises
  ([4](0037-rfc-system-and-io-bus.md#4-clock-and-timing)).
- **HOLD:** a microinstruction can keep F and the carry from the one
  before, instead of latching the ALU. R in its second half is then the
  previous result, which it can write to the register or memory it
  addresses, or load into AC, X or another register. So a move between
  any two places in the SRAM takes two microinstructions, without
  touching AC.
- **Transfers overlap microinstructions.** The address clock is the
  second half; the data clock is the first half of the next
  microinstruction. So back-to-back transfers take their 2 clocks each.
  A transfer that runs longer (WAIT) or a bus the IOP doesn't hold yet
  stalls the next transfer's microinstruction at E1 until it can go.
- **Read data** is in BA when its transfer ends, during the next
  microinstruction. That one can move it into AB in its second half, for
  a copy; the one after can put it on R.
- **T units stretch the microcycle:** an I/O bus access by its
  device's entry in the timing table
  ([RFC 0037, 17](0037-rfc-system-and-io-bus.md#17-the-timing-table)),
  the shared RAM by a clock or two while the system bus is using it.
- **One branch delay slot.** The microprogram counter addresses the flash
  a microcycle ahead, so the microinstruction after a branch always runs.

#### 3.3 The microinstruction

48 bits, six flash ROMs wide:

| Field | Bits | Meaning |
|---|---:|---|
| K | 16 | A constant onto R, or a branch target |
| REG | 6 | A register in the current bank, or a T unit and its register (bits 5–3, 2–0) |
| RS | 2 | R in the first half: the register, memory at X, K, or T |
| ALU | 6 | The 74181's S0–S3 and M, and the carry in. One of the codes that repeat a logic function (with M = 1 the carry in is ignored) means HOLD |
| WB | 1 | Write F back in the second half: to the register, or to memory at X if RS chose memory |
| LD | 3 | Load from R at the end: none, AC, X, BANK, AH0, AH1, LC, the control register |
| BUS | 2 | None, read, write; the fourth value is kept for a locked read |
| SEG | 1 | AH0 or AH1 onto A16–A31 |
| SZ | 2 | Byte lanes: byte 0, byte 1, halfword, word |
| T | 3 | None; AB ← BA (a copy); AB ← F; AB ← a T unit; a T unit ← BA; a T unit ← F; T ← a T unit (for RS = T); spare |
| SEQ | 2 | Next; branch to K if the condition holds; branch to K if it doesn't; to F if the condition holds, otherwise to K |
| COND | 3 | Always, carry, F's bit 15, LC not done (and count), attention, doorbell, two spare |
| TASK | 1 | Reserved for hardware tasks ([section 14](#14-alternatives)): a task switch may follow this microinstruction. Ignored until then |

- **The all-zero microinstruction does nothing,** so reset clears the
  uIR and the counter and the IOP starts at address 0.
- **The dispatch:** SEQ's last code with COND = F's bit 15 is the Forth's
  step to the next word ([6.2](#62-the-inner-interpreter)). A
  primitive's microaddress has bit 15 set and is jumped to; a colon
  definition's address hasn't, and goes to K, the entry that calls it.
  With COND = always, it is a plain computed jump.
- **Conditions:** no zero flag. A register is tested for zero by
  decrementing it and branching on the borrow, and for equality with an
  XOR first. Bit 15 is on R in the second half, where the branch samples
  it.
- **Testing AC for zero** (**tentative**, Emily, 2026-10-16): AC is the
  ALU's B input, so the A side needs −1, and K is taken by the branch
  target. A register that holds −1 in the bank (`m1` in a Forth task's)
  gives it: `F ← m1 + AC` carries exactly when AC isn't 0. That costs no
  chip. A spare T unit reading all ones through pull-up resistors
  would be too slow: T carries about 100 pF, and its value goes straight
  into the 56 ns path from T through the ALU.
- ***Attention*** is set by the polling tick, by any doorbell, and by a
  control-register bit that the microcode sets while native work is
  waiting ([6.4](#64-tasks-native-jobs-and-events)).
- **AC** holds the step for pointers in native loops (2 for halfwords, 4
  for words, 0 for a device's register) and, while Forth runs, the top of
  its data stack.

#### 3.4 Registers and memory

One 64K × 16 SRAM (IS61C6416AL-12), addressed in 16-bit cells:

| Cells | |
|---|---|
| `0x0000`–`0x7FFF` | The Forth's dictionary: code, and any data. Every colon definition starts here |
| `0x8000`–`0xBFFF` | Stacks, buffers and tables |
| `0xC000`–`0xFFFF` | The register banks: register r of bank b is at `0xC000` + 64b + r |

- **Registers** are at {BANK, REG}: 256 banks of 64. Each job and each
  Forth task gets a bank of its own, so changing job is one load of
  BANK. Address bits 14–15 are driven high for a register access from
  two spare bits of the uIR, which costs no chip.
- **Registers are memory too:** X reaches them at their addresses, so a
  task's registers can be set up or examined with ordinary fetches and
  stores.
- **Working memory** is everything else, at X. X loads from R, usually
  in the microinstruction that steps the register that shadows it
  (`xr, X ← xr + AC`).

#### 3.5 T units

A *T unit* is one of the eight things a microinstruction reads or writes
over T. It picks one with REG bits 5–3, and one of the unit's registers
with bits 2–0. *Device* is kept for the I/O bus's devices (a UART, a CF
card, the console), which are all behind T unit 0:

| T unit | What | Address |
|---|---|---|
| 0 | The I/O bus: any device on an I/O card, or on this card ([section 5](#5-the-io-bus-side-and-the-devices-on-the-card)) | X: 256 × device + register ([RFC 0037, 15](0037-rfc-system-and-io-bus.md#15-devices-and-addresses)) |
| 1 | The shared RAM ([4.3](#43-the-shared-ram)) | {page, X} |
| 2 | The swap register: written from T, read back with its two bytes swapped | – |
| 3 | The event ports: the I/O bus's 16 INT lines, ATN0–ATN3, the tick, the doorbells; writes clear a doorbell or the tick | REG bits 2–0, and X for a doorbell's number |
| 4 | Page registers: the shared RAM's (4 bits) and the image flash's (11 bits) | REG bits 2–0 |
| 5 | The timing table, written at boot ([RFC 0037, 17](0037-rfc-system-and-io-bus.md#17-the-timing-table)) | X bits 8–11 |
| 6 | Spare: the optional shift register (a right shift by one, like the swap register) | – |
| 7 | Spare | – |

- **An I/O bus access** stalls the core until its strobe ends; reads and
  writes alike. Posting writes, so that the core runs on, is **open**: it
  needs the I/O side to hold the address and data, which it may already.
- **Bulk reads** go straight into AB (`AB ← a T unit`), which leaves R
  free for the pointer being stepped.
- **X addresses both the I/O bus and the shared RAM,** so a loop between
  the two reloads X every halfword, about 3–4 microinstructions. An
  address counter for the shared RAM and the spare T code (the shared
  RAM takes another T unit's data from T) would make it one: about 3 chips,
  **optional**.
- **Registers come in groups, one per T unit.** A microinstruction that
  uses a register and a T unit at once has only REG's 6 bits for both,
  so the register's bits 5–3 must be the unit's number:

  | Registers | Go with | |
  |---|---|---|
  | 0–7 | T unit 0, the I/O bus | any of the eight, as the address comes from X |
  | 8–15 | T unit 1, the shared RAM | any of the eight, likewise |
  | 16–63 | T units 2–7 | exactly one: bits 2–0 also pick the unit's own register, so reading event port 2 while stepping a register steps register 26 |

  So a native loop between a T unit and the bus keeps its pointers in
  that unit's group. The Forth's own registers can sit anywhere: NEXT,
  `nest` and the stack words never use a T unit, and the words that do
  (`io@`, `sr@`) combine it with AC and X, not with a bank register. This
  is a numbering convention, which costs nothing. A separate field for
  the T unit would need a seventh microcode flash, 56 bits; worth looking
  into only if the convention turns out to be a problem.

#### 3.6 Timing

| Path | Steps, worst case (ns) | Total | Budget |
|---|---|---:|---:|
| A register through the ALU into F | phase flip-flop (74ABT74) 4.7, decoder enable 9, SRAM output enable 6 (or its address: uIR 6.8, 12), 74F181/182 with lookahead 29.5, setup 2.1 | 51 | 60 |
| Bus read data from BA, across the bridge, through the ALU | phase 4.7, decoder 9, 16245 enable 6.4, bridge 4.2, ALU 29.5, setup 2.1 | 56 | 60 |
| The carry into its flip-flop | uIR 6.8, SRAM 12, 74F181 to the 182 10.5, 182 9.5, last 181's carry out 9.5, setup 3 | 51 | 60 |
| Microcode fetch | uPC 11, flash 55, uIR setup 2.1 | 68 | 120 |
| Branch | phase 4.7, F onto R 6.5, condition 7.5, gate 6, 74F161 load setup 11.5 | 36 | 60 |
| The dispatch: to F or to K by F's bit 15 | phase 4.7, F onto R 6.5, condition 7.5, gate 6, 16245 enable 6.4 and through 4.2, 74F161 load setup 11.5 | 47 | 60 |
| HOLD: F's clock enable | uIR 6.8, decode 5, 16823 enable setup 3 | 15 | before E1 |
| Bus outputs at the card's edge | clock buffer 4.9, 74ABT16823 6.8 | 12 | 16 ([RFC 0037, 4](0037-rfc-system-and-io-bus.md#4-clock-and-timing)) |
| SRAM write strobe | from the phase flip-flop (4.7) to BCLK's fall, against the SRAM's 9 ns minimum; it must end before the next address, after E2 | | BCLK high ≥ ~15 ns, low ≥ ~10 ns |

- **The path from T is the tightest.** Decoding the R bus's source ahead
  of the uIR, as one-hot bits, would give back the decoder's 9 ns for
  two more microinstruction bits.
- **The dispatch** turns the K transceiver round only once the condition
  is known, which costs it 11 ns over a plain branch. The uIR's K outputs
  and the transceiver must not overlap as they swap; a gate's delay
  between them is enough (*to be checked* in the netlist).
- **A 50 ns bus clock** (RFC 0037's floor) leaves no room in the first
  half: the IOP would need three bus clocks a microcycle, or a faster ALU.

### 4. The system bus side

#### 4.1 As a master

[RFC 0037, section 6](0037-rfc-system-and-io-bus.md#6-bus-mastering):

- **Addresses:** AL drives A1–A15 from its bits 1–15 (SZ picks the byte
  lanes), and AHOUT drives A16–A31. AH0 and AH1 are two segments, so a
  copy between two cards changes its upper address on every transfer at
  no cost. AHOUT exists so that each bused line sees one output, rather
  than AH0 and AH1 both.
- **Data:** one 74ABT16652 registered transceiver. BA takes read data at
  the end of every data clock without WAIT; AB drives write data. A copy
  moves BA to AB across T without using R.
- **Control:** START, WRITE, BE0–BE3 and LOCK come from a 74ABT574 loaded
  at E1. REQ follows a session bit in the control register, which the
  firmware clears after every 16 transfers, as RFC 0037's courtesy rule
  asks ([6.3](0037-rfc-system-and-io-bus.md#63-masters)).
- **16 bits by default:** halfword and byte transfers.
- **32 bits (optional, +1 chip):** a second 16652 on D16–D31, on P2. Word
  transfers go only to cards the card table says are 32-bit; W32
  inactive then is counted as an error.
- **The stuck-transfer counter** (~2 chips) counts the data clocks of
  every transfer on the bus, whoever owns it. At 256 the IOP asserts
  RESET, a system reset, and records the owner and the address
  ([RFC 0037, 5.6](0037-rfc-system-and-io-bus.md#56-unused-addresses-and-faults)).
- **Reset:** the card listens to COLD only, and drives RESET between its
  own transfers ([RFC 0037, 7](0037-rfc-system-and-io-bus.md#7-reset)).

#### 4.2 As a slave

Three ranges of [RFC 0037's map](0037-rfc-system-and-io-bus.md#51-addresses),
fixed, so the card needs no jumpers:

| Range | What |
|---|---|
| `0x4000_0000`–`0x4FFF_FFFF`, region 4 | The shared RAM, 2 MB, repeated through the region ([4.3](#43-the-shared-ram)) |
| `0x7400_0000`–`0x74FF_FFFF` | Its registers for the CPUs ([4.4](#44-registers-for-the-cpus)) |
| `0x7F00_0000`–`0x7FFF_FFFF` | The I/O bus's window ([RFC 0037, 20](0037-rfc-system-and-io-bus.md#20-the-window-from-the-system-bus)) |

- **Decoding:** from A31–A24 by gates, in the address clock, registered
  with A1–A23, BE and WRITE.
- **A 16-bit card:** it never drives W32, so a 32-bit master makes a word
  as two transfers
  ([RFC 0037, 5.5](0037-rfc-system-and-io-bus.md#55-data-width-and-byte-lanes)).
- **Data** goes through the master side's 16652. The IOP can't be
  addressed while it owns the bus, so the two uses never collide.
- **T is shared:** a slave access takes T for its data clock; a core
  microinstruction that uses T meanwhile waits at E1. One that doesn't use
  T runs on, so Forth and a copy's address arithmetic both carry on.
- **WAIT** from the first data clock until the data is ready: about 2
  clocks for the shared RAM (*estimate*), 1 for the registers, and as
  RFC 0037 says for the window.

#### 4.3 The shared RAM

- **2 MB:** four 512K × 8 SRAMs (AS6C4008-55), as 1M × 16, on T.
- **From the system bus:** region 4, at `0x4000_0000` + its byte
  address; halfwords and bytes. About 3 clocks a transfer, 4 when the
  core was using it (*estimate*), like report 0025's memory card.
- **From the IOP:** T unit 1, at {page, X}. A halfword in a
  microcycle, unless the bus has it.
- **The system bus comes first;** the core waits.
- **What it holds:** the rings and their buffers; slow RAM for the CPUs; a
  disk cache or a RAM disk; swap; images; the Forth's bigger data. The
  operating system owns it and tells the IOP which parts it may use, as
  windows ([7.2](#72-requests-and-windows)).
- **Copies** between it and a CPU's RAM take one bus transfer a halfword,
  the IOP's own side being local: about 7.6 MB/s
  ([11.2](#112-what-the-iop-does-on-the-bus)). Copies between it and an
  I/O device use no bus time at all.
- **32 bits (optional):** two more SRAM lanes and P2's transceivers, once
  a master makes word transfers.
- **Room for more** (**open**, a proposal of Emily's, 2026-10-16): space on
  the card for more shared RAM than 2 MB, fitted as wanted, say up to
  8 MB.
  - The page register grows from 4 bits to 6, which still fits its chip.
  - The slave side already registers A1–A23, enough for 16 MB.
  - A decoder picks the bank: about 1 chip.
  - The SRAMs: 4 more for each 2 MB with these parts, or 2 with 512K × 16
    ones.
  - Board space is what limits it, and more T loading; the card may take
    two positions anyway ([section 2](#2-the-card)).
- **The status block:** its first 64 bytes are the IOP's, written by its
  firmware: a count that changes while the firmware runs, its state, the
  firmware's version, and where its log is. That saves a status register
  and its read path.

#### 4.4 Registers for the CPUs

At `0x7400_0000`, the range RFC 0037 left open for them:

| Address | |
|---|---|
| `0x7400_0000` + 4n, n = 0–15 | Doorbell n: a write sets it, whatever the data |
| anything else in the range | Unused: a write is lost, a read returns stale data |

- **One doorbell per client** ([7.1](#71-rings-and-doorbells)). The IOP
  sees any doorbell as attention, reads which on its event port, and
  clears it before it looks at the ring, so a doorbell rung during the
  look is kept.
- **Parts:** two 74HC259 addressable latches, set from the slave side and
  cleared from the IOP's, through a multiplexer: about 3 chips.
- **A CPU's own request register** is on its card, at `0x7N00_0000`
  ([RFC 0037, 9](0037-rfc-system-and-io-bus.md#9-cpu-cards)); the IOP
  writes it to interrupt that CPU.

### 5. The I/O bus side, and the devices on the card

- **The I/O bus:** the IOP is its master, as
  [RFC 0037, Part II](0037-rfc-system-and-io-bus.md#part-ii-the-io-bus)
  specifies: about 15 chips
  ([22](0037-rfc-system-and-io-bus.md#22-the-io-processors-side)),
  which replace the first version's device decode and stretch counter.
- **Addressing:** device S, register r is reached through T unit 0, with
  X = 256S + r.
- **The window's accesses** take turns with the IOP's own
  ([RFC 0037, 20](0037-rfc-system-and-io-bus.md#20-the-window-from-the-system-bus)).
- **Devices 12–15 are on this card,** with the same rules and the same
  timing table as the slots:

| Device | What | Chips |
|---|---|---:|
| 12 | The console: a 16C550 UART with its own 14.7456 MHz oscillator, for 921,600 baud | 2 |
| 13 | The image flash: two SST39SF040, 1 MB as 512K × 16, addressed by its page register and A0–A7; programmable in place | 2 |
| 14 | A timer: an 82C54 from CLKB, for the polling tick, the microsecond clock and timeouts | 1 |
| 15 | Ports. Out: LEDs, the front panel's shift chain, the clock chip's three wires, the watchdog's kick. In: the clock chip's data, the panel | 2 |
| – | The time of day: a DS1302 on the ports | 1 |
| – | The watchdog: a retriggerable monostable that asserts COLD if the firmware stops kicking it for about 100 ms | 1 |

- **The image flash's size** is to be confirmed (Emily, 2026-10-16).
  1 MB holds the Forth's dictionary (up to 64 KB), the 1b's control store
  and decode table (about 260 KB), and a boot program or a small
  operating system. Draft 2's control store, and how many images the
  flash should hold at once, decide it. More needs larger or more parts
  and a wider page register.
- **Moved to I/O cards** since the first version: the quad UART, the CF
  socket, PS/2 (with a shift register for each port on its card), sound
  and the parallel port. RFC 0037 lists such cards in
  [section 21](0037-rfc-system-and-io-bus.md#21-electrical-rules-and-cards).
- **The event ports** add about 2 chips to the I/O side's INT port: the
  doorbells, ATN0–ATN3 and the tick.

### 6. The Forth

#### 6.1 The machine

- **Cells** are 16 bits, and addresses count cells in the SRAM. A
  character takes a cell (`1 chars` is 1): wasteful, but simple, in 64K
  cells. Text in the shared RAM and on the system bus is bytes, which the
  bus words and the swap register pack and unpack.
- **A thread** is a list of cells:
  - a cell with bit 15 set is a primitive: its value is the primitive's
    microaddress, so the primitives start in the upper half of the
    microcode, `0x8000`–`0xFFFF`;
  - a cell with bit 15 clear is a colon definition: the SRAM address of
    its body. So every colon definition starts below `0x8000`.
- **No other kinds of word:**
  - a constant or a variable compiles inline as `lit n`;
  - `create` makes a colon definition that pushes its data's address;
  - `does>` makes that definition go on to the shared code.
- **A task's registers,** in its bank:

  | Register | |
  |---|---|
  | `ip` | The cell being executed |
  | `sp` | The data stack: the second item. The top is in AC while the task runs |
  | `rp` | The return stack's top |
  | `tos` | The top of the data stack while the task is switched out |
  | `resume` | The microaddress the task goes on at: NEXT for a Forth task |
  | `link` | The next task's bank |
  | `wait` | The event the task waits for, or 0 if it can run |
  | `m1` | −1, for testing the top of the stack for zero ([3.3](#33-the-microinstruction), **tentative**) |
  | `t0`–`t7` | Scratch for primitives; `w`, the word `execute` runs, is `t0` |
  | 16–63 | The task's user variables: `base`, `state`, `>in`, its terminal, and so on |

- **Stacks** grow down in `0x8000`–`0xBFFF`, 64 cells each by default.
- **Flags** are −1 and 0.
- **AC is the top of the stack** while Forth runs, which suits the
  datapath: the ALU's B input is AC, so a binary operation reads the
  second item from memory as A. Native words that need AC as their step
  keep the top in `tos` and put it back.

#### 6.2 The inner interpreter

The notation, for this RFC: each line is one microinstruction; `r ← r + 1`
reads register r and writes it back; `X ← …` loads X from the result;
`F ← [X]` reads the cell at X; `(hold)` keeps the previous result, so
`[X] ← F (hold)` writes it at X; `to F if F15, else nest` is the dispatch;
the line after a jump is its delay slot and always runs.

NEXT, the step to the next word, with `ip` at the cell just executed:

```
next:   ip, X ← ip + 1                          ; the next cell
        F ← [X]; X ← F; to F if F15, else nest  ; a primitive, or a colon definition
        ...                                     ; the delay slot
```

It is inline at the end of every primitive. Its delay slot does the
primitive's last step, when it has one. `+`, with the top of the stack in
AC and the second item at `[sp]`:

```
plus:   X ← sp
        AC ← [X] + AC
        ip, X ← ip + 1
        F ← [X]; X ← F; to F if F15, else nest
        sp ← sp + 1                             ; the delay slot: the pop
```

Calling a colon definition (`nest`) and returning (`exit`):

```
nest:   rp, X ← rp − 1                          ; room on the return stack
        F ← ip
        [X] ← F (hold)                          ; push ip
        X ← ip
        F ← [X] − 1                             ; the body, less one
        ip ← F (hold)
        ...                                     ; NEXT, 3 more

exit:   X ← rp
        F ← [X]
        ip ← F (hold)                           ; the caller's ip
        ip, X ← ip + 1
        F ← [X]; X ← F; to F if F15, else nest
        rp ← rp + 1                             ; the delay slot: the pop
```

- **Why bit 15:** the dispatch tells a primitive from a colon definition
  in the same microinstruction that fetches the cell, so no word needs a
  code field and no fetch is spent on one.
- **`execute`** runs a word that isn't in the thread, so `nest` can't
  re-read its address from `[ip]`. It goes through a second entry,
  `nest-w`, that takes the address from a register instead. That is about
  half a dozen microinstructions more microcode, and a colon definition
  through `execute` takes about 13 microcycles:

  ```
  execute: w ← AC                                  ; the word to run
           X ← sp
           AC ← [X]                                ; pop: the new top
           F ← w; to F if F15, else nest-w         ; a primitive, or a colon definition
           sp ← sp + 1                             ; the delay slot
  nest-w:  rp, X ← rp − 1
           F ← ip
           [X] ← F (hold)                          ; push ip, which points at execute's cell
           F ← w − 1                               ; the body, less one
           ip ← F (hold)
           ...                                     ; NEXT
  ```

  A primitive run this way ends with its own NEXT and carries on after
  `execute`, as `ip` hasn't moved.
- **`branch`, `0branch`, `exit` and `pause`** also look at attention, one
  microinstruction each ([6.4](#64-tasks-native-jobs-and-events)).

#### 6.3 Primitives

About 60, in microcode. Times include NEXT (*estimates*, 120 ns a
microcycle):

| Group | Words | Microcycles |
|---|---|---:|
| Stack | `dup` `drop` `swap` `over` `nip` `>r` `r>` `r@` | 5–7 |
| Arithmetic and logic | `+` `-` `and` `or` `xor` `invert` `negate` `1+` `1-` `2*` | 5 |
| Comparisons | `=` `<>` `<` `u<` `0=` `0<` | 6–8 |
| Memory | `@` `!` `+!` (`c@` and `c!` are `@` and `!`) | 5–8 |
| Control | `lit` `branch` `0branch` `execute` `(do)` `(loop)` `i` | 6–9 |
| A colon definition | `nest` and `exit` | 15 |
| Slow arithmetic, in microcode loops | `um*` `um/mod` `rshift` `2/` | 40–160 (5–20 µs) |
| The system bus | `bus@` `bus!` `busc@` `busc!` `bus2@` `bus2!`: an address as a double cell | ~10 and the transfer |
| The shared RAM | `sr@` `sr!` `src@` `src!` | ~6 |
| The I/O bus | `io@` `io!`, with 256 × device + register | ~5 and the access |
| Blocks, native | `bus-move` `bus-fill` `sr>bus` `bus>sr` `io>sr` `sr>io` `flash>sr` | at [11.2](#112-what-the-iop-does-on-the-bus)'s rates, pausing between slices |
| Tasks and events | `pause` `wait` `wake` `route` | ~7 |
| The CPUs | `post` (an event into a CPU's ring) `cpu-int` (a level) `cpu-halt` `cpu-run` `cpu-step` | ~15 and the bus writes |
| Time | `us` `ms` | |

- **Speed:** NEXT is 3 microcycles (0.36 µs), 2 when its delay slot
  holds the word's last step. Most primitives take 5–7 (0.6–0.84 µs), and
  a call and return 15 (1.8 µs). About **a million Forth words a
  second** in ordinary code.
- **Bytes** at an odd address on the system bus come in on D8–D15. The
  swap register brings them to the low byte, 2 microinstructions more.
- **Right shifts** have no path. Without the optional shift register a
  shift right by one takes about 15 microinstructions, and by eight a
  swap and an `and`.

#### 6.4 Tasks, native jobs and events

- **Forth tasks are cooperative.** They run round robin through `link`
  and switch at `pause`; every word that waits (`key`, `emit` to a full
  FIFO, a block transfer, `ms`) pauses. A switch saves AC in `tos`, loads
  BANK from `link`, skips the task if its `wait` isn't 0, puts `tos`
  back in AC and jumps to `resume`: about 7 microinstructions, 4 for each
  task skipped.
- **Native jobs come first.** The rings' fast path, copies and fills,
  routing events, and any device with tight timing run in microcode, in
  slices of at most 16 bus transfers. Each has a bank too, with its own
  resume address.
- **Attention** says native work is waiting: the tick, a doorbell, or a
  native job with work left. Forth looks at it in `branch`, `0branch`,
  `exit` and `pause`, runs the native work there, and carries on with the
  same task. So native work waits at most a few microseconds for Forth.
  Forth gets a turn at least every eighth slice (*a convention*), so the
  console stays alive during a long copy.
- **Events:** at each tick (every 10 µs; the timer sets it) the native
  layer reads the event ports: the I/O bus's INT lines and ATN0–ATN3.
  - **Each source** has an entry in an event table in the SRAM: its
    owner, which is a Forth task or a CPU with a level
    ([7.3](#73-interrupts-to-the-cpus)), a mask bit and its state.
  - **A source owned by a task** clears that task's `wait`; one owned by a
    CPU is forwarded.
  - **A level-sensitive source** is masked in software from then until
    its owner says it has been served: the task by waiting again, a CPU's
    driver by a request.
  - **Doorbells** raise attention at once, without waiting for the tick.
- **What polling costs:** about 0.5–1 µs a tick, so 5–10% of the IOP at
  10 µs (*estimate*). Change detection in hardware (a register of the
  lines' last state and two 74F521s, about 4 chips) would save that time
  and most of the latency. **optional**.
- **Hardware tasks, later:** the TASK bit marks where a switch may happen,
  and the event lines would wake tasks directly
  ([section 14](#14-alternatives)).

#### 6.5 What stays in microcode

- reset, the SRAM's self test, and copying the Forth out of the image
  flash;
- the inner interpreter and the primitives;
- copies, fills, zeroing, and blocks between devices and memory;
- the rings' fast path: fetching a request, checking its windows, and
  starting a copy or fill;
- the tick: reading the event ports, routing events, posting them to the
  CPUs;
- anything per byte at a high rate: the serial line during an image load
  (921,600 baud), a floppy's data phase if there is one;
- text into VRAM: a glyph at a time from a font in the SRAM.

#### 6.6 The system in Forth

Everything else: the console monitor, booting the CPU, the card table and
the timing table, the line discipline, PS/2 scan codes, the clock chip,
the rings' control requests, the routing table, the watchdog's policy,
self tests. The console *is* the Forth's interpreter, so the monitor is
interactive from the first day. In outline:

```forth
\ the monitor's examine and deposit, on any address on the system bus
: e  ( d -- )    2dup ud.  ." : "  bus@ u. ;
: d  ( x d -- )  bus! ;

\ boot the CPU: its control store, then its first program
: boot-cpu  ( -- )
   cpu-halt  wcs-image play  boot-image play  cpu-reset cpu-run ;

\ a terminal line's task, on the terminal in its user variables:
\ echo and erase, then a whole line to the CPU
: line-task  ( -- )
   begin  key
      dup 8 = if  drop rub-out  else          \ backspace
      dup emit  dup 13 = if  drop line-done  else  put-char  then
      then
   again ;
```

#### 6.7 Building and changing it

- **Tools:** a Python microassembler builds the microcode, as the 1b's
  microcode generator does (`studies/v1b_hw/ucode.py`), and a Python
  metacompiler builds the Forth's dictionary from its source. An image
  builder puts the dictionary, the CPU's images and the card table into
  the image flash.
- **At power-up** the microcode copies the dictionary from the image
  flash into the SRAM (32K cells in about 30 ms, *estimate*) and starts
  the console task.
- **Changing it in place:** the console compiles new words, and `save`
  writes the dictionary back into the image flash. Only the microcode
  needs its flash taken off the board: without buffers onto its data
  pins the IOP can't reprogram it.
- **Code from the CPU:** the kernel's ring can hand the IOP Forth source
  to compile, or compiled words to add ([7.2](#72-requests-and-windows)).
  It runs from the SRAM at full speed like the rest, so nothing needs to
  run more slowly from elsewhere. Only the kernel's ring may do it:
  Forth trusts its code, and a word can write anywhere in the IOP.

### 7. The interface to the CPUs

#### 7.1 Rings and doorbells

- **Rings** in the shared RAM (**recommended**: the IOP reads them
  locally, and a CPU writes them like any memory), or in a CPU's RAM: a
  ring of requests the client writes and a ring of completions the IOP
  writes, each index with one writer.
- **Clients:** one pair of rings per client, with its own doorbell: the
  kernel's on doorbell 0, and up to 15 more, for user-level drivers.
- **Ringing:** a client adds requests, then writes its doorbell
  ([4.4](#44-registers-for-the-cpus)).

#### 7.2 Requests and windows

- **Requests:** copy, fill, zero; read and write disk blocks; send and
  receive on a terminal line, raw or a line at a time; a timer deadline;
  Ethernet frames; console and panel operations. On the kernel's ring
  only: setting up rings and their windows, routing interrupt sources,
  owning I/O devices through the window, and loading Forth.
- **Windows:** each ring has a list of physical address ranges its
  requests may touch, set through the kernel's ring. The IOP checks every
  request against them, about 6 microinstructions.
- **A request** is 16 bytes: an operation, flags, two addresses, a length
  and a tag the completion returns.
- **The fast path is native:** fetching a request, checking its windows
  and starting a copy or fill take about 5 µs
  ([11.4](#114-what-a-request-costs-the-cpu)). Other requests go to a
  Forth task.

#### 7.3 Interrupts to the CPUs

- **The IOP routes every source:** the I/O bus's INT lines, ATN0–ATN3
  from cards on the system bus, its own completions and timers. Each has
  an entry in the event table: a task of the IOP's, or a CPU, a level and
  so a class. The kernel sets them through its ring.
- **Interrupting a CPU,** as [RFC 0037, 8](0037-rfc-system-and-io-bus.md#8-interrupts)
  has it: the IOP writes the event into a ring for that CPU (one ring per
  sender and receiver, so each has one writer), then the level's bit to
  the set address of the CPU's request register.
- **Slow, levels 1–5:** the kernel passes the events on, usually to a
  user-level driver as a notification. The IOP may batch them: it holds
  a slow level back for up to a time the kernel sets for each source
  (say 1 ms), then posts all the events with one interrupt.
- **Fast, levels 6–8:** never batched, and **one source to a level**.
  Draft 2 vectors interrupts by level
  ([RFC 0029, 7](0029-rfc-draft-2-system.md#7-interrupts)), so a fast
  level's vector is its source's handler, with nothing to look up. That
  is where vectoring matters most (Emily, 2026-10-16). Each fast level
  has a mailbox word beside the rings, written before the bit is set. A
  fourth fast source would share a level and look at the mailboxes.
- **Which sources are fast** is the kernel's choice. The candidates: a
  CPU-to-CPU interrupt for a page-map change the sender waits for, the
  end of a short request a thread is waiting on, an audio buffer running
  low, a break on the console.
- **What the kernel does for them:**
  - its critical sections run at `SPL #5` instead of with interrupts
    off, so levels 6–8 get in even then;
  - a fast handler touches only its own data, and raises a slow level on
    its own CPU, by a write to its own set address, for anything more;
  - a register bank for each fast level would let their handlers save
    nothing, which RFC 0029 leaves **open**.
- **The CPU card's own timer,** which drives the scheduler, is a slow
  source at level 5: its handler needs the kernel's data.
- **CPU-to-CPU interrupts** are writes between CPU cards directly, and
  follow the same split.
- **Masking:** the IOP masks a CPU's source when it forwards it, until
  the driver says it's done, as Fen's interrupt mask does
  ([report 0036, 1.2](0036-report-fen.md#12-the-board)). The CPU's own
  masking (I and IPL) stays synchronous.
- **For Fen:** its devices would move behind the IOP, its timer from
  level 6 to 5, and its kernel's critical sections from interrupts off
  to `SPL #5`.

#### 7.4 Latency

| From | To | About |
|---|---|---|
| A doorbell | The IOP reading the ring | 1–3 µs: the current slice |
| A device's INT | The IOP seeing it | up to a tick, 10 µs |
| The IOP seeing an event | A CPU's request bit | 2–3 µs |
| A fast level | Its handler running, even over the kernel | the CPU's entry, perhaps 5–10 µs (*estimate*) |
| A slow level | A user-level driver running | 85–107 µs ([report 0020](0020-report-operating-system.md#interrupts-and-devices)'s 500–640 cycles at Fen's 6 MHz), up to about 1 ms while Fen's kernel runs ([report 0036](0036-report-fen.md#3-what-it-costs)) |
| An event | A Forth task on the IOP | up to the running task's next `pause` |

The rule for devices that follows: anything that can't wait about 1 ms
for a CPU is buffered in hardware or handled by the IOP; anything that
can't wait for a Forth task is native microcode; anything that can't
wait a tick has a FIFO, or a native job that polls it.

### 8. Booting the CPU

#### 8.1 What the CPU card provides

| | Chips | |
|---|---:|---|
| **A control register** among its registers: RUN, RESET (runs the reset routine), STEP (one microcycle, or to the end of the instruction), NMI; status: running, halted, at an instruction boundary | ~2 | [RFC 0037, 9](0037-rfc-system-and-io-bus.md#9-cpu-cards). At power-up RUN is off if the control store is SRAM, on if it's flash (a jumper). Its RESET is the warm reset of RFC 0037's reset levels, taken when the CPU's current transfer ends |
| **A slave port** into its RAM | (~12–15) | For DMA into its RAM, so not counted here. The IOP can load the boot program through it |
| **A write port into an SRAM control store** | ~14 | Each 64K × 16 SRAM is a 16-bit lane in a window among the card's registers, written (and read back, to verify) while RUN is off |

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
flash chips for the images, which live in the IOP's image flash instead.
So an SRAM control store costs about 6 chips more than the flash one
(10 SRAMs and the port's 14, against 18 flash ROMs), not about 15. In
return: 1.2 times the speed at chip level (0.82 s for the suite against
0.99 s) and a writable control store
([RFC 0024, open question 2](0024-rfc-faster-smaller.md#15-open-questions)).

#### 8.2 The sequence

1. **Power-up, or COLD:** everything resets. The arbiter grants position
   0, where the CPU card holds its CPU
   ([RFC 0037, 7](0037-rfc-system-and-io-bus.md#7-reset)).
2. **The IOP starts** at microaddress 0: it tests its SRAM, copies the
   Forth out of the image flash and starts the console task, which prints
   a banner. From here on it's Forth.
3. **The cards:** it loads the card table and the I/O bus's timing table
   from the flash, and probes each card the table lists with a harmless
   read, written so that a held value can't pass for an answer
   ([RFC 0037, 27](0037-rfc-system-and-io-bus.md#27-what-it-costs)).
4. **The control store:** it plays records of {bus address, count,
   halfwords} from the flash into the CPU card's window. Records skip
   what isn't used. The 1b's microcode is 3,507 microinstructions in
   4,096 slots, with a copy in the interrupt half of the address space
   and the fault entries: about 8K microinstructions in 8 lanes, plus the
   64K-entry decode table, about 130K halfwords. That takes about 35 ms
   at 7.6 MB/s, and all 640K halfwords 0.17 s.
5. **Verify,** if asked: read it back, the same time again.
6. **The boot program:** into the CPU's RAM at physical 0, where draft 2's
   vectors are ([RFC 0037, 5.1](0037-rfc-system-and-io-bus.md#51-addresses)),
   through its slave port. Without a slave port, into the shared RAM, for
   the CPU's reset routine to copy to 0 before the first fetch, a few
   microinstructions in its control store.
7. **Start:** RESET, then RUN.
8. **Service:** native jobs and Forth tasks
   ([6.4](#64-tasks-native-jobs-and-events)).

With a flash control store the IOP isn't needed to boot. It still loads
the boot program, and the CPU card's own boot ROM and its overlay at
reset (about 3 chips) can go.

#### 8.3 Where the images come from

- **Its image flash:** 1 MB for now (its size is to be confirmed,
  [section 5](#5-the-io-bus-side-and-the-devices-on-the-card)), for the
  Forth, the control store, and a boot program or a small operating
  system.
- **A CF card** on an I/O card: any size, read at 3–6 MB/s.
- **The serial line:** the monitor takes an image from the PC at 921,600
  baud, about 90 KB/s, by a native loop into the shared RAM. The 1b's
  microcode and decode table, about 260 KB, take about 3 s, and can then
  be written into the flash.
- **Ethernet,** later ([RFC 0009, section 4](0009-rfc-ideas-io.md#4-networking)).

### 9. Chips

| Block | Parts | Chips |
|---|---|---:|
| Microcode | 6 × SST39SF010A (64K × 48 bits) | 6 |
| Microinstruction register | 3 × 74ABT16823 | 3 |
| Sequencer, with the dispatch | 4 × 74F161 (uPC), 74F151 (condition), gates | 6 |
| Field decoders, with HOLD | 74F139, 2 × 74F138, a gate | 4 |
| Timing: phase, write strobe | 74ABT74, gates | 2 |
| ALU | 4 × 74F181, 74F182 | 5 |
| F and AC | 2 × 74ABT16823 | 2 |
| Constants, K ↔ R | 74ABT16245 | 1 |
| Carry | 74F74 | 1 |
| Registers and working memory | IS61C6416AL-12, BANK (74ABT574), X (74ABT16823) | 3 |
| Loop counter | 74F161 | 1 |
| Control register: session, native work waiting, spare | 74ABT273 | 1 |
| Swap register | 74ABT16823, inputs crossed | 1 |
| Bus addresses | AL, AHOUT, AH0, AH1: 4 × 74ABT16823 | 4 |
| Bus data | 74ABT16652 | 1 |
| Bridge, R ↔ T | 74ABT16245 | 1 |
| Bus control and state | 74ABT574, 2 for REQ, GNT and the transfer's state | 3 |
| Clock buffer | One part with specified skew (CDC341 class), as every card has | 1 |
| **Core** | | **46** |
| Stuck-transfer counter | | 2 |
| Slave side: three ranges' decode, address register, WAIT and T's sharing, the window's own logic | | ~10 |
| Doorbells | 2 × 74HC259, a multiplexer | ~3 |
| Shared RAM | 4 × AS6C4008-55; X onto its address, its page register, control | ~8 |
| I/O bus side | [RFC 0037, 22](0037-rfc-system-and-io-bus.md#22-the-io-processors-side) | ~15 |
| Event ports beyond the I/O side's INT port | | 2 |
| Image flash, with its page register | 2 × SST39SF040, a register | 3 |
| Console UART, with its oscillator | 16C550 | 2 |
| Timer | 82C54 | 1 |
| Ports, clock chip, watchdog | 74HCT574, 74HCT541, DS1302, 74HC123 | 4 |
| **The card** | | **about 95** |

Where it could shrink:

- **16-bit EPROMs** for the microcode, three 64K × 16 one-time
  programmable parts such as the AT27C1024: −3. A new chip for every
  microcode change, so only once the microcode settles. With the Forth
  in the image flash, it settles sooner than it would have.
- **No shared RAM,** keeping a memory card instead: −8 here, +28 there.
- **GALs** for the timing, decode and bus state: perhaps −8 to −10. Emily
  would rather not use them.
- **The ALU from parts still made** costs more, not less: 74F283 adders
  with XOR gates and multiplexers for the logic operations, about 12–16
  chips against 5. The 74F181 is new-old stock, the same question the CPU
  has ([RFC 0007, section 3](0007-rfc-ideas-microarchitecture.md#3-parts)).

## Part II: Discussion

### 10. What it's for, and precedents

- **Booting.** An SRAM control store is empty at power-up
  ([RFC 0024, section 5](0024-rfc-faster-smaller.md#5-faster-parts)), so
  the CPU can't start itself: something must fill up to 1.25 MB of
  microcode and decode table, load a program and start it. A flash
  control store needs only the program, and the boot ROM that RFC 0010
  overlays on low memory at reset
  ([RFC 0010, section 2](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system))
  can go.
- **I/O.** Every access the CPU makes to a simple card on RFC 0014's bus
  holds its microcycle for 880–960 ns
  ([report 0025, section 13](0025-report-draft-1b-system.md#13-what-a-bus-transfer-costs)),
  and every interrupt handed to a user-level driver costs 500–640 cycles
  ([report 0020](0020-report-operating-system.md#interrupts-and-devices)).
  Characters and polled disk sectors are where that adds up.
- **Copies:** disk sectors, network frames, pages for the operating
  system (zeroing is 4,619 of a demand-zero fault's 4,753 cycles,
  [report 0020](0020-report-operating-system.md#zeroing-and-copying)),
  graphics.
- **Everything else:** [section 13](#13-other-uses).

| Machine | Year | The other processor | What it did |
|---|---|---|---|
| CDC 6600 | 1964 | Ten peripheral processors sharing one datapath (the barrel) | All I/O, and the operating system's monitor; the CPU had no I/O instructions |
| IBM System/360 | 1964 | Channels | Ran channel programs, lists of commands, from main memory |
| Xerox Alto | 1973 | None: device tasks in the CPU's own microcode | The opposite way: one machine switching between microcode tasks |
| DEC KL10 | 1975 | A PDP-11 front end | Loaded the microcode, booted the machine, ran the console and slow devices |
| VAX-11/780 | 1977 | An LSI-11 console processor with a floppy drive | Loaded microcode into the control store, booted, gave the console |
| Intel 8089 | 1979 | An I/O processor chip beside the 8086 | Two DMA channels running channel programs from memory |
| Symbolics 3600 | 1983 | A 68000 front-end processor | Booted the machine, loaded its microcode, slow I/O and diagnostics |
| Sun workstations | 1989 | None: OpenBoot, a Forth in the boot ROM | Booted, probed the cards, ran the drivers each card carried as Forth bytecode (FCode) |

The IOP is the KL10's and the VAX's front end in its boot and console
jobs, the 8089 in its DMA job, and OpenBoot in its firmware. It is built
from TTL, since there are to be no microcontrollers in peripherals
([docs](../docs/README.md)); the front ends above were off-the-shelf
computers.

### 11. The DMA engine

**decided** (Emily, 2026-10-16). The evaluation behind it, kept from the
first version and brought up to date for the shared RAM:

#### 11.1 What there is to move

- **Devices:** disk sectors, Ethernet frames, terminal output (DH11-style
  output DMA, [RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)).
- **The operating system's pages:** zeroing, copy-on-write, swapping
  ([report 0020](0020-report-operating-system.md#zeroing-and-copying)).
- **Graphics:** fills and text in VRAM, from a stage-1 video card without
  a blitter ([RFC 0016, section 7](0016-rfc-video.md#7-blitter)).

#### 11.2 What the IOP does on the bus

Assumptions:

- a 60 ns bus clock;
- the memory card reads in 2 clocks and writes in 3
  ([report 0025](0025-report-draft-1b-system.md#13-what-a-bus-transfer-costs));
- a CPU card's slave port takes 3 clocks either way, one WAIT with 55 ns
  RAM, longer when it collides with the CPU;
- every 16 transfers the IOP lets go of the bus and takes about 6 clocks
  to have it back (a request on an idle bus takes 4).

| Transfer | Clocks per 16 transfers | Rate |
|---|---|---:|
| Copy, memory card to memory card, 16 bits | 8 × (2 + 3) + 6 = 46, per 16 bytes | 5.8 MB/s |
| Copy, memory card to the CPU's RAM | 8 × (2 + 3) + 6 = 46 | 5.8 MB/s |
| Copy, the CPU's RAM to its RAM | 8 × (3 + 3) + 6 = 54 | 4.9 MB/s |
| Copy, the shared RAM to or from the CPU's RAM: a local access and one bus transfer a halfword, 2 microinstructions | 16 × 4 + 6 = 70, per 32 bytes | 7.6 MB/s |
| Fill, the CPU's RAM | 16 × 3 + 6 = 54, per 32 bytes | 9.9 MB/s |
| Fill, a card without WAIT (VRAM's posted writes, when a slot is free) | 16 × 2 + 6 = 38 | 14 MB/s |
| Copy, 32-bit card to 32-bit card (+1 chip) | 46, per 32 bytes | 11.6 MB/s |
| Fill, 32 bits | 54, per 64 bytes | 19.8 MB/s |
| The image flash to the bus | 16 × 4 + 6 = 70, per 32 bytes | 7.6 MB/s |
| A CF card to a CPU's RAM, PIO mode 4 / mode 0: X holds the CF's register, one microinstruction a halfword | 16 × 5 + 6 = 86 / 16 × 10 + 6 = 166 | 6.2 / 3.2 MB/s, less the card's own wait per sector |
| A CF card to the shared RAM, PIO mode 4 / mode 0 | no bus time | 3–4 / 2 MB/s (*estimate*): X addresses both, so the loop reloads it every halfword |

With the shared RAM on its card, the memory card's rows are for a system
that keeps one. **Without the DMA parts** (one segment register, no loop
counter, one bus for R and T), a copy would take about 6
microinstructions a halfword, 2.5–4 MB/s (*estimate*); the four chips
buy about twice that.

#### 11.3 Against the CPU and the other ways

| How | Chips | Copy within the CPU's RAM | Copy across the bus | CPU time to copy a 4 KB page |
|---|---:|---:|---:|---:|
| The CPU, unrolled loop (report 0020's count, report 0025's 304 ns microcycle) | 0 | 1.4 MB/s | ~1 MB/s | 9,746 cycles |
| The CPU, `SAVE`/`RESTORE` through any register | microcode | 2.2 MB/s | ~1.2 MB/s | 6,184 cycles |
| The fast CPU of RFC 0024 (*estimate*) | 0 | ~3.5–5.5 MB/s | ~2 MB/s | the same cycles, ~2.5 times shorter |
| A microcoded channel in the CPU ([RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)) | ~5 | – | as fast as the device | for devices only: 5–7 cycles a word |
| RFC 0014's DMA card ([section 12](0014-rfc-system-bus.md#12-example-cards)) | ~34 | – | ~3–5 MB/s from the CF card | a request |
| Bus mastering on each device card | ~15–25 per device | – | – | a request |
| **The IOP** | **4 more** | **4.9 MB/s** | **5.8 MB/s (7.6 from the shared RAM, 11.6 at 32 bits)** | **a request, ~200–700 cycles** |

Across the bus the IOP is 5–6 times the CPU as built (10 times at 32
bits), and about 3 times the fast CPU. Within the CPU's own RAM it is
2–3.5 times the CPU as built and about level with the fast one. What it
always gives is the CPU's time back.

#### 11.4 What a request costs the CPU

- **Writing a descriptor:** about 8 stores, 20 cycles.
- **The doorbell:** one write, a few bus clocks.
- **The completion:** an interrupt, 150–250 cycles into the nucleus
  (like a preemption) or 500–640 to a user-level driver
  ([report 0020](0020-report-operating-system.md#interrupts-and-devices)).
  A completion can answer several requests.

So 200–700 cycles. The CPU copies at about 2.4 cycles a byte, so a
request pays from about 100–300 bytes up; smaller copies stay with the
CPU. **Latency:** the IOP sees the doorbell within about 3 µs (at its
next slice), reads a 16-byte descriptor in about 2 µs and posts the
completion in about 1 µs, so about 5 µs on top of the transfer.

#### 11.5 What it costs

- **Four chips,** and the overlapped bus timing of section 3.2, which is
  logic the IOP's stall control has anyway.
- **One engine for everything.** A device waits for the current 16
  transfers (about 3 µs) before the IOP looks at it, and throughput is
  shared between jobs, the Forth's included.
- **The bus.** The IOP holds it for up to 16 transfers at a time, so the
  CPU's own bus accesses can wait about 3 µs. Its instruction fetches
  are local and never wait.
- **The slave port** limits copies into and out of the CPU's RAM. With
  fast parts the CPU uses its RAM more of the time, and the slave port
  waits more (*estimate*; nothing measures it yet).
- **Its firmware is trusted:** a bug writes anywhere. The other side of
  that is protection in firmware: the IOP checks each request against
  windows the supervisor set ([7.2](#72-requests-and-windows)). As long as
  the IOP and the CPUs are the only bus masters, that does the job of
  the DMA window in the slave port, two comparators that
  [RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory) recommends
  (~3–4 chips).
- **No blitter.** Reading VRAM over the bus holds WAIT for 0.4–0.6 µs
  ([RFC 0016, 4.5](0016-rfc-video.md#45-how-the-cpu-reaches-it)), so a
  copy inside VRAM runs at about 3 MB/s at 16 bits and 6 at 32, against
  the blitter's 16–48. Fills and text work well enough.

What stays with the CPU: copies under a few hundred bytes, and copies
inside VRAM, which want RFC 0016's blitter if they matter.

### 12. Why Forth

#### 12.1 What it gives

- **Firmware that is mostly ordinary code.** The monitor, the drivers,
  the line discipline and the rings' control move out of microcode into
  a language that is much easier to write and debug. Microcode keeps the
  inner interpreter, the data-moving loops and anything with tight
  timing, perhaps 1–2K microinstructions (*estimate*): the interpreter
  and primitives 500–1,000, the native jobs the rest.
- **The console is the Forth,** interactive from the first day, for
  bring-up and debugging with the CPU halted or broken.
- **It changes in place.** The dictionary lives in the image flash, which
  the IOP can program, so most firmware changes need no programmer.
- **Tasks almost come free.** A task is a bank: switching is a load of
  BANK, with nothing to save but AC.
- **The CPU can teach it new tricks** at run time, through the kernel's
  ring.
- **It fits the job's history.** Chuck Moore wrote Forth around 1970 to
  control radio telescopes at the NRAO; Sun's OpenBoot (1989), later
  Open Firmware (IEEE 1275), put Forth in the boot ROM and drivers on the
  cards as Forth bytecode; the Novix NC4016 (1985) and the Harris
  RTX2000 (1988) ran Forth directly in hardware. This is the TTL,
  microcoded cousin.
- **It answers half of RFC 0005's open question,** "a Forth or BASIC, a
  likely program for this machine"
  ([RFC 0005, 1](0005-rfc-ideas-direction.md#1-direction-and-ambition)).
  A Forth for the main CPU could share most of the source.
- **Its caveat:** Forth trusts its programs. Code from user processes
  stays out; they get rings with windows instead.

#### 12.2 Its speed

About a million Forth words a second, roughly 3–10 times slower than
microcode for the same job. That's enough for what it does:

- **a character with echo and line editing** is about 30–60 words, so
  30–60 µs. Four lines typing flat out at 9,600 baud would take about a
  fifth of the IOP; ordinary typing, almost nothing. A native word for
  the common case would cut that if it ever matters;
- **a console command** is microseconds;
- **booting the CPU** is spent in native copies;
- **anything per byte at a high rate** is native by the rule of
  [7.4](#74-latency).

#### 12.3 Other ways to the same end

| Way | Chips | Effect | Status |
|---|---:|---|---|
| **Bit 15 picks a primitive or a colon definition,** with the dispatch of 3.3 | ~0–1 | NEXT is 2 microinstructions and a delay slot | **recommended** |
| Indirect threading: a code field in every word | 0 | A fetch more per word; no dispatch needed | **not recommended** |
| `execute` through a two-cell thread built in the task's registers, the word and a primitive that returns | 0 | Works if the real `ip` goes on the return stack, so that a nested `execute` can't overwrite it | **not recommended**: `nest-w` ([6.2](#62-the-inner-interpreter)) is plainer |
| A second memory pointer, Y, for `ip` or the stacks | +2–6, and a microinstruction bit | About 30% faster Forth | **not recommended**: speed isn't the goal |
| Carry in from the carry flag, through another repeated ALU code | a gate | Double-cell arithmetic about twice as fast | **optional** |
| A register machine's bytecode instead of Forth | 0 | 6–10 microinstructions an instruction; better for a C compiler | **not recommended**: Emily chose the Forth |
| The 1b's instruction set, interpreted | 0 | Shares the CPU's tools | **not recommended**: an instruction set of the IOP's own (Emily, 2026-10-16) |
| A Forth CPU in TTL, in the style of the J1 or the NC4016, instead of microcode | ~35–45 for its core | Forth 5–10 times faster | **not recommended**: copies would run at 1.5–3 MB/s, since the DMA job wants the horizontal machine's parallel address arithmetic and transfers |

### 13. Other uses

Ranked by value for the effort, highest first. "Forth" or "native" means
no chips beyond the card's.

| Use | What it takes | What it gives |
|---|---|---|
| **Boot** the CPU, a writable control store included | Forth, the CPU card's ports | Goal 2 |
| **A console monitor**, after the PDP-11's ODT and the VAX's console: examine and deposit anywhere on the bus, load images (binary, S-records), start, halt, step, dump and patch the control store. A key sequence returns the console from the CPU to the monitor, as ^P did on the VAX | Forth | Bring-up and debugging, with the CPU halted or broken |
| **Microcode development:** new CPU microcode from the PC, loaded and restarted in a few seconds, without a programmer | Forth | Makes RFC 0005's user-defined instructions and every microcode experiment cheap |
| **Power-on self test:** its own SRAM, the shared RAM, the cards in the card table, memory tests | Forth | A machine that says what's wrong with it |
| **Terminal lines** with line discipline: echo, erase, line editing, ^C, flow control; the CPU gets a line per interrupt | Forth, a serial I/O card | At 9,600 baud an interrupt per character takes 17% of the machine per line (report 0020); per line, under 1% for four busy lines. RFC 0009's intelligent terminal multiplexer, without the microcontroller it rejected |
| **The disk:** CF sectors into a CPU's RAM at 3–6 MB/s or into the shared RAM at 2–4, queued, with read-ahead and a buffer cache in the shared RAM | Native and Forth, a CF I/O card (1 chip) | 10–20 times the CPU's polled rate, and none of its time |
| **Pages for the operating system:** zero free pages in the background, copy for copy-on-write and spawn, swap to the shared RAM or the CF card | Native | A demand-zero fault in ~130 cycles instead of 4,753; a 64 KB copy in 13 ms of the IOP's time instead of 52 ms of the CPU's |
| **Keyboard and mouse:** PS/2 scan codes turned into characters or events | Forth, a PS/2 I/O card | |
| **The front panel:** lights and switches through shift registers on the panel; examine, deposit, halt, run and step through the bus and the control register | The ports | Works when the CPU is wedged |
| **Ethernet frames:** copied between the MAC card's packet buffer and memory, the descriptor rings run by firmware | Native and Forth, with the MAC card | The MAC card needs no bus mastering; a full frame in ~0.3 ms instead of ~1.2 ms of the CPU's |
| **Text on the screen:** glyphs from a font in its SRAM drawn into VRAM, about 30 µs each at 8 bits (the CPU: ~130 µs, the blitter: ~12 µs) | Native, with a video card | Boot messages and a console before the CPU runs |
| **Fills in VRAM:** clearing 640 × 480 at 8 bits in ~25 ms (~15 at 32 bits; the CPU: 154 ms, the blitter: 10 ms) | Native | A colour GUI's fills without the blitter |
| **Copy and checksum** in one pass, for TCP/IP | Native: a third microinstruction per halfword | About 4 MB/s, checksummed |
| **Watchdogs:** NMI or reset a CPU if its operating system stops checking in; its own hardware watchdog behind it | Forth | |
| **Boot the other CPUs** of a multiprocessor: load their RAM, release their resets | Forth | |
| **Scripts from the CPU:** Forth source the kernel sends, compiled and run | Forth | New I/O jobs without new firmware |
| **A RAM disk or swap** in the shared RAM | Native | Faster than the CF card, and survives a warm reset |
| **Network boot,** once Ethernet works | Forth | Images from the PC without the serial line |
| **Sound:** samples from a ring to a DAC on an I/O card, 8–22 kHz | Native, a sound I/O card | A few microinstructions a sample |
| **Profiling the CPU:** sample the PC at, say, 10 kHz into a histogram | A PC sample register on the CPU card, ~2 chips | Where the time goes, without instrumenting |
| **A flight recorder:** bus errors, interrupts and console output in a ring in the shared RAM, kept over a warm reset | Forth | |
| **Test runs on the CPU:** load a program, run it, compare memory | Forth | A hardware regression harness |
| **Memory testing** in idle time | Native | Bad memory found before it corrupts anything |
| **Drivers on the I/O cards** as Forth in a small ROM on each, read at boot, as OpenBoot's FCode | a ROM per card | Self-describing cards, if ever wanted; **optional** |

### 14. Alternatives

| Design | Chips | Boots a WCS | Programmable | Copies | Status |
|---|---:|---|---|---:|---|
| A loader on the CPU card ([RFC 0024](0024-rfc-faster-smaller.md#5-faster-parts)) | ~24, on the CPU card | yes | no | – | the alternative for booting alone, before the IOP was decided |
| A boot sequencer card: plays records of bus writes from flash, no ALU | ~25 | yes | no | from flash only | **not recommended**: a card for one job |
| **The IOP** | ~46 + its card | yes | yes, in Forth | 5–6 MB/s | **recommended** |
| A microprocessor (a 68000) with a bus bridge, flash and RAM | ~20–25 | yes | yes | ~2–3 MB/s | **not recommended**: it is what the decision against microcontrollers in peripherals rules out in spirit; listed for its chip count |
| A barrel of 8 virtual I/O processors (RFC 0009, the CDC 6600's) | ~60–100 | yes | yes | ÷ 8 | **not recommended**: see below |
| **Hardware tasks** in the IOP, as the Alto's microcode tasks: a uPC per task in a 16-word RAM, a priority encoder of the event lines, a switch where the TASK bit allows | +~6–8 | | | the same | **open**, later: devices served at once, without the tick |
| **A one-clock microcycle,** with the microcode copied into fast SRAM at reset | +~4 | | | the same: copies are bound by the bus | **not recommended**: a register read through the ALU takes 51–56 ns, nearly the whole 60 ns clock, so it would also need the register file pipelined |
| **A Gigatron-style 8-bit core** (one ROM word per instruction, a decoder of a few gates) with the same bus interface | ~40 | yes | yes | ~1.4 MB/s | **not recommended**: 16-bit address arithmetic in 8-bit steps makes it no faster at copying than the CPU |

- **Against the barrel:**
  - **It divides the copy by its number of threads.** The copy loop runs
    one microinstruction per transfer, so it is bound by the bus. In a
    barrel of N it gets every Nth cycle: 1.5 MB/s with 4 threads, 0.7
    with 8, no faster than the CPU copying for itself.
  - **The 6600's reason doesn't apply.** Its barrel hid a memory about 10
    times slower than its logic. The IOP's transfer already fits its
    microcycle and overlaps the next one.
  - **Every register outside the SRAM needs N copies:** the uPC, AC, X,
    AH0, AH1, LC, BANK and the carry, about 100 bits, so about 15–25
    chips more for 4 threads.
  - **Its latency isn't needed:** 0.5–1 µs against a tick of 10 µs, when
    the CPU's side takes 100 µs and more ([7.4](#74-latency)).
- **What the barrel has that is worth having** is its firmware model: one
  plain program per device. The Forth's tasks give that now, and
  hardware tasks would make them prompt, for about 6–8 chips. The TASK
  bit is reserved so that they can come later as a board change, not a
  new microcode format. The Alto's rule keeps the datapath as it is: a
  switch happens only where nothing outside the bank is live, which in
  the Forth is `pause`, and in a copy the end of a slice.

Two smaller choices inside the design:

- **The ALU:** the 74F181 (5 chips, new-old stock) against adders still
  made (12–16). **open**, with the CPU's.
- **The register file in flip-flops** (four 74ABT16823 registers with
  their outputs on R) instead of the SRAM: no strobe timing and no need
  for BCLK's falling edge, for 4 more chips and 4 registers instead of
  64 per bank, and no Forth in it. **not recommended**.

### 15. What it costs and saves

The IOP is decided, so this is for the record: against a system with the
same things on RFC 0014's bus and no IOP (*estimates*):

| | Without the IOP | With it | From |
|---|---:|---:|---|
| The memory card | 31 | – (the shared RAM, in the IOP's card) | [report 0025](0025-report-draft-1b-system.md#11-chips) |
| The I/O card: UART, timer, CF and its bus glue | 16 | I/O cards: a CF card 1, two serial lines 3–4 | report 0025, [RFC 0037, 21](0037-rfc-system-and-io-bus.md#21-electrical-rules-and-cards) |
| The CPU card's boot ROM and its overlay at reset | ~3 | – | [RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system) |
| Filling an SRAM control store | ~22 and 1–3 flash | ~14 (the write port) | [RFC 0024](0024-rfc-faster-smaller.md#5-faster-parts) |
| DMA: RFC 0014's card, or bus mastering on the disk and Ethernet cards | ~34 | – | [RFC 0014](0014-rfc-system-bus.md#12-example-cards) |
| The DMA window in the slave port | ~3–4 | – | [RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory) |
| PS/2 keyboard and mouse | ~8 | a PS/2 I/O card, ~3–4 | [RFC 0009](0009-rfc-ideas-io.md#1-io) |
| The IOP's card | – | ~95 | |
| **Total** | **~120** | **~120** | |

About even in chips, and the IOP adds the Forth monitor, the line
discipline, DMA for every device, the window, interrupt routing and the
rest of section 13. The backplane's saving (51 chips to about 10) is
RFC 0037's, from moving the slow devices to the I/O bus.

### 16. Stages, and simulate first

| Stage | The IOP's card | It gives | The CPU card needs |
|---|---|---|---|
| 1 | The core, the console UART, the image flash, the timer; microcode: the interpreter and primitives; Forth: the monitor and the loader | Booting from flash or serial; examine, deposit, step | The control register; a slave port, or the shared RAM's way round it; the write port for an SRAM control store |
| 2 | The shared RAM, the slave side and the doorbells; rings, copies and fills; the I/O bus side with a CF card | The operating system's disk and pages; slow RAM | The slave port |
| 3 | The window; serial and PS/2 I/O cards; the line discipline; routing events, slow and fast | Terminals, keyboard, mouse, interrupts | The interrupt request register |
| 4 | Frames for the Ethernet card; text and fills for the video card | The network and the screen | |
| Later | Hardware tasks; the 32-bit paths | | |

**Simulate first, recommended:**

1. **A model of the IOP** at microinstruction level, clocked by the bus
   clock, in Rust as RFC 0015 asks of engines, in the system model Fen
   runs on (`studies/fen`), with the device models `infra/devices`
   already has: the UART, the CF card and the timer.
2. **Firmware against it:** the microassembler and the interpreter's
   primitives, then the Forth's metacompiler, the monitor and the loader,
   then the rings, copies and the CF card.
3. **Measure** what this RFC estimates: the Forth's speed, the tick's
   cost, the copy rates on a model of the bus, the request costs with
   Fen's kernel, the firmware's size.
4. **Then the netlist:** the IOP's card in the chip-level simulator on
   the v1b_system backplane, booting the 1b CPU card with a control
   register, a slave port and a write port into an SRAM control store
   added.

### 17. Against RFC 0009

How this RFC stands to the ideas in
[RFC 0009, section 2](0009-rfc-ideas-io.md#2-channels-and-dma) and
section 1:

| RFC 0009 | Here |
|---|---|
| A block I/O instruction in microcode (open) | Still worth having for the small copies that stay with the CPU |
| A microcoded channel in the CPU, recommended first (~5 chips) | The IOP does that job without the CPU's cycles |
| Cycle-stealing DMA, ~15–20 chips per channel | Replaced: the IOP is every device's DMA |
| A DMA card, 8 channels, ~34 chips | The IOP is that card, programmable |
| An intelligent terminal multiplexer: hardly needed with FIFO UARTs; with a microcontroller, rejected | The IOP does it in TTL and Forth, for the price of a serial I/O card |
| A CDC 6600-style barrel, ~60–100 chips | Not recommended; the Forth's tasks give its firmware model, hardware tasks its promptness |
| PS/2, ~4 chips per port | A PS/2 I/O card, decoded in Forth |
| A timer for a tickless kernel on the CPU card, ~4–6 chips | Stays on the CPU card (Fen's); the IOP has its own |
| The front panel through the CPU's microcode, recommended | An alternative: the panel on the IOP's ports |
| Ethernet: later, DMA as a bus master with LANCE-style rings | The MAC card stays a slave; the IOP runs the rings |
| Reset levels | RFC 0037's: the IOP's watchdog asserts COLD, and the IOP asserts RESET |
| The 82C37, rejected | Stays rejected |

### 18. Open questions

For Emily:

1. **Forth as the IOP's firmware** (recommended), with native microcode
   for the interpreter, the primitives and everything that moves data?
2. **The core's changes for it:** the dispatch on bit 15, HOLD, the swap
   register, the banks at the top of the SRAM (recommended, about 2
   chips)? And the optional shift register and carry in from the flag?
3. **The shared RAM** on the IOP's card, 2 MB at 16 bits, instead of a
   memory card (recommended)? And space on the card for more of it,
   up to 8 MB, as Emily proposed (open, [4.3](#43-the-shared-ram))?
4. **Rings in the shared RAM** (recommended), rather than in a CPU's RAM?
5. **Slow and fast interrupts:** levels 1–5 slow and batched, 6–8 fast
   with one source each; the kernel's critical sections at `SPL #5`
   (recommended)? Or more fast levels, or fewer?
6. **Polling the INT lines at a tick** (recommended: no chips, 5–10% of
   the IOP), or detecting changes in hardware (about 4 chips)?
7. **The status block in the shared RAM,** rather than a register?
8. **The TASK bit reserved** for hardware tasks later (recommended)?
9. **The ALU:** the 74F181 (new-old stock) or adders still made, 7–11
   chips more? The CPU has the same question.
10. **Its microcode** in 8-bit flash, reprogrammable off the board, or in
    16-bit one-time-programmable EPROMs, 3 chips fewer?
11. **The 32-bit paths,** on the bus (one chip) and in the shared RAM,
    later?
12. **The card's size:** about 95 chips, one full 6U card or two
    positions?
13. **The control store in SRAM:** with the IOP it costs about 6 chips
    more on the CPU card than flash, instead of about 15 (RFC 0024, open
    question 2).
14. **The image flash's size:** 1 MB, or more? To be confirmed, once
    draft 2's control store and the images it should hold are known.
