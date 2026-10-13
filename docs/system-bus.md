# System bus

A draft specification of the backplane bus shared by the main CPU, the ECL
number cruncher, DMA devices and peripherals. The reasoning behind it is in
[proposals.md](proposals.md) (sections 4 and 5).

The electrical numbers come from ngspice simulations of the backplane with
TI's IBIS models ([tmc/si/README.md](../tmc/si/README.md); results in
[bus-si/full.json](bus-si/full.json)). The datasheet delays in the timing
budgets are rough worst-case figures and need checking against the parts
actually used.

Statuses are as in the proposals: **decided** (Emily chose it),
**recommended**, **open**, and **optional** for features a card may leave
out.

## Contents

1. [Summary](#1-summary)
2. [Kinds of card](#2-kinds-of-card)
3. [Signals](#3-signals)
4. [Clock and timing conventions](#4-clock-and-timing-conventions)
5. [Transfers](#5-transfers)
6. [Arbitration](#6-arbitration)
7. [Bursts (optional)](#7-bursts-optional)
8. [Interrupts, reset and synchronisation](#8-interrupts-reset-and-synchronisation)
9. [Electrical rules](#9-electrical-rules)
10. [The main CPU board on the bus](#10-the-main-cpu-board-on-the-bus)
11. [Other CPUs as masters](#11-other-cpus-as-masters)
12. [Alternative: a separate I/O bus](#12-alternative-a-separate-io-bus)
13. [Open questions](#13-open-questions)

## 1. Summary

| | |
|---|---|
| Timing | **Synchronous**: one bus clock, every signal sampled on its rising edge. **decided** |
| Bus clock | The main CPU's 50 MHz master clock ÷ 3 (16.7 MHz, 60 ns) or ÷ 4 (12.5 MHz, 80 ns), set by a jumper on the CPU board. Cards are designed for ÷ 3. **recommended** |
| Address | 32 bits (4 GB). 16 slot regions of 256 MB, selected by A31–A28 |
| Data | 16 bits on P1 (D0–D15), 32 bits with P2. Masters handle 16-bit slaves themselves |
| Transfers | An address clock, then a data clock: 2 clocks (120 ns at ÷ 3). Wait states in whole clocks |
| Bursts | One word per clock after the first: **optional** ([section 7](#7-bursts-optional)) |
| Masters | Any slot. A central round-robin arbiter; the bus stays with the last master while nobody else asks |
| Cards | 6U Eurocards (233 × 160 mm), up to 16 slots at 20.32 mm, two 96-pin DIN 41612 connectors. P1 alone is enough for a simple peripheral. **decided** |
| Simple peripherals | Supported: a per-slot select line from the backplane, read and write strobes, and wait states kept by the masters, so a card needs no clock and no address comparator |

Peak rates:

| | ÷ 3 (16.7 MHz) | ÷ 4 (12.5 MHz) |
|---|---:|---:|
| Single transfer | 120 ns | 160 ns |
| 16-bit singles | 16.7 MB/s | 12.5 MB/s |
| 32-bit singles | 33 MB/s | 25 MB/s |
| 32-bit bursts (optional) | 67 MB/s | 50 MB/s |
| Simple-peripheral transfer, minimum | 180 ns | 240 ns |

## 2. Kinds of card

A card can play any combination of these roles. A CPU board is a master and
a synchronous slave (its RAM, for other masters).

**Master** (main CPU, DMA engines, the cruncher). Must:

- request the bus and follow the arbitration rules
  ([section 6](#6-arbitration));
- run transfers, driving the read and write strobes for simple slaves;
- keep a **per-slot wait-state table**: 16 entries, loaded by boot
  software, giving the minimum data clocks for each slot
  ([section 5.3](#53-wait-states));
- split 32-bit accesses for 16-bit slaves and steer the halves
  ([section 5.5](#55-data-width-and-byte-lanes));
- report a bus error to its own processor when a transfer ends in BERR.

**Synchronous slave** (memory cards, the CPU boards' slave ports, DMA and
Ethernet cards' registers and buffers). Samples the bus on clock edges and
answers within the data clock, or holds WAIT. It needs fast parts (74ABT or
74FCT-T) at the bus interface; 74HCT is too slow for a one-clock path at
÷ 3 or ÷ 4 ([section 4](#4-clock-and-timing-conventions)).

**Simple slave** (UARTs, the CF card, an RTC, a parallel port, the front
panel). Needs only:

- P1, with D0–D7 (or D0–D15), a few low address lines, SEL, RD, WR,
  PRESENT (tied to ground) and an IRQ line;
- no clock, no address comparator, no WAIT logic. The masters' wait-state
  tables stretch its transfers.

  A UART card, for example: a 16C550 with its crystal, a 74HCT245 on the
  data lines and a 74HCT14 to square up RD and WR. It can be built entirely
  from 74HCT.

## 3. Signals

Polarity: control signals are active low on the backplane. Signal names
below are given without a suffix, and "asserted" means active.

**Topology** (column "Type" below):

- **bused:** runs past every slot.
- **radial:** each slot has its own trace to logic on the backplane, on the
  same pin at every slot.
- **strapped:** fixed per slot.

**Drive types:**

- **3-state:** driven by the current owner (or the selected slave for read
  data).
- **shared:** driven by one card at a time, actively both ways, and held
  inactive by a weak pull-up when nobody drives (as in PCI).
- **OC:** open collector, with a pull-up on the backplane.

### P1: the 16-bit bus

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D0–D15 | 16 | bused, 3-state | master in write data clocks, slave in read data clocks | data |
| A1–A31 | 31 | bused, 3-state | bus owner | address; A31–A28 select the slot |
| BE0, BE1 | 2 | bused, 3-state | bus owner | byte enables within the halfword A1 selects |
| START | 1 | bused, 3-state | bus owner | asserted for the address clock of each transfer |
| WRITE | 1 | bused, 3-state | bus owner | asserted for a write, valid with START |
| LOCK | 1 | bused, 3-state | bus owner | keep the bus across a read-modify-write |
| RD, WR | 2 | bused, 3-state, slow edges | bus owner | strobes for simple slaves |
| WAIT | 1 | bused, shared | addressed slave | add a data clock |
| BERR | 1 | bused, shared | bus monitor on the backplane | end the transfer with an error |
| PRESENT | 1 | radial | card (tied to ground) | a card is in this slot |
| REQ | 1 | radial | master | bus request to the arbiter |
| GNT | 1 | radial | arbiter | bus grant |
| BUSY | 1 | bused, shared | bus owner | the bus is owned |
| SEL | 1 | radial | slot decoder on the backplane | A31–A28 match this slot |
| GA0–GA3 | 4 | strapped | backplane | slot number |
| BCLK | 1 | radial | clock buffer on the backplane | bus clock |
| CLKSRC | 1 | slot 0 only | main CPU board | clock into the backplane buffer; not connected at other slots |
| RESET | 1 | bused, OC, slow edges | backplane power-on reset, main CPU | system reset |
| IRQ0–IRQ3 | 4 | bused, OC | any card | interrupt requests |
| +5 V, ground | 24 | | | |

### P2: the upper half and extras

| Signal | Pins | Type | Driven by | Meaning |
|---|---:|---|---|---|
| D16–D31 | 16 | bused, 3-state | as D0–D15 | upper halfword |
| BE2, BE3 | 2 | bused, 3-state | bus owner | byte enables of the upper halfword in a 32-bit transfer |
| W32 | 1 | bused, shared | addressed slave | "I'm a 32-bit slave": the whole word moved |
| IRQ4–IRQ7 | 4 | bused, OC | any card | interrupt requests |
| BURST, BACK, BFIX | 3 | bused | owner, slave | burst control, **optional** ([section 7](#7-bursts-optional)) |
| +5 V, ground | ~16 | | | |
| user-defined | ~54 | | | private links between neighbouring cards, as on VME's P2 |

### Pin assignment rules

The pin-by-pin assignment is still to do. It must follow these rules:

- BCLK, RD, WR and RESET each have a ground pin on both sides, in the row
  and across rows. The simulations show connector coupling dominating
  crosstalk ([section 9](#9-electrical-rules)).
- Power and ground pins are spread along the connector, not grouped.
- The same signal is on the same pin at every slot. That includes the
  radial ones, which the backplane routes to its own logic.

## 4. Clock and timing conventions

- **Clock source.** The main CPU board divides its 50 MHz master clock by 3
  or 4 and sends the result on CLKSRC, wired only at slot 0, to a clock
  buffer on the backplane.
- **Distribution.** The buffer drives each slot's BCLK on its own trace,
  through a 56–68 Ω series resistor, with one load per card. Every card,
  the CPU board included, clocks its bus logic from its own BCLK pin.
- **When signals change and are sampled.** Every bused signal changes just
  after a rising BCLK edge and is sampled at the next rising edge. Masters
  also use the falling edge to shape strobes.
- **Clock skew.** 0.8 ns between slots with unmatched trace lengths, none
  with matched lengths (simulated).

**Budget for a one-clock path** between two fast cards, at 16 slots, in ns:

| Step | ABT or FCT-T card |
|---|---:|
| Register clock-to-output (e.g. 74ABT574, 74ABT652) | ≈ 6 |
| Transceiver onto the bus | ≈ 5 |
| Backplane: flight and settling with 22 Ω series resistors (simulated, worst case) | ≤ 11 |
| Transceiver off the bus | ≈ 5 |
| Register setup time | ≈ 3 |
| Clock skew | ≤ 1 |
| **Total** | **≈ 31** |
| Slack at ÷ 3 (60 ns) / ÷ 4 (80 ns) | 29 / 49 |

A 74HCT card would need roughly 35 + 30 + 14 + 30 + 15 ≈ 125 ns for the
same path. That's why HCT cards are simple slaves.

**Budget for a synchronous slave's read.** The address is registered at the
end of the address clock, then:

| Step | ns |
|---|---:|
| Register clock-to-output | ≈ 6 |
| SRAM | 15–25 |
| Slave's transceiver | ≈ 5 |
| Backplane | ≤ 11 |
| Master's transceiver | ≈ 5 |
| Master's setup | ≈ 3 |
| **Total** | **45–55** |

That fits one data clock at ÷ 3 with 20 ns SRAM, or at ÷ 4 with anything up
to about 35 ns. Otherwise the slave adds a wait state.

## 5. Transfers

### 5.1 Read

| Clock | The owner drives | The addressed slave drives | At the end of the clock |
|---|---|---|---|
| 1, address | A, BE, START, WRITE off; RD stays off | nothing | slaves sample the address; SEL is valid well before the edge |
| 2, data | RD | D, WAIT, W32 if 32-bit | the master samples D, WAIT, W32 and BERR |

### 5.2 Write

| Clock | The owner drives | The addressed slave drives | At the end of the clock |
|---|---|---|---|
| 1, address | A, BE, START, WRITE asserted | nothing | slaves sample the address |
| 2, data | D, and WR (see [5.4](#54-simple-slaves-and-the-strobes)) | WAIT, W32 if 32-bit | the slave samples D; the master samples WAIT, W32 and BERR |

**No contention between transfers.** Data lines are only driven during
data clocks, and every transfer starts with an address clock. So there's
always a clock between one transfer's data and the next, and read-to-write
turnaround needs no extra clock.

A slave drives WAIT and W32 from its first data clock through the clock
after its last one, inactive in that final clock, then lets go. The next
slave can't start driving them until its own first data clock, one clock
after that. Simple slaves drive neither.

### 5.3 Wait states

- **WAIT** from the slave adds a data clock. The master samples it at the
  end of each data clock and finishes at the first one where it's
  inactive. For variable delays: a FIFO running dry, a busy memory.
- **The per-slot wait-state table** in every master sets a minimum number
  of data clocks per slot. The master counts it out itself.
  - With it, a slow card works at any bus clock without having to raise
    WAIT in time. At ÷ 3 a slave has about 40 ns from seeing its address to
    asserting WAIT, too little for 74HCT.
  - Each entry holds:
    - the extra data clocks, 0–15;
    - a recovery count, 0–3 idle clocks after a transfer to that slot, for
      peripherals that need time between accesses.
  - Boot software fills the table from each card's ID; until then every slot
    gets the maximum.
  - Cost: a 16 × 8 register file or small RAM and a counter, ~3 chips per
    master.
- **The bus monitor** on the backplane asserts BERR if a transfer lasts
  more than 256 clocks, so a stuck slave can't hang the system
  ([section 5.6](#56-bus-errors)).

### 5.4 Simple slaves and the strobes

Masters drive RD and WR on every transfer; synchronous slaves ignore them.
A simple slave's table entry must give at least one extra data clock, so a
simple transfer has an address clock and at least two data clocks.

| | Asserted | Released | Guarantees |
|---|---|---|---|
| RD | start of the first data clock | end of the last data clock, when the master samples D | address stable a whole clock before RD |
| WR | start of the first data clock | start of the last data clock | address and data stable a whole clock before WR and a whole clock after it |

**Example, ÷ 3 with one extra data clock** (180 ns in total):

- RD is 120 ns wide, WR 60 ns.
- The card has about 70 ns from seeing RD to its data arriving at the
  master. That allows for the strobe's slow edges and the 74HCT245 on its
  data lines.
- Each extra data clock adds 60 ns.
- The address clock of the next transfer guarantees at least one clock of
  recovery between strobes; the table's recovery count adds more.

**What a simple card does:**

- It enables its data drivers with SEL and RD, and writes with SEL and WR.
- It puts 8-bit registers on D0–D7 at addresses 4 bytes apart, and 16-bit
  ones on D0–D15, 4 apart. Software uses byte or halfword accesses; if a
  master tries a 32-bit transfer, the missing W32 makes it split it.

### 5.5 Data width and byte lanes

**What each width sees:**

- A **16-bit slave** sees only P1. A1 picks the halfword; BE0 and BE1 pick
  its bytes, and the data is on D0–D15.
- A **32-bit slave** also sees P2:
  - with A1 = 0, BE0 and BE1 are the lower halfword's bytes and BE2 and BE3
    the upper's;
  - with A1 = 1, it's a halfword transfer of the upper half, with BE0 and
    BE1 as its byte enables.

  Its data is in natural lanes: bytes 0–1 on D0–D15, bytes 2–3 on D16–D31.
- **A 32-bit slave asserts W32 on every transfer.** If W32 is missing at the
  end of the data clock, the master knows only D0–D15 moved. For a 32-bit
  access it then does a second transfer for the upper half at A1 = 1.

The masters do all the steering, so slaves need no lane multiplexers:

| Access by a 32-bit master | Write | Read |
|---|---|---|
| Halfword or byte at A1 = 0 | data on D0–D15 | from D0–D15 |
| Halfword or byte at A1 = 1 | data on both D0–D15 and D16–D31 | from D16–D31 if W32, else D0–D15 |
| Word | low half on D0–D15, high half on D16–D31, BE0–BE3; repeat the high half at A1 = 1 if W32 is missing | the same, and the same repeat |

A 16-bit master, like the draft 1b CPU with its 16-bit memory bus, uses P1
only and does two transfers per word.

### 5.6 Bus errors

BERR ends a transfer with an error. On the draft 1b CPU it becomes a trap
next to the address error.

- **Only the bus monitor on the backplane drives BERR**, so no two drivers
  ever fight over it.
- **Empty slots:** every card ties its PRESENT pin to ground. The monitor
  looks up the addressed slot's PRESENT during the address clock. If the
  slot is empty, it asserts BERR in the first data clock, and the master
  samples it at the end of that clock.
- **Timeouts:** the monitor also asserts BERR for any transfer longer than
  256 clocks.
- **Errors inside a card** (an unmapped address in its region, a parity
  error) are the card's business: it can ignore the access or raise an
  interrupt.

Earlier drafts had slaves claim each transfer on a shared line. A simple
card can only release such a line, not drive it high again, and a 10 kΩ
pull-up takes microseconds to restore it on a loaded backplane. The PRESENT
straps need no logic on the cards.

## 6. Arbitration

- **Requests and grants.** Each slot has its own REQ and GNT to a
  round-robin arbiter on the backplane. The arbiter is synchronous: it
  samples REQ at each edge and changes GNT just after.
- **Taking the bus.** A master that sees GNT and BUSY inactive at an edge
  owns the bus. It asserts BUSY and starts its first address clock in the
  next clock. From a request on an idle bus to the first address clock
  takes 2 clocks.
- **Parking.** While nobody else requests, GNT stays with the last owner,
  normally the main CPU, so it can start a transfer with no arbitration
  delay. If GNT moves at the same edge the parked master starts, BUSY
  settles it: the new master waits.
- **Giving it up.** When GNT moves away, the owner finishes its current
  transfer (a burst counts as one, at most 16 words). It then drives BUSY
  inactive for one clock and releases it. The next owner starts one clock
  later, so a handover costs about a clock.
- **LOCK.** The owner holds LOCK across a read-modify-write, and the
  arbiter doesn't move GNT while it's asserted. **optional**: the hardware
  semaphores ([section 8](#8-interrupts-reset-and-synchronisation)) don't
  need it.
- **Deadlock rule** for CPU boards with slave ports. A CPU stalled waiting
  for the bus must still let its slave port use its RAM; otherwise two
  CPUs can wait for each other forever.

## 7. Bursts (optional)

**optional.** A master or slave without bursts never drives BURST or BACK;
weak pull-ups keep them inactive, and everything still works with single
transfers. The pins are reserved on P2.

```
clock      | 1, address | 2, data | 3, data | 4, data | 5, data |
A, START   | A          |         |         |         |         |
BURST      | asserted   | asserted| asserted| asserted| off     |   another word follows
BACK       |            | asserted| asserted| asserted| asserted|   (slave) burst accepted
D          |            | D(A)    | D(A+4)  | D(A+8)  | D(A+12) |
```

- **BURST.** The master asserts it in the address clock and in every data
  clock except the last.
- **BACK.** A burst-capable slave asserts it in the first data clock.
  Without BACK the master stops after the first word and carries on with
  single transfers.
- **Addresses.** The slave counts the address up itself: by 4 with W32, by
  2 for a 16-bit slave.
- **BFIX**, asserted with BURST in the address clock, keeps every word at
  the same address. That's for FIFOs, like the Ethernet card's packet
  buffer or a disk controller's data port.
- **Limits.** At most 16 words, and a burst never crosses a 16-word aligned
  block, so a slave needs a 4-bit counter.
- **WAIT** works on any word. W32 and BERR are sampled in the first data
  clock only.
- **Cost on a memory card:** a loadable counter (74ACT163) driving the low
  SRAM address bits. The path, counter to SRAM to backplane to master, is
  about 45–55 ns, so a word per clock fits at ÷ 3 with 15–20 ns SRAM.

| | ÷ 3 | ÷ 4 |
|---|---:|---:|
| Burst of 4 | 5 clocks, 75 ns per word | 100 ns per word |
| Burst of 16 | 17 clocks, 64 ns per word | 85 ns per word |

**Not adopted: pipelined addresses**, where the master sends a new address
every clock while the previous word's data moves, as the 386's pipelined
mode does. Slaves wouldn't need counters and addresses needn't be
sequential, but every pipelining slave must accept an address every clock.
Counters are simpler for memory-like cards.

## 8. Interrupts, reset and synchronisation

- **Eight interrupt lines**, IRQ0–IRQ3 on P1 and IRQ4–IRQ7 on P2: open
  collector, level-sensitive. Each card picks its line with a jumper; each
  CPU listens to its own subset through its priority encoder.
- **Doorbells.** A write to a register in a CPU board's slot region
  interrupts that CPU.
- **Hardware semaphores.** A read returns the old value and sets the
  semaphore (test-and-set on read), so CPUs without a locked
  read-modify-write can share them. Sixteen of them, in the main CPU
  board's slot region.
- **A control register per CPU** for reset/run and NMI. The main CPU boots
  the cruncher by loading its RAM through the cruncher's slave port and
  releasing its reset.
- **RESET** is open collector with slow edges. Cards receive it through a
  Schmitt trigger.

## 9. Electrical rules

From the signal-integrity simulations: 16 slots, 25 mm card stubs, an
estimated 12 nH and 2 pF per connector contact, TI IBIS models.
**recommended.**

**The backplane:**

- 4 layers (signal, ground, +5 V, signal).
- 0.2 mm traces: 67.5 Ω and 5.8 ps/mm bare (field-solved). Loaded with 16
  cards, a bused line is about 24–29 Ω and 13.5–16 ps/mm, about 5 ns from
  end to end.
- Active parts on the backplane:
  - the clock buffer;
  - the slot decoder (SEL);
  - the arbiter;
  - the bus monitor;
  - the power-on reset;
  - about 6–8 chips, possibly the semaphores too.

  A system-controller card in slot 0 is the alternative, but the radial
  lines (BCLK, SEL, GNT, PRESENT) would then need many extra pins on
  slot 0. **open**

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

- Synchronous cards use 74ABT or 74FCT-T (reduced swing, high level about
  3.3 V).
- 74ACT isn't recommended as a bus driver: it overshoots to about 7 V and
  undershoots to −1.4 V.
- 74HCT is fine on simple slaves.

**One load per card on each bused signal:** a transceiver or one or two
inputs, at most 25 mm from the connector (as simulated).

**RD, WR and RESET** must give clean edges to cards that act on the edges:

- 33 Ω + 220 pF to ground at both ends of the backplane, on top of the
  series resistors. That leaves 0–2 extra crossings and no dip below
  ground, at the cost of about 20–30 ns slower edges, which the strobe
  timing allows for.
- Schmitt-trigger receivers (74HCT14) on simple slaves.
- Ground pins on both sides.

**BCLK:**

- An ABT buffer with 56–68 Ω series resistors: peak about 4.5 V, dip −0.1
  to −0.5 V.
- No threshold re-crossing at any slot in any simulated case. Matched trace
  lengths are optional.

**Shared lines** (WAIT, BUSY, BERR, W32, BACK) are driven both ways by
their current driver, with a weak (10 kΩ) pull-up for when nobody drives.
An open-collector pull-up on a loaded line (150–250 pF) would be too slow
to rise within a clock.

**Interrupt lines:** open collector, one 1 kΩ pull-up each. They're slow
(~250 ns to rise), which is fine since every CPU synchronises them.

**Crosstalk.** Two neighbours switching put 1–2 V spikes on a quiet line
through the connector contacts' coupling. This is harmless on lines
sampled at a clock edge, as they're quiet again by then. It's why RD, WR,
RESET and BCLK get ground pins either side.

**Simulated settling, 16 slots,** worst case over driver positions, both
corners and all receivers. "Added delay" is on top of the datasheet
propagation delay:

| Driver, termination | Added delay, rise / fall | Peak / lowest voltage | Extra threshold crossings |
|---|---|---|---|
| ABT, 22 Ω series | 9 / 11 ns | 4.4 / −0.45 V | 2 |
| FCT-T, 22 Ω series | 10 / 10 ns | 4.1 / −0.4 V | 4 |
| HCT, 22 Ω series | 8 / 14 ns | 5.7 / −0.3 V | 2 |
| ABT, none | 7 / 9 ns | 6.0 / −0.9 V | 8 |
| ABT, 330/470 Ω (VME) | 5 / 26 ns | 5.7 / −0.9 V | 4 |
| ABT, series + 33 Ω + 220 pF (strobes) | 22 / 31 ns | 4.0 / +0.2 V | 0 |

With 8 slots, every delay is about half.

**Not settled yet:**

- **Ground bounce.** The simulation model is numerically unreliable. Until
  it's fixed: decouple every bus chip, and prefer SOIC or flow-through
  parts (such as the 74ABT16245, with many ground pins) for wide drivers.
- **Gaps in the sweep.** 39 of the 840 bus-line runs failed, mostly with
  series resistors on 16 slots, which have 12–15 of 16 driver positions
  covered.
- **Driver models.** TI's ABT, FCT and HCT models disagree with themselves.
  The simulation follows the waveforms through the edge and the V-I tables
  for the levels.

## 10. The main CPU board on the bus

**Addresses.** On the draft 1b CPU, MAR bit 31 set means "system bus". MAR
bits 30–27 drive A31–A28, the slot number; A27 is 0; and MAR bits 26–0
drive A26–A0. So the CPU reaches the first 128 MB of every slot, with
plain wiring. A later CPU with an MMU can produce full 32-bit bus
addresses.

The draft 1b CPU's cycles are whole numbers of 20 ns ticks of the 50 MHz
master clock ([proposals.md, section 4](proposals.md#4-microarchitecture)).
The bus clock is the same clock divided by N, so the CPU always knows the
phase of the next bus clock edge and needs no synchroniser.

**A bus access is one stretched microcycle.** A read starts at tick $t_0$.
The address clock starts at the first bus clock edge $E$ at least a tick
later, which gives MAR and its decode time to settle. The data is in a CPU
register about two ticks after the data clock ends:

$$t_\text{read} = (E - t_0) + 2N + 2 \text{ ticks}, \quad 1 \le E - t_0 \le N$$

| Bus clock | Bus read from the CPU, average (range) |
|---|---|
| ÷ 3 | 200 ns (180–220) |
| ÷ 4 | 250 ns (220–280) |

That's about one ordinary microcycle with HCT parts, two with ACT. Waiting
for the next bus clock edge costs 1.5–2.5 ticks per access on average. That
doesn't matter, because RAM is private and the bus only carries I/O and
remote accesses. The CPU's cycle lengths never need to be multiples of the
bus clock. **recommended.**

- **Posted writes.** Registered bus transceivers (74ABT652 or 646) take the
  address and data at the end of an ordinary microcycle. The bus interface
  finishes the write on its own, so the CPU only waits if it reaches the bus
  again before then.
- **Bus parking and early request.** The bus normally stays parked on the
  main CPU. When it isn't, the pipelined microcode tells the bus interface
  a cycle ahead that the next microinstruction uses the bus. It requests
  then, and the arbitration delay is mostly hidden.
- **The returned clock.** The bus interface runs on the board's BCLK pin,
  about 4 ns behind the internal phase it was divided from, like every
  other card. That's a fixed skew between two clocks from one source, easy
  to check in the timing analysis. Driving the bus from the internal phase
  would eat the hold-time margin.

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
  bus clock, or the CPU's cycle stretches by a tick instead.
- **Timing.** The RAM is 55 ns, so at ÷ 3 a slave-port transfer needs one
  wait clock anyway (180 ns, 240 ns at ÷ 4). Other masters reach the CPU's
  RAM in about 180–320 ns, instead of 300–600 ns with whole-cycle stealing.
  The CPU's RAM becomes usable as a DMA buffer.

## 11. Other CPUs as masters

A CPU with its own bus timing, like a Z80, a 68000 or the ECL cruncher, can
be a master through a small **bridge** on its card. **recommended** as the
way to attach them. The bridge turns the CPU's own bus cycles into bus
transfers:

1. The CPU starts a cycle in an address window mapped to the system bus.
2. The bridge holds the CPU: WAIT on a Z80, DTACK withheld on a 68000.
3. It synchronises the request to BCLK with two flip-flops (1–2 clocks),
   requests the bus unless it's parked there, and runs an ordinary transfer:
   strobes, wait-state table, lane steering.
4. It releases the CPU, with read data latched.

**Cost:**

- About 4–6 bus clocks per access: 250–400 ns at ÷ 3. That's a few wait
  states to a 4–8 MHz CPU.
- About 15–20 chips: the synchroniser and a small state machine, a bank
  register for the window, transceivers, lane steering and the wait-state
  table. A GAL or two would shrink that a lot.

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
  maps directly onto W32: with W32 it's a 32-bit port, without it 16-bit.
- Optional: other masters can reach its RAM through BR/BG/BGACK.

## 12. Alternative: a separate I/O bus

**open.** Instead of putting simple slaves on the system bus, a bridge card
would run a slow, separate I/O bus for them:

- 8 data bits, about 12 address bits, 8080-style read and write strobes;
- interrupt lines;
- its own small backplane with cheaper connectors. 3U cards with 64-pin
  DIN 41612 connectors would do, or RC2014-style headers.

| For | Against |
|---|---|
| The system bus carries only fast cards: fewer loads, cleaner edges, perhaps ÷ 2 | One more card (~10–15 chips) and a second backplane and card format |
| No strobes on the fast backplane; masters need no strobe logic or wait tables | Every I/O access crosses the bridge: about two system-bus transfers plus the I/O cycle |
| The I/O bus can be as slow as needed (~500 ns), on 2-layer cards, with chips that want odd timing (6800-style E clock, Z80 peripherals) | DMA to simple devices has to go through the bridge |

The simple-slave profile is the baseline, because it's cheap and makes "P1
is enough for a simple peripheral" literally true. The bridge is the
fallback if simple cards multiply, need odd timing, or load the bus too
much. Some of P2's user-defined pins could carry it to a group of
neighbouring slots.

## 13. Open questions

1. Design cards for ÷ 3 or ÷ 4? The CPU board's jumper allows both; ÷ 3 is
   recommended.
2. Simple peripherals on the system bus (the simple-slave profile,
   recommended) or on a separate I/O bus behind a bridge?
3. Active parts on the backplane (clock buffer, slot decoder, arbiter,
   bus monitor, reset), or a system-controller card in slot 0?
4. Does the backplane carry −5.2 V (or −4.5 V) for the ECL cruncher, or
   does the cruncher bring its own supply?
5. What the cruncher needs: 32-bit transfers, bursts, LOCK?
6. The pin-by-pin assignment of P1 and P2.
7. Ground bounce, once the model is fixed: which packages and parts for the
   wide bus drivers.
