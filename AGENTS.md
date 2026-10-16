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
| What the machine should be (hardware, ISA, its software and their conventions), even if a study built it | an RFC with a self-contained specification |
| An experiment: the code that builds or measures a design, a tool, and how it works | its own folder in `studies/` |
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
  text. Only its status, `superseded-by`, clearly marked errata and
  (below) a specification it carries change.
- **RFCs may carry findings:** an RFC can include the findings behind it.
  Findings that exist to inform one RFC's decision go in its folder as an
  unnumbered sub-document (`reports/NNNN-rfc-slug/topic.md`), linked from
  its discussion, like RFC 0028's `link-register.md`; findings that stand
  on their own get a report ([RFC 0000](reports/0000-rfc-repository-layout.md#what-each-is)).
- **Reports may carry specifications:** a report can include the
  specification of the design it measured, as a part or an appendix
  (0012, 0018, 0020, 0025). While its study is active, that part follows
  the code, like the report's generated files.
- **Specifications:** written to be read on its own and moved to
  `docs/` unchanged: in full rather than as a diff, built only on live
  specifications, undecided parts marked **open**, reasons kept apart.
  By default Part I is the specification and Part II the discussion;
  deviate, or add parts, where that suits the document. Where your code
  needs something its RFC leaves open, add it to the RFC for Emily
  rather than deciding it in the study.
- **Mentioning one to Emily:** in chat, a PR description or a comment,
  link a report, an RFC or any other file on GitHub, at the branch that
  has the version you mean: your PR's branch if you changed it there,
  `main` otherwise. For example
  `[RFC 0006](https://github.com/aiju/heron/blob/main/reports/0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)`.
  A bare "RFC 0006" leaves her to find the right version. Inside the
  repository's own files, keep relative links.
- **The index:** after adding a report or changing a status, run
  `python3 -m heron reports`. It rewrites `reports/README.md` and checks
  the front matter. Git merges the index by keeping both sides' lines
  (`.gitattributes`), so merging `main` never stops on it; run
  `heron reports` after the merge to clean up what that leaves.

## Generated files

Change the generator and rerun it rather than editing the output by hand:

- the `performance.md` in reports 0004, 0011, 0012, 0017, 0018, 0019 and
  0020:
  - `heron v1_isa report`
  - `heron c_compiler bench --write`
  - `heron v1b_hw report`
  - `heron egret bench --write`
  - `heron lisp report --write`
  - `heron graphics bench --write` (also the screenshots next to it)
  - `heron kernel report --write`
- `reports/0036-report-fen/performance.md` and `desktop.png`:
  `heron fen bench --write`;
- `reports/0029-rfc-draft-2-system/register-banks-results.md`:
  `heron fen banks --write`;
- `reports/0032-report-lisp-egret-draft-2/lisp.md` and `egret.md`:
  `heron lisp report --isa v2 --write` and
  `heron egret bench --isa v2 --write`;
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
- `reports/0022-report-bus-si-revised/results.md`: `heron bus_si report`;
  the figures next to it: `heron bus_si traces`;
- `reports/0023-rfc-pcb-flow/results.md`: `heron pcb sweep --write` (needs
  KiCad; about an hour and a half);
- `reports/0024-rfc-faster-smaller/results.md`:
  `heron v1b_tradeoffs report --write` (`--hw` reruns the chip-level
  suites, about 30 minutes);
- `reports/README.md`: `heron reports`.

## Checking changes

Run commands from the repository root as `python3 -m heron ...` (or as
`heron` after `pip install -e .`).

- `heron test`: the repository's own tests (front matter, the index, links,
  infra's dependencies).
- `heron test v1_isa v2_isa c_compiler v1b_hw v1b_system v1b_tradeoffs
  v0_hw graphics kernel bus_si`: a study's unit tests. Run the ones for the studies you touched, or
  `--active` for every active one.
- `heron v1_isa test`, `heron v1_isa --isa v1a test` and
  `heron v2_isa test`: the programs against their expected output, in 1b,
  1a and draft 2.
- `heron c_compiler bench`: the C versions of the programs on both
  encodings.
- `heron lisp test` and `heron lisp test -c`: the Lisp's programs and
  tests, interpreted and compiled (`-c --features tagged`: on v1bx). With
  `--isa v2`, on draft 2 (`--features tagged`: its tagged operations).
- `heron egret test --heron [--isa v2]`: Egret's programs on every build
  of the VM, on 1b or draft 2.
- `heron graphics test` and `heron graphics selftest`: the graphics
  scenes against the host reference, and the kernels against pixel
  references.
- `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` and
  `cargo test`: the Rust workspace. CI runs all three, then `heron test`,
  which builds the engines' Python module and tests it.
- `heron site --serve`: the website as GitHub Pages publishes it from
  `main` (`.github/workflows/pages.yml`), served on localhost:8000;
  `--apps` adds the browser tools. A draft shows the text on the branch
  its stub names, and a page other branches change links to their
  versions, with revision bars where they differ from main
  (`--no-branches` skips both). `heron test` checks the site's links; its
  code is in `heron/site/`.
- **Slow runs:** the chip-level runs take minutes: `heron v1b_hw hw test`
  about 5 for every program, `heron v1b_system test --jobs 4` (the whole
  system on the bus) about 8, and `heron v1b_hw report --hw` longer.
- **Signal integrity:** `heron bus_si report` runs report 0022's sweeps
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
