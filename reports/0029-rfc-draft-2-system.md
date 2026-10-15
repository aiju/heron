---
number: 29
type: rfc
title: Draft 2's system architecture
status: open
date: 2026-10-15
context:
  studies: [kernel, v1_isa]
  commit: 1b8e4d2
depends-on: [10, 28]
---

# RFC 0029: Draft 2's system architecture

What draft 2's CPU gives an operating system: modes, exceptions, special
registers, register banks and the page map. The starting point is v1bs,
draft 1b with system extensions
([studies/kernel/system.md](../studies/kernel/system.md)), which
[report 0020](0020-report-operating-system.md) built and measured with a
small message-passing kernel; [RFC 0010](0010-rfc-ideas-os.md) collects
the ideas around it. This RFC records only what draft 2 keeps, changes or
still has to decide, and leaves the evidence where it is. The
instructions' encodings are in [RFC 0028](0028-rfc-draft-2-isa.md).

## 1. Summary

| | Proposal | Status |
|---|---|---|
| Modes | Supervisor and user, as v1bs; only traps and `RTI` change S | proposed |
| Exceptions | Precise, as in draft 1; v1bs's vectors plus a trace trap and a vector per `SWI` number | proposed |
| Special registers | 0–7 for user mode, 8–15 privileged | proposed |
| Register banks | A full bank per thread; the kernel is bank 0 | proposed |
| Page map | v1bs's flat map with 128 contexts; page tables in RAM are the source of truth | proposed |
| The supervisor and user memory | Flag bits, an address split or software | open |
| Interrupts | Prioritised and vectored, on the bus's eight lines | proposed, details open |

## 2. Modes

- **Supervisor and user mode,** as in v1bs. Reset starts in supervisor
  mode, every trap and interrupt enters it, and `RTI` takes the mode from
  the flags word it pops.
- **Privileged:** `HALT`, `EI`, `DI`, `RTI`, `MFUR`, `MTUR`, and
  `MFSR`/`MTSR` of special registers 8–15. In user mode they trap to the
  privilege vector.
- **`MTSR flags` never changes S,** in either mode. Report 0020's nucleus
  fell into user mode by writing the flags back
  ([report 0020](0020-report-operating-system.md#protection-modes-and-the-stack)).
  In user mode it changes only N, Z, C and V, as in v1bs.
- **The flags word:**

  | Bit | Name | |
  |---|---|---|
  | 0–4 | V C Z N I | as in draft 1 |
  | 5 | S | supervisor mode |
  | 6, 7 | XL, XS | only if they're kept ([7](#7-the-supervisor-and-user-memory)) |
  | 8 | T | trace: trap after every instruction |
  | 9–11 | IPL | interrupts at or below this level are held off ([8](#8-interrupts-and-the-timer)) |
  | 12–31 | | reserved, written as 0 |

  T is in the flags word, so it's per thread, and only the supervisor can
  set it: a `ptrace`-style debugger
  ([RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)).

## 3. Exceptions

- **Precise:** an exception is taken before the instruction has changed
  anything, the saved PC is the instruction's own, and `RTI` runs it
  again. Draft 1's rules carry over
  ([RFC 0010, 3](0010-rfc-ideas-os.md#3-mmu)). What draft 2 adds to them:
  - `SAVE`, `RESTORE`, `LDM` and `STM` as microcode loops
    ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch))
    change their base register only after their last access.
  - `CALL [r]+` and `CALL -[r]` push before they move `r`, unless calls
    stop pushing at all with a link register
    ([RFC 0006, 5](0006-rfc-ideas-isa.md#5-more-instruction-ideas)).
  - `CAS`'s locked read is checked as a write
    ([RFC 0028, 9](0028-rfc-draft-2-isa.md#9-open-questions)).
- **Entering** pushes the PC and the flags word on the supervisor's
  stack, which is bank 0's `r15` ([5](#5-register-banks)), as draft 1
  does. It switches to supervisor mode and bank 0, and turns I (and XL
  and XS) off.
- **Vectors,** 4 bytes apart with a `JMP` in each, as in draft 1
  ([isa-v1.md](../studies/v1_isa/isa-v1.md#calls-the-stack-and-interrupts)):

  | Address | Vector | From |
  |---|---|---|
  | `0x00` | reset | draft 1 |
  | `0x04` | interrupt, until there are levels | draft 1 |
  | `0x08` | illegal instruction | draft 1 |
  | `0x0C` | reserved: draft 1's one `SWI` | |
  | `0x10` | divide error | draft 1 |
  | `0x14` | address error | draft 1 |
  | `0x18` | tag trap | v1bx |
  | `0x1C` | privilege violation | v1bs |
  | `0x20` | page fault | v1bs |
  | `0x24` | trace | new |
  | `0x100` + 4n | `SWI #n`, n = 0–255 | new |

  The decode ROM gives each `SWI #n` its own microcode entry, so each
  jumps straight to its own vector: a null system call loses the 16 of
  its 39 cycles that went to dispatching
  ([report 0020](0020-report-operating-system.md#the-paths-measured)).
- **The fault registers** `far` and `fsr` are v1bs's, at their new
  numbers ([4](#4-special-registers)). With a vector per `SWI` number,
  `fsr` no longer needs to hold n.

## 4. Special registers

`MFSR rd, n` and `MTSR n, rs` hold n in 4 bits. Draft 2 numbers them so
that the privilege check is one bit:

| n | Name | Mode | |
|---|---|---|---|
| 0 | `flags` | user: N, Z, C, V only | the flags word ([2](#2-modes)) |
| 1 | `hi` | user | `HI` |
| 2 | `lo` | user | `MULA`'s low half ([RFC 0028, 6.9](0028-rfc-draft-2-isa.md#69-tentative-instructions)) |
| 3 | | user | reserved for the FPU's control and status ([RFC 0006, 8](0006-rfc-ideas-isa.md#8-floating-point)) |
| 4–7 | | user | reserved |
| 8 | `far` | read only | the address of the last fault |
| 9 | `fsr` | read only | why it faulted (v1bs's bits) |
| 10 | `ctx` | | the map context user mode runs in, 0–127 |
| 11 | `mapa` | | the map address: `ctx` × 4096 + virtual page |
| 12 | `mapd` | | the map entry at `mapa`; writing it moves `mapa` on by one |
| 13 | `bank` | | user mode's register bank, 0–255 |
| 14 | `bkpt` | | a breakpoint address (open) |
| 15 | | | reserved |

v1bs's `sysctl`, the banking policy, goes ([5](#5-register-banks)).

## 5. Register banks

- **A full bank per thread, and the kernel is bank 0.** A trap switches
  to bank 0 along with supervisor mode, and `RTI` returns to bank `bank`.
  Kernel code is ordinary code with all 16 registers, compiled C
  included, and its `sp` is bank 0's `r15`.
- **One policy, not three.** v1bs's none and half policies go, and with
  them the variants of every kernel path. Full banks also add nothing to
  any timing path; half banks put a gate in the register read path.
  Report 0020's paths with full banks: a null system call 39 cycles, a
  call and reply 347, a yield 222, a preemption 147
  ([report 0020](0020-report-operating-system.md#register-banks)).
- **Arguments, results and messages** cross between banks with `MFUR`
  and `MTUR`, one parcel each in RFC 0028's map
  ([6.8](0028-rfc-draft-2-isa.md#68-control-multiple-and-system-rows-0-and-f)).
  That copying is why a call and reply costs 347 cycles here against half
  banks' 293. A microcoded copy of `r0`–`r7` into bank n would win most
  of it back (open).
- **256 banks:** `bank` is 8 bits, in the register file's spare address
  lines. Past 256 threads, the kernel saves a bank's registers when it
  reuses the bank, as it reuses map contexts.
- **The register file's hidden entries,** the microcode's constants and
  the zero that replaces `r0`, stay outside the banks. Room should be
  left for each bank to hold its thread's PC and flags as well, so that
  an interrupt could one day switch straight to a driver's bank
  ([report 0020](0020-report-operating-system.md#interrupts-and-devices)).

## 6. The page map

- **v1bs's flat map**
  ([system.md](../studies/kernel/system.md#the-page-map),
  [RFC 0010, 3](0010-rfc-ideas-os.md#3-mmu)): 4 KB pages, 16 MB per
  context, V, W and X, and the PC's physical page in a register so that
  the map stays off the instruction fetch.
- **128 contexts instead of 16.** Three 512K × 8 SRAMs (the AS6C4008,
  55 ns, still made in DIP) in place of three 128K × 8 hold 128 contexts
  for the same chip count. A nucleus with servers would outgrow 16
  processes, and reassigning a context costs about 800 cycles a switch,
  or 9 ms to clear one.
- **Page tables in RAM are the source of truth.** The kernel fills the
  map from them, when a page faults or ahead of time; a refill costs 85
  cycles with banks
  ([report 0020](0020-report-operating-system.md#the-paths-measured)).
  The kernel needs the tables anyway to reuse contexts, and with them a
  tagged translation cache, RFC 0010's upgrade path to any number of
  processes and full 32-bit spaces, could replace the map without
  changing more of the kernel than its fill routine.
- **Referenced and dirty bits** stay in software, as in v1bs.
- **DMA** bypasses the map; a window register in the slave port confines
  bus masters ([RFC 0010, 3](0010-rfc-ideas-os.md#3-mmu)).

## 7. The supervisor and user memory

**Open.** The supervisor runs untranslated, so it needs a way to reach a
user's memory, for system call buffers, in which a bad pointer is a fault
and not a wild access:

| | How | For | Against |
|---|---|---|---|
| **XL and XS** (v1bs) | Flag bits send the supervisor's loads or stores through the user's map | Measured; any instruction, at full speed | A mode on every load or store: while XL is set the kernel's own stack goes through the user's map, so copy loops have to be hand-written, never compiled |
| **An address split** (as on MIPS) | In supervisor mode, addresses below 16 MB go through the current context and the rest are physical | No mode; compiled C copies with `memcpy` | Physical memory can't sit in the low 16 MB, which ties into which address bits pick the slot ([RFC 0014](0014-rfc-system-bus.md), open); the kernel checks that user pointers are below 16 MB |
| **Software** | The kernel reads the map through `mapa` and `mapd` once per page and copies physically | No hardware, and no faults inside the kernel | A few instructions per page and per call |

The kernel needs the last one anyway, for copies between processes that
aren't running.

## 8. Interrupts and the timer

- **Prioritised and vectored:** RFC 0009's priority encoder, the IPL
  field in the flags word ([2](#2-modes)), and the bus's eight interrupt
  lines ([RFC 0014, 8.3](0014-rfc-system-bus.md#83-interrupts-and-synchronisation),
  [RFC 0009, 1](0009-rfc-ideas-io.md#1-io)). Whether the vector comes
  from the level or from the device, as RFC 0009 proposes, is open.
- **Interrupts enter bank 0** like every trap. A bank per level, so that
  a handler saves nothing, is open.
- **The timer,** a microsecond counter with a one-shot compare
  ([RFC 0009, 1](0009-rfc-ideas-io.md#1-io)), is a device, not a special
  register.

## 9. Open questions

1. **The supervisor and user memory** ([7](#7-the-supervisor-and-user-memory)).
2. **Interrupt vectors** from the level or from the device, and whether
   each level gets a bank.
3. **A bank-to-bank copy** of the message registers.
4. **The breakpoint register,** and what a trace trap reports.
5. **Boot** ([RFC 0010, 2](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)).
6. **`CALL [r]+`:** push first, or a link register.
7. **When, if ever, to replace the map** with a tagged translation cache.

## 10. Next steps

- **The system half of the draft 2 simulator:** v1bs's
  ([sys.rs](../studies/v1_isa/isa/src/sys.rs)) on draft 2, with the
  changes above. Then port the nucleus and measure its paths again with
  full banks.
