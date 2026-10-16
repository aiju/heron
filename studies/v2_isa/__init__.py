"""Draft 2 (RFC 0028): its simulator, assembler and disassembler, and the
program suite ported to it. See README.md."""

from heron.infra import isas

isas.register("v2", "heron.studies.v2_isa.v2")
