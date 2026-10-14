---
number: 10
type: rfc
title: Operating system and MMU ideas
status: open
date: 2026-10-14
context:
  studies: [kernel, v1_isa, v1b_hw, lisp]
  commit: 2f81658
---

# RFC 0010: Operating system and MMU ideas

An ideas RFC: a scratchpad of ideas for the operating system and what the
hardware gives it, each with its own status
([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). Most of the
evidence is [report 0020](0020-report-operating-system.md), which built
v1bs, draft 1b with system extensions
([studies/kernel/system.md](../studies/kernel/system.md)), and a small
message-passing kernel on it.

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | It has numbers behind it |
| **recommended** | Suggested for draft 2 or the next hardware |
| **decided** | Emily chose it; not built yet |
| **open** | Discussed, not decided |
| **not recommended** | The evidence is against it; Emily hasn't decided |
| **rejected** | Decided against, with the reason, so it isn't proposed again without new evidence |

Chip counts are rough estimates. Cycles are the timing model's, on
D32-separate, the draft 1b hardware's configuration.

## 1. The operating system

**On Heron a trap is cheap and copying is dear:** a null system call is
39 cycles, a call and reply between processes 293–390, and zeroing a 4 KB
page 4,622 ([report 0020](0020-report-operating-system.md#short-version)).
So the structure of an operating system (traps, switches, messages) is
affordable, and anything that copies data is not.

- **A message-passing nucleus with servers, asynchronous I/O by rings,
  one protocol for every server (9P or similar) with per-process name
  spaces, and the Lisp and Egret as worlds of their own, with a Unix-like
  library on top.** **recommended** by report 0020, which also stages it,
  from a monitor needing no new hardware to protection and a writable
  control store ([the recommendation and the stages](0020-report-operating-system.md#a-recommendation-and-the-stages)).
  The other candidates it weighs, each with a verdict: a small Unix, a
  single-address-space persistent world (the most interesting
  alternative), a capability nucleus, and something small and
  period-flavoured as stage 0
  ([seven candidates](0020-report-operating-system.md#seven-candidates)).
- **The ambition ladder,** from a resident monitor to protected
  multi-user: [RFC 0005](0005-rfc-ideas-direction.md#1-direction-and-ambition).
- **Processes by spawning, not `fork`.** Copying a 64 KB process eagerly
  is 52 ms, and copy-on-write still copies each page written. **measured**,
  recommended.
- **Threads in user space.** A switch between user-level threads is 52
  cycles, a quarter of a yield through the nucleus. An async runtime
  should switch in user space and use the nucleus only to wait for
  completions. **measured**, recommended.
- **Batching system calls through rings doesn't pay here:** a request
  through a ring costs about 140 cycles against a 39-cycle trap. Rings pay
  between processes, from about 8 requests a batch, and as the interface
  to DMA hardware. **measured.**
- **Shared libraries the Amiga way:** a table of entry points and its own
  data, reached through a base register. A call through the table costs
  4–5 cycles more than a direct call on 1b, data nothing extra, and with
  the flat page map every library can sit at the same address in every
  process, so nothing is relocated. Windows' import tables are the other
  good choice; ELF's PLT is the dearest
  ([report 0020](0020-report-operating-system.md#dynamic-linking)).
  **measured**, open.
- **Errors returned in the carry flag** by editing the saved flags word
  (the PDP-11 Unix trick). **open.**
- **Further ideas** ([report 0020](0020-report-operating-system.md#further-ideas)),
  all **open**: microcode as the nucleus, given a writable control store;
  hardware threads for devices (below); Heron, the PC and the number
  cruncher as one system speaking one protocol; record and replay of a
  process's messages, completions and preemptions.

## 2. What the CPU gives the operating system

From [report 0020](0020-report-operating-system.md#part-1-what-the-hardware-should-give),
which built the supervisor mode, the register banks and the cross-mode
loads and stores (section 3) in v1bs and measured them; the rows marked
**measured** are those. The rest are its estimates and older ideas. None
needs a new opcode except a block move
([RFC 0006](0006-rfc-ideas-isa.md#5-more-instruction-ideas)); the rest are
special registers, flag bits, address lines and microcode.

| Feature | Cost | What it buys | Status |
|---|---|---|---|
| **Supervisor mode:** an S bit in the flags word, saved by traps and `RTI`; `HALT`, `EI`, `DI`, `RTI` and the system registers trap in user mode, and user `MTF` changes only N, Z, C and V; a supervisor `sp` the trap switches to before it pushes; fault address and reason; privilege and page-fault vectors | ~5 chips, microcode; the mode can be a spare microcode address line | Protection at all | **measured**, **recommended** |
| **S writable only by traps and `RTI`**, out of `MTSR`'s reach | gates | v1bs lets `MTSR flags` set S, and the nucleus once fell into user mode by writing the flags back without it (the 68000 has the same trap) | **recommended** |
| **Register banks** in the register file's spare SRAM (15 address lines, draft 1b uses 5), with `MFUR`/`MTUR` to reach the user's bank | ~4–6 chips | A call and reply −25% with half banks, a preemption −41% with full banks, and no saving on system calls. Selectable policy, or half banks for message passing. `r0` must be zero in every bank, in logic; the reset routine's constants pinned to one bank | **measured**, **recommended** |
| **A vectored `SWI`:** the decode ROM sends `SWI #n` to its own entry | decode ROM | 16 of a null system call's 39 cycles are dispatch; vectored, about 23 (an estimate; v1bs latches the number in `fsr` instead) | **recommended** |
| **Restartable instructions:** nothing is committed before the last memory access (the 68000 couldn't restart after bus errors, and the 68010 had to fix it) | microcode | Demand paging, guard pages, copy-on-write. One 1b form breaks it, `CALL [r]+` ([RFC 0006](0006-rfc-ideas-isa.md#32-1bs-gaps)) | **adopted** in draft 1's rules |
| **Relocation** by position-independent code (PC-relative addressing), or a relocating loader | – | Programs load anywhere; with the map, every process can also start at the same address | **adopted** (PC-relative modes) |
| **A trace bit** (trap after every instruction), with `SWI` as a breakpoint and the breakpoint register of [RFC 0005](0005-rfc-ideas-direction.md#3-big-ideas) | microcode | A `ptrace`-style debugger; the trace bit lives in the flags word, so it's per thread | **recommended** |
| **Prioritised, vectored interrupts**, ideally a bank per level | ~3–4 chips ([RFC 0009](0009-rfc-ideas-io.md#1-io)) | Interrupts go straight to their handler, which saves nothing | **recommended** |
| **A one-shot timer and a microsecond counter** | ~4–6 chips ([RFC 0009](0009-rfc-ideas-io.md#1-io)) | Tickless scheduling, timeouts | **recommended** |
| **Interrupts straight to a bank:** a bank that holds a thread's PC and flags as well as its registers, so an interrupt switches to the driver thread with no nucleus code, as the Xerox Alto switched between microcode tasks | ~5 chips, moving the PC to and from the register file | The 500-cycle path to a user-level driver would take tens of cycles | **open**, later |
| **A microcoded call path** over banks | writable control store | A call and reply about halved, to ~150 cycles (an estimate) | **open**, later |
| **Boot:** a boot ROM overlaid on low memory at reset, switched out by an I/O write; or a loader toggled in from the front panel; or boot over Ethernet ([RFC 0009](0009-rfc-ideas-io.md#4-networking)) | | | **open** |

What the paths cost, with each banking policy
([report 0020](0020-report-operating-system.md#the-paths-measured)):

| Operation | none | half | full |
|---|---:|---:|---:|
| Null system call | 39 | 39 | 39 |
| Yield to another process | 257 | 207 | 222 |
| Call and reply between processes | 390 | 293 | 347 |
| Timer preemption | 249 | 203 | 147 |
| Interrupt handed to a user-level driver | 640 | 545 | 503 |
| Demand-zero page fault | 4,755 | 4,753 | 4,753 |

## 3. MMU

What the OS needs: separate address spaces, protection (user/kernel, read
only, no execute), restartable faults (demand paging, copy-on-write,
growing stacks, guard pages), and sharing.

**Options considered:**

| Design | Gives | Cost | Status |
|---|---|---|---|
| Base/limit registers | relocation and protection, one block per process | ~6 chips (an adder in the address path) | **open** |
| Protection regions (ARM MPU style) | protection only; needs position-independent code | ~4 chips per boundary | **open** |
| Segments (PDP-11 style, 8 per space) | a few variable pieces | ~15 chips | **open** |
| **Flat page map in SRAM** | paging, no flushes, no misses | ~12–15 chips | **recommended**, **measured** in v1bs |
| Two-level map (Sun-2 style) | sparse, larger spaces | ~20 chips, two lookups in series | **open** |
| Tagged translation cache plus page-table walk in microcode (as the VAX did) | full 32-bit spaces | ~20 chips plus microcode | **open**, the upgrade path to a 4 GB single address space |
| Address registers as the translation cache | see [section 4](#4-address-registers-with-hidden-state) | ~10–14 chips | **open** |

**The flat page map:**
- **Shape:**
  - 16 MB virtual per process in 4 KB pages (4096 pages);
  - 16 contexts in the map SRAM (64K entries);
  - an entry is a physical page plus V/W/X bits. As proposed, a 12-bit
    physical page in 24 bits, 3 × 128K×8 SRAM, up to 16 MB physical. v1bs
    simulates a 20-bit page, so the I/O page can be mapped into a
    user-level driver;
  - a context switch is one register write.
- **Translation misses are not the question.** The other studies' bigger
  programs touch up to 223 pages; a translation cache of 256 entries would
  miss only on their first touches, and a software refill costs 85 cycles
  with banks. The map's 64K entries are, for this machine, an infinitely
  large translation cache
  ([report 0020](0020-report-operating-system.md#translation-the-page-map)).
- **Keep the map off the instruction fetch.** The fetch sets the draft 1b
  hardware's clock, and a 55 ns map SRAM in it would make the clock 9%
  slower.
  - **Data addresses** go through the map from MAR; a fault has to reach
    the next-address logic about 240 ns into the cycle, as an address
    error does now. To be checked with the timing analysis.
  - **The PC's physical page in a register,** loaded from the map when the
    PC leaves its page (a carry out of bit 11, or a jump compared with two
    74HCT688): ~4 chips, under 1% of cycles. **recommended.**
- **Referenced and dirty bits in software:** map pages read-only; the first
  write faults, about 100 cycles. The same mechanism gives copy-on-write.
- **Cross-mode loads and stores:** supervisor mode is untranslated, and two
  flag bits, XL and XS, send its loads or stores through the user's map
  (the 68010's `MOVES` without a new instruction). Copying to and from user
  memory runs at full speed with any instruction, and a bad pointer is
  just a page fault. ~1–2 chips. **measured**, **recommended**. They
  replace the `LDU`/`STU` instructions first proposed.
- **Writing the map:** `MTSR mapd` with `mapa` stepping on by one, so a
  run of entries takes one instruction each (v1bs).
- **More than 16 processes:** reassign contexts. Reusing one costs about 7
  cycles per page the old and new process have mapped, ~800 cycles for a
  60-page process. Clearing a whole context takes 9 ms with interrupts
  off, so a kernel needs preemption points there, or hardware to clear a
  context. **open.**
- **The X bit** makes stacks and heaps non-executable, at the cost of a map
  change when the Lisp or Egret writes code. **open.**
- **DMA bypasses the map:** a window register in the CPU board's slave
  port confines bus masters
  ([RFC 0008](0008-rfc-ideas-memory-and-buses.md#1-memory)).

**Restartability audit (draft 1):**
- Single-access instructions update registers after the access, including
  auto-increment.
- `CALL` and `JMP/CALL [mem]` read the target and push before changing the
  PC or `sp`, except 1b's `CALL [r]+` and `CALL -[r]`, which move `r`
  first ([report 0020](0020-report-operating-system.md#what-was-hard)).
- `SAVE` writes first and moves `sp` last; re-running it is idempotent.
- `RESTORE` re-runs idempotently (`sp` is never in the range).
- Prefetch faults are held back until the parcel is used.
- Interrupt entry pushes onto the supervisor stack, so it never faults.
- Block moves must keep their progress in registers.
- On a fault the microcode: stops the write, latches the address and reason,
  saves the PC of the faulting instruction, and traps.

**ISA additions** (as v1bs has them, [system.md](../studies/kernel/system.md)):
the S, XL and XS flag bits; a supervisor `sp` or banks; privileged
instructions; special registers for the fault address and reason, the
context, the map address and data, the bank and the banking policy;
vectors for page faults and privilege violations; I/O from supervisor
mode only, unless the map gives a driver its device's page.

**Guard pages:** an unmapped page below a stack or after a heap turns a
limit check into a page fault. The Lisp ([report 0018](0018-report-lisp.md))
checks the stack limit at every function entry and the heap limit at every
`cons`; guard pages would save 5.0% and 1.8% of its compiled cycles (up to
7.2% and 5.2%). Pairs are 8-byte aligned, so `cons`'s first store is the
one that faults, and the handler can collect and restart it. Comes free
with the flat page map; protection regions would do for the stack alone.
**open.**

**Staging:**
1. A socket for the map chips plus a bypass jumper on the first boards.
2. The flat map.
3. Tags plus a microcode walker, if a single address space of 4 GB is
   wanted.

## 4. Address registers with hidden state

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
- **Pointer arithmetic doesn't set flags.**
- **A separate address adder** runs alongside the data ALU (68000 style),
  so auto-increment and `[A + d]` are free.
- **`sp` and `PC` are A registers:** cached stack page, and cached code page
  (instruction-fetch translation for free, which section 3's PC page
  register also gives).
- **Register budget** (from the 20 draft 1a programs):
  - Pointer registers: seven programs use up to 7, but rarely more than 3–5
    in one loop.
  - Data registers are the pinch: sha256 needs 9–12, mandel 8.
  - So A registers need some arithmetic (`ADDA`/`SUBA`/`CMPA`/`MOVEA`), and
    indexed addressing should take a D register as the index
    (`[A2 + D3*4]`).
- **It's a different register model from both 1a and 1b,** so it would
  change a 1b-based draft 2 more than anything in
  [RFC 0006](0006-rfc-ideas-isa.md).

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
- The first discussion's pick, with hidden state sized so flavour 2 can
  be added later.

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

**Measuring it:** the current programs fit in a few pages and would show
near-perfect hit rates. The bigger workloads now exist: report 0020
traced the page references of the Lisp, Egret and the window manager
([page references](0020-report-operating-system/performance.md#page-references-of-bigger-programs)),
up to 223 pages. Flavour 1 on those traces, counting walks per pointer
load, is the next step.
