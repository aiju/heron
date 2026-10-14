# Agent instructions

Heron is the design of a minicomputer built from 7400-series logic: the
instruction sets, CPU implementations with their microcode and chip-level
netlists, simulators and timing analysis, a C compiler, the system bus, and
the design discussions behind them. [README.md](README.md) has the layout
and how to run everything; [RFC 0000](reports/0000-rfc-repository-layout.md)
has the reasons.

## Git

- Start from the latest `main`, work on a branch, and open a pull request
  against `main` when the work is done. Leave merging to Emily.
- **The one push to `main`:** reserving a report's or RFC's number pushes
  its stub straight to `main` ([below](#reports-and-rfcs)). Nothing else
  goes to `main` except through a pull request.
- Keep each pull request to one topic: the bus spec, the compiler, the CPU
  netlist and so on.

## Where things go

| What | Where |
|---|---|
| The current design, as reference: what it is, not why or what else was considered | `docs/` (and, from draft 2, `isa/`, `hw/`, `sw/`, `tools/`) |
| An experiment: a design, a measurement, a tool | its own folder in `studies/` |
| Code any design can reuse, with no opcodes, microcode fields or memory map in it | `infra/` |
| An engine: a simulator, an assembler or linker | a Rust crate, in the folder it belongs to ([RFC 0015](reports/0015-rfc-languages.md#where-the-rust-code-lives)) |
| What you did and found | a report in `reports/` |
| A proposal, or anything that needs Emily to decide | an RFC in `reports/` |
| A small idea, not yet worth an RFC | the area's ideas RFC (0005–0010) |

- **Dependencies:** `infra/` never imports a study. A study may use other
  studies, and lists them in the front matter of its README.
- **Frozen studies:** don't fix a frozen study unless asked. Its code may
  stop working as `infra/` changes; its README says which commit it last
  ran at.
- **Working in the root:** where work happens isn't dogma. Work in the
  root when that's the natural place.

## Rust

The engines are Rust, everything else is Python
([RFC 0015](reports/0015-rfc-languages.md)).

- **The workspace:** every crate is a member of the one workspace in the
  root `Cargo.toml`; add new crates to its `members`. `Cargo.lock` is
  committed. Cargo's output goes to `build/cargo/`.
- **The bindings:** `heron/bindings` is the only crate that uses PyO3. It
  wraps the engines as one Python module, which Python code imports as
  `heron.native`. An engine crate is plain Rust, with its own Rust API and
  tests; it doesn't know about Python.
- **Lints:** crates take the workspace's lints (`[lints] workspace = true`).
  Unsafe code is denied; where it's really needed, allow it locally and say
  why.

## Reports and RFCs

- **Files:** `reports/NNNN-report-slug.md` or `reports/NNNN-rfc-slug.md`.
  Data or generated files that go with one live in a folder of the same
  name next to it (`reports/NNNN-report-slug/`).
- **Numbers:** reports and RFCs share one numbering space. Before writing
  one, reserve its number:

  ```sh
  heron reports reserve report graphics "Graphics on draft 1"   # or rfc
  ```

  This pushes a stub (front matter, status `draft`) and the index straight
  to `main`. The push only succeeds if `main` hasn't moved, so the number
  is yours; if it has moved, it tries the next one. Then merge
  `origin/main` into your branch and write over the stub, changing the
  title or status as you go. Don't create the file on your branch before
  the merge: that's an add/add conflict.
- **If the push to `main` is refused:** take the next free number on your
  branch, say so in the PR, and renumber if another PR takes it first.
- **A reservation you won't use:** remove its stub in your PR.
- **Front matter:** every report and RFC starts with YAML front matter
  (number, type, title, status, date, context with the studies and a
  commit on `main`). Copy it from an existing one.
- **Statuses:**
  - reports are `draft`, `current` or `obsolete`;
  - RFCs are `draft`, `open`, `accepted`, `rejected` or `obsolete`;
  - set `superseded-by` when something replaces a document.
- **Who decides:** only Emily decides. Never set `accepted` or `rejected`
  unless she has made that choice. A rejected idea keeps its reason, so it
  isn't proposed again without new evidence.
- **Reports are snapshots:** once a report is `current`, don't rewrite its
  text. Only its status, `superseded-by` and clearly marked errata change.
- **RFCs may carry findings:** an RFC can include the findings behind it.
  Whether they deserve a report of their own is a judgement call.
- **The index:** after adding a report or changing a status, run
  `python3 -m heron reports`. It rewrites `reports/README.md` and checks
  the front matter. Git merges the index by keeping both sides' lines
  (`.gitattributes`), so merging `main` never stops on it; run
  `heron reports` after the merge to clean up what that leaves.

## Generated files

Change the generator and rerun it rather than editing the output by hand:

- the `performance.md` in reports 0001, 0004, 0011, 0012, 0018 and 0019:
  - `heron v0_hw report`
  - `heron v1_isa report`
  - `heron c_compiler bench --write`
  - `heron v1b_hw report`
  - `heron lisp report --write`
  - `heron graphics bench --write` (also the screenshots next to it)
- `studies/v0_hw/microcode.md` and `studies/v1b_hw/microcode.md`:
  `heron v0_hw ucode --doc` and `heron v1b_hw ucode --doc`;
- `studies/v1_isa/programs/expected/` and
  `studies/v1_isa/programs/common/vm_code.s`:
  `python3 studies/v1_isa/programs/reference.py`;
- `studies/c_compiler/tests/cc/expected/`:
  `python3 studies/c_compiler/tests/cc/gen_expected.py` (needs gcc);
- `studies/graphics/expected/`: `heron graphics expected` (needs gcc);
- `studies/graphics/fonts/sans.ttf`, `sans12.txt` and `mono12.txt`:
  `python3 studies/graphics/fonts/make_fonts.py` (needs the DejaVu fonts
  and Pillow);
- `infra/hw/timing.json`: `python3 -m heron.infra.hw.build_timing`, from
  `infra/hw/datasheets/`;
- `studies/v0_hw/baseline.json`: `baseline.write()` in that study (it's
  frozen, so this shouldn't be needed);
- `reports/0021-report-bus-si-revised/results.md`: `heron bus_si report`;
- `reports/README.md`: `heron reports`.

## Checking changes

Run commands from the repository root as `python3 -m heron ...` (or as
`heron` after `pip install -e .`).

- `heron test`: the repository's own tests (front matter, the index, links,
  infra's dependencies).
- `heron test v1_isa c_compiler v1b_hw v0_hw graphics bus_si`: a study's
  unit tests. Run the ones for the studies you touched, or `--active` for
  every active one.
- `heron v1_isa test` and `heron v1_isa --isa v1a test`: the programs
  against their expected output.
- `heron c_compiler bench`: the C versions of the programs on both
  encodings.
- `heron lisp test` and `heron lisp test -c`: the Lisp's programs and
  tests, interpreted and compiled (`-c --features tagged`: on v1bx).
- `heron graphics test` and `heron graphics selftest`: the graphics
  scenes against the host reference, and the kernels against pixel
  references.
- `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` and
  `cargo test`: the Rust workspace. CI runs all three, then `heron test`,
  which builds the engines' Python module and tests it.
- **Slow runs:** the chip-level runs take minutes: `heron v1b_hw hw test`
  about 5 for every program, and `heron v1b_hw report --hw` longer.
- **Signal integrity:** `heron bus_si report` runs report 0021's sweeps
  on the native engine, about 15 minutes on four cores; a single preset
  takes seconds to minutes. Run long ones in the background: they resume
  where they stopped, and no job can hang
  ([studies/bus_si](studies/bus_si/README.md)).

## Big files

Git history is permanent, so a big file stays in every clone even after
it's been deleted.

- Never commit build output or downloads. `build/` holds ROM images,
  netlists, cargo's output and the engines' Python module, simulation
  scratch and the IBIS models from ti.com.
- Don't commit anything that can be regenerated quickly from the code. The
  signal-integrity results in report 0013 are the exception, since they
  take hours to produce.
- Keep every file under 10 MB, and check `git diff --cached --stat` before
  committing.
