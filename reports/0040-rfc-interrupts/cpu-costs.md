# RFC 0040: what it costs on draft 2's CPU

What [RFC 0040](../0040-rfc-interrupts.md)'s CPU side and CPU card cost,
from the draft 2 hardware session, which built the RFC in
[studies/v2_hw](../../studies/v2_hw/README.md) on 2026-10-17: in the
microcode, the RTL model and the chip-level netlist. Every program,
`systest` and the interrupt program match the RTL model cycle for cycle at
chip level, with no timing violations. [RFC 0031](../0031-rfc-draft-2-cpu.md)
carries the design; this note keeps the numbers that bear on RFC 0040's
choices.

- **The core's counts** are from the netlist, in package equivalents,
  with gates counted fractionally, against `main`'s single request.
- **The card's counts** are estimates from parts. In the chip-level
  simulator the card's registers are a behavioural fixture, not yet a
  netlist.
- **Times** are from the RTL model, from an entry's first
  microinstruction to the cycle that decodes the handler's first
  instruction, with ns at worst-case lengths.

## The core

| Part | Packages |
|---|---:|
| Eight real levels: a 74148 encoder (1), the level as code + 1 (1), the compare chain, a 74151 and PEND (3.1), the LT register (1), the IPL register and its multiplexer (3.7) | 10.3 |
| `sr`'s IPL read out as RFC 0029 lays it out, bytes 2 and 3 onto B | 1.0 |
| The non-maskable interrupt: gating the vector's offset, the acknowledge, a bit in LT (the latch is on the card) | 1 |
| The message level: MSGT and the M flag (1.4); its sixteen registers of their own (4.4, [below](#the-message-levels-registers)) | 5.8 |
| VBR: nothing new, since the per-level offset's driver onto B (½) is needed anyway | 0 |
| No bus errors | −0.8 |
| **In all** | **+17.75** |

That takes the core from 366 packages to 385. The hardware session then
took 3 back elsewhere (MAR off the A bus, SX's load multiplexer), so the
core is 382.

For the record, estimates of the alternatives in RFC 0040's
[section 9](../0040-rfc-interrupts.md#9-why-eight-levels-stay):

- **Three fixed levels** (the message level 7, the timer 6 and one IRQ
  level), still with IPL and `SPL`: about 2.5 packages fewer than eight.
  The encoder, the incrementer and the compare chain go, and about 2.5
  of gates come back. The card's request register shrinks to one bit.
- **ARM's IRQ and FIQ,** two masks and no IPL: about 4–5 packages for the
  whole interrupt logic, against about 11 for eight levels.

## Time

- **The suite** is unchanged: 752.97 ms, against `main`'s 753.06. The
  timing analysis of every microinstruction finds none longer by a tick.
- **Control store words:** 51 more out of 6,346: `SPL` 27, `MTSR vbr` 18,
  the message entry 9, the privilege check on `SWI` 1, and 4 fewer in
  reset.

| Entry | Cycles | ns |
|---|---:|---:|
| A level | 6 | 640 |
| The non-maskable interrupt | 6 | 640 |
| The message level, with `r1` and `r2` | 9 | 940 |
| `SWI` | 6 | 660 |
| A trap | 7 | 740 |
| Trace | 5 | 560 |
| `RTI` | 5 | 520 |
| `RTI` back into the message level | 5 | 520 |

`main`'s single request took 6 cycles, 640 ns. VBR's OR would have cost a
cycle, but one came back elsewhere: an entry that saves the PC unchanged
now stores it straight from the A bus. That took `SWI` from 7 cycles to 6,
the message entry from 11 to 9 and `RTI` from 6 to 5 (its MAR load folds
into the privilege check).

## VBR

- **An OR,** since VBR is aligned to 2 KB.
- **In microcode, not hardware:** traps use vectors pre-ORed with VBR,
  kept as constants in the register file, and `MTSR vbr` rewrites them
  (18 words).
- **Special register 15** in v2_hw, where `bkpt` isn't built. Reset sets
  it to `0x8000_0000`.

## The `SWI` numbers kept for sources

Not quite free. Each `SWI #n` already has its own entry in the decode
table. For n ≥ 128, the entry's first cycle, which works out the vector,
branches on S to a shared privilege-violation trap: one control store
word, no cycles.

## The message level's registers

RFC 0040 has the message level enter a bank of its own, 255 say. v2_hw
builds something else: sixteen registers of the message level's own, a
separate region of the register file on its unused address line A14.

- **On the read path:** M & S & not UBR is precomputed into a flip-flop
  every cycle, as the read bank is, so it stays off the read path. The
  suite's time is unaffected.
- **What it shares:** the constants and special registers (the G
  locations) are shared, `MTUR` and `MFUR` (UBR and UBW) still reach the
  user's bank, BANK and CTX are untouched, and no user bank is lost.
- **Cost:** 2 × 74F151, a 74ABT74 and about 5 gates, about 4.4 packages.

Bank 255, through the read-bank register, would cost about 2 packages of
OR gates, but has two snags:

- **The G locations:** in M mode, reads of G would read bank 255's copy of
  the microcode's constants. The special registers (ctx, bank, mapa, vbr
  and the trap vectors' copies) live only in bank 0, so `MFSR` of those
  in the message handler would read stale values, unless every `MTSR` of
  a special also writes bank 255, about 4 cycles more each.
- **Processes lose bank 255.**

## The card

| Part | Packages |
|---|---:|
| Decode, for reads and the write strobes: 2 × 74138 | 2 |
| The non-maskable interrupt's latch and acknowledge: ½ × 74 | ½ |
| Board information: a 74x16244 on jumpers | 1 |
| The request register, with RFC 0040's set and clear masks: a register, 16 gates for (q \| set & d) & ~(clr & d), a read buffer | 4–5 |
| … or as a 74x259 addressable latch, one level per write, the level and set or clear in the data | 1½ |
| The message register: two 16-bit halves with their own write strobes (2), the claim and full state (½–1), read-back buffers (2) | 4–6 |
| The timer counting BCLK / 4: 4 × 74HC590 on one counter clock, each stage enabled by the lower stages' RCOs (a couple of 74F32 gates), a ÷4 prescaler and the two tick flags in 74ABT74s | about 6 |
| … or counting BCLK: 8 × 74F161, 2 × 74ABT16374 as the snapshot and the bus driver, and the flags | about 11 |
| The levels ORed | ¾ |
| Zero fill for the small registers' upper half | 1 |
| **In all** | **about 17** (the 259, BCLK / 4) **to 27** (masks, BCLK) |

- **The message register's low half** goes straight into the register
  from a 16-bit master: no holding register is needed, since nothing
  reads it until the high half sets FULL.
- **Its read-back buffers** are 0 if nothing but the CPU reads its
  contents: the CPU reads the message over its internal B bus, as a
  microinstruction source that releases the register at the end of that
  cycle, not as a memory-mapped load.
- **The board information's layout** (a proposal): the region in bits
  3–0, log2 of the RAM in MB in 7–4, BCLK's period in ns in 15–8.

### The timer: a snapshot

The first estimate, about 5 chips, had four 74HC590s count BCLK. TI's
data sheet for the SN74HC590A (SCLS039F) rules that out:

- **Its clock:** at most 16 MHz at 4.5 V over −40 to 85 °C (the SN54, 13
  MHz; 20 MHz at 25 °C). A 60 ns BCLK is 16.7 MHz.
- **Its cascade:** CCLK↑ to RCO takes up to 38 ns, and CCKEN's setup is
  25 ns, so even two stages, RCO into CCKEN, need about 63 ns. Beyond
  two, the data sheet has each stage's RCO clock the next, which ripples,
  about 38 ns a stage. A snapshot taken mid-ripple would hold a torn
  value.
- **Its register:** the data sheet allows RCLK tied to CCLK, the register
  then one count behind the counter.

So there are two timers, both read through a snapshot:

- **Counting BCLK / 4,** 240 ns, about 6 chips: four 74HC590s on one
  counter clock at 4.2 MHz, each stage's CCKEN the OR of the lower
  stages' RCOs, so that every stage changes on one edge with no ripple.
  RCLK is tied to the counter clock, so the register always holds a
  settled count, one behind, and is held while a 16-bit master reads its
  two halves. A ÷4 prescaler and the two tick flags in 74ABT74s.
- **Counting BCLK,** 60 ns, about 11 chips: eight synchronous 74F161s
  (their ENT chain settles in about 57 ns, which is tight), two
  74ABT16374s as the snapshot and the bus driver, and the flags.

- **Held from the low half's read,** the snapshot gives a 16-bit master
  one value in two halves. The CPU's 32-bit read is one access anyway.
- **Reading twice** saves the snapshot's register but not the counters,
  needs bus buffers instead, and software.
- **The tick** taps the register's outputs. They follow the count one
  behind, except while a 16-bit master's read holds them, which delays a
  tick's edge by at most that long.
- **v2_hw** still counts BCLK in its model and fixture; changing the rate
  is a line. RFC 0031 marks the rate open.

### The local path

The CPU decodes PA[31:28] = 0111 with a 74F688 the core has anyway. The
registers sit on the card's data bus, so a register access is an ordinary
load or store cycle. Over the bus instead, a read would take 11–13 ticks
more (about 240 ns) and a write 14–16 more (about 300 ns).

### The non-maskable interrupt

Built as RFC 0040 recommends: the card's latch, control register bit 3,
cleared by the entry (the acknowledge at the clock edge); the entry
clears I and T, leaves IPL alone, and goes to VBR + 4. Setting IPL to 8
instead would cost about 1 package (LT's level forced to 8) and no
cycles.

## What it means for RFC 0040

- **Eight levels** cost about 11 packages of the core's 382, about 2.5
  more than three fixed levels and about 6 more than ARM's two masks.
  Eight levels are Emily's decision; the cost is now known.
- **The whole RFC** costs about 18 packages on the core and 17–27 on the
  card, and no time in the suite.
- **The message entry** takes under a microsecond, so the latency
  table's "perhaps 5–10 µs" was pessimistic: what remains is the
  instruction in progress and any exception being entered.
- **For Emily:** the message level's registers (sixteen of their own, or
  bank 255), the request register (masks, or a 259 with one level per
  write), the timer's rate (BCLK, or BCLK / 4 for about 5 chips fewer),
  and the board information's layout.
