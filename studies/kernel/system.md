# v1bs: draft 1b with system extensions

The system extensions this study proposes, as the simulator runs them:
draft 1b ([isa-v1b.md](../v1_isa/isa-v1b.md)) with a supervisor mode,
register banks, a flat page map and cross-mode loads and stores. They
use no new opcodes except two system-group functions, so they would fit
draft 1a just as well. Why these, and what they cost and save, is
[report 0020](../../reports/0020-report-operating-system.md).

The simulator is `Isa::V1bs` in the draft 1 crate
([sys.rs](../v1_isa/isa/src/sys.rs)), the assembler's encoder is
[asm/v1bs.rs](../v1_isa/isa/src/asm/v1bs.rs), and the disassembler is
[v1bs.py](v1bs.py). Plain 1a and 1b are unchanged: on them, everything
below traps as an illegal instruction.

## Modes

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
  that once; [report 0020](../../reports/0020-report-operating-system.md#what-was-hard)
  suggests keeping S out of `MTSR`'s reach.

## Registers and banks

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

## Special registers

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

## The page map

The flat page map of [RFC 0010](../../reports/0010-rfc-ideas-os.md#3-mmu):

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

## Faults

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
does for plain 1b; see [report 0020](../../reports/0020-report-operating-system.md#what-was-hard).

## What the simulator leaves out

- **Time.** Mode switches, bank switches and translation cost no cycles;
  the timing model costs `MFUR`/`MTUR` like a register move, `MTSR` like
  any system instruction and a fault like any trap. That is close for
  banks, which are address lines, and for a map that stays off the
  instruction fetch ([report 0020](../../reports/0020-report-operating-system.md#translation-the-page-map)).
- **DMA and other bus masters**, and so any protection from them.
- **Interrupt priorities:** there is one interrupt, the timer's.
