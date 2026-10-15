# The current design

Heron's current design is what this folder describes: only what has been
decided, as reference. Why it was decided, and what else was considered,
is in the RFCs and reports it links to ([the index](../reports/README.md)).

There's no complete current design yet. Draft 2 comes next, built on
draft 1b's encoding
([RFC 0006](../reports/0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
Earlier designs are studies: [draft 0](../studies/v0_hw/README.md),
[draft 1](../studies/v1_isa/README.md) and
[the draft 1b hardware](../studies/v1b_hw/README.md).

## Decided so far

**Architecture**

- A 32-bit architecture
  ([RFC 0005](../reports/0005-rfc-ideas-direction.md#1-direction-and-ambition)).
- 16-bit instruction parcels, with 0–2 extension parcels.
- Draft 2 builds on draft 1b: one register and one addressing mode per
  instruction ([isa-v1b.md](../studies/v1_isa/isa-v1b.md)).

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

- The operating system has protection.
- A console on serial terminals, and video too (the first build might
  leave video out).
- No microcontrollers inside peripherals.
- Ethernet, preferably with a MAC built from TTL.
