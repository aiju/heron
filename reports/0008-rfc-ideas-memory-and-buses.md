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
  - At 60 ns a transfer to a fast slave is an address clock and a data
    clock: 120 ns. Wait states come in whole clocks.
  - Two fast cards (ABT or FCT-T) need about 33 ns for a one-clock path,
    including up to 11 ns of backplane settling at 16 slots (simulated) and
    3 ns of clock skew.
  - The longest one-clock path is the backplane's address lookup, about
    48 ns. Much below 60 ns wouldn't help anyway: a slave's SRAM path would
    need a wait state.

  | At 60 ns | |
  |---|---:|
  | 32-bit single transfers | 33 MB/s |
  | 32-bit bursts (optional) | 67 MB/s |
  | Simple-peripheral transfer | 180 ns at the least, 300 ns for a 74HCT UART card |

- **Bursts: an optional feature.** **decided.**
  - Pins reserved on P2 (BURST, BACK, BFIX).
  - At most 16 words, within an aligned 16-word block.
  - The map says which pages take bursts; on other pages a master falls
    back to single transfers.
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
- **Two 96-pin connectors per slot**, with P1 alone enough for simple
  peripherals. **decided.**
  - DIN 41612, as VME uses: **recommended.**
  - The card size waits until the design is closer to completion (Emily,
    2026-10-13). 6U Eurocards (233 × 160 mm) were proposed, and the
    simulations assumed them.
  - **P1:** D0–D15, A1–A31, BE0–1, START, WRITE, LOCK, RD, WR, RDY, WAIT,
    BERR, BUSY, REQ, GNT, SEL, PRESENT, BCLK, RESET, IRQ0–3, four reserved
    pins, and 24 power and ground pins.
  - **P2:** D16–D31, BE2–3, W32, the burst lines, IRQ4–7, the slot number,
    CLKSRC, about 16 power and ground pins and about 49 user-defined pins.
  - Full lists in [RFC 0014, section 3](0014-rfc-system-bus.md#3-signals); the
    pin-by-pin assignment is still to do.
- **Full-width and half-width slots** (Emily's idea). **open**, until the
  card size is settled.
  - Some columns of the backplane take full cards on P1 and P2. Others take
    two P1-only cards stacked, with a second P1 where a full column has its
    P2. For example, 4 full columns and 4 half columns give 12 slots in
    8 columns.
  - Half cards are exactly the simple-slave profile: 16 bits wide, no
    bursts, IRQ0–IRQ3 only. The map marks their pages as 16-bit.
  - Eurocards fit it: 6U is two 3U heights plus a gap for a middle rail.
    The rail also keeps full cards out of half columns, so a P2 never meets
    a lower P1.
  - To check: P1 then runs through both connector rows, as one chain with
    an unloaded hop of about 133 mm between them, which needs simulating.
    BCLK needs length matching to the lower slots.
- **An address map in RAM on the backplane.** **decided** (Emily,
  2026-10-13).
  - **What it maps:** each 128 KB page of the 32-bit address space
    (**recommended**) to a slot, with the page's data clocks, recovery
    clocks, width, and whether it takes bursts.
  - **What the backplane does with it:** it times every transfer from the
    entry. It drives the slot's SEL line and the read and write strobes,
    and RDY, which marks the end of a transfer for every card.
  - **What it saves:** masters need no wait-state tables, and cards never
    compare addresses.
  - **Cost:** two 32K × 8 SRAMs and about 15 more chips.
  - **Programming:** software writes the map at boot, from the cards' IDs
    ([RFC 0014, section 5.1](0014-rfc-system-bus.md#51-the-address-map)).
  - **What it replaces:** the geographic slot regions and the per-master
    wait-state tables.
- **Geographic slot regions** (NuBus style). **rejected**: replaced by the
  address map (Emily, 2026-10-13). A31–A28 selected one of 16 slots, 256 MB
  each, decoded on the backplane into each slot's SEL line.
- **Per-slot wait-state tables in every master**, loaded at boot (16
  entries, ~3 chips per master). **rejected**: replaced by the address map
  (Emily, 2026-10-13).
- **Mixed widths.** **recommended.**
  - Halfwords and bytes always travel on D0–D15. A word moves on D0–D31
    when the map says the page is 32 bits wide (W32), and in two transfers
    otherwise.
  - 32-bit slaves need one swap transceiver; 16-bit slaves need nothing.
    So masters that use only P1 can use 32-bit slaves.
- **Simple peripherals on the system bus** (the "simple slave" profile).
  **decided** (Emily, 2026-10-13). A simple card needs:
  - no clock, no address comparator and no WAIT logic;
  - a per-slot SEL line from the backplane, like the Apple II's per-slot
    select lines;
  - read and write strobes from the backplane, with the address stable a
    whole clock before them and recovery clocks after them;
  - its wait states and recovery from the backplane's map.

  A UART card is a 16C550, a 74HCT245 and a 74HCT14, all 74HCT, plus its
  card ID.
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
  - A central round-robin arbiter on the backplane, with per-slot REQ and
    GNT. No CPU owns the bus.
  - The bus parks on the last master while nobody else asks.
  - A handover leaves a clock in which nobody drives the owner's lines, and
    BUSY, driven by the backplane, shows whether a transfer is under way.
  - LOCK is optional, for locked read-modify-write. It's on P1, so 16-bit
    masters (the draft 1b CPU, a 68000) can use it.
- **Bus errors from the backplane.** **recommended.**
  - The backplane asserts BERR for an unmapped page, and when a slave's
    WAIT lasts 256 clocks. On the draft 1b CPU that's a trap next to
    address error.
  - Every card grounds a PRESENT pin, and software maps only slots with a
    card in them.
  - A claim line driven by the slaves was considered and dropped: simple
    cards could only release it, and a pull-up restores it too slowly.
- **A master port and a slave port on every CPU board.** Other CPUs and DMA
  reach a CPU's RAM through its window on the bus. **recommended.**
  - **Deadlock rule:** a CPU stalled waiting for the bus must let its slave
    port use its local RAM. Otherwise CPU A, holding the bus while waiting
    for B's RAM, and B, holding its RAM while waiting for the bus, wait
    forever.
  - With tick-level RAM sharing (the table above), the main CPU's RAM is a
    reasonable DMA buffer. A fast shared-memory card is still better for
    bulk data at full burst speed. **open.**
- **Synchronisation in hardware**, independent of any CPU's instruction
  set, since a heterogeneous CPU may lack a locked read-modify-write.
  **recommended.**
  - Semaphore registers that return their old value and set themselves in
    one bus read (test-and-set on read). Sixteen of them is a couple of
    chips. Whether they go on the main CPU board or the backplane is
    **open**.
  - Doorbells: a write to a register in a CPU board's window interrupts
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
    - The address map and transfer timing, the arbiter, the bus monitor,
      the clock buffer and the power-on reset.
    - About 45 chips in plain 74-series, or about 25 with GALs. Whether
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
  - **Bus drivers:** 74ABT or 74FCT-T on synchronous cards and the
    backplane. 74ACT isn't recommended (7 V overshoot, −1.4 V undershoot).
    74HCT only on simple slaves.
  - **RD, WR and RESET:** also 33 Ω + 220 pF at both backplane ends, for
    monotonic edges, at the cost of 20–30 ns slower edges. Schmitt-trigger
    receivers on simple slaves. RD and WR are driven only by the backplane.
  - **The bus clock:** radial from an ABT buffer on the backplane, through
    56–68 Ω series resistors. Clean at every slot in every simulated case;
    0.8 ns skew without length matching. The buffers' own skew needs a
    budget too.
  - **Ground pins on both sides of BCLK, RD, WR, RESET and SEL** in the
    connector. Two switching neighbours put 1–2 V spikes on a quiet line
    through the contacts. That's harmless on lines sampled at a clock edge.
  - **Who drives what:**
    - WAIT is the only line slaves share. It's actively driven both ways,
      and held by a weak pull-up when idle, as in PCI.
    - RDY, BUSY, BERR, W32, BACK and the strobes come from the backplane.
    - The owner's control lines have pull-ups too.
    - Interrupt lines stay open-collector.
  - **Ground bounce: not known yet.** The simulation model needs fixing.
    Until then, decouple every bus chip and prefer SOIC or flow-through
    parts for wide drivers.
- **CPU board partitioning:** at least two boards. Where to split, and DIP
  or SOIC, are **open**, and wait until the design is closer to completion
  (Emily, 2026-10-13). The internal buses (A, B, F, RES) and the 120
  control lines are what make the split hard.
