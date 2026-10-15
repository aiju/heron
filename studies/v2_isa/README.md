---
status: active
depends-on: [v1_isa]
reports: []
---

# Draft 2: the instruction set of RFC 0028

Draft 2's encoding ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)) in
an assembler, a disassembler and an instruction-level simulator with the
timing model, and draft 1's 20 programs ported to it. It's a study until
RFC 0028 is accepted; then draft 2 moves to the root's `isa/` and
`tools/` as the current design
([RFC 0000](../../reports/0000-rfc-repository-layout.md#where-work-happens)).

It depends on `v1_isa` only for the program suite: the expected output
every draft is checked against, the shared input in `programs/common/`,
and the reference implementations that write them. The simulator and
the timing model started as copies of draft 1's, so that draft 2 can
change them without moving draft 1's numbers.

| File | What's in it |
|---|---|
| [isa-v2.md](isa-v2.md) | Draft 2 as these tools have it: the syntax, how the assembler picks encodings, and the details RFC 0028 leaves open |
| `isa/` | The engine, in Rust ([RFC 0015](../../reports/0015-rfc-languages.md)): the decoder (`decode.rs`) and semantics (`insn.rs`), the machine, the timing model and the encoder the assembler uses (`asm.rs`). Python reaches it as `heron.native.v2` |
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

## The programs

They are 1b's, ported as they are. Stores are written `MOV`. The `MOV`s
whose N and Z something reads became `MOVS`, 37 of them: found by
tracing, on the 1b simulator, which instruction last set the flags
whenever an instruction read them, and by a static pass over the code for
the paths the runs miss. 1b's `ST r0` became `CLR`, and where 1b read `r0`
as zero (`ADC`, `SBC`, `MTHI`) a `CLR r0` comes first. The SWI handler in
`interrupts.s` reads the call number with one byte load: it's the
instruction's register byte.

Every program also passes with `r0` holding garbage from the start, which
`tests/` checks, and linked from relocatable object files.
