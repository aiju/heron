---
number: 49
type: rfc
title: "The next Heron, board first: sketches on double Eurocards"
status: draft
date: 2026-11-02
context:
  studies: [cards, reed, v2_isa, c_compiler]
  commit: c9a6678
depends-on: [22, 26, 28, 48]
---

# RFC 0049: The next Heron, board first: sketches on double Eurocards

Sketches for the next Heron (its name **open**), built as boards on a
backplane from the start. Chibi Heron ([RFC 0047](0047-rfc-chibi-heron.md))
put draft 2 on one board and became a board of 52 GALs whose cut into
smaller boards was an afterthought; Heron Mini ([RFC 0041](0041-rfc-heron-mini.md),
[report 0044](0044-report-mini-cpu-boards.md)) was cut into boards after
its netlist was done, and its crossings cost it 5 to 17%. Here the boards
and the buses between them come first, and the CPU is drawn to fit them.

Emily's brief:

- boards of double Eurocard size, about 70 chips each: small enough to
  design, debug and respin, as many boards as it takes;
- the cost of building them counts: hard routing, tight timing and paths
  between boards each have a price;
- GALs for decode, such as a µop decode, and not much else;
- two 32-bit buses, **A** and **B**, for everything between boards; two
  DIN 41612 connectors leave 64 lines for control, each with a single
  driver where it can be;
- variable-length microcycles stay, perhaps with two bus transfers a
  cycle;
- one board for the ALU and the register file, so that most ALU
  operations stay on it;
- no performance target, but not slow; instruction timings, not the
  suite;
- the ISA as a core, peripheral instructions of real use (multiply), and
  extras that are optional (`MULFX` and the like).

This is a napkin, not a netlist: three designs, each a set of boards
whose chips are parts lists, block by block, and each timed on the key
instructions by summing worst-case delays along each microcycle's longest
path. The study is [studies/cards](../studies/cards/README.md); its
tables, every board's parts and every microcycle's path, are in
[napkin.md](0049-rfc-board-first/napkin.md).

## Summary

**Decided** (Emily, 2026-11-02): design A, under the codename **Reed**;
no part with a pitch finer than 1 mm (SOIC's 1.27 mm is fine); IO and
VIDEO on boards of their own, so that the video has room to grow; the
control store in 45 ns parts; and design for test by the backplane
([14](#14-reed-design-a-at-chip-level)). Reed has a first chip-level
netlist, [studies/reed](../studies/reed/README.md): what it found is
in section 14, and the napkin's sections below are as they were.

- **Reed's first netlist:** five boards (CTRL 67 packages, ALU 71, MEM 65,
  IO 30, VIDEO 49: 282, 47 of them 22V10s, and the backplane's clock
  tree), each within a double
  Eurocard, joined on the backplane by name. It passes the netlist's
  checks, and every control line has one driver. The static timing
  engine (RFC 0048) finds that a microcycle that reads and writes the
  register file needs **5 ticks** without wire delays, not the
  napkin's 4 (Emily: 5 is fine), and with the napkin's 1–12 ns over
  the backplane **5** too, once the clocks come from a clock card (the
  generator on the oscillator itself, the write phase two and a half
  ticks): loads and fetches 6
  ([clocking-and-front-end.md](0049-rfc-board-first/clocking-and-front-end.md)).
  Y's handover to the register file's copies, the store's RAM checks
  at 5 and a few small holds still fail. The backplane has twelve spare
  lines. On the napkin's mix, about 316 ns an instruction, and about 254
  with a branch adder (an estimate, `heron reed estimate`). At 5 ticks the 55 ns flash costs nothing. A taken branch
  takes about five microcycles. The SST39SF010A's 45 ns grade was
  end-of-lifed in 2013 ([14](#14-reed-design-a-at-chip-level)).

The napkin's summary:

- **A backplane transfer is about two ticks.** Register to register
  between boards is 31 ns at worst (ABT parts, 10 ns for the backplane,
  2.5 ns of skew between boards). A 4-tick microcycle (79 ns) carries two
  transfers on each bus, one a slot: four in all. That is the unit the
  designs are drawn in ([2](#2-the-backplane)).
- **The microprogram address crosses, the microinstruction doesn't.**
  CTRL broadcasts the µPC on 14 control lines; every board holds its own
  slice of the control store, 3–4 flashes and as many registers. With
  55 ns flashes that loop sets a floor of **5 ticks**. Most microcycles
  need only 4, so 45 ns parts or a control store in SRAM, loaded at
  boot, is worth about 18% for about 15 chips ([3](#3-control-across-boards)).
- **Three designs** ([6](#6-design-a-spine)–[8](#8-design-c-twin-slices)):

  | | Boards | Board designs | Packages | Tax | 22V10s | Weighted, ns |
  |---|---:|---:|---:|---:|---:|---:|
  | **A, Spine:** CTRL, ALU, MEM, IO + VIDEO | 4 | 4 | 248 | 47 | 30 | 190 |
  | **B, Address board:** an operand stage with its own register file copy | 5 | 5 | 267 | 59 | 35 | 180 |
  | **C, Twin slices:** two identical 16-bit boards, each with half the RAM | 4 | 3 | 256 | 41 | 36 | 213 |

  *Tax* is the chips a board needs only because it is a board: its
  control slice, receivers, clock buffer and bus drivers. *Weighted* is
  the time an instruction takes, weighted by the compiled C programs'
  instruction mix, at the 4-tick floor, with multiply and divide on the
  ALU board. It's a weighting, not a benchmark.
- **Instruction timings,** in ticks of 19.86 ns, at the 4-tick floor
  (A / B / C): a register `ADD` 4 / 4 / 5; `MOV r1, [r2 + 8]` 9 / 5 / 9;
  `ADD r1, [r2 + 8]` 10 / 6 / 11; a store 9 / 4 / 9; a branch not taken
  5, taken 9; `RET` 11 / 9 / 10; `LSR #8` 6 / 6 / 5
  ([9](#9-instruction-timings)).
- **That is about Heron Mini's speed** by a rough measure (Mini about
  275 ns an instruction on these programs) in two thirds of its chips,
  and three to four times Chibi's. A napkin is optimistic by construction,
  so read it as "not slow", not as a number.
- **Multiply and divide are a third of the time** on the ALU board's MQ,
  though they're 2% of the instructions. An optional **ARITH board**
  (58 chips: 8 × 8 product tables in SRAM) takes `MULU` from 140 ticks to
  44, and 12% off the weighted time. Divide is left open
  ([10](#10-boards-every-design-shares)).
- **The board tax is 16–22% of the chips** (41–59). It's the price of
  boards that can be respun alone ([12](#12-what-being-boards-costs)).
- **My lean: A,** with the control store in SRAM. B buys about 5% for a
  fifth board and a register file kept coherent over the backplane. C
  gives up about 12% so that the CPU is one board design built twice
  ([13](#13-what-i-would-do-and-open-questions)).

## Contents

1. [The brief, as rules](#1-the-brief-as-rules)
2. [The backplane](#2-the-backplane)
3. [Control across boards](#3-control-across-boards)
4. [The napkin's rules](#4-the-napkins-rules)
5. [The instruction set by tiers](#5-the-instruction-set-by-tiers)
6. [Design A: Spine](#6-design-a-spine)
7. [Design B: Address board](#7-design-b-address-board)
8. [Design C: Twin slices](#8-design-c-twin-slices)
9. [Instruction timings](#9-instruction-timings)
10. [Boards every design shares](#10-boards-every-design-shares)
11. [Variants and other ideas](#11-variants-and-other-ideas)
12. [What being boards costs](#12-what-being-boards-costs)
13. [What I would do, and open questions](#13-what-i-would-do-and-open-questions)
14. [Reed: design A at chip level](#14-reed-design-a-at-chip-level)

## 1. The brief, as rules

The rules the sketches keep, Emily's and the ones that follow from them:

- **B1 Boards.** Double Eurocard, 233.35 × 160 mm. After the guided
  edges, the front strip and the connectors that leaves about 31,000 mm²,
  or about **70 area units**, where a unit is a DIP-20's slot soldered by
  hand (report 0044's tight packing). A DIP-24 0.6" (the 74F181, the
  82C54) takes 1.7 units, a socketed PLCC-32 or an SOJ 1.2, a DIP-40 2.4
  ([napkin.md](0049-rfc-board-first/napkin.md#area-units)). Every board
  here is within 70 units.
- **B2 The backplane.** Two DIN 41612 connectors of 96 pins: A (32), B
  (32), 64 control lines, 64 grounds and supplies.
- **B3 One driver a control line.** Every control line here has exactly
  one board that drives it; no exceptions turned out to be needed.
- **B4 A slot is a register-to-register transfer.** A value crosses the
  backplane from a register, or from logic fed by registers clocked at
  the cycle's start, into a register at the slot's end. A microcycle may
  chain two crossings (out and back) only if it's long enough.
- **B5 Control stays local.** Only the µPC, the instruction's register
  numbers, the clocks and a few conditions cross. Every board decodes its
  own microinstruction bits.
- **B6 Registers, counters, multiplexers and bus drivers are 74 parts;
  22V10s decode.** The exceptions are state machines (the clock
  generator, the instruction queue's control) and the flags register,
  where a 74-part version would take several chips for one GAL.
- **B7 The ALU and the register file share a board** (designs A and B;
  C breaks this rule on purpose).

## 2. The backplane

### 2.1 The pins

| | Pins | |
|---|---:|---|
| A | 32 | addresses and results |
| B | 32 | data, constants, instructions |
| control | 64 | one driver each ([2.4](#24-the-control-lines)) |
| ground and supply | 64 | one for every two signals; guard grounds beside the clocks (report 0022, section 2) |

### 2.2 What a transfer costs

Worst case, from a register on one board to a register on another:

| | ns |
|---|---:|
| 74ABT574 clock to Q | 7.1 |
| its own bus driver (74ABT245) | 3.9 |
| the backplane: connector, flight, settling, 6–8 slots loaded | 10.0 |
| the receiver | 3.9 |
| the wire on the receiving board | 2.0 |
| setup | 1.5 |
| skew between boards | 2.5 |
| **total** | **30.9** |

Report 0022 measured 4.8–6.3 ns for the backplane itself with 8 slots
at 20.32 mm. Ten nanoseconds leaves room for heavier cards, for the
reflections a short backplane still has, and for being wrong. So a
transfer is 1.6 ticks, and a slot is **two ticks** (39.7 ns).

### 2.3 The cycle

- **The tick** is 19.86 ns: a 50.35 MHz master clock, twice VGA's pixel
  clock, as in Chibi and Mini.
- **A microcycle** is 4 ticks or more, its length a field of CTRL's slice
  of the microinstruction. The clock generator is CTRL's (two 22V10s).
- **The write tick:** a board with a register file writes the last
  cycle's result in the first tick, then reads. So a register file's data
  is valid 41.4 ns into the cycle.
- **Two slots:** S1 from the cycle's start, S2 from tick 2 to the end.
  Each bus can carry a transfer in each slot. A transfer that starts late
  in the cycle (an address the ALU has just computed) takes S2.
- **The clocks on the backplane:** MCLK (the tick), CYC (the cycle's
  start), SLOT (S2's start) and WT (the write tick), all from CTRL, each
  between grounds, each buffered on every board by a CDC341 (report
  0022's skew of 2.0–2.6 ns assumes clock parts of that class).

### 2.4 The control lines

Design A's, with their drivers; B's and C's differ as their sections say.

| Lines | Driver | |
|---:|---|---|
| 4 | CTRL | clocks: MCLK, CYC, SLOT, WT |
| 14 | CTRL | µPC: 16K microinstructions |
| 12 | CTRL | register numbers d, s, x of the instruction executing |
| 3 | CTRL | the memory operation (for MEM, IO, VIDEO): read, write, size |
| 2 | CTRL | SQUASH (this microinstruction does nothing: a mispredicted decode), RESET |
| 5 | ALU | flags N, Z, C, V, and ST, the microcode's test bit |
| 1 | MEM | address error |
| 3 | IO + VIDEO | WAIT, IRQ, the frame's interrupt |
| 1 | ARITH | present |
| **45** | | **19 spare** |

### 2.5 Two transfers a cycle

The slots are what make a board split affordable. A 4-tick cycle can,
for instance, take a constant from CTRL over B in S1, add it in the ALU
board, and send the sum to MEM's MAR over A in S2. A 6-tick cycle can
send a register to MEM's crossbar over B in S1 and bring it back
rotated over B in S2 ([6](#6-design-a-spine)). In general a crossing
costs a slot, not a cycle.

## 3. Control across boards

**The µPC is broadcast and the control store is sliced.** A horizontal
microinstruction is 120–140 bits across these boards: it won't fit 64
lines, and a µop bus decoded on every board would put a GAL's delay in
every control signal. So CTRL drives the µPC (14 lines), and every board
holds its own slice of the store: 3–4 SST39SF010A flashes, the same
number of 74ABT574s holding the microinstruction, and two 74ABT541s
receiving the µPC. With its clock buffer that's 9–11 chips a board. The
store is pipelined: CTRL's next-address logic works from its own flash
slice's outputs, on its own board, while every board executes the word
before.

**The flash floor.** µPC (7.1 ns) over the backplane (15.9 ns with its
receiver), the flash (55), into the register (1.5) with skew (2.5) is
82 ns: **5 ticks.** CTRL's own loop doesn't cross the backplane, so it
fits 4. Most microcycles need only 4 ([9](#9-instruction-timings)), so
the floor costs about 18% (A: 11.3 ticks an instruction at 5 against 9.6
at 4). Ways down to 4:

- **45 ns flashes.** RFC 0047's pipelining note expected the
  SST39SF010A in a 45 ns grade; whether it can still be bought is to
  check. A 45 ns OTP EPROM (the AT27C010-45) would do, but isn't
  reprogrammable.
- **A control store in SRAM**, loaded at boot. Each 32 bits of a slice
  becomes two IS61C6416 (the register file's part), its four registers,
  and four 74ABT541s that write it from B: two chips more a board. A
  loader on CTRL (a counter for the µPC, a word assembled from the boot
  flash) is about 11 more. In all about 15 chips, and new microcode is a
  file on the CF card or a transfer over the serial line, not 15 flashes
  to program. **My lean.**
- **A sequencer on every board,** each computing the next address from
  its own copy of the next-address fields: about 7 chips a board. No.

**Branches in a pipelined store.** The decode of an instruction happens
in its predecessor's last microcycle (the entry is the opcode × 16 + d,
as RFC 0047 proposes). The flags are a pipeline stage: Z and N are
computed from the result register in the next cycle's write tick, so an
`ADD` doesn't carry its zero detection (two GAL levels). The flags reach
CTRL 49 ns into the next cycle, early enough for a `Bcc` right after a
`CMP` to choose its successor in its own cycle. A taken branch decodes
its target from a word fetched speculatively in the same cycle, and the
fall-through word decoded meanwhile is squashed (SQUASH): 9 ticks taken,
5 not. Not fetching speculatively would make it 13 and 4, which is worse
at 45% taken.

## 4. The napkin's rules

- **Chips are parts lists.** Every block of every board names its parts
  ([napkin.md](0049-rfc-board-first/napkin.md#the-parts-block-by-block)).
  For example, the ALU board's "result" isn't "a few chips": it is
  `Y_A` and `Y_B`, 8 × 74ABT574, because each copy of the register file
  is written from its own register so that no buffer sits between them.
- **Delays** are worst-case datasheet figures (infra's timing table
  where it has the part) with generous wires: 2 ns on a board's heavy
  nets, 10 ns for the backplane, 2.5 ns of skew between boards. A
  microcycle's ticks are its longest path plus 2 ns, rounded up, and at
  least the floor.
- **An instruction's ticks** are the sum of its microcycles. Its decode
  overlaps the instruction before.
- **Left out:** fetch stalls (one RAM access a cycle, fetches in idle
  cycles; Mini found the second word of its queue worth 10%),
  interrupts, wait states of devices, the clock generator's granularity.
  So the napkin is optimistic.

## 5. The instruction set by tiers

My reading of RFC 0028 by Emily's three tiers, with what each gets:

| Tier | Instructions | What they get |
|---|---|---|
| **core** | `MOV`, `MOVS`, `ADD`, `SUB`, `CMP`, `AND`, `OR`, `XOR` in every mode; stores; `LEA`; `CLR`, `INC`, `DEC`; the 7-bit forms; `Bcc`, `Jcc`, `BSR`, `CALL`, `JMP`, `RET`; `PUSH` and `POP` (modes 6, 7); `ADC`, `SBC`, `BIC`, `TST`; `NOT`, `NEG`; `ZXB`, `ZXH`, `SXB`, `SXH`; shifts; `SETcc`; the system group | the fast paths: the slot plan is drawn for these |
| **peripheral** | `MULU`, `MULS`, `DIVU`, `DIVS`, `DIVUL`; `SAVE`, `RESTORE`, `LDM`, `STM`; `SWAP`, `RLC`, `RRC`, `CLZ`, `DBNZ`; the indexed and special modes | hardware that's cheap (the MQ, MAR's counter, the crossbar) or an optional board (ARITH) |
| **optional** | `MULFX`, `MULA`, `ADD.B4`, `FFS`, `POPC`, `REV`, `MERGE`, the tagged operations, `CAS`, the FPU escape | microcode only, built on what the others have |

**What decomposes.** Most of the map is an operand fetch followed by an
operation, and the microcode can be written that way, with one GAL
choosing the ALU function from the opcode (the µop decode of the brief):

- **Operand × operation:** rows 1, 3–6 and 8–A are 8 operations by 16
  modes. That's 16 operand routines ending in "do the row's operation",
  plus a GAL that gives the 181's function, the carry in and which flags
  to set from the row (MOV none, MOVS NZ, ADD NZCV, CMP NZCV and no
  write).
- **Address × action:** stores (row 2), `LEA`, `CLR`, `INC` and `DEC`
  of memory, `JMP` and `CALL` with an operand: the address routines end
  in a write, a register load, a read-modify-write or a jump.
- **Branch family:** `Bcc` (s8), `Jcc` (s16, abs32), `BSR` and `CALL`
  (cc F), `DBNZ` (a decrement, then `BNE`): one target adder, one
  condition decode.
- **Byte family:** byte and half loads and stores, `ZXB`, `ZXH`, `SWAP`,
  `REV`, rotations and logical shifts by 8, 16 and 24. All of them are
  the byte crossbar ([6](#6-design-a-spine)) choosing a source lane, or
  zero, for each lane.
- **Shift family:** a shift by n is n mod 8 bit steps and at most one
  crossbar pass. In the compiled programs' traces 44% of shifts are by
  8 and 25% by 1.
- **Multiply family:** `MULU`, `MULS` (sign fix-ups), `MULA` (an
  accumulate), `MULFX` (a shift of the product).
- **Block family:** `SAVE`, `RESTORE`, `LDM` and `STM` are loops of
  stores or loads with MAR counting.
- **Trivially similar pairs:** `CMP` is `SUB` without the write; `TST`
  is `AND` without it; `BIC` is the 181's A AND NOT B; `INC` and `DEC`
  of a register are `ADD` and `SUB` of 1; `MOV #u7` and `CMP #u7` are
  mode 1 with a wider constant; `RET` is `JMP r7`; `PUSH` and `POP` are
  modes 7 and 6 at sp.

**What matters:** in the compiled C programs (each program weighted
equally), conditional branches are 19% of instructions, register and
constant operations about 45%, memory operands about 22%. Multiply and
divide are 2% of instructions, but a third of the time on an MQ.

## 6. Design A: Spine

<!-- blocks
bus a "A (32)" from 0,0 to 64,0
bus b "B (32)" from 0,5 to 64,5
box ctrl "CTRL" "sequencer, queue" "PC, branch adder" at 6,10 width=13 height=7
box alu "ALU" "RF × 2, 8 × 181" "Y, MQ, flags" right of ctrl gap 2 align=top width=13 height=7
box mem "MEM" "4 MB, crossbar" "MAR, FPC" right of alu gap 2 align=top width=13 height=7
box io "IO + VIDEO" "devices" "frame buffer" right of mem gap 2 align=top width=13 height=7
bus c "control (64)" from 0,23 to 64,23
ctrl.top-3 - a
ctrl.top+3 - b
alu.top-3 - a
alu.top+3 - b
mem.top-3 - a
mem.top+3 - b
io.top-3 - a
io.top+3 - b
ctrl - c
alu - c
mem - c
io - c
-->
![Design A: four boards on A, B and the control lines](0049-rfc-board-first/spine.svg)

The obvious cut, done carefully: control, the ALU, memory, and the
devices.

| Board | Packages | Area | Tax | What's on it |
|---|---:|---:|---:|---|
| **CTRL** | 56 | 56 | 0 | clock generator, µPC and next address, its own flash slice, the instruction queue (two words, eight parcel bytes on a parcel bus), the immediate unit, PC, a branch adder (PC + 2 × disp, 6 × 74F283) with its target register, condition and interrupt decode |
| **ALU** | 60 | 68 | 23 | register file (two copies of 64K × 32 in four IS61C6416, one per read port), 8 × 74F181 with a GAL's lookahead, `Y_A` and `Y_B`, transceivers to A and B, the one-bit shift path, flags, MQ, F onto A |
| **MEM** | 67 | 67 | 19 | 4 MB in eight AS7C4096A, the byte crossbar (16 × 74F153), store lanes, MAR (its low 4 bits a counter, for `SAVE` and friends), FPC |
| **IO + VIDEO** | 65 | 70 | 5 | two UARTs, timer, boot flash, CF card, PS/2, sound, interrupts; 2 MB of frame buffer with its own scan counter and palette, and posted writes |

**The ALU board** is full, 68 of 70 units, 14 of them its 181s. The two copies of the register file sit on the ALU's two inputs.
Each copy's I/O net is that input, so a 74ABT245 connects it to its bus
both ways: an operand comes in from A or B, or a register goes out.
`Y_A` and `Y_B` write their copies in the write tick. A right shift is
four 541s from copy A's net, wired one bit over, onto copy B's: a step
of `LSR` or of a divide is a pass through the ALU. A left shift is
`A + A`.

**The byte crossbar** is MEM's: 16 × 74F153, each byte lane choosing any
of the four lanes or zero, by a GAL that decodes the access's size,
address and operation. Loads go through it; stores replicate their low
byte or half into the lanes. The ALU board uses it too: a register over
B in S1, back through the crossbar over B in S2, makes `LSR #8`,
`ROR #16`, `SWAP`, `REV` and `ZXB` single 6-tick cycles.

**Slots:**

| | S1 | S2 |
|---|---|---|
| A | CTRL: a fetch address or a branch target to MEM; PC to the ALU | ALU: an address into MAR, an operand to ARITH |
| B | CTRL: constants and displacements to the ALU | MEM: load data to the ALU, fetched words to CTRL, crossbar results; ALU: store data to MEM |

**Walk-throughs** (ticks at the 4-tick floor; every path in
[napkin.md](0049-rfc-board-first/napkin.md#cycle-by-cycle)):

- `ADD r1, r2`, **4:** write tick, both copies read (41.4 ns), add
  (29.5), into `Y_A` and `Y_B` (73.4 ns). Z and N come from Y in the
  next write tick.
- `ADD r1, [r2 + 8]`, **5 + 5:** r2 from copy A and d16 from CTRL over
  B/S1 into the ALU, the sum straight onto A/S2 into MAR (94.7 ns). Then
  MAR into the RAM, the crossbar, over B to the ALU, add (83.9 ns).
- `MOV [sp + 8], r1`, **5 + 4:** the address as above, then r1 from copy
  B over B into the store lanes (76.2 ns).
- `POP r1`, **4 + 4:** sp goes onto A from copy A's net while the ALU
  adds 4 to it; then the load.
- `BNE` taken, **5 + 4:** the target was added on CTRL during the
  decode. In the `BNE`'s cycle it goes onto A to the RAM, its word comes
  back over B and is decoded (88.4 ns). The cycle after is the target's
  first microinstruction coming out of the flashes.
- `RET`, **7 + 4:** r7 from copy A onto A, straight to the RAM's
  address, the word back over B, decoded (119.8 ns).

**What's tight:** the address cycle (94.7 ns in 5 ticks: 4.6 ns to
spare) crosses the backplane once after an add. Everything else keeps 6
ns or more.

## 7. Design B: Address board

<!-- blocks
bus a "A (32)" from 0,0 to 66,0
bus b "B (32)" from 0,5 to 66,5
box ctrl "CTRL + IO" "sequencer, queue" "devices" at 5,10 width=11 height=7
box addr "ADDR" "RF copy, AGU" "MAR, FPC, PC" right of ctrl gap 1.5 align=top width=11 height=7
box ex "EX" "RF × 2, ALU" "MQ, flags" right of addr gap 1.5 align=top width=11 height=7
box mem "MEM" "4 MB" "crossbar" right of ex gap 1.5 align=top width=11 height=7
box vid "VIDEO" "frame buffer" right of mem gap 1.5 align=top width=11 height=7
bus c "control (64)" from 0,23 to 66,23
ctrl.top-2 - a
ctrl.top+2 - b
addr.top-2 - a
addr.top+2 - b
ex.top-2 - a
ex.top+2 - b
mem.top-2 - a
mem.top+2 - b
vid.top-2 - a
vid.top+2 - b
ctrl - c
addr - c
ex - c
mem - c
vid - c
-->
![Design B: five boards, the operand stage on ADDR](0049-rfc-board-first/address.svg)

The addressing × operation decomposition, in hardware. **ADDR** has a
third copy of the register file, an address adder (eight more 181s), PC,
FPC and MAR. During the last microcycle of an instruction, ADDR computes
the next instruction's operand address from the mode (GALs decode it
from the opcode: the operand stage is hardwired for the simple modes,
microcoded for the indexed and special ones). The instruction's own
cycle then begins with the address already in MAR.

| Board | Packages | Area | Tax | |
|---|---:|---:|---:|---|
| **CTRL + IO** | 62 | 68 | 4 | sequencer, queue, immediates, and the devices (there's no PC or branch adder here) |
| **ADDR** | 57 | 63 | 19 | register file copy, AGU, remote-write register, PC, FPC, MAR, mode decode, hazard compare |
| **EX** | 56 | 64 | 19 | design A's ALU board without its address path |
| **MEM** | 51 | 52 | 16 | RAM, crossbar, store lanes |
| **VIDEO** | 41 | 41 | 1 | as A's, alone |

- **Coherence:** EX broadcasts every result it writes over A/S2, and
  ADDR's remote-write register writes it into ADDR's copy at the next
  write tick. ADDR never writes back: it updates its own copy for a post
  increment or a push, so the next address can use it at once, and EX
  makes the same update architecturally in a cycle its ALU is idle (a
  store's) or one more (a pop's).
- **Hazards:** a base register written by the instruction just before
  reaches ADDR two cycles late, one written the instruction before that
  one cycle late. ADDR's GAL compares the register numbers and holds the
  decode. In the compiled programs' traces 10% of memory operands take
  their base from the instruction before and 5% from the one before that
  (some of these are post increments, which don't stall, so this is an
  upper bound).
- **What it buys:** a load 5 ticks (A: 9), an `ADD` from memory 6 (10),
  a store 4 (9), `RET` 9 (11), since r7 is in ADDR's copy. Weighted: 180
  ns against A's 190, **about 5%**. Branches and multiplies, where B
  doesn't help, are most of the time.
- **What it costs:** a fifth board, 19 chips, a register file kept
  coherent over the backplane, and hazard logic whose bugs would be
  timing-dependent. The control lines are 58 of 64: the next
  instruction's register numbers and mode go out at its decode, and each
  board latches what it needs.

## 8. Design C: Twin slices

<!-- blocks
bus a "A (32)" from 0,0 to 64,0
bus b "B (32)" from 0,5 to 64,5
box ctrl "CTRL" "sequencer, queue" "PC, FPC" at 6,10 width=13 height=7
box lo "SLICE" "bits 15–0" "lanes 0–1, 2 MB" right of ctrl gap 2 align=top width=13 height=7
box hi "SLICE" "bits 31–16" "lanes 2–3, 2 MB" right of lo gap 2 align=top width=13 height=7
box io "IO + VIDEO" "devices" "frame buffer" right of hi gap 2 align=top width=13 height=7
bus c "control (64)" from 0,23 to 64,23
lo.bottom+3 <-> hi.bottom-3 "C16, Z, shift"
ctrl.top-3 - a
ctrl.top+3 - b
lo.top-3 - a
lo.top+3 - b
hi.top-3 - a
hi.top+3 - b
io.top-3 - a
io.top+3 - b
ctrl - c
lo.bottom-3 - c
hi.bottom+3 - c
io - c
-->
![Design C: the CPU's datapath as two copies of one board, each with half of everything](0049-rfc-board-first/slices.svg)

One board design built twice: each **SLICE** is 16 bits of everything,
including the register file, the ALU (4 × 181), result, MAR, MQ, half of
the crossbar, and two of the RAM's four byte lanes (2 MB). A strap on
the board says which half it is. Both carry the same microcode, and the
strap changes what their GALs do with the carry, the shifts and the byte
lanes.

| Board | Packages | Area | Tax | |
|---|---:|---:|---:|---|
| **CTRL** | 65 | 65 | 0 | A's CTRL with FPC (fetches go out on A to both slices) |
| **SLICE × 2** | 63 | 68 | 18 | per slice |
| **IO + VIDEO** | 65 | 70 | 5 | as A's |

- **What crosses:** the carry C16 and the low half's Z on control lines,
  a bit for right shifts the other way, and the address. Each slice
  drives its half of MAR onto A, and both RAMs take the whole address
  from A. Word data never leaves its slice. Bytes that change halves go
  over B, as do immediates (each slice takes its half) and fetched words
  to CTRL.
- **What it costs:** the carry crossing puts 47 ns into a 32-bit add
  instead of 29.5, so an add-type operation is 5 ticks at the 4-tick
  floor (and costs nothing at the 5-tick one). The control slice, its
  receivers and clock buffer are built twice (11 chips more than one
  ALU board). It breaks B7 on purpose.
- **What it buys:** three board designs for the machine, not four. A
  slice respun fixes both, a spare slice fits either place, and a byte
  rotation crosses the backplane once, not twice (`LSR #8` in 5).
  Weighted: 213 ns, **12% slower than A** at the 4-tick floor, the same
  at 5.

## 9. Instruction timings

Ticks, at the 4-tick floor / the 5-tick floor of 55 ns flashes. These
come from [napkin.md](0049-rfc-board-first/napkin.md#instruction-timings),
which `heron cards napkin --write` generates:

| Instruction | A | B | C |
|---|---:|---:|---:|
| `ADD r1, r2` | 4 / 5 | 4 / 5 | 5 / 5 |
| `AND r1, r2` | 4 / 5 | 4 / 5 | 4 / 5 |
| `CMP r1, #5` | 4 / 5 | 4 / 5 | 5 / 5 |
| `MOV r1, #0x12345678` | 4 / 5 | 4 / 5 | 4 / 5 |
| `LEA r1, [r2 + 100]` | 4 / 5 | 4 / 5 | 5 / 5 |
| `MOV r1, [r2 + 8]` | 9 / 10 | 5 / 5 | 9 / 10 |
| `MOV r1, [r2]` | 8 / 10 | 5 / 5 | 8 / 10 |
| `ADD r1, [r2 + 8]` | 10 / 10 | 6 / 6 | 11 / 11 |
| `MOV [r2 + 8], r1` | 9 / 10 | 4 / 5 | 9 / 10 |
| `MOV [abs16], r1` | 8 / 10 | 4 / 5 | 8 / 10 |
| `PUSH r1` | 9 / 10 | 4 / 5 | 9 / 10 |
| `POP r1` | 8 / 10 | 9 / 10 | 9 / 10 |
| `MOVS r1, byte [r2]+` | 8 / 10 | 9 / 10 | 9 / 10 |
| `MOV r1, [r2 + r3*4 + 8]` | 21 / 25 | 22 / 25 | 24 / 25 |
| `INC [r2]` | 13 / 15 | 10 / 11 | 14 / 16 |
| `Bcc`, not taken | 5 / 5 | 5 / 5 | 5 / 5 |
| `Bcc`, taken | 9 / 10 | 9 / 10 | 9 / 10 |
| `BSR`, `CALL label` | 9 / 10 | 9 / 10 | 9 / 10 |
| `RET` | 11 / 12 | 9 / 10 | 10 / 11 |
| `JMP [table + r2*4]` | 25 / 30 | 27 / 30 | 27 / 30 |
| `LSL r1, #1` | 4 / 5 | 4 / 5 | 5 / 5 |
| `LSR r1, #8` | 6 / 6 | 6 / 6 | 5 / 5 |
| `ROR r1, #13` | 18 / 21 | 18 / 21 | 20 / 20 |
| `MULU r0:r1, r2`, MQ | 140 / 175 | 140 / 175 | 175 / 175 |
| `MULU r0:r1, r2`, ARITH | 44 / 55 | 44 / 55 | 44 / 55 |
| `DIVU r0:r1, r2` | 148 / 185 | 148 / 185 | 185 / 185 |
| `SAVE r8-r14` | 33 / 40 | 28 / 35 | 33 / 40 |
| `RESTORE r8-r14` | 36 / 45 | 39 / 40 | 38 / 45 |
| `SETcc r1` | 5 / 5 | 5 / 5 | 5 / 5 |

**Weighted** by the compiled C programs' dynamic mix: conditional
branches 45% taken; shifts by the counts in the traces; `SAVE` and
`RESTORE` of four registers; B's hazards as measured. In ticks, then ns,
an instruction:

| | A | B | C |
|---|---:|---:|---:|
| floor 4, MQ | 9.57 (190 ns) | 9.05 (180 ns) | 10.74 (213 ns) |
| floor 4, ARITH board | 8.39 (167 ns) | 7.88 (156 ns) | 9.13 (181 ns) |
| floor 5, MQ | 11.33 (225 ns) | 10.68 (212 ns) | 11.33 (225 ns) |
| floor 5, ARITH board | 9.85 (196 ns) | 9.21 (183 ns) | 9.86 (196 ns) |

Where A's time goes, at the 4-tick floor with the MQ: multiply and
divide 31%, memory operands 25%, branches and calls 23%, register and
constant operations 18%, shifts 4%. For a rough anchor, Heron Mini runs
these programs at about 275 ns an instruction (RFC 0041's 13.9 MHz of
the reference timing, on their mean CPI of 3.8). Chibi takes 3.6 times
Mini's time on the suite (RFC 0047: 3.8 times the full Heron's, Mini
1.05). Neither figure is measured the way the napkin is.

## 10. Boards every design shares

**IO + VIDEO** (65 packages, 70 units, A and C; split in B):

- **The devices:** two TL16C550Cs with MAX232s, an 82C54, the boot flash,
  a CF card with its buffers, two PS/2 ports, sound (a 574, a DAC0832, an
  op-amp), three GALs (interrupts, I/O decode, the slow devices' timing),
  and a data bus and latched address of their own from B and A.
- **The video** has its own 2 MB frame buffer, so it never steals a cycle
  from the CPU. The CPU's writes are posted: an address latch on A, a
  data latch on B, written in the video's next free slot. Reads wait on
  WAIT. Scan counters, a palette in three fast SRAMs, an ADV7125 triple
  DAC (the IMS G171 is long gone; the ADV7125 is in production, but it's
  LQFP).

**ARITH,** optional, any design (58 packages, 65 units):

- **8 × 8 products from tables:** four IS61C6416, each 64K × 16 holding
  every product of two bytes, written at boot (the microcode computes
  them in about 10 ms through eight 541s). X's bytes in turn
  address all four tables, each also addressed by one of Y's bytes:
  four byte products a step.
- **One 40-bit adder** (8 × 181 and 2 × 74F283) adds a step's products
  into a row, then the row into the accumulator, while the product's
  low bytes retire into a byte-wide shift register: 2 cycles a step,
  4 steps.
- **`MULU` 44 ticks** (0.9 µs) against 140 on the ALU board's MQ, and
  `MULS`, `MULA` and `MULFX` on the same steps. Weighted, 12% off the
  time.
- **Divide stays on the MQ** (148 ticks, 12% of the weighted time by
  itself, mostly from arith, bignum, bst and matmul). Two ideas, neither built:
  the C compiler divides by a constant with a multiply when ARITH is
  there, and radix 4 on ARITH's adder and the ALU's together.
- **Not a barrel shifter:** a shift through the multiplier takes 44
  ticks; the crossbar and bit steps do better for every count.

The machine runs without ARITH: the microcode tests its present line
and falls back to the MQ.

## 11. Variants and other ideas

- **A stack in the register file's SRAMs** (A). The four IS61C6416 hold
  64K words each, and the registers use 32 of them. With the effective
  address driven onto their address pins (4 × 541), the rest is a 256 KB
  memory on the ALU board itself, read in the same place as a register.
  If the stack lives there, `[sp + n]` doesn't cross the backplane: a
  load or `ADD` from the stack is 4 + 4 ticks instead of 9 or 10.
  Pointers to locals still work: the ALU board decodes the range itself
  and MEM ignores it. The cost is 4 chips the ALU board doesn't have
  room for, and a stack that video and DMA can't see.
- **Code RAM on CTRL** (Harvard inside, von Neumann outside). 1 MB of
  RAM next to the instruction queue: fetches never cross the backplane
  or take MEM's RAM cycle, and `RET` drops to 9. Data accesses to that
  range go to CTRL over the buses, slowly. Code a program writes at run
  time, as the Lisp and Egret compilers do, would be fetched slowly from
  MEM unless it's put in the code range. About 6 chips, less MEM's FPC.
- **ADDR and EX as one board design** (B). Both are a register file,
  181s and bus transceivers. Populated differently, they could be one
  PCB, which takes away one of B's five board designs.
- **A table ALU.** If 74F181s run out, an IS61C6416 addressed by A, B (4
  bits each), the function (5) and the carry gives a 4-bit slice's F, G,
  P and carry out in 12 ns, one chip per 181. It's loaded at boot, like
  the product tables.
- **Considered and left:**
  - broadcasting a µop bus rather than the µPC, which puts a GAL in
    every control path;
  - a transport-triggered machine, with every unit a source and sink on
    A and B, which crosses the backplane for every operand;
  - two microengines, one for addresses and one for operations, each
    sequencing itself with handshakes, which needs two sequencers and the
    same coherence as B, for B's gain;
  - Chibi's two halves over a backplane, which halves the ALU board but
    doubles the time of every 32-bit operation.

## 12. What being boards costs

- **The tax:** 41 (C), 47 (A) and 59 (B) chips, 16–22%: per board a
  control slice of 6–8 chips, two µPC receivers, a clock buffer, and the
  bus transceivers and receivers (some of which also serve as an
  operand's multiplexer).
- **16-bit buffers** (74ABT16245 and 16541 in SSOP-48) would halve the
  transceivers and receivers: about 25 packages in A, and the ALU board
  would have room for the stack variant. Report 0022 prefers them for
  ground bounce too. Their 0.635 mm pitch is the price, if the boards
  are soldered by hand.
- **Timing margins:** with 10 ns for the backplane, the tightest cycles
  have 3.3–4.6 ns to spare, the 2 ns every cycle keeps included
  ([napkin.md](0049-rfc-board-first/napkin.md#cycle-by-cycle): A's
  address cycle, B's load, C's load). None of them depends on a minimum
  delay.
- **Routing:** the ALU board is the dense one. It has four 32-bit nets
  (two copies' I/O, F, Y) each reaching three or four groups of chips,
  and two 32-bit buses at its edge. MEM's crossbar is 16 chips with 32
  inputs each from the same 32 nets. Both want the chips of a byte lane
  in a column.
- **What's likely to be respun:** IO + VIDEO (devices change), then
  CTRL (the sequencer's glue). The ALU and MEM boards are regular and
  unlikely to change, which is one reason to keep the devices on their
  own board.
- **Bring-up:** CTRL, MEM and IO first. ODT in microcode needs the
  sequencer, the UART and memory, and the ALU for little else.

## 13. What I would do, and open questions

**My lean:** design A, with the control store in SRAM loaded at boot
(the 4-tick floor), the byte crossbar on MEM, IO and the video on one
board, and the ARITH board designed after the rest works. B's 5% doesn't
pay for its fifth board and its coherence. C is the one to take if one
board design built twice matters more than 12%.

For Emily:

1. **The design:** A, B, C, or a mix (A with the stack in the register
   file; C's slices with B's address board).
2. **The control store:** flash (a 5-tick floor), SRAM loaded at boot
   (4 ticks, about 15 chips), or 45 ns parts if they can still be bought.
3. **DIP or 16-bit buffers in SSOP:** about 25 packages either way.
4. **ARITH:** in the first set of boards or later, and what to do about
   divide.
5. **The backplane:** how many slots, their pitch, termination. Before
   any board is laid out, report 0022's engine should run the µPC lines
   and A and B as these boards load them.
6. **74F181s:** enough for the boards (8 in A and C, 16 in B, 8 more on
   ARITH), or the table ALU.
7. **Memory:** 4 MB on MEM, and 2 MB of frame buffer on VIDEO.
8. **The name.**

**Next,** once a design is picked: a register-transfer model of it with
its microcode, checked against draft 2's instruction-level simulator,
to replace these napkin timings with counted ones; then the ALU board's
netlist and static timing, the board everything else waits on.

## 14. Reed: design A at chip level

Emily's decisions of 2026-11-02 (design A, the codename Reed, nothing
finer than 1.27 mm, IO and VIDEO apart, 45 ns parts for the control
store, design for test by the backplane) and a first netlist of all of
Reed: [studies/reed](../studies/reed/README.md). Each board is a netlist
of its own in infra's language, its backplane nets named as
[`bus.py`](../studies/reed/bus.py) has them, and `heron reed check` joins
them and checks the whole: the netlist's own checks (every input
connected, no net driven twice) and the backplane's (each control line
driven by its own board alone). `heron reed boards` counts them,
`heron reed sta` times them. There is no microcode yet, and no
chip-level simulation.

### 14.1 What's built

| Board | Packages | Area | 22V10s | What's on it |
|---|---:|---:|---:|---|
| **CTRL** | 67 | 59 | 14 | the clock generator (U_CGA: the sources of CYC, WPH and WRS); the sequencer (µPC, next address, condition); its slice of the control store (5 parts, 2 × 574); the decode table (2 parts: entry and length); the queue (two words, each parcel held twice, onto PD for the decode and PE for the extension parcels); the two-stage instruction register; the immediates; PC; the interrupt's synchroniser |
| **ALU** | 71 | 69 | 15 | its slice (4 parts, the µPC and 4 × 574); the register file (its own U_RB, two copies, read latches, Y_A and Y_B, the write address in U_WG, the bypass in U_BYP, the write strobes in U_RFW; those and the address muxes in the 22V10's 5 ns grade); 8 × 74F181 with a GAL's lookahead; the transceivers to A and B; the shift path; F onto A; the flags |
| **MEM** | 65 | 52 | 5 | its slice (1 part, the µPC and 1 × 574); 4 MB; the byte crossbar (16 × 74F153); the store lanes; MAR (823s), FPC; MQ |
| **IO** | 30 | 29 | 7 | two UARTs, the timer, the boot flash, the CF card, two PS/2 ports (a 299 each, received in hardware), the interrupt controller, sound, reset |
| **VIDEO** | 49 | 40 | 6 | a 2 MB frame buffer, 640 × 480 × 8 through a palette in SRAM and an ADV7125, posted writes and latched reads |
| **total** | **282** | | **47** | |
| *backplane* | 4 | | | the clock tree: a CDC341 for each of MCLK, CYC, WPH, WRS |

Area is in the napkin's units (a DIP-20's slot, 70 to a board), with SOIC
at three quarters of one. Where building it changed the napkin:

- **A store's data goes out on A**, the address having gone into MAR the
  cycle before: the register file's port B lost d (its address GALs ran
  out of pins), and MEM loses its B receivers. Loads still come back on
  B.
- **MQ moved to MEM:** CTRL was full.
- **No branch adder:** CTRL was full (and the library has no 74x283).
- **Decoding a cycle ahead** needs the decoded instruction and the
  executing one at once: a two-stage instruction register (U_NOP, U_NRB,
  then U_OP, U_RB), and the queue's parcels held twice (onto PD at the
  decode pointer, onto PE at the executing instruction's). Its control
  is five GALs.
- **A decode table** (two parts) gives each instruction's first
  microinstruction and its length, rather than opcode × 16 + d.
- **The register file** reads into 573 latches, then switches to the
  write address for the write phase. Where a port reads the register
  about to be written, Y bypasses the copy: one GAL (U_BYP) compares both
  ports' addresses with W and drives the copies', Y's and the latches'
  enables. The address muxes and U_BYP are ATF22V10C-5s (PLCC-28, the
  only package of the 5 ns grade): with a 74F521 per port and the 7 ns
  grade, the bypass missed a 5-tick cycle by 13.6 ns.
- **One write strobe for every board:** WRS, from the clock generator.
- **SEQ BRDEC:** a branch's last word goes to JT if the condition holds,
  else decodes.

### 14.2 The 45 ns part

The datasheet notes in `infra/hw/datasheets` record that the
SST39SF010A's 45 ns grade was end-of-lifed in 2013: today's grades are
55 and 70 ns. RFC 0047's pipelining note assumed the 45 ns grade. The
netlist stands in the AT27C010-45, a 45 ns OTP EPROM in PLCC-32, its
figures estimated and its availability to check. As 14.3 shows, the
register file, not the control store, sets the shortest cycle for now:
with the SST39SF010A-55 in every slice and the decode table, every
microcycle still fits 5 ticks, so the 55 ns flash (reprogrammable)
costs nothing at the moment.

### 14.3 What the timing analysis finds

`heron reed sta` times each kind of microcycle (`sta.WORDS`): every
board's fields pinned to the word, the clock generator running its
equations on the master clock, the cycle from the edge it starts at to
the one the next starts at. Minimum delays are 30% of typical where a
datasheet gives none (RFC 0048's default, its value open), which makes
every two paths from one edge race. The wires are the napkin's (2.2):
1–12 ns from board to board over the backplane (0 at the least where
the receiving board drives the net too), 0–1 ns on a board. The clocks
come through a tree on the backplane (`bus.tree`: a CDC341 for each of
MCLK, CYC, WPH and WRS, a trace from it to each slot, 1–2.5 ns), which
CTRL feeds from four source pins (0–2 ns). One net that every board
takes, timed as the other backplane lines, left the engine unable to
time anything. No load derating: the parts' data has no pin
capacitances yet.

| Microcycle | Ticks | Without the wires |
|---|---:|---:|
| `ADD r, r`, `ADD r, #q`, shift right | 6 | 5 |
| r + d16 into MAR, r into MAR | 6 | 5 |
| load, load byte | 6 | 5 |
| load and add | 7 | 6 |
| store | 6 | 5 |
| fetch, jump, a branch's target | 6 | 5 |

What sets the lengths:

- **A register op needs 6 ticks with the wires.** A cycle reads the
  copies, then writes them in a write phase of three ticks (the write
  address, the strobe, the read address back). It needed 7 while the
  register numbers came over the backplane from CTRL's U_RB; the ALU
  board now has a U_RB of its own, loaded from the decoded instruction's
  numbers (U_NRB's, NRD and NRS on the backplane a cycle early, with
  DEC1_n). In 5 ticks the read misses by 9.6 ns: the board's CYC comes
  27 ns after the master clock's edge (the master clock's tree, the clock
  generator, CYC's tree, the board's CDC341), then U_RB, the address
  mux, the bypass's enable, while the latches can close at 48.8 ns. The
  parts' grades and WPH's route don't give that much back; the read
  address registered on the ALU board's master clock (about 20 ns
  earlier than its CYC) would, but the board can't sample CTRL's phases
  a tick after they change: their spread and the clocks' skew leave
  no room for a setup and a hold in 19.86 ns.
- **Loads and stores need 6,** a load and add 7: the RAM's read, the
  crossbar, B and the ALU's add in one cycle.

What changed in the netlist to get here, and what fails:

- **The read latches** open on the ALU board's clock (CK2, Y's) and stay
  open, their enable (LE) held by its own feedback, until the write
  phase: the next read can't reach the ALU before the board has taken
  the result, and a longer cycle gives the read longer. The copies'
  addresses and the copies' and Y's enables take LEW, LE's copy, so
  they change only while the latches are closed: at least 2 ns after
  they close (a GAL and an output enable) against their 1.8 ns hold.
- **The register numbers on the ALU board** (above).
- **The clock tree** on the backplane (above), and no MCLKN, which
  nothing took. CTRL loses its MCLK and CYC buffers to the backplane's.
- **No gated clocks on CTRL, ALU or MEM:** MAR, H and the queue's
  sixteen registers are 74ABT823s (9 bits, a clock enable, three-state
  outputs) on their board's plain clock, U_LN0's latched address bits
  are held by feedback, and the enables come from the microinstruction
  (ALE_n for MAR) and the queue's GALs (QLD0_n, QLD1_n, HLD_n). A gated
  clock was a GAL later than the clocks that launch its data, so A and
  B could change before it rose (MAR −10.2 ns, the queue −4.2), and its
  ARM sampled WPH on the master clock a tick after WPH changed, which
  doesn't fit a tick (−3.8). IO's ALEK and VIDEO's three remain (those
  boards aren't timed yet).
- **The opcode stays on CTRL:** the ALU's function, carry and flags
  are its microinstruction's alone (AOP, CI and FL; their opcode-driven
  codes are reserved), so each operation has microcode of its own,
  which the decode table's entries make free. The ALU's U_ALUF stops
  decoding opcodes, and eight backplane lines come free.
- **Every board has its own µPC:** CTRL drives the next address
  (UPCN) on the backplane, and each board loads it on the clock its
  slice's 574s take. A µPC on CTRL alone changed the word under the
  other boards' 574s before they had loaded it (the parts' output hold
  is 0); a µPC clocked later on CTRL would race the flags into the
  next-address logic instead.
- **22V10s the part can implement:** a 22V10 has one product term for
  each output enable and for its reset. The GAL helper now records any
  GAL that asks for more and refuses it in Reed's checks; CTRL's
  U_IMMG asked for 9 and 10, and now takes its enables from U_IMMO.
- **The cases pin IORD_n and IOWR_n high** (memory loads and stores),
  as they do the WAIT lines: a 26 ns setup on the flags at every length
  was the VIDEO board's read latch possibly on B.
- **What still fails,** with the engine's fixes (below), at each word's
  length; the cases branch on WEN, which the case's start leaves open:
  - **MAR** (−1.2 ns, loaded from a register): A against MEM's clock,
    the slots' skew.
  - **The write strobe against the addresses** (U_RFA/U_RFB, −5.2 ns):
    the copies' addresses switch through two GALs after WPH, the strobe
    through one after WRS, down two trees. U_RFW now holds each copy's
    strobe off until its address is W, and the address muxes have
    their consensus terms, so each bit changes once (a bit the same on
    both sides doesn't move): the strobe can't start before the address
    is there. The engine can't see that, as it compares the address's
    latest change with the strobe's earliest, not with the change that
    lets the strobe fall; with the register numbers known, the copy
    whose address doesn't change passes.
  - **Y against the copy** (−17.5 ns, with no write): both enables
    switch from U_BYP as LEW rises, with no break before make; most of
    the slack is the engine taking LEW's rise and the addresses that
    follow as one change.
  - **The microinstruction's holds:** each board's µPC against UPCN
    (−1.7 ns: CTRL's next-address GALs change UPCN as CTRL's own clock
    rises, before another board's may have), and the 574s against the
    µPC on the same clock net (−0.6 ns: the parts' output hold is 0,
    and the wires on a board are 0–1 ns).
  - **PC, FPC** (−1.6 to −3.9 ns, in the words that load them from A).
  - **Interrupts are synchronised** to CTRL's cycle clock (U_IRQS, a
    74F74: two flip-flops) before the decode sees them; the crossings
    from the CF card's INTRQ went.
- **The backplane's spare lines:** ten. The tree takes four source
  pins on top of the four clocks and the decoded register numbers'
  DEC1_n one; MCLKN's line, the opcode's eight and the master clock's
  two guard grounds (row b's grounds are beside every pin) came back.
  (Not 160-pin connectors: Emily, 2026-11-04.) CTRL's sources could
  share their positions with its own slot's clocks, for four more, but
  only with a CDC341 a clock on CTRL to match the tree's stage.
- **A false path, named and counted:** every check but the register
  file's own leaves out what goes through LEW.

**The engine,** fixed for what Reed found (RFC 0048, at
`claude/dazzling-volta-xxh8wp` 07d2c97):

1. **Gated outputs:** a change that reaches an output only once another
   input changes is traced through that input, so the latches' opening
   at CK2 gets CK2's credit. Y's and the flags' holds went.
2. **Latches:** a change that goes back through the closing of the
   latch's own enable, on the same net, and passes its hold doesn't
   reach Q. LEW isn't LE's net, and LE's opening may glitch by Atmel's
   rule (WPH falling and CK2 rising overlap), so the false path through
   LEW stays for now.
3. **False paths** apply to strobes' and handovers' checks too, and
   strobes get the CPPR credit.
4. **Widths** credit the path a signal's two edges share: the write
   strobe's width passes. (Open in RFC 0048: rise and fall are taken to
   track.)
5. **No checks** are now a glitch with a note, not silence.

It also stopped keeping an input's old value when its change didn't
reach an output, which had been optimistic: the gated clocks', MAR's,
the queue's, the µPC's and the interrupt's failures above showed then.

### 14.4 Branches

A `Bcc` tests the flags in its second word, since the flags of the
instruction before reach CTRL only in the cycle after: not taken it's two
microcycles. Taken, the target is computed in the ALU (PC on A, the
displacement on B), sent back out on A to FPC and PC, fetched, decoded
from the queue, and its first word fetched from the control store:
about five microcycles, against the napkin's 9 ticks. The napkin assumed
a branch adder on CTRL and the fetched parcel bypassed into the decode;
both would need CTRL to give up something (PC could move to MEM, with
two control lines for its advance).

### 14.5 Design for test

Everything between boards is on the backplane: A, B and the 64 control
lines. A board can be tested alone by a tester on the 128 lines
(a microcontroller or an FPGA board with a few hundred I/O), playing a
cycle at a time:

- **ALU:** drive the clocks, the next µPC, UPCN (its slice holds a test
  microprogram as well as the real one), OP and d, s and x, and A and B;
  read the flags, QIN, and A and B.
- **MEM:** drive the clocks, UPCN, A, B and FETCH; read B, MQ0, AERR,
  ALE and the I/O strobes.
- **CTRL:** drive the clocks' sources, the flags, MQ0, AERR, IRQ and the
  WAIT lines; read UPCN, OP, the register numbers, FETCH, and A and B.
- **IO and VIDEO:** drive ALE, IORD_n, IOWR_n and SZ with A and B, as
  MEM would.

Because every control line has one driver, a board's outputs and inputs
are known from bus.py alone. The simulator's `vector` fixture can play
such a test against a board's netlist; that harness isn't built yet.

### 14.6 Next

[clocking-and-front-end.md](0049-rfc-board-first/clocking-and-front-end.md)
has the clock card (built: register ops in 5 ticks with the wires), where
the fast clock has to go, and what the branch path, two transfers a
cycle and the write phase are worth. Section 14.3 is from before the
card.

1. **The register file's timing:** 7 ticks for now (Emily, 2026-11-04),
   in place of the 5 of 2026-11-02: under the strict analysis a read and
   a write in one cycle of a single-ported copy don't fit 5 or 6 with
   margin, and 5 was worth about 1% on RFC 0050's suite. A dual-ported
   register file: leaning against (special parts), not a definite no.
   The netlist isn't changed yet: the design gets completed first, and
   this comes back after ([clocking-and-front-end.md, 6](0049-rfc-board-first/clocking-and-front-end.md#6-the-write-phase-at-6-or-7-ticks)).
2. **The clocking, again:** a board can't sample CTRL's phases a tick
   after they change, which the read address on the master clock (for
   5 ticks) and strobes made on each board would need; phases each
   board makes for itself in lockstep would avoid it. A synchroniser
   for the interrupt requests (done). Y's handover, the µPC's holds
   (14.3); cases with the register numbers known (a bypass, none), as
   the unknown ones hide paths.
3. **The branch hardware**, if CTRL can give room.
4. **The control store's part:** the 55 ns flash for now (14.2).
5. **The minimum delays' fraction** (RFC 0048, open): 30% makes every
   same-edge ordering fail; real minima for the 22V10s would help most.
6. **The microcode and a cycle-level model** (done, 2026-11-05:
   [microcode-and-model.md](0049-rfc-board-first/microcode-and-model.md)):
   the user instruction set but `DIVUL`, `ADC`, `SBC`, `CLZ` and the
   system instructions; the model in lockstep with the chip level; RFC
   0050's workloads all right on it, 360-720 ns an instruction at 7
   ticks. Next there: an index dispatch, the fetch and the refill,
   multiply and shifts. The rest of the instruction set is done too
   (item 9).
7. **The board tester** of 14.5, in the simulator first.
8. **System features, some time** (Emily, 2026-11-05): register banking
   (the register file's SRAMs are 64K deep and use addresses 0-31 only:
   a bank register on their address bits 5 and up, the microcode's
   registers shared or banked **open**), and a trap on an address with
   bit 31 clear (beside the address error: MEM latches A30 with MAR
   already). Both after the exceptions' microcode, following RFC 0029.
   Built with item 9: banked, the microcode's registers too; bit 31 as
   RFC 0029's window has it.
9. **The system half and a kernel** (done, 2026-11-05:
   [system.md](0049-rfc-board-first/system.md)): RFC 0029 on Reed, its
   differences **open** (interrupts by the IO board's sources at fixed
   levels, contexts of 4 MB, the page map's enable in `ctx`); a fault
   cancels its cycle and the next; the page map on MEM; every instruction
   of draft 2 but the tentative ones. The system test the same as draft
   2's system simulator, and in lockstep at chip level; a small
   preemptive kernel on the model and at chip level. Memory words 7
   ticks with the map. 0-2.3% on RFC 0050's suite.

