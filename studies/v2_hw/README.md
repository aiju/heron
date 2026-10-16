---
status: active
depends-on: [v2_isa, v1b_hw, c_compiler]
reports: [31]
---

# A draft 2 CPU

A CPU for draft 2 ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)) with
RFC 0029's system architecture, built on RFC 0024's advice: fast parts and
short variable-length cycles, a writable control store that the I/O
processor fills at boot, a 32-bit memory and system bus, and a prefetch
queue that fetches in the cycles that don't use memory. The design is
[RFC 0031](../../reports/0031-rfc-draft-2-cpu.md).

Work in progress: the microcode and a register-transfer model checked
against draft 2's instruction-level simulator; no netlist yet.

It depends on `v2_isa` for the ISA, its simulator and the program suite,
on `v1b_hw` for the shift planner (the shift steps are draft 1b's), and on
`c_compiler` for the compiled programs.

| File | What's in it |
|---|---|
| `ucode.py` | The control word, the microcode for every instruction, the decode table |
| `timing.py` | How long each microinstruction's cycle must be (an estimate from datasheet delays until there's a netlist), and the four length classes |
| `rtl.py` | The register-transfer model: datapath, prefetch queue, page map, register banks, sequencer |
| `system.py` | The memory system behind it: translation, the card's RAM, the system bus and its cards, with transfer times |
| `check.py` | The RTL model against the instruction-level simulator, on the suite |

```sh
heron v2_hw check [NAMES] [--lockstep]   # the suite on the RTL model against the ISA simulator
heron v2_hw run studies/v2_isa/programs/life.s --profile   # cycles, time, where they go
heron v2_hw run PROG.s --bus             # the code on the memory card, fetched over the bus
heron v2_hw ucode [--list]               # the microcode's size and length classes
```
