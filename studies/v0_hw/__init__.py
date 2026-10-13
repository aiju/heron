"""Draft 0: a 16-bit ISA and its 98-chip implementation. Frozen; see README.md."""

from heron.infra import isas

isas.register("v0", "heron.studies.v0_hw.isa")
