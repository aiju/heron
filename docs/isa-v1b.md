# ISA draft 1b: register + addressing mode (CISC-like)

In draft 1b, every main instruction has one register operand and one
*effective address* (EA): a register, an immediate, or a memory operand
reached through one of a dozen addressing modes. So `ADD r1, [r2 + 8]` adds a
word from memory in one instruction, and there are no separate load
instructions: a load is `MOV rd, ea` and a store is `ST rd, ea`. At most one
operand is ever in memory. The machine state, flags, unary and shift
functions, system group, interrupts and I/O are in the
[common document](isa-v1.md).

## Encoding

The main format is `F D M R`: operation, register, mode, and a register (or
a small constant) for the mode. Each digit is one field, as in draft 0.

| op | Layout | Instructions |
|---|---|---|
| 0 | `0 a b f` | System group (the same as draft 1a) |
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
| B | `B k M R` | k = 0: `JMP ea`, k = 1: `CALL ea`: jump to the *value* of the operand (below) |
| C | `C d s f` | Unary group: `rd ← f(rs)` (same functions as draft 1a) |
| D | `D d s f` | Shift group (same as draft 1a) |
| E | `E c ii` | `Bcc` (c = F: `BSR`): `PC ← PC + 2·simm8` |
| F | `F d s f` | Register-only ALU functions (below); `f = F` traps, so `FFFF` traps |

`PC` in relative branches and addresses is the address of the next
instruction.

### Addressing modes

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

### Which instructions take which modes

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

### Register-only ALU functions (op F)

| f | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9–F |
|---|---|---|---|---|---|---|---|---|---|---|
| | `ADC` | `SBC` | `BIC` | `TST` | `MULU` | `MULS` | `DIVU` | `DIVS` | `DIVUL` | traps |

These are `rd ← rd ⊕ rs` with both operands in registers. `TST`, `BIC`,
`ADC`, `SBC`, multiply and divide have no immediate or memory forms in 1b.

### Unary group (op C), shift group (op D), system group (op 0)

Exactly as in draft 1a (and the common document): unary `C d s f` with
`f` = `NOT NEG INC DEC RLC RRC SWAP SXB ZXB SXH ZXH CLZ`; shift `D d s f`;
system `0 a b f`.

## What 1b has that 1a doesn't, and the reverse

- 1b: memory operands for `ADD SUB CMP AND OR XOR`, auto-increment and
  auto-decrement, indexed addressing with a scaled index register, stack
  slots, PC-relative loads and stores, indirect jumps and calls through
  memory, and constants −16…15 in one parcel for every main instruction.
- 1a: one-parcel loads and stores with a small offset from any base register
  (`[r8 + 1]` is 2 parcels in 1b), 8-bit constants in one parcel for
  `MOV`/`ADDI`/`CMP`, immediate forms of every ALU function (including
  `TST`, `BIC`, `MUL`, `DIV`), a flag-preserving `ADDI`, and sign-extending
  loads.

## Assembler syntax

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

The size keywords are `byte`, `half` and `word` (the default). `[pc + label]`
forces PC-relative addressing. `LI rd, x` is an alias for `MOV rd, #x`.
