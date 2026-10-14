"""Build infra/hw/timing.json from the datasheet research in infra/hw/datasheets/.

The research files keep each datasheet's own arc names and conditions.
This script maps them onto the delay names used by infra/hw/chips.py and
the simulator's models, and picks one value per corner:

  max  datasheet maximum (-40..85 C, 4.5 V, 50 pF for HCT/ACT; the 74F
       commercial-range maximum; for 74LS/74S the 25 C maximum, which is
       all TI gives)
  typ  25 C typical. For HCT the 4.5 V / 50 pF typical where given, else
       the 5 V / 15 pF one. Where a datasheet gives no typical, typ is
       estimated as a fraction of max (listed under "estimated").

Memories only have guaranteed maxima, so both corners use them.

timing_bus.json (the parts of the cards on the system bus: 74F, 74ABT,
devices) already uses these delay names, so its entries are taken as they
are: max and typ per delay (typ estimated from max where missing), checks.
A part the other files already have keeps their numbers (74HCT245, 74HCT20),
so adding the bus parts doesn't move earlier designs' results.

Run: python3 -m heron.infra.hw.build_timing
"""

import json
import os

HERE = os.path.dirname(__file__)
DS = os.path.join(HERE, "datasheets")

# my delay name -> list of candidate research arc names (max over all that exist)
LOGIC_MAP = {
    "00": {"A->Y": ["A->Y"]}, "02": {"A->Y": ["A->Y"]}, "04": {"A->Y": ["A->Y"]},
    "08": {"A->Y": ["A->Y"]}, "10": {"A->Y": ["A->Y"]}, "21": {"A->Y": ["A->Y"]},
    "30": {"A->Y": ["A->Y"]}, "32": {"A->Y": ["A->Y"]}, "86": {"A->Y": ["A->Y"]},
    "74": {"CLK->Q": ["CLK->Q"], "PRE/CLR->Q": ["/PRE,/CLR->Q"]},
    "138": {"A->Y": ["A->Y"], "G->Y": ["G1->Y", "/G2A,/G2B->Y"]},
    "151": {"D->Y": ["data->Y"], "D->W": ["data->W"], "S->Y": ["select->Y"],
            "S->W": ["select->W"], "G->Y": ["/G->Y", "/G->W"]},
    "153": {"C->Y": ["data->Y"], "S->Y": ["select->Y"], "G->Y": ["/G->Y"]},
    "157": {"A->Y": ["data->Y"], "S->Y": ["select->Y"], "G->Y": ["/G->Y"]},
    "161": {"CLK->Q": ["CLK->Q"], "CLK->RCO": ["CLK->RCO"], "ENT->RCO": ["ENT->RCO"],
            "CLR->Q": ["/CLR->Q", "/CLR->RCO"]},
    "163": {"CLK->Q": ["CLK->Q"], "CLK->RCO": ["CLK->RCO"], "ENT->RCO": ["ENT->RCO"]},
    "175": {"CLK->Q": ["CLK->Q,/Q"], "CLR->Q": ["/CLR->Q", "/CLR->/Q", "/CLR->Q,/Q"]},
    "377": {"CLK->Q": ["CLK->Q"]},
    "541": {"A->Y": ["A->Y"], "OE->Y en": ["/OE->Y enable"], "OE->Y dis": ["/OE->Y disable"]},
    "688": {"P->PEQ": ["P,Q->/P=Q"], "G->PEQ": ["/G->/P=Q"]},
    "299": {"CLK->Q": ["CLK->I/O"], "CLK->QS": ["CLK->Q0,Q7"], "CLR->Q": ["/CLR->I/O", "/CLR->Q0,Q7"],
            "OE->Y en": ["/OE->I/O enable", "S0,S1->I/O enable_est"],
            "OE->Y dis": ["/OE->I/O disable", "S0,S1->I/O disable_est"]},
}
LOGIC_CHECKS = {
    "74": {"setup D": ["setup D->CLK"], "hold D": ["hold D->CLK"]},
    "161": {"setup data": ["setup D->CLK"], "hold data": ["hold D->CLK"],
            "setup LOAD": ["setup /LOAD->CLK"], "hold LOAD": ["hold /LOAD->CLK", "hold /LOAD->CLK_est"],
            "setup EN": ["setup ENP,ENT->CLK", "setup ENP,ENT->CLK_est"], "hold EN": ["hold ENP,ENT->CLK"]},
    "163": {"setup data": ["setup D->CLK"], "hold data": ["hold D->CLK"],
            "setup LOAD": ["setup /LOAD->CLK"], "hold LOAD": ["hold /LOAD->CLK"],
            "setup EN": ["setup ENP,ENT->CLK"], "hold EN": ["hold ENP,ENT->CLK"],
            "setup CLR": ["setup /CLR->CLK"], "hold CLR": ["hold /CLR->CLK"]},
    "175": {"setup D": ["setup D->CLK"], "hold D": ["hold D->CLK"]},
    "377": {"setup D": ["setup D->CLK"], "hold D": ["hold D->CLK"],
            "setup EN": ["setup /EN->CLK"], "hold EN": ["hold /EN->CLK"]},
    "299": {"setup S": ["setup S0,S1->CLK"], "hold S": ["hold S0,S1->CLK"],
            "setup DS": ["setup DS0,DS7->CLK"], "hold DS": ["hold DS0,DS7->CLK"],
            "setup IO": ["setup I/O->CLK"], "hold IO": ["hold I/O->CLK"]},
}

ALU_MAP = {
    "181": {
        "AB->F": ["AnyA/B->AnyF (M=0 sum)", "AnyA/B->AnyF (M=0 diff)",
                  "AnyA/B->AnyF (M=0 sum)_est", "AnyA/B->AnyF (M=0 diff)_est"],
        "AB->F logic": ["Ai/Bi->Fi (M=1 logic)", "A/B->F (M=1 logic)"],
        "AB->P": ["A/B->P (M=0 sum)", "A/B->P (M=0 diff)"],
        "AB->G": ["A/B->G (M=0 sum)", "A/B->G (M=0 diff)"],
        "AB->CN4": ["A/B->Cn+4 (M=0 sum)", "A/B->Cn+4 (M=0 diff)"],
        "AB->AEQB": ["A/B->A=B (M=0 diff)"],
        "CN->F": ["Cn->F (M=0 sum or diff)", "Cn->F (M=0 any)"],
        "CN->CN4": ["Cn->Cn+4"],
        "M->F": ["M->F_est"],
    },
    "182": {
        "PG->CN": ["Gn/Pn->Cn+x/y/z", "P0-P2->Cn+x/y/z", "G0-G2->Cn+x/y/z"],
        "CN->CN": ["Cn->Cn+x/y/z"],
        "P->P": ["Pn->P"],
        "PG->G": ["Gn/Pn->G", "P1-P3->G", "Gn->G"],
    },
}

SRAM_DELAYS = ["tAA", "tACE", "tOE", "tOHZ", "tCHZ", "tWHZ"]
SRAM_CHECKS = ["tAS", "tAW", "tWP", "tDW", "tDH", "tWR", "tAH"]
ROM_DELAYS = ["tACC", "tCE", "tOE", "tDF"]

TYP_FRACTION = {"HCT": 0.5, "ACT": 0.6, "F": 0.6, "ABT": 0.6}


def arc_value(arc, corner, family):
    """(value, estimated?) for one research arc entry."""
    if corner == "max":
        if "max_com" in arc:
            return arc["max_com"], False
        return arc.get("max"), False
    if family == "HCT" and arc.get("typ_4V5_50pF") is not None:
        return arc["typ_4V5_50pF"], False
    if arc.get("typ") is not None:
        return arc["typ"], False
    m = arc.get("max_com", arc.get("max"))
    if m is None:
        return None, False
    return round(m * TYP_FRACTION.get(family, 0.6), 1), True


def build():
    logic = json.load(open(os.path.join(DS, "timing_logic.json")))
    alumem = json.load(open(os.path.join(DS, "timing_alu_mem.json")))
    out = {"_about": __doc__.strip().splitlines()[0] + " Generated by infra/hw/build_timing.py."}

    for part, entry in logic.items():
        if part.startswith("_"):
            continue
        fam = "HCT" if "HCT" in part else "ACT"
        typ = part.replace("74HCT", "").replace("74ACT", "")
        if typ not in LOGIC_MAP or not entry.get("arcs"):
            continue
        delays, est = {}, []
        for name, cands in LOGIC_MAP[typ].items():
            vals = {}
            for corner in ("typ", "max"):
                best = None
                for c in cands:
                    if c in entry["arcs"]:
                        v, e = arc_value(entry["arcs"][c], corner, fam)
                        if v is not None and (best is None or v > best[0]):
                            best = (v, e)
                if best:
                    vals[corner] = best[0]
                    if best[1]:
                        est.append(f"{name} typ")
            if vals:
                delays[name] = vals
        checks = {}
        for name, cands in LOGIC_CHECKS.get(typ, {}).items():
            vs = [entry["checks"][c] for c in cands if c in entry.get("checks", {})]
            if vs:
                checks[name] = max(vs)
                if any(c.endswith("_est") and c in entry["checks"] for c in cands):
                    est.append(name)
        out[part] = {"delays": delays, "checks": checks, "source": entry.get("source"),
                     "part_number": entry.get("part_number"), "estimated": est}

    for part, entry in alumem.items():
        if part.startswith("_") or "_" in part:
            continue
        if "181" in part or "182" in part:
            typ = "181" if "181" in part else "182"
            if not entry.get("arcs"):
                continue
            fam = "LS" if "LS" in part else ("F" if "74F" in part else "S")
            delays, est = {}, []
            for name, cands in ALU_MAP[typ].items():
                vals = {}
                for corner in ("typ", "max"):
                    best = None
                    for c in cands:
                        if c in entry["arcs"]:
                            v, e = arc_value(entry["arcs"][c], corner, fam)
                            if v is not None and (best is None or v > best[0]):
                                best = (v, e)
                    if best:
                        vals[corner] = best[0]
                if vals:
                    delays[name] = vals
                    if any(c.endswith("_est") for c in cands if c in entry["arcs"]):
                        est.append(name)
            if typ == "181":
                # select inputs feed the same first-level gates as A/B (research note)
                delays["S->F"] = dict(delays["AB->F"])
                est.append("S->F")
            out[part] = {"delays": delays, "checks": {}, "source": entry.get("source"),
                         "estimated": est}
        else:
            params = dict(entry.get("params", {}))
            params.update(entry.get("write", {}))
            names = ROM_DELAYS if "SST" in part or "AT28" in part else SRAM_DELAYS
            delays = {}
            for n in names:
                p = params.get(n)
                if p and "max" in p:
                    delays[n] = {"typ": p["max"], "max": p["max"]}
            if "tDF" in names and "tDF" not in delays:
                for alt in ("tOHZ", "tCHZ"):
                    if alt in params and "max" in params[alt]:
                        delays["tDF"] = {"typ": params[alt]["max"], "max": params[alt]["max"]}
            checks = {}
            for n in SRAM_CHECKS + ["tOH"]:
                p = params.get(n)
                if p and "min" in p:
                    checks[n] = p["min"]
            out[part] = {"delays": delays, "checks": checks, "source": entry.get("source"),
                         "estimated": []}
    bus_path = os.path.join(DS, "timing_bus.json")
    if os.path.exists(bus_path):
        for part, entry in json.load(open(bus_path)).items():
            if part.startswith("_") or part in out:
                continue
            fam = entry.get("family", "")
            delays, est = {}, list(entry.get("estimated", []))
            for name, arc in entry.get("delays", {}).items():
                vals = {}
                for corner in ("typ", "max"):
                    v, e = arc_value(arc, corner, fam)
                    if v is not None:
                        vals[corner] = v
                        if e:
                            est.append(f"{name} typ")
                if "min" in arc:
                    vals["min"] = arc["min"]
                if vals:
                    delays[name] = vals
            out[part] = {"delays": delays, "checks": dict(entry.get("checks", {})),
                         "source": entry.get("source"), "part_number": entry.get("part_number"),
                         "estimated": est}
    return out


if __name__ == "__main__":
    data = build()
    path = os.path.join(HERE, "timing.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    print(f"wrote {path}: {len(data) - 1} parts")
