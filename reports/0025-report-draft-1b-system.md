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
[RFC 0007](0007-rfc-ideas-microarchitecture.md#2-clocking-variable-length-cycles). The
work is in [studies/v1b_system](../studies/v1b_system/README.md).
[Part I](#part-i-the-system) describes every card;
[Part II](#part-ii-findings) is what building and running them found.

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
  forced by timing ([3](#3-the-bus-as-built)):
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

## Part I: The system

Every card is a chip-level netlist; `bus.compose` puts them into slots
and the chip-level simulator runs the result from power-up. An
instruction-level model of the same system (`model/`, on the `v1_isa`
simulator) is what the hardware is checked against.

### 1. At a glance

| Slot | Card | Chips | What's on it |
|---|---|---:|---|
| – | Backplane | 51 | Clock drivers, power-on reset, slot and class lookup, transfer timing and the bus monitor, SEL, RDY/BERR and the status drivers, the arbiter |
| 0 | CPU | 269 | The 1b CPU (220 chips with its RAM, 213 in report 0012), its clock generator and length class (13), the bus interface (35), a reset buffer |
| 1 | Memory | 31 | 2 MB of 12 ns SRAM: a fast 32-bit card, close to RFC 0014's example |
| 15 | I/O | 16 | A 16C550 UART, an 82C54 timer and a CF card in True IDE mode, as a simple card |

| | |
|---|---|
| Chips | 367: backplane 51, CPU card 269, memory card 31, I/O card 16 |
| CPU clock | 50 MHz oscillator; each microcycle takes 13, 15, 16 or 17 ticks of 20 ns, by a length class in a 16th microcode ROM |
| Bus clock | 60 ns, the oscillator ÷ 3, from the CPU card in slot 0 |
| Speed | 289–334 ns per microcycle on the program suite (a fixed clock would need 340): 1.14× |
| Memory | 1 MB on the CPU card (slot 0), 2 MB on the memory card (slot 1) |
| I/O | 16C550 UART at 921600 baud, 82C54 timer counting microseconds, CF card in True IDE mode, 8-bit |
| Verified | The 22 programs at chip level, against the model: output, RAM, the memory card, the CF image and the registers; no timing violations. The bus against the RFC with scripted masters (`tests/test_bus.py`) |

### 2. Memory map

The top four address bits pick the slot (RFC 0014 section 4). The CPU's
own slot is its RAM; every other slot is a bus transfer.

| Address | What |
|---|---|
| `0x00000000`–`0x000FFFFF` | The CPU card's RAM (repeats through slot 0) |
| `0x10000000`–`0x101FFFFF` | The memory card (repeats through the slot); its ID, `0x0102`, at any address with A27 set and A1 clear |
| `0xF0000000`–`0xFFFFFFFF` | The I/O card: registers below, decoded from A2–A8, so they repeat every 512 bytes |
| other slots | Empty: a bus error |

Programs reach the I/O card's registers in the top 256 bytes with 16-bit
absolute addresses, which sign-extend to `0xFFFFFFxx`:

| Offset | Register |
|---|---|
| `0x40 + 4n` | CF control block (CS1): `0x58` alternate status / device control |
| `0x80 + 4n` | CF task file (CS0), registers 0–7 |
| `0xC0 + 4n` | UART registers 0–7 |
| `0xE0`, `0xE4`, `0xE8`, `0xEC` | Timer counters 0–2, control word |
| `0x...EE0` (A8 low) | Timer interrupt acknowledge: any write |

Any read of the I/O card also has its ID (`0x10`) in D8–D15.

**Interrupts:** the UART on IRQ0, the CF card on IRQ1, and the timer on
IRQ2: counter 0's output, rising, sets a flag that holds IRQ2 until it's
acknowledged. The CPU card ORs IRQ0–IRQ2 into the CPU's one IRQ; IRQ3–7
aren't used.

**Bus errors** (an empty slot, the bus monitor) trap through the address
error vector, `0x14`, with the faulting instruction's PC saved: 1b has no
vector of its own for them.

### 3. The bus as built

The backplane follows RFC 0014, with these differences, all from timing.
RFC 0014 lists them in
[section 18](0014-rfc-system-bus.md#18-the-bus-as-built), as pending.

- **SEL is active high,** not active low as the RFC's signal table says, so
  that a simple card's strobes are one Schmitt NAND from SEL, as its
  section 6 needs.
- **RDY and BERR come straight from a register** (the RFC's budgets assume
  it; a gate between the state and the driver is too slow for a master
  that decides on them). The backplane works out what they will be in the
  next clock: in an address clock that's the live class lookup, the
  slowest path on the backplane, so RDY's next value comes through a
  74F153 whose selects are the address clock and WAIT, and BERR's empty-slot
  part is one gate after the lookup.
- **REQ is registered** before the arbiter uses it. From REQ to the grant
  registers is about 42 ns of priority encoder, comparator and grant
  decoder, more than a clock leaves after a master's REQ arrives. So a
  request on an idle bus takes 4 clocks to the first address clock, not
  the RFC's 3. The main CPU doesn't notice, since the bus is parked on it.
- **The bus monitor counts data clocks,** not WAIT clocks: WAIT arrives
  too late for a 74F163's 11.5 ns enable setup. BERR comes in the clock
  after 256 clocks of WAIT.
- **A fast card can't raise WAIT from SEL** and meet the backplane's own
  timing: SEL reaches the card about 15 ns into the clock, so WAIT is
  about 41 ns in at the backplane, and the backplane needs about 20 ns
  more to decide SEL and the data phase for the next clock. The RFC's
  budget for this path stops at the master. The memory card decides in
  the address clock instead ([6](#6-memory-card-memcardpy)).

### 4. Backplane (`backplane.py`)

| Part | Chips |
|---|---:|
| Clock driver (CLKSRC to 16 slots and the backplane's own logic) | 4 CDC341 |
| Power-on reset, reset buffer | TL7705A, 74HCT14 |
| Input buffer: A28–A31, START, WAIT, LOCK, WRITE | 74ABT541 |
| Class lookup: CLASS0/1 of the addressed slot | 4 × 74F151, 74F157 |
| Transfer timing: state, slot and class register, data-clock counter, monitor | 74F74 × 2, 74ABT377, 74F163 × 3, gates |
| SEL: decoded into registers, so it never glitches | 2 × 74F138, 2 × 74ABT534 |
| RDY, BERR next-state and register; driver for DPH, RDY, BERR, W32 | 74F153, 74ABT574, 74ABT541 |
| Arbiter: REQ register, priority encoder, owner register and comparison, grant decoder and register | 2 × 74ABT574, 2 × 74F148, 74F521, 74F175, 2 × 74F157, 2 × 74F138, 2 × 74ABT574 |

Every register is clocked by the backplane's own copy of BCLK, through one
buffer like a card's, so its clock is as late as the cards' and the
clock skew stays within a package's.

**Transfer timing:** DQ marks a data clock, RQ a simple card's recovery
clock. An address clock loads the slot and class (U_SR) and a simple
card's data-clock counter (16 − N). A fast card's transfer goes on while
it holds WAIT, a simple card's for N clocks and then the recovery clock.
N is 6: the CF card in PIO mode 0 wants 290 ns strobes and 70 ns of
address setup.

### 5. CPU card (`cpucard.py`)

The draft 1b CPU in its card mode (`cpu.build(card=True)` in
`studies/v1b_hw/cpu.py`), with what the standalone machine had as fixtures
(the clock, the I/O device) replaced by the clock generator and the bus
interface. Card mode changes the CPU itself only where the bus meets it;
the standalone CPU of report 0012 is unchanged:

- the MAR is 32 bits, and MARBUS, the OR of its slot bits, says an access
  goes to the bus;
- RAMOFF keeps the RAM off the data bus for a bus access, and gates its
  write strobes (74F parts, so it's there before the write window opens);
- FAULT is a misaligned access or a bus error, and selects the address
  error entry as before.

#### 5.1 The clock generator

A 50 MHz oscillator (MCLK) drives three things:

- **The bus clock:** a ring of three flip-flops makes the 60 ns BCLK
  source (CLKSRC) for the backplane. Like every card, the CPU card then
  clocks its bus logic from its own slot's BCLK, through one buffer.
- **The CPU clock:** a cycle is K ticks of 20 ns: 4 head ticks, a
  74ACT163 counting from a preload P = 22 − K to 15, and 2 tail ticks.
  CLK is high for the first two ticks.
- **The length class:** a 16th microcode ROM, beside the 15 that hold the
  microinstruction, gives each microinstruction a class, 0–3, registered
  with it. Two 74F153s pick that class's preload from jumpers.

The RAM's write strobe is gated by a write window that opens at tick 10
and closes two ticks before the end of the cycle. It comes from two J-K
flip-flops that never change at the same edge, so the window can't
glitch.

#### 5.2 Length classes (`lengths.py`)

Static timing analysis (`infra/hw/sta.py`) of every distinct
microinstruction, 3,396 of them, with the CPU card's netlist, gives the
ticks each one needs: its slowest path to a register, and its RAM writes
inside the window with the RAM's address and data setup. A write also
needs the window's opening to come after the write enable's inputs have
settled, or the strobe glitches; that's why the window opens late. A
microinstruction that can go to the bus needs at least 12 ticks, so that
the bus hold comes at least 6 ticks before the end.

The four lengths are chosen to minimise the program suite's time, given
how often each microinstruction runs (the suite's profile on the model):

| Class | Ticks | ns | Microinstructions |
|---:|---:|---:|---:|
| 0 | 13 | 260 | 1,339 |
| 1 | 15 | 300 | 922 |
| 2 | 16 | 320 | 1,026 |
| 3 | 17 | 340 | 109 |

`heron v1b_system lengths` prints the jumpers for every set of parts.

#### 5.3 The bus interface

A bus access is one microcycle, held at a fixed point until the transfer
is over:

1. A tick after bit 3 of the count is seen (from count 9, or tick 5 in a
   short class), the clock generator stops counting (HOLD) if the
   microinstruction reads or writes at the MAR on the bus.
2. The request crosses to the bus side at the MCLK edge entering the
   bus clock's phase P2, one tick after CLKSRC rises; the answer comes
   back at the edge entering P1, the next CLKSRC rise. The bus side's
   flip-flops change about 33 ns after CLKSRC rises (the clock driver on
   the backplane, the line, the card's buffer), so these fixed phases
   never catch them changing, and the crossings need no synchronisers.
3. The bus side asks for the bus (REQ), starts an address clock when it
   has GNT, registers the address, byte enables and WRITE (4 ×
   74ABT823), and drives write data from the address clock to the end.
   It ends at RDY without WAIT, or at BERR.
4. A read is registered at the end of every data clock with DPH and
   without WAIT (2 × 74ABT823). The latch drives the CPU's data bus from
   tick 4 of the cycle to just after its end, once the RAM has let go of
   it.
5. After BERR the bus side waits two more clocks before saying it's done,
   so that FAULT has time to reach the microcode ROMs' address before the
   cycle ends; meanwhile it doesn't start another transfer.

The CPU is a 16-bit master: a word is two halfword transfers, in two
microcycles, and a byte goes on both halves of D0–D15. W32 isn't used.

**Limits:** instruction fetches come only from the CPU card's RAM (the
fetch address doesn't go through the bus); there's no slave port into
the CPU card's RAM, no card ID for the CPU card, and no cycle counter
register. LOCK is never asserted.

### 6. Memory card (`memcard.py`)

A fast 32-bit card, close to RFC 0014's example: 4 × AS7C4096A-12, the
address and byte enables registered at the end of every address clock,
transceivers for D0–D15, D16–D31 and the swap between them.

- **Reads** take one data clock.
- **Writes** take two. The card holds WAIT in the first and writes the
  SRAMs during it, while the master still drives the data. One clock
  would need the strobe to end before the clock edge, and the bus gives
  no earlier time to end it on (the RFC doesn't define BCLK's duty cycle).
- **WAIT and the write strobes** come from a register (W1) set by an
  address clock that writes to this slot: a 74F521 compares A28–A31
  with the slot number (GA0–GA3). WAIT from SEL would be too late
  ([3](#3-the-bus-as-built)). Two drivers put W1 on WAIT: one while SEL is
  asserted, as the RFC says, and one from W1 itself, since SEL comes too
  late.
- **The byte lanes** are decoded in the address clock and registered with
  the address, so they are steady before a write strobe can start.
- **The swap** for a halfword at A1 = 1 happens behind the card's bus
  transceivers, so each bus line sees one transceiver pin. The RFC's chip
  list puts two on D0–D15.
- **RESET** holds W1 clear, so that power-up's random state can't start a
  write.

### 7. I/O card (`iocard.py`)

A simple card: no clock, no address registers. Its strobes come from SEL
and WRITE through a 74HCT132, its devices decode A2–A8 themselves, and a
74HCT245 joins their D0–D7 to the bus. A 74HCT541 puts the ID on D8–D15
in any read.

- **UART:** TL16C550C with a 14.7456 MHz oscillator: 921600 baud at
  divisor 1. The terminal on its serial line is part of the model; it
  sends the program's input and records what the UART sends.
- **Timer:** 82C54 with a 1 MHz clock on all three counters. Counter 0's
  output sets a flag that drives IRQ2 until a write to the acknowledge
  address.
- **CF card:** True IDE mode, data on D0–D7 only, so programs set 8-bit
  transfers (SET FEATURES 01h) first.

### 8. Software (`sw/v1b`)

The system's runtime library replaces the `v1_isa` one where the console
changed: `lib/start.s` sets up the UART and calls `main`, `lib/uart.s` has
the polled console primitives, and `lib/console.s` and `lib/print.s`
build on them. The terminal's input ends with ^D.

The `v1_isa` programs run unchanged against it, except the four that used
the console register directly or the old timer (`interrupts`), which have
copies here. Two programs are the system's own:

- `memcard`: every slot's ID and the empty slots' bus errors, every width
  written and read back on the memory card, single bytes and halves into
  words, the address lines, misaligned accesses, memcpy both ways, and a
  sieve with its table on the card.
- `cfcard`: the CF card's reset signature, IDENTIFY DEVICE, reads and
  writes checked against the disk's pattern, READ VERIFY, the error
  cases, and transfers driven by the card's interrupt.

### 9. Simulation

- **The chip level** (`machine.py`): `infra/hwsim`'s system runner plays
  the whole netlist from power-up, with oscillators and the power-on reset
  as parts. RAM images are loaded when reset ends, as a loader would put
  them there: power-up's random state can write to a RAM before reset
  reaches its control logic. A run checks setup, hold, the SRAMs' write
  timing and the devices' strobe timing, and reports bus contention.
- **The model** ([`model/`](../studies/v1b_system/model)): the cards
  behind the CPU, for the `v1_isa` simulator. It decodes addresses as the
  cards do and runs the same device models (`infra/devices`), with time
  from the cycle count at 300 ns a cycle. `heron v1b_system test` compares
  everything that doesn't depend on time; a program names the words that
  do (`;! timing-dependent: ticks`).
- **The bus tests** (`bfm.py`, `tests/test_bus.py`): scripted masters and
  a slave that never lets go of WAIT, as `vector` fixtures, on the
  backplane with the real memory and I/O cards. They check each class of
  transfer clock by clock, the arbiter's rules (one grant at a time, only
  on an idle bus, priority, withdrawal, LOCK) and the bus monitor.

## Part II: Findings

### 10. What the first version got wrong

Besides the five differences from RFC 0014 ([3](#3-the-bus-as-built)),
chip-level runs found these, all fixed. The first two are rules for later
cards as much as fixes:

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
    before the window opens ([5.2](#52-length-classes-lengthspy)).

### 11. Chips

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

**The CPU's changes for the bus** ([5](#5-cpu-card-cpucardpy)) are 7
chips, against RFC 0014's estimate of about 2 (its section 10).

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

### 12. Variable-length cycles

The mechanism is in Part I ([5.1](#51-the-clock-generator) and
[5.2](#52-length-classes-lengthspy)).

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

### 13. What a bus transfer costs

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

### 14. Performance

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

### 15. Verification

- **Programs:** all 22 agree with the model ([9](#9-simulation)): the
  UART's output, the CPU card's RAM, the memory card, the CF card's disk
  and the registers, leaving out the words a program names as depending
  on time.
- **Timing:** the suite has no violation of setup or hold, the SRAMs'
  write timing or the devices' strobe timing. The worst bus contention is
  the CPU core's own 37 ns on its internal A and data buses, as in
  report 0012.
- **The bus against the RFC:** `tests/test_bus.py` passes. It checks:
  - each kind of transfer, clock by clock: fast reads and writes, IDs and
    byte lanes, a simple card, an empty slot, back-to-back transfers;
  - the arbiter's rules: one grant at a time, only on an idle bus,
    priority, withdrawal, LOCK;
  - the bus monitor's timeout.

### 16. Tools

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

### 17. Limits

- **One corner:** the simulator runs worst-case delays only. The 74ABT
  registers' hold margins are thin, 0.4 ns at worst case, and minimum
  delays aren't checked.
- **Parts:**
  - the 74F148 is obsolete;
  - the CDC341 is rated for 80 MHz with one bank loaded and 40 MHz with
    both: fine for the 60 ns bus clock, but not for the 50 MHz master
    clock, which needs a part of its own.
- **Not built:** what the bus interface leaves out
  ([5.3](#53-the-bus-interface)): instruction fetches over the bus, a
  slave port into the CPU card's RAM, a card ID for the CPU card, 32-bit
  transfers and LOCK. Nor DMA, the MMU or the physical design.
