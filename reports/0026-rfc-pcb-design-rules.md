---
number: 26
type: rfc
title: PCB design rules
status: open
date: 2026-10-15
context:
  studies: [pcb]
  commit: cc89b79
---

# RFC 0026: PCB design rules

The rules every printed circuit board of the machine follows: how a card
fits its case, how it is made and assembled, how its parts are placed,
and when it is done. They are for whoever builds the next board, person
or agent. Section 1 is the rules alone, numbered so a board, a review or
an RFC can cite them. Section 2 says why, with the sources and the
numbers they give. Section 3 is what is still open.

The flow of [RFC 0023](0023-rfc-pcb-flow.md) applies most of these rules
by itself; section 1.7 says where. The rules come first, though: a rule
the flow does not apply yet still holds, and the flow should learn it.

## Contents

1. [The rules](#1-the-rules)
   1. [Board and process](#11-board-and-process)
   2. [Outline and mechanics](#12-outline-and-mechanics)
   3. [Holes](#13-holes)
   4. [Placement](#14-placement)
   5. [Assembly](#15-assembly)
   6. [When a board is done](#16-when-a-board-is-done)
   7. [Where the flow applies them](#17-where-the-flow-applies-them)
2. [Rationale and sources](#2-rationale-and-sources)
3. [Open questions](#3-open-questions)
4. [Sources](#4-sources)

## 1. The rules

Terms: the **front** edge carries the front panel, the **back** edge the
backplane connectors, and the **guided** edges (top and bottom) run in
the card guides. A **gap** is copper edge to copper edge. A **courtyard**
is a footprint's IPC-7351 courtyard, 0.25 mm beyond its pads and body.
THT is through-hole, SMD surface-mount.

### 1.1 Board and process

- **R1 Board.** FR-4, 1.6 mm. A card that runs in guides is ordered at
  1.6 +0.2/−0 mm where the fab offers it.
- **R2 Stack-up.** Four layers (signal, ground, power, signal) or six
  (signal, ground, signal, signal, power, signal). Every signal layer
  lies next to a plane, and the stack-up is symmetric.
- **R3 Minimums.** Track and gap 0.127 mm. Vias 0.45 mm with a 0.2 mm
  hole. Copper keeps 0.25 mm from any hole's edge and 0.5 mm from a
  routed board edge, on every layer.
- **R4 Flatness.** Bow and twist at most 0.5%, stated in the order.
- **R5 Edges.** Routed (milled), ±0.2 mm or better. A guided edge has no
  V-score, mouse bites or break-off nubs. Where an assembly rail was
  broken off a guided edge, the edge is sanded flush.
- **R6 Thermal relief.** A through-hole pin joins a plane through four
  spokes, 0.3 to 0.5 mm wide. No via of another net comes within 0.6 mm
  of such a pad's edge, so that the holes those vias leave in the plane
  don't cut off the spokes; KiCad's DRC requires at least two. Tracks
  may pass on the signal layers, which the plane doesn't share; where a
  pour shares a layer with tracks, they keep the same distance.

### 1.2 Outline and mechanics

- **R7 Size.** A Eurocard size where the parts fit one:
  - heights: 3U is 100 mm, 6U 233.35 mm, 9U 366.7 mm;
  - depths: 100 to 400 mm, in steps of 60.

  Otherwise any size within the assembly limits of R23.
- **R8 Guided edges.** Within 5 mm of a guided edge, on either side:
  - no components;
  - no copper within 2.5 mm, except an ESD strip if the case uses one
    (1.5 mm wide, 1.0 to 2.5 mm from the edge).
- **R9 Front edge.**
  - A strip 8 mm deep with no components.
  - Holes for the front panel's bracket: M2.5 (ø2.7 mm, non-plated),
    3.57 mm from the front edge and 5.5 mm from each guided edge.
  - A third hole halfway along the front edge on a card taller than 6U.
- **R10 Back edge.**
  - The connectors are DIN 41612, with the outer pin row 5.3 mm from
    the edge (their mounting holes are then 2.76 mm from it).
  - On a card 6U or taller, P2's middle is 50 mm from the bottom edge
    and P1's 133.35 mm above it: the Eurocard positions.
  - Nothing else in the strip the connectors take.
  - Copper keeps 2.5 mm from the guided edges there, as everywhere
    (R8).
- **R11 Heights.**
  - Top side: at most the slot pitch less 6.61 mm. That is 13.71 mm at
    4HP (20.32 mm) and 18.79 mm at 5HP.
  - Bottom side: at most 2.47 mm including the board's warp. In
    practice that means flat SMD passives no thicker than 1.3 mm, and
    THT leads trimmed to 1.5 mm.
- **R12 Insertion force.** A card with two 96-pin connectors needs about
  180 N to pull out. It gets injector/extractor handles (IEEE 1101.10)
  at its front corners.
- **R13 Stiffening.** A card larger than the largest Eurocard (9U × 400)
  gets a stiffener bar on M3 holes, or a thicker board milled to 1.6 mm
  along its guided edges.

### 1.3 Holes

- **R14 Mounting holes.**
  - M2.5 holes are ø2.7 mm; M3 holes are ø3.2 mm (close fit).
  - Non-plated, unless the screw grounds the card. Then plated and on
    chassis ground.
  - Around each hole, on both sides, no components and no copper but
    the hole's own: ø7 mm for M2.5, ø8 mm for M3.

### 1.4 Placement

- **R15 Arrangement.** The chips sit in rows and columns on a grid of
  slots, all the same way round (pin 1 at the top left).
  - Each chip sits at the top of its slot, centred across it.
  - A part bigger than a slot takes whole slots, starting on an even
    column or row, so the columns stay aligned.
  - The slot size comes from the board's package mix: the smallest that
    holds most packages in one slot.
- **R16 Spacing.** Gaps, pad to pad:

  | Between | Least gap |
  |---|---|
  | SMD and SMD | 1.3 mm between ICs (0.8 mm between courtyards); courtyards never overlap |
  | SMD and THT | 2.5 mm |
  | THT and THT | 2.54 mm |

  Components keep their distance from the edges by R8 to R10.
- **R17 Bottom side.**
  - Only flat passives go on the bottom side; no ICs on a board with THT
    parts.
  - No bottom-side part within 5 mm of any THT pad, and nothing under a
    THT part.
- **R18 Decoupling.**
  - One 100 nF capacitor (0603) per IC.
  - It goes under the IC on the bottom, between the pin rows, as near
    the supply pin as its vias can be while clearing the IC's pads and
    keeping R17.
  - Where it can't go under the IC (a small IC, a THT IC, a spot within
    5 mm of a THT pad), it goes beside the IC at its supply end, on top.
- **R19 Supplies.**
  - Power and ground are planes.
  - Every supply pad gets its own via, at the pad's inner end under the
    body where that is clear, otherwise at its outer end.
  - Supply nets are never routed as tracks.
- **R20 Timing.** Wires the timing depends on are kept short in
  placement: the nets of the fastest clock domain weigh more. A net the
  board simulation (R30) shows failing is placed shorter or buffered
  until it passes. A clock with more than a handful of loads is driven
  through a clock tree, not one output.

### 1.5 Assembly

- **R21 Fiducials.**
  - Three on each side that has parts, in an L that isn't symmetric.
  - Each is 1.0 mm copper, centred in a 3.0 mm circle with no mask or
    other copper.
  - Their circles stay out of the guide strips (R8): centres at least
    7 mm from a guided edge and 5 mm from the others.
  - No local fiducials while every pitch is 0.5 mm or more.
- **R22 Conveyor edges.**
  - Two parallel edges with no components within 5 mm; the guided edges
    are these.
  - If a house adds rails anyway, R5 applies to the edges they leave.
- **R23 Size for assembly.**
  - Up to 6U × 340 (233.35 × 340 mm), a card fits every assembly house
    surveyed.
  - Larger cards fit only some: up to 460 × 500 mm at JLCPCB, and up to
    400 × 510 mm at Eurocircuits by arrangement.
- **R24 Footprints.** KiCad's library: IPC-7351 at nominal density, never
  high density.
- **R25 Through-hole parts.**
  - As few as the design allows. Each THT joint is soldered selectively
    or by hand, and the houses charge per joint.
  - *Pending (section 3):* a THT pad that may be soldered by hand has at
    least X mm of copper around its hole. Many library footprints have
    less (section 2.4), so this rule will mean choosing or drawing
    footprints with larger pads.
- **R26 Files.**
  - Gerbers (copper, mask, paste, silkscreen, outline) and Excellon
    drill files.
  - A placement file (CSV, mm, both sides) and a BOM.
  - The IPC-D-356 netlist for the fab's electrical test.
  - Rotations as KiCad writes them, checked in the house's own preview.
    Conventions differ: JLCPCB follows IPC-7351, Eurocircuits IEC
    61188-7.
- **R27 Silkscreen.** Every part has its reference designator and a pin-1
  mark, outside its pads.
- **R28 Test.** The fab tests the bare board against the IPC-D-356
  netlist; no test pads are needed for that. In-circuit test would need
  pads (1.27 mm, at a 2.54 mm pitch, 3.2 mm from the edges) and is not
  planned.

### 1.6 When a board is done

- **R29 One source.** All connectivity comes from the simulated netlist.
  Nothing that changes connectivity is edited on the board.
- **R30 Checks.** All of these pass with no differences or errors:
  - the pinouts against KiCad's symbols;
  - the pads against the netlist;
  - the copper's connectivity;
  - KiCad's DRC;
  - the keep-outs;
  - the fab's netlist against the board.

  The simulation with the board's own wire delays, each load with its
  own, runs the programs with no violations, with the timing worked out
  again for the board.
- **R31 Review.** Someone looks at the board, layer by layer, in the
  viewer.

### 1.7 Where the flow applies them

| Rules | In the flow ([RFC 0023](0023-rfc-pcb-flow.md)) |
|---|---|
| R2, R3 | the stack-ups and design rules written into every board and its project file |
| R6 | the router keeps other nets' vias 0.6 mm from a through-hole pad on a plane (`router.THERMAL_ROOM`); tracks may pass, as they don't cut the plane; KiCad's zones draw the spokes |
| R7–R10, R14, R21 | a card's keep-out strips, bracket holes, connector positions and fiducials (`studies/pcb/cards.py`), honoured by the placers and the router and checked by `check.keepouts` and KiCad's DRC |
| R15 | the grid placement (`place.GridPlacer`) |
| R16, R17 | the placers' margins around THT parts; the capacitors' spots (`place.place_decaps`) |
| R18, R19 | `place.place_decaps`; the power fanout |
| R20 | net weights in placement; the timing loop in `heron pcb sweep` |
| R26 | the fab files written by every full check |
| R29–R31 | `heron pcb build`, `check` and `view` |
| R1, R4, R5, R11–R13, R22–R25, R27, R28 | not applied by the flow: they go in the order, the case design, or the flow's next steps (R27: silkscreen) |

## 2. Rationale and sources

Section 4 lists the sources; [VME] and the like below refer to it. The
IEEE 1101 and IEC 60297 texts are paywalled: their dimensions come here
from the VMEbus specification, which uses the same mechanics, and from a
Eurocard subrack maker's catalogue that reproduces them. Where a number
is our reading of a drawing, it says so.

### 2.1 The card in its case (R1, R5, R7–R13)

**Size (R7).** The Eurocard sizes are the only standard family that
covers plug-in cards of every size and still has parts on sale: card
guides, subracks, front panels, handles, backplanes [APW, WIKI].
- Heights are 100 mm plus n × 133.35 mm: 3U, 6U, 9U.
- Depths run 100, 160, 220, 280, 340 and 400 mm, and any height goes
  with any depth [APW].
- Eurocards are what VMEbus (6U × 160), Multibus II (6U × 220) and
  Futurebus (9U × 280) used, all on DIN 41612 type C connectors [VME,
  MB2, FB].
- Norsk Data built a minicomputer of the same kind, the ND-100, with its
  CPU on one 9U × 280 Eurocard [ND].

On the CPU card ([RFC 0023](0023-rfc-pcb-flow.md)), 6U × 340 is the
smallest Eurocard its chips fit on with these rules.

**How big boards were.** The minicomputers of the TTL era used cards
from 6 × 8 in up to 16 × 18 in, and the one-board CPUs were the big ones.

| Machine | Year | Board | mm | Note |
|---|---|---|---|---|
| DEC PDP-8/E (Omnibus) | 1970 | quad, extended | 216 × 264 | CPU on 4 boards, edge connectors [DEC, BELL] |
| DEC PDP-11/40 (Unibus) | 1972 | hex | 216 × 396 | CPU on 4 hex and 1 quad; a hex wire-wrap board held 84 DIP-16 [BELL, W95] |
| DEC VAX-11/780 | 1977 | super hex | 305 × 396 | about 20 boards [BELL] |
| Data General Nova, Nova 1200, Nova 4, Eclipse | 1969–80 | 15 × 15 in | 381 × 381 | Nova 1200 and Nova 4: CPU on one board; two 100-pin edge connectors per board [DGE, DGH, DG4] |
| HP 21MX (HP 1000) | 1974 | 8 layers | about 330 × 430 | the whole CPU, about 240 ICs, on one board [HPJ] |
| Interdata 7/32, 8/32 | 1974–75 | 15 × 15 in | 381 × 381 | mounted flat, ¼ in aluminium stiffeners, pin headers not edge fingers [I732, I832] |
| Computer Automation LSI-2 | about 1974 | 15 × 16.5 in | 381 × 419 | CPU on one board and two half boards [LSI2] |
| Prime 100/200/300 | 1972–75 | 16 × 18 in | 406 × 457 | CPU on one board [PRIME] |
| Norsk Data ND-100 | 1979 | Eurocard 9U × 280 | 367 × 280 | CPU on one board [ND] |
| Apple II main board (for scale) | 1977 | | about 305 × 248 | [CHM] |
| Cray-1 module board (for scale) | 1976 | 5 layers | 152 × 203 | up to 144 ICs [CRAY] |

Two things follow from the table:
- One board per CPU was common (Nova 1200 and 4, HP 21MX, Prime,
  ND-100), on boards from 0.10 to 0.19 m².
- Boards that large were stiffened and supported (Interdata's
  aluminium) or carried in deep guides; so R13 is not new.

For comparison, a DIP card of RFC 0023's CPU, at about 490 × 345 mm,
holds 0.16 ICs per cm², the same density as the HP 21MX board (0.17).

**Guided edges (R8).**
- VME says: "Solder fillets, tracking, and components … MUST NOT be
  closer than 2.5 mm from the top and bottom edges" [VME, rule 7.13];
  the subrack catalogue agrees [APW].
- The guide's groove lips are at most about 2.0 mm high (our reading of
  VME fig. 7-18), so 2.5 mm leaves a margin.
- Deep-channel commercial guides go 5.08 mm deep [ESS]. Taking the
  component strip to 5 mm allows for those, and makes the guided edges
  the assembly line's conveyor edges as well (R22), which want 3 to
  5 mm [JT, PM, LCSC].
- IEEE 1101.10 puts optional ESD strips on these edges: about 1.5 mm
  wide, 1.0 to 2.5 mm from the edge (our reading of the drawing), which
  a clip touches as the card goes in [APW, ED].

**Thickness and edges (R1, R5).**
- VME wants 1.6 +0.2 mm in the guide area and warns that thinner boards
  may not guide into the connector [VME, rule 7.32, obs. 7.1].
- The fabs' standard tolerance is ±10%: JLCPCB and Eurocircuits quote
  1.44 to 1.76 mm, and PCBWay ±0.18 mm on advanced boards [JP, ET, PC].
  A stock board can therefore be thinner than VME allows.
- Routed outlines hold ±0.2 mm, V-scores ±0.3 to ±0.5 mm [JP, ET, PC].
- A rail broken off a guided edge leaves nubs or a rough V-cut, which
  would catch in the guide (R5).

**Front edge (R9, R12).**
- VME places the bracket holes at ø2.7 ±0.1 mm, 3.57 mm from the front
  edge and 5.5 mm from the guided edges [VME, fig. 7-2].
- It reserves a bracket area 7.0 mm deep at each front corner, and
  recommends a centre bracket on double-height boards [VME, fig. 7-9,
  rec. 7.5, 7.6]. R9's 8 mm strip covers the 7 mm.
- Front panel screws are M2.5 [VME, rule 7.16].
- Pulling a board with two 96-pin connectors "requires up to 180 N"
  [VME, obs. 7.15]. IEEE 1101.10's injector/extractor handles are made
  for this [ED].

**Back edge (R10).**
- VME puts the connector's mounting holes 2.76 mm from the rear edge and
  its outer pin row 5.3 mm from it [VME, fig. 7-2; APW].
- On 6U, P2 sits 50.0 mm from the bottom edge and P1 133.35 mm above
  it, holes 88.9 mm apart [VME, fig. 7-4, rule 7.11].
- Keeping these positions lets a card use a standard subrack and
  backplane, and their 1.6 mm guide geometry.
- A connector overhanging the edge rules out an assembly rail on that
  edge [EO].

**Heights (R11).**
- VME's budget, per slot: component height plus warp at most
  13.71 mm + N × 20.32 mm on the component side, and leads plus warp at
  most 2.47 mm on the solder side. Leads are trimmed to 1.52 mm, with
  2.54 mm between neighbouring boards [VME, rule 7.14, sugg. 7.3,
  obs. 7.11].
- For other pitches, R11 carries the same margins over (our
  extrapolation).
- An 0603 capacitor is 0.8 mm thick, and an 0805 up to 1.25 mm; either
  leaves room for the warp R4 allows.

**Stiffening (R4, R13).**
- No standard or fab gives a size above which a card needs stiffening;
  R13's threshold is a judgement.
- The IPC-6012 limit of 0.75% lets a 340 mm card bow 2.6 mm and twist
  6 mm diagonally. That alone would use up VME's 2.47 mm solder-side
  budget, so R4 asks for 0.5%, which the fabs offer [EW, ET, PC].
- VME allows thicker boards milled to 1.6 mm along the guides [VME,
  perm. 7.3]. ATCA cards, about 322 × 280 mm, take 1.6 to 2.4 mm [ATCA].
- Interdata's 15 inch boards carried aluminium stiffeners [I732].

### 2.2 Holes (R14)

- Clearance holes, close/medium/free fit: M2.5 is 2.7/2.9/3.1 mm, M3
  3.2/3.4/3.6 mm [OPT, JN].
- DIN 125 washers are 6 mm across for M2.5 and 7 mm for M3 [W25, W3].
  R14's keep-outs add half a millimetre all round for the screw head and
  a slightly off-centre washer.
- Holes are non-plated by default. Plated ones are for grounding the
  card through the screw [JN].

### 2.3 Placement (R15–R20)

**Arrangement (R15).** The grid is Emily's choice, made in RFC 0023: the
board reads like the classic TTL boards, and a person can find a chip
by row and column. Under these rules it cost RFC 0023's CPU card no area:
placed anywhere or on the grid, the card gets down to 6U × 320 mm.
Before the edge strips and the spacing, it cost that card 10 to 13%. For
DIP parts it costs nothing, since all the 0.3 inch DIPs are the same
width.

**Spacing (R16).**
- Eurocircuits keeps courtyards 0.25 mm apart (0.5 mm for connectors)
  [EC]. JLCPCB requires IPC-7351 footprints at medium or low density
  [JT].
- The wider gaps come from Sierra Circuits' assembly guide [SCD]:

  | Between | Gap |
  |---|---|
  | SOIC and SOIC | 0.76–1.27 mm |
  | PLCC and PLCC | 2.54–3.05 mm |
  | SOIC and a THT pin | 2.54–3.81 mm |
  | THT and THT | 2.54–3.81 mm |

- R16 takes the low end of each range, which every house surveyed
  accepts, and keeps room for rework and inspection.

**Bottom side (R17).** THT pins on a board with SMD parts are soldered
by selective soldering or by hand, rarely by wave.
- A selective mini-wave nozzle needs 2 mm clear on three sides of a pin
  and 5 mm on the side where the board leaves the wave. A dip nozzle
  needs at least 3 mm all round [SEHO].
- R17's 5 mm all round allows both.
- The houses differ:
  - Eurocircuits solders THT mostly selectively, some by hand [EM].
  - JLCPCB's pages variously say wave and hand soldering, with fixtures
    that mask the SMD parts [JA, JF, JX].
  - MacroFab uses selective and wave [MF].
- No source limits bottom-side 0603/0805 capacitors under SMD ICs.

On RFC 0023's CPU card this rule moved the 74LS181s' capacitors on top,
beside them, and spaced the DIP slots wider (from 10.75 to 11.8 mm).

**Decoupling and supplies (R18, R19).**
- One 100 nF capacitor per IC, fed from planes, is the usual practice
  for TTL.
- Under the IC it costs no board area and sits close to both supply
  pins.
- A supply via at the pad's inner end, under the body, can't meet a
  neighbour's. RFC 0023's first boards put both at the outer ends, and
  facing vias of neighbouring chips collided.

**Timing (R20).** RFC 0023 found that a routed board changes timing
enough to matter:
- one clock output driving dozens of loads was 16 ns late;
- the 20 ns clock-generator domain broke over a few centimetres of wire.

Both were found only by simulating with the board's own wires, which is
why R30 requires it.

### 2.4 Assembly (R21–R28)

**Fiducials (R21).**

| House | Fiducial rules |
|---|---|
| JLCPCB | 1 mm dots with an opening twice that; 3 or 4 along the edges, at least 3.35 mm from the edge [JR] |
| PCBWay | 1.0 mm preferred, a clear radius of 2R or better 3R, at least 5 mm from the edge, at least three in an asymmetric L, on every populated side [PF] |
| Eurocircuits | 1.5 mm ideal (0.6 mm minimum), three near the corners [EF] |
| Aisler | 1.0 mm in a 2.0 mm opening, and ignores the customer's own [AIS] |

R21 meets all of them. It puts the centres 7 mm from the guided edges
so the 3 mm circle stays out of the 5 mm strip (R8).

**Conveyor edges and rails (R22).**
- JLCPCB keeps component bodies 2.5 mm from the edge, wants rails of at
  least 5 mm, and treats rails as necessary on its Standard service
  [JT, JR, JA].
- PCBWay needs rails when parts are closer than 3 mm to the edge [PM].
- Eurocircuits always adds a 5 mm border [EA].
- Machines may clamp 3 mm of the edge [LCSC].

**Size limits (R23).**

| House | Largest assembled board (mm) |
|---|---|
| JLCPCB Standard | 460 × 500 [JA] |
| JLCPCB Economic | 470 × 500, one side only [JA] |
| PCBWay | 250 × 500, or 330 × 530 as a panel (its pages disagree) [PA, PP] |
| Eurocircuits | 340 × 440 including its border, 400 × 510 by arrangement [EA] |
| MacroFab | 378 × 378 [MF] |

A 6U × 340 card, with a 5 mm border, fits all of them. Six-layer bare
boards go larger: JLCPCB 656 × 586, Eurocircuits 500 × 425 [JP, ES].

**Files and conventions (R26, R27).**
- JLCPCB wants Gerbers, a BOM and a placement file [JF].
- Eurocircuits takes KiCad files directly, or Gerber X2 or ODB++ [EI].
  It defines zero rotation by IEC 61188-7, with pin 1 at the lower left
  [E1], where IPC-7351 puts pin 1 at the upper left. The house's preview
  is where a wrong rotation shows [JT].

**Hand soldering (R25).** Many of KiCad's THT footprints are drawn
with little copper around the hole:

| Footprint | Pad | Hole | Ring |
|---|---|---|---|
| DIP (`DIP-16_W7.62mm`), also the disc capacitors and DIP oscillators | ø1.6 mm | ø0.8 mm | 0.4 mm |
| DIN 41612 type C, right angle | ø1.55 mm | ø1.0 mm | 0.28 mm |
| DIP, long pads (`DIP-16_W7.62mm_LongPads`) | 2.4 × 1.6 mm oval | ø0.8 mm | 0.4 mm across, 0.8 mm along |

That is enough for wave and selective soldering, but awkward by hand.
A small ring holds little heat and leaves little room for a fillet, and
it lifts more easily when a part is reworked. Emily has preferences
here that are still to be written down as R25's number.

**Test (R28).**
- Every fab tests bare boards electrically against a netlist.
- In-circuit test needs pads of 1.27 mm at a 2.54 mm pitch, 3.2 mm from
  the edge [JJS].
- Flying probe needs pads of at least 0.15 mm (0.5 mm recommended)
  [SCFP].
- AOI and X-ray inspection need nothing from the board [JA, PA, EA].

## 3. Open questions

For Emily:

1. **Eurocard 6U** (233.35 mm) as the height of every card, and so
   standard subracks, guides, front panels and handles?
2. **Slot pitch:** 4HP (20.32 mm), with components up to 13.71 mm high
   on the top side? Socketed PLCCs and DIPs fit; electrolytic capacitors
   may not.
3. **Assembly rails:** a house that accepts the clear guided edges as
   conveyor edges, or rails that are broken off and sanded (R5, R22)?
4. **THT soldering:** the DIN connectors and any DIP parts soldered by
   the house (selectively, per joint) or by hand?
5. **ESD strips** on the guided edges (IEEE 1101.10), with clips in the
   case?
6. **Stiffening** (R13): only for cards beyond the Eurocard sizes, or a
   stiffener on every 6U × 340 card too?
7. **THT pads for hand soldering** (R25): how much copper around the
   hole, at least? This applies to which parts: all THT parts, or only
   those likely to be soldered or reworked by hand? And with it, which
   footprints to use or draw (section 2.4).

## 4. Sources

- [VME] VMEbus specification Rev C.1: https://transputer.net/mtw/imsb016/doc/vme/vmebus.pdf
- [APW] APW/Vero KM6 subrack catalogue (IEEE 1101.10 dimensions): https://docs.rs-online.com/53da/0900766b8002ed3c.pdf
- [ED] A guide to IEEE 1101.10: https://www.electronicdesign.com/technologies/embedded/article/21774173/a-guide-to-dot-ten-ieee-110110
- [WIKI] Eurocard: https://en.wikipedia.org/wiki/Eurocard_(printed_circuit_board)
- [ESS] Essentra deep-channel card guides: https://americas.bossard.com/content/ProductSpecSheets/ESNTRAE00001_189.pdf
- [ATCA] ATCA front panels: https://web.pa.msu.edu/hep/atlas/l1calo/hub/hardware/components/mechanical/elma_aluminum_atca_front_panels.pdf
- [OPT] Clearance holes: https://optimas.com/technical-resources/tapping-sizes/
- [W25] M2.5 washers: https://www.aspenfasteners.com/m2-5-din-125-type-a-iso-7089-7090-metric-standard-flat-washers-steel-zinc-plated/
- [W3] M3 washers: https://www.fabory.com/en/plain-washer-din-125-1a-brass-m3/p/50060030001
- [JA] JLCPCB assembly capabilities: https://jlcpcb.com/capabilities/pcb-assembly-capabilities
- [JP] JLCPCB PCB capabilities: https://jlcpcb.com/capabilities/pcb-capabilities
- [JT] JLCPCB assembly terms: https://jlcpcb.com/help/article/61-Terms-and-Conditions-of-JLCPCB-Assembly-Service
- [JR] JLCPCB rails and fiducials: https://jlcpcb.com/help/article/How-to-add-edge-rails-fiducials-for-PCB-assembly-order
- [JF] JLCPCB assembly FAQ: https://jlcpcb.com/help/article/pcb-assembly-faqs
- [JX] JLCPCB assembly fixtures: https://jlcpcb.com/help/article/pcb-assembly-fixtures
- [JN] JLCPCB NPTH guide: https://jlcpcb.com/blog/npth-design-guide
- [LCSC] Fiducial placement: https://www.lcsc.com/blog/how-to-properly-place-fiducial-marks-on-pcbs-a-step-by-step-guide/
- [PA] PCBWay assembly capabilities: https://www.pcbway.com/assembly-capabilities.html
- [PC] PCBWay PCB capabilities: https://www.pcbway.com/capabilities.html
- [PF] PCBWay rails, fiducials and tooling holes: https://www.pcbway.com/helpcenter/design_instruction/PCB_Panelization__Breakaway_Rails__Fiducial_Marks__Tooling_Holes.html
- [PM] PCBWay machine assembly requirements: https://www.pcbway.com/helpcenter/pcb_assembly_ordering/What_are_the_requests_on_pcb_for_assembly_by_machine_.html
- [PP] PCBWay panels for assembly: https://www.pcbway.com/pcb_prototype/Panel_Requirements_for_Assembly.html
- [EA] Eurocircuits assembly capabilities: https://www.eurocircuits.com/services/pcb-assembly-capabilities/
- [ES] Eurocircuits standard pool: https://www.eurocircuits.com/services/standard-pool/
- [EF] Eurocircuits fiducials: https://www.eurocircuits.com/tips-tricks/finding-fiducials/
- [EC] Eurocircuits component clearances: https://www.eurocircuits.com/pcb-assembly-guidelines/component-clearances/
- [EM] Eurocircuits assembly technology: https://www.eurocircuits.com/technical-guidelines/assembly-manufacturing-technology/
- [E1] Eurocircuits pin 1 and zero rotation: https://www.eurocircuits.com/technical-guidelines/pcb-assembly-guidelines/defining-pin-1-zero-point-rotation/
- [EI] Eurocircuits input formats: https://www.eurocircuits.com/technical-guidelines/pcb-design-guidelines/input-data-formats/
- [EO] Eurocircuits overhanging components: https://www.eurocircuits.com/pcb-assembly-guidelines/overhanging-components/
- [EW] Eurocircuits warp and twist: https://www.eurocircuits.com/warp-twist/
- [ET] Eurocircuits tolerances: https://www.eurocircuits.com/?p=3648
- [AIS] Aisler production panel: https://community.aisler.net/t/aisler-production-panel-specification/2779
- [MF] MacroFab: https://www.macrofab.com/pcba/
- [SEHO] Selective soldering design rules (SEHO): https://www.electronics.org/system/files/technical_resource/E8%26S23_02.pdf
- [JJS] Design guidelines for in-circuit testability: https://www.smtnet.com/library/files/upload/Design_guidelines_for_in-circuit_testability.pdf
- [SCFP] Flying probe test points: https://protoexpress.com/?p=569
- [SCD] Sierra Circuits DFA rules: https://www.protoexpress.com/kb/dfa-rules/
- [DEC] DEC Digital Logic Handbook 1975–76: https://ftp.mirrorservice.org/sites/www.bitsavers.org/pdf/dec/handbooks/Digital_Logic_Handbook_1975-76.pdf
- [W95] DEC W95xx wire-wrap modules: https://new.vaxbarn.com/pub/pdf/dec/pdp11/W95xx_HD_Wirewrap_Modules_DataSheet_Mar1978.pdf
- [BELL] Bell, Computer Engineering: http://gordonbell.azurewebsites.net/computer_engineering/00000140.htm
- [DGE] Electronics, 9 December 1968 (the Nova): https://ftp.mirrorservice.org/sites/www.bitsavers.org/magazines/Electronics/Electronics_V41_N25_19681209_DG_Nova.pdf
- [DGH] How to Use the Nova Computers (1971): https://ftp.mirrorservice.org/sites/www.bitsavers.org/pdf/dg/DG_NM-5_How_To_Use_The_Nova_Computers_Apr1971.pdf
- [DG4] Nova 4 Field Engineer's Reference: https://new.vaxbarn.com/pub/pdf/dg/nova/015-000095-02__Nova_4-S_and_4-X_Field_Engineers_Reference.pdf
- [HPJ] HP Journal, October 1974: https://www.hparchive.com/Journals/HPJ-1974-10.pdf
- [I732] Interdata 7/32 brochure: https://ftp.mirrorservice.org/sites/www.bitsavers.org/pdf/interdata/32bit/7-32/7-32_Brochure_1973.pdf
- [I832] Interdata 8/32 maintenance manual: https://ftp.mirrorservice.org/sites/www.bitsavers.org/pdf/interdata/32bit/8-32/29-394R02_M83-Series_Model_8-32_Maintenance_Manual_Nov75.pdf
- [LSI2] Computer Automation LSI-2 handbook: https://ftp.mirrorservice.org/sites/www.bitsavers.org/pdf/computerAutomation/lsi/91-20400-0080_LSI-2_Series_Minicomputer_Handbook_Apr1976.pdf
- [PRIME] Prime System Reference Guide (1975): https://sysovl.info/pages/blobs/prime/archhw/Sys%20Ref%20Guide%20MAN1671%201975.pdf
- [ND] ND-100 Functional Description: https://ftp.mirrorservice.org/sites/www.bitsavers.org/pdf/norskData/ND-100-FD-ND-06.015.02_ND-100_Functional_Description_1985.pdf
- [MB2] Multibus: https://en.wikipedia.org/wiki/Multibus
- [FB] Futurebus: https://handwiki.org/wiki/Futurebus
- [CHM] Apple II board, Computer History Museum: https://www.computerhistory.org/collections/catalog/102646017/
- [CRAY] Russell, The CRAY-1 Computer System (CACM 1978): https://tcm.computerhistory.org/ComputerTimeline/Chap44_cray1_CS2.pdf
