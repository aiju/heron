---
number: 0
type: rfc
title: Repository layout, studies, reports and RFCs
status: open
date: 2026-10-13
context:
  commit: 852df5e (main, after the cleanup in PR #9)
discussion: https://github.com/aiju/heron/pull/11
---

# RFC 0000: Repository layout, studies, reports and RFCs

## Summary

The repository is reorganised around one idea: the root holds the
**current design**, and everything else is either reusable code, an
experiment, or a numbered record of what was found or decided.

| Folder | Holds |
|---|---|
| `docs/` | Reference documentation for the current design: what it is, not why |
| `isa/` | The current ISA's definition, shared by the tools, the hardware and the tests |
| `hw/` | The current hardware design |
| `sw/` | Software for the machine: boot ROM, monitor, OS, C library |
| `tools/` | Host tools for the current design: assembler, simulators, compiler |
| `tests/` | Tests of the current design and of `infra/`; test programs and their expected output |
| `infra/` | Reusable code that doesn't depend on any one design |
| `studies/` | Experiments, one folder each, mostly self-contained |
| `reports/` | Numbered reports and RFCs |
| `heron/` | The `heron` package and command (see [Python packaging](#python-packaging)) |
| `build/` | Generated output, ignored by git (as now) |

There is no current design yet, so `isa/`, `hw/`, `sw/` and `tools/` don't
exist at first. Draft 2 fills them.

## Motivation

- **Every tool serves three machines.** Draft 0, 1a and 1b share one package
  and are picked with `--isa`. The shared tools branch on each: the `WIDE`
  checks, `run` and `run32`, the global `cli.MACHINE`, about 20
  `if machine == "v1b"` branches. Draft 2 would add a fourth.
- **`docs/` mixes five kinds of document:** reference (the ISA specs),
  results (the evaluations), history ("Getting there"), session logs (the
  program writers' notes) and proposals.
  - `proposals.md` is 1,083 lines. It repeats much of the bus spec, and
    the two have started to disagree (#2).
- **Nothing says what the current design is.** The bus spec and the
  clocking work assume "the draft 1b CPU", while the evaluations recommend
  building draft 2 on 1a.

## Layout

### Dependencies

- `infra/` depends on nothing else in the repository.
- The current design (`isa/`, `hw/`, `sw/`, `tools/`, `tests/`) depends on
  `infra/`, never on a study.
- A study depends on `infra/` and may depend on other studies. It lists
  them (see [Studies](#studies)).
- Nothing depends on `reports/`. Reports cite code by study and commit.

### Where work happens

This isn't a rule to be dogmatic about. Usually:

- New design ideas start as studies, for example the candidates for
  draft 2.
- When Emily picks one, it moves to the root. The study's folder keeps
  only its README, with `status: moved`, saying where the code went and in
  which commit.
- When the current design is replaced, it becomes a frozen study.

But work can happen in the root directly when that's the natural place for
it, for example a change to the current design that doesn't need an
experiment first.

## infra/

Reusable code that doesn't depend on any one design:

- the assembler and linker core and the object format;
- the netlist language, the chip library and its timing data;
- static timing analysis;
- the event-driven chip-level simulator (Go);
- the program test harness;
- the IBIS and ngspice plumbing.

**Rule:** no design details in `infra/`: no opcodes, no microcode fields,
no memory map. Code that needs them takes them from the design or study
that uses it.

`infra/`'s internals are documented next to the code
(`infra/<part>/README.md`). `docs/` is about the machine.

## Studies

A study is an experiment: a design, a measurement, a tool. It is mostly
self-contained.

- **Folder:** `studies/<name>/`, named in snake_case so it can be a Python
  package: `v0_hw`, `v1_isa`, `v1b_hw`, `c_compiler`, `bus_si`.
- **Front matter:** its `README.md` starts with:

  ```yaml
  ---
  status: active          # or frozen, or moved
  depends-on: [v1_isa]    # other studies; infra is implied
  frozen-at: 1a2b3c4      # frozen only: the last commit on main where it ran
  reports: [12, 31]       # its reports
  ---
  ```

  After that, the README says what the study is and how to run it.
- **Documentation:** a study's own documentation (an ISA spec, a hardware
  description) lives in the study. Its findings are reports.
- **Command line:** each study has its own, reached through the `heron`
  command (see [Python packaging](#python-packaging)), for example
  `heron v1b_hw hw run fib.s`. There is no `--isa` across machines; a study knows its machine.
- **Active vs frozen:**
  - **Active:** its tests run in the slow CI (see [CI](#ci)). Breakage
    while someone is working on it is accepted.
  - **Frozen:** no tests run. To reproduce its results, check out
    `frozen-at`. Its code may stop working as `infra/` changes, and that is
    accepted. Fixing it makes it active again.
  - **Moved:** its design became the current one and moved to the root;
    only the README is left.

## Reports and RFCs

### What each is

- **Report:** what was done and what was found. A report doesn't ask for
  decisions. If it suggests one, it points to an RFC.
- **RFC:** proposes something and invites decisions: a design choice, a
  process, a set of ideas. Once the decision is made, the RFC records it.
  An RFC can include findings that support it; an ISA RFC might include
  measurements of the ISA, for example. Whether those findings deserve a
  report of their own is a judgement call.

Reports and RFCs share one numbering space.

### Files

- **Name:** `reports/NNNN-report-slug.md` or `reports/NNNN-rfc-slug.md`,
  with a four-digit number.
- **Folder form:** a folder with the same name, holding a `README.md` plus
  data or generated files. Examples are the SI sweep results, or a
  performance report a study generates.

### Numbers

For now, a new document takes the next free number. A unit test checks
that numbers are unique and the front matter is valid. If two PRs take the
same number, the one merged second renumbers. How parallel sessions should
allocate numbers is still open (see [Open questions](#open-questions)).

### Front matter

```yaml
---
number: 46
type: report                # or rfc
title: Backplane signal integrity, quick and full sweeps
status: current
date: 2026-08-02
context:
  studies: [bus_si]
  commit: 1a2b3c4           # on main: the code the results came from
depends-on: [44]            # reports and RFCs this one builds on
superseded-by: 51           # only once obsolete
discussion: https://github.com/aiju/heron/pull/52   # optional: where it was discussed
---
```

`commit` is always a commit on main. A PR branch's commits vanish when the
PR is squash- or rebase-merged. A report written in a PR cites the main commit the
branch started from, or gets its commit filled in after the merge.

### Statuses

| Status | For | Meaning |
|---|---|---|
| `draft` | both | Being written; nothing to act on yet |
| `open` | RFC | Waiting for Emily's decision |
| `accepted` | RFC | Emily decided yes; `docs/` and the code should match |
| `rejected` | RFC | Emily decided no; the reason stays, so it isn't proposed again without new evidence |
| `current` | report | The findings still describe things as they are |
| `obsolete` | both | No longer applies; kept for history, with `superseded-by` if something replaced it |

**Who decides:** only Emily sets `accepted` or `rejected`. An accepted
RFC's content is reflected in `docs/`, and the RFC stays as the record of
why.

**RFCs with several items:** an RFC can hold several items, each with its
own status in the same words. One RFC of instruction-set ideas is an
example. The front matter gives the status of the RFC as a whole, and it
stays `open` while any item is.

**Changing a report after the fact:** once a report is `current`, its
text isn't rewritten. Only its status, `superseded-by` and clearly marked
errata change.

The exception is a generated report: a folder whose README names the
command that writes it. While its study is active, rerunning the command
updates the report and its `commit`.

**Index:** `reports/README.md` lists every report and RFC with its status.
It is generated from the front matter.

### Ideas RFCs

An ideas RFC (`NNNN-rfc-ideas-<area>.md`) is a scratchpad for one area. It
holds ideas not yet worth an RFC of their own, each with a status.

- An idea worth pursuing gets its own RFC, linked from the list.
- When a scratchpad gets stale, it is marked `obsolete` and a new one
  starts with whatever is still live.

## docs/

- **Reference for the current design:** what it is and how to use it.
- **No history and no alternatives:** nothing on alternatives considered.
  For why, link the RFC or report.
- **Decided parts belong here too:** a part of the design that has been
  decided but not built belongs in `docs/` once its RFC is accepted. The
  clocking scheme is an example.

## Python packaging

- **One package, `heron`, spanning the folders:** the top-level folders are
  its subpackages.

  | Import | Folder |
  |---|---|
  | `heron.infra` | `infra/` |
  | `heron.studies` | `studies/` |
  | `heron.tests` | `tests/` |
  | `heron.isa`, `heron.hw`, `heron.tools` | `isa/`, `hw/`, `tools/` (from draft 2) |

  A small `heron/` folder at the root holds the package itself. Its
  `__init__.py` adds the repository root to the package's path, so a plain
  checkout works from the root with `python3 -m heron ...` and nothing to
  install.
- **Installing is optional:** `pip install -e .` (with `pyproject.toml`)
  makes the imports work from any directory and installs a `heron`
  command.
- **Folder names:** every folder below these is a valid Python identifier.
- **Go:** the chip-level simulator stays a Go module, in `infra/hwsim/`.
- **The `heron` command** runs a study by name, and has a few commands of
  its own:
  - `heron v1b_hw hw run fib.s`, `heron c_compiler cc prog.c --run`;
  - `heron list`: the studies, with their status and dependencies;
  - `heron test [study...]`: unit tests;
  - `heron reports`: the index.

  Each study has a `cli.py` with `main(argv)`, so
  `python3 -m heron.studies.v1b_hw` works too. Names of studies and tools
  must not clash.
- **ISAs register themselves:** object files and command lines name ISAs,
  so the study that defines one registers it with `heron.infra.isas` when
  it is imported. `infra/` never has to know which studies exist.
- **Machines are modules:** the chip-level tools (`heron.infra.hw.runner`,
  `heron.infra.hw.sta`) take a *machine* module from the study that
  describes it (`studies/v0_hw/machine.py`, `studies/v1b_hw/machine.py`).

Which languages the tools should be written in is a separate question for a
separate RFC.

## CI

| Run | When | What |
|---|---|---|
| Fast | Every push to a PR | `infra/` and the current design (`tests/`): minutes, must pass |
| Slow | By hand or nightly, on GitHub | Active studies' tests and the chip-level runs; failures are reported, not blocking |
| Never | | Frozen studies; the signal-integrity sweeps (local only, as now) |

## Migration

Done in three stages, each a commit with the tests passing: the code, the
documents, then README, AGENTS.md and CI. Where everything went:

| Before | After |
|---|---|
| `tmc/asm.py`, `obj.py`, `link.py`, `tools.py` | `infra/asm.py`, `obj.py`, `link.py`, `objtools.py` |
| `tmc/isa/__init__.py` | `infra/isas.py`, a registry |
| `tmc/testing.py` | `infra/programs.py` (the shared parts) and a `testing.py` per study |
| `tmc/hw/netlist.py`, `chips.py`, `sta.py`, `build_timing.py`, `timing.json`, `datasheets/` | `infra/hw/` |
| `tmc/hw/cli.py` | `infra/hw/runner.py`, taking a machine module |
| `hwsim/` | `infra/hwsim/` |
| `tmc/si/`: IBIS, ngspice, field solver | `infra/si/` |
| `tmc/si/`: the bus, crosstalk and ground-bounce models, the sweeps | `studies/bus_si/` |
| Draft 0: `tmc/isa/v0.py`, `sim.py`, `hw/microcode.py`, `hw/cpu_v0.py`, `report.py`, `analyze.py`, `programs/v0/`, its tests; `isa-v0.md`, `hardware.md`, `microcode.md` | `studies/v0_hw/`, frozen, plus `baseline.json` (its results, which the draft 1 reports compare against) |
| `tmc/isa/v1a.py`, `v1b.py`, `v1common.py`, `sim32.py`, `timing32.py`, `report1.py`, `programs/v1a/`, `programs/v1b/`, the program suite (`reference.py`, `expected/`, `common/`), its tests; `isa-v1*.md`, `timing-model-v1.md` | `studies/v1_isa/` |
| `tmc/hw/ucode_v1b.py`, `rtl_v1b.py`, `cpu_v1b.py`, `check_v1b.py`, `report1b.py`, `tests/hw/exercise_v1b.py`; `hardware-v1b.md`, `microcode-v1b.md` | `studies/v1b_hw/` |
| `tmc/cc`, `tmc/ir`, `tmc/codegen`, the C library, `programs/c/`, `tests/cc/`, the compiler tests; `compiler.md` | `studies/c_compiler/` |
| `docs/linking.md` | `infra/linking.md` |
| `docs/evaluation.md`, `performance.md` | Report 0001 (obsolete, superseded by 0004) |
| `docs/programming-notes.md` | Report 0002 (obsolete) |
| `docs/notes-v1/*` | Report 0003, one folder with the five writers' notes |
| `docs/evaluation-v1.md`, `performance-v1.md` | Report 0004 |
| `docs/proposals.md` | Ideas RFCs 0005–0010, one per area, each item keeping its status; the decisions in "Answered so far" are in `docs/README.md` |
| `compiler.md`'s results, `compiler-performance.md` | Report 0011 |
| `docs/performance-v1b.md` | Report 0012 |
| `docs/bus-si/*.json` | Report 0013 |
| `docs/system-bus.md` | RFC 0014, open |
| The clocking scheme (decided) | `docs/clocking.md`; its measurements stay in RFC 0007 |

Existing documents were numbered from 0001 in the order they were first
written. The program suite stays with the draft 1 study (`studies/v1_isa`)
for now, so draft 0 and the compiler depend on it for their expected
output.

## AGENTS.md, in short

- **Where things go:** the table in [Summary](#summary).
- **Write findings as a report** and proposals as an RFC, with the next
  free number. Small ideas go in the area's ideas RFC.
- **Never set `accepted` or `rejected`.**
- **`docs/` is reference for the current design only.**
- **Studies:** a study lists what it depends on, and `infra/` never
  depends on a study. Don't fix a frozen study unless asked.

## Decisions

Emily has decided, in the discussion of this RFC:

- the layout above, with the names `studies/`, `infra/` and `tests/`;
- active and frozen studies, with only a slow, hand-started CI for
  studies, and some breakage accepted while work is under way;
- the statuses, and ideas RFCs as per-area scratchpads;
- report folders for generated tables and data;
- one `heron` package, and a top-level `heron` command;
- the C compiler is a study;
- the program suite lives in `studies/v1_isa` for now;
- a study whose design becomes current is moved to the root, not copied;
- for now, a new document takes the next free number.

## Open questions

1. **Numbers:** how should parallel sessions allocate them, so two PRs
   don't take the same one?
