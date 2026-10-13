---
number: 14
type: rfc
title: System bus
status: open
date: 2026-10-13
context:
  studies: [bus_si, v1b_hw]
  commit: a14eeb2
---

# RFC 0014: System bus

A draft specification of the backplane bus shared by the main CPU, DMA
devices, peripherals and possibly other CPUs. The reasoning behind it is in
[RFC 0007](0007-rfc-ideas-microarchitecture.md) and
[RFC 0008](0008-rfc-ideas-memory-and-buses.md).

The electrical numbers come from ngspice simulations of the backplane with
TI's IBIS models ([studies/bus_si/README.md](../studies/bus_si/README.md); results in
[report 0013](0013-report-bus-si/full.json)). The datasheet delays in the timing
budgets are rough worst-case figures and need checking against the parts
actually used.

Statuses: **decided** (Emily chose it), **recommended**, **open**,
**optional** for features a card may leave out, and **rejected**. What
Emily has decided is collected in [section 14](#14-decisions).

**Revised on 2026-10-13**, after Emily's decisions and a review of the
first draft:

- **Bus clock:** the period T is open. 60 ns is the working value, and the
  figures here are for 60 ns ([section 4](#4-clock-and-timing-conventions)).
- **The address map:** RAM on the backplane maps addresses to slots, with
  each page's wait states (**decided**). It replaces the fixed slot regions
  and the masters' wait-state tables. The backplane now times every
  transfer: it drives SEL, the strobes, a new RDY line, BUSY, W32, BACK
  and BERR ([section 5.1](#51-the-address-map)).
- **Fixes from the review:**
  - halfwords always travel on D0–D15, so 16-bit masters can use 32-bit
    slaves ([5.7](#57-data-width-and-byte-lanes));
  - every card can see where a transfer ends, and shared lines get a clock
    to turn around ([5.4](#54-the-end-of-a-transfer-and-turnaround));
  - simple slaves get recovery clocks with the address held, so a strobe
    never ends as the next address appears
    ([5.6](#56-simple-slaves-and-the-strobes));
  - idle lines are driven or held by pull-ups ([section 6](#6-arbitration),
    [section 9](#9-electrical-rules));
  - clock skew and hold time ([section 4](#4-clock-and-timing-conventions));
  - LOCK and slave ports ([section 6](#6-arbitration)).
- **Simple peripherals** go on the system bus; the separate I/O bus is
  rejected ([section 12](#12-rejected-a-separate-io-bus)).
- **Cards:** two 96-pin connectors per slot are decided. The card size,
  and how the system splits into cards, wait until the design is closer to
  completion. Nothing in the protocol depends on them.
- **The backplane** carries active logic (decided), and no −5.2 V. The ECL
  number cruncher is deprioritised, so the bus no longer plans around it.

## Contents

1. [Summary](#1-summary)
2. [Kinds of card](#2-kinds-of-card)
3. [Signals](#3-signals)
4. [Clock and timing conventions](#4-clock-and-timing-conventions)
5. [Transfers](#5-transfers)
6. [Arbitration](#6-arbitration)
7. [Bursts (optional)](#7-bursts-optional)
8. [Reset, configuration, interrupts and synchronisation](#8-reset-configuration-interrupts-and-synchronisation)
9. [Electrical rules](#9-electrical-rules)
10. [The main CPU board on the bus](#10-the-main-cpu-board-on-the-bus)
11. [Other CPUs as masters](#11-other-cpus-as-masters)
12. [Rejected: a separate I/O bus](#12-rejected-a-separate-io-bus)
13. [Open questions](#13-open-questions)
14. [Decisions](#14-decisions)

## 1. Summary

| | |
|---|---|
| Timing | **Synchronous**: one bus clock, every signal sampled on its rising edge. **decided** |
| Bus clock | Period T **open**; this RFC uses 60 ns (16.7 MHz). The tightest path, the backplane's address lookup, needs about 48 ns |
| Address | 32 bits (4 GB). **decided** |
| Address map | RAM on the backplane maps each 128 KB page to a slot, with the page's data clocks, recovery clocks and width. **decided** (the page size is recommended) |
| Data | 16 bits on P1 (D0–D15), 32 bits with P2. Halfwords and bytes always travel on D0–D15 |
| Transfers | An address clock, then data clocks: 2 clocks (120 ns) for a fast slave. The map sets the minimum, a slave adds more with WAIT, and the backplane's RDY marks the end |
| Bursts | One word per clock after the first: **optional** ([section 7](#7-bursts-optional)) |
| Masters | Any slot. A round-robin arbiter on the backplane; the bus stays with the last master while nobody else asks |
| Backplane | Active logic: the address map and transfer timing, the arbiter, the bus monitor, the clock buffer and the power-on reset. **decided** |
| Cards | Two 96-pin connectors per slot (DIN 41612, as simulated), up to 16 slots. P1 alone is enough for a simple peripheral. **decided**. The card size, and how the system splits into cards, wait until the design is closer to completion |
| Simple peripherals | On the system bus. **decided**. The backplane gives each one a select line, read and write strobes and its wait states, so a card needs no clock, no address comparator and no WAIT logic |

Peak rates at T = 60 ns:

| | Clocks | |
|---|---:|---:|
| Single transfer to a fast slave | 2 | 120 ns |
| 16-bit singles | 2 | 16.7 MB/s |
| 32-bit singles | 2 | 33 MB/s |
| 32-bit bursts (optional) | 1 per word | 67 MB/s |
| Simple-peripheral transfer, d data clocks and r recovery clocks | 1 + d + r | 180 ns at the least; 300 ns for a 74HCT UART card |

## 2. Kinds of card

A card can play any combination of these roles. A CPU board is a master and
a synchronous slave (its RAM, for other masters). The backplane takes part
in every transfer.

**Master** (main CPU, DMA engines, bridges for other CPUs). Must:

- request the bus and follow the arbitration rules
  ([section 6](#6-arbitration));
- run transfers: an address clock, then hold the address through the rest
  of the transfer ([5.2](#52-read), [5.3](#53-write));
- take read data at the end of each data clock in which RD is asserted and
  WAIT isn't, and end the transfer when RDY says so
  ([5.4](#54-the-end-of-a-transfer-and-turnaround));
- split words for 16-bit pages and steer the halves
  ([5.7](#57-data-width-and-byte-lanes));
- report a bus error to its own processor when a transfer ends in BERR.

Masters keep no wait-state tables and drive no strobes: the backplane does
both.

**Synchronous slave** (memory cards, the CPU boards' slave ports, DMA and
Ethernet cards' registers and buffers). Registers the address at the end of
every address clock, and answers when the backplane asserts its SEL. It
needs fast parts (74ABT or 74FCT-T) at the bus interface; 74HCT is too slow
for a one-clock path ([section 4](#4-clock-and-timing-conventions)).

**Simple slave** (UARTs, the CF card, an RTC, a parallel port, the front
panel). Needs only:

- P1, with D0–D7 (or D0–D15), a few low address lines, SEL, RD, WR,
  PRESENT (tied to ground) and an IRQ line;
- no clock, no address comparator, no WAIT logic. The backplane times its
  strobes from the map.

  A UART card, for example: a 16C550 with its crystal, a 74HCT245 on the
  data lines, a 74HCT14 to square up RD and WR, and its card ID
  ([section 8.2](#82-configuration)). It can be built entirely from 74HCT.

**The backplane** holds the address map. For every transfer it drives SEL
to the addressed slot, RD or WR, RDY, BUSY, W32, BACK and, on an error,
BERR. It also arbitrates, buffers the clock and resets the system. The
parts are in [section 9](#9-electrical-rules).

## 3. Signals

Polarity: control signals are active low on the backplane. Signal names
below are given without a suffix, and "asserted" means active.

**Topology** (column "Type" below):

- **bused:** runs past every slot.
- **radial:** each slot has its own trace to logic on the backplane, on the
  same pin at every slot.
- **strapped:** fixed per slot.

**Drive types:**

- **backplane:** driven by the backplane's logic all the time, so it never
  floats.
- **3-state:** driven by the current owner (or the selected slave for read
  data), and otherwise by nobody.
- **shared:** driven by one card at a time, actively both ways, and held
  inactive by a weak pull-up when nobody drives (as in PCI).
- **OC:** open collector, with a pull-up on the backplane.
- **pull-up:** a 3-state line with a weak pull-up, which holds it inactive
  between owners ([section 9](#9-electrical-rules)).

### P1: the 16-bit bus

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D0–D15 | 16 | bused, 3-state | master in a write, slave in a read | data |
| A1–A31 | 31 | bused, 3-state | bus owner | address |
| BE0, BE1 | 2 | bused, 3-state | bus owner | byte enables ([5.7](#57-data-width-and-byte-lanes)) |
| START | 1 | bused, 3-state, pull-up | bus owner | asserted in the address clock of each transfer |
| WRITE | 1 | bused, 3-state, pull-up | bus owner | asserted for a write, valid with START |
| LOCK | 1 | bused, 3-state, pull-up | bus owner | keep the bus across a read-modify-write (**optional**) |
| RD, WR | 2 | bused, backplane, slow edges | backplane | strobes for simple slaves |
| RDY | 1 | bused, backplane | backplane | the page's data clocks are done ([5.4](#54-the-end-of-a-transfer-and-turnaround)) |
| WAIT | 1 | bused, shared | addressed slave | add a data clock |
| BERR | 1 | bused, backplane | backplane | end the transfer with an error |
| BUSY | 1 | bused, backplane | backplane | a transfer is past its address clock |
| PRESENT | 1 | radial | card (tied to ground) | a card is in this slot |
| REQ | 1 | radial | master | bus request to the arbiter |
| GNT | 1 | radial | backplane | bus grant |
| SEL | 1 | radial | backplane | this slot is addressed; asserted from the first data clock to the end |
| BCLK | 1 | radial | backplane | bus clock |
| RESET | 1 | bused, OC, slow edges | backplane power-on reset, main CPU | system reset |
| IRQ0–IRQ3 | 4 | bused, OC | any card | interrupt requests |
| reserved | 4 | | | for ground pins beside SEL, or a higher supply voltage (**open**) |
| +5 V, ground | 24 | | | |

### P2: the upper half and extras

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D16–D31 | 16 | bused, 3-state | as D0–D15 | upper halfword of a word transfer |
| BE2, BE3 | 2 | bused, 3-state, pull-up | bus owner | byte enables of the upper halfword in a word transfer |
| W32 | 1 | bused, backplane | backplane | the page is 32 bits wide (from the map) |
| BURST, BFIX | 2 | bused, 3-state, pull-up | bus owner | burst control, **optional** ([section 7](#7-bursts-optional)) |
| BACK | 1 | bused, backplane | backplane | the page takes bursts (from the map), **optional** |
| IRQ4–IRQ7 | 4 | bused, OC | any card | interrupt requests |
| GA0–GA3 | 4 | strapped | backplane | slot number, for cards that want to know it |
| CLKSRC | 1 | slot 0 only | main CPU board | clock into the backplane's buffer, if the bus clock comes from the CPU board (**open**, [section 4](#4-clock-and-timing-conventions)) |
| +5 V, ground | ~16 | | | |
| user-defined | ~49 | | | private links between neighbouring cards, as on VME's P2 |

GA0–GA3 and CLKSRC were on P1 in the first draft. A simple card doesn't
need its slot number, and CLKSRC is wired at one slot only, so moving them
made room for RDY and four reserved pins. P1 was exactly full before.

### Pin assignment rules

The pin-by-pin assignment is still to do. It must follow these rules:

- BCLK, RD, WR and RESET each have a ground pin on both sides, in the row
  and across rows. The simulations show connector coupling dominating
  crosstalk ([section 9](#9-electrical-rules)). SEL should get them too,
  since simple cards combine it with the strobes: **recommended**, from
  the reserved pins.
- Power and ground pins are spread along the connector, not grouped.
- The same signal is on the same pin at every slot. That includes the
  radial ones, which the backplane routes to its own logic.

## 4. Clock and timing conventions

- **The period T is open.** 60 ns is the working value, and the figures in
  this RFC are for it. The budgets below show the limits: the backplane's
  address lookup needs about 48 ns, and the strobes' slow edges about
  45–55 ns ([5.6](#56-simple-slaves-and-the-strobes)).
- **Clock source: open.** Either:
  - the main CPU board divides its 50 MHz master clock (60 ns is ÷ 3) and
    sends the result on CLKSRC, wired only at slot 0, to the backplane's
    buffer. Then the CPU always knows where the next bus clock edge is
    ([section 10](#10-the-main-cpu-board-on-the-bus));
  - or an oscillator on the backplane, independent of any CPU, with every
    master synchronising to it.
- **Distribution.** A buffer on the backplane drives each slot's BCLK on
  its own trace, through a 56–68 Ω series resistor, with one load per
  card. Every card, the CPU board included, clocks its bus logic from its
  own BCLK pin.
- **When signals change and are sampled.** Every bused signal changes just
  after a rising BCLK edge and is sampled at a later rising edge. Simple
  slaves also act on the edges of RD, WR and RESET.

**Clock skew.**

- **Trace lengths:** 0.8 ns between slots with unmatched lengths, none with
  matched lengths (simulated).
- **Buffers:** a 16-slot backplane needs at least two buffer packages, and
  every card buffers BCLK once more. The delay of a '244-type buffer ranges
  over roughly 1–5 ns from part to part, so two cards can be several ns
  apart from the buffers alone.
- **recommended:**
  - a clock-driver part with a specified output-to-output and part-to-part
    skew on the backplane;
  - on every card, exactly one buffer of a specified fast family between
    the BCLK pin and the bus registers.
- The budgets below assume at most 3 ns between any two cards. **open**
  until the parts are chosen.

**Card-edge timing.** **recommended:** specify each card's timing at its
connector, as PCI does, so a card can be checked on its own:

| Parameter | Meaning | Value |
|---|---|---|
| T<sub>co</sub> max | BCLK at the card's pin to its outputs valid at its pins | to do |
| T<sub>co</sub> min | the same, to the earliest change | to do |
| T<sub>su</sub> | an input valid at the pin before BCLK | to do |
| T<sub>h</sub> | an input held at the pin after BCLK | to do |
| T<sub>skew</sub> | between any two cards' BCLK, as their registers see it | 3 ns |

The two constraints:

- **Setup:** T<sub>co</sub> max + the backplane's settling time +
  T<sub>su</sub> + T<sub>skew</sub> ≤ T.
- **Hold:** T<sub>co</sub> min ≥ T<sub>h</sub> + T<sub>skew</sub>. With
  minimum datasheet delays, a register and a transceiver can change their
  outputs within a few ns, which is about the same as the skew. So hold
  time needs checking, not assuming.

The values can be filled in once ABT and FCT parts are in
`infra/hw/timing.json`. It only has HCT, ACT and F parts so far.

**Budget for a one-clock path** between two fast cards, at 16 slots, in ns:

| Step | ABT or FCT-T card |
|---|---:|
| Register clock-to-output (e.g. 74ABT574, 74ABT652) | ≈ 6 |
| Transceiver onto the bus | ≈ 5 |
| Backplane: flight and settling with 22 Ω series resistors (simulated, worst case) | ≤ 11 |
| Transceiver off the bus | ≈ 5 |
| Register setup time | ≈ 3 |
| Clock skew | ≤ 3 |
| **Total** | **≈ 33** |
| Slack at 60 ns | 27 |

A 74HCT card would need roughly 35 + 30 + 14 + 30 + 15 ≈ 125 ns for the
same path. That's why HCT cards are simple slaves.

**Budget for the backplane's address lookup**, from the start of the
address clock to the backplane's registers ([5.1](#51-the-address-map)),
in ns:

| Step | ns |
|---|---:|
| Master's register and transceiver | ≈ 11 |
| Backplane | ≤ 11 |
| Index multiplexer, a FET bus switch (74CBT3257) | < 1 |
| Map SRAM, 10 ns | 10 |
| Slot decoder (74ACT138) | ≈ 9 |
| Register setup | ≈ 3 |
| Clock skew | ≤ 3 |
| **Total** | **≈ 48** |
| Slack at 60 ns | 12 |

This is the longest one-clock path on the bus, so it sets the shortest
usable period: about 50 ns with these parts. With a 74ACT157 as the
multiplexer it would be about 56 ns, too close at 60.

**Budget for a synchronous slave's read.** The address is registered at
the end of the address clock, then:

| Step | ns |
|---|---:|
| Register clock-to-output | ≈ 6 |
| SRAM | 15–25 |
| Slave's transceiver | ≈ 5 |
| Backplane | ≤ 11 |
| Master's transceiver | ≈ 5 |
| Master's setup | ≈ 3 |
| Clock skew | ≤ 3 |
| **Total** | **48–58** |

That fits one data clock with 20 ns SRAM or faster. Otherwise the page gets
two data clocks in the map, or the slave raises WAIT. SEL reaches the card
about 10 ns into the first data clock, early enough to enable the slave's
transceiver before its data gets there.

## 5. Transfers

Every transfer is an address clock and one or more data clocks, sometimes
followed by recovery clocks. The backplane looks up the address during the
address clock, and from then on it times the transfer.

### 5.1 The address map

The map is **decided**; its details here are **recommended**.

- **Pages.** The 4 GB address space is split into 32,768 pages of 128 KB.
  A31–A17 is the page number.
- **Entries.** One 16-bit entry per page, in RAM on the backplane:

  | Bits | Field | Meaning |
  |---|---|---|
  | 15 | V | the page is mapped; any access to an unmapped page gets BERR |
  | 14–11 | SLOT | the slot that answers |
  | 10–7 | D | data clocks with the strobe asserted, minus 1 (so 1–16) |
  | 6–5 | R | recovery clocks after the strobe, 0–3 |
  | 4 | W32 | the page is 32 bits wide |
  | 3 | BST | the page takes bursts |
  | 2–0 | | reserved, written as 0 |

- **The lookup.** In each address clock the backplane reads the entry for
  the page on A31–A17, decodes the slot and registers it at the end of the
  clock. From the first data clock it drives that slot's SEL, and times
  the transfer from D and R ([5.5](#55-wait-states-and-recovery)). The
  budget is in [section 4](#4-clock-and-timing-conventions): about 48 ns.
- **Windows.**
  - A card's window is a power of two of at least 128 KB, aligned to its
    size, so the card decodes only the address bits below its size.
    Software maps each page of the window to the card's slot.
  - A card can have several kinds of register, say 16-bit registers and a
    32-bit buffer. Software then gives each kind its own pages, with their
    own timing and width.
  - Cards see the full address but never compare it: that's the
    backplane's job.
- **Programming.** The map is in the backplane's own page, which it never
  covers ([section 8.1](#81-reset-and-the-backplanes-page)). Software writes
  it after reset, and can change it at any time. Changing a page another
  master is using is software's business.
- **Cost:** about 17 chips:
  - two 32K × 8 SRAMs (10 ns);
  - a 15-bit multiplexer to address the RAM by entry number while software
    programs it (four 74CBT3257);
  - two transceivers for programming;
  - the decode for the backplane's page;
  - the registers and slot decoders for the entry.

### 5.2 Read

| Phase | Clocks | The owner drives | The backplane drives | The slave drives |
|---|---|---|---|---|
| Address | 1 | A, BE, START; WRITE inactive | | |
| Data | d, more while the slave asserts WAIT | A, BE | SEL, RD, BUSY, W32, BACK; RDY from clock d on if r = 0 | D, WAIT |
| Recovery | r | A, BE | SEL, BUSY; RDY in the last one | |

The master takes the data at the end of every data clock in which RD is
asserted and WAIT isn't; the last one counts. Slaves register the address,
WRITE and BE at the end of every address clock, whether they are addressed
or not.

### 5.3 Write

| Phase | Clocks | The owner drives | The backplane drives | The slave drives |
|---|---|---|---|---|
| Address | 1 | A, BE, START, WRITE | | |
| Data | d, more while the slave asserts WAIT | A, BE, D | SEL, WR, BUSY, W32, BACK; RDY from clock d on if r = 0 | WAIT |
| Recovery | r | A, BE, D | SEL, BUSY; RDY in the last one | |

A synchronous slave takes the data at the end of the transfer, a simple
slave at the end of WR.

**Synchronous slaves** have r = 0 and usually d = 1, so a transfer is two
clocks. The strobes run alongside, and they ignore them.

### 5.4 The end of a transfer, and turnaround

- **The end.**
  - A transfer ends at the end of the first data or recovery clock in
    which RDY is asserted and WAIT isn't. The one exception is a burst,
    while BURST and BACK are both asserted ([section 7](#7-bursts-optional)).
  - Every card sees RDY and WAIT, so the master, the slave and the bus
    monitor agree on the end without counting anything themselves.
  - BERR also ends a transfer, with an error
    ([5.8](#58-bus-errors)).
- **Back to back.** The owner can start its next address clock in the clock
  right after the end.
- **Data lines** are only driven in data and recovery clocks: by the slave
  in a read, by the master in a write, until just after the end. The next
  transfer's address clock is a clock in which nobody drives them. So
  transfers never clash on D, and read-to-write turnaround needs no extra
  clock.
- **WAIT** is the only line that slaves share.
  - The addressed slave drives it from its first data clock to the end. It
    is inactive in the last clock, and the slave lets go just after the
    end.
  - The weak pull-up then holds it inactive.
  - The next slave starts driving it in its own first data clock, a clock
    later.
- **Every other line** has one driver at a time: the backplane's lines
  always, and the owner's lines while the master owns the bus
  ([section 6](#6-arbitration)).

The first draft had no visible end. The master counted wait states from
its own table, which the slave couldn't see. So whenever the table asked
for more clocks than a slave would have taken, the slave stopped driving
too early. That happened at boot, when every slot got the maximum. Also, a
slave let go of WAIT at the same edge where the next slave started to drive
it.

### 5.5 Wait states and recovery

- **D**, from the map: the number of data clocks with the strobe asserted,
  1–16. It is the minimum for every transfer to the page.
- **WAIT**, from the slave: adds data clocks, for variable delays: a FIFO
  running dry, a busy memory, a slave port waiting for its CPU's RAM.
  - The data phase ends at the first clock at or after clock d in which
    WAIT is inactive.
  - A slave can raise WAIT in its first data clock: SEL arrives about 10 ns
    into it ([section 4](#4-clock-and-timing-conventions)).
- **R**, from the map: recovery clocks after the strobe, 0–3.
  - The owner keeps the address, and in a write the data, on the bus
    through them. So a simple slave sees its strobe end a whole clock
    before anything else on the bus changes.
  - Simple slaves need R ≥ 1; synchronous slaves have R = 0.
- **The bus monitor** on the backplane asserts BERR if WAIT stays asserted
  for 256 clocks, so a stuck slave can't hang the system.

### 5.6 Simple slaves and the strobes

The backplane drives RD or WR in every transfer, from the start of the
first data clock to the end of the data phase. Synchronous slaves ignore
them.

| | Asserted | Released | Guarantees |
|---|---|---|---|
| RD | start of the first data clock | end of the data phase | address stable a whole clock before RD and r clocks after it |
| WR | start of the first data clock | end of the data phase | address stable a whole clock before WR; address and data stable r clocks after it; data valid from early in the first data clock |

**SEL** for the addressed slot is asserted with the strobes, about 10 ns
into the first data clock, and released at the end of the transfer.
Another slot's SEL only appears in the next transfer's first data clock, at
least r + 1 clocks after the strobe ended. So a strobe never overlaps
another card's select or an address change.

The first draft released RD at the edge where a back-to-back transfer puts
out its next address. With RD's slow edge, the next card's select arrived
while RD was still asserted: a false read, which can lose a UART character.

**Timing of a simple card**, at T = 60 ns:

- **The strobe:** it reaches the card about 40 ns into the first data clock,
  since its slow edge ([section 9](#9-electrical-rules)) takes up to about
  30 ns. A 74HCT14 adds about 15 ns.
- **Time left for the card:** the data has to reach the master by the end of
  clock d, and the backplane and the master take about 20 ns of that. That
  leaves the card about d × 60 − 80 ns from its 74HCT14's output to its
  data on the bus: 40 ns with d = 2, 100 ns with d = 3.
- **Example:** a 16C550 behind a 74HCT245 needs d = 3. With r = 1, a
  transfer is 5 clocks, 300 ns.

**What a simple card does:**

- It enables its data drivers with SEL and RD, and writes with SEL and WR.
- It puts 8-bit registers on D0–D7 at addresses 4 bytes apart, and 16-bit
  ones on D0–D15, 4 apart. Software uses byte or halfword accesses. Its
  pages are 16 bits wide, so a master splits a word access.

### 5.7 Data width and byte lanes

**recommended.**

- **Halfwords and bytes always travel on D0–D15**, for every master and
  every slave. A1 picks the halfword; BE0 and BE1 pick its bytes.
- **Words** travel on D0–D31 when the page is 32 bits wide, which the
  backplane signals with W32, from the map:
  - A1 = 0 and BE0–BE3 pick the bytes;
  - bytes 0–1 are on D0–D15, bytes 2–3 on D16–D31.

  BE2 and BE3 are only asserted in a word transfer. Their pull-ups keep
  them inactive while a master that uses only P1 owns the bus.
- **A word to a 16-bit page:** the master sees W32 inactive at the end of
  the first data clock, so it knows only D0–D15 moved. It repeats the high
  half at A1 = 1, also on D0–D15.

| Access by a 32-bit master | 32-bit page (W32) | 16-bit page |
|---|---|---|
| Byte or halfword | D0–D15 | D0–D15 |
| Word | D0–D31, one transfer | low half, then the high half at A1 = 1, both on D0–D15 |

**What each card needs:**

- A **16-bit slave** uses P1 only.
- A **32-bit slave** connects the upper half of its data to D16–D31 for
  words, and to D0–D15 for halfwords and bytes at A1 = 1. That takes one
  swap transceiver, a 74ABT16245 or two 74ABT245. In return, a master that
  uses only P1 can use it like any 16-bit slave.
- A **32-bit master** does the same swap for its own upper half.
- A **16-bit master**, like the draft 1b CPU with its 16-bit memory bus,
  uses P1 only and does two transfers per word.

The first draft put a halfword at A1 = 1 on D16–D31 for 32-bit slaves. A
master that uses only P1 can't see those lines, so the main CPU couldn't
have reached half of a 32-bit card.

### 5.8 Bus errors

BERR ends a transfer with an error. On the draft 1b CPU it becomes a trap
next to the address error.

- **Only the backplane drives BERR**, so no two drivers ever fight over it.
- **Unmapped pages:** BERR in the first data clock for a page whose entry
  has V clear. While the map is off, that's every page except the
  backplane's own ([section 8.1](#81-reset-and-the-backplanes-page)). SEL
  and the strobes stay inactive.
- **Timeouts:** BERR when WAIT has been asserted for 256 clocks.
- **Slaves see BERR too**, and let go at the end of the transfer, as at
  any other end.
- **Empty slots:** every card ties its PRESENT pin to ground, and software
  only maps slots that have a card. So there's no separate check for an
  empty slot.
- **Errors inside a card** (an unmapped address in its window, a parity
  error) are the card's business: it can ignore the access or raise an
  interrupt.

Earlier drafts had slaves claim each transfer on a shared line. A simple
card can only release such a line, not drive it high again, and a 10 kΩ
pull-up takes microseconds to restore it on a loaded backplane.

## 6. Arbitration

- **Requests and grants.**
  - Each slot has its own REQ and GNT to a round-robin arbiter on the
    backplane.
  - The arbiter is synchronous: it samples REQ at each edge and changes GNT
    just after.
  - It only moves GNT at the edge that ends a transfer, or at an edge with
    no transfer under way (START and BUSY inactive). It never moves GNT
    while LOCK is asserted.
- **Owning the bus.**
  - The master with GNT owns the bus.
  - It drives the owner's lines (A, BE, START, WRITE, LOCK, BURST, BFIX)
    the whole time it has GNT, whether or not it is running a transfer. So
    they don't float while the bus is parked.
- **Starting.**
  - The owner can start an address clock after any edge at which it
    sampled GNT, once its previous transfer has ended.
  - A master that has just been granted waits until it has sampled GNT
    asserted at two edges in a row, with START and BUSY inactive at the
    second. Then it starts driving.
  - The arbiter can move GNT just as the old owner starts another transfer.
    START and BUSY then show the new owner that the bus is still in use.
- **Handing over.**
  - The old owner stops driving its lines just after the first edge at
    which it samples GNT inactive with no transfer of its own under way.
  - The new owner starts a clock later, so there's always a clock with
    nobody driving those lines, and the pull-ups hold START, WRITE and LOCK
    inactive through it.
  - From a request on an idle bus to the first address clock takes 3
    clocks.
- **Parking.** While nobody else asks, GNT stays with the last owner,
  normally the main CPU, so it can start transfers with no arbitration
  delay.
- **Fairness.** When another master asks, the arbiter moves GNT after the
  owner's current transfer. A burst counts as one transfer, at most 16
  words. The old owner may squeeze in one more transfer at the edge where
  GNT moves.
- **LOCK.** **optional**: the hardware semaphores
  ([section 8.3](#83-interrupts-and-synchronisation)) don't need it.
  - The owner holds LOCK across a read-modify-write, and the arbiter
    doesn't move GNT while it's asserted.
  - A slave with a second way into its memory, like a CPU board's slave
    port, must keep that way out too, from the first locked transfer to it
    until LOCK is released. Otherwise the read-modify-write isn't atomic.
- **Deadlock rule** for CPU boards with slave ports. A CPU stalled waiting
  for the bus must still let its slave port use its RAM. Otherwise two
  CPUs can wait for each other forever.

## 7. Bursts (optional)

**optional.** A master or slave without bursts never drives BURST or BFIX,
and the map marks its pages without BST. Pull-ups keep BURST and BFIX
inactive, and everything still works with single transfers. The pins are
reserved on P2.

```
clock      | address  | data    | data    | data    | data    |
A, START   | A        |         |         |         |         |
BURST      | asserted | asserted| asserted| asserted| off     |   (master) another word follows
BACK       |          | asserted| asserted| asserted| asserted|   (backplane) the page takes bursts
RDY        |          | asserted| asserted| asserted| asserted|   (backplane)
D          |          | D(A)    | D(A+4)  | D(A+8)  | D(A+12) |
```

- **BURST.** The master asserts it in the address clock and in every data
  clock except the last word's.
- **BACK.** The backplane asserts it from the first data clock when the
  page's entry has BST. Without BACK the master stops after the first word
  and carries on with single transfers.
- **Words.** One word moves at the end of each data clock in which RDY is
  asserted and WAIT isn't. A burst page has D = 1 and R = 0.
- **Addresses.** The slave counts the address up itself: by 4 on a 32-bit
  page, by 2 on a 16-bit one.
- **BFIX**, asserted with BURST in the address clock, keeps every word at
  the same address. That's for FIFOs, like the Ethernet card's packet
  buffer or a disk controller's data port.
- **Limits.**
  - At most 16 words, and a burst never crosses a 16-word aligned block,
    so a slave needs a 4-bit counter.
  - The master learns W32 at the end of the first data clock. On a 16-bit
    page the block is 32 bytes, so the master ends the burst at that
    boundary.
- **WAIT** works on any word.
- **Cost on a memory card:** a loadable counter (74ACT163) driving the low
  SRAM address bits. The path, counter to SRAM to backplane to master, is
  about 45–55 ns, so a word per clock fits at 60 ns with 15–20 ns SRAM.

| At T = 60 ns | Clocks | Per word |
|---|---:|---:|
| Burst of 4 | 5 | 75 ns |
| Burst of 16 | 17 | 64 ns |

**Not adopted: pipelined addresses**, where the master sends a new address
every clock while the previous word's data moves, as the 386's pipelined
mode does. Slaves wouldn't need counters and addresses needn't be
sequential, but every pipelining slave, and the backplane's map, must
accept an address every clock. Counters are simpler for memory-like cards.

## 8. Reset, configuration, interrupts and synchronisation

### 8.1 Reset and the backplane's page

- **RESET** is open collector with slow edges. Cards receive it through a
  Schmitt trigger. The backplane's power-on reset and the main CPU drive it.
- **After reset the map is off.** Every access gets BERR except accesses to
  the backplane's own page, 0xFFFE0000–0xFFFFFFFF, which the map never
  covers.
- **The backplane's page.** 16 bits wide; reads take two data clocks,
  writes one.

  | Address | Register |
  |---|---|
  | 0xFFFE0000 + 2n | the entry for page n (n = A31–A17 of the page's addresses), read and write |
  | 0xFFFF0000 | control: bit 0 turns the map on, and is 0 after reset |
  | 0xFFFF0002 | PRESENT: bit n is set if slot n has a card; read only |

  The entry for the last page (n = 32,767) is never used.

### 8.2 Configuration

At boot, software:

1. reads PRESENT;
2. clears the map, writing V = 0 to all 32,768 entries. That takes about
   4 ms of bus time at 60 ns;
3. gives each slot n that has a card a boot window: 16 MB at
   0xF0000000 + n × 16 MB, 16 bits wide, with the slowest timing (D = 16,
   R = 3) and no bursts. Then it turns the map on;
4. reads each card's ID from the start of its boot window;
5. writes the real map from the IDs, and removes the boot windows.

**Card IDs: open.** Each card needs something at a fixed place in its
window that says what it is.

- **The simplest:** an 8-bit type code, read as a byte at offset 0, from a
  74HCT541 with straps on a simple card. Software looks the type up to get
  the card's window size, timing, width and driver.
- **Still to decide:** whether memory cards give up that word, and what
  larger cards add.

Cards that want to know their slot number can read it from GA0–GA3 on P2.

### 8.3 Interrupts and synchronisation

- **Eight interrupt lines**, IRQ0–IRQ3 on P1 and IRQ4–IRQ7 on P2: open
  collector, level-sensitive. Each card picks its line with a jumper; each
  CPU listens to its own subset through its priority encoder.
- **Doorbells.** A write to a register in a CPU board's window interrupts
  that CPU.
- **Hardware semaphores.** A read returns the old value and sets the
  semaphore (test-and-set on read), so CPUs without a locked
  read-modify-write can share them. Sixteen of them. Where they live is
  **open**: on the main CPU board, or in the backplane's page, where every
  master finds them at a fixed address.
- **A control register per CPU** for reset/run and NMI. One CPU can boot
  another by loading its RAM through its slave port and releasing its
  reset.

## 9. Electrical rules

From the signal-integrity simulations: 16 slots, 25 mm card stubs, an
estimated 12 nH and 2 pF per connector contact, TI IBIS models.
**recommended.**

**The backplane:**

- 4 layers (signal, ground, +5 V, signal).
- 0.2 mm traces: 67.5 Ω and 5.8 ps/mm bare (field-solved). Loaded with 16
  cards, a bused line is about 24–29 Ω and 13.5–16 ps/mm, about 5 ns from
  end to end.
- **Active parts on the backplane: decided.**

  | Part | Chips |
  |---|---:|
  | The address map ([5.1](#51-the-address-map)) | ~17 |
  | Transfer timing: counters for D and R, the state, output registers and drivers | ~8 |
  | Control and PRESENT registers | ~3 |
  | Bus monitor | ~3 |
  | Arbiter, 16-way round robin | ~10 |
  | Clock buffer, power-on reset | ~4 |
  | **Total, in plain 74-series** | **~45** |

  With half a dozen GALs it would be about 25. Whether PLDs are allowed is
  **open**. That's a lot of logic on a board that's hard to replace; a
  module on its own connector at the back of the backplane would keep it
  replaceable.

**No resistor terminators on bused lines:**

- 74HCT and 74AHCT can't pull a line low against them: the low level was
  0.66–1.19 V, against the 0.8 V threshold.
- They'd burn about 8–12 W across ~86 lines.
- With ABT or ACT drivers, falling edges ring back above 0.8 V for about
  30 ns. The line resonates as a whole, since 194 Ω terminators barely load
  a 26 Ω line.

**22 Ω in series at every bus driver output**, or parts with built-in
series resistors such as the 74ABT2245. With ABT drivers it lowers the
peak from 6.0 to 4.4 V and the dip below ground from −0.9 to −0.45 V, and
cuts extra threshold crossings from 8 to 2. It costs about 2 ns of
settling.

**Bus drivers:**

- Synchronous cards and the backplane use 74ABT or 74FCT-T (reduced swing,
  high level about 3.3 V).
- 74ACT isn't recommended as a bus driver: it overshoots to about 7 V and
  undershoots to −1.4 V.
- 74HCT is fine on simple slaves.

**One load per card on each bused signal:** a transceiver or one or two
inputs, at most 25 mm from the connector (as simulated).

**RD, WR and RESET** must give clean edges to cards that act on the edges:

- 33 Ω + 220 pF to ground at both ends of the backplane, on top of the
  series resistors. That leaves 0–2 extra crossings and no dip below
  ground, at the cost of about 20–30 ns slower edges, which the strobe
  timing allows for ([5.6](#56-simple-slaves-and-the-strobes)). RD and WR
  are driven only by the backplane.
- Schmitt-trigger receivers (74HCT14) on simple slaves.
- Ground pins on both sides.

**BCLK:**

- An ABT buffer with 56–68 Ω series resistors: peak about 4.5 V, dip −0.1
  to −0.5 V.
- No threshold re-crossing at any slot in any simulated case. Matched trace
  lengths are optional.

**SEL and GNT** are point-to-point from the backplane's registers, like
BCLK, and need series resistors like it. They haven't been simulated.

**Lines without a driver:**

- **Pull-ups.** WAIT, START, WRITE and LOCK on P1, and BE2, BE3, BURST and
  BFIX on P2, have a weak (10 kΩ) pull-up for when nobody drives them.
- **Pull-ups only hold.** On a loaded line (150–250 pF) a pull-up would take
  microseconds to bring the line back up, far more than a clock. So the
  rules in [5.4](#54-the-end-of-a-transfer-and-turnaround) and
  [section 6](#6-arbitration) make sure each of these lines is driven
  inactive before it is let go.
- **Address and data lines** float between owners and outside data
  clocks. **recommended:** bus-hold inputs (74ABTH parts) on the backplane,
  or weak pull-ups, so they don't drift to mid-rail and make every receiver
  draw current. Nothing samples them while they float.
- **The backplane's own lines** (RD, WR, RDY, BUSY, BERR, W32, BACK, SEL,
  GNT, BCLK) are always driven.

**Interrupt lines:** open collector, one 1 kΩ pull-up each. They're slow
(~250 ns to rise), which is fine since every CPU synchronises them.

**Crosstalk.** Two neighbours switching put 1–2 V spikes on a quiet line
through the connector contacts' coupling. This is harmless on lines
sampled at a clock edge, as they're quiet again by then. It's why RD, WR,
RESET, BCLK and SEL get ground pins either side.

**Simulated settling, 16 slots,** worst case over driver positions, both
corners and the receivers on every other card. "Added delay" is on top of the datasheet
propagation delay:

| Driver, termination | Added delay, rise / fall | Peak / lowest voltage | Extra threshold crossings |
|---|---|---|---|
| ABT, 22 Ω series | 9 / 11 ns | 4.4 / −0.45 V | 2 |
| FCT-T, 22 Ω series | 10 / 10 ns | 4.1 / −0.4 V | 4 |
| HCT, 22 Ω series | 8 / 14 ns | 5.7 / −0.3 V | 2 |
| ABT, none | 7 / 9 ns | 6.0 / −0.9 V | 8 |
| ABT, 330/470 Ω (VME) | 5 / 26 ns | 5.7 / −0.9 V | 4 |
| ABT, series + 33 Ω + 220 pF (strobes) | 22 / 31 ns | 4.0 / +0.2 V | 0 |

With 8 slots, the delays without the RC network are about half. With it
they barely change: 18 / 26 ns for ABT.

**Not settled yet:**

- **Ground bounce.** The simulation model is numerically unreliable. Until
  it's fixed: decouple every bus chip, and prefer SOIC or flow-through
  parts (such as the 74ABT16245, with many ground pins) for wide drivers.
- **Gaps in the sweep.** 39 of the 840 bus-line runs failed, mostly with
  series resistors on 16 slots. Every driver position still has at least
  one corner covered: 12–15 of the 16 position and corner runs finished.
- **Driver models.** TI's ABT, FCT and HCT models disagree with themselves.
  The simulation follows the waveforms through the edge and the V-I tables
  for the levels.
- **Card size.** The simulations assumed 6U cards at a 20.32 mm pitch with
  25 mm stubs. Once the card size and the backplane's layout are settled,
  the affected cases need rerunning.
- **Power.** No −5.2 V on the backplane. A higher supply voltage, such as
  +12 V, may come: **open**.

## 10. The main CPU board on the bus

**Addresses.** On the draft 1b CPU, MAR bit 31 set means "system bus". MAR
bits 30–0 drive A30–A0, and A31 is 1. So the CPU sees the top 2 GB of the
bus, which includes the backplane's page, and software maps the cards it
uses there. A later CPU with an MMU can produce full 32-bit bus addresses.

**If the bus clock comes from the CPU board** (one of the options in
[section 4](#4-clock-and-timing-conventions)):

- **No synchroniser.** The draft 1b CPU's cycles are whole numbers of
  20 ns ticks of the 50 MHz master clock
  ([RFC 0007, section 4](0007-rfc-ideas-microarchitecture.md#4-microarchitecture)).
  The bus clock is the same clock divided by N, N = 3 for 60 ns. So the CPU
  always knows the phase of the next bus clock edge.
- **A bus access is one stretched microcycle.** A read starts at tick
  $t_0$. The address clock starts at the first bus clock edge $E$ at least
  a tick later, which gives MAR and its decode time to settle. For a
  two-clock transfer, the data is in a CPU register about two ticks after
  the data clock ends:

  $$t_\text{read} = (E - t_0) + 2N + 2 \text{ ticks}, \quad 1 \le E - t_0 \le N$$

  At N = 3 that's 200 ns on average (180–220).

  That's about one ordinary microcycle with HCT parts, two with ACT.
  Waiting for the next bus clock edge costs 1.5–2.5 ticks per access on
  average. That doesn't matter, because RAM is private and the bus only
  carries I/O and remote accesses. The CPU's cycle lengths never need to
  be multiples of the bus clock. **recommended.**

**If it comes from an oscillator on the backplane**, the CPU synchronises
to it, which costs about 20–40 ns per access
([RFC 0008](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses)).

Either way:

- **No wait-state table, no strobes.** The bus interface runs the address
  clock, holds the address, and watches RDY, WAIT, RD, W32 and BERR. The
  backplane does the rest.
- **Posted writes.** Registered bus transceivers (74ABT652 or 646) take the
  address and data at the end of an ordinary microcycle. The bus interface
  finishes the write on its own, so the CPU only waits if it reaches the bus
  again before then.
- **Bus parking and early request.** The bus normally stays parked on the
  main CPU. When it isn't, the pipelined microcode tells the bus interface
  a cycle ahead that the next microinstruction uses the bus. It requests
  then, and the arbitration delay is mostly hidden.
- **The returned clock.** The bus interface runs on the board's BCLK pin,
  like every other card. With the bus clock from the CPU board, that's
  about 4 ns behind the internal phase it was divided from: a fixed skew
  between two clocks from one source, easy to check in the timing
  analysis. Driving the bus from the internal phase would eat the hold-time
  margin.

**The slave port shares the RAM by ticks, not cycles:**

- **When the CPU uses the RAM.** Half the CPU's cycles don't touch it:
  fetch is 25% of executed cycles, reads 20%, writes 5%. With pipelined
  microcode, the RAM arbiter knows about 40 ns into each cycle whether the
  next one uses the RAM, and when it starts.
- **Freeing the RAM early.** A data latch (2 × 74ACT573 on the 16-bit
  memory bus) frees the RAM about 4 ticks into a memory cycle, instead of at
  its end. It adds a few ns to the fetch path, which is at 309 ns against
  the 334 ns multiply step.
- **What other masters get.** The RAM is then busy roughly 15% of the time,
  so most slave-port accesses get it straight away. A collision costs a
  bus clock (the slave raises WAIT), or the CPU's cycle stretches by a tick
  instead.
- **Timing.** The RAM is 55 ns, so at 60 ns the slave port's pages get
  D = 2: 180 ns per transfer. Other masters reach the CPU's RAM in about
  180–320 ns, instead of 300–600 ns with whole-cycle stealing. The CPU's
  RAM becomes usable as a DMA buffer.

## 11. Other CPUs as masters

A CPU with its own bus timing, like a Z80 or a 68000, can be a master
through a small **bridge** on its card. **recommended** as the way to
attach them. The bridge turns the CPU's own bus cycles into bus transfers:

1. The CPU starts a cycle in an address window mapped to the system bus.
2. The bridge holds the CPU: WAIT on a Z80, DTACK withheld on a 68000.
3. It synchronises the request to BCLK with two flip-flops (1–2 clocks),
   requests the bus unless it's parked there, and runs an ordinary
   transfer, with lane steering.
4. It releases the CPU, with read data latched.

**Cost:**

- About 4–6 bus clocks per access: 250–400 ns at 60 ns. That's a few wait
  states to a 4–8 MHz CPU.
- About 12–15 chips: the synchroniser and a small state machine, a bank
  register for the window, transceivers and lane steering. The bridge needs
  no wait-state table and no strobes. A GAL or two would shrink it a lot.

**Z80:**

- 8-bit data and 16-bit addresses. A window, say the top 16 KB of memory,
  or a range of I/O ports, maps to the bus through a bank register that
  supplies A31–A14. So it can reach anywhere, 16 KB at a time.
- Little-endian like the bus. A byte goes on D0–D7 or D8–D15 according to
  its address bit 0, so the card steers the lanes with two transceivers. It
  is a P1-only master doing single transfers.
- WAIT must reach the Z80 before the falling clock edge in T2, about 60 ns
  after the address is valid at 8 MHz. The window decode needs 74ACT or 74F
  gates.
- Interrupts: one bus IRQ line into INT, mode 1 or with a vector from the
  card.
- Optional: other masters can reach the Z80's RAM by taking its local bus
  with BUSREQ/BUSACK.

**68000:**

- Its asynchronous bus fits best: the bridge just withholds DTACK until the
  transfer is done.
- 16-bit data and 24-bit addresses. A window, say the top 8 MB, maps
  through a bank register. It is a P1-only master.
- BERR goes straight to the 68000's own BERR input, so bus errors become
  68000 exceptions.
- TAS (an indivisible read-modify-write) maps onto LOCK, which is on P1 so
  16-bit masters can use it.
- **Byte order.** The 68000 is big-endian: a byte at an even address
  travels on D8–D15.
  - Wiring its D8–D15 to the bus's D0–D7 makes bytes at the same address
    match, but 16-bit words look byte-swapped to the 68000, as with ISA
    cards on an Atari.
  - Straight wiring makes words match, but byte addresses differ in bit 0.

  A swap bit in the bank register can pick per window: swapped for
  peripherals and text, straight for 16-bit data.
- Interrupts: a priority encoder from the bus IRQ lines to IPL0–IPL2.
- A 68020 or 68030 is a 32-bit master. Its dynamic bus sizing (DSACK0/1)
  can be driven from W32: with W32 it's a 32-bit port, without it 16-bit.
  The bridge steers the lanes, since the 68020 expects a 16-bit port on its
  upper data lines.
- Optional: other masters can reach its RAM through BR/BG/BGACK.

## 12. Rejected: a separate I/O bus

**rejected** (Emily, 2026-10-13): simple peripherals go on the system bus.
The idea and its arguments are kept here, so it isn't proposed again
without new evidence.

A bridge card would have run a slow, separate I/O bus for simple
peripherals:

- 8 data bits, about 12 address bits, 8080-style read and write strobes;
- interrupt lines;
- its own small backplane with cheaper connectors: 3U cards with 64-pin
  DIN 41612 connectors, or RC2014-style headers.

| For | Against |
|---|---|
| The system bus carries only fast cards: fewer loads, cleaner edges, perhaps a faster clock | One more card (~10–15 chips) and a second backplane and card format |
| No strobes on the fast backplane | Every I/O access crosses the bridge: about two system-bus transfers plus the I/O cycle |
| The I/O bus can be as slow as needed (~500 ns), on 2-layer cards, with chips that want odd timing (6800-style E clock, Z80 peripherals) | DMA to simple devices has to go through the bridge |

## 13. Open questions

1. The bus clock period (60 ns for now), and whether the clock comes from
   the main CPU board or an oscillator on the backplane.
2. The card size and how the system splits into cards. These wait until
   the design is closer to completion. Two 96-pin connectors are decided.
   One idea for then, full-width and half-width slots, is in
   [RFC 0008](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses).
3. May the design use PLDs (GALs)? The backplane's logic is about 45 chips
   without them and about 25 with them, and the bridges shrink too.
4. A higher supply voltage on the backplane: which one, and on which pins.
   P1 has four reserved pins, and P2 has room.
5. The pin-by-pin assignment of P1 and P2.
6. Ground bounce, once the model is fixed: which packages and parts for the
   wide bus drivers.
7. Card IDs: what they hold and where they are
   ([section 8.2](#82-configuration)).
8. The page size of the map (128 KB recommended), and what the three
   reserved bits of an entry are for. Write protection is one candidate.
9. Where the hardware semaphores live: on the main CPU board or in the
   backplane's page.
10. The card-edge timing values and the skew budget
    ([section 4](#4-clock-and-timing-conventions)).

## 14. Decisions

Emily has decided:

- the bus is synchronous: one bus clock, every signal sampled on its rising
  edge;
- simple, dumb peripherals must be possible;
- bus addresses are the full 32 bits;
- burst transfers are optional;
- two connectors per slot, with P1 enough for a simple peripheral.

And on 2026-10-13:

- two 96-pin connectors per slot. The card size, and how the system is
  split into cards, wait until the design is closer to completion (6U
  Eurocards had been marked as decided);
- the bus clock isn't decided: it is a variable for now, with 60 ns as the
  starting point;
- the mapping from addresses to slots, and from addresses to wait states,
  is held in RAM on the backplane;
- simple peripherals go on the system bus, and the separate I/O bus idea is
  closed;
- active parts on the backplane are fine;
- no −5.2 V on the backplane, though it may carry a higher voltage;
- the ECL number cruncher is deprioritised: it may not happen.
