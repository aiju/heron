---
number: 37
type: rfc
title: The system bus and the I/O bus
status: open
date: 2026-10-16
context:
  studies: [v1b_system, bus_si]
  commit: 8a3b775
depends-on: [14, 22, 25, 27, 29]
---

# RFC 0037: The system bus and the I/O bus

A proposal for two buses in place of [RFC 0014](0014-rfc-system-bus.md)'s
one:

- **the system bus,** a plainer synchronous backplane for a few fast
  cards: realistically three or four, such as the main CPU, the I/O
  processor and video;
- **the I/O bus,** the I/O processor's own bus brought out to a small
  backplane of simple cards: serial lines, disks, sound, ports and
  experiments.

It follows from two decisions (Emily, 2026-10-16): the I/O processor of
[RFC 0027](0027-rfc-io-coprocessor.md) is part of every Heron, and it is
the system's DMA engine. Once the slow devices leave the system bus, most
of what RFC 0014 added for them can go: the class straps, SEL, RDY, DPH,
BERR, the bus monitor and the card IDs. With so few cards, so can the
slots in the address: each card answers fixed ranges from a static map.

Three parts:

- **[Part I](#part-i-the-system-bus)** specifies the system bus, to be
  read on its own by someone designing a card or the backplane.
- **[Part II](#part-ii-the-io-bus)** specifies the I/O bus.
- **[Part III](#part-iii-discussion)** gives the reasons, what changes
  against RFC 0014 and draft 2's system architecture
  ([RFC 0029](0029-rfc-draft-2-system.md)), the alternatives, and the
  open questions.

If Emily accepts it, RFC 0014 becomes obsolete, superseded by this one.

Statuses: **decided** (Emily chose it), **open**, **optional**, and
**not recommended**. Anything in Parts I and II without a status is
recommended. Chip counts are estimates, not from a netlist; delays are
worst-case datasheet figures from the repository's timing data, with
[report 0022](0022-report-bus-si-revised.md)'s 13 ns of settling and
2.5 ns of skew.

## Contents

- [Part I: The system bus](#part-i-the-system-bus)
  1. [Overview](#1-overview)
  2. [Cards and the backplane](#2-cards-and-the-backplane)
  3. [Signals](#3-signals)
  4. [Clock and timing](#4-clock-and-timing)
  5. [Transfers](#5-transfers)
  6. [Bus mastering](#6-bus-mastering)
  7. [Reset](#7-reset)
  8. [Interrupts](#8-interrupts)
  9. [CPU cards](#9-cpu-cards)
  10. [Electrical rules](#10-electrical-rules)
  11. [The backplane's logic](#11-the-backplanes-logic)
- [Part II: The I/O bus](#part-ii-the-io-bus)
  12. [Overview](#12-overview)
  13. [Cards and the I/O backplane](#13-cards-and-the-io-backplane)
  14. [Signals](#14-signals)
  15. [Devices and addresses](#15-devices-and-addresses)
  16. [The access](#16-the-access)
  17. [The timing table](#17-the-timing-table)
  18. [WAIT](#18-wait)
  19. [Interrupts, reset and clocks](#19-interrupts-reset-and-clocks)
  20. [The window from the system bus](#20-the-window-from-the-system-bus)
  21. [Electrical rules and cards](#21-electrical-rules-and-cards)
  22. [The I/O processor's side](#22-the-io-processors-side)
- [Part III: Discussion](#part-iii-discussion)
  23. [Why two buses](#23-why-two-buses)
  24. [Against RFC 0014](#24-against-rfc-0014)
  25. [Decisions this asks for](#25-decisions-this-asks-for)
  26. [Chips](#26-chips)
  27. [What it costs](#27-what-it-costs)
  28. [Fitting draft 2](#28-fitting-draft-2)
  29. [Alternatives](#29-alternatives)
  30. [Still to check](#30-still-to-check)
  31. [Open questions](#31-open-questions)
  32. [Next steps](#32-next-steps)

## Part I: The system bus

### 1. Overview

| | |
|---|---|
| Timing | **Synchronous**: one bus clock, BCLK. Every signal changes just after a rising edge and is sampled at a later one. **decided** |
| Bus clock | Period T chosen when the system is built: the main CPU card's master clock divided by N. Every card works at 60 ns and at any longer period. Working value 60 ns |
| Address | 32 bits. **decided**. A static map, all below `0x8000_0000`, inside draft 2's supervisor window ([5.1](#51-addresses)): seven regions of memory, 256 MB each, then 16 MB of registers for each region's card and the I/O bus's window. The address doesn't carry a slot |
| Cards | A few fast cards, realistically 3–4: 16-bit on P1, 32-bit on P1 and P2. A card compares the top address bits with its own base. No class straps |
| Positions | Up to 8 on the backplane. A card may be two positions wide and connect to one |
| Transfers | An address clock and one data clock, 2 clocks in all, unless the addressed card adds data clocks with WAIT |
| The end of a transfer | The first data clock without WAIT. There are no RDY, DPH or BERR lines |
| An unused address | Nothing answers: the transfer ends after one data clock, and a read returns whatever the data lines last held |
| Bus mastering | Master positions 0–3, a central arbiter on the backplane, withdraw then grant, fixed priority |
| Bursts | None. **decided** |
| Interrupts | Cards signal the I/O processor on ATN0–ATN3. CPUs are interrupted by writes to a register on their card |
| Reset | COLD resets everything; RESET everything but the I/O processor |
| Backplane | Clock drivers, the power-on reset and the arbiter: about 10 chips |
| Slow devices | On the I/O bus ([Part II](#part-ii-the-io-bus)), not here |

Peak rates:

| | T = 60 ns | T = 80 ns |
|---|---:|---:|
| A transfer, no WAIT | 120 ns | 160 ns |
| 16-bit transfers | 16.7 MB/s | 12.5 MB/s |
| 32-bit transfers | 33 MB/s | 25 MB/s |

### 2. Cards and the backplane

**Every card is a slave.** Its slave side must:

- register, at the end of every address clock, whether the address is in
  one of its ranges, decided from at most 8 of A31–A24 ([5.1](#51-addresses)),
  with the address bits, byte enables and WRITE it needs;
- decide in that same address clock whether it will need more than one
  data clock, and if so drive WAIT from the start of the first data clock
  ([5.4](#54-wait));
- in a read, drive D through the data phase; in a write, take D at the
  end, or at the end of any data clock in which it holds WAIT;
- if it is a 32-bit card, drive W32 ([5.5](#55-data-width-and-byte-lanes));
- let go of D, WAIT and W32 at the end, as [5.3](#53-the-end-of-a-transfer-and-turnaround)
  says;
- use fast parts at its bus interface: 74ABT, or 74FCT-T.

**A master** (a CPU, the I/O processor) must also:

- sit in a master position and follow [section 6](#6-bus-mastering);
- drive the owner's lines from its address clock to the end of the
  transfer;
- take read data at the end of the data phase's last clock;
- split a word into two halfword transfers when W32 is missing;
- use bus-hold transceivers (74ABTH), which keep the bus's 3-state lines
  from drifting while nobody drives them.

**The backplane:**

- has up to 8 positions at a 20.32 mm pitch. A card may be two positions
  wide and connect to one; a position no card connects to needs no
  connector, only a card guide;
- distributes BCLK, one trace per position;
- makes the power-on reset and drives COLD and RESET ([section 7](#7-reset));
- arbitrates between the master positions.

Nothing on the backplane takes part in a transfer: it doesn't decode
addresses, time transfers or report errors.

### 3. Signals

Control signals are active low, as in RFC 0014. **Topology:** *bused*
runs past every position; *radial* is a trace per position to the
backplane's logic, on the same pin at every position.
**Drive types:** *owner*, driven by the master holding GNT; *3-state*,
driven by the owner or, for read data, the addressed card; *shared*,
driven only by the addressed card, actively both ways, and held inactive
by a pull-up otherwise; *OC*, open collector with a pull-up on the
backplane.

#### P1: the 16-bit bus

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D0–D15 | 16 | bused, 3-state | the owner in a write, the addressed card in a read | data |
| A1–A31 | 31 | bused, owner | the owner | address |
| BE0, BE1 | 2 | bused, owner | the owner | byte enables |
| START | 1 | bused, owner | the owner | asserted in the address clock |
| WRITE | 1 | bused, owner | the owner | a write, from the address clock to the end |
| LOCK | 1 | bused, owner | the owner | keep the bus for a locked sequence ([6.4](#64-locked-sequences)) |
| WAIT | 1 | bused, shared | the addressed card | add a data clock |
| BCLK | 1 | radial | the backplane | bus clock |
| REQ, GNT | 2 | radial, master positions only | the master, the backplane | request and grant |
| COLD | 1 | bused, OC, slow edges | the backplane's power-on reset and button, the I/O processor's watchdog | reset everything, the I/O processor included |
| RESET | 1 | bused, OC, slow edges | the backplane (with COLD), the I/O processor | reset every card but the I/O processor |
| ATN0–ATN3 | 4 | bused, OC | any card | attention: a request to the I/O processor |
| reserved | 8 | | | an answer line ([29](#29-alternatives)), a higher supply voltage, more ATN lines |
| +5 V, ground | 26 | | | |

#### P2: the upper half

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D16–D31 | 16 | bused, 3-state | as D0–D15 | the upper halfword of a word transfer |
| BE2, BE3 | 2 | bused, owner | the owner | byte enables of the upper halfword, in word transfers only |
| W32 | 1 | bused, shared | the addressed card | it is a 32-bit card |
| CLKSRC | 1 | position 0 only | the main CPU card | the clock into the backplane's clock driver |
| +5 V, ground | 16 | | | |
| user-defined | 60 | | | private links between neighbouring cards |

#### Pin rules

- BCLK, COLD and RESET each have a ground pin on both sides, in the row
  and across rows. Where those pins really sit needs a careful physical
  review ([section 30](#30-still-to-check)).
- Power and ground are spread along the connector, not grouped.
- The same signal is on the same pin at every position, radial ones
  included.

The pin-by-pin assignment is still to do, keeping report 0022's
reference assignment's spread of returns.

### 4. Clock and timing

- **The period** is chosen when the system is built: the main CPU card's
  50 MHz master clock divided by N, so N = 3, 4 or 5 gives 60, 80 or
  100 ns. Every card must work at 60 ns and at any longer period. The
  shortest usable period is about 50 ns, set by a card's address comparison
  ([section 30](#30-still-to-check)).
- **The source:** the main CPU card sends its divided clock on CLKSRC, in
  position 0, to the backplane's clock driver, as report 0025 built it. An
  oscillator on the backplane instead is **open**: it would cost each CPU
  card a synchroniser.
- **Duty cycle:** BCLK is high for at least 15 ns and low for at least
  10 ns of each period, which the I/O processor's register file needs
  ([RFC 0027, 3.2](0027-rfc-io-coprocessor.md#32-the-microcycle)). The
  CPU card's divide-by-three gives 20 and 40 ns.
- **Distribution:** a clock driver with specified part-to-part skew
  (CDC341 or FCT807 class) on the backplane drives each position's BCLK
  through 56–68 Ω. Every card clocks its bus logic from its own BCLK pin
  through exactly one buffer of the same class.
- **Card-edge timing,** measured at the card's connector from BCLK at its
  pin:

  | Parameter | Meaning | Value |
  |---|---|---:|
  | T<sub>co</sub> max | outputs valid | ≤ 16 ns |
  | T<sub>co</sub> min | earliest change of an output | ≥ 3 ns |
  | T<sub>su</sub> | input setup | ≤ 8 ns |
  | T<sub>h</sub> | input hold | ≤ 1 ns |
  | T<sub>skew</sub> | between any two cards' BCLK, as their registers see it | ≤ 2.5 ns |

  They must satisfy T<sub>co</sub> max + 13 ns of settling +
  T<sub>su</sub> + T<sub>skew</sub> ≤ T, and T<sub>co</sub> min ≥
  T<sub>h</sub> + T<sub>skew</sub>.

### 5. Transfers

#### 5.1 Addresses

- **Each card answers a fixed range** of addresses, by its design or by
  jumpers. The bus doesn't divide the address space into slots, and a
  card's address doesn't depend on where it is plugged in.
- **Whether a card is addressed** is decided from A31 down: at least
  A31–A28, at most A31–A24. Eight bits are what one 74F521 compares in
  time for the card to raise WAIT ([section 30](#30-still-to-check)), so
  ranges come in steps of 16 MB. The bits below are decoded inside the
  range afterwards, with no hurry.
- **No two cards' ranges overlap.** Nothing on the bus prevents it: two
  cards answering one read both drive D. With three or four cards a
  static map makes it easy.
- **Heron's map,** a convention rather than a rule, puts every card
  below `0x8000_0000`, where RFC 0029's supervisor window reaches it: the
  kernel sees physical address p at `0x8000_0000` + p. Below
  `0x7000_0000` are seven regions of memory, 256 MB each; above it
  are registers, 16 MB for each region's card, and the I/O bus's window
  (Emily, 2026-10-16):

  | Physical | Kernel | What |
  |---|---|---|
  | `0x0000_0000`–`0x3FFF_FFFF` | `0x8000_0000` | regions 0–3: CPU or memory cards, the main CPU card in region 0 |
  | `0x4000_0000`–`0x4FFF_FFFF` | `0xC000_0000` | region 4: the I/O processor's shared RAM, if it has one ([section 26](#26-chips)) |
  | `0x5000_0000`–`0x5FFF_FFFF` | `0xD000_0000` | region 5: a second video card, or another fast card that is neither video nor a CPU (Emily, 2026-10-16) |
  | `0x6000_0000`–`0x6FFF_FFFF` | `0xE000_0000` | region 6: video |
  | `0x7000_0000`–`0x76FF_FFFF` | `0xF000_0000` | registers: those of the card in region N at `0x7N00_0000` |
  | `0x7700_0000`–`0x7EFF_FFFF` | `0xF700_0000` | free |
  | `0x7F00_0000`–`0x7FFF_FFFF` | `0xFF00_0000` | the I/O bus's window: register RRRR of device S at `0x7F0S_RRRR` ([section 20](#20-the-window-from-the-system-bus)) |
  | `0x8000_0000` and up | – | unused: outside the supervisor window |

  - **A card's region number N** sets both its ranges, from one set of
    jumpers: its memory at N × 256 MB, its registers at `0x7N00_0000`.
    That is two comparisons, a 74F521 each; a card with only one kind
    needs one. The I/O processor's card answers three: its RAM, its
    registers at `0x7400_0000` and the window.
  - **To the kernel,** everything from `0xF000_0000` up is a register
    and everything below it memory.
  - **The main CPU card's registers** at `0x7000_0000` are Fen's timer,
    board information and interrupt mask, and the control and interrupt
    request registers of [section 9](#9-cpu-cards).
  - **The I/O processor's registers** are 16 doorbells, one for each
    client of its rings; its status is in its shared RAM
    ([RFC 0027, 4.4](0027-rfc-io-coprocessor.md#44-registers-for-the-cpus)). Requests,
    replies and the ring of events ([section 8](#8-interrupts)) are in
    memory.
  - **The CPU's RAM is at 0** because draft 2's reset and exception
    vectors are at `0x8000_0000` and up, physical 0
    ([RFC 0029, 6](0029-rfc-draft-2-system.md#6-exceptions)): they and
    the kernel want the fast RAM. The I/O processor writes the boot
    image there while it holds the CPU in reset.

- **The main CPU** sits in position 0, the lowest-priority master
  position, wherever its range is.

#### 5.2 The phases of a transfer

| Phase | Clocks | The owner drives | The addressed card drives |
|---|---|---|---|
| Address | 1 | A, BE, START, WRITE | nothing: it registers whether it is addressed, the address, BE and WRITE |
| Data | 1, more while the card holds WAIT | A, BE, WRITE; D in a write | D in a read; WAIT, if it may need more clocks; W32, if it is a 32-bit card |

- **The data phase** is the clocks after an address clock, up to and
  including the first clock in which WAIT is inactive. Every card that
  takes part works it out from START and WAIT; so does the arbiter. No
  line marks it.
- **Read data:** the master takes D at the end of the data phase's last
  clock.
- **Write data:** the master drives D through the whole data phase. The
  card takes it at the end of the last data clock, or at the end of an
  earlier one in which it holds WAIT, as report 0025's memory card writes
  its SRAM in its WAIT clock.

#### 5.3 The end of a transfer, and turnaround

- **The end:** the end of the first data clock in which WAIT is
  inactive. The master, the addressed card and the arbiter all see it.
- **Back to back:** the owner may start its next address clock in the
  clock right after the end.
- **D** is driven only in data clocks: by the card in a read, the owner
  in a write. Both let go just after the end, so the next address clock
  has nobody driving D.
- **WAIT** is driven only by the addressed card, from its first data
  clock to the end, inactive in the last clock, and let go just after
  the end. The pull-up holds it inactive until the next card drives it.
  A card that never needs WAIT never drives it.
- **W32** is driven by the addressed 32-bit card, asserted, through its
  data phase, then *inactive* through the clock after the end (the next
  transfer's address clock, when nobody else drives it), and then let
  go. A pull-up alone would take microseconds to bring it back.
- **Every other line** has one driver at a time: the owner's lines as
  [section 6](#6-bus-mastering) says, the backplane's always.

#### 5.4 WAIT

- **What it's for:** a CPU card's slave port while the CPU uses its RAM;
  slow memory; a posted write still going; reading VRAM; the I/O
  processor's window into the I/O bus ([section 20](#20-the-window-from-the-system-bus)).
- **Deciding it:** a card raises WAIT from its own registered decode of
  the address clock. Report 0025 found that a fast card can't decide it
  any later.
- **The bound:** no card holds WAIT for more than 255 data clocks in a
  row. A longer one is a fault ([5.6](#56-unused-addresses-and-faults)).

#### 5.5 Data width and byte lanes

- **Halfwords and bytes always travel on D0–D15.** A1 picks the
  halfword, BE0 and BE1 its bytes.
- **A word** travels on D0–D31 in one transfer when the addressed card
  drives W32. A1 is 0, BE0–BE3 pick the bytes; bytes 0–1 are on D0–D15,
  bytes 2–3 on D16–D31.
- **A word to a 16-bit card:** W32 stays inactive, so the master knows
  only D0–D15 moved, and repeats the upper half at A1 = 1, on D0–D15.
- **What each kind of card needs:** a 16-bit card uses P1 only; a 32-bit
  card puts its upper half on D16–D31 for words and on D0–D15 for
  halfwords and bytes at A1 = 1 (a swap transceiver); a 32-bit master
  does the same for its own upper half; a 16-bit master uses P1 only,
  with two transfers per word.
- BE2 and BE3 are asserted only in word transfers; their pull-ups keep
  them inactive while a P1-only master owns the bus.

#### 5.6 Unused addresses and faults

- **An address no card decodes,** or one inside a card's range that the
  card ignores: nothing drives WAIT, so the transfer ends after one data
  clock. A write is lost. A read returns whatever the data lines last
  held, kept there by the masters' bus-hold transceivers. W32 stays
  inactive. Nothing is signalled. Whether an unanswered access should be
  a fault, through an answer line, is **open**
  ([section 28](#28-fitting-draft-2), [29](#29-alternatives)).
- **Faults inside a card** (a parity error, an impossible request) are
  the card's business: it signals the I/O processor on an ATN line.
- **A stuck transfer:** the I/O processor counts consecutive data
  clocks. At 256 it asserts RESET, a system reset, and records which of
  its own transfers, if any, was under way ([7](#7-reset)).

### 6. Bus mastering

#### 6.1 Master positions

- **Positions 0–3** are master positions, with REQ and GNT; the others
  carry no REQ or GNT. **open**: four is a guess at "the main CPU, the
  I/O processor and two more CPUs".
- **Priority** is fixed: the higher position first. Position 0, the main
  CPU, is lowest. The I/O processor goes in position 3.

#### 6.2 The arbiter

- **Requests and grants:** each master position has its own REQ and GNT;
  the backplane pulls REQ up, so an empty position never requests, and registers
  it, so a request on an idle bus takes 4 clocks to its first address
  clock (report 0025). At most one GNT is asserted at a time.
- **What it knows:** at each edge it samples REQ, START, WAIT and LOCK,
  and so knows whether a transfer is under way.
- **Parking:** when nobody requests, GNT goes to position 0 or stays there.
- **Switching** from owner P to master Q (the highest requesting, or
  position 0 for parking), when LOCK isn't asserted and either Q has the
  higher priority or P isn't requesting:
  1. **withdraw:** deassert P's GNT just after an edge E;
  2. **wait** until the first edge, from E + 1 on, at which no transfer
     is under way (P may have started one more just after E);
  3. **grant:** assert Q's GNT just after that edge.

  So GNT is only asserted on an idle bus that its last owner is letting
  go of.

#### 6.3 Masters

As RFC 0014, section 7.2:

- **Request:** assert REQ while wanting the bus. The main CPU needn't
  while the bus is parked on it.
- **Start** an address clock just after any edge at which GNT is sampled
  asserted, once the master's own previous transfer has ended.
- **Drive** the owner's lines from just after the first edge at which GNT
  is sampled, for as long as it is held.
- **Let go** just after the first edge at which GNT is sampled deasserted
  with no transfer of its own under way, or after that transfer's end.
- **Courtesy:** a master other than the main CPU deasserts REQ for at
  least one clock after every 16 transfers.

#### 6.4 Locked sequences

**decided** (LOCK stays), with RFC 0014's rules: the owner asserts LOCK
in an idle clock and starts the first locked transfer only if it still
has GNT at the next edge; the arbiter never withdraws GNT while LOCK is
asserted; a sequence is at most 4 transfers; a card with a second way
into its memory (a CPU card's slave port) keeps that way out from the
first locked transfer addressed to it until LOCK is released.

#### 6.5 Deadlock

A CPU card stalled waiting for the bus still lets its slave port use its
RAM. The I/O processor's count of data clocks is the backstop
([5.6](#56-unused-addresses-and-faults)).

### 7. Reset

Four levels, after [RFC 0009](0009-rfc-ideas-io.md#1-io): at least a cold
and a warm reset (Emily, 2026-10-15).

| Level | Resets | From |
|---|---|---|
| Cold | Everything, the I/O processor included, as at power-up; RAM keeps its contents | COLD: power-up, the reset button, the I/O processor's watchdog |
| System | Every card but the I/O processor, and the backplane's arbiter | RESET from the I/O processor, at a request or from its monitor |
| Warm | One CPU, through its card's control register ([section 9](#9-cpu-cards)) | Any master's write |
| Device | One device, by a reset bit of its own | Its driver |

- **COLD and RESET** are open collector, with slow edges. The backplane
  asserts both for COLD; the I/O processor asserts RESET alone. The I/O
  processor's card listens to COLD only; every other card to RESET only.
- **Each card** takes them through a Schmitt trigger, synchronises their
  end to BCLK with one flip-flop, and holds clear any state that could
  start a write while reset lasts (report 0025's memory card).
- **During and after reset** the arbiter grants position 0. A CPU card whose
  control store is SRAM holds its CPU until the I/O processor starts it
  ([RFC 0027, section 8](0027-rfc-io-coprocessor.md#8-booting-the-cpu)).
- **Never in the middle of a transfer:** a CPU card takes a warm reset
  when its current transfer ends; the I/O processor asserts RESET only
  between its own transfers.

### 8. Interrupts

- **ATN0–ATN3** are open-collector, level-sensitive requests from cards
  on the system bus (the video card's vertical blank, a network card) to
  the I/O processor, the only card that listens to them. Each card picks
  its line with a jumper.
- **Devices on the I/O bus** interrupt the I/O processor on their own
  lines ([section 19](#19-interrupts-reset-and-clocks)).
- **A CPU is interrupted by a write** to the interrupt request register
  on its card ([section 9](#9-cpu-cards)): one bit for each of draft 2's
  levels 1–8 ([RFC 0029, 7](0029-rfc-draft-2-system.md#7-interrupts)).
  - Any master can write it: the I/O processor for its devices' events,
    another CPU as a doorbell, the CPU itself.
  - A write to its set address raises the levels whose bits are 1; a write
    to its clear address lowers them. There's no read-modify-write between
    two writers.
  - The CPU sees each level as the OR of its bit and that level's
    sources on the CPU's own card, chosen by jumper (a timer, say), so
    the levels stay level-sensitive, as RFC 0029 has them.
  - **Why the level was raised** is in a ring of events the I/O processor
    writes in memory before it sets the bit. A handler clears its level
    first, then drains the ring. An event posted in between raises the
    level again, so none is lost.
- **Slow and fast:** the I/O processor sends slow events at levels 1–5,
  through the ring and possibly batched, and fast ones at levels 6–8,
  one source to a level, so that the level's vector is its handler
  ([RFC 0027, 7.3](0027-rfc-io-coprocessor.md#73-interrupts-to-the-cpus)).
- **NMI** is a bit in the CPU card's control register, not a line.

### 9. CPU cards

Guidance for every CPU card, not part of the specification proper.
Among its registers, at `0x7N00_0000` for a card in region N
([5.1](#51-addresses)):

| Register | What it does | Chips |
|---|---|---:|
| **Control** | RUN, RESET (the warm reset), STEP (a microcycle, or to the end of the instruction), NMI; status: running, halted, at an instruction boundary. At power-up RUN is off if the control store is SRAM, on if it is flash (a jumper) | ~2 |
| **Interrupt request** | Levels 1–8, set and cleared by writes ([section 8](#8-interrupts)) | ~1–2 |
| **Slave port** into its RAM | DMA, booting, other CPUs; shares the RAM by ticks, honours LOCK and the deadlock rule (RFC 0014, section 10) | ~12–15 |
| **Control store write port** | For an SRAM control store: each SRAM a 16-bit lane in a window, written and read back while RUN is off ([RFC 0027, 8.1](0027-rfc-io-coprocessor.md#81-what-the-cpu-card-provides)) | ~14 |

A CPU card compares its two ranges like every card: its RAM's for the
slave port, and its registers'. It needs no logic for BERR, RDY or DPH.

### 10. Electrical rules

From RFC 0014's section 9 and report 0022's findings:

- **The backplane:** 4 layers (signal, ground, +5 V, signal), 0.2 mm
  traces, up to 8 positions at a 20.32 mm pitch, its logic in the middle.
- **No resistor terminators** on bused lines.
- **22 Ω in series** at every bused output, the backplane's included.
- **Bus drivers:** 74ABT16245 in TSSOP for wide drivers; an octal 74ABT245
  in SOIC is acceptable; not DIP, not 74FCT-T in DIP, not the 74ABT2245,
  not 74ACT. Masters' transceivers are the bus-hold kind (74ABTH).
- **Loading:** on each bused line a card puts at most one transceiver
  pin, or up to three CMOS inputs close together: about 12 pF in all,
  counting its trace, which is at most about 50 mm.
  - A card's address comparison and its address register are two inputs
    on A31–A24; that's within the rule.
- **Radial lines** (BCLK, REQ, GNT) through 56–68 Ω; at the card, one
  buffer for BCLK, at most three inputs for GNT.
- **COLD and RESET:** open collector, 1 kΩ pull-ups, 33 Ω and 220 pF to
  ground at both ends of the backplane, Schmitt-trigger receivers.
- **Pull-ups, 10 kΩ:** START, WRITE, LOCK and WAIT on P1; BE2, BE3 and
  W32 on P2; REQ and the GA straps at the backplane end.
- **ATN0–ATN3:** open collector, a 1 kΩ pull-up each.
- **Decoupling:** every bus chip decoupled; SOIC or flow-through parts for
  wide drivers.

### 11. The backplane's logic

| Part | Chips |
|---|---:|
| Clock drivers for 8 positions and the arbiter (CDC341) | 1–2 |
| Power-on reset, the reset button, COLD and RESET drivers | 2 |
| Arbiter: REQ register, the next owner, GNT register, a transfer's state from START and WAIT, LOCK | ~6 |
| **Total** | **~10** |

Against 51 for the backplane report 0025 built.

## Part II: The I/O bus

### 12. Overview

| | |
|---|---|
| What it is | The I/O processor's local bus, brought out to a passive I/O backplane of simple cards |
| Master | The I/O processor only |
| Timing | Strobe-timed. The I/O processor makes every edge from its bus clock; cards need no clock |
| Slots | Up to 12, in two rows of six |
| Data | 16 bits; 8-bit devices on D0–D7 |
| Address | 8 register bits per device; a radial select per slot, so cards decode nothing else |
| Strobe | The slot's select line, as SEL is on RFC 0014's simple cards, with a shared WRITE |
| Timing per slot | A table in the I/O processor: address setup, strobe and hold, in bus clocks, set by firmware |
| WAIT | Optional, for cards that can't promise a time |
| Interrupts | A line from each slot to the I/O processor |
| Cards | 3U Eurocards with one 64-pin DIN 41612 connector (rows a and c) |
| The CPU's access | Through a window in the I/O processor's range ([section 20](#20-the-window-from-the-system-bus)) |

### 13. Cards and the I/O backplane

**An I/O card** (a slave) must:

- make its devices' strobes from its select line and WRITE through a
  Schmitt NAND (74HCT132): read strobe = SEL and not WRITE, write strobe
  = SEL and WRITE;
- put SEL and WRITE into at most two inputs on the card;
- drive D only while its read strobe is active;
- take its device registers from A0–A7, and a device's chip select from
  those bits or tie it active;
- hold its INT line while it wants service.

**The I/O processor** (the only master) drives the address, WRITE, the
selects and write data, takes read data, and times everything from its
table ([section 17](#17-the-timing-table)).

**The I/O backplane** is passive: connectors, and each slot's SEL and INT
routed to their own pins at the I/O processor's connector. How the I/O
processor's card reaches it (a cable, or a connector of its own) waits
for the card size.

### 14. Signals

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D0–D15 | 16 | bused, 3-state | the I/O processor in a write, the selected card in a read | data |
| A0–A7 | 8 | bused | the I/O processor | the register in the selected device |
| WRITE | 1 | bused | the I/O processor | a write; stable from before the select to after it |
| SEL | 1 | radial | the I/O processor | this slot is accessed: the strobe. Active high |
| WAIT | 1 | bused, OC | a selected card | stretch the strobe ([section 18](#18-wait)) |
| INT | 1 | radial | the card | interrupt request. Active high |
| IORESET | 1 | bused | the I/O processor | reset the I/O cards |
| CLKA, CLKB | 2 | bused | the I/O processor's card | free-running clocks: 1.8432 MHz and 4 MHz |
| +5 V, +12 V, −12 V, ground | 26 | | | +12 and −12 V for line drivers, analog and audio |
| reserved | 7 | | | |

**Pin rules:** SEL and WRITE each have a ground pin on both sides
(report 0022 found these guard pins necessary for SEL as a strobe), to
be checked physically ([section 30](#30-still-to-check)); power and
ground are spread; every signal is on the same pin at every slot.

### 15. Devices and addresses

The I/O processor addresses a device register with its X register:

| X bits | |
|---|---|
| 0–7 | the register: A0–A7 |
| 8–11 | the device, S: 0–11 the I/O slots 0–11, 12–15 on the I/O processor's own card (the console UART, the image flash, its ports) |
| 12–15 | reserved |

Devices 12–15 on the I/O processor's card follow the same rules and use
the same table as the slots.

### 16. The access

```
BCLK edge   0     1     2     3     4     5     6     7
A0-A7,      X=====================================X     address, WRITE (and write data)
WRITE         |<-1+setup->|                 |<-1+hold->|
SEL         ______________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\__________
                          |<---- strobe ---->|
read data                        card drives ^ taken at the end of the strobe
```

An access is, in bus clocks:

1. **Address setup:** A0–A7, WRITE and any write data are valid for 1 +
   SETUP clocks before SEL rises.
2. **The strobe:** SEL is high for STROBE clocks, longer while the card
   holds WAIT. In a read the I/O processor latches D at its end.
3. **Hold:** A0–A7, WRITE and write data stay for 1 + HOLD clocks after
   SEL falls. The next access to anything starts after that.

What a card can rely on, with T the bus clock's period:

| | Guaranteed |
|---|---|
| Address and WRITE stable before SEL rises | (1 + SETUP) × T, less about 10 ns |
| SEL's width | STROBE × T, less a few ns |
| Address, WRITE and write data held after SEL falls | (1 + HOLD) × T |
| From the device's strobe starting to its read data being needed at the card's connector | about STROBE × T − 65 ns (SEL's register and line, the 74HCT132, the return path); a buffer on the card takes its own delay off that |

SEL comes from registers in the I/O processor, so it never glitches.

### 17. The timing table

- **One entry per device**, 16 entries of 16 bits, indexed by X bits 8–11
  for the I/O processor's accesses and by the window's address for the
  CPU's ([section 20](#20-the-window-from-the-system-bus)). Every access
  takes its own device's timing; nothing is reloaded between devices.
- **An entry:**

  | Bits | Field | Range |
  |---|---|---|
  | 0–1 | SETUP | 0–3 extra clocks of address setup |
  | 2–7 | STROBE | 1–64 clocks of SEL |
  | 8–11 | HOLD | 0–15 extra clocks of hold |
  | 12 | WAIT | the card may stretch the strobe |
  | 13 | WINDOW | the system bus may reach this device |
  | 14–15 | | reserved |

- **The I/O processor's firmware** loads the table at boot, from the card
  table in its flash ([RFC 0027](0027-rfc-io-coprocessor.md)). A device's
  minimum cycle time goes in HOLD, or its driver spaces its accesses.
- **The values are in bus clocks,** so a different period means a new
  table, computed by firmware.

Examples at T = 60 ns:

| Device | SETUP / STROBE / HOLD | Clocks per access | Why |
|---|---|---:|---|
| 16C550 UART | 0 / 2 / 0 | 4 | read data 45 ns after its strobe, 40 ns recovery, 87 ns cycle |
| CF card, PIO mode 0 | 1 / 6 / 1 | 10 | 70 ns address setup, read data 240 ns after its strobe, a 600 ns cycle |
| CF card, PIO mode 4 (*estimate*) | 0 / 3 / 0 | 5 | 25 ns setup, 70 ns strobe, 120 ns cycle |
| HD44780 LCD (*estimate*, from its datasheet) | 0 / 8 / 7 | 17 | about 450 ns enable pulse, a 1 µs cycle |

The UART and CF figures come from the repository's timing data
(`infra/hw/timing.json`). They assume no buffer on the card between the
device and the bus; with a 74HCT245, add a clock to STROBE.

### 18. WAIT

For cards that can't promise a time: a packet buffer the card's own
receiver also writes, an SRAM a synthesiser shares, or Motorola-style
chips (6522, 6850) that must line up with an E clock the card makes from
CLKB.

- **Only slots with WAIT set in their table entry** may use it, with a
  STROBE of at least 3 clocks.
- **A card asserts WAIT** within 30 ns of SEL rising, and holds it until
  its read data is on D, or its write is done.
- **The I/O processor** synchronises WAIT with two flip-flops and keeps
  SEL high while it sees WAIT. The strobe ends 2 clocks after it sees
  WAIT released.
- **The bound:** the I/O processor ends any strobe after 256 clocks, and
  records an error for that device. It is the I/O bus's only master, so
  it can end an access itself, which the system bus can't.
- **Electrical:** open collector, 1 kΩ pull-up on the I/O processor's
  card.

### 19. Interrupts, reset and clocks

- **INT:** each slot's line goes to a status port that the I/O processor
  reads at every tick of its polling, every 10 µs
  ([RFC 0027, 6.4](0027-rfc-io-coprocessor.md#64-tasks-native-jobs-and-events)). It is
  level-sensitive: a card holds it until it has been serviced. A 10 kΩ
  pull-down at the I/O processor makes an empty slot quiet. The I/O
  processor services the device or forwards the event to a CPU
  ([section 8](#8-interrupts)).
- **IORESET:** asserted while the I/O processor is reset, on a system
  reset, and when its firmware resets the I/O bus alone. A card may also
  have reset bits of its own for each device.
- **CLKA and CLKB:** 1.8432 MHz for UARTs (baud rates up to 115,200) and
  4 MHz for sound chips and a 1 MHz E clock, from oscillators on the I/O
  processor's card. A card that needs another frequency has its own
  crystal.

### 20. The window from the system bus

A part of the I/O processor's range maps straight onto the I/O bus, so a
CPU can reach a device directly, as on a PDP-11, without the I/O
processor's firmware.

- **Layout:** device S at offset S × 64 KB, register r at 4r. At
  `0x7F00_0000` in the map of [5.1](#51-addresses), the kernel finds
  register r of device S at `0xFF0S_0000` + 4r: `0xFF0S_RRRR` with
  RRRR = 4r (Emily, 2026-10-16).
  - **Each register is a word:** 8-bit registers on D0–D7, 16-bit ones
    on D0–D15. A word access is one device access with an upper half of
    zero, whether the card drives W32 or the master repeats the upper
    half at A1 = 1: an access at 4r + 2 reaches nothing, and reads zero.
    A halfword or byte access at 4r reaches the register.
  - **The eight register bits use 1 KB** of each device's 64 KB. A10–A15
    and A20–A23 are ignored, so the registers repeat. The room is there
    if the I/O bus ever gets more address lines.
  - **The kernel's copy:** the one at `0x7F8S_0000`, which the kernel
    reaches at `0xFF8S_RRRR` with mode D's sign-extended 24-bit absolute
    addresses, a parcel shorter than a 32-bit one
    ([report 0036, 2.3](0036-report-fen.md#23-the-window-and-the-short-addresses)).
    A driver in user mode has its device's page mapped wherever it
    likes.
  - **A page per device:** all of a device's registers are in its first
    4 KB page and nothing else is in its 64 KB, so the page map can give
    a driver its device and nothing else, as with
    [report 0036](0036-report-fen.md)'s I/O card.
- **An access through the window:**
  1. the I/O processor's card registers the address in the address
     clock and holds WAIT on the system bus;
  2. it waits for the I/O processor's own access in progress, if any, to
     end;
  3. it runs the access with that device's timing from the table;
  4. it releases WAIT when the access ends.

  It takes about 0.4–1 µs, like an access to report 0025's I/O card.
- **The bound:** a window access ends within 200 I/O-bus clocks or is cut
  off, so the I/O processor's card never holds WAIT past the system
  bus's 255 ([5.4](#54-wait)).
- **Devices without WINDOW** in their table entry ignore writes through
  the window and return all ones.
- **Ownership:** each device belongs either to the I/O processor or to a
  CPU, recorded in the card table. Two masters touching one device
  (a CPU reading a UART's receive register under the I/O processor's line
  discipline, say) is a software error the hardware doesn't prevent.

The I/O processor's own registers at `0x7400_0000`, and its shared RAM
in region 4 ([section 26](#26-chips)), are RFC 0027's business.

### 21. Electrical rules and cards

- **Drivers on the I/O processor's card:** 74ABT or 74HCT, 33 Ω in series
  on bused outputs, 33–68 Ω on SEL.
- **On the cards:** 74HCT or CMOS devices; Schmitt inputs (74HCT132) for
  SEL and WRITE.
- **Loading:** at most one transceiver pin or three CMOS inputs per bused
  line per card; a device's data pins straight on D count as one pin.
- **The I/O backplane:** up to 12 slots in two rows of six, each row about
  12 cm long, with a short hop between the rows; 4 layers recommended, 2
  possible.
- **Why strobes are safe here:** RFC 0014 rejected strobe-timed buses for
  fast multidrop edges ringing along a 16-slot backplane. Here every
  strobe is radial, only the address and data lines are bused, and they
  have at least a clock to settle before a strobe starts.

Some cards, roughly:

| Card | Parts | Chips |
|---|---|---:|
| Two serial lines | 16C552 or two 16C550, line drivers, 74HCT132 | 3–4 |
| CF card or IDE disk | Connector, 74HCT132 | 1 |
| Printer port | Latch, status buffer, 74HCT132 | 3 |
| Sound | 8-bit DAC and latch, or an AY-3-8910 | 2–3 |
| Floppy | µPD765-class controller, line drivers, 74HCT132 | 3–4 |
| General-purpose I/O | Two latches, two buffers, 74HCT132 | 5 |
| Character LCD | 74HCT132 and a connector | 1 |
| Ethernet | The TTL MAC of RFC 0009, its packet buffer behind a pointer register | 40–60 |

### 22. The I/O processor's side

| Part | Chips |
|---|---:|
| Address and WRITE drivers | 1 |
| Data transceiver, and the read latch at the end of a strobe | 2 |
| Selects: a 74HCT154 and registers, so SEL can't glitch | 2–3 |
| Timing table: two CY7C199, and a buffer to load them | 3 |
| Strobe counters and their control | 3 |
| WAIT synchroniser | 1 |
| INT status port | 1 |
| CLKA and CLKB oscillators | 2 |
| **Total** | **~15** |

That replaces RFC 0027's device decode, stretch counter and jumpers
(about 3), so it adds about 12 to the I/O processor's card. The window
adds about 5–7 more ([RFC 0027, 9](0027-rfc-io-coprocessor.md#9-chips)).

## Part III: Discussion

### 23. Why two buses

- **The I/O processor is in every Heron, and it is the DMA engine**
  (Emily, 2026-10-16). It already owns booting, the console and every
  transfer.
- **So slow devices can be its alone.** The CPU no longer needs to reach
  a UART register in 880–960 ns over the system bus
  ([report 0025](0025-report-draft-1b-system.md#13-what-a-bus-transfer-costs));
  the I/O processor reaches it on its own bus, and the window keeps a
  direct path for the CPU.
- **And then the system bus only carries fast cards.** Most of RFC 0014's
  machinery was for telling simple cards from fast ones, timing them and
  reporting their absence. Without simple cards it isn't needed.
- **And only a few of them:** realistically 3–4, such as the I/O
  processor, the Heron CPU and video (Emily, 2026-10-16), with up to 8
  positions because many cards take two. Allocating them static
  addresses is trivial, so the address needn't carry a slot.
- **Simple, dumb peripherals stay possible** (decided, RFC 0014 section
  19): on the I/O bus, as cheap as they were on the system bus. The
  I/O card of report 0025 would move over almost unchanged.

### 24. Against RFC 0014

| RFC 0014 | Here | Why |
|---|---|---|
| Simple cards on the system bus (decided) | On the I/O bus | The I/O processor serves them, and the window keeps the CPU's direct path |
| Class straps read by the backplane (decided) | None | One kind of card: nothing to tell apart |
| The backplane times transfers (decided) | Nobody: a transfer is 2 clocks unless the card holds WAIT | Fast cards already decide WAIT from their own decode (report 0025) |
| SEL, the strobe for simple cards (decided) | Each card compares its own range; SEL becomes the I/O bus's strobe | SEL comes too late for a fast card's WAIT anyway (report 0025) |
| RDY and DPH | Worked out from START and WAIT | Their only job was to mark the data phase |
| BERR | None | Unused addresses and faults: [5.6](#56-unused-addresses-and-faults) |
| The bus monitor | The I/O processor's count of data clocks, and a system reset | It sees DPH's equivalent anyway; recovery is a reset either way |
| Every card has an ID (decided) | A card table in the I/O processor's flash | No ID chips or decode on cards |
| GA0–GA3, each slot's number | None | Addresses don't carry the slot |
| IRQ0–IRQ7, each CPU listening to its subset | ATN0–ATN3 to the I/O processor; CPUs interrupted by writes | The I/O processor is the interrupt controller |
| RESET | COLD and RESET | A system reset mustn't reset the card that asserts it |
| Any slot a master | Master positions 0–3 | The CPUs and the I/O processor are the only masters |
| A recovery clock for simple cards | Only on the I/O bus, as HOLD | |
| One N for every simple card, by jumpers | A timing table per device on the I/O bus | Each card at its own speed |
| A separate I/O bus behind a bridge (rejected, 2026-10-13) | The I/O bus | The bridge is the I/O processor, and the CPU makes few device accesses |
| Addresses carry the slot (decided), A31–A28 tentatively; 16 slots | A static map, each card a fixed range below 2 GB; up to 8 positions | 3–4 cards; a card's address follows the card; RFC 0029's window reaches everything |
| The backplane, 51 chips as built | About 10 | |

What stays from RFC 0014's decisions: the bus is synchronous; addresses
are 32 bits; two 96-pin connectors per position, with P1
enough for a 16-bit card; LOCK; no bursts; logic on the backplane (less
of it); no −5.2 V.

### 25. Decisions this asks for

It reverses decisions of 2026-10-13 and 14, so these are Emily's:

1. **Simple peripherals off the system bus,** onto the I/O bus, and the
   separate I/O bus reopened.
2. **No class straps;** a fast card holds WAIT when it needs longer, and
   nothing else times a transfer.
3. **SEL as the I/O bus's strobe,** not the system bus's; system-bus cards
   compare their own range.
4. **No card IDs;** the card table instead.
5. **"P1 is enough for a simple peripheral"** becomes "P1 is enough for a
   16-bit card".
6. **Addresses don't carry the slot:** a static map instead
   ([5.1](#51-addresses)).

### 26. Chips

| | As built (report 0025) | Here (*estimate*) |
|---|---:|---:|
| Backplane | 51 | ~10 |
| Memory card | 31 | ~28 (no ID; a W32 driver) |
| CPU card's bus interface | 35 | ~34 (no BERR handling; address comparisons for its RAM and its registers) |
| I/O card | 16 | – (its devices go on I/O cards) |
| I/O processor card | – | about 95: RFC 0027's core, the I/O bus's side, the window and the shared RAM |

The backplane's saving pays for most of the I/O bus's side on the I/O
processor's card. RFC 0027 puts the memory card's RAM on the I/O
processor's card, as RAM the CPUs share
([4.3](0027-rfc-io-coprocessor.md#43-the-shared-ram)), so the memory card's ~28 chips
become about 8 there.

### 27. What it costs

- **Every Heron needs its I/O processor** for any slow device. That's
  decided.
- **An unanswered access is silent.** A read of an unused address
  returns stale data; nothing traps. The MMU only maps cards that exist,
  so a user process can't reach one by accident, but a kernel bug that
  does reads garbage instead of faulting. The I/O processor checks its
  card table at boot with harmless probes, written so that a held value
  can't pass for a card's answer.
  - An earlier idea, weak pull-ups on D so that an unused address reads
    all ones, doesn't work: a 10 kΩ pull-up takes microseconds to charge a
    loaded bus line, not one data clock.
- **A stuck transfer is a system reset,** not an error the operating
  system can catch and survive. The bound on WAIT makes it a hardware
  fault only.
- **No 74HCT cards on the system bus:** every card needs fast parts and
  an address comparator.
- **Overlapping ranges are a configuration error** the bus can't catch:
  two cards answering a read fight on D. With 3–4 cards and the map of
  [5.1](#51-addresses) it shouldn't happen.
- **The I/O bus is strobe-timed,** fine at its size but not yet
  simulated ([section 30](#30-still-to-check)).
- **Interrupts go through the I/O processor:** about 3–15 µs from a
  device to a CPU (a tick of polling, then the routing), against about
  1 µs over a line ([RFC 0027, 7.4](0027-rfc-io-coprocessor.md#74-latency)).
  Sources that need less live on the CPU's own card.
- **One master on the I/O bus:** devices can't DMA; the I/O processor
  moves everything, as decided.
- **The window shares the I/O bus** with the I/O processor's own accesses;
  who owns a device is a software convention.

### 28. Fitting draft 2

[RFC 0029](0029-rfc-draft-2-system.md) (draft 2's system architecture,
open) and [report 0036](0036-report-fen.md) (the Fen operating system)
assume RFC 0014's bus in four places:

- **Interrupts.** RFC 0029 takes levels 1–8 from the system bus's
  IRQ1–IRQ8, or from sources on the CPU's own card, level-sensitive. Here
  the levels come from the interrupt request register on the CPU card
  ([section 8](#8-interrupts)), ORed with the card's own sources. The CPU
  sees the same eight level-sensitive inputs, so RFC 0029's CPU side is
  unchanged. Fen's interrupt mask and timer on the CPU board stay as they
  are. RFC 0029 holds the interrupt architecture as a whole open (Emily,
  2026-10-16); keeping IRQ1–IRQ8 as bused lines driven by the I/O
  processor is the alternative ([section 29](#29-alternatives)).
- **An access that nothing answers.** RFC 0029 leaves open a bus timeout
  and its vector (its open question 2); Fen's simulator made it a bus
  error through `0x8000_000C`, and Fen's kernel ends a process that
  causes one. Here nothing answers and nothing traps. If that should be
  a fault, the answer line of [section 29](#29-alternatives) gives the
  CPU card a way to raise one, for a pin and a driver on each card.
- **The supervisor window** reaches physical addresses below
  `0x8000_0000`. The static map puts every card there
  ([5.1](#51-addresses)). Against Fen's map, RAM stays at 0 and the
  rest moves: the CPU card's registers from `0x0F00_0000` to
  `0x7000_0000`; video from `0x1000_0000` to `0x6000_0000`, its
  registers from `0x1FF0_0000` to `0x7600_0000`; and the I/O bus from
  `0x2000_0000`, where Fen's I/O card was, to `0x7F00_0000`, 64 KB
  apart. Fen's drivers change their base addresses and the I/O bus's
  stride. That answers part of RFC 0029's open question 2, where things
  sit.
- **A page per device.** Fen's I/O card gives each device a 4 KB page so
  that the page map can grant a driver exactly one device. The window
  keeps that: device S's registers are all in the page at
  `0x7F00_0000` + S × 64 KB
  ([section 20](#20-the-window-from-the-system-bus)).

### 29. Alternatives

| Idea | Status | Why |
|---|---|---|
| Keep simple cards on the system bus with the class in the address (A26 set: simple timing) | **not recommended** | Removes the straps and their lookup but keeps the backplane's transfer timing and SEL, for a convention software can get wrong |
| Keep the backplane's SEL for fast cards | **not recommended** | It arrives too late for WAIT; cards compare their own range anyway |
| Slots in the address (RFC 0014's A31–A28, or A30–A27) with the slot number on GA0–GA3 | **not recommended** | With 3–4 cards a static map is trivial; slots cost four pins and tie a card's address to where it is plugged in |
| An answer line, driven by the addressed card through its data phase (PCI's DEVSEL#) | **open** | Gives unanswered accesses a fault for one pin and a driver per card; needs the same rule as W32 for letting go |
| IDs on cards: a 74HCT541 of straps, or "a read with no byte enables returns the ID" | **not recommended** | 1–3 chips per card; the card table does the job |
| A serial ID bus: an I²C EEPROM on each card | **not recommended** | Probably against Emily's rule against new-fangled chips (2026-10-15), and 5–6 P1 pins with slot addressing |
| A 74HC165 chain of ID straps through the backplane | **not recommended** | Four P1 pins, and empty positions break the chain |
| The bus monitor on the backplane, ending a stuck transfer with an error | **not recommended** | Needs BERR; the I/O processor's count and a reset do without |
| IRQ1–IRQ8 kept as bused lines, driven by the I/O processor and the cards | **open** | Closest to RFC 0029 as written; costs eight pins and ties every CPU to one set of lines |
| Per-device jumpers for the I/O bus's timing (RFC 0027 as written) | **not recommended** | Moving a card means moving jumpers on another card; the window couldn't share them |
| One timing register, reloaded when the device changes | **not recommended** | A forgotten reload gives a device the wrong timing; the window couldn't use it |
| WAIT-only timing on the I/O bus, each card timing itself | **not recommended** | A clock and a counter on every card (about 8 chips for a simple card, RFC 0014) |
| Making the bus period fixed | **not recommended** | Bring-up at 80 or 100 ns is free if every card works at any longer period |

Precedents: the Unibus and VME, whose cards answer the addresses they
are built or jumpered for; NuBus, synchronous like this bus; PCI's DEVSEL# and message-signalled interrupts; the Apple II's
select line per slot; ECB, the European 8-bit Eurocard bus on a 64-pin
DIN 41612; the CDC 6600, whose peripheral processors did all the I/O;
the 68000's E clock and VPA for 6800-family peripherals.

### 30. Still to check

Before a netlist, against the timing data and in `studies/bus_si`:

| Path | Steps (ns) | Total | At 60 ns |
|---|---|---:|---:|
| Card to card, one clock | register 7, transceiver 4, settling 13, transceiver 4, setup 3, skew 2.5 | 34 | 26 left |
| A card's address comparison in the address clock | the master's outputs at the edge (T<sub>co</sub> max) 16, settling 13, receiver 4, 74F521 11, register setup 3, skew 2.5 | 50 | 10 left |
| WAIT or W32 from a card's registered decode | register 7, driver 4, settling 13, receiver 4, setup 3, skew 2.5 | 34 | 26 left |
| A fast SRAM card's read | address register 7, SRAM 12, transceiver 4, settling 13, setup 3, skew 2.5 | 42 | 18 left, less the lane multiplexing |

- **The address comparison sets the shortest period,** about 50 ns, as
  RFC 0014's class lookup did, as long as a card decides from at most 8
  address bits. A second, cascaded 74F521 adds about 10 ns, which leaves
  nothing at 60 ns.
- **W32 driven inactive into the next address clock** needs checking for
  contention with the next card's first data clock.
- **Bus-hold** on the masters' transceivers alone: enough for 8 positions
  of floating lines?
- **The I/O backplane's hop** between its two rows of slots.
- **The I/O backplane:** crosstalk on SEL and WRITE with HCT edges, and
  the guard pins, with the same tools as report 0022.
- **The guard pins need a careful physical review,** on both buses, once
  there is a pin assignment, a connector part and a layout. A rule like
  "a ground pin on both sides" is only as good as the geometry behind it:
  - **Which pins are neighbours** depends on the connector. On the
    system bus's 96-pin DIN 41612 (rows a, b and c), a pin's neighbours
    are along its row and across in the next row. On the I/O bus's
    64-pin connector, rows a and c only, the pin across is two row
    pitches away, so a different pin is "beside" it.
  - **On a right-angle connector** each row's contacts are a different
    length, so coupling along the contacts differs by row.
  - **A guard pin only guards** if it reaches the ground plane through a
    short via right at the connector, on the backplane and on the card.
    One joined to ground through a trace guards nothing.
  - **The guarded lines' traces** should leave the connector field
    without running long beside other signals, on the backplane and on
    each card.
  - **Report 0022 simulated an assumed contact coupling** and its own
    reference pin assignment. The real assignment and layouts need
    simulating again, and in the end a measurement on a prototype
    backplane.

  The lines concerned: BCLK, COLD and RESET on the system bus; SEL and
  WRITE on the I/O bus, where SEL is the strobe and a spike on either
  becomes a false or broken access.
- **The duty cycle** the I/O processor needs, at the far end of the clock
  tree.

### 31. Open questions

For Emily:

1. **Two buses:** the system bus for fast cards only, and the I/O bus for
   everything slow, reversing the decisions in [section 25](#25-decisions-this-asks-for)?
2. **Unanswered accesses:** silent, or a fault through an answer line
   (one pin; RFC 0029's open question 2)?
3. **Interrupts:** a request register on each CPU card, written over the
   bus, or IRQ1–IRQ8 as bused lines? The interrupt architecture is open
   as a whole (RFC 0029).
4. **The static map** of [5.1](#51-addresses) instead of slots in the
   address: seven 256 MB regions of memory below `0x7000_0000`, the
   registers of region N's card at `0x7N00_0000`, and the I/O bus at
   `0x7F00_0000`, `0xFF0S_RRRR` to the kernel?
5. **Master positions:** four, of up to 8?
6. **The bus period:** 60 ns as the working value, with any longer period
   allowed?
7. **The I/O bus:** 12 slots in two rows of six, 3U cards with 64-pin
   connectors, in the same card cage?
8. **The window** into the I/O bus, about 5–7 chips on the I/O processor's
   card?
9. **The bus clock's source:** the main CPU card (as built) or an
   oscillator on the backplane? Still RFC 0014's open question 1.
10. **P2 as a 64-pin connector** (rows a and c): its 20 signals and its
    power fit, leaving no user-defined pins, for 32 fewer joints a
    position. The decided "two 96-pin connectors per slot" would change.

### 32. Next steps

- **At chip level,** a variant of `studies/v1b_system` with this system
  bus: the backplane without its transfer timing, the memory card and
  CPU card comparing their ranges, W32 and WAIT from the cards. Run the
  suite and count the chips.
- **The I/O bus** as a netlist on the I/O processor's model, with
  report 0025's I/O card moved over as an I/O card.
- **Signal integrity** of the I/O backplane, and of W32's turnaround.
- **RFC 0027 revised** for the I/O processor's new jobs: the I/O bus's
  side, the window, the interrupt controller, its interpreted programs,
  and the shared RAM.
- **When this is accepted:** RFC 0014 obsolete with `superseded-by: 37`,
  and `docs/` changed to match.
