# Clocking

Each microinstruction sets how long its own cycle is, so a cycle takes only
as long as the slowest path that microinstruction exercises. The
measurements behind this, and the details that are still open, are in
[RFC 0007](../reports/0007-rfc-ideas-microarchitecture.md#4-microarchitecture).

- **Master clock: 50 MHz.** Cycle lengths are whole numbers of 20 ns ticks.
- **Lengths are set by jumpers.** A microinstruction picks a length class,
  and jumpers map each class to a number of ticks. So one microcode image
  runs on any choice of parts and can be tuned on a real board.
- **The timer and the cycle counter count real time** (master-clock
  ticks), not CPU cycles.
