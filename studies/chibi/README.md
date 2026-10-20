---
status: active
depends-on: [v2_isa, pcb_columns]
reports: [47]
---

# Chibi Heron

Draft 2's instruction set ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md))
on one board of 110 packages, with 2 MB of RAM, 640 x 480 x 4 VGA
through a palette, a microcoded copper, two serial ports, PS/2 ports and
PCM sound received and played by a microcode task, a timer, a
CompactFlash slot, a boot flash and a debugger in microcode (ODT). The **two-halves machine**: a 16-bit datapath that does a
32-bit operation in one microinstruction as two halves, on variable
cycles in ticks of 19.86 ns, with horizontal unpipelined microcode in a
flat store (every word names the next), ATF22V10s for the decode and
the state machines and most registers, 74 parts for the plain registers
and the buses. The design and its measurements are
[RFC 0047](../../reports/0047-rfc-chibi-heron.md), with the tables in
[performance.md](../../reports/0047-rfc-chibi-heron/performance.md) and
[placement.md](../../reports/0047-rfc-chibi-heron/placement.md).

The microcode and a register-transfer model are checked against draft 2's
instruction-level simulator. A chip-level netlist of every chip on the
board runs the program suite on the chip-level simulator exactly as the
model does, cycle for cycle, with no timing violation. Static timing
analysis of the netlist gives every microinstruction its length.

The **first cut**, one fixed cycle of 158.9 ns on 70 packages, is kept
beside it (the files without a 2; `--first`).

It depends on `v2_isa` for the ISA, its simulator and the program suite,
and on `pcb_columns` for placing the board on RFC 0046's column grid.

| File | What's in it |
|---|---|
| `ucode2.py` | The control word (72 bits in nine flashes), its fields and encodings, the immediates, the flag operations, the sequencer's next addresses |
| `routines2.py` | The microcode, as blocks of (page, N, opcode) and named routines: the decode, the addressing modes, the instructions, the interrupt and exception entries, reset and the boot, the copper, the device task (PCM and PS/2); the control store, its lengths from `ticks.json` |
| `flat.py` | The routines compiled into the flat store: their states followed, the alike merged, the dispatches made 16-way branches, the words laid out |
| `odt.py` | ODT, the console monitor in microcode |
| `rtl2.py` | The register-transfer model: phase F and the two halves as the netlist has them, tasks |
| `system2.py` | The board behind the model: RAM, the I/O space and its map, UART 0, the scanline, the PS/2 devices, the timer's counter 1 and the DAC, the suite's console |
| `board2.py` | The chip-level netlist: every chip on the board |
| `gals.py`, `gals.md` | Every 22V10's pins and equations, as the netlist has them (generated) |
| `draft.py` | Device parts that board2.py uses: chip types, part names, the PS/2 ports |
| `sta2.py` | Static timing analysis of the netlist: each distinct microinstruction's halves in ticks; writes `ticks.json` |
| `check.py` | The model against the instruction-level simulator: the suite |
| `hw.py` | The netlist on the chip-level simulator against the model; ODT's session, the copper's test and the device task's |
| `report.py` | RFC 0047's performance.md |
| `pipeline.py` | What a pipelined control store would buy: an estimate from the suite's microinstructions (RFC 0047's pipelining.md) |
| `place.py` | The netlist placed on [RFC 0046](../../reports/0046-rfc-column-grid.md)'s column grid at a few board sizes; RFC 0047's placement.md and placement.svg |
| `parts.py` | The parts, as a variant of the chip library |
| `ucode.py`, `routines.py`, `rtl.py`, `system.py`, `board.py`, `sta.py` | The first cut |
| `programs/` | Test programs for the board's own devices: the keyboard, PCM, ODT, the copper |
| `tests/` | The unit tests (`heron test chibi`) |

## Commands

```sh
heron chibi check [NAMES] [--first] # the suite on the model against the simulator
heron chibi run FILE.s [--profile]  # one program on the model
heron chibi hw test [NAMES]         # the suite at chip level against the model
heron chibi hw run FILE.s [--trace A:B]
heron chibi hw odt                  # ODT's session at chip level, against the model
heron chibi hw copper               # the copper's test at chip level
heron chibi hw devices              # the device task's (PCM, the keyboard) at chip level
heron chibi hw sta [--write]        # static timing analysis; --write: ticks.json
heron chibi hw bom                  # the parts list
heron chibi hw gals [--write]       # every 22V10's equations; --write: gals.md
heron chibi report [--write]        # RFC 0047's performance.md (a few minutes)
heron chibi pipeline                # a pipelined control store's estimate (a few minutes)
heron chibi place [--write]         # placed on the column grid (about 5 minutes):
                                    # build/chibi/place/, RFC 0047's placement.md and .svg
heron test chibi                    # the unit tests
```

After changing the netlist or the microcode, run `heron chibi hw sta
--write`: the unit tests fail while a microinstruction isn't in
`ticks.json`. The chip-level suite takes about forty minutes, most of it
vm and mandel (5–6 million cycles each); the timing analysis a few
minutes.

## Not done yet

- **The chip-level suite** on this revision of the netlist: hello, fib,
  interrupts, monitor, queens, rpn and strings pass, with ODT's session,
  the copper's test and the device task's; the rest hasn't been run yet.
- **The expansion port** at 0xFFFE_0000: its decode and buffers.
- **A checker for tasks:** that the tasks keep to a task's rules, and
  every task point to its own.
- **JEDEC files** for the 22V10s.
- **The devices at chip level:** ODT on UART 0, the copper, PCM and the
  keyboard are tested; the picture, the palette, the DAC's analog side,
  the CF card, the mouse and UART 1 aren't.
