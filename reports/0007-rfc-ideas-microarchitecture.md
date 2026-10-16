---
number: 7
type: rfc
title: Microarchitecture and clocking ideas
status: open
date: 2026-10-15
context:
  studies: [v1_isa, v1b_hw, graphics, v2_guests]
  commit: 0987e76
---

# RFC 0007: Microarchitecture and clocking ideas

An ideas RFC: a scratchpad of ideas for the CPU's implementation, each
with its own status ([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)).
The evidence is in the reports each item links to.

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1, or the draft 1b hardware has it |
| **measured** | It has numbers behind it |
| **recommended** | Suggested for draft 2 or the next hardware |
| **decided** | Emily chose it; not built yet |
| **open** | Discussed, not decided |
| **not recommended** | The evidence is against it; Emily hasn't decided |
| **rejected** | Decided against, with the reason, so it isn't proposed again without new evidence |

Two sources of numbers: the draft 1 timing model's six configurations
([RFC 0004](0004-rfc-draft-1-isa.md#33-the-hardware-configurations)),
and the 213-chip draft 1b hardware, a chip-level netlist in the model's
D32-separate configuration ([report 0012](0012-report-draft-1b-hardware.md),
[report 0012](0012-report-draft-1b-hardware.md)). Chip counts are rough
estimates unless they come from that netlist.

## 1. Datapath and fetch

| Proposal | Status | Notes |
|---|---|---|
| 32-bit datapath (D32) instead of 16-bit (D16) | **measured**, **adopted** in the draft 1b hardware | ~22% fewer cycles; ~25–35 more chips. Draft 1 starts paying off here: 1.6–1.7× draft 0 overall with overlapped fetch. On a 16-bit datapath and bus, draft 1 is slower than draft 0 on everything but multiply and divide, so a narrow implementation first is rejected (Emily, 2026-10-15) |
| Overlap the next fetch with the last cycle (draft 0 style) | **measured**, **recommended** | 17–22% fewer cycles than a separate fetch cycle; ~0–2 chips. The draft 1b hardware already writes back in its fetch cycle, so against it the model expects 12%. It needs the decode ROM's input, the opcode on the data bus, at a different time in each instruction ([report 0012](0012-report-draft-1b-hardware.md#8-known-issues-and-what-a-second-iteration-would-change)) |
| Wide fetch: 32-bit bus plus two-parcel prefetch buffer | **measured**, **recommended** | ~10% fewer cycles than overlap, single-cycle word loads; +10–15 chips. Only D32-wide beats draft 0 on every program. Graphics takes 0.67 of D16-overlap's cycles on it, more than all the ISA ideas together ([report 0019](0019-report-graphics.md#and-the-hardware)); the operating system's paths take 53–68% of D32-separate's ([report 0020](0020-report-operating-system.md#the-paths-measured)). If the datapath must be 16 bits, keep the 32-bit bus: D16-wide is 1.36–1.48× draft 0 |
| A loop buffer: the last 16 or more parcels fetched, replayed when a short backward branch is taken | **open** | Executed instructions inside a loop of at most 8, 16, 32 and 64 parcels: 44%, 51%, 69% and 76% of the hand-written programs', 12%, 32%, 50% and 64% of compiled C's ([RFC 0006](0006-rfc-ideas-isa.md#35-what-1b-code-uses)'s programs). Any backward branch can use it, `DBNZ` or not: the branch's offset says where the loop starts, so a hit compares it with a count of parcels fetched in sequence since the last jump, and needs no address comparator (the CDC 6600's instruction stack; the 68010's loop mode with `DBcc`). A jump, interrupts included, flushes it, so code that writes code stays safe. On the draft 1b hardware as built it saves little, since the fetch cycle also writes back. With overlapped fetch, fetching is 30% of its microcycles, and a 16-parcel buffer would save at most about 15% of hand-written cycles and 10% of compiled ones (32 parcels: 20% and 15%), rough upper bounds; it also leaves the bus to loads and stores inside loops. Roughly 8–10 chips: four 74F189s for 16 parcels driving the data bus in place of the RAM, two 4-bit counters and the compare. It's the bigger fetch buffer kept open below |
| Two 16-bit transfers per cycle on the local memory bus (32-bit loads and stores in one cycle) | **open**, parked | The second halves of 32-bit transfers are 6.7% of all executed cycles (14–15% in queens and fib) |
| Write results back to the register file in the same cycle | **open** | 33% of draft 0's cycles went to a separate write-back (CPI 2.1 → ~1.4), but it needs much faster register-file parts or a slower clock. The draft 1b hardware puts the write-back in the fetch cycle instead, which is most of why it takes 0.91 of the model's cycles |
| Pipelined microinstruction register | **adopted** in the draft 1b hardware | 15 × 74HCT377; control signals are valid 40 ns after the clock. With it, the 32-bit draft 1b hardware runs at 334 ns against draft 0's 486 ns |
| Fix bus contention when a bus changes source | **recommended** | Up to 67 ns at worst-case delays in draft 0. In the draft 1b hardware, 37 ns on the B bus and 24 ns on the data bus after a store. A break-before-make dead time at the start of each cycle, or ACT buffers, would fix it |
| A barrel shifter | **open** | The draft 1b hardware shifts 1–2 places a step (right shifts take 2–11 cycles). For graphics a barrel shifter saves 4.4% over all the phases and 25–34% of bit-aligned copies at 1 bit, and a funnel shift ([RFC 0006](0006-rfc-ideas-isa.md#5-more-instruction-ideas)) needs one. A 32-bit one is about 40 multiplexer chips; the cheaper half step is the byte rotation the datapath already has plus a rotate by 0–7 ([report 0019](0019-report-graphics.md#a-funnel-shift-or-a-barrel-shifter)) |
| A faster multiply for small multipliers | **open** | The draft 1b hardware takes 16 or 32 steps, where the timing model stops early; that alone makes mandel 1.39× the model. An 8-step path for multipliers below 2⁸ is a byte test and two cycles to realign the product ([report 0012](0012-report-draft-1b-hardware.md#8-known-issues-and-what-a-second-iteration-would-change)); it wouldn't help mandel's fixed-point fractions |
| Shrinking the draft 1b hardware | **open** | 213 chips, more than twice draft 0. The big levers: a narrower control word with decoded fields (the microcode ROMs and uIR are 30 chips), at some cost in speed; or one register-file copy instead of two, at an extra cycle for two-register operations |
| `SAVE`/`RESTORE` (and `LDM`/`STM`) as a microcode loop, with the register number counting in SX | **recommended** | The draft 1b hardware unrolls a routine per register range: 1,476 of its 3,507 microinstructions (`SAVE` 406, `RESTORE` 1,070), 42% of a control store 86% full ([RFC 0006](0006-rfc-ideas-isa.md#35-what-1b-code-uses)). SX already feeds the register-file address; making it a counter is about 1–2 chips. The four instructions would take a few dozen microinstructions, at about the same 3 cycles per register (an estimate). A register mask would also have to skip its zero bits: a cycle per bit through MQ, or a priority encoder, 3–4 chips |
| Quick constants and stack-slot offsets from the instruction register, not the microcode | **recommended** | The draft 1b microcode has a routine per value of `#q`, `#−q` and `[sp + 4R]`'s offset, for every operation that takes them ([report 0012](0012-report-draft-1b-hardware.md#5-control)), which the immediate unit could take from the parcel instead. Draft 2 keeps its constants in a few fixed places in the parcel ([RFC 0028](0028-rfc-draft-2-isa.md#2-instruction-format)), so gathering them is mostly wiring |
| Decode a cycle later, from IR | **not recommended** | It would take the RAM out of the fetch path, which sets the draft 1b hardware's clock, but costs a cycle on every instruction |
| Separate instruction bus (Harvard) for speed | **rejected** | Would save 1.6% of draft 0's cycles; the bottleneck is register write-back |
| Pipelining, caches | **rejected** for now | Lowest payoff per effort; hazards and forwarding in TTL multiply the debugging. More overlap of the fetch, or a bigger fetch buffer (in effect a small instruction cache), stays open: see overlapped and wide fetch above (Emily, 2026-10-15) |
| ALU from in-production parts | **open** | 74181/74182 are new-old-stock only. Alternative: 74HC283 adders plus multiplexers for the logic functions |
| 6502-style page-crossing shortcut for address arithmetic on D16 | **adopted** (timing model assumption) | Add the low halves; a second cycle only when the upper half changes |
| Extension parcels latched, not fed straight into the ALU | **adopted** (timing model assumption; the draft 1b hardware latches them in T) | Draft 0's critical path was the 16-bit immediate going from memory straight into the ALU |
| Scaled index (`*2`/`*4`/`*8`) | **adopted** in 1b | The draft 1b hardware's indexed load (`MOV r3, [r2 + r4*4]`) takes 6 cycles |

## 2. Clocking: variable-length cycles

**decided** ([docs/clocking.md](../docs/clocking.md)). Each
microinstruction picks how long its own cycle is. Measured from the draft
1b hardware's timing analysis
([report 0012](0012-report-draft-1b-hardware.md#7-timing)) over the programs;
this RFC is where the numbers are recorded. Built into the draft 1b CPU
card on the system bus, with four lengths, it makes the suite's
microcycles 1.14 times as fast
([report 0025](0025-report-draft-1b-system.md#12-variable-length-cycles)).

- **Why.** A fixed clock runs every cycle at the slowest microinstruction's
  speed. With HCT + LS181 at worst case:
  - the fetch-ending cycles (25% of executed cycles) need 309 ns;
  - the multiply steps (7%) need 334 ns;
  - the rest average 254 ns, and a quarter of all cycles need only
    200–219 ns.

  With typical delays or 74ACT the spread is bigger: the memory-bound fetch
  sets the clock while the logic gets much faster.
- **Gains** (geometric mean over 18 programs, against a fixed clock; with
  a 50 MHz master clock every length is a whole number of 20 ns ticks):

  | Scheme | HCT + LS181 worst | HCT + LS181 typical | ACT + F181 worst |
  |---|---:|---:|---:|
  | Ideal: every cycle exactly as long as it needs | 1.22× | 1.36× | 1.45× |
  | 50 MHz master clock (20 ns steps) | 1.17× | 1.29× | 1.35× |
  | 4 lengths (2-bit field) | 1.16× | 1.28× | 1.35× |
  | 2 lengths (1-bit field) | 1.07× | 1.19× | 1.28× |
  | 2 lengths derived from existing fields (fetch and multiply long) | 0.98× | 1.05× | 1.02× |

- **How:**
  - A 2-bit length class in the microinstruction: a 16th microcode ROM and
    register, +2 chips. With pipelined microcode it's valid 40 ns into the
    cycle, long before the shortest cycle (~200 ns) ends.
  - A 50 MHz master clock and a counter end the cycle; the CPU clock comes
    from a flip-flop, so it can't glitch. The generator needs 74AC/74F
    parts, ~5–8 chips; 74HCT can't count at 50 MHz at worst case.
  - **Jumpers** map each length class to a count, so one microcode image
    runs on any parts and can be tuned on a real board. **decided.**
  - **One clock edge for all registers.** Phases only shape strobes: the
    write window starts a fixed time after the edge and ends a fixed time
    before the next.
  - **The timer and cycle counter count real time** (master-clock ticks),
    not CPU cycles. **decided.**
  - **Wait states come free:** the same mechanism stretches a cycle for a
    slow device or the system bus.
- **A 20 ns tick (50 MHz).** **recommended**: not fully decided (Emily,
  2026-10-15). Finer ticks gain at most
  about 3%, and a faster counter would need fussier parts. Gains with the
  best 4 lengths for each grid:

  | Tick | HCT + LS181 worst | HCT typical | ACT + F181 worst |
  |---|---:|---:|---:|
  | 10 ns | 1.18× | 1.30× | 1.37× |
  | 12.5 ns | 1.18× | 1.28× | 1.41× |
  | 15 ns | 1.17× | 1.29× | 1.34× |
  | **20 ns** | **1.16×** | **1.28×** | **1.35×** |
  | 25 ns | 1.15× | 1.26× | 1.34× |

  The best lengths at 20 ns are 11/14/16/17 ticks for HCT at worst case and
  6/7/10/11 for ACT.
- **Variable-length cycles meet the synchronous system bus.**
  **recommended.** Details in
  [RFC 0014, section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus):
  a bus access is one microcycle, stretched until the transfer is done;
  if the bus clock is the master clock divided down, the CPU needs no
  synchroniser; writes are posted through registered transceivers; the bus
  parks on the main CPU. The bus clock's period and source are **open**
  (Emily, 2026-10-13).
- **Lengths derived from existing fields:** **rejected.** At most 1.05×,
  because a few ordinary microinstructions need nearly as long as the
  fetch.
- **Clocking datapath registers on different phases:** **rejected.** It
  mostly moves slack between cycles, adds hold-time hazards between phases,
  and complicates the timing analysis and simulation.

## 3. Parts

**open.** What's still made decides more than speed
([report 0012](0012-report-draft-1b-hardware.md#8-known-issues-and-what-a-second-iteration-would-change)).

- **Surface-mount parts.** Emily is more open to them: an SMT build,
  assembled by a PCB assembly service, would be easier to put together
  (2026-10-15). Most of the problems below are about DIP, and go away
  with SMT.

- The 74181 and 74182 are new-old-stock only (the alternative is in
  section 1).
- Fast SRAM is no longer made in DIP; 5 V 512K × 8 parts in 10–15 ns still
  come in SOJ and TSOP ([RFC 0016](0016-rfc-video.md#42-size-and-width)).
  The AS6C4008 main RAM is available in DIP.
- The 55 ns SST39SF010A flash is PLCC only.
- There is no 74ACT30 or 74ACT688, so the ACT variant uses HCT there. The
  74HCT299 is made only by TI.
- On the bus, report 0022 suggests ABT16245 in TSSOP for wide drivers and
  no DIP ([RFC 0014, section 17](0014-rfc-system-bus.md#17-signal-integrity)).
- PLDs: Emily would rather not use them, though it isn't a definite no
  ([RFC 0014](0014-rfc-system-bus.md#14-open-questions)).

## 4. Other instruction sets in the control store

Draft 2's control store and decode table are RAM, so the CPU can run
another instruction set's microcode: RV32IM, the 6502 and draft 1b's
binaries run on it as it is, and Thumb with D1 below
([report 0039](0039-report-guest-isas.md)). The changes below were
measured on the register-transfer model, not built.

| Proposal | Status | Notes |
|---|---|---|
| A wider decode table: for every first parcel, also the IR to load and a 16-bit immediate (D1) | **measured**, **open** | Moves a guest's register fields to where draft 2's selectors look, and gives its immediate ready-made. Thumb runs at 2.4 cycles an instruction with it, against some 6 to 8 without; it would do the same for the PDP-11 and the 68000. Two 64K × 16 SRAMs, a 16-bit register and its B-bus drivers, a mux on the IR's input; no control bits (BX = 6 is free) |
| Decode table pages selected by two status-word bits (D2) | **measured**, **open** | User processes in different instruction sets: RTI loads the bits with the status word, exception entry clears them, so the kernel always runs draft 2 and a context switch is the same for every process. A draft 2 kernel time-slices draft 2 and Thumb processes with it. Decode SRAMs four times as deep, two flip-flops |
| The whole 64K control store reachable: NEXT 16 bits wide (D3) | **measured**, **open** | The sequencer reaches 8K words; draft 2's own microcode is 6,235 of them, 1b's 7,856, Thumb's 4,770, so no guest but the 6502 fits beside draft 2's. Decode entries can stay 13 bits (routines start in the first 8K). Takes the control word's three spare bits |
| A lookup table on the head parcel, on the B bus, and SX loaded from the B bus, five bits | **open** (estimated) | For guests whose register fields aren't in the first parcel or are five bits (RV32, AVR, ARM): one cycle for a register number or an immediate from the second parcel. RV32 from 9.9 cycles an instruction to an estimated 6.6, and to 5.4 with shifts by a count (the barrel shifter above). A 256K × 16 SRAM, a mux on SX, three or four control bits: with D3, a wider control word |
