# ISA draft 0

> **Draft 0 is superseded.** This is the 16-bit first draft, kept as a record. Draft 1 replaced it: see [report 0004](../../reports/0004-report-draft-1-evaluation.md) and [studies/v1b_hw/hardware.md](../v1b_hw/hardware.md).

A 16-bit load/store instruction set designed to be built from 7400-series
logic. Every instruction word is four hex digits, and fields never move:
the destination register is always the 2nd digit and the source register
always the 3rd. That makes the register fields wire straight to the register
file and lets you read instructions off front-panel lights.

## Machine state

| Item | Description |
|---|---|
| `r0` | Always reads as 0. Writes are discarded. |
| `r1`–`r14` | General purpose. |
| `r15` / `sp` | Stack pointer. Used implicitly by `PUSH`, `POP`, `CALL`, `RET`, `BSR`, interrupts and traps. |
| `PC` | Program counter, always even. Not a general register. |
| Flags | `N` negative, `Z` zero, `C` carry, `V` overflow, `I` interrupt enable. |

Memory is 64 KB, byte addressed, little-endian. Word accesses ignore address
bit 0, so they are always aligned. The top 256 bytes (`FF00`–`FFFF`) are the
I/O page.

## Encoding

```
 15  12 11   8 7    4 3    0
+------+------+------+------+
|  op  |  a   |  b   |  c   |
+------+------+------+------+
  a = rd (destination) or cc (condition)
  b = rs (source or base register)
  c = fn (function) or o (4-bit offset)
  ii = bits 7..0, a signed 8-bit immediate
```

| op | Words | Layout | Instructions |
|---|---|---|---|
| 0 | 1 | `0 d s f` | System group (table below) |
| 1 | 1 | `1 d s f` | `rd ← rd ⊕ rs` (ALU table) |
| 2 | 1 | `2 d s f` | `rd ← f(rs)` (unary table) |
| 3 | 1 | `3 c i i` | `Bcc target`: if condition, `PC ← PC + 2·simm8`; `c = F` is `BSR` |
| 4 | 1 | `4 d s o` | `LD rd, [rs + 2o]` (word offset 0–30) |
| 5 | 1 | `5 d s o` | `ST rd, [rs + 2o]` |
| 6 | 1 | `6 d s o` | `LDB rd, [rs + o]` (byte offset 0–15, zero-extends) |
| 7 | 1 | `7 d s o` | `STB rd, [rs + o]` |
| 8 | 2 | `8 d 0 f` + imm16 | `rd ← rd ⊕ #imm16` (same functions as op 1) |
| 9 | 2 | `9 c 0 0` + addr | `Jcc addr` (absolute); `c = F` is `CALL addr`, `c = E` is `JMP addr` |
| A | 2 | `A d s f` + disp16 | `f`: 0 `LD`, 1 `ST`, 2 `LDB`, 3 `STB`, 4 `LEA` with address `rs + disp16` |
| B | – | – | Reserved for a MUL/DIV extension (traps) |
| C | 1 | `C d i i` | `MVI rd, simm8` |
| D | 1 | `D d i i` | `ADDI rd, simm8` |
| E | 1 | `E d i i` | `CMPI rd, simm8` |
| F | – | – | Reserved (traps), so `FFFF` (erased memory) traps |

`PC` in branch offsets is the address of the next instruction. With `rs = r0`,
the long memory forms give absolute addressing: `LD r1, [label]`.

### ALU functions (op 1 and op 8)

| f | Name | Operation | Flags |
|---|---|---|---|
| 0 | `ADD` | `rd ← rd + rs` | NZCV |
| 1 | `ADC` | `rd ← rd + rs + C` | NZCV |
| 2 | `SUB` | `rd ← rd − rs` | NZCV |
| 3 | `SBC` | `rd ← rd − rs − !C` | NZCV |
| 4 | `AND` | `rd ← rd & rs` | NZ |
| 5 | `OR` | `rd ← rd \| rs` | NZ |
| 6 | `XOR` | `rd ← rd ^ rs` | NZ |
| 7 | `BIC` | `rd ← rd & ~rs` | NZ |
| 8 | `MOV` | `rd ← rs` | NZ |
| 9 | `CMP` | `rd − rs`, flags only | NZCV |
| A | `TST` | `rd & rs`, flags only | NZ |
| B–F | – | traps | |

### Unary functions (op 2): `rd ← f(rs)`

| f | Name | Operation | Flags |
|---|---|---|---|
| 0 | `NOT` | `~rs` | NZ |
| 1 | `NEG` | `0 − rs` | NZCV |
| 2 | `INC` | `rs + 1` | NZCV |
| 3 | `DEC` | `rs − 1` | NZCV |
| 4 | `SHL` | `rs << 1`, C ← bit 15 | NZCV (V = sign changed) |
| 5 | `SHR` | logical `rs >> 1`, C ← bit 0 | NZC, V ← 0 |
| 6 | `ASR` | arithmetic `rs >> 1`, C ← bit 0 | NZC, V ← 0 |
| 7 | `RLC` | rotate left through carry | NZCV |
| 8 | `RRC` | rotate right through carry | NZC, V ← 0 |
| 9 | `SWAB` | swap bytes | NZ |
| A | `SXT` | sign-extend low byte | NZ |
| B | `ZXT` | zero-extend low byte | NZ |
| C–F | – | traps | |

### System group (op 0)

| f | Name | Operation |
|---|---|---|
| 0 | `HALT` | Stop. With interrupts enabled, wait for an interrupt instead (see below). `0000` is `HALT`. |
| 1 | `NOP` | |
| 2 | `JMP rs` | `PC ← rs` |
| 3 | `CALL rs` | push `PC`; `PC ← rs` |
| 4 | `RET` | pop `PC` |
| 5 | `PUSH rs` | `sp ← sp − 2; [sp] ← rs` (pushes the old value of `sp` for `PUSH sp`) |
| 6 | `POP rd` | `rd ← [sp]; sp ← sp + 2`; sets NZ |
| 7 | `RTI` | pop flags; pop `PC` |
| 8 | `EI` | `I ← 1` |
| 9 | `DI` | `I ← 0` |
| A | `MFF rd` | `rd ← flags` (flags unchanged) |
| B | `MTF rs` | `flags ← rs` (including `I`) |
| C | `SWI` | software trap |
| D–F | – | traps |

### Conditions

ARM's encoding: bits 3–1 choose a test, bit 0 inverts it. `C` is a carry for
additions and "no borrow" for subtractions, so after `CMP a, b`, `HS` means
`a ≥ b` unsigned.

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

### Flag rules in one sentence

Arithmetic sets NZCV, logic and data moves (including loads, `MOV`, `MVI` and
`POP`) set N and Z and leave C and V alone, and stores, `LEA`, `MFF`, jumps,
branches and calls don't touch the flags.

## Stack, interrupts and traps

The stack grows down and `sp` points at the last item pushed.

| Event | Vector |
|---|---|
| Reset | `0000` (also `I ← 0`) |
| IRQ (level-triggered, when `I = 1`) | `0004` |
| Trap (`SWI`, reserved opcodes and functions) | `0008` |

Entering an interrupt or trap pushes `PC` (the next instruction), then the
flags word, clears `I` and jumps to the vector. `RTI` undoes it. The flags word
is `I N Z C V` in bits 4–0. `SWI` and reserved instructions share the trap
vector; a handler can tell them apart by the instruction before the saved PC.
A reserved opcode traps after its first word, even in the two-word groups.

When interrupts are recognised:

- Between instructions only, and only if `I` was set before the instruction's
  last cycle. So no interrupt can be taken right after `EI`: the instruction
  after `EI` always runs first. This makes `EI` followed by `HALT` a race-free
  way to sleep.
- One can still be taken right after `DI` (it was enabled when `DI` started).
  The handler then returns with `I = 0`, so `DI` still protects what follows.
- Right after `RTI`, if the restored flags enable interrupts and one is
  pending.
- `HALT` with `I = 1` waits for an interrupt and continues after the `HALT`
  when the handler returns. If one is already pending it's taken at once.
  `HALT` with `I = 0` stops the machine for good.

## I/O page

| Address | Read | Write |
|---|---|---|
| `FF00` | console input byte, or `FFFF` if no byte is waiting | console output (low byte) |
| `FF02` | bit 0: a byte is waiting; bit 1: end of input | – |
| `FF04` | – | timer period in clock cycles (0 = off) |
| `FF06` | timer flag (drives IRQ) | acknowledge timer |
| `FF08` | cycle counter bits 15–0 (latches the high half) | – |
| `FF0A` | latched cycle counter bits 31–16 | – |

Byte writes to the I/O page present the byte as the low byte of the register
at the even address. On real hardware `FFFF` from `FF00` only means "nothing
yet"; the simulators supply all input up front, so there they also set the
end-of-input bit once it's used up.

## Assembler syntax

```
label:  ADD   r1, r2          ; register-register
        ADD   r1, #1000       ; immediate: picks ADDI if it fits in 8 bits
        MOV   r1, #msg        ; picks MVI or the two-word form
        LD    r1, [r2 + 4]    ; picks the 1-word form if the offset fits
        LDB   r3, [buffer]    ; absolute
        LDB   r3, [table + r2]; static array indexed by a register (long form)
        BNE   .loop           ; becomes JNE (two words, same cycles) if out of range
        BSR   helper          ; becomes CALL if out of range
.loop:                        ; local label, scoped to the last global label
        .word 1, 2, label
        .byte 'a', 0x0D, "text"
        .asciz "hello\n"
        .space 32             ; zero-filled bytes
        .align 2
        .org  0x0100
size = end - start            ; constants (also .equ)
        .include "lib/print.s"
```

Mnemonics and registers are case-insensitive; `sp` is `r15`. `LI rd, x` is an
alias for `MOV rd, #x`. Expressions support `+ - * / % & | ^ << >> ~`,
parentheses, `'c'` characters, `$` (current address), `lo()`/`hi()` (the low
and high byte) and `lo16()`/`hi16()` (the two halves of a 32-bit constant).
There's no register + register addressing mode; `[label + reg]` and
`[reg + offset]` are the same mode (a 16-bit displacement plus a base
register).

## Software conventions

These are conventions for the programs in `studies/v0_hw/programs/`, not hardware rules.

- Arguments go in `r1`–`r4`, results come back in `r1` (and `r2` for a second
  value or the high half of a 32-bit result; a third result goes in `r3`).
- `r1`–`r7` are scratch (caller-saved). `r8`–`r14` must be preserved by the
  callee. `sp` is `r15`.
- Calls use `CALL`/`BSR` and `RET`; the return address is on the stack.
- Programs start with `.include "lib/start.s"`, which puts the vectors at
  `0000`/`0004`/`0008`, sets `sp` to `FF00` and calls `main`. When `main`
  returns, the machine halts.
