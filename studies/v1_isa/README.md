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
report 0004 compares against.
