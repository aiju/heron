---
number: 5
type: rfc
title: Direction, big ideas and open questions
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw]
  commit: e494b0c
---

# RFC 0005: Direction, big ideas and open questions

An ideas RFC: a scratchpad of ideas for one area, each with its own status
([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). It was split out of
`docs/proposals.md` in the restructure, so the items keep the statuses they
had there:

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | Evaluated with numbers ([report 0001](0001-report-draft-0-evaluation/README.md), [report 0004](0004-report-draft-1-evaluation/README.md)) |
| **recommended** | Suggested for the next draft or hardware round |
| **decided** | Emily chose it for the next hardware round; not built yet |
| **open** | Discussed, not decided |
| **rejected** | Decided against, with the reason, so it doesn't get re-proposed without new evidence |

Chip counts are rough estimates, scaled from the 98-chip draft 0 design.

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
    [section 4](0007-rfc-ideas-microarchitecture.md#4-microarchitecture).
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
  ([section 5](0008-rfc-ideas-memory-and-buses.md#5-memory-system-and-buses)). The CPU needs at least two
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
  [RFC 0014](0014-rfc-system-bus.md).

  It has to compute out of its own RAM, because no hobby backplane can
  stream operands to it. At ~10 MFLOPS on 64-bit numbers, a streaming
  vector operation like `y += a*x` would need ~120 MB/s. Dense work is fine
  over the bus: a 100 × 100 matrix multiply moves 240 KB (~10 ms at
  25 MB/s) for ~200 ms of computing.

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
- **Packed byte arithmetic** by carry gating ([2.4](0006-rfc-ideas-isa.md#24-more-instruction-ideas-not-yet-decided)).
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
  are the light version ([section 12](0010-rfc-ideas-os.md#12-address-registers-with-hidden-state),
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
  [RFC 0014](0014-rfc-system-bus.md), and timing diagrams for its transfers.
- A fuller write-up of the bus signal-integrity results from
  the sweep data in [report 0013](0013-report-bus-si/). Before that:
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
