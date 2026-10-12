# ISA draft 1a: load/store (RISC-like)

Draft 1a is draft 0 widened to 32 bits, with the changes from the draft 0
evaluation: multiply and divide, a shift group, `SAVE`/`RESTORE`,
flag-preserving `INC`/`DEC`/`ADDI`, halfword and sign-extending loads, and
wider immediates. ALU instructions work on registers; memory is reached only
through loads and stores. The machine state, flags, unary and shift
functions, system group, interrupts and I/O are in the
[common document](isa-v1.md).

## Encoding

Every first parcel is four hex digits `op a b c`, and fields never move:
`a` is the destination register (or a condition), `b` the source or base
register, `c` a function or a small offset.

| op | Parcels | Layout | Instructions |
|---|---|---|---|
| 0 | 1 | `0 a b f` | System group |
| 1 | 1 | `1 d s f` | `rd ← rd ⊕ rs`: the 16 ALU functions |
| 2 | 1 | `2 d s f` | `rd ← f(rs)`: unary group |
| 3 | 1 | `3 c ii` | `Bcc` (c = F: `BSR`): `PC ← PC + 2·simm8` |
| 4 | 1 | `4 d s o` | `LD rd, [rs + 4o]` (word, offset 0–60) |
| 5 | 1 | `5 d s o` | `ST rd, [rs + 4o]` |
| 6 | 1 | `6 d s o` | `LDB rd, [rs + o]` (byte, zero-extended, offset 0–15) |
| 7 | 1 | `7 d s o` | `STB rd, [rs + o]` |
| 8 | 2–3 | `8 d k f` + imm | `rd ← rd ⊕ #imm`: the 16 ALU functions with an immediate (below) |
| 9 | 2–3 | `9 c k 0` + target | `Jcc` (c = E: `JMP`, c = F: `CALL`): k = 0: `PC ← PC + 2·simm16`; k = 1: absolute 32-bit address |
| A | 2–3 | `A d s f` + disp | Long memory forms (below) |
| B | 1 | `B d s f` | Shift group |
| C | 1 | `C d ii` | `MVI rd, simm8` |
| D | 1 | `D d ii` | `ADDI rd, simm8` (sets N and Z only) |
| E | 1 | `E d ii` | `CMPI rd, simm8` |
| F | – | – | Reserved (traps), so `FFFF` traps |

`PC` in relative branches and addresses is the address of the next
instruction.

### ALU functions (op 1, op 8)

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `ADD` | `ADC` | `SUB` | `SBC` | `AND` | `OR` | `XOR` | `BIC` | `MOV` | `CMP` | `TST` | `MULU` | `MULS` | `DIVU` | `DIVS` | `DIVUL` |

### Immediates (op 8)

The `k` digit says what follows:

| k | Extension | Value |
|---|---|---|
| 0 | 1 parcel | signed 16-bit, sign-extended |
| 1 | 1 parcel | unsigned 16-bit, zero-extended |
| 2 | 1 parcel | 16 bits shifted left by 16 (`0xNNNN0000`) |
| 3 | 2 parcels | full 32 bits |

### Long memory forms (op A)

`A d s f` followed by a displacement. The address is `rs + disp`, and with
`rs = r0` that's an absolute address.

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

### Unary group (op 2)

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C–F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `NOT` | `NEG` | `INC` | `DEC` | `RLC` | `RRC` | `SWAP` | `SXB` | `ZXB` | `SXH` | `ZXH` | `CLZ` | traps |

### Shift group (op B)

`B d s f`, where bits 1–0 of `f` pick `LSL`, `LSR`, `ASR`, `ROR` and bits 3–2
pick the count:

| f bits 3–2 | Count |
|---|---|
| 0 | `#s` (0–15) |
| 1 | `#s + 16` (16–31) |
| 2 | register `rs` (low 5 bits) |
| 3 | reserved (traps) |

### System group (op 0)

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C | D | E–F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `HALT` | `NOP` | `JMP rs` | `CALL rs` | `RET` | `SAVE` | `RESTORE` | `RTI` | `EI` | `DI` | `MFSR` | `MTSR` | `SWI` | `SETcc` | traps |

Field use: `JMP`/`CALL rs` put `rs` in `b`; `SAVE`/`RESTORE ra-rb` put `a`
and `b` in `a` and `b`; `MFSR rd, n` is `0 d n A`; `MTSR n, rs` is
`0 n s B`; `SWI #n` puts the 8-bit number in `a b`; `SETcc rd` is
`0 d cc D`.

## Assembler syntax

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
