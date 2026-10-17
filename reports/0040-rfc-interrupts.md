---
number: 40
type: rfc
title: Interrupts
status: open
date: 2026-10-16
context:
  studies: [fen, v2_hw]
  commit: 198d40a
depends-on: [27, 29, 31, 36, 37]
---

# RFC 0040: Interrupts

The whole interrupt design in one place: the CPU's levels and vectors,
what every CPU card provides (a request register, a message register and
a timer), how the I/O processor routes every device's interrupt, the
rings in memory that say why, and how it all works with several CPUs. It
takes over the interrupt parts of
[RFC 0029, section 7](0029-rfc-draft-2-system.md#7-interrupts),
[RFC 0037, sections 8 and 9](0037-rfc-system-and-io-bus.md#8-interrupts)
and [RFC 0027, section 7](0027-rfc-io-coprocessor.md#7-the-interface-to-the-cpus),
which point here.

**Decided** (Emily, 2026-10-16):

- eight real interrupt levels, as RFC 0029 has them;
- a vector base register;
- no WINDOW bit in the I/O bus's timing table
  ([section 15](#15-the-window-bit)).

**Tentative** (Emily, 2026-10-16):

- a queue or a flag lives in its reader's RAM;
- the message register (revised on 2026-10-17, below);
- messages vectored through the `SWI` entries;
- four ATN lines from cards on the system bus;
- the I/O processor polling its INT lines at a tick;
- registers of their own for the message level.

**Tentative** (Emily, 2026-10-17):

- the CPU card's registers as [section 3](#3-the-cpu-card) has them:
  levels raised and lowered by address, no board information, and reads
  undefined but the timer's and the status;
- a 16-bit message register, whose drops set DROPPED and interrupt;
- a 32-bit timer and a 16-bit one-shot, in place of a periodic tick.

**To be confirmed:** the non-maskable interrupt.

Everything else is proposed. Statuses: **decided**, **tentative**,
**recommended**, **open** (a real choice either way), **optional** (an
add-on that can come later without changing the rest) and **not
recommended**.

## Contents

Part I: Specification

1. [Overview](#1-overview)
2. [The CPU](#2-the-cpu)
3. [The CPU card](#3-the-cpu-card)
4. [The I/O processor](#4-the-io-processor)
5. [Memory: rings and flags](#5-memory-rings-and-flags)
6. [Several CPUs](#6-several-cpus)
7. [The kernel's conventions](#7-the-kernels-conventions)
8. [Latency](#8-latency)

Part II: Discussion

9. [Why eight levels stay](#9-why-eight-levels-stay)
10. [The message register](#10-the-message-register)
11. [Vectoring through the SWI entries](#11-vectoring-through-the-swi-entries)
12. [The vector base register](#12-the-vector-base-register)
13. [The timer](#13-the-timer)
14. [The lazy class](#14-the-lazy-class)
15. [The WINDOW bit](#15-the-window-bit)
16. [Cards on the system bus, and noticing INT lines](#16-cards-on-the-system-bus-and-noticing-int-lines)
17. [What changes elsewhere](#17-what-changes-elsewhere)
18. [Open questions](#18-open-questions)

## Part I: Specification

### 1. Overview

```
 I/O cards ------ INT, one line per slot ----+
 system-bus cards -------- ATN0-ATN3 --------+
                                             v
                      +-------------------------------------+
   CPUs --doorbells-> |  I/O processor                      |
                      |  polls INT and ATN every 10 us;     |
                      |  routing table: for each source,    |
                      |  its owner, class and level         |
                      +---------+-------------------+-------+
            owner: an I/O       |                   |  owner: a CPU
            processor task      v                   v
                    wake that Forth task     lazy: an event into the CPU's ring, no bit
                                             slow: an event into the ring, then a level's bit
                                             fast: an event into the ring, then the message register
                                                    v
            CPU card: request register (levels 1-8), message register (level 7),
                      one-shot timer (level 6)
                                                    v
            CPU: level L above IPL -> vector at VBR + 0x40 + 4(L - 1);
                 with a message    -> vector at VBR + 0x100 + 4 x source
```

- **Devices never interrupt a CPU directly.** Every device's interrupt
  goes to the I/O processor, which serves it itself or forwards it.
- **A CPU is interrupted by a write,** to its card's request register or
  its message register. Any bus master can write them: the I/O
  processor, another CPU, or the CPU itself.
- **Why it was interrupted** is in memory, in a ring of events for each
  sender and receiver; the message register's 8 bits of data are a hint. A level's
  bit only says "look".
- **Three classes of event:**
  - **lazy:** no interrupt; the kernel notices it at its next context
    switch, tick or idle;
  - **slow:** a level's bit, possibly batched;
  - **fast:** the message register, taken even while the kernel holds the
    slow levels off.

### 2. The CPU

This restates RFC 0029's section 7, with this RFC's changes.

#### 2.1 Levels

- **Eight levels,** 1–8, 8 the highest (**decided**, Emily, 2026-10-16).
  The CPU card says which are requested
  ([3.1](#31-the-request-register)).
- **Level-sensitive:** a level stays requested until its handler clears
  its cause.
- **Taken** between instructions, when I is set and the highest level L
  requesting is above IPL: never straight after `EI`, possibly straight
  after `DI`, and straight after `RTI` if the status it restores allows
  it. IPL above 8 holds off every level, as 8 does.
- **Entering** an interrupt is entering an exception
  ([RFC 0029, 6](0029-rfc-draft-2-system.md#6-exceptions)), sets IPL to
  L, and jumps to the vector at VBR + `0x40` + 4(L − 1). Level 7 with a
  message waiting is the exception ([2.3](#23-the-message-level)).
  - I is clear in the handler. Executing `EI` lets higher levels in,
    which is how interrupts nest.
  - `RTI` restores the I and IPL of the code it returns to.
- **`SPL #n`** sets IPL to n, 0–8, and changes nothing else: levels n and
  below are then held off.
- **`HALT`** with I set waits for an interrupt, and resumes after the
  `HALT` once the handler returns. With I clear it stops until reset.
- **A request that has gone** by the time its handler looks is answered
  by returning.

#### 2.2 The vector base register

**decided** (Emily, 2026-10-16).

- **VBR** is a supervisor special register. Which number it takes is
  **open**: 15, if `bkpt` (itself still open) moves. v2_hw uses 15.
- **Every vector is VBR plus its offset** in RFC 0029's table: `0x04` the
  non-maskable interrupt, `0x08`–`0x24` the exceptions, `0x40` + 4(L − 1)
  level L, `0x100` + 4n `SWI #n`.
- **Reset** sets VBR to `0x8000_0000`, so the vectors start where RFC
  0029 has them. Reset itself always starts at physical 0.
- **VBR is aligned to 2 KB.** The table's offsets end at `0x4FC`, so the
  entry can OR the offset in.
- **What it's for:** each CPU points its VBR at a table in its own RAM
  ([section 6](#6-several-cpus)).

#### 2.3 The message level

**tentative** (Emily, 2026-10-16).

- **Level 7 is the message level.** The CPU card's message register
  requests it while it holds a message, or has dropped one
  ([3.2](#32-the-message-register)).
- **Its entry vectors on the message's source,** through the `SWI`
  entries: VBR + `0x100` + 4 × source. That gives up to 256 sources, each
  with a handler of its own, without a table of their own.
- **The message comes with it:** the entry copies the source into `r1`
  and the 8 bits of data into `r2` of the handler's registers,
  zero-extended, and the register empties. How the microcode reaches its
  own card's register is RFC 0031's business.
- **Level 7 without a message,** from a dropped message or from level 7
  raised in the request register, goes to level 7's own vector, VBR +
  `0x58`, whose handler scans the rings.
- **Sources and `SWI`s share numbers.** The kernel keeps a range for
  interrupt sources, tentatively 128–255, and an `SWI` from user mode in
  that range raises a privilege violation. `SWI` already has an entry per
  number in the decode table, so in v2_hw the check costs one control
  store word and no cycles ([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#the-swi-numbers-kept-for-sources)).

#### 2.4 Banks

- **Exceptions and interrupts enter bank 0,** as in RFC 0029, except one.
- **The message level has registers of its own** (**tentative**, Emily,
  2026-10-16), so that its handler saves nothing. It pushes the PC and
  `sr` on their `sp`. Which registers is **open**: a bank, 255 say, the
  last of Fen's thread banks; or sixteen registers outside the banks,
  sharing the constants and special registers, as v2_hw builds them
  ([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#the-message-levels-registers)).
- **`sr`'s bit 28,** reserved now, becomes M: set while in the message
  level's registers, kept in the `sr` an exception pushes, and restored
  by `RTI`. A level 8 interrupt during a message handler enters bank 0 as
  usual, and its `RTI` goes back to the message level's registers through
  M.

#### 2.5 The non-maskable interrupt

**To be confirmed.** As RFC 0029 has it: vector VBR + `0x04`, taken
between instructions whatever I and IPL, from the CPU's own card. Any
master can raise it with a write to the card's `0x1000`, or to the
control register's bit 3, as v2_hw has it now (**open**): the I/O
processor's watchdog, or a debugger. What it does to I and IPL is open.
**Recommended:** the control register's NMI bit is a latch that the
entry clears, so that one write is one NMI, and the entry does what every
exception's does: it clears I and T and leaves IPL alone. Setting IPL to
8 as well would matter only to a handler that executes `EI`. v2_hw builds
the recommendation, with the latch as the control register's bit 3;
setting IPL to 8 would cost it about 1 package and no cycles.

### 3. The CPU card

**tentative** (Emily, 2026-10-17, worked out with the hardware session):
the registers every CPU card provides, at `0x7N00_0000` for a card in
region N ([RFC 0037, 5.1](0037-rfc-system-and-io-bus.md#51-addresses)).
They take about 18 chips, with a one-shot timer, where the set they
replace took 17–27 without one
([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#the-card-as-emily-directed-it)).
The offsets are a proposal.

| Offset | Access | Effect |
|---|---|---|
| `0x0000` | read, write | Control, as RFC 0037 has it: RUN, RESET, STEP; status |
| `0x1000` | write, any value | Raise the non-maskable interrupt ([2.5](#25-the-non-maskable-interrupt)) |
| `0x2000` + 4(L − 1) | write, any value | Lower level L, L = 1–8 ([3.1](#31-the-request-register)) |
| `0x2020` + 4(L − 1) | write, any value | Raise level L |
| `0x3000` | write, 16 bits | The message register ([3.2](#32-the-message-register)) |
| `0x4000` | read, 32 bits | The timer's count ([3.3](#33-the-timer)) |
| `0x4000` | write, 16 bits | The one-shot: load its count and clear its alarm |
| `0x5000` | write, any value | Clear DROPPED |
| `0x6000` | write, any value | Clear the periodic tick, if one is fitted |
| `0x7000` | write, any value | Clear the profiling tick, if one is fitted |
| `0x80_0000` + `0x2_0000` k | read, write, halfwords, while RUN is off | The control store's SRAM k, 64K × 16: k = 0–8 the microinstruction's 16-bit lanes, k = 9 the decode table ([RFC 0031](0031-rfc-draft-2-cpu.md)) |

- **Only the timer and the control register's status can be read.**
  Every other read, every unused bit and every unused address is
  undefined. One 74F138 on A12–A14 decodes the groups, and the other
  address bits in a group aren't decoded, so registers repeat.
- **The data is ignored** in every write but the message's and the
  one-shot's.
- **No board information.** How a CPU learns its region N, and so its
  number, and BCLK's period is **open** ([18](#18-open-questions)).
- **The CPU reaches its own card's registers locally,** as an ordinary
  load or store, and its writes take effect at the end of its cycle. In
  v2_hw that is about 240 ns quicker than a bus transfer to read and 300
  ns to write. Other masters come in through the slave port, and their
  writes take effect at the end of the transfer. A CPU reaching another
  card's registers goes over the bus like any other master.
- **By convention** only the card's own CPU loads its one-shot and clears
  its flags. Its own CPU's writes to the control register are ignored
  (proposed): it stops itself with `HALT`.
- **RESET** clears the request register, the message register's FULL and
  DROPPED, and the timer. It leaves the one-shot's count undefined and may
  set its alarm, so the kernel loads the one-shot before it sets I.

#### 3.1 The request register

- **Eight bits, one per level, raised and lowered by address:** a write
  to a level's raise or lower address changes that level alone, whatever
  the data. No writer reads it first, so any number of writers can't
  collide. It can't be read back.
- **A 74HCT259 addressable latch,** with A4–A2 as its address and A5 as
  its data input, so that a level's raise address is its lower address
  plus `0x20`.
- **Any master** can write it: the I/O processor for its events, another
  CPU, or the CPU itself, for deferred work, which it sees two clock edges
  later.
- **A level is requested** while its bit is set, or while one of the
  card's own sources for it is:

  | Level | Also requested while |
  |---|---|
  | 6 | the one-shot's alarm is set, or the periodic tick, if one is fitted |
  | 7 | the message register is FULL, or DROPPED is set |
  | 8 | the profiling tick is set, if one is fitted |

- **Parts:** 1 chip, and about 1½ for the ORs onto the CPU's levels.

#### 3.2 The message register

**tentative** (Emily, 2026-10-17).

- **16 bits,** {source 8, data 8}, so that a 16-bit master writes it in
  one transfer. There is no claim and no release.
- **Empty or full:** a write while it is empty loads it and sets FULL. A
  write while it is FULL is discarded and sets DROPPED. Either requests
  level 7.
- **The message entry,** at level 7 with FULL set and DROPPED clear,
  copies the source into `r1` and the data into `r2`, zero-extended, and
  goes to VBR + `0x100` + 4 × source ([2.3](#23-the-message-level)). The
  register empties at the end of the cycle that reads it. Only the CPU
  reads it, over its own datapath; it has no address.
- **DROPPED, or level 7 raised in the request register,** goes to level
  7's own vector, VBR + `0x58`. Its handler clears DROPPED, then scans
  the rings.
- **Drop first:** with FULL and DROPPED both set, level 7's own vector
  runs first. Its scan covers every ring, the held message's source's
  too. After its `RTI`, FULL brings the message entry, for an event the
  scan may already have handled. So the next entry at level 7 after any
  drop scans; message first could starve the scan while messages keep
  coming. It costs a gate.
- **In hardware:** the register, FULL and DROPPED change only at a clock
  edge, with the write and the release as enables. A write is loaded only
  if FULL is 0 at that edge, so a write during the CPU's read is dropped
  and flagged, never torn and never lost unseen. A drop and a clear of
  DROPPED on the same edge leave DROPPED set, which costs at most one
  more scan.
- **In software:**
  - a sender puts the event in its ring first, then writes the message
    register. A write gets no reply, so the ring is the only sure copy;
  - the 8 data bits are a hint: a handler must cope with finding its ring
    empty, since a scan may have taken the event;
  - the handler for level 7's own vector clears DROPPED before it scans,
    so a drop during the scan brings another scan;
  - any master may send, since every sender has a ring.
- **Drops are rare** with the kernel at `SPL #6`: under 1% of messages,
  even at 10,000 a second, against Fen's measured spans
  ([10](#10-the-message-register)).
- **Parts:** about 2½: a 74ABT16823 loaded only while empty, FULL and
  DROPPED in a 74F109, and the gate.

#### 3.3 The timer

**tentative** (Emily, 2026-10-17).

- **A 32-bit count of BCLK / 2,** so that code can be timed with
  interrupts off: 120 ns a count at a 60 ns BCLK, wrapping every 8.6
  minutes. It is free-running and cleared by RESET. Every card divides
  the same BCLK from the same RESET, so every CPU reads the same time.
- **Four 74HC590s,** which can't count a 60 ns BCLK, hence the ÷2.
  Whether the prescaler is fixed or jumpered, ÷2 to ÷16, is **open**.
- **Reading:** RCLK is tied to the counter clock and held during a read,
  so a 32-bit read is one count, at most one behind. A 16-bit master's
  two halves may come from different counts, so it reads the high half,
  the low half and the high half again. From the slave port a read takes
  about 240 ns of the bus.
- **The one-shot** (Emily's proposal): a 16-bit down counter, clocked by
  one of the timer's bits 2–15, picked with a jumper (**open**; proposed:
  bit 3).

  | Clock | A count | Range |
  |---|---:|---:|
  | bit 2 | 0.96 µs | 63 ms |
  | bit 3 | 1.92 µs | 126 ms |
  | bit 7 | 31 µs | 2.0 s |
  | bit 11 | 0.49 ms | 32 s |
  | bit 15 | 7.9 ms | 8.6 min |

  - A write to `0x4000` loads the count and clears the alarm. The alarm
    sets when the count reaches 0, that many periods after the write, to
    within half a period, and requests level 6 until the next write.
  - After firing, the counter carries on from `0xFFFF`, so it fires
    again 65,536 periods later unless it is loaded. A handler treats an
    alarm with nothing due as spurious, or loads it.
  - **It replaces the periodic tick:** the kernel loads it with the time
    to its next tick or deadline, worked out from the 32-bit count, so
    errors don't add up. A deadline finer than a tick needs no request to
    the I/O processor, within the one-shot's range; beyond it, software
    loads it again.
  - Bit 2 or above, since a read's hold on RCLK can swallow an edge of
    bit 0 or 1, but only delays a slower bit's.
- **A periodic tick** from a jumpered bit alongside the one-shot, and a
  **profiling tick** onto level 8 so that the PC can be sampled even
  inside message handlers, are **open**: about ½ chip each.
- **Parts:** the timer about 6¼ (four 74HC590s, a 74ABT16244 for bits
  0–15, the ÷2, the enables and RCLK's hold), the one-shot about 4¾ (four
  74HCT193s, the alarm flag and the load's strobe).

### 4. The I/O processor

#### 4.1 Sources

| Source | How it reaches the I/O processor |
|---|---|
| Devices on the I/O bus | 16 radial INT lines: the 12 slots and the 4 devices on its own card; level-sensitive ([RFC 0037, 19](0037-rfc-system-and-io-bus.md#19-interrupts-reset-and-clocks)) |
| Cards on the system bus | ATN0–ATN3, open collector and level-sensitive; each card picks its line with a jumper (**tentative**) |
| The I/O processor itself | the completions of its requests, its timers |
| The CPUs | the doorbells ([RFC 0027, 4.4](0027-rfc-io-coprocessor.md#44-registers-for-the-cpus)) |

#### 4.2 Noticing

- **Polling** (**tentative**): every 10 µs, at the tick of its own timer,
  the I/O processor reads its INT lines and ATN0–ATN3
  ([RFC 0027, 6.4](0027-rfc-io-coprocessor.md#64-tasks-native-jobs-and-events)).
  That costs it about 5–10% of its time.
- **Doorbells** get its attention at once.
- **Change detection in hardware** (**optional**): a register of the
  lines' last state and two comparators, about 4 chips, would save the
  polling's time and most of its latency.

#### 4.3 The routing table

One entry for each source, in the I/O processor's memory, set by the
kernel through its ring
([RFC 0027, 7.2](0027-rfc-io-coprocessor.md#72-requests-and-windows)):

| Field | |
|---|---|
| Owner | One of the I/O processor's tasks, or a CPU |
| Class | Lazy, slow or fast |
| Level | For a slow event: the level on that CPU (4, by the kernel's convention in [section 7](#7-the-kernels-conventions)) |
| Batching | For a slow event: how long the I/O processor may hold it back to post several with one interrupt, say 1 ms |
| Deadline | For a lazy event: how long it may wait before it is sent as a slow one |
| Source number | For a fast event: the source field of its message |
| Mask and state | Set when the event is forwarded; cleared when its owner says it has been served |

The I/O processor study keeps 8 cells for each of 48 sources: the INT
lines, ATN0–3 and each client's completions
([iop-latency.md](0040-rfc-interrupts/iop-latency.md#routing-masking-and-batching)).

#### 4.4 Delivery

- **To one of its own tasks:** it clears that task's wait.
- **Lazy:** it writes the event into the CPU's event ring and sets no bit.
  If the ring's wake-me word is set, or the event is older than its
  deadline, it sends it as slow instead.
- **Slow:** it writes the event into the ring, then to the level's raise
  address on that CPU's card. It may hold the write back for the source's
  batching time, to post several events with one interrupt. The I/O
  processor study keeps one countdown, to the shortest hold waiting, and
  when it runs out raises every held level at once.
- **Fast:** it writes the event into the ring, then {source, data} to the
  CPU's message register, in one transfer. If the register is full, the
  write is dropped, and the CPU's scan of its rings finds the event
  ([3.2](#32-the-message-register)).
- **Masking:** it masks the source from then until its owner says it has
  been served: one of its tasks by waiting again, a CPU's driver by a
  request. So each source has at most one event outstanding. For a
  ring's completions, the I/O processor study serves the source without
  a request: the rings' head words count the events posted and handled
  in their high halves, and the next is posted only when the two are
  equal (an option,
  [iop-latency.md](0040-rfc-interrupts/iop-latency.md#routing-masking-and-batching)).

#### 4.5 Requests for time

A CPU's own deadlines are its one-shot's
([3.3](#33-the-timer)), to within 2 µs up to 126 ms with the proposed
clock. "Interrupt me at t" as a request on the kernel's ring, which the
I/O processor answers at t to within its polling tick, stays for
deadlines tied to the I/O processor's own work. (Proposed.)

### 5. Memory: rings and flags

#### 5.1 Rings

```
  +0   head      written only by the producer
  +4   tail      written only by the consumer
  +8   entry 0
  ...            N entries of a fixed size
       entry N-1
```

- **The producer** writes the entry at `head mod N`, then advances
  `head`, then sets the receiver's bit if it is to interrupt.
- **The consumer** clears its level first, then, while `tail` isn't
  `head`, handles the entry at `tail mod N` and advances `tail`.
- **Each index has one writer,** so producer and consumer share a ring
  with plain stores, no lock and no locked bus cycle. It needs stores to
  arrive in order, which they do.
- **No event is lost:** the event is written before the bit is set, and
  the bit is cleared before the ring is read, so an event posted during
  the drain raises the level again.
- **A ring never fills** if it has a slot for every source its producer
  routes there, since a source is masked while it has an event
  outstanding ([4.4](#44-delivery)).
- **Rings in this design:**
  - an event ring for each sender and receiver: from the I/O processor
    to each CPU, and from each CPU to each other CPU;
  - requests and completions between a client and the I/O processor
    ([RFC 0027, 7.1](0027-rfc-io-coprocessor.md#71-rings-and-doorbells)).

#### 5.2 Where they live

**tentative** (Emily, 2026-10-16): with their reader.

| What | Its reader | It lives in |
|---|---|---|
| An event ring to a CPU | that CPU | that CPU's own RAM |
| A ring of requests to the I/O processor | the I/O processor | the shared RAM |
| A ring of completions from the I/O processor | the client | the client's CPU's RAM |
| A ring's wake-me word | the I/O processor | the shared RAM |
| A "done" word that someone waits for | the waiter | the waiter's RAM |

So a handler reads only its own RAM and never waits for the bus. The
senders pay the bus instead, before they set a bit.

### 6. Several CPUs

- **Each CPU card** has its own request register, message register and
  timer, so each CPU has its own eight levels and its own message level.
- **Each CPU points its VBR** at a vector table in its own RAM. The reset
  vector at physical 0 is common: a CPU that the I/O processor starts
  later (its RUN bit) runs a short stub there, which learns its region
  (how is **open**, [18](#18-open-questions)), sets its VBR and jumps to
  its own code.
- **Time agrees** across CPUs ([3.3](#33-the-timer)).
- **CPU to CPU:** slow, an event in the pair's ring and level 5 on the
  receiver; fast, the event in the pair's ring and then the receiver's
  message register.
- **Routing:** the I/O processor's table names the CPU for each source.
  Moving a source to another CPU is a change to the table, as long as
  the other CPU has a handler for it.
- **A kernel for each CPU,** each in its own RAM and talking by messages,
  fits this best. That is the multikernel of Barrelfish (2009), and Fen
  passes messages already.

### 7. The kernel's conventions

Software, not hardware: a convention for Fen.

| Level | Use |
|---|---|
| 8 | The profiling tick (optional) |
| 7 | The message level: fast events |
| 6 | The CPU card's timer |
| 5 | Other CPUs' slow events |
| 4 | The I/O processor's slow events |
| 2–3 | Free |
| 1 | Deferred work, which a CPU raises itself |

- **Critical sections the scheduler shares** run at `SPL #6`: they hold
  off levels 1–6, and messages and profiling still get in.
- **Critical sections only drivers share** run at `SPL #4`, so the timer
  still gets in.
- **A message handler** touches only its own data. Anything more it hands
  on to level 1, by setting its own CPU's bit 1, as VMS's fork levels and
  Unix's software interrupts did.
- **Lazy rings** are drained at every context switch, every tick, and
  before `HALT`. Before halting, the kernel sets its rings' wake-me
  words, and clears them when it is busy again.
- **For Fen:** it runs its kernel with interrupts off throughout and uses
  no `SPL` ([fen-latency.md](0040-rfc-interrupts/fen-latency.md)). Under
  this convention its kernel enters at `SPL #6` with I set, two
  instructions, so that messages get in; its timer moves from level 7 to
  6, as the one-shot (Fen counts levels from 0, after its board's mask bits,
  so it calls these 6 and 5); its board's devices move behind the I/O
  processor; it drains its lazy rings; and each CPU sets its VBR.

### 8. Latency

| From | To | About |
|---|---|---|
| A device's INT | The I/O processor seeing it | up to 10 µs, its polling tick |
| The I/O processor seeing an event | A CPU's level bit, or its message | 2–3 µs: the routing and a bus write (*estimate*); about 10.5 µs in the I/O processor study, with the event ring's entry and head written into the CPU's RAM |
| … with another master holding the bus | | up to about 1.5 µs more (VRAM reads, locked sequences), or about 12 µs for a window read of a slow device |
| A doorbell | The I/O processor reading the ring | 1–3 µs, the slice it is in; 1.4–3.2 µs in the I/O processor study to take the doorbell |
| A request | Its completion's interrupt | the transfer and a few µs (*estimate*); about 60 µs for a 64-byte fill in the I/O processor study, 18 of them in two scheduling waits |
| A message | Its handler running, even over the kernel's critical sections | the CPU's entry, 0.94 µs in v2_hw, after the instruction in progress and any exception being entered |
| A CPU's level bit | Its handler running | the CPU's entry, 0.64 µs in v2_hw, once I and IPL let it in |
| A slow level | A user-level driver running | 85–107 µs ([report 0020](0020-report-operating-system.md#interrupts-and-devices)'s 500–640 cycles at Fen's 6 MHz), up to about 1 ms while the kernel holds slow levels off ([report 0036](0036-report-fen.md#3-what-it-costs)) |
| A lazy event | The kernel seeing it | up to a tick, 8–16 ms, or sooner at a context switch |

Measured in Fen, which holds interrupts off throughout its kernel: a
slow interrupt arriving at a random moment waits about 145 µs on average
at the shell and 0.7 ms on the desktop, but up to 46 ms while a large
`vm_alloc` zeroes its pages; Fen takes at most about 500 interrupts a
second; and a lazy event waits a few milliseconds while the machine is
busy ([fen-latency.md](0040-rfc-interrupts/fen-latency.md), with the
numbers in [fen-latency-results.md](0040-rfc-interrupts/fen-latency-results.md)).
The CPU's entries are measured on v2_hw's RTL model
([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#time)), the I/O
processor's side on the I/O processor study's model
([iop-latency.md](0040-rfc-interrupts/iop-latency.md)): its two scheduling waits, for the tick to run a
queued job and for the ring to be found empty before posting, are its
choices, and without them a request comes close to the estimate.

The rule for devices that follows:

- anything that can't wait about 1 ms for a CPU is buffered in hardware,
  or handled by the I/O processor;
- anything that can't wait for a Forth task on the I/O processor is its
  native microcode;
- anything that can't wait a polling tick has a FIFO, or a native job
  that polls it.

## Part II: Discussion

### 9. Why eight levels stay

- **The I/O processor is in front** of every device. It buffers, batches
  and orders their events, so only a handful of sources reach a CPU: the
  I/O processor's events, the other CPUs, the timer and messages.
- **Eight levels anyway** (**decided**, Emily, 2026-10-16). The hardware
  session found that eight real levels cost about the same as three wired
  to fixed levels, and that ARM's two masks would save a few chips; built
  in v2_hw, the eight levels take about 10.3 packages of the core's 382
  ([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#the-core)). Eight real levels give:
  - software interrupts at a low level for deferred work;
  - a level for each kind of event, so a handler knows the source without
    looking;
  - the timer above the drivers' events, so `SPL #4` lets it in;
  - room for later local sources: a profiling tick, a performance
    counter, a parity error;
  - no change to RFC 0029, `SPL` or Fen.

| Design | Chips on the CPU | The instruction set | Status |
|---|---|---|---|
| **Eight real levels** | about 10.3 packages, and 1 to read IPL out of `sr` | unchanged | **decided** |
| Eight in the instruction set, three wired at fixed levels | about 2.5 fewer | unchanged | **not recommended**: little saving |
| Two masks, as ARM's IRQ and FIQ | about 4–5 for all the interrupt logic, against about 11 | IPL and `SPL` go; an F bit in `sr` | **not recommended** |

### 10. The message register

- **What it gives:** one bus write, even from a 16-bit master, raises
  the interrupt and says which handler to run. The handler is vectored by
  the source and has a hint in `r2`; the event itself is in a ring.
- **Why 16 bits:** a 16-bit master writes it in one transfer, so two
  senders can't interleave halves, and nothing has to be claimed first.
  The bus has no master IDs, so a 32-bit register written in two halves
  needed a claim by read, three transfers in all.
- **Why the drop interrupts:** a write gets no reply, so a sender can't
  learn that its message was dropped. The receiver can, and the ring has
  the event, so DROPPED sends it to scan its rings.
- **Slow events never use it.** They come in bursts that would keep it
  full and the receiver scanning. Rings queue any number of events, and
  batch them.
- **How often a message drops** depends on how the kernel holds
  interrupts off, more than on the register. Measured against Fen's
  spans ([fen-latency.md](0040-rfc-interrupts/fen-latency.md#busy-claims-depend-on-the-kernel-not-on-the-fifo),
  where a drop is a busy claim): with a kernel at `SPL #6`, under 1% of
  messages even at 10,000 a second; with Fen's kernel as it is, 6–39% at
  1,000 a second, and a FIFO of four still loses 0–29%.

| Semantics | Chips | Behaviour | Status |
|---|---:|---|---|
| **16 bits; a write while full is dropped, sets DROPPED and interrupts** | ~2½ | One transfer from any master; the event is in a ring; a drop is rare, and the receiver's scan finds it | **tentative** (Emily, 2026-10-17) |
| Claim, then write, 32 bits | ~4–6 | No message is dropped, but three transfers, a claim that a sender can hold, and a fall-back to a ring | **superseded** (it was tentative on 2026-10-16) |
| First write wins; later ones set an overflow bit, with no interrupt | ~2 | A drop goes unseen until someone looks | **not recommended** |
| A small FIFO of messages (Emily's alternative) | ~5 more | Writes queue and the handler takes them off; drops only when it is full | **an alternative**, if drops turn out to be common; measured, they are rare with the kernel at `SPL #6` |
| A mailbox word in memory for each fast level, and one source to a level | 0 | Three fast levels for three sources, and the handler reads memory | **superseded** (RFC 0027 as revised on 2026-10-16) |

### 11. Vectoring through the SWI entries

**tentative** (Emily, 2026-10-16).

- **The `SWI` vectors** already give 256 entries, and the microcode
  already works a vector out from a number: `SWI` puts its vector into a
  temporary register before it jumps
  ([RFC 0031, 9](0031-rfc-draft-2-cpu.md#9-exceptions-interrupts-and-trace)).
  The message level's entry can do the same with the source.
- **The cost** is sharing the numbers: a range kept for interrupt
  sources, privileged from user mode.
- **The alternatives:**
  - a vector table of the messages' own: another 1 KB of vectors and
    another offset;
  - a software jump on the source from level 7's vector: 3–4
    instructions, and no change to the microcode.

### 12. The vector base register

**decided** (Emily, 2026-10-16).

- **The problem:** RFC 0029's vectors are at physical 0, in the first
  CPU's RAM. A second CPU would fetch every vector, and every handler,
  over the bus from the first CPU's card, and both would have the same
  handlers.

| Design | Cost | |
|---|---|---|
| **A vector base register** | a special register, and an OR in the entry: in v2_hw no chips, and 18 control store words, since the traps' vectors are kept pre-ORed with it | **decided**; as the 68010's VBR. It also helps a hypervisor (RFC 0029's open question on virtualisation) |
| One table, shared | none | every exception of the second CPU goes over the bus |
| A private low page on each CPU card | ~2–3 chips per card | physical 0–4 KB means something different to each CPU, which DMA and debugging must remember |

### 13. The timer

- **A 32-bit count** (Emily, 2026-10-17), so that code can be timed with
  interrupts off, and a **one-shot** instead of a periodic tick, so that
  the kernel can be tickless. That is RFC 0009's timer, recommended there
  and the one Fen's board simulates, with a down counter in place of a
  32-bit compare register: about 5 chips against a comparator's 6 or so,
  and a 16-bit master loads it in one transfer.
- **Counting BCLK / 2** gives 120 ns, finer than any use of it so far,
  and the same time on every CPU, with no synchronising. The 74HC590
  can't count a 60 ns BCLK: TI's data sheet gives it 16 MHz at most at
  4.5 V over temperature, and beyond two stages its cascade ripples
  ([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#the-timer-a-snapshot)).
  Counting BCLK itself would take synchronous 74F161s and a register to
  read them through, about 5 chips more.
- **No drift:** the kernel works its deadlines out from the 32-bit
  count and loads the one-shot with the time left, so a late handler
  doesn't push the next deadline back.
- **The 74HCT193,** since the 74F193 looks obsolete, and nothing here
  needs F speed.

| Design | Chips | |
|---|---:|---|
| **A 32-bit count and a 16-bit one-shot** | ~11 | **tentative** (Emily, 2026-10-17) |
| A 32-bit count and a periodic tick from a jumpered bit | ~6½ | the design before; the card ≈ 13½ |
| A tick from a stage's carry only, bits 0–15 not readable | ~5½ | the card ≈ 12½ |
| A 32-bit count of BCLK and a snapshot register | ~11, without a one-shot | **not recommended**: the 74HC590 can't count it |

### 14. The lazy class

- **For events that can wait** until the next context switch: background
  work done (zeroed pages back in the pool, read-ahead filled, bulk
  writes finished), space free again in a terminal's output buffer,
  statistics, network frames under load.
- **It costs no chips:** a class in the routing table, a wake-me word for
  each ring, and a check in the scheduler, two local loads a ring.
- **The wake-me word** also lets the kernel move a ring between
  interrupts and polling as its load changes, as Linux's NAPI does for
  network cards and virtio's event index does for its queues.

### 15. The WINDOW bit

**Removed** (Emily, 2026-10-16) from the I/O bus's timing table
([RFC 0037, 17](0037-rfc-system-and-io-bus.md#17-the-timing-table)). It
did three jobs, which pulled against each other:

- **ownership,** guarding a device the I/O processor drives against a CPU.
  But it only guarded against a buggy kernel, which is trusted anyway, and
  the page map already keeps user processes out;
- **keeping slow devices off the system bus,** which is a rule about
  timing, not a permission;
- **and it stood in the way** of a panicking kernel printing on the
  console when the I/O processor's firmware is wedged, since the console
  belongs to the I/O processor.

Instead:

- **the window reaches every device,** and who owns a device is the card
  table's convention;
- **window writes are posted:** the I/O processor's card ends the bus
  transfer at once and makes the I/O access after it, and the next window
  access waits for it. So writes never hold the system bus;
- **slow devices are reached through the I/O processor's rings,** by
  convention. The window's cut-off of 200 I/O-bus clocks still bounds a
  read.

### 16. Cards on the system bus, and noticing INT lines

- **ATN0–ATN3** (**tentative**). With three or four cards on the system
  bus, four lines are enough. The other ways, for more cards:
  - interrupts as bus writes from cards that are masters;
  - a one-transfer poll for cards that aren't: in an acknowledge read,
    each card asking pulls down its own data bit, so one read says who.
- **Polling** (**tentative**) costs no chips and 5–10% of the I/O
  processor; change detection (**optional**) about 4 chips.

### 17. What changes elsewhere

| Where | Change |
|---|---|
| [RFC 0029](0029-rfc-draft-2-system.md) | VBR (section 4); vectors relative to VBR (6); `sr`'s bit 28 as M (2, tentative); section 7 points here |
| [RFC 0028](0028-rfc-draft-2-isa.md) | `SWI`s in the range kept for interrupt sources are privileged (tentative) |
| [RFC 0031](0031-rfc-draft-2-cpu.md) | Its open question 7: build the eight levels, IPL and `SPL`, VBR, and the message level's entry and registers. v2_hw has built them: about 18 packages on the core, and the suite's time unchanged ([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md)) |
| [RFC 0037](0037-rfc-system-and-io-bus.md) | Sections 8 and 9 point here, and section 9's table follows [section 3](#3-the-cpu-card); the WINDOW bit leaves section 17's table; section 20's window writes are posted |
| [RFC 0027](0027-rfc-io-coprocessor.md) | Sections 7.1, 7.3 and 7.4 point here |
| [RFC 0009](0009-rfc-ideas-io.md) | Its tickless timer returns, as the one-shot |
| Fen ([report 0036](0036-report-fen.md)) | As [section 7](#7-the-kernels-conventions) says |

### 18. Open questions

For Emily:

1. **The non-maskable interrupt:** its sources, and what it does to I and
   IPL (to be confirmed); raised at the card's `0x1000`, or by the control
   register's bit 3?
2. **VBR's number** among the special registers: 15, moving `bkpt`?
   v2_hw uses 15.
3. **The message level's registers:** a bank, 255 say, for about 2
   packages, but with the special registers read stale from it unless
   every `MTSR` writes both, and a bank lost to processes; or sixteen of
   their own, sharing the constants and special registers, for about 4.4,
   as v2_hw builds them
   ([cpu-costs.md](0040-rfc-interrupts/cpu-costs.md#the-message-levels-registers))?
4. **The `SWI` numbers kept for interrupt sources:** 128–255?
5. **The CPU card's offsets** of [section 3](#3-the-cpu-card), and which
   half of the `0x2000` group raises.
6. **How a CPU learns its region N** (to reach its own registers, and its
   CPU number) and BCLK's period, without board information: from the I/O
   processor's boot record in its RAM, or from an address that aliases
   its own registers, for a few gates. `0x7000_0000` can't be that alias,
   as it would hide CPU 0's registers from the others.
7. **Level 7 raised in the request register:** "scan the rings", sharing
   the handler for drops, or reserved?
8. **The control register written by its own CPU:** ignored, as
   proposed, or allowed?
9. **The timer's prescaler:** a fixed ÷2, or jumpered from ÷2 to ÷16, for
   ½ chip (or 1, with the setting readable in two spare status bits)?
   The count's period is then 120–960 ns, and it wraps in 8.6–69 minutes.
10. **The one-shot's clock:** bit 3 of the timer, 1.92 µs a count and
    126 ms at most, as proposed?
11. **A periodic tick** alongside the one-shot, and **the profiling
    tick:** fitted, at about ½ chip each?
12. **Defaults for batching and lazy deadlines.**
13. **Change detection** on the I/O processor, about 4 chips?
