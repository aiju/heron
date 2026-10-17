# RFC 0040: the I/O processor's side, measured

What the I/O processor study found for [RFC 0040](../0040-rfc-interrupts.md)'s
I/O processor side: how long a request takes from its doorbell to the
CPU's interrupt, and how the study routes, masks and batches events. The
study is `studies/iop`, on branch
[`claude/ecstatic-shannon-xpofpc`](https://github.com/aiju/heron/tree/claude/ecstatic-shannon-xpofpc/studies/iop)
until it is merged; the numbers are from its microinstruction-level model,
in a test that plays the client, as its `bench.py` does. Its choices here
are proposals, like the rest of RFC 0040.

## A request, from its doorbell to the interrupt

A fill of 64 bytes with a slow event, timed from the client's doorbell
write, over two runs:

| Step | Time | Total |
|---|---:|---:|
| The native layer takes the doorbell, at the Forth's next branch or primitive's end, not at the tick | 1.4–3.2 µs | 1.4–3.2 µs |
| The ring job is queued | 2.2 µs | |
| The ring job first runs, from the native layer's loop at the tick | 8.0–9.6 µs | |
| The request is fetched and its windows checked: shared RAM reads and microcode | 5.4 µs | |
| The fill's first slice | 3.0 µs | |
| The fill is done: 32 halfword writes at 3 bus clocks, about 6 µs, the rest slices between ticks and the Forth's turns | 12.7–20.4 µs | |
| The completion is written | 1.4 µs | 36–42 µs |
| The ring is found empty, at the ring job's next turn | 8–16 µs | |
| The routing table is looked up | 3.3 µs | |
| The event ring's entry and head are written into the CPU's RAM over the bus, then the set write to its request register | 7.2 µs | about 60 µs |

- **Two scheduling waits,** about 18 of the 60 µs: the ring job waits for
  the tick's loop to run it, and the event waits for the ring to be found
  empty. Both are the study's choices.
- **The bus work** is about 10 µs.
- **Running a job as soon as it is queued and posting at its
  completion** should bring a request close to RFC 0040's estimate: a few
  µs on top of the transfer.
- **From the I/O processor seeing an event to the CPU's level bit,** the
  routing and the writes take about 10.5 µs here, against the 2–3 µs
  RFC 0040 estimated. That includes the event ring's entry and head,
  written over the bus into the CPU's RAM.

## Routing, masking and batching

As the study builds them:

- **The routing table:** 8 cells for each of 48 sources (the INT lines
  0–15, ATN0–3, and each client's completions). An entry holds the owner
  (a task's wait register, or a CPU), the CPU, the class, the level, the
  hold or deadline, and a fast event's source number.
- **Masking by counters,** for a client's completions, in place of a
  request from the driver:
  - the high halves of the rings' head words count the events: the
    completion ring's (written by the I/O processor) those posted, the
    request ring's (written by the client) those handled;
  - having handled one, the client copies the first count into the
    second, then looks at its completions again;
  - the I/O processor posts the next event only when the two are equal.

  So the source is served without a request, and a spurious interrupt
  can't put the two counts out of step.
- **Batching held levels:** a level held back sets TICKS, a countdown the
  tick takes, to the shortest hold waiting. When it runs out, every held
  level goes in one write to each CPU's set address. A lazy event's
  deadline uses the same mechanism, so a CPU that drained its ring at its
  own tick may still get the level with nothing new in the ring.
- **Fast events** claim the CPU card's message register and write
  {source, the event's source number}, or go as slow when the claim fails.

## Where the studies differ

The I/O processor study and v2_hw ([cpu-costs.md](cpu-costs.md)) model
the same CPU card, and agree on its offsets and on the control store's
window. Two differences remain, both left open by RFC 0040:

- **The request register's bits:** the I/O processor study has bit L − 1
  for level L (bits 0–7, as Fen's board has its mask); v2_hw has bit L
  (bits 1–8). The I/O processor writes these bits for every slow event.
- **The board information:** four words in the I/O processor study (the
  RAM's size, BCLK's period in ns, the region, the boot flags, at +0, +4,
  +8 and +`0xC`); one halfword in v2_hw's proposal. The I/O processor
  never reads it.
