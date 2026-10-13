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
