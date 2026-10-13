---
status: frozen
depends-on: [v1_isa]
frozen-at: e494b0c
reports: [1, 2]
---

# Draft 0: a 16-bit ISA and its hardware

The first round: a 16-bit load/store instruction set, an assembler and
instruction-level simulator, 16 programs, and a 98-chip implementation
with microcode, a chip-level netlist and static timing analysis. Draft 1
replaced it.

This study is **frozen**: its tests don't run in CI, and its code may stop
working as `infra/` changes. Check out `frozen-at` to reproduce its
results. The draft 1 reports compare against draft 0 through
`baseline.json`, so they don't need this code to run.

It depends on the `v1_isa` study only for the program suite's expected
output (`studies/v1_isa/programs/expected/`).
