# The system: draft 1b on the bus

The draft 1b CPU ([v1b_hw](../v1b_hw/hardware.md)) as a card on the
system bus of [RFC 0014](../../reports/0014-rfc-system-bus.md), with the
backplane's logic, a memory card and an I/O card. Every card is a
chip-level netlist; `bus.compose` puts them into slots and the chip-level
simulator runs the result from power-up. An instruction-level model of the
same system (`model/`, on the `v1_isa` simulator) is what the hardware is
checked against.

Left out, as asked: anything the 1b ISA doesn't have (MMU, floating
point), DMA, video, and the physical design (card sizes, connectors).

## At a glance

| | |
|---|---|
| Chips | 367: backplane 51, CPU card 269, memory card 31, I/O card 16 |
| CPU clock | 50 MHz oscillator; each microcycle takes 13, 15, 16 or 17 ticks of 20 ns, by a length class in a 16th microcode ROM |
| Bus clock | 60 ns, the oscillator ÷ 3, from the CPU card in slot 0 |
| Speed | 289–334 ns per microcycle on the program suite (a fixed clock would need 340): 1.14× |
| Memory | 1 MB on the CPU card (slot 0), 2 MB on the memory card (slot 1) |
| I/O | 16C550 UART at 921600 baud, 82C54 timer counting microseconds, CF card in True IDE mode, 8-bit |
| Verified | The 22 programs at chip level, against the model: output, RAM, the memory card, the CF image and the registers; no timing violations. The bus against the RFC with scripted masters (`tests/test_bus.py`) |

## Memory map

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

## The bus as built

The backplane follows RFC 0014, with these differences, all from timing:

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
  the RFC's 3.
- **The bus monitor counts data clocks,** not WAIT clocks: WAIT arrives
  too late for a 74F163's 11.5 ns enable setup. BERR comes in the clock
  after 256 clocks of WAIT.
- **A fast card can't raise WAIT from SEL** and meet the backplane's own
  timing: SEL reaches the card about 15 ns into the clock, so WAIT is
  about 41 ns in at the backplane, and the backplane needs about 20 ns
  more to decide SEL and the data phase for the next clock. The memory
  card decides in the address clock instead (below).

## Backplane (`backplane.py`)

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

The RFC estimated about 28 chips. The difference is mostly the
registered radial outputs (SEL, GNT: 8 chips), the class lookup (5), the
REQ register (2) and the next-state logic for RDY and BERR.

Every register is clocked by the backplane's own copy of BCLK, through one
buffer like a card's, so its clock is as late as the cards' and the
clock skew stays within a package's.

**Transfer timing:** DQ marks a data clock, RQ a simple card's recovery
clock. An address clock loads the slot and class (U_SR) and a simple
card's data-clock counter (16 − N). A fast card's transfer goes on while
it holds WAIT, a simple card's for N clocks and then the recovery clock.
N is 6: the CF card in PIO mode 0 wants 290 ns strobes and 70 ns of
address setup.

## CPU card (`cpucard.py`)

The draft 1b CPU in its card mode (`cpu.build(card=True)` in
`studies/v1b_hw/cpu.py`), with what the standalone machine had as fixtures
(the clock, the I/O device) replaced by the clock generator and the bus
interface. Card mode changes the CPU itself only where the bus meets it:

- the MAR is 32 bits, and MARBUS, the OR of its slot bits, says an access
  goes to the bus;
- RAMOFF keeps the RAM off the data bus for a bus access, and gates its
  write strobes (74F parts, so it's there before the write window opens);
- FAULT is a misaligned access or a bus error, and selects the address
  error entry as before.

### The clock generator

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

### Length classes (`lengths.py`)

Static timing analysis (`infra/hw/sta.py`) of every distinct
microinstruction, with the CPU card's netlist, gives the ticks each one
needs: its slowest path to a register, and its RAM writes inside the
window with the RAM's address and data setup. A write also needs the
window's opening to come after the write enable's inputs have settled, or
the strobe glitches. A microinstruction that can go to the bus needs at
least 12 ticks, so that the bus hold comes at least 6 ticks before the
end.

The four lengths are chosen to minimise the program suite's time, given
how often each microinstruction runs (the suite's profile on the model):

| Class | Ticks | ns | Microinstructions |
|---:|---:|---:|---:|
| 0 | 13 | 260 | 1339 |
| 1 | 15 | 300 | 922 |
| 2 | 16 | 320 | 1026 |
| 3 | 17 | 340 | 109 |

That's 1.138× faster than a fixed 340 ns clock over the suite.
`heron v1b_system lengths` prints the jumpers for every set of parts.

### The bus interface

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

## Memory card (`memcard.py`)

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
  with the slot number (GA0–GA3). WAIT from SEL would be too late (above).
  Two drivers put W1 on WAIT: one while SEL is asserted, as the RFC says,
  and one from W1 itself, since SEL comes too late.
- **The byte lanes** are decoded in the address clock and registered with
  the address, so they are steady before a write strobe can start.
- **The swap** for a halfword at A1 = 1 happens behind the card's bus
  transceivers, so each bus line sees one transceiver pin. The RFC's chip
  list puts two on D0–D15.
- **RESET** holds W1 clear, so that power-up's random state can't start a
  write.

## I/O card (`iocard.py`)

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

## Software (`sw/v1b`)

The system's runtime library replaces the `v1_isa` one where the console
changed: `lib/start.s` sets up the UART and calls `main`, `lib/uart.s` has
the polled console primitives, and `lib/console.s` and `lib/print.s`
build on them. The terminal's input ends with ^D.

The `v1_isa` programs run unchanged against it, except the ones that used
the console register directly or the old timer (`interrupts`), which have
copies here. Two programs are the system's own:

- `memcard`: every slot's ID and the empty slots' bus errors, every width
  written and read back on the memory card, single bytes and halves into
  words, the address lines, misaligned accesses, memcpy both ways, and a
  sieve with its table on the card.
- `cfcard`: the CF card's reset signature, IDENTIFY DEVICE, reads and
  writes checked against the disk's pattern, READ VERIFY, the error
  cases, and transfers driven by the card's interrupt.

## Simulation

- **The chip level** (`machine.py`): `infra/hwsim`'s system runner plays
  the whole netlist from power-up, with oscillators and the power-on reset
  as parts. RAM images are loaded when reset ends, as a loader would put
  them there: power-up's random state can write to a RAM before reset
  reaches its control logic. A run checks setup, hold, the SRAMs' write
  timing and the devices' strobe timing, and reports bus contention.
- **The model** (`model/`): the cards behind the CPU, for the `v1_isa`
  simulator. It decodes addresses as the cards do and runs the same
  device models (`infra/devices`), with time from the cycle count at
  300 ns a cycle. `heron v1b_system test` compares everything that doesn't
  depend on time; a program names the words that do
  (`;! timing-dependent: ticks`).
- **The bus tests** (`bfm.py`, `tests/test_bus.py`): scripted masters and
  a slave that never lets go of WAIT, as `vector` fixtures, on the
  backplane with the real memory and I/O cards. They check each class of
  transfer clock by clock, the arbiter's rules (one grant at a time, only
  on an idle bus, priority, withdrawal, LOCK) and the bus monitor.

## Performance

At chip level, worst-case delays (`heron v1b_system test`):

| Program | Microcycles | Time | ns per microcycle |
|---|---:|---:|---:|
| arith | 139,147 | 44.6 ms | 320 |
| fib | 363,484 | 108.7 ms | 299 |
| life | 610,851 | 183.0 ms | 300 |
| mandel | 816,276 | 257.4 ms | 315 |
| sha256 | 251,140 | 73.9 ms | 294 |
| vm | 2,847,614 | 839.3 ms | 295 |
| memcard | 624,959 | 208.5 ms | 334 |
| cfcard | 224,330 | 72.1 ms | 321 |

The programs that use the bus most are the slowest per microcycle: a
transfer to the memory card holds its microcycle for 620–680 ns, and one
to the I/O card for 880–960 ns.

## Known issues

- **Hold margins** on the ABT registers are thin (0.4 ns at worst-case
  delays), and the simulator runs at one corner: minimum delays aren't
  checked.
- **Inherited from v1b_hw:** contention of up to 37 ns on the CPU's
  internal A and data buses, the same as in the standalone machine.
- **The 74F148** is obsolete.
- **The CDC341** is rated for 80 MHz with one bank loaded, 40 MHz with
  both: fine for the bus clock, not for MCLK.
