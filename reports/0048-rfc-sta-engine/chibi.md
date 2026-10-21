# RFC 0048: Chibi Heron on the engine, the first results

What the engine (`infra/sta`) finds on Chibi Heron's netlist, through
`studies/chibi/sta3.py` (`heron chibi hw sta`): the results behind step 3
of [RFC 0048's order of work](../0048-rfc-sta-engine.md#18-order-of-work).
Every distinct microinstruction is a case, as
[8](../0048-rfc-sta-engine.md#8-cases) says, with the clock generator's
22V10s running their own equations. The delays are the datasheets'
minimums and maximums, with a fraction of 0.3 of typical where a datasheet
gives no minimum.

## Summary

- **The ticks are `sta2.py`'s.** For all 626 words, both halves, the
  shortest lengths at which no check a length can fix fails are exactly
  `ticks.json`'s: low halves 2 ticks (391 words) and 3 (235), high
  halves 2 (218) and 3 (123).
- **RFC 0047's U_IRH failure is found.** With `U_IRH` a -15, its setup
  on the fetch's parcel (MD8–MD15 from the RAM) fails by 0.3 ns in 9
  words. The chip-level run says 3.4 ns, on the same path.
- **RFC 0047's UART 0 failure isn't.** With `U_IODEC` a CQZ-20, UART 0's
  select still meets ADS's rise by about 25 ns in every case. The
  chip-level run sees it 7 ns late, so it must come from a cycle the
  cases don't have yet: a task's access, TCHG, or a slow access (HOLD).
- **No length fixes 417 checks.** Most are holds at the halves' ends, a
  few nanoseconds short, between the clock generator's outputs on one
  edge. The rest:
  - the I/O writes' data holds;
  - the register file's write at phase F's end;
  - VEXT's setup in phase F after a write to the video controller;
  - status reads that race SREQ;
  - glitches that need the previous cycle's tails.
- **It takes 84 s** for the search's 2888 cases on four cores. The aim
  is under a second ([17](../0048-rfc-sta-engine.md#17-performance)).

## The ticks

The search runs every word at the longest lengths first (LEN and HLEN at
3). What fails there, no length fixes; a shorter length passes if
nothing a length can fix (setup, strobe, width, period) fails worse than
there. The low half is searched with the high half at its longest, then
the high half. The accesses to the I/O space are checked at their
words' lengths, not searched: their 6 ticks are fixed.

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
- **One-way races are clean.** Inputs that all move their literals the
  same way change a sum of products once at most (Atmel's rule calls
  any race a glitch).
- **A driver letting go** changes a bus only if another driver is surely
  on. One that may be on (every device, in an I/O case with the address
  unknown) would be a contention, which is the handover check's.

## What no length fixes

Counted as (chip, pin) checks over every case, worst first. The paths
are in `heron chibi hw sta`'s report.

### Holds at the halves' ends

Of the 387 (chip, pin) holds that fail, those at the halves' ends are
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
output skew) clears only 44 to 64 of the 387. Most of each race is the clock
buffer's delay against the data's short minimum.

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

### Glitches that need the cycle before

At edge 0 the device write strobes (`U_LCMP`'s, `U_PB`'s and `U_PCM`'s
clocks) may glitch. IOWR_n's rise, the end of an I/O write in the cycle
before, races MAR's load at the same edge through `U_IODEC`. That needs
a word that writes to the I/O space and loads MAR at once. The start
state allows any word before; the previous cycle's tails and pairs
([8](../0048-rfc-sta-engine.md#8-cases)) would decide it.

## Not yet

- **Checks:**
  - the handover checks;
  - crossings;
  - recovery and removal;
  - coverage.
- **Cases:**
  - a case for the video's own phase (its chips' checks are skipped);
  - cases with a task (TCHG), and slow accesses (HOLD);
  - the tails and pairs.
- **Delays:** wire delays and load derating.
- **Then:** the grade search.
