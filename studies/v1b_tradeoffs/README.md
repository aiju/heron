---
status: active
depends-on: [v1b_system, v1b_hw, v1_isa]
reports: [24]
---

# Faster and smaller: the draft 1b system's time and chips

Where the system of `v1b_system` spends its time and its chips, what
could make it faster or smaller, and how far either can go. The findings
and the proposals are [RFC 0024](../../reports/0024-rfc-faster-smaller.md);
its generated tables are its
[results.md](../../reports/0024-rfc-faster-smaller/results.md).

| File | What's in it |
|---|---|
| `parts.py` | Sets of faster parts, as variants of the chip library: 74F/74ABT logic, 12 ns RAM, the control store in flash or in SRAM |
| `timing.py` | Static timing of the 1b CPU with each set, and the program suite's time at a fixed clock, with ideal cycle lengths, and with four length classes |
| `fastcard.py` | The CPU card with those parts and a clock generator for short cycles (4-19 ticks of 20 ns); the bus interface is v1b_system's |
| `fastsys.py` | The system with that card: its length classes, and the program suite at chip level |
| `cycles.py` | A cycle model for other microarchitectures (draft 1's timing model with more knobs, calibrated on the 1b hardware), cycle floors, and multiply and divide what-ifs |
| `breakdown.py` | Chips by card and section, what 16-bit parts would save, the upper half of the datapath, the microinstruction's fields |
| `report.py` | The RFC's generated tables |

```sh
heron v1b_tradeoffs report [--write] [--hw]     # the RFC's tables (--hw: run the suites at chip level, ~30 min)
heron v1b_tradeoffs parts [SET...] [--path]     # static timing with other parts
heron v1b_tradeoffs cpu sweep exercise --variant fast --lo 95 --hi 115   # the 1b CPU alone at chip level
heron v1b_tradeoffs fast [--parts fast-flash] lengths       # the fast system's length classes
heron v1b_tradeoffs fast [--parts fast-flash] run PROG.s    # a program on it at chip level
heron v1b_tradeoffs fast [--parts fast-flash] test [NAMES]  # the suite on it (~10 min)
heron test v1b_tradeoffs                        # unit tests
```

Two parts sets run the whole system at chip level: `fast`, with the
control store in 12 ns SRAM, and `fast-flash`, with it in the 55 ns flash
the system has now. The SRAM control store is modelled as the flash
chips' one-for-one replacement; a real one needs a loader that fills it
from a flash at power-up, which isn't in the netlist (RFC 0024 counts it).
