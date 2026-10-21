//! Phase A: values, edge by edge.
//!
//! The reference clock's edges are the events: even ones rising, odd ones
//! falling. Before each event the combinatorial logic settles (zero delay,
//! three values); at it, every register whose clock pin then has an edge
//! loads from the values settled before the event (directly on the clock,
//! or on a clock derived from it in the same event). Values don't depend
//! on delays, so phase B (waves.rs) only times what this finds.

use crate::Error;
use crate::design::{Design, Kind, Source};
use crate::input::Case;
use crate::logic::{X, Z, holds, known, merge, read, sop};

/// What phase A found for one branch of a case.
pub struct Trace {
    /// Events simulated: 0..events.
    pub events: u32,
    /// The event the window ends at.
    pub end: u32,
    /// Net values settled before event 0.
    pub init: Vec<u8>,
    /// Registers' states before event 0 (X for other outputs).
    pub init_state: Vec<u8>,
    /// Net values settled before each event.
    pub pre: Vec<Vec<u8>>,
    /// Registers' states before each event.
    pub pre_state: Vec<Vec<u8>>,
    /// Per output: (event, old, new) at each of its loads.
    pub loads: Vec<Vec<(u32, u8, u8)>>,
    /// Per output: the events at which it was clocked but surely held a
    /// state that isn't known (its next state its state, whatever that is).
    pub held: Vec<Vec<u32>>,
    /// The reference clock's net and its period.
    pub clock: u32,
    pub period: i64,
    /// Pinned nets' values, and those held throughout.
    pub pinned: Vec<Option<u8>>,
    pub constant: Vec<Option<u8>>,
}

pub enum Outcome {
    Done(Box<Trace>),
    /// A branch register would load X at this event: split the case.
    Fork {
        net: u32,
        event: u32,
    },
}

struct Sim<'a> {
    d: &'a Design,
    net: Vec<u8>,
    touched_net: Vec<bool>,
    val: Vec<u8>,
    en: Vec<u8>,
    state: Vec<u8>,
    touched: Vec<bool>,
    pinned: Vec<Option<u8>>,
    constant: Vec<Option<u8>>,
    clock: u32,
    clock_val: u8,
    /// The outputs whose inputs changed since they were evaluated, and
    /// the groups that have one.
    dirty: Vec<bool>,
    gdirty: Vec<bool>,
    /// Outputs a load touched: their nets resolve even if their values
    /// stay.
    force: Vec<bool>,
    /// The first settling resolves every driven net.
    first: bool,
}

impl Sim<'_> {
    fn mark(&mut self, o: u32) {
        self.dirty[o as usize] = true;
        self.gdirty[self.d.group_of[o as usize] as usize] = true;
    }

    /// A register's state changed (or was touched): what reads it.
    fn mark_state(&mut self, o: u32) {
        let d = self.d;
        for &r in &d.state_readers[o as usize] {
            self.mark(r);
        }
    }

    fn pin(&self, chip: u32, p: u32) -> u8 {
        match self.d.chips[chip as usize].source(p) {
            Source::Net(n) => self.net[n as usize],
            Source::State(r) => self.state[r as usize],
            Source::Open => X,
        }
    }

    fn pin_touched(&self, chip: u32, p: u32) -> bool {
        match self.d.chips[chip as usize].source(p) {
            Source::Net(n) => self.touched_net[n as usize],
            Source::State(r) => self.touched[r as usize],
            Source::Open => false,
        }
    }

    /// An output's value and enable from the present values: whether
    /// either changed.
    fn eval(&mut self, oi: u32) -> bool {
        let d = self.d;
        let o = &d.outs[oi as usize];
        let c = o.chip;
        let (v, e, state) = {
            let get = |p: u32| self.pin(c, p);
            let e = match &o.enable {
                Some(en) => sop(&en.f, &get),
                None => 1,
            };
            match &o.kind {
                Kind::Comb { func, .. } => {
                    let v = match func {
                        Some(f) if o.inv => crate::logic::not(sop(f, &get)),
                        Some(f) => sop(f, &get),
                        None => X,
                    };
                    (v, e, None)
                }
                Kind::Reg {
                    clear,
                    clear_value,
                    preset,
                    ..
                } => {
                    let mut st = self.state[oi as usize];
                    for (force, value) in [(clear, *clear_value), (preset, 1 - *clear_value)] {
                        if let Some(f) = force {
                            match sop(&f.f, &get) {
                                1 => st = value,
                                X => st = merge(st, value),
                                _ => {}
                            }
                        }
                    }
                    (st, e, Some(st))
                }
                Kind::Osc { .. } if o.net == Some(self.clock) => (self.clock_val, e, None),
                Kind::Osc { .. } | Kind::Async => (X, e, None),
            }
        };
        let was_touched = self.touched[oi as usize];
        if let Some(st) = state
            && st != self.state[oi as usize]
        {
            self.state[oi as usize] = st;
            self.touched[oi as usize] = true;
            self.mark_state(oi);
        }
        let touched = match &o.kind {
            Kind::Comb { .. } => d.reads_of[oi as usize]
                .iter()
                .any(|&p| self.pin_touched(c, p)),
            _ => d.en_reads[oi as usize]
                .iter()
                .any(|&p| self.pin_touched(c, p)),
        };
        if touched {
            self.touched[oi as usize] = true;
        }
        let changed = self.val[oi as usize] != v
            || self.en[oi as usize] != e
            || self.touched[oi as usize] != was_touched;
        self.val[oi as usize] = v;
        self.en[oi as usize] = e;
        changed
    }

    /// A net's value from its drivers.
    fn resolve(&mut self, n: u32) -> bool {
        let d = self.d;
        let ni = n as usize;
        let was_touched = self.touched_net[ni];
        let v = if let Some(r) = d.rail[ni].or(self.constant[ni]) {
            r
        } else {
            let drv = &d.drivers[ni];
            let mut touched = false;
            let (mut on, mut maybe) = (Vec::new(), Vec::new());
            for &o in drv {
                touched |= self.touched[o as usize];
                match self.en[o as usize] {
                    1 => on.push(self.val[o as usize]),
                    0 => {}
                    _ => maybe.push(self.val[o as usize]),
                }
            }
            if touched {
                self.touched_net[ni] = true;
            }
            let v = resolve(&on, &maybe, d.pulled[ni]);
            match self.pinned[ni] {
                Some(p) if self.touched_net[ni] => p,
                _ => v,
            }
        };
        let changed = self.net[ni] != v || self.touched_net[ni] != was_touched;
        self.net[ni] = v;
        changed
    }

    /// Evaluates what changed, group by group in order, a loop's group
    /// until nothing in it changes.
    fn settle(&mut self) -> Result<(), Error> {
        let d = self.d;
        let first = std::mem::take(&mut self.first);
        for (gi, g) in d.order.iter().enumerate() {
            if !self.gdirty[gi] {
                continue;
            }
            for round in 0.. {
                self.gdirty[gi] = false;
                for &o in g {
                    if !std::mem::take(&mut self.dirty[o as usize]) {
                        continue;
                    }
                    let changed = self.eval(o);
                    let force = std::mem::take(&mut self.force[o as usize]);
                    if let Some(n) = d.outs[o as usize].net
                        && (changed || first || force)
                        && self.resolve(n)
                    {
                        for &r in &d.net_readers[n as usize] {
                            self.mark(r);
                        }
                    }
                }
                if !self.gdirty[gi] {
                    break;
                }
                if round > 64 {
                    let nets: Vec<String> = g
                        .iter()
                        .filter_map(|&o| d.outs[o as usize].net)
                        .map(|n| d.nets[n as usize].clone())
                        .collect();
                    return Err(Error(format!(
                        "a loop that doesn't settle: {}",
                        nets.join(", ")
                    )));
                }
            }
        }
        Ok(())
    }
}

/// The value of a net from the drivers surely on and those that may be.
pub fn resolve(on: &[u8], maybe: &[u8], pulled: bool) -> u8 {
    if on.len() == 1 && maybe.is_empty() {
        return read(on[0]);
    }
    if on.is_empty() && maybe.is_empty() {
        return if pulled { 1 } else { Z };
    }
    let mut vals: Vec<u8> = on.iter().chain(maybe).map(|&v| read(v)).collect();
    if on.is_empty() && pulled {
        vals.push(1);
    }
    let first = vals[0];
    if known(first) && vals.iter().all(|&v| v == first) {
        first
    } else {
        X
    }
}

/// Phase A for one branch of a case.
pub fn run(d: &Design, case: &Case) -> Result<Outcome, Error> {
    let clock = d.net(&case.clock)?;
    let period = d.drivers[clock as usize]
        .iter()
        .find_map(|&o| match d.outs[o as usize].kind {
            Kind::Osc { period, .. } => Some(period),
            _ => None,
        })
        .ok_or_else(|| Error(format!("{} isn't an oscillator's", case.clock)))?;
    let end_net = d.net(&case.end.net)?;
    let mut pinned = vec![None; d.nets.len()];
    for (n, &v) in &case.pins {
        pinned[d.net(n)? as usize] = Some(v);
    }
    let mut constant = vec![None; d.nets.len()];
    for (n, &v) in &case.constant {
        constant[d.net(n)? as usize] = Some(v);
    }
    // registers by net, for the start state, the forced loads and branches
    let reg_of = |name: &str| -> Result<u32, Error> {
        let n = d.net(name)?;
        d.drivers[n as usize]
            .iter()
            .copied()
            .find(|&o| d.outs[o as usize].is_reg())
            .ok_or_else(|| Error(format!("{name}: no register drives it")))
    };
    let mut start = vec![None; d.outs.len()];
    for (n, &(before, after)) in &case.start {
        start[reg_of(n)? as usize] = Some((before, after));
    }
    // a branch's few choices: a list is quicker than a map
    let mut forced: Vec<((u32, u32), u8)> = Vec::new();
    for (n, e, v) in &case.forced {
        forced.push(((reg_of(n)?, *e), *v));
    }
    let mut branch = vec![false; d.outs.len()];
    for n in &case.branch {
        branch[reg_of(n)? as usize] = true;
    }
    let no = d.outs.len();
    let mut s = Sim {
        d,
        net: vec![X; d.nets.len()],
        touched_net: vec![false; d.nets.len()],
        val: vec![X; no],
        en: vec![X; no],
        state: (0..no)
            .map(|o| start[o].map(|x| x.0).unwrap_or(X))
            .collect(),
        touched: vec![false; no],
        pinned: pinned.clone(),
        constant: constant.clone(),
        clock,
        clock_val: 0,
        dirty: vec![true; no],
        gdirty: vec![true; d.order.len()],
        force: vec![false; no],
        first: true,
    };
    for (n, v) in s.net.iter_mut().enumerate() {
        *v = match d.rail[n].or(constant[n]) {
            Some(r) => r,
            None if d.drivers[n].is_empty() => {
                if d.pulled[n] {
                    1
                } else {
                    Z
                }
            }
            None => X,
        };
    }
    s.settle()?;
    let init = s.net.clone();
    let init_state = s.state.clone();
    let regs: Vec<u32> = (0..no as u32)
        .filter(|&o| d.outs[o as usize].is_reg())
        .collect();
    let clock_pin = |s: &Sim, o: u32| -> u8 {
        let out = &d.outs[o as usize];
        match out.kind {
            Kind::Reg { clock, .. } => read(s.pin(out.chip, clock)),
            _ => X,
        }
    };
    let mut last: Vec<u8> = vec![X; no];
    for &o in &regs {
        last[o as usize] = clock_pin(&s, o);
    }
    let mut loads = vec![Vec::new(); no];
    let mut held = vec![Vec::new(); no];
    let mut pre = Vec::new();
    let mut pre_state = Vec::new();
    let mut end = None;
    let max = case.end.events.max(2);
    let mut e = 0;
    loop {
        let before = s.net.clone();
        let before_state = s.state.clone();
        s.clock_val = if e % 2 == 0 { 1 } else { 0 };
        for &o in &d.drivers[clock as usize] {
            s.mark(o);
        }
        s.settle()?;
        for _cascade in 0..32 {
            let mut loading = Vec::new();
            for &o in &regs {
                let now = clock_pin(&s, o);
                let was = last[o as usize];
                let rise = matches!(d.outs[o as usize].kind, Kind::Reg { rise: true, .. });
                let (from, to) = if rise { (0, 1) } else { (1, 0) };
                let edge = if was == from && now == to {
                    Some(true)
                } else if was != now && (was == from || now == to || (was == X && now == X)) {
                    Some(false)
                } else {
                    None
                };
                last[o as usize] = now;
                if let Some(definite) = edge {
                    loading.push((o, definite));
                }
            }
            if loading.is_empty() {
                break;
            }
            let mut new = Vec::new();
            for (o, definite) in loading {
                let out = &d.outs[o as usize];
                let Kind::Reg { next, .. } = &out.kind else {
                    continue;
                };
                let own = |p: u32| match d.chips[out.chip as usize].source(p) {
                    Source::State(r) => r == o,
                    Source::Net(n) => Some(n) == out.net,
                    Source::Open => false,
                };
                let chip = &d.chips[out.chip as usize];
                let get = |p: u32| match chip.source(p) {
                    Source::Net(n) => before[n as usize],
                    Source::State(r) => before_state[r as usize],
                    Source::Open => X,
                };
                let mut v = sop(next, &get);
                if out.inv {
                    v = crate::logic::not(v);
                }
                let old = s.state[o as usize];
                if !definite {
                    v = merge(old, v);
                }
                if e == 0
                    && let Some((_, after)) = start[o as usize]
                {
                    v = after;
                }
                let force = forced.iter().find(|x| x.0 == (o, e)).map(|x| x.1);
                if let Some(f) = force {
                    v = f;
                } else if v == X
                    && definite
                    && branch[o as usize]
                    && end.is_none()
                    && !(e == 0 && start[o as usize].is_some())
                {
                    return Ok(Outcome::Fork {
                        net: out.net.unwrap_or(0),
                        event: e,
                    });
                }
                if v == X
                    && old == X
                    && force.is_none()
                    && !(e == 0 && start[o as usize].is_some())
                    && holds(next, out.inv, &own, &get)
                {
                    held[o as usize].push(e);
                    continue;
                }
                loads[o as usize].push((e, old, v));
                new.push((o, v));
            }
            for (o, v) in new {
                let old = s.state[o as usize];
                if !(old == v && known(v)) && !s.touched[o as usize] {
                    s.touched[o as usize] = true;
                    s.force[o as usize] = true;
                }
                s.state[o as usize] = v;
                s.mark_state(o);
            }
            s.settle()?;
        }
        if e == 0 {
            for (o, st) in start.iter().enumerate() {
                if st.is_some() && !loads[o].iter().any(|l| l.0 == 0) {
                    return Err(Error(format!(
                        "start: {} doesn't load at the edge at 0",
                        d.out_name(o as u32)
                    )));
                }
            }
        }
        pre.push(before.clone());
        pre_state.push(before_state);
        if e > 0 && end.is_none() && before[end_net as usize] == 0 && s.net[end_net as usize] == 1 {
            end = Some(e);
        }
        e += 1;
        if let Some(x) = end {
            if e > x + 2 {
                break;
            }
        } else if e >= max {
            return Err(Error(format!(
                "{}: {} doesn't rise within {max} events",
                case.label, case.end.net
            )));
        }
    }
    Ok(Outcome::Done(Box::new(Trace {
        events: e,
        end: end.unwrap_or(0),
        init,
        init_state,
        pre,
        pre_state,
        loads,
        held,
        clock,
        period,
        pinned,
        constant,
    })))
}
