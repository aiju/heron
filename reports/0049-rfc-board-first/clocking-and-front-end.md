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

## 4. The branch adder as built, the microcode, and the machine running

Done after the above, 2026-11-04.

**The branch adder** (`ctrl.branch_adder`, five 5 ns 22V10s, in front of
PC's drivers onto A): PC + 2 × the register byte while PCOP is BRANCH,
else PC. Its low byte has its carries looked ahead (bits 1–4's carry
out, bits 5–8's generate and propagate, straight from the inputs), the
upper bits count up or down from those: about six GAL levels, against
thirteen as a ripple. With it:

- **FLUSH** (a backplane line, and CTRL's own copy): PC and FPC load from
  A and the queue empties, on PCOP LOAD (a jump), or on TK (a new field)
  and TAKEN, the executing instruction's condition (row B its opcode's
  cc, row F d's; 14 and 15 always). MEM's FPC loads on it.
- **BRDEC** jumps on FLUSH: a branch's tail word goes to WAITD if the
  branch's word loaded PC, else to the next instruction.
- A branch's word fits **5 ticks**; nothing else changed length. A word
  that may load PC doesn't fetch.

**The microassembler** (`ucode.py`, `heron reed ucode`): words by field,
their successors and lengths, placed in the control store; the decode
table from draft 2's encodings; the images of every control-store part.
136 words: MOV, MOVS, ADD, SUB, CMP, AND, OR and XOR on registers, the
small immediates, sext16, zext16 and imm32, and words at `[r]`,
`[r + d16]` and `[abs16]`; their stores; row 7's MOV and CMP; LSL and LSR
by one; Bcc, BRA and BSR; JMP r and RET; Jcc, JMP and CALL with a 16-bit
displacement; HALT. Anything else decodes to UNIMPL.

**At chip level** (`hw.py`, `heron reed hw smoke`, and a unit test): the
whole machine's netlist on the chip-level simulator from power-up, the
images in its parts, a 20-instruction program (register and immediate
operations, a store and a load, a compare and a branch, BSR and RET,
shifts) in the RAM. Its registers and memory match draft 2's simulator.
Loops, measured there:

| An iteration | Cycles | ns |
|---|---:|---:|
| SUB, BNE taken | 5 | 556 |
| ADD, XOR, SUB, BNE taken | 8 | 914 |
| a load, ADD, SUB, BNE taken | 9 | 1013 |

**What the microcode and the run found:**

- **A taken branch is four microcycles** (about 440 ns), a not-taken one
  two: the sequencer chooses a word's successor while the word before it
  executes, so the branch needs its tail word to see its own outcome. A
  not-taken branch in one would need the fall-through's first word
  squashed (a line every board obeys); a taken one in three, the fetched
  word bypassed into the decode table.
- **A word that may fetch is 6 ticks:** the fetch path (FPC, the RAM, B,
  the queue) needs them, and whether a word fetches is decided in it. So
  the register operations that fetch are 6 ticks, not 5. FETCH decided a
  cycle ahead and registered would take them back to 5.
- **The write phase was too tight** with WPH half a tick late: the
  chip-level run showed the register file's write data 4.2 ns short of
  its setup to the strobe's end, which the static analysis couldn't see
  (the strobe waits for its address, a correlation it doesn't follow).
  The register file's strobe (WRS) is now half a tick later too, and
  MEM's (WRSE, a fifth clock from the card, one line) stays where it was,
  as a store's data comes over A, which the next cycle's word may drive.
  The run is then clean but for the VIDEO board, not timed yet; the
  static analysis instead finds the register file's late strobe ending
  too near the next cycle's switch back (−5 to −9 ns). The way out is
  the address and Y's data released by the strobe itself, which needs
  pins on full GALs on the full ALU board.

`heron reed estimate`, on the napkin's mix, with what was built:

| Cycles | today | adder, as built | adder (1 / 3 microcycles) | + bypass |
|---|---:|---:|---:|---:|
| as microcoded (fetching words 6 ticks) | 346 | 329 | 293 | 276 |
| with FETCH registered (5 ticks) | 316 | 303 | 271 | 254 |

So the adder as built buys 5%; FETCH registered a cycle ahead, and the
squash for a not-taken branch, are worth more than the adder was alone.

## 5. A timing bug the static analysis missed, and the checking since

**What happened.** With WPH half a tick late, the chip-level run found
the register file's write data 4.2 ns short of its setup to the strobe's
end. The static analysis reported no strobe check on the register file at
all. Two causes:

- **In the design:** the clock card delayed WPH half a tick through an
  inverter and two GAL stages (about 14 ns), against about 4 ns for WRS,
  so the write phase started with the strobe, not half a tick before it.
- **In the analysis:** the strobe is gated by its address, and the
  address changes in a window overlapping both of WRS's edges. The engine
  folded the whole pulse into one transition ("high, high, may glitch")
  and then ran none of the strobe's checks. It did report "the strobe may
  pulse", at a slack of 0.0, and I took that for an artefact. A glitch on
  a strobe is a failure.

**What changed in the design.** The ALU's write phase (WPA, a sixth clock)
and its strobe (WRS) both come straight from U_CGB's registers on the
inverted clock, WPH and WRSE half a tick later each, so their order is the
clock's edges'. WPA falls half a tick into the next cycle: the address and
the data stay a tick after the strobe ends. MEM keeps WRSE, where U_CGA
makes it: its data comes over A, which the next cycle's word may drive.

**What changed in the checking.**

- `heron reed sta` lists every glitch first, as something to fix.
- `heron reed hw check` (and a unit test): four programs on the whole
  machine at chip level, at the parts' maximum delays and at their minima
  (else 30% of typical), each with the wires on the drivers' pins (12 ns
  and 1 ns over the backplane), and three power-up seeds, against draft
  2's simulator. All 24 runs are right and have no timing violation on
  CTRL, ALU, MEM or the clock card.
- Two engine gaps to RFC 0048's session: a strobe folded into "may
  glitch" gets no checks; and a register that first loads after the
  window's start (U_CGB's) can't be given its state, so the analysis
  can't judge the new write phase yet (its strobe shows as "may pulse").

**Found along the way:** B's handovers between boards (CTRL's immediates
and MEM's crossbar) overlap up to 17.8 ns at the maximum corner. The
napkin's slots were the discipline for this; the netlist has none.

**The engine's fixes, and what they show.** RFC 0048's session closed
both gaps: a strobe whose pulse merges into one change is now checked
across the whole of it, and a register's `start` and `before` hold until
its first load, wherever that is (U_CGB's, half a tick in). With them the
analysis judges the new write phase, and finds two things the chip-level
runs didn't:

- **The register file's address isn't a tick ahead of its strobe:** 5.4
  ns short of tAS, on every word that writes, at every length. The
  address comes from WPA through U_RFT (LEW) and U_RAG, two GALs behind
  the inverter, U_CGB and the tree: 31.4 ns at the maximum after its
  edge, against the strobe's 7.1 ns at the minimum a tick later. Nothing
  shares a path but the inverter, and two edges' paths get no credit for
  it (RFC 0048 9.1).
- **The read starts half a tick in, honestly:** the copies' addresses
  are W until WPA falls and LEW follows, so the read starts there and not
  at the edge at 0. Four words take a tick more: r into MAR, the jump
  and the store 6, a load and add 7. Register ops stay at 5.

U_RFW gates the strobe on its address being W, so the strobe can't start
before the address reaches U_RFW. That's why the chip-level runs pass,
at a margin of about U_RFW's minimum delay less the wires' skew. The
engine can't see it: with the register numbers unknown, W and the
addresses are X, so the strobe may start anywhere in WRS's window. That
is the "may pulse" still flagged: X values the engine can't correlate,
not a pulse, but it stays on the list until a case shows it gone.

**Two attempts, neither kept:**

- **The latches' enable from the card** (RDA, the inverse of WPA, a U_CGB
  register: the 573s' LE and the address muxes' select, with no U_RFT).
  The address is then one GAL behind the tree, and the strobe's tAS
  would pass by about 2 ns. But the latches then close on the same edge
  that switches their inputs a GAL later. The hold check credits the
  shared path and passes, by 0.7 ns. The latch's own closing, though,
  is propagated without the credit, so its output may change through the
  write phase, and every check after it fails at every length (by 17 to
  56 ns). U_BYP on the address match alone, instead of the phase, needs
  the engine to know that the address is W, which it can't with X
  values.
- **Cases with the register numbers known** (d and s 1, the last word's
  d 14, or 1 for the bypass, or no write), as 14.6 asked: the strobe is
  then a clean pulse, and a new set of failures shows up (the latches'
  setups in the bypass and no-write cases, 32 ns, against an edge I
  don't yet understand). Not triaged; the patch is kept aside.

The chip-level gate passes on the merged engine: all 24 runs.

**The second round** (the engine's cc0a9a6): a latch closing on an
unknown value now keeps it, and the latch-enable glitch is Atmel's rule
on U_RFT's two inputs. With both attempts together (the latches' enable
from the card, known register numbers), the register file's strobe
checks and its glitch are gone and register ops, r into MAR, the jump
and the store are at 5 again; what's left is the handover on the copies'
data pins (the copy and Y switch on the same terms: up to 28 ns of
overlap under the strict model) and the holds around the strobe. Kept
aside with the rest (`rda+regs`).

## 6. The write phase at 6 or 7 ticks

Worked on paper (2026-11-04), before any netlist: phases on whole ticks
from U_CGA only (no inverter, no U_CGB), every pin at most one GAL from
the tree, nothing gated by logic, every check at +1 ns or more under the
strict analysis. A phase reaches the ALU's pins 5.1-11.4 ns after its
edge (U_CGA, the tree, the slot's wire), a GAL adds 1-6, so two events
a tick apart have about 7-8 ns between them at worst, and a tick serves
every handover.

In a cycle of n ticks, the copies' pins, counted from its end (the
write's data has to stay past the strobe, and Y loads the next result
at n):

| Tick | |
|---|---|
| 0 | the address back to the read; Y lets go |
| 1 | the copy drives again; the latches open (Y has taken the result) |
| 0 to n-4 | the read |
| n-4 | the latches close; the copy lets go |
| n-3 | the address to W; Y drives (WPH) |
| n-2 to n-1 | the strobe (as MEM's WRSE) |
| n | Y loads the next result |

So the read has two ticks at 6 and three at 7. At 6 two paths miss: the
register numbers (U_RB and the microinstruction at 0, U_RAG, the SRAM)
reach the latches 0.6 ns before they close, and the copy turning on at
1 through U_BYP misses by 1.3 ns. Loading the register numbers earlier
doesn't help (the port's select is the microinstruction's), and a
half-tick phase moves the shortfall to the next handover. At 7 both
have about a tick to spare.

On RFC 0050's suite (the estimate, `heron reed estimate`'s recipes on
each workload's mix): 7 everywhere costs 13-17% against 6; 7 only where
a write is pending (the card stretching the cycle on ALU's WEN, a
backplane line) 8-13%; a dual-ported register file is 17-20% faster
than as built. The phases collapse to MCLK, CYC, WPH, RDA (the latches'
enable and the copies' window) and WRS (one strobe for ALU and MEM):
nine of U_CGA's ten outputs.

Still open in that plan: U_BYP's choice (the copy or Y) settles from
the register numbers about 35 ns in, after RDA's earliest rise at 1, so
the copy and Y may overlap there unless the choice comes earlier.

**Decision (Emily, 2026-11-04):** the cycle not stretched on WEN. The
netlist stays as it is while the design is completed; this comes back
after. (Corrected 2026-11-05: I had this as "7 ticks for now" as well,
everywhere, which Emily didn't decide. Where the other documents quote
times "at 7 ticks", that is every microcycle at 7, a pessimistic bound,
not a decided length.)

## What I'd do

1. The card, with the CDC341s on the backplane (1), and the fast clock
   kept on it (2): VIDEO and IO their own oscillators.
2. The branch adder and the bypass on CTRL (3): the largest single gain,
   and it fits.
3. Settle the store's RAM checks at 5 with RFC 0048's session.
4. Then, if the ALU board can make room, a dual-ported register file.
