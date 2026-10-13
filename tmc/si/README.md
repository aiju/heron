# Backplane signal-integrity simulation

Simulates the proposed system bus ([docs/system-bus.md](../../docs/system-bus.md);
its section 9 has the electrical rules that came out of these runs) in
ngspice: one bus line along a 6U backplane with 8 or 16 slots, each slot a
DIN 41612 contact, a card stub and a '245 transceiver. The transceivers are
TI's IBIS models (74ABT245B, 74ACT245, 74FCT245T, 74AHCT245, 74HCT245),
converted to ngspice behavioural sources.

| File | What it does |
|---|---|
| `ibis.py` | Downloads the IBIS files from ti.com into `build/ibis/`, parses them, derives the switching coefficients, writes ngspice sources |
| `fields.py` | 2D field solver for the backplane trace's L and C (checked against the closed-form Hammerstad formula) |
| `bus.py` | The backplane model, terminations, the radial clock tree, settle-time measurements |
| `noise.py` | Crosstalk between neighbouring lines, and ground bounce from many outputs switching at once |
| `spice.py` | Runs ngspice in batch mode |
| `sweep.py` | The `quick` and `full` presets; runs jobs in parallel, resumably |
| `cli.py` | `python3 -m tmc si check` and `python3 -m tmc si sweep` |

## Running the sweeps on your own machine

The sweeps are too slow for the cloud VM (four slow cores), so run them
locally. These steps are written so a Claude Code session can follow them
as they are.

### What's needed

- Python 3.10+ with numpy (`pip install numpy`). Nothing else in Python.
- **ngspice** on the PATH. The models were tested with ngspice 42; the
  committed results in `docs/bus-si/` came from ngspice 47. Any recent one
  should do.
  - macOS: `brew install ngspice`
  - Debian/Ubuntu: `sudo apt install ngspice`
  - Fedora: `sudo dnf install ngspice`
  - Windows: use WSL and the Ubuntu package
- Internet access to www.ti.com once, for the IBIS models. If the download
  fails with a certificate error (python.org builds on macOS), run
  "Install Certificates.command" from the Python folder in Applications, or
  fetch them by hand into `build/ibis/` (each zip holds the
  one `.ibs` file named):

  | URL | File |
  |---|---|
  | https://www.ti.com/lit/zip/scbm052 | `sn74abt245b.ibs` |
  | https://www.ti.com/lit/zip/SCAM044 | `sn74act245.ibs` |
  | https://www.ti.com/lit/zip/SCCM001 | `cy74fct245t.ibs` |
  | https://www.ti.com/lit/zip/SCLM076 | `sn74ahct245.ibs` |
  | https://www.ti.com/lit/zip/SCLM097 | `sn74hct245.ibs` |

### Steps

All commands run at the top of the repository, on whichever branch the
request names (`main` if none):

```sh
git fetch origin
git checkout main && git pull
```

1. **Check the setup:** `python3 -m tmc si check`. It takes a minute or two,
   most of it the field solver (cached afterwards in `build/`). It should
   print:
   - the ngspice version and the five IBIS models;
   - a trace impedance of about 67.5 Ω (closed form about 67.9 Ω) and about
     5.80 ps/mm;
   - IBIS check errors under about 0.05 ns for ACT and 0.3 ns for ABT;
   - the time of one bus-line run (5–6 s on the cloud VM), and rough
     estimates for both presets.

   If anything here fails, stop and report the output.
2. **Quick sweep:** `python3 -m tmc si sweep --preset quick`. That's 72 jobs:
   - 36 bus-line runs: ABT, FCT and HCT drivers; no termination, VME-style
     330/470 Ω, or 33 Ω + 220 pF; the driver at the end or middle slot;
     slow and fast corners;
   - 8 clock-tree runs, 8 crosstalk runs and 4 ground-bounce runs;
   - the IBIS checks and reference delays.

   It uses every core by default (`-j N` to change that) and prints progress
   and an estimate of the time left. At the end it writes
   `docs/bus-si/quick.json`, including how long the run took.
3. **Full sweep** (only if the quick one went fine and its time looks
   reasonable for 1,197 jobs): `python3 -m tmc si sweep --preset full`. That's
   8 and 16 slots, all five families, seven terminations, every driver
   position, more crosstalk and ground-bounce cases. It writes
   `docs/bus-si/full.json`.
4. **Commit and push** only `docs/bus-si/*.json` (`build/` is ignored), with
   a message that says which preset ran and on what machine, then
   push the branch.

### If something goes wrong

- **Stopping and resuming.** A sweep can be stopped with Ctrl-C at any
  time. Every finished job is in `build/si/<preset>.jsonl`, so running the
  same command again carries on from there.
- **Errors in a few jobs.** Usually a timeout (a run that takes more than
  5 minutes is killed), or ngspice giving up part way through ("Timestep
  too small", reported as "ngspice stopped at … ns"). They're listed as
  they happen and counted at the end.
  `--retry-errors` runs them again. To look at one, run it on its own:

  ```sh
  python3 -c "from tmc.si import sweep; print(sweep.run_job(('line', 16, 'vme', 'abt', 'min', 0)))"
  ```

  using the job tuple from the error message.
- **Every job fails.** Probably ngspice: a missing binary, or a version that
  rejects some syntax. The error message carries the end of ngspice's
  output.
- **Don't change the models, presets or thresholds** to make a run pass.
  Report what failed instead, so the results stay comparable with the ones
  already committed.

### What to report back

- The machine (CPU, cores), the `-j` used, and the ngspice version.
- The wall-clock time of each preset. It's also in the JSON
  (`wall_minutes_last_run`, `cpu_minutes`).
- The number of errors, with the job and message for each.

For now, section 9 of [docs/system-bus.md](../../docs/system-bus.md)
summarises the results; a fuller write-up (`docs/bus-si.md`) is still to
come (see [docs/proposals.md](../../docs/proposals.md)).

## The model, in short

- **Backplane trace:** 0.2 mm wide on 0.21 mm of 7628 prepreg (εr 4.4) over
  a plane. Field-solved at 67.5 Ω and 5.8 ps/mm. Neighbouring traces are
  1.27 mm apart, where they pass between connector pins.
- **Slots:** 20.32 mm apart (4HP), with 10 mm from each end slot to the
  terminator.
- **Connector:** 12 nH and 2 pF. That's estimated from the contact geometry,
  since no measured figures turned up. Neighbouring contacts couple with
  k = 0.4, or 0.2 in the low case.
- **Card:** a 25 mm stub to the transceiver, a DIP package with the worst
  I/O pin's R, L and C from the IBIS file, and 100 kΩ of input leakage per
  receiver.
- **Driver models:** TI's ACT and AHCT files are self-consistent and the
  converted models reproduce them within 20 mV. The ABT, FCT and HCT files'
  V-T waveforms disagree with their own V-I tables. For those, the model
  follows the waveform through the edge and the V-I tables for the DC
  levels; the 50% points match within 0.3 ns.
- **What's measured:**
  - **Settle time:** the last time a receiver's input crosses into the
    valid region (above 2.0 V or below 0.8 V) after the driver's edge,
    measured from the start of the edge. The `ref` jobs give the time to
    1.5 V into the datasheet test load, which is subtracted to get the delay
    the bus adds to the datasheet propagation delay.
  - **Overshoot and undershoot.**
  - **Bus high and low levels.**
  - **Extra threshold crossings,** i.e. ringing back through the threshold
    region.
- **Ground bounce:** each switching line is an equivalent uniform line of
  the loaded impedance; only the quiet victim line has every receiver
  modelled.
