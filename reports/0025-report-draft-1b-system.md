---
number: 25
type: report
title: Draft 1b on the system bus
status: current
date: 2026-10-15
context:
  studies: [v1b_system, v1b_hw, v1_isa]
  commit: ce72627
---

# Report 0025: Draft 1b on the system bus

The draft 1b CPU ([report 0012](0012-report-draft-1b-hardware.md)) as a
card on the system bus of [RFC 0014](0014-rfc-system-bus.md), with the
backplane's logic, a memory card and an I/O card. All four are chip-level
netlists that run together on the chip-level simulator from power-up.
The CPU card gives each microinstruction a cycle as long as it needs, the
variable-length cycles of
[RFC 0007](0007-rfc-ideas-microarchitecture.md#4-microarchitecture). The
work is in [studies/v1b_system](../studies/v1b_system/README.md); its
[design.md](../studies/v1b_system/design.md) describes every card in
detail.

Left out: the MMU and floating point (not in 1b), DMA, video and the
physical design. How much faster and smaller this system could be is
[RFC 0024](0024-rfc-faster-smaller.md)'s question, not this report's.

## Summary

- **It works.** The system is 367 chips. All 22 programs (the `v1_isa`
  suite and two that exercise the cards) run at chip level and agree with
  an instruction-level model of the same system. That covers output, RAM,
  the memory card, the CF card's disk and the registers, with no timing
  violation at worst-case delays.
- **The bus can be built as RFC 0014 says, with five changes,** all
  forced by timing:
  - SEL active high;
  - RDY and BERR from registers;
  - REQ registered, so a request on an idle bus takes 4 clocks;
  - the bus monitor counting data clocks;
  - a fast card's WAIT from its own address decode rather than from SEL.

  [RFC 0014's section 18](0014-rfc-system-bus.md#18-the-bus-as-built)
  lists them as pending.
- **Variable-length cycles make the suite's microcycles 1.14 times as
  fast:**
  - four lengths, 13, 15, 16 and 17 ticks of 20 ns, against a fixed 17;
  - for four chips: a microcode ROM, its register and two multiplexers;
  - at chip level the suite averages 304 ns a microcycle, bus transfers
    included, 1.12 times a fixed 340 ns clock.
- **A bus transfer is slow for the CPU.** A read from the memory card
  holds a microcycle for 520–600 ns, a write for 620–660 ns and a
  transfer to the I/O card for 880–960 ns. The read's 260 ns of bus time
  is about 60 ns more than RFC 0014 estimates, mostly because the bus
  clock reaches a card's logic 33 ns after the CPU card makes it.
- **The bus costs more chips than the RFC estimated:**

  | What | Built | RFC 0014's estimate |
  |---|---:|---:|
  | Backplane | 51 | about 28 |
  | Memory card | 31 | about 19 |
  | 32-bit MAR for the CPU's slot bits | 7 more | about 2 more |

  The differences are registers that timing asks for, and decoding the
  RFC left out.

## 1. What was built

| Slot | Card | Chips | What's on it |
|---|---|---:|---|
| – | Backplane | 51 | Clock drivers, power-on reset, slot and class lookup, transfer timing and the bus monitor, SEL, RDY/BERR and the status drivers, the arbiter |
| 0 | CPU | 269 | The 1b CPU (220 chips with its RAM, 213 in report 0012), its clock generator and length class (13), the bus interface (35), a reset buffer |
| 1 | Memory | 31 | 2 MB of 12 ns SRAM: a fast 32-bit card, close to RFC 0014's example |
| 15 | I/O | 16 | A 16C550 UART, an 82C54 timer and a CF card in True IDE mode, as a simple card |

The CPU card in slot 0 makes the bus clock: 60 ns, its 50 MHz master
clock divided by three. Each card clocks its bus logic from its own
slot's copy, through one buffer.

**The memory map** is RFC 0014's: the top four address bits pick the
slot.

- The CPU's own slot, 0, is its 1 MB RAM; any other slot is a bus
  transfer, and an empty slot is a bus error.
- The I/O card's registers sit in the top 256 bytes, where 16-bit absolute
  addresses reach them: the CF card at `0x40` and `0x80`, the UART at
  `0xC0`, the timer at `0xE0`.
- The UART, the CF card and the timer interrupt on IRQ0–2; the CPU card
  ORs them into the CPU's one interrupt input.
- 1b has no vector for bus errors, so they trap through the address error
  vector.

**Changes to the 1b CPU** are only where it meets the bus
(`cpu.build(card=True)`):

- the MAR holds 32 bits;
- 74F gates decode the slot bits early enough to keep a write for the bus
  off the RAM;
- a bus error raises FAULT, like a misaligned access.

That's 7 chips, against RFC 0014's estimate of about 2 (section 10). The
standalone CPU of report 0012 is unchanged.

**Software:** the `v1_isa` programs run on a runtime library that uses the
UART. Four had copies made because they used the old console register or
timer. Two are new:

- `memcard` checks every slot's ID and every access width, and runs a
  sieve with its table on the memory card;
- `cfcard` resets the CF card, identifies it, reads, writes and verifies
  sectors, and drives transfers from its interrupt.

**The reference** is an instruction-level model of the same system
([model/](../studies/v1b_system/model)). It runs on the `v1_isa`
simulator, with the same device models the chip-level simulator puts pins
on.

## 2. The bus as built

Building the bus met RFC 0014's timing budgets except in five places.
RFC 0014 now lists them in
[section 18](0014-rfc-system-bus.md#18-the-bus-as-built), as pending.

1. **SEL is active high.** The RFC makes every control signal active low,
   but a simple card's strobes are one Schmitt NAND from SEL, which needs
   it active high.
2. **RDY and BERR come straight from a register.** The RFC's budgets
   assume it. With a gate between the transfer's state and the driver, a
   master that decides on them misses its setup.
   - The backplane works out what they'll be in the next clock.
   - In an address clock that means the class lookup, the backplane's
     slowest path, so RDY's next value comes through a 74F153 that the
     address clock and WAIT select.
3. **REQ is registered.** From REQ to the grant registers is about 42 ns
   (priority encoder, owner comparison, grant decoder): more than a clock
   leaves after REQ arrives from a card.
   - A request on an idle bus now takes 4 clocks to the first address
     clock, not 3.
   - The main CPU doesn't notice, since the bus is parked on it.
4. **The bus monitor counts data clocks.** WAIT comes too late for a
   74F163's count enable (11.5 ns setup).
5. **A fast card can't raise WAIT from SEL.**
   - SEL reaches the card about 15 ns into the clock, so its WAIT is at
     the backplane about 41 ns in.
   - The backplane needs about 20 ns more to decide SEL and DPH for the
     next clock: 61 ns in a 60 ns clock.
   - The RFC's budget for this path stops at the master.
   - The memory card decides in the address clock instead. A 74F521
     compares A28–A31 with its slot number, and a register set from that
     drives WAIT and the write strobes.

**What the first version got wrong.** Besides the five above, chip-level
runs found these, all fixed. The first two are rules for later cards as
much as fixes:

- **The memory card's byte lanes** were decoded from the address register
  and could change under a write strobe. They're now decoded in the
  address clock and registered with the address.
- **Power-up:** random register states started a write on the memory card
  before reset reached its control logic. RESET now holds the write state
  clear. The CPU card's RAM gets the same treatment by being loaded when
  reset ends, as a loader would.
- **Bus errors:** after BERR, the CPU card's bus side waits two more
  clocks before saying it's done. That gives FAULT time to reach the
  microcode ROMs' address before the cycle ends. Until then it doesn't
  start another transfer.
- **The CPU card's read latch** drove the CPU's data bus while the RAM
  still did. It now drives from tick 4 of the cycle.
- **The CPU card's RAM writes** came out short, or glitched. Three
  changes fixed them:
  - the slot bits are decoded in 74F, so that a write meant for the bus
    is gated off before the window opens;
  - the write window opens at a fixed tick 10, from two J-K flip-flops;
  - the length analysis now asks a write's control inputs to settle
    before the window opens (section 4).

## 3. Chips

**The backplane** is 51 chips against RFC 0014's estimate of about 28
(its section 13.9):

| Part | Built | Estimate | Why the difference |
|---|---:|---:|---|
| Clock drivers, power-on reset | 6 | 3 | Four CDC341s, which specify part-to-part skew as report 0022 recommends, for 16 slots and the backplane |
| Input buffer, slot and class lookup | 6 | 6 | |
| SEL: decoders and registers | 5 | 4 | |
| Transfer timing and the bus monitor | 16 | 6 | Registered RDY and BERR need their next values, and the recovery clock and data-clock counting need state |
| Status drivers: DPH, RDY, BERR, W32 | 4 | 1 | The RDY/BERR register and its 74F153 |
| Arbiter | 14 | about 8 | The REQ and GNT registers (4), and the multiplexers that choose the next grant and owner (2) |
| **Total** | **51** | **about 28** | |

**The memory card** is 31 against about 19:

- the WAIT and write-strobe logic is 7 chips where the RFC counted about
  3, since its slot comparison and register replace WAIT from SEL;
- the registered byte lanes add about 4;
- the ID takes 3 chips, not 1.

**The I/O card** is 16: the UART (2 with its oscillator), the timer (7,
with its clock and the latch that holds its interrupt), the CF card (1),
the strobes, data transceiver and ID (5), and one interrupt gate.

**The CPU card's bus interface** is 35 chips:

| Part | Chips |
|---|---:|
| State | 13 |
| Access decode | 6 |
| Address registers | 5 |
| Data registers and transceivers | 6 |
| Hold and crossings | 4 |
| Interrupts | 1 |

Its clock generator and length class are 13 more. The schematic viewer
(`heron v1b_system schematic`) shows each of these as a sheet.

## 4. Variable-length cycles

The CPU card's clock generator counts 20 ns ticks of its 50 MHz master
clock:

- **The cycle.** It's K ticks long: four head ticks, a counter from a
  preload to 15, and two tail ticks.
- **The length class.** A 16th microcode ROM, beside the 15 that hold the
  microinstruction, gives each microinstruction a class from 0 to 3. Two
  74F153s pick that class's preload from jumpers.
- **The write window.** The RAM's write strobes are gated by a window
  from tick 10 to two ticks before the end. It comes from two J-K
  flip-flops that never change at the same edge, so it can't glitch.

**Choosing the classes.** Static timing analysis of every distinct
microinstruction, 3,396 of them, on the card's netlist gives the ticks
each needs: its slowest path to a register, and its RAM writes inside
the window.

- A write's control inputs must settle before the window opens, or its
  strobe can pulse twice. That's why the window opens late.
- A microinstruction that can reach the bus needs at least 12 ticks, for
  the hold point.
- The four lengths minimise the suite's time, given how often each
  microinstruction runs on the model.

| Class | Ticks | ns | Microinstructions |
|---:|---:|---:|---:|
| 0 | 13 | 260 | 1,339 |
| 1 | 15 | 300 | 922 |
| 2 | 16 | 320 | 1,026 |
| 3 | 17 | 340 | 109 |

**The gain:**

- **On the model's microcycles:** the suite takes 90.9 million ticks,
  against 103.4 million at a fixed 17. That's 1.138 times.
- **At chip level:** the average is 304 ns a microcycle, bus transfers
  included, against 340. That's 1.12 times.
- **The cost:** four chips, the length ROM, its register and the two
  multiplexers.

**Other parts and corners** need only new jumpers (`heron v1b_system
lengths`):

| Parts | Delays | Jumpers (ticks) |
|---|---|---|
| 74HCT and 74LS181 | worst case | 13, 15, 16, 17 |
| 74HCT and 74LS181 | typical | 13, 15, 15, 15 |
| 74ACT and 74F181 | worst case | 13, 15, 15, 15 |

With faster parts the classes stop at the clock generator's own floor:
the window opens at tick 10, whatever the parts.

## 5. What a bus transfer costs

Microcycle lengths over two whole programs at chip level, `memcard` and
`cfcard`, by what the microcycle did:

| Microcycle | Count | Length, ns (the commonest) |
|---|---:|---|
| No bus transfer | 793,095 | 260–340 |
| Read from the memory card | 17,979 | 520–600 (560) |
| Write to the memory card (two data clocks) | 27,989 | 620–660 (660) |
| Read from the I/O card | 6,650 | 880–920 (880) |
| Write to the I/O card | 3,560 | 920–960 (960) |
| An empty slot's bus error | 14 | 680–720 |

The spread comes from the bus clock's phase against the CPU's cycle and
from the microinstruction's length class.

**A read from the memory card, step by step,** in a 15-tick
microinstruction:

| ns into the cycle | What happens |
|---:|---|
| 140 | The clock generator holds its count (tick 7): the microinstruction reads at the MAR, on the bus |
| 160 | The request crosses to the bus side, at the master-clock edge that starts the bus clock's second phase |
| 214 | The address clock starts. It's the next bus clock edge, which the bus side's registers see 33 ns after the CPU card made it (the backplane's clock driver, the line, the card's buffer). The bus is parked on slot 0, so there's no arbitration |
| 334 | The data clock ends, and the read data is latched |
| 380 | Done crosses back, at the edge that starts the bus clock's first phase |
| 400 | The count resumes |
| 560 | The cycle ends, 8 ticks later: the rest of the count and the two tail ticks |

The bus holds the cycle for 260 ns. RFC 0014 estimates 180–220 ns for a
two-clock transfer (its section 10). The difference is the 33 ns by which
the bus side's clock lags, and the crossings at fixed phases of the
master clock. Those phases are why the crossings need no synchronisers:
the bus side's registers never change near them.

**Over a program,** the bus shows only where a program uses it:

- in `memcard`, 7.5% of the microcycles are transfers, and it averages
  334 ns a microcycle;
- the programs that only compute and print average 289–322 ns, except
  `hello` (333 ns), which does little but print.

Instructions are always fetched from the CPU card's RAM.

## 6. Performance

The suite at chip level, worst-case delays (`heron v1b_system test`):

| Program | Microcycles | Time (ms) | ns per microcycle |
|---|---:|---:|---:|
| arith | 139,147 | 44.6 | 320 |
| bignum | 31,657 | 10.0 | 315 |
| bst | 36,809 | 11.1 | 302 |
| cfcard | 224,330 | 72.1 | 321 |
| crc | 165,335 | 49.6 | 300 |
| fib | 363,484 | 108.7 | 299 |
| hello | 611 | 0.2 | 333 |
| interrupts | 110,472 | 31.9 | 289 |
| life | 610,851 | 183.0 | 300 |
| lines | 146,554 | 46.1 | 315 |
| mandel | 816,276 | 257.4 | 315 |
| matmul | 36,453 | 11.3 | 310 |
| memcard | 624,959 | 208.5 | 334 |
| monitor | 83,445 | 26.5 | 318 |
| queens | 193,634 | 57.5 | 297 |
| rpn | 56,158 | 18.0 | 320 |
| sha256 | 251,140 | 73.9 | 294 |
| sieve | 183,241 | 55.9 | 305 |
| sort | 105,143 | 31.9 | 304 |
| strings | 36,172 | 11.6 | 322 |
| vm | 2,847,614 | 839.3 | 295 |
| wordfreq | 277,922 | 85.8 | 309 |
| **all** | **7,341,407** | **2,235** | **304** |

The microcycle counts differ from report 0012's in two ways:

- the console is now a UART, polled through the bus;
- the timer is the 82C54, so `interrupts` waits on a different clock.

## 7. Verification

- **Programs:** each runs on the chip-level system and on the model. The
  comparison covers the UART's output, the CPU card's RAM, the memory
  card, the CF card's disk and the registers. A program names the words
  that depend on time (`;! timing-dependent: ticks`), and those are
  skipped.
- **Timing:** the simulator checks setup and hold on every register, the
  SRAMs' write timing, and the devices' strobe timing against their
  datasheets. It also reports bus contention.
  - The suite has no violation.
  - The worst contention is the CPU core's own 37 ns on its internal A
    and data buses, as in report 0012.
- **The bus against the RFC:** `tests/test_bus.py` uses scripted masters
  and a slave that never lets go of WAIT. They're the simulator's
  `vector` fixture, on the backplane with the real memory and I/O cards.
  The tests check:
  - each kind of transfer, clock by clock: fast reads and writes, IDs and
    byte lanes, a simple card, an empty slot, back-to-back transfers;
  - the arbiter's rules: one grant at a time, only on an idle bus,
    priority, withdrawal, LOCK;
  - the bus monitor's timeout.

## 8. Tools

The work added these, outside the study:

- **The simulator's system runner** (`infra/hwsim`): runs a whole system
  from power-up.
  - Oscillators and the power-on reset are parts in the netlist, so
    nothing is driven from outside.
  - Pull-ups and open-collector outputs are modelled, and pin-level models
    of the UART, the timer and the CF card check their strobe timing.
- **Device models** (`infra/devices`): the 16C550, the 82C54 and a True
  IDE CF card at register level. The chip-level simulator and the
  instruction-level model share them.
- **The `vector` fixture**, which plays a script against a clock, for
  bus-functional tests.
- **Netlist composition:** `include()` puts each card's netlist into a
  slot.
- **Datasheet timing** for the 74F and 74ABT parts and the devices.
- **A schematic viewer:** `heron v1b_system schematic` draws every card as
  a set of sheets, one for each section of the design, laid out in the
  browser. A net can be followed across sheets and cards.

## 9. Limits

- **One corner:** the simulator runs worst-case delays only. The 74ABT
  registers' hold margins are thin, 0.4 ns at worst case, and minimum
  delays aren't checked.
- **Parts:**
  - the 74F148 is obsolete;
  - the CDC341 is rated for the 60 ns bus clock but not for the 50 MHz
    master clock, which needs a part of its own.
- **Not built:**
  - instruction fetches over the bus;
  - a slave port into the CPU card's RAM;
  - a card ID for the CPU card;
  - 32-bit transfers: the CPU is a 16-bit master, and W32 isn't used;
  - LOCK, which is never asserted;
  - DMA, the MMU and the physical design.
