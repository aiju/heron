---
status: active
depends-on: [v0_hw]
reports: [3, 4]
---

# Draft 1: a 32-bit ISA in two encodings

A 32-bit machine with 16-bit instruction parcels, in two candidate
encodings: 1a (load/store) and 1b (register + addressing mode). It has an
assembler, object files and a linker, an instruction-level simulator, a
timing model for six hardware configurations, and the program suite:
20 programs written for both encodings, checked against independent
Python reference implementations.

It depends on `v0_hw` only for `baseline.json`, draft 0's numbers, which
RFC 0004 compares against.

Both encodings are specified, each in full, in
[RFC 0004](../../reports/0004-rfc-draft-1-isa.md): Part I is 1a, Part II 1b.

| File | What's in it |
|---|---|
| [timing-model-v1.md](timing-model-v1.md) | How cycle counts are estimated for six hardware configurations |
| `refcard.py` | Quick reference cards for 1a and 1b, two A4 pages each, as PDF in `build/refcard/` |
| `isa/` | The ISAs' decoders and semantics, the instruction-level simulator, the timing model and the encoders the assembler uses, in Rust ([RFC 0015](../../reports/0015-rfc-languages.md)). Also two variants other studies use, v1bx for the Lisp ([report 0018's appendix](../../reports/0018-report-lisp.md#appendix-v1bx-draft-1b-with-a-tagged-register-mode)) and v1bs for the kernel study ([report 0020's appendix](../../reports/0020-report-operating-system.md#appendix-v1bs-draft-1b-with-system-extensions), `sys.rs`), and page reference counters (`pages.rs`) |
| `v1common.py`, `v1a.py`, `v1b.py` | The ISAs' disassemblers, and what the tools need to know about them |
| `sim32.py`, `timing32.py` | The simulator and the timing model as the studies use them, running the Rust ones |
| `programs/v1a/`, `programs/v1b/` | The 20 programs and their libraries, in each encoding |
| `programs/reference.py`, `programs/expected/`, `programs/common/` | The program suite: independent reference implementations, the expected output every draft (and the C versions) is checked against, and shared input |

Documents: [report 0003](../../reports/0003-report-draft-1-programming-notes.md)
(writing the programs) and
[RFC 0004](../../reports/0004-rfc-draft-1-isa.md) (the specifications, and
1a against 1b with the generated performance tables).

```sh
heron v1_isa run studies/v1_isa/programs/v1b/life.s --stats   # cycles for all six configurations, mix, profile
heron v1_isa --isa v1a test                   # every 1a program against its expected output
heron v1_isa asm -c util.s                    # an object file; ld links, objdump shows them, ar makes libraries
heron v1_isa report                           # RFC 0004's generated tables (seconds)
heron v1_isa refcard                          # the quick reference cards, in build/refcard/ (needs Chromium)
cargo test -p v1-isa                          # the Rust simulator's and encoders' own tests
python3 studies/v1_isa/programs/reference.py  # rewrite the expected output
```
