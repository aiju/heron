"""Chip library: pins, timing arcs and timing checks for every part type.

Behaviour lives in the chip-level simulator (infra/hwsim/src/models.rs),
keyed by `model`. This file is the shared description of each part's pins
and timing:
  - arcs: (from pins, to pins, delay name);
  - checks: (data pins, clock pin, edge, setup name, hold name) for
    sequential parts.
The arcs and checks are documentation (only their pin names are checked):
neither tool reads them. The simulator's models and static timing analysis
(sta.py, Case.m_<model>) each encode which named delay applies between
which pins.
Both take the delay values per part number from infra/hw/timing.json, via
delays_for().

The static timing engine (infra/sta, RFC 0048) reads a type's timing as
data instead: outputs, regs, timing (its checks), sensitive, asynchronous
and joins, in cells.py's vocabulary. A type without them is untimed there.

Pin kinds: 'in', 'out', 'tri' (three-state output), 'io' (bidirectional),
'pull' (a pull-up resistor to VCC: a weak driver of 1).

Families: 'logic' (74HCT/ACT, or a family the netlist names), 'alu'
(74LS/F/S), 'mem', 'device' (UART, timer, CF card), 'osc' (canned
oscillators), 'misc' (a supply supervisor), 'passive' (resistor
networks), 'fixture' (test equipment, not on any board).
"""

import json
import os

from . import cells
from .cells import Arc, Latch, Out, Period, Recovery, Reg, Setup, Strobe, Width


class ChipType:
    def __init__(self, name, model, pins, arcs=(), checks=(), family="logic", desc="",
                 per_package=1, tied=(), outputs=None, regs=None, timing=(), sensitive=(),
                 asynchronous=(), joins=(), latches=None):
        self.name = name
        self.model = model
        self.pins = pins            # list of (name, kind)
        self.pin_index = {p: i for i, (p, _) in enumerate(pins)}
        self.arcs = list(arcs)      # (from list, to list, delay name)
        self.checks = list(checks)  # (data list, clock pin, edge 'rise'/'fall', setup, hold)
        self.family = family        # 'logic' (74HCT/ACT), 'alu' (74LS/F/S), 'mem', 'fixture'
        self.desc = desc
        self.per_package = per_package  # a part of a package: two halves of a 16-bit part
        # pin groups the model treats as one: the netlist must put each on one net
        self.tied = list(tied)
        for frm, to, _ in self.arcs:
            for p in list(frm) + list(to):
                assert p in self.pin_index, (name, p)
        # the static timing engine's description (cells.py)
        self.outputs = dict(outputs or {})
        self.outputs.update({pin: latch.out(pin) for pin, latch in (latches or {}).items()})
        self.regs = dict(regs or {})
        self.timing = list(timing)
        self.sensitive = list(sensitive)
        self.asynchronous = list(asynchronous)
        self.joins = list(joins)
        try:
            cells.check(self)
        except ValueError as e:
            raise ValueError(f"chip type {name}: {e}") from None

    def kind(self, pin):
        return self.pins[self.pin_index[pin]][1]


TYPES = {}


def T(*a, **kw):
    t = ChipType(*a, **kw)
    TYPES[t.name] = t
    return t


def gate_type(name, model, n_sections, n_inputs, desc, out_kind="out"):
    pins, arcs, outputs = [], [], {}
    letters = "ABCDEFGH"
    for s in range(1, n_sections + 1):
        ins = [f"{s}{letters[i]}" for i in range(n_inputs)] if n_sections > 1 else \
              [letters[i] for i in range(n_inputs)]
        out = f"{s}Y" if n_sections > 1 else "Y"
        pins += [(p, "in") for p in ins] + [(out, out_kind)]
        arcs.append((ins, [out], "A->Y"))
        outputs[out] = _gate_out(model, ins)
    return T(name, model, pins, arcs, desc=desc, outputs=outputs)


def _gate_out(model, ins):
    """A gate's output as the static timing engine sees it (cells.Out)."""
    arcs = {" ".join(ins): "A->Y"}
    if model == "nand":
        return Out(" + ".join(f"/{p}" for p in ins), arcs)
    if model == "nor":
        return Out("·".join(f"/{p}" for p in ins), arcs)
    if model == "and":
        return Out("·".join(ins), arcs)
    if model == "or":
        return Out(" + ".join(ins), arcs)
    if model == "xor":
        a, b = ins
        return Out(f"{a}·/{b} + /{a}·{b}", arcs)
    if model == "nand_oc":
        # open collector: low while A is high, else off
        return Out("0", {}, enable=ins[0], on=arcs, off=arcs)
    raise ValueError(f"no gate model {model}")


_MUX151 = "/G·(" + " + ".join(
    "·".join(("" if s >> k & 1 else "/") + "ABC"[k] for k in (2, 1, 0)) + f"·D{s}"
    for s in range(8)) + ")"


def _sram_out(addr):
    """A static RAM's data pin: valid tAA after the address (changing from
    tOH); on while CE and OE are low and WE high, valid tACE and tOE after
    CE and OE fall, off tCHZ, tOHZ and tWHZ after they change."""
    return Out(None, {addr: Arc("tAA", min="tOH")},
               enable="/CE·/OE·WE",
               on={"CE": Arc("tACE", min=0), "OE": Arc("tOE", min=0), "WE": Arc("tOE", min=0)},
               off={"CE": "tCHZ", "OE": "tOHZ", "WE": "tWHZ"})


def _sram_write(addr):
    """A static RAM's write: CE and WE low, the address stable tAS before
    it, tAW before its end and tAH after, the data set up tDW before the
    end and held tDH, at least tWP long."""
    return Strobe("/CE·/WE", stable={addr: ("tAS", "tAW", "tAH")},
                  data={"IO0-IO7": ("tDW", "tDH")}, width="tWP")


def _rom_out(addr):
    """A flash's data pin: valid tACC after the address (changing from
    tOH); on while CE and OE are low, valid tCE and tOE after they fall,
    off tDF after either rises."""
    return Out(None, {addr: Arc("tACC", min="tOH")},
               enable="/CE·/OE", on={"CE": Arc("tCE", min=0), "OE": Arc("tOE", min=0)},
               off={"CE OE": Arc("tDF", min=0)})


def _uart_out():
    """A 16C550's data pin: driven while RD and CS2 are low, valid RD->D
    after them (and after the address); off RD->D dis after."""
    return Out(None, {"A0 A1 A2": "RD->D"}, enable="/CS2·/RD",
               on={"RD CS2": Arc("RD->D", min=0)}, off={"RD CS2": "RD->D dis"})


gate_type("00", "nand", 4, 2, "quad 2-input NAND")
gate_type("02", "nor", 4, 2, "quad 2-input NOR")
gate_type("04", "nand", 6, 1, "hex inverter")
gate_type("08", "and", 4, 2, "quad 2-input AND")
gate_type("10", "nand", 3, 3, "triple 3-input NAND")
gate_type("21", "and", 2, 4, "dual 4-input AND")
gate_type("30", "nand", 1, 8, "8-input NAND")
gate_type("32", "or", 4, 2, "quad 2-input OR")
gate_type("86", "xor", 4, 2, "quad 2-input XOR")
gate_type("11", "and", 3, 3, "triple 3-input AND")
gate_type("20", "nand", 2, 4, "dual 4-input NAND")
gate_type("27", "nor", 3, 3, "triple 3-input NOR")
gate_type("132", "nand", 4, 2, "quad 2-input NAND, Schmitt-trigger inputs")
gate_type("14", "nand", 6, 1, "hex inverter, Schmitt-trigger inputs")
gate_type("05", "nand_oc", 6, 1, "hex inverter, open-collector outputs", out_kind="tri")

T("74", "dff74",
  [(f"{s}{p}", k) for s in (1, 2) for p, k in
   (("D", "in"), ("CLK", "in"), ("PRE", "in"), ("CLR", "in"), ("Q", "out"), ("QN", "out"))],
  arcs=[([f"{s}CLK"], [f"{s}Q", f"{s}QN"], "CLK->Q") for s in (1, 2)]
  + [([f"{s}PRE", f"{s}CLR"], [f"{s}Q", f"{s}QN"], "PRE/CLR->Q") for s in (1, 2)],
  checks=[([f"{s}D"], f"{s}CLK", "rise", "setup D", "hold D") for s in (1, 2)],
  desc="dual D flip-flop with preset and clear",
  regs={**{f"{s}Q": Reg(f"{s}CLK", f"{s}D", "CLK->Q", clear=f"/{s}CLR",
                           clear_arcs={f"{s}CLR": "PRE/CLR->Q"}, preset=f"/{s}PRE",
                           preset_arcs={f"{s}PRE": "PRE/CLR->Q"}) for s in (1, 2)},
        **{f"{s}QN": Reg(f"{s}CLK", f"/{s}D", "CLK->Q", clear=f"/{s}PRE",
                            clear_arcs={f"{s}PRE": "PRE/CLR->Q"}, preset=f"/{s}CLR",
                            preset_arcs={f"{s}CLR": "PRE/CLR->Q"}) for s in (1, 2)}},
  timing=[Setup(f"{s}D", f"{s}CLK", "setup D", "hold D") for s in (1, 2)]
  + [Recovery(f"{s}CLK", "recovery PRE/CLR", width="tw PRE/CLR") for s in (1, 2)],)

T("138", "dec138",
  [(p, "in") for p in ("A", "B", "C", "G1", "G2A", "G2B")] + [(f"Y{i}", "out") for i in range(8)],
  arcs=[(["A", "B", "C"], [f"Y{i}" for i in range(8)], "A->Y"),
        (["G1", "G2A", "G2B"], [f"Y{i}" for i in range(8)], "G->Y")],
  desc="3-to-8 decoder",
  outputs={f"Y{i}": Out(" + ".join(["/G1", "G2A", "G2B"]
                                   + [("/" if i >> k & 1 else "") + "ABC"[k] for k in range(3)]),
                         {"A B C": "A->Y", "G1 G2A G2B": "G->Y"}) for i in range(8)},)

T("151", "mux151",
  [(f"D{i}", "in") for i in range(8)] + [(p, "in") for p in ("A", "B", "C", "G")]
  + [("Y", "out"), ("W", "out")],
  arcs=[([f"D{i}" for i in range(8)], ["Y"], "D->Y"),
        ([f"D{i}" for i in range(8)], ["W"], "D->W"),
        (["A", "B", "C"], ["Y"], "S->Y"),
        (["A", "B", "C"], ["W"], "S->W"),
        (["G"], ["Y", "W"], "G->Y")],
  desc="8-to-1 multiplexer",
  outputs={"Y": Out(_MUX151, {"D0-D7": "D->Y", "A B C": "S->Y", "G": "G->Y"}),
           "W": Out(f"/({_MUX151})", {"D0-D7": "D->W", "A B C": "S->W", "G": "G->Y"})},)

T("153", "mux153",
  [(f"{s}C{i}", "in") for s in (1, 2) for i in range(4)] + [(p, "in") for p in ("1G", "2G", "A", "B")]
  + [("1Y", "out"), ("2Y", "out")],
  arcs=[([f"1C{i}" for i in range(4)], ["1Y"], "C->Y"),
        ([f"2C{i}" for i in range(4)], ["2Y"], "C->Y"),
        (["A", "B"], ["1Y", "2Y"], "S->Y"),
        (["1G"], ["1Y"], "G->Y"),
        (["2G"], ["2Y"], "G->Y")],
  desc="dual 4-to-1 multiplexer",
  outputs={f"{s}Y": Out(f"/{s}G·(/B·/A·{s}C0 + /B·A·{s}C1 + B·/A·{s}C2 + B·A·{s}C3)",
                          {f"{s}C0-{s}C3": "C->Y", "A B": "S->Y", f"{s}G": "G->Y"})
           for s in (1, 2)},)

T("157", "mux157",
  [("S", "in"), ("G", "in")] + [(f"{i}{x}", "in") for i in range(1, 5) for x in "AB"]
  + [(f"{i}Y", "out") for i in range(1, 5)],
  arcs=[([f"{i}A", f"{i}B"], [f"{i}Y"], "A->Y") for i in range(1, 5)]
  + [(["S"], [f"{i}Y" for i in range(1, 5)], "S->Y"),
     (["G"], [f"{i}Y" for i in range(1, 5)], "G->Y")],
  desc="quad 2-to-1 multiplexer",
  outputs={f"{i}Y": Out(f"/G·(/S·{i}A + S·{i}B)",
                          {f"{i}A {i}B": "A->Y", "S": "S->Y", "G": "G->Y"}) for i in range(1, 5)},)

for _n, _model in (("161", "cnt161"), ("163", "cnt163")):
    _arcs = [(["CLK"], ["QA", "QB", "QC", "QD"], "CLK->Q"),
             (["CLK"], ["RCO"], "CLK->RCO"),
             (["ENT"], ["RCO"], "ENT->RCO")]
    if _n == "161":
        _arcs.append((["CLR"], ["QA", "QB", "QC", "QD", "RCO"], "CLR->Q"))
    _checks = [(["A", "B", "C", "D"], "CLK", "rise", "setup data", "hold data"),
               (["LOAD"], "CLK", "rise", "setup LOAD", "hold LOAD"),
               (["ENP", "ENT"], "CLK", "rise", "setup EN", "hold EN")]
    if _n == "163":
        _checks.append((["CLR"], "CLK", "rise", "setup CLR", "hold CLR"))
    T(_n, _model,
      [(p, "in") for p in ("CLK", "CLR", "LOAD", "ENP", "ENT", "A", "B", "C", "D")]
      + [(p, "out") for p in ("QA", "QB", "QC", "QD", "RCO")],
      arcs=_arcs, checks=_checks,
      desc="4-bit binary counter, " + ("async clear" if _n == "161" else "sync clear"))

T("193", "cnt193",
  [(p, "in") for p in ("CPU", "CPD", "MR", "PL", "P0", "P1", "P2", "P3")]
  + [(p, "out") for p in ("Q0", "Q1", "Q2", "Q3", "TCU", "TCD")],
  arcs=[(["CPU", "CPD"], ["Q0", "Q1", "Q2", "Q3"], "CP->Q"),
        (["CPU", "CPD"], ["TCU", "TCD"], "CP->TC"),
        ([f"P{i}" for i in range(4)], ["Q0", "Q1", "Q2", "Q3"], "P->Q"),
        ([f"P{i}" for i in range(4)], ["TCU", "TCD"], "P->TC"),
        (["PL"], ["Q0", "Q1", "Q2", "Q3"], "PL->Q"),
        (["PL"], ["TCU", "TCD"], "PL->TC"),
        (["MR"], ["Q0", "Q1", "Q2", "Q3"], "MR->Q"),
        (["MR"], ["TCU", "TCD"], "MR->TC")],
  checks=[([f"P{i}" for i in range(4)], "PL", "rise", "setup P", "hold P")],
  desc="4-bit up/down binary counter with separate up and down clocks (PL, TCU, TCD active "
       "low; MR active high): CPU or CPD rising counts while the other is high; MR resets and "
       "PL loads P, asynchronously; TCU is CPU at 15, TCD is CPD at 0, to clock the next counter")

T("175", "dff175",
  [("CLK", "in"), ("CLR", "in")] + [(f"{i}D", "in") for i in range(1, 5)]
  + [(f"{i}{q}", "out") for i in range(1, 5) for q in ("Q", "QN")],
  arcs=[(["CLK"], [f"{i}{q}" for i in range(1, 5) for q in ("Q", "QN")], "CLK->Q"),
        (["CLR"], [f"{i}{q}" for i in range(1, 5) for q in ("Q", "QN")], "CLR->Q")],
  checks=[([f"{i}D" for i in range(1, 5)], "CLK", "rise", "setup D", "hold D")],
  desc="quad D flip-flop with clear",
  regs={**{f"{i}Q": Reg("CLK", f"{i}D", "CLK->Q", clear="/CLR", clear_arcs={"CLR": "CLR->Q"})
           for i in range(1, 5)},
        **{f"{i}QN": Reg("CLK", f"/{i}D", "CLK->Q", preset="/CLR", preset_arcs={"CLR": "CLR->Q"})
           for i in range(1, 5)}},
  timing=[Setup("1D 2D 3D 4D", "CLK", "setup D", "hold D"),
          Recovery("CLK", "recovery CLR", width="tw CLR")],)

T("377", "reg377",
  [("CLK", "in"), ("EN", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
  + [(f"Q{i}", "out") for i in range(1, 9)],
  arcs=[(["CLK"], [f"Q{i}" for i in range(1, 9)], "CLK->Q")],
  checks=[([f"D{i}" for i in range(1, 9)], "CLK", "rise", "setup D", "hold D"),
          (["EN"], "CLK", "rise", "setup EN", "hold EN")],
  desc="octal D flip-flop with enable",
  regs={f"Q{i}": Reg("CLK", f"EN·Q{i} + /EN·D{i}", "CLK->Q") for i in range(1, 9)},
  timing=[Setup("D1-D8", "CLK", "setup D", "hold D"), Setup("EN", "CLK", "setup EN", "hold EN")],)

T("541", "buf541",
  [("OE1", "in"), ("OE2", "in")] + [(f"A{i}", "in") for i in range(1, 9)]
  + [(f"Y{i}", "tri") for i in range(1, 9)],
  arcs=[([f"A{i}"], [f"Y{i}"], "A->Y") for i in range(1, 9)]
  + [(["OE1", "OE2"], [f"Y{i}" for i in range(1, 9)], "OE->Y en")],
  desc="octal three-state buffer",
  outputs={f"Y{i}": Out(f"A{i}", {f"A{i}": "A->Y"}, enable="/OE1·/OE2",
                         on={"OE1 OE2": "OE->Y en"}, off={"OE1 OE2": "OE->Y dis"})
           for i in range(1, 9)},)

T("540", "buf540",
  [("OE1", "in"), ("OE2", "in")] + [(f"A{i}", "in") for i in range(1, 9)]
  + [(f"Y{i}", "tri") for i in range(1, 9)],
  arcs=[([f"A{i}"], [f"Y{i}"], "A->Y") for i in range(1, 9)]
  + [(["OE1", "OE2"], [f"Y{i}" for i in range(1, 9)], "OE->Y en")],
  desc="octal three-state inverting buffer",
  outputs={f"Y{i}": Out(f"/A{i}", {f"A{i}": "A->Y"}, enable="/OE1·/OE2",
                         on={"OE1 OE2": "OE->Y en"}, off={"OE1 OE2": "OE->Y dis"})
           for i in range(1, 9)},)

T("688", "cmp688",
  [(f"P{i}", "in") for i in range(8)] + [(f"Q{i}", "in") for i in range(8)] + [("G", "in"), ("PEQ", "out")],
  arcs=[([f"P{i}" for i in range(8)] + [f"Q{i}" for i in range(8)], ["PEQ"], "P->PEQ"),
        (["G"], ["PEQ"], "G->PEQ")],
  desc="8-bit identity comparator",
  outputs={"PEQ": Out("G + " + " + ".join(f"P{i}·/Q{i} + /P{i}·Q{i}" for i in range(8)),
                      {"P0-P7 Q0-Q7": "P->PEQ", "G": "G->PEQ"})},)

T("521", "cmp688",
  [(f"P{i}", "in") for i in range(8)] + [(f"Q{i}", "in") for i in range(8)] + [("G", "in"), ("PEQ", "out")],
  arcs=[([f"P{i}" for i in range(8)] + [f"Q{i}" for i in range(8)], ["PEQ"], "P->PEQ"),
        (["G"], ["PEQ"], "G->PEQ")],
  desc="8-bit identity comparator (the 688's function, in 74F)",
  outputs={"PEQ": Out("G + " + " + ".join(f"P{i}·/Q{i} + /P{i}·Q{i}" for i in range(8)),
                      {"P0-P7 Q0-Q7": "P->PEQ", "G": "G->PEQ"})},)

T("181", "alu181",
  [(f"A{i}", "in") for i in range(4)] + [(f"B{i}", "in") for i in range(4)]
  + [(f"S{i}", "in") for i in range(4)] + [("M", "in"), ("CN", "in")]
  + [(f"F{i}", "out") for i in range(4)] + [("AEQB", "out"), ("P", "out"), ("G", "out"), ("CN4", "out")],
  arcs=[([f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)], [f"F{i}" for i in range(4)], "AB->F"),
        ([f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)], ["P"], "AB->P"),
        ([f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)], ["G"], "AB->G"),
        ([f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)], ["CN4"], "AB->CN4"),
        ([f"A{i}" for i in range(4)] + [f"B{i}" for i in range(4)], ["AEQB"], "AB->AEQB"),
        (["CN"], [f"F{i}" for i in range(4)] + ["AEQB"], "CN->F"),
        (["CN"], ["CN4"], "CN->CN4"),
        ([f"S{i}" for i in range(4)], [f"F{i}" for i in range(4)] + ["P", "G", "CN4", "AEQB"], "S->F"),
        (["M"], [f"F{i}" for i in range(4)] + ["AEQB"], "M->F")],
  family="alu", desc="4-bit ALU",
  outputs={**{f"F{i}": Out(None, {"A0-A3 B0-B3": [Arc("AB->F", when="/M"),
                                                      Arc("AB->F logic", when="M")],
                                      "CN": Arc("CN->F", when="/M"), "S0-S3": "S->F", "M": "M->F"})
              for i in range(4)},
           "AEQB": Out(None, {"A0-A3 B0-B3": "AB->AEQB", "CN": Arc("CN->F", when="/M"),
                              "S0-S3": "S->F", "M": "M->F"}),
           "P": Out(None, {"A0-A3 B0-B3": "AB->P", "S0-S3": "S->F"}),
           "G": Out(None, {"A0-A3 B0-B3": "AB->G", "S0-S3": "S->F"}),
           "CN4": Out(None, {"A0-A3 B0-B3": "AB->CN4", "CN": "CN->CN4", "S0-S3": "S->F"})},)

T("182", "cla182",
  [("CN", "in")] + [(f"P{i}", "in") for i in range(4)] + [(f"G{i}", "in") for i in range(4)]
  + [(p, "out") for p in ("CNX", "CNY", "CNZ", "P", "G")],
  arcs=[([f"P{i}" for i in range(4)] + [f"G{i}" for i in range(4)], ["CNX", "CNY", "CNZ"], "PG->CN"),
        (["CN"], ["CNX", "CNY", "CNZ"], "CN->CN"),
        ([f"P{i}" for i in range(4)], ["P"], "P->P"),
        ([f"P{i}" for i in range(4)] + [f"G{i}" for i in range(4)], ["G"], "PG->G")],
  family="alu", desc="carry lookahead generator",
  outputs={**{p: Out(None, {"P0-P3 G0-G3": "PG->CN", "CN": "CN->CN"}) for p in ("CNX", "CNY", "CNZ")},
           "P": Out(None, {"P0-P3": "P->P"}),
           "G": Out(None, {"P0-P3 G0-G3": "PG->G"})},)

T("sram", "sram",
  [(f"A{i}", "in") for i in range(15)] + [(f"IO{i}", "io") for i in range(8)]
  + [("CE", "in"), ("OE", "in"), ("WE", "in")],
  arcs=[([f"A{i}" for i in range(15)], [f"IO{i}" for i in range(8)], "tAA"),
        (["CE"], [f"IO{i}" for i in range(8)], "tACE"),
        (["OE"], [f"IO{i}" for i in range(8)], "tOE")],
  family="mem", desc="32K x 8 static RAM",
  outputs={f"IO{i}": _sram_out("A0-A14") for i in range(8)},
  timing=[_sram_write("A0-A14")],)

T("299", "sr299",
  [(p, "in") for p in ("S0", "S1", "OE1", "OE2", "MR", "CP", "DS0", "DS7")]
  + [(f"IO{i}", "io") for i in range(8)] + [("Q0S", "out"), ("Q7S", "out")],
  arcs=[(["CP"], [f"IO{i}" for i in range(8)], "CLK->Q"),
        (["CP"], ["Q0S", "Q7S"], "CLK->QS"),
        (["MR"], [f"IO{i}" for i in range(8)] + ["Q0S", "Q7S"], "CLR->Q"),
        (["OE1", "OE2", "S0", "S1"], [f"IO{i}" for i in range(8)], "OE->Y en")],
  checks=[(["S0", "S1"], "CP", "rise", "setup S", "hold S"),
          (["DS0", "DS7"], "CP", "rise", "setup DS", "hold DS"),
          ([f"IO{i}" for i in range(8)], "CP", "rise", "setup IO", "hold IO")],
  desc="8-bit universal shift/storage register, 3-state I/O (S1 S0: 00 hold, "
       "01 shift toward Q7 (DS0 in), 10 toward Q0 (DS7 in), 11 load from I/O)")

T("sram64k", "sram",
  [(f"A{i}", "in") for i in range(16)] + [(f"IO{i}", "io") for i in range(8)]
  + [("CE", "in"), ("OE", "in"), ("WE", "in")],
  arcs=[([f"A{i}" for i in range(16)], [f"IO{i}" for i in range(8)], "tAA"),
        (["CE"], [f"IO{i}" for i in range(8)], "tACE"),
        (["OE"], [f"IO{i}" for i in range(8)], "tOE")],
  family="mem", desc="64K x 8 static RAM: one byte of a 64K x 16 part (IS61C6416), "
                     "whose two bytes the netlist places as two of these", per_package=2,
  outputs={f"IO{i}": _sram_out("A0-A15") for i in range(8)},
  timing=[_sram_write("A0-A15")],)

T("sram512", "sram",
  [(f"A{i}", "in") for i in range(19)] + [(f"IO{i}", "io") for i in range(8)]
  + [("CE", "in"), ("OE", "in"), ("WE", "in")],
  arcs=[([f"A{i}" for i in range(19)], [f"IO{i}" for i in range(8)], "tAA"),
        (["CE"], [f"IO{i}" for i in range(8)], "tACE"),
        (["OE"], [f"IO{i}" for i in range(8)], "tOE")],
  family="mem", desc="512K x 8 static RAM",
  outputs={f"IO{i}": _sram_out("A0-A18") for i in range(8)},
  timing=[_sram_write("A0-A18")],)

# a 22V10 (GAL): ten outputs, each a sum of products of the pins
# (infra/hw/gal.py); every pin may be an input, and CLK clocks the
# registered outputs. The equations are the instance's (`gal`, `program`)
T("flash4", "rom",
  [(f"A{i}", "in") for i in range(19)] + [(f"D{i}", "tri") for i in range(8)]
  + [("CE", "in"), ("OE", "in"), ("WE", "in")],
  arcs=[([f"A{i}" for i in range(19)], [f"D{i}" for i in range(8)], "tACC"),
        (["CE"], [f"D{i}" for i in range(8)], "tCE"),
        (["OE"], [f"D{i}" for i in range(8)], "tOE")],
  family="mem", desc="512K x 8 parallel flash",
  outputs={f"D{i}": _rom_out("A0-A18") for i in range(8)},)

T("22v10", "gal", [("CLK", "io")] + [(f"I{i}", "io") for i in range(1, 12)]
  + [(f"IO{i}", "io") for i in range(10)], desc="22V10 programmable logic")

T("flash", "rom",
  [(f"A{i}", "in") for i in range(17)] + [(f"D{i}", "tri") for i in range(8)]
  + [("CE", "in"), ("OE", "in"), ("WE", "in")],
  arcs=[([f"A{i}" for i in range(17)], [f"D{i}" for i in range(8)], "tACC"),
        (["CE"], [f"D{i}" for i in range(8)], "tCE"),
        (["OE"], [f"D{i}" for i in range(8)], "tOE")],
  family="mem", desc="128K x 8 parallel flash (microcode)",
  outputs={f"D{i}": _rom_out("A0-A16") for i in range(8)},)

# ---- bus interface, clock generator and backplane parts ----

T("109", "jk109",
  [(f"{s}{p}", k) for s in (1, 2) for p, k in
   (("J", "in"), ("K", "in"), ("CLK", "in"), ("PRE", "in"), ("CLR", "in"), ("Q", "out"),
    ("QN", "out"))],
  arcs=[([f"{s}CLK"], [f"{s}Q", f"{s}QN"], "CLK->Q") for s in (1, 2)]
  + [([f"{s}PRE", f"{s}CLR"], [f"{s}Q", f"{s}QN"], "PRE/CLR->Q") for s in (1, 2)],
  checks=[([f"{s}J", f"{s}K"], f"{s}CLK", "rise", "setup JK", "hold JK") for s in (1, 2)],
  desc="dual J-K̄ flip-flop with preset and clear (K is active low)",
  regs={**{f"{s}Q": Reg(f"{s}CLK", f"{s}J·/{s}Q + {s}K·{s}Q", "CLK->Q", clear=f"/{s}CLR",
                           clear_arcs={f"{s}CLR": "PRE/CLR->Q"}, preset=f"/{s}PRE",
                           preset_arcs={f"{s}PRE": "PRE/CLR->Q"}) for s in (1, 2)},
        **{f"{s}QN": Reg(f"{s}CLK", f"/({s}J·/{s}Q + {s}K·{s}Q)", "CLK->Q", clear=f"/{s}PRE",
                            clear_arcs={f"{s}PRE": "PRE/CLR->Q"}, preset=f"/{s}CLR",
                            preset_arcs={f"{s}CLR": "PRE/CLR->Q"}) for s in (1, 2)}},
  timing=[Setup(f"{s}J {s}K", f"{s}CLK", "setup JK", "hold JK") for s in (1, 2)]
  + [Recovery(f"{s}CLK", "recovery PRE/CLR", width="tw PRE/CLR") for s in (1, 2)],)

T("574", "dreg",
  [("OE", "in"), ("CLK", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
  + [(f"Q{i}", "tri") for i in range(1, 9)],
  arcs=[(["CLK"], [f"Q{i}" for i in range(1, 9)], "CLK->Q"),
        (["OE"], [f"Q{i}" for i in range(1, 9)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 9)], "CLK", "rise", "setup D", "hold D")],
  desc="octal D flip-flop, three-state outputs",
  regs={f"Q{i}": Reg("CLK", f"D{i}", "CLK->Q", enable="/OE", on={"OE": "OE->Y en"},
                         off={"OE": "OE->Y dis"}) for i in range(1, 9)},
  timing=[Setup("D1-D8", "CLK", "setup D", "hold D"), Width("CLK", 1, "tw CLK"),
          Width("CLK", 0, "tw CLK"), Period("CLK", "fmax MHz")],)

T("534", "dreg_inv",
  [("OE", "in"), ("CLK", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
  + [(f"Q{i}", "tri") for i in range(1, 9)],
  arcs=[(["CLK"], [f"Q{i}" for i in range(1, 9)], "CLK->Q"),
        (["OE"], [f"Q{i}" for i in range(1, 9)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 9)], "CLK", "rise", "setup D", "hold D")],
  desc="octal D flip-flop, inverting three-state outputs",
  regs={f"Q{i}": Reg("CLK", f"/D{i}", "CLK->Q", enable="/OE", on={"OE": "OE->Y en"},
                         off={"OE": "OE->Y dis"}) for i in range(1, 9)},
  timing=[Setup("D1-D8", "CLK", "setup D", "hold D"), Width("CLK", 1, "tw CLK"),
          Width("CLK", 0, "tw CLK"), Period("CLK", "fmax MHz")],)

T("823", "dreg",
  [("OE", "in"), ("CLK", "in"), ("EN", "in"), ("CLR", "in")]
  + [(f"D{i}", "in") for i in range(1, 10)] + [(f"Q{i}", "tri") for i in range(1, 10)],
  arcs=[(["CLK"], [f"Q{i}" for i in range(1, 10)], "CLK->Q"),
        (["CLR"], [f"Q{i}" for i in range(1, 10)], "CLR->Q"),
        (["OE"], [f"Q{i}" for i in range(1, 10)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 10)], "CLK", "rise", "setup D", "hold D"),
          (["EN"], "CLK", "rise", "setup EN", "hold EN")],
  desc="9-bit D flip-flop with clock enable, clear and three-state outputs (EN, CLR, OE active low)",
  regs={f"Q{i}": Reg("CLK", f"EN·Q{i} + /EN·D{i}", "CLK->Q", clear="/CLR",
                         clear_arcs={"CLR": "CLR->Q"}, enable="/OE", on={"OE": "OE->Y en"},
                         off={"OE": "OE->Y dis"}) for i in range(1, 10)},
  timing=[Setup("D1-D9", "CLK", "setup D", "hold D"), Setup("EN", "CLK", "setup EN", "hold EN"),
          Recovery("CLK", "recovery CLR", width="tw CLR")],)

T("573", "latch573",
  [("OE", "in"), ("LE", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
  + [(f"Q{i}", "tri") for i in range(1, 9)],
  arcs=[([f"D{i}"], [f"Q{i}"], "D->Q") for i in range(1, 9)]
  + [(["LE"], [f"Q{i}" for i in range(1, 9)], "LE->Q"),
     (["OE"], [f"Q{i}" for i in range(1, 9)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 9)], "LE", "fall", "setup D", "hold D")],
  desc="octal transparent latch, three-state outputs (Q follows D while LE is high; OE active low)",
  latches={f"Q{i}": Latch("LE", f"D{i}", {f"D{i}": "D->Q", "LE": "LE->Q"}, oe="/OE",
                           on={"OE": "OE->Y en"}, off={"OE": "OE->Y dis"}) for i in range(1, 9)},
  timing=[Setup("D1-D8", "LE", "setup D", "hold D", edge="fall"), Width("LE", 1, "tw LE")],)

# Halves of 16-bit parts (74ABT16374, 16823, 16373, 16244): each half has
# its own clock and enables, so the netlist places them as two of these,
# with the 8-bit part's pins and model.
T("16374h", "dreg",
  [("OE", "in"), ("CLK", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
  + [(f"Q{i}", "tri") for i in range(1, 9)],
  arcs=[(["CLK"], [f"Q{i}" for i in range(1, 9)], "CLK->Q"),
        (["OE"], [f"Q{i}" for i in range(1, 9)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 9)], "CLK", "rise", "setup D", "hold D")],
  desc="octal D flip-flop, three-state outputs: one half of a 16-bit 74ABT16374",
  per_package=2,
  regs={f"Q{i}": Reg("CLK", f"D{i}", "CLK->Q", enable="/OE", on={"OE": "OE->Y en"},
                         off={"OE": "OE->Y dis"}) for i in range(1, 9)},
  timing=[Setup("D1-D8", "CLK", "setup D", "hold D"), Width("CLK", 1, "tw CLK"),
          Width("CLK", 0, "tw CLK"), Period("CLK", "fmax MHz")],)

T("16823h", "dreg",
  [("OE", "in"), ("CLK", "in"), ("EN", "in"), ("CLR", "in")]
  + [(f"D{i}", "in") for i in range(1, 10)] + [(f"Q{i}", "tri") for i in range(1, 10)],
  arcs=[(["CLK"], [f"Q{i}" for i in range(1, 10)], "CLK->Q"),
        (["CLR"], [f"Q{i}" for i in range(1, 10)], "CLR->Q"),
        (["OE"], [f"Q{i}" for i in range(1, 10)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 10)], "CLK", "rise", "setup D", "hold D"),
          (["EN"], "CLK", "rise", "setup EN", "hold EN")],
  desc="9-bit D flip-flop with clock enable, clear and three-state outputs (EN, CLR, OE "
       "active low): one half of an 18-bit 74ABT16823", per_package=2,
  regs={f"Q{i}": Reg("CLK", f"EN·Q{i} + /EN·D{i}", "CLK->Q", clear="/CLR",
                         clear_arcs={"CLR": "CLR->Q"}, enable="/OE", on={"OE": "OE->Y en"},
                         off={"OE": "OE->Y dis"}) for i in range(1, 10)},
  timing=[Setup("D1-D9", "CLK", "setup D", "hold D"), Setup("EN", "CLK", "setup EN", "hold EN"),
          Recovery("CLK", "recovery CLR", width="tw CLR")],)

T("16373h", "latch573",
  [("OE", "in"), ("LE", "in")] + [(f"D{i}", "in") for i in range(1, 9)]
  + [(f"Q{i}", "tri") for i in range(1, 9)],
  arcs=[([f"D{i}"], [f"Q{i}"], "D->Q") for i in range(1, 9)]
  + [(["LE"], [f"Q{i}" for i in range(1, 9)], "LE->Q"),
     (["OE"], [f"Q{i}" for i in range(1, 9)], "OE->Y en")],
  checks=[([f"D{i}" for i in range(1, 9)], "LE", "fall", "setup D", "hold D")],
  desc="octal transparent latch, three-state outputs: one half of a 16-bit 74ABT16373",
  per_package=2,
  latches={f"Q{i}": Latch("LE", f"D{i}", {f"D{i}": "D->Q", "LE": "LE->Q"}, oe="/OE",
                           on={"OE": "OE->Y en"}, off={"OE": "OE->Y dis"}) for i in range(1, 9)},
  timing=[Setup("D1-D8", "LE", "setup D", "hold D", edge="fall"), Width("LE", 1, "tw LE")],)

T("16244h", "buf541",
  [("OE1", "in"), ("OE2", "in")] + [(f"A{i}", "in") for i in range(1, 9)]
  + [(f"Y{i}", "tri") for i in range(1, 9)],
  arcs=[([f"A{i}"], [f"Y{i}"], "A->Y") for i in range(1, 9)]
  + [(["OE1", "OE2"], [f"Y{i}" for i in range(1, 9)], "OE->Y en")],
  desc="octal three-state buffer: one half of a 16-bit 74ABT16244, whose OE1 and OE2 enable "
       "bits 1-4 and 5-8 (the 541's model, which needs both: so they must be tied together)",
  per_package=2, tied=[("OE1", "OE2")],
  outputs={f"Y{i}": Out(f"A{i}", {f"A{i}": "A->Y"}, enable="/OE1·/OE2",
                         on={"OE1 OE2": "OE->Y en"}, off={"OE1 OE2": "OE->Y dis"})
           for i in range(1, 9)},)

T("245", "xcvr245",
  [("DIR", "in"), ("OE", "in")] + [(f"A{i}", "io") for i in range(1, 9)]
  + [(f"B{i}", "io") for i in range(1, 9)],
  arcs=[([f"A{i}"], [f"B{i}"], "A->B") for i in range(1, 9)]
  + [([f"B{i}"], [f"A{i}"], "B->A") for i in range(1, 9)]
  + [(["OE", "DIR"], [f"A{i}" for i in range(1, 9)], "OE->A en"),
     (["OE", "DIR"], [f"B{i}" for i in range(1, 9)], "OE->B en")],
  desc="octal transceiver (DIR high: A to B; OE active low)",
  outputs={**{f"A{i}": Out(f"B{i}", {f"B{i}": "B->A"}, enable="/OE·/DIR",
                            on={"OE DIR": "OE->Y en"}, off={"OE DIR": "OE->Y dis"})
              for i in range(1, 9)},
           **{f"B{i}": Out(f"A{i}", {f"A{i}": "A->B"}, enable="/OE·DIR",
                            on={"OE DIR": "OE->Y en"}, off={"OE DIR": "OE->Y dis"})
              for i in range(1, 9)}},)

T("125", "tribuf",
  [(f"{s}{p}", k) for s in range(1, 5) for p, k in (("OE", "in"), ("A", "in"), ("Y", "tri"))],
  arcs=[([f"{s}A"], [f"{s}Y"], "A->Y") for s in range(1, 5)]
  + [([f"{s}OE"], [f"{s}Y"], "OE->Y en") for s in range(1, 5)],
  desc="quad three-state buffer (OE active low)",
  outputs={f"{s}Y": Out(f"{s}A", {f"{s}A": "A->Y"}, enable=f"/{s}OE",
                          on={f"{s}OE": "OE->Y en"}, off={f"{s}OE": "OE->Y dis"})
           for s in range(1, 5)},)

T("148", "enc148",
  [(f"I{i}", "in") for i in range(8)] + [("EI", "in")] + [(f"A{i}", "out") for i in range(3)]
  + [("GS", "out"), ("EO", "out")],
  arcs=[([f"I{i}" for i in range(8)], ["A0", "A1", "A2", "GS", "EO"], "I->Y"),
        (["EI"], ["A0", "A1", "A2", "GS", "EO"], "EI->Y")],
  desc="8-line to 3-line priority encoder, active low, I7 first")

T("clkdrv", "fanbuf", [("A", "in")] + [(f"Y{i}", "out") for i in range(1, 9)],
  arcs=[(["A"], [f"Y{i}" for i in range(1, 9)], "A->Y")],
  desc="1-to-8 clock driver",
  outputs={f"Y{i}": Out("A", {"A": "A->Y"}) for i in range(1, 9)},)

T("osc", "osc", [("OUT", "io")], family="osc",
  desc="crystal oscillator (params period_ps, phase_ps: the first rising edge)")

T("cy22393", "clocksynth",
  [(p, "io") for p in ("CLKA", "CLKB", "CLKC", "CLKD", "CLKE", "XBUF")]
  + [("SCLK", "in"), ("SDAT", "io"), ("S2", "in"), ("OE", "in"), ("XTALIN", "in"),
     ("XTALOUT", "io"), ("VDD", "in"), ("AVDD", "in")], family="osc",
  desc="programmable clock chip, three PLLs and six outputs from its stored configuration "
       "(params <a-e, x>_ps and _phase: each output's period and first rising edge); its "
       "serial port (SCLK, SDAT), its crystal (XTALIN, XTALOUT) and SHUTDOWN/OE (OE) aren't "
       "modelled. A 3.3 V part: VDD and AVDD on a 3.3 V rail, and its inputs no higher")

T("button", "button", [("OUT", "tri")], family="misc",
  desc="push button to ground (params press_ps, release_ps: when the simulation presses it)",
  asynchronous=["OUT"],)

T("ps2dev", "ps2dev", [("CLK", "io"), ("DATA", "io"), ("WAKE", "io")], family="fixture",
  desc="a PS/2 keyboard or mouse on its cable (open-collector CLK and DATA): sends its preload, "
       "answers the host's bytes with 0xFA, dumps what the host sent (params half_ps, gap_ps, "
       "start_ps); WAKE is the simulator's, on a net of its own",
  asynchronous=["CLK DATA WAKE"],)

T("por", "por", [("RST", "tri")], family="misc",
  desc="supply supervisor as power-on reset: open-collector RST low until params release_ps",
  asynchronous=["RST"],)

T("pullup", "pullup", [(f"P{i}", "pull") for i in range(1, 9)], family="passive",
  desc="eight pull-up resistors to VCC (a resistor network)")

# parts on a board that the simulation doesn't model beyond a pull-up: they
# are in the netlist for the boards' PCBs
T("rpull", "passive", [("A", "pull"), ("R", "in")], family="passive",
  desc="a pull-up resistor from A to the rail R (one other than VCC)")
T("cap", "passive", [("A", "in"), ("B", "in")], family="passive",
  desc="a capacitor (its value the part); decoupling on a rail other than VCC")
T("capbulk", "passive", [("A", "in"), ("B", "in")], family="passive",
  desc="a bulk capacitor, 10 uF or so (its value the part)")
T("xtal", "passive", [("X1", "io"), ("X2", "io")], family="passive",
  desc="a crystal (its frequency the part)")
T("ldo33", "passive", [("OUT", "pull")], family="passive",
  desc="a 3.3 V regulator from VCC: OUT the 3.3 V rail, which reads high")

# ---- devices: register-level models in infra/devices, pins in hwsim ----

T("16c550", "uart16550",
  [(f"D{i}", "io") for i in range(8)] + [(f"A{i}", "in") for i in range(3)]
  + [(p, "in") for p in ("CS0", "CS1", "CS2", "RD", "WR", "MR", "XIN")]
  + [(p, "out") for p in ("INTR", "RTS", "DTR", "OUT1", "OUT2")],
  arcs=[(["RD"], [f"D{i}" for i in range(8)], "RD->D")], family="device",
  desc="UART with 16-byte FIFOs (CS2, RD, WR, RTS, DTR, OUT1, OUT2 active low; MR active high); "
       "the terminal on its serial line is inside the model",
  outputs={f"D{i}": _uart_out() for i in range(8)},
  asynchronous=["INTR RTS DTR OUT1 OUT2"],
  timing=[Strobe("/CS2·/WR", stable={"A0 A1 A2": ("tAS", None, "tAH WR")},
                 data={"D0-D7": ("tDS", "tDH")}, width="tWR"),
          Strobe("/CS2·/RD", stable={"A0 A1 A2": ("tAS", None, "tAH")}, width="tRD")],)

T("82c54", "i8254",
  [(f"D{i}", "io") for i in range(8)] + [("A0", "in"), ("A1", "in")]
  + [(p, "in") for p in ("CS", "RD", "WR")]
  + [(f"{p}{i}", "in") for i in range(3) for p in ("CLK", "GATE")]
  + [(f"OUT{i}", "out") for i in range(3)],
  arcs=[(["RD"], [f"D{i}" for i in range(8)], "RD->D")]
  + [([f"CLK{i}"], [f"OUT{i}"], "CLK->OUT") for i in range(3)], family="device",
  desc="programmable interval timer: three 16-bit counters (CS, RD, WR active low)",
  outputs={f"D{i}": Out(None, {"A0 A1": "A->D"}, enable="/CS·/RD",
                         on={"RD CS": Arc("RD->D", min=0)}, off={"RD CS": "RD->D dis"})
           for i in range(8)},
  asynchronous=["OUT0 OUT1 OUT2"],
  timing=[Strobe("/CS·/WR", stable={"A0 A1": ("tAW", None, "tWA")}, data={"D0-D7": ("tDW", "tWD")},
                 width="tWW"),
          Strobe("/CS·/RD", stable={"A0 A1": ("tAR", None, "tRA")}, width="tRR")],)

T("cf", "cf",
  [(f"D{i}", "io") for i in range(16)] + [(f"A{i}", "in") for i in range(3)]
  + [(p, "in") for p in ("CS0", "CS1", "IORD", "IOWR", "RESET")]
  + [("INTRQ", "out"), ("WAKE", "io")],
  arcs=[(["IORD"], [f"D{i}" for i in range(16)], "RD->D")], family="device",
  desc="CompactFlash card in True IDE mode (CS0, CS1, IORD, IOWR, RESET active low); "
       "WAKE is the simulator's, on a net of its own",
  outputs={f"D{i}": Out(None, {"A0-A2": "RD->D"}, enable="/IORD·/CS0 + /IORD·/CS1",
                         on={"IORD CS0 CS1": Arc("RD->D", min=0)},
                         off={"IORD CS0 CS1": "RD->D dis"}) for i in range(16)},
  asynchronous=["INTRQ WAKE"],
  timing=[Strobe("/IOWR·/CS0 + /IOWR·/CS1", stable={"A0 A1 A2 CS0 CS1": ("t1", None, "t9")},
                 data={"D0-D15": ("t3", "t4")}, width="t2"),
          Strobe("/IORD·/CS0 + /IORD·/CS1", stable={"A0 A1 A2 CS0 CS1": ("t1", None, "t9")},
                 width="t2")],)

# ---- test fixtures (not chips on the board) ----

T("const", "const", [("LO", "out"), ("HI", "out")], family="fixture", desc="GND and VCC",
  outputs={"LO": Out("0", {}), "HI": Out("1", {})},)

T("wire", "wire", [("A", "in"), ("Y", "out")], family="fixture",
  desc="the far end of a wire: Y is A, later by Y's pin delay (a routed board's flight "
       "time to one load, infra/pcb/wires.py)",
  outputs={"Y": Out("A", {"A": 0})},)

T("vector", "vector", [("CLK", "in")] + [(f"O{i}", "tri") for i in range(64)]
  + [(f"I{i}", "in") for i in range(48)], family="fixture",
  desc="a script played against CLK and a record of its inputs (params outs, ins, "
       "delay_ps; the script is its preload, the record its dump): a test's bus master")

T("clockgen", "clockgen", [("CLK", "out"), ("WEWIN", "out"), ("RESET", "out")],
  family="fixture", desc="clock, write window and reset (oscillator + phase logic)")

T("iodev", "iodev",
  [("CLK", "in"), ("IOSEL", "in"), ("RD", "in"), ("WEL", "in"), ("WEH", "in")]
  + [(f"A{i}", "in") for i in range(8)] + [(f"D{i}", "io") for i in range(16)] + [("IRQ", "out")],
  arcs=[([f"A{i}" for i in range(8)] + ["IOSEL", "RD"], [f"D{i}" for i in range(16)], "tACC")],
  family="fixture", desc="console, timer and cycle counter on the I/O page")


# --------------------------------------------------------------------------
# Timing data

TIMING_PATH = os.path.join(os.path.dirname(__file__), "timing.json")


def load_timing():
    with open(TIMING_PATH) as f:
        return json.load(f)


T("iodev_w32", "iodev_w32",
  [("CLK", "in"), ("IOSEL", "in"), ("RD", "in"), ("WR", "in")]
  + [(f"A{i}", "in") for i in range(2, 8)] + [(f"BE{i}", "in") for i in range(4)]
  + [(f"D{i}", "io") for i in range(32)] + [("IRQ", "out")],
  arcs=[([f"A{i}" for i in range(2, 8)] + ["IOSEL", "RD"], [f"D{i}" for i in range(32)], "tACC")],
  family="fixture", desc="draft 1 I/O page on a 32-bit data bus, one register access per "
                         "16-bit half (byte enables, IOSEL, RD, WR active low; input preloaded)")

T("cpucard_w32", "iodev_w32",
  [("CLK", "in"), ("MCLK", "in"), ("RESET_n", "in"), ("IOSEL", "in"), ("RD", "in"), ("WR", "in")]
  + [(f"A{i}", "in") for i in list(range(2, 16)) + list(range(24, 28))]
  + [(f"BE{i}", "in") for i in range(4)] + [(f"D{i}", "io") for i in range(32)]
  + [("IRQ", "out")] + [(f"LV{i}", "out") for i in range(1, 9)]
  + [("MSGF", "out"), ("NMI", "out"), ("MSGOE", "in"), ("NMIACK", "in")]
  + [(f"B{i}", "io") for i in range(32)],
  arcs=[([f"A{i}" for i in range(2, 8)] + ["IOSEL", "RD"], [f"D{i}" for i in range(32)], "tACC")],
  family="fixture", desc="a CPU card's registers (RFC 0040, 3: control, the request register, "
                         "the message register onto the CPU's B bus, the timer from the master "
                         "clock) and draft 1's I/O page, on a 32-bit data bus")

T("tickclk", "tickclk",
  [("CLK", "out"), ("MWIN", "out"), ("LATE", "out"), ("PHASE", "out"), ("RW", "out"),
   ("RSTB", "out"), ("RESET", "out")],
  family="fixture", desc="for static timing analysis: a tick clock generator's outputs as "
                         "functions of the cycle (CLK's edge at 0; the memory write window, "
                         "two phases from later ticks, the register file's write phase and "
                         "its write strobe)")

T("iodev32", "iodev32",
  [("CLK", "in"), ("IOSEL", "in"), ("RD", "in"), ("WEL", "in"), ("WEH", "in")]
  + [(f"A{i}", "in") for i in range(8)] + [(f"D{i}", "io") for i in range(16)] + [("IRQ", "out")],
  arcs=[([f"A{i}" for i in range(8)] + ["IOSEL", "RD"], [f"D{i}" for i in range(16)], "tACC")],
  family="fixture", desc="draft 1 I/O page (32-bit registers on a 16-bit bus)")


# Bill-of-materials variants: chip type -> part number.
VARIANTS = {
    # The default: in-production HCT logic, new-old-stock 74LS181 + 74S182.
    "hct-ls181": {"logic": "74HCT", "alu": "74LS181", "cla": "74S182",
                  "rf": "AS7C256A-15", "ram": "AS6C62256-55", "rom": "SST39SF010A-55"},
    # Faster ALU: 74F181 + 74F182 (also new-old-stock only).
    "hct-f181": {"logic": "74HCT", "alu": "74F181", "cla": "74F182",
                 "rf": "AS7C256A-15", "ram": "AS6C62256-55", "rom": "SST39SF010A-55"},
    # Everything fast: 74ACT logic where it exists (no ACT30/ACT688/ACT193: HCT used).
    "act-f181": {"logic": "74ACT", "alu": "74F181", "cla": "74F182",
                 "rf": "AS7C256A-12", "ram": "AS6C62256-55", "rom": "SST39SF010A-55"},
}
DEFAULT_VARIANT = "hct-ls181"
ACT_MISSING = {"30", "688", "193"}


# Parts outside the variants: families that only the card designs use,
# named in the netlist by part number (Netlist.add(..., part=...)).
FIXED_PARTS = {"osc": "oscillator", "por": "TL7705A", "pullup": "10k x8 resistor network",
               "16c550": "TL16C550C", "82c54": "82C54", "cf": "CF", "cy22393": "CY22393",
               "button": "push button", "flash4": "SST39SF040-55", "rpull": "resistor",
               "cap": "capacitor", "capbulk": "capacitor", "xtal": "crystal",
               "ldo33": "LM1117-3.3"}
# Families whose parts may have no timing data (their models have defaults).
UNTIMED = {"osc", "misc", "passive", "fixture"}


# Delay names a model reads that fall back to another one in the timing
# data: the 245 turns each side on in the time the datasheet gives for both.
DELAY_FALLBACK = {"OE->A en": "OE->Y en", "OE->B en": "OE->Y en"}


def part_number(variant, chip_type, role=None, part=None):
    """The part a chip of this type is in this variant: `part` if the
    netlist names one, else the variant's choice for its type and role.
    Besides the keys above, a variant may name a part per chip type
    ("parts": {"153": "74F153", ...}), the slower 512K x 8 RAM ("ram512")
    and the decode ROMs apart from the microcode ROMs ("decode")."""
    if part is not None:
        return part
    if chip_type in FIXED_PARTS:
        return FIXED_PARTS[chip_type]
    v = VARIANTS[variant]
    if chip_type in v.get("parts", {}):
        return v["parts"][chip_type]
    if chip_type == "181":
        return v["alu"]
    if chip_type == "182":
        return v["cla"]
    if chip_type == "sram":
        return v["ram"] if role == "ram" else v["rf"]
    if chip_type == "sram512":
        return "AS7C4096A-12" if role == "fastram" else v.get("ram512", "AS6C4008-55")
    if chip_type == "flash":
        return v.get("decode", v["rom"]) if role == "decode" else v["rom"]
    if TYPES[chip_type].family == "fixture":
        return chip_type
    if v["logic"] == "74ACT" and chip_type in ACT_MISSING:
        return "74HCT" + chip_type
    return v["logic"] + chip_type


def delays_for(timing, part, corner):
    """{delay name: picoseconds} for a part number at corner 'typ' or 'max'."""
    entry = timing.get(part)
    if entry is None:
        if part in FIXED_PARTS.values():
            return {}
        raise KeyError(f"no timing data for {part}")
    out = {}
    for k, v in entry.get("delays", {}).items():
        val = v.get(corner, v.get("max", v.get("typ")))
        out[k] = int(round(val * 1000))
    for k, v in entry.get("checks", {}).items():
        out[k] = int(round(v * 1000))
    return out
