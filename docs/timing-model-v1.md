# Draft 1 timing model

There's no hardware design for draft 1 yet, so its cycle counts are
estimates from a model of a microcoded machine like the draft 0 one. The
model lives in `tmc/timing32.py`. The simulator records what every executed
instruction did, and the model turns that into cycles for six machine
configurations. All six come out of one simulation run.

## The configurations

| | 16-bit datapath (D16) | 32-bit datapath (D32) |
|---|---|---|
| **separate fetch** | `D16-separate` | `D32-separate` |
| **overlapped fetch** | `D16-overlap` | `D32-overlap` |
| **wide fetch** | `D16-wide` | `D32-wide` |

**Datapath width.** With a 16-bit ALU, every 32-bit ALU operation takes two
cycles, one per half. The register file is 32 bits wide either way: it reads
or writes a whole register in one cycle. It takes 4 byte-wide SRAMs per copy
in both cases.

Address arithmetic (base + small displacement, `PC` + branch offset,
`sp ± 4`) is a special case on D16. The low halves are added first, and the
upper half only needs a second cycle when it actually changes, like the
6502's page-crossing cycle. The simulator knows the addresses, so it charges
that second cycle exactly when it happens.

**Fetch style.**

- `separate`: every instruction starts with its own opcode fetch cycle. The
  bus is 16 bits.
- `overlap`: the next opcode is fetched during the instruction's last cycle
  if the bus is free then. This is what the draft 0 hardware does. The bus is
  16 bits.
- `wide`: a 32-bit bus with a two-parcel prefetch buffer:
  - Each fetch brings in an aligned 32-bit word, and parcels already in the
    buffer cost nothing.
  - Because the buffer, not the instruction register, receives the fetch, the
    next fetch can happen in any cycle where the bus is idle.
  - The 32-bit bus also makes word loads and stores single bus cycles.

  This is the most expensive option in hardware: 32-bit memory, the buffer,
  and steering for parcels at odd positions.

## How an instruction is costed

An instruction is made of a few micro-operations. Each one uses some of three
resources for a number of cycles:

| Resource | Used by |
|---|---|
| `A` (ALU) | arithmetic, address arithmetic |
| `B` (bus) | instruction fetches, loads and stores |
| `R` (register file port) | one read of up to two registers, *or* one write, per cycle |

A list scheduler places each micro-operation at the earliest cycle its inputs
and resources allow, the way a microcode writer would pack them. The rules
on top of that:

1. **Extension parcels come first.** With a 16-bit bus each extension parcel
   is a bus cycle of its own, and nothing uses it in the same cycle. (Draft 0
   did use it in the same cycle, and that was its critical path.) With the
   wide fetch, parcels already in the buffer are free and are used straight
   from the buffer.
2. **The result write-back is a cycle of its own.** The register file is
   ordinary SRAM, so it can't be read and written in the same cycle. This is
   the same reason draft 0 instructions mostly take 2 cycles.
3. **Memory needs the address in MAR first.**
   - `[register]` loads MAR straight from the register file (1 cycle).
   - `[register + disp]` and PC-relative addresses take an ALU cycle (or two
     on D16 when the upper half changes).
   - An absolute address goes from the immediate latch into MAR (1 cycle).
   - Indexed addresses take two adds. The second adds a whole 32-bit
     index register, so it is a full add: two cycles on D16, where the
     page-crossing shortcut doesn't apply.
   - Auto-increment loads MAR from the register and computes `R + size` in
     the same cycle. The register is written back while the bus is busy, as
     draft 0 does for `sp` in `RET`.
4. **Loads set flags at no cost.** Zero detect sits on the result bus.
5. **Stores read their data during the address cycle.** The register file
   has two read ports (two copies, as in draft 0).
6. **Taken branches and jumps fetch from the new `PC` after it's known**, so
   that fetch is never overlapped with computing it. A branch that isn't taken
   costs one cycle; the condition is known before the cycle starts.
7. **Calls** push the return address and update `sp` alongside the push.
   **Returns** read the return address while incrementing `sp`.
8. **`SAVE`/`RESTORE n`** stream registers over the bus at one per bus word,
   with the register-file reads or writes overlapped.
9. **Multiply** is a shift-and-add loop, one 32-bit add per bit of the
   multiplier (the second operand), stopping when the rest of it is zero. **Divide** is 32
   restoring steps. Signed versions take 2 more cycles. Each step is one cycle
   on D32 and two on D16.
10. **Shifts by `n`** take one step per 16, then per 8 (using the byte
    lanes), then per remaining bit. Each step is 1 cycle on D32 and 2 on D16.
    There's no barrel shifter.

## Examples

Cycles per instruction (first parcel at a word boundary, operands without
a 64 KB crossing):

| Instruction | D16-sep | D16-ovl | D16-wide | D32-sep | D32-ovl | D32-wide |
|---|---:|---:|---:|---:|---:|---:|
| `ADD r1, r2` | 4 | 3 | 3 | 3 | 2 | 2 |
| `CMP r1, r2` | 3 | 2 | 2 | 2 | 1 | 1 |
| `ADD r1, #1000` (2 parcels) | 5 | 4 | 3 | 4 | 3 | 2 |
| word load `[r2 + 4]` | 5 | 4 | 3 | 5 | 4 | 3 |
| byte load `[r2 + 1]` | 4 | 3 | 3 | 4 | 3 | 3 |
| word store `[r2 + 4]` | 4 | 4 | 2 | 4 | 4 | 2 |
| 1b `ADD r1, [r2]` (word) | 7 | 6 | 5 | 6 | 5 | 4 |
| 1b `ADD r1, byte [r2 + 8]` | 7 | 6 | 5 | 6 | 5 | 4 |
| 1b `MOV r1, [r2]+` | 5 | 4 | 3 | 5 | 4 | 3 |
| branch taken / not taken | 2 / 2 | 2 / 1 | 2 / 1 | 2 / 2 | 2 / 1 | 2 / 1 |
| `CALL` (2 parcels) | 5 | 5 | 3 | 5 | 5 | 3 |
| `RET` | 4 | 4 | 3 | 4 | 4 | 3 |
| `SAVE` of 4 registers | 10 | 10 | 5 | 10 | 10 | 5 |
| `MULU`, 16-bit multiplier | 35 | 34 | 34 | 19 | 18 | 18 |
| `DIVU` | 68 | 67 | 67 | 36 | 35 | 35 |

For comparison, draft 0's measured costs on a 16-bit machine were: register
ALU op 2 cycles, compare 1, load or store 3, `CALL`/`RET` 3. D32-overlap is
the closest equivalent.

## What the model leaves out

- **Clock speed.** A 32-bit datapath, a wide bus and draft 1b's mode decoding
  all add some delay or chips, but without a design they're all assumed to
  run at the same clock. The draft 0 hardware ran at 2–3.4 MHz (74HCT), and
  the evaluation uses 3 MHz for times.
- **Microcode details.** Real microcode will be a cycle better or worse here
  and there. Both drafts are costed by the same rules, so the comparison
  between them is fairer than the absolute numbers.
- **Memory wait states, DMA and video stealing bus cycles.** None of these
  are modelled.
