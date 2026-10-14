---
number: 21
type: report
title: Signal integrity of the revised bus
status: current
date: 2026-10-14
context:
  studies: [bus_si]
  commit: 8828750
---

# Report 0021: Signal integrity of the revised bus

The signal-integrity work [RFC 0014](0014-rfc-system-bus.md) asks for in
its 2026-10-14 revision (section 17, "Signal-integrity work to do"): ground
bounce, SEL as a strobe, card loading, hold time, the clock tree, the
backplane's own lines, WAIT, report 0013's failed jobs, the connector, the
geometry and a faster clock. Every item has an answer here, from the
[bus_si study](../studies/bus_si/README.md) on a simulator of its own.

All the numbers are in the [tables](0021-report-bus-si-revised/results.md),
which `heron bus_si report` regenerates (about 15 minutes on four cores).
Corners are IBIS's: `min` is slow (4.5 V, hot), `max` fast (5.5 V, cold).
What follows suggests changes to the RFC; making them is for Emily.

## Summary

| Item | Finding | Suggests |
|---|---|---|
| 1. Ground bounce | 16-bit TSSOP parts (ABT16245) bounce a fifth as much as octal SOIC or DIP parts: 0.4 V on the die against 1.8–2.8 V. The bus filters most of it: the quiet line stays under 0.8 V at the receivers with ABT parts in SOIC or TSSOP, and every glitch is gone 12 ns after the edge | ABT16245 (TSSOP) for wide drivers; octal ABT245 in SOIC acceptable; not DIP, not FCT-T in DIP, not the ABT2245 |
| 2. SEL as a strobe | No series resistor makes the 74HCT132 retrigger; 56–68 Ω keeps its inputs within their ratings. Without the guard ground pins, a simple card's own data drivers can pull WRITE below VT− (a read becomes a write); with them both strobes keep at least 1.1 V of margin | 56–68 Ω on SEL and GNT; the guard-pin rule is necessary, and with it the Schmitt inputs are enough |
| 3. Card loading | 12 pF per card on all 16 slots adds 10.3 / 12.8 ns (rise / fall, ABT); 15 pF adds 14.3; 20 pF jumps to 19.1. A stub costs only its capacitance | Keep 12 pF, counting the card's trace; the settling budget becomes 13 ns, not 11; traces up to 50 mm |
| 4. Hold time | The bus never makes a change arrive earlier than the driver's datasheet delay; the earliest is 0.46 ns after it | T<sub>co</sub> min ≥ 3 ns and T<sub>h</sub> ≤ 1 ns hold with ABT574/273 and ABT16245; they leave 2.9–3.8 ns for skew |
| 5. The clock tree | The traces add 0.25 ns of skew unmatched. Skew is the parts': 2.0–2.6 ns with clock drivers that specify part-to-part skew at both ends; about 8 ns with a CDC329A and a generic '244 per card | T<sub>skew</sub> ≤ 2.5 ns, with specified clock parts on the backplane and every card (FCT807CT or CDC341 class); 68 Ω |
| 6. The backplane's lines | Its logic in the middle shortens SEL, GNT and CLASS to under 200 mm and speeds rising edges; 22 Ω at its bused outputs, not 33 (the fast-corner fall takes 22 ns); its input buffer settles no later than any card | Logic in the middle; 22 Ω on DPH, RDY, BERR, W32 |
| 7. WAIT | Released at 3.4 V, it holds at least 2.7 V against two switching neighbours, and keeps 0.13 V of any shift | Fine as specified; so are the open CLASS and REQ lines |
| 8. Failed jobs | All 68 ran. None changes report 0013's worst cases | – |
| 9. The connector | Settling barely depends on it (6–20 nH: +0.5 ns). A pin-field model fitted to TE's measured crosstalk gives 12 nH for a typical P1 contact, as estimated, and couplings of up to 0.5 between unguarded neighbours | – |
| 10. Geometry | Delay scales with the bus's length: 20 slots add 3 ns, a 15.24 mm pitch saves 1 ns | Tables for when the card size is chosen |
| 11. A 50 ns clock | A card-to-card transfer uses about 32 ns of the 50; simple cards lose 10 ns to HCT's slow falling edge | 50 ns works for the bused paths; simple cards get N × T − 60 ns |

## 1. The tools

### A simulator of our own

Report 0013's sweeps ran on ngspice, and 68 of its 1,197 jobs failed: 44
ran past five minutes, and 24 stopped with "timestep too small". Its
ground-bounce model gave die voltages in the tens of kilovolts. The cause
is ngspice's adaptive time step: the IBIS buffers are piecewise-linear
tables whose kinks collapse it, at places that move with every change to a
model.

So the study now runs on `infra/sisim`, a transient simulator in Rust
(RFC 0015's engines), written for these circuits:

- **A fixed time step,** 5 ps. A run takes a known number of steps, so it
  can't stall. Newton's method gets a bounded number of iterations per
  step, and a step that doesn't converge is counted, not retried. Over
  this report's 4,911 jobs, 125 million steps in all, none failed to.
- **Lossless lines by the method of characteristics,** coupled lines by
  their modes. They split the circuit into small pieces, each solved on
  its own; the linear ones are factorised once.
- **The same netlists.** `infra/si/engine.py` parses the SPICE text the
  models already wrote, so either engine runs any model, and ngspice stays
  as a cross-check.

Against report 0013's results it agrees within 0.002 ns (rise) and
0.007 ns (fall) on 95% of the 10,640 settle times, and within 5 mV on
99.5% of the peaks. The few large differences (0.6% of the settle times)
are edges that ring right at a threshold, where a few millivolts move the
last crossing; in the four checked by shortening the steps, ngspice's
20 ps maximum step was the inaccurate one. Halving the native engine's
step moves 95% of settle times by under 0.007 ns.

It runs report 0013's full sweep in 18 CPU-minutes, against 672 for
ngspice, and a typical bus-line run in 0.7 s against 3–11 s.

### Sweeps that can't get stuck

Report 0013 lost hours to runs that hung. Now:

- **The engine can't hang:** a fixed number of steps, and a wall-clock
  limit as a backstop.
- **Each job has a deadline.** Workers run in process groups of their own;
  a job past its deadline is killed with its children (ngspice included),
  recorded as a timeout, and its worker replaced.
- **A heartbeat** every 30 s gives progress and the oldest running job's
  age, and **a budget** stops starting new jobs after a set time.
- **Everything resumes** from a per-job log.

No job has timed out on the native engine.

### Models

Three changes to what's modelled, beyond report 0013's single bus line:

- **The connector as a pin field.** Each contact is a conductor coupled to
  every other by its partial inductance, and the ground and power pins are
  real return paths. A signal's loop inductance, its coupling to its
  neighbours and a card's ground bounce all follow from where the ground
  pins are. With 25 mm contacts the model reproduces the one measurement
  found, TE's crosstalk figures for a standard DIN 41612 connector: 23.0%
  near end and 21.3% far end, against 23.3% and 20.0% measured
  ([tables](0021-report-bus-si-revised/results.md#the-connector-against-tes-measurement)).
- **Supply currents calibrated against datasheets.** Classic IBIS files
  don't say what a driver draws from its own rails. Taken as they are,
  they put the datasheet's ground-bounce test (VOLP) at two to three times
  the published value: 2.4 V for an ABT245 in SOIC, against 0.7 V typical
  and 1.0 V maximum (Fairchild). A calibrated model fixes two things:
  - the transistor turning off does so before the other turns on, where
    the files' fit has both half on;
  - drive strength follows the die's own rail-to-rail voltage, which is
    what IBIS 5's [ISSO] tables add.

  It gives 0.88 V for that part, and 1.67 V for an FCT245T in DIP against
  about 1.6 V that QSI measured on an FCT244 in DIP. Ground bounce runs on
  both models.
- **Cards and the backplane as they now are:** cards per slot (or empty),
  devices on the backplane itself, radial lines, and a whole driving card
  with its packages, rails, decoupling and planes.

## 2. Ground bounce (item 1)

A card in the middle slot drives 16 (P1) or 32 (P1 and P2) data lines
through 22 Ω onto 16 cards of 12 pF, all but one switching at once. Fast
corner, calibrated model; the raw model in brackets where it differs
much.

| Drivers | Die ground | Quiet line at the receivers | Card ground | Push-out |
|---|---:|---:|---:|---:|
| ABT16245, TSSOP | 0.37 V (1.23) | 0.44 V (0.52) | 0.61 V | +1.3 ns |
| ABT245, SOIC | 1.83 V (2.22) | 0.66 V (0.78) | 0.51 V | +2.1 ns |
| ABT245, DIP | 2.20 V (2.52) | 0.66 V (0.92) | 0.52 V | +2.7 ns |
| FCT245T, SOIC | 2.59 V | 0.75 V (1.02) | 0.68 V | +1.0 ns |
| FCT245T, DIP | 2.81 V | 0.87 V (1.27) | 0.79 V | +4.0 ns |
| ABT2245, SOIC | 1.42 V (2.11) | 0.87 V (1.28) | 0.77 V | +3.9 ns |

(Worst of 16 and 32 lines, falling and rising. Quiet line: its highest
level at the receivers while the others fall, from a low level of 0.2 V.
Card ground: against the backplane's. Push-out: the switching line's
settle time against one line switching alone.)

- **The package decides.** The ABT16245 returns 16 outputs through eight
  ground pins of about 2.9 nH each; an octal part in SOIC returns 8
  through one of 6.4 nH, in DIP 10.3 nH. Its die bounces a fifth as much.
- **The bus filters it.** 22 Ω against the loaded bus (about 22 Ω)
  divides the die's bounce by three or more. With ABT parts in SOIC or
  TSSOP the quiet line never reaches 0.8 V at a receiver. With FCT-T or
  the ABT2245 it can, briefly. Every glitch is over within 12 ns of the
  edge, inside the settling budget, so clocked receivers don't see it.
- **32 lines against 16** changes little: each package bounces on its own,
  and P2 has its own return pins. The card's ground moves 10–20% more.
- **The card's ground moves 0.4–0.8 V** against the backplane's while the
  return current crosses the connector, for the few nanoseconds of the
  edge (0.9 V with the raw model and 32 lines). Inputs the card takes from
  the backplane see that shift: BCLK is high when outputs switch
  (T<sub>co</sub> ≥ 3 ns into the clock), and drops by at most 0.9 V from
  a level of 3.4 V or more.
- **Decoupling** hardly changes these numbers. The package's own pins are
  the bottleneck, and one 100 nF capacitor per package is enough.
- **The ABT2245's built-in 25 Ω** behaves like an external resistor for
  ringing but pushes edges out by 4 ns with 16 switching.

The RFC's "prefer SOIC or flow-through parts (74ABT16245) for wide
drivers" stands; the data suggests going further: ABT16245 in TSSOP for
wide drivers on fast cards, octal ABT245 in SOIC where a narrow driver is
wanted, and neither DIP nor FCT-T in DIP for words.

## 3. SEL as a strobe (item 2)

**The line itself.** An ABT273 on the backplane drives SEL through its
series resistor and 50–350 mm of trace to one to three inputs on the card,
at every corner.

| Series | Peaks at the HCT inputs | Ring-back margin to the 74HCT132's thresholds | Slowest edge |
|---:|---:|---:|---:|
| none | −1.09 / 6.36 V | 0.73 V | 1.7 V/ns |
| 33 Ω | −0.87 / 5.41 V | 1.02 V | 1.6 V/ns |
| 47 Ω | −0.81 / 4.80 V | 0.97 V | 1.4 V/ns |
| 56 Ω | −0.67 / 4.51 V | 0.68 V | 1.2 V/ns |
| 68 Ω | −0.34 / 4.42 V | 0.54 V | 1.0 V/ns |

- No value up to 68 Ω makes the gate retrigger: once an edge has
  crossed, it never comes back within 0.5 V of the far threshold (VT+ at
  least 1.2 V, VT− at most 1.2 V at 4.5 V; Nexperia). ABT inputs on fast
  cards see the same peaks and slower edges (0.6 V/ns at 68 Ω).
- 68 Ω keeps the HCT inputs within their −0.5 V rating; 56 Ω nearly. The
  resistor costs at most 0.4 ns.

**Crosstalk.** The worst case for a simple card is its own read: while SEL
is asserted and WRITE high, its two transceivers drive D0–D15, all
switching together, through the contacts next to SEL and WRITE. Measured
at its 74HCT132's inputs against its own ground:

| | SEL margin to VT+ | WRITE margin to VT− |
|---|---:|---:|
| Ground pins on all four sides (the RFC's rule) | +1.09 V or more | +1.77 V or more |
| Data lines on those pins instead | +0.21 V | **−0.94 V** |

- **Without the guard pins a read can become a write.** WRITE dips to
  0.36 V with ABT drivers in DIP, and to 1.0–1.7 V with HCT drivers
  (calibrated model), below the gate's VT− in three of the eight cases.
- **With them, both are safe** in every case, by more than a volt. The
  rule cuts SEL's summed coupling to the 16 data lines from 3.0 to 0.43,
  and its loop inductance from 14.8 to 9.5 nH.
- The series resistor on SEL makes no difference to crosstalk.

So the guard-pin rule is necessary, and with it the Schmitt inputs are
enough. The RFC's "33–68 Ω" could narrow to 56–68 Ω.

## 4. Card loading (item 3)

The delay the bus adds to the driver's datasheet delay, worst over driver
positions, receivers and corners; ABT drivers, 22 Ω on every card, every
slot filled. A card's load is everything on its side of the connector: the
trace (0.086 pF/mm), the transceiver's pin and die, any other inputs.

| Load per card | 25 mm trace | 50 mm | 75 mm |
|---:|---:|---:|---:|
| 9 pF | 9.1 / 11.4 ns | – | – |
| 12 pF | 10.3 / 12.8 ns | 10.6 / 13.1 ns | 11.0 / 13.4 ns |
| 15 pF | 11.7 / 14.3 ns | 12.0 / 14.5 ns | 12.1 / 15.1 ns |
| 20 pF | 13.9 / 19.1 ns | 14.2 / 19.1 ns | 14.4 / 19.3 ns |
| 25 pF | 16.2 / 22.2 ns | 17.1 / 22.4 ns | 18.1 / 22.6 ns |

- **12 pF is the right rule.** The RFC's 11 ns settling figure is the 9 pF
  card of report 0013; at 12 pF it's 12.8 ns, and the budgets should use
  13. Up to 15 pF costs 1.5 ns more; past that the falling edge's first
  step stops crossing 0.8 V at the far cards and the delay jumps.
- **The trace length hardly matters by itself:** at the same total load,
  75 mm costs 0.7 ns more than 25 mm. But 75 mm of trace and one
  transceiver are already 12 pF, so in practice the trace should stay
  under about 50 mm.
- **FCT-T drivers** settle a little faster (11.0 / 11.6 ns at 12 pF) but
  ring through the threshold region more (4–8 extra crossings at
  12–15 pF), within those times.
- **HCT drivers** (simple cards' read data) are slow to fall: 20.8 ns at
  12 pF, 25.6 at 15 pF.
- **A partly filled backplane** is faster (four cards: 7 ns) and rings
  more; the times above cover it.

## 5. Hold time (item 4)

The earliest moment any receiver's input leaves its old valid level,
measured from the driver's datasheet delay point (its output crossing 1.5 V
into the datasheet load), at the fast corner with the nearest receiver and
the lightest load: **+0.46 ns** for ABT, **+0.49 ns** for FCT-T. The bus
never brings a change forward.

So hold depends only on the parts. From their datasheets (TI, Cypress):

| Launch: register + transceiver, min | Capture: register hold − transceiver min | Skew allowed |
|---|---:|---:|
| ABT574A 2.2 + ABT16245 1.0 = 3.2 ns | 1.8 − 1.0 = 0.8 ns | 3.2 + 0.46 − 0.8 = 2.9 ns |
| ABT273 2.5 + ABT16245 1.0 = 3.5 ns | 1.2 − 1.0 = 0.2 ns | 3.8 ns |
| FCT574T 2.0 + FCT245T 1.5 = 3.5 ns | 1.5 − 1.5 = 0 ns | 4.0 ns |

The RFC's T<sub>co</sub> min ≥ 3 ns and T<sub>h</sub> ≤ 1 ns are met by
these parts, if both are counted from the card's own register clock, with
the card's clock buffer in T<sub>skew</sub>. Its hold equation then leaves
at least 2.9 ns for skew. Section 6 says what skew costs.

## 6. The clock tree (item 5)

A clock driver in the middle of the backplane, 30 mm below the connector
row, drives each slot through its own trace and series resistor to one
buffer on the card.

**The signal.** A CDC329A (5 V, six outputs) gives clean edges: at least
1.4 V/ns at the card's buffer, ring-back of 0.5 V at most, at every
corner (calibrated model).
The arrival spreads by 0.25 ns over the slots with unmatched traces (30 to
185 mm), and by nothing with matched ones; length matching isn't worth
it. An ABT244 used as the backplane's clock driver gives only 0.4 V/ns, too
slow for a clock.

**The driver's own ground bounce** is the uncertain part. Six outputs of
one package switching together:

| Model | Falling edge's ring-back | Die ground |
|---|---:|---:|
| Calibrated | 0.33–0.50 V | 0.5 V |
| Raw IBIS | 1.9–2.2 V | 2.6 V |
| Raw IBIS, three outputs | 1.3–1.7 V | 1.8 V |

The calibrated model is the better estimate (section 1), and says it's
fine. The raw one says a falling edge could ring back through the
threshold and clock twice. The CDC329A's datasheet gives no ground-bounce
figure to settle it, so this deserves a measurement on a prototype
backplane, and favours a clock driver that publishes one, with few outputs
per ground pin.

**The skew budget.** The traces are the smallest part:

| | Generic parts | Specified parts |
|---|---:|---:|
| Backplane driver, between its outputs and packages | CDC329A: no part-to-part figure; 1.7–5.9 ns delay | FCT807CT: 0.75 ns part to part |
| Traces, unmatched | 0.25 ns | 0.25 ns |
| Threshold at the card's buffer (±0.2 V at 1.4 V/ns) | 0.3 ns | 0.3 ns |
| Card buffer, between cards | ABT244A: 1.0–4.6 ns | FCT807CT: 0.75 ns part to part |
| **T<sub>skew</sub>** | **about 8 ns** | **2.0 ns** (CDC341 at both ends: 2.6 ns) |

The RFC's T<sub>skew</sub> ≤ 2 ns is reachable only with clock drivers
that specify part-to-part skew, on the backplane and on every card. With
them, 2.5 ns is a comfortable limit, and section 5 allows 2.9. With a
generic '244 on each card, hold fails. 68 Ω on each output keeps the
overshoot lowest (5.9 V against 6.8 V at 47 Ω).

## 7. The backplane's own lines (item 6)

**Bused outputs** (DPH, RDY, BERR, W32) from the backplane's logic to 16
cards of 12 pF, ABT, added delay rise / fall:

| Logic at | No resistor | 22 Ω | 33 Ω |
|---|---:|---:|---:|
| beyond slot 0 | 8.4 / 9.0 ns, −0.9 V | 10.8 / 13.5 ns | 11.6 / 21.6 ns |
| between slots 7 and 8 | 5.2 / 5.2 ns, −0.8 V | 8.4 / 13.3 ns | 11.4 / 19.9 ns |

- **The middle is better.** Rising edges settle 2.4 ns sooner, and the
  radial lines (SEL, GNT, CLASS, REQ, BCLK) get shorter: under 200 mm
  instead of up to 350.
- **22 Ω, as on the cards.** 33 Ω is too much: at the fast corner the
  falling edge's first step no longer crosses 0.8 V, and the edge takes
  20 ns. Without a resistor it undershoots to −0.9 V and rings.
- **Its input buffer** on a 15 mm trace settles no later than the worst
  card, wherever it sits.
- **SEL and GNT:** section 3 (56–68 Ω).
- **CLASS and REQ pull-ups:** an open class line moves by under 0.06 V
  when its neighbours switch (section 8), so 10 kΩ is enough.

## 8. WAIT and lines held by a pull-up (item 7)

WAIT after release sits at the driver's high level, 3.4 V at the slow
corner, and the 10 kΩ pull-up needs microseconds to raise it. Two
neighbours rising and falling along the whole backplane, worst of all
corners:

| Contacts | Lowest | Shift that stays |
|---|---:|---:|
| Guarded (k = 0.07) | 3.18 V | 0.12 V |
| Unguarded (k = 0.35) | 2.70 V | 0.13 V |

At least 0.7 V above VIH, so WAIT is fine as specified. An open CLASS
line, pulled up to 5 V, moves by less than 0.06 V.

## 9. Report 0013's failed jobs (item 8)

All 68 ran on the native engine, without changing models or thresholds.
None changes a worst case in report 0013 or in RFC 0014's table in section
13.8: ABT with 22 Ω is still 8.7 / 10.9 ns, 4.42 / −0.45 V, two extra
crossings; FCT-T 9.7 / 9.7 ns; HCT 7.9 / 14.1 ns. Report 0013's
ground-bounce results are superseded by section 2.

## 10. The connector (item 9)

- **No published inductance or capacitance** for DIN 41612 contacts turned
  up (ERNI, Harting, TE, Amphenol). TE publishes crosstalk measurements,
  which the pin-field model now reproduces (section 1).
- **With 25 mm contacts** the model gives 9.5–15 nH for P1's signal
  contacts (median 12.3 nH, report 0013's estimate) and couplings up to
  0.5 between unguarded neighbours; the guard pins bring SEL's to 0.07.
- **Settling barely depends on it.** 6 to 20 nH changes the added delay by
  under 0.5 ns, and 1 to 3 pF by about 1 ns. Crosstalk and ground bounce
  depend on it, and the model is anchored to TE's measurement for those.

## 11. Geometry (item 10)

ABT, cards of 12 pF, added delay rise / fall:

| Slots | 15.24 mm pitch | 20.32 mm | 25.4 mm |
|---:|---:|---:|---:|
| 8 | 4.4 / 5.8 ns | 4.8 / 6.3 ns | 5.3 / 6.9 ns |
| 12 | 6.8 / 8.7 ns | 7.6 / 9.6 ns | 8.4 / 10.6 ns |
| 16 | 9.3 / 11.8 ns | 10.3 / 12.8 ns | 11.5 / 14.2 ns |
| 20 | 11.8 / 15.6 ns | 13.2 / 16.0 ns | 14.5 / 17.8 ns |

The delay follows the backplane's length. The half-width layout's unloaded
hop between connector rows waits for that layout to be chosen.

## 12. A 50 ns clock (item 11)

A transfer between fast cards, worst case, from the datasheets and
sections 4 to 6:

| | ns |
|---|---:|
| T<sub>co</sub> max: ABT574A clock to Q 7.1, ABT16245 4.2 | 11.3 |
| The bus, 16 cards of 12 pF | 12.8 |
| T<sub>su</sub> at the card: ABT16245 4.2, ABT574A setup 1.5 | 5.7 |
| T<sub>skew</sub> | 2.5 |
| **Total** | **32.3** |

That leaves 17.7 ns at 50 ns, and the RFC's own limits (16 + 13 + 8 + 2.5)
fit too. The paths that limit the clock are logic: the class lookup and a
fast card's read (RFC 0014, 13.7), not the bus.

Simple cards lose 10 ns: HCT's falling edge takes 21 ns to settle at 12 pF,
against the 11 the RFC assumed. Read data must then be at the connector
about 32 ns before the end of the last data clock, so a simple card's
device gets about N × T − 60 ns from the strobe starting: 60 ns with
N = 2 at T = 60 ns, which may push a 16C550 behind an HCT245 to N = 3.

## 13. Limits

- **Classic IBIS** sets the ground-bounce and clock-driver numbers'
  uncertainty: they're given both raw and calibrated, and the calibration
  rests on three published figures.
- **The planes** are single nodes: their spreading inductance and the
  decoupling capacitors' placement aren't modelled.
- **The pin assignment** is a reference one that follows RFC 0014's rules;
  the real assignment should keep the guard pins and spread the returns
  the same way (P1: 24 power and ground pins).
- **Not modelled:** trace losses, temperature beyond the IBIS corners, and
  the delays inside the parts (from datasheets, in sections 5, 6 and 12).
