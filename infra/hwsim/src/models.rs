//! Behavioural models of the chips, with their datasheet delays. A model
//! is chosen by the netlist's `model` name (infra/hw/chips.py); its delays
//! come from the netlist too, keyed by arc ("A->Y", "setup D", ...).

use std::collections::HashMap;

use crate::Error;
use crate::devices::{CompactFlash, I8254, Uart16550};
use crate::rng::Rng;
use crate::sim::{ChipInfo, Ctx, Kind, Time};

/// A chip's pins and delays, while its model is built.
pub struct Spec<'a> {
    pub info: &'a ChipInfo,
    pub delays: &'a HashMap<String, Time>,
    pub params: &'a HashMap<String, i64>,
    pub program: &'a [i64],
}

impl Spec<'_> {
    pub(crate) fn has(&self, name: &str) -> bool {
        self.info.pin_names.iter().any(|p| p == name)
    }

    pub(crate) fn pin(&self, name: &str) -> Result<usize, Error> {
        self.info
            .pin_names
            .iter()
            .position(|p| p == name)
            .ok_or_else(|| {
                Error(format!(
                    "{} ({}): no pin {}",
                    self.info.reference, self.info.part, name
                ))
            })
    }

    pub(crate) fn pins<const N: usize>(
        &self,
        name: impl Fn(usize) -> String,
    ) -> Result<[usize; N], Error> {
        let mut out = [0; N];
        for (i, p) in out.iter_mut().enumerate() {
            *p = self.pin(&name(i))?;
        }
        Ok(out)
    }

    pub(crate) fn d(&self, name: &str) -> Result<Time, Error> {
        self.delays.get(name).copied().ok_or_else(|| {
            Error(format!(
                "{} ({}): no timing value {:?}",
                self.info.reference, self.info.part, name
            ))
        })
    }

    pub(crate) fn d_or(&self, name: &str, default: Time) -> Time {
        self.delays.get(name).copied().unwrap_or(default)
    }

    pub(crate) fn param(&self, name: &str) -> Result<i64, Error> {
        self.params.get(name).copied().ok_or_else(|| {
            Error(format!(
                "{} ({}): no parameter {:?}",
                self.info.reference, self.info.part, name
            ))
        })
    }

    pub(crate) fn param_or(&self, name: &str, default: i64) -> i64 {
        self.params.get(name).copied().unwrap_or(default)
    }

    /// For each pin, the bits of a bus that are on the same net, so that a
    /// cached value of the bus can follow a change seen on any pin of it.
    pub(crate) fn masks(&self, bus: &[usize]) -> Vec<u64> {
        let pins = &self.info.pins;
        let on = |n, b: usize| pins[b] == Some(n);
        (0..pins.len())
            .map(|p| match pins[p] {
                Some(n) => (0..bus.len())
                    .filter(|&i| on(n, bus[i]))
                    .map(|i| 1 << i)
                    .sum(),
                None => 0,
            })
            .collect()
    }

    /// pin -> Some(i) for each pin in `pins`, None for the others.
    fn index(&self, pins: &[usize]) -> Vec<Option<usize>> {
        let mut out = vec![None; self.info.pin_names.len()];
        for (i, &p) in pins.iter().enumerate() {
            out[p] = Some(i);
        }
        out
    }
}

fn b2u(b: bool) -> u8 {
    b as u8
}

/// A bus's value, low bit first.
pub(crate) fn bus_value(cx: &Ctx, c: &ChipInfo, pins: &[usize]) -> usize {
    pins.iter()
        .enumerate()
        .map(|(i, &p)| (cx.input(c, p) as usize) << i)
        .sum()
}

/// A net changed to v: set the bits of a cached bus value that are on it.
pub(crate) fn follow(value: &mut usize, mask: u64, v: u8) {
    if mask != 0 {
        let mask = mask as usize;
        *value = if v == 1 {
            *value | mask
        } else {
            *value & !mask
        };
    }
}

pub enum Model {
    Gate(Gate),
    Dff74(Dff74),
    Dec138(Dec138),
    Mux151(Mux151),
    Mux153(Mux153),
    Mux157(Mux157),
    Counter(Counter),
    Cnt193(Cnt193),
    Dff175(Dff175),
    Reg377(Reg377),
    Buf541(Buf541),
    Cmp688(Cmp688),
    Alu181(Alu181),
    Cla182(Cla182),
    Sram(Sram),
    Rom(Rom),
    Const,
    /// The clock generator's outputs are driven by the main loop.
    ClockGen,
    IoDev(IoDev),
    IoDevW(IoDevW),
    Sr299(Sr299),
    Jk109(Jk109),
    DReg(DReg),
    Latch573(Latch573),
    Xcvr245(Xcvr245),
    TriBuf(TriBuf),
    Enc148(Enc148),
    FanBuf(FanBuf),
    Osc(Osc),
    Por(Por),
    Uart(Box<Uart16550>),
    Timer(Box<I8254>),
    Cf(Box<CompactFlash>),
    Vector(Vector),
    Gal(Gal),
}

impl Model {
    /// The model called `name` for a chip. `rng` sets the power-on state of
    /// flip-flops and memories; `preload` is a memory's initial contents.
    pub fn new(
        name: &str,
        s: &Spec,
        rng: &mut Rng,
        preload: Option<&[u8]>,
    ) -> Result<Model, Error> {
        Ok(match name {
            "nand" => Model::Gate(Gate::new(GateFn::Nand, s)?),
            "nand_oc" => Model::Gate(Gate::new(GateFn::Nand, s)?.open_collector()),
            "and_oc" => Model::Gate(Gate::new(GateFn::And, s)?.open_collector()),
            "nor" => Model::Gate(Gate::new(GateFn::Nor, s)?),
            "and" => Model::Gate(Gate::new(GateFn::And, s)?),
            "wire" => Model::Gate(Gate::wire(s)?),
            "or" => Model::Gate(Gate::new(GateFn::Or, s)?),
            "xor" => Model::Gate(Gate::new(GateFn::Xor, s)?),
            "dff74" => Model::Dff74(Dff74::new(s, rng)?),
            "dec138" => Model::Dec138(Dec138::new(s)?),
            "mux151" => Model::Mux151(Mux151::new(s)?),
            "mux153" => Model::Mux153(Mux153::new(s)?),
            "mux157" => Model::Mux157(Mux157::new(s)?),
            "cnt161" => Model::Counter(Counter::new(s, rng, false)?),
            "cnt163" => Model::Counter(Counter::new(s, rng, true)?),
            "cnt193" => Model::Cnt193(Cnt193::new(s, rng)?),
            "dff175" => Model::Dff175(Dff175::new(s, rng)?),
            "reg377" => Model::Reg377(Reg377::new(s, rng)?),
            "buf541" => Model::Buf541(Buf541::new(s, false)?),
            "buf540" => Model::Buf541(Buf541::new(s, true)?),
            "cmp688" => Model::Cmp688(Cmp688::new(s)?),
            "alu181" => Model::Alu181(Alu181::new(s)?),
            "cla182" => Model::Cla182(Cla182::new(s)?),
            "sram" => Model::Sram(Sram::new(s, rng, preload)?),
            "rom" => Model::Rom(Rom::new(s, preload)?),
            "const" => {
                s.pin("LO")?;
                s.pin("HI")?;
                Model::Const
            }
            "clockgen" => Model::ClockGen,
            "iodev" => Model::IoDev(IoDev::new(s, false)?),
            "iodev32" => Model::IoDev(IoDev::new(s, true)?),
            "sr299" => Model::Sr299(Sr299::new(s, rng)?),
            "jk109" => Model::Jk109(Jk109::new(s, rng)?),
            "dreg" => Model::DReg(DReg::new(s, rng, false)?),
            "dreg_inv" => Model::DReg(DReg::new(s, rng, true)?),
            "latch573" => Model::Latch573(Latch573::new(s, rng)?),
            "iodev_w32" => Model::IoDevW(IoDevW::new(s, preload)?),
            "xcvr245" => Model::Xcvr245(Xcvr245::new(s)?),
            "tribuf" => Model::TriBuf(TriBuf::new(s)?),
            "enc148" => Model::Enc148(Enc148::new(s)?),
            "fanbuf" => Model::FanBuf(FanBuf::new(s)?),
            "osc" => Model::Osc(Osc::new(s)?),
            // pull-up resistors are weak drivers in the engine (sim.rs)
            "pullup" => Model::Const,
            "por" => Model::Por(Por::new(s)?),
            "uart16550" => Model::Uart(Box::new(Uart16550::new(s, preload)?)),
            "i8254" => Model::Timer(Box::new(I8254::new(s)?)),
            "cf" => Model::Cf(Box::new(CompactFlash::new(s, preload)?)),
            "vector" => Model::Vector(Vector::new(s, preload)?),
            "gal" => Model::Gal(Gal::new(s)?),
            _ => {
                return Err(Error(format!(
                    "{}: unknown model {:?}",
                    s.info.reference, name
                )));
            }
        })
    }

    /// Drive the initial outputs, at time 0.
    pub fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        match self {
            Model::Gate(m) => m.init(cx, c),
            Model::Dff74(m) => m.init(cx, c),
            Model::Dec138(m) => m.eval_all(cx, c, 0),
            Model::Mux151(m) => m.eval_all(cx, c, 0, 0),
            Model::Mux153(m) => m.init(cx, c),
            Model::Mux157(m) => m.init(cx, c),
            Model::Counter(m) => m.out(cx, c, 0, 0),
            Model::Cnt193(m) => m.init(cx, c),
            Model::Dff175(m) => m.out(cx, c, 0),
            Model::Reg377(m) => m.init(cx, c),
            Model::Buf541(m) => m.init(cx, c),
            Model::Cmp688(m) => m.eval_all(cx, c, 0),
            Model::Alu181(m) => m.eval_all(cx, c, Some(0), Some(0), Some(0), Some(0), Some(0)),
            Model::Cla182(m) => m.eval_all(cx, c, Some(0), Some(0), Some(0)),
            Model::Sram(m) => m.init(cx, c),
            Model::Rom(m) => m.init(cx, c),
            Model::Const => {
                if let Some(lo) = c.pin_names.iter().position(|p| p == "LO") {
                    cx.drive(c, lo, 0, true, 0);
                }
                if let Some(hi) = c.pin_names.iter().position(|p| p == "HI") {
                    cx.drive(c, hi, 1, true, 0);
                }
            }
            Model::ClockGen => {}
            Model::IoDev(m) => cx.drive(c, m.irq, 0, true, 0),
            Model::Sr299(m) => m.outputs(cx, c, 0, 0),
            Model::Jk109(m) => m.init(cx, c),
            Model::DReg(m) => m.init(cx, c),
            Model::Latch573(m) => m.init(cx, c),
            Model::IoDevW(m) => {
                cx.drive(c, m.irq, 0, true, 0);
                if let Some(card) = m.card.as_ref() {
                    card.outputs(cx, c);
                }
            }
            Model::Xcvr245(m) => m.init(cx, c),
            Model::TriBuf(m) => m.init(cx, c),
            Model::Enc148(m) => m.eval_all(cx, c, 0),
            Model::FanBuf(m) => m.eval_all(cx, c, 0),
            Model::Osc(m) => m.init(cx, c),
            Model::Por(m) => m.init(cx, c),
            Model::Uart(m) => m.init(cx, c),
            Model::Timer(m) => m.init(cx, c),
            Model::Cf(m) => m.init(cx, c),
            Model::Vector(m) => m.init(cx, c),
            Model::Gal(m) => m.init(cx, c),
        }
    }

    /// Put an image into a RAM again (a loader's doing, after power-up);
    /// other chips keep what they have.
    pub fn reload(&mut self, image: &[u8]) {
        if let Model::Sram(m) = self {
            let n = image.len().min(m.mem.len());
            m.mem[..n].copy_from_slice(&image[..n]);
            m.mem[n..].fill(0);
        }
    }

    /// What a chip holds that a run reports at the end: a RAM's contents,
    /// what a device sent to the outside world. None for the others.
    pub fn dump(&self) -> Option<Vec<u8>> {
        match self {
            Model::Sram(m) => Some(m.mem.clone()),
            Model::IoDev(m) => Some(m.output.clone()),
            Model::IoDevW(m) => Some(m.output.clone()),
            Model::Uart(m) => Some(m.core.tx_out.clone()),
            Model::Cf(m) => Some(m.core.image().to_vec()),
            Model::Vector(m) => Some(m.log.clone()),
            _ => None,
        }
    }

    /// The value on `pin` changed.
    pub fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        match self {
            Model::Gate(m) => m.eval(cx, c, pin),
            Model::Dff74(m) => m.eval(cx, c, pin),
            Model::Dec138(m) => m.eval(cx, c, pin),
            Model::Mux151(m) => m.eval(cx, c, pin),
            Model::Mux153(m) => m.eval(cx, c, pin),
            Model::Mux157(m) => m.eval(cx, c, pin),
            Model::Counter(m) => m.eval(cx, c, pin),
            Model::Cnt193(m) => m.eval(cx, c, pin),
            Model::Dff175(m) => m.eval(cx, c, pin),
            Model::Reg377(m) => m.eval(cx, c, pin),
            Model::Buf541(m) => m.eval(cx, c, pin),
            Model::Cmp688(m) => m.eval(cx, c, pin),
            Model::Alu181(m) => m.eval(cx, c, pin),
            Model::Cla182(m) => m.eval(cx, c, pin),
            Model::Sram(m) => m.eval(cx, c, pin),
            Model::Rom(m) => m.eval(cx, c, pin),
            Model::Const | Model::ClockGen => {}
            Model::IoDev(m) => m.eval(cx, c, pin),
            Model::Sr299(m) => m.eval(cx, c, pin),
            Model::Jk109(m) => m.eval(cx, c, pin),
            Model::DReg(m) => m.eval(cx, c, pin),
            Model::Latch573(m) => m.eval(cx, c, pin),
            Model::IoDevW(m) => m.eval(cx, c, pin),
            Model::Xcvr245(m) => m.eval(cx, c, pin),
            Model::TriBuf(m) => m.eval(cx, c, pin),
            Model::Enc148(m) => m.eval(cx, c, pin),
            Model::FanBuf(m) => m.eval(cx, c, pin),
            Model::Osc(m) => m.eval(cx, c, pin),
            Model::Por(_) => {}
            Model::Uart(m) => m.eval(cx, c, pin),
            Model::Timer(m) => m.eval(cx, c, pin),
            Model::Cf(m) => m.eval(cx, c, pin),
            Model::Vector(m) => m.eval(cx, c, pin),
            Model::Gal(m) => m.eval(cx, c, pin),
        }
    }
}

// ---------------------------------------------------------------- gates

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum GateFn {
    And,
    Nand,
    Or,
    Nor,
    Xor,
}

/// A package of gates: each section is a run of inputs followed by its
/// output, in pin order.
pub struct Gate {
    f: GateFn,
    sec_of: Vec<usize>,
    ins: Vec<Vec<usize>>,
    out: Vec<usize>,
    d: Time,
    /// Open-collector outputs: they pull low or let go. Letting go takes
    /// `d_release`, which includes the pull-up's rise to the threshold.
    oc: bool,
    d_release: Time,
}

impl Gate {
    fn new(f: GateFn, s: &Spec) -> Result<Gate, Error> {
        Gate::with_delay(f, s, s.d("A->Y")?)
    }

    /// A wire's far end: Y follows A with no delay of its own; the wire's
    /// is the pin delay on Y (a routed board's flight time to one load).
    fn wire(s: &Spec) -> Result<Gate, Error> {
        Gate::with_delay(GateFn::And, s, 0)
    }

    fn with_delay(f: GateFn, s: &Spec, d: Time) -> Result<Gate, Error> {
        let mut sec_of = vec![0; s.info.pin_names.len()];
        let (mut ins, mut out, mut cur) = (Vec::new(), Vec::new(), Vec::new());
        for (p, &k) in s.info.kinds.iter().enumerate() {
            if k == Kind::In {
                cur.push(p);
                sec_of[p] = out.len();
            } else {
                ins.push(std::mem::take(&mut cur));
                out.push(p);
                sec_of[p] = out.len() - 1;
            }
        }
        if !cur.is_empty() {
            return Err(Error(format!(
                "{}: inputs after the last output",
                s.info.reference
            )));
        }
        Ok(Gate {
            f,
            sec_of,
            ins,
            out,
            d,
            oc: false,
            d_release: s.d_or("release", 0),
        })
    }

    fn open_collector(mut self) -> Gate {
        self.oc = true;
        self.d_release = self.d_release.max(self.d);
        self
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for sec in 0..self.out.len() {
            self.eval_section(cx, c, sec, 0);
        }
    }

    fn eval_section(&self, cx: &mut Ctx, c: &ChipInfo, sec: usize, d: Time) {
        let ins = self.ins[sec].iter().map(|&p| cx.input(c, p));
        let v = match self.f {
            GateFn::And => ins.fold(1, |v, i| v & i),
            GateFn::Nand => ins.fold(1, |v, i| v & i) ^ 1,
            GateFn::Or => ins.fold(0, |v, i| v | i),
            GateFn::Nor => ins.fold(0, |v, i| v | i) ^ 1,
            GateFn::Xor => ins.fold(0, |v, i| v ^ i),
        };
        if self.oc {
            // the pull-up holds the line at 1 while the output lets go
            let d = if v == 1 && d > 0 { self.d_release } else { d };
            cx.drive(c, self.out[sec], v, v == 0, d);
        } else {
            cx.drive(c, self.out[sec], v, true, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        self.eval_section(cx, c, self.sec_of[pin], self.d);
    }
}

// ---------------------------------------------------------------- 74: dual D flip-flop

struct Dff74Section {
    d: usize,
    clk: usize,
    pre: usize,
    clr: usize,
    q: usize,
    qn: usize,
    prev: u8,
    state: u8,
    last_edge: Option<Time>,
}

pub struct Dff74 {
    sec: [Dff74Section; 2],
    d_clk: Time,
    d_pc: Time,
    setup: Time,
    hold: Time,
}

impl Dff74 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Dff74, Error> {
        let mut section = |i: usize| -> Result<Dff74Section, Error> {
            let p = |n: &str| s.pin(&format!("{}{}", i + 1, n));
            Ok(Dff74Section {
                d: p("D")?,
                clk: p("CLK")?,
                pre: p("PRE")?,
                clr: p("CLR")?,
                q: p("Q")?,
                qn: p("QN")?,
                prev: 0,
                state: rng.bit(),
                last_edge: None,
            })
        };
        let sec = [section(0)?, section(1)?];
        Ok(Dff74 {
            sec,
            d_clk: s.d("CLK->Q")?,
            d_pc: s.d("PRE/CLR->Q")?,
            setup: s.d("setup D")?,
            hold: s.d("hold D")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for x in &self.sec {
            Self::out(cx, c, x, 0);
        }
    }

    fn out(cx: &mut Ctx, c: &ChipInfo, x: &Dff74Section, d: Time) {
        let (pre, clr) = (cx.input(c, x.pre), cx.input(c, x.clr));
        let (q, qn) = if pre == 0 && clr == 0 {
            (1, 1)
        } else {
            (x.state, x.state ^ 1)
        };
        cx.drive(c, x.q, q, true, d);
        cx.drive(c, x.qn, qn, true, d);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        for x in &mut self.sec {
            if pin == x.clk {
                let v = cx.input(c, x.clk);
                if v == 1 && x.prev == 0 && cx.input(c, x.pre) == 1 && cx.input(c, x.clr) == 1 {
                    cx.check_setup(c, x.d, self.setup, "D");
                    x.state = cx.input(c, x.d);
                    x.last_edge = Some(cx.now());
                    Self::out(cx, c, x, self.d_clk);
                }
                x.prev = v;
            } else if pin == x.pre || pin == x.clr {
                if cx.input(c, x.pre) == 0 {
                    x.state = 1;
                }
                if cx.input(c, x.clr) == 0 {
                    x.state = 0;
                }
                Self::out(cx, c, x, self.d_pc);
            } else if pin == x.d {
                cx.check_hold(c, x.d, x.last_edge, self.hold, "D");
            }
        }
    }
}

// ---------------------------------------------------------------- 138 decoder

pub struct Dec138 {
    sel: [usize; 3],
    g1: usize,
    g2a: usize,
    g2b: usize,
    y: [usize; 8],
    d_a: Time,
    d_g: Time,
}

impl Dec138 {
    fn new(s: &Spec) -> Result<Dec138, Error> {
        Ok(Dec138 {
            sel: [s.pin("A")?, s.pin("B")?, s.pin("C")?],
            g1: s.pin("G1")?,
            g2a: s.pin("G2A")?,
            g2b: s.pin("G2B")?,
            y: s.pins(|i| format!("Y{i}"))?,
            d_a: s.d("A->Y")?,
            d_g: s.d("G->Y")?,
        })
    }

    fn eval_all(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let en =
            cx.input(c, self.g1) == 1 && cx.input(c, self.g2a) == 0 && cx.input(c, self.g2b) == 0;
        let sel = sel3(cx, c, &self.sel);
        for (i, &p) in self.y.iter().enumerate() {
            cx.drive(c, p, b2u(!(en && sel == i)), true, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        let d = if pin == self.g1 || pin == self.g2a || pin == self.g2b {
            self.d_g
        } else {
            self.d_a
        };
        self.eval_all(cx, c, d);
    }
}

fn sel3(cx: &Ctx, c: &ChipInfo, sel: &[usize; 3]) -> usize {
    cx.input(c, sel[0]) as usize
        | (cx.input(c, sel[1]) as usize) << 1
        | (cx.input(c, sel[2]) as usize) << 2
}

// ---------------------------------------------------------------- 151 8:1 mux

pub struct Mux151 {
    d: [usize; 8],
    sel: [usize; 3],
    g: usize,
    y: usize,
    w: usize,
    d_dy: Time,
    d_dw: Time,
    d_sy: Time,
    d_sw: Time,
    d_g: Time,
}

impl Mux151 {
    fn new(s: &Spec) -> Result<Mux151, Error> {
        Ok(Mux151 {
            d: s.pins(|i| format!("D{i}"))?,
            sel: [s.pin("A")?, s.pin("B")?, s.pin("C")?],
            g: s.pin("G")?,
            y: s.pin("Y")?,
            w: s.pin("W")?,
            d_dy: s.d("D->Y")?,
            d_dw: s.d("D->W")?,
            d_sy: s.d("S->Y")?,
            d_sw: s.d("S->W")?,
            d_g: s.d("G->Y")?,
        })
    }

    fn eval_all(&self, cx: &mut Ctx, c: &ChipInfo, dy: Time, dw: Time) {
        let v = if cx.input(c, self.g) == 0 {
            cx.input(c, self.d[sel3(cx, c, &self.sel)])
        } else {
            0
        };
        cx.drive(c, self.y, v, true, dy);
        cx.drive(c, self.w, v ^ 1, true, dw);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if self.sel.contains(&pin) {
            self.eval_all(cx, c, self.d_sy, self.d_sw);
        } else if pin == self.g {
            self.eval_all(cx, c, self.d_g, self.d_g);
        } else {
            self.eval_all(cx, c, self.d_dy, self.d_dw);
        }
    }
}

// ---------------------------------------------------------------- 153 dual 4:1 mux

pub struct Mux153 {
    cin: [[usize; 4]; 2],
    g: [usize; 2],
    y: [usize; 2],
    a: usize,
    b: usize,
    sec_of: Vec<Option<usize>>,
    d_c: Time,
    d_s: Time,
    d_g: Time,
}

impl Mux153 {
    fn new(s: &Spec) -> Result<Mux153, Error> {
        let mut sec_of = vec![None; s.info.pin_names.len()];
        let mut cin = [[0; 4]; 2];
        for (sec, pins) in cin.iter_mut().enumerate() {
            *pins = s.pins(|i| format!("{}C{}", sec + 1, i))?;
            for &p in pins.iter() {
                sec_of[p] = Some(sec);
            }
        }
        Ok(Mux153 {
            cin,
            g: s.pins(|sec| format!("{}G", sec + 1))?,
            y: s.pins(|sec| format!("{}Y", sec + 1))?,
            a: s.pin("A")?,
            b: s.pin("B")?,
            sec_of,
            d_c: s.d("C->Y")?,
            d_s: s.d("S->Y")?,
            d_g: s.d("G->Y")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.eval_section(cx, c, 0, 0);
        self.eval_section(cx, c, 1, 0);
    }

    fn eval_section(&self, cx: &mut Ctx, c: &ChipInfo, sec: usize, d: Time) {
        let v = if cx.input(c, self.g[sec]) == 0 {
            let sel = cx.input(c, self.a) as usize | (cx.input(c, self.b) as usize) << 1;
            cx.input(c, self.cin[sec][sel])
        } else {
            0
        };
        cx.drive(c, self.y[sec], v, true, d);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.a || pin == self.b {
            self.eval_section(cx, c, 0, self.d_s);
            self.eval_section(cx, c, 1, self.d_s);
        } else if pin == self.g[0] {
            self.eval_section(cx, c, 0, self.d_g);
        } else if pin == self.g[1] {
            self.eval_section(cx, c, 1, self.d_g);
        } else if let Some(sec) = self.sec_of[pin] {
            self.eval_section(cx, c, sec, self.d_c);
        }
    }
}

// ---------------------------------------------------------------- 157 quad 2:1 mux

pub struct Mux157 {
    a: [usize; 4],
    b: [usize; 4],
    y: [usize; 4],
    sec: Vec<Option<usize>>,
    sel: usize,
    g: usize,
    d_a: Time,
    d_s: Time,
    d_g: Time,
}

impl Mux157 {
    fn new(s: &Spec) -> Result<Mux157, Error> {
        let a = s.pins(|i| format!("{}A", i + 1))?;
        let b = s.pins(|i| format!("{}B", i + 1))?;
        let mut sec = vec![None; s.info.pin_names.len()];
        for i in 0..4 {
            sec[a[i]] = Some(i);
            sec[b[i]] = Some(i);
        }
        Ok(Mux157 {
            a,
            b,
            y: s.pins(|i| format!("{}Y", i + 1))?,
            sec,
            sel: s.pin("S")?,
            g: s.pin("G")?,
            d_a: s.d("A->Y")?,
            d_s: s.d("S->Y")?,
            d_g: s.d("G->Y")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for i in 0..4 {
            self.eval_section(cx, c, i, 0);
        }
    }

    fn eval_section(&self, cx: &mut Ctx, c: &ChipInfo, i: usize, d: Time) {
        let v = if cx.input(c, self.g) == 0 {
            if cx.input(c, self.sel) == 1 {
                cx.input(c, self.b[i])
            } else {
                cx.input(c, self.a[i])
            }
        } else {
            0
        };
        cx.drive(c, self.y[i], v, true, d);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.sel || pin == self.g {
            let d = if pin == self.g { self.d_g } else { self.d_s };
            for i in 0..4 {
                self.eval_section(cx, c, i, d);
            }
        } else if let Some(i) = self.sec[pin] {
            self.eval_section(cx, c, i, self.d_a);
        }
    }
}

// ---------------------------------------------------------------- 161/163 counters

/// A 4-bit binary counter: the 161 clears asynchronously, the 163 at the
/// clock edge.
pub struct Counter {
    sync: bool,
    clk: usize,
    clr: usize,
    load: usize,
    enp: usize,
    ent: usize,
    rco: usize,
    d: [usize; 4],
    q: [usize; 4],
    state: u8,
    prev: u8,
    last_edge: Option<Time>,
    load_at_edge: bool,
    d_clk_q: Time,
    d_clk_rco: Time,
    d_ent_rco: Time,
    d_clr: Time,
    su_data: Time,
    h_data: Time,
    su_load: Time,
    h_load: Time,
    su_en: Time,
    h_en: Time,
    su_clr: Time,
    h_clr: Time,
}

impl Counter {
    fn new(s: &Spec, rng: &mut Rng, sync: bool) -> Result<Counter, Error> {
        let names = |n: [&str; 4]| -> Result<[usize; 4], Error> { s.pins(|i| n[i].to_string()) };
        let mut state = 0;
        for i in 0..4 {
            state |= rng.bit() << i;
        }
        Ok(Counter {
            sync,
            clk: s.pin("CLK")?,
            clr: s.pin("CLR")?,
            load: s.pin("LOAD")?,
            enp: s.pin("ENP")?,
            ent: s.pin("ENT")?,
            rco: s.pin("RCO")?,
            d: names(["A", "B", "C", "D"])?,
            q: names(["QA", "QB", "QC", "QD"])?,
            state,
            prev: 0,
            last_edge: None,
            load_at_edge: false,
            d_clk_q: s.d("CLK->Q")?,
            d_clk_rco: s.d("CLK->RCO")?,
            d_ent_rco: s.d("ENT->RCO")?,
            d_clr: if sync { 0 } else { s.d("CLR->Q")? },
            su_data: s.d("setup data")?,
            h_data: s.d("hold data")?,
            su_load: s.d("setup LOAD")?,
            h_load: s.d("hold LOAD")?,
            su_en: s.d("setup EN")?,
            h_en: s.d("hold EN")?,
            su_clr: if sync { s.d("setup CLR")? } else { 0 },
            h_clr: if sync { s.d("hold CLR")? } else { 0 },
        })
    }

    fn out(&self, cx: &mut Ctx, c: &ChipInfo, dq: Time, drco: Time) {
        for i in 0..4 {
            cx.drive(c, self.q[i], (self.state >> i) & 1, true, dq);
        }
        let rco = b2u(self.state == 15 && cx.input(c, self.ent) == 1);
        cx.drive(c, self.rco, rco, true, drco);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            if v == 1 && self.prev == 0 {
                let (clr, load) = (cx.input(c, self.clr), cx.input(c, self.load));
                cx.check_setup(c, self.load, self.su_load, "LOAD");
                cx.check_setup(c, self.enp, self.su_en, "ENP");
                cx.check_setup(c, self.ent, self.su_en, "ENT");
                if self.sync {
                    cx.check_setup(c, self.clr, self.su_clr, "CLR");
                }
                self.load_at_edge = load == 0;
                if load == 0 {
                    for i in 0..4 {
                        cx.check_setup(c, self.d[i], self.su_data, "data");
                    }
                }
                self.last_edge = Some(cx.now());
                if clr == 0 {
                    self.state = 0;
                } else if load == 0 {
                    self.state = 0;
                    for i in 0..4 {
                        self.state |= cx.input(c, self.d[i]) << i;
                    }
                } else if cx.input(c, self.enp) == 1 && cx.input(c, self.ent) == 1 {
                    self.state = (self.state + 1) & 15;
                }
                self.out(cx, c, self.d_clk_q, self.d_clk_rco);
            }
            self.prev = v;
        } else if pin == self.clr {
            if self.sync {
                cx.check_hold(c, pin, self.last_edge, self.h_clr, "CLR");
            } else if cx.input(c, self.clr) == 0 {
                self.state = 0;
                self.out(cx, c, self.d_clr, self.d_clr);
            }
        } else if pin == self.ent {
            cx.check_hold(c, pin, self.last_edge, self.h_en, "ENT");
            let rco = b2u(self.state == 15 && cx.input(c, self.ent) == 1);
            cx.drive(c, self.rco, rco, true, self.d_ent_rco);
        } else if pin == self.enp {
            cx.check_hold(c, pin, self.last_edge, self.h_en, "ENP");
        } else if pin == self.load {
            cx.check_hold(c, pin, self.last_edge, self.h_load, "LOAD");
        } else if self.load_at_edge {
            cx.check_hold(c, pin, self.last_edge, self.h_data, "data");
        }
    }
}

// ---------------------------------------------------------------- 193 up/down counter

/// A 74x193: a 4-bit counter with an up clock and a down clock, each
/// counting on its rising edge while the other is high; an asynchronous
/// reset (MR high) and load (PL low: Q follows P) that override both; and
/// terminal-count outputs that repeat a clock's low phase at 15 (TCU) or
/// 0 (TCD), to clock the next counter.
pub struct Cnt193 {
    cpu: usize,
    cpd: usize,
    mr: usize,
    pl: usize,
    tcu: usize,
    tcd: usize,
    p: [usize; 4],
    q: [usize; 4],
    p_idx: Vec<Option<usize>>,
    state: u8,
    prev_cpu: u8,
    prev_cpd: u8,
    cpu_fall: Option<Time>,
    cpd_fall: Option<Time>,
    cpu_rise: Option<Time>,
    cpd_rise: Option<Time>,
    pl_fall: Option<Time>,
    pl_rise: Option<Time>,
    mr_rise: Option<Time>,
    mr_fall: Option<Time>,
    /// the direction of the last count: true up
    last_up: Option<bool>,
    d_cp_q: Time,
    d_cp_tc: Time,
    d_p_q: Time,
    d_p_tc: Time,
    d_pl_q: Time,
    d_pl_tc: Time,
    d_mr_q: Time,
    d_mr_tc: Time,
    su_p: Time,
    h_p: Time,
    tw_cp: Time,
    /// the low width after a change of direction, the high width, and
    /// the time from one clock's rise to the other's fall: each 0 where
    /// the datasheet gives none
    tw_cp_dir: Time,
    tw_cp_high: Time,
    h_cp_dir: Time,
    tw_pl: Time,
    tw_mr: Time,
    rec_pl: Time,
    rec_mr: Time,
}

impl Cnt193 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Cnt193, Error> {
        let p = s.pins(|i| format!("P{i}"))?;
        let mut state = 0;
        for i in 0..4 {
            state |= rng.bit() << i;
        }
        Ok(Cnt193 {
            cpu: s.pin("CPU")?,
            cpd: s.pin("CPD")?,
            mr: s.pin("MR")?,
            pl: s.pin("PL")?,
            tcu: s.pin("TCU")?,
            tcd: s.pin("TCD")?,
            p_idx: s.index(&p),
            p,
            q: s.pins(|i| format!("Q{i}"))?,
            state,
            prev_cpu: 0,
            prev_cpd: 0,
            cpu_fall: None,
            cpd_fall: None,
            cpu_rise: None,
            cpd_rise: None,
            pl_fall: None,
            pl_rise: None,
            mr_rise: None,
            mr_fall: None,
            last_up: None,
            d_cp_q: s.d("CP->Q")?,
            d_cp_tc: s.d("CP->TC")?,
            d_p_q: s.d("P->Q")?,
            d_p_tc: s.d("P->TC")?,
            d_pl_q: s.d("PL->Q")?,
            d_pl_tc: s.d("PL->TC")?,
            d_mr_q: s.d("MR->Q")?,
            d_mr_tc: s.d("MR->TC")?,
            su_p: s.d("setup P")?,
            h_p: s.d("hold P")?,
            tw_cp: s.d("tw CP")?,
            tw_cp_dir: s.d_or("tw CP dir", 0),
            tw_cp_high: s.d_or("tw CP high", 0),
            h_cp_dir: s.d_or("hold CP dir", 0),
            tw_pl: s.d("tw PL")?,
            tw_mr: s.d("tw MR")?,
            rec_pl: s.d("recovery PL")?,
            rec_mr: s.d("recovery MR")?,
        })
    }

    /// What MR or PL holds the count to: 0 in reset, P while loading.
    fn forced(&self, cx: &Ctx, c: &ChipInfo) -> Option<u8> {
        if cx.input(c, self.mr) == 1 {
            Some(0)
        } else if cx.input(c, self.pl) == 0 {
            Some(bus_value(cx, c, &self.p) as u8)
        } else {
            None
        }
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.prev_cpu = cx.input(c, self.cpu);
        self.prev_cpd = cx.input(c, self.cpd);
        if let Some(v) = self.forced(cx, c) {
            self.state = v;
        }
        self.out(cx, c, 0, 0);
    }

    fn tc(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let tcu = b2u(!(self.state == 15 && cx.input(c, self.cpu) == 0));
        let tcd = b2u(!(self.state == 0 && cx.input(c, self.cpd) == 0));
        cx.drive(c, self.tcu, tcu, true, d);
        cx.drive(c, self.tcd, tcd, true, d);
    }

    fn out(&self, cx: &mut Ctx, c: &ChipInfo, dq: Time, dtc: Time) {
        for i in 0..4 {
            cx.drive(c, self.q[i], (self.state >> i) & 1, true, dq);
        }
        self.tc(cx, c, dtc);
    }

    /// At least `min` must have passed since `since`: a pulse width or a
    /// recovery time.
    fn since(cx: &mut Ctx, c: &ChipInfo, pin: usize, since: Option<Time>, min: Time, what: &str) {
        if let Some(t) = since {
            let slack = cx.now() - t - min;
            if slack < 0 {
                cx.violate(c, pin, what, slack);
            }
        }
    }

    fn clock(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize, up: bool) {
        let v = cx.input(c, pin);
        let prev = if up {
            &mut self.prev_cpu
        } else {
            &mut self.prev_cpd
        };
        if v == *prev {
            return;
        }
        *prev = v;
        let now = cx.now();
        let (fall, rise, other_rise, other) = if up {
            (self.cpu_fall, self.cpu_rise, self.cpd_rise, self.cpd)
        } else {
            (self.cpd_fall, self.cpd_rise, self.cpu_rise, self.cpu)
        };
        if v == 0 {
            Self::since(cx, c, pin, rise, self.tw_cp_high, "tw CP high");
            Self::since(cx, c, pin, other_rise, self.h_cp_dir, "hold CP dir");
            if up {
                self.cpu_fall = Some(now);
            } else {
                self.cpd_fall = Some(now);
            }
            self.tc(cx, c, self.d_cp_tc);
            return;
        }
        if up {
            self.cpu_rise = Some(now);
        } else {
            self.cpd_rise = Some(now);
        }
        if self.last_up == Some(!up) {
            Self::since(cx, c, pin, fall, self.tw_cp_dir, "tw CP dir");
        } else {
            Self::since(cx, c, pin, fall, self.tw_cp, "tw CP");
        }
        if self.forced(cx, c).is_none() {
            Self::since(cx, c, pin, self.pl_rise, self.rec_pl, "recovery PL");
            Self::since(cx, c, pin, self.mr_fall, self.rec_mr, "recovery MR");
            if cx.input(c, other) == 0 {
                cx.violate(c, pin, "count with the other clock low", 0);
            }
            self.state = if up {
                self.state + 1
            } else {
                self.state.wrapping_sub(1)
            } & 15;
            self.last_up = Some(up);
            for i in 0..4 {
                cx.drive(c, self.q[i], (self.state >> i) & 1, true, self.d_cp_q);
            }
        }
        self.tc(cx, c, self.d_cp_tc);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        let now = cx.now();
        if pin == self.cpu || pin == self.cpd {
            self.clock(cx, c, pin, pin == self.cpu);
        } else if pin == self.mr {
            if cx.input(c, pin) == 1 {
                self.mr_rise = Some(now);
                self.state = 0;
                self.out(cx, c, self.d_mr_q, self.d_mr_tc);
            } else {
                Self::since(cx, c, pin, self.mr_rise, self.tw_mr, "tw MR");
                self.mr_fall = Some(now);
                if let Some(v) = self.forced(cx, c) {
                    self.state = v;
                    self.out(cx, c, self.d_pl_q, self.d_pl_tc);
                }
            }
        } else if pin == self.pl {
            let reset = cx.input(c, self.mr) == 1;
            if cx.input(c, pin) == 0 {
                self.pl_fall = Some(now);
                if !reset {
                    self.state = bus_value(cx, c, &self.p) as u8;
                    self.out(cx, c, self.d_pl_q, self.d_pl_tc);
                }
            } else {
                Self::since(cx, c, pin, self.pl_fall, self.tw_pl, "tw PL");
                self.pl_rise = Some(now);
                if !reset {
                    for i in 0..4 {
                        cx.check_setup(c, self.p[i], self.su_p, "P");
                    }
                }
            }
        } else if let Some(i) = self.p_idx[pin] {
            if cx.input(c, self.mr) == 1 {
                return;
            }
            if cx.input(c, self.pl) == 0 {
                let b = cx.input(c, pin);
                self.state = (self.state & !(1 << i)) | (b << i);
                cx.drive(c, self.q[i], b, true, self.d_p_q);
                self.tc(cx, c, self.d_p_tc);
            } else {
                cx.check_hold(c, pin, self.pl_rise, self.h_p, "P");
            }
        }
    }
}

// ---------------------------------------------------------------- 175 quad D flip-flop

pub struct Dff175 {
    clk: usize,
    clr: usize,
    d: [usize; 4],
    q: [usize; 4],
    qn: [usize; 4],
    state: [u8; 4],
    prev: u8,
    last_edge: Option<Time>,
    d_clk: Time,
    d_clr: Time,
    su: Time,
    h: Time,
}

impl Dff175 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Dff175, Error> {
        let mut state = [0; 4];
        for x in &mut state {
            *x = rng.bit();
        }
        Ok(Dff175 {
            clk: s.pin("CLK")?,
            clr: s.pin("CLR")?,
            d: s.pins(|i| format!("{}D", i + 1))?,
            q: s.pins(|i| format!("{}Q", i + 1))?,
            qn: s.pins(|i| format!("{}QN", i + 1))?,
            state,
            prev: 0,
            last_edge: None,
            d_clk: s.d("CLK->Q")?,
            d_clr: s.d("CLR->Q")?,
            su: s.d("setup D")?,
            h: s.d("hold D")?,
        })
    }

    fn out(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        for i in 0..4 {
            cx.drive(c, self.q[i], self.state[i], true, d);
            cx.drive(c, self.qn[i], self.state[i] ^ 1, true, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            if v == 1 && self.prev == 0 && cx.input(c, self.clr) == 1 {
                for i in 0..4 {
                    cx.check_setup(c, self.d[i], self.su, "D");
                    self.state[i] = cx.input(c, self.d[i]);
                }
                self.last_edge = Some(cx.now());
                self.out(cx, c, self.d_clk);
            }
            self.prev = v;
        } else if pin == self.clr {
            if cx.input(c, self.clr) == 0 {
                self.state = [0; 4];
                self.out(cx, c, self.d_clr);
            }
        } else {
            cx.check_hold(c, pin, self.last_edge, self.h, "D");
        }
    }
}

// ---------------------------------------------------------------- 377 octal register with enable

pub struct Reg377 {
    clk: usize,
    en: usize,
    d: [usize; 8],
    q: [usize; 8],
    state: [u8; 8],
    prev: u8,
    last_edge: Option<Time>,
    loaded: bool,
    d_clk: Time,
    su_d: Time,
    h_d: Time,
    su_e: Time,
    h_e: Time,
}

impl Reg377 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Reg377, Error> {
        let mut state = [0; 8];
        for x in &mut state {
            *x = rng.bit();
        }
        Ok(Reg377 {
            clk: s.pin("CLK")?,
            en: s.pin("EN")?,
            d: s.pins(|i| format!("D{}", i + 1))?,
            q: s.pins(|i| format!("Q{}", i + 1))?,
            state,
            prev: 0,
            last_edge: None,
            loaded: false,
            d_clk: s.d("CLK->Q")?,
            su_d: s.d("setup D")?,
            h_d: s.d("hold D")?,
            su_e: s.d("setup EN")?,
            h_e: s.d("hold EN")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for i in 0..8 {
            cx.drive(c, self.q[i], self.state[i], true, 0);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            if v == 1 && self.prev == 0 {
                cx.check_setup(c, self.en, self.su_e, "EN");
                self.last_edge = Some(cx.now());
                self.loaded = cx.input(c, self.en) == 0;
                if self.loaded {
                    for i in 0..8 {
                        cx.check_setup(c, self.d[i], self.su_d, "D");
                        self.state[i] = cx.input(c, self.d[i]);
                        cx.drive(c, self.q[i], self.state[i], true, self.d_clk);
                    }
                }
            }
            self.prev = v;
        } else if pin == self.en {
            cx.check_hold(c, pin, self.last_edge, self.h_e, "EN");
        } else if self.loaded {
            cx.check_hold(c, pin, self.last_edge, self.h_d, "D");
        }
    }
}

// ---------------------------------------------------------------- 541 octal buffer

/// The 74xx541 octal three-state buffer (and the 540, which inverts).
pub struct Buf541 {
    invert: u8,
    oe1: usize,
    oe2: usize,
    a: [usize; 8],
    y: [usize; 8],
    idx: Vec<Option<usize>>,
    enabled: bool,
    en_at: Time,
    d_a: Time,
    d_en: Time,
    d_dis: Time,
}

impl Buf541 {
    fn new(s: &Spec, invert: bool) -> Result<Buf541, Error> {
        let a = s.pins(|i| format!("A{}", i + 1))?;
        Ok(Buf541 {
            invert: invert as u8,
            oe1: s.pin("OE1")?,
            oe2: s.pin("OE2")?,
            a,
            y: s.pins(|i| format!("Y{}", i + 1))?,
            idx: s.index(&a),
            enabled: false,
            en_at: 0,
            d_a: s.d("A->Y")?,
            d_en: s.d("OE->Y en")?,
            d_dis: s.d("OE->Y dis")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.enabled = cx.input(c, self.oe1) == 0 && cx.input(c, self.oe2) == 0;
        for i in 0..8 {
            let v = cx.input(c, self.a[i]) ^ self.invert;
            cx.drive(c, self.y[i], v, self.enabled, 0);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.oe1 || pin == self.oe2 {
            let en = cx.input(c, self.oe1) == 0 && cx.input(c, self.oe2) == 0;
            if en == self.enabled {
                return;
            }
            self.enabled = en;
            let d = if en { self.d_en } else { self.d_dis };
            self.en_at = cx.now() + d;
            for i in 0..8 {
                let v = cx.input(c, self.a[i]) ^ self.invert;
                cx.drive(c, self.y[i], v, en, d);
            }
            return;
        }
        if let Some(i) = self.idx[pin]
            && self.enabled
        {
            let t = (cx.now() + self.d_a).max(self.en_at);
            let v = cx.input(c, self.a[i]) ^ self.invert;
            cx.drive_at(c, self.y[i], v, true, t);
        }
    }
}

// ---------------------------------------------------------------- 688 comparator

pub struct Cmp688 {
    p: [usize; 8],
    q: [usize; 8],
    g: usize,
    peq: usize,
    d_p: Time,
    d_g: Time,
}

impl Cmp688 {
    fn new(s: &Spec) -> Result<Cmp688, Error> {
        Ok(Cmp688 {
            p: s.pins(|i| format!("P{i}"))?,
            q: s.pins(|i| format!("Q{i}"))?,
            g: s.pin("G")?,
            peq: s.pin("PEQ")?,
            d_p: s.d("P->PEQ")?,
            d_g: s.d("G->PEQ")?,
        })
    }

    fn eval_all(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let eq = cx.input(c, self.g) == 0
            && (0..8).all(|i| cx.input(c, self.p[i]) == cx.input(c, self.q[i]));
        cx.drive(c, self.peq, b2u(!eq), true, d);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        self.eval_all(cx, c, if pin == self.g { self.d_g } else { self.d_p });
    }
}

// ---------------------------------------------------------------- 74181 ALU

/// The 74181's outputs for one set of inputs.
#[derive(Debug, PartialEq, Eq)]
pub struct Alu181Out {
    pub f: u8,
    pub aeqb: u8,
    pub p: u8,
    pub g: u8,
    pub cn4: u8,
}

/// The 74181, with active-high data. Per bit: u = A | B&S0 | ~B&S1,
/// v = A&~B&S2 | A&B&S3, half-sum h = u & ~v. True carries
/// c(i+1) = v | u&c(i), c0 = !CN. F = h ^ c in arithmetic mode (M=0) and
/// F = !h in logic mode (M=1). P and G are the active-low group propagate
/// and generate; CN4 is the active-low carry out.
pub fn alu181(a: u8, b: u8, sel: u8, m: u8, cn: u8) -> Alu181Out {
    let (s0, s1, s2, s3) = (sel & 1, (sel >> 1) & 1, (sel >> 2) & 1, (sel >> 3) & 1);
    let (mut u, mut v) = ([0u8; 4], [0u8; 4]);
    for i in 0..4 {
        let (ai, bi) = ((a >> i) & 1, (b >> i) & 1);
        u[i] = ai | (bi & s0) | ((bi ^ 1) & s1);
        v[i] = (ai & (bi ^ 1) & s2) | (ai & bi & s3);
    }
    let mut carry = cn ^ 1;
    let mut f = 0;
    for i in 0..4 {
        let h = u[i] & (v[i] ^ 1);
        let fi = if m == 1 { h ^ 1 } else { h ^ carry };
        f |= fi << i;
        carry = v[i] | (u[i] & carry);
    }
    let gg = v[3] | (u[3] & v[2]) | (u[3] & u[2] & v[1]) | (u[3] & u[2] & u[1] & v[0]);
    let pp = u[0] & u[1] & u[2] & u[3];
    Alu181Out {
        f,
        aeqb: b2u(f == 15),
        p: pp ^ 1,
        g: gg ^ 1,
        cn4: carry ^ 1,
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Alu181Pin {
    Other,
    Data,
    Carry,
    Select,
    Mode,
}

pub struct Alu181 {
    a: [usize; 4],
    b: [usize; 4],
    sel: [usize; 4],
    f: [usize; 4],
    m: usize,
    cn: usize,
    aeqb: usize,
    p: usize,
    g: usize,
    cn4: usize,
    kind: Vec<Alu181Pin>,
    d_ab_f: Time,
    d_ab_f_logic: Time,
    d_ab_p: Time,
    d_ab_g: Time,
    d_ab_c: Time,
    d_eq: Time,
    d_cn_f: Time,
    d_cn_c: Time,
    d_s_f: Time,
    d_m_f: Time,
}

impl Alu181 {
    fn new(s: &Spec) -> Result<Alu181, Error> {
        let a = s.pins(|i| format!("A{i}"))?;
        let b = s.pins(|i| format!("B{i}"))?;
        let sel = s.pins(|i| format!("S{i}"))?;
        let (m, cn) = (s.pin("M")?, s.pin("CN")?);
        let mut kind = vec![Alu181Pin::Other; s.info.pin_names.len()];
        for i in 0..4 {
            kind[a[i]] = Alu181Pin::Data;
            kind[b[i]] = Alu181Pin::Data;
            kind[sel[i]] = Alu181Pin::Select;
        }
        kind[m] = Alu181Pin::Mode;
        kind[cn] = Alu181Pin::Carry;
        Ok(Alu181 {
            a,
            b,
            sel,
            f: s.pins(|i| format!("F{i}"))?,
            m,
            cn,
            aeqb: s.pin("AEQB")?,
            p: s.pin("P")?,
            g: s.pin("G")?,
            cn4: s.pin("CN4")?,
            kind,
            d_ab_f: s.d("AB->F")?,
            d_ab_f_logic: s.d("AB->F logic")?,
            d_ab_p: s.d("AB->P")?,
            d_ab_g: s.d("AB->G")?,
            d_ab_c: s.d("AB->CN4")?,
            d_eq: s.d("AB->AEQB")?,
            d_cn_f: s.d("CN->F")?,
            d_cn_c: s.d("CN->CN4")?,
            d_s_f: s.d("S->F")?,
            d_m_f: s.d("M->F")?,
        })
    }

    /// Drive the outputs that have a delay given; None leaves one alone.
    #[allow(clippy::too_many_arguments)]
    fn eval_all(
        &self,
        cx: &mut Ctx,
        c: &ChipInfo,
        df: Option<Time>,
        dp: Option<Time>,
        dg: Option<Time>,
        dc: Option<Time>,
        de: Option<Time>,
    ) {
        let (mut a, mut b, mut sel) = (0, 0, 0);
        for i in 0..4 {
            a |= cx.input(c, self.a[i]) << i;
            b |= cx.input(c, self.b[i]) << i;
            sel |= cx.input(c, self.sel[i]) << i;
        }
        let o = alu181(a, b, sel, cx.input(c, self.m), cx.input(c, self.cn));
        if let Some(d) = df {
            for i in 0..4 {
                cx.drive(c, self.f[i], (o.f >> i) & 1, true, d);
            }
        }
        if let Some(d) = dp {
            cx.drive(c, self.p, o.p, true, d);
        }
        if let Some(d) = dg {
            cx.drive(c, self.g, o.g, true, d);
        }
        if let Some(d) = dc {
            cx.drive(c, self.cn4, o.cn4, true, d);
        }
        if let Some(d) = de {
            cx.drive(c, self.aeqb, o.aeqb, true, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        match self.kind[pin] {
            Alu181Pin::Data => {
                let df = if cx.input(c, self.m) == 1 {
                    self.d_ab_f_logic
                } else {
                    self.d_ab_f
                };
                self.eval_all(
                    cx,
                    c,
                    Some(df),
                    Some(self.d_ab_p),
                    Some(self.d_ab_g),
                    Some(self.d_ab_c),
                    Some(self.d_eq),
                );
            }
            Alu181Pin::Carry => self.eval_all(
                cx,
                c,
                Some(self.d_cn_f),
                None,
                None,
                Some(self.d_cn_c),
                Some(self.d_cn_f),
            ),
            Alu181Pin::Select => {
                let d = Some(self.d_s_f);
                self.eval_all(cx, c, d, d, d, d, d)
            }
            Alu181Pin::Mode => {
                self.eval_all(cx, c, Some(self.d_m_f), None, None, None, Some(self.d_m_f))
            }
            Alu181Pin::Other => {}
        }
    }
}

// ---------------------------------------------------------------- 74182 carry lookahead

/// The 74182, with the same polarities as the 74181s it connects to: CN
/// and the carry outputs are active-low carries, the P and G inputs
/// active-low.
pub struct Cla182 {
    cn: usize,
    cnx: usize,
    cny: usize,
    cnz: usize,
    p_out: usize,
    g_out: usize,
    p: [usize; 4],
    g: [usize; 4],
    d_pg: Time,
    d_cn: Time,
    d_pp: Time,
    d_pgg: Time,
}

impl Cla182 {
    fn new(s: &Spec) -> Result<Cla182, Error> {
        Ok(Cla182 {
            cn: s.pin("CN")?,
            cnx: s.pin("CNX")?,
            cny: s.pin("CNY")?,
            cnz: s.pin("CNZ")?,
            p_out: s.pin("P")?,
            g_out: s.pin("G")?,
            p: s.pins(|i| format!("P{i}"))?,
            g: s.pins(|i| format!("G{i}"))?,
            d_pg: s.d("PG->CN")?,
            d_cn: s.d("CN->CN")?,
            d_pp: s.d("P->P")?,
            d_pgg: s.d("PG->G")?,
        })
    }

    fn eval_all(
        &self,
        cx: &mut Ctx,
        c: &ChipInfo,
        dc: Option<Time>,
        dp: Option<Time>,
        dg: Option<Time>,
    ) {
        let (mut p, mut g) = ([0u8; 4], [0u8; 4]);
        for i in 0..4 {
            p[i] = cx.input(c, self.p[i]) ^ 1;
            g[i] = cx.input(c, self.g[i]) ^ 1;
        }
        let c0 = cx.input(c, self.cn) ^ 1;
        let c1 = g[0] | (p[0] & c0);
        let c2 = g[1] | (p[1] & c1);
        let c3 = g[2] | (p[2] & c2);
        if let Some(d) = dc {
            cx.drive(c, self.cnx, c1 ^ 1, true, d);
            cx.drive(c, self.cny, c2 ^ 1, true, d);
            cx.drive(c, self.cnz, c3 ^ 1, true, d);
        }
        if let Some(d) = dp {
            cx.drive(c, self.p_out, (p[0] & p[1] & p[2] & p[3]) ^ 1, true, d);
        }
        if let Some(d) = dg {
            let gg = g[3] | (p[3] & g[2]) | (p[3] & p[2] & g[1]) | (p[3] & p[2] & p[1] & g[0]);
            cx.drive(c, self.g_out, gg ^ 1, true, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.cn {
            self.eval_all(cx, c, Some(self.d_cn), None, None);
        } else {
            self.eval_all(cx, c, Some(self.d_pg), Some(self.d_pp), Some(self.d_pgg));
        }
    }
}

// ---------------------------------------------------------------- static RAM

#[derive(Clone, Copy, PartialEq, Eq)]
enum SramPin {
    Other,
    Addr,
    Data,
    Enable,
    Output,
    Write,
}

pub struct Sram {
    a: Vec<usize>,
    io: [usize; 8],
    ce: usize,
    oe: usize,
    we: usize,
    kind: Vec<SramPin>,
    /// The address, kept up to date as its pins change.
    addr: usize,
    addr_mask: Vec<u64>,
    pub mem: Vec<u8>,
    reading: bool,
    we_low: bool,
    we_fall: Time,
    we_rise: Option<Time>,
    t_aa: Time,
    t_ace: Time,
    t_oe: Time,
    t_ohz: Time,
    t_chz: Time,
    t_whz: Time,
    t_as: Time,
    t_aw: Time,
    t_wp: Time,
    t_dw: Time,
    t_dh: Time,
    t_wr: Time,
}

impl Sram {
    fn new(s: &Spec, rng: &mut Rng, preload: Option<&[u8]>) -> Result<Sram, Error> {
        let mut kind = vec![SramPin::Other; s.info.pin_names.len()];
        let mut a = Vec::new();
        while s.has(&format!("A{}", a.len())) {
            let p = s.pin(&format!("A{}", a.len()))?;
            kind[p] = SramPin::Addr;
            a.push(p);
        }
        let io = s.pins(|i| format!("IO{i}"))?;
        for &p in &io {
            kind[p] = SramPin::Data;
        }
        let (ce, oe, we) = (s.pin("CE")?, s.pin("OE")?, s.pin("WE")?);
        kind[ce] = SramPin::Enable;
        kind[oe] = SramPin::Output;
        kind[we] = SramPin::Write;
        let size = 1 << a.len();
        let mem = match preload {
            Some(img) => {
                let mut mem = vec![0; size];
                let n = img.len().min(size);
                mem[..n].copy_from_slice(&img[..n]);
                mem
            }
            None => (0..size).map(|_| rng.byte()).collect(),
        };
        let t_ohz = s.d("tOHZ")?;
        Ok(Sram {
            addr: 0,
            addr_mask: s.masks(&a),
            a,
            io,
            ce,
            oe,
            we,
            kind,
            mem,
            reading: false,
            we_low: false,
            we_fall: 0,
            we_rise: None,
            t_aa: s.d("tAA")?,
            t_ace: s.d("tACE")?,
            t_oe: s.d("tOE")?,
            t_ohz,
            t_chz: s.d("tCHZ")?,
            t_whz: s.d_or("tWHZ", t_ohz),
            t_as: s.d("tAS")?,
            t_aw: s.d("tAW")?,
            t_wp: s.d("tWP")?,
            t_dw: s.d("tDW")?,
            t_dh: s.d_or("tDH", 0),
            t_wr: s.d_or("tWR", 0),
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.addr = bus_value(cx, c, &self.a);
        self.update(cx, c, 0);
    }

    fn last_addr_change(&self, cx: &Ctx, c: &ChipInfo) -> Time {
        self.a
            .iter()
            .map(|&p| cx.last_change(c, p))
            .fold(crate::sim::NEVER, Time::max)
    }

    fn update(&mut self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let read =
            cx.input(c, self.ce) == 0 && cx.input(c, self.oe) == 0 && cx.input(c, self.we) == 1;
        if read {
            let v = self.mem[self.addr];
            for i in 0..8 {
                cx.drive(c, self.io[i], (v >> i) & 1, true, d);
            }
        } else if self.reading {
            for i in 0..8 {
                let v = cx.driven(c, self.io[i]);
                cx.drive(c, self.io[i], v, false, d);
            }
        }
        self.reading = read;
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        follow(&mut self.addr, self.addr_mask[pin], cx.input(c, pin));
        match self.kind[pin] {
            SramPin::Addr => {
                if self.we_low && cx.input(c, self.ce) == 0 {
                    cx.violate(c, pin, "address changed during write", 0);
                }
                cx.check_hold(c, pin, self.we_rise, self.t_wr, "address after write");
                if self.reading {
                    self.update(cx, c, self.t_aa);
                }
            }
            SramPin::Data => {
                if !self.reading {
                    cx.check_hold(c, pin, self.we_rise, self.t_dh, "data after write");
                }
            }
            SramPin::Write | SramPin::Enable => {
                let (we, ce) = (cx.input(c, self.we), cx.input(c, self.ce));
                let active = we == 0 && ce == 0;
                if active && !self.we_low {
                    self.we_low = true;
                    self.we_fall = cx.now();
                    let slack = cx.now() - self.last_addr_change(cx, c) - self.t_as;
                    if slack < 0 {
                        cx.violate(c, pin, "tAS address setup to write", slack);
                    }
                } else if !active && self.we_low {
                    self.we_low = false;
                    self.we_rise = Some(cx.now());
                    let slack = cx.now() - self.we_fall - self.t_wp;
                    if slack < 0 {
                        cx.violate(c, pin, "tWP write pulse width", slack);
                    }
                    let slack = cx.now() - self.last_addr_change(cx, c) - self.t_aw;
                    if slack < 0 {
                        cx.violate(c, pin, "tAW address valid to end of write", slack);
                    }
                    let (mut v, mut last) = (0u8, crate::sim::NEVER);
                    for i in 0..8 {
                        v |= cx.input(c, self.io[i]) << i;
                        last = last.max(cx.last_change(c, self.io[i]));
                        if cx.contended(c, self.io[i]) {
                            cx.violate(c, self.io[i], "data under contention at end of write", 0);
                        }
                    }
                    let slack = cx.now() - last - self.t_dw;
                    if slack < 0 {
                        cx.violate(c, pin, "tDW data setup to end of write", slack);
                    }
                    self.mem[self.addr] = v;
                }
                let d = if self.kind[pin] == SramPin::Write {
                    if we == 0 { self.t_whz } else { self.t_oe }
                } else if ce == 1 {
                    self.t_chz
                } else {
                    self.t_ace
                };
                self.update(cx, c, d);
            }
            SramPin::Output => {
                let d = if cx.input(c, self.oe) == 1 {
                    self.t_ohz
                } else {
                    self.t_oe
                };
                self.update(cx, c, d);
            }
            SramPin::Other => {}
        }
    }
}

// ---------------------------------------------------------------- flash ROM (read only)

pub struct Rom {
    a: [usize; 17],
    dq: [usize; 8],
    ce: usize,
    oe: usize,
    is_a: Vec<bool>,
    /// The address, kept up to date as its pins change.
    addr: usize,
    addr_mask: Vec<u64>,
    mem: Vec<u8>,
    t_acc: Time,
    t_ce: Time,
    t_oe: Time,
    t_df: Time,
}

impl Rom {
    fn new(s: &Spec, preload: Option<&[u8]>) -> Result<Rom, Error> {
        let a: [usize; 17] = s.pins(|i| format!("A{i}"))?;
        let mut is_a = vec![false; s.info.pin_names.len()];
        for &p in &a {
            is_a[p] = true;
        }
        let mut mem = vec![0; 1 << 17];
        if let Some(img) = preload {
            let n = img.len().min(mem.len());
            mem[..n].copy_from_slice(&img[..n]);
        }
        Ok(Rom {
            addr: 0,
            addr_mask: s.masks(&a),
            a,
            dq: s.pins(|i| format!("D{i}"))?,
            ce: s.pin("CE")?,
            oe: s.pin("OE")?,
            is_a,
            mem,
            t_acc: s.d("tACC")?,
            t_ce: s.d("tCE")?,
            t_oe: s.d("tOE")?,
            t_df: s.d("tDF")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.addr = bus_value(cx, c, &self.a);
        self.update(cx, c, 0);
    }

    fn update(&mut self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        if cx.input(c, self.ce) == 0 && cx.input(c, self.oe) == 0 {
            let v = self.mem[self.addr];
            for i in 0..8 {
                cx.drive(c, self.dq[i], (v >> i) & 1, true, d);
            }
        } else {
            for i in 0..8 {
                let v = cx.driven(c, self.dq[i]);
                cx.drive(c, self.dq[i], v, false, self.t_df);
            }
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        follow(&mut self.addr, self.addr_mask[pin], cx.input(c, pin));
        let d = if self.is_a[pin] {
            self.t_acc
        } else if pin == self.ce {
            self.t_ce
        } else {
            self.t_oe
        };
        self.update(cx, c, d);
    }
}

// ---------------------------------------------------------------- I/O page

/// The I/O page: console, timer and cycle counter. Read side effects and
/// the timer happen at clock edges; writes take effect at the end of the
/// write strobe.
///
/// Draft 0's (`iodev`) has the register semantics of the draft 0 simulator
/// (studies/v0_hw/sim.py). Draft 1's (`iodev32`) has 32-bit registers 4
/// apart, seen a half at a time over the 16-bit bus, with the rules of the
/// IODev in studies/v1b_hw/rtl.py: console data at 0 (reading the low half
/// consumes a byte; the high half is FFFF after an empty read), status at
/// 4, timer period at 8/A (writing the low half sets the period, the high
/// half adds the top bits), timer flag at C, cycle counter at 10/12.
pub struct IoDev {
    /// Draft 1's 32-bit registers, not draft 0's 16-bit ones.
    wide: bool,
    clk: usize,
    iosel: usize,
    rd: usize,
    wel: usize,
    weh: usize,
    irq: usize,
    a: [usize; 8],
    d: [usize; 16],
    prev: u8,
    writing: bool,
    driving: bool,
    /// Byte lanes of the current write: 1 low, 2 high.
    lanes: u8,
    pub input: Vec<u8>,
    input_pos: usize,
    pub output: Vec<u8>,
    pub timer_period: i64,
    timer_count: i64,
    timer_flag: u8,
    last_empty: bool,
    cycle_hi: u16,
    d_acc: Time,
}

impl IoDev {
    fn new(s: &Spec, wide: bool) -> Result<IoDev, Error> {
        Ok(IoDev {
            wide,
            clk: s.pin("CLK")?,
            iosel: s.pin("IOSEL")?,
            rd: s.pin("RD")?,
            wel: s.pin("WEL")?,
            weh: s.pin("WEH")?,
            irq: s.pin("IRQ")?,
            a: s.pins(|i| format!("A{i}"))?,
            d: s.pins(|i| format!("D{i}"))?,
            prev: 0,
            writing: false,
            driving: false,
            lanes: 0,
            input: Vec::new(),
            input_pos: 0,
            output: Vec::new(),
            timer_period: 0,
            timer_count: 0,
            timer_flag: 0,
            last_empty: false,
            cycle_hi: 0,
            d_acc: 20000,
        })
    }

    fn addr(&self, cx: &Ctx, c: &ChipInfo) -> usize {
        let a: usize = self
            .a
            .iter()
            .enumerate()
            .map(|(i, &p)| (cx.input(c, p) as usize) << i)
            .sum();
        a & !1
    }

    fn pending_input(&self) -> Option<u8> {
        self.input.get(self.input_pos).copied()
    }

    fn value(&self, cycle: i64, a: usize) -> u16 {
        let has_input = self.pending_input().is_some();
        if self.wide {
            match a {
                0x00 => self.pending_input().map_or(0xFFFF, u16::from),
                0x02 => {
                    if self.last_empty {
                        0xFFFF
                    } else {
                        0
                    }
                }
                0x04 => {
                    if has_input {
                        1
                    } else {
                        2
                    }
                }
                0x08 => self.timer_period as u16,
                0x0A => (self.timer_period >> 16) as u16,
                0x0C => self.timer_flag as u16,
                0x10 => cycle as u16,
                0x12 => self.cycle_hi,
                _ => 0,
            }
        } else {
            match a {
                0x00 => self.pending_input().map_or(0xFFFF, u16::from),
                // 2 is the end of input: all input is supplied up front
                0x02 => {
                    if has_input {
                        1
                    } else {
                        2
                    }
                }
                0x06 => self.timer_flag as u16,
                0x08 => cycle as u16,
                0x0A => self.cycle_hi,
                _ => 0,
            }
        }
    }

    /// A read of address a, at a clock edge.
    fn read_edge(&mut self, cycle: i64, a: usize) {
        let (console, counter) = if self.wide {
            (0x00, 0x10)
        } else {
            (0x00, 0x08)
        };
        if a == console {
            if self.pending_input().is_some() {
                self.input_pos += 1;
                self.last_empty = false;
            } else {
                self.last_empty = true;
            }
        } else if a == counter {
            self.cycle_hi = (cycle >> 16) as u16;
        }
    }

    /// The end of a write of v to address a.
    fn write(&mut self, a: usize, v: u16) {
        if self.wide {
            match a {
                0x00 => {
                    if self.lanes & 1 != 0 {
                        self.output.push(v as u8);
                    }
                }
                0x08 => {
                    self.timer_period = v as i64;
                    self.timer_count = 0;
                    if v == 0 {
                        self.timer_flag = 0;
                    }
                }
                0x0A => {
                    self.timer_period = (self.timer_period & 0xFFFF) | (v as i64) << 16;
                    self.timer_count = 0;
                    if self.timer_period == 0 {
                        self.timer_flag = 0;
                    }
                }
                0x0C | 0x0E => self.timer_flag = 0,
                _ => {}
            }
        } else {
            match a {
                0x00 => self.output.push(v as u8),
                0x04 => {
                    self.timer_period = v as i64;
                    self.timer_count = 0;
                    if v == 0 {
                        self.timer_flag = 0;
                    }
                }
                0x06 => self.timer_flag = 0,
                _ => {}
            }
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if !cx.state.check_on {
            return; // power-up and reset: the bus isn't meaningful yet
        }
        let cycle = cx.state.cycle;
        let sel = cx.input(c, self.iosel) == 0;
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            if v == 1 && self.prev == 0 {
                if sel && cx.input(c, self.rd) == 0 {
                    let a = self.addr(cx, c);
                    self.read_edge(cycle, a);
                }
                if self.timer_period > 0 && cycle >= 0 {
                    self.timer_count += 1;
                    if self.timer_count >= self.timer_period {
                        self.timer_flag = 1;
                        self.timer_count = 0;
                    }
                }
                cx.drive(c, self.irq, self.timer_flag, true, 5000);
            }
            self.prev = v;
        }
        let (wl, wh) = (cx.input(c, self.wel) == 0, cx.input(c, self.weh) == 0);
        let wr = sel && (wl || wh);
        if wr {
            self.lanes = wl as u8 | (wh as u8) << 1;
        }
        if self.writing && !wr {
            let v = (0..16).map(|i| (cx.input(c, self.d[i]) as u16) << i).sum();
            let a = self.addr(cx, c);
            self.write(a, v);
            cx.drive(c, self.irq, self.timer_flag, true, 5000);
        }
        self.writing = wr;
        if sel && cx.input(c, self.rd) == 0 {
            let v = self.value(cycle, self.addr(cx, c));
            for i in 0..16 {
                cx.drive(c, self.d[i], ((v >> i) & 1) as u8, true, self.d_acc);
            }
            self.driving = true;
        } else if self.driving {
            for i in 0..16 {
                let v = cx.driven(c, self.d[i]);
                cx.drive(c, self.d[i], v, false, 10000);
            }
            self.driving = false;
        }
    }
}

// ---------------------------------------------------------------- 109 dual J-K flip-flop

struct Jk109Section {
    j: usize,
    k: usize,
    clk: usize,
    pre: usize,
    clr: usize,
    q: usize,
    qn: usize,
    prev: u8,
    state: u8,
    last_edge: Option<Time>,
}

/// The 74F109: positive-edge J-K̄ flip-flops with preset and clear. At an
/// edge, J K̄ = 00 resets, 01 holds, 10 toggles and 11 sets.
pub struct Jk109 {
    sec: [Jk109Section; 2],
    d_clk: Time,
    d_pc: Time,
    setup: Time,
    hold: Time,
}

impl Jk109 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Jk109, Error> {
        let mut section = |i: usize| -> Result<Jk109Section, Error> {
            let p = |n: &str| s.pin(&format!("{}{}", i + 1, n));
            Ok(Jk109Section {
                j: p("J")?,
                k: p("K")?,
                clk: p("CLK")?,
                pre: p("PRE")?,
                clr: p("CLR")?,
                q: p("Q")?,
                qn: p("QN")?,
                prev: 0,
                state: rng.bit(),
                last_edge: None,
            })
        };
        let sec = [section(0)?, section(1)?];
        Ok(Jk109 {
            sec,
            d_clk: s.d("CLK->Q")?,
            d_pc: s.d("PRE/CLR->Q")?,
            setup: s.d("setup JK")?,
            hold: s.d("hold JK")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for x in &self.sec {
            Self::out(cx, c, x, 0);
        }
    }

    fn out(cx: &mut Ctx, c: &ChipInfo, x: &Jk109Section, d: Time) {
        let (pre, clr) = (cx.input(c, x.pre), cx.input(c, x.clr));
        let (q, qn) = if pre == 0 && clr == 0 {
            (1, 1)
        } else {
            (x.state, x.state ^ 1)
        };
        cx.drive(c, x.q, q, true, d);
        cx.drive(c, x.qn, qn, true, d);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        for x in &mut self.sec {
            if pin == x.clk {
                let v = cx.input(c, x.clk);
                if v == 1 && x.prev == 0 && cx.input(c, x.pre) == 1 && cx.input(c, x.clr) == 1 {
                    cx.check_setup(c, x.j, self.setup, "J");
                    cx.check_setup(c, x.k, self.setup, "K");
                    x.state = match (cx.input(c, x.j), cx.input(c, x.k)) {
                        (0, 0) => 0,
                        (0, _) => x.state,
                        (_, 0) => x.state ^ 1,
                        _ => 1,
                    };
                    x.last_edge = Some(cx.now());
                    Self::out(cx, c, x, self.d_clk);
                }
                x.prev = v;
            } else if pin == x.pre || pin == x.clr {
                if cx.input(c, x.pre) == 0 {
                    x.state = 1;
                }
                if cx.input(c, x.clr) == 0 {
                    x.state = 0;
                }
                Self::out(cx, c, x, self.d_pc);
            } else if pin == x.j || pin == x.k {
                cx.check_hold(c, pin, x.last_edge, self.hold, "JK");
            }
        }
    }
}

// ---------------------------------------------------------------- D registers (574, 823)

/// A register of D flip-flops on one clock: pins D1..Dn and Q1..Qn, CLK,
/// and optionally EN (active-low clock enable), CLR (active-low,
/// asynchronous) and OE (active-low output enable, with three-state Q
/// pins). The 74ABT574 has OE; the 74ABT823 has all three; the 74ABT534
/// is a 574 with inverting outputs.
pub struct DReg {
    invert: u8,
    clk: usize,
    en: Option<usize>,
    clr: Option<usize>,
    oe: Option<usize>,
    d: Vec<usize>,
    q: Vec<usize>,
    is_d: Vec<bool>,
    state: Vec<u8>,
    prev: u8,
    last_edge: Option<Time>,
    loaded: bool,
    enabled: bool,
    d_clk: Time,
    d_clr: Time,
    d_en: Time,
    d_dis: Time,
    su_d: Time,
    h_d: Time,
    su_e: Time,
    h_e: Time,
}

impl DReg {
    fn new(s: &Spec, rng: &mut Rng, invert: bool) -> Result<DReg, Error> {
        let (mut d, mut q) = (Vec::new(), Vec::new());
        while s.has(&format!("D{}", d.len() + 1)) {
            d.push(s.pin(&format!("D{}", d.len() + 1))?);
            q.push(s.pin(&format!("Q{}", q.len() + 1))?);
        }
        let opt = |n: &str| {
            if s.has(n) {
                s.pin(n).map(Some)
            } else {
                Ok(None)
            }
        };
        let (en, clr, oe) = (opt("EN")?, opt("CLR")?, opt("OE")?);
        let mut is_d = vec![false; s.info.pin_names.len()];
        for &p in &d {
            is_d[p] = true;
        }
        Ok(DReg {
            invert: invert as u8,
            clk: s.pin("CLK")?,
            en,
            clr,
            oe,
            state: (0..d.len()).map(|_| rng.bit()).collect(),
            d,
            q,
            is_d,
            prev: 0,
            last_edge: None,
            loaded: false,
            enabled: oe.is_none(),
            d_clk: s.d("CLK->Q")?,
            d_clr: if clr.is_some() { s.d("CLR->Q")? } else { 0 },
            d_en: if oe.is_some() { s.d("OE->Y en")? } else { 0 },
            d_dis: if oe.is_some() { s.d("OE->Y dis")? } else { 0 },
            su_d: s.d("setup D")?,
            h_d: s.d("hold D")?,
            su_e: if en.is_some() { s.d("setup EN")? } else { 0 },
            h_e: if en.is_some() { s.d("hold EN")? } else { 0 },
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        if let Some(oe) = self.oe {
            self.enabled = cx.input(c, oe) == 0;
        }
        self.out(cx, c, 0);
    }

    fn out(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        for (i, &q) in self.q.iter().enumerate() {
            cx.drive(c, q, self.state[i] ^ self.invert, self.enabled, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            let cleared = self.clr.is_some_and(|p| cx.input(c, p) == 0);
            if v == 1 && self.prev == 0 && !cleared {
                if let Some(en) = self.en {
                    cx.check_setup(c, en, self.su_e, "EN");
                }
                self.last_edge = Some(cx.now());
                self.loaded = self.en.is_none_or(|en| cx.input(c, en) == 0);
                if self.loaded {
                    for i in 0..self.d.len() {
                        cx.check_setup(c, self.d[i], self.su_d, "D");
                        self.state[i] = cx.input(c, self.d[i]);
                    }
                    self.out(cx, c, self.d_clk);
                }
            }
            self.prev = v;
        } else if Some(pin) == self.clr {
            if cx.input(c, pin) == 0 {
                self.state.fill(0);
                self.out(cx, c, self.d_clr);
            }
        } else if Some(pin) == self.oe {
            let en = cx.input(c, pin) == 0;
            if en != self.enabled {
                self.enabled = en;
                self.out(cx, c, if en { self.d_en } else { self.d_dis });
            }
        } else if Some(pin) == self.en {
            cx.check_hold(c, pin, self.last_edge, self.h_e, "EN");
        } else if self.is_d[pin] && self.loaded {
            cx.check_hold(c, pin, self.last_edge, self.h_d, "D");
        }
    }
}

// ---------------------------------------------------------------- 573 transparent latch

/// The 74xx573 octal transparent latch with three-state outputs: Q follows
/// D while LE is high and keeps what D was when LE fell; OE (active low)
/// turns the outputs on. D must be steady `setup D` before LE falls and
/// `hold D` after.
pub struct Latch573 {
    le: usize,
    oe: usize,
    d: [usize; 8],
    q: [usize; 8],
    d_idx: Vec<Option<usize>>,
    state: [u8; 8],
    enabled: bool,
    last_fall: Option<Time>,
    d_dq: Time,
    d_leq: Time,
    d_en: Time,
    d_dis: Time,
    su_d: Time,
    h_d: Time,
}

impl Latch573 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Latch573, Error> {
        let d = s.pins(|i| format!("D{}", i + 1))?;
        let mut state = [0; 8];
        for b in state.iter_mut() {
            *b = rng.bit();
        }
        Ok(Latch573 {
            le: s.pin("LE")?,
            oe: s.pin("OE")?,
            d_idx: s.index(&d),
            d,
            q: s.pins(|i| format!("Q{}", i + 1))?,
            state,
            enabled: false,
            last_fall: None,
            d_dq: s.d("D->Q")?,
            d_leq: s.d("LE->Q")?,
            d_en: s.d("OE->Y en")?,
            d_dis: s.d("OE->Y dis")?,
            su_d: s.d("setup D")?,
            h_d: s.d("hold D")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.enabled = cx.input(c, self.oe) == 0;
        if cx.input(c, self.le) == 1 {
            for i in 0..8 {
                self.state[i] = cx.input(c, self.d[i]);
            }
        }
        self.out(cx, c, 0);
    }

    fn out(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        for i in 0..8 {
            cx.drive(c, self.q[i], self.state[i], self.enabled, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.le {
            if cx.input(c, self.le) == 1 {
                for i in 0..8 {
                    self.state[i] = cx.input(c, self.d[i]);
                }
                self.out(cx, c, self.d_leq);
            } else {
                for i in 0..8 {
                    cx.check_setup(c, self.d[i], self.su_d, "D");
                }
                self.last_fall = Some(cx.now());
            }
        } else if pin == self.oe {
            let en = cx.input(c, pin) == 0;
            if en != self.enabled {
                self.enabled = en;
                self.out(cx, c, if en { self.d_en } else { self.d_dis });
            }
        } else if let Some(i) = self.d_idx[pin] {
            if cx.input(c, self.le) == 1 {
                self.state[i] = cx.input(c, pin);
                cx.drive(c, self.q[i], self.state[i], self.enabled, self.d_dq);
            } else {
                cx.check_hold(c, pin, self.last_fall, self.h_d, "D");
            }
        }
    }
}

// ---------------------------------------------------------------- 32-bit I/O page

/// Draft 1's I/O page (console, timer, cycle counter) as a test fixture
/// on a 32-bit data bus: what draft 2's register-transfer model reaches
/// through its 16-bit console card, one 16-bit register access per half
/// whose byte enables are on, low half first. A read of one half drives
/// it on both halves; a word read of the console register gives the
/// input character, or 0xFFFF, and above it the end-of-input flag that
/// read leaves behind. Pins: A2-A7 (the word), BE0-BE3 (the byte lanes),
/// IOSEL, RD and WR active low; a write happens when WR rises. The input
/// is the chip's preload.
///
/// With pins LV1-LV8 it is also a CPU card's registers (RFC 0040, 3), and
/// the I/O page is only where A27-A24 are 0xF; where they are 0, the
/// registers: control (NMI in bit 3), the request register (bit L - 1
/// for level L: set, clear, read), the message register (claim, write,
/// release, read; on B0-B31 while MSGOE is low, as {message, source},
/// released at that cycle's CLK edge) and the timer, which counts every third MCLK edge from the
/// last CLK edge with RESET_n low and ticks on counter bit `tick_bit`
/// (a parameter, -1 none); the count and the tick change only at CLK
/// edges, as a register clocked by CLK would see them. LV1-LV8 are the levels (active low), MSGF the
/// message register full, NMI the NMI, cleared at a CLK edge with NMIACK
/// high. Its outputs change 12 ns after the edge that changes them, so a
/// CLK edge in the same master-clock tick doesn't see them; a register
/// reads onto D 10 ns after RD falls (the I/O page, 20 ns).
pub struct IoDevW {
    clk: usize,
    iosel: usize,
    rd: usize,
    wr: usize,
    irq: usize,
    a: [usize; 6],
    be: [usize; 4],
    d: [usize; 32],
    prev: u8,
    writing: bool,
    driving: bool,
    input: Vec<u8>,
    input_pos: usize,
    pub output: Vec<u8>,
    timer_period: i64,
    timer_count: i64,
    timer_flag: u8,
    last_empty: bool,
    cycle_hi: u16,
    d_acc: Time,
    card: Option<Box<Card>>,
    wr_off: Option<usize>,
}

/// The CPU card's registers, in an IoDevW.
struct Card {
    mclk: usize,
    rstn: usize,
    a_mid: [usize; 8],
    a_top: [usize; 4],
    lv: [usize; 8],
    msgf: usize,
    nmi: usize,
    msgoe: usize,
    nmiack: usize,
    b: [usize; 32],
    req: u16,
    msg_state: u8,
    msg: u32,
    nmi_latch: u8,
    count: u64,
    ticks: u64,
    started: bool,
    tick: u8,
    tick_bit: i64,
    prev_mclk: u8,
    b_driving: bool,
}

const MSG_FREE: u8 = 0;
const MSG_CLAIMED: u8 = 1;
const MSG_FULL: u8 = 2;
const CARD_DELAY: Time = 12000;
/// The registers' read access from RD: a buffer's enable onto the data bus.
const CARD_READ: Time = 10000;

impl Card {
    fn levels(&self) -> u16 {
        let lv =
            self.req << 1 | (self.tick as u16) << 6 | ((self.msg_state == MSG_FULL) as u16) << 7;
        lv & 0x1FE
    }

    fn outputs(&self, cx: &mut Ctx, c: &ChipInfo) {
        let lv = self.levels();
        for k in 0..8 {
            cx.drive(c, self.lv[k], b2u(lv >> (k + 1) & 1 == 0), true, CARD_DELAY);
        }
        cx.drive(
            c,
            self.msgf,
            b2u(self.msg_state == MSG_FULL),
            true,
            CARD_DELAY,
        );
        cx.drive(c, self.nmi, self.nmi_latch, true, CARD_DELAY);
    }

    /// RESET: the registers clear, the message register free, the timer
    /// at 0.
    fn reset(&mut self) {
        self.req = 0;
        self.msg_state = MSG_FREE;
        self.nmi_latch = 0;
        self.count = 0;
        self.ticks = 0;
        self.tick = 0;
        self.started = false;
    }

    /// A CPU clock edge: the count from the master-clock ticks, and the tick
    /// if counter bit `tick_bit` has gone from 0 to 1 since the last.
    fn clock(&mut self) {
        let new = self.ticks / 3;
        if self.tick_bit >= 0 {
            let (n, half) = (self.tick_bit as u32, 1u64 << self.tick_bit);
            if (new + half) >> (n + 1) != (self.count + half) >> (n + 1) {
                self.tick = 1;
            }
        }
        self.count = new;
    }

    /// A read's value; at the edge that ends it (`edge`), its side effects.
    fn read(&mut self, off: usize, edge: bool) -> u32 {
        match off {
            0x0000 => 1 | 4 | (self.nmi_latch as u32) << 3,
            0x1000 => 0x3C10,
            0x2008 => self.req as u32,
            0x3000 => {
                if self.msg_state == MSG_FREE {
                    if edge {
                        self.msg_state = MSG_CLAIMED;
                    }
                    0
                } else {
                    1
                }
            }
            0x300C => self.msg,
            0x4000 => self.count as u32,
            _ => 0,
        }
    }

    fn write(&mut self, off: usize, v: u32) {
        match off {
            0x0000 if v & 8 != 0 => self.nmi_latch = 1,
            0x2000 => self.req |= (v & 0xFF) as u16,
            0x2004 => self.req &= !(v & 0xFF) as u16,
            0x3004 if self.msg_state == MSG_CLAIMED => {
                self.msg = v;
                self.msg_state = MSG_FULL;
            }
            0x3008 => self.msg_state = MSG_FREE,
            0x4004 if v & 1 != 0 => self.tick = 0,
            _ => {}
        }
    }
}

impl IoDevW {
    fn new(s: &Spec, preload: Option<&[u8]>) -> Result<IoDevW, Error> {
        Ok(IoDevW {
            clk: s.pin("CLK")?,
            iosel: s.pin("IOSEL")?,
            rd: s.pin("RD")?,
            wr: s.pin("WR")?,
            irq: s.pin("IRQ")?,
            a: s.pins(|i| format!("A{}", i + 2))?,
            be: s.pins(|i| format!("BE{i}"))?,
            d: s.pins(|i| format!("D{i}"))?,
            prev: 0,
            writing: false,
            driving: false,
            input: preload.map(|p| p.to_vec()).unwrap_or_default(),
            input_pos: 0,
            output: Vec::new(),
            timer_period: 0,
            timer_count: 0,
            timer_flag: 0,
            last_empty: false,
            cycle_hi: 0,
            d_acc: 20000,
            card: if s.has("LV1") {
                Some(Box::new(Card {
                    mclk: s.pin("MCLK")?,
                    rstn: s.pin("RESET_n")?,
                    a_mid: s.pins(|i| format!("A{}", i + 8))?,
                    a_top: s.pins(|i| format!("A{}", i + 24))?,
                    lv: s.pins(|i| format!("LV{}", i + 1))?,
                    msgf: s.pin("MSGF")?,
                    nmi: s.pin("NMI")?,
                    msgoe: s.pin("MSGOE")?,
                    nmiack: s.pin("NMIACK")?,
                    b: s.pins(|i| format!("B{i}"))?,
                    req: 0,
                    msg_state: MSG_FREE,
                    msg: 0,
                    nmi_latch: 0,
                    count: 0,
                    ticks: 0,
                    started: false,
                    tick: 0,
                    tick_bit: s.param_or("tick_bit", -1),
                    prev_mclk: 0,
                    b_driving: false,
                }))
            } else {
                None
            },
            wr_off: None,
        })
    }

    /// With a card: the register offset an access is at, or None for the
    /// I/O page.
    fn card_off(&self, cx: &Ctx, c: &ChipInfo) -> Option<usize> {
        let card = self.card.as_ref()?;
        if bus_value(cx, c, &card.a_top) != 0 {
            return None;
        }
        let mid = bus_value(cx, c, &card.a_mid);
        Some((mid & 0xF0) << 8 | (bus_value(cx, c, &self.a) << 2) & 0x0C)
    }

    fn word(&self, cx: &Ctx, c: &ChipInfo) -> usize {
        (bus_value(cx, c, &self.a) << 2) & 0xFC
    }

    /// The halves an access covers (bit 0 low, bit 1 high), from its byte
    /// enables.
    fn halves(&self, cx: &Ctx, c: &ChipInfo) -> u8 {
        let on = |i: usize| cx.input(c, self.be[i]) == 0;
        b2u(on(0) || on(1)) | b2u(on(2) || on(3)) << 1
    }

    fn pending(&self) -> bool {
        self.input_pos < self.input.len()
    }

    /// The value a read of the 16-bit register at `a` gives, and whether
    /// the end-of-input flag is set after it (`empty`: before it).
    fn read16(&self, cycle: i64, a: usize, empty: bool) -> (u16, bool) {
        match a {
            0x00 => {
                if self.pending() {
                    (self.input[self.input_pos] as u16, false)
                } else {
                    (0xFFFF, true)
                }
            }
            0x02 => (if empty { 0xFFFF } else { 0 }, empty),
            0x04 => (if self.pending() { 1 } else { 2 }, empty),
            0x08 => (self.timer_period as u16, empty),
            0x0A => ((self.timer_period >> 16) as u16, empty),
            0x0C => (self.timer_flag as u16, empty),
            0x10 => (cycle as u16, empty),
            0x12 => (self.cycle_hi, empty),
            _ => (0, empty),
        }
    }

    /// The data a read drives: each half it covers, low first; one half
    /// alone on both.
    fn value(&self, cycle: i64, w: usize, halves: u8) -> u32 {
        let mut empty = self.last_empty;
        let mut v = [0u16; 2];
        for (h, x) in v.iter_mut().enumerate() {
            if halves >> h & 1 != 0 {
                let a = w + 2 * h;
                // the cycle counter's high half is what reading the low half latched
                let (r, e) = if a == 0x12 && halves == 3 {
                    ((cycle >> 16) as u16, empty)
                } else {
                    self.read16(cycle, a, empty)
                };
                *x = r;
                empty = e;
            }
        }
        match halves {
            1 => v[0] as u32 * 0x10001,
            2 => v[1] as u32 * 0x10001,
            _ => v[0] as u32 | (v[1] as u32) << 16,
        }
    }

    /// A read's side effects, at the clock edge that ends it.
    fn read_edge(&mut self, cycle: i64, w: usize, halves: u8) {
        for h in 0..2 {
            if halves >> h & 1 == 0 {
                continue;
            }
            match w + 2 * h {
                0x00 => {
                    if self.pending() {
                        self.input_pos += 1;
                        self.last_empty = false;
                    } else {
                        self.last_empty = true;
                    }
                }
                0x10 => self.cycle_hi = (cycle >> 16) as u16,
                _ => {}
            }
        }
    }

    fn write16(&mut self, a: usize, v: u16, lanes: u8) {
        match a {
            0x00 => {
                if lanes & 1 != 0 {
                    self.output.push(v as u8);
                }
            }
            0x08 => {
                self.timer_period = (self.timer_period & !0xFFFF) | v as i64;
                self.timer_count = 0;
                if self.timer_period == 0 {
                    self.timer_flag = 0;
                }
            }
            0x0A => {
                self.timer_period = (self.timer_period & 0xFFFF) | (v as i64) << 16;
                self.timer_count = 0;
                if self.timer_period == 0 {
                    self.timer_flag = 0;
                }
            }
            0x0C | 0x0E => self.timer_flag = 0,
            _ => {}
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if let Some(card) = self.card.as_mut() {
            // the timer's master-clock ticks, from the last CPU clock edge
            // in reset (where the CPU's first cycle starts, the control
            // store's word 0 in its register); its count and tick change at
            // CPU clock edges
            if pin == card.mclk {
                let v = cx.input(c, card.mclk);
                if v == 1 && card.prev_mclk == 0 && card.started {
                    card.ticks += 1;
                }
                card.prev_mclk = v;
                return;
            }
            if pin == self.clk && cx.input(c, self.clk) == 1 {
                if cx.input(c, card.rstn) == 0 {
                    card.reset();
                    card.started = true;
                } else {
                    card.clock();
                }
            }
        }
        if !cx.state.check_on {
            if let Some(card) = self.card.as_ref() {
                card.outputs(cx, c);
            }
            return; // power-up and reset: the bus isn't meaningful yet
        }
        let cycle = cx.state.cycle;
        let sel = cx.input(c, self.iosel) == 0;
        let coff = if sel { self.card_off(cx, c) } else { None };
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            if v == 1 && self.prev == 0 {
                if let Some(card) = self.card.as_mut() {
                    if cx.input(c, card.msgoe) == 0 {
                        card.msg_state = MSG_FREE;
                    }
                    if cx.input(c, card.nmiack) == 1 {
                        card.nmi_latch = 0;
                    }
                }
                if sel && cx.input(c, self.rd) == 0 {
                    if let Some(off) = coff {
                        self.card.as_mut().unwrap().read(off, true);
                    } else {
                        let (w, h) = (self.word(cx, c), self.halves(cx, c));
                        self.read_edge(cycle, w, h);
                    }
                }
                if let Some(card) = self.card.as_ref() {
                    card.outputs(cx, c);
                }
                if self.timer_period > 0 && cycle >= 0 {
                    self.timer_count += 1;
                    if self.timer_count >= self.timer_period {
                        self.timer_flag = 1;
                        self.timer_count = 0;
                    }
                }
                cx.drive(c, self.irq, self.timer_flag, true, 5000);
            }
            self.prev = v;
        }
        let wr = sel && cx.input(c, self.wr) == 0;
        if self.writing && !wr {
            let v: u32 = (0..32).map(|i| (cx.input(c, self.d[i]) as u32) << i).sum();
            if let Some(off) = self.wr_off {
                let card = self.card.as_mut().unwrap();
                card.write(off, v);
                card.outputs(cx, c);
            } else {
                let w = self.word(cx, c);
                let on: Vec<bool> = (0..4).map(|i| cx.input(c, self.be[i]) == 0).collect();
                for h in 0..2 {
                    let lanes = b2u(on[2 * h]) | b2u(on[2 * h + 1]) << 1;
                    if lanes != 0 {
                        self.write16(w + 2 * h, (v >> (16 * h)) as u16, lanes);
                    }
                }
            }
            cx.drive(c, self.irq, self.timer_flag, true, 5000);
        }
        if wr {
            self.wr_off = coff;
        }
        self.writing = wr;
        if let Some(card) = self.card.as_mut() {
            // the message register onto the CPU's B bus
            if cx.input(c, card.msgoe) == 0 {
                let w = (card.msg & 0xFFFFFF) << 8 | card.msg >> 24;
                for i in 0..32 {
                    cx.drive(c, card.b[i], ((w >> i) & 1) as u8, true, 8000);
                }
                card.b_driving = true;
            } else if card.b_driving {
                for i in 0..32 {
                    let v = cx.driven(c, card.b[i]);
                    cx.drive(c, card.b[i], v, false, 8000);
                }
                card.b_driving = false;
            }
        }
        if sel && cx.input(c, self.rd) == 0 {
            let (v, acc) = match coff {
                Some(off) => (self.card.as_mut().unwrap().read(off, false), CARD_READ),
                None => (
                    self.value(cycle, self.word(cx, c), self.halves(cx, c)),
                    self.d_acc,
                ),
            };
            for i in 0..32 {
                cx.drive(c, self.d[i], ((v >> i) & 1) as u8, true, acc);
            }
            self.driving = true;
        } else if self.driving {
            for i in 0..32 {
                let v = cx.driven(c, self.d[i]);
                cx.drive(c, self.d[i], v, false, 10000);
            }
            self.driving = false;
        }
    }
}

// ---------------------------------------------------------------- 245 transceiver

/// The 74xx245 octal transceiver: DIR = 1 drives B from A, DIR = 0 drives
/// A from B, while OE (active low) is low.
pub struct Xcvr245 {
    dir: usize,
    oe: usize,
    a: [usize; 8],
    b: [usize; 8],
    a_idx: Vec<Option<usize>>,
    b_idx: Vec<Option<usize>>,
    /// The direction being driven: Some(true) A to B, Some(false) B to A.
    mode: Option<bool>,
    en_at: Time,
    d_ab: Time,
    d_ba: Time,
    /// Turning on the A side and the B side; a side on a bus line takes
    /// longer, since the line has to settle.
    d_en_a: Time,
    d_en_b: Time,
    d_dis: Time,
}

impl Xcvr245 {
    fn new(s: &Spec) -> Result<Xcvr245, Error> {
        let a = s.pins(|i| format!("A{}", i + 1))?;
        let b = s.pins(|i| format!("B{}", i + 1))?;
        Ok(Xcvr245 {
            dir: s.pin("DIR")?,
            oe: s.pin("OE")?,
            a_idx: s.index(&a),
            b_idx: s.index(&b),
            a,
            b,
            mode: None,
            en_at: 0,
            d_ab: s.d("A->B")?,
            d_ba: s.d("B->A")?,
            d_en_a: s.d_or("OE->A en", s.d("OE->Y en")?),
            d_en_b: s.d_or("OE->B en", s.d("OE->Y en")?),
            d_dis: s.d("OE->Y dis")?,
        })
    }

    fn mode(&self, cx: &Ctx, c: &ChipInfo) -> Option<bool> {
        (cx.input(c, self.oe) == 0).then(|| cx.input(c, self.dir) == 1)
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.mode = self.mode(cx, c);
        self.drive_all(cx, c, 0, 0);
    }

    /// The time to turn on the side the mode drives.
    fn d_on(&self) -> Time {
        match self.mode {
            Some(true) => self.d_en_b,
            _ => self.d_en_a,
        }
    }

    /// Drive both sides as the mode says: the driven side follows the
    /// other after `d_on`, the side not driven lets go after `d_off`.
    fn drive_all(&self, cx: &mut Ctx, c: &ChipInfo, d_on: Time, d_off: Time) {
        for i in 0..8 {
            let (va, vb) = (cx.input(c, self.a[i]), cx.input(c, self.b[i]));
            match self.mode {
                Some(true) => {
                    cx.drive(c, self.b[i], va, true, d_on);
                    cx.drive(c, self.a[i], cx.driven(c, self.a[i]), false, d_off);
                }
                Some(false) => {
                    cx.drive(c, self.a[i], vb, true, d_on);
                    cx.drive(c, self.b[i], cx.driven(c, self.b[i]), false, d_off);
                }
                None => {
                    cx.drive(c, self.a[i], cx.driven(c, self.a[i]), false, d_off);
                    cx.drive(c, self.b[i], cx.driven(c, self.b[i]), false, d_off);
                }
            }
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.oe || pin == self.dir {
            let m = self.mode(cx, c);
            if m != self.mode {
                self.mode = m;
                let d_on = self.d_on();
                self.en_at = cx.now() + d_on;
                self.drive_all(cx, c, d_on, self.d_dis);
            }
            return;
        }
        match self.mode {
            Some(true) => {
                if let Some(i) = self.a_idx[pin] {
                    let t = (cx.now() + self.d_ab).max(self.en_at);
                    cx.drive_at(c, self.b[i], cx.input(c, pin), true, t);
                }
            }
            Some(false) => {
                if let Some(i) = self.b_idx[pin] {
                    let t = (cx.now() + self.d_ba).max(self.en_at);
                    cx.drive_at(c, self.a[i], cx.input(c, pin), true, t);
                }
            }
            None => {}
        }
    }
}

// ---------------------------------------------------------------- 125 quad three-state buffer

/// Three-state buffers with an active-low enable each: sections nOE, nA,
/// nY (the 74xx125).
pub struct TriBuf {
    oe: Vec<usize>,
    a: Vec<usize>,
    y: Vec<usize>,
    sec_of: Vec<Option<usize>>,
    enabled: Vec<bool>,
    en_at: Vec<Time>,
    d_a: Time,
    d_en: Time,
    d_dis: Time,
}

impl TriBuf {
    fn new(s: &Spec) -> Result<TriBuf, Error> {
        let (mut oe, mut a, mut y) = (Vec::new(), Vec::new(), Vec::new());
        let mut sec_of = vec![None; s.info.pin_names.len()];
        while s.has(&format!("{}A", a.len() + 1)) {
            let n = a.len() + 1;
            oe.push(s.pin(&format!("{n}OE"))?);
            a.push(s.pin(&format!("{n}A"))?);
            y.push(s.pin(&format!("{n}Y"))?);
            sec_of[oe[n - 1]] = Some(n - 1);
            sec_of[a[n - 1]] = Some(n - 1);
        }
        let n = a.len();
        Ok(TriBuf {
            oe,
            a,
            y,
            sec_of,
            enabled: vec![false; n],
            en_at: vec![0; n],
            d_a: s.d("A->Y")?,
            d_en: s.d("OE->Y en")?,
            d_dis: s.d("OE->Y dis")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for i in 0..self.a.len() {
            self.enabled[i] = cx.input(c, self.oe[i]) == 0;
            cx.drive(c, self.y[i], cx.input(c, self.a[i]), self.enabled[i], 0);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        let Some(i) = self.sec_of[pin] else { return };
        if pin == self.oe[i] {
            let en = cx.input(c, pin) == 0;
            if en != self.enabled[i] {
                self.enabled[i] = en;
                let d = if en { self.d_en } else { self.d_dis };
                self.en_at[i] = cx.now() + d;
                cx.drive(c, self.y[i], cx.input(c, self.a[i]), en, d);
            }
        } else if self.enabled[i] {
            let t = (cx.now() + self.d_a).max(self.en_at[i]);
            cx.drive_at(c, self.y[i], cx.input(c, pin), true, t);
        }
    }
}

// ---------------------------------------------------------------- 148 priority encoder

/// The 74xx148 8-to-3 priority encoder, all active low: I7 has priority.
/// With EI high everything is high; with no input low, A = 111, GS high
/// and EO low; otherwise A is the complement of the highest low input's
/// number, GS low and EO high.
pub struct Enc148 {
    i: [usize; 8],
    ei: usize,
    a: [usize; 3],
    gs: usize,
    eo: usize,
    d_i: Time,
    d_ei: Time,
}

impl Enc148 {
    fn new(s: &Spec) -> Result<Enc148, Error> {
        Ok(Enc148 {
            i: s.pins(|i| format!("I{i}"))?,
            ei: s.pin("EI")?,
            a: s.pins(|i| format!("A{i}"))?,
            gs: s.pin("GS")?,
            eo: s.pin("EO")?,
            d_i: s.d("I->Y")?,
            d_ei: s.d("EI->Y")?,
        })
    }

    fn eval_all(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let (a, gs, eo) = if cx.input(c, self.ei) == 1 {
            (7, 1, 1)
        } else {
            match (0..8).rev().find(|&n| cx.input(c, self.i[n]) == 0) {
                Some(n) => (7 - n, 0, 1),
                None => (7, 1, 0),
            }
        };
        for (k, &p) in self.a.iter().enumerate() {
            cx.drive(c, p, ((a >> k) & 1) as u8, true, d);
        }
        cx.drive(c, self.gs, gs, true, d);
        cx.drive(c, self.eo, eo, true, d);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        let d = if pin == self.ei { self.d_ei } else { self.d_i };
        self.eval_all(cx, c, d);
    }
}

// ---------------------------------------------------------------- clock drivers

/// One input buffered to many outputs (a clock driver such as the
/// CDC341): A to Y1..Yn.
pub struct FanBuf {
    a: usize,
    y: Vec<usize>,
    d: Time,
}

impl FanBuf {
    fn new(s: &Spec) -> Result<FanBuf, Error> {
        let mut y = Vec::new();
        while s.has(&format!("Y{}", y.len() + 1)) {
            y.push(s.pin(&format!("Y{}", y.len() + 1))?);
        }
        Ok(FanBuf {
            a: s.pin("A")?,
            y,
            d: s.d("A->Y")?,
        })
    }

    fn eval_all(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let v = cx.input(c, self.a);
        for &p in &self.y {
            cx.drive(c, p, v, true, d);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, _pin: usize) {
        self.eval_all(cx, c, self.d);
    }
}

// ---------------------------------------------------------------- oscillator and power-on reset

/// A crystal oscillator. Its output pin is also its own input, so that
/// each edge schedules the next: high for half the period (rounded
/// down), then low; the first rising edge comes at `phase_ps`.
pub struct Osc {
    out: usize,
    high: Time,
    low: Time,
    phase: Time,
}

impl Osc {
    fn new(s: &Spec) -> Result<Osc, Error> {
        let period = s.param("period_ps")?;
        if period < 2 {
            return Err(Error(format!(
                "{}: period_ps must be at least 2",
                s.info.reference
            )));
        }
        Ok(Osc {
            out: s.pin("OUT")?,
            high: period / 2,
            low: period - period / 2,
            phase: s.param_or("phase_ps", period / 2),
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        cx.drive(c, self.out, 0, true, 0);
        cx.drive_at(c, self.out, 1, true, self.phase.max(1));
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.out {
            let v = cx.input(c, self.out);
            let d = if v == 1 { self.high } else { self.low };
            cx.drive(c, self.out, v ^ 1, true, d);
        }
    }
}

/// The power-on reset: an open-collector output that holds RST low from
/// power-up until `release_ps`.
pub struct Por {
    rst: usize,
    release: Time,
}

impl Por {
    fn new(s: &Spec) -> Result<Por, Error> {
        Ok(Por {
            rst: s.pin("RST")?,
            release: s.param("release_ps")?,
        })
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        cx.drive(c, self.rst, 0, true, 0);
        cx.drive_at(c, self.rst, 1, false, self.release);
    }
}

// ---------------------------------------------------------------- 299 shift/storage register

/// The 74HCT299: S1 S0 = 00 hold, 01 shift toward Q7 (DS0 into Q0), 10
/// shift toward Q0 (DS7 into Q7), 11 parallel load from the I/O pins. The
/// I/O pins drive only when OE1 = OE2 = 0 and not S0 = S1 = 1. Q0S and Q7S
/// (Q0', Q7') are always driven.
pub struct Sr299 {
    s0: usize,
    s1: usize,
    oe1: usize,
    oe2: usize,
    mr: usize,
    cp: usize,
    ds0: usize,
    ds7: usize,
    q0s: usize,
    q7s: usize,
    io: [usize; 8],
    is_io: Vec<bool>,
    state: [u8; 8],
    prev: u8,
    last_edge: Option<Time>,
    /// the mode (S1 S0) at the last edge: which data inputs it took, and so
    /// which ones have a hold time to keep
    last_mode: u8,
    driving: bool,
    d_clk: Time,
    d_qs: Time,
    d_clr: Time,
    d_en: Time,
    d_dis: Time,
    su_s: Time,
    h_s: Time,
    su_ds: Time,
    h_ds: Time,
    su_io: Time,
    h_io: Time,
}

impl Sr299 {
    fn new(s: &Spec, rng: &mut Rng) -> Result<Sr299, Error> {
        let io = s.pins(|i| format!("IO{i}"))?;
        let mut is_io = vec![false; s.info.pin_names.len()];
        for &p in &io {
            is_io[p] = true;
        }
        let mut state = [0; 8];
        for x in &mut state {
            *x = rng.bit();
        }
        Ok(Sr299 {
            s0: s.pin("S0")?,
            s1: s.pin("S1")?,
            oe1: s.pin("OE1")?,
            oe2: s.pin("OE2")?,
            mr: s.pin("MR")?,
            cp: s.pin("CP")?,
            ds0: s.pin("DS0")?,
            ds7: s.pin("DS7")?,
            q0s: s.pin("Q0S")?,
            q7s: s.pin("Q7S")?,
            io,
            is_io,
            state,
            prev: 0,
            last_edge: None,
            last_mode: 0,
            driving: false,
            d_clk: s.d("CLK->Q")?,
            d_qs: s.d("CLK->QS")?,
            d_clr: s.d("CLR->Q")?,
            d_en: s.d("OE->Y en")?,
            d_dis: s.d("OE->Y dis")?,
            su_s: s.d("setup S")?,
            h_s: s.d("hold S")?,
            su_ds: s.d("setup DS")?,
            h_ds: s.d("hold DS")?,
            su_io: s.d("setup IO")?,
            h_io: s.d("hold IO")?,
        })
    }

    fn enabled(&self, cx: &Ctx, c: &ChipInfo) -> bool {
        cx.input(c, self.oe1) == 0
            && cx.input(c, self.oe2) == 0
            && !(cx.input(c, self.s0) == 1 && cx.input(c, self.s1) == 1)
    }

    fn outputs(&mut self, cx: &mut Ctx, c: &ChipInfo, dq: Time, dqs: Time) {
        let en = self.enabled(cx, c);
        let mut d = dq;
        if en != self.driving {
            d = if en { self.d_en } else { self.d_dis }.max(dq);
        }
        for i in 0..8 {
            cx.drive(c, self.io[i], self.state[i], en, d);
        }
        self.driving = en;
        cx.drive(c, self.q0s, self.state[0], true, dqs);
        cx.drive(c, self.q7s, self.state[7], true, dqs);
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.cp {
            let v = cx.input(c, self.cp);
            if v == 1 && self.prev == 0 && cx.input(c, self.mr) == 1 {
                cx.check_setup(c, self.s0, self.su_s, "S0");
                cx.check_setup(c, self.s1, self.su_s, "S1");
                let mode = cx.input(c, self.s0) | cx.input(c, self.s1) << 1;
                let mut nx = [0u8; 8];
                match mode {
                    0 => nx = self.state,
                    1 => {
                        cx.check_setup(c, self.ds0, self.su_ds, "DS0");
                        nx[0] = cx.input(c, self.ds0);
                        nx[1..].copy_from_slice(&self.state[..7]);
                    }
                    2 => {
                        cx.check_setup(c, self.ds7, self.su_ds, "DS7");
                        nx[7] = cx.input(c, self.ds7);
                        nx[..7].copy_from_slice(&self.state[1..]);
                    }
                    _ => {
                        for (i, x) in nx.iter_mut().enumerate() {
                            cx.check_setup(c, self.io[i], self.su_io, "IO");
                            *x = cx.input(c, self.io[i]);
                        }
                    }
                }
                self.state = nx;
                self.last_edge = Some(cx.now());
                self.last_mode = mode;
                self.outputs(cx, c, self.d_clk, self.d_qs);
            }
            self.prev = v;
        } else if pin == self.mr {
            if cx.input(c, self.mr) == 0 {
                self.state = [0; 8];
                self.outputs(cx, c, self.d_clr, self.d_clr);
            }
        } else if pin == self.s0 || pin == self.s1 {
            cx.check_hold(c, pin, self.last_edge, self.h_s, "S");
            self.outputs(cx, c, self.d_en, self.d_qs);
        } else if pin == self.oe1 || pin == self.oe2 {
            self.outputs(cx, c, self.d_en, self.d_qs);
        } else if (pin == self.ds0 && self.last_mode == 1)
            || (pin == self.ds7 && self.last_mode == 2)
        {
            // a serial input has a hold time only after an edge that shifted it in
            cx.check_hold(c, pin, self.last_edge, self.h_ds, "DS");
        } else if self.is_io[pin] && !self.driving && self.last_mode == 3 {
            cx.check_hold(c, pin, self.last_edge, self.h_io, "IO");
        }
    }
}

/// A test fixture that plays a script against a clock: a test's bus
/// master. At every rising edge of CLK it records its inputs I0.. (as they
/// were just before the edge); then, if the current step's conditions held
/// in what it recorded, it moves to the next step and drives its outputs
/// O0.. with it after `delay_ps`. The script is the preload, a step being
/// `outs` bytes (0, 1, or 2 to let go of the pin) and then `conds` bytes,
/// each 0 for none or 1 + 2k + v for "input k was v"; after its last step
/// the outputs stay. The record is the dump: `ins` bytes per edge.
pub struct Vector {
    clk: usize,
    outs: Vec<usize>,
    ins: Vec<usize>,
    conds: usize,
    script: Vec<u8>,
    step: usize,
    delay: Time,
    prev: u8,
    pub log: Vec<u8>,
}

impl Vector {
    fn new(s: &Spec, preload: Option<&[u8]>) -> Result<Vector, Error> {
        let n_out = s.param("outs")? as usize;
        let n_in = s.param("ins")? as usize;
        let conds = s.param_or("conds", 0) as usize;
        let outs = (0..n_out)
            .map(|i| s.pin(&format!("O{i}")))
            .collect::<Result<Vec<_>, _>>()?;
        let ins = (0..n_in)
            .map(|i| s.pin(&format!("I{i}")))
            .collect::<Result<Vec<_>, _>>()?;
        let script = preload.unwrap_or(&[]).to_vec();
        let size = n_out + conds;
        if size == 0 || !script.len().is_multiple_of(size) {
            return Err(Error(format!(
                "{}: the script isn't a whole number of {size}-byte steps",
                s.info.reference
            )));
        }
        if let Some(&b) = script
            .chunks(size)
            .flat_map(|st| &st[n_out..])
            .find(|&&b| b != 0 && (b as usize - 1) / 2 >= n_in)
        {
            return Err(Error(format!(
                "{}: condition {b} names an input it doesn't have",
                s.info.reference
            )));
        }
        Ok(Vector {
            clk: s.pin("CLK")?,
            outs,
            ins,
            conds,
            script,
            step: 0,
            delay: s.param_or("delay_ps", 1).max(1),
            prev: 0,
            log: Vec::new(),
        })
    }

    fn size(&self) -> usize {
        self.outs.len() + self.conds
    }

    fn steps(&self) -> usize {
        self.script.len() / self.size()
    }

    fn drive(&self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        let at = self.step * self.size();
        for (i, &p) in self.outs.iter().enumerate() {
            let v = self.script[at + i];
            cx.drive(c, p, (v == 1) as u8, v < 2, d);
        }
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        if self.steps() > 0 {
            self.drive(cx, c, 0);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin != self.clk {
            return;
        }
        let v = cx.input(c, self.clk);
        if v == 1 && self.prev == 0 {
            let seen: Vec<u8> = self.ins.iter().map(|&p| cx.input(c, p)).collect();
            let at = self.step * self.size() + self.outs.len();
            let met = self.step >= self.steps()
                || self.script[at..at + self.conds]
                    .iter()
                    .all(|&b| b == 0 || seen[(b as usize - 1) / 2] == (b - 1) % 2);
            self.log.extend_from_slice(&seen);
            if met && self.step + 1 < self.steps() {
                self.step += 1;
                self.drive(cx, c, self.delay);
            }
        }
        self.prev = v;
    }
}

// ---------------------------------------------------------------- 22V10

/// A 22V10 (GAL) programmed with sums of products (the netlist's
/// `program`, infra/hw/gal.py): each output the sum of its terms, or the
/// complement; a registered output loads at CLK's rising edge, the others
/// follow their inputs. A term reads an output's pin, which feeds back.
pub struct Gal {
    clk: usize,
    prev: u8,
    outs: Vec<GalOut>,
    /// The combinatorial outputs each pin reaches.
    fanout: Vec<Vec<usize>>,
    tpd: Time,
    tco: Time,
    setup: Time,
}

struct GalOut {
    pin: usize,
    reg: bool,
    inv: bool,
    /// Each term: (pin, the value it must have).
    terms: Vec<Vec<(usize, u8)>>,
    inputs: Vec<usize>,
    state: u8,
}

impl Gal {
    fn new(s: &Spec) -> Result<Gal, Error> {
        let bad = || Error(format!("{}: a malformed 22V10 program", s.info.reference));
        let mut words = s
            .program
            .iter()
            .map(|&w| usize::try_from(w).map_err(|_| bad()));
        let mut next = || words.next().unwrap_or_else(|| Err(bad()));
        let n = s.info.pin_names.len();
        let mut outs = Vec::new();
        for _ in 0..next()? {
            let pin = next()?;
            let flags = next()?;
            let mut terms = Vec::new();
            for _ in 0..next()? {
                let mut t = Vec::new();
                for _ in 0..next()? {
                    let l = next()?;
                    if l / 2 >= n {
                        return Err(bad());
                    }
                    t.push((l / 2, (1 - l % 2) as u8));
                }
                terms.push(t);
            }
            let mut inputs: Vec<usize> = terms.iter().flatten().map(|&(p, _)| p).collect();
            inputs.sort_unstable();
            inputs.dedup();
            if pin >= n {
                return Err(bad());
            }
            outs.push(GalOut {
                pin,
                reg: flags & 1 != 0,
                inv: flags & 2 != 0,
                terms,
                inputs,
                state: 0,
            });
        }
        let mut fanout = vec![Vec::new(); n];
        for (i, o) in outs.iter().enumerate() {
            if !o.reg {
                for &p in &o.inputs {
                    fanout[p].push(i);
                }
            }
        }
        Ok(Gal {
            clk: s.pin("CLK")?,
            prev: 0,
            outs,
            fanout,
            tpd: s.d("tPD")?,
            tco: s.d("CLK->Q")?,
            setup: s.d("setup")?,
        })
    }

    fn sum(cx: &Ctx, c: &ChipInfo, o: &GalOut) -> u8 {
        let on = o
            .terms
            .iter()
            .any(|t| t.iter().all(|&(p, v)| cx.input(c, p) == v));
        u8::from(on) ^ u8::from(o.inv)
    }

    fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for o in &self.outs {
            let v = if o.reg { o.state } else { Self::sum(cx, c, o) };
            cx.drive(c, o.pin, v, true, 0);
        }
    }

    fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.clk {
            let v = cx.input(c, self.clk);
            if v == 1 && self.prev == 0 {
                for i in 0..self.outs.len() {
                    if !self.outs[i].reg {
                        continue;
                    }
                    for k in 0..self.outs[i].inputs.len() {
                        cx.check_setup(c, self.outs[i].inputs[k], self.setup, "input");
                    }
                    let state = Self::sum(cx, c, &self.outs[i]);
                    self.outs[i].state = state;
                    cx.drive(c, self.outs[i].pin, state, true, self.tco);
                }
            }
            self.prev = v;
        }
        for k in 0..self.fanout[pin].len() {
            let o = &self.outs[self.fanout[pin][k]];
            let v = Self::sum(cx, c, o);
            cx.drive(c, o.pin, v, true, self.tpd);
        }
    }
}
