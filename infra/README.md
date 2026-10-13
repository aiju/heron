# infra

Reusable code that doesn't depend on any one design: no opcodes, no
microcode fields, no memory map. A design or study that uses it supplies
those ([RFC 0000](../reports/0000-rfc-repository-layout.md#infra)).

| Module | What it is |
|---|---|
| `asm.py` | The assembler: expressions, labels, directives, size relaxation, object files. An ISA supplies the encoder |
| `obj.py`, `link.py`, `objtools.py` | Object files, executables and libraries; the linker; ld, objdump and ar ([linking.md](linking.md)) |
| `toolchain/` | The assembler core, the object format and the linker, in Rust. Python uses them as `heron.native.toolchain`, through `asm.py`, `obj.py` and `link.py`. The encoders for drafts 1a and 1b are in `studies/v1_isa/isa/` |
| `isas.py` | The ISA registry: a study registers the ISAs it defines, so object files can name them |
| `programs.py` | Running test programs against their expected output: metadata lines, the results table |
| `hw/netlist.py`, `hw/chips.py` | The netlist description language and the chip library: pins, parts variants |
| `hw/timing.json`, `hw/datasheets/`, `hw/build_timing.py` | Delays per part, built from the datasheet research |
| `hw/sta.py` | Static timing analysis with case analysis per microinstruction |
| `hw/runner.py` | Running a machine on the chip-level simulator, and the `hw` commands (run, test, sweep, bom, sta); what a machine module provides is in its docstring |
| `hwsim/` | The event-driven chip-level simulator, in Rust: chip models, setup and hold, write timing, bus contention. Python runs it as `heron.native.hwsim` (through `hw/runner.py`) |
| `si/` | Signal-integrity plumbing: IBIS models in ngspice, a 2D field solver, running ngspice |

`cargo test -p hwsim` and `cargo test -p toolchain` run the Rust crates'
tests.
