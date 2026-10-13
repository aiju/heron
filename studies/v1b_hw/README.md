---
status: active
depends-on: [v1_isa, v0_hw]
reports: [12]
---

# The draft 1b hardware

A 213-chip implementation of draft 1b with a 32-bit datapath, pipelined
microcode and a separate fetch cycle: the microcode generator, a
register-transfer model, the chip-level netlist, and the checks that tie
them to the instruction-level simulator.

It depends on `v1_isa` for the ISA and the programs, and on `v0_hw` only
for `baseline.json`, which its report compares against.

| File | What's in it |
|---|---|
| [hardware.md](hardware.md) | The design: datapath, pipelined microcode, timing, known issues |
| [microcode.md](microcode.md) | Generated: the microcode for a selection of instructions, cycle by cycle |
| `ucode.py` | The control word, the microcode generator and the decode ROM |
| `rtl.py` | The register-transfer model the netlist was built from (it runs the ROM images) |
| `cpu.py`, `machine.py` | The chip-level netlist, and the machine the hardware tools run |
| `check.py`, `exercise.py` | The RTL model against the instruction-level simulator; a generated program that exercises every instruction class |

Report: [0012](../../reports/0012-report-draft-1b-hardware/README.md).

```sh
heron v1b_hw hw run studies/v1_isa/programs/v1b/fib.s --period 340   # on the chip-level simulator
heron v1b_hw hw test --period 340 --max-cycles 10000000   # every program at chip level
heron v1b_hw hw sta                       # static timing analysis
heron v1b_hw hw bom                       # the parts list
heron v1b_hw ucode [--doc]                # ROM images and the full listing in build/ucode-v1b (--doc: microcode.md)
heron v1b_hw check [--lockstep] [NAME]    # the RTL model against the ISA simulator ("exercise" too)
heron v1b_hw report [--hw]                # report 0012's generated tables (--hw: 30–60 minutes)
```

`--variant` picks the parts (`hct-ls181`, `hct-f181`, `act-f181`) and
`--corner` the delays (`max` worst case, `typ` typical) for the `hw`
commands.
