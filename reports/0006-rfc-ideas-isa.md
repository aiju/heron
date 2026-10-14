---
number: 6
type: rfc
title: Instruction set ideas
status: open
date: 2026-10-12
context:
  studies: [v1_isa, v1b_hw, lisp, c_compiler, kernel]
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

### 2.6 For Lisp

From the Lisp study ([report 0018](0018-report-lisp.md)): a dynamically
typed, garbage-collected language on 1b, interpreted and compiled. Shares
are of compiled cycles, on 12 benchmarks.

| Proposal | Evidence | Status |
|---|---|---|
| Keep misaligned-access traps **precise** (the saved PC is the faulting instruction's, nothing changed) in draft 2 | Tagged pointers make `car`, `cdr` and calls type-check themselves through the trap; checking in software would cost 16% compiled (up to 35%) and 19% interpreted | **recommended** |
| A tagged register operand: `MOV`, `ADD`, `SUB`, `CMP`, ... that trap unless both operands have bit 0 clear, and `ADD`/`SUB` that trap on overflow (1b's reserved mode E; in 1a, op F) | Built as v1bx ([isa.md](../studies/lisp/isa.md)): −6.4% geometric mean, up to −16% (fib); −5.6% if it costs a cycle more. About one chip | **measured**, open |
| Keep a memory-indirect call (`CALL [r + d]`) in draft 2 | Calls go through a code word in every object; a load and `CALL r` would cost 1.3% (up to 2.5%) | **measured**, open |
| One-parcel `[r - 1]` and `[r + 3]` (the pair offsets) | Saves 1.1% compiled, 1.7% interpreted; not worth the encoding space | **measured** |
| Guard pages for the stack and heap limits | In [RFC 0010](0010-rfc-ideas-os.md#11-mmu): 5.0% and 1.8% | **open** |

### 2.7 `r0` as a general register

**measured**, open. Only for a draft 2 built on 1b. In draft 1, `r0` reads
as zero in both encodings. In 1a it carries its weight: `[r0 + disp]` is
1a's only absolute address. 1b's encoding already covers the usual reasons
for a zero register: `#0` is a one-parcel constant (mode 1), absolute
addresses have their own modes (F4–F9) and `NEG` is a unary op. The idea is
to make `r0` a 15th general register.

- **What `r0` does in 1b now.** Every use in the 1b code (the programs,
  compiled C, the kernel and the Lisp runtime) is one of these:
  - **Storing zero:** `ST r0, ea`, since 1b has no store-immediate. That's
    13 of the 16 uses in the hand-written programs, 16 of the 24 in
    compiled C (the other 8 are `MOV rX, r0`, the same as `MOV rX, #0`),
    and 52 in the kernel and the Lisp runtime.
  - **A zero for instructions that only take registers:** `ADC r5, r0`
    (bignum), `SBC r6, r0` (sort), `MTHI r0` before a `DIVUL` chain, the
    kernel's `MTUR r1, r0` and `MTSR mapd, r0`, and the Lisp's
    `CMP.T r1, r0`.
  - **A zero in the hardware:** `NEG` and the multiply and divide routines
    read `r0` onto the A bus. A hidden register-file entry that the reset
    routine zeroes, like the loop constants at 24 and 25, would do the same.
  - **Unused:** `MOV r0, ea` tests a memory operand without a scratch
    register.

  Executed, it's 0.99% of the hand-written programs' instructions, and 92%
  of that is one store in sieve's inner loop.
- **What it costs:**
  - one register: 14 general registers instead of 15;
  - 5 OR gates, a microinstruction bit (`WR0`) and a reset step in the 1b
    hardware;
  - encodings: with `R = r0`, modes 2, 6, 7, 8, A and B are useless, and
    3, 9 and C duplicate the absolute modes.
- **Measured** on the 15 C programs for 1b, with the compiler patched two
  ways at `b6ffcfd` (not committed). The table gives cycles in the
  programs' own code, geometric means, D16-overlap / D32-overlap:

  | Change | Cycles | Where |
  |---|---:|---|
  | No zero register: a 0 needed in a register is a fresh `MOV rX, #0` | +1.3% / +1.1% | sieve +19% / +16%, bst +1% |
  | One register fewer (r14 not allocated), an upper bound on what a 15th is worth | +0.5% / +0.7% | sha256 +6% / +11%, wordfreq +0.8% |

  - The other programs barely change.
  - Sieve's cost is the compiler's: it puts the `MOV` inside the inner
    loop rather than hoisting it, and the loop has registers to spare.
  - The C library is left out because of a layout effect. Its size moves
    sieve's byte array on or off a word boundary, which changes `memset`'s
    time by 3.6×.
  - [Report 0004](0004-report-draft-1-evaluation.md) found no hand-written
    program short of registers either.
- **Replacing it:**
  - Op B (`JMP`/`CALL ea`) has 14 unused values of `d`. One could be
    `CLR ea`, which stores zero at any size, in any mode.
  - `ADC`/`SBC`, `MTSR` and `MTUR` would still need a zero from a register,
    or new forms. For example, the unary group has four free functions,
    room for an add-carry.
- **Against:**
  - It's about 1% either way, so performance doesn't decide it.
  - `r0 = 0` is part of the common draft 1 machine, and 1a needs it.
  - The kernel and the Lisp rely on it.
  - It keeps the compiler simple: a zero never needs a register of its own.

  Only worth it if a 1b-based draft 2 wants the register or the encoding
  space for something else.

### 2.8 Which `MOV`s set the flags

**measured**, open. Stores could be written as `MOV` too: `MOV [r2], r1`
for `ST r1, [r2]`, and `MOV -[sp], r1` for a push. Loads, stores, register
copies and constants would then share one mnemonic, and its flag rule has to
read well for all of them. In draft 1, loads, `MOV`, `MVI` and 1b's `POP`
set N and Z (C and V unchanged); stores don't.

- **Whose N and Z get read.** These are traces of every program in both
  encodings. Each cell says how often a move's N and Z were read before
  something overwrote them:

  | Move | Hand-written, 1a / 1b | Compiled C, 1a / 1b |
  |---|---|---|
  | Constant (`MVI`, `MOV r, #c`) | 0 of 9.4k / 0 of 9.7k | 0 of 22k / 0 of 32k |
  | Register copy | 21 of 103k / 21 of 86k | 0 of 137k / 0 of 123k |
  | 1b `POP` (`MOV r, [sp]+`) | – / 0 of 33k | – |
  | Load | 13.8k of 506k / 13.8k of 263k | 5.7k of 190k / 9.4k of 72k |

  - The 21 are one place in lines: `MOV r8, r3; BEQ`.
  - Every read is `EQ`, `NE`, `MI` or `PL`. Nothing branches on a signed
    condition after a move.
  - The loads whose flags are read are:
    - string loops (`MOV r2, byte [r1]+; BNE`);
    - the console's end-of-input test (`BMI`);
    - lookups that test for an empty table entry or a null link.
- **Four possible rules for a unified `MOV`:**
  - **Never sets the flags** (x86, Z80). Loads need a `TST` wherever their
    flags are read:
    - hand-written code, estimated as one `TST` per read: +2.7% / +3.1%
      (1a / 1b) on D16-overlap and +1.6% / +1.8% on D32-overlap, geometric
      means, up to +13% in strings;
    - compiled C, measured with the compiler keeping its `CMP r, #0` after
      moves and loads: +0.4–0.7% in the programs' own code, up to +7.5% in
      strings. Code grows by 28 bytes across all 15 programs, plus up to 26
      bytes of library.
  - **Sets N and Z when the destination is a register** (draft 1's rule,
    and the 6502's). No measured cost:
    - A constant can't be loaded between a compare and its branch.
    - It can nearly always be loaded before the compare instead. In
      `line`, `MOV r5, #1` can go above the `SUB` that sets the flags. That
      saves the `BRA` that
      [report 0003](0003-report-draft-1-programming-notes.md) put down to
      this rule.
  - **Sets N and Z when the source is memory** (loads only). No measured
    cost. With copies and constants not setting the flags, the compiled C
    doesn't change at all. Hand-written code loses only the 21 reads above.
  - **Always sets N and Z, stores included** (PDP-11, VAX, 68000):
    - **Software:** one idiom has to change. `lib/print.s` pushes a digit
      between the `DIVU` and the branch on its quotient; pushing with
      `SAVE r3-r3` would leave the flags alone. Compiled C never keeps the
      flags live across a store.
    - **1b hardware:** N and Z come from the B bus, and flags can't change
      in a checked memory cycle, or traps would stop being precise. So a
      store can only set them in its last cycle. A plain store's B bus is
      free then, but a push or an `[r]+` store needs it to write back the
      address register.
    - **The cost:** one more cycle for those stores is +0.9% (from report
      0012's cycle counts), up to +2% in vm and sort. A second N/Z source
      instead would be about 5 chips.
- **Whichever rule is chosen:**
  - `RESTORE r-r` already pops without touching the flags, in 1b too.
  - bst's insert walk relies on moves leaving C alone
    (`MOV r3, r4; BCC`). All four rules keep that; a 68000-style move,
    which clears C, would not.
  - Loads could also clear V, as on the PDP-11 and VAX. A signed branch
    after a load would then compare with zero instead of reading a stale
    V. No measured program needs it: it would only save 62 executions of
    a `CMP r, #0` in compiled C. It would remove the same trap as the
    `INC`/`DEC`/`TST` wish in
    [section 14](#14-wishes-from-the-program-writers), and nothing branches
    on V after a move.
- **The syntax itself:**
  - In 1b it's an assembler and disassembler change only.
  - 1a's loads and stores would take 1b's size keywords, plus one more for
    sign-extending loads (`sbyte`, say).
  - `MOV [x], #c` would be the natural thing to write, and neither
    encoding has it. With `r0 = 0`, `MOV [x], #0` can assemble to
    `ST r0, [x]` (2.7).
- **The question:** is one rule for loads and stores worth its price?
  - "Never" costs about 2–3% in hand-written string code.
  - "Always" costs about 1% in the 1b hardware.
  - Without one rule, draft 1's rule reads as "a `MOV` into a register sets
    N and Z".

Measured at `b6ffcfd` with scripts that aren't committed.

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
| `POP` that leaves the flags alone | 1b | `MOV [sp]+` sets N and Z; `RESTORE r-r` doesn't (2.8) |
| Longer reach for the short byte offsets | 1a | 0–15 is too short for a 34-byte Life row |
| `MOV`/`MVI` that don't set flags, or an explicit flag-setting bit (ARM's S bit) | both | A constant can't be loaded between a compare and its branch; measured in 2.8 |
| V updated (or defined) by `INC`/`DEC`/`TST` | both | Signed branches after them test a stale V |
| Assembler macros, `.rept` | tools | sha256's rounds |
| Library constants not polluting the global namespace (`CONSOLE`, `PR_OUT`) | library | Programs couldn't reuse the names |
| `strcmp` setting flags from its result | library | Every call was followed by `TST` |
| Accept `MVI r, 0x80` when only the low byte matters | tools | Had to write −128 |

Tooling items already done in this round: per-kind and per-routine cycles in
`run --stats`; raw-byte output from `heron v1_isa run`.
