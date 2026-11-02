# Pipelining Chibi Heron's control store

Findings for [RFC 0047](../0047-rfc-chibi-heron.md#19-proposals): can the
control store be pipelined, so that the flashes give the next
microinstruction while this one runs? The estimates are
`heron chibi pipeline` (studies/chibi/pipeline.py), from the program
suite's 13.8 million microinstructions as the model runs them.

## What phase F does now

Every microinstruction starts with phase F, 3 ticks (59.6 ns). It is
3 of the 6.43 ticks a microinstruction averages, so nearly half the
machine's time. Three things happen in it:

- **The flashes settle** on the new address: 55 ns, with no register on
  their outputs.
- **The register file is written**: the last microinstruction's low
  half's result in tick 1, its high half's in tick 2.
- **The video reads the RAM**, in ticks 1–2 (3–4 when its buffer is
  empty).

The flash and the writes each need about 3 ticks. Hiding only one of them
gains little.

## Holding the executing word

Every control bit but HALT goes only into 22V10s: 71 bits make 129 GAL
inputs. The GALs can't be the pipeline register, though. They use the
control bits combinationally all through the cycle, together with signals
that change within it (the half, the tick, the flags, the data). So the
executing word has to be held in a register:

- **57 bits**: everything but the next-address fields (SEQ, CND, JT, PT),
  which the sequencer takes from the flashes directly, and HALT. That's
  8 × 74ABT574.
- Spare macrocells in the GALs on the cycle's clock could hold at most 14
  of the bits, which would leave 6 × 574.

## Sequencing

For the flashes to have the whole cycle, the next address must be loaded
at the cycle's start. So the sequencer works from the fetched word (the
flashes' outputs) during the cycle before.

- **No delay slots.** A jump takes effect for the very next
  microinstruction, as now.
- **Conditions:** a jump sees the flags after the microinstruction before
  it, as a one-half microinstruction does now. The condition comes about
  12 ns into the cycle, so a cycle with a conditional jump is at least 4
  ticks.
- **The microcode's changes:**
  - a two-half microinstruction that branches on its own low half's
    flags (6.0% of those executed) needs reordering or a microinstruction
    more;
  - N ← s can be applied a cycle earlier in `U_NG`;
  - N from the index parcel (1.4%) costs a microinstruction;
  - each decode costs a bubble, since the fetched parcel gives the next
    address only at its cycle's end, unless the next instruction's parcel
    is prefetched (which the brief ruled out);
  - a task starting drops the word already fetched.

## The floor

The flashes' word must reach the register within a cycle: 4 ns from the
address register, 55 ns of the SST39SF040, and the 574's setup, about
61 ns, so 4 ticks. The SST39SF010A comes in a 45 ns grade, which makes it
3 ticks (4 with a conditional jump). It has only 128K words, which the
flat layout (start address = opcode × 4, 8–16K words) fits and today's
19-bit layout doesn't.

## The register writes and the video

- **If the writes keep a phase of their own** (2 ticks), the gain is
  1.06–1.08×: not worth it.
- **Writes overlapped with the halves.** The four-SRAM register file
  makes this possible. The low half's result is written while the high
  half reads the other pair, and the high half's result while the next
  low half does. A one-half microinstruction pays a tick, and a half that
  reads the pair being written stalls.
- **The video** loses its free slot. It would read the RAM in halves
  that don't use it (most don't), and stretch a cycle when its buffer
  runs dry.

## The estimate

`heron chibi pipeline`, on the suite. I/O halves, the slow devices and the
video's stretches are left out of every row alike (under 0.1% of the
ticks):

| | Ticks a microinstruction | Speed |
|---|---:|---:|
| today | 6.43 | 1.00x |
| pipelined, writes in F, 55 ns flashes | 6.07 | 1.06x |
| pipelined, writes overlapped, 55 ns | 5.13 | 1.25x |
| pipelined, writes overlapped, 55 ns, prefetch | 4.71 | 1.37x |
| pipelined, writes in F, 45 ns flashes | 5.97 | 1.08x |
| pipelined, writes overlapped, 45 ns | 4.65 | 1.38x |
| pipelined, writes overlapped, 45 ns, prefetch | 4.34 | 1.48x |

## Cost

- the register: 6–8 × 74ABT574;
- the write scheduling and its stalls: the clock generator and `U_RFW`,
  perhaps one GAL more;
- the video's reads in free halves: perhaps one GAL more;
- for 45 ns flashes, the flat layout (about 1–2 packages);
- a prefetch: an instruction register and PC's logic, 2–3 more.

About 9–11 packages for 1.38×, against 119 now. For comparison, the
multiplier in flash ([RFC 0047](../0047-rfc-chibi-heron.md#19-proposals)) is
2 packages for about 1.3×, mostly on mandel; the two combine.

## Conclusion

Pipelining pays only together with the flat layout and the register writes
moved into the halves: about 1.38× for about 10 packages. A pipeline
register alone, keeping the writes in phase F, gains under 10%. The
estimate is the model's mix costed by these rules, not a built machine;
the stalls of the overlapped writes and the video's reads aren't counted,
so the real figure would be somewhat lower.
