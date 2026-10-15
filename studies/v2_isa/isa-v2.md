# ISA draft 2, as the tools have it

Draft 2's encoding is [RFC 0028](../../reports/0028-rfc-draft-2-isa.md),
which is open: the map, the modes and the reasons are there. This page is
what the simulator and the assembler make of it: the syntax, and the
details the RFC leaves open, each of which the tools had to choose. Those
are marked **chosen** below; any of them can change.

The machine is draft 1's ([isa-v1.md](../v1_isa/isa-v1.md)): registers,
flags, memory, the I/O page, interrupts and the vectors. The differences:

- `r0` is a general register. All registers start at zero.
- `LO` is a new special register, which `MULA` accumulates into with `HI`.
- The tag check of the tagged operations traps to its own vector, `0x18`.
- The zero parcel is `ILLEGAL`, not `HALT`, and so is `FF`.

```sh
heron v2_isa test                                    # the 20 programs
heron v2_isa run studies/v2_isa/programs/life.s --stats
heron v2_isa asm -l prog.lst prog.s                  # a listing, opcode byte first
cargo test -p v2-isa                                 # the encoder and the semantics
```

## Syntax

Draft 1b's syntax ([isa-v1b.md](../v1_isa/isa-v1b.md)), with one spelling
per instruction: the assembler takes
what the disassembler prints.

- **Moves:** `MOV rd, src` loads, copies and takes constants, and leaves
  the flags alone. `MOV [address], rs` is a store: the operand order says
  which. `MOVS rd, src` is a `MOV` that sets N and Z.
- **No aliases:** no `ST`, `MVI` or `CMPI` (only labels in the map), and
  none of 1b's `PUSH`, `POP`, `LI`, `MFHI`, `MTHI`, `MFF` or `MTF`. A push
  is `MOV -[sp], r1`, a pop `MOV r1, [sp]+`, `MFHI r1` is `MFSR r1, hi`.
  The assembler says so when it meets one.
- **One operand:** `CLR`, `INC` and `DEC` take a register or any memory
  operand: `CLR byte [r1]+`, `INC [counter]`. `MOV [x], #0` is `CLR [x]`.
- **Tables:** `[table + r2*4]` and `byte [table + r2*2]` index a table
  without a base register; `[pc + table + r2*4]` does it PC-relative.
- **Special registers:** `flags`, `hi`, `lo`, or a number.

The assembler picks the shortest encoding:

- **Constants:** a quick constant for 0…15 and −1…−16, the 7-bit form for
  16…127 (`MOV` and `CMP`), then the special mode's 16- and 32-bit forms.
  RFC 0028 left open which one-parcel form takes 0…15 and proposed the
  quick constant; **chosen**.
- **`[R + d]`:** `[R]`, then `[sp + 4k]` for a word, `[R + d16]`, and the
  table mode with `R` as its index when `d` needs 17 to 24 bits.
- **Absolute:** 16 bits, then PC-relative, then 32 bits, as 1b.
- **`LEA rd, [R]`** is `MOV rd, R`: draft 2 has no `LEA [R]`, and neither
  touches the flags.
- **`INC r5` and `DEC r5`** are row D's in-place forms. `CLR r5` is `CLR`
  with mode 0, and `MOV r5, #0` the quick constant: the same in effect.
- **`BIC`, `TST`, `MULU` and `MULS` with a memory operand** have only the
  special mode, so `[R + d]` is its table with `R` as the index.

Listings, `dis` and `objdump` show an instruction's first parcel as its two
bytes, opcode first, as RFC 0028 writes them, and the extension parcels as
16-bit values: `13 34 0008` is `MOV r3, [r4 + 8]`.

## What the tools chose

The RFC defines these only in part.

| | Chosen |
|---|---|
| `Jcc` (`F2`, `F3`) | Condition 14 is `JMP` and 15 `CALL`, as in 1b, so `JMP label` and `CALL label` are `Jcc` (`JMP #label` is `JMP ea`). The spare nibble must be 0: anything else traps |
| `DBNZ r, label` (`F6`) | Like `Bcc`, the offset counts from the next instruction: the low nibble is `k − 1` for a branch `k` parcels back, 1–16. Flags unchanged |
| `LDM rb, ra-rc`, `STM` (`01`, `02`) | The register byte holds `ra` (high) and `rb` (low); the extension parcel holds `rc` in bits 15–12, and its other 12 bits must be 0. Ascending from `[rb]`, `rb` unchanged; `LDM` reads every word before writing any register |
| Shifts by `#n` | Count bit 0 in opcode bit 0, bits 4–1 in the register byte's low nibble |
| `SETcc rd` (`DF`) | `rd` and the condition in the register byte; condition 15 traps |
| `SAVE`, `RESTORE` | Any range within `r0`–`r14` |
| `INC`, `DEC` on a byte or half | N from the operand's own top bit, Z from the value stored |
| `MULFX rd, rs, #n` (`FD 10`) | The extension parcel holds `rd` in bits 15–12, `rs` in 11–8, `n` in 4–0; bits 7–5 must be 0 |
| `MFUR`, `MTUR` (`FE 10`, `FE 11`) | The extension parcel holds `rd` in bits 15–12 and `rs` in 11–8, its low byte 0. The assembler and the disassembler have them; the simulator, which has no supervisor yet, traps on them |
| `MULA` | `MULU` and `MULS` leave `LO` alone |
| The tag | An integer has bit 0 clear, the Lisp's, as RFC 0028 suggests until it's settled |
| `CAS` (`F7`), `FPU` (`F8`), the free cells | Trap as illegal, until they're designed |
| Reserved values | An index parcel's size 3, the special mode's `R` = F, mode E where it isn't the tagged column, and the free extension-grid cells trap as illegal |

## Timing and linking

- **Timing:** draft 1's [timing model](../v1_isa/timing-model-v1.md),
  the same six configurations, so it estimates a draft 2 machine built
  like the 1b hardware; the microcode estimate is still to come (RFC 0028,
  11). It adds draft 2's kinds of work:
  - `INC` and `DEC` on memory (`rmw`) read, add in the ALU, and write
    back.
  - `DBNZ` (`dbnz`) decrements in one ALU step, which also detects zero,
    writes the register back and, when it branches, adds the offset to
    `PC`.
  - `LDM` and `STM` (`ldm`, `stm`) stream words like `RESTORE` and `SAVE`,
    without updating `sp`.
  - The tables without a base register: `[abs24 + x·s]` (`absx`) is one
    full add; `[pc + d24 + x·s]` (`pcx`) is an address add, then a full
    one.
  - `MULA` is a multiply and two more steps for the 64-bit add. `MULFX` is
    a multiply, then two steps per step of its shift: one over each half
    of the product.
  - `MULU` and `MULS` with a word from memory cost the multiply alone.
- **Linking:** the tables' 24-bit address has its top byte in the index
  parcel, so the linker fills it in with two relocations, `abs24h` and
  `abs24l` (`pc24h` and `pc24l` PC-relative)
  ([linking.md](../../infra/linking.md)).
