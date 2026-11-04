//! A netlist compiled for analysis: every output with what it reads, the
//! drivers of every net, the checks, and the order to evaluate outputs in.

use std::collections::HashMap;

use crate::Error;
use crate::input::{
    ArcIn, CheckKindIn, ChipIn, DataIn, DelaySpec, EST_TYP, EST_VALUE, Netlist, Sop, StableIn,
};
use crate::logic::support;

/// A delay: its minimum (None: a fraction of typical), typical, maximum,
/// and whether the data marks its value or its typical as estimated.
#[derive(Clone, Copy, Debug)]
pub struct Delay {
    pub min: Option<i64>,
    pub typ: i64,
    pub max: i64,
    pub est: bool,
    pub est_typ: bool,
}

impl Delay {
    /// Lengthened (or shortened) by a load's change: [to min, to max].
    fn loaded(self, l: [i64; 2]) -> Delay {
        Delay {
            min: self.min.map(|m| (m + l[0]).max(0)),
            typ: self.typ + l[1],
            max: self.max + l[1],
            ..self
        }
    }

    pub fn zero() -> Delay {
        Delay {
            min: Some(0),
            typ: 0,
            max: 0,
            est: false,
            est_typ: false,
        }
    }

    pub fn of(d: &DelaySpec, est: u8) -> Delay {
        let max = d[2].or(d[1]).unwrap_or(0);
        Delay {
            min: d[0],
            typ: d[1].unwrap_or(max),
            max,
            est: est & EST_VALUE != 0,
            est_typ: est & EST_TYP != 0,
        }
    }

    /// Whether its minimum rests on an estimate.
    pub fn lo_estimated(&self) -> bool {
        self.est || self.min.is_none() && self.est_typ
    }

    /// The shortest it can be, with `fraction` of typical where the data
    /// gives no minimum.
    pub fn lo(&self, fraction: f64) -> i64 {
        self.min
            .unwrap_or_else(|| (self.typ as f64 * fraction).round() as i64)
    }

    pub fn hi(&self) -> i64 {
        self.max
    }

    /// Whether the minimum comes from the fraction.
    pub fn assumed(&self) -> bool {
        self.min.is_none()
    }
}

/// An arc: from some of the chip's pins to an output, under a condition.
#[derive(Clone, Debug)]
pub struct Arc {
    pub from: Vec<u32>,
    pub d: Delay,
    /// Index into Design::labels: "U_X: A->Y".
    pub label: u32,
    pub when: Option<Sop>,
}

#[derive(Clone, Debug)]
pub struct Enable {
    pub f: Sop,
    pub on: Vec<Arc>,
    pub off: Vec<Arc>,
}

#[derive(Clone, Debug)]
pub struct Force {
    pub f: Sop,
    pub arcs: Vec<Arc>,
}

#[derive(Clone, Debug)]
pub enum Kind {
    /// A combinatorial output; func None: opaque.
    Comb { func: Option<Sop>, arcs: Vec<Arc> },
    /// A register: loads next ^ inv at its clock's edge.
    Reg {
        clock: u32,
        rise: bool,
        next: Sop,
        d: Delay,
        label: u32,
        clear: Option<Force>,
        clear_value: u8,
        preset: Option<Force>,
        feedback: Option<Delay>,
        /// Index into Design::labels for the feedback's arc.
        fb_label: u32,
    },
    /// An oscillator: its period, first rising edge, the range of its high
    /// time (per mille of the period) and its jitter (each edge within
    /// that of its time).
    Osc {
        period: i64,
        phase: i64,
        duty: (i64, i64),
        jitter: i64,
    },
    /// An output on a clock of its chip's own.
    Async,
}

#[derive(Clone, Debug)]
pub struct Output {
    pub chip: u32,
    pub pin: u32,
    pub net: Option<u32>,
    pub inv: bool,
    pub kind: Kind,
    pub enable: Option<Enable>,
    /// The wiring's delay after the pin.
    pub wire: i64,
}

impl Output {
    pub fn is_reg(&self) -> bool {
        matches!(self.kind, Kind::Reg { .. })
    }
}

/// Where a chip's pin reads from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    Net(u32),
    /// A register of the chip's own, fed back.
    State(u32),
    Open,
}

#[derive(Clone, Debug)]
pub struct Chip {
    pub reference: String,
    pub part: String,
    pub model: String,
    pub pins: Vec<String>,
    pub nets: Vec<Option<u32>>,
    pub outs: Vec<u32>,
    /// A register's output by its pin.
    pub reg_of_pin: Vec<Option<u32>>,
    pub nocheck: bool,
    pub described: bool,
    pub unchecked: Vec<String>,
    pub sensitive: Vec<u32>,
    pub family: String,
    /// Its pins that drive.
    pub out_pins: Vec<u32>,
}

impl Chip {
    pub fn source(&self, pin: u32) -> Source {
        if let Some(&Some(r)) = self.reg_of_pin.get(pin as usize) {
            return Source::State(r);
        }
        match self.nets.get(pin as usize).copied().flatten() {
            Some(n) => Source::Net(n),
            None => Source::Open,
        }
    }
}

#[derive(Clone, Debug)]
pub enum CheckKind {
    Setup {
        pins: Vec<u32>,
        clock: u32,
        rise: bool,
        setup: i64,
        hold: i64,
    },
    Width {
        pin: u32,
        level: u8,
        min: i64,
    },
    Period {
        pin: u32,
        min: i64,
    },
    Recovery {
        clock: u32,
        rise: bool,
        recovery: Option<i64>,
        removal: Option<i64>,
        width: Option<i64>,
    },
    Strobe {
        active: Sop,
        stable: Vec<StableIn>,
        data: Vec<DataIn>,
        width: Option<i64>,
        eq: String,
    },
}

#[derive(Clone, Debug)]
pub struct Check {
    pub chip: u32,
    pub kind: CheckKind,
    pub names: Vec<String>,
    /// Its limits the data marks as estimated.
    pub estimated: Vec<String>,
}

pub struct Design {
    pub nets: Vec<String>,
    pub net_index: HashMap<String, u32>,
    pub chips: Vec<Chip>,
    pub outs: Vec<Output>,
    pub checks: Vec<Check>,
    /// The outputs that drive each net.
    pub drivers: Vec<Vec<u32>>,
    pub pulled: Vec<bool>,
    /// GND and VCC.
    pub rail: Vec<Option<u8>>,
    /// The outputs in groups that depend on each other (a loop), each group
    /// after the ones it reads; whether each is a loop (more than one
    /// output, or one that reads its own net).
    pub order: Vec<Vec<u32>>,
    pub looped: Vec<bool>,
    /// The arcs' names, for paths: "U_X: A->Y"; 0 is a wire's, TAIL a tail
    /// of the cycle before's. Each one's delay, where it has one.
    pub labels: Vec<String>,
    pub label_delays: Vec<Option<Delay>>,
    /// The pins each output reads (Design::reads), and those of its enable.
    pub reads_of: Vec<Vec<u32>>,
    pub en_reads: Vec<Vec<u32>>,
    /// The outputs that read each net, and each register's state (the
    /// register's own output among them); each output's group in order.
    pub net_readers: Vec<Vec<u32>>,
    pub state_readers: Vec<Vec<u32>>,
    pub group_of: Vec<u32>,
}

/// Design::labels's index for a tail of the cycle before.
pub const TAIL: u32 = 1;

impl Design {
    pub fn new(n: &Netlist) -> Result<Design, Error> {
        let nets = n.nets.clone();
        let net_index: HashMap<String, u32> = nets
            .iter()
            .enumerate()
            .map(|(i, s)| (s.clone(), i as u32))
            .collect();
        let mut d = Design {
            rail: nets
                .iter()
                .map(|s| match s.as_str() {
                    "GND" => Some(0),
                    "VCC" => Some(1),
                    _ => None,
                })
                .collect(),
            pulled: vec![false; nets.len()],
            drivers: vec![Vec::new(); nets.len()],
            nets,
            net_index,
            chips: Vec::new(),
            outs: Vec::new(),
            checks: Vec::new(),
            order: Vec::new(),
            looped: Vec::new(),
            labels: vec!["wire".into(), "the cycle before (a tail)".into()],
            label_delays: vec![None, None],
            reads_of: Vec::new(),
            en_reads: Vec::new(),
            net_readers: Vec::new(),
            state_readers: Vec::new(),
            group_of: Vec::new(),
        };
        for &p in &n.pulled {
            if let Some(x) = d.pulled.get_mut(p as usize) {
                *x = true;
            }
        }
        for (ci, c) in n.chips.iter().enumerate() {
            d.add_chip(ci as u32, c)?;
        }
        for (ci, c) in n.chips.iter().enumerate() {
            for (p, w) in c.in_delays.iter().enumerate() {
                if w[1] > 0 || w[0] > 0 {
                    d.add_wire(ci, p as u32, *w);
                }
            }
        }
        for (oi, o) in d.outs.iter().enumerate() {
            if let Some(net) = o.net {
                d.drivers[net as usize].push(oi as u32);
            }
        }
        d.reads_of = d.outs.iter().map(|o| d.reads(o)).collect();
        d.en_reads = d
            .outs
            .iter()
            .map(|o| o.enable.as_ref().map(|e| support(&e.f)).unwrap_or_default())
            .collect();
        d.net_readers = vec![Vec::new(); d.nets.len()];
        d.state_readers = (0..d.outs.len() as u32).map(|o| vec![o]).collect();
        for (oi, o) in d.outs.iter().enumerate() {
            let chip = &d.chips[o.chip as usize];
            for &p in &d.reads_of[oi] {
                let list = match chip.source(p) {
                    Source::Net(n) => &mut d.net_readers[n as usize],
                    Source::State(r) => &mut d.state_readers[r as usize],
                    Source::Open => continue,
                };
                if list.last() != Some(&(oi as u32)) {
                    list.push(oi as u32);
                }
            }
        }
        d.order = d.groups();
        d.group_of = vec![0; d.outs.len()];
        for (gi, g) in d.order.iter().enumerate() {
            for &o in g {
                d.group_of[o as usize] = gi as u32;
            }
        }
        d.looped = d
            .order
            .iter()
            .map(|g| g.len() > 1 || d.deps(g[0]).contains(&g[0]))
            .collect();
        Ok(d)
    }

    /// A receiving pin's wire: a stage from its net to a net of its own,
    /// [min, max] long. A pin its chip drives keeps its net.
    fn add_wire(&mut self, ci: usize, p: u32, w: [i64; 2]) {
        let chip = &self.chips[ci];
        let Some(Some(net)) = chip.nets.get(p as usize).copied() else {
            return;
        };
        if chip.outs.iter().any(|&o| self.outs[o as usize].pin == p) {
            return;
        }
        let name = format!("{}.{}", chip.reference, chip.pins[p as usize]);
        let new = self.nets.len() as u32;
        self.nets.push(format!("{name}~"));
        self.net_index.insert(format!("{name}~"), new);
        self.rail.push(None);
        self.pulled.push(false);
        self.drivers.push(Vec::new());
        let dl = Delay {
            min: Some(w[0]),
            typ: w[1],
            max: w[1],
            est: false,
            est_typ: false,
        };
        let label = self.label(&name, "wire", Some(dl));
        let wc = self.chips.len() as u32;
        self.outs.push(Output {
            chip: wc,
            pin: 1,
            net: Some(new),
            inv: false,
            kind: Kind::Comb {
                func: Some(vec![vec![(0, 1)]]),
                arcs: vec![Arc {
                    from: vec![0],
                    d: dl,
                    label,
                    when: None,
                }],
            },
            enable: None,
            wire: 0,
        });
        self.chips.push(Chip {
            reference: format!("~{name}"),
            part: "wire".into(),
            model: "wire".into(),
            pins: vec!["IN".into(), "OUT".into()],
            nets: vec![Some(net), Some(new)],
            outs: vec![(self.outs.len() - 1) as u32],
            reg_of_pin: vec![None, None],
            nocheck: false,
            described: true,
            unchecked: Vec::new(),
            sensitive: Vec::new(),
            family: "wire".into(),
            out_pins: vec![1],
        });
        self.chips[ci].nets[p as usize] = Some(new);
    }

    pub fn label(&mut self, chip: &str, name: &str, d: Option<Delay>) -> u32 {
        self.labels.push(format!("{chip}: {name}"));
        self.label_delays.push(d);
        (self.labels.len() - 1) as u32
    }

    fn arcs(&mut self, chip: &str, a: &[ArcIn]) -> Vec<Arc> {
        a.iter()
            .map(|x| {
                let d = Delay::of(&x.d, x.est);
                Arc {
                    from: x.from.clone(),
                    d,
                    label: self.label(chip, &x.name, Some(d)),
                    when: x.when.clone(),
                }
            })
            .collect()
    }

    fn add_chip(&mut self, ci: u32, c: &ChipIn) -> Result<(), Error> {
        let nets: Vec<Option<u32>> = c
            .nets
            .iter()
            .map(|&x| if x < 0 { None } else { Some(x as u32) })
            .collect();
        let wire = |pin: u32| c.pin_delays.get(pin as usize).copied().unwrap_or(0);
        let mut chip = Chip {
            reference: c.reference.clone(),
            part: c.part.clone(),
            model: c.model.clone(),
            pins: c.pins.clone(),
            nets: nets.clone(),
            outs: Vec::new(),
            reg_of_pin: vec![None; c.pins.len()],
            nocheck: c.nocheck,
            described: c.desc.is_some(),
            unchecked: Vec::new(),
            sensitive: Vec::new(),
            family: c.family.clone(),
            out_pins: c.outputs.clone(),
        };
        let r = c.reference.clone();
        let add = |d: &mut Design, chip: &mut Chip, o: Output| {
            chip.outs.push(d.outs.len() as u32);
            if o.is_reg()
                && let Some(x) = chip.reg_of_pin.get_mut(o.pin as usize)
            {
                *x = Some(d.outs.len() as u32);
            }
            d.outs.push(o);
        };
        if c.model == "osc" {
            let pin = c.pins.iter().position(|p| p == "OUT").unwrap_or(0) as u32;
            let period = *c
                .params
                .get("period_ps")
                .ok_or_else(|| Error(format!("{r}: an oscillator needs period_ps")))?;
            let o = Output {
                chip: ci,
                pin,
                net: nets[pin as usize],
                inv: false,
                kind: Kind::Osc {
                    period,
                    phase: c.params.get("phase_ps").copied().unwrap_or(0),
                    duty: (
                        c.params.get("duty_min_permille").copied().unwrap_or(500),
                        c.params.get("duty_max_permille").copied().unwrap_or(500),
                    ),
                    jitter: c.params.get("jitter_ps").copied().unwrap_or(0),
                },
                enable: None,
                wire: wire(pin),
            };
            add(self, &mut chip, o);
        }
        // a pin's load lengthens what drives it
        let load = |pin: u32| c.load.get(pin as usize).copied().unwrap_or([0, 0]);
        let loaded = |a: Vec<Arc>, pin: u32| -> Vec<Arc> {
            a.into_iter()
                .map(|x| Arc {
                    d: x.d.loaded(load(pin)),
                    ..x
                })
                .collect()
        };
        if let Some(desc) = &c.desc {
            chip.unchecked = desc.unchecked.clone();
            chip.sensitive = desc.sensitive.clone();
            for o in &desc.outputs {
                let arcs = loaded(self.arcs(&r, &o.arcs), o.pin);
                let enable = o.enable.as_ref().map(|f| Enable {
                    f: f.clone(),
                    on: loaded(self.arcs(&r, &o.on), o.pin),
                    off: self.arcs(&r, &o.off),
                });
                let out = Output {
                    chip: ci,
                    pin: o.pin,
                    net: nets.get(o.pin as usize).copied().flatten(),
                    inv: o.inv,
                    kind: Kind::Comb {
                        func: o.func.clone(),
                        arcs,
                    },
                    enable,
                    wire: wire(o.pin),
                };
                add(self, &mut chip, out);
            }
            for g in &desc.regs {
                let dl = Delay::of(&g.d, g.est).loaded(load(g.pin));
                let fb = g.feedback.as_ref().map(|f| Delay::of(f, g.fb_est));
                let label = self.label(&r, &g.name, Some(dl));
                let fb_label = self.label(&r, "feedback", fb);
                let clear = g.clear.as_ref().map(|f| Force {
                    f: f.clone(),
                    arcs: self.arcs(&r, &g.clear_arcs),
                });
                let preset = g.preset.as_ref().map(|f| Force {
                    f: f.clone(),
                    arcs: self.arcs(&r, &g.preset_arcs),
                });
                let enable = g.enable.as_ref().map(|f| Enable {
                    f: f.clone(),
                    on: loaded(self.arcs(&r, &g.on), g.pin),
                    off: self.arcs(&r, &g.off),
                });
                let out = Output {
                    chip: ci,
                    pin: g.pin,
                    net: nets.get(g.pin as usize).copied().flatten(),
                    inv: g.inv,
                    kind: Kind::Reg {
                        clock: g.clock,
                        rise: g.edge == 1,
                        next: g.next.clone(),
                        d: dl,
                        label,
                        clear,
                        clear_value: g.clear_value,
                        preset,
                        feedback: fb,
                        fb_label,
                    },
                    enable,
                    wire: wire(g.pin),
                };
                add(self, &mut chip, out);
            }
            for &p in &desc.asynchronous {
                let out = Output {
                    chip: ci,
                    pin: p,
                    net: nets.get(p as usize).copied().flatten(),
                    inv: false,
                    kind: Kind::Async,
                    enable: None,
                    wire: 0,
                };
                add(self, &mut chip, out);
            }
            for k in &desc.checks {
                let (kind, names) = match &k.kind {
                    CheckKindIn::Setup {
                        pins,
                        clock,
                        edge,
                        setup,
                        hold,
                        names,
                    } => (
                        CheckKind::Setup {
                            pins: pins.clone(),
                            clock: *clock,
                            rise: *edge == 1,
                            setup: *setup,
                            hold: *hold,
                        },
                        names.clone(),
                    ),
                    CheckKindIn::Width {
                        pin,
                        level,
                        min,
                        names,
                    } => (
                        CheckKind::Width {
                            pin: *pin,
                            level: *level,
                            min: *min,
                        },
                        names.clone(),
                    ),
                    CheckKindIn::Period { pin, min, names } => (
                        CheckKind::Period {
                            pin: *pin,
                            min: *min,
                        },
                        names.clone(),
                    ),
                    CheckKindIn::Recovery {
                        clock,
                        edge,
                        recovery,
                        removal,
                        width,
                        names,
                    } => (
                        CheckKind::Recovery {
                            clock: *clock,
                            rise: *edge == 1,
                            recovery: *recovery,
                            removal: *removal,
                            width: *width,
                        },
                        names.clone(),
                    ),
                    CheckKindIn::Strobe {
                        active,
                        stable,
                        data,
                        width,
                        eq,
                    } => (
                        CheckKind::Strobe {
                            active: active.clone(),
                            stable: stable.clone(),
                            data: data.clone(),
                            width: *width,
                            eq: eq.clone(),
                        },
                        Vec::new(),
                    ),
                };
                self.checks.push(Check {
                    chip: ci,
                    kind,
                    names,
                    estimated: k.estimated.clone(),
                });
            }
        }
        self.chips.push(chip);
        Ok(())
    }

    /// The pins an output reads, for its value and its enable.
    pub fn reads(&self, o: &Output) -> Vec<u32> {
        let mut pins = Vec::new();
        match &o.kind {
            Kind::Comb { func, arcs } => {
                if let Some(f) = func {
                    pins.extend(support(f));
                }
                for a in arcs {
                    pins.extend(&a.from);
                    if let Some(w) = &a.when {
                        pins.extend(support(w));
                    }
                }
            }
            Kind::Reg {
                clock,
                clear,
                preset,
                ..
            } => {
                pins.push(*clock);
                for f in [clear, preset].into_iter().flatten() {
                    pins.extend(support(&f.f));
                    for a in &f.arcs {
                        pins.extend(&a.from);
                    }
                }
            }
            Kind::Osc { .. } | Kind::Async => {}
        }
        if let Some(e) = &o.enable {
            pins.extend(support(&e.f));
            for a in e.on.iter().chain(&e.off) {
                pins.extend(&a.from);
            }
        }
        pins.sort_unstable();
        pins.dedup();
        pins
    }

    /// The outputs an output depends on: the drivers of the nets it reads
    /// and the registers of its chip it reads back.
    fn deps(&self, oi: u32) -> Vec<u32> {
        let o = &self.outs[oi as usize];
        let chip = &self.chips[o.chip as usize];
        let mut out = Vec::new();
        for p in self.reads(o) {
            match chip.source(p) {
                Source::Net(n) => out.extend(&self.drivers[n as usize]),
                Source::State(r) => {
                    if r != oi {
                        out.push(r)
                    }
                }
                Source::Open => {}
            }
        }
        // a register's state, read back, waits for its own clock's wave
        out.sort_unstable();
        out.dedup();
        out
    }

    /// Strongly connected groups of outputs, dependencies first (Tarjan's
    /// algorithm, without recursion).
    fn groups(&self) -> Vec<Vec<u32>> {
        let n = self.outs.len();
        let deps: Vec<Vec<u32>> = (0..n as u32).map(|i| self.deps(i)).collect();
        let mut index = vec![u32::MAX; n];
        let mut low = vec![0u32; n];
        let mut on = vec![false; n];
        let mut stack = Vec::new();
        let mut out = Vec::new();
        let mut next = 0u32;
        for root in 0..n {
            if index[root] != u32::MAX {
                continue;
            }
            let mut work: Vec<(usize, usize)> = vec![(root, 0)];
            index[root] = next;
            low[root] = next;
            next += 1;
            stack.push(root);
            on[root] = true;
            while let Some(&mut (v, ref mut k)) = work.last_mut() {
                if *k < deps[v].len() {
                    let w = deps[v][*k] as usize;
                    *k += 1;
                    if index[w] == u32::MAX {
                        index[w] = next;
                        low[w] = next;
                        next += 1;
                        stack.push(w);
                        on[w] = true;
                        work.push((w, 0));
                    } else if on[w] {
                        low[v] = low[v].min(index[w]);
                    }
                } else {
                    work.pop();
                    if let Some(&(u, _)) = work.last() {
                        low[u] = low[u].min(low[v]);
                    }
                    if low[v] == index[v] {
                        let mut g = Vec::new();
                        loop {
                            let w = stack.pop().unwrap();
                            on[w] = false;
                            g.push(w as u32);
                            if w == v {
                                break;
                            }
                        }
                        g.sort_unstable();
                        out.push(g);
                    }
                }
            }
        }
        out
    }

    pub fn net(&self, name: &str) -> Result<u32, Error> {
        self.net_index
            .get(name)
            .copied()
            .ok_or_else(|| Error(format!("no net {name}")))
    }

    /// "U_X.PIN" for an output.
    pub fn out_name(&self, oi: u32) -> String {
        let o = &self.outs[oi as usize];
        let c = &self.chips[o.chip as usize];
        format!("{}.{}", c.reference, c.pins[o.pin as usize])
    }
}
