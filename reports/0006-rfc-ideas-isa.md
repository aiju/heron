---
number: 6
type: rfc
title: Instruction set ideas
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw]
  commit: e494b0c
---

# RFC 0006: Instruction set ideas

An ideas RFC: a scratchpad of ideas for one area, each with its own status
([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). It was split out of
`docs/proposals.md` in the restructure, so the items keep the statuses they
had there:

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | Evaluated with numbers ([report 0001](0001-report-draft-0-evaluation.md), [report 0004](0004-report-draft-1-evaluation.md)) |
| **recommended** | Suggested for the next draft or hardware round |
| **decided** | Emily chose it for the next hardware round; not built yet |
| **open** | Discussed, not decided |
| **rejected** | Decided against, with the reason, so it doesn't get re-proposed without new evidence |

Chip counts are rough estimates, scaled from the 98-chip draft 0 design.

## 2. Instruction set

### 2.1 Adopted in draft 1

These came from the draft 0 evaluation; draft 1 has them
([studies/v1_isa/isa-v1.md](../studies/v1_isa/isa-v1.md)):

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
programs ([report 0004](0004-report-draft-1-evaluation.md)).

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

From [report 0004](0004-report-draft-1-evaluation.md):

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
| Tagged add, subtract and compare that trap unless both operands are SmallInts (SPARC's `TADDccTV`) | opcode or mode, trap vector | Dynamic languages: 2–3% of an interpreter's run, 5.5% of compiled code's and 16–18% of numeric programs' ([report 0017](0017-report-egret.md)) | **measured** |
| For dynamic languages: load a tagged value's class, three-operand `XOR`, unaligned 16-bit loads, a call that leaves the return address in a register, `CHK` | microcode | About 1% or less each, interpreted or compiled ([report 0017](0017-report-egret.md)) | **measured** |
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

## 14. Wishes from the program writers

From [report 0003](0003-report-draft-1-programming-notes.md), not covered above:

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
`run --stats`; raw-byte output from `heron v1_isa run`.
