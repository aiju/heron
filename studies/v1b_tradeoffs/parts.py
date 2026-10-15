"""Sets of parts for the experiments, as variants of the chip library
(heron.infra.hw.chips.VARIANTS): the draft 1b CPU's own three, and faster
ones.

  fast-flash   74F and 74ABT logic, 74F181/182, 12 ns SRAM for the RAM and
               the register file; the microcode and decode in 55 ns flash
  fast-dec     the same, with the two decode ROMs in 12 ns SRAM (loaded at
               power-up)
  fast         the same, with all of the control store in 12 ns SRAM
  act-ram12    74ACT logic, 74F181/182, 12 ns SRAM for the RAM

"Fast" logic is the quickest family the timing data has for each type:
74F for gates, multiplexers, decoders, counters and the 175, 74ABT for
registers, buffers and transceivers. Where neither exists in the data, a
74ACT or 74HCT part stands in (the 10, 30, 132, 14, 05). 74F is specified
for 0-70 C only; the 74ABT, 74ACT and 74HCT maxima cover -40..85 C.
"""

from heron.infra.hw import chips

FAST_LOGIC = {
    "00": "74F00", "02": "74F02", "04": "74F04", "08": "74F08", "11": "74F11",
    "20": "74F20", "21": "74F21", "27": "74F27", "32": "74F32", "86": "74F86",
    "10": "74ACT10", "30": "74HCT30", "05": "74HCT05", "14": "74HCT14", "132": "74HCT132",
    "74": "74ABT74", "109": "74F109", "175": "74F175",
    "138": "74F138", "148": "74F148", "151": "74F151", "153": "74F153", "157": "74F157",
    "161": "74F161", "163": "74F163", "299": "74F299", "688": "74F521",
    "377": "74ABT377", "541": "74ABT541", "540": "74ABT540", "574": "74ABT574",
    "534": "74ABT534", "823": "74ABT823", "245": "74ABT245", "125": "74ABT125",
}
SRAM12 = "AS7C4096A-12"           # 512K x 8, the RAM
RF12 = "AS7C256A-12"              # 32K x 8, the register file
STORE = "IS61C6416AL-12"          # 64K x 16 SRAM as a control store
FLASH = "SST39SF010A-55"


def _fast(rom, decode):
    return {"logic": "74ACT", "alu": "74F181", "cla": "74F182", "rf": RF12,
            "ram": "AS6C62256-55", "ram512": SRAM12, "rom": rom, "decode": decode,
            "parts": FAST_LOGIC}


SETS = {
    "fast-flash": _fast(FLASH, FLASH),
    "fast-dec": _fast(FLASH, STORE),
    "fast": _fast(STORE, STORE),
    "act-ram12": {"logic": "74ACT", "alu": "74F181", "cla": "74F182", "rf": RF12,
                  "ram": "AS6C62256-55", "ram512": SRAM12, "rom": FLASH},
}
chips.VARIANTS.update(SETS)

# what each set is, in the order the tables list them
DESCRIBE = {
    "hct-ls181": "74HCT, 74LS181/74S182, 55 ns RAM and flash (the system as built)",
    "act-f181": "74ACT, 74F181/182, 55 ns RAM and flash",
    "act-ram12": "74ACT, 74F181/182, 12 ns RAM, 55 ns flash",
    "fast-flash": "74F/74ABT, 74F181/182, 12 ns RAM, 55 ns flash",
    "fast-dec": "74F/74ABT, 74F181/182, 12 ns RAM, decode ROMs in 12 ns SRAM, microcode in 55 ns flash",
    "fast": "74F/74ABT, 74F181/182, 12 ns RAM, the control store in 12 ns SRAM",
}
