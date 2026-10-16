---
number: 20
type: report
title: An operating system for Heron, what the hardware should give it and what it could be
status: current
date: 2026-10-14
context:
  studies: [kernel, v1_isa, c_compiler, lisp, egret, graphics]
  commit: 8828750
---

# Report 0020: An operating system for Heron

Two questions:

1. **What should the hardware give an operating system?** Both the big
   features (modes, an MMU, interrupts, DMA) and the details that decide
   what an operating system's hot paths cost.
2. **What should the operating system be like?** Not only a small Unix:
   which kinds of system suit a computer of this shape, and what they
   would need.

To answer the first with numbers rather than guesses, the
[kernel study](../studies/kernel/README.md) built three things:

- **v1bs** ([the appendix](#appendix-v1bs-draft-1b-with-system-extensions)):
  draft 1b with a supervisor mode, register banks, the flat page map of
  [RFC 0010](0010-rfc-ideas-os.md#3-mmu), loads and stores across
  modes, and precise page faults, as an ISA variant of the draft 1
  simulator.
- **A benchmark nucleus**: a small message-passing kernel in 1b assembly,
  written three times, once per register-banking policy, with every hot
  path an operating system has: system calls, thread switches, calls
  between processes, notifications, an io_uring-style ring, timer
  preemption, interrupts handed to user-level drivers, demand-zero page
  faults and map refills.
- **Small routines** on plain 1a and 1b (zeroing and copying pages,
  dynamic linking, user-level thread switches, the scheduler in C), and
  the **page references** of the other studies' bigger programs (the
  Lisp compiling on the machine, Egret's JIT, the window manager).

Cycles are for D32-separate, the configuration of the draft 1b hardware
([report 0012](0012-report-draft-1b-hardware.md)), and times are at
3 MHz. The full tables are in
[performance.md](0020-report-operating-system/performance.md), written by
`heron kernel report --write`.

## Short version

**What things cost.** On Heron a trap is cheap and copying is dear:

| | Cycles | At 3 MHz |
|---|---:|---:|
| A procedure call and return | 8 | 2.7 µs |
| A switch between two user-level threads (coroutines) | 52 | 17 µs |
| A null system call | 39 | 13 µs |
| A yield to another process | 207–257 | 69–86 µs |
| A call and its reply between two processes | 293–390 | 98–130 µs |
| Copying one 32-bit word (an unrolled loop) | 9.5 | 3.2 µs |
| Zeroing a 4 KB page | 4,622 | 1.5 ms |
| A demand-zero page fault | 4,753 | 1.6 ms |

The ranges are the three banking policies, from best to worst. A system
call costs five procedure calls and a round trip between processes
35–50, and that round trip costs about as much as copying 30–40 words.
So the structure of an operating system (traps, switches, messages) is
affordable here, and anything that copies data is not.

**Hardware, in order of what it buys for what it costs:**

1. **A supervisor mode** with a banked `sp`, privileged instructions and
   precise faults that report the address and the reason. Without these
   there is no protection; they are a few chips and microcode.
2. **Register banks** in the register file's spare SRAM (it has 15
   address lines; draft 1b uses 5). With every thread's registers in a
   bank of their own, a call and reply between processes takes 25% fewer
   cycles (293 against 390), a timer preemption 41% fewer (147 against
   249), and the nucleus never saves a register on a system call. About
   4–6 chips.
3. **The flat page map** of RFC 0010 (16 contexts of 16 MB in 4 KB
   pages), with the PC's physical page held in a register so the map
   stays off the instruction fetch, which sets the clock. Translation
   misses are not the question: the other studies' bigger programs touch
   up to 223 pages, and a 256-entry translation cache would see only
   their first touches.
4. **Two flag bits, XL and XS,** that make the supervisor's loads or
   stores go through the user's map (the 68010's `MOVES`, without a new
   instruction): copying to and from user memory runs at full speed with
   any instruction, and a bad pointer is just a page fault.
5. **A vectored `SWI`** (the decode ROM sends `SWI #n` to its own
   entry): 16 of a null system call's 39 cycles are the dispatch.
6. **A block move**, or loads and stores of several registers through
   any base register: zeroing a page drops from 4,622 cycles to 2,708
   with `SAVE` standing in for it, and copying one from 9,746 to 6,184.
   [Report 0019](0019-report-graphics.md) wants the same for graphics.
7. **Devices that buffer, and DMA**: handing an interrupt to a
   user-level driver costs 500–640 cycles, so a terminal interrupting
   for every character at 9,600 baud would take 17% of the machine.

**The operating system.** Heron is about as fast as a VAX-11/780 or a
68000 workstation, and machines of that class ran timesharing Unix, VMS,
QNX, AmigaOS, Smalltalk and the Lisp machines' systems. Of the designs
surveyed below, the one that fits best is **a small message-passing
nucleus, with every resource a file server speaking one protocol and
assembled into per-process name spaces as in Plan 9, and asynchronous
I/O through rings of requests and completions**. It suits the hardware
(cheap traps and switches, banks, expensive copies), the machine's
place next to a PC and an ECL number cruncher, and its Lisp and Egret,
which can live in it as worlds of their own. A Unix-like library goes on
top for C programs. A single-address-space, persistent object system
built on the Lisp or Egret is the most interesting alternative, and the
hardware above serves it too.

## What was built

- **v1bs** adds no opcodes but two system-group functions (`MFUR` and
  `MTUR`, move from and to a user register) and seven special registers
  (`far`, `fsr`, `ctx`, `mapa`, `mapd`, `bank`, `sysctl`). The flags
  word gains S, XL and XS. Its three banking policies, chosen with
  `sysctl`:
  - **none**: only `sp` is banked by the mode (as on the 68000);
  - **half**: every thread has its own `r8`–`r15`, the supervisor too,
    and `r1`–`r7` and `HI` are shared (ARM's FIQ mode banks `r8`–`r14`
    the same way);
  - **full**: every thread has its own `r1`–`r15` and `HI`, and the
    supervisor has bank 0.
- **The nucleus** is 1,200 lines of 1b assembly, with each banking
  policy's code in its own `.if` blocks. It is in the style of L4 and
  QNX: one thread per process, synchronous call, receive and
  reply-and-receive with a four-word message in registers, notification
  bits (`notify`, `wait`), 32 priority queues found with `CLZ`, the
  nucleus running with interrupts off on a 128-byte stack per thread.
  Processes come from a boot table; there is no file system or loader.
- **The measurements** run every scenario with n and 2n iterations and
  take the difference, so booting cancels out, and attribute each
  instruction's cycles to the routine it is in. The write scenarios
  check what reaches the console.
- **Checked:** the nucleus runs every scenario on every policy with the
  right output; unit tests cover v1bs's semantics (privilege, precise
  faults, the bank policies, XL and XS) in Rust and Python.

## Part 1: what the hardware should give

### The paths, measured

| Operation | none | half | full |
|---|---:|---:|---:|
| Null system call | 39 | 39 | 39 |
| Yield to another process | 257 | 207 | 222 |
| Call and reply between processes | 390 | 293 | 347 |
| Timer preemption (nucleus only) | 249 | 203 | 147 |
| Interrupt handed to a user-level driver (nucleus only) | 640 | 545 | 503 |
| Demand-zero page fault | 4,755 | 4,753 | 4,753 |
| Map refill from a page table (nucleus only) | 103 | 85 | 85 |

Where a null system call's 39 cycles go: the user's loop (5), taking the
trap (6), the vector's `JMP` (3), dispatching on the number (16) and the
handler with its `RTI` (9). A call and reply between processes, with
half banks, is 63 instructions in the nucleus: two traps, two
dispatches, the bookkeeping in `call` (74 cycles) and `reply_recv`
(59), and two switches (39 each), which load the next thread's stack
pointer, bank and map context.

On D32-wide (a 32-bit bus with a prefetch buffer, the likely draft 2
hardware) every path takes 53–68% of these cycles: a null system call
26, a call and reply 174 with half banks.

### Protection: modes and the stack

The minimum is the list in [RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system),
and the nucleus confirms it: a supervisor bit in the flags word, a
supervisor stack pointer the trap switches to before it pushes, `HALT`,
`EI`, `DI`, `RTI` and the system registers trapping in user mode, and
user-mode `MTF` changing only N, Z, C and V.

Two details matter:

- **Keep S out of `MTSR`'s reach.** The nucleus clears XL by writing
  the flags back, and an early version wrote a word without S, dropping
  into user mode in the middle of a system call. The 68000 has the same
  trap. Only a trap and `RTI` need to change S.
- **The trap frame says where the trap came from.** The page-fault
  handler must know whether it interrupted user code or the nucleus
  itself (copying with XL on), because that decides what it has to save.
  The saved flags word's S bit tells it; the nucleus reads it from its
  stack.

### Register banks

The register file is eight 32K × 8 SRAMs, two copies of 32 entries.
Banks cost the bank number register, the gating that forces bank 0 in
supervisor mode, and a microinstruction bit that lets `MFUR` and `MTUR`
reach the user's bank from supervisor mode: about 4 chips for full
banks. Half banks also gate the bank lines with bit 3 of the register
number, after the register-file address multiplexers, which adds a gate
(~15–20 ns) to the register read path; full banks add nothing to any
path, since the bank lines are steady through the cycle. The constants
the reset routine writes into entries 24 and 25 have to be pinned to
one bank.

What each policy saves, and what it costs:

| | none | half | full |
|---|---|---|---|
| A system call saves | nothing (the ABI lets it clobber `r1`–`r7`) | nothing | nothing |
| A blocking system call saves | `r8`–`r14`, the user `sp` | nothing | nothing |
| An interrupt that switches saves | `r1`–`r14`, `sp`, `HI` | `r1`–`r7`, `HI` | nothing |
| A message passes | in the registers | in the registers | copied bank to bank with `MFUR`/`MTUR` |
| A woken thread's results go | to its TCB, then its registers | the same | to its TCB, then into its bank with `MTUR` |
| The nucleus keeps | nothing in registers | `r8`–`r14` | everything |

- **Half banks are best for messages.** The four-word message stays in
  `r2`–`r5` across the switch, and the nucleus keeps the current thread
  in `r14` between traps. Call and reply: 293 cycles.
- **Full banks are best for interrupts.** Nothing is saved, so a
  preemption is 147 cycles, but every message and every result has to
  be copied into another bank, which makes calls (347) and yields (222)
  dearer than with half banks.
- **None** pays for both: 390 and 249.

**Recommendation:** banks, with the policy selectable (it is a gate or
two more than either alone), or, if only one, half banks for a
message-passing system. A microcoded "move the message to bank n"
would take most of full banks' copying cost away.

A bank number of 8 bits gives 256 threads their own registers, about as
many threads as 1 MB will hold. Beyond that a thread's registers can
be saved to memory when its bank is reused, as contexts are.

### System calls

- **A vectored `SWI`.** Today `SWI` goes to one vector, and the handler
  reads the number (v1bs latches it in `fsr`; plain 1b leaves it in the
  instruction at `PC − 2`, which in user mode means reading user
  memory), checks it and jumps through a table: 16 of a null call's 39
  cycles. If the decode ROM sent `SWI #n` straight to `0x100 + 4n`, a
  null system call would be about 23 cycles. The Macintosh's A-line
  traps did the dispatch in software; here it is a decode ROM table.
- **A system call is a procedure call.** With `r1`–`r7` caller-saved in
  the C convention, the nucleus can use them without saving them, and
  with banks it saves nothing at all.
- **The trap itself** (pushing the PC and the flags) is 6 cycles in the
  timing model; switching to the supervisor's stack or bank adds no
  cycles, since it is an address line.

### Translation: the page map

**The workloads.** The simulator counted every page reference (4 KB
pages) of the biggest programs the other studies have:

| Program | Pages: code + data | PC page changes per 1,000 instr. | Misses per 1,000 instr., LRU 16 / 32 | Direct-mapped 64 / 256 |
|---|---:|---:|---|---|
| Lisp: compile and run boyer | 19 + 211 | 25.6 | 1.59 / 0.09 | 13.5 / 0.01 |
| Lisp: boyer, interpreted | 4 + 202 | 3.9 | 0.23 / 0.06 | 25.0 / 0.00 |
| Egret: richards, JIT | 23 + 61 | 24.5 | 2.07 / 0.02 | 2.1 / 0.01 |
| Egret: json, interpreted | 12 + 174 | 25.9 | 9.49 / 0.04 | 34.1 / 0.01 |
| Graphics: window manager, 8 bits | 8 + 102 | 11.9 | 1.31 / 0.74 | 5.1 / 0.02 |

(*LRU n*: a fully associative translation cache of n entries; *direct-mapped
n*: n entries indexed by the low bits of the page number. Never flushed,
so these are one program's own misses. More programs in
[performance.md](0020-report-operating-system/performance.md#page-references-of-bigger-programs).)

- **Programs use all of memory.** The Lisp's two semispaces and Egret's
  heaps fill the 1 MB machine: over 200 pages.
- **A small cache misses a lot; a modest one hardly at all.** A
  direct-mapped cache of 64 entries misses up to 34 times per 1,000
  instructions; one of 256 entries misses only on first touches. A
  fully associative one needs 32 entries, and a fully associative cache
  in TTL is a comparator per entry.
- **Refilling in software costs 85 cycles** with banks (103 without):
  the trap, reading `far`, indexing a page table, writing the map,
  `RTI`. At 34 misses per 1,000 instructions that would add 70% to
  Egret's interpreter; a refill walked in microcode, about 10 cycles,
  would add 8%. With 256 entries either is negligible.

So the flat map's 64K entries are, for this machine, an infinitely large
translation cache, and the choice between it and a cache of page tables
in memory is about something else:

| | Flat map (RFC 0010) | Tagged cache of page tables |
|---|---|---|
| Virtual space | 16 MB per context | 4 GB |
| Address spaces | 16 at once; more by reloading a context | as many as the tag has bits for |
| Page tables in memory | none (the map is the page table) | yes |
| Misses | none | first touches, conflicts |
| A context switch | one `MTSR` | one `MTSR` (the tag) |
| Reusing a context | ~7 cycles per page the old and new process have mapped | nothing |

16 MB per process is plenty for a machine with 1–16 MB, and reusing a
context costs about 800 cycles for a 60-page process. The flat map is
the right first step, as RFC 0010 says, and the same SRAM can become a
tagged cache later if a single address space of 4 GB is wanted
([below](#a-single-address-space-persistent-world)).

**Keeping the map off the clock.** The fetch path (RAM, decode ROM, next
address, microcode ROM) is the 1b hardware's critical path at 309 of
334 ns ([report 0012](0012-report-draft-1b-hardware.md)); a 55 ns map
SRAM in it would make the clock 9% slower. Data accesses have room to
spare: their data only has to reach T by the end of the cycle, and it is
on the data bus about 140 ns into it. So:

- **Translate data addresses through the map**, from MAR. A fault
  (invalid, write-protected) must reach the next-address logic by about
  240 ns into the cycle, as an address error does now; with a 55 ns map
  it can. This needs checking with the timing analysis, which this study
  didn't do.
- **Give the PC its physical page in a register**, loaded from the map
  whenever the PC leaves its page: a sequential carry out of bit 11, or
  a jump to another page (a 12-bit comparison, two 74HCT688). The PC
  changes page 4–26 times per 1,000 instructions in the workloads, so a
  cycle each time is under 1%.

**Cross-mode loads and stores** (XL and XS) worked as hoped. `write`
copies the user's buffer with `MOV r5, byte [r1]+` after setting XL, at
the same 13 cycles a byte as any copy, and a bad buffer address is an
ordinary page fault with the "cross" bit in `fsr`. Two bits rather than
one, because a copy loop reads one side and writes the other. What they
can't do is copy between two processes that aren't running; the
nucleus would translate those addresses itself, by reading the map
(supervisor mode is physical), or the processes share pages.

**Referenced and dirty bits** in software (map read-only, take the first
write's fault) cost a fault each, about 100 cycles: cheap next to
writing the page back to a CompactFlash card (~9 ms per 4 KB by polled
I/O, [RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)).

### Zeroing and copying

A demand-zero page fault is 4,753 cycles, and 4,619 of them are zeroing
the page. Copying is twice that. On 1b, per 4 KB page:

| | Zero | Copy |
|---|---:|---:|
| Unrolled loop | 4,622 | 9,746 |
| `SAVE` / `RESTORE` of 14 (zero) or 12 (copy) registers through `sp` | 2,708 | 6,184 |
| The 16-bit bus's limit (one bus cycle per halfword) | 2,048 | 4,096 |
| D32-wide: unrolled / with `SAVE` / the bus's limit | 2,441 / 1,436 / 1,024 | 5,516 / 3,523 / 2,048 |

1a is the same with `SAVE`/`RESTORE` and 8% slower unrolled.

- **A store- and load-multiple through any register** (draft 1's
  `SAVE`/`RESTORE` with a base other than `sp`) gets most of the way to
  the bus's limit. A microcoded block fill and copy (an interruptible
  `REP MOVS`, RFC 0006) would reach it.
- **Fork is expensive:** copying a 64 KB process eagerly is 156,000
  cycles (52 ms), and copy-on-write still copies each page written. An
  operating system for Heron should create processes by spawning a
  program, not by copying one.
- **Zero pages in advance**, when the machine is idle, or with DMA: the
  tick-level RAM sharing of [RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory)
  would let a bus master clear pages while the CPU runs.
- **The nucleus can't take interrupts while it zeroes** a page with
  interrupts off: 1.5 ms of latency. A real kernel zeroes with
  interrupts on, or ahead of time.

### Interrupts and devices

- **Preemption costs 147–249 cycles** of nucleus time per tick: 0.5–0.8%
  of the machine at 100 Hz.
- **Handing an interrupt to a user-level driver costs 503–640 cycles**:
  the nucleus takes the interrupt, saves the running thread, signals the
  driver, switches to it, and later switches back. At 9,600 baud, an
  interrupt per character is 960 a second, or 17% of the machine; a
  terminal multiplexer with eight lines would take all of it. Ethernet
  frames by programmed I/O are worse.
- **So the devices should buffer:** UARTs with FIFOs (the 16C550
  recommended in RFC 0009 has 16 bytes), and DMA with descriptor rings
  for the disk and the network, so an interrupt means a buffer, not a
  byte. This matters more for a microkernel than a monolithic kernel,
  but it matters for both.
- **Prioritised, vectored interrupts** (RFC 0009's encoder and vector,
  ~3–4 chips) give each device its own entry, and with banks each
  priority level could have a bank of its own, so an interrupt handler
  saves nothing.
- **A thought: interrupts straight to a bank.** If a bank held a
  thread's PC and flags as well as its registers, an interrupt could
  switch to the driver thread's bank in user mode with no nucleus code
  at all, as the Xerox Alto switched between its microcode tasks for
  each device. The nucleus would only decide which banks may run. That
  turns the 500-cycle path into tens of cycles; it would cost moving the
  PC (74HCT161 counters in the 1b hardware) to and from the register
  file on a switch.
- **DMA bypasses the map.** Any bus master can write anywhere in the
  CPU's RAM through its slave port ([RFC 0014](0014-rfc-system-bus.md)),
  so a user-level driver that can start DMA owns the machine. A window
  register in the slave port (base and limit, two comparators, ~3–4
  chips) that only the supervisor sets would confine each master.

### Asynchrony: rings against traps

The io_uring idea (a ring of requests the kernel reads, and a ring of
completions it writes, shared with the process) was measured three ways,
writing 16-byte lines to the console:

| How | Cycles per write |
|---|---:|
| `write`: one system call, the nucleus copies to the console | 273 |
| Through the nucleus's ring, 8 / 32 requests per system call | 423 / 413 |
| A call to a user-level console server (half banks) | 479 |
| Through a ring to the user-level server, 1 / 8 / 32 per notify | 1,123 / 454 / 382 |

- **Batching system calls doesn't pay on Heron.** A trap is 39 cycles;
  filling in a request (four stores), the nucleus reading it, and
  posting and reading the completion cost more, about 140 cycles a
  request. On a modern processor a system call is expensive (mode
  switches flush pipelines and pollute caches) and batching pays; here
  it doesn't.
- **Rings pay between processes.** One `notify` per batch instead of a
  call per request: from about 8 requests a batch the ring to a server
  beats calling it, and at 32 it comes within 40% of the monolithic
  system call.
- **What rings are really for is asynchrony:** submit, keep working,
  collect the completions later, from one place for every kind of I/O.
  The hardware's own interfaces should be rings too: a DMA engine that
  takes descriptors from a ring and writes completions to another can
  have its rings mapped straight into a user-level driver.
- **Threads inside a process are cheap:** a switch between user-level
  threads (save `r8`–`r14` and `sp`, restore the other's) is 52 cycles,
  a quarter of a yield through the nucleus. An async runtime, coroutines
  or `async`/`await` should switch in user space and use the nucleus only
  to wait for completions.

### Dynamic linking

Calling a function, and loading a global, the ways a linker can wire
them up (cycles over the loop alone):

| | 1a | 1b |
|---|---:|---:|
| Direct call | 8 | 8 |
| Through an import table entry (Windows' IAT) | 14 | 12 |
| Through a PLT stub and the GOT (ELF) | 16 | 13 |
| Through a table at a base register (AmigaOS libraries, COM) | 13 | 12 |
| A virtual call: object, table, function | 18 | 17 |
| Global at an absolute address | 6 | 6 |
| Global PC-relative | 9 | 6 |
| Global through the GOT | 14 | 11 |
| Global at a base register | 5 | 6 |

- **Dynamic linking is cheap here:** 4–5 cycles a call over a direct
  one on 1b, 5–8 on 1a. 1b's `CALL [mem]` makes an import table one
  instruction; 1a needs a load and `CALL r`.
- **Position-independent data is free on 1b** (`[pc + d16]`) and costs
  3 cycles a load on 1a (`LEA`, then the load).
- **The Amiga way suits Heron:** a library is a table of entry points
  and its own data, reached through a base register; calls through the
  table cost what an import table does, its data costs nothing extra,
  there is nothing to relocate, a library can have one base per process
  that opens it, and versions are checked by the table's length when
  it's opened. Windows' import tables filled in at load time are the
  other good choice. ELF's PLT, with its lazy binding and GOT, is the
  most expensive and the most complicated.
- With the flat map, every shared library can sit at the same address
  in every process, so none needs relocating at all.
- **Windows-style interfaces** (COM: an object with a table of functions,
  versions by asking the object for an interface by name, handles for
  everything the system owns) cost a virtual call, 17 cycles on 1b: fine
  for system interfaces, though not for inner loops. They suit a system
  whose servers and libraries should keep working across versions.

### The rest

- **Timers.** The draft 1 timer is periodic. A free-running counter in
  microseconds (32 bits last 71 minutes; 48 bits forever) and a compare
  register that interrupts once give a tickless kernel and timeouts
  without polling, ~4–6 chips. The cycle counter at 50 MHz wraps in 86 s.
- **Atomics.** On one CPU, the nucleus runs with interrupts off, and user
  code can use restartable sequences (the nucleus restarts a thread
  preempted inside a marked sequence) with no hardware at all. Between
  the CPU and the ECL cruncher, the bus's semaphore registers and
  doorbells ([RFC 0014](0014-rfc-system-bus.md)) are enough.
- **Writing the nucleus in C** would cost about 1.5 times as much: the
  ready queue (an enqueue and a dequeue) is 99 cycles compiled and 64 by
  hand. The compiled code calls a function for `CLZ`, reloads globals,
  and shifts by a register count, which costs a step per bit. A kernel
  in C wants intrinsics (`CLZ`, the special registers, `MFUR`/`MTUR`) and
  an interrupt-handler attribute; its trap entry and exit, and the IPC
  path, stay in assembly.
- **1a or 1b?** The extensions are special registers, flag bits and two
  system-group functions, so they fit either. Kernel code is mostly
  loads and stores of control-block fields at small offsets: 1a's
  one-parcel `[r + 4o]` (offsets up to 60) would encode most of the
  nucleus's field accesses in one parcel, where 1b needs an extension
  parcel for each, a cycle apiece on D32-separate. In the small
  routines 1b is 8% faster in unrolled loops and 1–3 cycles faster on
  calls through tables; the nucleus wasn't ported to 1a to compare.
- **Debugging:** the trace bit and breakpoint register of RFC 0010 and
  RFC 0005, per thread (the trace bit in the flags word, saved with the
  thread), give a `ptrace`-style debugger for user processes.
- **Security** beyond protection itself: the X bit makes stacks and heaps
  non-executable, at the cost of a map change when the Lisp or Egret
  writes code (write it, then map it executable); guard pages catch
  stack overflows (and save the Lisp 5% of its cycles, [report
  0018](0018-report-lisp.md)); handles to threads are checked indexes
  into a table, not addresses. Heron has no caches and no speculation,
  so the timing side channels that plague modern processors mostly don't
  exist, and its RAM is static, so there is no Rowhammer.

### What was hard

Writing the nucleus turned up these:

- **Knowing what to save.** Without banks, the nucleus can't look at
  anything before it has saved registers to look with, and every path
  that returns to the same thread must keep the callee-saved registers
  it touched: the reply-and-receive path that finds callers waiting
  first clobbered the caller's `r8` and `r9` through a call to
  `enqueue`. Banks remove the whole class.
- **Two kinds of trap frame.** A thread that blocked in a system call
  needs only some registers back; one that was preempted needs all of
  them. The nucleus records which in the thread's control block and
  restores accordingly. With full banks there is only one kind.
- **Results for a thread that isn't running** have to be put somewhere:
  its control block (none, half) or its bank (full, with `MTUR` after
  selecting it).
- **Faults inside the nucleus.** Copying with XL on, a page fault
  interrupts the nucleus itself, which with banks shares the nucleus's
  registers; the handler must check the saved S bit and save what it
  uses. A trap in supervisor mode could get a bank of its own.
- **`MTSR flags` clearing S** ([above](#protection-modes-and-the-stack)).
- **One draft 1b instruction can't be restarted:** `CALL` through an
  auto-incremented or auto-decremented operand (`CALL [r]+`) moves the
  register before pushing the return address, so a fault on the push
  would run it again with the register moved. Either the microcode
  pushes first (and the simulator with it) or draft 2 leaves the form
  out; one of the draft 1 programs (crc) uses it, to call through a
  table. `JMP [r]+` is fine, since it pushes nothing.
- **Long paths with interrupts off:** zeroing a page (1.5 ms) and
  invalidating a context's 4,096 entries (27,000 cycles, 9 ms) in the
  soft-TLB experiment. A real kernel needs preemption points there, or
  hardware to clear a context.
- **Copying between two processes** that aren't the current one has no
  hardware help; the nucleus translates by reading the map, or shares
  pages.

### The hardware list

| Feature | Rough cost | What it buys |
|---|---|---|
| Supervisor mode: S bit, banked `sp`, privileged instructions, fault address and reason, privilege and page-fault vectors | ~5 chips, microcode | Protection at all |
| Register banks, policy selectable | ~4–6 chips | IPC −25%, preemption −41%, no saving on traps |
| Flat page map, 16 contexts × 4096 pages, V/W/X | ~12–15 chips (RFC 0010) | Address spaces, demand paging, guard pages, user-level drivers |
| The PC's physical page in a register | ~4 chips | Keeps the map out of the fetch path, the clock unchanged |
| XL and XS flag bits | ~1–2 chips | Copying to and from users at full speed |
| Vectored `SWI` | decode ROM | Null system call 39 → ~23 cycles |
| `S` writable only by traps and `RTI` | gates | One way less to fall into user mode by mistake |
| Store- and load-multiple through any register, or a block move | microcode | Page zeroing and copying −37–41%, about −55% at the bus's limit (graphics too) |
| Prioritised vectored interrupts, ideally a bank per level | ~3–4 chips (RFC 0009) | Interrupts without saving, direct to their handler |
| One-shot timer compare, microsecond counter | ~4–6 chips | Tickless scheduling, timeouts |
| FIFOs in serial devices; DMA with descriptor rings | per device | Interrupts per buffer, not per byte; no copying |
| A DMA window in the slave port | ~3–4 chips | Bus masters confined |
| `CALL [r]+` pushing before it moves `r`, or removed | microcode | Every instruction restartable |
| Later: a microcoded call path, interrupts straight to banks | microcode, ~5 chips | IPC ~2× (an estimate), drivers without the nucleus |

None of this needs a new opcode except a block move; the rest are
special registers, flag bits, address lines and microcode.

## Part 2: what the operating system could be

### What kind of computer this is

- **About 0.7–0.9 million instructions a second** on the 1b hardware at
  3 MHz (3.6–4.2 cycles an instruction in the bigger programs), more on
  draft 2. That's the class of a VAX-11/780 or a 68000 workstation of the
  early 1980s.
- **1–16 MB of static RAM**, no caches, so memory is fast next to the
  CPU, and copying is limited by instructions, not memory.
- **Storage:** a CompactFlash card at a few hundred KB/s.
- **Networking:** 10 Mbit/s Ethernet, first of all to a PC next to it,
  which will build software, hold files and stand in for anything not yet
  built.
- **People:** serial terminals, and perhaps a 640 × 480 screen with a
  window manager ([report 0019](0019-report-graphics.md)).
- **A second, very different processor:** the ECL number cruncher on the
  bus, with its own memory, fed by doorbells and shared memory
  ([RFC 0014](0014-rfc-system-bus.md)).
- **Languages:** C (no floating point yet), a Lisp that compiles itself
  on the machine, and Egret, a Smalltalk-like language with a JIT.
- **What's cheap and dear** (part 1): traps, switches and messages are
  cheap; copying, zeroing, per-byte I/O and shifts are dear.

Machines of this class ran a remarkable range of systems: V7 and BSD Unix
on PDP-11s and VAXes; VMS; Smalltalk-80 and Interlisp on Xerox's
machines; the MIT and Symbolics Lisp machines; Oberon on the Ceres
workstation; AmigaOS, preemptive and message-passing, on a 7 MHz 68000
with 512 KB; QNX on the first IBM PCs. Bill Buzbee's Magic-1, a 16-bit
TTL machine of about 200 chips, runs Minix. So the question isn't
whether a real operating system fits, but which.

### The design space

| Axis | Choices |
|---|---|
| Protection | none (trust); hardware address spaces; a safe language; capabilities |
| Structure | monolithic kernel; microkernel and servers; exokernel or library OS; microcode as the kernel |
| Concurrency | processes with blocking calls; asynchronous requests and completions; CSP channels; actors; coroutines |
| Naming | one file tree; per-process name spaces; object references (capabilities); a database |
| Persistence | files; a single-level store; a checkpointed image |
| Distribution | standalone; a terminal of a bigger system; one system across several machines |
| Interface | serial terminals and a shell; a graphical desktop; text as commands (Oberon, Acme) |

### Seven candidates

#### A small Unix

V7 or Minix: processes, `fork` and `exec`, one file tree, pipes, a shell,
timesharing on serial terminals.

- **For:** everyone knows it; the C compiler and its library are halfway
  there; ported software (an editor, `make`, games) comes with it.
- **Against, on Heron:** `fork` copies (52 ms for a 64 KB process, or
  copy-on-write faults later); pipes copy through the kernel twice;
  everything blocks, so a program that waits on two things needs
  `select` or threads; signals are a poor substitute for asynchronous
  I/O.
- **Needs:** the supervisor mode and the map.
- **Verdict:** the safe baseline, and a good personality to offer on
  top of something else: a C library with `open`, `read`, `write`,
  `spawn` (instead of `fork`) and a shell.

#### A message-passing nucleus with servers

What the benchmark nucleus is the core of: QNX, L4, Minix 3 and, first,
Brinch Hansen's RC 4000 nucleus of 1969. The kernel does threads,
address spaces, messages and interrupts; file systems, drivers, the
network stack and the window system are processes.

- **For:** small (the nucleus's paths are 1,200 lines of assembly
  for three variants), robust (a driver that crashes is restarted), and
  the costs are known: a call and reply is 293 cycles with half banks,
  about 98 µs, so 10,000 a second would take the whole machine, and a
  workload doing a few hundred a second spends a few percent on them.
- **Against:** a 16-byte write is 75% dearer than a monolithic system
  call (479 against 273 cycles); interrupts to user-level drivers need
  buffering devices. Bulk data must move by sharing pages, not by
  copying in messages.
- **Needs:** banks to be fast, the map for address spaces and for giving
  drivers their devices' pages (the nucleus maps the I/O page into the
  console driver).
- **Verdict:** the best fit for the hardware, if the devices buffer.

#### Plan 9: everything a file server

Every resource is a file tree served over one protocol (9P: about a
dozen messages: `walk`, `open`, `read`, `write`, `stat`, `clunk`...),
and every process assembles its own name space by mounting servers and
binding directories. `/dev/cons` is the console, `/net/tcp` the
network, a window is a directory of files (`rio`), another machine's
files are something you `import`, and a CPU server something you `cpu`
to.

- **On Heron it fits unusually well:**
  - **The PC as the file server.** Heron boots over Ethernet, mounts the
    PC's development tree over 9P, and works with real files before it
    has a file system of its own. A 9P server on the PC is a few hundred
    lines of Python.
  - **The cruncher as a file tree.** `/dev/crunch/ctl`, `data`,
    `result`: write a job, read the answer; the protocol hides doorbells
    and shared memory.
  - **The window manager as a file server**, as `rio` is: the graphics
    study's window manager behind `/dev/wsys`.
  - **9P messages are IPC messages:** a request and its reply is the
    nucleus's call and reply, or a ring of requests for bulk work. The
    same protocol runs over IPC, the bus and the network.
  - **Name spaces are protection:** a process sees only what was mounted
    for it, a capability system without saying so.
- **Against:** everything as text and files costs parsing and copying,
  and 9P's reads and writes copy data; large transfers want shared
  pages under the protocol.
- **Verdict:** the naming and protocol layer to put on the nucleus.

#### Asynchronous throughout

VMS's `QIO` with event flags and ASTs, AmigaOS's `SendIO`/`WaitIO` on
message ports with signals, Windows NT's completion ports, Fuchsia's
ports, Linux's io_uring: no call blocks except "wait"; every request
completes into a queue.

- **On Heron:** the measurements say rings don't save system calls here,
  but they are the natural interface to DMA hardware, to servers (from 8
  requests a batch they beat calls) and to a program that juggles a
  terminal, a network connection and a disk at once. AmigaOS showed an
  operating system for a machine this size can be built that way.
- **Programs stay simple** with user-level threads (52-cycle switches)
  or coroutines on top of the completion queue: a thread blocks in user
  space while the queue is asynchronous underneath.
- **Upcalls** (VMS's ASTs, scheduler activations) are the asynchronous
  way to tell a process something happened; with banks, the handler can
  run in a bank of its own, without saving anything of the thread it
  interrupts.
- **Verdict:** the I/O model for the nucleus, with a blocking library on
  top.

#### A single-address-space, persistent world

The Lisp machines, Smalltalk-80, Oberon, IBM's System/38 and KeyKOS:
one address space for everything, protection by a safe language or by
capabilities, and the system's state, not files, as the thing that
persists. KeyKOS and EROS wrote a consistent checkpoint of all of
memory every few minutes, so the machine never boots: it resumes.

- **On Heron it builds on what exists:** the Lisp already saves and
  reloads its whole heap as an image; its tagged pointers check
  themselves through the misaligned-access trap; Egret's objects are
  safe by construction. A Lisp or Egret world can be the operating
  system: processes are threads with stack groups, protection is the
  language, the file system is the object graph, and the CompactFlash
  card is the backing store of a single-level store, paged on demand.
- **Persistence by checkpoint:** write-protect every page at a
  checkpoint (a map change per page), copy each page before its first
  write after that (a fault and a 6,000–10,000-cycle copy), and write the
  copies out in the background. With 1 MB and a card at a few hundred
  KB/s, a full checkpoint takes seconds; an incremental one, of the pages
  written since, much less.
- **C needs a fence:** unsafe code gets a context of its own (an address
  space), and talks to the world by messages: the nucleus again.
- **A 4 GB single address space** wants the map as a tagged cache of page
  tables rather than 16 contexts of 16 MB; see part 1.
- **Verdict:** the most interesting thing Heron could do that a Unix
  can't, and a world to run inside the nucleus first, then perhaps
  instead of it.

#### A capability nucleus

KeyKOS, EROS, seL4, and earlier Hydra on C.mmp and the Cambridge CAP
computer: every right to do anything is a handle held in a table the
kernel guards; there is no global name to guess, no ambient authority,
and rights are passed in messages.

- **On Heron:** the nucleus's thread ids are already checked indexes;
  making them per-process handle tables, and letting messages carry
  handles, makes it a capability system for little cost. Plan 9's name
  spaces give much the same at the file level.
- **Verdict:** design the nucleus's handles this way from the start; it
  costs a table lookup that is already there.

#### Something small and period-flavoured

A resident monitor, then an Oberon-like single-user system: one address
space, no protection, cooperative tasks, text as commands, the compiler
and editor built in, the window manager as the screen. Or a timesharing
BASIC (RSTS/E), a Forth machine, or Pick's database operating system.

- **For:** needs no hardware beyond what draft 1 has; usable in weeks;
  the right thing to bring the machine up with, and fun in itself.
- **Verdict:** stage 0.

### Further ideas

- **Microcode as the nucleus.** The Transputer scheduled processes and
  passed messages in microcode, switching in about a microsecond; the
  iAPX 432 did too much of it and was slow. On Heron, a microcoded call
  and reply over banks (the 63 nucleus instructions of a round trip,
  without their fetches and extension parcels) would perhaps halve the
  round trip, to about 150 cycles; worth trying once there is a writable
  control store.
- **Hardware threads for devices** (above): banks with their own PC, an
  interrupt switching banks, the nucleus as the policy. It is the Alto's
  microcode tasks and the CDC 6600's peripheral processors, one level up.
- **Heron, PC and cruncher as one system:** the cruncher runs a tiny
  nucleus that speaks the same messages over the bus; the PC is a file
  server and a CPU server (compile there, transparently, through a
  mounted toolchain), as Plan 9's terminals used CPU servers.
- **Record and replay:** a process's only inputs are its messages,
  completions and the times it was preempted. Logging them makes any run
  repeatable, and with the branch-trace buffer of RFC 0005, a debugger
  can step backwards through a crash.
- **One protocol everywhere:** 9P on the nucleus, between Heron and the
  PC, to the cruncher, and to the window system, so a program doesn't
  know or care which of them answers.

### A recommendation, and the stages

The design that fits Heron best is a combination:

1. **A small message-passing nucleus** (the benchmark nucleus grown up):
   threads, address spaces in the flat map, register banks, calls with
   messages in registers, notifications, interrupts as notifications,
   handles checked per process.
2. **Asynchronous I/O by rings** between programs, servers and DMA
   devices, with completions and a `wait` for any of them, and a
   blocking C library and user-level threads on top.
3. **One protocol (9P or something like it) for every server**, and
   per-process name spaces: the PC's files, the console, the network,
   the window system and the cruncher all appear as file trees.
4. **Language worlds as citizens:** the Lisp and Egret run as processes
   with their own heaps and images; persistence and a single address
   space are tried there first.
5. **A Unix-like personality** for C programs: `spawn` not `fork`, the
   C library speaking 9P underneath.

What using it might look like, at a terminal on the day the network
works (a sketch, not a design):

```
% import pc /n/pc                     # the PC's files, over 9P
% cd /n/pc/heron/work
% cpu pc cc life.c                    # compiled on the PC, in this directory
% ./life | wc                         # run here
% cat /dev/crunch/status              # the number cruncher, as files
idle
% lisp -w lab.img                     # a Lisp world, where it was saved
```

Stages, each usable:

| Stage | What | Needs from the hardware |
|---|---|---|
| 0 | A monitor; an Oberon-like single-user system; programs loaded from the PC | nothing new |
| 1 | The nucleus without protection, servers for console, disk and network, 9P to the PC | a timer, a UART with FIFO, Ethernet |
| 2 | Protection: user mode, the map, user-level drivers | the supervisor mode, the map, XL/XS, banks |
| 3 | The window system as a file server; Lisp and Egret worlds; the cruncher | DMA, the display |
| 4 | Experiments: persistence, a single address space, microcoded messages | a writable control store |

### Next steps

- **Timing:** put the map and the PC page register into the 1b netlist
  and run the static timing analysis, to confirm that data translation
  fits the cycle.
- **Draft 2:** the same extensions for whatever draft 2 becomes (they
  fit 1a: system-group functions and special registers only), and a
  privileged variant of its simulator.
- **The nucleus grown up:** in C with assembly entry and exit, with a
  loader, a 9P server for the console, and a 9P server on the PC over a
  simulated Ethernet; then a shell.
- **Microcode estimates:** cost the call path and a block move in the 1b
  microcode generator, rather than estimating them here.

## Caveats

- **The cycles are the timing model's**, which the 1b hardware matches
  to within 9% overall ([report 0012](0012-report-draft-1b-hardware.md)).
  The system extensions themselves cost no cycles in the simulator,
  which is close for banks (address lines) and for a map off the fetch
  path; that the map fits the data cycle is still to be checked.
- **The nucleus is a benchmark, not an operating system:** its paths are
  short because it does little. A real kernel adds checks, accounting
  and more general code; the comparisons between policies and between
  structures should hold better than the absolute numbers.
- **The page references are single programs** in a never-flushed
  translation cache. Several programs sharing a tagged cache would miss
  more; with the flat map they wouldn't.
- **The console is a fast device** in the simulator: a store per byte,
  no status to poll. A real UART would make every write path slower by
  the same amount.
- **The chip counts are rough,** in the style of RFC 0010's.

## Appendix: v1bs, draft 1b with system extensions

The system extensions the kernel study built, as the simulator runs them:
draft 1b ([RFC 0004, Part II](0004-rfc-draft-1-isa.md#part-ii-draft-1b))
with a supervisor mode, register banks, a flat page map and cross-mode
loads and stores. They use no new opcodes except two system-group
functions, so they would fit draft 1a just as well. Draft 2's version of
them, without XL and XS, is [RFC 0029](0029-rfc-draft-2-system.md).

The simulator is `Isa::V1bs` in the draft 1 crate
([sys.rs](../studies/v1_isa/isa/src/sys.rs)), the assembler's encoder is
[asm/v1bs.rs](../studies/v1_isa/isa/src/asm/v1bs.rs), and the
disassembler is [v1bs.py](../studies/kernel/v1bs.py). Plain 1a and 1b
are unchanged: on them, everything below traps as an illegal instruction.

### Modes

- **Supervisor and user mode.** Reset starts in supervisor mode. Every
  trap and interrupt enters supervisor mode; `RTI` takes the mode from
  the flags word it pops.
- **The flags word** gains three bits:

  | Bit | Name | Meaning |
  |---|---|---|
  | 0–4 | V C Z N I | as in draft 1 |
  | 5 | S | supervisor mode |
  | 6 | XL | supervisor loads go through the map (cross loads) |
  | 7 | XS | supervisor stores go through the map (cross stores) |

- **Entering a trap or interrupt** saves the flags word as it was (with
  the old S, XL and XS), switches to supervisor mode with XL and XS off
  and I off, and pushes the PC and the flags on the supervisor's stack.
- **Privileged in user mode:** `HALT`, `EI`, `DI`, `RTI`, `MFUR`, `MTUR`,
  and `MFSR`/`MTSR` of every special register above `HI`. They trap to
  the privilege vector with the PC of the instruction. `MTSR flags` (`MTF`)
  in user mode changes only N, Z, C and V.
- **`MTSR flags` in supervisor mode** sets S, XL and XS too, so writing a
  word without S enters user mode, as on the 68000. The nucleus fell into
  that once; [What was hard](#what-was-hard) suggests keeping S out of
  `MTSR`'s reach.

### Registers and banks

The register file has room for many banks of registers (its SRAMs have
15 address lines and draft 1b uses 5). The `sysctl` special register
picks how supervisor mode and user mode share them:

| `sysctl` | Policy | Supervisor mode uses | User mode uses |
|---|---|---|---|
| 0 | none | the same registers, but its own `sp` | `r1`–`r15`, `HI` |
| 1 | full | bank 0: `r1`–`r15` and `HI` | bank `bank`: `r1`–`r15` and `HI` |
| 2 | half | `r1`–`r7` and `HI` (shared), bank 0's `r8`–`r15` | the shared `r1`–`r7` and `HI`, bank `bank`'s `r8`–`r15` |

- With **none**, the two modes have one `sp` each, as on the 68000.
- With **full** banks the supervisor never has to save a user register,
  and switching threads is choosing another bank.
- With **half** banks a system call's arguments and results, and a
  message between threads in `r1`–`r5`, pass through untouched; a
  preempted thread's `r1`–`r7` and `HI` still have to be saved.
- `bank` (special register 7) names the bank user mode runs in: 256 in
  the simulator. Bank 0 is the supervisor's, so threads use the others.
- **`MFUR rd, rs`** (`0 d s E`) reads the user's register `rs` from
  supervisor mode: from bank `bank` where the policy banks it, else the
  shared register (and, with none, the user's `sp` for `rs` = 15).
  **`MTUR rd, rs`** (`0 d s F`) writes the user's `rd`. Both are
  privileged and take 2 cycles in the timing model, like a register move.

### Special registers

`MFSR rd, n` and `MTSR n, rs`, with these names in the assembler:

| n | Name | |
|---|---|---|
| 0 | `flags` | the flags word (above) |
| 1 | `hi` | `HI` |
| 2 | `far` | the address of the last page fault (read only) |
| 3 | `fsr` | why it faulted (read only, below); after `SWI #n`, n |
| 4 | `ctx` | the map context user mode runs in, 0–15 |
| 5 | `mapa` | the map address: context × 4096 + virtual page |
| 6 | `mapd` | the map entry at `mapa`; writing it moves `mapa` on by one |
| 7 | `bank` | user mode's register bank |
| 8 | `sysctl` | the banking policy, 0–2 |

Writing `mapd` with `mapa` auto-incremented loads a run of map entries
with one `MTSR` each.

### The page map

The flat page map of [RFC 0010](0010-rfc-ideas-os.md#3-mmu):

- **16 contexts of 4096 entries,** 4 KB pages, so 16 MB of virtual
  space per context. An address of 16 MB or more faults.
- **An entry** is a physical page address in bits 31–12 and V (valid),
  W (writable) and X (executable) in bits 0–2. Bits 3–11 are the
  software's. A physical page above RAM can be mapped: the I/O page
  (`0xFFFFF000` + V W) puts the console and the timer in a user
  process, for a user-level driver.
- **Translated:** every fetch and data access in user mode, through
  context `ctx`; in supervisor mode, data loads while XL is set and data
  stores while XS is set, as user accesses (so they fault where the user
  would). Everything else in supervisor mode is physical.
- **Referenced and dirty bits** are left to software (map a page
  read-only and take the first write's fault).

### Faults

A page fault traps to vector `0x20` with the PC of the faulting
instruction, which hasn't changed anything, so `RTI` runs it again. The
privilege vector is `0x1C`. `far` holds the address and `fsr` why:

| `fsr` bit | Meaning |
|---|---|
| 0 | the page isn't valid |
| 1 | a store to a page without W |
| 2 | a fetch from a page without X |
| 3 | the address is 16 MB or more |
| 4 | the access was a store |
| 5 | the access was a fetch |
| 6 | a supervisor access with XL or XS (a cross access) |

One draft 1b form can't be restarted: `CALL` through an auto-incremented
or auto-decremented operand (`CALL [r]+`) changes the register before
it pushes the return address, so a fault on the push would run it again
with the register moved. The simulator does it in that order, as it
does for plain 1b; see [What was hard](#what-was-hard).

### What the simulator leaves out

- **Time.** Mode switches, bank switches and translation cost no cycles;
  the timing model costs `MFUR`/`MTUR` like a register move, `MTSR` like
  any system instruction and a fault like any trap. That is close for
  banks, which are address lines, and for a map that stays off the
  instruction fetch ([Translation: the page map](#translation-the-page-map)).
- **DMA and other bus masters**, and so any protection from them.
- **Interrupt priorities:** there is one interrupt, the timer's.
