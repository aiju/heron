---
number: 13
type: report
title: Signal integrity of the backplane bus, quick and full sweeps
status: current
date: 2026-10-12
context:
  studies: [bus_si]
  commit: e494b0c
---

# Report 0013: Signal integrity of the backplane bus, quick and full sweeps

The ngspice sweeps of the proposed backplane bus ([the bus_si study](../studies/bus_si/README.md)):
one bus line along a 6U backplane with 8 or 16 slots, with the transceiver
families, terminations, driver positions, crosstalk, ground bounce and the
clock tree. The electrical rules in
[RFC 0014, section 9](0014-rfc-system-bus.md#9-electrical-rules) come from
these results, summarised by hand.

| File | Preset | Jobs | Errors |
|---|---|---:|---:|
| [quick.json](0013-report-bus-si/quick.json) | `quick` | 72 | 0 |
| [full.json](0013-report-bus-si/full.json) | `full` | 1,197 | 68 |

Both ran on a MacBook Air (Apple M3, 8 cores, 24 GB) with ngspice 47, in
4.3 and 86.8 minutes. Of the 68 failed jobs, 44 hit the 300 s ngspice
timeout and 24 stopped early with "timestep too small"; they fail the same
way on an idle machine, so they weren't retried. The ground-bounce model
is numerically unreliable, so those results shouldn't be relied on yet.

The sweeps write these files (`heron bus_si sweep --preset quick|full`);
the bus_si study's README says how to run them on a local machine.
