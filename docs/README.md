# The current design

Heron's current design is what this folder describes: only what has been
decided, as reference. Why it was decided, and what else was considered,
is in the RFCs and reports it links to ([the index](../reports/README.md)).

There's no complete current design yet. Draft 2 comes next, built on
draft 1b
([RFC 0006](../reports/0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
Its encoding is drafted, not decided, in
[RFC 0028](../reports/0028-rfc-draft-2-isa.md).
Earlier designs are [RFC 0001](../reports/0001-rfc-draft-0.md) (draft 0),
[RFC 0004](../reports/0004-rfc-draft-1-isa.md) (draft 1) and
[report 0012](../reports/0012-report-draft-1b-hardware.md) (the draft 1b
hardware), with their code in [studies](../studies/README.md).

## Decided so far

**Architecture**

- A 32-bit architecture
  ([RFC 0005](../reports/0005-rfc-ideas-direction.md#1-direction-and-ambition)).
- 16-bit instruction parcels, with 0–2 extension parcels.
- Draft 2 builds on draft 1b: one register and one addressing mode per
  instruction ([RFC 0004, Part II](../reports/0004-rfc-draft-1-isa.md#part-ii-draft-1b)).
- In draft 2, `r0` is a general register; it no longer reads as zero
  ([RFC 0006](../reports/0006-rfc-ideas-isa.md#33-r0-as-a-general-register)).

**Construction**

- 4-layer PCBs on a backplane, two 96-pin connectors per slot. The first
  connector, P1, is enough for a simple peripheral.

**Clocking**

- Variable-length cycles from a master clock: [clocking.md](clocking.md).

**System bus** (the draft specification is [RFC 0014](../reports/0014-rfc-system-bus.md))

- Synchronous: one bus clock, every signal sampled on its rising edge.
- Simple, dumb peripherals must be possible, and they go on the system bus:
  there's no separate I/O bus.
- Bus addresses are the full 32 bits.
- Addresses carry the slot: four address bits select one of 16 slots
  (which four is still open).
- SEL, sent only to the addressed slot, is the strobe for simple cards.
- LOCK, for locked read-modify-write across the bus.
- Each card says what it is, and so how it's timed, with class straps that
  the backplane reads. A fast card holds WAIT when it needs longer.
- No burst transfers.
- Every card has an ID.
- The backplane carries active logic.
- No −5.2 V on the backplane.

**Beyond the CPU**

- A console on serial terminals, and video too (the first build might
  leave video out).
- No microcontrollers inside peripherals.
- Ethernet, preferably with a MAC built from TTL.
