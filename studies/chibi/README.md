---
status: active
depends-on: [v2_isa, pcb_columns]
reports: [47]
---

# Chibi Heron

Draft 2's instruction set ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md))
on one board of about seventy chips, with 2 MB of RAM, 640 x 480 x 4 VGA,
two UARTs and PS/2 ports for a keyboard and a mouse. A fresh design rather
than a cut-down Heron Mini: a 16-bit datapath with 32-bit registers, one
internal bus and an operand latch on the ALU, unpipelined horizontal
microcode, no prefetch, one fixed cycle of 158.9 ns (four VGA pixels), and
ATF22V10s for nearly all the logic. The design and its measurements are
[RFC 0047](../../reports/0047-rfc-chibi-heron.md), with the tables in
[performance.md](../../reports/0047-rfc-chibi-heron/performance.md).

A first cut: the microcode and a register-transfer model checked against
draft 2's instruction-level simulator, and a chip-level netlist of the
whole board that runs the program suite on the chip-level simulator
exactly as the model does, cycle for cycle, with no timing violation.
Static timing analysis of the netlist says the period it needs.

It depends on `v2_isa` for the ISA, its simulator and the program suite,
and on `pcb_columns` for placing the board on RFC 0046's column grid.

| File | What's in it |
|---|---|
| `ucode.py` | The control word (67 bits in nine flashes), its fields and their encodings, the ALU's and the flags' operations, the immediates, the control store's address; placing a routine in its block |
| `routines.py` | The microcode: the decode, the addressing modes, the instructions, the interrupt and exception entries and reset; the control store |
| `rtl.py` | The register-transfer model: the datapath and sequencer, a cycle's two phases as the netlist has them |
| `system.py` | The board behind the model's CPU: the RAM, the I/O space, the suite's console |
| `check.py` | The model against the instruction-level simulator: the suite |
| `board.py` | The chip-level netlist: CPU, memory, I/O and video |
| `parts.py` | The parts, as a variant of the chip library |
| `hw.py` | The netlist on the chip-level simulator against the model |
| `sta.py` | Static timing analysis of the netlist: every distinct microinstruction's period |
| `report.py` | RFC 0047's performance.md |
| `place.py` | The draft netlist placed on [RFC 0046](../../reports/0046-rfc-column-grid.md)'s column grid: each part's package, the connectors on the edges, a few board sizes; RFC 0047's placement.md and placement.svg |
| `programs/` | Test programs for the board's own devices |
| `tests/` | The unit tests (`heron test chibi`) |

## Commands

```sh
heron chibi check [NAMES]           # the suite on the model against the simulator
heron chibi run FILE.s [--profile]  # one program on the model
heron chibi hw test [NAMES]         # the suite at chip level against the model
heron chibi hw run FILE.s [--trace A:B]
heron chibi hw sta [--paths N]      # static timing analysis: the period it needs
heron chibi hw bom                  # the parts list
heron chibi report [--write]        # RFC 0047's performance.md
heron chibi place [--write]         # placed on the column grid at a few sizes (about 5 minutes):
                                    # build/chibi/place/, RFC 0047's placement.md and .svg
heron test chibi                    # the unit tests
```

The chip-level suite takes about forty minutes (vm and mandel, about 9
million cycles each, most of it); the timing analysis a minute.

## Not done yet

- **Instructions:** LDM and STM, ADD.B4, the tagged operations (09-0D),
  FFS and POPC, MULU and MULS with the special mode's operand (EC, ED) and
  MERGE (EE). The suite doesn't use them; their blocks stop the machine.
- **Booting:** reset enters the program at 0 in RAM, which the simulator
  preloads. On the board the reset routine would copy the boot flash into
  RAM first.
- **The devices:** the UARTs, the PS/2 ports and the video are in the
  netlist, and a test program reads the keyboard at chip level, but
  nothing checks the UARTs or the video's picture yet.
