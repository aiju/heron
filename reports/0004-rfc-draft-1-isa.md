---
number: 4
type: rfc
title: Draft 1's instruction set, 1a and 1b
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v0_hw]
  commit: e494b0c
---

# RFC 0004: Draft 1's instruction set, 1a and 1b

Draft 1 is a 32-bit machine with 16-bit instruction parcels, in two
candidate encodings that share everything except how operands are
encoded:

- **[Part I: draft 1a](#part-i-draft-1a)**, RISC-like: load/store,
  register–register ALU, short and long load/store forms. It follows on
  directly from draft 0 ([RFC 0001](0001-rfc-draft-0.md)).
- **[Part II: draft 1b](#part-ii-draft-1b)**, CISC-like: every ALU
  instruction takes one register and one *addressing mode*, which can be a
  register, an immediate or a memory operand (like the IBM 360's RX
  format, the 68000 and x86).

Each part is a complete specification on its own.
[Part III](#part-iii-1a-against-1b) measures the two against each other.
Draft 2 builds on 1b
([RFC 0006](0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2),
[RFC 0028](0028-rfc-draft-2-isa.md)).

## Part I: Draft 1a

### 1. Overview

Draft 1a is draft 0 widened to 32 bits, with the changes from the draft 0
evaluation: multiply and divide, a shift group, `SAVE`/`RESTORE`,
`INC`/`DEC`/`ADDI` that leave C and V alone, halfword and sign-extending
loads, and wider immediates. ALU instructions work on registers; memory is
reached only through loads and stores.

Instructions are made of 16-bit *parcels*: a first parcel, which is the
opcode, and 0–2 extension parcels holding immediates, displacements or
addresses. A 32-bit value in an instruction takes two parcels, low half
first. Instructions only need to be 2-byte aligned.

### 2. Machine state

| Item | Description |
|---|---|
| `r0` | Always reads as 0. Writes are discarded. |
| `r1`–`r14` | General purpose, 32 bits. |
| `r15` / `sp` | Stack pointer. Used implicitly by calls, returns, `SAVE`/`RESTORE`, interrupts and traps. |
| `PC` | Program counter, 32 bits, always even. |
| `HI` | High half of a multiply, remainder of a divide. Read with `MFHI`, written with `MTHI`. |
| Flags | `N` negative, `Z` zero, `C` carry, `V` overflow, `I` interrupt enable. |

### 3. Memory

- Byte addressed, little-endian, 32-bit addresses.
- RAM is 1 MB at `0x00000000`–`0x000FFFFF` in the simulator. The 256-byte
  I/O page is at `0xFFFFFF00`–`0xFFFFFFFF`, at the very top of the address
  space, so a sign-extended 16-bit absolute address (`0xFF00` → `0xFFFFFF00`)
  reaches it.
- Sizes: byte (8), half (16), word (32). A half must be at an even address
  and a word at a multiple of 4. A misaligned access is an *address error*
  trap. Touching an address that is neither RAM nor I/O stops the simulator
  with an error.
- Byte and half loads zero-extend; `LDSB` and `LDSH` sign-extend.

### 4. Flags

| Instructions | Flags |
|---|---|
| `ADD`, `ADC`, `SUB`, `SBC`, `CMP`, `NEG` | NZCV |
| `AND`, `OR`, `XOR`, `BIC`, `TST`, `NOT` | NZ (C and V unchanged) |
| Loads, `MOV`, `MVI`, `SWAP`, extends, `CLZ` | NZ (C and V unchanged) |
| `INC`, `DEC`, `ADDI` | **NZ only**: adding a constant never changes C or V |
| Shifts and rotates | NZ, C = last bit shifted out (unchanged for a count of 0), V = 0 |
| `MULU`, `MULS` | NZ from the low 32 bits; C = V = 1 if the full product doesn't fit in 32 bits (unsigned / signed) |
| `DIVU`, `DIVS`, `DIVUL` | NZ from the quotient; C = 0; V = 1 on overflow ([6](#6-alu-functions)) |
| Stores, `LEA`, branches, jumps, calls, `SAVE`, `RESTORE`, `SETcc`, `MFHI`/`MTHI`, `MFF` | unchanged |

`C` is a carry for additions and "no borrow" for subtractions, so after
`CMP a, b`, `HS` means `a ≥ b` unsigned.

`ADC` and `SBC` have a **sticky Z**: they can clear Z but never set it. So a
64-bit compare or subtract (`CMP lo` then `SBC hi`) leaves Z set only if the
whole 64-bit result is zero, and one conditional branch is enough.

#### 4.1 Conditions

Bits 3–1 pick a test and bit 0 inverts it, as in draft 0 and ARM.

| cc | Name | Test | cc | Name | Test |
|---|---|---|---|---|---|
| 0 | `EQ` | Z | 1 | `NE` | !Z |
| 2 | `CS`/`HS` | C | 3 | `CC`/`LO` | !C |
| 4 | `MI` | N | 5 | `PL` | !N |
| 6 | `VS` | V | 7 | `VC` | !V |
| 8 | `HI` | C & !Z | 9 | `LS` | !C \| Z |
| A | `GE` | N = V | B | `LT` | N ≠ V |
| C | `GT` | !Z & N = V | D | `LE` | Z \| N ≠ V |
| E | `RA` (always) | 1 | F | link | `BSR` / `CALL` |

### 5. Encoding

Every first parcel is four hex digits `op a b c`, and fields never move:
`a` is the destination register (or a condition), `b` the source or base
register, `c` a function or a small offset.

| op | Parcels | Layout | Instructions |
|---|---|---|---|
| 0 | 1 | `0 a b f` | System group ([10](#10-system-group)) |
| 1 | 1 | `1 d s f` | `rd ← rd ⊕ rs`: the 16 ALU functions ([6](#6-alu-functions)) |
| 2 | 1 | `2 d s f` | `rd ← f(rs)`: unary group ([8](#8-unary-functions)) |
| 3 | 1 | `3 c ii` | `Bcc` (c = F: `BSR`): `PC ← PC + 2·simm8` |
| 4 | 1 | `4 d s o` | `LD rd, [rs + 4o]` (word, offset 0–60) |
| 5 | 1 | `5 d s o` | `ST rd, [rs + 4o]` |
| 6 | 1 | `6 d s o` | `LDB rd, [rs + o]` (byte, zero-extended, offset 0–15) |
| 7 | 1 | `7 d s o` | `STB rd, [rs + o]` |
| 8 | 2–3 | `8 d k f` + imm | `rd ← rd ⊕ #imm`: the 16 ALU functions with an immediate ([6.1](#61-immediates)) |
| 9 | 2–3 | `9 c k 0` + target | `Jcc` (c = E: `JMP`, c = F: `CALL`): k = 0: `PC ← PC + 2·simm16`; k = 1: absolute 32-bit address |
| A | 2–3 | `A d s f` + disp | Long memory forms ([7](#7-long-memory-forms)) |
| B | 1 | `B d s f` | Shift group ([9](#9-shifts)) |
| C | 1 | `C d ii` | `MVI rd, simm8` |
| D | 1 | `D d ii` | `ADDI rd, simm8` (sets N and Z only) |
| E | 1 | `E d ii` | `CMPI rd, simm8` |
| F | – | – | Reserved (traps), so `FFFF` traps |

`PC` in relative branches and addresses is the address of the next
instruction.

### 6. ALU functions

The 16 two-operand functions, `rd ← rd ⊕ src`, on two registers (op 1) or
on a register and an immediate (op 8). `src` is the second operand.

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `ADD` | `ADC` | `SUB` | `SBC` | `AND` | `OR` | `XOR` | `BIC` | `MOV` | `CMP` | `TST` | `MULU` | `MULS` | `DIVU` | `DIVS` | `DIVUL` |

| Name | Operation |
|---|---|
| `ADD` | `rd ← rd + src` |
| `ADC` | `rd ← rd + src + C` (sticky Z) |
| `SUB` | `rd ← rd − src` |
| `SBC` | `rd ← rd − src − !C` (sticky Z) |
| `AND` | `rd ← rd & src` |
| `OR` | `rd ← rd \| src` |
| `XOR` | `rd ← rd ^ src` |
| `BIC` | `rd ← rd & ~src` |
| `MOV` | `rd ← src` |
| `CMP` | flags of `rd − src` |
| `TST` | flags of `rd & src` |
| `MULU` | `HI:rd ← rd × src`, unsigned 64-bit product |
| `MULS` | `HI:rd ← rd × src`, signed 64-bit product |
| `DIVU` | `rd ← rd ÷ src`, `HI ← remainder`, unsigned |
| `DIVS` | `rd ← rd ÷ src` rounded toward zero, `HI ← remainder` (sign of the dividend) |
| `DIVUL` | `rd ← HI:rd ÷ src`, `HI ← remainder`, unsigned 64/32 divide |

- Dividing by zero is a *divide error* trap (registers unchanged).
- Multiply time depends on the implementation, but small operands are
  faster, so put the smaller factor second (`src`). The timing model charges
  by the significant bits of `src`; the draft 1b hardware takes 16 or 32
  steps ([report 0012](0012-report-draft-1b-hardware.md)).
- `DIVS` of `−2^31 ÷ −1` gives `−2^31`, remainder 0, and sets V.
- `DIVUL` with `HI ≥ src` would overflow: it sets V and leaves `rd`, `HI`
  and the other flags unchanged. Chained `DIVUL`s (remainder left in `HI` for the next word)
  divide a bignum by a word, one instruction per word.

#### 6.1 Immediates

In op 8, the `k` digit says what follows:

| k | Extension | Value |
|---|---|---|
| 0 | 1 parcel | signed 16-bit, sign-extended |
| 1 | 1 parcel | unsigned 16-bit, zero-extended |
| 2 | 1 parcel | 16 bits shifted left by 16 (`0xNNNN0000`) |
| 3 | 2 parcels | full 32 bits |

### 7. Long memory forms

Op A: `A d s f` followed by a displacement. The address is `rs + disp`, and
with `rs = r0` that's an absolute address.

| f | Instruction | Displacement |
|---|---|---|
| 0 | `LD rd, [rs + disp]` | signed 16 |
| 1 | `ST rd, [rs + disp]` | signed 16 |
| 2 | `LDB rd, [rs + disp]` (zero-extends) | signed 16 |
| 3 | `STB rd, [rs + disp]` | signed 16 |
| 4 | `LDH rd, [rs + disp]` (zero-extends) | signed 16 |
| 5 | `STH rd, [rs + disp]` | signed 16 |
| 6 | `LDSB rd, [rs + disp]` (sign-extends) | signed 16 |
| 7 | `LDSH rd, [rs + disp]` (sign-extends) | signed 16 |
| 8 | `LEA rd, [rs + disp]` (`rd ← rs + disp`, no flags) | signed 16 |
| 9 | `LEA rd, label`: `rd ← PC + disp` (PC-relative, `s` = 0) | signed 16 |
| A–E | `LD`, `ST`, `LDB`, `STB`, `LEA` with a 32-bit displacement | 32 |
| F | reserved | |

### 8. Unary functions

Op 2, `2 d s f`: `rd ← f(rs)`. The source is a separate register; `NOT r1`
is short for `NOT r1, r1`.

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C–F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `NOT` | `NEG` | `INC` | `DEC` | `RLC` | `RRC` | `SWAP` | `SXB` | `ZXB` | `SXH` | `ZXH` | `CLZ` | traps |

| Name | Operation | Flags |
|---|---|---|
| `NOT` | `~rs` | NZ |
| `NEG` | `0 − rs` | NZCV |
| `INC` | `rs + 1` | NZ |
| `DEC` | `rs − 1` | NZ |
| `RLC` | rotate left through carry: `(rs << 1) \| C`, `C ← bit 31` | NZC, V ← 0 |
| `RRC` | rotate right through carry: `(rs >> 1) \| (C << 31)`, `C ← bit 0` | NZC, V ← 0 |
| `SWAP` | swap the 16-bit halves | NZ |
| `SXB`, `ZXB` | sign-/zero-extend the low byte | NZ |
| `SXH`, `ZXH` | sign-/zero-extend the low half | NZ |
| `CLZ` | number of leading zero bits, 0–32 | NZ |

### 9. Shifts

Op B, `B d s f`, in place on `rd`. Bits 1–0 of `f` pick the operation and
bits 3–2 the count.

| f bits 1–0 | Name | Operation |
|---|---|---|
| 0 | `LSL rd, #n` / `LSL rd, rs` | logical shift left |
| 1 | `LSR rd, #n` / `LSR rd, rs` | logical shift right |
| 2 | `ASR rd, #n` / `ASR rd, rs` | arithmetic shift right |
| 3 | `ROR rd, #n` / `ROR rd, rs` | rotate right (C = the last bit rotated round, i.e. the new bit 31) |

| f bits 3–2 | Count |
|---|---|
| 0 | `#s` (0–15) |
| 1 | `#s + 16` (16–31) |
| 2 | register `rs` (low 5 bits) |
| 3 | reserved (traps) |

`n` is 0–31. With a register, the count is `rs & 31`. Rotate left by `n` is
`ROR` by `32 − n`.

### 10. System group

Op 0, `0 a b f`:

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C | D | E–F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `HALT` | `NOP` | `JMP rs` | `CALL rs` | `RET` | `SAVE` | `RESTORE` | `RTI` | `EI` | `DI` | `MFSR` | `MTSR` | `SWI` | `SETcc` | traps |

| Name | Operation |
|---|---|
| `HALT` | Stop. With interrupts enabled, wait for an interrupt instead. The all-zero parcel is `HALT`. |
| `NOP` | |
| `JMP rs` | `PC ← rs` |
| `CALL rs` | push the return address; `PC ← rs` |
| `RET` | pop `PC` |
| `SAVE ra-rb` | push `ra`…`rb` (1 ≤ a ≤ b ≤ 14): `sp ← sp − 4n`, then `ra` at `[sp]`, `ra+1` at `[sp+4]`, … |
| `RESTORE ra-rb` | the reverse: load `ra`…`rb` from `[sp]`…, then `sp ← sp + 4n`. Flags unchanged. |
| `RTI` | pop flags, pop `PC` |
| `EI` / `DI` | `I ← 1` / `I ← 0` |
| `MFSR rd, n` / `MTSR n, rs` | read/write special register `n`: 0 = flags word, 1 = `HI`. Aliases: `MFF rd`, `MTF rs`, `MFHI rd`, `MTHI rs`. |
| `SWI #n` | software interrupt with an 8-bit number (the handler finds it in the instruction at `[saved PC − 2]`) |
| `SETcc rd` | `rd ← 1` if the condition holds, else 0. Flags unchanged. |

Field use: `JMP`/`CALL rs` put `rs` in `b`; `SAVE`/`RESTORE ra-rb` put `a`
and `b` in `a` and `b`; `MFSR rd, n` is `0 d n A`; `MTSR n, rs` is
`0 n s B`; `SWI #n` puts the 8-bit number in `a b`; `SETcc rd` is
`0 d cc D`.

`PUSH r` and `POP r` are assembler aliases for `SAVE r-r` and
`RESTORE r-r`.

### 11. Calls, the stack and interrupts

- The stack grows down and `sp` points at the last word pushed. Every push
  and pop is a 32-bit word.
- `CALL`/`BSR` push the address of the next instruction. `RET` pops it.
- Vectors are 4 bytes apart, each room for one `JMP handler` (2 parcels):

  | Address | Vector |
  |---|---|
  | `0x00` | reset (also `I ← 0`) |
  | `0x04` | IRQ (level-triggered, when `I = 1`) |
  | `0x08` | illegal instruction |
  | `0x0C` | `SWI` |
  | `0x10` | divide error |
  | `0x14` | address error (misaligned access) |

- Entering an interrupt or trap pushes `PC`, then the flags word (`I N Z C V`
  in bits 4–0), clears `I` and jumps to the vector. `RTI` undoes it. For IRQs
  and `SWI` the saved `PC` is the next instruction; for the faults it's the
  faulting instruction.
- Interrupt timing is as in draft 0: interrupts are taken between
  instructions, never straight after `EI`, still possibly straight after `DI`,
  and right after `RTI` if the restored flags enable them. `HALT` with `I = 1`
  waits for an interrupt and continues after the `HALT` when the handler
  returns.

### 12. I/O page

All registers are 32 bits wide, 4 bytes apart. Byte accesses work on the low
byte.

| Address | Read | Write |
|---|---|---|
| `0xFFFFFF00` | console input byte, or `−1` (`0xFFFFFFFF`) if none is waiting | console output (low byte) |
| `0xFFFFFF04` | bit 0: a byte is waiting; bit 1: end of input | – |
| `0xFFFFFF08` | timer period | timer period in clock cycles (0 = off) |
| `0xFFFFFF0C` | timer flag (drives IRQ) | acknowledge the timer |
| `0xFFFFFF10` | cycle counter | – |

The timer:
- The first tick comes one period after the period is written.
- Writing period 0 stops the timer and clears a pending flag.
- In the simulator, the timer counts the cycles of the reference
  configuration (D16-overlap, see
  [the timing model](../studies/v1_isa/timing-model-v1.md)).
- `HALT` with `I = 1` but no timer running stops the machine, as with
  `I = 0`, because nothing could ever wake it.

The simulator supplies all input up front, so once it's used up the
end-of-input bit is set and reads return `−1`. Read the console with a word
load: a byte load returns `0xFF` at the end of input, which can't be told
apart from a real `0xFF` byte.

### 13. Software conventions

These are conventions for the programs, not hardware rules.

- Arguments in `r1`–`r4`, results in `r1` (and `r2` for a second value).
- `r1`–`r7` are scratch (caller-saved); `r8`–`r14` must be preserved by the
  callee; `sp` is `r15`.
- Programs start with `.include "lib/start.s"`, which sets up the vectors,
  sets `sp` to `0x00100000` (top of RAM) and calls `main`. When `main`
  returns, the machine halts.

### 14. Assembler syntax

```
label:  ADD   r1, r2
.loop:                          ; local label, scoped to the last global label
        .byte 1, 'a', "text"    ; 8-bit values
        .half 0x1234            ; 16-bit values (2-byte aligned)
        .word 0x12345678, label ; 32-bit values (4-byte aligned); .long is the same
        .asciz "hello\n"
        .space 32               ; zero-filled bytes
        .align 4
        .org  0x0100
size = end - start              ; constants (also .equ)
        .include "lib/print.s"
```

Mnemonics and registers are case-insensitive; `sp` is `r15`. Expressions
support `+ - * / % & | ^ << >> ~`, parentheses, `'c'` characters, `$` (the
current address), `lo()`/`hi()` (bytes) and `lo16()`/`hi16()` (halves).
Branches relax automatically: an out-of-range `Bcc` becomes a 2-parcel `Jcc`,
`BSR` becomes `CALL`. `LI rd, x` is an alias for `MOV rd, #x`.

Memory operands are written in square brackets: `[r2]`, `[r2 + 8]`,
`[r2 - 4]`, `[label]` (absolute), `[label + r2]` (a 16-bit address plus a
register).

```
        ADD   r1, r2            ; register-register
        ADD   r1, #1000         ; op 8: picks the shortest immediate kind
        ADDI  r1, -1            ; 1 parcel, leaves C and V alone (ADD #1 sets them)
        MOV   r1, #5            ; picks MVI if it fits in 8 bits, else op 8
        LI    r1, #0x12345678   ; same as MOV
        CMP   r1, #'0'          ; picks CMPI if it fits
        LD    r1, [r2 + 8]      ; picks the short form if the offset fits
        LDB   r3, [buffer]      ; absolute (r0 + disp16, or disp32 if needed)
        LDB   r3, [table + r2]  ; static array indexed by a register (long form)
        LDSH  r3, [r4 + 2]      ; long form only
        LEA   r1, msg           ; PC-relative address of msg
        LEA   r1, [r2 + 12]     ; rd ← r2 + 12, flags unchanged
        LSL   r1, #4
        ASR   r1, r2            ; count in r2
        BNE   .loop             ; becomes JNE (2 parcels) if out of range
        BSR   helper            ; becomes CALL if out of range
        JMP   r3                ; or JMP label
        SAVE  r8-r11            ; PUSH r8 = SAVE r8-r8
        MULU  r1, r2            ; HI:r1 ← r1 × r2
        MFHI  r2
        SETLT r4
```

`MVI`, `ADDI` and `CMPI` can also be written directly. Note that the
assembler never turns `ADD #n` into `ADDI`, because their flags differ.

## Part II: Draft 1b

### 15. Overview

In draft 1b, every main instruction has one register operand and one
*effective address* (EA): a register, an immediate, or a memory operand
reached through one of a dozen addressing modes. So `ADD r1, [r2 + 8]` adds a
word from memory in one instruction, and there are no separate load
instructions: a load is `MOV rd, ea` and a store is `ST rd, ea`. At most one
operand is ever in memory.

Instructions are made of 16-bit *parcels*: a first parcel, which is the
opcode, and 0–2 extension parcels holding immediates, displacements or
addresses. A 32-bit value in an instruction takes two parcels, low half
first. Instructions only need to be 2-byte aligned.

### 16. Machine state

| Item | Description |
|---|---|
| `r0` | Always reads as 0. Writes are discarded. |
| `r1`–`r14` | General purpose, 32 bits. |
| `r15` / `sp` | Stack pointer. Used implicitly by calls, returns, `SAVE`/`RESTORE`, interrupts and traps. |
| `PC` | Program counter, 32 bits, always even. |
| `HI` | High half of a multiply, remainder of a divide. Read with `MFHI`, written with `MTHI`. |
| Flags | `N` negative, `Z` zero, `C` carry, `V` overflow, `I` interrupt enable. |

### 17. Memory

- Byte addressed, little-endian, 32-bit addresses.
- RAM is 1 MB at `0x00000000`–`0x000FFFFF` in the simulator. The 256-byte
  I/O page is at `0xFFFFFF00`–`0xFFFFFFFF`, at the very top of the address
  space, so a sign-extended 16-bit absolute address (`0xFF00` → `0xFFFFFF00`)
  reaches it.
- Sizes: byte (8), half (16), word (32). A half must be at an even address
  and a word at a multiple of 4. A misaligned access is an *address error*
  trap. Touching an address that is neither RAM nor I/O stops the simulator
  with an error.
- Byte and half memory operands are zero-extended when read.

### 18. Flags

| Instructions | Flags |
|---|---|
| `ADD`, `ADC`, `SUB`, `SBC`, `CMP`, `NEG` | NZCV |
| `AND`, `OR`, `XOR`, `BIC`, `TST`, `NOT` | NZ (C and V unchanged) |
| `MOV` (and so every load), `POP`, `SWAP`, extends, `CLZ` | NZ (C and V unchanged) |
| `INC`, `DEC` | **NZ only**: unlike `ADD #1`, they never change C or V |
| Shifts and rotates | NZ, C = last bit shifted out (unchanged for a count of 0), V = 0 |
| `MULU`, `MULS` | NZ from the low 32 bits; C = V = 1 if the full product doesn't fit in 32 bits (unsigned / signed) |
| `DIVU`, `DIVS`, `DIVUL` | NZ from the quotient; C = 0; V = 1 on overflow ([21](#21-alu-functions)) |
| `ST`, `LEA`, branches, jumps, calls, `SAVE`, `RESTORE`, `SETcc`, `MFHI`/`MTHI`, `MFF` | unchanged |

`C` is a carry for additions and "no borrow" for subtractions, so after
`CMP a, b`, `HS` means `a ≥ b` unsigned.

`ADC` and `SBC` have a **sticky Z**: they can clear Z but never set it. So a
64-bit compare or subtract (`CMP lo` then `SBC hi`) leaves Z set only if the
whole 64-bit result is zero, and one conditional branch is enough.

#### 18.1 Conditions

Bits 3–1 pick a test and bit 0 inverts it, as in draft 0 and ARM.

| cc | Name | Test | cc | Name | Test |
|---|---|---|---|---|---|
| 0 | `EQ` | Z | 1 | `NE` | !Z |
| 2 | `CS`/`HS` | C | 3 | `CC`/`LO` | !C |
| 4 | `MI` | N | 5 | `PL` | !N |
| 6 | `VS` | V | 7 | `VC` | !V |
| 8 | `HI` | C & !Z | 9 | `LS` | !C \| Z |
| A | `GE` | N = V | B | `LT` | N ≠ V |
| C | `GT` | !Z & N = V | D | `LE` | Z \| N ≠ V |
| E | `RA` (always) | 1 | F | link | `BSR` / `CALL` |

### 19. Encoding

The main format is `F D M R`: operation, register, mode, and a register (or
a small constant) for the mode. Each digit is one field, as in draft 0.

| op | Layout | Instructions |
|---|---|---|
| 0 | `0 a b f` | System group ([24](#24-system-group)) |
| 1 | `1 d M R` | `MOV rd, ea`: load, move, load immediate. Sets NZ. |
| 2 | `2 d M R` | `ST rd, ea`: store (memory modes only) |
| 3 | `3 d M R` | `LEA rd, ea`: the address of a memory operand (not the auto-increment modes) |
| 4 | `4 d M R` | `ADD rd, ea` |
| 5 | `5 d M R` | `SUB rd, ea` |
| 6 | `6 d M R` | `CMP rd, ea` |
| 7 | `7 d M R` | `AND rd, ea` |
| 8 | `8 d M R` | `OR rd, ea` |
| 9 | `9 d M R` | `XOR rd, ea` |
| A | `A c k 0` + target | `Jcc` (c = E: `JMP`, c = F: `CALL`): k = 0: `PC ← PC + 2·simm16`; k = 1: absolute 32-bit |
| B | `B k M R` | k = 0: `JMP ea`, k = 1: `CALL ea`: jump to the *value* of the operand ([20.1](#201-which-instructions-take-which-modes)) |
| C | `C d s f` | Unary group: `rd ← f(rs)` ([22](#22-unary-functions)) |
| D | `D d s f` | Shift group ([23](#23-shifts)) |
| E | `E c ii` | `Bcc` (c = F: `BSR`): `PC ← PC + 2·simm8` |
| F | `F d s f` | Register-only ALU functions ([21](#21-alu-functions)); `f = F` traps, so `FFFF` traps |

`PC` in relative branches and addresses is the address of the next
instruction.

### 20. Addressing modes

`M` is the mode, `R` the register (or constant) it uses. Memory operands are
words unless the mode says otherwise; byte and half operands are
zero-extended when read.

| M | Operand | Syntax | Extra parcels |
|---|---|---|---:|
| 0 | register `R` | `r2` | 0 |
| 1 | constant `R` (0–15) | `#5` | 0 |
| 2 | word at `R` | `[r2]` | 0 |
| 3 | word at `R + d16` | `[r2 + 8]`, `[label + r2]` | 1 |
| 4 | word at `sp + 4R` (stack slot, 0–60) | `[sp + 12]` | 0 |
| 5 | indexed: `R + Rx·scale + d8`, any size | `[r2 + r3*4 + 8]`, `byte [r2 + r3]` | 1 |
| 6 | word at `R`, then `R ← R + 4` | `[r2]+` | 0 |
| 7 | `R ← R − 4`, then word at `R` | `-[r2]` | 0 |
| 8 | byte at `R` | `byte [r2]` | 0 |
| 9 | byte at `R + d16` | `byte [r2 + 1]`, `byte [table + r2]` | 1 |
| A | byte at `R`, then `R ← R + 1` | `byte [r2]+` | 0 |
| B | half at `R` | `half [r2]` | 0 |
| C | half at `R + d16` | `half [r2 + 2]` | 1 |
| D | constant `−(R + 1)` (−1 to −16) | `#-1` | 0 |
| E | reserved (traps) | | |
| F | special, chosen by `R` (below) | | 1–2 |

The extension parcel of the indexed mode (5) is `x s z dd`: index register
`x` (4 bits), scale `s` (2 bits: ×1, ×2, ×4, ×8), size `z` (2 bits: byte,
half, word; 3 is reserved) and a signed 8-bit displacement.

Mode F uses `R` to pick an operand that needs no register:

| R | Operand | Syntax | Extra parcels |
|---|---|---|---:|
| 0 | signed 16-bit constant | `#-300` | 1 |
| 1 | unsigned 16-bit constant | `#0xFFFF` | 1 |
| 2 | 16-bit constant shifted left 16 | `#0x12340000` | 1 |
| 3 | 32-bit constant | `#0x12345678` | 2 |
| 4, 5, 6 | word, byte, half at a sign-extended 16-bit absolute address | `[counter]`, `byte [0xFFFFFF00]` | 1 |
| 7, 8, 9 | word, byte, half at a 32-bit absolute address | | 2 |
| A, B, C | word, byte, half at `PC + d16` | `[pc + label]` | 1 |
| D–F | reserved | | |

The assembler picks the shortest mode for each operand: a constant 0–15 or
−1…−16 fits in the instruction, `[sp + 8]` uses the stack-slot mode, `[r2 + 0]`
becomes `[r2]`, and an address becomes a 16-bit absolute address if it fits,
otherwise PC-relative, otherwise 32-bit.

#### 20.1 Which instructions take which modes

| Instruction | Modes |
|---|---|
| `MOV`, `ADD`, `SUB`, `CMP`, `AND`, `OR`, `XOR` | all |
| `ST` | memory modes only (not 0, 1, D, or the constants in F) |
| `LEA` | memory modes except the auto-increment and auto-decrement ones (6, 7, A) |
| `JMP ea`, `CALL ea` | all: `JMP r3` jumps to the address in `r3`, `JMP [r3 + 8]` to the address *stored* at `r3 + 8`, `JMP #addr` to an absolute address |

A mode an instruction can't use traps as an illegal instruction.

`JMP ea`/`CALL ea` take the operand's *value*, like `MOV PC, ea`, so a jump
table is one instruction: `JMP [table + r2]` (with `r2` already multiplied by
4). For plain relative jumps and calls, use `Bcc`/`BSR` and op A.

### 21. ALU functions

The 16 two-operand functions, `rd ← rd ⊕ src`. Seven of them take any
addressing mode for `src`, each in an op of its own ([19](#19-encoding)):
`MOV`, `ADD`, `SUB`, `CMP`, `AND`, `OR` and `XOR`. The other nine take
two registers, in op F, `F d s f`:

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9–F |
|---|---|---|---|---|---|---|---|---|---|---|
| | `ADC` | `SBC` | `BIC` | `TST` | `MULU` | `MULS` | `DIVU` | `DIVS` | `DIVUL` | traps |

So `TST`, `BIC`, `ADC`, `SBC`, multiply and divide have no immediate or
memory forms.

| Name | Operation |
|---|---|
| `ADD` | `rd ← rd + src` |
| `ADC` | `rd ← rd + src + C` (sticky Z) |
| `SUB` | `rd ← rd − src` |
| `SBC` | `rd ← rd − src − !C` (sticky Z) |
| `AND` | `rd ← rd & src` |
| `OR` | `rd ← rd \| src` |
| `XOR` | `rd ← rd ^ src` |
| `BIC` | `rd ← rd & ~src` |
| `MOV` | `rd ← src` |
| `CMP` | flags of `rd − src` |
| `TST` | flags of `rd & src` |
| `MULU` | `HI:rd ← rd × src`, unsigned 64-bit product |
| `MULS` | `HI:rd ← rd × src`, signed 64-bit product |
| `DIVU` | `rd ← rd ÷ src`, `HI ← remainder`, unsigned |
| `DIVS` | `rd ← rd ÷ src` rounded toward zero, `HI ← remainder` (sign of the dividend) |
| `DIVUL` | `rd ← HI:rd ÷ src`, `HI ← remainder`, unsigned 64/32 divide |

- Dividing by zero is a *divide error* trap (registers unchanged).
- Multiply time depends on the implementation, but small operands are
  faster, so put the smaller factor second (`src`). The timing model charges
  by the significant bits of `src`; the draft 1b hardware takes 16 or 32
  steps ([report 0012](0012-report-draft-1b-hardware.md)).
- `DIVS` of `−2^31 ÷ −1` gives `−2^31`, remainder 0, and sets V.
- `DIVUL` with `HI ≥ src` would overflow: it sets V and leaves `rd`, `HI`
  and the other flags unchanged. Chained `DIVUL`s (remainder left in `HI` for the next word)
  divide a bignum by a word, one instruction per word.

### 22. Unary functions

Op C, `C d s f`: `rd ← f(rs)`. The source is a separate register; `NOT r1`
is short for `NOT r1, r1`.

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C–F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `NOT` | `NEG` | `INC` | `DEC` | `RLC` | `RRC` | `SWAP` | `SXB` | `ZXB` | `SXH` | `ZXH` | `CLZ` | traps |

| Name | Operation | Flags |
|---|---|---|
| `NOT` | `~rs` | NZ |
| `NEG` | `0 − rs` | NZCV |
| `INC` | `rs + 1` | NZ |
| `DEC` | `rs − 1` | NZ |
| `RLC` | rotate left through carry: `(rs << 1) \| C`, `C ← bit 31` | NZC, V ← 0 |
| `RRC` | rotate right through carry: `(rs >> 1) \| (C << 31)`, `C ← bit 0` | NZC, V ← 0 |
| `SWAP` | swap the 16-bit halves | NZ |
| `SXB`, `ZXB` | sign-/zero-extend the low byte | NZ |
| `SXH`, `ZXH` | sign-/zero-extend the low half | NZ |
| `CLZ` | number of leading zero bits, 0–32 | NZ |

### 23. Shifts

Op D, `D d s f`, in place on `rd`. Bits 1–0 of `f` pick the operation and
bits 3–2 the count.

| f bits 1–0 | Name | Operation |
|---|---|---|
| 0 | `LSL rd, #n` / `LSL rd, rs` | logical shift left |
| 1 | `LSR rd, #n` / `LSR rd, rs` | logical shift right |
| 2 | `ASR rd, #n` / `ASR rd, rs` | arithmetic shift right |
| 3 | `ROR rd, #n` / `ROR rd, rs` | rotate right (C = the last bit rotated round, i.e. the new bit 31) |

| f bits 3–2 | Count |
|---|---|
| 0 | `#s` (0–15) |
| 1 | `#s + 16` (16–31) |
| 2 | register `rs` (low 5 bits) |
| 3 | reserved (traps) |

`n` is 0–31. With a register, the count is `rs & 31`. Rotate left by `n` is
`ROR` by `32 − n`.

### 24. System group

Op 0, `0 a b f`:

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C | D | E–F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `HALT` | `NOP` | `JMP rs` | `CALL rs` | `RET` | `SAVE` | `RESTORE` | `RTI` | `EI` | `DI` | `MFSR` | `MTSR` | `SWI` | `SETcc` | traps |

| Name | Operation |
|---|---|
| `HALT` | Stop. With interrupts enabled, wait for an interrupt instead. The all-zero parcel is `HALT`. |
| `NOP` | |
| `JMP rs` | `PC ← rs` |
| `CALL rs` | push the return address; `PC ← rs` |
| `RET` | pop `PC` |
| `SAVE ra-rb` | push `ra`…`rb` (1 ≤ a ≤ b ≤ 14): `sp ← sp − 4n`, then `ra` at `[sp]`, `ra+1` at `[sp+4]`, … |
| `RESTORE ra-rb` | the reverse: load `ra`…`rb` from `[sp]`…, then `sp ← sp + 4n`. Flags unchanged. |
| `RTI` | pop flags, pop `PC` |
| `EI` / `DI` | `I ← 1` / `I ← 0` |
| `MFSR rd, n` / `MTSR n, rs` | read/write special register `n`: 0 = flags word, 1 = `HI`. Aliases: `MFF rd`, `MTF rs`, `MFHI rd`, `MTHI rs`. |
| `SWI #n` | software interrupt with an 8-bit number (the handler finds it in the instruction at `[saved PC − 2]`) |
| `SETcc rd` | `rd ← 1` if the condition holds, else 0. Flags unchanged. |

Field use: `JMP`/`CALL rs` put `rs` in `b`; `SAVE`/`RESTORE ra-rb` put `a`
and `b` in `a` and `b`; `MFSR rd, n` is `0 d n A`; `MTSR n, rs` is
`0 n s B`; `SWI #n` puts the 8-bit number in `a b`; `SETcc rd` is
`0 d cc D`.

`PUSH r` and `POP r` are assembler aliases for `ST r, -[sp]` and
`MOV r, [sp]+` (which sets NZ).

### 25. Calls, the stack and interrupts

- The stack grows down and `sp` points at the last word pushed. Every push
  and pop is a 32-bit word.
- `CALL`/`BSR` push the address of the next instruction. `RET` pops it.
- Vectors are 4 bytes apart, each room for one `JMP handler` (2 parcels):

  | Address | Vector |
  |---|---|
  | `0x00` | reset (also `I ← 0`) |
  | `0x04` | IRQ (level-triggered, when `I = 1`) |
  | `0x08` | illegal instruction |
  | `0x0C` | `SWI` |
  | `0x10` | divide error |
  | `0x14` | address error (misaligned access) |

- Entering an interrupt or trap pushes `PC`, then the flags word (`I N Z C V`
  in bits 4–0), clears `I` and jumps to the vector. `RTI` undoes it. For IRQs
  and `SWI` the saved `PC` is the next instruction; for the faults it's the
  faulting instruction.
- Interrupt timing is as in draft 0: interrupts are taken between
  instructions, never straight after `EI`, still possibly straight after `DI`,
  and right after `RTI` if the restored flags enable them. `HALT` with `I = 1`
  waits for an interrupt and continues after the `HALT` when the handler
  returns.

### 26. I/O page

All registers are 32 bits wide, 4 bytes apart. Byte accesses work on the low
byte.

| Address | Read | Write |
|---|---|---|
| `0xFFFFFF00` | console input byte, or `−1` (`0xFFFFFFFF`) if none is waiting | console output (low byte) |
| `0xFFFFFF04` | bit 0: a byte is waiting; bit 1: end of input | – |
| `0xFFFFFF08` | timer period | timer period in clock cycles (0 = off) |
| `0xFFFFFF0C` | timer flag (drives IRQ) | acknowledge the timer |
| `0xFFFFFF10` | cycle counter | – |

The timer:
- The first tick comes one period after the period is written.
- Writing period 0 stops the timer and clears a pending flag.
- In the simulator, the timer counts the cycles of the reference
  configuration (D16-overlap, see
  [the timing model](../studies/v1_isa/timing-model-v1.md)).
- `HALT` with `I = 1` but no timer running stops the machine, as with
  `I = 0`, because nothing could ever wake it.

The simulator supplies all input up front, so once it's used up the
end-of-input bit is set and reads return `−1`. Read the console with a word
load: a byte load returns `0xFF` at the end of input, which can't be told
apart from a real `0xFF` byte.

### 27. Software conventions

These are conventions for the programs, not hardware rules.

- Arguments in `r1`–`r4`, results in `r1` (and `r2` for a second value).
- `r1`–`r7` are scratch (caller-saved); `r8`–`r14` must be preserved by the
  callee; `sp` is `r15`.
- Programs start with `.include "lib/start.s"`, which sets up the vectors,
  sets `sp` to `0x00100000` (top of RAM) and calls `main`. When `main`
  returns, the machine halts.

### 28. Assembler syntax

```
label:  ADD   r1, r2
.loop:                          ; local label, scoped to the last global label
        .byte 1, 'a', "text"    ; 8-bit values
        .half 0x1234            ; 16-bit values (2-byte aligned)
        .word 0x12345678, label ; 32-bit values (4-byte aligned); .long is the same
        .asciz "hello\n"
        .space 32               ; zero-filled bytes
        .align 4
        .org  0x0100
size = end - start              ; constants (also .equ)
        .include "lib/print.s"
```

Mnemonics and registers are case-insensitive; `sp` is `r15`. Expressions
support `+ - * / % & | ^ << >> ~`, parentheses, `'c'` characters, `$` (the
current address), `lo()`/`hi()` (bytes) and `lo16()`/`hi16()` (halves).
Branches relax automatically: an out-of-range `Bcc` becomes a 2-parcel `Jcc`,
`BSR` becomes `CALL`. `LI rd, x` is an alias for `MOV rd, #x`.

Memory operands are written in square brackets, with the forms of the
addressing modes ([20](#20-addressing-modes)): `[r2]`, `[r2 + 8]`,
`[r2 - 4]`, `[label]` (absolute), `[label + r2]` (a 16-bit address plus a
register), `[r2]+`, `-[r2]`, `[r2 + r3*4 + 8]`. The size keywords are
`byte`, `half` and `word` (the default). `[pc + label]` forces PC-relative
addressing.

```
        MOV   r1, r2            ; register
        MOV   r1, #5            ; constant in the instruction
        MOV   r1, #msg          ; address of msg as a constant (16 or 32 bits)
        MOV   r1, [r2 + 8]      ; load a word
        MOV   r1, byte [r2]+    ; load a byte, then r2 += 1
        ADD   r1, byte [r8 + 1] ; add a zero-extended byte from memory
        CMP   r1, [sp + 12]     ; compare with a stack slot
        ST    r1, half [r2 + 6] ; store the low half of r1
        ST    r1, -[sp]         ; push (also: PUSH r1)
        MOV   r1, [sp]+         ; pop  (also: POP r1)
        MOV   r3, [r2 + r4*4]   ; indexed
        LEA   r1, [msg]         ; address of msg (absolute or PC-relative)
        LEA   r1, [r2 + r3*8 + 4]
        JMP   [table + r2]      ; jump table
        CALL  [r9 + 8]          ; call through a pointer in memory
        CALL  r3                ; call the address in r3
        BNE   .loop             ; becomes JNE (2 parcels) if out of range
        BSR   helper            ; becomes CALL if out of range
        LSL   r1, #4            ; shift group
        INC   r1                ; unary group: NZ only
        MULU  r1, r2            ; register-only group: HI:r1 ← r1 × r2
        SAVE  r8-r11
```

## Part III: 1a against 1b

**Short version.**

- **1b is faster, but not by much.** In every hardware configuration 1b
  takes 7–10% fewer cycles than 1a, runs 13% fewer instructions and has 3%
  less code (geometric means over 20 programs).
- **The gain is concentrated in a few programs.** A bytecode interpreter
  (−24%), Life (−16%) and the string- and pointer-walking programs (−7 to
  −17%) carry it. In the register-bound programs (queens, mandel, fib,
  bignum, matmul, bst, interrupts) the two drafts are within 3%.
- **Most of 1b's lead comes from auto-increment, which 1a could have.** 1a's
  unused opcode F has room for post-increment and pre-decrement loads and
  stores, and that alone would close more than half the gap. 1b has the
  opposite problem: its 4-bit constants make every character constant
  2 parcels, and its encoding has no room left to fix that.
- **The hardware choices matter more than the ISA choice.**
  - Going from a 16-bit to a 32-bit datapath saves ~22% of cycles.
  - Overlapping fetch with execution saves 17–22%.
  - A 32-bit bus with a prefetch buffer saves another ~10%.
  - A 32-bit ISA on draft 0's 16-bit datapath and bus is *slower* than
    draft 0 on 10 of the 16 shared programs: everything that isn't
    multiply or divide.

**Recommendation:** base draft 2 on 1a and add auto-increment loads and
stores, and probably a jump through a table. Build it with a 32-bit datapath
if the chip budget allows, or at least a 32-bit bus.

> **Erratum (2026-10-15).** The recommendation to base draft 2 on 1a is
> withdrawn, and draft 2 builds on 1b (Emily). It rested on faulty
> numbers:
>
> - **Compiled C.** The C compiler's first measurement had 1b taking
>   0.978 of 1a's cycles, with seven of the fifteen programs slower on 1b,
>   and that was read as support for 1a. A register-allocation bug caused
>   it: the compiler counted a loop with two back edges twice, and spilled
>   1b's hot loops in `printf`. Fixed in `bfe9b7e`, compiled C takes
>   0.943 of 1a's cycles and three programs are a fraction slower
>   ([report 0011](0011-report-c-compiler.md#1a-against-1b-for-compiled-code)).
> - **1b's encoding isn't full.** This report counted only the reserved
>   modes and special forms. Op A alone has about 4,064 free encodings
>   ([RFC 0006, 3.1](0006-rfc-ideas-isa.md#31-room-left-in-1bs-encoding)),
>   room for a one-parcel form with a 7-bit constant.
>
> The hand-written cycle counts weren't affected, and neither are the
> hardware recommendations.

**Since then, draft 1b has been built** as a chip-level netlist in the
D32-separate configuration ([report 0012](0012-report-draft-1b-hardware.md)).

- It's 213 chips.
- It runs at 3.0 MHz worst case (4.2 MHz typical) with 74HCT, which
  confirms the 3 MHz used below.
- It needs 0.91 times the cycles the model estimates. Everything that writes
  a register is a cycle cheaper, because the write-back shares the fetch
  cycle. Multiplies are slower, because they don't stop early.
- It's about twice as fast as the draft 0 hardware.

### 29. What was built

- **Specs:** [draft 1a](#part-i-draft-1a) and [draft 1b](#part-ii-draft-1b).
  - Both are 32-bit machines with 16 registers and 16-bit instruction
    parcels plus 0–2 extension parcels.
  - Both have hardware multiply/divide with a `HI` register, `SAVE`/`RESTORE`,
    shifts by n, `SETcc`, and `INC`/`DEC` that leave C and V alone.
  - They differ only in how operands are encoded
    ([30](#30-what-each-has-that-the-other-doesnt)).
- **Tooling:** an assembler and instruction-level simulator for each. Every
  first parcel round-trips through the disassembler and assembler unchanged.
- **Timing model** ([timing-model-v1.md](../studies/v1_isa/timing-model-v1.md)): a micro-op
  scheduler that costs each executed instruction for six machines. These are
  a 16- or 32-bit datapath, each with one of three fetch styles:
  - **separate:** its own fetch cycle per instruction;
  - **overlap:** the next fetch in the last cycle, like draft 0;
  - **wide:** a 32-bit bus and a two-parcel prefetch buffer.
- **20 programs, each written for both ISAs.** They are the 16 from draft 0
  plus four new 32-bit-era ones: SHA-256, word frequencies with a hash table,
  a bytecode interpreter, and line/circle drawing into a framebuffer.
  - All 40 versions produce output identical to independent Python reference
    implementations.
  - Five agents wrote them. Each wrote its programs for both ISAs,
    alternating which came first, and kept notes
    ([report 0003](0003-report-draft-1-programming-notes.md): library, numeric, games, interactive,
    newprogs).
- **Tables:** [performance.md](0004-rfc-draft-1-isa/performance.md), generated by
  `heron v1_isa report`, has every number below plus per-program tables.

### 30. What each has that the other doesn't

- 1b: memory operands for `ADD SUB CMP AND OR XOR`, auto-increment and
  auto-decrement, indexed addressing with a scaled index register, stack
  slots, PC-relative loads and stores, indirect jumps and calls through
  memory, and constants −16…15 in one parcel for every main instruction.
- 1a: one-parcel loads and stores with a small offset from any base register
  (`[r8 + 1]` is 2 parcels in 1b), 8-bit constants in one parcel for
  `MOV`/`ADDI`/`CMP`, immediate forms of every ALU function (including
  `TST`, `BIC`, `MUL`, `DIV`), an `ADDI` that leaves C and V alone, and sign-extending
  loads.

### 31. Cycles

Cycles, 1b relative to 1a: the geometric mean over the 20 programs, so each
program counts once. The bytecode interpreter alone is half of all cycles, so
a plain total would mostly measure it.

| | separate fetch | overlapped fetch | wide fetch |
|---|---:|---:|---:|
| 16-bit datapath | 0.902 | 0.919 | 0.905 |
| 32-bit datapath | 0.909 | 0.932 | 0.915 |

The gap is smallest with a 32-bit datapath and overlapped fetch. There the
extra cycle that 1a's separate pointer-step instruction costs is cheapest,
and 1b's longer instructions cost the most fetch cycles relative to the rest.

Where the difference comes from (D16-overlap, 1b / 1a):

| Group | Programs | 1b / 1a | Why |
|---|---|---:|---|
| Dispatch and stack code | vm | 0.76 | `MOV r1, byte [r8]+` / `JMP [r13 + r1*4]` is the whole dispatch, 9 cycles. 1a needs `LDB` / `ADDI` / `LSL #2` / `LD` / `JMP`, 18 cycles. Binary operators are `ADD r9, [sp]+`. |
| Memory operands | life | 0.84 | the neighbour count is one `ADD r1, byte [r2 + d]` per neighbour, against `LDB` + `ADD` |
| Pointer walking | strings, sort, wordfreq, rpn, monitor, sieve | 0.83–0.93 | `[r]+` absorbs the pointer step, which is 9.5% of the instructions 1a executes |
| Everything in registers | queens, mandel, fib, bignum, matmul, bst, interrupts, lines, crc, sha256, arith | 0.95–1.00 | the hot loops are the same instructions in both |

1b executes 13% fewer instructions but saves only about 8% of cycles. Its
instructions are longer: 1.22 parcels executed on average, against 1.14 for
1a. A memory operand also saves only one write-back cycle, not a whole
instruction's worth:

| Instruction | Cycles on D16-overlap |
|---|---:|
| 1b `ADD r1, [r2]` | 6 |
| 1a `LD` + `ADD` | 4 + 3 = 7 |

#### 31.1 What if 1a had auto-increment?

1a's op F is unused, so post-increment and pre-decrement loads and stores
(`LDB r1, [r2]+`, `ST r1, -[sp]`) fit without changing anything else. As an
estimate, I removed every `ADDI` that steps the base register of an adjacent
load or store and charged the access the same as before.

**Result:** 1a's cycles drop to 0.952 of today's (geometric mean), against
1b's 0.919. That recovers 60% of the gap with one opcode.

The estimate is probably low. The 1a code is shaped around the short
offsets, so many steps aren't next to an access. For example, the
interpreter reads operands at `[r8 + 1]`, `[r8 + 2]` and steps once per
instruction, and only a rewrite would show what auto-increment does there.
What's left after auto-increment is mostly the interpreter's dispatch
(fixable with a jump-through-table instruction) and Life's memory operands.

### 32. Code size

| | 1a | 1b |
|---|---:|---:|
| Code in all programs and libraries | 6,304 bytes | 6,044 bytes |
| Bytes per instruction | 2.44 | 2.57 |
| 2-parcel instructions | 22% | 28% |
| Per-program own code, geometric mean | 1 | 0.972 |
| Instruction bytes fetched while running | 4.69 MB | 3.65 MB |
| Data bytes loaded and stored | 1.98 MB | 1.98 MB |

1b has fewer instructions, but more of them are long. Three things push its
size up:

- **4-bit constants.** 13% of 1b's operands in the source are 16-bit
  constants that 1a would mostly encode in one parcel: characters, 16, 31,
  32, 255, `AND #255`.
- **No one-parcel `[r + small offset]`.** Struct fields cost an extension
  parcel, so bst's `inorder` and `height` are 3–5% slower in 1b.
- **Constants needed as registers.** No immediate forms of `TST`, `BIC`,
  `MUL` or `DIV`.

As a result, rpn, bst, fib, mandel, queens, wordfreq and strings have
slightly *more* own code in 1b despite running fewer instructions.

Counting the library routines each program pulls in, draft 1 code is
smaller than draft 0's for 13 of the 16 shared programs in 1a and 14 in 1b,
by 6–44%. 32-bit registers and hardware multiply/divide remove whole
subroutines. The exceptions are hello (a bigger startup file), queens and,
in 1a, bignum.

### 33. The hardware configurations

Cycles relative to D16-separate of the same ISA (geometric mean):

| | separate | overlap | wide |
|---|---:|---:|---:|
| 1a, 16-bit datapath | 1.00 | 0.83 | 0.76 |
| 1a, 32-bit datapath | 0.82 | 0.64 | 0.58 |
| 1b, 16-bit datapath | 1.00 | 0.84 | 0.76 |
| 1b, 32-bit datapath | 0.82 | 0.66 | 0.58 |

Speed-up over draft 0 (exact draft 0 cycles on its own hardware) on the 16
shared programs, geometric mean:

| | separate | overlap | wide |
|---|---:|---:|---:|
| 1a, 16-bit datapath | 1.03× | 1.24× | 1.36× |
| 1a, 32-bit datapath | 1.27× | 1.60× | 1.78× |
| 1b, 16-bit datapath | 1.13× | 1.34× | 1.48× |
| 1b, 32-bit datapath | 1.38× | 1.70× | 1.93× |

**The averages hide that a narrow draft 1 machine is slower than draft 0 on
most programs.** On D16-overlap, 1a beats draft 0 only on the programs that
multiply or divide:

| Program | Speed-up over draft 0 |
|---|---:|
| bignum | 4.4× |
| mandel | 3.6× |
| interrupts | 3.2× |
| matmul | 2.6× |
| rpn | 1.1× |

It loses on 10 others, for example crc 0.75×, sort 0.76× and fib 0.79×.
Three things cost extra cycles there:

- every 32-bit ALU operation takes two passes on a 16-bit datapath;
- every return address, saved register and word load takes two bus cycles
  on a 16-bit bus;
- extension parcels get a cycle of their own. Draft 0 fed them straight into
  the ALU, which was its critical path; the model doesn't allow that.

Even D32-overlap leaves call-heavy fib 9% slower than draft 0, because of the
16-bit bus. Only D32-wide beats draft 0 on every program.

**Alignment.** The wide fetch reads aligned 32-bit words, so its numbers
depend on where loops fall. Shifting 1b's Life by one parcel changes it by
12–15%. The report averages both alignments. A real assembler should have an
`.align` that pads code with `NOP`s, so hot loops can be aligned (today
`.align` pads with zeros, which are `HALT`).

#### 33.1 Rough hardware cost

These are estimates from the 98-chip draft 0 design, not a design:

| Option | Extra chips (rough) | What it buys |
|---|---:|---|
| 32-bit registers, 16-bit ALU and bus (D16) | +40–50 over draft 0 | the 32-bit ISA; slower than draft 0 except on multiply/divide |
| 32-bit ALU and datapath (D32) | +25–35 over D16 | ~22% fewer cycles |
| Overlapped fetch | ~0–2 (draft 0 already does it) | ~17% fewer cycles |
| Wide fetch: 32-bit memory, prefetch buffer, parcel steering | +10–15 | ~9% fewer cycles than overlap, and single-cycle word loads |
| 1b instead of 1a | +5–15, plus a microcode ROM twice the size | ~8% fewer cycles |

The extra 1b chips go on:

- feeding the extended mode decode into the microcode address;
- the index-register field of the extension parcel, into the register-file
  address mux;
- the scale shifter on the B bus, which the model assumes exists;
- zero-extending byte and half memory operands on their way into the ALU.

### 34. Programming niceness

From the five writers' notes:

- **Both drafts were easy to get right.**
  - 40 programs plus libraries produced 3 assembler errors and 1 wrong
    output, all in 1a's long programs (sha256, lines, bst).
  - Every 1b version and most 1a versions worked the first time they ran.
  - The extra edge-case testing the writers did found one tool bug: `tmc
    run` re-encoded output bytes above 0x7F. It is fixed, and `tmc test`
    was never affected.
- **Draft 1 removed draft 0's pain in both drafts alike.**
  - Hardware `MUL`/`DIV`/`DIVUL` replaced the software routines that took
    60–80% of draft 0's arithmetic programs.
  - `SAVE r1-r7` replaced 14 pushes and pops.
  - `SETcc` replaced Life's `NEG`/`ADC` trick.
  - `SXH`/`ZXH` make 16-bit semantics exact.
  - `LSL #4` replaced four shifts.
  - Every writer said the shared machine, not the encoding, made their
    programs simpler.
- **1b reads better in pointer and table code.**
  - The byte loops shrink to 3 instructions (`MOV r2, byte [r1]+` / `BEQ` /
    `ST`).
  - Life's neighbour count reads like the algorithm:

    ```
    1a:  LDB  r5, [r2 + 2]         1b:  ADD  r1, byte [r2 + 1]
         ADD  r1, r5                    ADD  r1, byte [r2 + W2 - 1]
         LDB  r5, [r2 + W2]             ...
         ADD  r1, r5
    ```

  - Dispatch tables are one instruction (`JMP [table + r2]`,
    `CALL [cmdtab + r2]`).
  - `LEA [rA + rB*s]` is the only three-operand add either draft has.
- **1b needs more thought.**
  - Post-increment overshoots: after `byte [r]+` the pointer is past the
    NUL. That forced `DEC` fix-ups in rpn and the monitor, and two
    `SUB #4`s in qsort.
  - `CMP reg, [mem]` puts the memory operand second, so "a[i] < pivot"
    became `BHI`.
  - 1b's `POP` is `MOV [sp]+`, which sets N and Z, so it can't sit between
    a test and its branch. 1a's `RESTORE` leaves the flags alone.
  - There is no byte or half auto-decrement (backwards loops in `memmove`
    and `reverse`), no half auto-increment, and the indexed mode's 8-bit
    displacement can't hold a table address.
  - The writers rarely used ALU memory operands outside Life and the
    interpreter: "worth using in only 8 places" in the five numeric
    programs, 5 in the three interactive ones.
- **1a has fewer rules, and 8-bit immediates that fit real constants.** Its
  pitfalls:
  - `ADDI` sets Z, so a pointer step can't sit between a load and the branch
    that tests it. This forced a "step first, then load" idiom.
  - The short offsets reach only 15 bytes for byte loads, too little for a
    34-byte Life row.
  - There is no register + register addressing.
- **Gaps both share:**
  - Two-operand shifts are destructive: `MOV` is 25–27% of sha256's
    instructions.
  - Neither has a memory increment (`INC [count]`). fib's call counter is
    30% of its time, and the timer interrupt handler is a load, add and
    store.
  - `MOV`/`MVI` set N and Z, so a constant can't be loaded between a
    compare and its branch.
  - `INC`/`DEC`/`TST` leave V stale for signed branches.
  - There are no assembler macros, which sha256's rounds wanted.
- **Registers:**
  - Neither draft ran short. Most programs named 10–15 registers, the same
    number in both drafts. sha256, lines and wordfreq used all 15 without
    spilling.
  - 1b's stack-slot mode (`[sp + n]`) was used 0.0% of the time.
  - In the three interactive programs, 1b's memory operands saved a
    register exactly once.

### 35. Recommendations for draft 2

> **Erratum (2026-10-14):** recommendation 1 is withdrawn; see the
> erratum at the top of Part III.

1. **Start from 1a.** 1b's lead is real, but most of it is auto-increment
   and table dispatch, which fit 1a's spare encoding space. 1b's
   weaknesses, by contrast, have no room left in its encoding:
   - its 4-bit constants;
   - no one-parcel small offsets;
   - no immediate `TST`/`BIC`/`MUL`/`DIV`.

   1b's 16-bit `F D M R` format is full, with one reserved mode and three
   reserved special forms left. 1b also costs more chips and microcode.
2. **Add post-increment and pre-decrement loads and stores to 1a**, in op F:
   - byte and word `[r]+`, plus half if it fits;
   - word `-[r]` for pushes, plus byte for backwards loops.

   This recovers an estimated 60% or more of the gap to 1b, and removes the
   "`ADDI` sets Z" ordering problem from pointer loops.
3. **Consider a jump through a table:** `JMP [table + r*4]` in a free system
   function, with the table in an extension parcel. It matters only for
   interpreters and command dispatchers. But a BASIC or Forth is a likely
   program for this machine. 1b runs the interpreter 24% faster, and its
   one-instruction dispatch (9 cycles against 18) is the biggest single part
   of that.
4. **Smaller additions the notes argue for:**
   - an `INC [mem]`-style memory increment (counters, interrupt handlers);
   - `.align` padding code with `NOP`s;
   - assembler macros;
   - 1b's three-operand `LEA [rA + rB*s]` as a 1a `ADD rd, rs, rt`, if an
     encoding turns up.
5. **Hardware.** A 32-bit ISA on a 16-bit datapath and bus is a step back
   from draft 0 on ordinary code.
   - **32-bit datapath with overlapped fetch:** this is where draft 1 starts
     to pay off, at 1.6–1.7× draft 0 overall.
   - **32-bit bus:** the next best step. It's the only one that fixes stack
     and call cost, and the wide-fetch configurations need it anyway.
   - **If the chip budget forces a 16-bit datapath,** keep the 32-bit bus
     and the prefetch buffer: D16-wide gets 1.36–1.48× draft 0.

### 36. Caveats

- **The cycle counts come from a model, not a design.** All six
  configurations are assumed to run at the same clock. A 32-bit datapath, a
  wide bus and 1b's decoding each add some delay or chips. The model costs
  both drafts by the same rules, so the 1a/1b comparison is more reliable
  than the absolute numbers. (The 1b implementation has since checked one
  configuration, D32-separate: within 9%, see above.)
- **The model changed twice while the programs were written**, both times to
  remove an unfairness the writers found:
  - auto-increment had cost an extra cycle that microcode wouldn't need;
  - a scaled index register had been charged like a small displacement on
    the 16-bit datapath.

  All numbers here are from the final model.
- **The programs are hand-written by careful programmers, and were checked
  against the Python references.** Compiled code was expected to lean more
  on stack frames and memory operands, which would favour 1b. The C
  compiler has since measured it: compiled code gains less from 1b, not
  more. 1b saves 6% of the cycles in compiled C, against 7.5% for the
  hand-written versions of the same 15 programs
  ([report 0011](0011-report-c-compiler.md#1a-against-1b-for-compiled-code)).
- **The writers knew which program they were comparing**, and were asked to
  give both ISAs equal care. Each alternated which ISA it wrote first.
