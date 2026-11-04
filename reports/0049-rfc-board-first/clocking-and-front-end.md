# Reed: the clock card, the fast clock, the front end

Findings behind [RFC 0049](../0049-rfc-board-first.md)'s section 14.6,
2026-11-04: what a clock card does for Reed's timing, where the 50 MHz
clock has to go, and what the branch path, two transfers per cycle and
the register file's write phase are worth. The timing is `heron reed
sta`'s, with the napkin's wires (1–12 ns over the backplane); the times
an instruction are `heron reed estimate`'s, a rough count on the napkin's
mix, not a measurement.

## 1. The clock card

The oscillator, the clock generator and the clock trees on a card of
their own (`studies/reed/clockcard.py`), in a slot of its own:

| | Packages |
|---|---:|
| oscillator | 1 |
| U_CGA, the clock generator (22V10, 5 ns) | 1 |
| U_CGB, WPH half a tick late (22V10, 5 ns, on the inverted clock), and its 74F04 | 2 |
| a CDC341 for each of MCLK, CYC, WPH, WRS (an output a slot) | 4 |

Three things make the difference, each measured:

- **The generator on the oscillator itself.** On CTRL it ran on its
  slot's MCLK: a tree stage, a trace and CTRL's connector before it, and
  the phases out through the connector again. That spread counts in
  full in the read's race at 5 ticks (the data off CYC at one edge, the
  latches closing off WPH at another). On the oscillator, the register
  op's miss at 5 ticks went from −9.6 ns to −3.7, and every check a
  length can fix passed at 6, the write strobe's address check too.
  Clocked from its own tree output, as a slot's MCLK, it was no better
  than on CTRL.
- **LEN a cycle early.** From CTRL's microinstruction register, over the
  backplane, LEN came 4.5 ns too late for the generator at 6 and 7
  ticks. It's now a direct field of CTRL's control store (the next
  word's, as the sequencer's fields are), and the generator takes it as
  a cycle starts.
- **WPH half a tick late.** With the master clock on the card, the card
  can place an edge on either of its edges. U_CGB delays WPH's rise by
  half a tick and leaves its fall at the cycle's end: the write phase is
  two and a half ticks, and the read half a tick longer.

| Microcycle | CTRL's generator | the card |
|---|---:|---:|
| `ADD r, r`, `ADD r, #q`, shift right | 6 | **5** |
| r into MAR, jump, a branch's target | 6 | **5** |
| r + d16 into MAR, loads, fetch | 6 | 6 |
| load and add | 7 | 6 |
| store | 6 | 5 (its RAM checks to settle, below) |

- **Pins:** the four sources CTRL fed the trees from go; LEN takes two
  lines. Twelve spare.
- **CTRL** gives up U_CGA.
- **Open:** at 5 ticks the store's RAM shows a −40.6 ns hold of its data
  against the write strobe, where the data comes before the strobe
  begins (an SRAM takes the data at the strobe's end), and a float as
  the lanes come on just after the strobe does. Likely the engine's
  reading of a strobe check; to take to RFC 0048's session.

**Card, active backplane, or between.** In the timing they're the same
chips and the same delays: what differs is what can be changed.

- **An active backplane** (all of it on the backplane): nothing to plug
  in, but the generator's equations (the cycle lengths, where the phases
  fall) are then in the backplane.
- **The card** (as built): replaceable, its connector its own. The
  backplane routes four clocks from the card's slot to each other slot:
  twenty traces, the card's own pinout.
- **Between:** the card has the oscillator and the GALs, the backplane
  the four CDC341s beside the card's slot. The card then needs four
  clock pins and its inputs (LEN, the WAIT lines, reset), and can sit in
  an ordinary slot with the ordinary pinout; the backplane's CDC341s
  never need to change.

The last is what I'd do: what may change is on the card, the backplane
is fan-out and traces.

## 2. Where the fast clock has to go

After the 823s replaced the gated clocks, CTRL, ALU and MEM take no
50 MHz clock at all: their clocks are CYC, WPH and WRS, each changing
twice a cycle (about 8–10 MHz) on a tick's edge. MCLK goes to:

- the clock card (the generator);
- IO: its WAIT counter (an access's ticks), ALE's latch strobe, and the
  PS/2 receivers' shifters;
- VIDEO: all its timing (the pixel clock is half of it).

So the fast clock can stay on the card:

- **VIDEO with its own oscillator,** 25.175 MHz, VGA's own. Its side
  toward the CPU is already a handshake (posted writes, WAIT_V); its
  WAIT_V and its accesses would cross with synchronisers.
- **IO with its own clock,** for the PS/2 shifters (any clock fast
  enough to sample them) and for counting an access's wait. WAIT_IO then
  crosses into the card with a synchroniser, which it should have
  anyway (the card samples it).
- **The backplane then carries no 50 MHz line:** its clocks change on a
  tick's edges but twice a cycle, which is far kinder to the backplane
  and to crosstalk. And MCLK's own pin comes free.

The cost is that no board can time anything to the tick for itself:
every edge a board needs is a phase line from the card, made there at
whatever resolution the card's own clock gives (both edges of 50 MHz
today, 10 ns; a faster oscillator on the card alone would give finer).
A board wanting a new edge costs a backplane line, of which there are
now twelve spare.

This is the opposite of making the phases on each board, which needed
each board to sample CTRL's phases on the master clock a tick after they
changed, and doesn't fit a tick with the wires. Centralised on the card,
nothing samples a phase: the phases are the clocks.

## 3. The branch path, two transfers a cycle, the write phase

`heron reed estimate` (ns an instruction, the napkin's mix; shifts a bit
a microcycle, as the crossbar's rotation isn't built):

| Cycles | today | two transfers a cycle | branch adder | adder + bypass |
|---|---:|---:|---:|---:|
| the netlist before the card: 6 ticks | 350 | 331 | 297 | 280 |
| the clock card: 5 and 6 | 316 | 300 | 271 | **254** |
| the card, and a register file with no write phase (estimate) | 279 | 266 | 243 | 226 |

- **The branch path (the biggest).** About 17% of instructions redirect
  the fetch (taken conditional branches, BRA, JMP, calls, returns). Today
  a taken `Bcc` is five microcycles: the target computed in the ALU,
  the test, the target sent out on A, the fetch, the decode. A branch
  adder on CTRL computes the target at the decode and tests the
  condition in hardware (a TAKEN line to MEM's FPC), so a branch is one
  word, and a taken one adds the fetch and the decode; bypassing the
  fetched word into the decode table merges those into one longer cycle
  (estimated F + 1 ticks). With the card: 316 → 254 ns, 20%. CTRL has
  12 area units free now (58 of 70): an adder of a few GALs, its target
  register, and two 541s from B into PD fit. The fetch-and-decode cycle
  wants timing before it's believed.
- **Two transfers a cycle (the napkin's slots).** Their use in the
  netlist is the taken branch's third word (PC in on A, the target out
  on A): 5% without the adder, nothing with it, as the adder sends the
  target itself. They'd cost a latch on the ALU's A input (four 573s on
  the full ALU board) and a SLOT phase. Not worth it with the adder.
- **The register file's write phase.** The card made it two and a half
  ticks, and the register op 5. Shorter takes more: its three events
  (to W, the strobe, back) are each the card's edges apart. The big step
  would be a register file with a write port of its own (dual-ported
  SRAMs, IDT7016-class, 16K × 9, PLCC-68; availability and price to
  check): no write phase, no read latches, a register op about 4 ticks
  (226 ns with the adder; an estimate, not timed). On the ALU board,
  eight PLCCs for four SOJs and eight latches is about five area units
  more, which it hasn't got: something would have to leave it (the
  flags or MQ's side, or the shift path to MEM's crossbar).
- **And the shifts:** bit by bit, about 1.4 ticks an instruction in the
  estimate. MEM's crossbar doing rotations by bytes (the napkin's plan,
  not built) would save about one tick an instruction.

## What I'd do

1. The card, with the CDC341s on the backplane (1), and the fast clock
   kept on it (2): VIDEO and IO their own oscillators.
2. The branch adder and the bypass on CTRL (3): the largest single gain,
   and it fits.
3. Settle the store's RAM checks at 5 with RFC 0048's session.
4. Then, if the ALU board can make room, a dual-ported register file.
