---
number: 10
type: rfc
title: Operating system and MMU ideas
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw, lisp]
  commit: e494b0c
---

# RFC 0010: Operating system and MMU ideas

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
