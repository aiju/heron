---
number: 5
type: rfc
title: Direction, big ideas and open questions
status: open
date: 2026-10-14
context:
  studies: [v1_isa, v1b_hw, c_compiler, lisp, egret, graphics, kernel, bus_si]
  commit: 2f81658
---

# RFC 0005: Direction, big ideas and open questions

An ideas RFC: a scratchpad of ideas about the whole machine, each with
its own status ([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)).
The other ideas RFCs are by area:

| RFC | Area |
|---|---|
| [0006](0006-rfc-ideas-isa.md) | The instruction set, and the base for draft 2 |
| [0007](0007-rfc-ideas-microarchitecture.md) | The CPU's implementation and clocking |
| [0008](0008-rfc-ideas-memory-and-buses.md) | Memory, and pointers into the system bus ([RFC 0014](0014-rfc-system-bus.md)) |
| [0009](0009-rfc-ideas-io.md) | I/O, DMA, video ([RFC 0016](0016-rfc-video.md)) and networking |
| [0010](0010-rfc-ideas-os.md) | The operating system and the MMU |

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | It has numbers behind it |
| **recommended** | Suggested for draft 2 or the next hardware |
| **decided** | Emily chose it; not built yet |
| **open** | Discussed, not decided |
| **not recommended** | The evidence is against it; Emily hasn't decided |
| **rejected** | Decided against, with the reason, so it isn't proposed again without new evidence |

Chip counts are rough estimates unless they come from a netlist.

## 1. Direction and ambition

- **A whole computer, not raw CPU speed.** The fun part is building a
  whole machine; period authenticity is held lightly (Emily, 2026-10-15).
  - Designing big is cheap now (netlist language, simulators, timing
    analysis). Building big isn't: wiring, signal integrity, parts.
  - Software is cheap too, with Claude writing most of it: since draft 1
    the studies have built a C compiler, a Lisp and an object language
    that compile on the machine, graphics and a window manager, and a
    kernel.
  - Three directions:
    1. A whole computer: OS, compiler, storage, terminals, front panel.
       Biggest payoff. Bill Buzbee's Magic-1 (~200 TTL chips, runs Minix)
       is the calibration point.
    2. Bigger: 32-bit (below).
    3. Faster: pipelining and caches. Lowest payoff per effort.
- **The operating system has protection** (Emily, 2026-10-15); what kind
  of system it is is still open. [Report 0020](0020-report-operating-system.md)
  proposes one, and stages it from a monitor to protection
  ([RFC 0010](0010-rfc-ideas-os.md#1-the-operating-system)).
- **A 32-bit architecture** (VAX-11/780, Eclipse MV/8000). **adopted**
  (draft 1).
  - A 32-bit address space removes the workarounds for 64 KB: banking,
    video windows, I/D spaces.
  - It gives encoding room and suits C and existing software.
  - The draft 1b hardware has a 32-bit datapath and a 16-bit memory bus:
    213 chips against draft 0's 98, about twice as fast
    ([report 0012](0012-report-draft-1b-hardware.md)). The system
    extensions of [report 0020](0020-report-operating-system.md#the-hardware-list)
    would add roughly 40 more.
- **Built narrow first** (a 16-bit datapath and bus, as the System/360
  Model 30 and the 68000 did): **rejected** (Emily, 2026-10-15). A 32-bit
  ISA on them is *slower* than draft 0 on ordinary code, and only gains
  on multiply and divide ([report 0004](0004-report-draft-1-evaluation.md)).
- **Draft 2 builds on 1b.** **decided** (Emily, 2026-10-15). The 1a
  recommendation of report 0004 is withdrawn
  ([RFC 0006](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
- **Keep 16-bit instruction parcels with 0–2 extension parcels**
  (precedents: SuperH, 68000, Thumb). **adopted.**
  - Alternatives for 32-bit constants, both **rejected**: literal pools
    (SuperH; awkward pool placement) and a prefix instruction (the
    Transputer's `pfix`; hidden state, interrupt shadow).
  - Fixed 32-bit instructions would suit a future pipelined full-width
    implementation better. **rejected** for now.
- **Software in simulation first,** ahead of hardware. Under way:
  - the engines in Rust with Python bindings
    ([RFC 0015](0015-rfc-languages.md), accepted);
  - object files and a linker, and a C compiler for 1a and 1b
    ([report 0011](0011-report-c-compiler.md));
  - a Lisp and Egret, an object language, both compiling on the machine
    ([report 0018](0018-report-lisp.md),
    [report 0017](0017-report-egret.md));
  - graphics and a window manager ([report 0019](0019-report-graphics.md));
  - a message-passing kernel on 1b with system extensions
    ([report 0020](0020-report-operating-system.md)).

  Still **open**: a stable system-call ABI, and a Forth or BASIC, a likely
  program for this machine. A C toolchain running on the machine itself
  would be C, or a small existing C compiler ported to it
  ([RFC 0015](0015-rfc-languages.md#what-doesnt-change)).
- **Build in stages on a backplane of cards** (CPU, memory, then MMU and I/O
  cards). Above ~150 chips, only PCBs or a backplane, no breadboards.
  **decided**: 4-layer PCBs and a backplane with two 96-pin connectors per
  slot ([RFC 0014](0014-rfc-system-bus.md)). The CPU needs at least two
  boards. The card size and how to split the system into cards wait until
  the design is closer to completion (Emily, 2026-10-13).
- **A second, heterogeneous CPU: an ECL number cruncher**, designed
  separately, sharing the system bus and with its own RAM. It had been
  **decided** in principle; now **deprioritised** (Emily, 2026-10-13): it
  may not happen, and the system bus no longer plans around it. The
  backplane won't carry −5.2 V. If it comes back, what the bus needs to
  know from its design:
  - its word size (32 or 64 bits) and how much RAM it has;
  - whether it is a bus master (fetching its own data) or only a slave the
    main CPU feeds.

  It has to compute out of its own RAM, because no hobby backplane can
  stream operands to it. At ~10 MFLOPS on 64-bit numbers, a streaming
  vector operation like `y += a*x` would need ~120 MB/s. Dense work is fine
  over the bus: a 100 × 100 matrix multiply moves 240 KB (~7 ms at the
  bus's 33 MB/s) for ~200 ms of computing. Report 0020 sketches it as a
  file server in the operating system
  ([Plan 9](0020-report-operating-system.md#plan-9-everything-a-file-server)).

## 2. What the measurements point to

The largest effects measured so far, across the studies, and where each
is proposed. All are on the draft 1 timing model: the graphics figures on
D16-overlap, the Lisp's, Egret's and the operating system's on
D32-separate. One is an estimate, and says so.

| Idea | Measured | Proposed in |
|---|---|---|
| A 32-bit bus with a prefetch buffer (D32-wide) | Graphics takes 0.67 of D16-overlap's cycles; the operating system's paths 53–68% of D32-separate's | [RFC 0007, 1](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch) |
| Variable-length cycles | 1.16–1.35× over a fixed clock, on the draft 1b hardware | [RFC 0007, 2](0007-rfc-ideas-microarchitecture.md#2-clocking-variable-length-cycles) (decided) |
| Overlapped fetch | 17–22% fewer cycles than a separate fetch cycle | [RFC 0007, 1](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch) |
| A precise misaligned-access trap, as the Lisp's type check | Checking in software would cost 16% of compiled cycles | [RFC 0006, 6](0006-rfc-ideas-isa.md#6-for-dynamic-languages) |
| Load- and store-multiple through any register | A copied word 9.2 → 5.1 cycles; zeroing a page −41% | [RFC 0006, 5](0006-rfc-ideas-isa.md#5-more-instruction-ideas) |
| Register banks | A call and reply between processes −25%, a preemption −41% | [RFC 0010, 2](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system) |
| Tagged arithmetic that traps | −6.4% of the Lisp's compiled cycles, −5.5% of Egret's JIT runs (16–18% of the numeric ones); 2–3% interpreted | [RFC 0006, 6](0006-rfc-ideas-isa.md#6-for-dynamic-languages) |
| Guard pages | −5.0% and −1.8% of the Lisp's compiled cycles | [RFC 0010, 3](0010-rfc-ideas-os.md#3-mmu) |
| A funnel shift; a barrel shifter | A word of a bit-aligned copy 26.5 → 13.5 cycles; a barrel shifter alone −4.4% over graphics | [RFC 0006, 5](0006-rfc-ideas-isa.md#5-more-instruction-ideas), [RFC 0007, 1](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch) |
| A merge under a mask | −20% of the glyph loop | [RFC 0006, 5](0006-rfc-ideas-isa.md#5-more-instruction-ideas) |
| A vectored `SWI` | A null system call 39 → ~23 cycles (estimated) | [RFC 0010, 2](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system) |
| Devices that buffer, and DMA | An interrupt to a user-level driver costs 500–640 cycles: 17% of the machine for a terminal at 9,600 baud without a FIFO | [RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma) |
| 1b rather than 1a | 3–10% fewer cycles; more for interpreters and copies | [RFC 0006, 2](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2) |
| Direct threading (software) | −11% of Egret's interpreter | [report 0017](0017-report-egret.md#isa-changes-for-the-interpreter) |

Measured and small, about 1% or less: `r0` as a general register, a
class load, a three-operand `XOR`, unaligned 16-bit loads, a link
register, `CHK`, one-parcel pair offsets for the Lisp
([RFC 0006](0006-rfc-ideas-isa.md#6-for-dynamic-languages)). Small isn't
the same as not wanted: the link register is open. Batching
system calls through rings doesn't pay on this machine at all
([RFC 0010](0010-rfc-ideas-os.md#1-the-operating-system)).

## 3. Big ideas

From "what would you like in an ISA". All **open**.

**Nearly free on this machine:**
- **Register windows in the register-file SRAM** (Berkeley RISC, SPARC,
  AMD 29000's register stack).
  - A frame counter on spare address lines banks r8–r14 per call: `CALL`
    steps it up, `RET` down. Saving and restoring disappears (23% of
    queens' cycles).
  - An overflow trap spills old frames after 256 or 2048.
  - ~3–4 chips.
  - The same spare address lines give register banks per thread, which
    the kernel study measured, and per interrupt level, which it proposes
    ([RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)).
    Windows and banks would share them.
- **Packed byte arithmetic** by carry gating
  ([RFC 0006](0006-rfc-ideas-isa.md#5-more-instruction-ideas)).
- **Debugging:**
  - a trace bit ([RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system));
  - a hardware breakpoint register compared against the PC (~8 chips);
  - a **branch trace buffer**: a counter and a small SRAM recording every
    taken-branch target, so after a crash you can see how it got there
    (~6–8 chips).

**Big swings:**
- **Writable control store, user-defined instructions** (Xerox Alto's
  microcoded BitBLT; optional on the VAX-11/780 and PDP-11/60).
  - Part of the microcode becomes RAM, and an escape opcode becomes "user
    opcodes" (1a's op F; in 1b, free values of op B,
    [RFC 0006](0006-rfc-ideas-isa.md#31-room-left-in-1bs-encoding)).
  - Uses: a Forth inner interpreter or a VM's dispatch in microcode (19% of
    Egret's interpreter is dispatch), BitBLT in microcode
    ([RFC 0016](0016-rfc-video.md#73-other-ways-to-get-the-same)), the
    nucleus's call path in microcode
    ([report 0020](0020-report-operating-system.md#further-ideas)),
    emulating another CPU.
  - ~10–12 chips. Microcode bugs are brutal to debug.
  - Turns every "should we add instruction X?" into an experiment.
- **Run a bytecode directly** as a second native instruction set: the
  Pascal MicroEngine ran UCSD p-code, Lisp machines ran Lisp. Boot into a
  Forth or BASIC machine.
- **Tagged memory** (Burroughs B5000, Lisp machines): 2–4 tag bits per word
  for type checks and garbage collection. Wider memory (34–36 bits) and tag
  checks in the ALU path; a whole-system decision. The Lisp and Egret got
  their type checks from tags in a word's low bits instead, with the
  misaligned-access trap and tagged arithmetic
  ([RFC 0006](0006-rfc-ideas-isa.md#6-for-dynamic-languages)).
- **Bounded pointers:** full CHERI is too big; base/limit checks per access
  are the light version ([RFC 0010](0010-rfc-ideas-os.md#4-address-registers-with-hidden-state),
  flavour 2).
- **Hardware time-travel debugging:** every store also logs the old value
  and address into a ring-buffer SRAM, so a debugger can step backwards.
  A read-modify-write per store plus ~10 chips; with the branch trace
  buffer, the last few thousand instructions can be replayed. Report 0020
  suggests the software half: logging a process's messages and
  preemptions makes any run repeatable.
- **A stack-machine alternative** (RTX2000, Transputer): 8-bit instructions,
  dense code, cheap calls. Registers were never short in our programs, so
  not as the main ISA; possible via a writable control store.

**The first discussion's wishlist** (2026-10-12), in order: register
windows; a writable control store with user opcodes; the idiom killers
(auto-increment, table jump, non-destructive shifts, memory increment,
multiply-accumulate); precise restartable traps plus the debug trio;
packed byte add. Since then, 1b has the auto-increment and the table jump,
draft 1 has precise traps, and section 2 ranks the rest by measurement.

## 4. Open questions

Questions that only Emily can answer:

1. **Build budget,** roughly in chips or months (100, 200 and 400 chips
   are different projects)? To be decided. The draft 1b CPU alone is 213
   chips.
2. **The operating system:** it has protection, but what kind of system?
   Report 0020 recommends a message-passing nucleus with file servers and
   per-process name spaces, in the style of Plan 9; a small Unix and a
   single-address-space world are the main alternatives
   ([RFC 0010](0010-rfc-ideas-os.md#1-the-operating-system)).
3. **How many terminals?** Undecided, and probably not more than 4 serial
   ports. It hardly matters for the CPU: with FIFO UARTs, a line running
   flat out at 9,600 baud is an estimated few percent of the machine,
   and a person typing much less
   ([RFC 0009](0009-rfc-ideas-io.md#1-io)).
4. **Bought-in chips:** a RAMDAC for the video card is undecided
   ([RFC 0016](0016-rfc-video.md#5-pixels-and-colour)), and so is a
   single-chip Ethernet controller for bring-up
   ([RFC 0009](0009-rfc-ideas-io.md#4-networking)).
5. **Cards:** the card size, and how the system splits into cards (the
   CPU needs at least two). To be decided, when the design is closer to
   completion.
6. **The system bus's open questions:** the bus clock, the slot bits, a
   slower simple class, arbitration, card IDs, and more
   ([RFC 0014, section 14](0014-rfc-system-bus.md#14-open-questions)).
7. **The video card's open questions,** from what the screen is mainly
   for to sprites and tiles
   ([RFC 0016, section 14](0016-rfc-video.md#14-open-questions)).

**Answered by Emily on 2026-10-15:**

- **The fun part** is building a whole machine. Period authenticity is
  held lightly.
- **Draft 2 builds on 1b**
  ([RFC 0006](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
- **A narrow implementation first** is rejected
  ([section 1](#1-direction-and-ambition)).
- **The operating system has protection.**
- **Console:** both serial terminals and video, at least in the design;
  the first build might not have video.
- **No microcontrollers** inside peripherals.
- **PLDs (PALs, GALs):** a preference against, though not a definite no.
  They make the machine harder to build, they're hard to source, and
  they're less fun. Without them the backplane's logic is about 28 chips
  rather than 13 ([RFC 0014](0014-rfc-system-bus.md#139-the-backplanes-logic)),
  and the video card about a third bigger.
- **Parts:** more open to surface-mount parts, for an SMT build assembled
  by a PCB assembly service ([RFC 0007](0007-rfc-ideas-microarchitecture.md#3-parts)).
- **The master clock:** 50 MHz is recommended, not decided
  ([RFC 0007](0007-rfc-ideas-microarchitecture.md#2-clocking-variable-length-cycles)).

Answered earlier: what's decided is in [docs/README.md](../docs/README.md),
and the bus decisions in
[RFC 0014, section 18](0014-rfc-system-bus.md#18-decisions). Besides
those: RISC-like and CISC-like encodings were compared (draft 1); the ECL
number cruncher is deprioritised; the tools' engines are Rust, with Python
for the rest ([RFC 0015](0015-rfc-languages.md)).

## 5. Next steps

Offered in the discussions and the reports, not done yet:

- **Device models in the simulator:** a CF card, DMA, the microcoded
  channel, a UART with a FIFO and wait states. Then a console driver.
- **The video card in the simulator** as
  [RFC 0016](0016-rfc-video.md#12-simulate-first) proposes: a behavioural
  model rendering PNGs, and a console, a GUI demo and a game demo against
  it.
- **A 1b-based draft 2 in the simulator:** 1b with the measured additions
  (the system extensions of v1bs, a tagged operand like v1bx's, a load-
  and store-multiple, a vectored `SWI`) and the gaps of
  [RFC 0006](0006-rfc-ideas-isa.md#3-for-a-draft-2-built-on-1b) that fit,
  with estimated microcode costs. Register windows and user opcodes as
  variants.
- **The operating system** ([report 0020](0020-report-operating-system.md#next-steps)):
  - the page map and the PC page register in the draft 1b netlist, through
    the timing analysis;
  - the nucleus grown up: C with assembly entry and exit, a loader, 9P
    servers for the console and on the PC, then a shell;
  - demand paging from a simulated disk;
  - the call path and a block move costed in the microcode generator.
- **The D/A split** with per-register translation caches, on report 0020's
  page traces ([RFC 0010](0010-rfc-ideas-os.md#4-address-registers-with-hidden-state)).
- **Variable-length cycles in the draft 1b netlist:** the length field, the
  clock generator in the chip-level simulator, timing analysis against
  each microinstruction's own length, and lengths assigned from the
  analysis.
- **The pin-by-pin assignment of P1 and P2,** following the rules in
  [RFC 0014](0014-rfc-system-bus.md#pin-assignment-rules); report 0022's
  reference assignment is a start. Then timing diagrams for the bus's
  transfers.
- **A chip-level model of the TTL Ethernet MAC** with a PHY fixture that
  replays pcap captures, plus a raw-frame program loader on the PC side.
- **Software:** direct threading for Egret's interpreter; register
  allocation for the Lisp's compiler; the C compiler's next steps
  ([compiler.md](../studies/c_compiler/compiler.md#limitations-and-next-steps)).

Done since they were offered:

- a 32-bit netlist through the timing analysis: the draft 1b hardware
  ([report 0012](0012-report-draft-1b-hardware.md));
- user mode, the page map and faults in the simulator, with a kernel
  running processes and demand-zero pages (v1bs,
  [report 0020](0020-report-operating-system.md));
- the signal-integrity write-up, with the ground-bounce model fixed and
  the failed jobs rerun ([report 0022](0022-report-bus-si-revised.md)).
