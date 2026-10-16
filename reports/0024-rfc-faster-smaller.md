---
number: 24
type: rfc
title: Faster and smaller: where the system's time and chips go
status: open
date: 2026-10-15
context:
  studies: [v1b_tradeoffs, v1b_system, v1b_hw, v1_isa]
  commit: d64d5a7
depends-on: [7, 14, 25]
---

# RFC 0024: Faster and smaller: where the system's time and chips go

The draft 1b system ([studies/v1b_system](../studies/v1b_system/README.md),
[report 0025](0025-report-draft-1b-system.md)) is 367 chips and runs a microcycle
every 300 ns or so. This RFC asks how much faster and how much smaller it
could be, and what each step costs: where the time and the chips go now,
how far either could go at best, which levers move them, measured where
it could be, and which requirements behind the design are worth another
look.

The measurements are in [studies/v1b_tradeoffs](../studies/v1b_tradeoffs/README.md);
every generated table is in [results.md](0024-rfc-faster-smaller/results.md).
Chip-level runs and static timing use worst-case datasheet delays, as
the reports before this one do.

Statuses: **recommended**, **open** (a real choice either way) and **not
recommended**. Nothing here is decided. Numbers marked *estimate* come
from counting or a model, not from a netlist.

## Contents

1. [Summary](#1-summary)
2. [Where the time goes](#2-where-the-time-goes)
3. [Where the chips go](#3-where-the-chips-go)
4. [How far it could go](#4-how-far-it-could-go)
5. [Faster: parts](#5-faster-parts)
6. [Faster: a clock generator for fast parts](#6-faster-a-clock-generator-for-fast-parts)
7. [Faster: fewer cycles](#7-faster-fewer-cycles)
8. [Smaller: packages and PLDs](#8-smaller-packages-and-plds)
9. [Smaller: what the ISA's features cost](#9-smaller-what-the-isas-features-cost)
10. [Smaller: a narrower datapath](#10-smaller-a-narrower-datapath)
11. [Smaller: the bus](#11-smaller-the-bus)
12. [Requirements worth another look](#12-requirements-worth-another-look)
13. [Design points](#13-design-points)
14. [What was tried and didn't work](#14-what-was-tried-and-didnt-work)
15. [Open questions](#15-open-questions)

## 1. Summary

- **The parts set the speed.** The microcycle is as long as 74HCT logic
  and 55 ns memories make it. With 74F and 74ABT logic and 12 ns SRAM
  for the RAM and the register file, the 1b CPU's netlist, unchanged,
  needs 159 ns at worst case instead of 334 ns, for no chips more; with
  the control store in 12 ns SRAM as well (about 15 chips for its
  loader), 107 ns, and the chip-level simulator runs the exercise
  program down to 102.5 ns.
- **The system's clock generator caps that gain at 15%.** It opens the
  write window 10 ticks into the cycle and holds bus accesses from count
  9, so no cycle is shorter than 13 ticks (260 ns), whatever the parts.
  A clock generator for short cycles, 4 to 19 ticks, is 4 chips
  smaller than the present one ([section 6](#6-faster-a-clock-generator-for-fast-parts)).
- **Measured at chip level**, the whole system with the fast parts and
  the new clock generator runs the program suite 2.71 times as fast with
  the control store in 12 ns SRAM (2.8 to 3.2 times on the programs that
  compute rather than print), and 2.26 times as fast with it in the
  present flash (2.2 to 2.6 times). Every program matches the
  instruction-level model, with no timing violation.
- **Cycles have about a factor of two left in them.** The hardware takes
  3.37 cycles per instruction; a 16-bit memory bus can't go below 1.67,
  a 32-bit one below 1.40. An overlapped fetch saves an estimated 9% of
  cycles, a 32-bit memory with a prefetch buffer 20%, and with a
  register file written in the second half of a cycle up to 36%.
- **The bus is a third of the chips.** The backplane (51), the CPU card's
  bus side (36) and the memory card (31, against about 5 for the same
  memory on the CPU card) come to about 120 of the 367.
- **No ISA feature is a big lever.** Each of 1b's costs 10 chips or
  fewer, and dropping the biggest, the multiply and divide hardware,
  would cost 45% more cycles. The chips are in the datapath's width
  times its number of sources (37 octal buffers, 37 dual multiplexers),
  the 30-chip control store, the PC and the MAR.
- **Packaging is the cheapest size lever.** 16-bit "Widebus" registers,
  buffers and transceivers, and 16-bit-wide SRAM for the register file,
  save 53 chips with no change to the design, if the boards may use
  fine-pitch surface-mount packages, which Emily is now more open to.
  GALs, which she'd rather not use, would save roughly 70 to 100 more
  (*estimate*).
- **A narrower datapath doesn't pay.** Once 16-bit parts are used, a
  16-bit datapath saves only about 30 more chips, for 10 to 30% more
  time. This agrees with RFC 0005, where building narrow first is
  rejected.

**Recommended:** fast parts and the new clock generator (2.3 times at
chip level with the flash control store, for no chips); 16-bit parts
(−53) if the packages are allowed; then decide on GALs, the SRAM control store,
the bus's multi-master and slot count, and the cycle levers
([section 13](#13-design-points), [section 15](#15-open-questions)).

## 2. Where the time goes

Over the program suite (20 programs, 1.5 million instructions, 6.08
million microcycles on the RTL model):

| Microcycles that are | Share |
|---|---:|
| ALU, address or shift work | 38.3% |
| opcode fetches | 24.6% |
| data reads, a 16-bit half each | 14.3% |
| multiply or divide steps | 12.1% |
| extension parcels | 5.4% |
| data writes, a 16-bit half each | 4.9% |

Half the cycles use the memory bus. The system's four length classes
are 13, 15, 16 and 17 ticks of 20 ns, and the suite's microcycles take
1.82 s.

**What sets a cycle's length.** With 74HCT, the slowest path is the signed
multiply step's sign logic after the carry (334 ns), and every
instruction's last cycle carries the fetch: RAM, decode ROM, the
next-address multiplexer and the microcode ROM in a row, three 55 ns
memories (309 ns). With fast logic, the memories dominate: the fetch path
is about 150 ns with flash and 65 ns with SRAM; with the control store in
SRAM the slowest path is again the signed multiply step's, through the
register file, the 74F181/182 carry chain, the sign logic and the result
multiplexer (107 ns, [results.md](0024-rfc-faster-smaller/results.md#parts)).

**The bus.** Report 0025 measured what a transfer costs: a read from
the memory card holds its microcycle for 520–600 ns, a write (two data
clocks) for 620–660 ns, a read from the I/O card for 880–920 ns and a
write to it for 920–960 ns
([report 0025](0025-report-draft-1b-system.md#13-what-a-bus-transfer-costs)).
Only programs that use the cards notice: instruction fetches always come
from the CPU card's RAM.

## 3. Where the chips go

| Card | Chips | Biggest parts of it |
|---|---:|---|
| CPU | 269 | control store 30, result multiplexer 18, A bus 17, register file 17, flags 15, the bus interface's state 15, PC 13, MAR 12, ALU 12, memory 12, B bus 12, immediate unit 10, clock generator 10 |
| Backplane | 51 | arbiter 15, transfer timing 14, clock and reset 6, slot and class lookup 6, status outputs 5, SEL 5 |
| Memory | 31 | address and lanes 7, WAIT and write strobes 7, data transceivers 7, SRAM 5, card ID 3 |
| I/O | 16 | timer 8, strobes and data 5, UART 2 |

Per section: [results.md](0024-rfc-faster-smaller/results.md#chips-by-card-and-section).

The 213-chip CPU core is mostly routing, not function:

- **37 × 74HCT541** drive the A bus (PC, R, R × 2, the bridge from B), the
  B bus (R, T by byte lane, 2 × T, the immediate unit, the flags) and the
  store data: 17% of the core. **37 × 74HCT153**: the result multiplexer
  (16), the register file's address (4), the next address (6), the
  immediate unit (4) and the rest.
- **The control store** is 15 flash ROMs and 15 registers for a 120-bit
  microinstruction, plus the length class ROM and its register on the
  card. The microcode uses its fields sparsely: numbering the values
  each group of fields takes would need 56 bits, not 120
  ([results.md](0024-rfc-faster-smaller/results.md#the-microinstruction)).
- **The PC** is eight 74HCT161 counters and five gates of carry
  lookahead; **the MAR** four registers and eight 2:1 multiplexers, so
  that auto-increment can load it from the A bus.

## 4. How far it could go

**The microcycle.** A 32-bit microcoded machine of this kind does, in its
slowest common cycle, a register-file read, a 32-bit add and a register
load. With the best parts the timing data has (74F181/182, 12 ns SRAM,
74ABT registers):

| Path | ns |
|---|---:|
| microinstruction register to the register file's address | 7 (or 19 through a multiplexer, as in 1b) |
| register file access | 12 |
| 32-bit add: 74F181, two levels of 74F182, 74F181 | 51 |
| setup | 3 |
| **register to register, 32 bits** | **73–85** |
| next address, control store, microinstruction register: SRAM / flash | 34 / 77 |
| the fetch: RAM, decode, next address, control store: SRAM / flash | 65 / 150 |

So about 75–85 ns is the floor for a cycle that adds 32 bits, about
12 MHz, and 150 ns for any cycle that decodes an instruction out of
flash, unless decoding moves a cycle later. The fast 1b CPU is at 107 ns
for its slowest microinstruction; most need 40–100 ns, a third less
than 60
([results.md](0024-rfc-faster-smaller/results.md#parts)).

**Cycles.** Counting one resource busy every cycle and nothing else,
geometric mean over the 18 programs report 0012 uses:

| | Cycles per instruction |
|---|---:|
| the 1b hardware | 3.37 |
| 16-bit memory bus: every parcel and data half takes a cycle | 1.67 |
| 32-bit memory bus: every 32-bit word of code and every data transfer | 1.40 |
| ALU: a cycle per instruction, per multiply, divide or shift step | 1.40 |
| the larger of the 16-bit bus and the ALU, per program | 1.90 |
| the larger of the 32-bit bus and the ALU, per program | 1.67 |

A machine with a 16-bit memory bus can't take fewer than about 1.7–1.9
cycles per instruction, one with a 32-bit bus about 1.4–1.7, without
pipelining that overlaps instructions. Even a pipelined machine with
separate instruction and data memories stops at 1.40, held by the
multiply and divide steps. With the microcycle's floor, that's roughly
105–160 ns per instruction at best, against about 400 ns for the fast
system with the control store in SRAM (490 ns with it in flash) and
1,200 ns for the system as built (the suite's microcycle time divided by
its instructions).

**Chips.** An inventory of what a 32-bit microcoded 1b CPU needs at
least, with 16-bit parts and without PLDs: the control store and its
register (about 23), sequencing and decode (9), the register file (8),
the ALU and its control (14), the shifts (8–16), the PC (10), the MAR
(10), R and T (4), bus drivers (about 10), the immediate unit (6),
multiply and divide (6), flags and conditions (12), the memory
interface (8) and glue. About 140–150 chips (*estimate*), against 213
for the 1b CPU and 176 for the same CPU with 16-bit parts.

## 5. Faster: parts

Static timing analysis of the 1b CPU's netlist, unchanged, with other
parts; times for the suite's microcycles with four length classes on a
20 ns grid (the CPU alone, with report 0012's write window):

| Parts | Slowest microinstruction | Suite, 4 classes | Speed-up |
|---|---:|---:|---:|
| 74HCT, 74LS181, 55 ns RAM and flash (as built) | 334 ns | 1.75 s | 1 |
| 74ACT, 74F181, 55 ns RAM and flash | 211 ns | 0.93 s | 1.9 |
| 74ACT, 74F181, 12 ns RAM, 55 ns flash | 176 ns | 0.86 s | 2.0 |
| 74F and 74ABT, 74F181, 12 ns RAM, 55 ns flash | 159 ns | 0.72 s | 2.4 |
| the same, decode ROMs in 12 ns SRAM | 116 ns | 0.66 s | 2.6 |
| the same, the whole control store in 12 ns SRAM | 107 ns | 0.51 s | 3.4 |

"74F and 74ABT" takes the faster family for each type: 74F for gates,
multiplexers, decoders, counters and the 74F299, 74ABT for registers,
buffers and transceivers ([parts.py](../studies/v1b_tradeoffs/parts.py)).
The timing data gained the 74F161, the 74F299 and the 64K × 16
IS61C6416AL for this, from their datasheets. With typical delays instead
of worst case the fast parts gain less than 74HCT does (1.2 against
1.6 times), since memory access times don't improve. (The slowest
microinstructions of the two rows with flash decode a fetch through the
standalone netlist's I/O fixture, a 20 ns stand-in on the data bus; with
only the 12 ns RAM there, they'd need about 151 and 108 ns.)

**The chip-level simulator agrees.** The unchanged netlist with the
fastest set runs fib, sieve, strings and hello at 108 ns, and the
exercise program (every instruction, mode and trap) down to 102.5 ns,
with no timing violation; bus contention drops from 37 ns to 6 ns.

**The control store in SRAM** isn't free. Fast SRAM is empty at power-up,
so something must fill it from flash: about 10 64K × 16 SRAMs for the
microcode, the length classes and the decode table, one to three flash
chips for their images (1.25 MB in all, less if the loader skips the
unused parts of the microcode's address space), and a loader that drives
their 160 data pins and their addresses (about 22 chips: 16-bit buffers,
a counter, a decoder for the write strobes). About 15 chips more than the
18 flash ROMs now (*estimate*). In return: 1.25
times the speed, and a writable control store, the user-defined opcodes
of [RFC 0005](0005-rfc-ideas-direction.md). **open.** The decode ROMs alone
in SRAM gain 9% for about 8 chips. **not recommended.**

**Costs of fast parts.**

- **Power.** 74F parts and 12 ns SRAMs draw far more supply current
  than 74HCT and flash: several amps more at 5 V for the CPU card
  (*estimate*). It needs a supply and a board that carry it.
- **Edges.** 74F and 74ABT edges are 2–3 ns: the 4-layer boards already
  decided are what they need, with short traces on the CPU card's buses.
- **Temperature.** 74F is specified for 0–70 °C, not −40–85 °C.
- **Packages.** The 12 ns SRAMs come only in SOJ and TSOP.

**Recommended:** 74F/74ABT logic, 12 ns SRAM for the RAM and the register
file, with the control store in flash for now.

## 6. Faster: a clock generator for fast parts

The CPU card's clock generator was made for 74HCT. A cycle is K ticks:
four head ticks, the counter from a preload to 15, two tail ticks; the
write window opens 10 ticks in; a bus access holds the count at 9. So K
is at least 13 (a window of one tick, two tail ticks), and with the fast
parts every microinstruction falls into 13 ticks: 1.58 s for the suite
against 1.82 s, 15% faster.

[fastcard.py](../studies/v1b_tradeoffs/fastcard.py) is the card with a
clock generator for short cycles, and the bus interface unchanged:

- **Two head ticks and one tail tick.** The length class comes through
  the microinstruction register and a 74F153 about 30 ns into the cycle
  (19 ns after the CPU clock, which a flip-flop makes 9.5 ns after the
  master clock's edge), so the counter loads its preload entering tick 2.
  K is 4 to 19.
- **The write window** opens entering tick 2 and closes entering the
  tail, without a glitch: it's MID and not TAILX, two J-K flip-flops that
  never change at the same edge (MID rises entering tick 2 and falls
  entering H0, TAILX rises entering the tail and falls entering H1).
  TAILX is set straight from the counter's carry: the 74ACT163's carry
  comes 15.2 ns into a 20 ns tick, with no time for an inverter.
- **A bus access holds from tick 3,** because the bus-access decode settles
  32 ns after the CPU clock. The counter's carry is masked while it
  holds, so a bus access needs 6 ticks at least.
- **Back-to-back bus accesses** were the subtle part: a cycle now ends a
  couple of ticks after its transfer, before the handshake with the bus
  side has finished. The next access's request waits until the last
  one's done signal has fallen, and its hold ends when done and request
  are both high.

It's 4 chips smaller than the present one (265 against 269 on the card).
Its length classes with the fast parts are 4, 4, 5 and 6 ticks: the
suite's microcycles take 0.59 s with the control store in SRAM and 0.74 s
(5, 6, 7 and 8 ticks) with it in flash. At chip level, the suite runs as
[results.md](0024-rfc-faster-smaller/results.md#the-fast-system) shows:
2.71 times as fast in total with the SRAM control store and 2.26 times
with flash, every program correct, no timing violations. Programs that
print a lot gain less: they wait for the 921,600-baud UART.

**Variable-length cycles stay worth it with fast parts:** a fixed clock
would take 0.73 s (6 ticks) and 0.97 s (8 ticks) instead of 0.59 and
0.74, for the four chips of the length class (its ROM, register and two
multiplexers).

**Recommended:** this clock generator, or one like it, with the fast
parts.

## 7. Faster: fewer cycles

A cycle model ([cycles.py](../studies/v1b_tradeoffs/cycles.py)): draft
1's timing model, ported, with more knobs. Set up as the 1b hardware is
(32-bit datapath, 16-bit bus, a separate fetch that also writes back,
multiplies of 16 or 32 steps), it comes within 0.1% of the hardware's
cycles over the suite (0.92–1.15 per program). Other configurations,
relative to the hardware:

| Change | Cycles | Chips (*estimate*) | Status |
|---|---:|---:|---|
| overlapped fetch: the next opcode in an instruction's last cycle | 0.91 | 0–2, and new microcode | **recommended** |
| 32-bit memory and a two-parcel prefetch buffer | 0.80 | +10–15 | **recommended** |
| the same, and a register file written in the second half of any cycle | 0.64 | +6–12 more | **open** |
| all that, and multiplies that stop early | 0.61 | +2 | **open** |
| multiply: stop when the rest of the multiplier is zero | 0.97 (mandel 0.74) | +2 | **open** |
| multiply: two bits a step | 0.97 (mandel 0.79) | +8–10 | **not recommended** |
| divide: two bits a step | 0.97 (bignum 0.85) | +10 or more | **not recommended** |
| draft 1a instead of 1b, on the same hardware | 1.04 | about the same | draft 2 builds on 1b: decided (RFC 0005) |

The two-phase register file needs input latches on the ALU, so the
register file can be written while the ALU still works from the values
read, and a way past the case where the next instruction reads the
register being written; the model assumes no stalls, so 0.64 is a bound.
Together with the fast parts and the SRAM control store, the 32-bit
memory and its prefetch buffer would bring the suite's microcycles to
roughly 0.47 s (*estimate*), 3.8 times the system as built.

None of these is pipelining or a cache, which RFC 0007 rejects for now
as the lowest payoff per effort; RFC 0005 ranks speed last of its three
directions too. The parts and the clock generator of sections 5 and 6
give more than all of these together, without touching the
microarchitecture.

## 8. Smaller: packages and PLDs

**16-bit parts.** Any two octal registers (74ABT16823, 16374), buffers
(16244) or transceivers (16245) of one type can share a package: their
halves have separate clocks, enables and directions. Two of the register
file's 32K × 8 SRAMs make one 64K × 16. That saves 53 chips: 44 on the CPU
card, 3 on the backplane, 6 on the memory card, with the netlists' logic
unchanged ([results.md](0024-rfc-faster-smaller/results.md#16-bit-parts)).
Report 0022 already recommends the 74ABT16245 for the bus drivers. The
512K × 8 RAMs stay: no 5 V 16-bit SRAM is that deep. The logic parts come
in TSSOP and SSOP (0.5–0.635 mm pitch), the 64K × 16 SRAM in TSOP-II
(0.8 mm); 74ABT16823 and IS61C6416AL are still listed as active.
**recommended**, if the boards may use these packages. DIP or SOIC is
still open ([RFC 0008](0008-rfc-ideas-memory-and-buses.md#splitting-the-cpu-into-boards)),
and Emily is more open to surface-mount parts, which a PCB assembly
service would put together
([RFC 0007](0007-rfc-ideas-microarchitecture.md#3-parts)).

**GALs.** Much of the system is state machines and decode logic, which
22V10s (ATF22V10C-7, 7.5 ns, still made) absorb at several chips each.
By block, *estimates*, not fitted:

| Where | Now | With GALs |
|---|---:|---:|
| CPU: flags, zero detect, condition latches, branch condition | 27 | 9 |
| CPU: ALU and step control, shift-in, register file addresses, PC carry, faults, glue | 25 | 8 |
| CPU card: bus interface state and decode, clock generator, length class | 33 | 8 |
| Backplane: arbiter, transfer timing, status, SEL, lookup | 45 | 14 |
| Memory and I/O cards: lanes, WAIT, strobes, glue | 18 | 4 |
| **total** | **148** | **43** |

That's about 100 chips, a quarter of the system; call it 70–100 until the
blocks are fitted. GALs are often faster than the 74F multiplexers they'd
replace (7.5 ns against 12). RFC 0014 estimated the backplane alone at 28
chips without GALs and 13 with them. **open**: Emily would rather not
use them, since they make the machine harder to build, are hard to
source and are less fun, but it isn't a definite no
([RFC 0014, open question 4](0014-rfc-system-bus.md#14-open-questions)).
This section is what they would buy.

## 9. Smaller: what the ISA's features cost

What each feature of 1b costs in the 1b CPU, and what dropping it would
cost in cycles:

| Feature | Chips | Without it |
|---|---:|---|
| multiply and divide hardware: MQ, the step multiplexers, the divide's sign logic | ~10 | 45% more cycles (bignum 3.7 times), multiplying in a subroutine |
| rotations by 8 and 16 in the result multiplexer | 8 | shifts by 8 or more one bit a step |
| the second register-file copy (two read ports) | 6 (4 with 16-bit SRAM) | a cycle more for every two-register operation |
| R × 2 on the A bus | 5 | left shifts one bit a step, scaled index slower |
| the flags beyond plain NZCV (sticky Z, eight carry sources, flags from the B bus) | ~6 | `ADC`/`SBC` chains, `RTI` and the shift carries need more microcode |
| precise address-error traps | ~3 | the Lisp's tagged pointers check by software: 16% slower compiled (report 0018) |
| the indexed mode's index register (SX) and dispatch | ~3 | the mode goes |
| 2 × T for jump offsets | 2 | a cycle more per `Jcc` |
| interrupts | ~1 | — |
| `r0` reads as zero | ~1.5 | (RFC 0006, section on `r0`) |

None is worth dropping for its chips. 1a instead of 1b would save a few
of them (the indexed mode, some of the immediate unit) and some
microcode, for 4% more cycles on this hardware, and draft 2 builds on
1b anyway (RFC 0005, decided). **not recommended** as a size lever.

## 10. Smaller: a narrower datapath

RFC 0005 rejects building narrow first (Emily, 2026-10-15): a 32-bit
ISA on a 16-bit datapath is slower than draft 0 on ordinary code. This
section adds what a narrower datapath would save in chips. The
cycle model gives a 16-bit datapath 1.27 times the 1b hardware's cycles
with a 32-bit register file and 1.51 with a 16-bit one; with a 32-bit
memory bus and prefetch 1.07, against 0.80 for a 32-bit datapath with
the same memory. An 8-bit datapath takes 2.5–2.9 times.

In chips, 44 of the CPU core's touch only bits 16–31 of the datapath.
Less the PC and MAR, which stay 32 bits, and plus half the result
multiplexer, a 16-bit datapath would save about 40. But 23 of those are
octal registers, buffers and SRAMs that 16-bit parts halve anyway: after
16-bit parts, a 16-bit datapath saves about 30 chips (15–20% of the
CPU), for 1.3–1.5 times the cycles of a 32-bit datapath with the same
memory, at a microcycle about 15% shorter (its carry chain is shorter).
Most of the CPU (the control store, the sequencer, the PC and MAR, the
flags, the memory interface) doesn't scale with width.
**not recommended**, which agrees with RFC 0005.

## 11. Smaller: the bus

| What | Chips |
|---|---:|
| Backplane | 51 |
| CPU card: bus interface (state 15, address 6, data 6.5, access decode 4, crossings 3.5, interrupts 1) | 36 |
| Memory card, against about 5 chips for the same 2 MB on the CPU card | 31 |
| I/O card's bus glue | about 5 |
| **The bus** | **about 120** |

The clock generator and the length class (14) aren't the bus's:
variable-length cycles need them anyway.

Requirements that drive the bus's chips, from RFC 0014's decisions:

| Requirement | Chips it costs | Without it |
|---|---:|---|
| any slot may be a bus master: the arbiter, REQ/GNT on the cards | 15 + ~3 | DMA and other CPUs couldn't master the bus |
| 16 slots (radial SEL, GNT, REQ, class straps, clock lines) | 7–12 more than 8 slots | 8 slots |
| the bus monitor | 3 | a stuck card hangs the machine |
| card IDs | 4 on these two cards | software probes the slots |
| a backplane at all | about 120 | a single-board machine with I/O on the CPU card (and wait states for its devices) |

A single-master bus with 8 slots, no monitor and no IDs would save about
30–35 chips. Of these, only the slot count isn't something a future card
needs: DMA (Ethernet, disk, video) wants mastering, and LOCK is decided
for a multi-CPU system. **open**: 8 slots instead of 16; mastering
limited to a few slots (RFC 0014's open idea, which estimated about 2
chips for 8 master slots; fewer master slots save a few more).

## 12. Requirements worth another look

| Requirement | Where it comes from | What it costs | Change, and its status |
|---|---|---|---|
| 74HCT logic | the draft 0 and 1b hardware | most of the factor of 2.5–3.4 | 74F and 74ABT: **recommended** |
| 55 ns memories | the 1b hardware | the rest of it | 12 ns RAM: **recommended**; the control store in SRAM: **open** |
| The clock generator's fixed window and hold point | v1b_system | any speed-up beyond 15% | one for short cycles: **recommended** |
| No PLDs | RFC 0014, open question 4 (a preference against) | roughly 70–100 chips | GALs: **open** |
| DIP or SOIC packages | RFC 0008 (open; Emily more open to surface mount, RFC 0007) | 53 chips | 16-bit parts in TSSOP: **recommended** if the packages are allowed |
| Worst-case timing over −40–85 °C | every report so far | 1.2–1.6 times the time, against typical delays | design to typical: **not recommended** (the jumpers let a real board run faster) |
| 16 slots | RFC 0014 | 7–12 chips | 8 slots: **open** |
| Any slot a bus master | RFC 0014 (DMA, LOCK) | about 18 chips | a single master: **not recommended** |
| A backplane of cards | RFC 0005, decided | about 120 chips | a single board: **not recommended** (decided) |
| Hardware multiply and divide | draft 1 | about 10 chips | drop it: **not recommended** |
| 1b's addressing modes | draft 1b | a few chips and microcode | drop them: **not recommended** |
| A 32-bit datapath | RFC 0005 (built narrow first: rejected) | about 30 chips, after 16-bit parts | 16 bits: **not recommended** |

## 13. Design points

Chips for the whole system (backplane, CPU, memory and I/O cards); time
for the program suite's microcycles, and at chip level where it was run.

| Design | Chips | Suite: microcycles | Suite at chip level |
|---|---:|---:|---:|
| As built | 367 | 1.82 s | 2.24 s |
| Fast parts, new clock generator, control store in flash | 363 | 0.74 s (2.5×) | 0.99 s (2.3×) |
| … in SRAM, with its loader | ~378 | 0.59 s (3.1×) | 0.82 s (2.7×) |
| Fast, flash, 16-bit parts | ~310 | 0.74 s | |
| … and GALs | ~210–240 | 0.74 s or less | |
| … and a single-master, 8-slot bus | ~195–230 | | |
| Fast, SRAM control store, 32-bit memory and prefetch | ~390 | ~0.47 s (3.8×) | |

The second and third rows are measured, with the netlist as built apart
from the CPU card's clock generator and parts (the third without the
SRAM loader, which isn't in the netlist); the rest are *estimates* built
from the measurements above. With GALs, the bus's single master and 8
slots save less than section 11's 30–35 chips, since the GALs already
shrink the arbiter and the slot logic. The microcycle column is the 20
programs of the `v1_isa` suite on the RTL model; the chip-level column is
v1b_system's 22, with its memory card and CF card programs.

The build budget is still open (RFC 0005, open question 1: 100, 200 and
400 chips are different projects). These points span about 200 to 390
chips; only GALs bring the whole system near 200.

## 14. What was tried and didn't work

- **The first fast clock generator** closed the write window with a J-K
  flip-flop whose K input needed the counter's carry inverted: the carry
  comes 15.2 ns into the tick, and with the inverter the flip-flop missed
  it. The register file wrote across the next cycle's address change.
- **Holding a bus access from tick 2** sampled the bus-access decode too
  early: it settles 32 ns after the CPU clock, about 41 ns into the
  cycle, and the hold's input changed just after the sampling edge (by
  0.9 ns in the run that caught it, by about 11 ns at worst). Tick 3
  costs about 9% of the suite's time with the SRAM control store (2%
  with flash, whose cycles are longer anyway): a bus-capable
  microinstruction needs 6 ticks instead of 4. Decoding the MAR's slot
  bits when the MAR loads would win it back.
- **The original handshake** with the bus side relies on a long tail
  after every transfer: its done signal stays up for up to 9 ticks after
  the release. With short cycles the next access would have seen it and
  not held at all. This one was found by reading the timing, before it
  could fail in a run.
- **Two tail ticks** would have avoided the window problem, at about 13%
  of the suite's time with the SRAM control store (3% with flash).
- **Upgrading every card's parts** made the I/O card's read data reach
  the CPU card's read latch inside the setup window of one of its early,
  discarded captures; only the CPU card's parts change now.
- **A path the length analysis can't see.** Static timing runs the CPU
  with BUSERR tied to 0. But the first microinstruction of a trap after
  a bus error starts with FAULT still high: it falls about 40 ns in, when
  that microinstruction's own bus-access decode does, and only then can
  the next address settle. With the control store in flash, that cycle
  came 0.6 ns short at chip level (memcard's bus errors). The fault pages
  now take the longest class; they run once per trap. The system as
  built has the same path, hidden by its 13-tick minimum.
- **The simulator's 74x299 model** checked the hold time of the serial
  inputs after every clock edge, even one that didn't shift them in. With
  the 74F299's real hold time (2 ns; the 74HCT and 74ACT parts' data says
  0) that flagged harmless changes as violations. It now checks only the
  inputs the last edge took.

## 15. Open questions

For Emily:

1. **Fast parts:** 74F and 74ABT logic and 12 ns SRAM, with the clock
   generator for them? It's the largest lever by far, for no chips; the
   costs are power, 0–70 °C, and SOJ/TSOP memories.
2. **The control store:** flash (2.3 times at chip level), or SRAM
   loaded at power-up (2.7 times, about 15 chips more, and writable
   microcode)?
3. **Packages:** may the boards use 16-bit parts in TSSOP, surface
   mounted (−53 chips)?
4. **GALs** (−70 to 100 chips, *estimate*)? RFC 0014 records a
   preference against them; this is what they would buy. If yes, the
   next step is to fit the blocks of section 8 for real.
5. **The bus:** 8 slots instead of 16? Mastering in a few slots only?
6. **Cycles:** is the next CPU worth the overlapped fetch and a 32-bit
   memory (about 1.25 times, 10–15 chips), and is a two-phase register
   file worth designing (up to 1.6 times)?
