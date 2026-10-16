---
status: active
depends-on: [v2_isa, v2_hw]
reports: [27]
---

# The I/O processor

The I/O processor of [RFC 0027](../../reports/0027-rfc-io-coprocessor.md),
step 1 of its "simulate first" (16): a model of the IOP at
microinstruction level, its microcode, and the Forth the microcode
interprets, on a system with a draft 2 CPU card that the IOP boots. An
experiment: RFC 0027 isn't settled, and where this study needed something
it leaves open, it chose (below).

- **The simulator** (`sim/`, Rust, `heron.native.iop`): RFC 0027's core
  clocked by the bus clock, a microinstruction at a time, with its
  pipeline and delay slot, HOLD, the SRAM as registers and memory, the
  devices on T, the system bus master side with overlapped transfers, the
  slave side (the shared RAM, the doorbells, the I/O bus's window), the
  I/O bus with its timing table, and the card's devices: the console UART
  and the 82C54 from `infra/devices`, the image flash (two SST39SF040
  with their command sequences) and the ports.
- **The system:** the IOP's card and a CPU card on RFC 0037's map, the
  CPU being draft 2 at instruction level (`studies/v2_isa`) behind a card
  with RFC 0027's control register, interrupt request register, slave port
  and control store window. The CPU starts with RUN off; the IOP loads it
  and starts it.
- **The microcode** (`ucode/`, about 1,000 microinstructions): reset (the
  timing table, the SRAM's self test, the dictionary out of the image
  flash), the inner interpreter, 76 primitives, the task switch, and the
  native layer that the tick and the doorbells call. The block primitives
  (`(flash>bus)`, `(move)`, `(fill)`, `(sr>bus)`, `(bus>sr)`) are native:
  any length, in slices of 16 transfers, a session on the bus each, with
  a look at attention between slices.
- **The Forth** (`forth/`, about 5,000 cells): the console *is* its
  interpreter. A kernel with the compiler, the monitor (examine, deposit,
  dump anywhere on the system bus), block moves and fills, the image flash
  and `save`, tasks, and booting the CPU: records played from the image
  flash into the CPU card, then RESET and RUN.

```sh
heron iop console                # the Forth in this terminal (Ctrl-] quits)
heron iop run '2 3 + .' ': sq dup * ; 7 sq .'
heron iop boot                   # power up, boot-cpu: the CPU's hello through the window
heron iop boot --wcs             # with draft 2's control store, checked (v2_hw's microcode: a minute to build, then cached)
heron iop build                  # build/iop: ucode.bin, ucode.lst, flash.bin
heron iop ucode [--list]         # the microcode's size by primitive, and its listing
heron iop words                  # the dictionary
heron iop bench [--wcs]          # what RFC 0027 estimates, measured (below)
heron test iop                   # the unit tests
```

At the console, for example:

```forth
boot-cpu cpu-wait          \ load and start the CPU, wait for it to halt
$1000. e                   \ examine the CPU's RAM at 0x1000, through its slave port
$BEEF $1000. d             \ deposit
$0. 16 dump                \ the CPU's RAM from 0
0 $10000. 4096 bus-fill    \ halfwords on the bus; bus-move, sr>bus, bus>sr likewise
variable n : counter begin 1 n +! pause again ;
' counter 3 spawn          \ a second task, in bank 3
: hi ." hello" ; save      \ into the image flash, for the next cold start
```

| File | What's in it |
|---|---|
| `sim/` | The simulator crate: `micro.rs` (the microinstruction, the 74181), `iop.rs` (the core, the T bus, the system bus master and slave sides), `iobus.rs` (the I/O bus and the card's devices), `flash.rs` (the image flash), `system.rs` (the CPU card and the two in turn) |
| `layout.py` | What the microcode, the Forth and the tools share: the SRAM's map, the bank's registers, the control register, the timing table, the image flash's header |
| `uasm.py` | The microassembler: RFC 0027's notation, one line a microinstruction |
| `ucode/core.uc`, `ucode/prims.uc` | The microcode |
| `meta.py` | The metacompiler: the Forth source into the dictionary image |
| `forth/kernel.fs`, `forth/monitor.fs` | The Forth |
| `build.py` | The image flash: the dictionary, and the CPU's images as records |
| `sw/hello.s`, `sw/irq.s` | CPU programs: the default boot program, and one that waits for an interrupt from the IOP |
| `run.py`, `cli.py` | Running it; the command line |
| `bench.py` | The measurements |

## The machine, as this study has it

RFC 0027 gives the fields and widths of the microinstruction; the rest of
this section is what the study chose to make it run. These are for the
RFC, not decisions.

- **The microinstruction's layout** (`sim/src/micro.rs`): K 0-15, REG
  16-21, RS 22-23, ALU 24-29, WB 30, LD 31-33, BUS 34-35, SEG 36, SZ
  37-38, T 39-41, SEQ 42-43, COND 44-46, TASK 47. M is stored inverted, so
  that the all-zero ALU field is HOLD (M = 1, S = 0000, carry in 0, one of
  the codes that repeat a logic function) and the all-zero
  microinstruction does nothing at all.
- **WB writes the SRAM at its address:** X when RS is memory, the register
  {BANK, REG} otherwise, so `t0 <- #5` and `t0 <- swap` write a register
  (in the second case one whose number REG can be for the swap register
  too).
- **CTRL is an addressable latch** (a 74x259 for the 74ABT273): LD CTRL
  sets bit R[2:0] to R[3], so firmware can change one bit without knowing
  the others. Its bits: SESSION, WORK, RESET (the system bus's), IORESET.
- **LC** is one 74F161: COND "LC not done" is LC != 15, and counts. Loading
  it with -n gives n passes, 1 to 16.
- **Device 7 on T reads all ones** (pull-ups on T, a resistor network).
  Without it a microinstruction can't test AC for zero and branch: the
  test needs all ones as the ALU's A input, `(A & AC) - 1`, and K is the
  branch target. The comparisons and `0branch` use it.
- **BA interlocks:** a microinstruction that reads BA before the last
  read's data is there waits (RFC 0027 says only that the next transfer
  waits at E1).
- **An I/O bus access** starts when the last one's hold has ended, and
  stretches its microinstruction to its strobe's end, (1 + SETUP) +
  STROBE clocks from the timing table, when that is more than 2 ("stalls
  the core until its strobe ends", RFC 0027, 3.5). The hold overlaps what
  follows, so the I/O side is taken to keep A0-A7, WRITE and the data
  through it.
- **REQ and GNT:** GNT comes 4 clocks after SESSION rises (an idle bus;
  the CPU's own use of the bus isn't modelled). A transfer without
  SESSION is a microcode error here.
- **The event ports** (device 3): register 0 the INT lines; 1 ATN0-3 and
  the tick in bit 15, written to clear the tick; 2 the doorbells, written
  to clear doorbell X[3:0]. **The page registers** (device 4): 0 the
  shared RAM's (6 bits), 1 the image flash's.
- **The bank's registers** (`layout.py`): REG names a register and a
  device on T at once, so a microinstruction that moves data to or from a
  device while it steps a register needs that register in the device's
  group of eight. So the scratch registers are in the groups of devices
  whose low bits are free (i0-i4 with the I/O bus, t0-t7 with the shared
  RAM, s0-s7 with the swap register), and RFC 0027's ip, sp and rp at
  0-2; tos, resume, link, wait, me and up at 32-37; user variables from 40.
- **`nest` reads the body from [ip]**, as RFC 0027's does, since X can't
  be read back. So `execute` runs a thread of two cells, the xt and
  `exit`, that it writes into the task's registers 38-39.
- **The native layer** runs in whatever bank is current, at a primitive's
  end (`branch`, `0branch`, `(loop)`, `(+loop)`) or while `pause` skips
  waiting tasks, with registers 24-31 as its scratch. At the tick it
  routes the enabled INT lines to the tasks waiting for them (an event
  table of the address of each owner's `wait`) and masks them until they
  wait again; doorbells are kept in a cell for the Forth for now.
- **The image flash's layout:** a header page, the dictionary from page 1,
  the CPU's images from halfword 0x10000 (`build.py`), as records of
  {bus address, n, n halfwords}.
- **The polling tick's fast path:** at a primitive's end, a tick with no
  INT line up is cleared and Forth goes on, 5 microcycles, without saving
  AC or entering the native layer. The INT lines are looked at only when
  one is up.
- **The CPU card's registers** at `0x7000_0000` (`sim/src/system.rs`):
  board information at +0, control at +0x1000 (RUN, RESET, STEP, NMI),
  interrupt requests at +0x2000 (set, and clear at +4), and the control
  store's ten lanes at +0x40_0000.

## Measurements

`heron iop bench --wcs`, against RFC 0027's estimates:

| | Measured | RFC 0027 |
|---|---:|---|
| SRAM self test (64K cells, two patterns) | 102.2 ms | - |
| dictionary out of the flash (5038 cells, 20 pages) | 3.4 ms | 32K cells in ~30 ms |
| power-up to the banner | 106.6 ms | - |
| Forth words a second, in a loop of `i inc dup + over swap - drop` | 1,286,449 | about 1,000,000 |
| microcycles a Forth word, there | 6.48 | NEXT 3 (2 with its delay slot used), most primitives 5-7 |
| the tick's share of the IOP while Forth computes | 7.2% | 5-10% (0.5-1 us a tick) |
| Forth words a second, `words` (the console, `emit` waiting on the UART) | 1,259,063 | - |
| fill, the CPU's RAM, 8192 halfwords | 6.6 MB/s | 9.9 MB/s |
| copy, the CPU's RAM to its RAM, 8192 halfwords | 3.6 MB/s | 4.9 MB/s |
| copy, the shared RAM to the CPU's RAM, 8192 halfwords | 5.5 MB/s | 7.6 MB/s |
| copy, the CPU's RAM to the shared RAM, 8192 halfwords | 4.7 MB/s | 7.6 MB/s |
| booting the CPU: draft 2's control store, its decode table and the program | 69.5 ms (3.5 MB/s) | about 35 ms for the 1b's (130K halfwords at 7.6 MB/s) |
| microcode | 1008 microinstructions, 76 primitives | 1-2K; the interpreter and primitives 500-1,000 |
| the Forth's dictionary | 5038 cells | up to 32K |

What the differences come from, so far:

- **The copies** run at the loop's rate in each slice (fill 3 clocks a
  halfword, two writes a microinstruction pair; copies 4-6), but a slice
  costs about 10 microinstructions more than RFC 0027's 6 clocks of
  re-arbitration: working out the next slice, the session off and on, the
  look at attention. The RFC's figures leave that out.
- **Into the shared RAM** a halfword waits a clock for BA: the CPU card's
  slave port takes 2 data clocks, so the read's data comes a clock after
  the next microinstruction's E1.
- **Out of the image flash** a halfword is 5 clocks, not 4: the
  SST39SF040-70 needs a 2-clock strobe (0/2/0), so the read stretches its
  microinstruction to 3. A 45 ns part (0/1/0) would make it 4.
- **The Forth** is faster than the RFC's estimate in ordinary code; the
  slow words are the ones with microcode loops (`um*`, `um/mod`, `rshift`
  and so `2/`: 80-160 microcycles).
- **The tick** was 20% of the IOP before its fast path: every tick through
  the native layer, AC saved and the INT lines masked, is about 17
  microcycles in 83.

## Not yet

- **Stage 2-3 of RFC 0027:** the rings and their windows, copies and
  fills as native jobs that requests start, routing events to the CPUs
  (slow and batched, fast and vectored). What's here is the mechanism:
  `cpu-int` sets a level in the CPU card's request register, and the
  doorbells reach the Forth.
- **Devices:** the I/O cards (a CF card is in `infra/devices`), the
  serial loader, the time of day and the front panel; the stuck-transfer
  counter; the 32-bit paths; change detection on the INT lines.
- **Fen on this system:** RFC 0037 (28) moves Fen's devices to the IOP's
  map, which changes Fen's drivers. Fen still runs on its own board.

Where the CPU's side doesn't match this system yet, for the RFCs rather
than this study: draft 2's CPU card in `studies/v2_hw` (`iop.py`, after
RFC 0031, 6) has its slave port in slot 0 by RFC 0014's slots, with the
control register at `0x600_0000` and the control store at `0x400_0000`
in the slot. Here the card is RFC 0037's region 0, its registers at
`0x7000_0000` with the control store's window among them, ten lanes:
draft 2's 144-bit microinstruction in nine, the decode table in one.
