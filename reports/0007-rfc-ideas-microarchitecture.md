---
number: 7
type: rfc
title: Microarchitecture and clocking ideas
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw]
  commit: e494b0c
---

# RFC 0007: Microarchitecture and clocking ideas

An ideas RFC: a scratchpad of ideas for one area, each with its own status
([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). It was split out of
`docs/proposals.md` in the restructure, so the items keep the statuses they
had there:

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | Evaluated with numbers ([report 0001](0001-report-draft-0-evaluation.md), [report 0004](0004-report-draft-1-evaluation.md)) |
| **recommended** | Suggested for the next draft or hardware round |
| **decided** | Emily chose it for the next hardware round; not built yet |
| **open** | Discussed, not decided |
| **rejected** | Decided against, with the reason, so it doesn't get re-proposed without new evidence |

Chip counts are rough estimates, scaled from the 98-chip draft 0 design.

## 4. Microarchitecture

| Proposal | Status | Notes |
|---|---|---|
| 32-bit datapath (D32) instead of 16-bit (D16) | **measured**, **recommended** | ~22% fewer cycles; ~25–35 more chips. Draft 1 starts paying off here: 1.6–1.7× draft 0 overall |
| Overlap the next fetch with the last cycle (draft 0 style) | **measured**, **recommended** | 17–22% fewer cycles than a separate fetch cycle; ~0–2 chips |
| Wide fetch: 32-bit bus plus two-parcel prefetch buffer | **measured** | ~10% fewer cycles, single-cycle word loads; +10–15 chips. Only D32-wide beats draft 0 on every program. If the datapath must be 16 bits, keep the 32-bit bus: D16-wide is 1.36–1.48× draft 0 |
| Write results back to the register file in the same cycle | **open** | 33% of draft 0's cycles go to separate write-back (CPI 2.1 → ~1.4), but it needs much faster register-file parts or a slower clock |
| Pipelined microinstruction register | **adopted** in the draft 1b hardware | 15 × 74HCT377; control signals are valid 40 ns after the clock. With it, the 32-bit draft 1b hardware runs at 334 ns against draft 0's 486 ns ([studies/v1b_hw/hardware.md](../studies/v1b_hw/hardware.md)) |
| Fix bus contention when the B bus changes source | **recommended** | Up to 67 ns at worst-case delays in draft 0, 37 ns in the draft 1b hardware |
| Separate instruction bus (Harvard) for speed | **rejected** | Would save 1.6% of draft 0's cycles; the bottleneck is register write-back |
| Pipelining, caches | **rejected** for now | Lowest payoff per effort; hazards and forwarding in TTL multiply the debugging |
| ALU from in-production parts | **open** | 74181/74182 are new-old-stock only. Alternative: 74HC283 adders plus multiplexers for the logic functions |
| 6502-style page-crossing shortcut for address arithmetic on D16 | **adopted** (timing model assumption) | Add the low halves; a second cycle only when the upper half changes |
| Extension parcels latched, not fed straight into the ALU | **adopted** (timing model assumption) | Draft 0's critical path was the 16-bit immediate going from memory straight into the ALU |
| Scaled index (`*2`/`*4`/`*8`) | **open** | Needs a shifter on the B bus (~8–16 chips), or up to 3 extra cycles |
| `.align` that pads code with `NOP`s | **recommended** | Wide-fetch cycles depend on loop alignment by up to 15%; today `.align` pads with zeros, which are `HALT` |
| Parts availability | **open** | Fast SRAM is no longer made in DIP; the 55 ns flash is PLCC only; no 74ACT30/688 |

**Clocking: variable-length cycles.** **decided.** Each microinstruction
picks how long its own cycle is. Measured on the draft 1b hardware
([studies/v1b_hw/hardware.md](../studies/v1b_hw/hardware.md)):

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
- **The tick stays 20 ns (50 MHz).** **decided.** Finer ticks gain at most
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
  [RFC 0014, section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus).
  - If the bus clock is the master clock divided down (÷ 3 for 60 ns), the
    CPU always knows where the next bus clock edge is; no synchroniser. The
    bus clock is **open** for now (Emily, 2026-10-13), and so is where it
    comes from.
  - A bus access is one microcycle, stretched until the transfer is done: a
    read takes about 200 ns at 60 ns. Waiting for the next bus edge costs
    1.5–2.5 ticks per access. CPU cycle lengths never need to be multiples
    of the bus clock.
  - **Posted writes** through registered bus transceivers (74ABT652): the
    CPU doesn't wait for a write unless it reaches the bus again first.
  - **The bus parks on the main CPU**, and the pipelined microcode requests
    it a cycle early when it's elsewhere.
  - The bus interface runs on the clock returned through the backplane, like
    every other card.
- **Lengths derived from existing fields:** **rejected.** At most 1.05×,
  because a few ordinary microinstructions need nearly as long as the
  fetch.
- **Clocking datapath registers on different phases:** **rejected.** It
  mostly moves slack between cycles, adds hold-time hazards between phases,
  and complicates the timing analysis and simulation.
- **Two 16-bit transfers per cycle on the local memory bus** (32-bit loads
  and stores in one cycle): **open**, parked. The second halves of 32-bit
  transfers are 6.7% of all executed cycles (14–15% in `queens` and `fib`).
