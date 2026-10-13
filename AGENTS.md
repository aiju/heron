# Agent instructions

Heron is the design of a minicomputer built from 7400-series logic: the
instruction sets, a CPU implementation with its microcode and chip-level
netlist, simulators and timing analysis, a C compiler, the system bus, and
the design discussions behind them. [README.md](README.md) has the layout
and how to run everything.

## Git

- Start from the latest `main`, work on a branch, and open a pull request
  against `main` when the work is done. Leave merging to Emily.
- Keep each pull request to one topic: the bus spec, the compiler, the CPU
  netlist and so on.

## Documents

- [docs/proposals.md](docs/proposals.md) holds every design idea with a
  status: adopted, measured, recommended, decided, open or rejected.
  - Only Emily decides. Record a choice as **decided** only when she has
    made it.
  - A rejected idea keeps its reason, so it isn't proposed again without
    new evidence.
- Some documents are generated, as the README's table says. Change the
  generator and rerun it rather than editing the output by hand:
  - `docs/performance*.md` and `docs/compiler-performance.md`;
  - `docs/microcode-v1b.md`.
- When you add a document or a command, add it to the README.

## Checking changes

- `python3 -m unittest discover tests`: assembler, ISA, compiler and linker
  tests.
- `python3 -m tmc test` and `python3 -m tmc --isa v1b test`: the programs
  against their expected output.
- `(cd hwsim && go test ./...)`: the Go simulator's chip models.
- The chip-level and signal-integrity runs are slow. The full hardware
  report takes about half an hour.
- The signal-integrity sweeps take over an hour on a fast laptop. Don't run
  them in a cloud session: they are meant for a local machine
  ([tmc/si/README.md](tmc/si/README.md)).

## Big files

Git history is permanent, so a big file stays in every clone even after
it's been deleted.

- Never commit build output or downloads. `build/` holds ROM images,
  netlists, the simulator binary, simulation scratch and the IBIS models
  from ti.com.
- Don't commit anything that can be regenerated quickly from the code. The
  signal-integrity results in `docs/bus-si/` are the exception, since they
  take hours to produce.
- Keep every file under 10 MB, and check `git diff --cached --stat` before
  committing.
