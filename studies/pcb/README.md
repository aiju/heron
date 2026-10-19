---
status: active
depends-on: [v1b_system, bus_si, v1b_hw, mini]
reports: [23, 26]
---

# Printed circuit boards

How the system's cards (`studies/v1b_system`) become printed circuit boards
that are checked to be the netlists the chip-level simulator runs: the CPU
card as a surface-mount board and as a plain DIP board, placed and routed
by code, written as KiCad boards, and checked against the netlist in four
independent ways. The flow and the reasons for it are in RFC 0023; the
design rules the boards follow (the card in its case, assembly, spacing)
are in RFC 0026.

The reusable parts are in `infra/pcb` (packages and pinouts, the board
model and KiCad writer, placement, power fanout, the router's driver, the
checks, the routed wires' delays, DSN/SES for other routers) and
`infra/pcbroute` (the grid router, in Rust). This study has the cards, the experiments and the commands.

| File | What's in it |
|---|---|
| `cards.py` | The cards as boards: their netlists, the DIN 41612 connectors at the back edge and their pin maps, the grid's slot sizes, the timing-critical nets for placement; Heron Mini's boards (`mini-cpu1`, `mini-cpu2`, `mini-io`) through `mini.py` |
| `mini.py` | Heron Mini's stacked A4 boards (report 0044): the stack's mechanics (standoff holes, power connector, fiducials), each ribbon cable's headers at the same site on both its boards, the cables' delays; each net's delays across the routed boards and the cables, for the mini's timing analysis and chip-level runs (`--pcb`); what fits on A4 as SMD or DIP; placement weights for the nets the delays slow (`mini-weights.json`); report 0044's tables |
| `flow.py` | The flow for one board: parts, placement, fanout, routing, the board file and a picture, the checks |
| `sweep.py` | The experiments: board sizes, layer counts, SMD and DIP, one and two sides, the routed wires back in the simulation and the timing analysis, Freerouting |
| `split.py` | What splitting the CPU card in two would cost |
| `cli.py` | The commands |

```sh
heron pcb build cpu --size 340x233.35         # place, route and check the CPU card (SMD, 6 layers, a grid, 6U)
heron pcb build cpu --style dip --size 490x345 --layers 4   # the DIP version
heron pcb build cpu --free --size 320x233.35  # the parts anywhere, not on a grid
heron pcb build mini-cpu1 --size 297x210      # one of Heron Mini's boards (A4, its IDC headers)
heron pcb build mini-cpu1 --size 297x210 --tight   # ... as DIP soldered by hand (1 mm between pads)
heron pcb mini build [--variant V | --all]    # Heron Mini's CPU boards, each variant of report 0044
heron pcb mini delays                         # their nets' delays: build/pcb/mini-delays.json
heron pcb mini sta                            # the mini's timing analysis with them
heron pcb mini tune                           # placement weights from the nets they slow
heron pcb mini report [--write]               # report 0044's tables (results.md, delays.json)
heron pcb view                                # the boards as a web page: build/pcb/viewer.html
heron pcb build cpu --router freerouting      # route with Freerouting instead (needs its jar)
heron pcb check build/pcb/<name>/board.kicad_pcb   # check a board file against the netlist
heron pcb pinouts                             # the pinouts against KiCad's symbols
heron pcb split                               # the signals between two halves of the CPU card
heron pcb sweep [--write]                     # the experiments (about two hours; --only, --reuse)
heron test pcb                                # the unit tests
```

Boards go to `build/pcb/<name>/`: `board.kicad_pcb` and its
`board.kicad_pro` (the design rules), `board.png`, `result.json`.

**What it needs:** KiCad 9 or later for its footprint and symbol
libraries (`/usr/share/kicad`, or `KICAD9_FOOTPRINT_DIR` and
`KICAD9_SYMBOL_DIR`); its `kicad-cli` for the DRC, and its `pcbnew`
Python module to fill the planes before the copper check (in whichever
Python has it: KiCad's packages build it for the distribution's Python,
which may not be the one running the flow; `KICAD_PYTHON` names it). Without them
the commands that need them say so, and the tests that need them are
skipped. Freerouting only for the comparison (`FREEROUTING_JAR`).
