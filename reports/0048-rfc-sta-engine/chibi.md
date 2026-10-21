# RFC 0048: Chibi Heron on the engine

What the engine (`infra/sta`) finds on Chibi Heron's netlist, through
`studies/chibi/sta3.py` (`heron chibi hw sta`): the results behind steps
3 and 4 of [RFC 0048's order of work](../0048-rfc-sta-engine.md#18-order-of-work).
Every distinct microinstruction is a case, as
[8](../0048-rfc-sta-engine.md#8-cases) says, with the clock generator's
22V10s running their own equations. The delays are the datasheets'
minimums and maximums, with a fraction of 0.3 of typical where a datasheet
gives no minimum.

## Summary

- **The ticks are `sta2.py`'s.** For all 626 words, both halves, the
  shortest lengths at which no check a length can fix fails are exactly
  `ticks.json`'s: low halves 2 ticks (391 words) and 3 (235), high
  halves 2 (218) and 3 (123). Neither the variants below nor the cycle
  before's tails change any.
- **RFC 0047's U_IRH failure is found.** With `U_IRH` a -15, its setup
  on the fetch's parcel (MD8–MD15 from the RAM) fails by 0.3 ns in 9
  words. The chip-level run says 3.4 ns, on the same path.
- **RFC 0047's UART 0 failure is very likely found** too, as a mix of
  grades. Its path goes through the video's address driver `U_VV`
  letting go of the address bus at phase F's end; a CQZ-20 there takes
  20 ns. With today's grade search's mix and `U_IODEC` a CQZ-20, UART
  0's select meets ADS by 1.1 ns. With `U_SYS` a -15 as well, it misses
  by 6.4 ns: the chip-level run's 7 ns, though its mix came from an
  older search that isn't at hand.
- **No length fixes 791 checks.** Most are holds at the halves' ends, a
  few nanoseconds short, between the clock generator's outputs on one
  edge. Of the new checks:
  - bus handovers: the D bus at the low half's start, the RAM's output
    enable as the phase changes, a task's change;
  - interrupts sampled with no synchroniser;
  - the CF card's strobes at PIO 0.
- **It takes 210 s** for 7402 cases on four cores: the search, the
  variants and the tails, the peak 4.8 GB. The aim is under a second
  ([17](../0048-rfc-sta-engine.md#17-performance)).

## The cases

Beyond each word's own case, at its word's lengths:

- **An access to the I/O space at each device** (13 of them), its
  address pinned:
  - the fast devices: the UARTs, the interrupt controller, the video's
    registers, the PS/2 ports, the boot flash;
  - the slow ones, by A6–A4, with U_SLOW's wait states and HOLD: the
    timer, the palette, the sample latch, CFFAST, and the CF card's two
    blocks at PIO mode 0. Not at PIO 4: the card's data has PIO 0's
    figures.

  The address is pinned from phase F on, so a word that loads MAR in
  its low half and accesses the I/O space in its high half changes it at
  the load, which these cases don't time. That's the path of
  [13](../0048-rfc-sta-engine.md#13-what-the-analysis-misses-today)'s
  tightest fixed-tick requirement (AIO from MAR into U_MEMC's IOACC), so
  its slack is open again. Before pinned nets kept still (below), the
  I/O case saw the same path at U_SLOW, SLOWCS from MAR's load through
  `U_IODEC`, at -0.04 ns, `sta2.py`'s figure. With AIO left free the
  cases branch past the limit.
- **A task:** running (TASK and TASKP 1) in the 90 words the tasks run;
  starting at their two entries; and ending, so with TCHG (phase F a
  tick longer), before every other word.
- **The cycle before's tails:** every case's changes still in flight
  past its end, the worst per net, at every case's start. Two rounds
  settle them: 86 nets, the latest the CF card's data, 71.5 ns into the
  next cycle. They make two checks worse, both of them overlaps at the
  window's start that pairs would settle
  ([below](#what-the-cycle-before-would-settle)).

## The ticks

The search runs every word at the longest lengths first (a low half of
4 ticks, a high half of 3). What fails there, no length fixes; a shorter length passes if
nothing a length can fix (setup, strobe, width, period, float) fails
worse than there. The low half is searched with the high half at its
longest, then the high half. The variants are checked at their words'
lengths, not searched: an access to the I/O space has its ticks fixed.

On the way there the engine needed several refinements, now in the
RFC's text. Each was a false failure that made some word longer than
`sta2.py`'s:

- **Sensitization is exact.** An input times a register only if its next
  state depends on it, given the other inputs' values. F_Z·Z16 + F_Z
  doesn't depend on Z16.
- **Narrowing drops covered terms.** An input's change counts only in
  the stretches where no other term covers it.
- **Held registers don't change.** A register whose state isn't known but
  whose next state is its state (U_KBD's KDATA, holding while IOWR_n is
  high) has no transition at its clock. Before this, every device
  register changed at every edge.
- **Parts per stretch, and both checks.** A transition's parts by
  reference edge keep their gaps. A change that may overlap the edge is
  late data only if it can start before the edge's earliest time. Each
  pin's setup and hold are checks of their own; before this, a failing
  hold hid a failing setup, and 14 high halves came out a tick short.
- **A driver letting go** changes a bus only if another driver is surely
  on. One that may be on would be a contention, which is the handover
  check's.
- **A pinned net doesn't move.** Once a pinned net has its value, a rise,
  fall or change starts and ends there, so it isn't one; only a glitch
  may pulse. Before this, MAR's registers, pinned to a device's address,
  reloading it at every HCK edge, glitched every select decoded from
  them.

Two choices of the first results changed and the ticks didn't:

- CPPR now credits a shared path only at one reference edge, as
  [9.1](../0048-rfc-sta-engine.md#91-setup-and-hold) says (the first
  results credited it across edges too);
- the one-way race rule (inputs all moving their literals one way change
  a sum of products once at most) is an option, off, since Atmel's
  guidelines don't have it
  ([14](../0048-rfc-sta-engine.md#14-the-datasheets-and-atmels-guidelines)).

## What no length fixes

Counted as (chip, pin) checks over every case, worst first. The paths
are in `heron chibi hw sta`'s report.

### Holds at the halves' ends

Of the 512 (chip, pin) holds that fail, those at the halves' ends are
1 to 6 ns short. A typical one:

- **The data:** U_FLG's inputs from the next word. CLK0 is from U_CGB,
  at least 1 ns after MCLK. µPC (`U_UPCL`) adds at least 1 ns, and the
  flash's output may follow its address at once: its tOH is 0. So the
  next word may reach U_FLG 2 ns after the edge.
- **The clock:** HCK, also from U_CGB, at most 4 ns, then through
  `U_HCKB` (a 74ABT541, at most 3.9 ns). It may reach U_FLG 7.9 ns after
  the edge.

So the hold is 5.9 ns short. The same shape holds for MAR, PC, the Y
registers, IRH, SYS, the register file's address GALs, the L latches
and µPC itself: data launched on an edge by the clock generator, or by
a register on MCLK, and captured on the same edge by a clock through
the 541s.

These minimums are the datasheets' own (the -5 22V10's tCO and tPD,
1 ns; the 541's, 1 ns), so the fraction doesn't change them: at a
fraction of 1.0 the worst is still -11 ns. Taking U_CGB's outputs on
one edge to track within a skew of 0 to 1 ns (its datasheet gives no
output skew) clears only 44 to 64 of the 387 the first results had. Most
of each race is the clock buffer's delay against the data's short
minimum.

**Open (Emily):** whether these are the design's, to fix with a
later-launching data path or an earlier capture, or the model's, to
take with a credit for one chip's outputs on one edge or minimums from
measurement. `sta2.py` checked no holds.

### Writes

- **The I/O writes:**
  - the data hold at `U_PB` (-11 ns), `U_LCMP` (-7.8) and UART 0 and 1
    (-6.0);
  - the write ends as LASTH ends the half;
  - RAMOE_n turns the RAM's outputs on onto MD (its tOE minimum 0) on
    the same edge;
  - the devices' strobes come through `U_IODEC`, up to 5 ns later.
- **The register file**, at phase F's end:
  - its address and data are held 1 to 2 ns too little after WE rises;
  - RFWH_n rises and PHW falls on the same edge (6), and PHW switches
    the address from the write's to the read's;
  - CE_HI_n turns on for the read through `U_RFW` at least 1 ns after
    PHW, while WE may still be low until 63.6 ns: a write half that
    shouldn't be written may see a pulse of up to 2 ns ("strobe may
    pulse").
- **The RAMs:** the address and data hold after WE (-1.0 ns), the same
  shape.

### Bus handovers

121 (chip, net) checks fail, on 31 chips; the tolerance is 1 ns.

- **The D bus at the low half's start**, in every case without a
  task's change:
  - the drivers (the register file, the X transceivers, RB, FWB, the
    immediates, PC, MAR) have enables decoded from the control store's
    word and opened as PHW falls (60.6 to 63.6 ns);
  - the control store's outputs settle at 60.6 ns (its tACC of 55 ns
    after µPC's address), and the decodes up to 5 ns later;
  - so an enable may glitch on as PHW opens it: 8 to 18 ns of overlap
    (-17.4 ns between the register file's halves, -15.9 against the
    transceivers);
  - a task's change makes phase F a tick longer, and then none fails.
- **The RAM's output enable as the phase changes** (-22 ns): RAMOE_n
  takes VRD, the video's read, which U_VQ decodes from PH0 and PH1. From
  L to H both change, so VRD may pulse (Atmel's rule), and the RAM's
  outputs with it. That fails against the other row (the rows' enables
  move with the address bus), the transceivers, and the device being
  read.
- **The slow devices' float:** the 82C54 lets go of MD up to 65 ns after
  its read ends (tDF), and its read ends with the half. So a timer read
  overlaps the next cycle's phase F, in which the video may read the RAM
  (-5.4 ns).
- **A task's change:** µPC's high bits (`U_UPCM`, `U_UPCH`) and `U_TOP`
  hand UPC7–UPC12 over in up to 7.8 ns (-6.8), and `U_UPCL` and
  `U_TASK` UPC0–UPC6 (-5.6). TASKD, one 22V10 delay, is all that
  separates them, and its minimum is 1 ns against the others' maximums.

### Nets no driver holds

Where a net is sampled while no driver is surely on, it keeps its value
on its capacitance; the check fails all the same
([9.6](../0048-rfc-sta-engine.md#96-bus-handover)). At CLK0, the cycle's
end, µPC's dispatch (`U_UPCL`, `U_UPCM`), IRH and the flags take MD and
D up to 3 ns after the RAM may have let go: LASTH turns its output
enable off as the half ends.

### Crossings

- **Interrupts:** `U_SYS` samples IRQ, the sources' OR, into IRQP with
  no synchroniser. The sources are the button's latch, the UARTs' and
  the timer's outputs, all asynchronous.
- **Status reads:** a read of the interrupt controller's status takes
  the raw sources onto D, into the L latches and the Y registers. That
  generalises the first results' SREQ race (below).
- **The synchronisers** (`U_KBD`, `U_MOUSE`, both `nocheck`) give their
  outputs 12.9 to 14.4 ns to settle before the next register's setup.

### The CF card at PIO 0

- **The write strobe** lasts at least 141 ns, against t2's 290 ns for an
  8-bit register (165 ns for 16-bit data). U_SLOW gives it 9 ticks
  (179 ns), and `U_CFA`, a 74HCT541 (4.5 to 35 ns), takes up to 30 ns of
  that in skew.
- **The address and CS** change with the read strobe at the half's end,
  through the same buffer, so they're held 34 to 56 ns less than t9
  (20 ns) after it.

### The timer's reads

In a 9-tick access the 82C54's data reaches the flags through the ALU
2.4 ns too late (`U_FLG`, 1 to 3 words). No LEN changes it; U_SLOW's
count for the timer does.

### Phase F's VEXT

`U_CGA` samples VEXT at phase F's first tick. VEXT is 1.1 ns late if the
cycle before ended an I/O write:
- IOWR_n's rise clocks `U_VC`'s DEN (4 ns);
- FETCH_ON follows it combinatorially in `U_VF` (5 ns);
- VEXT follows FETCH_ON in `U_VQ` (5 ns).

Only a write to the video controller changes DEN.

### Status reads against SREQ

SREQ (`U_LCK`, from the timer's TS) may change at any master clock
edge. A read of the mouse port, which returns it on MD2, may then see it
change up to two ticks before the half ends: too late for the carry
chain into the flags.
- U_FLG's Z and N miss setup by 33.5 ns.
- The Y registers miss it by 5.0 ns.

The value read is either, as it may be for any status bit. But the
flags may disagree with it.

### What the cycle before would settle

- **Glitches at edge 0:** the device write strobes (`U_LCMP`'s, `U_PB`'s
  and `U_PCM`'s clocks) may glitch. IOWR_n's rise, the end of an I/O
  write in the cycle before, races MAR's load at the same edge through
  `U_IODEC`. That needs a word that writes to the I/O space and loads
  MAR at once.
- **The CF card's buffers:** the card's data is still in flight at the
  start (its tails), while `U_CFD` may still be on from the cycle
  before (-8.9 ns). Its direction would keep them apart, but the start
  state doesn't know it.
- **Overlaps at the window's start** that can't be timed, the drivers'
  enables not known: the results list them as unresolved.

The start state allows any word before. Pairs
([8](../0048-rfc-sta-engine.md#8-cases)), from the microcode's
successors, would decide these.

## Coverage

- **241 checks**, 167 evaluated in some case.
- **The 40 in none,** the video's chips aside:
  - every recovery: the cases hold RESET_n high, and a reset case is
    open;
  - the latches' and some registers' periods and widths, whose clocks
    pulse once a cycle;
  - the sample latch's setup and width, which no case's write reaches.
- **No description:** `U_DAC` (the palette).
- **No data:** `U_PB`'s recovery and clear width.
- **RESET_n's release** (`U_POR`) reaches the clears of 17 chips: the
  crossing a reset case would time.
- **The exceptions:** one, U_ALUC's HC where the high half doesn't take
  the low half's carry (6732 checks in 2024 cases).

## Not yet

- **Cases:**
  - a case for the video's own phase (its chips' checks are skipped);
  - a reset case;
  - an I/O access whose address MAR loads in the same cycle;
  - pairs, from the microcode's successors;
  - the CF card at PIO 4, with its figures.
- **Data:** wire delays, load derating, the oscillators' duty and
  jitter.
- **Then:** the grade search, which the UART 0 path above says must
  run the engine itself.
