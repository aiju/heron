---
number: 47
type: rfc
title: Chibi Heron: draft 2 in about seventy chips
status: draft
date: 2026-10-19
context:
  studies: [chibi, v2_isa]
  commit: 65ebcd9
depends-on: [28]
---

# RFC 0047: Chibi Heron: draft 2 in about seventy chips

The smallest Heron so far: draft 2's user instruction set
([RFC 0028](0028-rfc-draft-2-isa.md)) on one board, with 2 MB of RAM,
640 × 480 × 4 VGA, two UARTs and PS/2 ports for a keyboard and a mouse.
Heron Mini ([RFC 0041](0041-rfc-heron-mini.md)) does this in 375
packages; the aim here was about 120. Emily's brief: a 16-bit datapath
with 32-bit registers, nothing of the system architecture but interrupts
(no register banks, no MMU), as few internal buses as can be (an operand
latch on the ALU), no microcode pipelining, no prefetch, perhaps
horizontal microcode, ATF22V10s, DIP but for the 22V10s and the flashes
in socketed PLCC and the RAM, one fixed cycle rather than variable
ones, and performance in mind without a target clock. It is a fresh
design, not a reduction of the earlier ones; only `infra/` is shared.

The study is [studies/chibi](../studies/chibi/README.md): the microcode,
a register-transfer model checked against draft 2's instruction-level
simulator, and a chip-level netlist of the whole board. Part I specifies
the machine as the netlist builds it; Part II is what it measures, why
it's built so, and what's left for Emily to decide. The tables are in
[performance.md](0047-rfc-chibi-heron/performance.md).

This is a **first cut**: it runs Heron code, all of the program suite,
but a few instructions, the boot and some of the devices aren't done
([17](#17-open-tasks)).

## Summary

- **70 packages** (and resistor networks): 36 ATF22V10s, the nine
  flashes of the control store, five chips of ALU, two of operand latch,
  two of register file, four of RAM, six buffers and transceivers, two
  UARTs, the boot flash, the reset supervisor and two oscillators. Well
  under the 120 aimed at, with room for what's open
  ([16](#16-open-questions)).
- **It works, at chip level.** The whole program suite, all twenty
  programs, runs on the register-transfer model as on draft 2's
  simulator, and on the netlist exactly as on the model: the output,
  the registers, the flags, the RAM and every instruction fetch at the
  same cycle, with no timing violation.
- **The period: 147.1 ns** by static timing analysis of the netlist
  with worst-case datasheet delays (6.80 MHz). The machine runs at
  158.9 ns, four of VGA's pixels (6.29 MHz), so that the video's timing
  is the CPU's clock: 11.8 ns to spare. The slowest cycle is a read of
  the boot flash that sets the flags ([12](#12-timing)).
- **Speed:** about 1 MIPS on ordinary code, 5–7 cycles an instruction;
  the suite takes 7.7 times as long as on the full Heron
  ([RFC 0031](0031-rfc-draft-2-cpu.md)), 3.3–6.4 times on the twelve
  programs without much multiplying, dividing or long shifts, up to 14
  times on those with ([13](#13-how-fast)).

## Contents

- Part I: Specification
  [1. Overview](#1-overview) ·
  [2. Clock and cycle](#2-clock-and-cycle) ·
  [3. Control store and sequencer](#3-control-store-and-sequencer) ·
  [4. Datapath](#4-datapath) ·
  [5. Addresses](#5-addresses) ·
  [6. Memory](#6-memory) ·
  [7. The I/O space](#7-the-io-space) ·
  [8. Interrupts and exceptions](#8-interrupts-and-exceptions) ·
  [9. Video](#9-video) ·
  [10. Reset](#10-reset) ·
  [11. Parts](#11-parts)
- Part II: Discussion
  [12. Timing](#12-timing) ·
  [13. How fast](#13-how-fast) ·
  [14. Why it's built so](#14-why-its-built-so) ·
  [15. How it was checked](#15-how-it-was-checked) ·
  [16. Open questions](#16-open-questions) ·
  [17. Open tasks](#17-open-tasks)

## Part I: Specification

### 1. Overview

A microcoded CPU with a 16-bit datapath around one internal bus, D:

- the **register file** (16-bit halves of draft 2's 16 registers and of
  16 microcode temporaries) drives D, and is written from it;
- the **ALU** (four 74F181s and a 74F182) takes D as its A operand and
  the **operand latch** L (two 74ABT377s, loaded from D) as its B;
- its result goes through the **result register** Y (two 22V10s, which
  can also shift it right a bit or extend a byte), which drives D at the
  start of the next cycle for the register file, PC and MAR to load;
- the **immediate unit** (two 22V10s) puts constants and the
  instruction's fields on D;
- **PC** and **MAR** are counters in 22V10s, loaded from D, and drive
  the address bus; PC is read back onto D through two 74ABT541s;
- the **memory data bus**, MD, joins D through three 74ABT245s (one of
  them crossing the bytes for byte accesses), and holds the RAM, the
  UARTs, the boot flash, the PS/2 ports, and the video's shifter.

The control store is horizontal: nine flashes give the 67 bits of a
microinstruction straight to the datapath, without a pipeline register.

### 2. Clock and cycle

A 50.35 MHz oscillator (twice VGA's pixel clock) drives a 22V10 (`U_CK`)
that counts its ticks, 19.86 ns, eight to a cycle of **158.9 ns**. Every
cycle is the same length. From the count it makes (registered, so they
change together, a 22V10's clock-to-output after the tick):

| Signal | Ticks | What it does |
|---|---|---|
| CLK | rises at 0 | the cycle's end: the sequencer, flags, Y, L, IR load (buffered by a 74ABT541) |
| PHW | 0–2 | phase W |
| YOE | 1–2 | Y drives D |
| RWS | 1 | the register file's write strobe |
| CLKW | rises at 3 | PC and MAR load |
| VLD | 1–2 | the video's read of the RAM |
| PIX | even ticks | the pixel clock, 25.175 MHz |

A cycle has two phases:

- **Phase W** (ticks 0–2), while the control store settles on the new
  microinstruction: Y, the result of the cycle before, drives D; the
  register file writes it if that microinstruction asked (its write
  address and enable registered at the cycle's end); PC and MAR load
  from D or count, as the microinstruction before asked, at CLKW. The
  video has the address bus and reads the RAM.
- **Phase R** (ticks 3–7): this microinstruction's source drives D; the
  ALU computes from D and L; PC or MAR drives the address bus; a memory
  or I/O access happens, its strobes timed by a 22V10 (`U_MEMC`) on the
  master clock: the RAM's write enables in ticks 4–6, the I/O read
  strobe in 4–7 and the write strobe in 4–6. At the cycle's end Y, L,
  the flags and the sequencer load.

So a result written to a register is there to be read by the very next
microinstruction, and an address loaded into MAR can be used by it.

### 3. Control store and sequencer

**The control store** is nine SST39SF040-55 flashes (512K × 8): 72
bits, 67 used. Its address is

$$\text{PAGE}[1{:}0] \cdot 2^{17} + N[3{:}0] \cdot 2^{13} + \text{OP}[7{:}0] \cdot 2^{5} + \text{STEP}[4{:}0]$$

a block of 32 microinstructions for each page, nibble N and opcode
byte. The four pages:

| Page | N | Entered |
|---|---|---|
| 0 | the register byte's high nibble (d) | at an instruction's decode |
| 1 | the register byte's low nibble (s), or d held | by a jump: the special mode's forms, the system instructions, SETcc, and longer routines' second parts |
| 2 | the index parcel's scale and size (or a register number from an extension parcel) | by a jump: the indexed mode, a third part |
| 3 | (any) | at reset, an interrupt and an exception |

There is no decode table: the opcode byte is part of the address. The
same microinstruction appears in many blocks; 1252 are distinct.

**The microinstruction's fields:**

| Field | Bits | What it says |
|---|---:|---|
| DS | 3 | D's source in phase R: none (D holds), register file, memory, immediate, PC low (541s), PC high |
| SZ | 1 | a byte access |
| IMMF | 5 | the immediate unit's format: a constant (0, 1, 2, 4, 8, 16, 32, −1, −2, 6, 31, 0xFF, the vectors…) or a field of the register byte (quick constants, shift counts, the 7-bit immediate's parts, displacements) |
| RS, KR, HR | 2, 5, 1 | the register read: d, s or a constant register number; the half |
| WS, KW, HW, WEN | 2, 5, 1, 1 | the register written in the next phase W: d, s or a constant; the half; whether |
| AOP | 5 | the ALU's operation: 31, the 74F181's function, mode and carry in (0, 1, C or the internal carry IC, some chosen by ST) |
| SISEL, RM | 2, 2 | Y's input: the ALU's output, shifted right by one (the bit in: 0, C, D15 or the carry out), the low byte zero- or sign-extended |
| FL | 5 | the flag operation: 31, among them the low and high halves of an add or subtract, the logical ones, shifts, the internal flags' |
| LDL | 1 | load L from D |
| MOP | 3 | the memory operation: read at MAR, write at MAR, read at PC, fetch, PC on the bus |
| AXP, AXM | 2, 2 | PC's and MAR's operation at the next CLKW: load low half, load high half; MAR + 2 |
| IROP | 2 | the register byte's nibbles: d + 1, s − 1, s from an extension parcel |
| NOP | 2 | N: hold, from s, from MD (an extension parcel's) |
| SEQ, CND | 2, 5 | next, jump if a condition (or its inverse), end |
| JT, PT | 5, 2 | the jump's step and page |
| HALT | 1 | stopped (HALT with interrupts off) |

**The sequencer** is four 22V10s and a fifth for the condition:

- `U_IRL`, the opcode register (OP), loads MD's low byte on a fetch;
- `U_IRH`, the register byte's nibbles d and s, loads MD's high byte on
  a fetch, counts d up and s down (SAVE, RESTORE), takes s from an
  extension parcel; it also gives NE (d ≠ s);
- `U_NG`, N: d at a fetch, s or MD's bits 11–8 when asked;
- `U_STEP`, STEP and PAGE: the next step, the jump's step and page if
  the condition holds, or step 0 of page 0 at the end of an instruction
  (page 3 if an interrupt is pending);
- `U_COND`, the condition: true, the flags N Z C V, HI LT LE (from them),
  IC, ST, INIT, the interrupt pending, NE, address bit 0 and a
  misaligned word, I.

**The end of an instruction** is in its last microinstruction where it
can be: that cycle fetches the next instruction's first parcel at PC
(PC + 2), loads it into OP, d, s and N, and the next cycle is its first
microinstruction. An instruction takes as many cycles as it has
microinstructions; there is no decode cycle.

### 4. Datapath

**The register file** is two CY7C199C-12 (32K × 8, 64 words used): 32
registers of two 16-bit halves, draft 2's r0–r15 and 16 temporaries the
microcode keeps. Its address comes from three 22V10s (`U_RFA0-2`): in
phase W the registered write address, in phase R the read's (d, s or a
constant, and the half).

**The ALU**: four 74F181s with a 74F182, A from D and B from L. Its
operation, mode and carry in come from `U_ALUC`, a 22V10 decoding AOP
with the flags C, IC and ST.

**Y**: two 22V10s (`U_YLO`, `U_YHI`), registered at the cycle's end,
drive D in ticks 1–2. They take the ALU's output as it is, shifted right
one place with the incoming bit from `U_ALUC` (0, C, the operand's sign
or the carry out), or its low byte zero- or sign-extended. `U_ZERO`, a
22V10, gives the flags GAL Y's zero, bit 15 and bit 7 before Y loads.

**The flags** are a 22V10 (`U_FLG`): N, Z, C, V and I, the ISA's, and
two of the microcode's own: IC, the carry between a 32-bit operation's
halves, and ST, a scratch flag (a sign, a count's end). Z of a 32-bit
result is the low half's Z and the high half's. `U_SYS`, another 22V10,
registers the interrupt request, INIT (set at reset) and the devices'
reset.

**The immediate unit**, two 22V10s (`U_IMML`, `U_IMMH`), puts on D a
constant or a format of the register byte (IMMF), and a byte read's
zero high half. `U_BUS`, a 22V10, enables D's source in phase R and
points the transceivers.

**Draft 2's registers and flags** are as RFC 0028 has them for a
machine without the supervisor: the flags word (MFSR, MTSR `ccr`) is
draft 1's, V C Z N I in bits 0–4. 32-bit operations take a cycle a half,
and an operand from a register an extra cycle for L: `ADD r1, r2` is
four cycles.

### 5. Addresses

The address bus has A20–A0 and A31. **PC** (bits 20–1) is three 22V10s
(`U_PCA-C`), **MAR** (bits 20–0 and 31) three more (`U_MARA-C`):
counters that load a half from D at CLKW, PC counting by 2 on a fetch or
a read at PC, MAR by 2 when asked. Their operations come from `U_ADC`, a
22V10 that registers them at the cycle's end, so that they happen in
the next cycle's phase W; it also selects which of PC and MAR drives the
address bus in phase R (PC for fetches and reads at PC, MAR otherwise).
MAR's bits 18–20 are buried in `U_MARC`, which drives A18–A20 from them
in phase R and from the video's constants in phase W. PC reads back
through two 74ABT541s (bits 15–0, via A15–A0) and `U_PCC`'s pins (bits
20–16).

Draft 2's addresses are 32 bits; the board decodes A20–A0 and A31.
**A31 = 0 is RAM**, 2 MB repeated through the low 2 GB; **A31 = 1 is
the I/O space**. PC has no bit 31: code runs from RAM.

### 6. Memory

**The RAM** is four AS7C4096A-12 (512K × 8, SOJ-36): two rows of two
byte lanes, 1M × 16 = 2 MB, the row chosen by A20. A word access is two
halfword cycles at MAR and MAR + 2; a byte access steers the odd byte
across (`U_XS`) and zero-extends it. RAM reads in phase R take one
cycle; so do writes, the write enables in ticks 4–6 (`U_MEMC`, on the
master clock, with the RAM's chip and output enables).

Draft 2's misaligned word accesses trap (address error), as RFC 0028
has them; halfword accesses must be even.

### 7. The I/O space

I/O devices are 8 or 16 bits on MD, at even addresses. The selects come
from `U_IODEC`, a 22V10 decoding A31 and MAR's buried bits 18–20, which
are there from CLKW (the address bus is the video's until tick 3). The
I/O strobes are `IORD_n` (ticks 4–7) and `IOWR_n` (ticks 4–6); every
device access is one cycle.

| Address | Device |
|---|---|
| 0x0000_0000–0x001F_FFFF | RAM, 2 MB (and its repeats to 0x7FFF_FFFF) |
| 0x8000_0000 + 2n | UART 0's register n (TL16C550C, on MD7–0) |
| 0x8004_0000 + 2n | UART 1's |
| 0x8008_0000 | PS/2: the keyboard's byte (read; a write clears the receiver) |
| 0x8008_0002 | PS/2: the mouse's byte |
| 0x8008_0004 | PS/2: the keyboard port's control (write: bit 0 pulls the clock low, bit 1 the data) and status (read: bits 0–1 the lines, bit 2 a byte waiting) |
| 0x8008_0006 | PS/2: the mouse port's |
| 0x800C_0000 | the video's control register (write): bit 0 the frame buffer shown, bit 1 the display on, bit 2 the frame interrupt enabled; any write clears the frame interrupt |
| 0x8010_0000 + 2n | the boot flash's byte n (SST39SF010A, 128K × 8, on MD7–0; writable with its command sequences) |
| 0x8018_0000 and up | free; the simulation's test fixture (the program suite's I/O page at 0xFFFF_FF00) is here |

The UARTs have a 1.8432 MHz oscillator of their own. The PS/2 ports:
each has a receiver, a 22V10 clocked by the port's clock line, which
shifts the inverted data line in on the rising edges; after nine
(the start bit and the byte) the start bit reaches the end, the
registers hold the byte, ignoring the line until a write clears them, and
the port's interrupt is raised. A second 22V10 a port holds the lines'
pull-downs (sending, the mouse's "enable data reporting", is
software's, clocking the bits out on the device's clock) and reads
them back. The lines are pulled up on the board.

### 8. Interrupts and exceptions

One level. The interrupt request is the OR of the UARTs', the PS/2
ports', the video's frame interrupt and (in the simulation) the suite's
timer; it's taken, while I is set, at the end of an instruction (never
straight after EI). Software polls the devices to find which.

An interrupt, an exception or SWI pushes the return address and then
the flags word (the flags at the new sp, the return address above
them), clears I and jumps to its vector in RAM:

| Vector | |
|---|---|
| 0x00 | reset |
| 0x04 | interrupt |
| 0x08 | illegal instruction |
| 0x0C | SWI |
| 0x10 | divide by zero |
| 0x14 | address error (a misaligned access) |
| 0x18 | tag check (draft 2's tagged operations, not built yet) |

The return address is the next instruction's for an interrupt and for
SWI, and the trapping instruction's for the others. RTI pops the flags
word and PC. HALT with I set waits for an interrupt, which returns after
the HALT; with I clear it stops.

### 9. Video

640 × 480 at 60 Hz (59.94), 4 bits a pixel, VGA's standard timing. The
video counts in CPU cycles of four pixels: a line is 200 cycles (160
visible), a frame 525 lines (480 visible). Five 22V10s:

- `U_VH`, the horizontal count, 0–199, and HSYNC (cycles 164–187);
- `U_VV`, the line, 0–524, and the blank from line 480;
- `U_VC`, VSYNC (lines 490–491), the frame interrupt (at line 480, if
  enabled; cleared by a write of the control register), and the control
  register's three bits;
- `U_SHA`, `U_SHB`, the shifter: in phase W of each visible cycle the
  RAM gives a halfword, four pixels, loaded at tick 2 and shifted out a
  pixel each PIX, pixel 0 in bits 3–0.

**The frame buffers** are at 0x18_0000 and 0x1C_0000 (control bit 0),
512 bytes a line: line $y$'s pixel $x$ is the nibble at
$\text{base} + 512y + \lfloor x/2 \rfloor$, the low nibble for even $x$. A line's last
192 bytes aren't shown. The video's reads are in phase W, which the CPU
never uses for memory: it takes no cycles from the CPU.

**The colours** are fixed: the four bits drive a resistor DAC to VGA's
R, G and B (not in the netlist; [16](#16-open-questions)). The display
is off after reset, until software sets bit 1.

### 10. Reset

A TL7705A holds RESET_n low at power-up. Reset clears the sequencer to
page 3, step 0, the flags, the PS/2 receivers and the video's control
register, resets the UARTs, and the reset routine sets INIT and enters
the program at address 0. The program's image must be in RAM: in the
simulation it's preloaded ([17](#17-open-tasks)).

### 11. Parts

| | Packages | |
|---|---:|---|
| ATF22V10C-5 (PLCC-28, socketed) | 36 | clock, sequencer (5), flags and system (2), register file addressing (3), ALU control, result (3), immediate unit and bus (3), PC and MAR (7), memory control, I/O decode, PS/2 (4), video (5) |
| SST39SF040-55 (PLCC-32, socketed) | 9 | the control store |
| SST39SF010A-55 (PLCC-32, socketed) | 1 | the boot flash |
| 74F181, 74F182 | 4, 1 | the ALU |
| 74ABT377 | 2 | the operand latch |
| 74ABT541 | 3 | the clock's buffer, PC's read-back |
| 74ABT245 | 3 | D to MD, and the byte crossing |
| CY7C199C-12 | 2 | the register file |
| AS7C4096A-12 (SOJ-36) | 4 | the RAM |
| TL16C550C | 2 | the UARTs |
| TL7705A | 1 | the power-on reset |
| oscillators | 2 | 50.35 MHz, 1.8432 MHz |
| **total** | **70** | |

Not counted: the resistor networks (the PS/2 lines' pull-ups, the DAC),
decoupling, the connectors (VGA, two serial ports, two PS/2 ports, power).

## Part II: Discussion

### 12. Timing

Static timing analysis of the netlist (`heron chibi hw sta`) takes every
distinct microinstruction as a case, its control bits held at their
values from the time the flashes give them (55 ns after the step
changes), with the clock generator's phases at their ticks for a period
T, and finds the smallest T that meets every setup: the registers' at
the cycle's end, `U_MEMC`'s before tick 4, the SRAMs' address and data
before and during their write strobes, the UARTs'. Phase W is one more
case, the control bits unknown. Worst-case delays throughout.

**The machine needs 147.1 ns.** The slowest microinstructions are the
reads of the I/O space that set the flags, the boot flash's 55 ns
access the bulk of it:

```
PHW falls at tick 3 + 4 ns     59.1 ns   (the video lets go of the address bus)
MARSEL (U_ADC)                 64.1
A1 (U_MARA)                    69.1
the boot flash's data         124.1      (tACC 55 ns)
D0 (U_X0)                     128.0
F0 (U_ALU0)                   139.0
Z16 (U_ZERO)                  144.0
U_FLG's setup                 147.1
```

Next come a UART's address before its strobe and `U_MEMC`'s inputs
before tick 4 (144.0 ns): the control store's 55 ns from the step's
change, then MARSEL and MAR's outputs. Of the 450 cases, the 54 that
need 140–149 ns are the I/O accesses and the RAM's writes, whose strobes
come at tick 4 and need the address (a write's byte lane, A31) before
it; the other 396, the RAM's reads and everything else, need 120–129 ns.
Phase W needs 120.0 ns (the video's read of the RAM into the shifter).

**It runs at 158.9 ns**, four VGA pixels, because the video counts in
CPU cycles: one oscillator, one count, and the video's reads in phase W
for free. 147.1 ns would be 8% faster, but the video would then need its
own clock and a way to get its reads in.

What would make it faster, were the clock free to change (none of it
built):

- **The boot flash's read:** its address comes at tick 3, then its
  55 ns. A 45 ns flash, or reading it into a temporary and setting the
  flags in the next cycle (it's only read at boot), brings the worst case
  to the 144.0 ns of the UARTs and `U_MEMC`.
- **The control store:** those 144.0 ns are the flashes' 55 ns from the
  step's change, then MARSEL and MAR, before tick 4, half the cycle. 45 ns
  flashes would bring them to about 124 ns, near the rest's 120–129; a
  pipeline register on their outputs (ruled out here) would hide them.
- **The phases:** phase W's three ticks are what the register file's
  write and PC's and MAR's loads need while the flashes settle; with a
  faster store, phase R could start at tick 2.

### 13. How fast

The suite on the model, which the netlist matches cycle for cycle, at
158.9 ns a cycle ([performance.md](0047-rfc-chibi-heron/performance.md)):

| | Chibi Heron | The full Heron (RFC 0031) | |
|---|---:|---:|---:|
| the suite (18 programs, not hello or interrupts) | 3599 ms | 465 ms | 7.7× |
| the twelve without much multiplying, dividing or long shifts | 589 ms | 137 ms | 4.3× |
| cycles an instruction, those twelve | 6.1 | | |

So about 1 MIPS on ordinary code: life, sieve, sort, queens and fib at
3.5–4.7 times the full Heron's time, CPI 5–7. Where it's slower:

- **Multiplying and dividing** go a bit a step, nine cycles a step on
  the 16-bit datapath: MULU and MULS take about 255 cycles, MULA 310,
  MULFX 355 (its shift a bit at a time too), DIVU and DIVS 375–385.
  mandel (MULFX), matmul (MULA), bignum and arith take 8–14 times as
  long; in the suite as a whole, the multiplies and divides are 54% of
  the cycles.
- **Shifts** go a bit a step too, unrolled up to six bits and a loop
  beyond: `LSL r1, #1` is 5 cycles, `LSL r1, #8` 28, `LSR r1, #12` 40.
  sha256's rotates (and REV) take it to 14 times.
- **32-bit operations** take a cycle a half, and a register operand a
  cycle more for the latch: `MOV r1, r2` is 2 cycles, `ADD r1, #5` 3,
  `ADD r1, r2` and `CMP r1, r2` 4, `MOV r1, [r2]` and `MOV [r2], r1` 5,
  `PUSH` 6, `POP` 7, a taken `BRA` 4. vm's dispatch, a `JMP` through a
  table, averages 18.5.

What would buy time back, in microcode: a multiply that retires two
bits a step (Booth's recoding) or skips runs of zeros; shifts by 8 and
16 through the byte-crossing transceiver and the halves; and in
hardware, a 74x shift register beside L for the multiply's and divide's
bits (two chips) or a 16-bit multiplier chip. None is in this cut.

Against Heron Mini ([RFC 0041](0041-rfc-heron-mini.md)), which runs the
suite in 1.05 times the full Heron's time with 375 packages: a fifth of
the chips for about a seventh of the speed.

### 14. Why it's built so

- **One bus and a latch.** Every operand crosses D: an ALU operation of
  two registers is a cycle to load L and a cycle to compute, a half at a
  time. A second read port (a second register file and a B bus) would
  save the latch's cycle, for perhaps five or six chips (not built).
- **Horizontal and unpipelined.** The flashes drive the datapath
  directly; their 55 ns comes first in every cycle, so the cycle is cut
  into a phase that doesn't need the new microinstruction (writing the
  last one's result, loading PC and MAR, the video's read) and one that
  does. No microinstruction register, no pipeline hazards, no delayed
  branches in the microcode. 67 bits suffice for every field to have
  its own bits; the encodings of the ALU's and the flags' operations
  were chosen (by annealing) so that their 22V10s fit.
- **22V10s for everything small.** The counters (PC, MAR, the video's),
  the registers (opcode, Y), the multiplexers (the register file's
  address) and the decoders are 22V10s, 36 of them; most of the 74-series
  parts left are where a 22V10 can't be (the ALU, the latch's 16 bits
  with one enable, the buffers' drive) or the memories.
- **The fixed cycle.** No variable-length cycles, as asked: the cycle
  is as long as the slowest microinstruction needs, which here is set by
  the video anyway.
- **The I/O selects from MAR's own bits.** The address bus is the
  video's until tick 3; decoding A18–A20 there would put the decode after
  tick 3 and the strobes later. MAR's bits are there from CLKW.
- **2 MB, not 4.** Four 512K × 8 SRAMs; 4 MB is four more and A21
  ([16](#16-open-questions)).

### 15. How it was checked

- **The model against the simulator** (`heron chibi check`): every
  program of the suite, the output, registers, flags and memory as
  draft 2's instruction-level simulator leaves them; and the long
  routines (multiply, divide, CLZ, REV, MULA, MULFX) on chosen and
  random operands, registers aliasing, against the simulator (the unit
  tests).
- **The netlist against the model** (`heron chibi hw test`): the chip-
  level simulator runs the netlist, its 22V10s from their equations, the
  flashes from the microcode's images, the RAM preloaded with the
  program, with worst-case delays; the output, the registers, the
  flags, the RAM and the address, parcel and cycle of every instruction
  fetch are the model's. The simulator's timing checks all pass, and it
  reports no bus driven twice but for overlaps of zero length, where one
  driver lets go as another takes over.
- **The PS/2 receiver** at chip level: a test program reads two bytes
  from the simulated keyboard.
- **Not checked yet:** the UARTs, the video's picture, the mouse.

### 16. Open questions

For Emily:

1. **The colours.** Fixed IRGB through resistors (no chips) or a palette
   (a RAMDAC such as the IMS G171, one chip in DIP, or a 16 × 12-bit
   palette in an SRAM and three resistor DACs)?
2. **RS-232 levels.** The UARTs' lines are TTL: for a USB serial cable
   as it is, or a MAX232-type level shifter (one chip for both ports'
   TX and RX, two for handshaking)?
3. **PS/2.** The receiver should hold the device off (the clock low)
   until the byte is read, and its clock should go through a Schmitt
   trigger; but holding before the frame's eleventh edge makes the device
   send the byte again, and the receiver's 22V10, nine of its ten
   registers the start bit and the byte, has no room to count the parity
   and stop bits as well. Heron Mini's way
   ([RFC 0041](0041-rfc-heron-mini.md), section 22: a 74HCT14 and a
   74HCT05) or a third 22V10 for both ports' counts: two or three chips.
   As built, a byte that arrives before the last is read is lost.
4. **4 MB?** Four more SRAMs, and bit 21 in PC and MAR (PC's needs
   another 22V10): about 75 packages.
5. **A timer.** The board's only regular interrupt is the video's frame
   (60 Hz); the UARTs have none. An 82C54 would be one chip.
6. **The I/O map** ([7](#7-the-io-space)) is a proposal.
7. **Faster arithmetic** ([13](#13-how-fast)): worth chips?

### 17. Open tasks

- **Instructions not built:** LDM and STM, ADD.B4, the tagged operations
  (09–0D), FFS and POPC, MULU and MULS with the special mode's operand
  (EC, ED) and MERGE (EE). The suite doesn't use them; their blocks stop
  the machine.
- **Booting:** the reset routine should copy the boot flash into RAM
  before entering it (a loop of about ten cycles a byte: 128 KB in 0.2
  s); it doesn't yet.
- **Devices at chip level:** test programs for the UARTs and the
  video's frame.
- **The parts:** the CY7C199C and the 74F181 in DIP at these speeds
  are to be checked for availability.
- **A board:** placing and routing it. A first placement of the draft
  netlist on [RFC 0046](0046-rfc-column-grid.md)'s column grid, at a few
  board sizes, is in [placement.md](0047-rfc-chibi-heron/placement.md)
  (`heron chibi place --write`); the board's size is open.
