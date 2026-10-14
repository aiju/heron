"""An operating system for Heron: what the hardware should give it, and
what it could be. See README.md."""

import heron.studies.v1_isa  # noqa: F401  (registers the ISAs)
from heron.infra import isas

isas.register("v1bs", "heron.studies.kernel.v1bs")
