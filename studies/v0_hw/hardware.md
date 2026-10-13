# Hardware: a 7400-series implementation of ISA draft 0

> **Draft 0 is superseded.** This is the 16-bit first draft, kept as a record. Draft 1 replaced it: see [report 0004](../../reports/0004-report-draft-1-evaluation/README.md) and [studies/v1b_hw/hardware.md](../v1b_hw/hardware.md).

This is a first-cut, buildable implementation of [ISA draft 0](isa.md):
98 chips including memory, microcoded, one bus cycle per clock. Its main job
at this stage is to put real numbers on the ISA: how many clock cycles each
instruction needs and how fast the clock can go. The netlist is in
[`cpu.py`](cpu.py), the microcode in
[`microcode.py`](microcode.py), and measured performance is
in [report 0001](../../reports/0001-report-draft-0-evaluation/performance.md).

## At a glance

| | |
|---|---|
| Chips | 98: 86 logic, 6 microcode flash, 4 register-file SRAM, 2 RAM |
| Logic family | 74HCT, with 74LS181 ALUs and a 74S182 lookahead (variants: 74F181/F182, 74ACT) |
| Control | 48-bit microinstructions in 6 × SST39SF010A, up to 16 steps per instruction |
| Register file | 16 × 16 bits, two copies in fast SRAM so both ALU operands read at once |
| Cycles per instruction | 1 to 4 for normal instructions (table below), 7 for traps and interrupt entry |
| Clock (guaranteed, worst-case datasheet delays) | 2.06 MHz (HCT + LS181) to 3.72 MHz (ACT + F181) |
| Clock (typical delays) | 3.4 to 5.0 MHz |

## Block diagram

```
                 +-----------+     ROM address: step, IR[15:12], IR[3:0],
  STEP (163) --->| microcode |<--  irq pending, link, mode bits
                 | 6 x flash |
                 +-----------+---> 48 control lines
                                   (bus enables, register loads, ALU function ...)

  +------------+  A bus   +-----------------+   F    +--------------+  RES
  | RF copy A  |--------->|                 |------->| result mux   |------+--> R (377) --> A bus, B bus
  | 2 x SRAM   |   PC --->|  4 x 74LS181    |        | lanes, swap, |      +--> MAR (via mux) --> address mux
  +------------+   R  --->|  + 74S182       |        | shift right, |      +--> PC (161 x 4, load)
                          |                 |        | sign/zero ext|      +--> flags (N Z C V)
  +------------+  B bus   |                 |        | 8 x 74HCT153 |      +--> D bus (541 x 2)
  | RF copy B  |--------->|                 |        +--------------+
  | 2 x SRAM   |  IMM --->+-----------------+
  +------------+  MEM (D bus) ---^  T, R, flags also drive the B bus

  address mux (PC or MAR) --> RAM (2 x 32K x 8), I/O page FF00-FFFF
  D bus <--> RAM, I/O; D bus --> IR (377 x 2), T (377 x 2), B bus (541 x 2)
  PC --> D bus (for pushing return addresses), PC --> A bus (for branches)
```

## Datapath

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

## Control

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

## Cycles per instruction

From the microcode (and cross-checked by the chip-level simulator):

| Cycles | Instructions |
|---|---|
| 1 | `CMP`, `TST`, `CMPI`, `NOP`, `EI`, `DI`, `MTF` |
| 2 | ALU register-register, unary, `MVI`, `ADDI`, ALU `#imm16`, `LEA`, `Bcc` (taken or not), `Jcc`/`JMP addr`, `JMP rs`, `MFF` |
| 3 | `LD`/`ST`/`LDB`/`STB` (both forms), `BSR`, `CALL`, `CALL rs`, `RET`, `PUSH` |
| 4 | `POP` |
| 7 | `RTI`, `SWI`, traps, interrupt entry |

## Timing

Delays come from manufacturer datasheets (collected in
[`infra/hw/datasheets`](../../infra/hw/datasheets), mapped by
[`build_timing.py`](../../infra/hw/build_timing.py)). Two corners: *max* is the
guaranteed worst case (−40…85 °C, 4.5 V, 50 pF for HCT/ACT); *typ* is the
25 °C typical. Memories only have guaranteed figures, so they use them in
both corners.

Two independent analyses:

- **Static timing analysis** ([`sta.py`](../../infra/hw/sta.py)) runs once per
  distinct microinstruction, with the control lines set to that
  microinstruction's values. Known values cut paths that can't happen: a
  disabled bus driver, an unselected mux input, a gate with a controlling
  input. Data stays unknown, so the result covers every data value, including
  full carry propagation.
- **Event-driven simulation** (the Go simulator in [`hwsim`](../../infra/hwsim))
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

## Known issues and what a second iteration would change

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

## Verifying the hardware model

`heron v0_hw hw run PROG.s` runs a program on the chip-level simulator and
compares the console output, all registers (both register-file copies), the
flags, the PC, all of RAM, the cycle count and the cycle-by-cycle sequence of
instruction fetches with the instruction-level simulator. `exercise.s`
runs every instruction class, every condition code against every flag
combination, every trap and both forms of every load and store, and matches
cycle-exactly. Programs that use interrupts are compared on results only,
since IRQ sampling can differ by a cycle or two.
