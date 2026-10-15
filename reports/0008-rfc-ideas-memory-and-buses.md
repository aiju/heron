---
number: 8
type: rfc
title: Memory system and bus ideas
status: open
date: 2026-10-14
context:
  studies: [v1b_hw, bus_si, kernel]
  commit: 2f81658
---

# RFC 0008: Memory system and bus ideas

An ideas RFC: a scratchpad of ideas for the memory system and the buses,
each with its own status
([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). The evidence is in
the reports each item links to.

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1, or the draft 1b hardware has it |
| **measured** | It has numbers behind it |
| **recommended** | Suggested for draft 2 or the next hardware |
| **decided** | Emily chose it; not built yet |
| **open** | Discussed, not decided |
| **not recommended** | The evidence is against it; Emily hasn't decided |
| **rejected** | Decided against, with the reason, so it isn't proposed again without new evidence |

Chip counts are rough estimates.

## 1. Memory

| Proposal | Status | Notes |
|---|---|---|
| **Main RAM private to each CPU board**, the system bus for everything else | **recommended** | Half of all executed cycles touch memory. Backplane transceivers each way would add ~50–60 ns to those cycles: ~10% slower overall with HCT, ~19% with ACT (with variable-length cycles). Boot ROM and the clock generator stay on the CPU side too |
| **Tick-level RAM sharing for the slave port**: other masters use the CPU's RAM in the ticks the CPU doesn't need, with a data latch (2 × 74ACT573) freeing the RAM about 4 ticks into each memory cycle | **recommended** | Works with variable-length cycles because everything runs from one 50 MHz clock and the pipelined microcode says a cycle ahead when the CPU needs the RAM. The RAM is busy roughly 15% of the time, so remote accesses take about 180–320 ns instead of 300–600 ns, and the CPU's RAM becomes usable as a DMA buffer ([RFC 0014, section 10](0014-rfc-system-bus.md#10-the-main-cpu-board-on-the-bus)). A bus master could zero pages for the operating system while the CPU runs ([report 0020](0020-report-operating-system.md#zeroing-and-copying)) |
| **A DMA window in the slave port**: base and limit registers, two comparators, set only by the supervisor | **recommended** | Any bus master can write anywhere in the CPU's RAM through the slave port, so a user-level driver that can start DMA owns the machine. ~3–4 chips ([report 0020](0020-report-operating-system.md#interrupts-and-devices)) |
| **Two memory buses**: CPU-private main RAM plus a shared memory on the system bus for video, display lists, DMA and disk buffers (Amiga chip/fast RAM) | **open** | Superseded as the default by slave ports on the CPU boards, which let DMA reach main RAM. A fast shared-memory card stays an option for bulk data. Video keeps its own memory on its card ([RFC 0016](0016-rfc-video.md#41-on-the-card)) |
| **How much RAM** | **open** | The draft 1b hardware has 1 MB, and the MAR holds address bits 0–19. The Lisp, Egret and the window manager each fill it: over 200 pages of 4 KB ([report 0020](0020-report-operating-system.md#translation-the-page-map)). The flat page map ([RFC 0010](0010-rfc-ideas-os.md#3-mmu)) allows 16 MB per process |
| **Interleaved memory time slots** (Apple II, BBC Micro): the RAM is ~9× faster than the CPU cycle, so give devices their own slots | **rejected** | Fixed slots don't fit variable-length CPU cycles. Video keeps its own memory on its card instead |
| Separate instruction and data address spaces (PDP-11/45 style) | **rejected** with the move to 32-bit | Doubled the per-process space on a 16-bit machine for one MMU address bit |
| Dual-port SRAM | **rejected** | Expensive, small sizes only |

## 2. The system bus

The bus shared by the main CPU, DMA devices, peripherals and other CPUs
is [RFC 0014](0014-rfc-system-bus.md): the draft specification, its
rationale, and everything still to decide.

- **Decided:** [section 18](0014-rfc-system-bus.md#18-decisions) of RFC
  0014, and in short in [docs/README.md](../docs/README.md). Synchronous,
  slots in the address, class straps read by the backplane, SEL as the
  strobe for simple cards, LOCK, no bursts, active logic on the
  backplane, two 96-pin connectors per slot.
- **Open questions** (the bus clock, the slot bits, PLDs, a slower simple
  class, arbitration, card IDs, semaphores, a higher supply voltage):
  [section 14](0014-rfc-system-bus.md#14-open-questions).
- **Open ideas:** [section 15](0014-rfc-system-bus.md#15-open-ideas).
- **Rejected and not recommended,** with the reasons: a strobe-timed bus,
  a fully asynchronous handshake, a separate I/O bus, an address map in
  RAM on the backplane, wait-state tables in every master, WAIT-only
  timing, bursts, bused RD and WR strobes, a system-controller card,
  terminators, 74ACT drivers, −5.2 V:
  [section 16](0014-rfc-system-bus.md#16-rejected-ideas).
- **Signal integrity:** the simulations are
  [report 0022](0022-report-bus-si-revised.md) (and
  [report 0013](0013-report-bus-si.md) before it). Its suggested changes
  to the electrical rules wait for Emily
  ([section 17](0014-rfc-system-bus.md#17-signal-integrity)).

Two ideas live here rather than in RFC 0014:

### Full-width and half-width slots

Emily's idea. **open**, until the card size is settled.

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

### Splitting the CPU into boards

**open**: at least two boards. Where to split, and DIP or SOIC, wait until
the design is closer to completion (Emily, 2026-10-13). The internal buses
(A, B, F, RES) and the 120 control lines of the draft 1b hardware are
what make the split hard.
