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
| `hw/schematic.py`, `hw/schematic.html` | A netlist as a schematic in one HTML page: a sheet for each section (`nl.section`), laid out in the browser by ELK; nets followed across sheets and cards |
| `hw/sta.py` | Static timing analysis with case analysis per microinstruction |
| `hw/runner.py` | Running a machine on the chip-level simulator, and the `hw` commands (run, test, sweep, bom, sta); what a machine module provides is in its docstring |
| `hwsim/` | The event-driven chip-level simulator, in Rust: chip models, setup and hold, write timing, bus contention. Python runs it as `heron.native.hwsim` (through `hw/runner.py`). Its system runner plays a whole system from power-up, with oscillators, the power-on reset, pull-ups and open-collector outputs as parts; its `vector` fixture plays a script against a clock, for bus-functional tests |
| `devices/` | Register-level models of the I/O chips, in Rust: the 16C550 UART (with the terminal on its line), the 82C54 timer, a CompactFlash card in True IDE mode. hwsim puts pins on them; an instruction-level model uses them as they are |
| `si/` | Signal-integrity plumbing: IBIS models as behavioural sources, a 2D field solver for traces and a pin-field model for connectors, the SPICE-netlist front end to the simulators (`engine.py`), ngspice, and a runner for sweeps that kills jobs past their deadline |
| `sisim/` | The fixed-step transient simulator for signal integrity, in Rust: lossless and coupled lines, IBIS tables, diodes. Python runs it as `heron.native.sisim` (through `si/engine.py`) |

`cargo test -p hwsim`, `cargo test -p devices`, `cargo test -p sisim` and
`cargo test -p toolchain` run the Rust crates' tests.
