//! Phase B: waveforms.
//!
//! Every net's wave is its value before the window and its transitions,
//! each with a window [earliest, latest], its values before and after and
//! whether it's clean (one change at most) or may glitch. An output's
//! transitions come from its inputs' through its arcs: inputs whose windows
//! at the output overlap race, and the output may glitch unless a term
//! holds it (Atmel's rule, RFC 0048 4). A register's transitions come from
//! its clock pin's edges, with the values phase A found at them. Each
//! transition's earliest and latest times are nodes of a tree of causes
//! back to the reference clock's edges: the paths, and what common path
//! pessimism removal compares.

use crate::Error;
use crate::design::{Arc, Delay, Design, Kind, Source};
use crate::logic::{V0, V1, X, Z, held0, held1, known, live, merge, not, sop, support};
use crate::values::{Trace, resolve};

pub const NONE: u32 = u32::MAX;
/// A node's key for a register's state inside its chip, not on a net.
pub const STATE: u32 = 1 << 31;

/// A point on a path: a time at a net (or a register's state), the node it
/// came from, the arc between, and the reference edge it goes back to.
#[derive(Clone, Copy, Debug)]
pub struct Node {
    pub t: i64,
    pub parent: u32,
    pub key: u32,
    pub label: u32,
    pub event: i32,
}

#[derive(Clone, Copy, Debug)]
pub struct Tr {
    pub e: i64,
    pub l: i64,
    pub before: u8,
    pub after: u8,
    pub clean: bool,
    /// The nodes that set the earliest and the latest time.
    pub ce: u32,
    pub cl: u32,
    /// The times by the reference edge each part goes back to, where it
    /// goes back to more than one: an index into Waves::parts; else NONE.
    pub parts: u32,
}

/// What of a transition goes back to one reference edge.
#[derive(Clone, Copy, Debug)]
pub struct Part {
    pub event: i32,
    pub e: i64,
    pub l: i64,
    pub ce: u32,
    pub cl: u32,
}

#[derive(Clone, Debug, Default)]
pub struct Wave {
    pub init: u8,
    pub tr: Vec<Tr>,
}

impl Wave {
    pub fn constant(v: u8) -> Wave {
        Wave {
            init: v,
            tr: Vec::new(),
        }
    }

    /// The value just before t: X inside a transition's window.
    pub fn at(&self, t: i64) -> u8 {
        let mut v = self.init;
        for tr in &self.tr {
            if tr.e >= t {
                break;
            }
            if tr.l >= t {
                return X;
            }
            v = tr.after;
        }
        v
    }

    fn same(&self, o: &Wave) -> bool {
        self.init == o.init
            && self.tr.len() == o.tr.len()
            && self.tr.iter().zip(&o.tr).all(|(a, b)| {
                a.e == b.e
                    && a.l == b.l
                    && a.before == b.before
                    && a.after == b.after
                    && a.clean == b.clean
            })
    }
}

/// One input transition's effect at an output, through the arcs that
/// apply: a window per set of arcs (an enable's turn-on and turn-off).
#[derive(Clone, Debug)]
struct Effect {
    pin: usize,
    /// Which of the pin's transitions.
    k: usize,
    tr: Tr,
    event: i32,
    /// Its window at the output per set of arcs, and over them all, with
    /// the nodes it comes from.
    win: Vec<Option<(i64, i64, u32, u32)>>,
    union: (i64, i64, u32, u32),
    from: (u32, u32),
}

pub struct Waves<'a> {
    pub d: &'a Design,
    pub t: &'a Trace,
    pub fraction: f64,
    pub net: Vec<Wave>,
    pub val: Vec<Wave>,
    pub en: Vec<Wave>,
    /// Registers' states as their chips' own functions see them.
    pub fb: Vec<Wave>,
    pub nodes: Vec<Node>,
    pub parts: Vec<Vec<Part>>,
    pub notes: Vec<String>,
    /// The nets of loops whose waves didn't settle.
    pub unsettled: Vec<u32>,
    xw: Wave,
}

pub fn event_time(e: u32, period: i64) -> i64 {
    (e / 2) as i64 * period + (e % 2) as i64 * (period / 2)
}

impl<'a> Waves<'a> {
    pub fn pin_wave(&self, chip: u32, p: u32) -> &Wave {
        match self.d.chips[chip as usize].source(p) {
            Source::Net(n) => &self.net[n as usize],
            Source::State(r) => &self.fb[r as usize],
            Source::Open => &self.xw,
        }
    }

    fn node(&mut self, t: i64, parent: u32, key: u32, label: u32) -> u32 {
        let event = if parent == NONE {
            -1
        } else {
            self.nodes[parent as usize].event
        };
        self.nodes.push(Node {
            t,
            parent,
            key,
            label,
            event,
        });
        (self.nodes.len() - 1) as u32
    }

    /// The wave of a function of a chip's pins through sets of arcs (one
    /// set for an output's value; turn-on and turn-off for an enable).
    pub(crate) fn eval(
        &mut self,
        chip: u32,
        func: Option<&crate::input::Sop>,
        inv: bool,
        sets: &[&[Arc]],
        key: u32,
    ) -> Wave {
        let mut pins: Vec<u32> = func.map(support).unwrap_or_default();
        for s in sets {
            for a in s.iter() {
                pins.extend(&a.from);
                if let Some(w) = &a.when {
                    pins.extend(support(w));
                }
            }
        }
        pins.sort_unstable();
        pins.dedup();
        let waves: Vec<Wave> = pins
            .iter()
            .map(|&p| self.pin_wave(chip, p).clone())
            .collect();
        let idx = |p: u32| pins.binary_search(&p).ok();
        let f = self.fraction;
        let own_net = if key & STATE == 0 { Some(key) } else { None };
        let own: Vec<bool> = pins
            .iter()
            .map(|&p| {
                own_net.is_some_and(|n| self.d.chips[chip as usize].source(p) == Source::Net(n))
            })
            .collect();
        let mut effects = Vec::new();
        for (pi, &p) in pins.iter().enumerate() {
            // an output's own net, fed back (a latch's): its value counts,
            // its changes are the output's own
            if own[pi] {
                continue;
            }
            for (k, tr) in waves[pi].tr.iter().enumerate() {
                // the stretches of a change in which the function can
                // answer it, with the other inputs as they are then: the
                // rest doesn't reach the output; between stretches the
                // input may or may not have changed yet
                let mut spans: Vec<(i64, i64)> = Vec::new();
                if let Some(fun) = func {
                    let mut bp: Vec<i64> = vec![tr.e, tr.l + 1];
                    for (q, w) in waves.iter().enumerate() {
                        if q == pi {
                            continue;
                        }
                        for t in &w.tr {
                            for x in [t.e, t.l + 1] {
                                if x > tr.e && x <= tr.l {
                                    bp.push(x);
                                }
                            }
                        }
                    }
                    bp.sort_unstable();
                    bp.dedup();
                    for win in bp.windows(2) {
                        let (a, b) = (win[0], win[1]);
                        let busy =
                            |q: usize| q == pi || waves[q].tr.iter().any(|t| t.e < b && t.l >= a);
                        let get = |q: u32| idx(q).map(|i| waves[i].at(a)).unwrap_or(X);
                        let mv = |q: u32| idx(q).is_some_and(busy);
                        if !held1(fun, &get, &mv) && live(fun, p, &get, &mv) {
                            match spans.last_mut() {
                                Some(last) if last.1 + 1 == a => last.1 = b - 1,
                                _ => spans.push((a, b - 1)),
                            }
                        }
                    }
                } else {
                    spans.push((tr.e, tr.l));
                }
                let n_spans = spans.len();
                for (si, &(ne, nl)) in spans.iter().enumerate() {
                    let mut tr = *tr;
                    if si > 0 {
                        tr.before = X;
                    }
                    if si + 1 < n_spans {
                        tr.after = X;
                    }
                    for part in self.parts_of(&tr) {
                        let (pe, pl) = (part.e.max(ne), part.l.min(nl));
                        if pe > pl {
                            continue;
                        }
                        let mut win = Vec::with_capacity(sets.len());
                        let mut any: Option<(i64, i64, u32, u32)> = None;
                        for s in sets {
                            let mut w: Option<(i64, i64, u32, u32)> = None;
                            for a in s.iter().filter(|a| a.from.contains(&p)) {
                                if let Some(cond) = &a.when {
                                    let at = |q: u32| idx(q).map(|i| waves[i].at(pe)).unwrap_or(X);
                                    if sop(cond, &at) == V0 {
                                        continue;
                                    }
                                }
                                let (lo, hi) = (pe + a.d.lo(f), pl + a.d.hi());
                                w = Some(match w {
                                    None => (lo, hi, a.label, a.label),
                                    Some((e, l, le, ll)) => {
                                        let (e, le) = if lo < e { (lo, a.label) } else { (e, le) };
                                        let (l, ll) = if hi > l { (hi, a.label) } else { (l, ll) };
                                        (e, l, le, ll)
                                    }
                                });
                            }
                            if let Some(x) = w {
                                any = Some(match any {
                                    None => x,
                                    Some(u) => (
                                        u.0.min(x.0),
                                        u.1.max(x.1),
                                        if x.0 < u.0 { x.2 } else { u.2 },
                                        if x.1 > u.1 { x.3 } else { u.3 },
                                    ),
                                });
                            }
                            win.push(w);
                        }
                        if let Some(union) = any {
                            effects.push(Effect {
                                pin: pi,
                                k,
                                tr,
                                event: part.event,
                                win,
                                union,
                                from: (part.ce, part.cl),
                            });
                        }
                    }
                }
            }
        }
        effects.sort_by_key(|x| (x.union.0, x.union.1));
        let mut cur: Vec<u8> = waves.iter().map(|w| w.init).collect();
        let value = |f: Option<&crate::input::Sop>, vals: &[u8]| -> u8 {
            match f {
                Some(f) => sop(f, &|q| idx(q).map(|i| vals[i]).unwrap_or(X)),
                None => X,
            }
        };
        let flip = |v: u8| if inv { not(v) } else { v };
        let init = flip(value(func, &cur));
        let mut out = Vec::new();
        let mut i = 0;
        while i < effects.len() {
            let mut j = i + 1;
            let mut end = effects[i].union.1;
            while j < effects.len() && effects[j].union.0 <= end {
                end = end.max(effects[j].union.1);
                j += 1;
            }
            let cluster = &effects[i..j];
            let before = cur.clone();
            for x in cluster {
                cur[x.pin] = x.tr.after;
            }
            for _ in 0..3 {
                let v = flip(value(func, &cur));
                for (q, &o) in own.iter().enumerate() {
                    if o {
                        cur[q] = v;
                    }
                }
            }
            let mut moving = vec![false; pins.len()];
            let mut distinct: Vec<(usize, usize)> = Vec::new();
            for x in cluster {
                moving[x.pin] = true;
                if !distinct.contains(&(x.pin, x.k)) {
                    distinct.push((x.pin, x.k));
                }
            }
            let one = distinct.len() == 1;
            let all_clean = cluster.iter().all(|x| x.tr.clean);
            let (rb, ra) = (value(func, &before), value(func, &cur));
            let clean = match func {
                Some(fun) => {
                    let get = |q: u32| idx(q).map(|i| before[i]).unwrap_or(X);
                    let mv = |q: u32| idx(q).map(|i| moving[i]).unwrap_or(false);
                    if held1(fun, &get, &mv) || held0(fun, &get, &mv) {
                        i = j;
                        continue;
                    }
                    if one && all_clean {
                        if known(rb) && known(ra) && rb != ra {
                            true
                        } else if rb == V0 && ra == V0 {
                            i = j;
                            continue;
                        } else if rb == V1 && ra == V1 {
                            false
                        } else {
                            rb == V0 || ra == V0
                        }
                    } else {
                        false
                    }
                }
                None => one && all_clean,
            };
            // an enable's turn-on or turn-off times, else either
            let set = if sets.len() == 2 && rb == V0 && ra == V1 {
                Some(0)
            } else if sets.len() == 2 && rb == V1 && ra == V0 {
                Some(1)
            } else {
                None
            };
            // by reference edge: each edge's earliest and latest
            let mut by: Vec<(i32, i64, i64, u32, u32, u32, u32)> = Vec::new();
            for x in cluster {
                let (e, l, le, ll) = set.and_then(|s| x.win[s]).unwrap_or(x.union);
                match by.iter_mut().find(|b| b.0 == x.event) {
                    Some(b) => {
                        if e < b.1 {
                            (b.1, b.3, b.5) = (e, le, x.from.0);
                        }
                        if l > b.2 {
                            (b.2, b.4, b.6) = (l, ll, x.from.1);
                        }
                    }
                    None => by.push((x.event, e, l, le, ll, x.from.0, x.from.1)),
                }
            }
            let mut parts = Vec::with_capacity(by.len());
            for &(event, e, l, le, ll, fe, fl) in &by {
                let ce = self.node(e, fe, key, le);
                let cl = self.node(l, fl, key, ll);
                parts.push(Part {
                    event,
                    e,
                    l,
                    ce,
                    cl,
                });
            }
            let first = *parts.iter().min_by_key(|p| p.e).unwrap();
            let last = *parts.iter().max_by_key(|p| p.l).unwrap();
            let pi = if parts.len() > 1 {
                self.parts.push(parts);
                (self.parts.len() - 1) as u32
            } else {
                NONE
            };
            out.push(Tr {
                e: first.e,
                l: last.l,
                before: flip(rb),
                after: flip(ra),
                clean,
                ce: first.ce,
                cl: last.cl,
                parts: pi,
            });
            i = j;
        }
        Wave { init, tr: out }
    }

    /// A transition's parts by reference edge: one, unless it has several.
    pub fn parts_of(&self, tr: &Tr) -> Vec<Part> {
        if tr.parts != NONE {
            return self.parts[tr.parts as usize].clone();
        }
        let event = if tr.cl == NONE {
            -1
        } else {
            self.nodes[tr.cl as usize].event
        };
        vec![Part {
            event,
            e: tr.e,
            l: tr.l,
            ce: tr.ce,
            cl: tr.cl,
        }]
    }

    /// A register's wave: its output's (fb false) or its state as its chip
    /// reads it back (fb true).
    fn reg(&mut self, oi: u32, fb: bool) -> Wave {
        let d = self.d;
        let o = &d.outs[oi as usize];
        let Kind::Reg {
            clock,
            rise,
            d: delay,
            label,
            clear,
            clear_value,
            preset,
            feedback,
            fb_label,
            ..
        } = &o.kind
        else {
            return Wave::constant(X);
        };
        let (dl, lab) = if fb {
            (feedback.unwrap_or(Delay::zero()), *fb_label)
        } else {
            (*delay, *label)
        };
        let key = if fb {
            STATE | oi
        } else {
            o.net.unwrap_or(STATE | oi)
        };
        let cw = self.pin_wave(o.chip, *clock).clone();
        let f = self.fraction;
        let mut out = Vec::new();
        for tr in &cw.tr {
            let (from, to) = if *rise { (V0, V1) } else { (V1, V0) };
            let possible = !tr.clean
                || (tr.before != tr.after || tr.before == X)
                    && (tr.before == from || tr.before == X)
                    && (tr.after == to || tr.after == X);
            if !possible {
                continue;
            }
            let ev = self.nodes[tr.cl as usize].event;
            if ev < 0 {
                continue;
            }
            let Some(&(_, old, new)) = self.t.loads[oi as usize].iter().find(|l| l.0 == ev as u32)
            else {
                if tr.clean && tr.before == from && tr.after == to && !fb {
                    self.notes.push(format!(
                        "{}: an edge at event {ev} that phase A didn't load at",
                        d.out_name(oi)
                    ));
                }
                continue;
            };
            if old == new && known(new) {
                continue;
            }
            let ce = self.node(tr.e + dl.lo(f), tr.ce, key, lab);
            let cl = self.node(tr.l + dl.hi(), tr.cl, key, lab);
            out.push(Tr {
                e: tr.e + dl.lo(f),
                l: tr.l + dl.hi(),
                before: old,
                after: new,
                clean: tr.clean,
                ce,
                cl,
                parts: NONE,
            });
        }
        let forces: Vec<(crate::design::Force, u8)> =
            [(clear, *clear_value), (preset, 1 - *clear_value)]
                .into_iter()
                .filter_map(|(f, v)| f.clone().map(|f| (f, v)))
                .collect();
        for (force, value) in forces {
            let w = self.eval(o.chip, Some(&force.f), false, &[&force.arcs], key);
            for tr in w.tr {
                if tr.after == V0 && tr.before == V0 {
                    continue;
                }
                let after = if tr.after == V1 { value } else { X };
                out.push(Tr {
                    before: X,
                    after: merge(after, after),
                    clean: false,
                    ..tr
                });
            }
        }
        let init = self.t.init_state[oi as usize];
        Wave {
            init,
            tr: normalize(out),
        }
    }

    fn output(&mut self, oi: u32) {
        let d = self.d;
        let o = &d.outs[oi as usize];
        let key = o.net.unwrap_or(STATE | oi);
        let mut val = match &o.kind {
            Kind::Comb { func, arcs } => self.eval(o.chip, func.as_ref(), o.inv, &[arcs], key),
            Kind::Reg { .. } => {
                self.fb[oi as usize] = self.reg(oi, true);
                self.reg(oi, false)
            }
            Kind::Osc { .. } if o.net == Some(self.t.clock) => {
                let mut w = Wave::constant(V0);
                for e in 0..self.t.events {
                    let t = event_time(e, self.t.period);
                    self.nodes.push(Node {
                        t,
                        parent: NONE,
                        key,
                        label: NONE,
                        event: e as i32,
                    });
                    let n = (self.nodes.len() - 1) as u32;
                    let rise = e % 2 == 0;
                    w.tr.push(Tr {
                        e: t,
                        l: t,
                        before: if rise { V0 } else { V1 },
                        after: if rise { V1 } else { V0 },
                        clean: true,
                        ce: n,
                        cl: n,
                        parts: NONE,
                    });
                }
                w
            }
            Kind::Osc { .. } | Kind::Async => Wave::constant(X),
        };
        let mut en = match &o.enable {
            Some(e) => self.eval(o.chip, Some(&e.f), false, &[&e.on, &e.off], key),
            None => Wave::constant(V1),
        };
        if o.wire > 0 {
            for w in [&mut val, &mut en] {
                for tr in w.tr.iter_mut() {
                    tr.e += o.wire;
                    tr.l += o.wire;
                    self.nodes.push(Node {
                        t: tr.e,
                        parent: tr.ce,
                        key,
                        label: 0,
                        event: self.nodes[tr.ce as usize].event,
                    });
                    tr.ce = (self.nodes.len() - 1) as u32;
                    self.nodes.push(Node {
                        t: tr.l,
                        parent: tr.cl,
                        key,
                        label: 0,
                        event: self.nodes[tr.cl as usize].event,
                    });
                    tr.cl = (self.nodes.len() - 1) as u32;
                }
            }
        }
        self.val[oi as usize] = val;
        self.en[oi as usize] = en;
    }

    fn net_wave(&mut self, n: u32) -> Wave {
        let d = self.d;
        let ni = n as usize;
        if let Some(r) = d.rail[ni].or(self.t.constant[ni]) {
            return Wave::constant(r);
        }
        let drv = &d.drivers[ni];
        let mut w = if drv.is_empty() {
            Wave::constant(if d.pulled[ni] { V1 } else { Z })
        } else if drv.len() == 1 && d.outs[drv[0] as usize].enable.is_none() {
            self.val[drv[0] as usize].clone()
        } else {
            self.bus(ni)
        };
        if let Some(p) = self.t.pinned[ni] {
            for tr in w.tr.iter_mut() {
                tr.after = p;
            }
            let mut prev = w.init;
            for tr in w.tr.iter_mut() {
                tr.before = prev;
                if tr.before == tr.after {
                    tr.clean = false;
                }
                prev = tr.after;
            }
        }
        w
    }
}

impl Waves<'_> {
    /// A net with several drivers or a three-state one: a sweep through
    /// time. In each stretch between the drivers' transitions the net is
    /// changing if a driver that may be on is changing, or an enable is;
    /// else it has the value its drivers resolve to. A driver's change
    /// while it is surely off doesn't count.
    fn bus(&mut self, ni: usize) -> Wave {
        let d = self.d;
        let drv = &d.drivers[ni];
        let mut parts = std::mem::take(&mut self.parts);
        let nodes = &self.nodes;
        let vals: Vec<&Wave> = drv.iter().map(|&o| &self.val[o as usize]).collect();
        let ens: Vec<&Wave> = drv.iter().map(|&o| &self.en[o as usize]).collect();
        let mut bp: Vec<i64> = Vec::new();
        for w in vals.iter().chain(&ens) {
            for t in &w.tr {
                bp.push(t.e);
                bp.push(t.l + 1);
            }
        }
        bp.sort_unstable();
        bp.dedup();
        let res = |v: &[u8], e: &[u8]| {
            let (mut on, mut maybe) = (Vec::new(), Vec::new());
            for (v, e) in v.iter().zip(e) {
                match *e {
                    V1 => on.push(*v),
                    V0 => {}
                    _ => maybe.push(*v),
                }
            }
            resolve(&on, &maybe, d.pulled[ni])
        };
        let n = drv.len();
        let iv: Vec<u8> = vals.iter().map(|w| w.init).collect();
        let ie: Vec<u8> = ens.iter().map(|w| w.init).collect();
        let init = res(&iv, &ie);
        // per wave: the first transition not yet over
        let mut kv = vec![0usize; n];
        let mut ke = vec![0usize; n];
        let state = |w: &Wave, k: &mut usize, a: i64| -> (u8, Option<usize>) {
            while *k < w.tr.len() && w.tr[*k].l < a {
                *k += 1;
            }
            if *k < w.tr.len() && w.tr[*k].e <= a {
                (X, Some(*k))
            } else if *k == 0 {
                (w.init, None)
            } else {
                (w.tr[*k - 1].after, None)
            }
        };
        let mut out = Vec::new();
        let mut last = init;
        // the transition being built: its start, end, and contributors
        let mut seg: Option<(i64, i64, u8, Vec<Tr>)> = None;
        let mut cv = vec![X; n];
        let mut ce = vec![X; n];
        for (bi, &a) in bp.iter().enumerate() {
            let b = bp.get(bi + 1).copied().unwrap_or(a + 1);
            let mut contrib: Vec<Tr> = Vec::new();
            let mut offs: Vec<Tr> = Vec::new();
            let mut steady_on = 0;
            for i in 0..n {
                let (v, vc) = state(vals[i], &mut kv[i], a);
                let (e, ec) = state(ens[i], &mut ke[i], a);
                cv[i] = v;
                ce[i] = e;
                match ec {
                    // a driver letting go: the net keeps its value
                    Some(k) if ens[i].tr[k].after == V0 => offs.push(ens[i].tr[k]),
                    Some(k) => contrib.push(ens[i].tr[k]),
                    None if e != V0 => steady_on += 1,
                    None => {}
                }
                if let Some(k) = vc
                    && e != V0
                {
                    contrib.push(vals[i].tr[k]);
                }
            }
            // the net changes as one lets go only if another is on all the
            // while; else when the other turns on
            if steady_on > 0 {
                contrib.extend(offs);
            }
            if contrib.is_empty() {
                // a net no driver drives keeps the value it had (its own
                // capacitance, a 22V10's pin keeper): letting go of it
                // doesn't change it
                let now = match res(&cv, &ce) {
                    Z => last,
                    v => v,
                };
                if let Some((s0, s1, before, c)) = seg.take() {
                    let t = Self::joined(&mut parts, nodes, s0, s1, before, now, &c);
                    if !(t.before == t.after && known(t.before) && c.iter().all(|x| x.clean)) {
                        out.push(t);
                    }
                }
                last = now;
            } else {
                match &mut seg {
                    Some((_, s1, _, c)) => {
                        *s1 = b - 1;
                        for t in contrib {
                            if !c.iter().any(|x| x.ce == t.ce && x.cl == t.cl) {
                                c.push(t);
                            }
                        }
                    }
                    None => seg = Some((a, b - 1, last, contrib)),
                }
            }
        }
        if let Some((s0, s1, before, c)) = seg {
            out.push(Self::joined(&mut parts, nodes, s0, s1, before, X, &c));
        }
        self.parts = parts;
        Wave { init, tr: out }
    }

    /// One transition of a bus from the drivers' transitions in it, with
    /// their parts by reference edge, clipped to it.
    #[allow(clippy::too_many_arguments)] // the segment's fields
    fn joined(
        parts: &mut Vec<Vec<Part>>,
        nodes: &[Node],
        e: i64,
        l: i64,
        before: u8,
        after: u8,
        c: &[Tr],
    ) -> Tr {
        let clean = c.len() == 1 && c[0].clean;
        let mut by: Vec<Part> = Vec::new();
        for t in c {
            let ps = if t.parts != NONE {
                parts[t.parts as usize].clone()
            } else {
                let event = if t.cl == NONE {
                    -1
                } else {
                    nodes[t.cl as usize].event
                };
                vec![Part {
                    event,
                    e: t.e,
                    l: t.l,
                    ce: t.ce,
                    cl: t.cl,
                }]
            };
            for p in ps {
                let (pe, pl) = (p.e.max(e), p.l.min(l));
                match by.iter_mut().find(|b| b.event == p.event) {
                    Some(b) => {
                        if pe < b.e {
                            b.e = pe;
                            b.ce = p.ce;
                        }
                        if pl > b.l {
                            b.l = pl;
                            b.cl = p.cl;
                        }
                    }
                    None => by.push(Part {
                        event: p.event,
                        e: pe,
                        l: pl,
                        ce: p.ce,
                        cl: p.cl,
                    }),
                }
            }
        }
        let first = *by.iter().min_by_key(|p| p.e).unwrap();
        let last = *by.iter().max_by_key(|p| p.l).unwrap();
        let pi = if by.len() > 1 {
            parts.push(by);
            (parts.len() - 1) as u32
        } else {
            NONE
        };
        Tr {
            e,
            l,
            before,
            after,
            clean: clean && (before != after || !known(before)),
            ce: first.ce,
            cl: last.cl,
            parts: pi,
        }
    }
}

/// Transitions in time order, those whose windows overlap made one that
/// may glitch.
fn normalize(mut tr: Vec<Tr>) -> Vec<Tr> {
    tr.sort_by_key(|t| (t.e, t.l));
    let mut out: Vec<Tr> = Vec::with_capacity(tr.len());
    for t in tr {
        if let Some(last) = out.last_mut()
            && t.e <= last.l
        {
            if t.l > last.l {
                last.l = t.l;
                last.cl = t.cl;
            }
            last.after = t.after;
            last.clean = false;
            continue;
        }
        out.push(t);
    }
    out
}

/// Phase B for one branch: every net's and output's wave.
pub fn run<'a>(d: &'a Design, t: &'a Trace, fraction: f64) -> Result<Waves<'a>, Error> {
    let no = d.outs.len();
    let mut w = Waves {
        d,
        t,
        fraction,
        net: t.init.iter().map(|&v| Wave::constant(v)).collect(),
        val: vec![Wave::constant(X); no],
        en: vec![Wave::constant(V1); no],
        fb: (0..no).map(|o| Wave::constant(t.init_state[o])).collect(),
        nodes: Vec::new(),
        parts: Vec::new(),
        notes: Vec::new(),
        unsettled: Vec::new(),
        xw: Wave::constant(X),
    };
    for (gi, g) in d.order.iter().enumerate() {
        let nets: Vec<u32> = {
            let mut v: Vec<u32> = g.iter().filter_map(|&o| d.outs[o as usize].net).collect();
            v.sort_unstable();
            v.dedup();
            v
        };
        for round in 0.. {
            for &o in g {
                w.output(o);
            }
            let mut changed = false;
            for &n in &nets {
                let nw = w.net_wave(n);
                if !nw.same(&w.net[n as usize]) {
                    changed = true;
                }
                w.net[n as usize] = nw;
            }
            if !d.looped[gi] || !changed {
                break;
            }
            if round > 64 {
                let names: Vec<&str> = nets.iter().map(|&n| d.nets[n as usize].as_str()).collect();
                w.notes.push(format!(
                    "a loop whose waves don't settle: {}",
                    names.join(", ")
                ));
                w.unsettled.extend(&nets);
                break;
            }
        }
    }
    Ok(w)
}
