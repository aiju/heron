---
number: 23
type: rfc
title: Printed circuit boards: a flow from the netlist to checked boards
status: draft
date: 2026-10-15
context:
  studies: [pcb, system, bus_si]
  commit: 2f81658
---

# RFC 0023: Printed circuit boards: a flow from the netlist to checked boards

## Contents

1. [Summary](#1-summary)
2. [How Claude can design a board](#2-how-claude-can-design-a-board)
3. [KiCad, our own tools, or something else](#3-kicad-our-own-tools-or-something-else)
4. [The flow](#4-the-flow)
5. [Making sure the board is the simulated netlist](#5-making-sure-the-board-is-the-simulated-netlist)
6. [The CPU card: size, layers, SMD or DIP](#6-the-cpu-card-size-layers-smd-or-dip)
7. [What the board says about the design](#7-what-the-board-says-about-the-design)
8. [Limits and what's next](#8-limits-and-whats-next)
9. [Open questions](#9-open-questions)

The numbers are in [results.md](0023-rfc-pcb-flow/results.md), which
`heron pcb sweep --write` generates; the code is `infra/pcb`,
`infra/pcbroute` and [studies/pcb](../studies/pcb/README.md).

## 1. Summary

**Recommended:** a flow of our own, from the netlist the simulator runs to
a KiCad board, with KiCad for what it does best (its libraries, its design
rule check, its plane filler, its Gerber writer, a GUI to look and
touch up), and four independent checks that the board is that netlist.

| Step | How | Where |
|---|---|---|
| **The source** | The Python netlist the chip-level simulator runs. Nothing about connectivity is ever edited on the board | `infra/hw/netlist.py`, the studies |
| **Packages and pinouts** | A table per chip type, checked against KiCad's symbol library; footprints from KiCad's library | `infra/pcb/packages.py` |
| **Parts** | Every chip with its supply pins, a decoupling capacitor each, the connectors by the bus's pin map | `infra/pcb/physical.py` |
| **Placement** | Quadratic placement, legalisation on a grid, annealing on wire length; capacitors under each chip | `infra/pcb/place.py` |
| **Routing** | Our own grid router (negotiated congestion), in Rust: the whole CPU card in under a minute | `infra/pcbroute` |
| **The board file** | Written directly as KiCad 9 s-expressions, with a project file holding the design rules | `infra/pcb/board.py` |
| **Checks** | Pinouts against KiCad's symbols; pads against the netlist; copper connectivity from geometry, and KiCad's DRC; the fab's test netlist against the board | `infra/pcb/check.py`, `copper.py` |
| **Timing** | The routed wires' delays back into the chip-level simulator | `infra/pcb/wires.py`, hwsim's per-pin delays |
| **Fab files** | Gerbers, drill, placement and the IPC-D-356 test netlist, by `kicad-cli` | `studies/pcb/flow.py` |

**For the CPU card** (269 chips): surface-mount parts, **six layers, about
300 × 220 mm**, parts on the top and the decoupling capacitors underneath.
It places in under a minute and routes in under a minute, with no DRC
errors, and every check passes. The DIP version needs about twice the area
(480 × 300 mm on six layers). Four layers aren't enough for either at a
sensible size, and splitting the CPU over two cards costs at least 171
signals between them.

**The finding that matters most:** with the routed board's wire delays
back in the simulator, the machine that passes every test with ideal
wires **stops after 11 cycles**. The CPU clock is one 74F175 output driving
53 inputs over 1.4 m of copper, 376 pF; the board adds about 19 ns to it.
Flight times alone (up to 3.2 ns) give 874 setup violations. A board needs
a clock tree, buffers on the heavy nets and timing-driven placement, and
the flow must keep putting the board's delays back into the simulation
(section 7).

## 2. How Claude can design a board

PCB design tools are made for a person at a screen: drag parts, watch the
ratsnest, push tracks. Claude can't use them that way, and shouldn't
try. What it can do well:

- **write programs** that produce the board, from a description it can
  read and change: the netlist is already one;
- **read files and numbers**: a board file is text, a DRC report is JSON;
- **look at pictures**: the flow renders every board as a PNG
  (`board.png`), and Claude can read images. That is how the placements
  here were reviewed;
- **run checks** and act on what they say.

So the board must come out of code, end to end, with every judgement
written down as a rule (where the capacitors go, which side the connector
is on) and every result checked by a program. A person then reviews the
picture, opens the board in KiCad if they like, and can touch up anything
that doesn't change connectivity (silkscreen, a track's shape). That is
also what makes the board reproducible: rebuild it after a netlist change
and it comes out checked again.

This also answers how much of the work is the model's: the code here was
written by Claude in one session, and every board in the tables was
produced and checked without a person in the loop.

## 3. KiCad, our own tools, or something else

The pieces of a PCB flow, and who should do each:

| Piece | Choice | Why |
|---|---|---|
| Netlist | **Ours** (`infra/hw`) | It exists and the simulator runs it. A schematic would be a second source to keep in step |
| Footprints | **KiCad's library** | Thousands of IPC-7351 footprints with 3D models, maintained. Writing our own is easy to get subtly wrong (paste, courtyards) |
| Pinouts | **Ours, checked against KiCad's symbols** | Our chips' pin names are the simulator's; the check found a real error (section 5) |
| Placement | **Ours** | Nothing headless and scriptable does it well. The problem is small enough (270 parts) for textbook methods |
| Routing | **Ours** | Freerouting, the open alternative, did not finish (below) |
| Board file | **KiCad's format, written directly** | Text, stable, documented, and every fab and tool reads what KiCad writes. No dependency on KiCad's Python API to write it |
| DRC, plane fill, Gerbers | **KiCad** (`kicad-cli`, its `pcbnew` module) | Mature, independent of our code, and the fab's tooling expects its output |
| Viewing and touch-ups | **KiCad's GUI** | For a person |

**KiCad's own scripting** was not used for the core of the flow:

- the SWIG Python module (`pcbnew`) is deprecated since KiCad 9 and due to
  go; the flow only uses it to fill the planes before the copper check;
- its new IPC API needs a running KiCad GUI in KiCad 9 and 10;
- its file format is the stable interface: KiCad reads old files forever.

**Freerouting**, the open-source autorouter KiCad users reach for (Java,
Specctra DSN in, SES out; `infra/pcb/dsn.py` writes and reads both),
was run on the same CPU card placement:

- [results pending: the first run with the planes as power layers, two
  hours; the second with only the signal layers and its fanout off, an
  hour.]

**Our router** routes the same board in about 30 seconds. It is a grid
router with negotiated congestion (PathFinder, the algorithm of FPGA
routers): every net is routed alone, nodes shared by two nets cost more
in each round, and nodes that stay contested build up a history cost,
until no node is shared. The grid's pitch is a track's width plus the
clearance (0.254 mm), so tracks of different nets may use neighbouring
grid lines; a via keeps other nets out of the nodes around it on every
layer; a multi-pin net grows as a tree, A* from the tree to the nearest
pad not yet reached. It is about 850 lines of Rust, and the things that
made it fast were the ones every router book lists: the heuristic must
count the via still to come, and a multi-pin net must aim at one pad at a
time, not at all of them.

**Other things considered:**

- **atopile, SKiDL:** languages that describe a circuit and hand it to
  KiCad, where a person places and routes. Our netlist language already
  does the describing; the placing and routing is what we need.
- **tscircuit:** circuits as TypeScript/React with its own autorouter. A
  third language, and a young router.
- **Horizon EDA, LibrePCB:** GUI tools, fine for a person.
- **Commercial AI placers and routers** (Quilter, DeepPCB, Cadence's):
  cloud services, paid, and not reproducible from the repository.
- **Entirely our own, Gerbers included:** possible (Gerber is simple), but
  it would throw away KiCad's footprints, DRC and viewer for nothing.

## 4. The flow

```sh
heron pcb build cpu --size 300x220     # place, route, check: build/pcb/<name>/
heron pcb check board.kicad_pcb        # check a board file against the netlist
heron pcb pinouts                      # the pinouts against KiCad's symbols
heron pcb sweep --write                # the experiments behind this RFC
```

One build, for the CPU card at 300 × 220 mm:

1. **Parts** (`physical.parts`): the card's netlist (`studies/system`)
   through the pinout table. Each chip keeps the simulator's reference
   (`U_ALU3`), so a board's part and the simulator's chip are the same
   name. Tied pins (a clock driver's enables, the supervisor's capacitor
   pins) get their rail or a capacitor; the connectors' pads get their bus
   signals by report 0022's reference pin map.
2. **Placement** (`place.Placer`): quadratic placement with the connectors
   as anchors, spread by recursive bisection to the board's density; then
   each part to the nearest free spot (a summed-area table over the
   occupancy makes that a vectorised search), and annealing that swaps
   same-footprint parts and turns them by 180°. Then each chip's 100 nF
   goes under it on the bottom, between its pin rows, as near its VCC pin
   as its vias can go clear of the pads.
3. **Fanout** (`fanout.fanout`): every surface pad on a supply gets a via
   just beyond its end; the planes do the rest. The router never sees the
   supplies.
4. **Routing** (`router.route`): the grid router on the four signal layers
   (top and bottom any way, the inner two horizontal and vertical).
5. **The board file**: KiCad 9 format, a project file with the rules (the
   standard six-layer process of a common fab: 0.127 mm tracks and gaps,
   0.2 mm holes in 0.45 mm vias), and a PNG.
6. **Checks** (section 5), and the fab files.

The stackup is signal, ground, signal, signal, power, signal: each signal
layer next to a plane, the two inner signal layers crossing at right
angles.

**What it takes:** about 40 s to place, 30–60 s to route, and three
minutes to check (most of it KiCad's DRC). Boards are build output, not
committed: a routed board is 24 MB of KiCad's text, and it comes back in
two minutes.

## 5. Making sure the board is the simulated netlist

The chain from the simulator to the fab has five links. Each is checked
by code, and the important ones by two programs that don't share code.

| Link | Check | Independent of |
|---|---|---|
| 1. The simulator's logical pins → package pins | `heron pcb pinouts`: every pinout against KiCad's symbol library | our pinout table: KiCad's librarians transcribed the same datasheets |
| 2. The netlist → the board's pads | `check.compare`: the board file read back, its pads' nets against the netlist through the pinouts, as partitions (names don't matter) | the code that built the board |
| 3. The pads' nets → the copper | `copper.check`: connectivity from the copper's geometry alone (tracks, vias, pads, the filled planes); and KiCad's DRC (`unconnected`, `shorting_items`) | each other, and the router |
| 4. The board → the fab | `check.compare_ipc356`: the IPC-D-356 netlist the fab tests the bare boards against, matched to pads by position | KiCad's net labels |
| 5. The board's wires → the timing | `wires.nets`: each net's copper as a graph, flight time to each load and the load in pF, back into hwsim as per-pin delays | — (section 7) |

**What each link caught while this was being built:**

- **Pinouts:** the TL7705A's active-low RESET is pin 5, not 6. KiCad's
  library had it right. The 42 pinouts KiCad has symbols for now all
  agree; the 74ABT823 and the CDC341, which it lacks, were checked against
  TI's datasheets by hand (the other two are an oscillator and a resistor
  network).
- **Copper:** the router ended a track in the corner of the oscillator's
  rounded pad, where there is no copper. KiCad's DRC reported it; our
  copper check didn't, because it shared the router's model of a pad as a
  sharp rectangle. Both now model rounded rectangles exactly, and agree.
  That is why link 3 has two checkers.
- **The fab's netlist:** KiCad truncates references to six characters in
  IPC-D-356 (`U_UIR15` becomes `U_UIR1`), so it is matched by position.

**The rules that keep it true:**

- **One source.** Anything that changes connectivity (a gate swapped to
  another package, pins swapped for routing, an address line moved) is a
  change to the netlist's Python, so the simulator runs it. The board is
  regenerated; `compare` fails on a board whose connectivity was edited
  by hand.
- **Parts the simulator doesn't have** are allowed only by rule: a
  decoupling capacitor `C<chip>` from VCC to GND, a tied pin's capacitor
  `C<chip>.<pin>`, the connectors by their pin map. Anything else fails.
- **The checks are tests:** `heron test pcb` builds a small board and
  checks that each check catches a swapped pin, an extra part, an open
  and a short. With KiCad's libraries in CI, it could also rebuild and
  check the CPU card on every change to its netlist (about four minutes).

## 6. The CPU card: size, layers, SMD or DIP

| Board | mm | Layers | Result |
|---|---|---|---|
| SMD, parts on top, capacitors under | 380 × 220 | 6 | routed; all checks pass |
| | 300 × 220 | 6 | routed; all checks pass |
| | 280 × 220 | 6 | routed, near the limit |
| | 260 × 220 | 6 | the parts don't fit |
| SMD, everything on top | 320 × 220 | 6 | [pending] |
| SMD, parts on both sides | 280 × 220 | 6 | routed |
| | 260 × 220 | 6 | not routed |
| SMD | 380 × 220 | 4 | [pending] |
| DIP | 480 × 300 | 6 | routed |
| | 440 × 300 | 6 | [pending] |
| | 520 × 300 | 4 | [pending] |

From these:

- **The limit is routing, around 60,000 mm² on six layers.** Below that,
  even with parts on both sides, the last nets don't resolve. Four signal
  layers carry about 115 m of track on this card; more layers or finer
  rules would shrink it, but neither is cheap.
- **One card is enough.** RFC 0005 expected the CPU to need two. On
  surface-mount parts and six layers it fits one card of about 300 × 220.
  Splitting it is costly: the best two-way split found (a min-cut
  bipartition) cuts 171 signals, control against datapath 201; the
  backplane's spare pins are about 52 per slot.
- **The card's height** comes from its connectors: P1 and P2 are 95 mm
  each, so 220 mm is about the least for both. Its depth then follows from
  the area: 300 mm. That is not a Eurocard size (6U is 233.35 mm high, and
  the common depths are 160, 220 and 280 mm), though 233 × 280 has about
  the same area and should route too.
- **Six layers, not four.** RFC 0005 recorded four-layer boards. With
  surface-mount parts, four layers leave two signal layers, one of them
  crowded with pads: [pending].
- **DIP needs twice the area:** 480 × 300 mm on six layers. The parts'
  footprints are twice as large (75,000 mm² against 37,000), and the
  through-hole pins block every layer.
- **Parts on both sides** save little: 280 × 220 against 300 × 220. It
  costs a second assembly pass for chips; the capacitors underneath
  already need one, but a fab charges less for a side of capacitors.

**Packages:** 74-series logic in SOIC (all of it is made in SOIC, and
SOIC is easy to rework); the microcode flash in PLCC-32 sockets, so it can
be reprogrammed; the 74LS181 and 74S182, which are only new-old-stock, in
DIP; the fast SRAMs in SOJ. TSSOP isn't needed: the board is limited by
routing, not by the parts' size.

## 7. What the board says about the design

The simulator runs the design with the datasheets' delays, which are for
a 50 pF load, and with ideal wires inside a card (only the backplane's
settling is modelled). A routed board has neither. `wires.nets` measures,
for every net, its copper, the flight time to each load along it, and the
load: the inputs' capacitance plus the track's. `wires.back_annotate`
turns that into extra delay per driving pin, and hwsim now takes a delay
per output pin (`pin_delays`, `Instance.add_pin_delay`).

`hello` on the whole system, with the CPU card's wires from the
300 × 220 board ([results.md](0023-rfc-pcb-flow/results.md)):

| Wires | Output | Violations |
|---|---|---|
| ideal, as simulated so far | right | 0 |
| flight times only | right | 874 |
| extra load, but not on CLK | right | 5240 |
| extra load on CLK alone | the machine stops after 11 cycles | 0 |

[to update from results.md]

- **CLK** is one output of a 74F175 driving 53 inputs over 1.38 m of
  copper: 376 pF, about 16 ns more than at 50 pF, and up to 3.2 ns of
  flight between its first and last load. It needs a clock tree: a
  low-skew driver (a CDC341, as the bus clock has) feeding a few branches,
  each with a series resistor and a handful of loads.
- **The microcode address lines** Y0–Y16 each drive 17 ROMs over half a
  metre (120 pF, 9 ns extra), FILL 37 inputs, FAULT 21. They want
  buffering, or the ROMs closer together.
- **The setup violations** with flight times alone are on the MAR
  registers, whose path is the one the length classes were tuned to, and
  on the clock generator's 20 ns domain, which allows one 74F gate
  between flip-flops: 0.2 ns of wire breaks it. Timing-driven placement
  (the clock generator together, the MAR beside the ALU) and the length
  classes worked out with the board's delays would fix them.
- **The violations don't show the failure.** With CLK late, the machine
  goes wrong and hwsim reports no violation at all: the clock's own
  lateness moves every capture with it. The output check caught it.

So the loop has to stay closed: the static timing analysis
(`infra/hw/sta.py`) and the length classes should take the board's
delays too, and a board is done only when the simulation with its wires
passes.

## 8. Limits and what's next

- **The router** is grid-based and orthogonal: no 45° tracks, no length
  matching, no differential pairs, one track width. Enough for this
  logic; the clock tree may want length matching later.
- **The placer** is simple; the size limit it shows at 260 × 220 is
  partly its own. Timing-driven placement (weights on the critical nets)
  is the next thing it needs.
- **Not built yet:** the memory card, the I/O card and the backplane as
  boards (the AS7C4096A, the 16C550 and the CF socket need pinouts), and
  the connectors' consistency between card and backplane, which the same
  `compare` would check on the backplane's board.
- **Signal integrity on the card:** the bus study's engine
  (`infra/sisim`) could simulate the clock tree's branches from the
  routed lengths.
- **Mechanics:** mounting holes, ejectors, the card guides' keep-outs,
  panelisation. The case is a later problem.

## 9. Open questions

For Emily:

1. **The flow:** our own placer and router, with KiCad for footprints,
   DRC, plane filling, Gerbers and viewing (recommended)?
2. **KiCad as a dependency:** install it in CI so `heron test pcb` can
   build and check boards there, or vendor the few footprints the cards
   use (CC-BY-SA, with KiCad's exception for designs)?
3. **SMD or DIP** for the CPU card? SMD (recommended) is 300 × 220 on six
   layers; DIP is about 480 × 300 on six.
4. **Layers:** six, not the four RFC 0005 recorded?
5. **Card size:** about 300 × 220, or a standard 6U × 280 (233 × 280)?
   The memory and I/O cards are small; their size can follow the CPU
   card's or be smaller.
6. **Assembly:** the decoupling capacitors underneath (a second, cheap
   assembly side), or everything on top on a larger board?
7. **The design changes** of section 7: a clock tree for CLK, buffers on
   the heavy nets. They belong in the system study.
8. **hwsim's per-pin delays** come with this RFC; should the static timing
   analysis take the board's delays next?
