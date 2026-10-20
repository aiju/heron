"""Chibi Heron's parts, as a variant of the chip library
(heron.infra.hw.chips.VARIANTS):

  chibi  74F gates and 74ABT registers, buffers and transceivers in DIP;
         74F181/182; ATF22V10C-5 programmable logic and the flash (the
         control store's SST39SF010A-55, or the first cut's SST39SF040-55,
         and the boot flash's SST39SF010A-55) in socketed PLCC; for the register file IS61C6416AL-12 (64K x 16,
         SOJ-44: the two-halves machine's) or CY7C199C-12 (32K x 8,
         DIP-28: the first cut's); AS7C4096A-12 (512K x 8, SOJ-36) for the
         RAM
"""

from heron.infra.hw import chips

VARIANT = "chibi"

chips.VARIANTS[VARIANT] = {
    "logic": "74ACT", "alu": "74F181", "cla": "74F182", "rf": "CY7C199C-12",
    "ram": "AS6C62256-55", "ram512": "AS7C4096A-12", "rom": "SST39SF010A-55",
    "parts": {"00": "74F00", "04": "74F04", "08": "74F08", "32": "74F32", "74": "74ABT74",
              "377": "74ABT377", "541": "74ABT541", "574": "74ABT574", "245": "74ABT245",
              "22v10": "ATF22V10C-5", "sram64k": "IS61C6416AL-12",
              "dac0832": "DAC0832LCN"},
}
