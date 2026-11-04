"""Reed's parts: a variant of the chip library (chips.VARIANTS) and the
chip types it adds (devices with their serial and analog pins, connectors).

  reed  74ABT registers, latches, buffers and transceivers and 74F logic,
        in SOIC (1.27 mm pitch, nothing finer: Emily, 2026-11-02); 74F181 in
        DIP-24 (0.6"); ATF22V10C-7 in DIP-24, but the register
        file's address muxes and bypass in the ATF22V10C-5 (PLCC-28, the
        only package of its 5 ns grade); the control store and decode
        table in a 45 ns 128K x 8 part in socketed PLCC-32 (CS_PART: the
        SST39SF010A's 45 ns grade is gone, so the AT27C010-45 OTP EPROM
        stands in, its figures estimated; "SST39SF010A-55" sets a 5-tick
        floor); IS61C6416AL-12 (64K x 16, SOJ-44, as two 8-bit halves) for
        the register file; AS7C4096A-12 (512K x 8, SOJ-36) for the RAM and
        the frame buffer; IS61C256AL-12 for the palette
"""

from heron.infra.hw import chips
from heron.infra.hw.cells import Arc, Out, Setup, Strobe

VARIANT = "reed"
CS_PART = "AT27C010-45"
# the register file's address muxes and bypass: the 22V10's 5 ns grade (PLCC only)
FAST_GAL = "ATF22V10C-5"

chips.VARIANTS[VARIANT] = {
    "logic": "74F", "alu": "74F181", "cla": "74F182", "rf": "IS61C256AL-12",
    "ram": "IS61C256AL-12", "ram512": "AS7C4096A-12", "rom": CS_PART,
    "parts": {"541": "74ABT541", "574": "74ABT574", "245": "74ABT245", "573": "74ABT573",
              "377": "74ABT377", "823": "74ABT823", "22v10": "ATF22V10C-7", "sram64k": "IS61C6416AL-12",
              "sram512": "AS7C4096A-12", "clkdrv": "CDC341", "14": "74HCT14"},
}

# packages and their area on a board: a unit is a DIP-20's slot soldered by
# hand (report 0044's tight packing); SOIC takes three quarters of that
# (report 0044: 59% of A4's slots in SMD against 79% in tight DIP)
PACKAGES = {
    "74ABT541": ("SOIC-20", 0.75), "74ABT574": ("SOIC-20", 0.75), "74ABT245": ("SOIC-20", 0.75),
    "74ABT573": ("SOIC-20", 0.75), "74ABT377": ("SOIC-20", 0.75), "74ABT823": ("SOIC-24", 0.85), "74F153": ("SOIC-16", 0.6),
    "74F163": ("SOIC-16", 0.6), "74F299": ("SOIC-20", 0.75), "74F521": ("SOIC-20", 0.75),
    "74F04": ("SOIC-14", 0.55), "74F74": ("SOIC-14", 0.55), "74HCT14": ("SOIC-14", 0.55), "74F181": ("DIP-24W", 1.7),
    "ATF22V10C-7": ("DIP-24", 1.1), "ATF22V10C-5": ("PLCC-28", 1.0),
    "AT27C010-45": ("PLCC-32 socket", 1.2),
    "SST39SF010A-55": ("PLCC-32 socket", 1.2), "IS61C6416AL-12": ("SOJ-44", 1.2),
    "AS7C4096A-12": ("SOJ-36", 1.2), "IS61C256AL-12": ("SOJ-28", 1.0), "CDC341": ("SOIC-20", 0.75),
    "oscillator": ("DIP-14 can", 0.8), "TL16C550C": ("PLCC-44", 1.6), "MAX232": ("SOIC-16", 0.6),
    "82C54": ("PLCC-28", 1.2), "CF": ("CF socket", 3.0), "DAC0832": ("SOIC-20", 0.75),
    "MCP6002": ("SOIC-8", 0.4), "TL7705A": ("SOIC-8", 0.4), "ADV7125": ("LQFP-48 (0.5 mm): open", 1.0),
    "SST39SF010A-70": ("PLCC-32 socket", 1.2),
}
# the halves a part is placed as (IS61C6416: two 64K x 8 halves, its byte enables)
HALVES = {"IS61C6416AL-12": 2}

T = chips.T


def _types():
    if "16c550s" in chips.TYPES:
        return
    T("16c550s", "uart16550",
      [(f"D{i}", "io") for i in range(8)] + [(f"A{i}", "in") for i in range(3)]
      + [(p, "in") for p in ("CS0", "CS1", "CS2", "RD", "WR", "MR", "XIN", "SIN", "CTS")]
      + [(p, "out") for p in ("INTR", "SOUT", "RTS", "DTR", "OUT1", "OUT2")],
      arcs=[(["RD"], [f"D{i}" for i in range(8)], "RD->D")], family="device",
      desc="TL16C550C with its serial pins",
      outputs={f"D{i}": Out(None, {"A0 A1 A2": "RD->D"}, enable="/CS2·/RD",
                             on={"RD CS2": Arc("RD->D", min=0)}, off={"RD CS2": "RD->D dis"})
               for i in range(8)},
      asynchronous=["INTR SOUT RTS DTR OUT1 OUT2"],
      timing=[Strobe("/CS2·/WR", data={"D0-D7": ("tDS", "tDH")}, width="tWR"),
              Strobe("/CS2·/RD", width="tRD")])
    T("max232", "passive", [(p, "in") for p in ("T1IN", "T2IN", "R1IN", "R2IN")]
      + [(p, "out") for p in ("T1OUT", "T2OUT", "R1OUT", "R2OUT")], family="device",
      desc="RS-232 driver and receiver, two of each", asynchronous=["T1OUT T2OUT R1OUT R2OUT"])
    T("dac0832", "passive", [(f"D{i}", "in") for i in range(8)]
      + [(p, "in") for p in ("CS", "WR1", "WR2", "XFER", "ILE")] + [("VOUT", "pull")],
      family="device", desc="DAC0832: its input latch on CS and WR1, the DAC latch open "
                            "(WR2, XFER low); voltage mode, the output at VREF")
    T("mcp6002", "passive", [(p, "pull") for p in ("IN", "OUT", "REF")], family="device",
      desc="dual op-amp: the DAC's reference and output buffers")
    T("adv7125", "passive", [(f"R{i}", "in") for i in range(8)] + [(f"G{i}", "in") for i in range(8)]
      + [(f"B{i}", "in") for i in range(8)] + [(p, "in") for p in ("CLK", "BLANK", "SYNC")]
      + [(p, "pull") for p in ("IOR", "IOG", "IOB")], family="device",
      desc="ADV7125 triple 8-bit video DAC (BLANK, SYNC active low)")
    T("din96", "passive", [(f"{r}{i}", "pull") for r in "abc" for i in range(1, 33)],
      family="passive", desc="DIN 41612 connector, 96 pins in rows a, b and c")
    T("conn", "passive", [(f"P{i}", "pull") for i in range(8)], family="passive",
      desc="a connector, socket or header (its part names it)")
    chips.FIXED_PARTS.update({"16c550s": "TL16C550C", "max232": "MAX232", "dac0832": "DAC0832",
                              "mcp6002": "MCP6002", "adv7125": "ADV7125",
                              "din96": "DIN 41612 96-pin", "conn": "connector"})


_types()
