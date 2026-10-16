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
- the message register, claimed by a read and then written;
- messages vectored through the `SWI` entries;
- four ATN lines from cards on the system bus;
- the I/O processor polling its INT lines at a tick;
- a register bank of its own for the message level.

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
                                             fast: claim the message register, write it
                                                    v
            CPU card: request register (levels 1-8), message register (level 7),
                      timer (level 6)
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
  sender and receiver, or in the message register's 24 bits. A level's
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
  **open**: 15, if `bkpt` (itself still open) moves.
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
  requests it while it holds a message
  ([3.2](#32-the-message-register)).
- **Its entry vectors on the message's source,** through the `SWI`
  entries: VBR + `0x100` + 4 × source. That gives up to 256 sources, each
  with a handler of its own, without a table of their own.
- **The message comes with it:** the entry copies the source into `r1`
  and the 24-bit message into `r2` of the handler's bank, then releases
  the register. How the microcode reaches its own card's register is
  RFC 0031's business.
- **Level 7 without a message,** from a write to the request register's
  bit 7, goes to level 7's own vector.
- **Sources and `SWI`s share numbers.** The kernel keeps a range for
  interrupt sources, tentatively 128–255, and an `SWI` from user mode in
  that range raises a privilege violation. `SWI` already has an entry per
  number in the decode ROM, so the check costs nothing.

#### 2.4 Banks

- **Exceptions and interrupts enter bank 0,** as in RFC 0029, except one.
- **The message level enters a bank of its own** (**tentative**, Emily,
  2026-10-16), so that its handler saves nothing. It pushes the PC and
  `sr` on that bank's `sp`. Which bank is **open**: 255, say, the last of
  Fen's thread banks.
- **`sr`'s bit 28,** reserved now, becomes M: set while in the message
  level's bank, kept in the `sr` an exception pushes, and restored by
  `RTI`. A level 8 interrupt during a message handler enters bank 0 as
  usual, and its `RTI` goes back to the message bank through M.

#### 2.5 The non-maskable interrupt

**To be confirmed.** As RFC 0029 has it: vector VBR + `0x04`, taken
between instructions whatever I and IPL, from the CPU's own card. Any
master can raise it through the card's control register: the I/O
processor's watchdog, or a debugger. What it does to I and IPL is open.
**Recommended:** the control register's NMI bit is a latch that the
entry clears, so that one write is one NMI, and the entry does what every
exception's does: it clears I and T and leaves IPL alone. Setting IPL to
8 as well would matter only to a handler that executes `EI`.

### 3. The CPU card

What every CPU card provides, among its registers at `0x7N00_0000` for a
card in region N
([RFC 0037, 5.1](0037-rfc-system-and-io-bus.md#51-addresses)). The
offsets are a proposal.

| Offset | Register | Access |
|---|---|---|
| `0x0000` | Control: RUN, RESET, STEP, NMI; status ([RFC 0037, 9](0037-rfc-system-and-io-bus.md#9-cpu-cards)) | read, write |
| `0x1000` | Board information: RAM size, BCLK's period, the region N (so the CPU's number), boot flags | read |
| `0x2000` | Request register, set: the levels whose bits are 1 are raised | write |
| `0x2004` | Request register, clear: the levels whose bits are 1 are lowered | write |
| `0x2008` | Request register: the levels requested | read |
| `0x3000` | Message register, claim | read |
| `0x3004` | Message register, the message | write |
| `0x3008` | Message register, release | write |
| `0x300C` | Message register, its contents | read |
| `0x4000` | Timer: the count | read |
| `0x4004` | Timer: clear the ticks, bit 0 the tick and bit 1 the profiling tick | write |
| `0x80_0000` + `0x2_0000` k | The control store's SRAM k, 64K × 16, halfwords, while RUN is off: k = 0–8 the microinstruction's 16-bit lanes, k = 9 the decode table ([RFC 0031, 6](0031-rfc-draft-2-cpu.md#6-the-bus-and-the-slave-port), whose slot-relative offsets predate RFC 0037) | read, write |

- **The CPU reaches its own card's registers locally,** without the
  system bus, so a handler never waits for the bus to clear its level or
  read the timer.
- **RESET** clears the request register, frees the message register and
  clears the timer.

#### 3.1 The request register

- **Eight bits, one per level.** A write to the set address raises the
  levels whose bits are 1, and a write to the clear address lowers them.
  No writer reads it first, so any number of writers can't collide.
- **Any master** can write it: the I/O processor for its events, another
  CPU, or the CPU itself, for deferred work.
- **A level is requested** while its bit is set, or while one of the
  card's own sources for it is: the timer at 6
  ([3.3](#33-the-timer)), the message register at 7
  ([3.2](#32-the-message-register)), and an optional profiling tick at 8.
- **Parts:** about 1–2 chips.

#### 3.2 The message register

**tentative** (Emily, 2026-10-16).

| Bits | |
|---|---|
| 31–24 | The source: which handler ([2.3](#23-the-message-level)) |
| 23–0 | The message: anything, such as a page-map entry's number, a request's tag or a ring's index |

It is free, claimed or full:

- **Claim:** a read of the claim address returns 0 and makes a free
  register claimed, or returns 1, changing nothing, if it is already
  claimed or full. That is one bus transfer, so it is atomic without
  LOCK.
- **The message:** a write to the message address while it is claimed
  stores the message. A 32-bit master writes it in one transfer. A 16-bit
  master, such as the I/O processor, writes the low half (the halfword at
  `0x3004`, bits 15–0) and then the high half (`0x3006`, bits 31–16), and
  the high half's write completes it. Then the register is
  full and requests level 7.
- **A write to the message address** while the register is free or full
  is ignored.
- **Release:** a write to the release address frees it, and its request
  for level 7 ends. The message level's entry releases it once it has
  copied the message.
- **If the claim returns 1,** the sender sends its event the slow way
  ([4.4](#44-delivery)), or tries again shortly.
- **The bus has no master IDs,** so the card can't tell who claimed it.
  Only the claimant writes, by convention. A sender that claims and never
  writes holds the register until a release.
- **Parts:** about 4–5 chips: the 32-bit register, the two state bits,
  the decode and a read path.

#### 3.3 The timer

The hardware session's design.

- **A 32-bit counter of BCLK,** free-running and cleared by RESET. Every
  card counts the same clock from the same reset, so every CPU reads the
  same time.
- **At a 60 ns BCLK** it counts in 60 ns and wraps every 4.3 minutes. The
  kernel extends it in software at each tick.
- **The tick:** a jumper picks counter bit n. Each 0→1 edge of that bit
  sets the tick flag, which requests level 6 until a write clears it. Bit
  n ticks every 2ⁿ⁺¹ clocks: at 60 ns, bit 16 every 7.9 ms (about 127 Hz)
  and bit 17 every 15.7 ms.
- **A profiling tick** (**optional**): a second jumper and flag, onto
  level 8, so that the PC can be sampled even inside message handlers.
- **Reading:** one word read of all 32 bits. How it stays consistent
  while the counter carries is **open**: a snapshot latched as the read
  starts, or reading the high half twice.
- **BCLK's period** is in the board information, for the kernel to scale
  the count.
- **No compare register:** a deadline finer than the tick is a request to
  the I/O processor ([4.5](#45-requests-for-time)).
- **Parts:** about 4–6 chips.

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

#### 4.4 Delivery

- **To one of its own tasks:** it clears that task's wait.
- **Lazy:** it writes the event into the CPU's event ring and sets no bit.
  If the ring's wake-me word is set, or the event is older than its
  deadline, it sends it as slow instead.
- **Slow:** it writes the event into the ring, then the level's bit to
  the set address of that CPU's request register. It may hold the bit
  back for the source's batching time, to post several events with one
  interrupt.
- **Fast:** it claims the CPU's message register and, if it gets it,
  writes {source, message}. If not, it sends the event as slow.
- **Masking:** it masks the source from then until its owner says it has
  been served: one of its tasks by waiting again, a CPU's driver by a
  request. So each source has at most one event outstanding.

#### 4.5 Requests for time

A deadline finer than the CPU's tick, such as "interrupt me at t", is a
request on the kernel's ring. The I/O processor answers it at t, to
within its polling tick, with a slow or fast event as the request asks.
(Proposed.)

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
  later (its RUN bit) runs a short stub there, which reads its region
  from the board information, sets its VBR and jumps to its own code.
- **Time agrees** across CPUs ([3.3](#33-the-timer)).
- **CPU to CPU:** slow, an event in the pair's ring and level 5 on the
  receiver; fast, the receiver's message register.
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
  6, now periodic (Fen counts levels from 0, after its board's mask bits,
  so it calls these 6 and 5); its board's devices move behind the I/O
  processor; it drains its lazy rings; and each CPU sets its VBR.

### 8. Latency

| From | To | About |
|---|---|---|
| A device's INT | The I/O processor seeing it | up to 10 µs, its polling tick |
| The I/O processor seeing an event | A CPU's level bit, or its message | 2–3 µs: the routing and a bus write |
| … with another master holding the bus | | up to about 1.5 µs more (VRAM reads, locked sequences), or about 12 µs for a window read of a slow device |
| A doorbell | The I/O processor reading the ring | 1–3 µs, the slice it is in |
| A message | Its handler running, even over the kernel's critical sections | the CPU's entry, perhaps 5–10 µs (*estimate*) |
| A slow level | A user-level driver running | 85–107 µs ([report 0020](0020-report-operating-system.md#interrupts-and-devices)'s 500–640 cycles at Fen's 6 MHz), up to about 1 ms while the kernel holds slow levels off ([report 0036](0036-report-fen.md#3-what-it-costs)) |
| A lazy event | The kernel seeing it | up to a tick, 8–16 ms, or sooner at a context switch |

Measured in Fen, which holds interrupts off throughout its kernel: a
slow interrupt arriving at a random moment waits about 145 µs on average
at the shell and 0.7 ms on the desktop, but up to 46 ms while a large
`vm_alloc` zeroes its pages; Fen takes at most about 500 interrupts a
second; and a lazy event waits a few milliseconds while the machine is
busy ([fen-latency.md](0040-rfc-interrupts/fen-latency.md), with the
numbers in [fen-latency-results.md](0040-rfc-interrupts/fen-latency-results.md)).

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
  to fixed levels, and that ARM's two masks would save a few chips. Eight
  real levels give:
  - software interrupts at a low level for deferred work;
  - a level for each kind of event, so a handler knows the source without
    looking;
  - the timer above the drivers' events, so `SPL #4` lets it in;
  - room for later local sources: a profiling tick, a performance
    counter, a parity error;
  - no change to RFC 0029, `SPL` or Fen.

| Design | Chips on the CPU | The instruction set | Status |
|---|---|---|---|
| **Eight real levels** | as RFC 0029 needs them | unchanged | **decided** |
| Eight in the instruction set, three wired at fixed levels | about the same | unchanged | **not recommended**: no saving |
| Two masks, as ARM's IRQ and FIQ | a few fewer | IPL and `SPL` go; an F bit in `sr` | **not recommended** |

### 10. The message register

- **What it gives:** one bus write, or two for a 16-bit master, carries
  both the interrupt and its message. The handler reads the message
  locally and is vectored by its source.
- **Why claim, then write:** the bus has no master IDs, so the card can't
  tell writes from different senders apart. A read, though, is atomic, so
  a read can claim the register. The claimant then writes alone, even in
  two halves.
- **Slow events never use it.** They come in bursts that would keep it
  full, so fast senders would keep failing their claims. Rings queue any
  number of events, and batch them.
- **How often a claim fails** depends on how the kernel holds
  interrupts off, more than on the register. Measured against Fen's
  spans ([fen-latency.md](0040-rfc-interrupts/fen-latency.md#busy-claims-depend-on-the-kernel-not-on-the-fifo)):
  with a kernel at `SPL #6`, under 1% of claims fail even at 10,000 fast
  events a second; with Fen's kernel as it is, 6–39% at 1,000 a second,
  and a FIFO of four still loses 0–29%.

| Semantics | Chips | Behaviour | Status |
|---|---:|---|---|
| **Claim, then write** | ~4–5 | No message is lost; a busy claim falls back to a ring | **tentative** |
| First write wins; later ones set an overflow bit | ~3–4 | One transfer, but a dropped message's sender never learns of it, so the message must be in memory too | **not recommended** |
| A small FIFO of messages (Emily's alternative) | ~5 more | Writes queue and the handler takes them off; no claim; messages are dropped only when it is full | **an alternative**, if busy claims turn out to be common; measured, they are rare with the kernel at `SPL #6` |
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
| **A vector base register** | a special register, and an OR in the entry | **decided**; as the 68010's VBR. It also helps a hypervisor (RFC 0029's open question on virtualisation) |
| One table, shared | none | every exception of the second CPU goes over the bus |
| A private low page on each CPU card | ~2–3 chips per card | physical 0–4 KB means something different to each CPU, which DMA and debugging must remember |

### 13. The timer

- **Periodic, not tickless.** A counter and a jumper instead of a compare
  register: a few chips fewer. Deadlines finer than a tick go to the I/O
  processor, which has a timer of its own.
- **Counting BCLK** gives 60 ns resolution, close to counting cycles, and
  the same time on every CPU, with no synchronising.
- **Against** RFC 0009's tickless timer, recommended there, and the one
  Fen's board simulates. Fen already counts the ticks it missed from the
  counter, so a periodic tick is a small change for it.

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
| [RFC 0031](0031-rfc-draft-2-cpu.md) | Its open question 7: build the eight levels, IPL and `SPL`, VBR, and the message level's entry and bank |
| [RFC 0037](0037-rfc-system-and-io-bus.md) | Sections 8 and 9 point here; the WINDOW bit leaves section 17's table; section 20's window writes are posted |
| [RFC 0027](0027-rfc-io-coprocessor.md) | Sections 7.1, 7.3 and 7.4 point here |
| [RFC 0009](0009-rfc-ideas-io.md) | The tickless timer gives way to this one |
| Fen ([report 0036](0036-report-fen.md)) | As [section 7](#7-the-kernels-conventions) says |

### 18. Open questions

For Emily:

1. **The non-maskable interrupt:** its sources, and what it does to I and
   IPL (to be confirmed).
2. **VBR's number** among the special registers: 15, moving `bkpt`?
3. **The message level's bank:** which one, 255 say? And the message in
   `r1` and `r2`?
4. **The `SWI` numbers kept for interrupt sources:** 128–255?
5. **The CPU card's register offsets** of [section 3](#3-the-cpu-card).
6. **Reading the timer consistently:** a snapshot, or reading twice?
7. **The tick's default jumper:** bit 16, about 127 Hz at 60 ns?
8. **Defaults for batching and lazy deadlines.**
9. **Change detection** on the I/O processor, about 4 chips?
10. **Requests for time** from the I/O processor ([4.5](#45-requests-for-time)),
    in place of a compare register?
