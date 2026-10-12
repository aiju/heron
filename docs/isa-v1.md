# ISA draft 1: the common machine

Draft 1 is a 32-bit machine with 16-bit instruction words. There are two
candidate encodings of it, which share everything in this document:

- **[Draft 1a](isa-v1a.md)**, RISC-like: load/store, register–register ALU,
  short and long load/store forms. It follows on directly from draft 0.
- **[Draft 1b](isa-v1b.md)**, CISC-like: every ALU instruction takes one
  register and one *addressing mode*, which can be a register, an immediate
  or a memory operand (like the IBM 360's RX format, the 68000 and x86).

Instructions are made of 16-bit *parcels*: a first parcel, which is the
opcode, and 0–2 extension parcels holding immediates, displacements or
addresses. A 32-bit value in an instruction takes two parcels, low half
first. Instructions only need to be 2-byte aligned.

## Machine state

| Item | Description |
|---|---|
| `r0` | Always reads as 0. Writes are discarded. |
| `r1`–`r14` | General purpose, 32 bits. |
| `r15` / `sp` | Stack pointer. Used implicitly by calls, returns, `SAVE`/`RESTORE`, interrupts and traps. |
| `PC` | Program counter, 32 bits, always even. |
| `HI` | High half of a multiply, remainder of a divide. Read with `MFHI`, written with `MTHI`. |
| Flags | `N` negative, `Z` zero, `C` carry, `V` overflow, `I` interrupt enable. |

## Memory

- Byte addressed, little-endian, 32-bit addresses.
- RAM is 1 MB at `0x00000000`–`0x000FFFFF` in the simulator. The 256-byte
  I/O page is at `0xFFFFFF00`–`0xFFFFFFFF`, at the very top of the address
  space, so a sign-extended 16-bit absolute address (`0xFF00` → `0xFFFFFF00`)
  reaches it.
- Sizes: byte (8), half (16), word (32). A half must be at an even address
  and a word at a multiple of 4. A misaligned access is an *address error*
  trap. Touching an address that is neither RAM nor I/O stops the simulator
  with an error.
- Byte and half loads zero-extend (draft 1a also has sign-extending forms).

## Flags

| Instructions | Flags |
|---|---|
| `ADD`, `ADC`, `SUB`, `SBC`, `CMP`, `NEG` | NZCV |
| `AND`, `OR`, `XOR`, `BIC`, `TST`, `NOT` | NZ (C and V unchanged) |
| Loads, `MOV`, `MVI`, `POP` (in 1b), `SWAP`, extends, `CLZ` | NZ (C and V unchanged) |
| `INC`, `DEC`, and `ADDI` (1a) | **NZ only**: adding a constant never changes C or V |
| Shifts and rotates | NZ, C = last bit shifted out (unchanged for a count of 0), V = 0 |
| `MULU`, `MULS` | NZ from the low 32 bits; C = V = 1 if the full product doesn't fit in 32 bits (unsigned / signed) |
| `DIVU`, `DIVS`, `DIVUL` | NZ from the quotient; C = 0; V = 1 on overflow (see below) |
| Stores, `LEA`, branches, jumps, calls, `SAVE`, `RESTORE`, `SETcc`, `MFHI`/`MTHI`, `MFF` | unchanged |

`C` is a carry for additions and "no borrow" for subtractions, so after
`CMP a, b`, `HS` means `a ≥ b` unsigned.

`ADC` and `SBC` have a **sticky Z**: they can clear Z but never set it. So a
64-bit compare or subtract (`CMP lo` then `SBC hi`) leaves Z set only if the
whole 64-bit result is zero, and one conditional branch is enough.

### Conditions

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

## Register ALU functions

Both drafts have the same 16 two-operand functions; they differ in which ones
can take an immediate or memory operand. `src` is the second operand.

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
- `DIVS` of `−2^31 ÷ −1` gives `−2^31`, remainder 0, and sets V.
- `DIVUL` with `HI ≥ src` would overflow: it sets V and leaves `rd` and `HI`
  unchanged. Chained `DIVUL`s (remainder left in `HI` for the next word)
  divide a bignum by a word, one instruction per word.

## Unary functions: `rd ← f(rs)`

The source is a separate register; `NOT r1` is short for `NOT r1, r1`.

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

## Shifts: in place on `rd`

| Name | Operation |
|---|---|
| `LSL rd, #n` / `LSL rd, rs` | logical shift left |
| `LSR rd, #n` / `LSR rd, rs` | logical shift right |
| `ASR rd, #n` / `ASR rd, rs` | arithmetic shift right |
| `ROR rd, #n` / `ROR rd, rs` | rotate right (C = the last bit rotated round, i.e. the new bit 31) |

`n` is 0–31. With a register, the count is `rs & 31`. Rotate left by `n` is
`ROR` by `32 − n`.

## System group (the same in both drafts)

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

`PUSH r` and `POP r` are assembler aliases: in draft 1a for `SAVE r-r` and
`RESTORE r-r`, in draft 1b for `ST r, -[sp]` and `MOV r, [sp]+` (which sets
NZ).

## Calls, the stack and interrupts

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

## I/O page

All registers are 32 bits wide, 4 bytes apart. Byte accesses work on the low
byte.

| Address | Read | Write |
|---|---|---|
| `0xFFFFFF00` | console input byte, or `−1` (`0xFFFFFFFF`) if none is waiting | console output (low byte) |
| `0xFFFFFF04` | bit 0: a byte is waiting; bit 1: end of input | – |
| `0xFFFFFF08` | timer period | timer period in clock cycles (0 = off) |
| `0xFFFFFF0C` | timer flag (drives IRQ) | acknowledge the timer |
| `0xFFFFFF10` | cycle counter | – |

The simulator supplies all input up front, so once it's used up the
end-of-input bit is set and reads return `−1`.

## Software conventions

These are conventions for the programs, not hardware rules.

- Arguments in `r1`–`r4`, results in `r1` (and `r2` for a second value).
- `r1`–`r7` are scratch (caller-saved); `r8`–`r14` must be preserved by the
  callee; `sp` is `r15`.
- Programs start with `.include "lib/start.s"`, which sets up the vectors,
  sets `sp` to `0x00100000` (top of RAM) and calls `main`. When `main`
  returns, the machine halts.

## Assembler syntax (common to both drafts)

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
register). Each draft adds its own forms.
