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

| File | What's in it |
|---|---|
| [isa.md](isa.md) | ISA draft 0: encoding, instructions, conventions, assembler syntax |
| [hardware.md](hardware.md) | The 98-chip implementation: datapath, microcode, timing, known issues |
| [microcode.md](microcode.md) | Generated: the microcode, cycle by cycle |
| `isa.py`, `sim.py` | The ISA (encoder, disassembler, semantics) and the instruction-level simulator |
| `microcode.py`, `cpu.py`, `machine.py` | The microcode, the chip-level netlist, and the machine the hardware tools run |
| `programs/` | The 16 test programs and their library |
| `baseline.json` | Draft 0's results, for the later drafts' reports |

Reports: [0001](../../reports/0001-report-draft-0-evaluation.md) (the
evaluation, with the generated performance tables) and
[0002](../../reports/0002-report-draft-0-programming-notes.md) (writing the
programs).

```sh
heron v0_hw run studies/v0_hw/programs/mandel.s --stats   # assemble and run, with an instruction mix
heron v0_hw test                                          # every program against its expected output
heron v0_hw hw run studies/v0_hw/programs/fib.s --period 500   # on the chip-level simulator at 2 MHz
heron v0_hw hw sta                                        # static timing analysis
heron v0_hw report --hw                                   # report 0001's generated tables (a few minutes)
```
