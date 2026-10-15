---
number: 28
type: rfc
title: Draft 2's instruction set
status: open
date: 2026-10-15
context:
  studies: [v1_isa, v1b_hw, c_compiler]
  commit: 0987e76
depends-on: [6]
---

# RFC 0028: Draft 2's instruction set

Draft 2 builds on 1b
([RFC 0006](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
This RFC is its encoding as Emily laid it out on 2026-10-15, the
measurements behind each part, and what is still open. It is a working
map: cells will move, and some instructions are tentative, defined so
they can be simulated and measured
([6.9](#69-tentative-instructions)).

The map itself is [map.json](0028-rfc-draft-2-isa/map.json), in the format
of the opcode explorer it was laid out with, an interactive page that
isn't in the repository.

## Contents

1. [Summary](#1-summary)
2. [The parcel](#2-the-parcel)
3. [What a cell costs](#3-what-a-cell-costs)
4. [The map](#4-the-map)
5. [Addressing modes](#5-addressing-modes)
6. [What is where, and why](#6-what-is-where-and-why)
7. [`r0` is a general register](#7-r0-is-a-general-register)
8. [How it was measured](#8-how-it-was-measured)
9. [Open questions](#9-open-questions)
10. [1b's gaps left open](#10-1bs-gaps-left-open)
11. [Next steps](#11-next-steps)

## 1. Summary

- **A parcel is an opcode byte and a register byte.** The opcode byte
  comes first in memory. The map's rows are its high nibble, its columns
  the low one.
- **The opcode byte is a table, not fields.** 1b's `F D M R` spent the
  same 8 bits on a cross product of 16 operations and 16 modes. Draft 2
  gives out the 256 values one by one, so an operation gets only the modes
  it uses.
- **Register numbers always sit in the register byte:** `rd` in its high
  nibble, the mode's register `R` in its low one.
- **Costs are simple.** Operands that fit the register byte take one cell.
  Each bit more doubles the cells, or the extra bits go in an extension
  parcel. Extension parcels carry data, as in draft 1: displacements,
  constants and addresses, at most two.
- **Two extension grids,** `FD` and `FE`, turn the register byte into a
  second opcode byte, for instructions that are rare or have no operands.
- **`r0` is a general register.** **decided** (Emily, 2026-10-15).
- **`MOV` never sets the flags; `MOVS` does.** Stores are written `MOV`
  too.
- **New since 1b:**
  - one-parcel 7-bit constants for `MOV` and `CMP`, labelled `MVI` and
    `CMPI` in the map;
  - one-operand instructions with every mode in one cell: `CLR`, `INC`
    and `DEC` on memory or a register, `JMP`, `CALL`;
  - a one-cell `DBNZ`;
  - constant forms of `TST`, `BIC` and multiply;
  - tables without a base register, in the special mode:
    `[abs24 + x·s]` and `[pc + d24 + x·s]`;
  - a second slot mode, `[r14 + 4R]`: the first 16 words of the current
    object in one parcel, for every operation that takes a mode;
  - `ILLEGAL` at `00`.
- **Some instructions are tentative:** `ADD.B4`, `FFS`, `POPC`, `REV`,
  `MULA`, `MERGE`, `MULFX` and the tagged operations. They're defined so
  that the simulator has them and software can use them, to measure
  whether they earn their cells ([6.9](#69-tentative-instructions)).
- **247 of the 256 root cells are used,** 9 are free.
- **Open:** `CAS` and the floating-point escape are marked out, not
  designed; `LEA`'s special mode; what `r0`'s change still needs; and the
  rest of [section 9](#9-open-questions).

## 2. The parcel

```
in memory:  byte 0     byte 1
            opcode     register byte
                       7      4 3      0
                       rd       R
```

As a little-endian 16-bit parcel, the register byte is bits 15–8 and the
opcode bits 7–0. Extension parcels follow, a 32-bit value low half first,
as in draft 1.

| Instruction | In memory |
|---|---|
| `ADD r1, [r2]+` | `46 12` |
| `MOV r3, [r4 + 8]` | `13 34` `08 00` |
| `MOV [sp + 12], r5` (a store) | `24 53` |
| `BNE .loop`, three parcels back | `B1 FD` |
| `MOV r5, #'a'` (`MVI`, the `#u7` form) | `71 5C` |
| `CLR [r6]+` | `20 66` |
| `RET` | `FD 00` |
| `HALT` | `FE 03` |
| `MOV r1, [r14 + 8]` (mode E) | `1E 12` |

- **Operand bits beyond the register byte** take the opcode byte's low
  bits, so the instruction fills an aligned block of 2, 4, 8 or 16 cells:
  - `Bcc`: the condition in the opcode's low nibble, the offset in the
    register byte;
  - `MVI`, `CMPI`: `rd` in the high nibble, the constant in the low nibble
    and opcode bits 2–0;
  - shifts by a constant: `rd`, then the count's low bit in opcode bit 0.

  Or they go in an extension parcel, like `LDM`'s last register.
- **Opcode first in memory:** a hex dump reads opcode, then registers, and
  a trap handler finds the opcode with one byte load. In the map; **open**
  ([9](#9-open-questions)).
- **Decoding costs nothing for an irregular map.** The 1b CPU decodes
  through a ROM that looks up all 16 bits of the first parcel
  ([hardware.md](../studies/v1b_hw/hardware.md#control)). What the hardware
  cares about is that register numbers sit in fixed places, and the
  register byte gives that. Constants come from a few places: the register
  byte (`Bcc`, `SWI`), its low nibble (`DBNZ`, the quick constants), or the
  low nibble and opcode bits (`MVI`, `CMPI`, shift counts). The immediate
  unit gathers them; it's wiring.
- **Quick constants should come from the instruction register.** 1b's
  microcode has a routine per value of `#q` and `#−q`, part of why it has
  1,082 routines in a control store 86% full.

## 3. What a cell costs

| Shape | Operand bits | Cells |
|---|---:|---|
| no operands | 0 | 1, or better a cell of an extension grid: still one parcel |
| `op rd, rs`; `op ea` with the mode from the register byte | 8 | 1 |
| `op rd, #n` with a 5-bit count | 9 | 2 |
| `op rd, #u7` | 11 | 8 |
| `op rd, ea` with every mode from the register byte; `Bcc` | 12 | 16, a row |
| anything wider | | an extension parcel instead |

- **An extension parcel pays when it carries data.** On the 1b hardware
  `ADD r1, [r2]` is one parcel and 5 cycles; `MOV r9, [r2]` and
  `ADD r1, r9` are two parcels and 4 + 2 cycles. A two-parcel long form of
  `ADD r1, [r2]` would also be two parcels and about 6 cycles. So a parcel
  that carries only opcode bits costs about what a second instruction
  does, and draft 2 has no general two-parcel forms. A combination without
  a one-parcel form traps, and code uses two instructions.
- **Two-parcel instructions are for what can't be split:** atomics
  (`CAS`), long operand lists (`LDM`, `STM`) and escapes with a command
  word (the floating-point escape).
- **One-parcel forms go where they're used.** 1b code executes about 90 of
  its operation × mode pairs. The 32 most frequent cover 88% of the
  executed instructions that take a mode, 48 cover 96%, 64 cover 99%.
  Those instructions are 56% of all executed instructions.

## 4. The map

`R` is the mode's register; `R+X·s` the indexed mode; `r14+4R` mode E, the
slot mode; `spec` 1b's special
mode ([5.1](#51-the-special-mode)); `+1`, `+1–2` the extension parcels; `×n`
an instruction that fills n cells. `ST` is a store, written `MOV` in draft
2's syntax; the assembler doesn't accept `ST`. Likewise `MVI` and `CMPI`
are written `MOV` and `CMP` ([6.3](#63-short-constants-row-7)).

| | _0 | _1 | _2 | _3 | _4 | _5 | _6 | _7 | _8 | _9 | _A | _B | _C | _D | _E | _F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0_ | ILLEGAL | LDM rb,ra-rc +1 | STM rb,ra-rc +1 |  | LEA [R+d16] +1 | LEA [sp+4R] | LEA [R+X·s] +1 | LEA spec +1–2 | ADD.B4 | TMOV | TTST | TADD | TSUB | TCMP | MFSR rd,n | MTSR n,rs |
| 1_ | MOV rs | MOV #q | MOV [R] | MOV [R+d16] +1 | MOV [sp+4R] | MOV [R+X·s] +1 | MOV [R]+ | MOV -[R] | MOV b[R] | MOV b[R+d16] +1 | MOV b[R]+ | MOV h[R] | MOV h[R+d16] +1 | MOV #−q | MOV [r14+4R] | MOV spec +1–2 |
| 2_ | CLR ea +0–2 | INC ea +0–2 | ST [R] | ST [R+d16] +1 | ST [sp+4R] | ST [R+X·s] +1 | ST [R]+ | ST -[R] | ST b[R] | ST b[R+d16] +1 | ST b[R]+ | ST h[R] | ST h[R+d16] +1 | DEC ea +0–2 | ST [r14+4R] | ST spec +1–2 |
| 3_ | MOVS rs | MFUR rd,rs | MOVS [R] | MOVS [R+d16] +1 | MOVS [sp+4R] | MOVS [R+X·s] +1 | MOVS [R]+ | MOVS -[R] | MOVS b[R] | MOVS b[R+d16] +1 | MOVS b[R]+ | MOVS h[R] | MOVS h[R+d16] +1 | MTUR rd,rs | MOVS [r14+4R] | MOVS spec +1–2 |
| 4_ | ADD rs | ADD #q | ADD [R] | ADD [R+d16] +1 | ADD [sp+4R] | ADD [R+X·s] +1 | ADD [R]+ | ADD -[R] | ADD b[R] | ADD b[R+d16] +1 | ADD b[R]+ | ADD h[R] | ADD h[R+d16] +1 | ADD #−q | ADD [r14+4R] | ADD spec +1–2 |
| 5_ | SUB rs | SUB #q | SUB [R] | SUB [R+d16] +1 | SUB [sp+4R] | SUB [R+X·s] +1 | SUB [R]+ | SUB -[R] | SUB b[R] | SUB b[R+d16] +1 | SUB b[R]+ | SUB h[R] | SUB h[R+d16] +1 | SUB #−q | SUB [r14+4R] | SUB spec +1–2 |
| 6_ | CMP rs | CMP #q | CMP [R] | CMP [R+d16] +1 | CMP [sp+4R] | CMP [R+X·s] +1 | CMP [R]+ | CMP -[R] | CMP b[R] | CMP b[R+d16] +1 | CMP b[R]+ | CMP h[R] | CMP h[R+d16] +1 | CMP #−q | CMP [r14+4R] | CMP spec +1–2 |
| 7_ | MVI #u7 ×8 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | CMPI #u7 ×8 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ |
| 8_ | AND rs | AND #q | AND [R] | AND [R+d16] +1 | AND [sp+4R] | AND [R+X·s] +1 | AND [R]+ | AND -[R] | AND b[R] | AND b[R+d16] +1 | AND b[R]+ | AND h[R] | AND h[R+d16] +1 | AND #−q | AND [r14+4R] | AND spec +1–2 |
| 9_ | OR rs | OR #q | OR [R] | OR [R+d16] +1 | OR [sp+4R] | OR [R+X·s] +1 | OR [R]+ | OR -[R] | OR b[R] | OR b[R+d16] +1 | OR b[R]+ | OR h[R] | OR h[R+d16] +1 | OR #−q | OR [r14+4R] | OR spec +1–2 |
| A_ | XOR rs | XOR #q | XOR [R] | XOR [R+d16] +1 | XOR [sp+4R] | XOR [R+X·s] +1 | XOR [R]+ | XOR -[R] | XOR b[R] | XOR b[R+d16] +1 | XOR b[R]+ | XOR h[R] | XOR h[R+d16] +1 | XOR #−q | XOR [r14+4R] | XOR spec +1–2 |
| B_ | Bcc s8 ×16 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ |
| C_ | LSL #n ×2 | ↳ | LSL rs |  | LSR #n ×2 | ↳ | LSR rs |  | ASR #n ×2 | ↳ | ASR rs |  | ROR #n ×2 | ↳ | ROR rs |  |
| D_ | NOT | NEG | INC | DEC | RLC | RRC | SWAP | SXB | SXH | ZXB | ZXH | CLZ | FFS | POPC | REV | SETcc |
| E_ | ADC rs | SBC rs | BIC rs | TST rs | MULU rs | MULS rs | MULA | DIVU rs | DIVS rs | DIVUL rs | BIC spec +1–2 | TST spec +1–2 | MULU spec +1–2 | MULS spec +1–2 | MERGE |  |
| F_ | JMP ea +0–2 | CALL ea +0–2 | Jcc rel16 +1 | Jcc abs32 +2 | SAVE ra-rb | RESTORE ra-rb | DBNZ r,back4 | CAS | FPU ea +1–3 |  |  |  | SWI #n | ext: misc | ext: system | ILLEGAL |

The two extension grids, with the second byte:

| `FD`, misc | | `FE`, system | |
|---|---|---|---|
| `FD 00` | `RET` | `FE 00` | `EI` |
| `FD 10` | `MULFX rd, rs, #n` (two parcels, tentative) | `FE 01` | `DI` |
| `FD FD` | `NOP` | `FE 02` | `RTI` |
| | | `FE 03` | `HALT` |

Free root cells: `03`, `C3`, `C7`, `CB`, `CF`, `EF`, `F9`–`FB`.

## 5. Addressing modes

One numbering of 16 modes is used everywhere: as the column in rows 1–6
and 8–A, and as the mode nibble `M` of instructions that take the mode
from the register byte. They are 1b's modes, in 1b's order
([isa-v1b.md](../studies/v1_isa/isa-v1b.md#addressing-modes)).

| M | Mode | M | Mode |
|---|---|---|---|
| 0 | `rs` | 8 | `byte [R]` |
| 1 | `#q`, 0…15 | 9 | `byte [R + d16]` |
| 2 | `[R]` | A | `byte [R]+` |
| 3 | `[R + d16]` | B | `half [R]` |
| 4 | `[sp + 4R]`, R is the offset | C | `half [R + d16]` |
| 5 | `[R + Rx·s + d8]`, indexed | D | `#−q`, −1…−16 |
| 6 | `[R]+` | E | `[r14 + 4R]`, R is the offset |
| 7 | `-[R]` | F | special |

- **Byte and half operands** zero-extend when read.
- **Indexed:** an extension parcel holds the index register `x`, the scale,
  the size and an 8-bit displacement:

  ```
  index parcel   15    12 11  10 9    8 7         0
                    x        s      z        d8
  ```

  The scale is ×1, ×2, ×4 or ×8, and the size byte, half or word; size 3
  traps.
- **Special:** `R` picks an operand that needs no register, in the table
  below ([5.1](#51-the-special-mode)).
- **Mode E, `[r14 + 4R]`:** the word at `r14` plus 4 × `R`, 0–60, shaped
  like mode 4 with `r14` for `sp`. **decided** (Emily, 2026-10-15).
  - `r14` holds the current object by convention: the kernel's current
    thread control block, Egret's frame record, the VM's state. It's
    callee-saved in the C convention, so C code called from them keeps it.
  - It's a mode like any other, so every operation in rows 1–6 and 8–A
    has it, and so do the instructions that take the mode from the
    register byte: `CLR [r14 + 8]`, `JMP [r14 + 20]`.
  - Measured on 1b with the mode added (the fixed-base report, in
    review): 3–5% of the nucleus's message and switch paths, and its code
    4% smaller; about 1% of Egret's cycles; nothing for the Lisp, whose
    tagged pointers put fields at 4k ± 1. Loads and stores are 75–100%
    of the uses, so the report suggested three cells; the whole column
    keeps the mode table orthogonal.
  - The assembler picks it for a word at `[r14 + 0…60]`, as it picks mode
    4 for `[sp + 0…60]`.
- **The mode from the register byte:** a one-operand instruction puts `M`
  in the register byte's high nibble and `R` in the low one, so one cell
  gets every mode. 1b's op B did this for `JMP ea` and `CALL ea`, and the
  68000's whole single-operand group works this way. A mode the
  instruction can't use traps, like `CLR #q`.
- **With `r0` a general register,** every mode works with it like any
  other register.
- **1b's gaps that remain** ([RFC 0006, 3.2](0006-rfc-ideas-isa.md#32-1bs-gaps)):
  no one-parcel `[R + small offset]` except through `r14`; no byte or
  half auto-decrement and no half auto-increment; no sign-extending loads
  (`SXB` and `SXH` after the load). [Section 10](#10-1bs-gaps-left-open)
  has what they cost and the options. The indexed mode's 8-bit displacement, which couldn't hold a
  table's address, is answered by the special mode's D and E.

### 5.1 The special mode

`M` = F uses `R` to pick an operand that needs no register. 0–C are 1b's.
D and E are new: tables without a base register. **decided** (Emily,
2026-10-15).

| R | Operand | Extension parcels | Syntax |
|---|---|---:|---|
| 0 | constant: 16 bits, sign-extended | 1 | `#-300` |
| 1 | constant: 16 bits, zero-extended | 1 | `#0xFFFF` |
| 2 | constant: 16 bits, shifted left 16 | 1 | `#0x12340000` |
| 3 | constant: 32 bits | 2 | `#0x12345678` |
| 4 | word at `[abs16]` | 1 | `[counter]` |
| 5 | byte at `[abs16]` | 1 | `byte [0xFFFFFF00]` |
| 6 | half at `[abs16]` | 1 | `half [counter]` |
| 7 | word at `[abs32]` | 2 | `[counter]`, where neither 4 nor A reaches |
| 8 | byte at `[abs32]` | 2 | `byte [counter]` |
| 9 | half at `[abs32]` | 2 | `half [counter]` |
| A | word at `[pc + d16]` | 1 | `[pc + counter]` |
| B | byte at `[pc + d16]` | 1 | `byte [pc + counter]` |
| C | half at `[pc + d16]` | 1 | `half [pc + counter]` |
| D | `[abs24 + x·s]`, any size | 2 | `[table + r2*4]`, `byte [table + r2]` |
| E | `[pc + d24 + x·s]`, any size | 2 | `[pc + table + r2*4]` |
| F | reserved: traps | | |

- **Addresses:** `abs16` and `abs24` are sign-extended, so `abs16`
  reaches the lowest and highest 32 KB and `abs24` the lowest and highest
  8 MB. `pc` is the next instruction's address: `d16` reaches ±32 KB,
  `d24` ±8 MB.
- **D and E's parcels:** first an index parcel laid out like the indexed
  mode's, whose low byte holds the address's bits 23–16, then bits 15–0:

  ```
  parcel 1       15    12 11  10 9    8 7         0
                    x        s      z     a23–16
  parcel 2       15                             0
                               a15–0
  ```

  The size comes from `z`, so one value of `R` covers bytes, halves and
  words. Like the indexed mode, the microcode dispatches on the index
  parcel as it arrives, then fetches the address.
- **By instruction:**
  - `ST`, `CLR`, `INC`, `DEC` and `LEA` trap on the constants (0–3), as
    they do on `#q`.
  - `LEA` takes the address, so its byte, half and word forms give the
    same result: `LEA r1, [table + r2*4]` is a three-operand table
    address.
  - `JMP` and `CALL` take the operand's value, as in 1b: `JMP #label`
    jumps to `label`, and `JMP [pc + table + r2*4]` to the address stored
    in the table.
- **The assembler picks the shortest form.** `[label + r2]` is mode 3, 9
  or C when the label fits 16 bits (two parcels), and D otherwise (three);
  `[table + r2*4]` is D, unless the table's address is in a base register.
- **What D and E are for:**
  - **A table without a base register.** Indexed accesses whose base was
    loaded with `MOV r, #label` are 1.47% of hand-written executed
    instructions (vm 16%, mandel 10%) and 0.19% of compiled ones. Each
    holds a register through its loop, or, where the load isn't hoisted,
    costs a `MOV` (sha256's `MOV r1, #_h` before
    `MOV r1, [r1 + r8*4]`).
  - **`[label + R]` beyond ±32 KB.** 1b's only form is the displacement
    modes with a label; D with ×1 reaches 8 MB.
  - **Position-independent jump tables,** for `switch` in relocatable
    code: `JMP [pc + table + r2*4]`. Nothing in 1b does it in one
    instruction.
  - With `r0` a general register, `[r0 + x·s + d8]` is no longer a
    base-less index either.
- **Cost:** microcode for two operands, and no cells.

## 6. What is where, and why

### 6.1 Moves (rows 1–3)

- **Row 1** is `MOV` with all 16 modes: loads, copies and constants. `1E`
  is `TMOV`.
- **Row 2** is the stores. The three slots a store can't use hold `CLR`
  (`20`), `INC` (`21`) and `DEC` (`2D`), one cell each, with every mode
  from the register byte. `2E` is `TTST`.
- **Row 3** is `MOVS`: a `MOV` that sets N and Z, with every mode except
  the quick constants. Their two cells hold the moves between register
  banks, `MFUR` (`31`) and `MTUR` (`3D`) ([6.8](#68-control-multiple-and-system-rows-0-and-f)).
- **Flags:** `MOV` never sets them. `MOVS` sets N and Z and leaves C and V,
  as draft 1's loads did. ALU operations set them as in draft 1.
  - `CLR` leaves them alone, like a store. `INC` and `DEC` set N and Z
    and leave C and V, like their register forms, in every mode.
    **decided** (Emily, 2026-10-15).
  - Almost every move whose flags anything reads is a load followed by a
    branch. Constant loads' flags were never read in any trace, and
    register copies' 21 times in 86,000
    ([RFC 0006, 3.4](0006-rfc-ideas-isa.md#34-which-movs-set-the-flags)).
  - Loads followed directly by a branch on N or Z, as a share of executed
    instructions:

    | Mode | Hand-written | Compiled C |
    |---|---:|---:|
    | `byte [R]+`: string loops | 3.91% | 0.98% |
    | `[R]`: null links | 0.75% | 0.31% |
    | `[sp + 4R]`: a spilled variable | – | 0.31% |
    | `byte [R]` | 0.05% | 0.16% |
    | `[R + d16]`, `byte [R + d16]` | 0.26% | – |
    | indexed | 0.03% | 0.14% |
    | **total** | **5.0%** | **1.9%** |

    Without `MOVS` each of these needs a `TST` after the load.
  - A constant, a register copy or a pop can then sit between a compare
    and its branch. 1b's `POP` couldn't.
- **Stores are written `MOV`:** `MOV [r2]+, r1`; a push is `MOV -[sp], r1`
  and a pop `MOV r1, [sp]+`. The operand order tells the assembler which.
  With `MOV` never setting the flags, one mnemonic reads the same for
  loads, stores, copies and constants. `ST` in the map is only a label.
  - The draft 2 assembler doesn't accept `ST`: a store is written `MOV`,
    so there's one spelling for it. **decided** (Emily, 2026-10-15).
- **`CLR`** stores zero at any size, in place of 1b's `ST r0, ea`.
  `MOV [x], #0` can assemble to it. With mode 0, `CLR r5` zeroes a
  register: one parcel, and the same instruction as `MOV r5, #0`, since
  neither touches the flags. `INC r5` and `DEC r5` likewise repeat row
  D's in-place forms. **`INC` and `DEC` on memory** are the memory
  increment RFC 0006 recommends: fib's call counter, a timer handler's
  load, add and store.

### 6.2 ALU operations (rows 4–6 and 8–A)

- **`ADD`, `SUB`, `CMP`, `AND`, `OR` and `XOR`** each have the 16 modes.
- **Memory operands are mostly `ADD` and `CMP`.** Memory operands on ALU
  operations (not counting moves, `LEA`, jumps and calls), as a share of
  executed instructions:

  | | Hand-written | Compiled C |
  |---|---:|---:|
  | `ADD` | 3.51% | 3.14% |
  | `CMP` | 0.71% | 1.92% |
  | `OR` | 0.59% | 0.35% |
  | `SUB` | 0.18% | 0.07% |
  | `XOR` | 0.15% | 0.13% |
  | `AND` | 0 | 0 |

  Each saves about a cycle over a load and an ALU operation. These rows are
  where to take cells back from: keeping `rs`, `#q`, `#−q` and the special
  mode for `AND`, `OR` and `XOR` frees up to 33.
- **Column E is mode E, `[r14 + 4R]`** ([5](#5-addressing-modes)).
- **The tagged operations** `TMOV`, `TTST`, `TADD`, `TSUB` and `TCMP`, on
  registers, are in `09`–`0D`. They trap unless their operands are integers, and
  `TADD` and `TSUB` on overflow too: −6.4% of the Lisp's compiled cycles,
  −5.5% of Egret's ([RFC 0006, 6](0006-rfc-ideas-isa.md#6-for-dynamic-languages)).
  Which tag marks an integer is open. Their definitions are tentative
  ([6.9](#69-tentative-instructions)).

### 6.3 Short constants (row 7)

- **`MVI rd, #u7`** (`70`–`77`) and **`CMPI rd, #u7`** (`78`–`7F`): a
  constant 0…127, zero-extended. `MVI` leaves the flags alone.
- **They're written `MOV rd, #c` and `CMP rd, #c`.** **decided** (Emily,
  2026-10-15).
  - Like `ST`, `MVI` and `CMPI` are only labels in the map. The assembler
    doesn't accept them, and the disassembler prints `MOV` and `CMP`.
  - They behave exactly as the other constant forms do: `MOV` leaves the
    flags alone whatever the constant's encoding, and `CMP` sets them the
    same way whether the constant took 7 bits or 16.
  - So they're one more encoding for the assembler to pick, as 1b's already
    picks between the quick constants and the special mode
    ([isa-v1b.md](../studies/v1_isa/isa-v1b.md#addressing-modes)): a quick
    constant for 0…15 and −1…−16, `#u7` for 16…127, and a 16- or 32-bit
    form for the rest. Which of the two one-parcel forms takes 0…15 is
    open ([9](#9-open-questions)).
  - A label's value isn't known when its instruction is assembled, so
    `MOV r1, #label` takes a 16- or 32-bit form, as in 1b, unless the
    linker learns to relax it.
- **Constants beyond the quick ones,** as a share of executed instructions:

  | Constant | `MOV`, hand-written | `MOV`, compiled C | `CMP`, hand-written | `CMP`, compiled C |
  |---|---:|---:|---:|---:|
  | 16…127 | 0.31% | 1.00% | 0.68% | 1.74% |
  | 128…255 | 0.00% | 0.07% | 0.04% | 0.00% |
  | −128…−17 | 0 | 0 | 0 | 0 |
  | wider | 0.73% | 0.40% | 0.30% | 0.14% |

  - Characters and small counts are 16…127. Seven bits hold them and make
    each instruction half a row.
  - Nothing loads or compares with −128…−17. The only such constant is
    `ADD r, #-48`, the compiler's `c - '0'` (0.13% of compiled
    instructions), which isn't these instructions.
  - Most hand-written "wider" loads are −256: the simulator's I/O page,
    which a real machine puts in a slot instead.
- **Compiled C compares with characters more than it loads them,** so
  the `CMP` half-row earns its place as much as the `MOV` one.

### 6.4 Branches and loops (row B, `F2`, `F3`, `F6`)

- **`Bcc`:** row B. The condition is the opcode's low nibble (E is `BRA`,
  F `BSR`), the 8-bit offset in parcels the register byte.
- **`Jcc rel16` and `Jcc abs32`:** the condition in the register byte's high
  nibble. The low nibble is spare.
- **`DBNZ r, back4`** (`F6`): decrement `r` and branch 1–16 parcels back
  unless it reached zero. It leaves the flags alone, so a carry chain
  through `ADC` survives the loop counter.
  - Decrement-and-branch-back loops are 3.6% of hand-written executed
    instructions (about 1.9% without the interrupts program's delay loop)
    and none of compiled C's, because the compiler counts up. Over 99% of
    them branch at most 16 parcels back, and all at most 32.
  - It saves a parcel per iteration, and probably a cycle on top of the
    4 that `DEC` and `BNE` take now. Compiled code would need the compiler
    to reverse loops whose index is only a counter.
  - A loop buffer would make it worth much more
    ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)).

### 6.5 Shifts (row C)

- **In place only:** `LSL`, `LSR`, `ASR` and `ROR` by a constant (two
  cells) or by a register.
- **No three-operand shifts.** A register copy feeding a shift is 1.2% of
  hand-written and 1.5% of compiled executed instructions, mostly sha256
  (10.5%) and a few percent in matmul and crc. One-parcel three-operand
  shifts would take 32 cells per kind, 128 for all four.

### 6.6 Unary (row D)

- **`rd ← f(rs)`:** `NOT` … `CLZ`, then `FFS`, `POPC` and `REV`, which
  are tentative ([6.9](#69-tentative-instructions)), and `SETcc`.
- **The separate source pays in compiled code.** `rd` ≠ `rs` is 3.0% of
  compiled executed instructions (`INC` 1.33%, `DEC` 0.66%, `NOT` 0.64%):
  the compiler's `x + 1` into another register. In hand-written code it is
  0.46%. Working in place, the whole group would fit one cell, with the
  function in the register byte.
- **`RLC`, `RRC` and `SWAP` never ran** in any program. They could share an
  in-place cell if the row gets tight.

### 6.7 Register-only ALU and constants (row E)

- **`ADC`, `SBC`, `BIC`, `TST`, `MULU`, `MULS`, `DIVU`, `DIVS`, `DIVUL`**
  on registers.
- **`BIC`, `TST`, `MULU` and `MULS` with the special mode** take 16- and
  32-bit constants, which closes 1b's "no immediate `TST`/`BIC`/`MUL`"
  gap. Dividing by a constant (`printf`'s `DIVU` by 10) takes a
  `MOV rX, #10` first.
- **`MULA` and `MERGE`** are tentative ([6.9](#69-tentative-instructions)).

### 6.8 Control, multiple and system (rows 0 and F)

- **`JMP ea` and `CALL ea`:** one cell each, with the mode from the
  register byte. `JMP r3` is mode 0.
- **`SAVE ra-rb` and `RESTORE ra-rb`:** one cell each.
  - All 29 compiled functions that save registers save `r8`–`rN`, and
    none saves a register it doesn't use, so register masks would buy
    compiled code nothing.
  - 1b unrolls one microcode routine per range: they take 1,476 of its
    3,507 microinstructions. A loop with a counting register number would
    free them
    ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)).
- **`LDM rb, ra-rc` and `STM rb, ra-rc`:** one cell each and an extension
  parcel holding `rc`, with 12 bits spare.
- **`LEA`** (`04`–`07`): `[R + d16]`, `[sp + 4R]`, indexed, and the special
  mode.
  - `LEA rd, [R]` went: it was the compiler's copy that leaves the flags
    alone, which is now `MOV`.
  - Measured: 1.9% of hand-written and 3.1% of compiled executed
    instructions. The indexed form is mostly a three-operand add,
    `rA + rB` or `rA + 2·rB`.
  - Of the special mode only the PC-relative address is new, and the only
    way to get a position-independent one. `LEA rd, [abs16]` (140 places
    in the hand-written code) is now exactly `MOV rd, #label`.
- **`SWI #n`** (`FC`): one parcel. The decode ROM sees the whole parcel, so
  each `n` can have its own microcode entry: RFC 0010's vectored `SWI`.
- **`MFSR rd, n` and `MTSR n, rs`** (`0E`, `0F`): `HI` (n = 1) is how a
  remainder or a product's high half is read.
- **The extension grids** hold instructions without operands, which are
  still one parcel there (`RET`, `NOP`, `EI`, `DI`, `RTI`, `HALT`).
- **`MFUR rd, rs` and `MTUR rd, rs`** (`31`, `3D`): the supervisor reads
  register `rs` of the user's bank into its own `rd`, or writes the
  user's `rd` from its own `rs` (v1bs's instructions,
  [studies/kernel/system.md](../studies/kernel/system.md#registers-and-banks)).
  Privileged ([RFC 0029](0029-rfc-draft-2-system.md)). With a full bank
  per thread and the kernel in a bank of its own, they are how a system call reads its arguments and writes its
  results, and how a message moves between threads, so they get one
  parcel each in the root map rather than two in `FE`.
- **`00` and `FF` are `ILLEGAL`,** so a jump into zeroed or erased memory
  traps. Draft 1 made the zero parcel `HALT`; a trap gives the kernel the
  PC.

### 6.9 Tentative instructions

**Tentative** means defined well enough to build, but not decided: the
draft 2 simulator implements these, and software should use them where
they fit, so that their use can be measured. Any of them may change or go
(Emily, 2026-10-15). The definitions follow draft 1's conventions
([isa-v1.md](../studies/v1_isa/isa-v1.md)): `rd ← f(rs)` for the unary
group, and "NZ" means N and Z from the result, with C and V unchanged.

`CAS` (`F7`) and the floating-point escape `FPU` (`F8`) are different:
they're only marked out, to be designed ([9](#9-open-questions)).

| Cell | Instruction | Does | Flags | For |
|---|---|---|---|---|
| `08` | `ADD.B4 rd, rs` | Adds each of the four bytes on its own, modulo 256: no carry crosses a byte boundary | NZ | Pixel arithmetic; finding a zero byte a word at a time |
| `DC` | `FFS rd, rs` | The index of `rs`'s lowest set bit, 0–31, or 32 if `rs` is 0: the trailing zeros, the mirror of `CLZ` | NZ | Allocator and scheduler bitmaps |
| `DD` | `POPC rd, rs` | The number of set bits in `rs`, 0–32 | NZ | Bitmaps, set sizes |
| `DE` | `REV rd, rs` | `rs` with its four bytes in reverse order | NZ | Big-endian data: SHA-256's message words, network headers, font files |
| `E6` | `MULA rd, rs` | `HI:LO ← HI:LO + rd × rs`, signed, 64 bits, like MIPS's `MADD`. `LO` is special register 2 ([RFC 0029, 4](0029-rfc-draft-2-system.md#4-special-registers)) | unchanged | Multiply-accumulate: mandel, audio, filters |
| `EE` | `MERGE rd, rs` | `rd ← (rd & ~HI) \| (rs & HI)`: `rs`'s bits where the mask in `HI` is set | NZ | Masked edges and glyph words in graphics: −20% of the glyph loop ([report 0019](0019-report-graphics.md#a-merge-under-a-mask)) |
| `FD 10` | `MULFX rd, rs, #n` | `rd ← (rd × rs) >> n`: the signed 64-bit product shifted right arithmetically by 0–31, its low 32 bits; `HI` gets the product's high half, as after `MULS`. The extension parcel holds `rd`, `rs` and `n`, with 3 bits spare | NZ; C = V = 1 if the result doesn't fit in 32 bits | Fixed-point multiply: mandel's inner loop |

The tagged operations in `09`–`0D` check that their operands are integers.
They follow the Lisp's v1bx ([studies/lisp/isa.md](../studies/lisp/isa.md)),
on registers only:

| Cell | Instruction | Does | Flags | Traps unless |
|---|---|---|---|---|
| `09` | `TMOV rd, rs` | `rd ← rs` | unchanged, like `MOV` | `rs` is an integer |
| `0A` | `TTST rd, rs` | flags of `rd & rs`, like `TST` | NZ | both are integers |
| `0B` | `TADD rd, rs` | `rd ← rd + rs` | as `ADD` | both are integers, and the sum doesn't overflow |
| `0C` | `TSUB rd, rs` | `rd ← rd − rs` | as `SUB` | as `TADD` |
| `0D` | `TCMP rd, rs` | flags of `rd − rs` | as `CMP` | both are integers |

- **The trap** has its own vector and is taken before anything is
  written, so the saved PC is the instruction's own, as in v1bx.
- **`TTST r1, r1`** checks `r1` and sets Z if it's zero and N if it's
  negative. That's the Lisp's `zero?` and its check of one operand,
  which v1bx wrote as `CMP.T r1, r0` and `MOV.T r9, r1`; neither needs a
  zero register any more.
- **The tag that marks an integer** is open ([9](#9-open-questions)).
  Until it's settled the simulator can take the Lisp's, bit 0 clear,
  which v1bx measured.

## 7. `r0` is a general register

**decided** (Emily, 2026-10-15). In draft 1 `r0` reads as zero.

- **What replaces it:** `CLR` stores zero, in memory or in a register
  (`CLR rX`).
- **What still needs a zero** ([RFC 0006, 3.3](0006-rfc-ideas-isa.md#33-r0-as-a-general-register)):
  - `ADC r5, r0` in bignum and `SBC r6, r0` in sort;
  - `MTHI r0` before a `DIVUL` chain;
  - the kernel's `MTUR r1, r0` and `MTSR mapd, r0`;
  - the Lisp's `CMP.T r1, r0`.

  These take a `CLR rX` first, or new forms: `ADC` and `SBC` with `#q`
  ([9](#9-open-questions)). The Lisp's needs neither: `TTST r1, r1` does
  the same ([6.9](#69-tentative-instructions)).
- **In the hardware:** `NEG` and the multiply and divide routines read
  `r0` as zero. A hidden register-file entry that the reset routine zeroes
  replaces it, like the loop constants at entries 24 and 25. The gates
  that keep `r0` from being written go.
- **Measured** (RFC 0006): without a zero register, compiled C takes 1.3%
  more cycles, mostly where the compiler puts a constant inside a loop; a
  15th register is worth up to 0.5–0.7%, and 6–11% in sha256.

## 8. How it was measured

On the instruction-level simulator at `0987e76`: the 20 hand-written 1b
programs and the 15 C programs compiled for 1b, with their C library.

- Shares are of executed instructions, as the mean over programs, so each
  program counts once.
- Because the C library is included, the compiled figures differ from
  [report 0011](0011-report-c-compiler.md)'s, which leave it out.
- The scripts aren't committed.
- [RFC 0006, 3.5](0006-rfc-ideas-isa.md#35-what-1b-code-uses) collects
  the counts, with some this RFC doesn't use: `LEA` by mode, the unary
  sources, the stack-slot mode.

## 9. Open questions

1. **`CAS`.** One cell holds two registers, so one operand is implicit.
   For example `CAS rs, [R]` with the expected value in `r1`, as x86's
   `CMPXCHG` has it: Z on success, the current value into `r1` on failure.
   Around it:
   - The page map should check the locked read as a write, so a read-only
     page faults before anything changes.
   - LOCK is released on a fault.
   - A locked read-modify-write of the CPU's own RAM holds off its slave
     port ([RFC 0014](0014-rfc-system-bus.md#73-locked-sequences)).
   - `XCHG` as well? `TAS` isn't needed beside the bus's semaphores.
2. **The floating-point escape.** A command word plus a mode with 32-bit
   data makes four parcels, one over draft 1's limit. Either its mode
   table leaves out the 32-bit forms, or escapes may be four parcels.
3. **`LEA` with the special mode,** or a dedicated `LEA rd, [pc + d]`? The
   register byte's spare nibble could take its displacement to 20 bits,
   ±512 KB.
4. **What `r0`'s change needs** ([7](#7-r0-is-a-general-register)): `ADC`
   and `SBC` with a constant, or a `CLR rX` first. The Lisp's
   `CMP.T r1, r0` becomes `TTST r1, r1` ([6.9](#69-tentative-instructions)).
5. **The tag that marks an integer:** the Lisp's bit 0 clear, or Egret's
   2n + 1. A register holding the expected tag bit could serve both.
6. **`LDM` and `STM`:** what their extension parcel's 12 spare bits do
   (direction, writeback). With a link register (`BL`), a range plus a
   bit for it.
7. **The opcode byte first in memory,** as in the map, or second.
8. **`MOVS rs`,** in the map. Register copies' flags were read 21 times in
   86,000.
9. **`Jcc`'s spare nibble:** a 20-bit relative offset?
10. **Sign-extending loads,** which 1a had and 1b doesn't. Proposed: none
    ([10.3](#103-sign-extending-loads)).
11. **How the assembler picks a constant's encoding:**
    - 0…15 fit both the quick constant and `#u7`. A fixed preference keeps
      the output reproducible; the proposal is the quick constant.
    - A qualifier that forces a long form, for patching code in place or
      instructions of a fixed length: `MOV.L r1, #5`, say, like ARM's
      `.W`. Only if something needs it.
12. **Room to grow:** 9 free cells, and `AND`, `OR` and `XOR`'s memory
    columns ([6.2](#62-alu-operations-rows-46-and-8a)).

## 10. 1b's gaps left open

Three of 1b's addressing gaps
([RFC 0006, 3.2](0006-rfc-ideas-isa.md#32-1bs-gaps)), and what they cost
in 1b code. Short offsets got mode E, `[r14 + 4R]`; the other two have no
cells.
Measured as in [section 8](#8-how-it-was-measured), with the same
uncommitted scripts.

### 10.1 Short offsets

There is no one-parcel `[R + small offset]`. `[R + d16]` accesses (word,
byte or half, `sp` aside), by displacement, as a share of executed
instructions:

| Displacement | Hand-written | Compiled C |
|---|---:|---:|
| 0–15 elements forward | 1.70% | 1.50% |
| …of which loads and stores | 0.78% | 0.34% |
| 1–16 elements back | 0.06% | 1.31% |
| otherwise within 255 bytes | 2.00% (life 38%) | 2.33% (life 31%) |
| 256 bytes or more: a label, `[table + R]` | 0.72% | 0.08% |

- **Loads and stores at a small offset are rare,** and nearly all of them
  are fields 1–3: `[R + 4]`, `[R + 8]`, `[R + 12]`. They're mostly bst's
  child pointers and vm's state. In compiled C the small forward offsets
  are mostly `LEA`, a pointer plus 4 into another register (matmul,
  wordfreq, queens).
- **The backward ones are the compiler's `a[i-1]`,** with its loop
  pointer on `a[i]`, and sha256's `W[t-2]` … `W[t-16]`. That is a
  compiler choice as much as a gap.
- **Life's 34-byte rows** are most of the rest. No short form reaches them.
- **What a short form would save is small.** On the 1b hardware a word at
  `[R + 4]` takes 5 cycles against 4 for `[R]`, and a byte 4 either way, so
  about 0.2% of hand-written cycles and 0.1% of compiled ones. With RFC
  0007's wide fetch the extension parcel arrives with the opcode, and the
  cycle mostly goes; the parcel stays.
- **The strongest case isn't in these programs:** the kernel study pays a
  cycle per control-block field
  ([report 0020](0020-report-operating-system.md#the-rest)).
- **Options:**
  - **`MOV` and `ST` with `[R + 4k]`,** k = 1–3 or 1–4: 4 cells each, 8 in
    all, in aligned blocks of 4. None is free now; moving `ADD.B4` would
    free `08`–`0B`.
  - **A second fixed-base slot,** shaped like `[sp + 4R]`: `[rT + 4R]`,
    with `rT` a register set aside by convention for the current object,
    such as the kernel's current thread, the Lisp's environment or the VM's
    state. One cell each for `MOV` and `ST` gives 16 word fields. It pays
    only if the software dedicates the register.
- **Decided:** the second fixed-base slot, as mode E with `r14`, after
  the fixed-base report measured it on the kernel, Egret and the Lisp
  (Emily, 2026-10-15; [5](#5-addressing-modes)). Short offsets through any
  register are not proposed.

### 10.2 More auto-increment and auto-decrement modes

1b has `[R]+`, `-[R]` and `byte [R]+`, but no byte or half auto-decrement
and no half auto-increment. Counted as a plain `[R]` access with its
pointer stepped by the access size in the instruction just before or
after, beside the modes 1b has:

| | Hand-written | Compiled C |
|---|---:|---:|
| `byte [R]+`, in 1b | 7.65% | 2.97% |
| `[R]+` / `-[R]`, in 1b | 3.70% / 2.12% | 0.72% / 0 |
| a byte access with a step back | 0.01% | 0 |
| a half access with a step forward | 0.04% (crc) | 0 |
| a half access with a step back | 0 | 0 |

- **Practically nothing wants them.** Hand-written code was written
  around 1b and may avoid what it lacks, but compiled C avoids nothing and
  shows none either. Its stray hits are a byte pre-increment (`*++p`,
  0.13%, in strings) and word steps the compiler didn't fold into `[R]+`
  (sha256), which is a peephole's job.
- **The usual users,** `memmove` with overlap and string reversal, don't
  run here, and Heron's graphics are 1–8 bits per pixel, so there are no
  halfword streams.
- **The count misses** a step further from its access than the next
  instruction.
- **Option:** they'd need only `MOV`, not a column: `MOV rd, byte -[R]`
  and `MOV byte -[R], rs`, 2 cells.
- **Proposed:** none until a program needs them.

### 10.3 Sign-extending loads

Byte and half loads zero-extend, so a signed one takes `SXB` or `SXH`
after it:

| | Hand-written | Compiled C |
|---|---:|---:|
| `SXB` | 0.19%, all right after a byte load (vm 3.9%) | 0 |
| `SXH` | 0.08%, none right after a load (rpn, arith) | 0.01% |

- **Compiled C never needs it:** plain `char` is unsigned
  ([compiler.md](../studies/c_compiler/compiler.md)), and `short` is
  rare.
- **The one user is vm,** loading signed bytecode operands.
- **Draft 0 pointed the same way:** 97% of the byte loads feeding an ALU
  operation wanted zero extension
  ([RFC 0006, 2](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
- **A load and `SXB`** cost a parcel and 2 cycles more than a signed load
  would. A signed load takes a cell per mode: `MOV rd, sbyte [R]+`, say.
- **Proposed:** none. A C ABI with a signed `char` would change this, and
  there's no reason for one.

## 11. Next steps

- **Draft 2 in the instruction-level simulator:** an ISA beside v1a, v1b,
  v1bs and v1bx in the draft 1 crate, with its assembler, the tentative
  instructions included. Then retarget the C compiler, the Lisp, Egret,
  the graphics library and the kernel, using the tentative instructions
  where they fit, and measure it against 1b.
- **An estimate of draft 2's microcode,** with `SAVE` and `RESTORE` as
  loops and the quick constants from the instruction register.
- **A loop buffer in the cycle model**
  ([studies/v1b_tradeoffs](../studies/v1b_tradeoffs/README.md)).
- **Once this is accepted,** draft 2 gets its own `isa/` folder
  ([RFC 0000](0000-rfc-repository-layout.md#python-packaging)) and
  `docs/` follows.
