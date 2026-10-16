"""The draft 2 CPU's parts, as a variant of the chip library
(heron.infra.hw.chips.VARIANTS): RFC 0024's fast set, as on its `fast`
card (studies/v1b_tradeoffs/parts.py), with the parts draft 2 adds.

  v2-fast   74F and 74ABT logic, 74F181/182; 12 ns SRAM for the control
            store, the decode table and the register file (IS61C6416AL,
            64K x 16, two 8-bit halves in the netlist), the page map and
            the RAM (AS7C4096A, 512K x 8); the registers, latches and
            buffers are 16-bit 74ABT parts (16374, 16823, 16373, 16244),
            two 8- or 9-bit halves each in the netlist
"""

from heron.infra.hw import chips
from heron.studies.v1b_tradeoffs.parts import FAST_LOGIC

VARIANT = "v2-fast"
SRAM16 = "IS61C6416AL-12"

chips.VARIANTS[VARIANT] = {
    "logic": "74ACT", "alu": "74F181", "cla": "74F182", "rf": "AS7C256A-12",
    "ram": "AS6C62256-55", "ram512": "AS7C4096A-12", "rom": SRAM16, "decode": SRAM16,
    "parts": dict(FAST_LOGIC, **{"573": "74ABT573", "sram64k": SRAM16,
                                 "16374h": "74ABT16374A", "16823h": "74ABT16823",
                                 "16373h": "74ABT16373A", "16244h": "74ABT16244A"}),
}
