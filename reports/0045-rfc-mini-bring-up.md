---
number: 45
type: rfc
title: "Heron Mini: bring-up and debugging"
status: open
date: 2026-10-19
context:
  studies: [mini]
  commit: c437d81
depends-on: [41]
---

# RFC 0045: Heron Mini: bring-up and debugging

How [Heron Mini](0041-rfc-heron-mini.md) gets debugged once it's built,
by Emily at the bench and Claude with the simulators. Part I specifies
what the machine has for it: ODT, a console in microcode on UART 0, which
the debug button enters, with a single step. Part II is design for test:
the order to bring the boards up in, what can be seen and where, how a
fault on the boards is found by comparing them with the simulators, which
run the netlist cycle for cycle, and what more could be built in.

ODT is in the study ([studies/mini](../studies/mini/README.md)): its
microcode in `ucode.py`, the debug request's and the sequencer's
equations in `board.py`, checked on the register-transfer model and at
chip level (`heron mini hw debug`). Part II is a plan, not yet built.

## Contents

- [Part I: Specification](#part-i-specification)
  - [1. ODT](#1-odt)
  - [2. Single step](#2-single-step)
- [Part II: Discussion](#part-ii-discussion)
  - [3. How ODT is built](#3-how-odt-is-built)
  - [4. Bringing the boards up](#4-bringing-the-boards-up)
  - [5. Seeing what it does](#5-seeing-what-it-does)
  - [6. The simulators as the reference](#6-the-simulators-as-the-reference)
  - [7. Stepping microinstructions](#7-stepping-microinstructions)
  - [8. Open questions](#8-open-questions)
  - [9. Open tasks](#9-open-tasks)

## Part I: Specification

### 1. ODT

A console in the microcode, after the PDP-11's (the LSI-11 had its ODT in
microcode too), on UART 0.

- **Entering it:** the debug button ([RFC 0041, 22.1](0041-rfc-heron-mini.md#221-the-debug-button)),
  at the next instruction boundary or `HALT`, whatever I; or reset, when
  the boot flash is erased (its count 2³¹ or more), with the PC and the
  flags word 0. A boot flash with a count of 0 copies nothing and starts
  the program at 0, as before.
- **Starting,** it waits for UART 0 to send what it has, sets it to
  115,200 baud, 8 bits, no parity, its FIFO on and auto RTS/CTS on (the
  program's settings are lost), and sends CR LF, the PC in hex, CR LF and
  the prompt `@`.
- **The program's state** stays as it was: its registers, flags, memory
  and devices change only by what's deposited. ODT's own is the
  microcode's: two of its locations hold the program's PC and flags word,
  and it uses only what's dead at an instruction boundary. Interrupts are
  off while it runs; the devices go on (the video shows, the timer counts,
  a pending interrupt is taken after `G` if I is on).
- **Commands:** a number is up to eight hex digits, either case (more:
  the last eight count). What's typed is echoed, but CR and LF, for which
  ODT starts its own lines. Anything else is answered with `?` and a new
  prompt.

  | Typed | |
  |---|---|
  | *addr* `/` | open the memory word at *addr*, rounded down to a word: shows it and a space |
  | `R`*n*`/` | open register r*n*, *n* one hex digit |
  | `RP/`, `RS/` | open the PC, the flags word (V C Z N I in bits 0–4) |
  | *value* CR | put *value* in the open location; close it. CR alone closes it |
  | *value* LF | the same, then open the next word (*addr* + 4, on a new line with its address) or register (r*n* + 1, after r15 r0); for the PC or the flags word, close it |
  | `G`, *addr*`G` | go on at the PC, or at *addr* |
  | `S`, *addr*`S` | one instruction at the PC, or at *addr*, then ODT again with the new PC |

  A session, as the chip-level test has it (the button pressed in a loop):

  ```
  0000002A
  @R2/00001234 5678
  @1000/CAFEF00D
  00001004/00C0FFEE 12345678
  @RP/0000002A
  @S
  0000002C
  @R3/00000000 1
  @G
  ```

- **Reads have their effects:** opening a device's register reads it (a
  UART's receive register gives up its byte). Words only: a byte register
  is read as its word, at the word's address.

### 2. Single step

`S` runs one instruction and stops at the boundary after it, whatever the
instruction: a jump stops at its target, `HALT` at itself. If the flags
word ODT restores lets a pending interrupt in, the interrupt's entry runs
instead and the step stops after the handler's first instruction.

## Part II: Discussion

### 3. How ODT is built

- **In microcode,** so that it works with nothing in the RAM or the boot
  flash, with the stack wrong, interrupts off and the program's state as
  it was: what a machine being brought up has. It's 446
  microinstructions in the control store's general page (5,192 of its
  8,192 words used now), with the program's PC and flags word in the
  microcode's last two free locations. A monitor in software, in the boot
  flash, could do more (disassembly, breakpoints, loading files) and is
  better written as a program; ODT can load one, or anything else, by
  hand or by a host pasting a session at full speed, which auto RTS/CTS
  makes safe.
- **The single step costs no chip and no wire:** two 22V10s' equations.
  ODT leaves through a page of the control store nothing else uses
  (U = 011): the sequencer's 22V10 makes that page for a halt
  microinstruction that also has LDPC (with PCCOND 3, a jump that's never
  taken), a combination nothing else uses, from inputs it already has.
  The debug request's 22V10 sees the page (it already watches U for the
  interrupt entry), arms the step, and at the next decode that goes
  ahead, the stepped instruction's, sets the debug request and raises the
  pending interrupt at once, so that the instruction after it doesn't
  start, even if the stepped one takes a single cycle. The 22V10s keep
  the pins the boards have them on; the step's flip-flop takes one that
  was free.
- **Checked:** on the register-transfer model, a program counting in a
  loop with interrupts off, the button pressed, a session that reads and
  changes a register and memory, reads the PC, single-steps, and lets it
  go on (its transcript exactly); reset with an erased boot flash; and
  the same session at chip level, against the transcript but for where
  the press found the loop (`heron mini hw debug`). The fast simulator
  doesn't model the button, so not ODT either.

### 4. Bringing the boards up

The order, each stage checking what the next relies on:

1. **Power:** each board alone, its current limited; the clock chip's
   3.3 V rail.
2. **The clocks:** the clock chip, programmed beforehand (a blank one
   gives nothing: [RFC 0041, 20](0041-rfc-heron-mini.md#20-the-clock)),
   its three outputs, the switch, the master clock and the clock
   generator's phases, on a scope.
3. **The control store and the sequencer,** with bring-up images in the
   flashes in place of the microcode (generated by the study, **open**):
   *count*, every microinstruction's next address its own plus one, so
   that the micro-address counts through the general page and a logic
   analyser on the Y lines sees a counter; *walk*, each control bit in
   turn, so that the microinstruction register's outputs can be checked
   one at a time.
4. **The datapath, by self-test microcode** (another image, **open**):
   the register file, the ALU and the result multiplexer on patterns, MQ,
   a march over both RAM banks, UART 0 in loopback; failures on the two
   LEDs, then on UART 0 once it works.
5. **The real microcode and ODT:** memory and registers by hand, small
   programs deposited and stepped.
6. **The rest:** the boot flash, the suite's programs (pasted through ODT
   or programmed into the boot flash), the devices, the video's modes.

### 5. Seeing what it does

- **The ribbons are probe points.** Every signal between boards is on an
  IDC header with a ground beside it, so a pass-through adapter (two
  headers and a short cable) lets a logic analyser clip on anywhere: as
  the boards are cut, the micro-address (Y0–12 and YU0–2 between cpu1
  and cpu2), the data and B buses, much of the microinstruction, the
  video's address, the I/O strobes. About 250 signals, for no parts.
- **A header for what doesn't cross** (**open**): CLK, DECGO, PEND, the
  debug request, the length class, HOLD, a few strobes: a 2 × 10 header on
  cpu1, one part.
- **LEDs** (**open**): beside the control register's two (software's),
  RESET, HOLD, the debug request and the 3.3 V rail, about one part.
- **Sockets:** the control store's sixteen flashes (PLCC-32 sockets) and
  the 22V10s, which a fix may reprogram; the clock chip on its adapter.

### 6. The simulators as the reference

The register-transfer model and the chip-level simulator run the same
microcode and netlist cycle for cycle, so a fault on the boards shows as
the first cycle where the real machine does something else:

1. **Capture** the micro-address (16 lines) and DECGO from reset, with CLK
   as the state clock, on a cheap USB logic analyser (16–32 channels,
   sigrok and PulseView), a program running; ODT's session or the
   console's output for what the program saw.
2. **Compare** (`heron mini trace`, **open**): the same program on the
   model, the first cycle that differs, its microinstruction, and the
   nets the difference depends on in the netlist, with their chips and
   boards: where to put the probe next.
3. **Narrow it down** with more channels on those nets, the chip-level
   simulator's waveform of the same cycle beside the analyser's.

That's how Emily and Claude would work on it: Emily runs the machine and
captures (analyser files, ODT transcripts, scope readings); Claude runs
the simulators, compares and says which chip, which pin, what it should
have been. The boards' exported netlists name every pin.

### 7. Stepping microinstructions

A step of one microinstruction would let a meter or LEDs read static
levels, and an analyser in state mode see every cycle. Two ways
(Emily's debug clocking, **open** for later):

- **A step clock:** the master clock's switch takes a third source, a
  debounced button or a header's signal, selected by a jumper; the video
  stops with it. About 2 chips.
- **A hold:** a header's line into the hold logic stops the CPU at the
  next cycle's tick 4, as an I/O access's wait does, while the master
  clock and the video run on; a button releases one cycle. About 2 chips
  and a 22V10's equations. With ODT's instruction step, the more useful.

### 8. Open questions

For Emily:

1. **ODT's commands:** enough to start with? Breakpoints (an unused
   opcode that enters ODT, microcode only), a binary load, a register
   dump.
2. **Stepping microinstructions:** which, if either (7).
3. **The test header and the LEDs** (5).

### 9. Open tasks

- **The bring-up images:** *count*, *walk* and the self-test (4).
- **The trace comparison** (6), once an analyser is chosen.
- **The header and LEDs** in the netlist, once decided.
- **ODT in the fast simulator:** the button and the step in the Rust
  engine.
