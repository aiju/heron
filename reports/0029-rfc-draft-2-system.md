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

What draft 2's CPU gives an operating system. Part I is the
specification, with its holes marked **open**; Part II is where it comes
from and why. The instructions' encodings are in
[RFC 0028](0028-rfc-draft-2-isa.md).

## Part I: Specification

### 1. Overview

To the machine of RFC 0028 this adds:

- **two modes,** supervisor and user ([2](#2-modes-and-the-status-register));
- **an address space** whose upper half is a window onto physical memory
  for the supervisor, and whose lower part is translated by a page map
  ([3](#3-the-address-space));
- **special registers** 8–15, for the supervisor ([4](#4-special-registers));
- **register banks,** one per thread ([5](#5-register-banks));
- **exceptions** that are precise and vectored ([6](#6-exceptions));
- **interrupts** at eight priority levels ([7](#7-interrupts)).

### 2. Modes and the status register

- **Supervisor and user mode.** The S bit of the status register `sr`
  says which. Reset enters supervisor mode, every exception enters it, and
  `RTI` takes the mode from the status word it pops. Nothing else changes
  S.
- **The status register** `sr`, special register 8:

  | Bit | Name | |
  |---|---|---|
  | 0 | V | overflow |
  | 1 | C | carry |
  | 2 | Z | zero |
  | 3 | N | negative |
  | 4–7 | | reserved for user flags |
  | 8–23 | | reserved |
  | 24–27 | IPL | interrupt priority level, 0–8: requests below it are held off ([7](#7-interrupts)) |
  | 28 | | reserved |
  | 29 | T | trace: trap after every instruction |
  | 30 | I | interrupts enabled |
  | 31 | S | supervisor mode |

  Reserved bits read as 0 and must be written as 0.
- **The condition-code register** `ccr`, special register 0, is `sr`'s
  byte 0, the condition codes: reading it gives byte 0 zero-extended, and
  writing it changes byte 0 alone. User mode reads and writes `ccr`; `sr`
  is privileged, to read and to write (**decided**, Emily, 2026-10-16).
  `MTSR sr, rs` changes every bit but S, and ignores what `rs` has in bit
  31 (**open**).
- **Privileged instructions:** `HALT`, `EI`, `DI`, `SPL`, `RTI`, `MFUR`,
  `MTUR`, and `MFSR` and `MTSR` of special registers 8–15. In user mode
  they raise a privilege violation ([6](#6-exceptions)).

### 3. The address space

A virtual address's bit 31 picks how it is mapped:

| Virtual address | User mode | Supervisor mode |
|---|---|---|
| `0x0000_0000`–`0x00FF_FFFF` | through the page map of context `ctx` | the same |
| `0x0100_0000`–`0x7FFF_FFFF` | page fault | page fault |
| `0x8000_0000`–`0xFFFF_FFFF` | page fault | physical: the address with bit 31 cleared |

- **The window.** In supervisor mode, an address with bit 31 set is
  physical address `va & 0x7FFF_FFFF`, for instruction fetches and data
  accesses alike, and nothing checks it. Physical addresses with bit 31
  set are reachable only through the page map (open, with the system
  bus's slot bits; [RFC 0014](0014-rfc-system-bus.md)).
- **The translated space.** Addresses below 16 MB are translated in both
  modes, through context `ctx`. So the supervisor uses a user's pointers
  as they are, and its accesses are checked like the user's.
- **The page map** has 128 contexts of 4096 entries, one per 4 KB page.
  An entry:

  | Bits | |
  |---|---|
  | 31–12 | the physical page |
  | 11–3 | read as 0, ignored when written |
  | 2 | X: instructions may be fetched |
  | 1 | W: data may be stored |
  | 0 | V: valid |

  It is read and written through `mapa` and `mapd` ([4](#4-special-registers)).
  Its contents are undefined after reset. Referenced and dirty bits are
  left to software.
- **A page fault** happens when a translated access finds its entry
  invalid, a store finds W clear or a fetch finds X clear, and for the
  addresses the table above marks as faulting. `far` gets the
  virtual address and `fsr` the reason:

  | `fsr` bit | |
  |---|---|
  | 0 | the entry isn't valid |
  | 1 | a store to a page without W |
  | 2 | a fetch from a page without X |
  | 3 | the address is between 16 MB and 2 GB |
  | 4 | a user-mode access with bit 31 set |
  | 5 | the access was a store |
  | 6 | the access was a fetch |
  | 7 | the access was made in supervisor mode |

- **An access to a physical address that nothing answers** (open: a bus
  timeout and a vector for it).

### 4. Special registers

`MFSR rd, n` and `MTSR n, rs`, n = 0–15. Registers 0–7 are user mode's,
8–15 the supervisor's.

| n | Name | |
|---|---|---|
| 0 | `ccr` | the condition codes, `sr`'s byte 0 ([2](#2-modes-and-the-status-register)) |
| 1 | `hi` | `HI` |
| 2 | `lo` | `LO`, for `MULA` (tentative, [RFC 0028, 5.10](0028-rfc-draft-2-isa.md#510-tentative-instructions)) |
| 3 | | reserved for the FPU's control and status |
| 4–7 | | reserved |
| 8 | `sr` | the status register ([2](#2-modes-and-the-status-register)) |
| 9 | `far` | read only: the address of the last page fault or address error |
| 10 | `fsr` | read only: why the last page fault happened ([3](#3-the-address-space)) |
| 11 | `ctx` | the page map context, 0–127 |
| 12 | `mapa` | the map address: context × 4096 + page, 0–524,287 |
| 13 | `mapd` | the map entry at `mapa`; writing it moves `mapa` on by one |
| 14 | `bank` | the register bank user mode runs in, 0–255 |
| 15 | `bkpt` | open: a breakpoint address |

Reserved registers read as 0 and ignore writes.

### 5. Register banks

- **A bank** holds `r0`–`r15`, `HI` and `LO`. There are 256.
- **Supervisor mode runs in bank 0,** and user mode in bank `bank`. An
  exception switches to bank 0; `RTI` into user mode switches to bank
  `bank`. With `bank` = 0 the two modes share their registers.
- **`MFUR rd, rs`** copies register `rs` of bank `bank` into the
  supervisor's `rd`. **`MTUR rd, rs`** copies the supervisor's `rs` into
  register `rd` of bank `bank`.

### 6. Exceptions

| Vector | Exception | Saved PC |
|---|---|---|
| `0x8000_0000` | reset | – |
| `0x8000_0004` | non-maskable interrupt ([7](#7-interrupts), open) | the next instruction |
| `0x8000_0008` | illegal instruction | the instruction |
| `0x8000_000C` | reserved | |
| `0x8000_0010` | divide error | the instruction |
| `0x8000_0014` | address error: a misaligned access | the instruction |
| `0x8000_0018` | tag trap ([RFC 0028, 5.10](0028-rfc-draft-2-isa.md#510-tentative-instructions)) | the instruction |
| `0x8000_001C` | privilege violation | the instruction |
| `0x8000_0020` | page fault ([3](#3-the-address-space)) | the instruction |
| `0x8000_0024` | trace | the next instruction |
| `0x8000_0040` + 4L | interrupt at level L, 0–7 ([7](#7-interrupts)) | the next instruction |
| `0x8000_0100` + 4n | `SWI #n`, n = 0–255 | the next instruction |

- **Vectors** are 4 bytes apart, room for one two-parcel instruction,
  normally a relative `JMP` to the handler.
- **Entering an exception:**
  1. switch to supervisor mode and bank 0;
  2. push the PC, then `sr` as it was, on bank 0's `sp`;
  3. clear I and T;
  4. jump to the vector.
- **`RTI`** pops `sr`, then the PC, and with them the mode and the bank.
- **Precise faults.** Where the saved PC is the instruction's own, the
  instruction has changed neither the flags nor the PC, nor any register
  it addresses memory with. It may already have loaded registers or
  stored to memory, but running it again gives the same result, so `RTI`
  resumes it. For that:
  - a register an addressing mode increments or decrements changes only
    once the access has succeeded;
  - `SAVE` and `RESTORE` update `sp` last, and `LDM` and `STM` don't
    change their base register; an `LDM` whose range includes its base
    register is open
    ([RFC 0028, 5.8](0028-rfc-draft-2-isa.md#58-multiple-registers));
  - `CAS`'s locked read is checked as a store.
- **Trace:** with T set when an instruction starts, a trace exception
  follows it.
- **Bank 0's `sp`** should point into the window, where a push can't
  fault. A fault while an exception is being entered is open.

### 7. Interrupts

- **Eight request lines,** levels 0–7, 7 the highest. Each is one of the
  system bus's interrupt lines IRQ0–IRQ7
  ([RFC 0014, 8.3](0014-rfc-system-bus.md#83-interrupts-and-synchronisation)),
  or, chosen by a jumper on the CPU's board, a source on that board in
  its place.
- **Level-sensitive:** a source holds its request until its handler
  clears the cause. Several sources may share a level; the handler finds
  out which by asking them.
- **Taken** between instructions, when I is set and the highest level L
  requesting is at least IPL: never straight after `EI`, possibly
  straight after `DI`, and straight after `RTI` if the status it restores
  allows it. IPL above 8 holds off every level, as 8 does.
- **Entering** an interrupt is entering an exception ([6](#6-exceptions)),
  and also sets IPL to L + 1. The vector is `0x8000_0040` + 4L.
  - I is clear in the handler. Executing `EI` lets higher levels in, which
    is how interrupts nest.
  - `RTI` restores the I and IPL of the code it returns to.
- **`SPL #n`** sets IPL to n, 0–8, and changes nothing else
  ([RFC 0028, 5.9](0028-rfc-draft-2-isa.md#59-system-instructions)). The
  kernel raises IPL around a critical section and puts back what was
  there with:

  ```
          MFSR r1, sr      ; save
          SPL  #5          ; raise
          ...
          MTSR sr, r1      ; restore
  ```

  The restore puts back I, T and the condition codes as well.
- **A request that has gone** by the time its handler asks is answered by
  returning.
- **`HALT`** with I set waits for an interrupt, and resumes after the
  `HALT` once the handler returns. With I clear it stops until reset.
- **A non-maskable interrupt (open):** room for one, from the CPU's own
  board, through vector `0x8000_0004`, taken between instructions whatever
  I and IPL. Its source, how it's triggered, and what it does to I and
  IPL are open.
- **A register bank per level,** so that a handler saves nothing, is
  open: interrupts enter bank 0, as every exception does.
- **The timer** and other sources on the CPU's board are devices, outside
  this RFC.

### 8. Reset

Supervisor mode, bank 0, I and T clear, IPL, `ctx` and `bank` 0, and the PC at
the reset vector, which is physical address 0. Everything else is
undefined.

## Part II: Discussion

### 9. Where it comes from

The kernel study built draft 1b's system extensions as an experiment,
v1bs ([report 0020's appendix](0020-report-operating-system.md#appendix-v1bs-draft-1b-with-system-extensions)), ran a
small message-passing kernel on them and measured its paths
([report 0020](0020-report-operating-system.md)).
[RFC 0010](0010-rfc-ideas-os.md) collects the ideas around it. Part I
keeps what worked and changes the rest.

### 10. The choices

- **S is changed only by exceptions and `RTI`.** v1bs let `MTSR flags`
  set it, and the nucleus once dropped into user mode by writing the
  flags back without it
  ([report 0020](0020-report-operating-system.md#protection-modes-and-the-stack)).
- **The supervisor's bits at the top of `sr`** (Emily, 2026-10-16),
  where draft 1 had I next to N, Z, C and V:
  - byte 0 is all the user's, so `ccr` is one byte lane, with no bits to
    mask;
  - S is the sign bit, so a handler tests where an exception came from
    with `MOVS` on the saved status word and `BMI`, and it means
    supervisor as bit 31 of an address does ([3](#3-the-address-space));
  - both ends have room: user flags in bits 4–7, the supervisor's below
    bit 29.
- **`ccr` as `sr`'s low byte** (Emily, 2026-10-16), as the 68000's
  `CCR` is its `SR`'s:
  - one status word goes into the exception frame and comes back with
    `RTI`;
  - user code sees only the condition codes, and the rest traps, so a
    kernel run deprivileged can't read or quietly fail to set S, I or T.
    That is what classical virtualisation needs from the status word; the
    68010 made reading the 68000's `SR` privileged for the same reason.
  - user code rarely writes `ccr` at all: a switch between user threads is
    a call, which keeps no flags. It's for upcalls that return without a
    system call, and for emulators.
- **The window at bit 31,** proposed by Emily (2026-10-15), instead of
  v1bs's flag bits XL and XS, which made the supervisor's loads or stores
  go through the user's map.
  - **XL and XS are dropped** (Emily, 2026-10-15). They're a mode on
    every load or store: while one is set, the kernel's own stack goes
    through the user's map too, so a copy loop has to be hand-written and
    can never be compiled.
  - **With the window,** the kernel lives in physical memory above
    `0x8000_0000`, and uses a user's pointers as they are. Copying in and
    out of user memory is a plain `memcpy`, and a bad pointer is a page
    fault with `fsr` bit 7 set. The handler finds out whether the kernel
    expected one, from a table of the copy routines' addresses, say.
  - **Checking a user's pointer** is a test of its sign: bit 31 set
    means it isn't the user's.
  - **What it costs:** the window reaches the lower 2 GB of the bus's
    physical space, so where RAM, ROM and the slots sit has to suit it.
    Which address bits pick the slot is still open in RFC 0014.
  - **The kernel still reads the map** to copy between processes that
    aren't running.
- **Precise faults** are draft 1's rules
  ([RFC 0010, 3](0010-rfc-ideas-os.md#3-mmu)), plus the cases draft 2's
  instructions add. `CALL [r]+` was the one 1b form that broke them, by
  moving `r` before it pushed; with draft 2's link register a call
  pushes nothing
  ([RFC 0028, 5.7](0028-rfc-draft-2-isa.md#57-jumps-and-calls)).
  Exceptions still push the PC and the flags, so a handler that calls
  saves `r7` like any function.
- **A vector per `SWI` number:** the decode ROM sees the whole parcel, so
  each number gets its own microcode entry. A null system call spent 16
  of its 39 cycles dispatching
  ([report 0020](0020-report-operating-system.md#the-paths-measured)).
- **Interrupts by level, with vectors from the CPU.** The bus has eight
  open-collector lines and no acknowledge cycle, so a vector per level
  costs nothing on the bus and keeps simple cards simple; a vector from
  the device, as on the PDP-11, would need a bus cycle to fetch it.
  - Raising IPL to L + 1 on entry, with I clear, holds off the level being
    handled and everything below; a handler that executes `EI` lets
    higher levels in, so nesting is the handler's choice. Four bits of IPL
    are needed for that: 0 allows every level, 8 none.
  - Report 0020 measured 500–640 cycles to hand an interrupt to a
    user-level driver, so devices should interrupt for a buffer, not a
    byte ([report 0020](0020-report-operating-system.md#interrupts-and-devices)).
  - **`SPL #n`** is the PDP-11's. Without it, raising IPL takes a read,
    two masks and a write, five instructions and seven parcels; with it,
    saving and raising take two parcels. Its nine values fit the `FE`
    grid's second byte, so it needs no root cell.
  - The non-maskable interrupt is for a front-panel halt or a debugger
    button, which helps most while the hardware is being brought up. The
    bus has no line for it.
- **Special registers 8–15 are the supervisor's,** so the privilege check
  is one bit. v1bs's numbering grew one register at a time.
- **Full banks, the kernel in bank 0.** v1bs offered three policies;
  report 0020 measured them
  ([register banks](0020-report-operating-system.md#register-banks)).
  - **Full banks are the simplest:** kernel code is ordinary code with
    all 16 registers, compiled C included, and the bank lines stay
    steady through the cycle. Half banks share `r0`–`r7` between the
    modes and add a gate to the register read path; a split by mode makes
    the kernel's registers mean something different from everyone else's.
  - **What full banks cost** is copying a message between banks. A call
    and reply is 347 cycles against half banks' 293, while a preemption
    is 147 against 203. `MFUR` and `MTUR` are one parcel each to keep the
    copy cheap
    ([RFC 0028, 5.9](0028-rfc-draft-2-isa.md#59-system-instructions)).
  - **256 banks** cover as many threads as a few MB will hold; past that,
    the kernel saves a bank's registers when it reuses it. What fewer
    would cost, measured with Fen, is in
    [register-banks.md](0029-rfc-draft-2-system/register-banks.md).
  - **In the hardware:** banks are spare address lines of the register
    file's SRAMs, about 4 chips. The microcode's own constants, and the
    zero that `r0` no longer gives it, stay outside the banks.
- **The page map is v1bs's flat map,** with 128 contexts instead of 16.
  - **No misses:** the bigger workloads touch at most 223 pages, and every
    translation is in the map
    ([report 0020](0020-report-operating-system.md#translation-the-page-map)).
  - **128 contexts** take three 512K × 8 SRAMs (the AS6C4008, 55 ns, made
    in DIP) where 16 took three 128K × 8. A kernel with servers would
    outgrow 16 processes, and reassigning a context costs about 800
    cycles a switch.
  - **Page tables in RAM should be the kernel's truth,** and the map
    filled from them: 85 cycles a refill with banks. Then a tagged
    translation cache, RFC 0010's upgrade path to any number of processes
    and 32-bit spaces, could replace the map without changing more than
    the kernel's fill routine.
  - **The map stays off the instruction fetch,** which sets the clock:
    the PC's physical page is held in a register and reloaded when the PC
    leaves the page
    ([RFC 0010, 3](0010-rfc-ideas-os.md#3-mmu)). Window fetches aren't
    translated at all.
  - **DMA bypasses the map.** A window register in the slave port, which
    only the supervisor sets, would confine bus masters.

### 11. Open questions

1. **Interrupts:** whether each level gets a register bank, so that a
   handler saves nothing; and the non-maskable interrupt's source,
   triggering, and effect on I and IPL.
2. **The physical memory map:** where RAM, ROM, the I/O registers and the
   slots sit, now that the window reaches only the lower 2 GB, and what
   an access that nothing answers does.
3. **A bank-to-bank copy** of `r0`–`r7`, which would win back most of the
   message cost of full banks.
4. **The breakpoint register** (special register 15).
5. **Boot:** the reset vector is physical address 0, so a ROM has to be
   there at reset ([RFC 0010, 2](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)).
6. **`LDM` and `STM` with the base register in their range.**
7. **When, if ever, a tagged translation cache replaces the map.**
8. **Virtualisation.** With `ccr` and `sr` split, the status word no
   longer stands in the way, but the address space does: a guest kernel
   lives in the window, which user mode can't map, so a hypervisor can't
   run it natively. Guests could be paravirtualised (linked into the low
   16 MB, calling the hypervisor with `SWI`), a context could map the
   window in user mode, or virtualisation needn't be a goal.
9. **`MTSR sr` and S.** The proposal: it leaves S alone and ignores bit
   31 of what it writes. Leaving supervisor mode always goes with a jump,
   which `RTI` does in one step; clearing S on its own would switch the
   register bank under the next instruction and fetch it from the window,
   which user mode can't reach. Ignoring the bit also keeps a
   read-modify-write of `sr` from dropping privilege. The alternative is
   to trap when bit 31 is clear, which would catch the mistake report
   0020's nucleus made instead of hiding it.

### 12. Next steps

- **The system half of the draft 2 simulator,** from the kernel study's
  ([sys.rs](../studies/v1_isa/isa/src/sys.rs)) with the changes above.
  Then port the nucleus and measure its paths again with full banks and
  the window.
