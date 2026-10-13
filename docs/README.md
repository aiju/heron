# The current design

Heron's current design is what this folder describes: only what has been
decided, as reference. Why it was decided, and what else was considered,
is in the RFCs and reports it links to ([the index](../reports/README.md)).

There's no complete current design yet. Draft 2 comes next; which of the
draft 1 encodings, 1a or 1b, it builds on is still open
([RFC 0006](../reports/0006-rfc-ideas-isa.md#23-recommended-for-draft-2)).
Earlier designs are studies: [draft 0](../studies/v0_hw/README.md),
[draft 1](../studies/v1_isa/README.md) and
[the draft 1b hardware](../studies/v1b_hw/README.md).

## Decided so far

**Architecture**

- A 32-bit architecture, with a narrow implementation first
  ([RFC 0005](../reports/0005-rfc-ideas-direction.md#1-direction-and-ambition)).
- 16-bit instruction parcels, with 0–2 extension parcels.

**Construction**

- 4-layer PCBs on a backplane, two connectors per slot. The first
  connector, P1, is enough for a simple peripheral.

**Clocking**

- Variable-length cycles from a 50 MHz master clock: [clocking.md](clocking.md).

**System bus** (the draft specification is [RFC 0014](../reports/0014-rfc-system-bus.md))

- Synchronous: one bus clock, every signal sampled on its rising edge.
- Simple, dumb peripherals must be possible.
- Bus addresses are the full 32 bits.
- Burst transfers are optional.

**Beyond the CPU**

- A second CPU: an ECL number cruncher, designed separately. It shares the
  system bus and has its own RAM.
- Ethernet, preferably with a MAC built from TTL.
