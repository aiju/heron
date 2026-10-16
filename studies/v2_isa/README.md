---
status: active
depends-on: [v1_isa]
reports: []
---

# Draft 2: the instruction set of RFC 0028

Draft 2's instruction set in an assembler, a disassembler and an
instruction-level simulator with the timing model, and draft 1's 20
programs ported to it. The specification they implement is Part I of
[RFC 0028](../../reports/0028-rfc-draft-2-isa.md); this README is only how
the tools work. It's a study until RFC 0028 is accepted; then the
specification moves to `docs/` and the code to the root's `isa/` and
`tools/` ([RFC 0000](../../reports/0000-rfc-repository-layout.md#where-work-happens)).

It depends on `v1_isa` only for the program suite: the expected output
every draft is checked against, the shared input in `programs/common/`,
and the reference implementations that write them. The simulator and
the timing model started as copies of draft 1's, so that draft 2 can
change them without moving draft 1's numbers.

| File | What's in it |
|---|---|
| `isa/` | The engine, in Rust ([RFC 0015](../../reports/0015-rfc-languages.md)): the decoder (`decode.rs`) and semantics (`insn.rs`), the machine, RFC 0029's system half (`sys.rs`), the timing model and the encoder the assembler uses (`asm.rs`). Python reaches it as `heron.native.v2` |
| `v2.py` | The disassembler, and what the tools need to know about the ISA |
| `sim.py` | The simulator as the studies use it |
| `programs/` | The 20 programs and their library, ported from `v1_isa/programs/v1b/` |
| `testing.py`, `tests/` | The program suite, and the unit tests |

```sh
heron v2_isa test                             # the 20 programs against their expected output
heron v2_isa run studies/v2_isa/programs/life.s --stats   # cycles for six configurations, mix, profile
heron v2_isa asm -l life.lst studies/v2_isa/programs/life.s   # a listing, opcode byte first
heron v2_isa bench                            # instructions, cycles and run times per program
heron test v2_isa                             # the unit tests
cargo test -p v2-isa                          # the encoder, the semantics and the timing keys
```

## The machine around the instructions

The simulator has two machines. The one the 20 programs run on has no
supervisor, and around the instructions it is draft 1's
([RFC 0004, 25 and 26](../../reports/0004-rfc-draft-1-isa.md#25-calls-the-stack-and-interrupts)):

- 1 MB of RAM from address 0, and the I/O page at `0xFFFFFF00`.
- Draft 1's vectors from address 0: reset, IRQ, illegal instruction,
  `SWI`, divide error and address error, then the tag trap at `0x18`.
  An exception pushes the PC and the flags. RFC 0029's vectors start at
  `0x8000_0000`.
- Every register is zero at reset.
- There's no supervisor, so `MFUR` and `MTUR` trap, and `MFSR` and
  `MTSR` know only `flags`.

The other, which `Machine::new_system` makes for a board such as Fen's,
is what [RFC 0029](../../reports/0029-rfc-draft-2-system.md) gives an
operating system (`sys.rs`, tested in `tests/system.rs`): supervisor and
user mode, the page map, register banks of `r0`–`r15`, and vectored
exceptions and interrupts. Interrupts are at levels 1–8, the bus's lines
IRQ1–IRQ8, taken when above IPL; the numbering is in one place in
`sys.rs`, since RFC 0029 keeps the interrupt design open.

## Listings, timing and linking

- **Listings,** `dis` and `objdump` show an instruction's first parcel as
  its two bytes, opcode first, as RFC 0028 writes them, and the extension
  parcels as 16-bit values: `13 34 0008` is `MOV r3, [r4 + 8]`.
- **Timing:** draft 1's [timing model](../v1_isa/timing-model-v1.md),
  the same six configurations, so it estimates a draft 2 machine built
  like the 1b hardware; the microcode estimate is still to come
  ([RFC 0028, 13](../../reports/0028-rfc-draft-2-isa.md#13-next-steps)).
  It adds draft 2's kinds of work:
  - `INC` and `DEC` on memory (`rmw`) read, add in the ALU, and write
    back.
  - `DBNZ` (`dbnz`) decrements in one ALU step, which also detects zero,
    writes the register back and, when it branches, adds the offset to
    `PC`.
  - `LDM` and `STM` (`ldm`, `stm`) stream words like `RESTORE` and `SAVE`,
    without updating `sp`.
  - A call (`call`, `callm`) writes `r7` instead of pushing: one register
    write, then the jump. `RET` is a jump to a register, and `JMP [sp]+`
    a jump through memory.
  - The tables without a base register: `[abs24 + x·s]` (`absx`) is one
    full add; `[pc + d24 + x·s]` (`pcx`) is an address add, then a full
    one.
  - `MULA` is a multiply and two more steps for the 64-bit add. `MULFX` is
    a multiply, then two steps per step of its shift: one over each half
    of the product.
  - `MULU` and `MULS` with a word from memory cost the multiply alone.
  - Mode E, `[r14 + 4R]`, costs what mode 4, `[sp + 4R]`, does: a
    register plus a displacement.
- **Linking:** the tables' 24-bit address has its top byte in the index
  parcel, so the linker fills it in with two relocations, `abs24h` and
  `abs24l` (`pc24h` and `pc24l` PC-relative)
  ([linking.md](../../infra/linking.md)).

## The programs

They were ported in four steps, which the history keeps apart.

1. **As they are.** Stores are written `MOV`. The `MOV`s whose N and Z
   something reads became `MOVS`, 37 of them: found by tracing, on the 1b
   simulator, which instruction last set the flags whenever an
   instruction read them, and by a static pass over the code for the
   paths the runs miss. 1b's `ST r0` became `CLR`, and where 1b read `r0`
   as zero (`ADC`, `SBC`, `MTHI`) a `CLR r0` comes first. The SWI handler
   in `interrupts.s` reads the call number with one byte load: it's the
   instruction's register byte.
2. **Using draft 2.** `DBNZ` for the counted loops; `INC` on memory for
   counters (in the timer handler it saves the register too); a pop
   between a test and its branch in `vm.s`; `REV` for SHA-256's
   big-endian words; `MULFX` in `mandel.s` and `MULA` in `matmul.s`; and
   mode E, with `r14` as the current object: `bst.s`'s node, and the
   sixteen-word window of SHA-256's message schedule.
3. **The link register.** A function that calls saves `r7` with the rest:
   `SAVE r8-rN` became `SAVE r7-rN`, and `PUSH r8` became `SAVE r7-r8`.
   One that saves nothing else pushes `r7` and returns with `JMP [sp]+`,
   and a tail call restores `r7` before its branch. The leaf routines
   that used `r7` as scratch (crc's two loops, rpn's `eval`, `isort`,
   `xor_rect`, `memcpy` and `memset`) use `r5` or `r0` instead.
4. **`HI` and `LO` are `r0` and `r1`.** A divide's remainder and a
   product's high half are read from `r0`: `MFHI rX` became `MOV rX, r0`,
   the decimal printer pushes each digit straight from `r0`, a `DIVUL`
   chain starts with `CLR r0`, and `MULA` accumulates into `r0:r1`.
   `memset`, which keeps its result in `r0`, now saves it after its
   `MULU`. The implicit registers are written out, as RFC 0028 now
   spells them: `DIVU r0:r1, r5`, `MULA r0:r1, r2, r3`.

Every program also passes with `r0` holding garbage from the start, which
`tests/` checks, and linked from relocatable object files.
