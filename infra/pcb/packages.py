"""Pinouts and packages: where each of a chip type's logical pins (the
names in infra/hw/chips.py, which the simulator uses) is on the package,
and which footprint a package is in each board style.

A pinout lists the package's pins in order, pin 1 first. Each entry is a
logical pin name, or:
  VCC, GND     a supply pin;
  NC           not connected;
  =VCC, =GND   a pin the logical model doesn't have, tied to a rail on the
               board (a clock driver's output enables, a factory pin).
Pins numbered the same way in DIP, SOIC, SOJ, TSSOP and PLCC-32 share one
pinout; a package with its own numbering (TSOP) would need its own.

Sources are the datasheets named with each pinout. `check_kicad` in
check.py compares them with KiCad's symbol library, which is an
independent transcription of the same datasheets.
"""

# ---- pinouts ------------------------------------------------------------------

def _gates(order):
    return order.split()


QUAD2 = "1A 1B 1Y 2A 2B 2Y GND 3Y 3A 3B 4Y 4A 4B VCC"            # 00 08 32 86 132
QUAD2_NOR = "1Y 1A 1B 2Y 2A 2B GND 3A 3B 3Y 4A 4B 4Y VCC"        # 02
HEX1 = "1A 1Y 2A 2Y 3A 3Y GND 4Y 4A 5Y 5A 6Y 6A VCC"            # 04 05 14
TRIPLE3 = "1A 1B 2A 2B 2C 2Y GND 3Y 3A 3B 3C 1Y 1C VCC"          # 10 11 27
DUAL4 = "1A 1B NC 1C 1D 1Y GND 2Y 2A 2B NC 2C 2D VCC"            # 20 21
OCT_FLOW = ("OE1 A1 A2 A3 A4 A5 A6 A7 A8 GND "
            "Y8 Y7 Y6 Y5 Y4 Y3 Y2 Y1 OE2 VCC")                    # 540 541
REG574 = "OE D1 D2 D3 D4 D5 D6 D7 D8 GND CLK Q8 Q7 Q6 Q5 Q4 Q3 Q2 Q1 VCC"
REG374 = "OE Q1 D1 D2 Q2 Q3 D3 D4 Q4 GND CLK Q5 D5 D6 Q6 Q7 D7 D8 Q8 VCC"
CMP688 = "G P0 Q0 P1 Q1 P2 Q2 P3 Q3 GND P4 Q4 P5 Q5 P6 Q6 P7 Q7 PEQ VCC"

PINOUTS = {
    # TI SN74HCT00, SN74F08, SN74HCT32, SN74HCT86, SN74HCT132
    "00": QUAD2, "08": QUAD2, "32": QUAD2, "86": QUAD2, "132": QUAD2,
    "02": QUAD2_NOR,                                  # SN74HCT02
    "04": HEX1, "05": HEX1, "14": HEX1,               # SN74HCT04, SN74HCT05, SN74HCT14
    "10": TRIPLE3, "11": TRIPLE3, "27": TRIPLE3,      # SN74HCT10, SN74HCT11, SN74F27
    "20": DUAL4, "21": DUAL4,                         # SN74F20, SN74HCT21
    "30": "A B C D E F GND Y NC NC G H NC VCC",       # SN74HCT30
    "74": "1CLR 1D 1CLK 1PRE 1Q 1QN GND 2QN 2Q 2PRE 2CLK 2D 2CLR VCC",
    "109": "1CLR 1J 1K 1CLK 1PRE 1Q 1QN GND 2QN 2Q 2PRE 2CLK 2K 2J 2CLR VCC",
    "125": "1OE 1A 1Y 2OE 2A 2Y GND 3Y 3A 3OE 4Y 4A 4OE VCC",
    "138": "A B C G2A G2B G1 Y7 GND Y6 Y5 Y4 Y3 Y2 Y1 Y0 VCC",
    "148": "I4 I5 I6 I7 EI A2 A1 GND A0 I0 I1 I2 I3 GS EO VCC",
    "151": "D3 D2 D1 D0 Y W G GND C B A D7 D6 D5 D4 VCC",
    "153": "1G B 1C3 1C2 1C1 1C0 1Y GND 2Y 2C0 2C1 2C2 2C3 A 2G VCC",
    "157": "S 1A 1B 1Y 2A 2B 2Y GND 3Y 3B 3A 4Y 4B 4A G VCC",
    "161": "CLR CLK A B C D ENP GND LOAD ENT QD QC QB QA RCO VCC",
    "163": "CLR CLK A B C D ENP GND LOAD ENT QD QC QB QA RCO VCC",
    "175": "CLR 1Q 1QN 1D 2D 2QN 2Q GND CLK 3Q 3QN 3D 4D 4QN 4Q VCC",
    # SN74LS181 (active-high data: the same pins as the datasheet's active-low names)
    "181": ("B0 A0 S3 S2 S1 S0 CN M F0 F1 F2 GND F3 AEQB P CN4 G B3 A3 B2 A2 B1 A1 VCC"),
    "182": "G1 P1 G0 P0 G3 P3 P GND CNZ G CNY CNX CN G2 P2 VCC",          # SN74S182
    "245": "DIR A1 A2 A3 A4 A5 A6 A7 A8 GND B8 B7 B6 B5 B4 B3 B2 B1 OE VCC",
    "299": ("S0 OE1 OE2 IO6 IO4 IO2 IO0 Q0S MR GND DS0 CP IO1 IO3 IO5 IO7 Q7S DS7 S1 VCC"),
    "377": "EN Q1 D1 D2 Q2 Q3 D3 D4 Q4 GND CLK Q5 D5 D6 Q6 Q7 D7 D8 Q8 VCC",
    "540": OCT_FLOW, "541": OCT_FLOW,
    "574": REG574,
    # SN74ABT573A (TI SCBS190F, DW and N): the 574's pins, LE for CLK
    "573": "OE D1 D2 D3 D4 D5 D6 D7 D8 GND LE Q8 Q7 Q6 Q5 Q4 Q3 Q2 Q1 VCC",
    "534": REG374,                                    # 74ABT534: the 374's pins, inverting
    "688": CMP688, "521": CMP688,                     # SN74HCT688, 74F521
    # 74ABT823 (Nexperia/TI): 9-bit register, CLR and EN active low
    "823": ("OE D1 D2 D3 D4 D5 D6 D7 D8 D9 CLR GND CLK EN Q9 Q8 Q7 Q6 Q5 Q4 Q3 Q2 Q1 VCC"),
    # TI CDC341 (DW): Y1-Y4 are bank 1, Y5-Y8 bank 2; 1G, 2G high enable;
    # P0, P1 factory pins to ground
    "clkdrv": ("VCC =VCC =VCC A =GND =GND VCC Y8 Y7 GND GND Y6 Y5 GND Y4 Y3 GND Y2 Y1 VCC"),
    # JEDEC 32-pin 1 Mbit flash (SST39SF010A, PDIP and PLCC)
    "flash": ("NC A16 A15 A12 A7 A6 A5 A4 A3 A2 A1 A0 D0 D1 D2 GND "
              "D3 D4 D5 D6 D7 CE A10 OE A11 A9 A8 A13 A14 NC WE VCC"),
    # JEDEC 32-pin 4 Mbit flash (SST39SF040, PDIP and PLCC): the 1 Mbit
    # part's pins, A18 on pin 1 and A17 on pin 30
    "flash4": ("A18 A16 A15 A12 A7 A6 A5 A4 A3 A2 A1 A0 D0 D1 D2 GND "
               "D3 D4 D5 D6 D7 CE A10 OE A11 A9 A8 A13 A14 A17 WE VCC"),
    # a push button to ground: a 6 mm tactile switch, whose footprint has
    # each of its two terminals on two pads
    "button": "OUT GND",
    # CY22393 (Cypress 38-07186 Rev. *N, figure 1 and the pin definitions,
    # 16-pin TSSOP): a 3.3 V part, VDD and AVDD on a 3.3 V rail; OE is
    # SHUTDOWN/OE, SDAT and SCLK the serial port (S0 and S1 at start-up),
    # S2 the frequency select's bit 2. A TSSOP-to-DIP adapter keeps the
    # numbering
    "cy22393": "CLKC VDD GND XTALIN XTALOUT XBUF CLKD CLKE CLKB CLKA GND SDAT SCLK AVDD S2 OE",
    # LM1117-3.3 (TI SNOS412): SOT-223 and TO-220 both 1 GND, 2 the output
    # (the tab), 3 the input
    "ldo33": "GND OUT VCC",
    # two-terminal parts
    "rpull": "A R", "cap": "A B", "capbulk": "A B", "xtal": "X1 X2",
    # JEDEC 28-pin 32K x 8 SRAM (AS7C256A, AS6C62256: SOJ, PDIP)
    "sram": ("A14 A12 A7 A6 A5 A4 A3 A2 A1 A0 IO0 IO1 IO2 GND "
             "IO3 IO4 IO5 IO6 IO7 CE A10 OE A11 A9 A8 A13 WE VCC"),
    # JEDEC 32-pin 512K x 8 SRAM (AS6C4008: SOP, PDIP)
    "sram512": ("A18 A16 A14 A12 A7 A6 A5 A4 A3 A2 A1 A0 IO0 IO1 IO2 GND "
                "IO3 IO4 IO5 IO6 IO7 CE A10 OE A11 A9 A8 A13 WE A17 A15 VCC"),
    # TL7705A: REF and CT get capacitors; RESIN and SENSE to VCC
    "por": "=CREF =VCC =CT GND RST NC =VCC VCC",
    # a canned oscillator, 4 pads: enable, ground, output, supply
    "osc": "=VCC GND OUT VCC",
    # 8 pull-ups in a 9-pin SIP network: pin 1 common
    "pullup": "VCC P1 P2 P3 P4 P5 P6 P7 P8",
    # 82C54 (PDIP, SOIC)
    "82c54": ("D7 D6 D5 D4 D3 D2 D1 D0 CLK0 OUT0 GATE0 GND OUT1 GATE1 CLK1 GATE2 "
              "OUT2 CLK2 A0 A1 CS RD WR VCC"),
    # 22V10 (Microchip/Atmel ATF22V10C, doc0735, figure 2-2, DIP and SOIC):
    # CLK/IN, ten inputs, GND, an input, ten I/O pins. The macrocells'
    # product terms (8, 10, ..., 16, 16, ..., 8, infra/hw/gal.py) are
    # symmetric, so IO0-IO9 on pins 14-23 fit as gal.py fits them. The
    # PLCC-28 has its own numbering, not here
    "22v10": ("CLK I1 I2 I3 I4 I5 I6 I7 I8 I9 I10 GND I11 "
              "IO0 IO1 IO2 IO3 IO4 IO5 IO6 IO7 IO8 IO9 VCC"),
    # TL16C550C, N package (TI SLLS177I, table 4-1). RD and WR are RD1 and
    # WR1 (active low), RD2 and WR2 tied to their inactive level, ADS low
    # (the address and selects not latched). The serial side (SIN, SOUT,
    # RCLK, which the board ties to BAUDOUT, the modem inputs) isn't in the
    # netlist: those pads get no net until it is. The FN (PLCC-44) package
    # has its own numbering, not here
    "16c550": ("D0 D1 D2 D3 D4 D5 D6 D7 RCLK SIN SOUT CS0 CS1 CS2 BAUDOUT XIN XOUT "
               "WR =GND GND RD =GND DDIS TXRDY =GND A2 A1 A0 RXRDY INTR OUT2 RTS DTR "
               "OUT1 MR CTS DSR DCD RI VCC"),
}

PINOUTS = {k: v.split() for k, v in PINOUTS.items()}

# Pins where the logical model's names come from KiCad's symbol for the
# check (check.py): our name -> KiCad's pin name, per type. Gate packages
# are checked by unit instead (which pins make a gate, and which is the
# output).
KICAD_SYMBOLS = {
    "74": "74xx:74LS74", "109": "74xx:74LS109", "138": "74xx:74LS138",
    "148": "74xx:74LS148", "151": "74xx:74LS151", "153": "74xx:74LS153",
    "157": "74xx:74LS157", "161": "74xx:74LS161", "163": "74xx:74LS163",
    "175": "74xx:74LS175", "181": "74xx:74LS181", "182": "74xx:74LS182",
    "245": "74xx:74LS245", "299": "74xx:74LS299", "377": "74xx:74LS377",
    "540": "74xx:74LS540", "541": "74xx:74LS541", "574": "74xx:74LS574",
    "688": "74xx:74LS688", "521": "74xx:74LS688",
    "00": "74xx:74LS00", "02": "74xx:74LS02", "04": "74xx:74LS04", "05": "74xx:74LS05",
    "08": "74xx:74LS08", "10": "74xx:74LS10", "11": "74xx:74LS11", "14": "74xx:74LS14",
    "20": "74xx:74LS20", "21": "74xx:74LS21", "27": "74xx:74LS27", "30": "74xx:74LS30",
    "32": "74xx:74LS32", "86": "74xx:74LS86", "125": "74xx:74LS125", "132": "74xx:74LS132",
    "flash": "Memory_Flash:SST39SF010", "flash4": "Memory_Flash:SST39SF040",
    "sram512": "Memory_RAM:AS6C4008-55PCN",
    "sram": "Memory_RAM:IS62C256AL", "82c54": "Timer:82C54",
    "534": "74xx:74LS374",            # the 534 has the 374's pins
    "por": "Power_Supervisor:TL7705A",
}

# Our pin name -> KiCad's, where they differ only by naming convention.
def kicad_pin_name(typ, pin):
    if typ in ("74",):
        return {"CLR": "~{R}", "PRE": "~{S}", "CLK": "C", "D": "D", "Q": "Q", "QN": "~{Q}"}[pin[1:]]
    if typ == "109":
        return {"CLR": "~{R}", "PRE": "~{S}", "CLK": "C", "J": "J", "K": "~{K}", "Q": "Q",
                "QN": "~{Q}"}[pin[1:]]
    if typ == "138":
        return {"A": "A0", "B": "A1", "C": "A2", "G1": "E3", "G2A": "E1",
                "G2B": "E2"}.get(pin) or f"O{pin[1]}"
    if typ == "148":
        if pin == "I0":
            return "IO"                 # sic: KiCad's 74LS148 has the letter O
        if pin[0] == "I":
            return pin
        return {"EI": "EI", "A0": "S0", "A1": "S1", "A2": "S2", "GS": "GS", "EO": "EO"}[pin]
    if typ == "151":
        return {"A": "S0", "B": "S1", "C": "S2", "G": "~{E}", "Y": "Z", "W": "~{Z}"}.get(
            pin) or f"I{pin[1]}"
    if typ == "153":
        if pin in ("A", "B"):
            return {"A": "S0", "B": "S1"}[pin]
        ab = "ab"[int(pin[0]) - 1]
        return {"G": f"E{ab}", "Y": f"Z{ab}"}.get(pin[1:]) or f"I{pin[2]}{ab}"
    if typ == "157":
        if pin in ("S", "G"):
            return {"S": "S", "G": "E"}[pin]
        x = "abcd"[int(pin[0]) - 1]
        return {"A": f"I0{x}", "B": f"I1{x}", "Y": f"Z{x}"}[pin[1]]
    if typ in ("161", "163"):
        return {"CLR": "~{MR}", "CLK": "CP", "LOAD": "~{PE}", "ENP": "CEP", "ENT": "CET",
                "RCO": "TC", "A": "D0", "B": "D1", "C": "D2", "D": "D3", "QA": "Q0", "QB": "Q1",
                "QC": "Q2", "QD": "Q3"}[pin]
    if typ == "175":
        if pin in ("CLR", "CLK"):
            return {"CLR": "~{Mr}", "CLK": "Cp"}[pin]
        n = int(pin[0]) - 1
        return {"D": f"D{n}", "Q": f"Q{n}", "QN": f"~{{Q{n}}}"}[pin[1:]]
    if typ == "181":
        return {"CN": "Cn", "AEQB": "A=B", "P": "X", "G": "Y", "CN4": "Cn+4"}.get(pin, pin)
    if typ == "182":
        return {"CN": "Cn", "CNX": "Cn+x", "CNY": "Cn+y", "CNZ": "Cn+z"}.get(pin, pin)
    if typ == "245":
        if pin in ("DIR", "OE"):
            return {"DIR": "A->B", "OE": "CE"}[pin]
        return f"{pin[0]}{int(pin[1:]) - 1}"
    if typ == "299":
        return {"MR": "Mr", "CP": "Cp", "DS0": "Ds0", "DS7": "Ds7", "Q0S": "Q0",
                "Q7S": "Q7"}.get(pin, pin)
    if typ == "377":
        if pin in ("EN", "CLK"):
            return {"EN": "~{E}", "CLK": "CP"}[pin]
        return f"{pin[0]}{int(pin[1:]) - 1}"
    if typ in ("540", "541"):
        if pin in ("OE1", "OE2"):
            return {"OE1": "G1", "OE2": "G2"}[pin]
        return f"{pin[0]}{int(pin[1:]) - 1}"
    if typ == "574":
        if pin in ("OE", "CLK"):
            return {"OE": "OE", "CLK": "Cp"}[pin]
        return f"{pin[0]}{int(pin[1:]) - 1}"
    if typ in ("688", "521"):
        return {"G": "G", "PEQ": "P=R"}.get(pin) or (pin if pin[0] == "P" else f"R{pin[1]}")
    if typ in ("flash", "flash4"):
        return {"WE": "PGM"}.get(pin, pin)
    if typ == "sram":
        if pin.startswith("IO"):
            return f"I/O{pin[2:]}"
        return {"CE": "~{CE}", "OE": "~{OE}", "WE": "~{WE}", "VCC": "VDD"}.get(pin, pin)
    if typ == "82c54":
        if pin.startswith("GATE"):
            return f"G{pin[4:]}"
        return {"CS": "~{CS}", "RD": "~{RD}", "WR": "~{WR}"}.get(pin, pin)
    if typ == "534":
        if pin in ("OE", "CLK"):
            return {"OE": "OE", "CLK": "Cp"}[pin]
        return f"{'O' if pin[0] == 'Q' else 'D'}{int(pin[1:]) - 1}"
    if typ == "sram512":
        if pin.startswith("IO"):
            return f"DQ{pin[2:]}"
        return {"CE": "CE#", "OE": "OE#", "WE": "WE#", "GND": "VSS"}.get(pin, pin)
    if typ == "por":
        return {"RST": "~{RESET}", "GND": "GND", "VCC": "VCC"}[pin]
    raise KeyError((typ, pin))


def pin_numbers(typ):
    """{logical pin: package pin number} for a chip type, the supply pins
    as {"VCC": [..], "GND": [..]} under their own keys, and the tied
    pins under "=VCC"/"=GND" and the like."""
    out = {}
    for i, name in enumerate(PINOUTS[typ], 1):
        if name in ("VCC", "GND", "NC") or name.startswith("="):
            out.setdefault(name, []).append(i)
        else:
            if name in out:
                raise ValueError(f"{typ}: pin {name} twice")
            out[name] = i
    return out


# ---- packages and footprints ------------------------------------------------------

# The package of each chip type, in the DIP world: pins and row spacing
# (mils). A board style maps each to a footprint.
DIP_PACKAGE = {
    **{t: "DIP14" for t in ("00", "02", "04", "05", "08", "10", "11", "14", "20", "21", "27",
                            "30", "32", "74", "86", "125", "132")},
    **{t: "DIP16" for t in ("109", "138", "148", "151", "153", "157", "161", "163", "175",
                            "182")},
    **{t: "DIP20" for t in ("245", "299", "377", "540", "541", "573", "574", "534", "688", "521",
                            "clkdrv")},
    "823": "DIP24", "181": "DIP24W", "82c54": "DIP24W", "22v10": "DIP24", "16c550": "DIP40W",
    "sram": "DIP28", "flash": "DIP32W", "flash4": "DIP32W", "sram512": "DIP32W",
    "por": "DIP8", "osc": "OSC", "pullup": "SIP9", "button": "BUTTON",
    "cy22393": "DIP16", "ldo33": "TO220", "rpull": "RES", "cap": "CAP", "capbulk": "CAPBULK",
    "xtal": "XTAL",
}

FP = {
    "dip": {
        "DIP8": "Package_DIP:DIP-8_W7.62mm",
        "DIP14": "Package_DIP:DIP-14_W7.62mm",
        "DIP16": "Package_DIP:DIP-16_W7.62mm",
        "DIP20": "Package_DIP:DIP-20_W7.62mm",
        "DIP24": "Package_DIP:DIP-24_W7.62mm",
        "DIP24W": "Package_DIP:DIP-24_W15.24mm",
        "DIP28": "Package_DIP:DIP-28_W7.62mm",
        "DIP32W": "Package_DIP:DIP-32_W15.24mm",
        "DIP40W": "Package_DIP:DIP-40_W15.24mm",
        "OSC": "Oscillator:Oscillator_DIP-14",
        "SIP9": "Resistor_THT:R_Array_SIP9",
        "CAP": "Capacitor_THT:C_Disc_D3.0mm_W1.6mm_P2.50mm",
        "CAPBULK": "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm",
        "BUTTON": "Button_Switch_THT:SW_PUSH_6mm",
        "TO220": "Package_TO_SOT_THT:TO-220-3_Vertical",
        "RES": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
        "XTAL": "Crystal:Crystal_HC49-U_Vertical",
    },
    "smd": {
        "DIP8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        "DIP14": "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
        "DIP16": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
        "DIP20": "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
        "DIP24": "Package_SO:SOIC-24W_7.5x15.4mm_P1.27mm",
        # the 74LS181 and 74S182 are new-old-stock, in DIP only
        "DIP24W": "Package_DIP:DIP-24_W15.24mm",
        "DIP28": "Package_SO:SOJ-28_7.62x18.415mm_P1.27mm",
        "DIP32W": "Package_SO:SOP-32_11.305x20.495mm_P1.27mm",
        # the 16C550's PLCC-44 numbers its pins differently: in DIP here too
        "DIP40W": "Package_DIP:DIP-40_W15.24mm",
        "PLCC32": "Package_LCC:PLCC-32_11.4x14.0mm_P1.27mm",
        "OSC": "Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm",
        "SIP9": "Resistor_SMD:R_Array_Convex_4x0603",
        "CAP": "Capacitor_SMD:C_0603_1608Metric",
        "CAPBULK": "Capacitor_SMD:C_1206_3216Metric",
        "BUTTON": "Button_Switch_THT:SW_PUSH_6mm",
        "TSSOP16": "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
        "SOT223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
        "RES": "Resistor_SMD:R_0603_1608Metric",
        "XTAL": "Crystal:Crystal_SMD_HC49-SD",
    },
}

# per style, chip types whose package differs from DIP_PACKAGE's choice
OVERRIDES = {
    "smd": {"flash": "PLCC32", "flash4": "PLCC32", "182": "DIP16THT", "cy22393": "TSSOP16",
            "ldo33": "SOT223"},
    "dip": {},
}
FP["smd"]["DIP16THT"] = "Package_DIP:DIP-16_W7.62mm"

# oscillator pads differ between the DIP-14 can and the SMD part
OSC_PADS = {"dip": {1: "=VCC", 7: "GND", 8: "OUT", 14: "VCC"}}


# Board-to-board IDC headers (boxed, 0.1"), by pins: two rows, pin 1 and
# the odd pins in one, the even pins in the other, so that wire k of a
# ribbon cable is on pin k. A header's pin map is its nets (the connectors
# of physical.parts), not a pinout
IDC_HEADERS = {n: f"Connector_IDC:IDC-Header_2x{n // 2}_P2.54mm_Vertical" for n in (40, 50, 64)}


def footprint_for(typ, style):
    pkg = OVERRIDES.get(style, {}).get(typ) or DIP_PACKAGE[typ]
    return FP[style][pkg]


def pad_map(typ, style):
    """{pad number (str): logical name}, with VCC, GND, NC and =RAIL
    entries, for a chip type in a style."""
    if typ == "osc" and style in OSC_PADS:
        return {str(k): v for k, v in OSC_PADS[style].items()}
    return {str(i): name for i, name in enumerate(PINOUTS[typ], 1)}
