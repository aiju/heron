# Design proposals

Every idea raised in the design discussions so far, so none get lost. It's
organised by topic, not by when it came up.

Each proposal has a **status**:

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | Evaluated with numbers ([evaluation.md](evaluation.md), [evaluation-v1.md](evaluation-v1.md)) |
| **recommended** | Suggested for the next draft or hardware round |
| **decided** | Emily chose it for the next hardware round; not built yet |
| **open** | Discussed, not decided |
| **rejected** | Decided against, with the reason, so it doesn't get re-proposed without new evidence |

Chip counts are rough estimates, scaled from the 98-chip draft 0 design.

## Contents

1. [Direction and ambition](#1-direction-and-ambition)
2. [Instruction set](#2-instruction-set)
3. [Floating point](#3-floating-point)
4. [Microarchitecture](#4-microarchitecture)
5. [Memory system and buses](#5-memory-system-and-buses)
6. [I/O](#6-io)
7. [Channels and DMA](#7-channels-and-dma)
8. [Video](#8-video)
9. [Networking](#9-networking)
10. [Operating system support](#10-operating-system-support)
11. [MMU](#11-mmu)
12. [Address registers with hidden state](#12-address-registers-with-hidden-state)
13. [Big ideas](#13-big-ideas)
14. [Wishes from the program writers](#14-wishes-from-the-program-writers)
15. [Open questions](#15-open-questions)
16. [Offered next steps](#16-offered-next-steps)

## 1. Direction and ambition

- **Put the ambition into the system, not raw CPU speed.** **open.**
  - Designing big is cheap now (netlist language, simulators, timing
    analysis). Building big isn't: wiring, signal integrity, parts.
  - Software will be the long pole: a C compiler, an OS port, drivers.
  - Three directions:
    1. A whole computer: OS, compiler, storage, terminals, front panel.
       Biggest payoff. Bill Buzbee's Magic-1 (~200 TTL chips, runs Minix)
       is the calibration point.
    2. Bigger: 32-bit (below).
    3. Faster: pipelining and caches. Lowest payoff per effort.
- **OS ambition ladder.** **open.** Aim for the top, build in stages:
  1. Resident monitor: needs a boot ROM.
  2. Single-tasking disk OS (CP/M, OS/8): needs storage, a system-call
     convention and a loader.
  3. Unprotected multitasking: needs timer preemption and relocatable
     programs.
  4. Protected multi-user (V6 Unix on a PDP-11/40): needs modes, an MMU, a
     kernel stack and faults.
- **A 32-bit architecture, built 16 bits wide first** (the System/360
  Model 30 and the 68000 did this). **adopted** (draft 1), **measured.**
  - A 32-bit address space removes the workarounds for 64 KB: banking,
    video windows, I/D spaces.
  - It gives encoding room and suits C and existing software. It's
    period-authentic: VAX-11/780, Eclipse MV/8000.
  - Rough chip counts:

    | Machine | Chips |
    |---|---:|
    | 16-bit full system | ~125 |
    | 32-bit on a 16-bit datapath | ~140–150 |
    | Full-width 32-bit | ~165, ~190–200 with the system features |

  - Measured: a 32-bit ISA on a 16-bit datapath and bus is *slower* than
    draft 0 on ordinary code. It only gains on multiply/divide. See
    [section 4](#4-microarchitecture).
- **Keep 16-bit instruction parcels with 0–2 extension parcels**
  (precedents: SuperH, 68000, Thumb). **adopted.**
  - Alternatives for 32-bit constants, both **rejected**: literal pools
    (SuperH; awkward pool placement) and a prefix instruction (the
    Transputer's `pfix`; hidden state, interrupt shadow).
  - Fixed 32-bit instructions would suit a future pipelined full-width
    implementation better. **rejected** for now.
- **Toolchain:** object files and a linker, a stable system-call ABI, and a
  language above assembly (a small C compiler, Forth, or BASIC). **open.**
- **Software in simulation first:** a toy kernel and a compiler port on the
  instruction-level simulator, ahead of hardware. **open.**
- **Build in stages on a backplane of cards** (CPU, memory, then MMU and I/O
  cards). Above ~150 chips, only PCBs or a backplane, no breadboards.
  **decided**: 4-layer PCBs and a backplane with two connectors per slot
  ([section 5](#5-memory-system-and-buses)). The CPU needs at least two
  boards; how to split it is **open**.
- **A second, heterogeneous CPU: an ECL number cruncher**, designed
  separately. It shares the system bus and has its own RAM. **decided** in
  principle. What the bus needs to know from its design:
  - its word size (32 or 64 bits) and how much RAM it has;
  - whether it is a bus master (fetching its own data) or only a slave the
    main CPU feeds;
  - whether it uses burst transfers;
  - whether the backplane should carry its −5.2 V supply.

  The draft bus specification to hand to its design is
  [system-bus.md](system-bus.md).

  It has to compute out of its own RAM, because no hobby backplane can
  stream operands to it. At ~10 MFLOPS on 64-bit numbers, a streaming
  vector operation like `y += a*x` would need ~120 MB/s. Dense work is fine
  over the bus: a 100 × 100 matrix multiply moves 240 KB (~10 ms at
  25 MB/s) for ~200 ms of computing.

## 2. Instruction set

### 2.1 Adopted in draft 1

These came from the draft 0 evaluation; draft 1 has them
([isa-v1.md](isa-v1.md)):

| Proposal | Evidence or reason |
|---|---|
| Hardware `MULU`/`MULS`/`DIVU`/`DIVS`, `HI` register for the high half and remainder, `DIVUL` 64/32 | Software multiply/divide was 61–80% of cycles in mandel, matmul, bignum, interrupts |
| `HI` as the multiply/divide shift register (instead of `MULH`/`REM`) | One divide gives quotient and remainder; the product isn't computed twice |
| `INC`/`DEC` (and 1a `ADDI`) set only N and Z | Overwriting C forced the shape of the multiply loop and caused a flag bug |
| `SAVE ra-rb` / `RESTORE ra-rb` | `PUSH`/`POP` were 34% of queens' cycles and 21% of fib's |
| `SWI #n` with its own vector | The shared trap vector meant decoding `[PC − 2]` |
| `SETcc` | Programs had no set-on-condition; Life used a `NEG`/`ADC` trick |
| Shifts by n (immediate or register), `ROR` | Draft 0 shifted one bit per instruction; `SWAB`+`ZXT` were shifts by 8 in disguise |
| `CLZ`, `SWAP` (halves), `SXB`/`ZXB`/`SXH`/`ZXH` | Normalising, bitmaps, halfword work |
| Sticky Z for `ADC`/`SBC` | A 64-bit compare needs only one branch |
| `MFSR`/`MTSR` special registers (flags, `HI`) | Generalises `MFF`/`MTF` |
| PC-relative `LEA` and addressing | Position-independent code; replaces most `MOV r, #address` |
| Halfword and sign-extending loads | 32-bit machine |
| Immediate kinds: signed 16, unsigned 16, 16 shifted left 16, 32 | Most constants still fit 2 parcels |
| Jumps and calls with 16-bit PC-relative displacements, 32-bit absolute form | Absolute 32-bit targets would be 3 parcels |
| Vectors 4 bytes apart: reset, IRQ, illegal, SWI, divide error, address error | |
| Word accesses 4-aligned, halfwords 2-aligned; misaligned accesses trap | |
| One escape opcode kept free (1a op F) | Future growth, floating point |

### 2.2 1a vs 1b

**measured.** Both encodings were specified, built and measured on 20
programs ([evaluation-v1.md](evaluation-v1.md)).

- **1a, RISC-like:** load/store, register-register ALU, short and long
  load/store forms, 8-bit immediates.
- **1b, CISC-like** (IBM 360 RX / 68000 / x86 style): every main
  instruction is `F D M R`, one register plus one addressing mode out of 14:
  - register, quick constant (−16…15), `[R]`, `[R + d16]`, `[sp + 4R]`;
  - indexed `[R + Rx·s + d8]`, `[R]+`, `-[R]`;
  - byte and half variants;
  - PC-relative and absolute addresses, 16/32-bit constants.
  - At most one memory operand per instruction, which keeps faults
    restartable. Size is part of the mode. Indirect `JMP`/`CALL [mem]`.
- **Result:**
  - 1b is 7–10% faster, runs 13% fewer instructions and has 3% less code.
  - The gain is concentrated in the VM (−24%), Life (−16%) and pointer
    walking. Register-bound programs are within 3%.
  - Most of the gain is auto-increment. 1b's 4-bit constants cost it code
    size, and its encoding is full.
- **Before 1b, measured on draft 0:**
  - 4.5% of draft 0 instructions were a load whose value fed the next ALU
    op; 97% of those loads were bytes, so memory operands need
    zero-extending byte forms.
  - Memory-destination operations were 0.4%, all in fib. **rejected.**

### 2.3 Recommended for draft 2

From [evaluation-v1.md](evaluation-v1.md):

- **Base draft 2 on 1a.** **recommended.**
- **Post-increment and pre-decrement loads and stores** in 1a's op F: byte
  and word `[r]+`, word `-[r]` (pushes), byte `-[r]` (backwards loops), half
  if it fits. **recommended.** Estimated to recover at least 60% of the gap
  to 1b, and it fixes the "`ADDI` sets Z" ordering problem.
- **Jump through a table** (`JMP [table + r*4]`) in a free system function.
  **recommended.** The VM's dispatch is 9 cycles in 1b against 18 in 1a.
  Matters for interpreters and command dispatch.
- **Memory increment** (`INC [mem]`, `ADD [mem], r`). **recommended.**
  Counters, interrupt handlers; fib's call counter was 30% of its time.
- **Three-operand add** (`ADD rd, rs, rt`), like 1b's `LEA [rA + rB*s]`, if
  an encoding turns up. **open.**

### 2.4 More instruction ideas, not yet decided

| Idea | Cost | Notes | Status |
|---|---|---|---|
| Shifts and rotates with a separate destination (`ROR rd, rs, #n`) | microcode | `MOV` was 25–27% of sha256's instructions | **recommended** |
| Multiply-accumulate into `HI:LO` (`MULA`), fixed-point multiply (multiply, then shift by n) | microcode | Multiply was 50% of mandel; audio, graphics, DSP | **open** |
| Bit-field extract/insert; byte reverse (`REV`) | microcode | Protocols, file formats, graphics; SHA needed big-endian loads | **open** |
| Packed byte arithmetic `ADD.B4` by gating carries at byte boundaries | 1–2 chips | Pixel arithmetic, zero-byte search. Saturation and per-lane flags cost much more | **open** |
| Zero-overhead loops (`LOOP count, end`) | ~10 chips (PC comparator) | DSP style; saves ~5 cycles per iteration in tight loops; modest here | **open** |
| `SKIPcc` (PDP-8 skips, Thumb-2 `IT`) | microcode | Branch-free min/max and conditional moves | **open** |
| Interruptible block move/fill/compare (like `REP MOVS`; progress in registers) | microcode | Page copies, screen clears; ~2 bus cycles per halfword against ~14 for a loop | **open** |
| Block I/O instruction (Z80 `INIR` style, interruptible) | microcode | ~5–6 cycles per word against ~12–15 for a software loop | **open** |
| Atomic exchange / test-and-set | microcode + bus lock | Only once DMA or a second CPU shares data structures | **open** |
| Popcount, find-first-set | microcode | Scheduler and allocator bitmaps | **open** |
| A 12-bit `BSR` (±4 KB, SuperH style) in op B | opcode | Saves ~9% of code size and no cycles; op B went to the shift group instead | **rejected** |

### 2.5 Rejected, with the evidence

| Proposal | Why not |
|---|---|
| Three-operand ALU throughout | `MOV`+op pairs were 1% of draft 0 instructions (12% in queens); doesn't fit 16-bit nibble fields |
| Compare-and-branch | `CMP`;`Bcc` is 5.4% of instructions, but a fused form needs an extension word: 2 parcels either way, ~1 cycle saved |
| `DBNZ` (decrement and branch) | 2.3% of instructions; needs a whole major opcode |
| Wider branch offsets | 95% of executed branches fit a 6-bit offset, 100% fit 8 bits; the assembler relaxes the rest |
| Link register instead of pushing the return address | ~2% of cycles, gives up a register |
| ARM-style conditional execution | No spare bits |
| 16-bit ALU ops alongside 32-bit (68000 `.W`/`.L`) | Doubles the ALU encodings and bakes the narrow implementation into the ISA |
| Decimal (BCD) arithmetic | No use |
| Separate I/O instructions (`IN`/`OUT`) | No opcode space; memory-mapped I/O works with every addressing mode |
| Register + register addressing in a load/store ISA | Not worth a major opcode; `[label + reg]` covered static arrays in 16-bit space (see the 1b indexed mode for the alternative) |

## 3. Floating point

**open**, and nothing needed yet. These decisions touch the base ISA,
so they should be settled before it's final:

- **Leave a hole:** one escape opcode with a 16-bit *command word* (like the
  68000's "line F" and the 68881, or the 8086's `ESC` and the 8087). It
  traps when no FPU is present.
  - Slow operations don't need compact encodings. The command word gives
    room for FP and later for MMU operations or block moves.
  - Before hardware exists, a trap handler emulates FP in software; same
    binaries throughout.
  - `FFFF` must stay illegal, so erased memory still traps.
- **FP registers:** a separate file, e.g. 16 × 64-bit, in the spare
  register-file SRAM. Nearly free in hardware, and doesn't take integer
  registers. The alternative, floats in integer registers (RISC-V's Zfinx),
  is simpler but doubles need register pairs.
- **Compares:** `FCMP` sets N, Z, C, V the ARM way (unordered sets C and V),
  so the existing `Bcc` conditions work and no new branches are needed.
- **Status and vectors to reserve:**
  - an FP-enable bit (for lazy context switching: FP instructions trap
    while it's off);
  - an FP exception vector;
  - a special-register number for FP control/status (rounding, sticky
    flags).
- **Can wait:**
  - instruction list and precision model (registers hold doubles,
    single precision on load/store like the 68881; or per-instruction
    precision);
  - IEEE 754, flushing tiny numbers to zero at first.
- **Implementation:**
  - microcode on the integer datapath (very roughly 30–80 cycles for a
    single-precision add or multiply);
  - or a memory-mapped period FPU: 68882 in peripheral mode, Am9511;
  - or software only.
- **The general "future-proofing kit":**
  - an escape opcode with a command word;
  - every unused function code traps;
  - `0000` = `HALT`, `FFFF` = illegal;
  - reserved bits in the status word (must be written as 0);
  - reserved vectors and special-register numbers.

## 4. Microarchitecture

| Proposal | Status | Notes |
|---|---|---|
| 32-bit datapath (D32) instead of 16-bit (D16) | **measured**, **recommended** | ~22% fewer cycles; ~25–35 more chips. Draft 1 starts paying off here: 1.6–1.7× draft 0 overall |
| Overlap the next fetch with the last cycle (draft 0 style) | **measured**, **recommended** | 17–22% fewer cycles than a separate fetch cycle; ~0–2 chips |
| Wide fetch: 32-bit bus plus two-parcel prefetch buffer | **measured** | ~10% fewer cycles, single-cycle word loads; +10–15 chips. Only D32-wide beats draft 0 on every program. If the datapath must be 16 bits, keep the 32-bit bus: D16-wide is 1.36–1.48× draft 0 |
| Write results back to the register file in the same cycle | **open** | 33% of draft 0's cycles go to separate write-back (CPI 2.1 → ~1.4), but it needs much faster register-file parts or a slower clock |
| Pipelined microinstruction register | **adopted** in the draft 1b hardware | 15 × 74HCT377; control signals are valid 40 ns after the clock. With it, the 32-bit draft 1b hardware runs at 334 ns against draft 0's 486 ns ([hardware-v1b.md](hardware-v1b.md)) |
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
([hardware-v1b.md](hardware-v1b.md)):

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
  [system-bus.md, section 10](system-bus.md#10-the-main-cpu-board-on-the-bus).
  - The bus clock is the master clock ÷ 3 or ÷ 4, so the CPU always knows
    where the next bus clock edge is; no synchroniser.
  - A bus access is one microcycle, stretched until the transfer is done: a
    read takes about 200 ns at ÷ 3 and 250 ns at ÷ 4. Waiting for the next
    bus edge costs 1.5–2.5 ticks per access. CPU cycle lengths never need to
    be multiples of the bus clock.
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

## 5. Memory system and buses

| Proposal | Status | Notes |
|---|---|---|
| **Bus release**: request/grant, three-state address and control drivers (74HCT257 instead of 74HCT157, gated read/write strobes) | **recommended**, design in now | Shared by DMA, a front panel acting as bus master, and debugging; cheap now, painful to retrofit. Now part of the system bus below |
| **Main RAM private to each CPU board**, the system bus for everything else | **recommended** | Half of all executed cycles touch memory. Backplane transceivers each way would add ~50–60 ns to those cycles: ~10% slower overall with HCT, ~19% with ACT (with variable-length cycles). Boot ROM and the clock generator stay on the CPU side too |
| **Two memory buses**: CPU-private main RAM plus a shared memory on the system bus for video, display lists, DMA and disk buffers (Amiga chip/fast RAM) | **open** | Superseded as the default by slave ports on the CPU boards (below), which let DMA reach main RAM. A fast shared-memory card stays an option for bulk data |
| **Interleaved memory time slots** (Apple II, BBC Micro): the RAM is ~9× faster than the CPU cycle, so give devices their own slots | **rejected** | Fixed slots don't fit variable-length CPU cycles. Video keeps its own memory on its card instead |
| **Tick-level RAM sharing for the slave port**: other masters use the CPU's RAM in the ticks the CPU doesn't need, with a data latch (2 × 74ACT573) freeing the RAM about 4 ticks into each memory cycle | **recommended** | Works with variable-length cycles because everything runs from one 50 MHz clock and the pipelined microcode says a cycle ahead when the CPU needs the RAM. The RAM is busy roughly 15% of the time, so remote accesses take about 180–320 ns instead of 300–600 ns, and the CPU's RAM becomes usable as a DMA buffer ([system-bus.md, section 10](system-bus.md#10-the-main-cpu-board-on-the-bus)) |
| Separate instruction and data address spaces (PDP-11/45 style) | **rejected** with the move to 32-bit | Doubled the per-process space on a 16-bit machine for one MMU address bit |
| Dual-port SRAM | **rejected** | Expensive, small sizes only |

**The system bus.** Shared by the main CPU, the ECL number cruncher
([section 1](#1-direction-and-ambition)), DMA devices and peripherals. The
draft specification is [system-bus.md](system-bus.md); the electrical rules
come from ngspice simulations of the backplane
([tmc/si/README.md](../tmc/si/README.md)).

- **Synchronous.** **decided.** One bus clock; every signal is sampled on
  its rising edge.
- **Bus clock: the 50 MHz master clock ÷ 3 (16.7 MHz) or ÷ 4 (12.5 MHz)**,
  set by a jumper on the CPU board. **recommended**, with cards designed
  for ÷ 3.
  - A transfer is an address clock and a data clock: 120 ns at ÷ 3, 160 ns
    at ÷ 4. Wait states come in whole clocks.
  - Two fast cards (ABT or FCT-T) need about 31 ns for a one-clock path,
    including up to 11 ns of backplane settling at 16 slots (simulated).
    That leaves 29 ns of slack at ÷ 3.
  - ÷ 2 (25 MHz) doesn't help single transfers, since a slave's SRAM path
    then needs a wait state anyway.

  | | ÷ 3 | ÷ 4 |
  |---|---:|---:|
  | 32-bit single transfers | 33 MB/s | 25 MB/s |
  | 32-bit bursts (optional) | 67 MB/s | 50 MB/s |
  | Simple-peripheral transfer, minimum | 180 ns | 240 ns |

- **Bursts: an optional feature.** **recommended.**
  - Pins reserved on P2 (BURST, BACK, BFIX).
  - At most 16 words, within an aligned 16-word block.
  - A slave without them is simply driven with single transfers.
  - BFIX keeps the address fixed, for FIFOs.
- **A strobe-timed bus without a clock** (8080, Z80, ISA style):
  **rejected**, again after the simulations.
  - Its read and write strobes would be multidrop lines, driven by whichever
    master owns the bus, and the timing reference for every transfer. The
    simulations show fast multidrop edges ringing back through the threshold
    region 2–14 times unless slowed by 20–35 ns.
  - In the synchronous bus, the only line that must have clean edges is the
    point-to-point clock.
  - Synchronising WAIT costs only 20–40 ns with 50 MHz masters, so that was
    never the main argument.
- **A fully asynchronous handshake** (Unibus, VME): **rejected.** Every card
  needs acknowledge logic, and the CPU still needs synchronisers.
- **Two connectors per slot**: P1 alone is enough for simple peripherals.
  **decided.** Two 96-pin DIN 41612 connectors on 6U Eurocards (233 × 160
  mm), as VME does: **recommended.**
  - **P1:** D0–D15, A1–A31, BE0–1, START, WRITE, LOCK, RD, WR, WAIT, BERR,
    REQ, GNT, BUSY, SEL, PRESENT, slot number, BCLK, CLKSRC, RESET, IRQ0–3,
    and 24 power and ground pins.
  - **P2:** D16–D31, BE2–3, W32 ("32-bit slave"), IRQ4–7, the burst lines,
    about 16 power and ground pins and about 54 user-defined pins.
  - Full lists in [system-bus.md, section 3](system-bus.md#3-signals); the
    pin-by-pin assignment is still to do.
- **Mixed widths.** **recommended.** A 32-bit slave asserts W32. Without it
  a master moves only the low halfword and repeats for the upper one. The
  masters do all the byte-lane steering, so slaves need no multiplexers.
- **Simple peripherals on the system bus** (the "simple slave" profile).
  **recommended.** A simple card needs:
  - no clock, no address comparator and no WAIT logic;
  - a per-slot SEL line, decoded on the backplane from A31–A28, like the
    Apple II's per-slot select lines;
  - read and write strobes from every master, with a whole clock of
    address and data setup and hold;
  - wait states from a **per-slot wait-state table** in every master,
    loaded at boot (16 entries, ~3 chips per master).

  A UART card is a 16C550, a 74HCT245 and a 74HCT14, all 74HCT.
- **Other CPUs as masters**: a Z80, a 68000 or 68020, or the cruncher.
  **recommended** as the pattern, with details in
  [system-bus.md, section 11](system-bus.md#11-other-cpus-as-masters).
  - A small bridge on the CPU's card holds the CPU (Z80 WAIT, 68000 DTACK),
    synchronises the request to the bus clock and runs an ordinary
    transfer.
  - About 4–6 bus clocks per access and 15–20 chips.
  - The 68000's BERR and the 68020's dynamic bus sizing map directly onto
    the bus's BERR and W32. Its big-endian byte order needs a swap option.
- **A separate I/O bus** for simple peripherals behind a bridge card: **open**,
  as the fallback if simple cards multiply, need odd timing (6800-style E
  clock, Z80 peripherals) or load the bus too much
  ([system-bus.md, section 12](system-bus.md#12-alternative-a-separate-io-bus)).
- **Arbitration:** **recommended.**
  - A central round-robin arbiter on the backplane, with per-slot REQ and
    GNT. No CPU owns the bus.
  - The bus parks on the last master while nobody else asks.
  - BUSY gives a clean handover: about one clock.
  - LOCK is optional, for locked read-modify-write. It's on P1, so 16-bit
    masters (the draft 1b CPU, a 68000) can use it.
- **Geographic slot regions** (NuBus style). **recommended.**
  - The bus address is 32 bits. A31–A28 select one of 16 slots, 256 MB
    each. **decided** (the full 32 bits).
  - The backplane decodes them into each slot's SEL line, so no card needs
    a comparator.
  - On the draft 1b CPU, MAR bit 31 set means "system bus". MAR bits 30–27
    give the slot and bits 26–0 the address within it, so it reaches the
    first 128 MB of every slot with plain wiring.
  - Replaces the 16 × 16-byte I/O slots ([section 6](#6-io)).
- **Bus errors from the backplane.** **recommended.**
  - Every card grounds a PRESENT pin.
  - A bus monitor on the backplane asserts BERR for a transfer to an empty
    slot, or one longer than 256 clocks. On the draft 1b CPU that's a trap
    next to address error.
  - A claim line driven by the slaves was considered and dropped: simple
    cards could only release it, and a pull-up restores it too slowly.
- **A master port and a slave port on every CPU board.** Other CPUs and DMA
  reach a CPU's RAM through its slot region. **recommended.**
  - **Deadlock rule:** a CPU stalled waiting for the bus must let its slave
    port use its local RAM. Otherwise CPU A, holding the bus while waiting
    for B's RAM, and B, holding its RAM while waiting for the bus, wait
    forever.
  - With tick-level RAM sharing (the table above), the main CPU's RAM is a
    reasonable DMA buffer. The cruncher's own RAM, or a fast shared-memory
    card, is still better for bulk data at full burst speed. **open.**
- **Synchronisation in hardware**, independent of either CPU's instruction
  set, since a heterogeneous CPU may lack a locked read-modify-write.
  **recommended.**
  - Semaphore registers that return their old value and set themselves in
    one bus read (test-and-set on read). Sixteen of them is a couple of
    chips.
  - Doorbells: a write to a register in a CPU board's region interrupts
    that CPU.
  - A per-CPU control register for reset/run and NMI. The main CPU boots
    the other by loading code into its RAM and releasing its reset.
- **Interrupts:** eight shared open-collector lines (four on P1, four on
  P2). Each device picks a line with a jumper, and each CPU listens to its
  own subset through its priority encoder. Doorbells cover CPU-to-CPU
  signalling. **recommended.**
- **Electrical**, from the simulations. **recommended.**
  - **Backplane:** 4 layers, 0.2 mm traces (67.5 Ω bare; about 26 Ω loaded
    with 16 cards).
  - **Active parts on the backplane:** the clock buffer, slot decoder,
    arbiter, bus monitor and power-on reset, about 6–8 chips. A
    system-controller card in slot 0 instead: **open.**
  - **No resistor terminators on bused lines.**
    - 74HCT can't pull a line low against them: 0.66–1.19 V, against the
      0.8 V threshold.
    - They'd burn 8–12 W.
    - ABT and ACT falling edges ring back above 0.8 V for about 30 ns.
  - **22 Ω in series at every bus driver**, or built-in series resistors
    (74ABT2245).
    - With ABT, the peak drops from 6.0 to 4.4 V and the dip below ground
      from −0.9 to −0.45 V.
    - About 9–11 ns of settling at 16 slots, half that at 8.
  - **Bus drivers:** 74ABT or 74FCT-T on synchronous cards. 74ACT isn't
    recommended (7 V overshoot, −1.4 V undershoot). 74HCT only on simple
    slaves.
  - **RD, WR and RESET:** also 33 Ω + 220 pF at both backplane ends, for
    monotonic edges, at the cost of 20–30 ns slower edges. Schmitt-trigger
    receivers on simple slaves.
  - **The bus clock:** radial from an ABT buffer on the backplane, through
    56–68 Ω series resistors. Clean at every slot in every simulated case;
    0.8 ns skew without length matching.
  - **Ground pins on both sides of BCLK, RD, WR and RESET** in the
    connector. Two switching neighbours put 1–2 V spikes on a quiet line
    through the contacts. That's harmless on lines sampled at a clock edge.
  - WAIT, BUSY, BERR and W32 are actively driven both ways and held by a
    weak pull-up when idle, as in PCI. Interrupt lines stay open-collector.
  - **Ground bounce: not known yet.** The simulation model needs fixing.
    Until then, decouple every bus chip and prefer SOIC or flow-through
    parts for wide drivers.
- **CPU board partitioning:** at least two boards. Where to split, and DIP
  or SOIC, are **open**. The internal buses (A, B, F, RES) and the 120
  control lines are what make the split hard.

## 6. I/O

- **Memory-mapped I/O page** at the top of memory. **adopted.**
  - In draft 1 it's at `0xFFFFFF00`, reachable with a sign-extended 16-bit
    absolute address.
  - A side effect of load/store: no accidental read-modify-write of device
    registers.
- **16 slots of 16 bytes**, one 74HCT154 on address bits 7–4. Each slot
  gets a select line, a shared IRQ and reset (Apple II / RC2014 style).
  **rejected** in favour of geographic slot regions on the system bus
  ([section 5](#5-memory-system-and-buses)). The device list below is
  still the plan for what the system needs.

  | Slot | Device |
  |---|---|
  | 0 | console UART (16C550) |
  | 1 | CF card (8-bit IDE) |
  | 2 | RTC (DS12887) |
  | 3–13 | free |
  | 14 | MMU registers |
  | 15 | system: timer, interrupt controller, front panel, boot-ROM disable |

- **Interrupts:** one level-triggered IRQ plus polling to start. Later,
  PDP-11-style vectored priorities: a 74HCT148 encoder, a priority field in
  the flags compared against the request level, and a 74HCT541 putting the
  vector on the bus (~3–4 chips). That gives nesting. **open**; reserve the
  priority field in the flags now.
- **Read strobes gated with a clock phase**, like writes. **recommended.**
  One gate. Otherwise a decode glitch is a phantom read, e.g. a lost UART
  character.
- **Automatic wait states for I/O** by stretching the clock, decoded early
  from MAR. **recommended.** On the system bus this becomes the masters'
  per-slot wait-state tables ([section 5](#5-memory-system-and-buses)). Every device gets ~2 µs; I/O is rare, so the
  cost is invisible. A per-device READY line is the more fiddly
  alternative. With variable-length cycles
  ([section 4](#4-microarchitecture)) this comes for free, and the system
  bus adds WAIT.
- **8-bit peripherals on the low byte lane**, one register per even
  address. **adopted.**
- **74HCT245 transceivers** between the CPU board and a backplane (~20 ns):
  **rejected** for the CPU board. 74HCT is too slow for a one-clock bus path
  and is only for simple slaves. The CPU board uses registered 74ABT
  transceivers (74ABT652), which also give posted writes
  ([section 5](#5-memory-system-and-buses)).
- **Front panel:**
  - **Through the microcode** (PDP-8 style): the switch register is a B-bus
    source, and a panel-mode bit on a spare microcode address line selects
    LOAD ADDRESS / DEPOSIT / EXAMINE sequences. Single-stepping instructions
    or micro-cycles falls out. **recommended.**
  - **As a bus master:** shares the bus-release mechanism. **open.**
- **Storage:** a CompactFlash card in 8-bit IDE mode (~300 KB/s by polled
  I/O). **open.** File system: FAT (swap cards with a PC) or a small
  Unix-style one plus a host tool to build images.
- **Console:** a serial terminal first (a VT100 or an emulator), with a
  16C550 UART with FIFO. **recommended.** At 9600 baud, character-by-
  character interrupts cost ~5% of the CPU per busy terminal.
- **Keyboard:** PS/2, a shift register, bit counter and interrupt (~4
  chips). **open.**

## 7. Channels and DMA

Background: a CF sector by software loop is ~12–15 cycles per word, ~3,500
cycles per 512-byte sector. Terminals cost ~5% of the CPU each.

| Option | Cost | CPU cost per word | Status |
|---|---|---:|---|
| Block I/O instruction in microcode | microcode | ~5–6 cycles | **open**, a good first step |
| **Microcoded channel** (like the integrated channels of the small System/360s): a device request runs a microcode sequence between instructions; address, count and command live in spare register-file SRAM | ~5 chips | ~5–7 cycles | **recommended first** for a timesharing system |
| **Cycle-stealing DMA**, optionally following descriptor chains ("channel lite") | ~15–20 chips per channel, plus bus release | ~1 stolen cycle | **recommended** once the OS swaps or multitasks for real: disk first, then terminal output (DH11-style output DMA) |
| DMA in its own memory time slot | memory-timing redesign | 0 | **open**; the recommended tick-level RAM sharing ([section 5](#5-memory-system-and-buses)) gets most of the way: DMA into the CPU's RAM at near bus speed, rarely delaying the CPU |
| Intelligent terminal multiplexer: 4–8 lines with buffers, one interrupt per line or buffer | a lot in TTL; one chip with a microcontroller | turns ~1000 interrupts/s per terminal into ~10 | **open**: is a microcontroller in a peripheral OK? 1980s minis did it |
| CDC 6600-style peripheral processor "barrel": one shared datapath, 8 virtual I/O processors with registers in SRAM | ~60–100 chips | – | **open**, a project of its own |
| 82C37 off-the-shelf DMA chip | 1 chip | – | **rejected**: 8-bit, 8085-style timing |

**Software side:**
- "Start channel" is a store to a command register; no new instructions.
- I/O becomes asynchronous: request queues, completion interrupts.
- DMA uses physical addresses, so buffers must be pinned and contiguous.

## 8. Video

**First question: what's the screen for?** A console (~30 chips) or
graphics (address space and drawing speed bite). Minicomputers mostly used
serial terminals; built-in video is home-computer territory. **open.**

**Text-mode VGA card** (~30 chips). **open**; recommended after the serial
terminal.
- 80×30 characters, 8×16 font, 640×480 at 60 Hz (25.175 MHz pixel clock,
  3.15 MHz character clock).
- Character plus attribute per 16-bit word, 16 foreground/background
  colours, 2-bit-per-channel resistor DAC.
- A 128-word row stride, so the address comes straight off the counters.
- Hardware scroll (a start-row register through two 74HCT283) and cursor
  (two 74HCT688 plus blink).
- Redefinable font in SRAM; posted writes so the CPU never waits.
- A 6845 CRTC could replace the timing and addressing (less authentic).

**Where screen memory lives:**

| Option | Notes |
|---|---|
| Video RAM in a window of the CPU's address space | best for text |
| Behind I/O ports with an auto-incrementing address (TMS9918 style) | best for bitmaps; zero address space |
| Dual-port SRAM | expensive |
| Main memory, interleaved | needs the memory redesign |
| Physical pages mapped by the MMU | the clean long-term answer |

**Graphics options:** **open.**
1. A bitmap plus a blitter on the card that fills and copies rectangles:
   a screen clear drops from ~65 ms to ~1 ms.
2. **Display lists** (below).
3. A vector display on an oscilloscope (two DACs, a line walker; GT40 and
   Spacewar style).

Avoid software-generated video (ZX81, Gigatron): it would eat a microcoded
CPU. **rejected.**

**Display-list processor** (ANTIC bands plus copper-style register writes;
the DEC GT40 was the minicomputer precedent). **open**, 40–60 chips (~35
minimal).
- **Instruction set**, nibble-aligned:

  | Word | Instruction |
  |---|---|
  | `1 m nn` | BAND mode `m` for `nn+1` units |
  | `2 m nn` + addr | BAND with a new data pointer |
  | `3 r vv` | PALETTE |
  | `4 r 00` + value | SET control register |
  | `5 0 nn` | BLANK |
  | `6 0 00` | IRQ |
  | `8 0 00` + addr | JMP |
  | `9 0 00` + addr | JVB (jump and wait for vertical blank) |

- **Modes:** 80- and 40-column text; 640-wide bitmaps at 1 and 2 bits per
  pixel; 320-wide at 4 bits per pixel. Bit 3 of the mode doubles lines.
- **Hardware:**
  - 64K×16 of video RAM on the card;
  - four fixed ~80 ns slots per character time (display data, font, CPU,
    display-list processor);
  - an EEPROM-sequenced processor running in horizontal blank (~20 memory
    slots per line);
  - a stride counter for virtual screens;
  - a 25 MHz pixel pipeline in 74AC/F with a 16-entry palette and fine
    scroll;
  - CPU access through a window or a data port; vertical-blank and
    display-list interrupts.
- **What it gives software:** scrolling by one store, split screens,
  tear-free double buffering, raster effects. A `FILL`/`COPY` blitter
  instruction could come later.
- **Vector variant:** `MOVETO`/`LINETO`/`POINT`/`TEXT` with a
  Bresenham-style engine and X/Y DACs.
- **Prototype first:** a Python model of the card in the simulator that
  renders PNGs.

## 9. Networking

Ethernet, for the main CPU and its OS: a fast link to a PC for development
first, TCP/IP later.

- **10 Mbit/s.** **recommended.**
  - 10BASE-T carries 1.25 MB/s. A word-copy loop on the draft 1b hardware
    moves about 1 MB/s at 3 MHz (~12 cycles per 32-bit word), so the CPU can
    roughly keep up. At 100 Mbit/s the link would mostly wait for the CPU.
  - It's a small fraction of a 16-bit system bus, so the card needs nothing
    special from the bus.
  - 100 Mbit/s would only pay for moving bulk data to and from a fast
    coprocessor, and then only with DMA.
- **Full duplex only.** **recommended.** Connected to a switch, the PHY
  negotiates full duplex, so there are no collisions: no carrier sense,
  collision detection or backoff. Those were the hardest part of a 1980s
  Ethernet controller.
- **No hardware address filter.** **recommended.** A switch only forwards
  this machine's frames and broadcasts, so software can drop the rest.

**Controller options:**

| Option | Chips | Notes | Status |
|---|---:|---|---|
| **TTL MAC with a PHY chip** | ~40–60 | Design below | **recommended** |
| WIZnet W5100 | ~2 | 8-bit parallel bus, 16 KB buffers; hardware TCP/IP or a raw-frame mode; still made | **open**, as a quick bring-up path |
| Realtek RTL8019AS (NE2000-compatible) | ~3 | 5 V, 8/16-bit ISA-style bus, 16 KB buffer, 10 Mbit/s only; obsolete but easy to find and documented everywhere | **open** |
| 16-bit 10/100 controllers (Davicom DM9000-class, Microchip LAN9221) | ~4 | 3.3 V; 5 V tolerance needs checking, may need level shifters | **open** |

**The TTL MAC:**

- **The PHY chip** does the analog side: line drivers and receivers, and
  Manchester or 4B/5B coding. The isolation transformer comes built into
  the RJ45 jack. 1980s boards used a serial-interface chip for the same job.
  The PHY's MII interface at 10 Mbit/s is 4 bits at 2.5 MHz each way,
  clocked by the PHY: slow enough for 74HCT.
- **Levels.** The PHY runs at 3.3 V. Its outputs drive 74HCT inputs directly
  (TTL thresholds); signals into it go through a 74LVC buffer.
- **Receive:** find the preamble and the start-of-frame nibble, assemble
  nibbles into 16-bit words, write them into the packet buffer, check the
  CRC-32 four bits at a time, and post each frame's length and status to a
  ring of receive descriptors.
- **Transmit:** read a frame from the buffer, send the preamble and
  start-of-frame, then the data, then the CRC.
- **Packet buffer:** a 32K × 16 SRAM on the card, holding a ring for
  received frames and space for frames to send. The CPU reaches it through
  a window in the card's address space.
- **CRC-32 by nibble:** a 32-bit register and an XOR network (or a 16-entry
  table), ~8–12 chips.
- **Interrupts** for frame received and frame sent.
- **Later: DMA** straight into main memory as a bus master, following
  descriptor rings like AMD's LANCE did (see [section 7](#7-channels-and-dma)).
  It would be the first real test of bus mastering. **open.**
- **Simulate first:** the MAC as a netlist in the chip-level simulator, with
  a PHY fixture that plays recorded frames (pcap files) in and captures what
  it sends.

**Software:**

- **Raw frames to a PC-side tool first:** loading programs in a fraction of
  a second instead of over serial, a remote console, network boot.
  **recommended.** That's a reason to build Ethernet early: it speeds up
  all the development after it.
- **CPU cost:** at ~1 MB/s, copying a full-size frame takes ~1.5 ms. A block
  I/O instruction (~5–6 cycles per word, [section 7](#7-channels-and-dma))
  roughly halves that; DMA removes it.
- **TCP/IP** (a uIP- or lwIP-sized stack) once there's a C compiler and an
  OS. **open.** Telnet into a timesharing system would give the OS ladder
  in [section 1](#1-direction-and-ambition) a concrete goal.

## 10. Operating system support

- **Privilege mode bit** in the status word, saved by interrupt entry and
  `RTI`. **recommended.**
  - User mode traps `EI`/`DI`/`HALT`/`MTSR`/`RTI`, map writes and I/O.
  - `RTI`/`MTF` in user mode must not be able to set the kernel bit.
  - The microcode can use a spare address line for the mode.
- **Separate kernel stack / banked registers** via the register-file SRAM
  address lines. **recommended.**
  - The mode bit on an address line gives the kernel its own registers.
  - A process-number register gives every process its own registers.
  - Catch: the kernel can't see the user's argument registers, so it needs
    "move from user register" (PDP-11 `MFPI`-like).
  - Catch: `r0` must be forced to zero in logic, not by the reset sequence.
- **Restartable instructions:** every instruction commits nothing before its
  last memory access. **adopted** in draft 1's rules; see the audit in
  [section 11](#11-mmu). (The 68000 couldn't restart after bus errors, and
  the 68010 had to fix it.)
- **Relocation:** position-independent code (PC-relative addressing), or a
  relocating loader with assembler relocation tables, or an MMU. **adopted**
  (PC-relative modes in draft 1).
- **System calls:** `SWI #n` with its own vector. **adopted.** Return errors
  in the carry flag by editing the saved flags word (the PDP-11 Unix
  trick). **open.**
- **Trace bit** (trap after every instruction) plus `SWI` as a breakpoint
  gives a real debugger. **recommended.**
- **Boot:** a boot ROM overlaid on low memory at reset, switched out by an
  I/O write. Or toggle in a loader from the front panel. **open.**
- **Reference numbers (draft 0):**
  - interrupt latency ~7 µs at 2 MHz;
  - context switch ~170 cycles (~30 with banked registers);
  - system-call round trip ~40 cycles plus the work.

## 11. MMU

What the OS needs: separate address spaces, protection (user/kernel, read
only, no execute), restartable faults (demand paging, copy-on-write `fork`,
growing stacks), and sharing.

**Options considered:**

| Design | Gives | Cost | Status |
|---|---|---|---|
| Base/limit registers | relocation and protection, one block per process | ~6 chips (an adder in the address path) | **open** |
| Protection regions (ARM MPU style) | protection only; needs position-independent code | ~4 chips per boundary | **open** |
| Segments (PDP-11 style, 8 per space) | a few variable pieces | ~15 chips | **open** |
| **Flat page map in SRAM** | paging, no flushes | ~12–15 chips | **recommended** |
| Two-level map (Sun-2 style) | sparse, larger spaces | ~20 chips, two lookups in series | **open** |
| Tagged translation cache plus page-table walk in microcode (as the VAX did) | full 32-bit spaces | ~20 chips plus microcode | **open**, upgrade path |
| Address registers as the translation cache | see [section 12](#12-address-registers-with-hidden-state) | ~10–14 chips | **open** |

**The flat page map proposal:**
- **Shape:**
  - 16 MB virtual per process in 4 KB pages (4096 pages);
  - 16 contexts in the map SRAM (64K entries);
  - entry = 12-bit physical page plus V/W/X bits (24 bits);
  - up to 16 MB physical;
  - a context switch is one register write.
- **Address path:** MAR → map SRAM → RAM. A 55 ns DIP SRAM adds 55 ns,
  which fits a cycle of 300 ns or more. Instruction fetches are translated
  too.
- **Hardware:** 3 × 128K×8 SRAM, a context register, a path for writing
  entries, check gates, a fault-address latch and a fault-reason register.
- **Referenced and dirty bits in software:** map pages read-only; the first
  write faults. The same mechanism gives copy-on-write.
- **Supervisor mode is untranslated.** The kernel uses `LDU`/`STU` (loads
  and stores through the user map, like the 68010's `MOVES`) for copying to
  and from user memory.
- **More than 16 processes:** reassign contexts (rewriting 4096 entries
  takes a few ms).

**Draft 0-era variant:** 16 pages of 4 KB covering the 64 KB space, an SRAM
indexed by process number, 1 MB physical (2 × 512K×8), ~4–6 chips, about 5%
slower clock.

**Restartability audit (draft 1):**
- Single-access instructions update registers after the access, including
  auto-increment.
- `CALL` and `JMP/CALL [mem]` read the target and push before changing the
  PC or `sp`.
- `SAVE` writes first and moves `sp` last; re-running it is idempotent.
- `RESTORE` re-runs idempotently (`sp` is never in the range).
- Prefetch faults are held back until the parcel is used.
- Interrupt entry pushes onto the kernel stack, so it never faults.
- Block moves must keep their progress in registers.
- On a fault the microcode: stops the write, latches the address and reason,
  saves the PC of the faulting instruction, and traps.

**ISA additions:**
- user/supervisor bit; a separate supervisor `sp`;
- privileged instructions;
- special registers: context, map address/data, fault address, fault
  reason;
- vectors: page fault, privilege violation;
- I/O from supervisor mode only.

**Staging:**
1. A socket for the map chips plus a bypass jumper on the first boards.
2. The flat map.
3. Tags plus a microcode walker, if ever.

## 12. Address registers with hidden state

Proposed by Emily: split the registers into D and A registers like the
68000, and give the A registers extra hidden state that caches MMU lookups
and serves as protection. **open.**

**Precedents:**
- the 286/386 segment registers' hidden descriptor cache (the closest);
- 68000 address registers;
- the CDC 6600's A registers with side effects;
- the Cambridge CAP computer and CHERI capability registers.

**The D/A split:**
- **Only A registers address memory,** so every access names one. Pointer
  operations (`LEA`, `ADDA`, auto-increment, A-to-A moves) keep or update
  the hidden state. Loading an A register from memory or from a D register
  invalidates it.
- **Pointer arithmetic doesn't set flags** (fixes 1a's "`ADDI` sets Z").
- **A separate address adder** runs alongside the data ALU (68000 style),
  so auto-increment and `[A + d]` are free.
- **`sp` and `PC` are A registers:** cached stack page, and cached code page
  (instruction-fetch translation for free).
- **Register budget** (from the 20 draft 1a programs):
  - Pointer registers: seven programs use up to 7, but rarely more than 3–5
    in one loop.
  - Data registers are the pinch: sha256 needs 9–12, mandel 8.
  - So A registers need some arithmetic (`ADDA`/`SUBA`/`CMPA`/`MOVEA`), and
    indexed addressing should take a D register as the index
    (`[A2 + D3*4]`).

**Flavour 1: the A registers are the translation cache.**
- **Hidden state per A register:** physical page, R/W/X, valid. About 24
  bits in ~3 extra SRAMs beside the register file.
- **Accesses:** the physical address is the cached physical page plus the
  low 12 bits, with no lookup in the memory path.
- **Misses:** microcode walks a two-level page table in RAM (~10 cycles).
- **After pointer arithmetic,** a page-crossing detector compares bits
  31..12 and invalidates on change. It's the D16 page-crossing logic at
  4 KB.
- **What it gives:** full 32-bit sparse address spaces, page tables in RAM,
  any number of processes, a context switch = load registers plus page-table
  base. ~10–14 chips.
- **Weak spot: pointer chasing.** Each newly loaded pointer costs a walk,
  roughly +40% on bst-like code. Fix: a small shared direct-mapped
  translation cache behind the A registers (~8–10 chips).
- **Loose ends:**
  - `[A + large d]` landing in another page: a one-off lookup;
  - globals through a "global pointer" A register;
  - when the kernel changes a page table it must invalidate the current
    registers' hidden state.
- **My pick**, with hidden state sized so flavour 2 can be added later.

**Flavour 2: the A registers are segment registers (per-object bounds).**
- **Pointers** are (segment, offset), e.g. 12 + 20 bits. Loading an A
  register fetches the segment's descriptor (base, limit, rights) from a
  per-process table. Accesses add the base and check the limit.
- **What it gives:**
  - every allocation can be its own segment, so overruns trap at once
    (memory safety for C-like code);
  - free relocation and compaction, since pointers are segment-relative
    (Burroughs);
  - sharing through descriptors.
- **Costs:**
  - a descriptor load per pointer loaded (~20 cycles on the 286);
    a descriptor cache fixes it;
  - a base adder in the address path (~6 chips, ~40 ns) and a limit
    comparator (~3 chips);
  - wider hidden state (~6 bytes);
  - 4096 segments per process;
  - contiguous segments, so compaction.
- ~20–25 chips. It catches accidents, not malice: a program can still build
  any segment number in a D register, but only within its own table.

**Flavour 3: unforgeable capabilities** (CHERI): tagged memory and 128-bit
pointers. **rejected** as too heavy for TTL.

**Measuring it needs bigger workloads.** The current programs fit in a few
pages and would show near-perfect hit rates.

## 13. Big ideas

From "what would you like in an ISA". All **open**.

**Nearly free on this machine:**
- **Register windows in the register-file SRAM** (Berkeley RISC, SPARC,
  AMD 29000's register stack).
  - A frame counter on spare address lines banks r8–r14 per call: `CALL`
    steps it up, `RET` down. Saving and restoring disappears (23% of
    queens' cycles).
  - An overflow trap spills old frames after 256 or 2048.
  - The counter's top bits can be a process number, for cheap context
    switches.
  - ~3–4 chips.
- **Banked registers for interrupts** (ARM FIQ, Z80 alternate registers,
  8051 banks): the handler saves nothing. ~1 mux input.
- **Packed byte arithmetic** by carry gating ([2.4](#24-more-instruction-ideas-not-yet-decided)).
- **Debugging:**
  - trace bit (microcode);
  - hardware breakpoint register compared against the PC (~8 chips);
  - **branch trace buffer**: a counter and a small SRAM recording every
    taken-branch target, so after a crash you can see how it got there
    (~6–8 chips).

**Big swings:**
- **Writable control store, user-defined instructions** (Xerox Alto's
  microcoded BitBLT; optional on the VAX-11/780 and PDP-11/60).
  - Part of the microcode becomes RAM, and 1a's op F becomes "user
    opcodes".
  - Uses: a Forth inner interpreter or the VM's dispatch in microcode, a
    blitter instruction, emulating another CPU.
  - ~10–12 chips. Microcode bugs are brutal to debug.
  - Turns every "should we add instruction X?" into an experiment.
- **Run a bytecode directly** as a second native instruction set: the
  Pascal MicroEngine ran UCSD p-code, Lisp machines ran Lisp. Boot into a
  Forth or BASIC machine.
- **Tagged memory** (Burroughs B5000, Lisp machines): 2–4 tag bits per word
  for type checks and garbage collection. Wider memory (34–36 bits) and tag
  checks in the ALU path; a whole-system decision.
- **Bounded pointers:** full CHERI is too big; base/limit checks per access
  are the light version ([section 12](#12-address-registers-with-hidden-state),
  flavour 2).
- **Hardware time-travel debugging:** every store also logs the old value
  and address into a ring-buffer SRAM, so a debugger can step backwards.
  A read-modify-write per store plus ~10 chips; with the branch trace
  buffer, the last few thousand instructions can be replayed.
- **A stack-machine alternative** (RTX2000, Transputer): 8-bit instructions,
  dense code, cheap calls. Registers were never short in our programs, so
  not as the main ISA; possible via a writable control store.

**My personal wishlist, in order:**
1. register windows;
2. a writable control store with user opcodes;
3. the idiom killers (auto-increment, table jump, non-destructive shifts,
   memory increment, multiply-accumulate);
4. precise restartable traps plus the debug trio;
5. packed byte add.

## 14. Wishes from the program writers

From [notes-v1/](notes-v1/), not covered above:

| Wish | ISA | Notes |
|---|---|---|
| One-parcel 8-bit constants | 1b | Character constants cost 2 parcels; no room in the `F D M R` encoding |
| Byte and half auto-decrement, half auto-increment | 1b | Backwards loops (`memmove`, `reverse`) |
| Indexed mode with more than 8 bits of displacement | 1b | A table base needs its own register |
| `[label + reg]` for labels beyond ±32 KB | both | 1b has no 32-bit displacement form |
| One-parcel `[r + small offset]` | 1b | Struct fields cost an extension parcel |
| Immediate `TST`/`BIC`/`MUL`/`DIV` | 1b | Constants needed registers |
| `POP` that leaves the flags alone | 1b | `MOV [sp]+` sets N and Z |
| Longer reach for the short byte offsets | 1a | 0–15 is too short for a 34-byte Life row |
| `MOV`/`MVI` that don't set flags, or an explicit flag-setting bit (ARM's S bit) | both | A constant can't be loaded between a compare and its branch |
| V updated (or defined) by `INC`/`DEC`/`TST` | both | Signed branches after them test a stale V |
| Assembler macros, `.rept` | tools | sha256's rounds |
| Library constants not polluting the global namespace (`CONSOLE`, `PR_OUT`) | library | Programs couldn't reuse the names |
| `strcmp` setting flags from its result | library | Every call was followed by `TST` |
| Accept `MVI r, 0x80` when only the low byte matters | tools | Had to write −128 |

Tooling items already done in this round: per-kind and per-routine cycles in
`run --stats`; raw-byte output from `tmc run`.

## 15. Open questions

Questions raised along the way that only Emily can answer:

1. What's the fun part: using the finished machine (OS, compiler,
   software), the hardware engineering itself, or period authenticity?
2. Build budget, roughly in chips or months (100, 200 and 400 chips are
   different projects)?
3. OS goal: Unix-like (processes, files, a shell), or period-flavoured (a
   BASIC timesharing system, a Forth machine)? Is multi-user protection
   needed, or is unprotected multitasking enough?
4. Console: a serial terminal, or should the machine drive its own screen?
   If graphics: raster or vector?
5. How many simultaneous terminals? Is a microcontroller inside a
   peripheral acceptable?
6. Design cards for a bus clock of ÷ 3 (16.7 MHz, recommended) or ÷ 4
   (12.5 MHz)? The CPU board's jumper allows both.
7. What does the ECL number cruncher need from the bus: 32-bit transfers,
   bursts, LOCK? Does the backplane carry its −5.2 V supply?
8. How to split the CPU over two or more boards, and DIP or SOIC?
9. Simple peripherals on the system bus (recommended) or on a separate I/O
   bus behind a bridge?
10. Active parts on the backplane (clock buffer, slot decoder, arbiter, bus
    monitor), or a system-controller card in slot 0?

Answered so far:
- 32-bit architecture with a narrow implementation first: yes.
- 16-bit instruction parcels: yes.
- Compare RISC-like and CISC-like encodings: done.
- PCBs: 4-layer.
- A backplane with slots: yes, with two connectors per slot, P1 enough for
  simple peripherals.
- Variable-length cycles from a 50 MHz master clock: yes, with lengths set
  by jumpers, and the timer counting real time.
- A second CPU: an ECL number cruncher, designed separately.
- Ethernet: yes, preferably with a TTL MAC.
- The system bus is synchronous. The strobed bus was reconsidered after the
  signal-integrity simulations and stays rejected.
- Simple, dumb peripherals must be possible.
- The master clock stays 50 MHz (20 ns ticks).
- Bursts: an optional feature for now.
- Bus addresses: the full 32 bits.

## 16. Offered next steps

Offered in the discussions, not done yet:

- Simulator models: a CF card, DMA, the microcoded channel, a UART with
  wait states, and the display-list video card rendering PNGs. Then a
  console driver and a demo screen.
- Add user mode, the MMU (flat map or A-register caches), faults and
  `LDU`/`STU` to the draft 1 simulator; a tiny kernel running two programs
  as processes with demand paging from a simulated disk.
- A "draft 2" in the simulator:
  - 1a plus auto-increment and a table jump;
  - register windows;
  - user opcodes with estimated microcode costs;
  - the D/A split with per-register translation caches and walk counters,
    on bigger workloads.
- The pin-by-pin assignment of P1 and P2, following the rules in
  [system-bus.md](system-bus.md), and timing diagrams for its transfers.
- A write-up of the bus signal-integrity results (`docs/bus-si.md`) from
  the sweep data in [bus-si/](bus-si/). Before that:
  - fix the ground-bounce model;
  - speed up the crosstalk model;
  - rerun the 68 jobs that failed.
- Variable-length cycles in the draft 1b netlist: the length field, the
  clock generator in the Go simulator, timing analysis against each
  microinstruction's own length, and lengths assigned from the analysis.
- A chip-level model of the TTL Ethernet MAC with a PHY fixture that replays
  pcap captures, plus a raw-frame program loader on the PC side.
- A 32-bit netlist estimate through the timing analysis, replacing the ±20%
  chip and clock guesses.
