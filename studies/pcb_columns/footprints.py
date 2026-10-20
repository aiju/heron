"""The footprints this study uses, from KiCad's library.

infra/pcb reads footprints from a KiCad installation (kicadlib). Where
there is none, fetch() downloads the few this study needs from KiCad's
footprint repository, at a fixed tag, into build/kicad/footprints/, and
use() points kicadlib there. They are build output, not committed: the
library is CC-BY-SA, with an exception for designs that use it.
"""

import os
import urllib.request

from heron import ROOT
from heron.infra.pcb import kicadlib

TAG = "9.0.0"
URL = "https://gitlab.com/kicad/libraries/kicad-footprints/-/raw/{tag}/{lib}.pretty/{name}.kicad_mod"
DIR = os.path.join(ROOT, "build", "kicad", "footprints")

# the DIPs in each pad style (DIP_STYLES), narrow and wide
DIPS = [f"DIP-{n}_W7.62mm" for n in (8, 14, 16, 20, 24, 28)] + \
       [f"DIP-{n}_W15.24mm" for n in (24, 28, 32, 40)]
DIP_STYLES = {"round": "", "long": "_LongPads", "socket": "_Socket",
              "socket-long": "_Socket_LongPads"}

OTHERS = [
    "Package_SO:SOJ-28_7.62x18.415mm_P1.27mm",
    "Package_SO:SOJ-36_10.16x23.495mm_P1.27mm",
    "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
    "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
    "Package_LCC:PLCC-32_THT-Socket",
    "Oscillator:Oscillator_DIP-14",
    "Oscillator:Oscillator_DIP-8",
    "Resistor_THT:R_Array_SIP9",
    "Capacitor_SMD:C_0805_2012Metric",
    "Capacitor_THT:C_Disc_D3.0mm_W1.6mm_P2.50mm",     # the "dip" style's, replaced
    "Connector_DIN:DIN41612_C_3x32_Male_Horizontal_THT",
    "MountingHole:MountingHole_2.7mm_M2.5",
    "Fiducial:Fiducial_1mm_Mask3mm",
]


def names():
    out = [f"Package_DIP:{d}{s}" for d in DIPS for s in DIP_STYLES.values()]
    return out + OTHERS


def _installed():
    return os.path.isdir(kicadlib._dir("FOOTPRINT"))


def fetch(quiet=False, extra=()):
    """Download the footprints not yet in build/kicad/footprints/, and
    `extra` (another study's) too."""
    for full in names() + list(extra):
        lib, name = full.split(":", 1)
        path = os.path.join(DIR, f"{lib}.pretty", f"{name}.kicad_mod")
        if os.path.exists(path):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        url = URL.format(tag=TAG, lib=lib, name=name)
        if not quiet:
            print(f"fetching {full}")
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)


def use(extra=()):
    """Make kicadlib read footprints from KiCad's installation if there is
    one, else from build/kicad/footprints/, fetching them (and `extra`)
    first."""
    if _installed():
        return
    fetch(quiet=True, extra=extra)
    os.environ["KICAD9_FOOTPRINT_DIR"] = DIR


def available(extra=()):
    """Whether the footprints (and `extra`) can be read without fetching
    anything."""
    return _installed() or all(
        os.path.exists(os.path.join(DIR, f"{n.split(':')[0]}.pretty", f"{n.split(':')[1]}.kicad_mod"))
        for n in names() + list(extra))
