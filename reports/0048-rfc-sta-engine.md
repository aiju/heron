---
number: 48
type: rfc
title: A static timing engine in Rust
status: draft
date: 2026-10-20
context:
  studies: [chibi]
  commit: bf5fd08
depends-on: [15, 47]
---

# RFC 0048: A static timing engine in Rust

A new static timing analysis for the netlists: an engine in Rust,
`infra/sta`, that replaces `infra/hw/sta.py`, for Chibi Heron
([RFC 0047](0047-rfc-chibi-heron.md)) first. Emily's brief
(2026-10-20):

- setup, hold, strobe and glitch checks for every signal;
- bus handovers;
- clock skew, wire load and wire delay;
- fast enough that running it is no burden;
- the ATF22V10 supported throughout;
- later, the slowest grade each 22V10 can be.

The engine checks **waveforms over a whole cycle**. Every net's stable
stretches, and the windows its transitions can fall in (from the
fastest to the slowest delays), are computed from the master clock's
edges. The clock generator's 22V10s run their real equations tick by
tick, rather than a fixture giving their outputs' times. The chips are
described as data in `chips.py`.

**Decided so far** (Emily, 2026-10-20):

- the chips' descriptions are Python data with their equations as
  strings ([16](#16-chip-descriptions-python-a-language-of-our-own-or-liberty));
- Chibi Heron alone first;
- the grade search waits until the engine is done;
- margin is reported, not added to the delays ([15](#15-margin));
- where a datasheet gives no minimum delay, the minimum is a fraction
  of the typical, set per run; its value is **open**.

This RFC changes [RFC 0015](0015-rfc-languages.md#what-doesnt-change)
in one place: that RFC kept infra's static timing analysis in Python.

## Contents

- Part I: Specification
  [1. What the engine does](#1-what-the-engine-does) ·
  [2. Time and the window](#2-time-and-the-window) ·
  [3. Values and waveforms](#3-values-and-waveforms) ·
  [4. Evaluating chips](#4-evaluating-chips) ·
  [5. Delays](#5-delays) ·
  [6. Chip descriptions](#6-chip-descriptions) ·
  [7. The 22V10](#7-the-22v10) ·
  [8. Cases](#8-cases) ·
  [9. Checks](#9-checks) ·
  [10. Results](#10-results) ·
  [11. Where it lives](#11-where-it-lives)
- Part II: Discussion
  [12. Why waveforms](#12-why-waveforms) ·
  [13. What the analysis misses today](#13-what-the-analysis-misses-today) ·
  [14. The datasheets and Atmel's guidelines](#14-the-datasheets-and-atmels-guidelines) ·
  [15. Margin](#15-margin) ·
  [16. Chip descriptions](#16-chip-descriptions-python-a-language-of-our-own-or-liberty) ·
  [17. Performance](#17-performance) ·
  [18. Order of work](#18-order-of-work) ·
  [19. Open questions](#19-open-questions)

# Part I: Specification

### 1. What the engine does

It takes:

- a netlist, as `Netlist.export()` gives it, with every chip's
  description ([6](#6-chip-descriptions)) and its delays ([5](#5-delays));
- the cases a study gives ([8](#8-cases)).

For each case it computes every net's waveform over the case's window,
evaluates every check ([9](#9-checks)) on those waveforms, and reports
each check's slack, the path that sets it, and what it couldn't check
([10](#10-results)).

It knows nothing of a machine's opcodes, microcode fields or memory
map. The study turns its microcode into cases, and the results into its
own tables (Chibi Heron's `ticks.json`).

**Sound by default.**

- Whatever a case doesn't fix is unknown.
- Any shortcut a study takes is a named exception.
- The report lists both what was assumed and what was never checked.

### 2. Time and the window

- **Times** are integer picoseconds; the reports print nanoseconds.
- **Reference clocks** are the netlist's oscillators (`osc`): a period
  and a first rising edge (its parameters `period_ps` and `phase_ps`),
  and, from its part's data, the range of its duty cycle and its jitter
  (**open**: the data; 50% and none until it's transcribed). Their
  edges are where all time comes from.
- **Every other clock is a net.** Chibi Heron's CLK0 and HCK are a
  22V10's registered outputs, timed like any other output, so the
  engine needs no clock definitions.
- **A case's window** runs from a reference edge, time 0, to a later
  edge that the case names: a number of edges, or a condition ("the
  edge at which CLK0 next rises").
- **Other reference clocks** (Chibi Heron's UCLK, for the UARTs and the
  timer) are asynchronous to the window ([9.7](#97-crossings)).

### 3. Values and waveforms

- **A value** is 0, 1, X (stable but unknown) or Z (no driver on).
- **A waveform** is a net's stable stretches and the transitions between
  them. A transition has a window, [earliest, latest], and a kind:

  | Kind | What the net may do in the window |
  |---|---|
  | rise | go from 0 to 1, once |
  | fall | go from 1 to 0, once |
  | change | change at most once, in a direction not known |
  | glitch | change any number of times, a pulse back to where it was included |

- **At time 0** every net is stable, except for the tails of the cycle
  before ([8](#8-cases)). Its value is the one the case gives, or X.

### 4. Evaluating chips

**Combinatorial outputs.** Over a stretch where the inputs are stable,
the output is its function's value. Where inputs change, the output has
a transition. Its window runs from the earliest input change plus that
arc's minimum to the latest input change plus that arc's maximum. Its
kind follows Atmel's rule for hazards (its *PLD Design Guidelines*,
0790C; [14](#14-the-datasheets-and-atmels-guidelines)), for every chip
whose function is a sum of products: the 22V10s, and the 74 gates and
multiplexers.

1. **Held:** a product term whose inputs are all stable and true holds
   the output at 1. A stable false input in every term holds it at 0.
   No transition.
2. **One input changes** (or several, each in a window of its own, taken
   one at a time). The output's value before and after is computed for
   every value of the unknown inputs:
   - different: one rise or fall (a change, if its direction isn't known);
   - 1 both before and after, with no term holding it: a glitch (a
     static hazard: one term turns off before the next turns on);
   - 0 both before and after: no transition.
3. **Two or more inputs change** in windows that overlap, and the output
   isn't held: a glitch (a race between the inputs).

Two refinements apply to every combinatorial output:

- **An opaque function** (an ALU's F, a memory's data) changes when an
  input changes: a change for one input, a glitch for more.
- **An input the function doesn't depend on**, given the other inputs'
  values, doesn't time the output. An arc with a condition counts only
  while its condition can be true. Known values cut false paths, as in
  today's analysis.

**Registers.**

- At each edge of its clock pin (a clean rise, for a rising-edge
  register), the next state is computed from the inputs' values at the
  edge.
- The output then changes in [edge's earliest + the clock-to-output
  minimum, edge's latest + its maximum]. That's a rise or fall, a change
  if the new value isn't known, or nothing if it is known and equal to
  the old.
- A clock pin whose transition is a change or a glitch leaves the state
  X, and fails its check ([9.4](#94-clean-clocks-and-strobes)). An input
  changing inside its setup and hold window leaves its bit X, and fails
  its check ([9.1](#91-setup-and-hold)).
- An asynchronous clear or preset acts through its own arcs.

**Latches** are transparent while their enable is true: Q follows D
through D→Q, and changes with LE→Q as the enable opens. They hold at
the enable's closing edge, which is checked as a capture
([9.1](#91-setup-and-hold)).

**Three-state outputs.**

- An output drives while its enable function is true. Its enable and
  disable times are arcs like any other.
- A net with no driver on is Z. A pull-up makes Z read as 1 (its rise
  time **open**); otherwise Z reads as X.
- Several drivers on at once: X wherever they may disagree, and a
  handover check ([9.6](#96-bus-handover)) fails.

**Loops.** A combinatorial loop the case's values don't cut is an
error naming its nets, as it is today.

### 5. Delays

- **Per instance and delay name, a minimum and a maximum.** They come
  from `timing.json` for the instance's part number. The netlist's
  `add_delay` (`Instance.extra`) adds to both; today's analysis ignores
  it ([13](#13-what-the-analysis-misses-today)).
- **Where the data has no minimum:** $\min = f \cdot \text{typ}$, where
  $f$ is a parameter of the run (**open**: its value; Atmel's
  guidelines take 0). Every check that depends on such a minimum
  reports the smallest $f$ it passes with, so the choice can be
  revisited without rerunning.
- **Memories:** the minimum of an access is its output hold, tOH. A
  memory's data starts changing tOH after its address does, and is
  valid at tAA.
- **Wires:**
  - a delay, minimum and maximum, per driving pin and receiving pin;
  - today's `pin_extra` (one value per driving pin, the same at every
    receiver) is taken as both;
  - values per receiver, from the placement or the routing (`infra/pcb`),
    are **open**.
- **Load:**
  - datasheet delays are at a test load: 50 pF for most logic;
  - derating by a net's capacitance (its trace, and every pin on it,
    three-state outputs that are off included) is **open**;
  - it needs pin capacitances and a slope per family in the data: the
    22V10's datasheet has curves, and many HC/HCT sheets give figures at
    both 50 and 150 pF.
- **Rise and fall:** each delay has one value for both, the larger of
  tPLH and tPHL, as the data has it now. Separate values (the
  transcriptions' detail rows have them) are **open**.
- **Operating conditions:** a part's maximum holds over its rated
  range. The report gives where all the board's parts' ranges overlap.
  For Chibi Heron that's 0–70 °C at 4.75–5.25 V, set by the -5 22V10s.

### 6. Chip descriptions

`chips.py`'s `T()` describes each chip type: its pins as now, and its
timing as data that the export carries to the engine.

- **`outputs`:** per output pin, an `Out`:
  - its function: an equation in `gals.md`'s notation (`/` not, `·` or
    `&` and, `+` or `|` or, parentheses, 0 and 1) over the chip's pins.
    `None` means an opaque function: an ALU's F, a memory's data.
  - its arcs: `{input pins: delay name}`. Pins are space-separated names,
    or a range such as `A0-A14`. A value can instead be
    `Arc(name, min=other name, when=equation)`: a minimum from another
    delay (a memory's tOH), or a condition the arc needs to be true
    ("CN→F only while M is 0").
  - for a three-state output: `enable`, an equation (it drives while it's
    true), with `on` and `off` arcs.
- **`regs`:** per registered output, a `Reg`:
  - its clock pin and edge;
  - its next state, as an equation, in which the pin's own name stands
    for the present state;
  - its clock-to-output delay;
  - an optional clear and preset, each an equation with its arcs.
- **`latches`:** `Latch(enable, d, arcs)`.
- **`checks`:** from a small set ([9](#9-checks)):
  - `Setup(pins, clock, setup, hold)`;
  - `Width(pin, level, name)`;
  - `Period(pin, name)`;
  - `Recovery(pin, clock, recovery, removal)`;
  - `Strobe(active, stable=, data=, width=)`.

  A setup check needs no condition: the next state's equation says when
  an input matters.
- **Glitch-sensitive pins:**
  - registers' clocks;
  - latches' enables;
  - clears and presets;
  - a strobe's pins;
  - any pin that `sensitive=` names (a UART's RD and WR).
- **Delay names** are looked up per part number in `timing.json`, as now.
  A name the part's data lacks is an error at export.

Three chips as examples:

```python
T("157", "mux157", pins,
  outputs={f"{i}Y": Out(f"/G·(/S·{i}A + S·{i}B)",
                        arcs={f"{i}A {i}B": "A->Y", "S": "S->Y", "G": "G->Y"})
           for i in range(1, 5)})

T("377", "reg377", pins,
  regs={f"Q{i}": Reg("CLK", f"EN·Q{i} + /EN·D{i}", "CLK->Q") for i in range(1, 9)},
  checks=[Setup("D1-D8", "CLK", "setup D", "hold D"),
          Setup("EN", "CLK", "setup EN", "hold EN")])

T("sram", "sram", pins,
  outputs={f"IO{i}": Out(None, arcs={"A0-A14": Arc("tAA", min="tOH"),
                                     "CE": "tACE", "OE": "tOE"},
                         enable="/CE·/OE·WE", off={"CE": "tCHZ", "OE": "tOHZ", "WE": "tWHZ"})
           for i in range(8)},
  checks=[Strobe("/CE·/WE", stable={"A0-A14": ("tAS", "tAW", "tAH")},
                 data={"IO0-IO7": ("tDW", "tDH")}, width="tWP")])
```

The 377's next state says D matters only while EN is low, so D's setup
is checked only then. The chip-level simulator does the same for the
22V10s.

Fixtures and connectors describe what reaches the board. An input with
no description of its timing is asynchronous ([9.7](#97-crossings)).

### 7. The 22V10

A 22V10's description comes from its program: `gal.py`'s equations, as
the chip-level simulator reads them.

- **Outputs:** each output's sum of products, registered (on CLK,
  rising) or combinatorial, inverted or not; its enable; and the
  asynchronous reset (AR).
- **Delays** (the datasheet's names):
  - tPD: an input or a feedback to a combinatorial output;
  - tCO: clock to a registered output;
  - tEA and tER: an output's enable and disable, rather than tPD as
    today;
  - tAP: AR to a registered output;
  - tCF: clock to feedback, inside the chip.
- **Feedback:** a registered output feeds the array from its register
  (tCF). A combinatorial output feeds back from its pin (tPD), as
  `gal.py` and the chip-level simulator have it.
- **Checks:**
  - tS and tH, per input the next state depends on;
  - tW, the clock's high and low times;
  - the clock's period: tWH + tWL with no feedback, and tS + tCF for a
    register that feeds the array;
  - for AR, its width (tAW) and its recovery to CLK (tAR).
- **The synchronous preset** isn't described until `gal.py` uses it.
- **The glitch rule** ([4](#4-evaluating-chips)) applies to the
  combinatorial outputs.
- **The CQZ-20's input transition detection:** its datasheet (0778L)
  gives no extra delay for waking, so the engine assumes none.
- **Data to add:** tEA, tER, tAP, tCF, tW, tAW and tAR for every grade in
  the timing data, and the -10 grade
  ([14](#14-the-datasheets-and-atmels-guidelines)).

### 8. Cases

A case is what a study fixes; everything else is X.

- **Pinned values:** a net's value, with its timing still computed:
  "the control store's outputs read word W once they settle". Today's
  analysis does the same with its constants.
- **The start state:** the values registers on the reference clock take
  at the edge at 0, and the values they had before it. In Chibi Heron:
  - the clock generator at phase F, tick 0, with CLK0 and HCK rising;
  - TASK as the case says, or X.
- **The end:** the edge the window ends at ([2](#2-time-and-the-window)).
- **Branches:**
  - A register on a reference clock that would load X, and that the
    case names as a branch, splits the case: one branch per value, each
    reported on its own. In Chibi Heron: the clock generator's phase and
    END, HOLD, VEXTQ and TCHG.
  - A branch that comes back to a state it was in, with nothing in
    flight, stops there, since the rest repeats.
  - A study sets a limit on branches.
- **Tails:**
  - The engine runs every case once, and finds every net's latest
    transition past its window's end, the worst over all cases.
  - It carries those into every case's start as changes in flight, and
    runs again, until nothing changes (usually two rounds).
  - So the previous cycle's slow paths are seen, without pairing cases.
- **Pairs:** where X before the start is too pessimistic (a bus driver
  the previous word may have left on), a study can give the previous
  word too, as pinned values before 0. The study chooses the pairs; in
  Chibi Heron they would come from the microcode's successors.
- **Exceptions:** each named and with a reason, and each listed in the
  report:
  - a false path: from, to, and under which values;
  - a check the study turns off (for example, a result register that
    loads every cycle but matters only when the result is used).

For Chibi Heron:

- one case per distinct microinstruction, with the fields that don't
  time it X, not 0;
- an access at MAR twice: the RAM and the I/O space;
- LEN and HLEN set to each value in turn; the shortest that passes
  gives `ticks.json`.

### 9. Checks

Every check has a slack, in picoseconds; a negative slack fails.

#### 9.1 Setup and hold

At each capture (a register's clock edge, a latch's closing edge):

- the inputs the next state depends on (given the others' values at the
  edge) mustn't change between the edge's earliest time less the setup
  and its latest time plus the hold;
- the shared part of the clock's path counts once:

$$t^{\max}_{\text{data}} + t_S \le t^{\min}_{\text{clk}} + c, \qquad t^{\min}_{\text{data}} \ge t^{\max}_{\text{clk}} + t_H - c$$

$c$ is the credit for common path pessimism (CPPR). Where the data's
launch and the capture trace back through the same pin at the same
reference edge, $c$ is the spread (maximum less minimum) of that pin's
arrival. Without it, a register launching on an HCK edge into another
capturing on the same edge sees U_CGB's clock-to-output spread, 1–4 ns,
as skew that can't exist.

#### 9.2 Widths and periods

- **Width:** from a transition's latest time to the next opposite
  transition's earliest.
- **Period:** from a transition's latest time to the next one in the same
  direction's earliest.

#### 9.3 Recovery and removal

An asynchronous clear's or preset's release, against the next clock
edge.

#### 9.4 Clean clocks and strobes

A glitch-sensitive pin sees only rises and falls, by
[4](#4-evaluating-chips)'s rule, while it matters:

- always, for clocks, latch enables and asynchronous controls;
- for a strobe's pins, while its other inputs let it act (WE while CE is
  active).

A change or a glitch there fails.

#### 9.5 Strobes

While a strobe is active (from its activating transition's earliest to
its deactivating one's latest):

- its address is stable from tAS before the start, at least tAW before
  the end, and until tAH after the end;
- its data is set up tDW before the end, and held tDH after it;
- the strobe lasts at least its width.

This covers the RAMs' and the register file's writes, the UARTs', the
DAC0832's, the 82C54's and the CF card's, each by its own description.
Reads need nothing extra: they're the data's arrival at whatever
samples it ([9.1](#91-setup-and-hold)), through the device's access
arcs.

#### 9.6 Bus handover

For every net that more than one output can drive, each driver's enable
waveform gives when it may be on (from its earliest turn-on to its latest
turn-off), and when it surely is (from its latest turn-on to its
earliest turn-off).

- Two drivers that may be on at once overlap by no more than a tolerance
  (**open**: 1 ns, as the chip-level simulator's runs allow).
- Nothing samples or strobes a net while no driver is surely on, unless
  a pull-up holds it.
- At the window's start, the previous cycle's drivers come from the
  tails or the pairs ([8](#8-cases)).

#### 9.7 Crossings

- **What counts as one:** a capture of a net that depends on an
  asynchronous source. That's another reference clock's domain, a
  connector's input, a button, or a device on its own clock.
- **What it needs:** to be at a register the netlist marks as a
  synchroniser (`nocheck` today).
- **What the report gives:** every crossing, its synchroniser, and the
  time the synchroniser's output has to settle before the next
  register's setup.
- **No MTBF:** the data has no metastability figures.
- RESET_n's release is a crossing, into every register it clears.

#### 9.8 Coverage

The report lists:

- every check no case evaluated (a register never clocked, a strobe
  never active);
- every chip with no description, or with outputs left untimed;
- every exception.

A study's tests can hold that list.

### 10. Results

- **Per check and case:** the slack, and the path that sets it. The path
  is the chain of transitions back to a reference edge, with each step's
  chip, pins, delay name, minimum and maximum.
- **A study's summary:**
  - the failing checks;
  - the marginal ones: slack under a band the run sets, 2 ns by default,
    reported and not added ([15](#15-margin));
  - the coverage ([9.8](#98-coverage)) and the exceptions;
  - which results rest on an `estimated` value in the timing data, or on
    a minimum from the fraction (with the smallest fraction they pass
    with).
- **A case's waveforms,** as data, and later as a timing diagram for the
  documents ([RFC 0000](0000-rfc-repository-layout.md#figures)).
- **Formats:** JSON for the study (Chibi Heron's `ticks.json` is made
  from it), and text for people.

### 11. Where it lives

- **The engine:** `infra/sta`, the crate `sta`, plain Rust, a member of
  the workspace. Its own Rust tests: each check, the waveform rules,
  small netlists.
- **The bindings:** `heron/bindings/src/py_sta.rs` makes it
  `heron.native.sta.analyse(netlist, cases, options)`. The netlist is
  `Netlist.export()`'s; the cases and options are plain dicts, as the
  chip-level simulator takes its netlist.
- **`chips.py`** gets the descriptions ([6](#6-chip-descriptions)).
- **The export** gives each delay name's minimum and maximum together,
  and each chip's description. A 22V10's equations come from `gal.py`.
  The chip-level simulator's fields stay as they are.
- **The study:** `heron chibi hw sta` runs the new engine; `sta2.py`
  stays alongside until the new one gives the same ticks or the
  differences are explained.
- **`infra/hw/sta.py`** stays for the other studies until each moves. A
  move checks its periods against the old analysis's.

# Part II: Discussion

### 12. Why waveforms

**A classic static timing analysis** (OpenSTA, PrimeTime) builds a
graph of the paths between registers from defined clocks, with
exceptions such as multicycle and false paths written by hand. Chibi
Heron has:

- clocks made by 22V10s;
- paths of 2 to 6 ticks, depending on the microinstruction;
- control values that change in the middle of a cycle: PHW switches the
  register file's address at tick 3.

In a graph analysis each of those would be a generated clock and an
exception per microinstruction. That's what `sta2.py`'s formulas are
today, written by hand.

**The waveform model** is the SCALD Timing Verifier's (McWilliams,
1980), which was built to check the S-1's ECL boards. Values over time,
with windows, handle derived clocks, phases, strobes, glitches, pulse
widths and handovers in one mechanism.

- **Its cost:** a few transitions per net rather than one arrival time.
  Chibi Heron has 662 nets.
- **Today's analysis is half-way there:** values per case and the
  latest arrivals, but one phase at a time, with the phases' times
  written by hand.

### 13. What the analysis misses today

RFC 0047's grade search found a mix that fails at chip level, because
"the analysis misses those paths"
([18](0047-rfc-chibi-heron.md#18-the-board)). `sta2.py` misses paths in
several ways, by design:

- **The clock generator is a fixture** (`m_chibiclk3`), and so are
  U_MEMC's strobes: the 22V10s' equations retyped, with the ticks as
  constants. That's also why U_CGA, U_CGB, U_MEMC and U_LCK stay out of
  the grade search.
- **Context is fixed, not unknown:**
  - TASK, TCHG and DREQ are 0, so no case has a task running;
  - the device 22V10s' outputs never change, but for MD, HOLD and VRD;
  - the 82C54 and the CF card never drive.
- **Requirements are formulas written per machine**
  (`8 * (addr + tAS - TCO) / 4`). A check nobody wrote doesn't exist.
- **Only the slowest delays:** no hold, width, handover or glitch
  checks.
- **`add_delay` is ignored:** `infra/hw/sta.py` reads `delays_for`
  directly, while `export()` applies `Instance.extra`, so the analysis
  and the chip-level simulator disagree wherever a netlist lengthens a
  delay that way (v1b_system's bus does).

Which of these costs U_IRH its 3.4 ns hasn't been traced. The engine's
first acceptance test is to find both of RFC 0047's failures: U_IRH at
-15, and UART 0's select with U_IODEC a CQZ-20.

One more finding from today's analysis: the tightest fixed-tick
requirement, U_MEMC's setup of IOACC, misses by 0.04 ns.

- **The path:** in the high half of an access at MAR, AIO comes from
  MAR at 11.9 ns, through U_MEMC's own combinatorial IOACC at 16.9 ns,
  back into its registers.
- **What it needs:** IOACC there tS (3 ns) before the half's second
  tick: 16.86 ns.
- **Why it passes:** only on the analysis's 0.05 ns tolerance.

The chip-level runs don't flag it, so one of the two is wrong. Settling
that is the new engine's job.

### 14. The datasheets and Atmel's guidelines

From the ATF22V10C's datasheet (Atmel 0735U) and the CZ/CQZ's (0778L):

- **The -7's tCO is 5.5 ns in DIP** (note 2), not the 4.5 ns of the other
  packages. The timing data had 4.5 for the -7PX, a DIP part; this
  branch corrects it, and RFC 0047's grade table with it.
  - With the correction, today's grade search (`grades()`, without its
    chip-level loop) sends U_UPCL, U_UPCM and U_UPCH back to the -5:
    33 at -7, 2 at -15, 7 CQZ-20s (36, 2, 7 before).
  - Neither matches RFC 0047's table (22, 9, 11), which came from the
    search before its latest version (commit 68ec274).
  - The grades wait for the engine, so the table's column stays as it
    is.
- **There's a -10 grade:** tPD 10, tCO 6.5, tS 4.5 ns. The timing data
  doesn't have it yet.
- **No CQZ-20 can be clocked by MCLK.** Its clock must be high and low
  for 10 ns each (tW), against MCLK's half period of 9.93 ns. Its
  frequency without feedback is at most 50.0 MHz, and 45.5 MHz with
  internal feedback, against MCLK's 50.35. The width and period checks
  ([9.2](#92-widths-and-periods)) find that from the data, with no floor
  written by hand.
- **Load and switching:** both datasheets have curves of tPD's and tCO's
  change with the load (to 300 pF) and with the number of outputs
  switching, and pin capacitances: at most 8 pF for the C parts, 10 pF
  for the CQZ. That's the data that load derating ([5](#5-delays)) needs
  for the 22V10s.

Atmel's *PLD Design Guidelines* (0790C) is the source of
[4](#4-evaluating-chips)'s rule, and of more:

- **Hazards.** A glitch can come whenever "the stability of a circuit
  output depends on the change of more than one input". A single input
  can make one through a static hazard, which "an additional product
  term" holding the output removes.
  - `gal.minimise` and `minimise_qm` never produce such terms, so an
    output that needs one has to be written with it, against its
    macrocell's 8 to 16 terms.
  - An extension was considered and left out: several inputs all
    pushing the output the same way. It's sound for an AND-OR array in
    theory, but the guidelines don't cover it.
- **Minimum delays.** Where the datasheet gives none, take zero; and
  assume "a skew between all signals".
- **Clocks.** Not more than one level of logic. Registered outputs are
  their recommended fix for a glitchy signal.
- **Clock edges** at least 0.1 V/ns. That's a matter for signal
  integrity (`bus_si`'s engine could check the clock nets), not for this
  engine.
- **The zero-power parts** wake on input transitions, and may miss edges
  slower than 7200 ns/V.

### 15. Margin

Emily (2026-10-20): reporting the margin is enough. The engine reports
every check's slack, and lists the checks under a band the run sets, but
adds nothing to the delays.

**Against a guard band:**

- the datasheets' maximums already hold over each part's rated
  temperature and voltage;
- on Chibi Heron, a guard band costs ticks. By today's analysis, every
  half whose length the timing sets has at least 3.7 ns before its tick
  edge, so a band of 3.7 ns would cost nothing; 5 ns would make 70
  halves a tick longer. The fixed-tick requirements are tighter: down to
  −0.04 ns ([13](#13-what-the-analysis-misses-today)), which no LEN or
  HLEN fixes.

**What a margin would stand for:** what the model doesn't see.

- a supply below 4.75 V, the limit of the -5s' and -7s' rating, on a
  board whose 22V10s alone draw 4.4 A typical, 6.8 A at most;
- many outputs switching at once;
- ringing on long nets, crosstalk, sockets;
- new-old-stock 74F181s and 74F182s of unknown origin;
- mistakes and estimates in the timing data, like the -7's tCO.

The marginal list is where to look for those.

### 16. Chip descriptions: Python, a language of our own, or Liberty

Emily chose option 2 for now (2026-10-20).

1. **A text format of our own.** It's compact. But it needs ranges,
   sections, conditions, and before long loops and parameters, which
   makes it a small language with its own parser and errors. Python
   would end up parsing it anyway, since Rust only takes JSON.
2. **Python, as `chips.py` is now, with equations as strings** in the
   notation `gals.md` prints. Python already has the loops. The netlist
   language and `gal.py` are embedded in Python already. One small
   parser, in Python.
3. **Liberty**, the industry's cell-library format. Its syntax is
   overkill: tables over slew and load, where the data has single
   numbers. But its vocabulary is well tested, and
   [6](#6-chip-descriptions) borrows it:
   - arcs positive-, negative- or non-unate;
   - combinational, edge, enable and disable arcs;
   - setup, hold, recovery, removal and pulse-width checks;
   - conditions on arcs.

Later, the chip-level simulator could evaluate the simple chips from the
same descriptions, so their logic would be written once. That's not part
of this RFC.

### 17. Performance

- **Today:** `heron chibi hw sta` takes 6.4 s on four cores for its 626
  cases, and the grade search runs the analysis again for each 22V10 it
  tries.
- **The aim:** the whole of Chibi Heron's analysis in under a second on
  four cores.
- **Re-timing:** a case's values don't depend on the delays. So the
  engine can keep each case's live arcs and re-time them with other
  delays (another grade, another fraction) in milliseconds. That's what
  the grade search needs.

### 18. Order of work

1. This RFC.
2. **The engine's core:**
   - waveforms and the chips' evaluation;
   - setup and hold with CPPR, widths and periods;
   - descriptions of the chips Chibi Heron uses;
   - Rust tests.
3. **Chibi Heron with its real clock generator:**
   - the cases, branches and tails;
   - `ticks.json` the same as `sta2.py`'s, or every difference explained;
   - RFC 0047's two failures found.
4. **The other checks:** strobes, glitches, handovers, crossings, reset,
   coverage.
5. **The other data:** wire delays per receiver, load derating, rise and
   fall, as the data comes.
6. **Then:** the grade search, and the other studies.

### 19. Open questions

1. **The minimum delay's fraction** of the typical, where the data has no
   minimum: configurable, its value to be reconsidered (Emily).
2. **The glitch rule:** Atmel's, as in [4](#4-evaluating-chips), is
   proposed. The extension in [14](#14-the-datasheets-and-atmels-guidelines)
   is left out.
3. **The handover tolerance:** 1 ns, as the chip-level simulator's runs
   allow?
4. **Wire delays per receiver and load derating:** where their data comes
   from.
5. **The oscillators' duty cycle and jitter.**
6. **Pull-up rise times** (RESET_n).
7. **Grades, once the engine is done:**
   - the objective (the -5s first, being PLCC-only; then current?);
   - the candidates (the -10);
   - whether a faster part in any socket must stay safe, which means
     checking hold with the fastest grade's minimums: the -5 guarantees
     1 ns of tPD, the others 3.
