---
number: 1
type: report
title: Evaluating ISA draft 0
status: obsolete
date: 2026-10-11
context:
  studies: [v0_hw]
  commit: e494b0c
superseded-by: 4
---

# Report 0001: Evaluating ISA draft 0

> **Draft 0 is superseded.** This is the 16-bit first draft, kept as a record. Draft 1 replaced it: see [evaluation-v1.md](0004-report-draft-1-evaluation.md) and [hardware-v1b.md](../studies/v1b_hw/hardware.md).

**Short version:** draft 0 is a sound base. Programs came out right first
time, the encoding made the hardware unusually simple, and a 98-chip
implementation runs every test program at 2 MHz with worst-case parts
(3.4 MHz typical, up to 5 MHz with faster logic). The one big problem is
the missing multiply and divide, which eats 60–80% of the time in any
program that does arithmetic. After that come register save/restore cost
and `INC`/`DEC` clobbering the carry. Most of the other changes I expected
to want (three-operand ALU, wider branch offsets, more addressing modes)
turned out to be worth little on the evidence.

## What was built

1. **Assembler and instruction-level simulator** for [draft 0](../studies/v0_hw/isa.md),
   with cycle counts taken from the microcode, so they're exact for the
   hardware below.
2. **16 programs plus a library**: arithmetic, strings, sieve, sorting,
   recursion, CRC, Mandelbrot, Life, 8 queens, a binary tree, bignum
   factorial, an RPN calculator, a memory monitor, interrupts and matrix
   multiply. A separate agent wrote them, working only from the spec, so
   they're a fresh programmer's code rather than mine. Expected outputs come
   from independent Python versions.
3. **[Programming notes](0002-report-draft-0-programming-notes.md)**: a program-by-program log of
   what was easy, what went wrong and why.
4. **[A 7400-series implementation](../studies/v0_hw/hardware.md)**: 98 chips, 74HCT logic with
   74LS181 ALUs, a 48-bit microcode in six flash ROMs.
5. **A chip-level timing simulator** (Go, event-driven, datasheet pin-to-pin
   delays, setup/hold, SRAM write timing, bus contention). All 16 programs run
   on it at the guaranteed clock and match the instruction-level simulator
   (15 cycle-exactly; the interrupt program in results).
6. **[Performance numbers](0001-report-draft-0-evaluation/performance.md)** from static timing analysis,
   simulation sweeps and the program suite, plus ISA usage statistics.

## Performance

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
numbers are in [performance.md](0001-report-draft-0-evaluation/performance.md).

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

## Ease of programming

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

## Findings, ranked by measured cost

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

## What the hardware says about the encoding

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

## Recommendations for draft 1

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

## Hardware issues to fix regardless of the ISA

From [hardware.md](../studies/v0_hw/hardware.md): bus contention when the B bus changes source
(up to 67 ns at worst-case delays), ~100 ns of microcode access at the start
of every cycle (a pipelined microinstruction register would remove most of
it), and some parts are only available as new-old-stock (74181/74182) or not
in DIP (fast SRAM, the 55 ns flash).

## Questions for the next round

These have since been answered or carried into
[proposals.md](0005-rfc-ideas-direction.md#4-open-questions).

- How much is speed worth in chips? The multiply datapath is about 4 chips;
  a pipelined microcode register about 6 and a redesign of the fetch path.
- 74HCT (safe, in production) or 74ACT (1.8× faster, harder on breadboards,
  some parts missing)?
- Is the build going to be breadboard, wire-wrap or PCB? That decides how much
  bus contention and ground bounce matter.
