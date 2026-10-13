---
number: 8
type: rfc
title: Memory system and bus ideas
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw]
  commit: e494b0c
---

# RFC 0008: Memory system and bus ideas

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

## 5. Memory system and buses

| Proposal | Status | Notes |
|---|---|---|
| **Bus release**: request/grant, three-state address and control drivers (74HCT257 instead of 74HCT157, gated read/write strobes) | **recommended**, design in now | Shared by DMA, a front panel acting as bus master, and debugging; cheap now, painful to retrofit. Now part of the system bus below |
| **Main RAM private to each CPU board**, the system bus for everything else | **recommended** | Half of all executed cycles touch memory. Backplane transceivers each way would add ~50–60 ns to those cycles: ~10% slower overall with HCT, ~19% with ACT (with variable-length cycles). Boot ROM and the clock generator stay on the CPU side too |
| **Two memory buses**: CPU-private main RAM plus a shared memory on the system bus for video, display lists, DMA and disk buffers (Amiga chip/fast RAM) | **open** | Superseded as the default by slave ports on the CPU boards (below), which let DMA reach main RAM. A fast shared-memory card stays an option for bulk data |
| **Interleaved memory time slots** (Apple II, BBC Micro): the RAM is ~9× faster than the CPU cycle, so give devices their own slots | **rejected** | Fixed slots don't fit variable-length CPU cycles. Video keeps its own memory on its card instead |
| **Tick-level RAM sharing for the slave port**: other masters use the CPU's RAM in the ticks the CPU doesn't need, with a data latch (2 × 74ACT573) freeing the RAM about 4 ticks into each memory cycle | **recommended** | Works with variable-length cycles because everything runs from one 50 MHz clock and the pipelined microcode says a cycle ahead when the CPU needs the RAM. The RAM is busy roughly 15% of the time, so remote accesses take about 180–320 ns instead of 300–600 ns, and the CPU's RAM becomes usable as a DMA buffer ([RFC 0014, section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus)) |
| Separate instruction and data address spaces (PDP-11/45 style) | **rejected** with the move to 32-bit | Doubled the per-process space on a 16-bit machine for one MMU address bit |
| Dual-port SRAM | **rejected** | Expensive, small sizes only |

**The system bus.** Shared by the main CPU, DMA devices, peripherals and
possibly other CPUs. The draft specification is
[RFC 0014](0014-rfc-system-bus.md); the electrical rules come from ngspice
simulations of the backplane
([studies/bus_si/README.md](../studies/bus_si/README.md)).

- **Synchronous.** **decided.** One bus clock; every signal is sampled on
  its rising edge.
- **The bus clock: open** (Emily, 2026-10-13). The period is a variable for
  now, with 60 ns as the starting point.
  - It had been recommended as the 50 MHz master clock ÷ 3 (60 ns) or ÷ 4
    (80 ns), set by a jumper on the CPU board.
  - Where it comes from is open too: the CPU board, which keeps the CPU in
    phase with it, or an oscillator on the backplane.
  - At 60 ns a transfer to a fast card is an address clock and a data
    clock: 120 ns. Wait states come in whole clocks.
  - Two fast cards (ABT or FCT-T) need about 33 ns for a one-clock path,
    including up to 11 ns of backplane settling at 16 slots (simulated) and
    3 ns of clock skew. The strobes' slow edges, which masters sample, are
    the tightest at about 45–55 ns.

  | At 60 ns | |
  |---|---:|
  | 32-bit transfers | 33 MB/s |
  | Transfer to a simple card | 360 ns (4 data clocks and a recovery clock) |

- **Bursts.** **rejected** (Emily, 2026-10-13): no burst transfers. They
  would need an address counter on every card that takes them, and more
  state on the backplane. They had been optional: BURST, BACK and BFIX on
  P2, up to 16 words in an aligned block, 67 MB/s.
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
- **Two 96-pin connectors per slot**, with P1 alone enough for simple
  peripherals. **decided.**
  - DIN 41612, as VME uses: **recommended.**
  - The card size waits until the design is closer to completion (Emily,
    2026-10-13). 6U Eurocards (233 × 160 mm) were proposed, and the
    simulations assumed them.
  - **P1:** D0–D15, A1–A31, BE0–1, START, WRITE, LOCK, RD, WR, RDY, WAIT,
    BERR, BUSY, CLASS0–1, REQ, GNT, SEL, BCLK, RESET, IRQ0–3, three
    reserved pins, and 24 power and ground pins.
  - **P2:** D16–D31, BE2–3, W32, IRQ4–7, the slot number, CLKSRC, about 16
    power and ground pins and about 52 user-defined pins.
  - Full lists in [RFC 0014, section 3](0014-rfc-system-bus.md#3-signals); the
    pin-by-pin assignment is still to do.
- **Full-width and half-width slots** (Emily's idea). **open**, until the
  card size is settled.
  - Some columns of the backplane take full cards on P1 and P2. Others take
    two P1-only cards stacked, with a second P1 where a full column has its
    P2. For example, 4 full columns and 4 half columns give 12 slots in
    8 columns.
  - Half cards are exactly the simple cards, and fast 16-bit cards: 16 bits
    wide, IRQ0–IRQ3 only.
  - Eurocards fit it: 6U is two 3U heights plus a gap for a middle rail.
    The rail also keeps full cards out of half columns, so a P2 never meets
    a lower P1.
  - To check: P1 then runs through both connector rows, as one chain with
    an unloaded hop of about 133 mm between them, which needs simulating.
    BCLK needs length matching to the lower slots.
- **Geographic slot regions** (NuBus style). **decided** (Emily,
  2026-10-13).
  - A31–A28 select one of 16 slots, 256 MB each. The backplane decodes them
    into each slot's SEL line, so no card needs a comparator.
  - On the draft 1b CPU, MAR bit 31 set means "system bus". MAR bits 30–27
    give the slot and bits 26–0 the address within it, so it reaches the
    first 128 MB of every slot with plain wiring.
  - Replaces the 16 × 16-byte I/O slots ([section 6](0009-rfc-ideas-io.md#6-io)).
- **Card classes, strapped on the card.** **decided** (Emily, 2026-10-13).
  - **What a card says:** two class pins, tied to ground or left open, say
    what's in a slot. The choices are: nothing, a simple card, a fast 16-bit
    card, or a fast 32-bit card.
  - **What the backplane does with it:** it reads the addressed slot's
    class during the address clock and times the transfer. A simple card
    gets the read or write strobe for N data clocks (set by jumpers on the
    backplane, the same for every simple card), then a recovery clock. A
    fast card gets one data clock unless it holds WAIT. RDY marks the end of
    a transfer for every card.
  - **What it saves:** there's no boot software, and masters need no
    wait-state tables or strobe logic.
  - **Cost:** about 8 chips on the backplane
    ([RFC 0014, section 5.1](0014-rfc-system-bus.md#51-slots-and-card-classes)).
- **An address map and timing table in RAM on the backplane**, with each
  128 KB page mapped to a slot with its own timing and width. **rejected**
  (Emily, 2026-10-13), the same day it was decided, in favour of slots in
  the address and class straps.
  - Nothing answered until software had written it, and a bad map made every
    card unreachable.
  - Its lookup was the longest path on the bus.
  - It bought flexibility this machine doesn't need: contiguous memory
    across cards, and timing per page.
- **Per-slot wait-state tables in every master**, loaded at boot (16
  entries, ~3 chips per master). **rejected**: replaced by the class straps
  (Emily, 2026-10-13).
- **Mixed widths.** **recommended.**
  - Halfwords and bytes always travel on D0–D15. A word moves on D0–D31 to
    a fast 32-bit card (W32, from its class), and in two transfers
    otherwise.
  - 32-bit cards need one swap transceiver; 16-bit cards need nothing. So
    masters that use only P1 can use 32-bit cards.
- **Simple peripherals on the system bus** (the "simple card" profile).
  **decided** (Emily, 2026-10-13). A simple card needs:
  - no clock, no address comparator and no WAIT logic;
  - a per-slot SEL line from the backplane, like the Apple II's per-slot
    select lines;
  - read and write strobes from the backplane, with the address stable a
    whole clock before them and a clock after them;
  - its class straps and an ID.

  A UART card is a 16C550, a 74HCT245, a 74HCT14 and a 74HCT541 for its
  ID, all 74HCT.
- **Per-slot strobes**, radial RD and WR from the backplane to each slot
  instead of bused ones. **open.** Clean point-to-point edges, so no RC
  networks or Schmitt triggers, and a card never sees another's strobe;
  about two more backplane chips and 32 more radial traces.
- **Card IDs.** **decided** (Emily, 2026-10-13): every card has one. The
  format and place are **open**.
- **Other CPUs as masters**: a Z80, a 68000 or a 68020.
  **recommended** as the pattern, with details in
  [RFC 0014, section 11](0014-rfc-system-bus.md#11-other-cpus-as-masters).
  - A small bridge on the CPU's card holds the CPU (Z80 WAIT, 68000 DTACK),
    synchronises the request to the bus clock and runs an ordinary
    transfer.
  - About 4–6 bus clocks per access and 12–15 chips.
  - The 68000's BERR maps directly onto the bus's BERR, and the 68020's
    dynamic bus sizing onto W32. Its big-endian byte order needs a swap
    option.
- **A separate I/O bus** for simple peripherals behind a bridge card:
  **rejected** (Emily, 2026-10-13): simple peripherals go on the system bus.
  It was the fallback if simple cards multiplied, needed odd timing
  (6800-style E clock, Z80 peripherals) or loaded the bus too much
  ([RFC 0014, section 12](0014-rfc-system-bus.md#12-rejected-a-separate-io-bus)).
- **Arbitration:** **recommended.**
  - A central arbiter on the backplane, with per-slot REQ and GNT. No CPU
    owns the bus.
  - Fixed priority by slot number, with the main CPU lowest, about 5 chips.
    Round robin is fairer, at about twice the logic: **open**.
  - The bus parks on the last master while nobody else asks.
  - A handover leaves a clock in which nobody drives the owner's lines, and
    BUSY, driven by the backplane, shows whether a transfer is under way.
  - LOCK is optional, for locked read-modify-write. It's on P1, so 16-bit
    masters (the draft 1b CPU, a 68000) can use it.
- **Bus errors from the backplane.** **recommended.**
  - The backplane asserts BERR for an empty slot (both class pins open), and
    when a card's WAIT lasts 256 clocks. On the draft 1b CPU that's a trap
    next to address error.
  - A claim line driven by the slaves was considered and dropped: simple
    cards could only release it, and a pull-up restores it too slowly.
- **A master port and a slave port on every CPU board.** Other CPUs and DMA
  reach a CPU's RAM through its slot region on the bus. **recommended.**
  - **Deadlock rule:** a CPU stalled waiting for the bus must let its slave
    port use its local RAM. Otherwise CPU A, holding the bus while waiting
    for B's RAM, and B, holding its RAM while waiting for the bus, wait
    forever.
  - With tick-level RAM sharing (the table above), the main CPU's RAM is a
    reasonable DMA buffer. A fast shared-memory card is still better for
    bulk data. **open.**
- **Synchronisation in hardware**, independent of any CPU's instruction
  set, since a heterogeneous CPU may lack a locked read-modify-write.
  **recommended.**
  - Semaphore registers that return their old value and set themselves in
    one bus read (test-and-set on read). Sixteen of them is a couple of
    chips. Whether they go on the main CPU board or the backplane is
    **open**.
  - Doorbells: a write to a register in a CPU board's region interrupts
    that CPU.
  - A per-CPU control register for reset/run and NMI. One CPU can boot
    another by loading code into its RAM and releasing its reset.
- **Interrupts:** eight shared open-collector lines (four on P1, four on
  P2). Each device picks a line with a jumper, and each CPU listens to its
  own subset through its priority encoder. Doorbells cover CPU-to-CPU
  signalling. **recommended.**
- **Electrical**, from the simulations. **recommended.**
  - **Backplane:** 4 layers, 0.2 mm traces (67.5 Ω bare; about 26 Ω loaded
    with 16 cards).
  - **Active parts on the backplane:** **decided** (Emily, 2026-10-13).
    - Slot decoding, the class straps and transfer timing, the arbiter, the
      bus monitor, the clock buffer and the power-on reset.
    - About 23 chips in plain 74-series, or about 12 with GALs. Whether
      PLDs are allowed is **open**.
    - A system-controller card in slot 0 was the alternative.
  - **No −5.2 V on the backplane:** **decided** (Emily, 2026-10-13). A
    higher supply voltage may come: **open**.
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
  - **Bus drivers:** 74ABT or 74FCT-T on fast cards and the backplane.
    74ACT isn't recommended (7 V overshoot, −1.4 V undershoot). 74HCT only
    on simple cards.
  - **RD, WR and RESET:** also 33 Ω + 220 pF at both backplane ends, for
    monotonic edges, at the cost of 20–30 ns slower edges. Schmitt-trigger
    receivers on simple cards. RD and WR are driven only by the backplane.
  - **The bus clock:** radial from an ABT buffer on the backplane, through
    56–68 Ω series resistors. Clean at every slot in every simulated case;
    0.8 ns skew without length matching. The buffers' own skew needs a
    budget too.
  - **Ground pins on both sides of BCLK, RD, WR, RESET and SEL** in the
    connector. Two switching neighbours put 1–2 V spikes on a quiet line
    through the contacts. That's harmless on lines sampled at a clock edge.
  - **Who drives what:**
    - WAIT is the only line cards share. It's actively driven both ways,
      and held by a weak pull-up when idle, as in PCI.
    - RDY, BUSY, BERR, W32 and the strobes come from the backplane.
    - The owner's control lines have pull-ups too.
    - Interrupt lines stay open-collector.
  - **Ground bounce: not known yet.** The simulation model needs fixing.
    Until then, decouple every bus chip and prefer SOIC or flow-through
    parts for wide drivers.
- **CPU board partitioning:** at least two boards. Where to split, and DIP
  or SOIC, are **open**, and wait until the design is closer to completion
  (Emily, 2026-10-13). The internal buses (A, B, F, RES) and the 120
  control lines are what make the split hard.
