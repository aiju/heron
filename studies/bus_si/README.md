---
status: active
depends-on: []
reports: [13, 14, 22]
---

# Backplane signal-integrity simulation

Simulates the system bus ([RFC 0014](../../reports/0014-rfc-system-bus.md))
on its backplane: bused and radial lines, card loading, ground bounce,
crosstalk and the clock tree, with TI's IBIS models of the parts. The
results are [report 0013](../../reports/0013-report-bus-si.md) (the first
round, in ngspice) and [report 0022](../../reports/0022-report-bus-si-revised.md)
(the revised bus's questions, on the native engine).

## Running it

Needs Python 3.10+ with numpy, and Rust for the engine (built on first use,
like the other engines). The IBIS files are downloaded from ti.com into
`build/ibis/` the first time they're needed. ngspice is only needed to
cross-check the engine (`--engine ngspice`).

```sh
heron bus_si check                         # the engines and models, one timed run
heron bus_si report                        # every report 0022 sweep, then its tables (~15 min on 4 cores)
heron bus_si traces                        # report 0022's figures: the waveforms behind its numbers (seconds)
heron bus_si sweep --preset loading        # one preset (heron bus_si sweep --help lists them)
heron bus_si sweep --preset full --engine ngspice   # report 0013's sweep on ngspice
heron bus_si compare A.json B.json         # two runs of a preset, job by job
heron test bus_si                          # the study's unit tests
```

- **Long runs** can go in the background, in a cloud session or anywhere
  else. A sweep logs every finished job to `build/si/<preset>-<engine>.jsonl`
  and carries on from there when run again; `--budget` stops starting new
  jobs after so many minutes.
- **Nothing can hang.** The native engine takes a fixed number of steps
  per run. Each job also runs in a worker of its own, and a job past its
  deadline (`--timeout`, 120 s native, 300 s ngspice) is killed with its
  children, recorded as a timeout, and the worker replaced. A heartbeat
  line every 30 s gives the oldest running job's age.
- **Results** go to `build/si/results/<preset>.json`; `heron bus_si
  report` turns them into `reports/0022-report-bus-si-revised/results.md`,
  and `heron bus_si traces` draws the figures next to it.
  Report 0013's ngspice results stay in its folder.

## The engine

`infra/sisim` is a fixed-step transient simulator in Rust: nodal analysis,
BDF2 at 5 ps, lossless lines by the method of characteristics (coupled
lines by their modes), the IBIS buffers' table sources, diodes, a DC
point by Newton's method with a line search. `infra/si/engine.py` parses
the same SPICE netlists the models write for ngspice, so either engine
runs any model. Against ngspice on report 0013's 1,197 jobs it agrees
within 0.007 ns on 95% of settle times; it's 5-15 times faster, and ran
the 68 jobs ngspice couldn't finish.

## The models

| File | What it is |
|---|---|
| `infra/si/ibis.py` | IBIS files: parsing, the switching coefficients (with or without crowbar current), ramp-only files, a supply factor so drive follows the die's rails |
| `infra/si/fields.py` | 2D field solver for the backplane trace's L and C |
| `infra/si/pins.py` | Partial inductances and capacitances of a connector's pin field |
| `infra/si/engine.py`, `spice.py` | The two simulators behind one `run` |
| `infra/si/runner.py` | Parallel jobs with deadlines, a heartbeat and a budget, resumable |
| `bus.py`, `noise.py` | Report 0013's models: one bused line, crosstalk, its ground bounce |
| `bused.py` | Bused lines with cards per slot (or empty) and devices on the backplane |
| `radial.py` | SEL, GNT and BCLK from a register or clock driver, outputs sharing its package's rails |
| `connector.py` | The DIN 41612 pin field: reference P1 and P2 maps, coupled contacts, the check against TE's measured crosstalk |
| `gb.py` | Ground bounce of a whole card: packages, rails, decoupling, planes, the connector, 16 or 32 lines; the datasheet VOLP test |
| `xt.py` | Crosstalk onto SEL and WRITE at a simple card, against the 74HCT132's thresholds |
| `floating.py` | WAIT and CLASS held only by their pull-ups, between switching neighbours |
| `sweep.py`, `revised.py` | The presets: report 0013's, then report 0022's |
| `summary.py`, `compare.py` | Report 0022's tables; comparing two runs |
| `traces.py`, `svgplot.py` | Report 0022's figures: some of its jobs again, with their waveforms, as SVG |

### What's assumed

- **Backplane:** 4 layers, 0.2 mm traces on 0.21 mm of prepreg, field-solved
  at 67.5 Ω and 5.8 ps/mm; 16 slots at 20.32 mm.
- **Connector:** each contact a 25 mm conductor, 0.4 mm in radius, coupled
  to every other by its partial inductance; 2 pF per contact. 25 mm makes
  the model reproduce TE's measured crosstalk on a standard DIN connector
  (23% near end, 20% far end with 16 lines driven).
- **Cards:** a 25 mm trace to the transceiver, 22 Ω at its pin, SOIC
  unless stated; 12 pF in all on the card's side of the connector.
- **IBIS:** the files' corners as they are: `min` slow (4.5 V, hot),
  `max` fast (5.5 V, cold). Classic IBIS doesn't say what a driver draws
  from its rails, so supply currents run both as the files give them
  ("raw", 2-3 times the datasheets' ground bounce) and calibrated (break
  before make, drive following the die's rails, within about 25% of
  them).
- **Not modelled:** losses in the traces, the planes' own inductance,
  and the gate delays inside the parts (they come from datasheets, in the
  report's budgets).
