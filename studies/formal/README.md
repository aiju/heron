---
status: active
depends-on: [v1b_hw, v1_isa]
reports: [38]
---

# Formal verification, explored

How far symbolic simulation and an SMT solver get in proving that the
hardware implements the instruction set: the draft 1b netlist
([v1b_hw](../v1b_hw/README.md)), run with symbolic values, against a
specification of draft 1b, run the same way, one instruction at a time.

- **The hardware side** is the chip-level netlist itself, run a clock
  cycle at a time on values that are known or z3 terms (`symsim.py`).
  The control store's address must stay known: where a symbolic bit
  reaches it, the run splits in two, each side with that bit decided.
  That is the case-splitting heuristic: control known, data symbolic.
- **The instruction set side** is a specification in a small language made
  for it ([RFC 0038, Part II](../../reports/0038-rfc-formal-verification.md#part-ii-the-specification-language),
  [v1b.isa](v1b.isa)), interpreted on
  known values (checked against the instruction-level simulator) or on
  symbolic ones, where it gives the next state as terms in one pass,
  without forking.
- **The proof** (`v1b.py`) is a commuting diagram per decode case: from
  any state at an instruction boundary, the hardware's run to the next
  boundary ends where the specification's instruction does, on every
  path; and reset reaches a boundary.

It uses z3 (`pip install z3-solver`), which nothing else in the
repository needs. The flow it suggests, the language, and the results: [RFC 0038](../../reports/0038-rfc-formal-verification.md).

| File | What's in it |
|---|---|
| `spec.py` | The specification language ([RFC 0038, Part II](../../reports/0038-rfc-formal-verification.md#part-ii-the-specification-language)): its parser, its checker and its interpreter, on known or symbolic values |
| [v1b.isa](v1b.isa) | Draft 1b, specified |
| `isacheck.py` | The specification against the instruction-level simulator: random states and instructions, one step each |
| `isagen.py` | The same on cases the specification chooses: each instruction run symbolically once, every outcome of every decision a goal, the solver finding inputs for each (the rest random) |
| `logic.py` | Bits that are known or z3 terms, with constant folding |
| `symsim.py` | Symbolic simulation of a netlist, cycle by cycle: models of the chip library's parts, three-state buses (contention as proof obligations), splits at the ROMs |
| `v1b.py` | The 1b hardware under it: the state by name, the I/O page fixture, the abstraction at an instruction boundary, the decode cases, the proofs (and reset) |
| `prove.py` | Proving decode cases in parallel, each with a time budget |
| `mutate.py` | Mutation testing: mistakes put into the netlist or the microcode on purpose (by hand, and at random), and whether the chip-level tests and the proofs catch them |
| `report.py` | RFC 0038's generated tables, from the proof and mutation runs |

```sh
heron formal isacheck -n 20000 --coverage      # the specification against the simulator
heron formal isagen --trials 3 -v               # ... on cases aimed at every outcome of every decision
heron formal prove --kind un                    # prove the unary group's decode cases
heron formal prove --key "ea 4 None 0 None"     # one case: ADD rd, rn
heron formal prove --jobs 4 --budget 1800       # every case (hours; results in build/formal/)
heron formal mutate                             # mutation testing (hours)
heron formal report --write                     # RFC 0038's results.md, from both
heron test formal                               # the unit tests
```
