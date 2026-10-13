"""Draft 1: a 32-bit ISA in two encodings, 1a and 1b, with the program suite
written for both. See README.md."""

from heron.infra import isas

isas.register("v1a", "heron.studies.v1_isa.v1a")
isas.register("v1b", "heron.studies.v1_isa.v1b")
