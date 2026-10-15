"""Cycle estimates for the draft 1 machines, from a model of six hardware
configurations. One of them, D32-separate, has since been built as the
draft 1b hardware; report 0012 describes it and compares
its cycle counts with this model's.

The instruction-level simulator records, for every executed instruction, a
*timing key*: how many parcels it has, where it sits in memory, and an
ISA-independent description of the work it does (an ALU operation, a load
through a given kind of address, a taken branch, ...). This module turns a
key into a cycle count for a given machine configuration, so one simulation
run gives the cycle counts for every configuration.

Configurations vary two things:

- Datapath width: 16 bits (a 32-bit ALU operation takes two passes) or
  32 bits. Either way the register file reads or writes a whole 32-bit
  register in one cycle.
- Fetch style:
    'separate'  every instruction starts with its own fetch cycle; 16-bit bus.
    'overlap'   the next opcode is fetched in the instruction's last cycle when
                the bus is free then (as in the draft 0 hardware); 16-bit bus.
    'wide'      32-bit bus and a two-parcel prefetch buffer: a fetch brings in
                an aligned 32-bit word, parcels already in the buffer are free,
                and the next fetch can happen in any cycle the bus is idle.
                The 32-bit bus also makes word loads and stores one cycle.

Each instruction is described as a few micro-operations, each using some of
three resources for a number of cycles: the ALU ('A'), the memory bus ('B')
and the register file port ('R': one read of up to two registers, or one
write, per cycle). A tiny list scheduler packs them, honouring dependencies,
the way a microcode writer would. The rules are in timing-model-v1.md;
the model is studies/v1_isa/isa/src/timing.rs.
"""

from functools import lru_cache

from heron import native

CONFIGS = {
    "D16-separate": (16, "separate"),
    "D16-overlap": (16, "overlap"),
    "D16-wide": (16, "wide"),
    "D32-separate": (32, "separate"),
    "D32-overlap": (32, "overlap"),
    "D32-wide": (32, "wide"),
}
CONFIG_NAMES = list(CONFIGS)
REFERENCE = "D16-overlap"   # used for the simulator's own cycle count (timer, limits)


@lru_cache(maxsize=None)
def cycles(key, config):
    """The cycles an instruction with timing key `key` (a tuple, see above)
    takes in a configuration. The model itself is Rust:
    studies/v1_isa/isa/src/timing.rs."""
    return native.v1.cycles(key, config)
