"""Heron Mini's parts, as a variant of the chip library
(heron.infra.hw.chips.VARIANTS): RFC 0024's fast set with the control
store in flash (studies/v1b_tradeoffs/parts.py, `fast-flash`), in
packages for hand soldering: 74F and 74ABT logic in DIP, 74F181/182,
the microcode in 55 ns flash (DIP-32 or PLCC-32), 12 ns SRAM for the
register file, the palette and the RAM (SOJ).

  mini   74F gates, multiplexers, decoders and counters; 74ABT registers,
         latches, buffers and transceivers, all 8-bit (DIP-20); 74F181/182;
         SST39SF010A-55 flash; AS7C256A-12 (32K x 8) and AS7C4096A-12
         (512K x 8) SRAM
"""

from heron.infra.hw import chips
from heron.studies.v1b_tradeoffs.parts import FAST_LOGIC

VARIANT = "mini"

chips.VARIANTS[VARIANT] = {
    "logic": "74ACT", "alu": "74F181", "cla": "74F182", "rf": "AS7C256A-12",
    "ram": "AS6C62256-55", "ram512": "AS7C4096A-12", "rom": "SST39SF010A-55",
    "parts": dict(FAST_LOGIC, **{"573": "74ABT573", "521": "74F521"}),
}
