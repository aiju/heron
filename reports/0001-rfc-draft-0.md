---
number: 1
type: rfc
title: Draft 0, a 16-bit ISA and its hardware
status: obsolete
date: 2026-10-11
context:
  studies: [v0_hw]
  commit: e494b0c
superseded-by: 4
---

# RFC 0001: Draft 0, a 16-bit ISA and its hardware

> **Draft 0 is superseded.** This is the 16-bit first draft, kept as a record. Draft 1 replaced it: see [RFC 0004](0004-rfc-draft-1-isa.md) and [the draft 1b hardware](0012-report-draft-1b-hardware.md).

[Part I](#part-i-the-instruction-set) is the instruction set,
[Part II](#part-ii-the-hardware) a 98-chip implementation of it, and
[Part III](#part-iii-evaluation) what both showed.

## Part I: The instruction set

### 1. Overview

A 16-bit load/store instruction set designed to be built from 7400-series
logic. Every instruction word is four hex digits, and fields never move:
the destination register is always the 2nd digit and the source register
always the 3rd. That makes the register fields wire straight to the register
file and lets you read instructions off front-panel lights.

### 2. Machine state

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

### 3. Encoding

<!-- bits
word 16
  15-12 op
  11-8  a
  7-4   b
  3-0   c
  under 7-0 ii
-->
![An instruction's first word](0001-rfc-draft-0/encoding.svg)

- a = rd (destination) or cc (condition)
- b = rs (source or base register)
- c = fn (function) or o (4-bit offset)
- ii = bits 7..0, a signed 8-bit immediate

| op | Words | Layout | Instructions |
|---|---|---|---|
| 0 | 1 | `0 d s f` | System group ([3.3](#33-system-group-op-0)) |
| 1 | 1 | `1 d s f` | `rd ← rd ⊕ rs` ([3.1](#31-alu-functions-op-1-and-op-8)) |
| 2 | 1 | `2 d s f` | `rd ← f(rs)` ([3.2](#32-unary-functions-op-2-rd--frs)) |
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

#### 3.1 ALU functions (op 1 and op 8)

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

#### 3.2 Unary functions (op 2): `rd ← f(rs)`

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

#### 3.3 System group (op 0)

| f | Name | Operation |
|---|---|---|
| 0 | `HALT` | Stop. With interrupts enabled, wait for an interrupt instead ([4](#4-stack-interrupts-and-traps)). `0000` is `HALT`. |
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

#### 3.4 Conditions

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

#### 3.5 Flag rules in one sentence

Arithmetic sets NZCV, logic and data moves (including loads, `MOV`, `MVI` and
`POP`) set N and Z and leave C and V alone, and stores, `LEA`, `MFF`, jumps,
branches and calls don't touch the flags.

### 4. Stack, interrupts and traps

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

### 5. I/O page

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

### 6. Assembler syntax

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

### 7. Software conventions

These are conventions for the programs in `studies/v0_hw/programs/`, not hardware rules.

- Arguments go in `r1`–`r4`, results come back in `r1` (and `r2` for a second
  value or the high half of a 32-bit result; a third result goes in `r3`).
- `r1`–`r7` are scratch (caller-saved). `r8`–`r14` must be preserved by the
  callee. `sp` is `r15`.
- Calls use `CALL`/`BSR` and `RET`; the return address is on the stack.
- Programs start with `.include "lib/start.s"`, which puts the vectors at
  `0000`/`0004`/`0008`, sets `sp` to `FF00` and calls `main`. When `main`
  returns, the machine halts.

## Part II: The hardware

### 8. Overview

This is a first-cut, buildable implementation of
[ISA draft 0](#part-i-the-instruction-set): 98 chips including memory,
microcoded, one bus cycle per clock. Its main job at this stage is to put
real numbers on the ISA: how many clock cycles each instruction needs and
how fast the clock can go. The netlist is in
[`cpu.py`](../studies/v0_hw/cpu.py), the microcode in
[`microcode.py`](../studies/v0_hw/microcode.py) (listed cycle by cycle in
[microcode.md](../studies/v0_hw/microcode.md)), and measured performance is
in [Part III](#18-performance).

### 9. At a glance

| | |
|---|---|
| Chips | 98: 86 logic, 6 microcode flash, 4 register-file SRAM, 2 RAM |
| Logic family | 74HCT, with 74LS181 ALUs and a 74S182 lookahead (variants: 74F181/F182, 74ACT) |
| Control | 48-bit microinstructions in 6 × SST39SF010A, up to 16 steps per instruction |
| Register file | 16 × 16 bits, two copies in fast SRAM so both ALU operands read at once |
| Cycles per instruction | 1 to 4 for normal instructions ([13](#13-cycles-per-instruction)), 7 for traps and interrupt entry |
| Clock (guaranteed, worst-case datasheet delays) | 2.06 MHz (HCT + LS181) to 3.72 MHz (ACT + F181) |
| Clock (typical delays) | 3.4 to 5.0 MHz |

### 10. Block diagram

<!-- blocks
# the control
text step "STEP (163)" at 0,3.5
box rom "microcode" "6 × flash" right of step gap 4 height=7
text addr "ROM address: step, IR[15:12], IR[3:0]," "irq pending, link, mode bits" right of rom gap 4 align=top
text ctl "48 control lines" "(bus enables, register loads, ALU function …)" right of rom gap 4 align=bottom
step -> rom
addr -> rom
rom -> ctl

# the datapath
box rfa "RF copy A" "2 × SRAM" at 0,13
box rfb "RF copy B" "2 × SRAM" below rfa gap 5
box alu "ALU" "4 × 74LS181" "+ 74S182" right of rfa gap 9 align=top height=15
box mux "result mux" "lanes, swap, shift right," "sign/zero ext" "8 × 74HCT153" right of alu gap 5 align=top
bus res "RES" from 51,12 to 51,25
text r "R (377) → A bus, B bus" at 53,13
text mar "MAR (via mux) → address mux" at 53,16
text pc "PC (161 × 4, load)" at 53,19
text flags "flags (N Z C V)" at 53,22
text db "D bus (541 × 2)" at 53,25
text a1 "PC" left of alu gap 2 dy=-2.5
text a2 "R" left of alu gap 2 dy=-1
text b1 "IMM" left of alu gap 2 dy=2
text mem "MEM (D bus)" below alu gap 2
text "T, R, flags also drive the B bus" right of mem gap 2
rfa -> alu "A bus"
rfb -> alu "B bus"
a1 -> alu
a2 -> alu
b1 -> alu
mem -> alu
alu -> mux "F"
mux -> res
res -> r
res -> mar
res -> pc
res -> flags
res -> db
-->
![The control and the datapath](0001-rfc-draft-0/block-diagram.svg)

- address mux (PC or MAR) → RAM (2 × 32K × 8), I/O page FF00–FFFF
- D bus ↔ RAM, I/O; D bus → IR (377 × 2), T (377 × 2), B bus (541 × 2)
- PC → D bus (for pushing return addresses), PC → A bus (for branches)

### 11. Datapath

**Buses.** The ALU has two input buses. The A bus is driven by register-file
copy A, the PC or R. The B bus is driven by register-file copy B, the
immediate unit, memory data, T, R or the flags (a 74HCT138 decodes the B
source). The ALU output F goes through the result multiplexer onto the result
bus RES, which can load R, MAR, PC and the flags, or drive the memory data bus.

**Register file.** Two copies of the 16 registers, each in a pair of
32K × 8 SRAMs using only four address lines. Copy A is addressed by
`d`/`s`/`sp`/`zero` (a 74HCT153 per two bits) and feeds the A bus; copy B
likewise feeds the B bus. Writes go to both copies at once from R, during
the write window of the clock. `r0` is never written (a 4-input OR of the
address gates the write strobe) except by the reset sequence, which zeroes
it, so it always reads as 0.

**R** (2 × 74HCT377) holds an ALU result until it's written back.
**T** (2 × 74HCT377) catches memory data that can't go straight into the ALU,
e.g. the target of `CALL addr` while the return address is being pushed.
**MAR** (2 × 74HCT377 behind 4 × 74HCT157) loads from the result bus or
straight from the A bus, so `RET` and `POP` can use `sp` as the address while
the ALU computes `sp + 2`. The **PC** is four 74HCT161 counters holding
bits 15–1 (bit 0 is always 0); any memory read at the PC increments it.

**Immediate unit.** A 4:1 mux chooses the low nibble (IR[3:0] or the
constants 1, 2, 4); AND gates add IR[7:4] and the sign for 8-bit immediates;
a 2:1 mux shifts everything left one place for word offsets, branch offsets
and the constants 2, 4 and 8 (stack adjust, IRQ and trap vectors).

**ALU.** Four 74LS181 with a 74S182 carry lookahead. Right shifts, byte swap,
sign/zero extension and byte-lane selection happen after the ALU in the
result multiplexer (8 × 74HCT153): low byte from F lo, F hi or F >> 1; high
byte from F hi, F lo, F >> 1 or the sign of F lo, or forced to zero. Left
shifts use the 74181 (`A + A`). Byte loads pick the lane with MAR bit 0;
byte stores put the byte on both lanes and write only one RAM chip.

**Flags.** N, Z, C and V live in a 74HCT175 (Z stored inverted to save an
inverter on the critical path), I in a 74HCT74. Each has a 4:1 mux in front:
hold, new value, value from the result bus (for `MTF`/`RTI`), or, for C and V,
the right-shift case (C ← bit shifted out, V ← 0). Zero detection is two
74HCT688 comparators. Overflow uses three XOR gates and works out whether the
74181 is adding or subtracting from its S0 input.

**Branch condition.** ARM's condition encoding pays off here: a 74HCT151
picks one of Z, C, N, V, C·!Z, N=V, !Z·(N=V) or 1 with IR[11:9], and an XOR
with IR[8] inverts it. The condition gates the PC load, so a conditional
branch costs the same cycles taken or not, and the condition logic stays
out of the microcode address path.

**Memory and I/O.** Two 32K × 8 SRAMs make 64 KB, little-endian, with word
accesses ignoring address bit 0. The I/O page is decoded from MAR (the PC
never points there), which keeps the decoder off the RAM access path. In the
simulator the I/O devices (console, timer, cycle counter) are a test fixture
rather than modelled chips.

### 12. Control

**Microcode address** (17 bits): step counter (74HCT163), opcode IR[15:12],
function nibble IR[3:0], interrupt pending, the *link* predecode bit, and two
mode bits (interrupt entry, reset). The link bit, `IR[11:8] == 1111`
(`BSR`/`CALL`), is computed from the data bus during fetch and registered
alongside the IR, so no decode logic sits between the IR and the ROMs.

**Control word**: 48 bits in six ROMs, one ROM per area of the board:

| ROM | Signals |
|---|---|
| 0 | A-bus source (RF, PC, R), B-bus source (3-bit code), result→D bus, PC→D bus |
| 1 | RF-A and RF-B address select, RF write, memory read, memory write, END |
| 2 | 74181 S3–S0 and M, carry-in/shift-in select, HALT |
| 3 | result mux low/high byte select, high byte zero, byte mode, 8-bit immediate, ×2 |
| 4 | flag updates (N/Z, C/V, load C/V, load flags, I write and value), immediate nibble |
| 5 | load R, MAR (+ source), T, IR; address source; load PC, gate PC load by condition |

Three signals that seem to need ROM bits are derived instead: PC increment
(any read at the PC), the `r0` write override (reset mode) and the
add/subtract choice for the V logic (74181 S0).

**Sequencing.** The fetch of the next instruction (`IR ← [PC]`, `PC += 2`)
rides along in the last step of the current instruction whenever that step
doesn't need the memory bus. That's why register-register ALU ops take 2
cycles (compute, then write back while fetching) and compare instructions only
1. At that last step the microcode looks at the registered interrupt-pending
bit: if it's set, it skips the fetch, and END switches the next sequence to
interrupt entry. The pending bit is registered from `IRQ & I_next` (the value
the I flag will have after the clock edge). Otherwise a just-finished
interrupt entry, which clears I in its second-to-last step, would see a stale
pending bit and immediately enter again.

**Clocking.** All registers clock on one rising edge. A second signal, the
*write window*, is high from 1/2 to 7/8 of the period; register-file and RAM
write strobes are the write enable ANDed with it, so addresses settle before
the strobe and data is held past it. In a build both would come from an
oscillator at 8× the CPU clock and a Johnson counter.

**Reset** holds the step counter and PC at 0 and forces reset mode. The reset
sequence zeroes `r0` and fetches the instruction at 0000.

### 13. Cycles per instruction

From the microcode (and cross-checked by the chip-level simulator):

| Cycles | Instructions |
|---|---|
| 1 | `CMP`, `TST`, `CMPI`, `NOP`, `EI`, `DI`, `MTF` |
| 2 | ALU register-register, unary, `MVI`, `ADDI`, ALU `#imm16`, `LEA`, `Bcc` (taken or not), `Jcc`/`JMP addr`, `JMP rs`, `MFF` |
| 3 | `LD`/`ST`/`LDB`/`STB` (both forms), `BSR`, `CALL`, `CALL rs`, `RET`, `PUSH` |
| 4 | `POP` |
| 7 | `RTI`, `SWI`, traps, interrupt entry |

### 14. Timing

Delays come from manufacturer datasheets (collected in
[`infra/hw/datasheets`](../infra/hw/datasheets), mapped by
[`build_timing.py`](../infra/hw/build_timing.py)). Two corners: *max* is the
guaranteed worst case (−40…85 °C, 4.5 V, 50 pF for HCT/ACT); *typ* is the
25 °C typical. Memories only have guaranteed figures, so they use them in
both corners.

Two independent analyses:

- **Static timing analysis** ([`sta.py`](../infra/hw/sta.py)) runs once per
  distinct microinstruction, with the control lines set to that
  microinstruction's values. Known values cut paths that can't happen: a
  disabled bus driver, an unselected mux input, a gate with a controlling
  input. Data stays unknown, so the result covers every data value, including
  full carry propagation.
- **Event-driven simulation** (the Go simulator in [`hwsim`](../infra/hwsim))
  runs real programs with every chip modelled at the pin level, checks setup
  and hold times, SRAM write timing and bus contention, and compares the final
  state with the instruction-level simulator. A binary search on the clock
  period finds where programs stop working.

The critical path, for the first step of `ADD rd, #imm16` (and the other ALU
ops with a 16-bit immediate), worst-case delays, HCT + LS181:

```
   0.0  clock edge
  49.0  step counter output             74HCT163 CLK->Q
 104.0  microcode out (address source)  SST39SF010A tACC
 152.0  RAM chip enable                 74HCT04 + 74HCT02 (I/O decode)
 207.0  data bus                        AS6C62256 tACE
 242.0  B bus                           74HCT541
 282.0  carry into bits 8-11            74LS181 P, 74S182
 308.0  F8                              74LS181 CN->F
 351.0  result bus                      74HCT153
 423.0  "result is zero"                74HCT688 + 74HCT32
 466.0  Z flag next value               74HCT153
 486.0  setup of the flag flip-flop     74HCT175
```

Almost every slow microinstruction ends at the Z flag: ALU, then result mux,
then zero detect, then flag mux. Because loads and moves set N and Z in this
ISA, even loads pay for it (`LD` second step: 458 ns). Taking the Z flag out
entirely would only gain about 10% here, because the same two-word-immediate
path is nearly as long without it.

### 15. Known issues and what a second iteration would change

- **Bus contention.** The 74HCT541's worst-case disable time (44 ns) is much
  longer than the register-file SRAM's output enable (7 ns), so when the B bus
  switches from a buffer to the SRAM, both drive it for up to 37 ns (67 ns for
  the immediate unit's high byte, whose enable goes through one more gate).
  The simulator reports these on every run. It works logically, but it's a
  current spike and ground-bounce source on a real board. Fixes: a
  break-before-make dead time at the start of each cycle (costs speed), ACT
  buffers (8 ns disable), or putting the register-file SRAMs behind buffers too.
- **Microcode in the critical path.** Every path starts with ~104 ns of step
  counter plus ROM access. A pipelined microinstruction register would remove
  most of it. It needs the next microcode address one cycle early, which
  usually means decoding the opcode from the data bus during fetch.
- **Flags from R.** Computing N/Z from R in the write-back cycle instead of
  from the ALU output would shorten most microinstructions; compare
  instructions would then need an extra cycle.
- **Hold times** aren't analysed: datasheets give no minimum delays for HCT,
  and the simulator uses one delay per arc.
- **Clock distribution** is ideal in the model (no skew). A real board would
  need a clock tree (e.g. a 74AC244 fan-out) and some margin.
- **Microcode ROM outputs glitch** while the address changes. The write
  strobes are qualified by the write window, so glitches can't cause writes,
  but they do add to bus contention.
- **Parts.** 74181/74182 are only available as new-old-stock (TI still makes
  the military SN54LS181J/SN54S182J). No fast 5 V 32K × 8 SRAM is made in DIP
  any more (AS7C256A in SOJ on an adapter, or old CY7C199/IDT71256 DIPs). The
  55 ns SST39SF010A is PLCC only. There's no 74ACT30 or 74ACT688, so the ACT
  variant uses HCT for those.

### 16. Verifying the hardware model

`heron v0_hw hw run PROG.s` runs a program on the chip-level simulator and
compares the console output, all registers (both register-file copies), the
flags, the PC, all of RAM, the cycle count and the cycle-by-cycle sequence of
instruction fetches with the instruction-level simulator. `exercise.s`
runs every instruction class, every condition code against every flag
combination, every trap and both forms of every load and store, and matches
cycle-exactly. Programs that use interrupts are compared on results only,
since IRQ sampling can differ by a cycle or two.

## Part III: Evaluation

**Short version:** draft 0 is a sound base. Programs came out right first
time, the encoding made the hardware unusually simple, and a 98-chip
implementation runs every test program at 2 MHz with worst-case parts
(3.4 MHz typical, up to 5 MHz with faster logic). The one big problem is
the missing multiply and divide, which eats 60–80% of the time in any
program that does arithmetic. After that come register save/restore cost
and `INC`/`DEC` clobbering the carry. Most of the other changes I expected
to want (three-operand ALU, wider branch offsets, more addressing modes)
turned out to be worth little on the evidence.

### 17. What was built

1. **Assembler and instruction-level simulator** for
   [draft 0](#part-i-the-instruction-set), with cycle counts taken from the
   microcode, so they're exact for the hardware below.
2. **16 programs plus a library**: arithmetic, strings, sieve, sorting,
   recursion, CRC, Mandelbrot, Life, 8 queens, a binary tree, bignum
   factorial, an RPN calculator, a memory monitor, interrupts and matrix
   multiply. A separate agent wrote them, working only from the spec, so
   they're a fresh programmer's code rather than mine. Expected outputs come
   from independent Python versions.
3. **[Programming notes](0002-report-draft-0-programming-notes.md)**: a program-by-program log of
   what was easy, what went wrong and why.
4. **[A 7400-series implementation](#part-ii-the-hardware)**: 98 chips,
   74HCT logic with 74LS181 ALUs, a 48-bit microcode in six flash ROMs.
5. **A chip-level timing simulator** (Go, event-driven, datasheet pin-to-pin
   delays, setup/hold, SRAM write timing, bus contention). All 16 programs run
   on it at the guaranteed clock and match the instruction-level simulator
   (15 cycle-exactly; the interrupt program in results).
6. **[Performance numbers](0001-rfc-draft-0/performance.md)** from static timing analysis,
   simulation sweeps and the program suite, plus ISA usage statistics.

### 18. Performance

| | 74HCT + 74LS181 | 74ACT + 74F181 |
|---|---:|---:|
| Clock, guaranteed (worst-case datasheet delays) | 2.06 MHz | 3.72 MHz |
| Clock, typical (25 °C typical delays) | 3.37 MHz | 5.00 MHz |
| Average cycles per instruction (whole suite) | 2.13 | 2.13 |
| Instructions per second, guaranteed / typical | 0.97 / 1.58 million | 1.75 / 2.35 million |
| Whole suite (4.9M cycles), guaranteed / typical | 2.4 s / 1.4 s | 1.3 s / 1.0 s |

Typical instructions take 2 cycles. That's compute plus write-back, with the
next fetch overlapped into the write-back. Compares take 1, loads, stores,
calls and returns 3, `POP` 4, and interrupt entry and `RTI` 7. Per program
numbers are in [performance.md](0001-rfc-draft-0/performance.md).

**What sets the clock** is the first step of the ALU-with-16-bit-immediate
instructions: read the extension word from RAM, through the 74181s and their
carry lookahead, through the result multiplexer, zero-detect, into the Z
flag. Almost every slow microinstruction ends at the Z flag. Two ISA choices
put work there: two-word immediates are fed straight from memory into the
ALU, and loads and moves set N and Z.

**What sets the cycle count** is mostly the microarchitecture: the register
file is ordinary SRAM, so writing a result back takes its own cycle. A
design that writes back in the same cycle would bring the average CPI from
2.1 to about 1.4, but would need a slower clock or much faster register-file
parts.

### 19. Ease of programming

From the [programming notes](0002-report-draft-0-programming-notes.md), plus what I ran into
writing the hardware test programs:

- **Correct code was easy.** Nearly every program produced correct output the
  first time it assembled. Over the whole suite the programmer hit 4 assembler
  errors (3 of them `BSR` out of range), 1 output-format bug and 1 carry-flag
  bug, caught on review. The regular encoding, ARM's full set of conditions,
  `r0` reading as zero, and unary ops with a separate source register all
  earned explicit praise.
- **Fast code was hard where arithmetic is involved.** There's no multiply or
  divide, and shifts go one bit at a time, so the multiply loop, the
  fixed-point format in `mandel` and the decimal printer were all designed
  around avoiding them.
- **Flags are a double-edged sword.** Loads setting Z removes most compare
  instructions in string loops. But `INC`, `DEC` and `ADDI` set the carry, so
  a loop counter can't run alongside a carry chain. This shaped the multiply
  routine and caused the only real flag bug.
- **The tooling mattered as much as the ISA.** Branch-range errors were an
  assembler problem: long forms cost no extra cycles, so the assembler should
  just pick them. It now does.

### 20. Findings, ranked by measured cost

| # | Finding | Evidence | Fix | Cost of the fix |
|---|---|---|---|---|
| 1 | **No multiply or divide** | 61–80% of cycles in `mandel`, `matmul`, `bignum`, `interrupts`; 39% of all cycles in the suite are in `umul16`. A multiply costs 72–157 cycles, a 32/16 divide ~220 | `MUL`/`DIV` in the reserved op B | ~4 chips for one bit per cycle (below) |
| 2 | **Register save/restore one at a time** | `PUSH`/`POP` are 34% of `queens`' cycles and 21% of `fib`'s | `SAVE n` / `RESTORE n` in free system functions | A register-number counter for the register file address, ~2–3 chips |
| 3 | **`INC`/`DEC`/`ADDI` overwrite the carry** | Forced the multiply loop's shape; caused the matmul flag bug | `INC`/`DEC` set only N and Z (as on the PDP-11) | Microcode only |
| 4 | **`BSR` reaches only ±256 bytes** | 3 of 4 assembler errors; a library call is almost never in range | Assembler relaxes `Bcc`→`Jcc`, `BSR`→`CALL` (done) | None. 95% of executed branches fit in a 6-bit offset, so no need to widen it |
| 5 | **Short load/store offsets are 4 bits, unsigned** | 30% of executed loads/stores used the long form for an offset under 128, almost all in `life` and `matmul` | Leave as is | Long forms cost a word, not a cycle |
| 6 | **Two-operand ALU** | `MOV` + op pairs are 1% of executed instructions overall (12% in `queens`) | Leave as is | A three-operand form doesn't fit the encoding and wouldn't pay |
| 7 | **No short immediates for `AND`/`OR`/`XOR`** | 6 static `AND #imm16` that would fit in 8 bits | Low priority | Opcode space |
| 8 | **`CMP` with a constant outside −128…127 takes 2 cycles** | 1.7% of `mandel`'s cycles | Low priority | Inherent in two-word instructions here |
| 9 | **32-bit compare needs two branches** | `SBC` sets Z from the high half only | Leave as is | – |
| 10 | **`SWI` and reserved instructions share a vector** | Trap handlers decode `[PC − 2]` | Optional separate `SWI` vector | One microcode constant |

The register count is right: programs used 9–15 of the 15 available, and
`mandel`'s inner loop needed every one. Byte addressing cost about three
gates in hardware and caused no trouble in software. Loads setting flags is
worth keeping for programming convenience, though it adds to the critical
path.

### 21. What the hardware says about the encoding

Choices that made the hardware simple:

- **Fixed nibble fields.** The register fields go straight from the
  instruction register to the register file address multiplexers, and the
  microcode ROMs are addressed by the opcode and function nibbles directly.
  There's no decode logic at all between the IR and the datapath.
- **ARM-style conditions** cost one 74HCT151 and one XOR gate, and gating the
  PC load with the condition keeps it off the microcode address path.
- **`r0` reads as zero** for four OR gates and one reset microinstruction. It
  also gives `NEG` (0 − rs) and absolute addressing for free.
- **Two-word instructions** are cheap in microcode, but `ALU rd, #imm16` is the
  slowest microinstruction in the machine.

Choices that cost hardware or cycles:

- **The full-descending stack** (`PUSH` = pre-decrement, `POP` =
  post-increment) needs both `sp` and `sp + 2` in one cycle for `POP`/`RET`, so
  MAR got a second input (4 chips). `POP` still takes 4 cycles, because it
  writes two registers.
- **Pushing return addresses** needed a path from the PC to the data bus
  (2 chips) to keep `CALL` at 3 cycles.
- **The interrupt entry and `RTI`** are 7 cycles each: two pushes or pops,
  each with a register-file write-back.

### 22. Recommendations for draft 1

1. **Add `MUL` and `DIV` in op B, with a little datapath help.** A
   multiplier in a 16-bit shift register (two 74HCT299) plus a "conditional
   add" (two AND gates forcing the 74181 to pass A when the multiplier bit is
   0) lets each bit take one cycle, with the partial product held in R. That
   makes a 16×16→32 multiply about 20 cycles and a 32/16 divide about 40.
   The step counter needs a fifth bit (the spare ROM address line). Projected
   speed-ups:

   | Program | Now | MUL 20 / DIV 40 cycles | MUL 70 / DIV 140 cycles (microcode only) |
   |---|---:|---:|---:|
   | matmul | 102k cycles | 3.3× faster | 1.8× faster |
   | bignum | 147k | 2.9× | 1.3× |
   | mandel | 2.48M | 2.5× | 1.2× |
   | interrupts | 201k | 2.1× | 1.4× |
   | arith | 91k | 1.2× | 1.1× |

   The last column is why it's worth the extra chips: a multiply done as a
   microcode loop over the existing datapath (~4 cycles per bit) barely beats
   the software routine, which stops early for small operands.
2. **Make `INC` and `DEC` leave C and V alone.** This is free (microcode
   only), and `ADDI` remains for when the carry is wanted.
3. **Add `SAVE n` / `RESTORE n`** (push or pop r8 up to r(7+n)), taking about
   n+2 cycles instead of 3n and 4n. That's −20% on `queens` and −9% on `fib`,
   and it makes interrupt handlers cheaper. It needs a counter as a register
   file address source.
4. **Keep the rest of the encoding.** The nibble fields, conditions, `r0`,
   16 registers, byte addressing, two-word forms and the interrupt model all
   held up.
5. **Not recommended on this evidence:** a three-operand ALU, wider branch
   offsets, register + register addressing, auto-increment. Auto-increment
   pairs were 0.1% of executed instructions; the others are covered above.

These would use op B and two of the three free system functions, and leave
the unary group's four free slots for later (e.g. multi-bit shifts).

### 23. Hardware issues to fix regardless of the ISA

From [Part II](#15-known-issues-and-what-a-second-iteration-would-change):
bus contention when the B bus changes source (up to 67 ns at worst-case
delays), ~100 ns of microcode access at the start of every cycle (a
pipelined microinstruction register would remove most of it), and some
parts are only available as new-old-stock (74181/74182) or not in DIP (fast
SRAM, the 55 ns flash).

### 24. Questions for the next round

These have since been answered or carried into
[RFC 0005](0005-rfc-ideas-direction.md#4-open-questions).

- How much is speed worth in chips? The multiply datapath is about 4 chips;
  a pipelined microcode register about 6 and a redesign of the fetch path.
- 74HCT (safe, in production) or 74ACT (1.8× faster, harder on breadboards,
  some parts missing)?
- Is the build going to be breadboard, wire-wrap or PCB? That decides how much
  bus contention and ground bounce matter.
