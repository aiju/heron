---
number: 14
type: rfc
title: System bus
status: open
date: 2026-10-14
context:
  studies: [bus_si, v1b_hw]
  commit: 1470409
---

# RFC 0014: System bus

The backplane bus shared by the main CPU, other CPUs, DMA engines and
peripherals. This RFC has three parts:

- **[Part 1](#part-1-the-specification)** is the specification. It's
  meant to be read on its own, by someone designing a card or the
  backplane.
- **[Part 2](#part-2-rationale)** gives the reasons for each choice in
  Part 1, with the timing budgets and the signal-integrity results behind
  them.
- **[Part 3](#part-3-open-questions-ideas-and-signal-integrity-work)**
  lists the open questions, the ideas still open, the ideas rejected and
  why, and the signal-integrity work still to do.

[Section 18](#18-decisions) records what Emily has decided.

Statuses: **decided** (Emily chose it), **recommended**, **open**,
**optional** for features a card may leave out, and **rejected**. Anything
in Part 1 without a status is recommended.

The electrical figures come from simulations of the backplane with TI's
IBIS models ([studies/bus_si](../studies/bus_si/README.md);
[report 0013](0013-report-bus-si.md), and
[report 0022](0022-report-bus-si-revised.md) for the revised bus). The datasheet delays in the timing
budgets are rough worst-case figures and need checking against the parts
actually used.

**Revised on 2026-10-13 and 14.** The main changes since the first draft:

- **Timing:** the backplane times every transfer from straps on each card.
  Masters lose their wait-state tables and strobe logic.
- **Strobes:** SEL is the strobe for simple cards; the bused RD and WR
  strobes are gone.
- **The end of a transfer** is visible on the bus (RDY and WAIT).
- **Bus mastering** is withdraw-then-grant, with no BUSY line.
- **No bursts;** halfwords always travel on D0–D15.
- **Fixes from reviews:** turnaround rules, a recovery clock for simple
  cards, a loading rule, skew and hold time, and LOCK with slave ports.
  Part 2 explains each.

## Contents

- [Part 1: The specification](#part-1-the-specification)
  1. [Overview](#1-overview)
  2. [Cards and the backplane](#2-cards-and-the-backplane)
  3. [Signals](#3-signals)
  4. [Clock and timing](#4-clock-and-timing)
  5. [Transfers](#5-transfers)
  6. [Simple cards](#6-simple-cards)
  7. [Bus mastering](#7-bus-mastering)
  8. [Reset, card IDs, interrupts and synchronisation](#8-reset-card-ids-interrupts-and-synchronisation)
  9. [Electrical rules](#9-electrical-rules)
  10. [The main CPU board on the bus](#10-the-main-cpu-board-on-the-bus)
  11. [Other CPUs as masters](#11-other-cpus-as-masters)
  12. [Example cards](#12-example-cards)
- [Part 2: Rationale](#part-2-rationale)
  13. [Why the bus looks like this](#13-why-the-bus-looks-like-this)
- [Part 3: Open questions, ideas and signal-integrity work](#part-3-open-questions-ideas-and-signal-integrity-work)
  14. [Open questions](#14-open-questions)
  15. [Open ideas](#15-open-ideas)
  16. [Rejected ideas](#16-rejected-ideas)
  17. [Signal integrity](#17-signal-integrity)
  18. [Decisions](#18-decisions)

## Part 1: The specification

### 1. Overview

| | |
|---|---|
| Timing | **Synchronous**: one bus clock, BCLK; every signal changes just after a rising edge and is sampled at a later one. **decided** |
| Bus clock | Period T **open**. This RFC uses 60 ns (16.7 MHz); the shortest usable period is about 50 ns ([13.7](#137-timing-budgets)) |
| Address | 32 bits. Four address bits select one of 16 slots: A31–A28 for now (**tentative**) |
| Card classes | Two straps on each card say what it is: a simple card, or a fast 16- or 32-bit card. The backplane reads them and times the transfer. **decided** |
| Data | 16 bits on P1 (D0–D15), 32 bits with P2. Halfwords and bytes always travel on D0–D15 |
| Transfers | An address clock, a data phase, and for simple cards a recovery clock. A fast card takes 2 clocks (120 ns) unless it holds WAIT. A simple card takes N + 2 clocks, with N set on the backplane |
| Strobes | SEL, sent only to the addressed slot, is the strobe; WRITE gives the direction. No bused strobes. **decided** |
| Bus mastering | Any slot can be a master. A central arbiter on the backplane withdraws GNT from one master before granting another; fixed priority |
| Bursts | None. **decided** |
| Backplane | Active logic: slot decoding, the class straps, transfer timing, the arbiter, the bus monitor, the clock buffer and the power-on reset. **decided** |
| Cards | Two 96-pin connectors per slot (DIN 41612), up to 16 slots. P1 alone is enough for a simple card. Every card has an ID. **decided**. The card size waits until the design is closer to completion |

Peak rates at T = 60 ns:

| | Clocks | |
|---|---:|---:|
| Transfer to a fast card | 2 | 120 ns |
| 16-bit transfers | 2 | 16.7 MB/s |
| 32-bit transfers | 2 | 33 MB/s |
| Transfer to a simple card (N data clocks, 1 recovery clock) | N + 2 | 300 ns with N = 3 |

### 2. Cards and the backplane

A card can play several of these roles. A CPU board is a master and a fast
card (its RAM, for other masters).

**Master** (CPUs, DMA engines, bridges for other CPUs). Must:

- follow the bus-mastering rules ([section 7](#7-bus-mastering));
- run transfers: drive the address clock, then hold the address and
  WRITE until the transfer ends ([5.2](#52-the-phases-of-a-transfer));
- take read data at the end of each clock in which DPH is asserted and
  WAIT isn't; the last one counts;
- end the transfer at the first clock with RDY asserted and WAIT not, or
  with BERR ([5.3](#53-the-end-of-a-transfer-and-turnaround));
- split words for 16-bit cards and steer the byte lanes
  ([5.5](#55-data-width-and-byte-lanes));
- report BERR to its own processor.

**Fast card** (memory, a CPU board's slave port, the registers and buffers
of DMA, Ethernet or video cards). Straps itself as fast 16-bit or fast
32-bit. Must:

- register the address, BE and WRITE at the end of every address clock;
- answer while its SEL is asserted. A transfer is one data clock unless the
  card holds WAIT ([5.4](#54-wait));
- let go of D and WAIT at the end of the transfer, whether it ended with
  RDY or with BERR;
- use fast parts (74ABT or 74FCT-T) at its bus interface.

**Simple card** (UARTs, the CF card, an RTC, a parallel port, the front
panel). Straps itself as simple. Needs P1 only, no clock, no address
comparator and no WAIT logic. It makes its device's read and write strobes
from SEL and WRITE ([section 6](#6-simple-cards)).

**The backplane** decodes the slot from the address and reads that slot's
class straps. For every transfer it drives:

- SEL to the addressed slot;
- DPH, RDY and W32;
- BERR, on an error.

It also arbitrates, buffers the clock and resets the system
([section 9](#9-electrical-rules) for its parts).

### 3. Signals

Control signals are active low on the backplane. Signal names are given
without a suffix, and "asserted" means active.

**Topology:**

- **bused:** runs past every slot.
- **radial:** each slot has its own trace to logic on the backplane, on the
  same pin at every slot.
- **strapped:** fixed per slot or per card.

**Drive types:**

- **backplane:** always driven by the backplane's logic.
- **owner:** driven by the master that holds GNT ([section 7](#7-bus-mastering)), with a weak pull-up for the clock between owners.
- **3-state:** driven by the owner, or by the addressed card for read data,
  and otherwise floating.
- **shared:** driven by the addressed card, actively both ways, and held
  inactive by a weak pull-up otherwise.
- **OC:** open collector, with a pull-up on the backplane.

#### P1: the 16-bit bus

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D0–D15 | 16 | bused, 3-state | owner in a write, card in a read | data |
| A1–A31 | 31 | bused, owner | owner | address; the slot bits select the slot |
| BE0, BE1 | 2 | bused, owner | owner | byte enables ([5.5](#55-data-width-and-byte-lanes)) |
| START | 1 | bused, owner | owner | asserted in the address clock of each transfer |
| WRITE | 1 | bused, owner | owner | asserted for a write, from the address clock to the end of the transfer |
| LOCK | 1 | bused, owner | owner | keep the bus for a locked sequence ([7.3](#73-locked-sequences)) |
| DPH | 1 | bused, backplane | backplane | data phase: asserted in the data-phase clocks of every transfer |
| RDY | 1 | bused, backplane | backplane | the transfer may end in this clock ([5.3](#53-the-end-of-a-transfer-and-turnaround)) |
| WAIT | 1 | bused, shared | addressed fast card | add a data clock |
| BERR | 1 | bused, backplane | backplane | end the transfer with an error |
| CLASS0, CLASS1 | 2 | radial, strapped | card (ground or open) | what's in this slot ([5.1](#51-slots-and-card-classes)) |
| REQ | 1 | radial | master | bus request |
| GNT | 1 | radial | backplane | bus grant |
| SEL | 1 | radial | backplane | this slot is addressed; asserted in the data phase only. The strobe for simple cards |
| BCLK | 1 | radial | backplane | bus clock |
| RESET | 1 | bused, OC, slow edges | backplane power-on reset, main CPU | system reset |
| IRQ0–IRQ3 | 4 | bused, OC | any card | interrupt requests |
| reserved | 5 | | | first: ground pins beside SEL and WRITE; then a higher supply voltage or a third class strap (**open**) |
| +5 V, ground | 24 | | | |

#### P2: the upper half and extras

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D16–D31 | 16 | bused, 3-state | as D0–D15 | upper halfword of a word transfer |
| BE2, BE3 | 2 | bused, owner | owner | byte enables of the upper halfword, in word transfers only |
| W32 | 1 | bused, backplane | backplane | the addressed card is a fast 32-bit card |
| IRQ4–IRQ7 | 4 | bused, OC | any card | interrupt requests |
| GA0–GA3 | 4 | strapped | backplane | slot number, for cards that want to know it |
| CLKSRC | 1 | slot 0 only | main CPU board | clock into the backplane's buffer, if the bus clock comes from the CPU board (**open**) |
| +5 V, ground | ~16 | | | |
| user-defined | ~52 | | | private links between neighbouring cards |

#### Pin assignment rules

The pin-by-pin assignment is still to do. It must follow these rules:

- BCLK, SEL, WRITE and RESET each have a ground pin on both sides, in the
  row and across rows.
- Power and ground pins are spread along the connector, not grouped.
- The same signal is on the same pin at every slot. That includes the
  radial ones, which the backplane routes to its own logic.

### 4. Clock and timing

- **The period T is open;** 60 ns is the working value.
- **The clock source is open.** Either:
  - the main CPU board divides its 50 MHz master clock (÷ 3 for 60 ns) and
    sends it on CLKSRC, wired at slot 0 only, to the backplane's buffer;
  - or an oscillator on the backplane.
- **Distribution:** a clock driver on the backplane drives each slot's
  BCLK on its own trace, through a 56–68 Ω series resistor.
  - Every card clocks its bus logic from its own BCLK pin, through exactly
    one buffer.
  - The CPU board does this too, even when it supplies the clock.
- **When signals change:**
  - Every bused and radial signal changes just after a rising BCLK edge and
    is sampled at a later one.
  - Simple cards also act on the edges of SEL, and act on WRITE and RESET
    as levels.
- **Card-edge timing**, measured at the card's connector, from BCLK at its
  pin. **recommended** values. Report 0022 confirms the hold rule with
  ABT parts, and suggests 2.5 ns for skew
  ([section 17](#17-signal-integrity)):

  | Parameter | Meaning | Proposed |
  |---|---|---:|
  | T<sub>co</sub> max | outputs valid | ≤ 16 ns |
  | T<sub>co</sub> min | earliest change of an output | ≥ 3 ns |
  | T<sub>su</sub> | input setup | ≤ 8 ns |
  | T<sub>h</sub> | input hold | ≤ 1 ns |
  | T<sub>skew</sub> | between any two cards' BCLK, as their registers see it | ≤ 2 ns |

  They must satisfy:
  - **setup:** T<sub>co</sub> max + backplane settling (≤ 11 ns at 16
    slots) + T<sub>su</sub> + T<sub>skew</sub> ≤ T;
  - **hold:** T<sub>co</sub> min ≥ T<sub>h</sub> + T<sub>skew</sub>.

### 5. Transfers

#### 5.1 Slots and card classes

- **Slots.** Four address bits select one of 16 slots. They're A31–A28 for
  now, giving 256 MB per slot. That choice is **tentative**: they might
  move, for example to A30–A27.
  - The backplane decodes the slot during the address clock.
  - A card decodes only the address bits within its own region, and never
    compares addresses.
- **Classes.** Each card ties its two class pins to ground or leaves them
  open; the backplane pulls them up. **decided** (the encoding is
  recommended).

  | CLASS1 | CLASS0 | The slot holds | The backplane |
  |---|---|---|---|
  | open | open | nothing | asserts BERR in the first data clock |
  | open | ground | a simple card, 16 bits | gives it N data clocks, then a recovery clock |
  | ground | open | a fast 16-bit card | gives it one data clock, more while it holds WAIT |
  | ground | ground | a fast 32-bit card | the same, and asserts W32 |

- **N** is the same for every simple card, set by jumpers on the backplane.
  The slowest simple device sets it ([13.7](#137-timing-budgets)).

#### 5.2 The phases of a transfer

| Phase | Clocks | The owner drives | The backplane drives | The addressed card drives |
|---|---|---|---|---|
| Address | 1 | A, BE, START, WRITE | | |
| Data | fast: 1; simple: N; more while a fast card holds WAIT | A, BE, WRITE; D in a write | SEL, DPH; W32 for a fast 32-bit card; RDY in every data clock for a fast card | D in a read; WAIT (fast cards) |
| Recovery | simple cards only: 1 | A, BE, WRITE; D in a write | RDY | |

- **SEL and DPH** are asserted about 10 ns into each data-phase clock, and
  released just after the data phase ends. SEL comes from registered
  outputs, so it never glitches.
- **Address-clock sampling:** fast cards register A, BE and WRITE at the
  end of every address clock, addressed or not.
- **Read data:** the master takes it at the end of every clock in which DPH
  is asserted and WAIT isn't; the last one counts.
- **Write data:** a fast card takes it at the end of the transfer; a simple
  card when its strobe ends.

#### 5.3 The end of a transfer, and turnaround

- **The end.** A transfer ends at the end of the first clock in which RDY
  is asserted and WAIT isn't, or in which BERR is asserted. Every card sees
  these lines, so the master, the card and the bus monitor all agree.
- **Back to back.** The owner may start its next address clock in the
  clock right after the end.
- **D** is driven only in data and recovery clocks: by the card in a read,
  by the owner in a write. Both let go just after the end. The next address
  clock is a clock with nobody driving D, so transfers never clash on it.
- **WAIT** is driven only by the addressed fast card:
  - from its first data clock to the end of the transfer;
  - inactive in the last clock;
  - let go just after the end.

  The pull-up then holds it inactive until the next card drives it, a
  clock later.
- **Every other line** has a single driver at a time: the backplane's lines
  always, and the owner's lines as [section 7](#7-bus-mastering) says.

#### 5.4 WAIT

- A fast card asserts WAIT to add data clocks. Uses:
  - a CPU board's slave port while the CPU uses its RAM;
  - slow SRAM;
  - DRAM refresh;
  - a FIFO that's empty or full.
- The data phase ends at the first clock, at or after the last scheduled
  data clock, in which WAIT is inactive.
- SEL reaches the card about 10 ns into the first data clock. A card that
  decides from SEL can still raise WAIT in that clock ([13.7](#137-timing-budgets)).
- Simple cards never drive WAIT.
- **The bus monitor** on the backplane asserts BERR if WAIT stays asserted
  for 256 clocks.

#### 5.5 Data width and byte lanes

- **Halfwords and bytes always travel on D0–D15.** A1 picks the halfword;
  BE0 and BE1 pick its bytes.
- **Words** travel on D0–D31 in one transfer when W32 is asserted (the card
  is a fast 32-bit card):
  - A1 = 0 and BE0–BE3 pick the bytes;
  - bytes 0–1 are on D0–D15, bytes 2–3 on D16–D31.

  BE2 and BE3 are only asserted in word transfers; their pull-ups keep
  them inactive while a P1-only master owns the bus.
- **A word to a 16-bit card:** W32 stays inactive, so the master knows only
  D0–D15 moved. It repeats the high half at A1 = 1, also on D0–D15.
- **What each kind of card needs:**
  - a 16-bit card uses P1 only;
  - a 32-bit card puts the upper half of its data on D16–D31 for words, and
    on D0–D15 for halfwords and bytes at A1 = 1: one swap transceiver;
  - a 32-bit master does the same swap for its own upper half;
  - a 16-bit master uses P1 only, with two transfers per word.

#### 5.6 Bus errors

- **Only the backplane drives BERR.** BERR ends a transfer at the end of
  the clock in which it's asserted.
- **Empty slot:** both class pins open. BERR comes in the first data clock.
- **Timeout:** WAIT asserted for 256 clocks.
- **Errors inside a card** (an unused address in its region, a parity
  error) are the card's business: it can ignore the access or raise an
  interrupt.

### 6. Simple cards

**decided** (SEL as the strobe).

- **The strobe.** A simple card's SEL is asserted for exactly the N clocks
  of its data phase. The card makes its device's strobes from SEL and
  WRITE:
  - read strobe = SEL and not WRITE;
  - write strobe = SEL and WRITE.
- **Inputs.** The device's strobes come from Schmitt-trigger NAND gates (a
  74HCT132):
  - SEL and WRITE each go to at most two inputs on the card;
  - the device's chip select is tied active, or taken from address bits.
- **What the card can rely on**, at T = 60 ns:

  | | Guaranteed |
  |---|---|
  | Address and WRITE stable before the strobe starts | from the address clock: about 50–70 ns |
  | Strobe width | N clocks, less a few ns |
  | Address, WRITE and write data held after the strobe ends | the recovery clock: about 35 ns or more |
  | Time from the strobe starting to read data being needed at the card's connector | about N × 60 − 50 ns |

- **Byte lanes.** The card puts 8-bit registers on D0–D7, and 16-bit ones
  on D0–D15, at addresses 4 bytes apart. A master splits a word access into
  halfwords.
- **No:** no clock, no address comparator, no WAIT.

A UART card, for example, is a 16C550 and its crystal, a 74HCT245, a
74HCT132 and a 74HCT541 for its ID ([12](#12-example-cards)).

### 7. Bus mastering

**recommended.**

#### 7.1 The arbiter

- **Requests and grants:**
  - every slot has its own REQ and GNT;
  - the backplane pulls REQ up, so an empty slot never requests;
  - the arbiter asserts at most one GNT at a time.
- **What it knows:** at each edge it samples REQ and LOCK, and it knows
  whether a transfer is under way, since it saw START and it drives RDY and
  BERR.
- **Priority:** fixed, by slot number, the highest slot first. Slot 0, the
  main CPU, is lowest.
- **Parking:** when nobody requests, GNT goes to slot 0, or stays there. If
  slot 0 is empty, nobody is granted.
- **Switching** from owner P to master Q, where Q is the highest-priority
  master requesting, or slot 0 for parking when nobody requests. It happens
  when LOCK isn't asserted, and either Q has the higher priority or P isn't
  requesting:
  1. **Withdraw:** the arbiter deasserts P's GNT just after an edge E.
  2. **Wait:** until the first edge, from E + 1 on, at which no transfer is
     under way. P may have started one more transfer just after E, since it
     still saw GNT at E. The arbiter sees that transfer's START at E + 1 and
     waits for its end.
  3. **Grant:** it asserts Q's GNT just after that edge.

  So **GNT is only ever asserted on an idle bus that its last owner is
  letting go of.** A master never has to check whether the bus is busy.

#### 7.2 Masters

- **Request:** a master asserts REQ while it wants the bus. The main CPU
  needn't request while the bus is parked on it.
- **Start:** a master may start an address clock just after any edge at
  which it samples GNT asserted, once its own previous transfer has ended.
- **Drive:** a master drives the owner's lines (A, BE, START, WRITE, LOCK)
  from just after the first edge at which it samples GNT, for as long as it
  holds GNT, idle or not.
- **Let go:**
  - just after the first edge at which it samples GNT deasserted with no
    transfer of its own under way;
  - or, if one is under way, just after that transfer's end.

  START and LOCK are inactive by then, and the pull-ups hold them. The
  next owner starts driving a clock later, so the owner's lines always
  have a clock with no driver between owners.
- **Courtesy:** a master other than the main CPU deasserts REQ for at
  least one clock after every 16 transfers, so lower-priority masters get a
  turn. **recommended.**

From a request on an idle bus to the new owner's first address clock takes
3 clocks. Between transfers of different masters there's one idle clock.

#### 7.3 Locked sequences

LOCK keeps the bus for a read-modify-write. A multi-CPU system needs it.
**decided** (LOCK stays).

- **Starting:** the owner asserts LOCK in an idle clock, then starts the
  first locked transfer only if it still samples GNT at the next edge. If
  GNT has gone, the arbiter withdrew it at that same edge: the owner drops
  LOCK, lets go, and tries again when it's granted.
- **Holding:** the arbiter never withdraws GNT at an edge where it samples
  LOCK asserted. The owner deasserts LOCK after the end of its last locked
  transfer.
- **Length:** a locked sequence is a read-modify-write, at most 4
  transfers.
- **Slave ports:** a card with a second way into its memory, like a CPU
  board's slave port, keeps that way out from the first locked transfer
  addressed to it until LOCK is released.

#### 7.4 Deadlock and timeouts

- **Deadlock rule:** a CPU board stalled waiting for the bus must still let
  its slave port use its RAM. Otherwise two CPUs, each waiting for the
  other's RAM through the bus, can wait forever.
- **The backstop:** the bus monitor's WAIT timeout
  ([5.6](#56-bus-errors)) turns anything that slips through into a bus
  error instead of a hang.

### 8. Reset, card IDs, interrupts and synchronisation

#### 8.1 Reset

- **RESET** is open collector with slow edges. Cards receive it through a
  Schmitt trigger. The backplane's power-on reset and the main CPU drive
  it.
- **During and after reset:** the arbiter grants slot 0, and nothing on the
  bus needs setting up. Slots come from the address, and timing from the
  class straps.

#### 8.2 Card IDs

**decided:** every card has an ID. Software reads it at boot to learn
what's in each slot; an empty slot answers with BERR.

- **Format and place: open.**
- **The cheapest version, for an 8-bit simple card:** a 74HCT541 with
  straps. It drives D8–D15 whenever the card's read strobe is active, so
  any halfword read from the card returns the ID in its upper byte.
- **Cards with registers on D8–D15** put the ID at a fixed offset instead,
  for example offset 0 of their region.
- **Slot numbers:** cards that want theirs read GA0–GA3 on P2.

#### 8.3 Interrupts and synchronisation

- **Interrupts:** eight lines, IRQ0–IRQ3 on P1 and IRQ4–IRQ7 on P2. Open
  collector, level-sensitive. Each card picks its line with a jumper; each
  CPU listens to its own subset through a priority encoder.
- **Doorbells:** a write to a register in a CPU board's region interrupts
  that CPU.
- **Semaphores:** sixteen hardware semaphores, test-and-set on read, for
  CPUs that share data without locked sequences. Where they live is
  **open**.
- **CPU control:** each CPU has a control register for reset/run and NMI.
  One CPU boots another by loading its RAM through its slave port and
  releasing its reset.

### 9. Electrical rules

These come from the signal-integrity simulations
([13.8](#138-electrical-rules-and-the-simulations)).

- **The backplane:** 4 layers (signal, ground, +5 V, signal), 0.2 mm traces
  (67.5 Ω bare). Up to 16 slots at a 20.32 mm pitch, as simulated.
- **No resistor terminators** on bused lines.
- **22 Ω in series at every bus driver output**, or parts with built-in
  series resistors (74ABT2245).
- **Bus drivers:**
  - 74ABT or 74FCT-T on fast cards and on the backplane;
  - 74HCT on simple cards;
  - not 74ACT.
- **Loading.** On each bused signal, a card puts at most one transceiver
  pin, or up to three CMOS inputs close together. That's about 12 pF in
  all, within 25 mm of the connector. Report 0022 supports 12 pF, counting
  the card's trace, with traces up to about 50 mm
  ([section 17](#17-signal-integrity)).
  - The backplane's own logic follows the same rule: it takes the signals
    it uses (the slot bits, START, WRITE, WAIT, LOCK) through one buffer.
- **Radial lines** (BCLK, SEL, GNT) are driven from registers on the
  backplane through 33–68 Ω series resistors. At the card end they go to
  one buffer (BCLK) or at most three inputs close together (SEL, GNT).
- **SEL and WRITE** reach simple cards' logic only through Schmitt-trigger
  inputs.
- **RESET:**
  - open collector with a 1 kΩ pull-up;
  - 33 Ω + 220 pF to ground at both ends of the backplane;
  - Schmitt-trigger receivers.
- **Pull-ups (10 kΩ):**
  - WAIT, START, WRITE and LOCK on P1;
  - BE2 and BE3 on P2;
  - REQ and the class pins at the backplane end.

  They only hold a line. Every line that has them is driven inactive before
  it's let go, except WRITE, which nothing reads between transfers.
- **Floating lines:** A, BE0–1 and D float between owners and outside data
  phases. Weak pull-ups in resistor packs, or bus-hold parts (74ABTH), keep
  them from drifting to mid-rail. **open** which.
- **Interrupt lines:** open collector, one 1 kΩ pull-up each.
- **Decoupling:** every bus chip is decoupled. Until ground bounce is
  understood, prefer SOIC or flow-through parts (74ABT16245) for wide
  drivers.

**The backplane's logic** ([13.9](#139-the-backplanes-logic)): about 28
chips in plain 74-series, or about 13 with GALs. Whether PLDs are allowed is
**open**; Emily would rather not use them, though it isn't a definite no
(2026-10-15).

### 10. The main CPU board on the bus

Guidance for the main CPU board; not part of the specification proper.

- **Addresses.** How a CPU maps its own address space onto the bus is the
  board's business.
  - A 32-bit CPU might give the bus part of its address space and pass the
    slot bits straight through.
  - The draft 1b hardware's MAR only holds address bits 0–19 and 31, so it
    would need about two more chips to supply the slot bits.
- **Slot:** the main CPU sits in slot 0. The bus parks on it, so it starts
  most bus accesses with no arbitration delay.
- **If the bus clock comes from the CPU board**, the bus clock is the 50 MHz
  master clock divided by N (N = 3 for 60 ns), and the CPU always knows
  where the next bus clock edge is. A bus access is one stretched
  microcycle. A read starts at tick $t_0$, and the address clock starts at
  the first bus clock edge $E$ at least a tick later. For a two-clock
  transfer:

  $$t_\text{read} = (E - t_0) + 2N + 2 \text{ ticks}, \quad 1 \le E - t_0 \le N$$

  That's 200 ns on average at N = 3 (180–220 ns). The CPU's cycle lengths
  never need to be multiples of the bus clock.
- **If it comes from an oscillator on the backplane**, the CPU synchronises
  to it, which costs about 20–40 ns per access.
- **Posted writes.** Registered bus transceivers (74ABT652) take the
  address and data at the end of an ordinary microcycle; the bus interface
  finishes the write on its own.
- **Early request.** When the bus isn't parked on the CPU, the pipelined
  microcode tells the bus interface a cycle ahead that the next
  microinstruction uses the bus.
- **The slave port shares the RAM by ticks, not cycles.** The board straps
  itself as a fast 16-bit card.
  - A data latch frees the RAM about 4 ticks into each CPU memory cycle.
    The RAM is then busy roughly 15% of the time.
  - With 55 ns RAM the slave port holds WAIT for one clock: 180 ns per
    transfer, longer when it collides with the CPU.
  - It honours LOCK and the deadlock rule ([7.3](#73-locked-sequences),
    [7.4](#74-deadlock-and-timeouts)).

### 11. Other CPUs as masters

Guidance, not specification. A CPU with its own bus timing (a Z80, a
68000) can be a master through a small **bridge** on its card.

**How the bridge works:**
1. The CPU starts a cycle in a window mapped to the system bus.
2. The bridge holds the CPU: WAIT on a Z80, DTACK withheld on a 68000.
3. It synchronises the request to BCLK, gets the bus, and runs an ordinary
   transfer, with lane steering.
4. It releases the CPU, with read data latched.

**Cost:** about 4–6 bus clocks per access, 250–400 ns, and about 12–15
chips.

**Z80:**
- An 8-bit P1-only master.
- A window of its memory or I/O space maps to the bus through a bank
  register.
- A byte goes on D0–D7 or D8–D15 according to its address bit 0.

**68000:**
- A 16-bit P1-only master.
- Its BERR maps onto the bus's BERR, and TAS onto LOCK.
- It's big-endian, so a swap bit in the bank register picks straight or
  swapped byte order per window.
- A 68020 or 68030 is a 32-bit master. Its DSACK0/1 can be driven from W32,
  with the bridge steering lanes.

### 12. Example cards

Not part of the specification: rough chip counts, to check that the rules
allow cheap cards.

| Card | Chips | Notes |
|---|---:|---|
| UART | 4 + the 16C550 | 74HCT245 on D0–D7; 74HCT132 for the strobes; 74HCT541 with straps for the ID |
| 2 MB 32-bit memory, 10–15 ns SRAM | ~19 | 4 SRAMs, 4 address registers, 6 transceivers (low half, high half, swap), ~3 for control, a clock buffer, the ID. Never needs WAIT |
| 1 MB 16-bit memory as a simple card | ~7 | 2 SRAMs, 2 '245, a '132 and a '00 for the strobes and byte write enables, the ID. N clocks per transfer, no registers |
| DMA engine, 8 channels, microcoded | ~34 | channel state in a small SRAM, a 16-bit adder, a microsequencer, a 32-bit address register, data registers with halfword packing. About 3–5 MB/s from the CF card |

## Part 2: Rationale

### 13. Why the bus looks like this

#### 13.1 Synchronous

**decided.**

- **Against strobe-timed buses** (8080, Z80, ISA style): read and write
  strobes driven by whichever master owns the bus would be multidrop lines
  and the timing reference for every transfer. The simulations show fast
  multidrop edges ringing back through the threshold 2–14 times unless
  slowed by 20–35 ns.
- **Against fully asynchronous handshakes** (Unibus, VME): every card needs
  acknowledge logic, and every CPU still needs synchronisers.
- **What synchronous buys:** the only line that must have clean edges is
  the point-to-point clock. With SEL as the strobe
  ([13.3](#133-sel-as-the-strobe)), every other edge that matters is also
  point-to-point.

#### 13.2 Slots in the address, and class straps

- **Why straps:** a card that says what it is with two straps needs no
  logic, and the backplane can time it from the first transfer after reset.
  PCI does the same with its PRSNT1# and PRSNT2# pins.
- **Why the backplane times transfers:**
  - masters need no wait-state tables or strobe logic;
  - simple cards need no clock;
  - every card sees where a transfer ends.
- **Alternatives tried** ([section 16](#16-rejected-ideas)):
  - **Per-master wait-state tables**, in the first draft. Slaves couldn't
    see the end of a transfer, and every table needed loading at boot.
  - **An address map in RAM on the backplane.** It was flexible, but
    nothing answered until software had written it.
  - **WAIT-only timing,** with each card timing itself. Simple cards grew
    to about 8 chips.
- **The slot bits:** A31–A28 give each slot 256 MB. That's plenty: main RAM
  is private to each CPU board, and an MMU will hide physical layout. They
  might move to A30–A27, to leave half the address space for something
  else.

#### 13.3 SEL as the strobe

**decided.** It replaces the bused RD and WR strobes of the earlier drafts.

- **What was wrong with the bused strobes:**
  - They were multidrop lines that simple cards act on, so they needed
    33 Ω + 220 pF at both ends of the backplane and Schmitt triggers on the
    cards.
  - Their 22–31 ns edges were the slowest path on the bus, since masters
    sampled them to know when read data was valid.
  - With a slow strobe and a fast select, a back-to-back transfer could
    start a false read on another card. The first draft had that problem.
- **What SEL as the strobe buys:**
  - **Clean edges:** SEL is already per slot, registered and
    point-to-point, like BCLK.
  - **Fewer parts:** the RC networks and the RD/WR pins go.
  - **More time for simple cards:** their strobes start about 30 ns into
    the data clock instead of about 55.
  - **No false reads across cards:** a card never sees another card's
    strobe.
  - **A faster clock floor:** masters take read data on DPH, a clean
    registered line, so the shortest usable period drops from about 55 ns
    to about 50 ns.
- **What it costs:**
  - **SEL and WRITE become glitch-sensitive.** A crosstalk spike on either
    while SEL is asserted becomes a false or broken access. Hence the
    ground pins beside both and the Schmitt-trigger inputs (the 74HCT132
    replaces the 74HCT14, same count).
  - **SEL must never glitch,** so it comes from registered one-hot outputs.
    That rules out the cheaper decode-after-register variant, which glitches
    at the clock edge.
  - **No chip-select window wider than the strobe,** because SEL is the
    strobe. A device's chip select is tied active or taken from address
    bits, which are steady from the address clock through the recovery
    clock.

#### 13.4 RDY, WAIT, DPH and the recovery clock

- **A visible end.** The first draft's masters counted wait states from
  their own tables, which slaves couldn't see. So whenever a table asked for
  more clocks than a slave would have taken, the slave stopped driving
  early, for example at boot when every slot got the maximum. With RDY and
  WAIT on the bus, every card sees the end.
- **WAIT rather than DTACK.**
  - RDY already acknowledges on behalf of every card, so slaves only speak
    up when they're late.
  - A slave-driven acknowledge would put logic on every card.
  - It would also hit the problem that dropped the first draft's claim
    line: a simple card can only release a shared line, and a 10 kΩ pull-up
    takes microseconds to restore it.
- **WAIT is bused, not radial.**
  - A radial WAIT, folded into RDY by the backplane, would leave no shared
    lines at all.
  - But it adds a second trip through the backplane: about 54 ns of the 60.
- **The turnaround rules** give WAIT and D a clock with nobody driving
  between transfers. Earlier drafts handed WAIT over at the same edge.
- **DPH** tells masters which clocks carry read data. For a simple card,
  RDY comes in the recovery clock, after its data has gone.
- **The recovery clock** holds the address after a simple card's strobe.
  - The first draft let the address change at the same edge RD was
    released.
  - With RD's slow edge, a UART could see its register address change while
    RD was still active, and lose a character.

#### 13.5 Data width and byte lanes

- **Why halfwords always travel on D0–D15:** in the first draft a halfword
  at A1 = 1 travelled on D16–D31 to 32-bit cards. A P1-only master can't see
  those lines, so 16-bit CPUs, Z80s and 68000s couldn't have used half of a
  32-bit card.
- **The cost:** a swap transceiver on every 32-bit card and master.
- **W32 comes from the class straps,** so no card drives a shared W32.
- **Why keep 32 bits:** the target is a 32-bit architecture with more than
  one CPU, so the 32-bit path stays. A review that suggested a 16-bit-only
  bus had been framed around the draft 1b hardware, which is only a study.

#### 13.6 Bus mastering

- **A central arbiter**, because the backplane already knows when
  transfers start and end. Distributed schemes (NuBus) need logic on every
  master.
- **Withdraw, then grant.**
  - The old rules let GNT move at the same edge the old owner started one
    more transfer. So a new master needed BUSY and a two-edge check, START
    and BUSY inactive at the second of two GNT samples, before it could
    trust GNT.
  - Now the arbiter does the waiting, and GNT means "idle and yours". BUSY's
    pin became DPH. The handover still takes 3 clocks.
- **Fixed priority,** with the main CPU lowest and parked on, because the
  CPU makes most bus accesses and DMA should pre-empt it.
  - Fixed priority can starve low-priority masters.
  - The courtesy rule (drop REQ after 16 transfers) bounds that.
  - Round robin is fairer, at about twice the logic. **open.**
- **LOCK and its idle clock.** A multi-CPU system needs atomic
  read-modify-write across the bus, and test-and-set semaphores don't cover
  every use.
  - Starting with an idle clock closes a race: the arbiter might withdraw
    GNT at the very edge where the owner asserts LOCK, and then the first
    locked transfer would go out without a lock.
  - It costs one clock per locked sequence.
- **The slave-port rule and the deadlock rule** make locked sequences
  atomic against the target CPU's own accesses, and stop two CPUs waiting
  for each other forever. The WAIT timeout catches whatever slips through.

#### 13.7 Timing budgets

All at 16 slots, in ns, with rough datasheet worst cases.

| Path | Steps | Total | Slack at 60 ns |
|---|---|---:|---:|
| One-clock path between fast cards | register 6, transceiver 5, backplane ≤ 11, transceiver 5, setup 3, skew 2 | ≈ 32 | 28 |
| Slot and class lookup on the backplane | master 11, backplane ≤ 11, input buffer 5, class multiplexer (two levels) 15, setup 3, skew 2 | ≈ 47 | 13 |
| A fast card's read, one data clock | its register 6, SRAM 15–25, transceiver 5, backplane ≤ 11, master 8, skew 2 | 47–57 | 3–13 |
| A fast card raising WAIT from SEL | SEL at the card 10, gate and driver 10, backplane ≤ 11, master 8, skew 2 | ≈ 41 | 19 |
| DPH or RDY to a master | register 6, driver 5, backplane ≤ 11, receiver 5, setup 3, skew 2 | ≈ 32 | 28 |

- **The class lookup sets the shortest usable period,** about 50 ns.
- **A 74HCT card** would need roughly 125 ns for the one-clock path. That's
  why HCT cards are simple cards.

**Simple cards.**

- **When the strobe starts:** SEL arrives about 10 ns into the first data
  clock, and the 74HCT132 adds about 20. So the device's strobe starts at
  about 30 ns.
- **How much time the card gets:** read data must be at the card's
  connector by about 22 ns before the end of the last data clock. That
  leaves about N × 60 − 50 ns from the strobe starting: 70 ns with N = 2,
  130 ns with N = 3.
- **What sets N:**
  - A 16C550 behind a 74HCT245 needs N = 2–3.
  - A CF card in ATA PIO mode 0, its state after reset, wants 290 ns
    strobes for 8-bit registers (N = 5) and 70 ns of address setup. The
    strobe gets 50–70 ns.
  - So with a CF card among the simple cards, either N = 5 with a slightly
    short setup, or a second, slower class with a setup clock (open idea,
    [section 15](#15-open-ideas)).

**Skew and hold.**

- **Where skew comes from:**
  - the trace lengths alone give 0.8 ns (simulated);
  - two clock-buffer packages on the backplane;
  - one buffer on every card.

  A '244-type buffer varies by about 1–5 ns from part to part, so skew
  could reach several ns.
- **Why hold time is the risk:**
  - with minimum datasheet delays, a register and a transceiver can change
    an output within 2.5–3 ns;
  - against about 1 ns of hold plus the skew, hold doesn't close on paper.
- **Hence the proposals in [section 4](#4-clock-and-timing):**
  - T<sub>skew</sub> ≤ 2 ns, from a clock-driver part with specified
    part-to-part skew and a specified buffer on each card;
  - T<sub>co</sub> min ≥ 3 ns.

  Both need confirming with parts data and simulation.

#### 13.8 Electrical rules and the simulations

From [report 0013](0013-report-bus-si.md): one bus line on a 6U backplane
with 8 or 16 slots, TI IBIS models, an estimated 12 nH and 2 pF per
connector contact, 25 mm card stubs. [Report 0022](0022-report-bus-si-revised.md)
reran these on a new simulator without changing a worst case, and extended
them to the revised bus ([section 17](#17-signal-integrity)).

- **No terminators.**
  - 74HCT and 74AHCT can't pull a terminated line below 0.8 V: the low
    level was 0.66–1.19 V.
  - Terminators would burn 8–12 W.
  - With ABT drivers, falling edges ring back above 0.8 V for about 30 ns,
    since 194 Ω barely loads a 26 Ω line.
- **22 Ω in series.** With ABT drivers it lowers the peak from 6.0 to
  4.4 V, the dip from −0.9 to −0.45 V, and extra threshold crossings from 8
  to 2. It costs about 2 ns of settling.
- **Drivers:** 74ACT overshoots to about 7 V and undershoots to −1.4 V.
- **The clock:** an ABT buffer with 56–68 Ω series resistors gave clean
  edges at every slot in every simulated case, with 0.8 ns of skew without
  length matching.
- **Crosstalk:** two switching neighbours put 1–2 V spikes on a quiet line
  through the connector contacts' coupling.
  - That's harmless on lines sampled at a clock edge.
  - It's not harmless on SEL and WRITE, which simple cards use as strobe
    and direction, hence their ground pins and Schmitt inputs.
- **Loading:**
  - A card as simulated adds about 9 pF per slot, giving a loaded line of
    about 27 Ω and 14 ps/mm.
  - The bus switches on the reflected wave: an ABT driver through 22 Ω
    reaches only about 1.4 V on its first step.
  - Heavier cards lower that step and lengthen the round trip. At about
    20 pF per card, settling might grow 1.5–2×, an estimate to be simulated.
  - Hence the loading rule.

Simulated settling at 16 slots, worst case over driver positions and
corners. "Added delay" is on top of the datasheet propagation delay:

| Driver, termination | Added delay, rise / fall | Peak / lowest | Extra crossings |
|---|---|---|---|
| ABT, 22 Ω series | 9 / 11 ns | 4.4 / −0.45 V | 2 |
| FCT-T, 22 Ω series | 10 / 10 ns | 4.1 / −0.4 V | 4 |
| HCT, 22 Ω series | 8 / 14 ns | 5.7 / −0.3 V | 2 |
| ABT, none | 7 / 9 ns | 6.0 / −0.9 V | 8 |
| ABT, 330/470 Ω (VME) | 5 / 26 ns | 5.7 / −0.9 V | 4 |
| ABT, series + 33 Ω + 220 pF (now only on RESET) | 22 / 31 ns | 4.0 / +0.2 V | 0 |

With 8 slots, the delays without the RC network are about half.

#### 13.9 The backplane's logic

| Part | Chips |
|---|---:|
| Input buffer for the slot bits, START, WRITE, WAIT, LOCK | 1 |
| Slot decoders and SEL registers | 4 |
| Class multiplexers, by the slot bits | 5 |
| Transfer timing: counter for N, state, class register | 4 |
| Drivers for DPH, RDY, BERR, W32 | 1 |
| Bus monitor | 2 |
| Arbiter: request priority encoder, owner register, comparison, state, grant decoders | ~8 |
| Clock driver, power-on reset | 3 |
| **Total, plain 74-series** | **~28** |

- **With GALs:** about 13. The arbiter, the transfer timing and the class
  multiplexers each fit one or two.
- **Fewer master slots:** limiting bus mastering to 8 slots would save
  about 2 chips of the arbiter.

#### 13.10 Relatives

- **VME:** the mechanics (two 96-pin connectors, P1 enough for basic cards,
  user pins on P2), BERR with a bus timer, and a central system controller.
- **NuBus:** synchronous operation, START, slot spaces, and declaration
  ROMs (our card IDs).
- **PCI:** per-slot REQ/GNT with parking, pull-ups and turnaround on shared
  lines, card-edge timing, and presence straps (our class straps).
- **SBus, the Apple II, and EISA's per-slot enables:** the slot select comes
  from a central decoder, so cards need no comparator.

## Part 3: Open questions, ideas and signal-integrity work

### 14. Open questions

Questions only Emily can answer:

1. **The bus clock:** its period (60 ns for now), and whether it comes from
   the main CPU board or an oscillator on the backplane.
2. **The slot bits:** A31–A28, or elsewhere (A30–A27)?
3. **Cards:** the card size and how the system splits into cards. These
   wait until the design is closer to completion.
4. **PLDs:** may the design use GALs? The backplane is about 28 chips
   without them and 13 with them, and the bridges and DMA engine shrink
   too. Emily (2026-10-15): a preference against, since they make the
   machine harder to build, are hard to source and are less fun, but not
   a definite no.
5. **Simple-card speed:** one speed N for all simple cards, or a second,
   slower class (with a setup clock) from a third class strap? It's about
   two more backplane chips and one reserved pin.
6. **Arbitration:** fixed priority (recommended) or round robin? Park on
   slot 0 (recommended) or on the last owner?
7. **Card IDs:** format and place.
8. **Semaphores:** on the main CPU board, or on the backplane, which would
   then need an address region of its own?
9. **A higher supply voltage:** which one, and on which pins?
10. **Floating lines:** resistor packs or bus-hold parts?

Still to do:

11. **Pins:** the pin-by-pin assignment of P1 and P2.

Answered by report 0022, waiting for Emily to adopt them or not
([section 17](#17-signal-integrity)):

12. **Timing values:**
    - skew of 2.5 ns or less, with specified clock parts on the backplane
      and every card;
    - 13 ns for settling in the budgets;
    - simple cards get about N × T − 60 ns.
13. **Loading:** 12 pF per card counting the trace, and traces up to about
    50 mm.
14. **Ground bounce:**
    - ABT16245 in TSSOP for wide drivers;
    - octal ABT245 in SOIC where a narrow one is wanted;
    - not DIP, not FCT-T in DIP, not the ABT2245.
15. **The backplane's lines:**
    - its logic in the middle;
    - 22 Ω on its bused outputs;
    - 56–68 Ω on SEL and GNT.

### 15. Open ideas

- **Full-width and half-width slots** (Emily's idea): some columns take
  full cards on P1 and P2, others two P1-only cards stacked. It waits for
  the card size ([RFC 0008](0008-rfc-ideas-memory-and-buses.md#full-width-and-half-width-slots)).
- **A slower simple-card class:** a third strap selecting a second N, and
  a setup clock before the strobe for devices like a CF card at PIO mode 0.
- **Round-robin arbitration.**
- **Master slots:** only some slots can be bus masters, to shrink the
  arbiter.
- **Semaphores on the backplane,** where every master finds them at a fixed
  address.
- **The bus clock from an oscillator on the backplane,** independent of the
  CPU board, at the cost of a synchroniser in each CPU.
- **Moving the slot bits** to A30–A27, or elsewhere.

### 16. Rejected ideas

Kept with their reasons, so they aren't proposed again without new
evidence.

| Idea | Status | Why |
|---|---|---|
| A strobe-timed bus without a clock (8080, Z80, ISA) | **rejected** (Emily) | Multidrop strobes as timing references ring unless slowed by 20–35 ns |
| A fully asynchronous handshake (Unibus, VME) | **rejected** (Emily) | Acknowledge logic on every card, synchronisers in every CPU |
| A separate I/O bus behind a bridge card | **rejected** (Emily, 2026-10-13) | Simple peripherals go on the system bus. It would have cost a bridge (~10–15 chips), a second backplane and card format, and two system-bus transfers per I/O access |
| An address map and timing table in RAM on the backplane | **rejected** (Emily, 2026-10-13) | Nothing answered until software had written it; a bad map made every card unreachable; its lookup was the longest path. Its flexibility (contiguous memory across cards, timing per page) isn't needed |
| Per-slot wait-state tables in every master | **rejected** (Emily, 2026-10-13) | Replaced by class straps. Slaves couldn't see the end of a transfer, and every table needed loading at boot |
| WAIT-only timing, each card timing itself | **rejected** (Emily, 2026-10-13) | Replaced by class straps. Simple cards would need a clock and about 8 chips |
| Burst transfers | **rejected** (Emily, 2026-10-13) | They'd need an address counter on every card that takes them, and more backplane state. Single transfers give 33 MB/s |
| Bused RD and WR strobes | **rejected** (Emily, 2026-10-14) | Replaced by SEL as the strobe ([13.3](#133-sel-as-the-strobe)) |
| A system-controller card in slot 0 | **rejected** (Emily, 2026-10-13) | Active logic on the backplane instead. The radial lines would have needed many extra pins on slot 0 |
| A slave-driven claim line | not recommended | A simple card can only release a shared line, and a 10 kΩ pull-up takes microseconds to restore it |
| A slave-driven acknowledge (DTACK) | not recommended | Logic on every card. RDY acknowledges on the cards' behalf |
| Resistor terminators (VME's 330/470 Ω) | not recommended | HCT can't pull them low; 8–12 W; ABT edges ring for 30 ns |
| 74ACT as bus drivers | not recommended | 7 V overshoot, −1.4 V undershoot |
| A radial WAIT folded into RDY | not recommended | No shared lines, but about 54 ns of the 60 for the WAIT path |
| Inverted polarity, inverting transceivers, bus-invert coding | not recommended | Clocked lines settle both ways, so polarity doesn't change the clock rate. Inverting ABT parts are about 1 ns faster at most. Bus-invert coding helps simultaneous switching, not timing, at an XOR per bit on every card |
| A 16-bit-only bus; dropping LOCK | not recommended | Proposed by a review framed around the draft 1b hardware. The target is a 32-bit, multi-CPU system |
| −5.2 V on the backplane | **rejected** (Emily, 2026-10-13) | The ECL cruncher is deprioritised. A higher voltage may come instead |

### 17. Signal integrity

[Report 0022](0022-report-bus-si-revised.md) did the work this section
used to list: eleven items, on a simulator of the study's own
([studies/bus_si](../studies/bus_si/README.md)). Report 0013's worst cases
stand; its ground-bounce results are superseded.

The report suggests the following changes. They're **pending**: Emily
decides, and Parts 1 and 2 haven't been changed to match yet.

| Item | Finding (report 0022) | Suggested change to this RFC |
|---|---|---|
| Ground bounce | 16-bit TSSOP parts (ABT16245) bounce a fifth as much as octal SOIC or DIP parts, and every glitch is gone within 12 ns of the edge | Wide drivers: ABT16245 in TSSOP; octal ABT245 in SOIC is acceptable; not DIP, not FCT-T in DIP, not the ABT2245 (section 9 now allows it) |
| SEL as a strobe | No series resistor up to 68 Ω makes the 74HCT132 retrigger. Without the guard ground pins, a simple card's own data drivers can turn a read into a write; with them both strobes keep 1.1 V or more of margin | SEL and GNT: 56–68 Ω, not 33–68. The guard-pin rule is necessary, and with it the Schmitt inputs are enough |
| Card loading | 12 pF per card adds 10.3 / 12.8 ns (rise / fall); 15 pF adds 14.3; 20 pF jumps to 19.1 | Keep 12 pF, counting the card's trace. Use 13 ns, not 11, for settling in the budgets. Card traces up to about 50 mm |
| Hold time | The bus never brings a change forward. ABT574/273 with ABT16245 meet T<sub>co</sub> min ≥ 3 ns and T<sub>h</sub> ≤ 1 ns | As proposed in section 4; that leaves at least 2.9 ns for skew |
| Clock tree | Trace skew is 0.25 ns. The rest is the parts': about 2.0–2.6 ns with clock drivers that specify part-to-part skew at both ends, about 8 ns with a generic '244 on each card | T<sub>skew</sub> ≤ 2.5 ns, with specified clock parts (FCT807CT or CDC341 class) on the backplane and on every card; 68 Ω |
| The backplane's lines | Logic in the middle shortens the radial lines to under 200 mm and settles rising edges 2.4 ns sooner. 33 Ω is too much on its bused outputs | The backplane's logic in the middle; 22 Ω on DPH, RDY, BERR and W32 |
| WAIT | Released, it stays at least 2.7 V against two switching neighbours | No change |
| Connector | 12 nH per contact confirmed against TE's measurements; settling barely depends on it | No change |
| Geometry | Delay follows the backplane's length: 20 slots add 3 ns, a 15.24 mm pitch saves 1 ns | Tables for when the card size is chosen |
| A 50 ns clock | Card-to-card transfers use about 32 ns of 50. HCT's falling edge settles in 21 ns, not 11 | 50 ns works for bused paths. Simple cards get about N × T − 60 ns from the strobe starting, not N × 60 − 50; a 16C550 behind a 74HCT245 may need N = 3 |

**Still open after report 0022:**

- **The clock driver's own ground bounce,** six outputs switching
  together. The calibrated model says it's fine; the raw IBIS model says a
  falling edge could ring back and clock twice. This needs a measurement on
  a prototype backplane, and it favours a clock driver that publishes a
  ground-bounce figure.
- **Not modelled:** the planes' spreading inductance and decoupling
  placement.
- **The real pin assignment:** it should keep the guard pins and spread
  the returns as report 0022's reference assignment does.
- **The half-width layout's hop** between connector rows, if that layout is
  chosen.

### 18. Decisions

Emily has decided:

- the bus is synchronous: one bus clock, every signal sampled on its rising
  edge;
- simple, dumb peripherals must be possible;
- bus addresses are the full 32 bits;
- two connectors per slot, with P1 enough for a simple peripheral.

On 2026-10-13:

- **Cards:**
  - two 96-pin connectors per slot;
  - the card size, and how the system is split into cards, wait until the
    design is closer to completion;
  - every card has an ID.
- **The bus clock** isn't decided: it is a variable for now, with 60 ns as
  the starting point.
- **Addressing and timing:**
  - addresses carry the slot;
  - a card's timing comes from class straps read by the backplane;
  - a fast card holds WAIT when it needs longer.

  These replaced an address map and timing table in RAM, decided earlier
  the same day, and a WAIT-only scheme.
- **No burst transfers.**
- **Simple peripherals** go on the system bus; the separate I/O bus is
  closed.
- **The backplane:** active parts on it are fine; no −5.2 V on it, though it
  may carry a higher voltage.
- **The ECL number cruncher** is deprioritised.

On 2026-10-14:

- **Strobes:** SEL is the strobe for simple cards, and the bused RD and WR
  strobes go.
- **LOCK stays:** a multi-CPU system will need it. The bus is designed for
  the 32-bit, multi-CPU target, not for the draft 1b hardware.
- **The slot bits:** A31–A28 is tentative; the slot bits may move, for
  example to A30–A27.
