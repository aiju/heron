---
status: active
depends-on: [v2_isa, v2_hw]
reports: [27]
---

# The I/O processor

The I/O processor of [RFC 0027](../../reports/0027-rfc-io-coprocessor.md),
its "simulate first" (16), steps 1-3: a model of the IOP at
microinstruction level, its microcode, and the Forth the microcode
interprets, on a system with a draft 2 CPU card that the IOP boots; then
the native jobs, the rings with their requests, windows and completions,
events and interrupts to the CPUs, I/O cards behind them, and the
measurements. An experiment: RFC 0027 isn't settled, and where this study
needed something it leaves open, it chose (below).

- **The simulator** (`sim/`, Rust, `heron.native.iop`): RFC 0027's core
  clocked by the bus clock, a microinstruction at a time, with its
  pipeline and delay slot, HOLD, the SRAM as registers and memory, the
  devices on T, the system bus master side with overlapped transfers, the
  slave side (the shared RAM, the doorbells, the I/O bus's window), the
  I/O bus with its timing table, and the card's devices: the console UART
  and the 82C54 from `infra/devices`, the image flash (two SST39SF040
  with their command sequences) and the ports. I/O cards for the slots: a
  CompactFlash card, two serial lines, and a GPIO card whose INT a test
  can raise.
- **The system:** the IOP's card and a CPU card on RFC 0037's map, the
  CPU being draft 2 at instruction level (`studies/v2_isa`) behind a card
  with RFC 0027's control register, interrupt request register, slave port
  and control store window. The CPU starts with RUN off; the IOP loads it
  and starts it.
- **The microcode** (`ucode/`, about 2,100 microinstructions): reset (the
  timing table, the SRAM's self test, the dictionary out of the image
  flash), the inner interpreter, 76 primitives and the task switch
  (`core.uc`, `prims.uc`); the native layer, which runs the tick, the
  doorbells and the native jobs; and the jobs themselves (`jobs.uc`): the
  movers (copies, fills and blocks between the bus, the shared RAM, the
  image flash and a device's register, in slices of 16 transfers), each
  client's ring job (requests fetched, checked against the client's
  windows, done or passed to the Forth, completed), and posting events
  and interrupts to the CPUs.
- **The Forth** (`forth/`, about 8,700 cells): the console *is* its
  interpreter. A kernel with the compiler, catch and throw; the monitor
  (examine, deposit, dump anywhere on the system bus), blocks as native
  jobs, the image flash and `save`, tasks, booting the CPU; the system:
  the server for the requests the ring jobs pass on (setting up rings,
  windows, routes, the CPUs' rings of events, Forth from the kernel), the
  CF card's sectors, and the serial lines with a line discipline.

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
0 $10000. 4096 bus-fill    \ halfwords on the bus, a native job; bus-move, sr>bus, bus>sr likewise
variable n : counter begin 1 n +! pause again ;
' counter 3 spawn          \ a second task, in bank 3
: hi ." hello" ; save      \ into the image flash, for the next cold start
```

The kernel on a CPU uses the IOP through its rings in the shared RAM
(layout.py has the formats, `sw/ring.s` is an example): requests of 16
bytes into the request ring, the doorbell, and completions of 8 bytes back,
with an interrupt and an event in the CPU's ring of events if it asked for
one. Client 0's rings, the kernel's, are set up at the cold start; others
through the kernel's ring.

| File | What's in it |
|---|---|
| `sim/` | The simulator crate: `micro.rs` (the microinstruction, the 74181), `iop.rs` (the core, the T bus, the system bus master and slave sides), `iobus.rs` (the I/O bus and the card's devices), `flash.rs` (the image flash), `cards.rs` (I/O cards for the slots), `system.rs` (the CPU card and the two in turn) |
| `layout.py` | What the microcode, the Forth and the tools share: the SRAM's map, the banks' registers, the system's variables and tables, the control register, the timing table, the image flash's header, the rings and their requests |
| `uasm.py` | The microassembler: RFC 0027's notation, one line a microinstruction, with macros |
| `ucode/core.uc`, `ucode/jobs.uc`, `ucode/prims.uc` | The microcode |
| `meta.py` | The metacompiler: the Forth source into the dictionary image |
| `forth/kernel.fs`, `monitor.fs`, `system.fs`, `devices.fs`, `cold.fs` | The Forth |
| `build.py` | The image flash: the dictionary, and the CPU's images as records |
| `sw/hello.s`, `sw/irq.s`, `sw/ring.s` | CPU programs: the default boot program, one that waits for an interrupt from the IOP, and the kernel's side of the rings |
| `run.py`, `cli.py` | Running it; the command line |
| `bench.py` | The measurements |
| `tests/` | The unit tests: the microassembler, the Forth, the system, the rings, the devices behind them, the events |

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
  {BANK, REG} otherwise, so `t0 <- #5` writes a register, and copying one
  register to another takes two microinstructions (`F <- a`, `b <- F`).
- **CTRL is an addressable latch** (a 74x259 for the 74ABT273): LD CTRL
  sets bit R[2:0] to R[3], so firmware can change one bit without knowing
  the others. Its bits: SESSION, WORK, RESET (the system bus's), IORESET.
- **LC** is one 74F161: COND "LC not done" is LC != 15, and counts. Loading
  it with -n gives n passes, 1 to 16.
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
  to clear doorbell X[3:0].
- **The shared RAM takes X as a byte address,** its bit 0 ignored, and
  its page register (device 4 register 0, 7 bits for up to 8 MB) as
  address bits 16-22: a CPU's physical address in region 4 splits into
  the two without a shift, which the datapath doesn't have. RFC 0027 has
  X count halfwords, with a 4-bit page register for 2 MB; with that, every
  request into the shared RAM would cost a 15-step shift.
- **The registers** are in RFC 0027's order and groups (6.1, 3.5): a
  task's `ip sp rp tos resume link wait m1` with the I/O bus, `t0`-`t7`
  with the shared RAM, `up` and `me` at 16-17, user variables from 18. So
  no primitive can step a scratch register while it reads the I/O bus:
  `io@` and `flash!` move their data through AC and X instead. `m1` is -1
  in every bank, and since BANK takes F's low 8 bits, `BANK <- m1` goes to
  bank 255, the native layer's, while K holds a branch target.
- **`execute`** goes through nest-w, with w = t0 (RFC 0027, 6.2).
- **The native layer** runs in bank 255, entered at a primitive's end
  (`branch`, `0branch`, `exit`, the loops), from `pause` while it skips
  waiting tasks, or between a job's slices. It runs the tick, the
  doorbells (each queues its client's ring job), and the jobs.
- **Native jobs** each have a bank: 64-79 the clients' ring jobs, 80-95 a
  pool the Forth's `(job)` takes from, which the task that started one
  waits on. Queued jobs are a ring through a table of links; the head
  runs, a slice at a time, and WORK is on while any wait, so that the
  Forth looks at attention. Between slices a job counts and clears the
  tick itself when nothing else is up (10 microcycles), and goes to the
  native layer otherwise. A job's turn is 4 ticks, then the queue moves
  on and the Forth gets a turn, only if a task is running or has been
  woken.
- **The movers** cut a block into chunks that keep each address within
  its 64 KB (the bus's AH, the shared RAM's page; b within its page of the
  image flash), and each chunk into slices of 16 transfers, with LC
  loaded from a table by the slice's bytes. Halfwords only; to and from a
  device's register, multiples of 4.
- **The rings** (layout.py): a client's request ring, completion ring and
  four indices (byte offsets, each with one writer) in one 64 KB page of
  the shared RAM. The ring job reads a request into its registers, and
  does copies, fills and zeroing itself, checked against up to 4 windows
  of the client's (the kernel's ring, client 0, has none to check); the
  rest go through a queue to a Forth task, the server. A completion
  interrupts its client when the ring is next empty, so a run of requests
  costs one interrupt.
- **Events to a CPU** (RFC 0027, 7.3, RFC 0037, 8): an event table of 4
  cells a source (its owner, CPU, level and hold); each CPU has a ring of
  events, halfwords, and a block beside it with the indices and the fast
  levels' mailboxes. A slow level held back sets TICKS, a countdown the
  tick takes, to the shortest hold waiting; when it runs out every held
  level goes in one write to each CPU's set address.
- **I/O cards** (`sim/src/cards.rs`): the CF card with A3 as its second
  chip select, PIO mode 4 timing (0/3/0); the serial card's two 16C550s
  on A3, from CLKA; a GPIO card with an INT mask register.
- **The image flash's layout:** a header page, the dictionary from page 1,
  the CPU's images from halfword 0x10000 (`build.py`), as records of
  {bus address, n, n halfwords}.
- **The CPU card's registers** at `0x7000_0000` (`sim/src/system.rs`):
  board information at +0, control at +0x1000 (RUN, RESET, STEP, NMI),
  interrupt requests at +0x2000 (set, and clear at +4), and the control
  store's ten lanes at +0x40_0000.

## Measurements

`heron iop bench --wcs`, against RFC 0027's estimates:

| | Measured | RFC 0027 |
|---|---:|---|
| SRAM self test (64K cells, two patterns) | 125.8 ms | - |
| dictionary out of the flash (8727 cells, 35 pages) | 6.0 ms | 32K cells in ~30 ms |
| power-up to the banner | 148.4 ms | - |
| Forth words a second, in a loop of `i inc dup + over swap - drop` | 1,250,150 | about 1,000,000 |
| microcycles a Forth word, there | 6.67 | NEXT 3 (2 with its delay slot used), most primitives 5-7 |
| the tick's share of the IOP while Forth computes | 9.7% | 5-10% (0.5-1 us a tick) |
| Forth words a second, `words` (the console, `emit` waiting on the UART) | 1,245,220 | - |
| fill, the CPU's RAM, 8192 halfwords | 6.1 MB/s | 9.9 MB/s |
| copy, the CPU's RAM to its RAM, 8192 halfwords | 3.0 MB/s | 4.9 MB/s |
| copy, the shared RAM to the CPU's RAM, 8192 halfwords | 4.6 MB/s | 7.6 MB/s |
| copy, the CPU's RAM to the shared RAM, 8192 halfwords | 3.8 MB/s | 7.6 MB/s |
| booting the CPU: draft 2's control store, its decode table and the program | 80.5 ms (3.0 MB/s) | about 35 ms for the 1b's (130K halfwords at 7.6 MB/s) |
| a request, the IOP's side: fill 64 bytes, from the doorbell to its completion, and to the interrupt | 35.4 us, 51.0 us | ~5 us on top of the transfer |
| a request, the IOP's side: copy a 4 KB page, from the doorbell to its completion, and to the interrupt | 1367.9 us, 1389.4 us | ~5 us on top of the transfer |
| a request, the IOP's side: OP_NOP, through the Forth's server, from the doorbell to its completion, and to the interrupt | 147.7 us, 198.1 us | ~5 us on top of the transfer |
| a request from the CPU at 6 MHz: fill 64 bytes, its cycles (the handler included), and the time from one to the next | 254 cycles, 100 us | 200-700 cycles |
| a request from the CPU at 6 MHz: copy a 4 KB page, its cycles (the handler included), and the time from one to the next | 254 cycles, 1435 us | 200-700 cycles |
| a request from the CPU at 6 MHz: a request to the Forth's server (OP_NOP), its cycles (the handler included), and the time from one to the next | 254 cycles, 244 us | 200-700 cycles |
| microcode | 2082 microinstructions, 76 primitives | 1-2K; the interpreter and primitives 500-1,000 |
| the Forth's dictionary | 8727 cells | up to 32K |

The copies are a job's time from its first slice to its end, with the
ticks and the Forth's turns. A request's CPU cycles are `sw/ring.s`'s,
whose handler takes one completion and drains the events: a kernel's
would do more.

What the differences come from, so far:

- **The copies** run at the loop's rate in each slice (fill 3 clocks a
  halfword, two writes a microinstruction pair; copies 4-6), but a slice
  costs 7 microinstructions more than RFC 0027's 6 clocks of
  re-arbitration (its count and test, LC, the step, the session off and
  on, the look at attention), the tick about 10 a job's slice when it
  comes, and a job's turn ending 30-40. The RFC's figures leave all three
  out. A copy within the CPU's RAM moves 8 halfwords a slice, so it pays
  that twice as often.
- **Into the shared RAM** a halfword waits a clock for BA: the CPU card's
  slave port takes 2 data clocks, so the read's data comes a clock after
  the next microinstruction's E1.
- **Out of the image flash** a halfword is 5 clocks, not 4: the
  SST39SF040-70 needs a 2-clock strobe (0/2/0), so the read stretches its
  microinstruction to 3. A 45 ns part (0/1/0) would make it 4. The boot
  is also a job for each run of the control store's used words, a few
  hundred, each started from the Forth.
- **A request** costs the IOP about 280 microcycles (34 us) from the
  doorbell to its completion for the smallest one, against RFC 0027's 5
  us: the doorbell and queueing its ring job (about 40), reading 8
  halfwords at 2 microinstructions each and the ring's bookkeeping (43),
  decoding, the checks and starting the mover (about 40), the move, the
  completion (56: its settings are read through X, 3 microinstructions a
  value), and ticks and turns meanwhile. The interrupt is another 55 or
  so: the event into the CPU's ring, then the level. So a request pays
  from about 200 bytes up, which is what RFC 0027 (11.4) expects of the
  CPU's side; with the IOP's side as measured, from about 500.
- **The server** is the Forth's: about 150 us for a request that does
  nothing, from the queue through `serve` to `(complete)` and `(post)`.
- **The Forth** is faster than the RFC's estimate in ordinary code; the
  slow words are the ones with microcode loops (`um*`, `um/mod`, `rshift`
  and so `2/`: 80-160 microcycles).
- **The tick** costs Forth 7 microcycles when nothing is up (the INT
  lines, ATN0-3, and TICKS counted), and a job between slices 10.

## Not yet

- **Fen on this system** (RFC 0027, 16, step 3's request costs with Fen's
  kernel): RFC 0037 (28) moves Fen's devices to the IOP's map, which
  changes Fen's drivers. Fen still runs on its own board.
- **Devices:** the serial loader, PS/2, the time of day and the front
  panel; the stuck-transfer counter; the 32-bit paths; change detection
  on the INT lines; a timer request (a completion after a delay).
- **The rings:** a full completion ring drops the completion (and counts
  it); requests from the CPU's RAM rather than the shared RAM; the
  server's own windows for Forth from the kernel.
- **The netlist** (RFC 0027, 16, step 4).

Where the CPU's side doesn't match this system yet, for the RFCs rather
than this study: draft 2's CPU card in `studies/v2_hw` (`iop.py`, after
RFC 0031, 6) has its slave port in slot 0 by RFC 0014's slots, with the
control register at `0x600_0000` and the control store at `0x400_0000`
in the slot. Here the card is RFC 0037's region 0, its registers at
`0x7000_0000` with the control store's window among them, ten lanes:
draft 2's 144-bit microinstruction in nine, the decode table in one.
