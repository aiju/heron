"""A link register for CALL: draft 1b with BSR and CALL leaving the return
address in r7 (v1bl), the software ported to it, and the measurements
against 1b. See README.md."""

import heron.studies.v1_isa  # noqa: F401  (registers the ISAs)
from heron.infra import isas

isas.register("v1bl", "heron.studies.link_register.v1bl")
