---
number: 28
type: rfc
title: Draft 2's instruction set
status: open
date: 2026-10-15
context:
  studies: [v1_isa, v1b_hw, c_compiler]
  commit: 48eafdf
depends-on: [6]
---

# RFC 0028: Draft 2's instruction set

Draft 2's instructions, their encoding and their assembler syntax. Part I
is the specification, with what isn't decided marked **open**; Part II is
where it comes from, the measurements behind it and the open questions.
What the CPU gives an operating system (modes, register banks, address
translation, exceptions) is [RFC 0029](0029-rfc-draft-2-system.md).

The opcode map is also in [map.json](0028-rfc-draft-2-isa/map.json), in
the format of the opcode explorer it was laid out with.

## Part I: Specification

### 1. The machine

- **32 bits:** registers, addresses and the ALU.
- **Memory** is byte-addressed and little-endian. Data is a byte (8
  bits), a half (16) or a word (32). A half must be at an even address
  and a word at a multiple of 4; a misaligned access is an address error
  ([RFC 0029, 6](0029-rfc-draft-2-system.md#6-exceptions)). A byte or half
  read as an operand is zero-extended to 32 bits; storing one writes the
  low byte or half of the register.
- **Registers:**

  | Register | |
  |---|---|
  | `r0`–`r15` | general, 32 bits |
  | `r0` | also the high half of a product and the remainder of a divide ([5.3](#53-multiply-and-divide)), and `MERGE`'s mask |
  | `r1` | also the low half of `MULA`'s sum ([5.10](#510-tentative-instructions)) |
  | `r7` | also the link register: every call writes the return address into it ([5.7](#57-jumps-and-calls)) |
  | `r14` | also the base of mode E, `[r14 + 4R]` ([3](#3-addressing-modes)) |
  | `r15`, `sp` | also the stack pointer, which `SAVE`, `RESTORE`, mode 4 and exceptions use |
  | `PC` | 32 bits, always even |
  | `ccr` | the condition codes N (negative), Z (zero), C (carry) and V (overflow): special register 0, the low byte of the status register `sr` |

  The status register's other bits, the special registers other than `ccr`, the
  modes, register banks, address translation, exceptions and reset are
  [RFC 0029](0029-rfc-draft-2-system.md)'s. The calling convention beyond
  `r7` and `sp` is **open**.

### 2. Instruction format

```
in memory:  byte 0     byte 1
            opcode     register byte
                       7      4 3      0
                       d        s
```

- **An instruction** is a first parcel of 16 bits and 0–2 extension
  parcels. The first parcel is an opcode byte and a register byte, the
  opcode first in memory: read as a little-endian parcel, the register
  byte is bits 15–8. Instructions are 2-byte aligned.
- **Extension parcels** follow the first. They hold displacements,
  constants, addresses and the indexed mode's index; a 32-bit value takes
  two, low half first.
- **The register byte** holds register numbers in fixed places: `rd` (or
  the mode `M`) in its high nibble `d`, and `rs` or the mode's register
  `R` in its low nibble `s`.
- **Wider fields** take low bits of the opcode byte as well, so that the
  instruction fills an aligned block of 2, 8 or 16 cells of the map. A
  field split between the two bytes has its high bits in the register
  byte and its low bits in the opcode byte.
- **The extension grids** `FD` and `FE` make the register byte a second
  opcode byte; an instruction there has its operands, if any, in an
  extension parcel.
- **Every encoding this specification doesn't define traps** as an
  illegal instruction: the free cells of the map and of the extension
  grids, reserved bits that aren't 0, modes an instruction doesn't take,
  the index parcel's size 3 and the special mode's `R` = F.

| Instruction | In memory |
|---|---|
| `ADD r1, [r2]+` | `46 12` |
| `MOV r3, [r4 + 8]` | `13 34` `08 00` |
| `MOV [sp + 12], r5` (a store) | `24 53` |
| `MOV r1, [r14 + 8]` (mode E) | `1E 12` |
| `BNE .loop`, three parcels back | `B1 FD` |
| `MOV r5, #'a'` (the 7-bit constant) | `71 5C` |
| `CLR [r6]+` | `20 66` |
| `RET`, which is `JMP r7` | `F0 07` |
| `HALT` | `FE 03` |

### 3. Addressing modes

One numbering of 16 modes is used everywhere: as the column in rows 1–6
and 8–A of the map and in `LEA`'s cells in row 0, and as the mode nibble
`M` of instructions that take it from the register byte
([below](#the-mode-from-the-register-byte)).

| M | Operand | Extension parcels |
|---|---|---:|
| 0 | the register `R` | 0 |
| 1 | the constant `R`, 0…15 | 0 |
| 2 | the word at `R` | 0 |
| 3 | the word at `R` + d16 | 1 |
| 4 | the word at `sp` + 4 × `R`, 0…60 | 0 |
| 5 | indexed: at `R` + `x` × s + d8, any size ([below](#the-index-parcel)) | 1 |
| 6 | the word at `R`, then `R` ← `R` + 4 | 0 |
| 7 | `R` ← `R` − 4, then the word at `R` | 0 |
| 8 | the byte at `R` | 0 |
| 9 | the byte at `R` + d16 | 1 |
| A | the byte at `R`, then `R` ← `R` + 1 | 0 |
| B | the half at `R` | 0 |
| C | the half at `R` + d16 | 1 |
| D | the constant −(`R` + 1), −1…−16 | 0 |
| E | the word at `r14` + 4 × `R`, 0…60 | 0 |
| F | special: `R` picks the operand ([3.1](#31-the-special-mode)) | 0–2 |

- **Displacements** (d16, d8) are signed.
- **Auto-increment and auto-decrement** change `R` only once the access
  has succeeded. A load whose `rd` is the mode's own `R` (`MOV r1, [r1]+`)
  is **open**.

#### The index parcel

Mode 5's extension parcel, and the first of the special mode's tables:

```
15    12 11  10 9    8 7         0
   x        s      z       d8
```

`x` is the index register, `s` the scale (×1, ×2, ×4, ×8), and `z` the
size: byte, half, word, or 3, which traps.

#### The mode from the register byte

An instruction with one operand (`CLR`, `INC` and `DEC` on any operand,
`JMP`, `CALL`, the floating-point escape) holds `M` in the register byte's
high nibble and `R` in its low one, so one cell takes every mode.

#### Which instructions take which modes

| Instruction | Modes |
|---|---|
| `MOV rd, src`, `ADD`, `SUB`, `CMP`, `AND`, `OR`, `XOR` | all |
| `MOV dst, rs`, a store | the memory modes: all but 0, 1, D and the special mode's constants |
| `MOVS rd, src` | all but 1 and D; the special mode's constants are **open** |
| `CLR`, `INC`, `DEC` | all but 1, D and the special mode's constants |
| `LEA rd, ea` | 3, 4, 5, E and the special mode's memory operands |
| `JMP`, `CALL` | all; a byte or half memory operand traps (**open**) |
| `BIC`, `TST`, `MULU`, `MULS` | a register, or any of the special mode's operands |

#### 3.1 The special mode

`M` = F uses `R` to pick an operand that needs no register:

| R | Operand | Extension parcels |
|---|---|---:|
| 0 | a 16-bit constant, sign-extended | 1 |
| 1 | a 16-bit constant, zero-extended | 1 |
| 2 | a 16-bit constant shifted left 16 | 1 |
| 3 | a 32-bit constant | 2 |
| 4, 5, 6 | the word, byte or half at abs16, sign-extended | 1 |
| 7, 8, 9 | the word, byte or half at abs32 | 2 |
| A, B, C | the word, byte or half at `PC` + d16 | 1 |
| D | at abs24, sign-extended, + `x` × s, any size | 2 |
| E | at `PC` + d24 + `x` × s, any size | 2 |
| F | traps | – |

- **`PC`** is the address of the next instruction.
- **D and E** take an index parcel whose low byte holds bits 23–16 of
  their address or displacement, then a parcel with bits 15–0:

  ```
  parcel 1   15    12 11  10 9    8 7         0
                x        s      z     a23–16
  parcel 2   15                             0
                           a15–0
  ```

### 4. The opcode map

The rows are the opcode byte's high nibble, the columns its low one. `R`
is the mode's register, `R+X·s` the indexed mode, `r14+4R` mode E, `spec`
the special mode; `+1`, `+1–2` are extension parcels, and `×n` an
instruction that fills n cells. `ST`, `MVI` and `CMPI` are only labels:
the instructions are written `MOV` and `CMP` ([6](#6-assembler-syntax)).

| | _0 | _1 | _2 | _3 | _4 | _5 | _6 | _7 | _8 | _9 | _A | _B | _C | _D | _E | _F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0_ | ILLEGAL | LDM rb,ra-rc +1 | STM rb,ra-rc +1 | LEA [R+d16] +1 | LEA [sp+4R] | LEA [R+X·s] +1 | MFSR rd,n | MTSR n,rs | ADD.B4 | TMOV | TTST | TADD | TSUB | TCMP | LEA [r14+4R] | LEA spec +1–2 |
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

The extension grids, by their second byte:

| `FD` | | `FE` | |
|---|---|---|---|
| `FD 00` | `MULFX rd, rs, #n` +1 (tentative) | `FE 00` | `EI` |
| | | `FE 01` | `DI` |
| | | `FE 02` | `RTI` |
| | | `FE 03` | `HALT` |
| | | `FE 10`–`FE 18` | `SPL #n` |

Free, and so trapping: the root cells `C3`, `C7`, `CB`, `CF`, `EF` and
`F9`–`FB`; `FD 01`–`FD FF`; `FE 04`–`FE 0F` and `FE 19`–`FE FF`. `CAS`
(`F7`) and the floating-point escape (`F8`) are **open** and trap until
they're designed. What becomes of `FD` is **open**.

### 5. Instructions

In the tables, `src` is an operand in one of the modes, `rs` a register;
**NZ** sets N and Z from the result and leaves C and V; **NZCV** sets all
four; **–** changes no flag. Unless a table says otherwise, the register
byte holds `rd` (or `ra`, or `r`) in its high nibble and `rs` (or the
mode's `R`) in its low one.

**Conditions,** for `Bcc`, `Jcc` and `SETcc`:

| cc | Name | Holds when | cc | Name | Holds when |
|---|---|---|---|---|---|
| 0 | `EQ` | Z | 1 | `NE` | not Z |
| 2 | `CS`, `HS` | C | 3 | `CC`, `LO` | not C |
| 4 | `MI` | N | 5 | `PL` | not N |
| 6 | `VS` | V | 7 | `VC` | not V |
| 8 | `HI` | C and not Z | 9 | `LS` | not C, or Z |
| A | `GE` | N = V | B | `LT` | N ≠ V |
| C | `GT` | not Z, and N = V | D | `LE` | Z, or N ≠ V |
| E | `RA` | always | F | | a call, for `Bcc` and `Jcc` |

#### 5.1 Moves

| Instruction | Cells | Operation | Flags |
|---|---|---|---|
| `MOV rd, src` | row 1 | `rd` ← `src` | – |
| `MOV rd, #u7` | `70`–`77` | `rd` ← a constant 0…127 | – |
| `MOV dst, rs` | row 2 | `dst` ← `rs`: a store | – |
| `MOVS rd, src` | row 3 | `rd` ← `src` | NZ |
| `CLR dst` | `20` | `dst` ← 0, at the operand's size | – |
| `INC dst` | `21` | `dst` ← `dst` + 1, at the operand's size | NZ |
| `DEC dst` | `2D` | `dst` ← `dst` − 1, at the operand's size | NZ |
| `LEA rd, ea` | `03`–`05`, `0E`, `0F` | `rd` ← the operand's address | – |

- **`MOV rd, #u7`** holds the constant's bits 6–3 in the register byte's
  low nibble and its bits 2–0 in the opcode's.
- **For a byte or half operand,** `MOVS` takes N from the operand's bit 7
  or 15, and Z from the operand (**decided**, Emily, 2026-10-15). So do
  `INC` and `DEC`, from the value they store (**open**).
- **`LEA`'s cells** are its modes' columns: `03`–`05` are modes 3–5,
  `0E` mode E and `0F` the special mode (**decided**, Emily, 2026-10-16).
- **`LEA`'s byte, half and word forms** give the same address.
- **`MOV r0, r0`** (`10 00`) changes nothing: it is `NOP`.

#### 5.2 Arithmetic and logic

| Instruction | Cells | Operation | Flags |
|---|---|---|---|
| `ADD rd, src` | row 4 | `rd` ← `rd` + `src` | NZCV |
| `SUB rd, src` | row 5 | `rd` ← `rd` − `src` | NZCV |
| `CMP rd, src` | row 6 | the flags of `rd` − `src` | NZCV |
| `CMP rd, #u7` | `78`–`7F` | the flags of `rd` − a constant 0…127 | NZCV |
| `AND rd, src` | row 8 | `rd` ← `rd` & `src` | NZ |
| `OR rd, src` | row 9 | `rd` ← `rd` \| `src` | NZ |
| `XOR rd, src` | row A | `rd` ← `rd` ^ `src` | NZ |
| `ADC rd, rs` | `E0` | `rd` ← `rd` + `rs` + C | NZCV, Z sticky |
| `SBC rd, rs` | `E1` | `rd` ← `rd` − `rs` − (1 − C) | NZCV, Z sticky |
| `BIC rd, src` | `E2`, `EA` | `rd` ← `rd` & ~`src` | NZ |
| `TST rd, src` | `E3`, `EB` | the flags of `rd` & `src` | NZ |

- **C** is the carry out of an addition, and "no borrow" for a
  subtraction: after `CMP a, b`, `HS` means `a` ≥ `b` unsigned.
- **Z sticky:** `ADC` and `SBC` can clear Z but never set it, so a 64-bit
  compare or subtraction (`CMP` the low words, `SBC` the high) leaves Z
  set only if the whole result is zero.
- **`CMP rd, #u7`** splits its constant as `MOV rd, #u7` does.
- **Every operation is 32 bits wide;** a byte or half operand is
  zero-extended first.

#### 5.3 Multiply and divide

| Instruction | Cells | Operation | Flags |
|---|---|---|---|
| `MULU rd, src` | `E4`, `EC` | `r0`:`rd` ← `rd` × `src`, unsigned | NZ from `rd`; C = V = 1 if the product needs more than 32 bits, else 0 |
| `MULS rd, src` | `E5`, `ED` | `r0`:`rd` ← `rd` × `src`, signed | the same, signed |
| `DIVU rd, rs` | `E7` | `rd` ← `rd` ÷ `rs`, `r0` ← the remainder, unsigned | NZ from `rd`; C = V = 0 |
| `DIVS rd, rs` | `E8` | `rd` ← `rd` ÷ `rs` rounded toward zero, `r0` ← the remainder, with the dividend's sign | NZ from `rd`; C = 0; V below |
| `DIVUL rd, rs` | `E9` | `rd` ← `r0`:`rd` ÷ `rs`, `r0` ← the remainder, unsigned | NZ from `rd`; C = 0; V below |

- **Dividing by zero** is a divide error, and changes nothing.
- **`DIVS`** of −2³¹ by −1 gives −2³¹, remainder 0, and sets V.
- **`DIVUL`** with `r0` ≥ `rs` would overflow: it sets V and changes
  nothing else.
- **The operands are read before anything is written,** so `src` and `rs`
  may be `r0`.
- **Where two results meet in one register,** the later stays: an
  addressing mode's update, then `r0`'s, then `rd`'s. So `MULU r0, src`
  gives the low 32 bits of the product, `DIVU r0, rs` the quotient, and
  `MULU r2, [r0]+` leaves the high half in `r0` (**open**).

#### 5.4 Unary operations

`rd` ← f(`rs`), in row D. `NOT r1` is short for `NOT r1, r1`.

| Cell | Instruction | f | Flags |
|---|---|---|---|
| `D0` | `NOT` | ~`rs` | NZ |
| `D1` | `NEG` | 0 − `rs` | NZCV |
| `D2` | `INC` | `rs` + 1 | NZ |
| `D3` | `DEC` | `rs` − 1 | NZ |
| `D4` | `RLC` | (`rs` << 1) \| C, C ← bit 31 | NZ, C; V ← 0 |
| `D5` | `RRC` | (`rs` >> 1) \| (C << 31), C ← bit 0 | NZ, C; V ← 0 |
| `D6` | `SWAP` | `rs` with its halves swapped | NZ |
| `D7` | `SXB` | the low byte, sign-extended | NZ |
| `D8` | `SXH` | the low half, sign-extended | NZ |
| `D9` | `ZXB` | the low byte, zero-extended | NZ |
| `DA` | `ZXH` | the low half, zero-extended | NZ |
| `DB` | `CLZ` | the number of leading zero bits, 0…32 | NZ |
| `DC`–`DE` | `FFS`, `POPC`, `REV` | tentative ([5.10](#510-tentative-instructions)) | |

**`SETcc rd`** (`DF`): `rd` ← 1 if condition cc holds, else 0. The
register byte holds `rd` and cc; cc = F traps (**open**). Flags: –.

#### 5.5 Shifts

In place, in row C:

| Instruction | Cells | Operation |
|---|---|---|
| `LSL rd, #n`, `LSL rd, rs` | `C0`–`C1`, `C2` | logical shift left |
| `LSR rd, #n`, `LSR rd, rs` | `C4`–`C5`, `C6` | logical shift right |
| `ASR rd, #n`, `ASR rd, rs` | `C8`–`C9`, `CA` | arithmetic shift right |
| `ROR rd, #n`, `ROR rd, rs` | `CC`–`CD`, `CE` | rotate right |

- **The count** is n, 0…31, or `rs` & 31. n's bit 0 is the opcode's
  bit 0, and its bits 4–1 the register byte's low nibble (**open**).
- **Flags:** NZ; C is the last bit shifted out, or for `ROR` the new
  bit 31, and unchanged for a count of 0; V ← 0.

#### 5.6 Branches

| Instruction | Cells | Operation | Flags |
|---|---|---|---|
| `Bcc label` | `B0`–`BF` | if cc holds, `PC` ← `PC` + 2 × s8 | – |
| `Jcc label` | `F2` +1 | if cc holds, `PC` ← `PC` + 2 × s16 | – |
| `Jcc label` | `F3` +2 | if cc holds, `PC` ← a 32-bit address, with bit 0 cleared | – |
| `DBNZ r, label` | `F6` | `r` ← `r` − 1; if `r` ≠ 0, `PC` ← `PC` − 2k | – |

- **`PC`** is the address of the next instruction.
- **`Bcc`** holds cc in the opcode's low nibble and s8 in the register
  byte. cc = E is `BRA`, and cc = F is `BSR`, a call
  ([5.7](#57-jumps-and-calls)).
- **`Jcc`** holds cc in the register byte's high nibble and its low
  nibble must be 0, and cc = E is `JMP`, cc = F `CALL` (**open**). s16 is
  the extension parcel.
- **`DBNZ`** holds `r` in the register byte's high nibble and k − 1 in its
  low nibble: it branches k = 1…16 parcels back (**open**).

#### 5.7 Jumps and calls

| Instruction | Cell | Operation |
|---|---|---|
| `JMP ea` | `F0` | `PC` ← the operand's value |
| `CALL ea` | `F1` | `PC` ← the operand's value, and `r7` ← the address of the next instruction |

- **The operand's value:** a register's contents, a constant, or the word
  stored at a memory operand, so `JMP [table + r2*4]` is a jump table.
  `CALL` reads it before it writes `r7`, so `CALL r7` calls the address
  `r7` held.
- **Every call** (`CALL ea`, `BSR`, `Jcc` with cc = F) writes the next
  instruction's address into `r7` and pushes nothing (**decided**, Emily,
  2026-10-15). A return is `JMP r7`, and `JMP [sp]+` returns to an
  address that was pushed.
- No flags change.

#### 5.8 Multiple registers

| Instruction | Cells | Operation |
|---|---|---|
| `SAVE ra-rb` | `F4` | `sp` ← `sp` − 4n, then `ra`…`rb` to `[sp]`, `[sp + 4]`, … |
| `RESTORE ra-rb` | `F5` | `ra`…`rb` from `[sp]`, `[sp + 4]`, …, then `sp` ← `sp` + 4n |
| `LDM rb, ra-rc` | `01` +1 | `ra`…`rc` from `[rb]`, `[rb + 4]`, … |
| `STM rb, ra-rc` | `02` +1 | `ra`…`rc` to `[rb]`, `[rb + 4]`, … |

- **`SAVE` and `RESTORE`** hold `ra` and `rb` in the register byte, any
  range with `ra` ≤ `rb` ≤ 14; any other traps (**open**).
- **`LDM` and `STM`** hold `ra` and `rb` in the register byte, and `rc`
  in bits 15–12 of the extension parcel, whose other bits must be 0
  (**open**). `rc` < `ra` traps. `rb` doesn't change. An `LDM` whose
  range includes `rb` is **open**.
- n is the number of registers. No flags change.

#### 5.9 System instructions

| Instruction | Cell | Operation |
|---|---|---|
| `MFSR rd, n` | `06` | `rd` ← special register n |
| `MTSR n, rs` | `07` | special register n ← `rs`; n in the high nibble |
| `MFUR rd, rs` | `31` | `rd` ← register `rs` of the user's register bank |
| `MTUR rd, rs` | `3D` | register `rd` of the user's register bank ← `rs` |
| `SWI #n` | `FC` | a software interrupt, n in the register byte |
| `EI`, `DI` | `FE 00`, `FE 01` | interrupts on, off |
| `RTI` | `FE 02` | return from an exception |
| `HALT` | `FE 03` | stop; with interrupts on, wait for one |
| `SPL #n` | `FE 10`–`FE 18` | the interrupt priority level ← n, 0…8, from the second byte's low nibble |
| `ILLEGAL` | `00`, `FF` | an illegal instruction |

What each special register is, which instructions are privileged, and
what exceptions do are [RFC 0029](0029-rfc-draft-2-system.md)'s.

#### 5.10 Tentative instructions

Defined so they can be built and measured, and not decided: any may
change or go (Emily, 2026-10-15).

| Cell | Instruction | Operation | Flags |
|---|---|---|---|
| `08` | `ADD.B4 rd, rs` | each of the four bytes added on its own, modulo 256 | NZ |
| `DC` | `FFS rd, rs` | the index of `rs`'s lowest set bit, 0…31, or 32 if `rs` = 0 | NZ |
| `DD` | `POPC rd, rs` | the number of set bits in `rs`, 0…32 | NZ |
| `DE` | `REV rd, rs` | `rs` with its four bytes in reverse order | NZ |
| `E6` | `MULA rd, rs` | `r0`:`r1` ← `r0`:`r1` + `rd` × `rs`, signed, 64 bits | – |
| `EE` | `MERGE rd, rs` | `rd` ← (`rd` & ~`r0`) \| (`rs` & `r0`) | NZ |
| `FD 00` | `MULFX rd, rs, #n` | `rd` ← the low 32 bits of the signed product `rd` × `rs` shifted right arithmetically by n, 0…31; `r0` ← the product's high half, as `MULS` gives it | NZ; C = V = 1 if the result needs more than 32 bits |

`MULFX`'s extension parcel holds `rd` in bits 15–12, `rs` in 11–8 and n
in 4–0; bits 7–5 must be 0.

**The tagged operations** check that their operands are integers, tagged
with bit 0 clear (**open**). A failed check is a tag trap
([RFC 0029, 6](0029-rfc-draft-2-system.md#6-exceptions)), taken before
anything changes.

| Cell | Instruction | Operation | Flags | Traps unless |
|---|---|---|---|---|
| `09` | `TMOV rd, rs` | `rd` ← `rs` | – | `rs` is an integer |
| `0A` | `TTST rd, rs` | the flags of `rd` & `rs` | NZ | both are |
| `0B` | `TADD rd, rs` | `rd` ← `rd` + `rs` | NZCV | both are, and the sum doesn't overflow |
| `0C` | `TSUB rd, rs` | `rd` ← `rd` − `rs` | NZCV | both are, and the difference doesn't overflow |
| `0D` | `TCMP rd, rs` | the flags of `rd` − `rs` | NZCV | both are |

### 6. Assembler syntax

The assembler's directives, expressions and labels are those of infra's
assembler ([infra](../infra/README.md)). Whether mnemonics and register
names may be written in either case is **open**.

- **Registers:** `r0`–`r15`, and `sp` for `r15`.
- **Operands:**

  | Written | Mode |
  |---|---|
  | `r2` | 0 |
  | `#c` | a constant: 1, D, the 7-bit form, or the special mode's |
  | `[r2]`, `[r2]+`, `-[r2]` | 2, 6, 7 |
  | `[r2 + d]`, `[r2 - d]` | 3; 2 for d = 0, and 4 or E for a word at `sp` or `r14` + 0…60 |
  | `[r2 + r3*s + d]` | 5; s is 1, 2, 4 or 8 |
  | `[label]` | the special mode: abs16, `PC` + d16 or abs32 |
  | `[pc + label]` | the special mode, `PC`-relative |
  | `[label + r3*s]` | 3, 9 or C where s is 1 and `label` fits 16 bits, else the special mode's D |
  | `[pc + label + r3*s]` | the special mode's E |

  `byte` or `half` before a memory operand gives its size: `byte [r2]+`.
- **Stores** are `MOV dst, rs`: `MOV [r2 + 8], r1`. The operand order
  says which.
- **Shorthands,** which the disassembler prints too (**decided**, Emily,
  2026-10-15):

  | Written | Is |
  |---|---|
  | `PUSH r1` | `MOV -[sp], r1` |
  | `POP r1` | `MOV r1, [sp]+` |
  | `RET` | `JMP r7` |
  | `NOP` | `MOV r0, r0` |

- **Not accepted:** `ST`, `MVI` and `CMPI` (**decided**, Emily,
  2026-10-15), and `LI`, `MFF` and `MTF` (**open**). The assembler says
  what to write instead.
- **One spelling per instruction:** the assembler takes what the
  disassembler prints (**open**).
- **Special registers** are written by name (`ccr` and RFC 0029's, such as
  `sr`) or by number.
- **Branches and calls:** `Bcc label`, `BRA`, `BSR`; `JMP label` and
  `CALL label` are `Jcc` with cc = E and F, and `JMP #label` is `JMP ea`.
  A `Bcc` out of reach becomes the `Jcc` with the same condition, and
  `BSR` becomes `CALL`.
- **The encoding** is the shortest that holds the operand:
  - **Constants:** the quick constant for 0…15 and −1…−16, the 7-bit form
    for 16…127 (`MOV` and `CMP`), then the special mode's 16-bit forms and
    its 32-bit one. The quick constant takes 0…15 (**open**). A label's
    value isn't known when it's assembled, so `#label` takes a 16- or
    32-bit form.
  - **`[R + d]`:** `[R]` for d = 0, then mode 4 or E for a word at
    `sp` or `r14` + 0…60, then `[R + d16]`, then the special mode's D with
    `R` as its index where d needs 17–24 bits (**open**).
  - **An absolute address:** abs16, then `PC` + d16, then abs32.
  - **`LEA rd, [R]`** is `MOV rd, R`, since `LEA` has no mode 2
    (**open**).
  - **`BIC`, `TST`, `MULU` and `MULS` with a memory operand** have only
    the special mode, so `[R + d]` becomes D with `R` as its index
    (**open**).
  - **`INC r5` and `DEC r5`** are row D's forms; `MOV [x], #0` is
    `CLR [x]`.
- **`.align`** pads code with `NOP`.

## Part II: Discussion

### 7. Where it comes from

Draft 2 builds on draft 1b
([RFC 0006](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)):
one register and one addressing mode per instruction, the same 16 modes,
draft 1's instruction semantics. Emily laid out its encoding in the
opcode explorer on 2026-10-15, and the decisions since are marked in
Part I. The draft 2 study (`studies/v2_isa`, in review) builds the
simulator, the assembler and the C compiler from it; where Part I
leaves a gap, it has the tools' choice as the proposal.

What changed from 1b, beyond the encoding:

- `r0` is a general register ([9.7](#97-r0-is-a-general-register));
- `MOV` never sets the flags and `MOVS` does; stores are written `MOV`;
- a link register: calls write `r7` instead of pushing;
- mode E, `[r14 + 4R]`, and the special mode's tables D and E;
- one-parcel 7-bit constants for `MOV` and `CMP`;
- `CLR`, `INC` and `DEC` on any operand, and a one-cell `DBNZ`;
- constant forms of `BIC`, `TST` and multiply;
- the zero parcel is `ILLEGAL`, not `HALT`.

### 8. The parcel and what a cell costs

- **The opcode byte is a table, not fields.** 1b's `F D M R` spent the
  same 8 bits on a cross product of 16 operations and 16 modes. Draft 2
  gives out the 256 values one by one, so an operation gets only the modes
  it uses.
- **Decoding costs nothing for an irregular map.** The 1b CPU decodes
  through a ROM that looks up all 16 bits of the first parcel
  ([report 0012](0012-report-draft-1b-hardware.md#5-control)). What the hardware
  cares about is that register numbers sit in fixed places, and the
  register byte gives that. Constants come from a few places: the register
  byte (`Bcc`, `SWI`), its low nibble (`DBNZ`, the quick constants), or the
  low nibble and opcode bits (the 7-bit constants, shift counts). The
  immediate unit gathers them; it's wiring.
- **Quick constants should come from the instruction register.** 1b's
  microcode has a routine per value of `#q` and `#−q`, part of why it has
  1,082 routines in a control store 86% full.
- **The opcode byte first in memory:** a hex dump reads opcode, then
  registers, and a trap handler finds the opcode with one byte load.
- **What a cell costs:**

  | Shape | Operand bits | Cells |
  |---|---:|---|
  | no operands | 0 | 1, or better a cell of an extension grid: still one parcel |
  | `op rd, rs`; `op ea` with the mode from the register byte | 8 | 1 |
  | `op rd, #n` with a 5-bit count | 9 | 2 |
  | `op rd, #u7` | 11 | 8 |
  | `op rd, ea` with every mode; `Bcc` | 12 | 16, a row |
  | anything wider | | an extension parcel instead |

- **An extension parcel pays when it carries data.** On the 1b hardware
  `ADD r1, [r2]` is one parcel and 5 cycles; `MOV r9, [r2]` and
  `ADD r1, r9` are two parcels and 4 + 2 cycles. A two-parcel long form of
  `ADD r1, [r2]` would also be two parcels and about 6 cycles. So a parcel
  that carries only opcode bits costs about what a second instruction
  does, and draft 2 has no general two-parcel forms: a combination without
  a one-parcel form traps, and code uses two instructions.
- **Two-parcel instructions are for what can't be split:** atomics
  (`CAS`), long operand lists (`LDM`, `STM`) and escapes with a command
  word (the floating-point escape).
- **One-parcel forms go where they're used.** 1b code executes about 90 of
  its operation × mode pairs. The 32 most frequent cover 88% of the
  executed instructions that take a mode, 48 cover 96%, 64 cover 99%.
  Those instructions are 56% of all executed instructions.

### 9. The choices

#### 9.1 Moves and flags

- **`MOV` never sets the flags; `MOVS` sets N and Z.** Almost every move
  whose flags anything reads is a load followed by a branch. Constant
  loads' flags were never read in any trace, and register copies' 21
  times in 86,000
  ([RFC 0006, 3.4](0006-rfc-ideas-isa.md#34-which-movs-set-the-flags)).
  Loads followed directly by a branch on N or Z, as a share of executed
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

  Without `MOVS` each of these needs a `TST` after the load. A constant,
  a register copy or a pop can now sit between a compare and its branch,
  which 1b's `POP` couldn't.
- **`MOVS` on a byte takes N from bit 7** so that a byte load tests its
  sign as a byte does, and agrees with `INC` and `DEC` on a byte.
- **Stores written `MOV`:** with `MOV` never setting the flags, one
  mnemonic reads the same for loads, stores, copies and constants, and
  the assembler has no `ST`.
- **`CLR`** stores zero at any size, in place of 1b's `ST r0, ea`; with
  mode 0 it clears a register, as `MOV r5, #0` does. **`INC` and `DEC` on
  memory** are the memory increment RFC 0006 recommends: fib's call
  counter, a timer handler's load, add and store. `CLR` leaves the flags
  alone like a store; `INC` and `DEC` set N and Z like their register
  forms (Emily, 2026-10-15).
- **`NOP` is `MOV r0, r0`,** now that `MOV` doesn't set the flags, so it
  needs no cell; `.align` pads with it, where a zero parcel would trap.
- **Shorthands** such as `PUSH` and `RET` name common forms of a general
  instruction, unlike `MVI`, which was a second name for one (Emily).

#### 9.2 ALU operations and constants

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

  Each saves about a cycle over a load and an ALU operation. These rows
  are where to take cells back from: keeping `rs`, `#q`, `#−q` and the
  special mode for `AND`, `OR` and `XOR` frees up to 33.
- **`BIC`, `TST`, `MULU` and `MULS` with the special mode** take 16- and
  32-bit constants, which closes 1b's "no immediate `TST`/`BIC`/`MUL`" gap,
  and the special mode's memory operands with them (Emily). Dividing by a
  constant (`printf`'s `DIVU` by 10) takes a `MOV rX, #10` first.
- **The 7-bit constants.** Constants beyond the quick ones, as a share of
  executed instructions:

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
    instructions).
  - Compiled C compares with characters more than it loads them, so the
    `CMP` half-row earns its place as much as the `MOV` one.
  - They're written `MOV` and `CMP`: they behave exactly as the other
    constant forms do, so they're one more encoding for the assembler to
    pick (Emily).

#### 9.3 Branches and loops

- **`DBNZ r, back4`** leaves the flags alone, so a carry chain through
  `ADC` survives the loop counter.
  - Decrement-and-branch-back loops are 3.6% of hand-written executed
    instructions (about 1.9% without the interrupts program's delay loop)
    and none of compiled C's, because the compiler counts up. Over 99% of
    them branch at most 16 parcels back, and all at most 32.
  - It saves a parcel per iteration, and probably a cycle on top of the 4
    that `DEC` and `BNE` take now.
  - A loop buffer would make it worth much more
    ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)).
- **`Jcc`'s spare nibble** must be 0 for now, so it could later widen the
  offset ([12](#12-open-questions)).

#### 9.4 Shifts and unary operations

- **No three-operand shifts.** A register copy feeding a shift is 1.2% of
  hand-written and 1.5% of compiled executed instructions, mostly sha256
  (10.5%) and a few percent in matmul and crc. One-parcel three-operand
  shifts would take 32 cells per kind, 128 for all four.
- **The unary group's separate source pays in compiled code.** `rd` ≠
  `rs` is 3.0% of compiled executed instructions (`INC` 1.33%, `DEC`
  0.66%, `NOT` 0.64%): the compiler's `x + 1` into another register. In
  hand-written code it is 0.46%. Working in place, the whole group would
  fit one cell, with the function in the register byte.
- **`RLC`, `RRC` and `SWAP` never ran** in any program. They could share an
  in-place cell if the row gets tight.

#### 9.5 Calls, multiple registers and rows 0 and F

- **The link register** (Emily, 2026-10-15). Measured on 1b with the
  convention ported
  ([link-register.md](0028-rfc-draft-2-isa/link-register.md)): −2.3% of
  the hand-written suite's cycles, −0.2% of compiled C's, −0.9% of
  Egret's JIT, and at worst +0.24%. A leaf call and return takes 5 cycles instead
  of 10. The microcode is 74 microinstructions shorter, and a call no
  longer writes memory, so `CALL [r]+` no longer needs care to be
  restartable. `r7` is the last caller-saved register, next to the
  callee-saved `r8`–`r14`, so a function that calls saves it in its
  `SAVE r7-rN`.
- **`SAVE` and `RESTORE` take ranges.** All 29 compiled functions that
  save registers save `r8`–`rN`, and none saves a register it doesn't
  use, so register masks would buy compiled code nothing. 1b unrolls one
  microcode routine per range, 1,476 of its 3,507 microinstructions; a
  loop with a counting register number would free them
  ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)).
- **`LDM` with its base in the range.** The tools read every word before
  writing any register, which is easy in a simulator and would need a
  buffer of up to 15 words in hardware. Loading the base register's word
  last, held in one temporary, restarts as cleanly
  ([12](#12-open-questions)).
- **`LEA`** keeps `[R + d16]`, `[sp + 4R]`, indexed and the special
  mode, and has mode E (Emily, 2026-10-16).
  - Its cells sit in its modes' columns, as in rows 1–A, so throughout
    rows 0–A a cell with a mode has that mode as the opcode's low nibble.
    `MFSR` and `MTSR` moved to `06` and `07` to make room. The decode ROM
    sees the whole parcel, so this costs the hardware nothing; it makes
    hex dumps, the assembler and the disassembler regular.
  - Mode E gives the address of a field in the first 16 words of the
    current object in one parcel, `LEA r1, [r14 + 8]`, as mode 4 does for
    a stack frame's. Its use isn't measured. It costs one of the free
    cells: 9 before, 8 now.
  - `LEA rd, [R]` went: it was the compiler's copy that leaves the flags
    alone, which is now `MOV`.
  - Measured: 1.9% of hand-written and 3.1% of compiled executed
    instructions. The indexed form is mostly a three-operand add,
    `rA + rB` or `rA + 2·rB`.
  - Of the special mode, the `PC`-relative address is the only way to get
    a position-independent one; `LEA rd, [abs16]` is now `MOV rd, #label`.
- **`SWI #n`** gets its own microcode entry for each n, since the decode
  ROM sees the whole parcel: RFC 0010's vectored `SWI`.
- **`MFUR` and `MTUR`** are one parcel each in `MOVS`'s two unused cells:
  with a full register bank per thread, they carry every system call's
  arguments and results ([RFC 0029](0029-rfc-draft-2-system.md)).
- **The extension grids** hold instructions without operands, which are
  still one parcel there. With `RET` now `JMP r7` and `NOP` a `MOV`, `FD`
  holds only the tentative `MULFX`, and may go.
- **`00` and `FF` are `ILLEGAL`,** so a jump into zeroed or erased memory
  traps. Draft 1 made the zero parcel `HALT`; a trap gives the kernel the
  `PC`.

#### 9.6 The addressing modes

- **Mode E, `[r14 + 4R]`** (Emily, 2026-10-15): the first 16 words of the
  current object in one parcel, as `[sp + 4R]` gives a stack frame's.
  - `r14` holds the current object by convention: the kernel's thread
    control block, Egret's frame record, the VM's state.
  - Measured on 1b with the mode added
    ([fixed-base-mode.md](0028-rfc-draft-2-isa/fixed-base-mode.md)): 3–5% of the nucleus's message and
    switch paths, and its code 4% smaller; about 1% of Egret's cycles;
    nothing for the Lisp, whose tagged pointers put fields at 4k ± 1.
    Loads and stores are 75–100% of the uses, so the measurements
    suggested three cells; the whole column keeps the mode table
    orthogonal.
- **The special mode's tables, D and E** (Emily, 2026-10-15):
  - **A table without a base register.** Indexed accesses whose base was
    loaded with `MOV r, #label` are 1.47% of hand-written executed
    instructions (vm 16%, mandel 10%) and 0.19% of compiled ones. Each
    holds a register through its loop, or, where the load isn't hoisted,
    costs a `MOV`.
  - **`[label + R]` beyond ±32 KB.** 1b's only form is the displacement
    modes with a label; D with ×1 reaches 8 MB.
  - **Position-independent jump tables,** for `switch` in relocatable
    code: `JMP [pc + table + r2*4]`.
  - **Without `r0` as zero,** `[r0 + x·s + d8]` is no longer a base-less
    index either.
  - They cost microcode for two operands and no cells.
- **The mode from the register byte:** 1b's op B did this for `JMP ea`
  and `CALL ea`, and the 68000's whole single-operand group works this
  way.

#### 9.7 `r0` is a general register

**decided** (Emily, 2026-10-15). In draft 1 `r0` reads as zero.

- **What replaces it:** `CLR` stores zero, in memory or in a register.
- **What still needs a zero** ([RFC 0006, 3.3](0006-rfc-ideas-isa.md#33-r0-as-a-general-register)):
  `ADC r5, r0` in bignum, `SBC r6, r0` in sort, and the kernel's
  `MTUR r1, r0` and `MTSR mapd, r0`. These take a
  `CLR rX` first, or new forms ([12](#12-open-questions)). The Lisp's
  `CMP.T r1, r0` becomes `TTST r1, r1`.
- **In the hardware:** `NEG` and the multiply and divide routines read
  `r0` as zero. A hidden register-file entry that the reset routine zeroes
  replaces it. The gates that keep `r0` from being written go.
- **Measured** (RFC 0006): without a zero register, compiled C takes 1.3%
  more cycles, mostly where the compiler puts a constant inside a loop; a
  15th register is worth up to 0.5–0.7%, and 6–11% in sha256.

#### 9.8 Tentative instructions

Tentative instructions are in the simulator, and software should use them
where they fit, so that their use can be measured (Emily, 2026-10-15).

- **What they're for:** `ADD.B4`, pixel arithmetic and finding a zero byte
  a word at a time; `FFS` and `POPC`, allocator and scheduler bitmaps;
  `REV`, big-endian data (SHA-256's message words, network headers, font
  files); `MULA`, multiply-accumulate (mandel, audio, filters); `MERGE`,
  masked edges and glyph words in graphics, −20% of the glyph loop
  ([report 0019](0019-report-graphics.md#a-merge-under-a-mask)); `MULFX`,
  fixed-point multiply (mandel's inner loop).
- **The tagged operations** are the Lisp's v1bx
  ([report 0018's appendix](0018-report-lisp.md#appendix-v1bx-draft-1b-with-a-tagged-register-mode)) on registers: −6.4% of
  the Lisp's compiled cycles, −5.5% of Egret's
  ([RFC 0006, 6](0006-rfc-ideas-isa.md#6-for-dynamic-languages)).
  - `TMOV` leaves the flags alone, like `MOV`, where v1bx's `MOV.T` set
    N and Z.
  - `TTST r1, r1` checks `r1` and sets Z if it's zero and N if it's
    negative: the Lisp's `zero?` and its check of one operand, which v1bx
    wrote as `CMP.T r1, r0` and `MOV.T r9, r1`.
  - The Lisp tags integers with bit 0 clear and Egret as 2n + 1; the
    tools take the Lisp's until it's settled.

#### 9.9 `HI` and `LO` are `r0` and `r1`

**decided** (Emily, 2026-10-16). Draft 1's `HI`, a hidden entry of 1b's
register file reached through `MFSR` and `MTSR`, and the `LO` that `MULA`
added were special registers 1 and 2.

- **The operating system** gets a thread whose state is `r0`–`r15`, the
  PC and the status word. `MFUR` and `MTUR` reach all of a bank, and an
  exception frame or a switch has no special registers to save. A kernel
  that shares register banks among threads needed a way to reach
  another bank's `HI` and `LO`
  ([RFC 0029's register-banks.md](0029-rfc-draft-2-system/register-banks.md#3-what-fewer-banks-would-change-in-software));
  now it needs none.
- **The hardware** loses `HI` and `LO`'s special-register path, and a
  bank is sixteen registers.
- **What it costs:** a multiply or divide writes `r0` whether or not the
  program wanted the high half or the remainder, so assembly keeps
  nothing in `r0` across one (nor in `r1` across `MULA`), and the
  compiler's register allocator treats `r0` as clobbered by them. In
  cycles, estimates put the cost close to nothing either way (Emily,
  2026-10-16). x86's `MUL` and `DIV` use `EDX` the same way.
- **A fixed register is a magic register,** which Emily dislikes, but a
  separate `HI` is worse (Emily).
- **Gone with them:** the shorthands `MFHI`, `MTHI`, `MFLO` and `MTLO`,
  and the open question of whether `MULU` and `MULS` leave `LO` alone.
  What happens when a multiply or divide writes `r0` twice, as its `rd`
  or its address register as well, is a new one. The proposal keeps the
  later write, so `rd` wins and a register allocator may still pick
  `r0` for it ([5.3](#53-multiply-and-divide)).

### 10. 1b's gaps left open

Three of 1b's addressing gaps
([RFC 0006, 3.2](0006-rfc-ideas-isa.md#32-1bs-gaps)), and what they cost
in 1b code. Short offsets got mode E, `[r14 + 4R]`; the other two have no
cells. Measured as in [section 11](#11-how-it-was-measured).

#### 10.1 Short offsets

There is no one-parcel `[R + small offset]` but through `r14`. `[R + d16]`
accesses (word, byte or half, `sp` aside), by displacement, as a share of
executed instructions:

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
    all, in aligned blocks of 4.
  - **A second fixed-base slot,** shaped like `[sp + 4R]`, with a register
    set aside by convention for the current object.
- **Decided:** the second fixed-base slot, as mode E with `r14`, after
  [the fixed-base measurements](0028-rfc-draft-2-isa/fixed-base-mode.md) on the kernel, Egret and the Lisp
  (Emily, 2026-10-15; [9.6](#96-the-addressing-modes)). Short offsets
  through any register are not proposed.

#### 10.2 More auto-increment and auto-decrement modes

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

#### 10.3 Sign-extending loads

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

### 11. How it was measured

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

### 12. Open questions

Part I marks each of these **open**; the proposal is what it states.

1. **`CAS`** (`F7`). One cell holds two registers, so one operand is
   implicit. For example `CAS rs, [R]` with the expected value in `r1`, as
   x86's `CMPXCHG` has it: Z on success, the current value into `r1` on
   failure. Its locked read is checked as a store
   ([RFC 0029, 6](0029-rfc-draft-2-system.md#6-exceptions)); LOCK is
   released on a fault; a locked read-modify-write of the CPU's own RAM
   holds off its slave port
   ([RFC 0014](0014-rfc-system-bus.md#73-locked-sequences)). `XCHG` as
   well? `TAS` isn't needed beside the bus's semaphores.
2. **The floating-point escape** (`F8`). A command word plus a mode with
   32-bit data makes four parcels, one over the limit. Either its mode
   table leaves out the 32-bit forms, or escapes may be four parcels.
3. **`LEA` with the special mode,** or a dedicated `LEA rd, [pc + d]`.
4. **What `r0`'s change needs:** `ADC` and `SBC` with a constant, or a
   `CLR rX` first ([9.7](#97-r0-is-a-general-register)).
5. **The tag that marks an integer:** the Lisp's bit 0 clear, as now, or
   Egret's 2n + 1. A register holding the expected tag bit could serve
   both.
6. **`LDM` and `STM`:** what the extension parcel's 12 spare bits do
   (direction, writeback), and an `LDM` whose range includes its base:
   load the base's word last, as proposed in
   [9.5](#95-calls-multiple-registers-and-rows-0-and-f), or trap.
7. **The opcode byte first in memory,** as in the map, or second.
8. **`MOVS rs`,** in the map. Register copies' flags were read 21 times in
   86,000. And whether `MOVS` takes the special mode's constants.
9. **`Jcc`:** cc = E and F as `JMP` and `CALL`, and its spare nibble, 0
   for now: a 20-bit relative offset later?
10. **Sign-extending loads.** Proposed: none ([10.3](#103-sign-extending-loads)).
11. **How the assembler picks an encoding** ([6](#6-assembler-syntax)):
    - the quick constant for 0…15, to keep the output reproducible;
    - the order of the `[R + d]` forms, and D with `R` as its index for
      the 17–24-bit displacements;
    - a qualifier that forces a long form, for patching code in place or
      instructions of a fixed length (`MOV.L r1, #5`, say, like ARM's
      `.W`), only if something needs it.
12. **The details the tools chose:** the shift count's split, `SETcc`
    with cc = F, `SAVE` and `RESTORE` within `r0`–`r14`, `DBNZ`'s offset,
    `INC` and `DEC` on a byte taking N from bit 7, `JMP` and `CALL`
    refusing byte and half memory operands, a load into its own
    auto-incremented register, and which result stays where a multiply
    or divide writes `r0` twice ([5.3](#53-multiply-and-divide)).
13. **Syntax:** `LI`, `MFF` and `MTF` refused; one spelling per
    instruction; case.
14. **The calling convention** beyond `r7` and `sp`.
15. **`FD`:** kept as room for rare instructions, or freed, with `MULFX`
    moving elsewhere.
16. **Room to grow:** 8 free cells, and `AND`, `OR` and `XOR`'s memory
    columns ([9.2](#92-alu-operations-and-constants)).

### 13. Next steps

- **The draft 2 study:** the simulator, the assembler and the C compiler
  exist (`studies/v2_isa`, in review). Then the Lisp, Egret, the graphics
  library and the kernel, using the tentative instructions where they
  fit, and draft 2 measured against 1b.
- **An estimate of draft 2's microcode,** with `SAVE` and `RESTORE` as
  loops and the quick constants from the instruction register.
- **A loop buffer in the cycle model**
  ([studies/v1b_tradeoffs](../studies/v1b_tradeoffs/README.md)).
- **Once this is accepted,** Part I moves to `docs/` unchanged.
