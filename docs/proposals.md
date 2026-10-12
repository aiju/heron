# Design proposals

Every idea raised in the design discussions so far, so none get lost. It's
organised by topic, not by when it came up.

Each proposal has a **status**:

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | Evaluated with numbers ([evaluation.md](evaluation.md), [evaluation-v1.md](evaluation-v1.md)) |
| **recommended** | Suggested for the next draft or hardware round |
| **open** | Discussed, not decided |
| **rejected** | Decided against, with the reason, so it doesn't get re-proposed without new evidence |

Chip counts are rough estimates, scaled from the 98-chip draft 0 design.

## Contents

1. [Direction and ambition](#1-direction-and-ambition)
2. [Instruction set](#2-instruction-set)
3. [Floating point](#3-floating-point)
4. [Microarchitecture](#4-microarchitecture)
5. [Memory system and buses](#5-memory-system-and-buses)
6. [I/O](#6-io)
7. [Channels and DMA](#7-channels-and-dma)
8. [Video](#8-video)
9. [Operating system support](#9-operating-system-support)
10. [MMU](#10-mmu)
11. [Address registers with hidden state](#11-address-registers-with-hidden-state)
12. [Big ideas](#12-big-ideas)
13. [Wishes from the program writers](#13-wishes-from-the-program-writers)
14. [Open questions](#14-open-questions)
15. [Offered next steps](#15-offered-next-steps)

## 1. Direction and ambition

- **Put the ambition into the system, not raw CPU speed.** **open.**
  - Designing big is cheap now (netlist language, simulators, timing
    analysis). Building big isn't: wiring, signal integrity, parts.
  - Software will be the long pole: a C compiler, an OS port, drivers.
  - Three directions:
    1. A whole computer: OS, compiler, storage, terminals, front panel.
       Biggest payoff. Bill Buzbee's Magic-1 (~200 TTL chips, runs Minix)
       is the calibration point.
    2. Bigger: 32-bit (below).
    3. Faster: pipelining and caches. Lowest payoff per effort.
- **OS ambition ladder.** **open.** Aim for the top, build in stages:
  1. Resident monitor: needs a boot ROM.
  2. Single-tasking disk OS (CP/M, OS/8): needs storage, a system-call
     convention and a loader.
  3. Unprotected multitasking: needs timer preemption and relocatable
     programs.
  4. Protected multi-user (V6 Unix on a PDP-11/40): needs modes, an MMU, a
     kernel stack and faults.
- **A 32-bit architecture, built 16 bits wide first** (the System/360
  Model 30 and the 68000 did this). **adopted** (draft 1), **measured.**
  - A 32-bit address space removes the workarounds for 64 KB: banking,
    video windows, I/D spaces.
  - It gives encoding room and suits C and existing software. It's
    period-authentic: VAX-11/780, Eclipse MV/8000.
  - Rough chip counts:

    | Machine | Chips |
    |---|---:|
    | 16-bit full system | ~125 |
    | 32-bit on a 16-bit datapath | ~140–150 |
    | Full-width 32-bit | ~165, ~190–200 with the system features |

  - Measured: a 32-bit ISA on a 16-bit datapath and bus is *slower* than
    draft 0 on ordinary code. It only gains on multiply/divide. See
    [section 4](#4-microarchitecture).
- **Keep 16-bit instruction parcels with 0–2 extension parcels**
  (precedents: SuperH, 68000, Thumb). **adopted.**
  - Alternatives for 32-bit constants, both **rejected**: literal pools
    (SuperH; awkward pool placement) and a prefix instruction (the
    Transputer's `pfix`; hidden state, interrupt shadow).
  - Fixed 32-bit instructions would suit a future pipelined full-width
    implementation better. **rejected** for now.
- **Toolchain:** object files and a linker, a stable system-call ABI, and a
  language above assembly (a small C compiler, Forth, or BASIC). **open.**
- **Software in simulation first:** a toy kernel and a compiler port on the
  instruction-level simulator, ahead of hardware. **open.**
- **Build in stages on a backplane of cards** (CPU, memory, then MMU and I/O
  cards). Above ~150 chips, only PCBs or a backplane, no breadboards.
  **open.**

## 2. Instruction set

### 2.1 Adopted in draft 1

These came from the draft 0 evaluation; draft 1 has them
([isa-v1.md](isa-v1.md)):

| Proposal | Evidence or reason |
|---|---|
| Hardware `MULU`/`MULS`/`DIVU`/`DIVS`, `HI` register for the high half and remainder, `DIVUL` 64/32 | Software multiply/divide was 61–80% of cycles in mandel, matmul, bignum, interrupts |
| `HI` as the multiply/divide shift register (instead of `MULH`/`REM`) | One divide gives quotient and remainder; the product isn't computed twice |
| `INC`/`DEC` (and 1a `ADDI`) set only N and Z | Overwriting C forced the shape of the multiply loop and caused a flag bug |
| `SAVE ra-rb` / `RESTORE ra-rb` | `PUSH`/`POP` were 34% of queens' cycles and 21% of fib's |
| `SWI #n` with its own vector | The shared trap vector meant decoding `[PC − 2]` |
| `SETcc` | Programs had no set-on-condition; Life used a `NEG`/`ADC` trick |
| Shifts by n (immediate or register), `ROR` | Draft 0 shifted one bit per instruction; `SWAB`+`ZXT` were shifts by 8 in disguise |
| `CLZ`, `SWAP` (halves), `SXB`/`ZXB`/`SXH`/`ZXH` | Normalising, bitmaps, halfword work |
| Sticky Z for `ADC`/`SBC` | A 64-bit compare needs only one branch |
| `MFSR`/`MTSR` special registers (flags, `HI`) | Generalises `MFF`/`MTF` |
| PC-relative `LEA` and addressing | Position-independent code; replaces most `MOV r, #address` |
| Halfword and sign-extending loads | 32-bit machine |
| Immediate kinds: signed 16, unsigned 16, 16 shifted left 16, 32 | Most constants still fit 2 parcels |
| Jumps and calls with 16-bit PC-relative displacements, 32-bit absolute form | Absolute 32-bit targets would be 3 parcels |
| Vectors 4 bytes apart: reset, IRQ, illegal, SWI, divide error, address error | |
| Word accesses 4-aligned, halfwords 2-aligned; misaligned accesses trap | |
| One escape opcode kept free (1a op F) | Future growth, floating point |

### 2.2 1a vs 1b

**measured.** Both encodings were specified, built and measured on 20
programs ([evaluation-v1.md](evaluation-v1.md)).

- **1a, RISC-like:** load/store, register-register ALU, short and long
  load/store forms, 8-bit immediates.
- **1b, CISC-like** (IBM 360 RX / 68000 / x86 style): every main
  instruction is `F D M R`, one register plus one addressing mode out of 14:
  - register, quick constant (−16…15), `[R]`, `[R + d16]`, `[sp + 4R]`;
  - indexed `[R + Rx·s + d8]`, `[R]+`, `-[R]`;
  - byte and half variants;
  - PC-relative and absolute addresses, 16/32-bit constants.
  - At most one memory operand per instruction, which keeps faults
    restartable. Size is part of the mode. Indirect `JMP`/`CALL [mem]`.
- **Result:**
  - 1b is 7–10% faster, runs 13% fewer instructions and has 3% less code.
  - The gain is concentrated in the VM (−24%), Life (−16%) and pointer
    walking. Register-bound programs are within 3%.
  - Most of the gain is auto-increment. 1b's 4-bit constants cost it code
    size, and its encoding is full.
- **Before 1b, measured on draft 0:**
  - 4.5% of draft 0 instructions were a load whose value fed the next ALU
    op; 97% of those loads were bytes, so memory operands need
    zero-extending byte forms.
  - Memory-destination operations were 0.4%, all in fib. **rejected.**

### 2.3 Recommended for draft 2

From [evaluation-v1.md](evaluation-v1.md):

- **Base draft 2 on 1a.** **recommended.**
- **Post-increment and pre-decrement loads and stores** in 1a's op F: byte
  and word `[r]+`, word `-[r]` (pushes), byte `-[r]` (backwards loops), half
  if it fits. **recommended.** Estimated to recover at least 60% of the gap
  to 1b, and it fixes the "`ADDI` sets Z" ordering problem.
- **Jump through a table** (`JMP [table + r*4]`) in a free system function.
  **recommended.** The VM's dispatch is 9 cycles in 1b against 18 in 1a.
  Matters for interpreters and command dispatch.
- **Memory increment** (`INC [mem]`, `ADD [mem], r`). **recommended.**
  Counters, interrupt handlers; fib's call counter was 30% of its time.
- **Three-operand add** (`ADD rd, rs, rt`), like 1b's `LEA [rA + rB*s]`, if
  an encoding turns up. **open.**

### 2.4 More instruction ideas, not yet decided

| Idea | Cost | Notes | Status |
|---|---|---|---|
| Shifts and rotates with a separate destination (`ROR rd, rs, #n`) | microcode | `MOV` was 25–27% of sha256's instructions | **recommended** |
| Multiply-accumulate into `HI:LO` (`MULA`), fixed-point multiply (multiply, then shift by n) | microcode | Multiply was 50% of mandel; audio, graphics, DSP | **open** |
| Bit-field extract/insert; byte reverse (`REV`) | microcode | Protocols, file formats, graphics; SHA needed big-endian loads | **open** |
| Packed byte arithmetic `ADD.B4` by gating carries at byte boundaries | 1–2 chips | Pixel arithmetic, zero-byte search. Saturation and per-lane flags cost much more | **open** |
| Zero-overhead loops (`LOOP count, end`) | ~10 chips (PC comparator) | DSP style; saves ~5 cycles per iteration in tight loops; modest here | **open** |
| `SKIPcc` (PDP-8 skips, Thumb-2 `IT`) | microcode | Branch-free min/max and conditional moves | **open** |
| Interruptible block move/fill/compare (like `REP MOVS`; progress in registers) | microcode | Page copies, screen clears; ~2 bus cycles per halfword against ~14 for a loop | **open** |
| Block I/O instruction (Z80 `INIR` style, interruptible) | microcode | ~5–6 cycles per word against ~12–15 for a software loop | **open** |
| Atomic exchange / test-and-set | microcode + bus lock | Only once DMA or a second CPU shares data structures | **open** |
| Popcount, find-first-set | microcode | Scheduler and allocator bitmaps | **open** |
| A 12-bit `BSR` (±4 KB, SuperH style) in op B | opcode | Saves ~9% of code size and no cycles; op B went to the shift group instead | **rejected** |

### 2.5 Rejected, with the evidence

| Proposal | Why not |
|---|---|
| Three-operand ALU throughout | `MOV`+op pairs were 1% of draft 0 instructions (12% in queens); doesn't fit 16-bit nibble fields |
| Compare-and-branch | `CMP`;`Bcc` is 5.4% of instructions, but a fused form needs an extension word: 2 parcels either way, ~1 cycle saved |
| `DBNZ` (decrement and branch) | 2.3% of instructions; needs a whole major opcode |
| Wider branch offsets | 95% of executed branches fit a 6-bit offset, 100% fit 8 bits; the assembler relaxes the rest |
| Link register instead of pushing the return address | ~2% of cycles, gives up a register |
| ARM-style conditional execution | No spare bits |
| 16-bit ALU ops alongside 32-bit (68000 `.W`/`.L`) | Doubles the ALU encodings and bakes the narrow implementation into the ISA |
| Decimal (BCD) arithmetic | No use |
| Separate I/O instructions (`IN`/`OUT`) | No opcode space; memory-mapped I/O works with every addressing mode |
| Register + register addressing in a load/store ISA | Not worth a major opcode; `[label + reg]` covered static arrays in 16-bit space (see the 1b indexed mode for the alternative) |

## 3. Floating point

**open**, and nothing needed yet. These decisions touch the base ISA,
so they should be settled before it's final:

- **Leave a hole:** one escape opcode with a 16-bit *command word* (like the
  68000's "line F" and the 68881, or the 8086's `ESC` and the 8087). It
  traps when no FPU is present.
  - Slow operations don't need compact encodings. The command word gives
    room for FP and later for MMU operations or block moves.
  - Before hardware exists, a trap handler emulates FP in software; same
    binaries throughout.
  - `FFFF` must stay illegal, so erased memory still traps.
- **FP registers:** a separate file, e.g. 16 × 64-bit, in the spare
  register-file SRAM. Nearly free in hardware, and doesn't take integer
  registers. The alternative, floats in integer registers (RISC-V's Zfinx),
  is simpler but doubles need register pairs.
- **Compares:** `FCMP` sets N, Z, C, V the ARM way (unordered sets C and V),
  so the existing `Bcc` conditions work and no new branches are needed.
- **Status and vectors to reserve:**
  - an FP-enable bit (for lazy context switching: FP instructions trap
    while it's off);
  - an FP exception vector;
  - a special-register number for FP control/status (rounding, sticky
    flags).
- **Can wait:**
  - instruction list and precision model (registers hold doubles,
    single precision on load/store like the 68881; or per-instruction
    precision);
  - IEEE 754, flushing tiny numbers to zero at first.
- **Implementation:**
  - microcode on the integer datapath (very roughly 30–80 cycles for a
    single-precision add or multiply);
  - or a memory-mapped period FPU: 68882 in peripheral mode, Am9511;
  - or software only.
- **The general "future-proofing kit":**
  - an escape opcode with a command word;
  - every unused function code traps;
  - `0000` = `HALT`, `FFFF` = illegal;
  - reserved bits in the status word (must be written as 0);
  - reserved vectors and special-register numbers.

## 4. Microarchitecture

| Proposal | Status | Notes |
|---|---|---|
| 32-bit datapath (D32) instead of 16-bit (D16) | **measured**, **recommended** | ~22% fewer cycles; ~25–35 more chips. Draft 1 starts paying off here: 1.6–1.7× draft 0 overall |
| Overlap the next fetch with the last cycle (draft 0 style) | **measured**, **recommended** | 17–22% fewer cycles than a separate fetch cycle; ~0–2 chips |
| Wide fetch: 32-bit bus plus two-parcel prefetch buffer | **measured** | ~10% fewer cycles, single-cycle word loads; +10–15 chips. Only D32-wide beats draft 0 on every program. If the datapath must be 16 bits, keep the 32-bit bus: D16-wide is 1.36–1.48× draft 0 |
| Write results back to the register file in the same cycle | **open** | 33% of draft 0's cycles go to separate write-back (CPI 2.1 → ~1.4), but it needs much faster register-file parts or a slower clock |
| Pipelined microinstruction register | **open** | ~6 chips; removes ~100 ns of microcode ROM access from every cycle |
| Fix bus contention when the B bus changes source | **recommended** | Up to 67 ns at worst-case delays in draft 0 |
| Separate instruction bus (Harvard) for speed | **rejected** | Would save 1.6% of draft 0's cycles; the bottleneck is register write-back |
| Pipelining, caches | **rejected** for now | Lowest payoff per effort; hazards and forwarding in TTL multiply the debugging |
| ALU from in-production parts | **open** | 74181/74182 are new-old-stock only. Alternative: 74HC283 adders plus multiplexers for the logic functions |
| 6502-style page-crossing shortcut for address arithmetic on D16 | **adopted** (timing model assumption) | Add the low halves; a second cycle only when the upper half changes |
| Extension parcels latched, not fed straight into the ALU | **adopted** (timing model assumption) | Draft 0's critical path was the 16-bit immediate going from memory straight into the ALU |
| Scaled index (`*2`/`*4`/`*8`) | **open** | Needs a shifter on the B bus (~8–16 chips), or up to 3 extra cycles |
| `.align` that pads code with `NOP`s | **recommended** | Wide-fetch cycles depend on loop alignment by up to 15%; today `.align` pads with zeros, which are `HALT` |
| Parts availability | **open** | Fast SRAM is no longer made in DIP; the 55 ns flash is PLCC only; no 74ACT30/688 |

## 5. Memory system and buses

| Proposal | Status | Notes |
|---|---|---|
| **Bus release**: request/grant, three-state address and control drivers (74HCT257 instead of 74HCT157, gated read/write strobes) | **recommended**, design in now | Shared by DMA, a front panel acting as bus master, and debugging; cheap now, painful to retrofit |
| **Two memory buses**: CPU-private main RAM plus a shared memory on the system bus for video, display lists, DMA and disk buffers (Amiga chip/fast RAM) | **recommended** once video or DMA arrive | No cycle stealing; arbitration stays off the CPU's critical path. Costs: slower CPU access to shared memory, two kinds of memory in software, a bridge |
| **Interleaved memory time slots** (Apple II, BBC Micro): the RAM is ~9× faster than the CPU cycle, so give devices their own slots | **open** | DMA and video become free, but the CPU's address must be ready early in the cycle; fits a pipelined-microcode redesign |
| Separate instruction and data address spaces (PDP-11/45 style) | **rejected** with the move to 32-bit | Doubled the per-process space on a 16-bit machine for one MMU address bit |
| Dual-port SRAM | **rejected** | Expensive, small sizes only |

## 6. I/O

- **Memory-mapped I/O page** at the top of memory. **adopted.**
  - In draft 1 it's at `0xFFFFFF00`, reachable with a sign-extended 16-bit
    absolute address.
  - A side effect of load/store: no accidental read-modify-write of device
    registers.
- **16 slots of 16 bytes**, one 74HCT154 on address bits 7–4. Each slot
  gets a select line, a shared IRQ and reset (Apple II / RC2014 style).
  **open.**

  | Slot | Device |
  |---|---|
  | 0 | console UART (16C550) |
  | 1 | CF card (8-bit IDE) |
  | 2 | RTC (DS12887) |
  | 3–13 | free |
  | 14 | MMU registers |
  | 15 | system: timer, interrupt controller, front panel, boot-ROM disable |

- **Interrupts:** one level-triggered IRQ plus polling to start. Later,
  PDP-11-style vectored priorities: a 74HCT148 encoder, a priority field in
  the flags compared against the request level, and a 74HCT541 putting the
  vector on the bus (~3–4 chips). That gives nesting. **open**; reserve the
  priority field in the flags now.
- **Read strobes gated with a clock phase**, like writes. **recommended.**
  One gate. Otherwise a decode glitch is a phantom read, e.g. a lost UART
  character.
- **Automatic wait states for I/O** by stretching the clock, decoded early
  from MAR. **recommended.** Every device gets ~2 µs; I/O is rare, so the
  cost is invisible. A per-device READY line is the more fiddly
  alternative.
- **8-bit peripherals on the low byte lane**, one register per even
  address. **adopted.**
- **74HCT245 transceivers** between the CPU board and a backplane (~20 ns).
  **open.**
- **Front panel:**
  - **Through the microcode** (PDP-8 style): the switch register is a B-bus
    source, and a panel-mode bit on a spare microcode address line selects
    LOAD ADDRESS / DEPOSIT / EXAMINE sequences. Single-stepping instructions
    or micro-cycles falls out. **recommended.**
  - **As a bus master:** shares the bus-release mechanism. **open.**
- **Storage:** a CompactFlash card in 8-bit IDE mode (~300 KB/s by polled
  I/O). **open.** File system: FAT (swap cards with a PC) or a small
  Unix-style one plus a host tool to build images.
- **Console:** a serial terminal first (a VT100 or an emulator), with a
  16C550 UART with FIFO. **recommended.** At 9600 baud, character-by-
  character interrupts cost ~5% of the CPU per busy terminal.
- **Keyboard:** PS/2, a shift register, bit counter and interrupt (~4
  chips). **open.**

## 7. Channels and DMA

Background: a CF sector by software loop is ~12–15 cycles per word, ~3,500
cycles per 512-byte sector. Terminals cost ~5% of the CPU each.

| Option | Cost | CPU cost per word | Status |
|---|---|---:|---|
| Block I/O instruction in microcode | microcode | ~5–6 cycles | **open**, a good first step |
| **Microcoded channel** (like the integrated channels of the small System/360s): a device request runs a microcode sequence between instructions; address, count and command live in spare register-file SRAM | ~5 chips | ~5–7 cycles | **recommended first** for a timesharing system |
| **Cycle-stealing DMA**, optionally following descriptor chains ("channel lite") | ~15–20 chips per channel, plus bus release | ~1 stolen cycle | **recommended** once the OS swaps or multitasks for real: disk first, then terminal output (DH11-style output DMA) |
| DMA in its own memory time slot | memory-timing redesign | 0 | **open** |
| Intelligent terminal multiplexer: 4–8 lines with buffers, one interrupt per line or buffer | a lot in TTL; one chip with a microcontroller | turns ~1000 interrupts/s per terminal into ~10 | **open**: is a microcontroller in a peripheral OK? 1980s minis did it |
| CDC 6600-style peripheral processor "barrel": one shared datapath, 8 virtual I/O processors with registers in SRAM | ~60–100 chips | – | **open**, a project of its own |
| 82C37 off-the-shelf DMA chip | 1 chip | – | **rejected**: 8-bit, 8085-style timing |

**Software side:**
- "Start channel" is a store to a command register; no new instructions.
- I/O becomes asynchronous: request queues, completion interrupts.
- DMA uses physical addresses, so buffers must be pinned and contiguous.

## 8. Video

**First question: what's the screen for?** A console (~30 chips) or
graphics (address space and drawing speed bite). Minicomputers mostly used
serial terminals; built-in video is home-computer territory. **open.**

**Text-mode VGA card** (~30 chips). **open**; recommended after the serial
terminal.
- 80×30 characters, 8×16 font, 640×480 at 60 Hz (25.175 MHz pixel clock,
  3.15 MHz character clock).
- Character plus attribute per 16-bit word, 16 foreground/background
  colours, 2-bit-per-channel resistor DAC.
- A 128-word row stride, so the address comes straight off the counters.
- Hardware scroll (a start-row register through two 74HCT283) and cursor
  (two 74HCT688 plus blink).
- Redefinable font in SRAM; posted writes so the CPU never waits.
- A 6845 CRTC could replace the timing and addressing (less authentic).

**Where screen memory lives:**

| Option | Notes |
|---|---|
| Video RAM in a window of the CPU's address space | best for text |
| Behind I/O ports with an auto-incrementing address (TMS9918 style) | best for bitmaps; zero address space |
| Dual-port SRAM | expensive |
| Main memory, interleaved | needs the memory redesign |
| Physical pages mapped by the MMU | the clean long-term answer |

**Graphics options:** **open.**
1. A bitmap plus a blitter on the card that fills and copies rectangles:
   a screen clear drops from ~65 ms to ~1 ms.
2. **Display lists** (below).
3. A vector display on an oscilloscope (two DACs, a line walker; GT40 and
   Spacewar style).

Avoid software-generated video (ZX81, Gigatron): it would eat a microcoded
CPU. **rejected.**

**Display-list processor** (ANTIC bands plus copper-style register writes;
the DEC GT40 was the minicomputer precedent). **open**, 40–60 chips (~35
minimal).
- **Instruction set**, nibble-aligned:

  | Word | Instruction |
  |---|---|
  | `1 m nn` | BAND mode `m` for `nn+1` units |
  | `2 m nn` + addr | BAND with a new data pointer |
  | `3 r vv` | PALETTE |
  | `4 r 00` + value | SET control register |
  | `5 0 nn` | BLANK |
  | `6 0 00` | IRQ |
  | `8 0 00` + addr | JMP |
  | `9 0 00` + addr | JVB (jump and wait for vertical blank) |

- **Modes:** 80- and 40-column text; 640-wide bitmaps at 1 and 2 bits per
  pixel; 320-wide at 4 bits per pixel. Bit 3 of the mode doubles lines.
- **Hardware:**
  - 64K×16 of video RAM on the card;
  - four fixed ~80 ns slots per character time (display data, font, CPU,
    display-list processor);
  - an EEPROM-sequenced processor running in horizontal blank (~20 memory
    slots per line);
  - a stride counter for virtual screens;
  - a 25 MHz pixel pipeline in 74AC/F with a 16-entry palette and fine
    scroll;
  - CPU access through a window or a data port; vertical-blank and
    display-list interrupts.
- **What it gives software:** scrolling by one store, split screens,
  tear-free double buffering, raster effects. A `FILL`/`COPY` blitter
  instruction could come later.
- **Vector variant:** `MOVETO`/`LINETO`/`POINT`/`TEXT` with a
  Bresenham-style engine and X/Y DACs.
- **Prototype first:** a Python model of the card in the simulator that
  renders PNGs.

## 9. Operating system support

- **Privilege mode bit** in the status word, saved by interrupt entry and
  `RTI`. **recommended.**
  - User mode traps `EI`/`DI`/`HALT`/`MTSR`/`RTI`, map writes and I/O.
  - `RTI`/`MTF` in user mode must not be able to set the kernel bit.
  - The microcode can use a spare address line for the mode.
- **Separate kernel stack / banked registers** via the register-file SRAM
  address lines. **recommended.**
  - The mode bit on an address line gives the kernel its own registers.
  - A process-number register gives every process its own registers.
  - Catch: the kernel can't see the user's argument registers, so it needs
    "move from user register" (PDP-11 `MFPI`-like).
  - Catch: `r0` must be forced to zero in logic, not by the reset sequence.
- **Restartable instructions:** every instruction commits nothing before its
  last memory access. **adopted** in draft 1's rules; see the audit in
  [section 10](#10-mmu). (The 68000 couldn't restart after bus errors, and
  the 68010 had to fix it.)
- **Relocation:** position-independent code (PC-relative addressing), or a
  relocating loader with assembler relocation tables, or an MMU. **adopted**
  (PC-relative modes in draft 1).
- **System calls:** `SWI #n` with its own vector. **adopted.** Return errors
  in the carry flag by editing the saved flags word (the PDP-11 Unix
  trick). **open.**
- **Trace bit** (trap after every instruction) plus `SWI` as a breakpoint
  gives a real debugger. **recommended.**
- **Boot:** a boot ROM overlaid on low memory at reset, switched out by an
  I/O write. Or toggle in a loader from the front panel. **open.**
- **Reference numbers (draft 0):**
  - interrupt latency ~7 µs at 2 MHz;
  - context switch ~170 cycles (~30 with banked registers);
  - system-call round trip ~40 cycles plus the work.

## 10. MMU

What the OS needs: separate address spaces, protection (user/kernel, read
only, no execute), restartable faults (demand paging, copy-on-write `fork`,
growing stacks), and sharing.

**Options considered:**

| Design | Gives | Cost | Status |
|---|---|---|---|
| Base/limit registers | relocation and protection, one block per process | ~6 chips (an adder in the address path) | **open** |
| Protection regions (ARM MPU style) | protection only; needs position-independent code | ~4 chips per boundary | **open** |
| Segments (PDP-11 style, 8 per space) | a few variable pieces | ~15 chips | **open** |
| **Flat page map in SRAM** | paging, no flushes | ~12–15 chips | **recommended** |
| Two-level map (Sun-2 style) | sparse, larger spaces | ~20 chips, two lookups in series | **open** |
| Tagged translation cache plus page-table walk in microcode (as the VAX did) | full 32-bit spaces | ~20 chips plus microcode | **open**, upgrade path |
| Address registers as the translation cache | see [section 11](#11-address-registers-with-hidden-state) | ~10–14 chips | **open** |

**The flat page map proposal:**
- **Shape:**
  - 16 MB virtual per process in 4 KB pages (4096 pages);
  - 16 contexts in the map SRAM (64K entries);
  - entry = 12-bit physical page plus V/W/X bits (24 bits);
  - up to 16 MB physical;
  - a context switch is one register write.
- **Address path:** MAR → map SRAM → RAM. A 55 ns DIP SRAM adds 55 ns,
  which fits a cycle of 300 ns or more. Instruction fetches are translated
  too.
- **Hardware:** 3 × 128K×8 SRAM, a context register, a path for writing
  entries, check gates, a fault-address latch and a fault-reason register.
- **Referenced and dirty bits in software:** map pages read-only; the first
  write faults. The same mechanism gives copy-on-write.
- **Supervisor mode is untranslated.** The kernel uses `LDU`/`STU` (loads
  and stores through the user map, like the 68010's `MOVES`) for copying to
  and from user memory.
- **More than 16 processes:** reassign contexts (rewriting 4096 entries
  takes a few ms).

**Draft 0-era variant:** 16 pages of 4 KB covering the 64 KB space, an SRAM
indexed by process number, 1 MB physical (2 × 512K×8), ~4–6 chips, about 5%
slower clock.

**Restartability audit (draft 1):**
- Single-access instructions update registers after the access, including
  auto-increment.
- `CALL` and `JMP/CALL [mem]` read the target and push before changing the
  PC or `sp`.
- `SAVE` writes first and moves `sp` last; re-running it is idempotent.
- `RESTORE` re-runs idempotently (`sp` is never in the range).
- Prefetch faults are held back until the parcel is used.
- Interrupt entry pushes onto the kernel stack, so it never faults.
- Block moves must keep their progress in registers.
- On a fault the microcode: stops the write, latches the address and reason,
  saves the PC of the faulting instruction, and traps.

**ISA additions:**
- user/supervisor bit; a separate supervisor `sp`;
- privileged instructions;
- special registers: context, map address/data, fault address, fault
  reason;
- vectors: page fault, privilege violation;
- I/O from supervisor mode only.

**Staging:**
1. A socket for the map chips plus a bypass jumper on the first boards.
2. The flat map.
3. Tags plus a microcode walker, if ever.

## 11. Address registers with hidden state

Proposed by Emily: split the registers into D and A registers like the
68000, and give the A registers extra hidden state that caches MMU lookups
and serves as protection. **open.**

**Precedents:**
- the 286/386 segment registers' hidden descriptor cache (the closest);
- 68000 address registers;
- the CDC 6600's A registers with side effects;
- the Cambridge CAP computer and CHERI capability registers.

**The D/A split:**
- **Only A registers address memory,** so every access names one. Pointer
  operations (`LEA`, `ADDA`, auto-increment, A-to-A moves) keep or update
  the hidden state. Loading an A register from memory or from a D register
  invalidates it.
- **Pointer arithmetic doesn't set flags** (fixes 1a's "`ADDI` sets Z").
- **A separate address adder** runs alongside the data ALU (68000 style),
  so auto-increment and `[A + d]` are free.
- **`sp` and `PC` are A registers:** cached stack page, and cached code page
  (instruction-fetch translation for free).
- **Register budget** (from the 20 draft 1a programs):
  - Pointer registers: seven programs use up to 7, but rarely more than 3–5
    in one loop.
  - Data registers are the pinch: sha256 needs 9–12, mandel 8.
  - So A registers need some arithmetic (`ADDA`/`SUBA`/`CMPA`/`MOVEA`), and
    indexed addressing should take a D register as the index
    (`[A2 + D3*4]`).

**Flavour 1: the A registers are the translation cache.**
- **Hidden state per A register:** physical page, R/W/X, valid. About 24
  bits in ~3 extra SRAMs beside the register file.
- **Accesses:** the physical address is the cached physical page plus the
  low 12 bits, with no lookup in the memory path.
- **Misses:** microcode walks a two-level page table in RAM (~10 cycles).
- **After pointer arithmetic,** a page-crossing detector compares bits
  31..12 and invalidates on change. It's the D16 page-crossing logic at
  4 KB.
- **What it gives:** full 32-bit sparse address spaces, page tables in RAM,
  any number of processes, a context switch = load registers plus page-table
  base. ~10–14 chips.
- **Weak spot: pointer chasing.** Each newly loaded pointer costs a walk,
  roughly +40% on bst-like code. Fix: a small shared direct-mapped
  translation cache behind the A registers (~8–10 chips).
- **Loose ends:**
  - `[A + large d]` landing in another page: a one-off lookup;
  - globals through a "global pointer" A register;
  - when the kernel changes a page table it must invalidate the current
    registers' hidden state.
- **My pick**, with hidden state sized so flavour 2 can be added later.

**Flavour 2: the A registers are segment registers (per-object bounds).**
- **Pointers** are (segment, offset), e.g. 12 + 20 bits. Loading an A
  register fetches the segment's descriptor (base, limit, rights) from a
  per-process table. Accesses add the base and check the limit.
- **What it gives:**
  - every allocation can be its own segment, so overruns trap at once
    (memory safety for C-like code);
  - free relocation and compaction, since pointers are segment-relative
    (Burroughs);
  - sharing through descriptors.
- **Costs:**
  - a descriptor load per pointer loaded (~20 cycles on the 286);
    a descriptor cache fixes it;
  - a base adder in the address path (~6 chips, ~40 ns) and a limit
    comparator (~3 chips);
  - wider hidden state (~6 bytes);
  - 4096 segments per process;
  - contiguous segments, so compaction.
- ~20–25 chips. It catches accidents, not malice: a program can still build
  any segment number in a D register, but only within its own table.

**Flavour 3: unforgeable capabilities** (CHERI): tagged memory and 128-bit
pointers. **rejected** as too heavy for TTL.

**Measuring it needs bigger workloads.** The current programs fit in a few
pages and would show near-perfect hit rates.

## 12. Big ideas

From "what would you like in an ISA". All **open**.

**Nearly free on this machine:**
- **Register windows in the register-file SRAM** (Berkeley RISC, SPARC,
  AMD 29000's register stack).
  - A frame counter on spare address lines banks r8–r14 per call: `CALL`
    steps it up, `RET` down. Saving and restoring disappears (23% of
    queens' cycles).
  - An overflow trap spills old frames after 256 or 2048.
  - The counter's top bits can be a process number, for cheap context
    switches.
  - ~3–4 chips.
- **Banked registers for interrupts** (ARM FIQ, Z80 alternate registers,
  8051 banks): the handler saves nothing. ~1 mux input.
- **Packed byte arithmetic** by carry gating ([2.4](#24-more-instruction-ideas-not-yet-decided)).
- **Debugging:**
  - trace bit (microcode);
  - hardware breakpoint register compared against the PC (~8 chips);
  - **branch trace buffer**: a counter and a small SRAM recording every
    taken-branch target, so after a crash you can see how it got there
    (~6–8 chips).

**Big swings:**
- **Writable control store, user-defined instructions** (Xerox Alto's
  microcoded BitBLT; optional on the VAX-11/780 and PDP-11/60).
  - Part of the microcode becomes RAM, and 1a's op F becomes "user
    opcodes".
  - Uses: a Forth inner interpreter or the VM's dispatch in microcode, a
    blitter instruction, emulating another CPU.
  - ~10–12 chips. Microcode bugs are brutal to debug.
  - Turns every "should we add instruction X?" into an experiment.
- **Run a bytecode directly** as a second native instruction set: the
  Pascal MicroEngine ran UCSD p-code, Lisp machines ran Lisp. Boot into a
  Forth or BASIC machine.
- **Tagged memory** (Burroughs B5000, Lisp machines): 2–4 tag bits per word
  for type checks and garbage collection. Wider memory (34–36 bits) and tag
  checks in the ALU path; a whole-system decision.
- **Bounded pointers:** full CHERI is too big; base/limit checks per access
  are the light version ([section 11](#11-address-registers-with-hidden-state),
  flavour 2).
- **Hardware time-travel debugging:** every store also logs the old value
  and address into a ring-buffer SRAM, so a debugger can step backwards.
  A read-modify-write per store plus ~10 chips; with the branch trace
  buffer, the last few thousand instructions can be replayed.
- **A stack-machine alternative** (RTX2000, Transputer): 8-bit instructions,
  dense code, cheap calls. Registers were never short in our programs, so
  not as the main ISA; possible via a writable control store.

**My personal wishlist, in order:**
1. register windows;
2. a writable control store with user opcodes;
3. the idiom killers (auto-increment, table jump, non-destructive shifts,
   memory increment, multiply-accumulate);
4. precise restartable traps plus the debug trio;
5. packed byte add.

## 13. Wishes from the program writers

From [notes-v1/](notes-v1/), not covered above:

| Wish | ISA | Notes |
|---|---|---|
| One-parcel 8-bit constants | 1b | Character constants cost 2 parcels; no room in the `F D M R` encoding |
| Byte and half auto-decrement, half auto-increment | 1b | Backwards loops (`memmove`, `reverse`) |
| Indexed mode with more than 8 bits of displacement | 1b | A table base needs its own register |
| `[label + reg]` for labels beyond ±32 KB | both | 1b has no 32-bit displacement form |
| One-parcel `[r + small offset]` | 1b | Struct fields cost an extension parcel |
| Immediate `TST`/`BIC`/`MUL`/`DIV` | 1b | Constants needed registers |
| `POP` that leaves the flags alone | 1b | `MOV [sp]+` sets N and Z |
| Longer reach for the short byte offsets | 1a | 0–15 is too short for a 34-byte Life row |
| `MOV`/`MVI` that don't set flags, or an explicit flag-setting bit (ARM's S bit) | both | A constant can't be loaded between a compare and its branch |
| V updated (or defined) by `INC`/`DEC`/`TST` | both | Signed branches after them test a stale V |
| Assembler macros, `.rept` | tools | sha256's rounds |
| Library constants not polluting the global namespace (`CONSOLE`, `PR_OUT`) | library | Programs couldn't reuse the names |
| `strcmp` setting flags from its result | library | Every call was followed by `TST` |
| Accept `MVI r, 0x80` when only the low byte matters | tools | Had to write −128 |

Tooling items already done in this round: per-kind and per-routine cycles in
`run --stats`; raw-byte output from `tmc run`.

## 14. Open questions

Questions raised along the way that only Emily can answer:

1. What's the fun part: using the finished machine (OS, compiler,
   software), the hardware engineering itself, or period authenticity?
2. Build budget, roughly in chips or months (100, 200 and 400 chips are
   different projects)? Breadboard, wire-wrap or PCBs?
3. OS goal: Unix-like (processes, files, a shell), or period-flavoured (a
   BASIC timesharing system, a Forth machine)? Is multi-user protection
   needed, or is unprotected multitasking enough?
4. Console: a serial terminal, or should the machine drive its own screen?
   If graphics: raster or vector?
5. How many simultaneous terminals? Is a microcontroller inside a
   peripheral acceptable?
6. A backplane with slots? If yes, write a small bus spec (signals, timing,
   connector) before the next hardware round.

Answered so far:
- 32-bit architecture with a narrow implementation first: yes.
- 16-bit instruction parcels: yes.
- Compare RISC-like and CISC-like encodings: done.

## 15. Offered next steps

Offered in the discussions, not done yet:

- Simulator models: a CF card, DMA, the microcoded channel, a UART with
  wait states, and the display-list video card rendering PNGs. Then a
  console driver and a demo screen.
- Add user mode, the MMU (flat map or A-register caches), faults and
  `LDU`/`STU` to the draft 1 simulator; a tiny kernel running two programs
  as processes with demand paging from a simulated disk.
- A "draft 2" in the simulator:
  - 1a plus auto-increment and a table jump;
  - register windows;
  - user opcodes with estimated microcode costs;
  - the D/A split with per-register translation caches and walk counters,
    on bigger workloads.
- One architecture sketch tying the system decisions together: private and
  shared memory, bus mastering, slots, the I/O page, interrupts.
- A 32-bit netlist estimate through the timing analysis, replacing the ±20%
  chip and clock guesses.
