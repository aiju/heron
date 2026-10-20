---
number: 12
type: report
title: The draft 1b hardware
status: current
date: 2026-10-12
context:
  studies: [v1b_hw, v1_isa]
  commit: e494b0c
---

# Report 0012: The draft 1b hardware

[Part I](#part-i-the-hardware) is a 213-chip implementation of draft 1b;
[Part II](#part-ii-performance) is what it achieves, measured on its
chip-level netlist.

## Part I: The hardware

### 1. Overview

This is a buildable implementation of
[ISA draft 1b](0004-rfc-draft-1-isa.md#part-ii-draft-1b), without an MMU
or floating point. It has a 32-bit datapath, pipelined microcode and a 16-bit
memory bus, and every instruction ends with a separate fetch cycle.
It's the configuration the draft 1 timing model calls **D32-separate**, and
its main job is to check that model's numbers against a real design.

- The netlist is in [`cpu.py`](../studies/v1b_hw/cpu.py).
- The microcode is in [`ucode.py`](../studies/v1b_hw/ucode.py).
- A register-transfer model the netlist was built from is in
  [`rtl.py`](../studies/v1b_hw/rtl.py).
- [microcode.md](../studies/v1b_hw/microcode.md) lists the microcode for a selection
  of instructions, cycle by cycle.
- Measured performance is in [Part II](#part-ii-performance).

### 2. At a glance

| | |
|---|---|
| Chips | 213: 186 logic, 17 flash (microcode and decode), 8 register-file SRAM, 2 RAM (draft 0: 98) |
| Logic family | 74HCT, with 74LS181 ALUs and 74S182 lookahead (variants: 74F181/F182, 74ACT) |
| Datapath | 32 bits: 8 × 74181, two-level carry lookahead, 32 registers' worth of fast SRAM in two copies |
| Memory | 1 MB (2 × 512K × 8), 16-bit bus: a word takes two bus cycles |
| Control | Pipelined: 120-bit microinstructions, 15 × SST39SF010A into a 15 × 74HCT377 register; a decode ROM picks each instruction's routine from the data bus during the fetch |
| Microcode | 3,507 microinstructions, 1,082 entry routines (one per instruction form) |
| Clock (guaranteed, worst-case datasheet delays) | 2.99 MHz (HCT + LS181) to 4.74 MHz (ACT + F181) |
| Clock (typical delays) | 4.20 to 5.13 MHz |
| Cycles per instruction | 1 for `MOV rd, #q`, 2 for register ALU ops and branches, 4–5 for most loads and stores ([6](#6-cycles-per-instruction)) |

The clock is faster than draft 0's (334 ns against 486 ns, both worst case
with HCT + LS181), even though the datapath is twice as wide. The pipelined
microcode takes the ROM access out of almost every path.

### 3. Block diagram

<!-- blocks
# the control
box dec "decode ROM" "2 × flash" at 0,0
text op "data bus (the opcode being fetched)" right of dec gap 4
box next "next address Y" "153 × 6" below dec gap 3
text cond "NEXT, condition, dispatch, reset/fault" right of next gap 4
box rom "microcode ROMs" "15 × flash" below next gap 3
box uir "µIR" "15 × 377" right of rom gap 4
text ctl "120 control lines" right of uir gap 4
op -> dec
cond -> next
dec -> next -> rom -> uir -> ctl

# the datapath
box rfa "RF copy A" "4 × SRAM" at 0,25
box rfb "RF copy B" "4 × SRAM" below rfa gap 4
box alu "ALU" "8 × 74LS181" "3 × 74S182" right of rfa gap 9 align=top height=14
box mux "result mux" "F, F >> 1, ror 8, ror 16," "per-byte clear" "153 × 16" right of alu gap 5 align=top
bus res "RES" from 54,26 to 54,39
text r "R (377 × 4) → A, A × 2, B" at 56,27
text mar "MAR (377 × 3, via 157s)" at 56,30
text pc "PC (161 × 8, load)" at 56,33
text lc "LC (161 × 2)" at 56,36
text db "data bus (541 × 5)" at 56,39
rfa -> alu "A bus"
rfb -> alu "B bus"
text a1 "PC" left of alu gap 2 dy=-1.5
text a2 "R, 2R" left of alu gap 2
text a3 "B → A" left of alu gap 2 dy=1.5
a1 -> alu
a2 -> alu
a3 -> alu
alu -> mux "F"
mux -> res
res -> r
res -> mar
res -> pc
res -> lc
res -> db
text "B bus also from: R, T (by byte lane, × 2), immediate unit, MQ (299 × 4), flags" below rfb gap 1 align=left
-->
![The control and the datapath](0012-report-draft-1b-hardware/block-diagram.svg)

- address mux (PC or MAR, 157 × 5) → RAM (2 × 512K × 8); I/O page when MAR bit 31 is set
- data bus ↔ RAM, I/O; data bus → IR (377 × 2), T (377 × 4), decode ROM, SX
- B bus → flags (zero detect: 688 × 4), and through the bridge (541 × 4) onto the A bus

### 4. Datapath

**Buses.** The ALU's A input comes from register-file copy A, the PC, R,
R × 2 (with a shift-in bit), or the *bridge* from the B bus. The B input
comes from register-file copy B, R, T, the immediate unit, MQ or the flags.
B-bus drivers are switched per byte lane, so a byte or half from T can be
combined with fill bytes from the immediate unit. The ALU output F goes
through the result multiplexer onto RES, which loads R, MAR, PC and LC and
drives the 16-bit memory data bus for stores.

**Register file.** There are two copies of 32 entries, each four 32K × 8
SRAMs (AS7C256A-15) using five address lines. Entries 0–15 are `r0`–`r15`,
16 is `HI`, 17 is a scratch register, and 24 and 25 hold loop-count constants
the reset routine writes. Each copy's address comes from a 74HCT153 per two
bits:

- `d`: IR[11:8].
- `r`: IR[3:0].
- `s`: the SX register.
- A constant from the microinstruction.

SX holds IR[7:4], loaded at every fetch. For the indexed mode it is loaded
instead with the index register number from the extension parcel (T[15:12]),
so no register-number path goes through a multiplexer switched by the
microinstruction. Writes go to both copies at once: the value is put on the
B bus and bridged onto the A bus, during the write window of the clock. A
gate tree on the address keeps `r0` from being written, except by the reset
routine.

**ALU.** Eight 74LS181 with two levels of 74S182 lookahead. In multiply and
divide steps a 4:1 multiplexer per function line (2 × 74HCT153, selected by
a 2-bit step field) replaces the microinstruction's S3–S0 with:

- "add if MQ[0]";
- "subtract if MQ[0]";
- "add or subtract by the remainder's sign".

The carry-in multiplexer (74HCT151) has inputs for those steps as well:
`MQ[0]`, and the inverted remainder sign.

**Overflow** is V = (A31 ⊕ B31 ⊕ S0) · (A31 ⊕ F31). The first factor (VT2)
is known early. Instead of an AND gate, it disables the V-flag 74HCT151 when
overflow is impossible. **Shifts** use the result multiplexer:

- right by one, shifting in 0, F31, C, F0, the carry out (multiply steps) or
  the true sign of a 33-bit sum (signed multiply steps);
- rotate by 8 or 16;
- clear any of the four bytes.

Left shifts use the ALU (A + A) or the A bus's R × 2 input, which together
give 2 places per step. A shift by a constant is a sequence of these steps;
the microcode generator finds the shortest one by search. Lengths, counting
the write-back:

| Shift | Cycles |
|---|---|
| `ROR` | 2–5 |
| `LSL` | 2–7 |
| `LSR` | 2–10 |
| `ASR` | 2–11 |

Right shifts are the slow ones, since the result multiplexer only moves one
place right per step; the worst counts are just below a multiple of 8.
Arithmetic shifts work in an "XOR with the sign" domain, so that byte
rotation with cleared bytes behaves like a sign fill.

**R** (4 × 74HCT377) holds results until the write-back.

**T** (4 × 74HCT377) holds memory data and extension parcels, loaded a
16-bit half at a time from the data bus. Byte loads pick the byte lane with
MAR bit 0, using the 74HCT541s' second output enables.

**MQ** (4 × 74HCT299) is the multiplier/quotient register, readable on the
B bus. It shifts right in multiply steps (the low bit of each sum shifts in
at the top) and left in divide steps (the quotient bit shifts in at the
bottom).

**LC** (2 × 74HCT161) counts loop iterations (multiply and divide steps,
shifts by a register). It's preloaded so that "all ones" ends the loop, and
a separate test of the low nibble gives 16-step loops.

**MAR** (3 × 74HCT377 behind 6 × 74HCT157) holds address bits 0–19 and 31,
loaded from RES or straight from the A bus. That lets `[R]+`, `-[R]` and
`RET` use a register as the address while the ALU updates it. The **PC** is
eight 74HCT161 counters (bits 31–1). Any memory read at the PC adds 2.

**Immediate unit.** Byte 0 of the immediate comes from a 74HCT153 per two
bits. It can be the branch offset × 2, an 8-bit constant from the
microinstruction, the fill bit repeated, or LC. Bytes 1–3 are the fill bit
from a 74HCT151, which can be 0, 1, IR7, T7, T15, A31, A15 or the latched
sign. That covers sign or zero extension of 8- and 16-bit immediates, of
loaded bytes and halves, and of jump offsets, and constants from −256 to 255.

**Memory and I/O.** Two 512K × 8 SRAMs make 1 MB on a 16-bit bus. A word
access takes two bus cycles: the second forces address bit 1. A byte write
strobes one chip. The I/O page is anything with MAR bit 31 set, decoded from
MAR, so the decode stays off the RAM's address path.

**Address errors.** A misaligned access is caught in the cycle that makes
it, from the microinstruction's 2-bit access size and MAR[1:0]. It blocks
the memory write and the I/O select and jumps to the address-error routine
(see [Control](#5-control)). The microcode never changes registers, flags
or the PC in a cycle that does a checked access, so the trap sees the
machine as it was; the generator checks that.

**Flags.** N, Z, C and V are in a 74HCT175 and I is in a 74HCT74. Flags are
set from the B bus during the write-back, so a result's N and Z cost nothing
extra. Z can be "sticky" for `ADC`/`SBC` chains. C comes from:

- the carry out;
- a bit of F (shifts);
- bit 1 of the B bus (restoring flags);
- the condition latch.

Condition latches **CL**, **SGN** and **S33** (74HCT74s) hold:

- a tested condition for microcode branches;
- a sign for absolute values and fills;
- the divide's 33rd bit.

**Branch conditions** use ARM's encoding, as in draft 0. A 74HCT151 picks
Z, C, N, V, C·!Z, N=V, !Z·(N=V) or 1, using IR[11:9] (or IR[7:5] for
`SETcc`). Conditional branches gate the PC load with that test XORed with
the polarity bit, so taken and not-taken cost the same.

### 5. Control

**Pipelined microcode.** The microcode ROMs are always addressed with the
address of the *next* microinstruction, Y. Their outputs are clocked into
the microinstruction register (uIR) at every edge, so control signals are
valid 40 ns after the clock instead of a ROM access after it. They don't
glitch while a ROM's address changes, as draft 0's did: every ROM output
goes into a register, or (the decode ROM's routine address) through Y into
the microcode ROMs. Y is chosen during the cycle by six 74HCT153s:

| Sequencing | Y |
|---|---|
| next / branch | `NEXT`; a branch replaces bit 0 with one of 7 conditions (loop counter done, R31, CL, MQ31, the branch condition or its inverse, 16 steps done) |
| decode | the decode ROM's output: two flash chips look at the opcode on the data bus *while it is being fetched* and give the routine's address and the instruction length |
| dispatch | `{NEXT[11:5], DBUS[11:8], DBUS[7:0] ≠ 0}`: the indexed mode picks one of 32 routines from its extension parcel as it arrives |

The ROM address has 16 bits: `{FAULT·LEN, FAULT, IRQP, Y}`.

- **Interrupts.** The IRQP = 1 half of the ROM is a copy of the other, except
  in each instruction's last microinstruction. There the fetch is suppressed
  and the decode ROM, told by a microinstruction bit (`GOIRQ`), returns the
  interrupt entry routine. IRQP is the registered `IRQ · I_next`, as in
  draft 0.
- **Address errors** (`FAULT`) turn the Y multiplexer off (its enable inputs,
  so Y = 0) and select a fault page by the instruction length (2 bits, from
  the decode ROM, kept beside IR).
  Word 0 of each page is the address-error entry, which first winds the PC
  back to the faulting instruction. A first version used the multiplexer's
  select lines for this. It was slow, because the select lines then depended
  on MAR and the access size every cycle, and it created long false paths.
- **Reset** holds Y at 0. The reset routine zeroes `r0`, `HI` and the flags,
  writes the two loop constants and fetches the instruction at address 0.
- **`HALT`** loops on itself. Its copy in the IRQP half goes to interrupt
  entry.

**The separate fetch cycle.** Every instruction ends with a microinstruction
that fetches the next opcode: a read at the PC into IR, with PC += 2, while
the decode ROM finds its routine. The bus is busy, but nothing else is, so
the same cycle writes the instruction's result from R into the register
file and sets N and Z from it. That's why a register ALU instruction takes 2
cycles (compute into R; write back and fetch) and `MOV rd, #q` takes 1. A
fetch overlapped with execution would save a cycle only where an
instruction's last cycle doesn't use the bus; see
[the tables](0012-report-draft-1b-hardware/performance.md) for what the timing model expects
that to be worth.

**Control word**: 120 bits in 15 ROMs. The 12-bit `NEXT` field takes the
first one and a half ROMs; the other fields are packed so none straddles
two ROMs:

| Group | Fields |
|---|---|
| sequencer | `NEXT` (12), `SEQ` (2), `COND` (3), `GOIRQ`, `HALT` |
| A bus | register file, PC, R, R × 2 (+ `SINA` shift-in, 2), bridge from B |
| B bus | register file, R, T byte lanes (4 enables + lane select), immediate byte 0, fill bytes 1 and 2–3, MQ, flags |
| register file | `RFA`, `RFB` address sources (2 each), constant address (5), write, write `r0`, load SX |
| ALU | `S` (4), `M`, carry in (3), MQ mode (2), step select (2) |
| result mux | `RMS` (2), per-byte clear (4), shift-in (2) |
| immediate unit | byte 0 source (2), fill source (3), constant (8), load sign latch |
| registers | load R, MAR (+ source), T low/high, IR, PC (+ conditional), LC (+ count), condition from IR[7:4] |
| memory | read, write, address from MAR, access size (2), high word, store-data source (2) |
| flags | N/Z mode (2), C mode (2), C source (3), clear C, V mode (3), I mode (2), load CL (+ source, 3) |

**Microcode.** The generator writes one routine for each distinct
first-parcel form, keyed by opcode, addressing mode and the fields that
change the sequence. Examples are `ADD m9` (byte with displacement), a
shift count, or the register range of a `SAVE`. That gives 1,082 routines.
Identical tails are shared: 3,507 microinstructions, 86% of the 4,096 slots.
Branch pairs sit at even/odd addresses and the indexed-mode tables at
32-word boundaries. The generator also checks the rules that keep the
hardware consistent (no flag, PC or register change in a checked memory
cycle, both register-file copies written together).

**Multiply** is shift-and-add over MQ, one step per cycle. The signed
version keeps the accumulator signed: each step shifts in the true sign of
the 33-bit sum, which is A31 if the operands' signs agree and F31 if not
(one 74HCT157). The last step subtracts instead of adding, because the
multiplier's top bit weighs −2³¹. This replaced Booth's algorithm, whose
decision gates sat between MQ[0] and the ALU on the slowest path in the
machine. Both multiplies take 16 steps when the operands fit in 16 bits
(`MULU`: the multiplier; `MULS`: both, signed), and 32 otherwise.

**Divide** is non-restoring, with S33 as the 33rd bit of the partial
remainder. Both the quotient bit and the new S33 are a single XOR after the
ALU's carry out. A fix-up step restores a negative remainder, and the
signed version works on magnitudes and fixes signs at the end.

Multiplies and divides are 2.4% of the instructions the test programs run,
but 18% of their cycles, most of it in `mandel`
([the tables](0012-report-draft-1b-hardware/performance.md) have the per-kind table).

### 6. Cycles per instruction

From the microcode, measured on the RTL model. *Model* is the draft 1 timing
model's estimate for D32-separate
([studies/v1_isa/timing-model-v1.md](../studies/v1_isa/timing-model-v1.md#examples)).

| Instruction | Cycles | Model |
|---|---:|---:|
| `MOV r1, #5` | 1 | |
| `ADD r1, r2`, `MOV r1, r2`, `INC r1` | 2 | 3 |
| `CMP r1, r2` | 2 | 2 |
| `ADD r1, #5` / `#1000` / `MOV r1, #70000` | 2 / 3 / 3 | – / 4 / – |
| `MOV r1, [r2]` / `[r2 + 4]` | 4 / 5 | – / 5 |
| `MOV r1, byte [r2 + 1]` | 4 | 4 |
| `ADD r1, [r2]` (word) / `byte [r2 + 8]` | 5 / 5 | 6 / 6 |
| `MOV r1, [r2]+`, `ST r1, -[sp]` (push), `MOV r1, [sp]+` (pop) | 4 | 5 / – / – |
| `ST r1, [r2 + 4]` / `byte [r2 + 1]` | 5 / 4 | 4 / – |
| `MOV r3, [r2 + r4*4]`, `LEA r1, [r2 + r4*8 + 4]` | 6 | |
| `LSL r1, #1` / `#4` / `LSR #8` / `ASR #3` / `ROR #7` | 2 / 4 / 2 / 4 / 3 | |
| `LSL r1, r4` (r4 = 3) | 6 | |
| `Bcc` taken / not taken | 2 / 2 | 2 / 2 |
| `Jcc` taken / not taken | 3 / 2 | |
| `BSR`, `CALL label`, `CALL r9`, `RET` | 5 | – / 5 / – / 4 |
| `SAVE r8-r11` / `RESTORE r8-r11` | 13 / 11 | 10 / – |
| `MULU`, multiplier < 2¹⁶ / any | 21 / 35 | 19 / – |
| `MULS`, both in 16 bits / any | 25 / 41 | |
| `DIVU` / `DIVS` | 37 / 48 | 36 / – |

Over whole programs the hardware needs 0.91 times the model's cycles
(geometric mean over 18 programs; per program and per kind of instruction
in [the tables](0012-report-draft-1b-hardware/performance.md)). The difference has a few
causes, pulling both ways.

**Faster than the model.** The write-back rides in the fetch cycle, which
the model costed as a cycle of its own. That makes everything that writes a
register a cycle cheaper: ALU operations, loads, LEA and shifts.

**Slower than the model.**

- **Multiply**: 25 cycles on average against the model's 11. The model
  stops as soon as the rest of the multiplier is zero; the hardware always
  takes 16 or 32 steps. That alone makes `mandel` 1.39 times the model.
- **Returns and jumps through memory**: one cycle more each. The PC can only
  be loaded from the result bus once both halves of the target are in T.
- **Word stores with a displacement, and `SAVE`**: up to a cycle more per
  word. The data goes through the ALU onto the data bus half a word at a
  time, so address and data don't overlap the way the model assumed. Stores
  as a whole still come out even with the model.

### 7. Timing

Delays come from manufacturer datasheets, as for draft 0
([`infra/hw/datasheets`](../infra/hw/datasheets)), at two corners: *max* is the
guaranteed worst case (−40…85 °C, 4.5 V, 50 pF), *typ* is 25 °C typical, and
memories use their guaranteed figures in both. The same two analyses run on
this netlist:

- **Static timing analysis** ([`sta.py`](../infra/hw/sta.py)) runs once for
  each of the 3,396 distinct microinstructions (with the control lines at
  their values), and covers every data value.
- **The event-driven chip-level simulator** ([`hwsim`](../infra/hwsim)) runs programs and
  checks setup/hold times, SRAM write timing and bus contention.

| Parts | Worst case | Typical |
|---|---:|---:|
| 74HCT + 74LS181/74S182 | 334 ns (2.99 MHz) | 238 ns (4.20 MHz) |
| 74HCT + 74F181/74F182 | 331 ns (3.02 MHz) | 238 ns (4.20 MHz) |
| 74ACT + 74F181/74F182 | 211 ns (4.74 MHz) | 195 ns (5.13 MHz) |

**The floor is the fetch.** In the fetch cycle the opcode has to come out of
the RAM, through the decode ROM, through the Y multiplexer and out of the
microcode ROMs before the clock edge. That's three memory accesses in a row,
and nothing can be faster:

```
   0.0  clock edge
  40.0  address from PC (uIR)           74HCT377 CLK->Q
  86.0  memory address                  74HCT157
 141.0  opcode on the data bus          AS6C4008-55 tAA
 196.0  routine address                 SST39SF010A-55 (decode ROM)
 239.0  next address Y                  74HCT153
 294.0  next microinstruction           SST39SF010A-55
 309.0  setup of the uIR                74HCT377
```

With typical delays the logic gets faster but the memories don't, so the
fetch path alone sets the clock: 238 ns, of which 165 ns is memory. With
74ACT logic it is the limit at both corners.

**The slowest microinstruction** with HCT logic is the signed multiply step,
at 334 ns, 8% above the fetch floor. Its path:

```
   0.0  clock edge
  56.0  MQ[0]                           74HCT299 CLK->Q7'
  99.0  ALU function select             74HCT153 (step select)
 140.0  lookahead P, bits 0-3           74LS181 S->P
 168.0  carry into bits 28-31           74S182 x 2
 194.0  F31                             74LS181 CN->F
 228.0  sign of the 33-bit sum          74HCT157
 276.0  shift-in bit                    74HCT151
 319.0  R31                             74HCT153 (result mux)
 334.0  setup of R                      74HCT377
```

Everything else needs 325 ns or less. Of the 3,396 distinct
microinstructions:

- 4 (the multiply steps) need over 330 ns;
- 149 need 310–325 ns. Most are ALU operations on a sign- or
  zero-extended operand (an immediate, or a byte or half from memory), whose
  V flag waits for the fill bits. The others are first steps that use a
  register's sign as the fill (signed multiply and divide, `ASR`, `SXH`) and
  microcode branches on the GT/LE conditions;
- 986 need 300–309 ns, most of them because they end an instruction and so
  contain the fetch path;
- the rest need less.

[The tables](0012-report-draft-1b-hardware/performance.md) have the full distribution.

**Getting there.** The first complete netlist needed 498 ns. These changes
took it to 334 ns, without adding cycles except one extra step for `ASR #8`
and `ASR #16`:

1. **Nothing data-dependent on a select line.** Address errors used to steer
   the Y multiplexer's select inputs. That put MAR, the fault logic and even
   the RAM's chip enable in front of every next-address computation, which
   made long false paths and some real ones. Address errors now act through
   the multiplexer's enable and the ROM's upper address bits. Likewise the
   index register number now has its own register (SX) instead of a
   multiplexer whose select came from the microinstruction.
2. **Branch conditions without gates.** The condition replaces bit 0 of
   `NEXT` (the 74HCT151 that picks it has `NEXT[0]` as its "no condition"
   input), so there's no OR gate. Microcode branches on instruction
   conditions test the condition *before* the polarity XOR: the decode ROM
   gives each polarity its own routine.
3. **One multiplexer level for multiply and divide steps.** The step logic
   used to be a mode decoder (an XOR and an OR on the microinstruction bits)
   and two multiplexer levels in front of the ALU's function inputs. It is
   now a single 4:1 multiplexer driven by a dedicated 2-bit field, with the
   carry-in coming from the ordinary carry multiplexer.
4. **Multiply without Booth** (above), and the divide's quotient bit one XOR
   after the carry.
5. **Enable inputs as free AND gates.** These are used for overflow, for the
   CL "and" sources, and for picking a T byte lane (the 74HCT541's second
   output enable).
6. **Shift plans** never fill from the A bus and take the carry in the same
   step: register read, fill, B bus, ALU, carry flag was 413 ns on its own.

**Simulation** agrees with the static analysis.

- Every program runs at 334 ns with worst-case delays without a violation.
- Sweeping the clock on the exercise program finds the same limit as the
  static analysis, to within a nanosecond, for all six combinations of
  parts and delays.
- With HCT + LS181 at worst case it fails at 333.6 ns: R bit 31 misses its
  setup time by 0.4 ns in a multiply step, the path above.

The exercise program does hit the worst-case paths: the multiply step's
carry chain and the fetch from the slowest memory.

### 8. Known issues and what a second iteration would change

- **The fetch path is the clock.** Every nanosecond taken off the RAM, the
  decode ROM or the microcode ROMs comes straight off the period, until the
  multiply step (25 ns above it) takes over. Decoding a cycle later, from IR,
  would take the RAM out of the path at the cost of a cycle on every
  instruction, which isn't worth it. Overlapping the fetch with execution
  doesn't change this path either.
- **Overlapped fetch.** The timing model expects overlapping the fetch to
  save 20% of D32-separate's cycles. Part of that saving, the write-back, is
  already in this design: the model's D32-overlap estimate is 12% fewer
  cycles than this hardware takes. An overlapped design would fetch the next
  opcode in an instruction's last cycle when the bus is free. That needs the
  decode ROM's input (the opcode on the data bus) at a different time in
  each instruction, and the write-back would have to move.
- **Bus contention.** The simulator reports drivers overlapping for up to
  37 ns, where a register-file SRAM turns on (7 ns) before a 74HCT541 has
  turned off (44 ns), as in draft 0. On the data bus, after a store, the
  store-data drivers and the next fetch's RAM read overlap by up to 24 ns.
  That was 88 ns until the drivers' enables stopped going through a 74HCT138
  and a gate; now the 541s' two enable inputs decode the 2-bit field. It
  works logically, but it's a current spike on a real board. A
  break-before-make dead time at the start of each cycle, or ACT buffers,
  would fix it.
- **Multiply time** isn't proportional to the multiplier's significant bits,
  as the timing model assumed. It takes 16 or 32 steps, and `MULS` only
  takes the fast path when *both* operands fit in 16 signed bits. This is
  the biggest difference from the model. An 8-step path for multipliers
  below 2⁸ would be cheap: a byte test like the 16-bit one, and two extra
  cycles to realign the product. It wouldn't help `mandel`, whose operands
  are fixed-point fractions. ([RFC 0004](0004-rfc-draft-1-isa.md#21-alu-functions) now only promises
  that small operands are faster.)
- **Hold times** aren't analysed (HCT datasheets give no minimum delays), and
  the clock is ideal (no skew), as in draft 0.
- **A misaligned read still reads the RAM** (the result is thrown away).
  Only the I/O device, whose reads have side effects, is protected.
- **The I/O page is decoded from MAR bit 31 alone**: everything at
  0x80000000 and above is I/O.
- **Parts.** As in draft 0, the 74181/74182 are new-old-stock, the fast
  32K × 8 SRAM and the 55 ns SST39SF010A aren't made in DIP, and the 74ACT
  variant uses HCT where there's no ACT part. The 74HCT299 is only still
  made by TI (CD74HCT299). The AS6C4008 RAM is available in DIP.
- **Size.** 213 chips is more than twice draft 0. Where they go:

  | Area | Chips |
  |---|---:|
  | microcode ROMs and uIR | 30 |
  | glue gates | 24 |
  | B-bus drivers and immediate unit | 21 |
  | result multiplexer | 18 |
  | A-bus drivers | 17 |
  | MAR and PC | 17 |
  | sequencer and decode | 16 |
  | flags and condition latches | 16 |
  | ALU and its control | 14 |
  | register file and its addressing | 14 |
  | memory interface and RAM | 12 |
  | R and T | 8 |
  | MQ and loop counter | 6 |

  A narrower control word (with decoded fields, at some cost in speed) or
  dropping the second register-file copy (an extra cycle for two-register
  operations) are the big levers.

### 9. Verifying the hardware model

There are three levels, each checked against the one above:

1. The **instruction-level simulator** ([`studies/v1_isa/sim32.py`](../studies/v1_isa/sim32.py))
   is the ISA reference.
2. The **RTL model** ([`rtl.py`](../studies/v1b_hw/rtl.py)) executes
   the microcode ROM images one cycle at a time. It models every register,
   bus and multiplexer the netlist has, and checks microcode rules as it
   goes: bus contention, floating buses used, conditions, step modes.
   `heron v1b_hw check` runs all 20 programs on it and compares
   output, registers, flags, PC and all of RAM with the ISA simulator.
   `--lockstep` compares after every instruction.
3. The **chip-level simulator** runs the netlist.
   `heron v1b_hw hw run PROG.s` compares everything above plus
   the cycle of every instruction fetch with the RTL model.

[`exercise.py`](../studies/v1b_hw/exercise.py) generates the
exercise program (`build/exercise_v1b.s`, 1.5 million cycles). It covers:

- every register-register operation on 20 values and 5 flag combinations;
- divide edge cases;
- every unary operation;
- every shift count, immediate and by register;
- every addressing mode with every operation, and every load and store
  size;
- auto-increment and decrement;
- every condition against all 16 flag combinations;
- every jump and call form, `SAVE`/`RESTORE` and the special registers;
- 37 traps: `SWI`, 19 illegal encodings, divide by zero, and address
  errors from loads, stores, auto-increment and decrement, indexed and
  absolute addresses, and jumps and calls through memory.

It matches cycle for cycle at chip level. Programs that use interrupts are
compared on results only, since the IRQ timing can differ by a cycle.

## Part II: Performance

What the draft 1b implementation of Part I achieves, measured on its
chip-level netlist. Its main job was to check the draft 1 timing model
against a real design.

- **Clock:** 334 ns (2.99 MHz) worst case with 74HCT and 74LS181, up to
  4.74 MHz with 74ACT and 74F181; 4.20 to 5.13 MHz with typical delays.
  That confirms the 3 MHz the draft 1 reports assumed.
- **Cycles:** 0.91 times what the timing model estimates for the same
  configuration (D32-separate). Everything that writes a register is a
  cycle cheaper, because the write-back shares the fetch cycle; multiplies
  are slower, because they don't stop early.
- **Against draft 0:** about twice as fast as the draft 0 hardware.
- **Checked:** all 20 programs run on the chip-level simulator at the
  guaranteed clock, matching the register-transfer model cycle for cycle
  (except `interrupts`, whose results match).

The tables are in [performance.md](0012-report-draft-1b-hardware/performance.md), generated by
`heron v1b_hw report --hw` (the chip-level runs take 30–60 minutes; without
`--hw` the report reuses their cached results in `build/`).
