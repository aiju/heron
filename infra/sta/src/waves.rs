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
use crate::logic::{
    V0, V1, X, Z, held0, held1, known, matters, merge, monotone, not, sop, support,
};
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

/// A transition's parts: itself, or several by reference edge.
pub enum Parts<'a> {
    One([Part; 1]),
    Many(&'a [Part]),
}

impl std::ops::Deref for Parts<'_> {
    type Target = [Part];
    fn deref(&self) -> &[Part] {
        match self {
            Parts::One(p) => p,
            Parts::Many(s) => s,
        }
    }
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

/// A change's window at an output: its earliest and latest times, the
/// arcs that set them, and the input's times they come from.
#[derive(Clone, Copy, Debug)]
struct Win {
    e: i64,
    l: i64,
    le: u32,
    ll: u32,
    ie: i64,
    il: i64,
}

impl Win {
    fn widen(self, o: Win) -> Win {
        let (e, le, ie) = if o.e < self.e {
            (o.e, o.le, o.ie)
        } else {
            (self.e, self.le, self.ie)
        };
        let (l, ll, il) = if o.l > self.l {
            (o.l, o.ll, o.il)
        } else {
            (self.l, self.ll, self.il)
        };
        Win {
            e,
            l,
            le,
            ll,
            ie,
            il,
        }
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
    win: [Option<Win>; 2],
    union: Win,
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
        let (effects, mut cur, own, func) = self.effects(chip, func, sets, key);
        let func = func.as_ref();
        let value = |f: Option<&crate::input::Sop>, vals: &[u8]| -> u8 {
            match f {
                Some(f) => sop(f, &|q| vals[q as usize]),
                None => X,
            }
        };
        let flip = |v: u8| if inv { not(v) } else { v };
        let init = flip(value(func, &cur));
        let mut out = Vec::new();
        let mut before = Vec::with_capacity(cur.len());
        let mut moving = vec![false; cur.len()];
        let mut distinct: Vec<(usize, usize)> = Vec::new();
        let mut moves: Vec<(u32, u8, u8)> = Vec::new();
        let mut by: Vec<(i32, Win, u32, u32)> = Vec::new();
        let mut i = 0;
        while i < effects.len() {
            let mut j = i + 1;
            let mut end = effects[i].union.l;
            while j < effects.len() && effects[j].union.e <= end {
                end = end.max(effects[j].union.l);
                j += 1;
            }
            let cluster = &effects[i..j];
            i = j;
            before.clear();
            before.extend_from_slice(&cur);
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
            moving.fill(false);
            distinct.clear();
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
                    let get = |q: u32| before[q as usize];
                    let mv = |q: u32| moving[q as usize];
                    if held1(fun, &get, &mv) || held0(fun, &get, &mv) {
                        continue;
                    }
                    if one && all_clean {
                        if known(rb) && known(ra) && rb != ra {
                            true
                        } else if rb == V0 && ra == V0 {
                            continue;
                        } else if rb == V1 && ra == V1 {
                            false
                        } else {
                            rb == V0 || ra == V0
                        }
                    } else if all_clean && distinct.len() == moves_of(cluster, &mut moves) {
                        // several inputs, each changing once, all one way
                        // through the function: one change at most
                        if !monotone(fun, &moves) {
                            false
                        } else if known(rb) && rb == ra {
                            continue;
                        } else {
                            true
                        }
                    } else {
                        false
                    }
                }
                None => one && all_clean,
            };
            // an enable's turn-on or turn-off times, else either
            let set = if sets.len() == 2 && ra == V1 && rb != V1 {
                Some(0)
            } else if sets.len() == 2 && ra == V0 && rb != V0 {
                Some(1)
            } else {
                None
            };
            // by reference edge: each edge's earliest and latest, a part
            // for each stretch its effects cover (between two, nothing it
            // launched changes the output)
            by.clear();
            for x in cluster {
                let w = set.and_then(|s| x.win[s]).unwrap_or(x.union);
                by.push((x.event, w, x.from.0, x.from.1));
            }
            by.sort_by_key(|b| (b.0, b.1.e));
            let mut m = 0;
            for k in 1..by.len() {
                let (event, w, _, fl) = by[k];
                let b = &mut by[m];
                if event == b.0 && w.e <= b.1.l {
                    if w.l > b.1.l {
                        (b.1.l, b.1.ll, b.1.il, b.3) = (w.l, w.ll, w.il, fl);
                    }
                } else {
                    m += 1;
                    by[m] = by[k];
                }
            }
            by.truncate(m + 1);
            let mut parts = Vec::with_capacity(by.len());
            for &(event, w, fe, fl) in &by {
                // the input's times as far as they reach the output
                let fe = clip(&mut self.nodes, fe, w.ie);
                let fl = clip(&mut self.nodes, fl, w.il);
                let ce = self.node(w.e, fe, key, w.le);
                let cl = self.node(w.l, fl, key, w.ll);
                parts.push(Part {
                    event,
                    e: w.e,
                    l: w.l,
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
        }
        Wave { init, tr: out }
    }

    /// The effects at an output of its inputs' changes, in time order;
    /// the inputs' values before the window; which inputs are the output's
    /// own net; and the function over the inputs' indices.
    #[allow(clippy::type_complexity)] // eval's working set
    fn effects(
        &self,
        chip: u32,
        func: Option<&crate::input::Sop>,
        sets: &[&[Arc]],
        key: u32,
    ) -> (Vec<Effect>, Vec<u8>, Vec<bool>, Option<crate::input::Sop>) {
        debug_assert!(sets.len() <= 2);
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
        let waves: Vec<&Wave> = pins.iter().map(|&p| self.pin_wave(chip, p)).collect();
        let idx = |p: u32| pins.binary_search(&p).ok();
        // the function over the pins' indices
        let lfunc: Option<crate::input::Sop> = func.map(|f| {
            f.iter()
                .map(|t| {
                    t.iter()
                        .map(|&(q, v)| (idx(q).unwrap_or(0) as u32, v))
                        .collect()
                })
                .collect()
        });
        let init = waves.iter().map(|w| w.init).collect();
        // inputs that don't change: no effects
        if waves.iter().all(|w| w.tr.is_empty()) {
            return (Vec::new(), init, Vec::new(), lfunc);
        }
        let f = self.fraction;
        let own_net = if key & STATE == 0 { Some(key) } else { None };
        let own: Vec<bool> = pins
            .iter()
            .map(|&p| {
                own_net.is_some_and(|n| self.d.chips[chip as usize].source(p) == Source::Net(n))
            })
            .collect();
        let func = lfunc.as_ref();
        // the stretches between the pins' transitions, and in each every
        // pin's value and whether it's changing
        let mut cuts: Vec<i64> = waves
            .iter()
            .flat_map(|w| w.tr.iter().flat_map(|t| [t.e, t.l + 1]))
            .collect();
        cuts.sort_unstable();
        cuts.dedup();
        let np = pins.len();
        let ns = cuts.len().saturating_sub(1);
        let mut sval = vec![X; ns * np];
        let mut sbusy = vec![false; ns * np];
        if func.is_some() {
            for (i, w) in waves.iter().enumerate() {
                let (mut k, mut v) = (0, w.init);
                for si in 0..ns {
                    let (a, b) = (cuts[si], cuts[si + 1]);
                    while k < w.tr.len() && w.tr[k].l < a {
                        v = w.tr[k].after;
                        k += 1;
                    }
                    let open = k < w.tr.len();
                    sbusy[si * np + i] = open && w.tr[k].e < b;
                    sval[si * np + i] = if open && w.tr[k].e < a { X } else { v };
                }
            }
        }
        let mut effects = Vec::with_capacity(cuts.len());
        let mut spans: Vec<(i64, i64)> = Vec::new();
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
                spans.clear();
                if let Some(fun) = func {
                    let first = cuts.binary_search(&tr.e).unwrap_or(0);
                    for si in first..ns {
                        let (a, b) = (cuts[si], cuts[si + 1]);
                        if a > tr.l {
                            break;
                        }
                        let row = si * np;
                        let get = |q: u32| sval[row + q as usize];
                        let mv = |q: u32| q as usize == pi || sbusy[row + q as usize];
                        if !held1(fun, &get, &mv) && matters(fun, pi as u32, &get, &mv) {
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
                    for part in self.parts_of(&tr).iter() {
                        let (pe, pl) = (part.e.max(ne), part.l.min(nl));
                        if pe > pl {
                            continue;
                        }
                        let mut win = [None; 2];
                        let mut any: Option<Win> = None;
                        for (s, slot) in sets.iter().zip(win.iter_mut()) {
                            let mut w: Option<Win> = None;
                            for a in s.iter().filter(|a| a.from.contains(&p)) {
                                let (mut pe, mut pl) = (pe, pl);
                                if let Some(cond) = &a.when {
                                    match cond_hull(&waves, &pins, cond, pe, pl) {
                                        Some((e, l)) => {
                                            pe = e;
                                            pl = l;
                                        }
                                        None => continue,
                                    }
                                }
                                let x = Win {
                                    e: pe + a.d.lo(f),
                                    l: pl + a.d.hi(),
                                    le: a.label,
                                    ll: a.label,
                                    ie: pe,
                                    il: pl,
                                };
                                w = Some(w.map_or(x, |w| w.widen(x)));
                            }
                            if let Some(x) = w {
                                any = Some(any.map_or(x, |u| u.widen(x)));
                            }
                            *slot = w;
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
        effects.sort_by_key(|x| (x.union.e, x.union.l));
        (effects, init, own, lfunc)
    }

    /// A transition's parts by reference edge: one, unless it has several.
    pub fn parts_of(&self, tr: &Tr) -> Parts<'_> {
        if tr.parts != NONE {
            return Parts::Many(&self.parts[tr.parts as usize]);
        }
        let event = if tr.cl == NONE {
            -1
        } else {
            self.nodes[tr.cl as usize].event
        };
        Parts::One([Part {
            event,
            e: tr.e,
            l: tr.l,
            ce: tr.ce,
            cl: tr.cl,
        }])
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
                if self.t.held[oi as usize].contains(&(ev as u32)) {
                    continue;
                }
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
        let nodes = &mut self.nodes;
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
                    None if e == V1 => steady_on += 1,
                    None => {}
                }
                if let Some(k) = vc
                    && e != V0
                {
                    contrib.push(vals[i].tr[k]);
                }
            }
            // the net changes as one lets go only if another is surely on
            // all the while; else when the other turns on (one that may be
            // on and took over would overlap the one letting go: a
            // handover's to check)
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
        nodes: &mut Vec<Node>,
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
                if pe <= pl {
                    by.push(Part { e: pe, l: pl, ..p });
                }
            }
        }
        // a stretch between a driver's parts: the driver's change, as a whole
        if by.is_empty() {
            let t = c[0];
            let event = if t.cl == NONE {
                -1
            } else {
                nodes[t.cl as usize].event
            };
            by.push(Part {
                event,
                e,
                l,
                ce: t.ce,
                cl: t.cl,
            });
        }
        // by reference edge, a part per stretch
        by.sort_by_key(|b| (b.event, b.e));
        let mut m = 0;
        for k in 1..by.len() {
            let p = by[k];
            let b = &mut by[m];
            if p.event == b.event && p.e <= b.l {
                if p.l > b.l {
                    b.l = p.l;
                    b.cl = p.cl;
                }
            } else {
                m += 1;
                by[m] = p;
            }
        }
        by.truncate(m + 1);
        // the drivers' times as far as they reach the bus
        for b in by.iter_mut() {
            b.ce = clip(nodes, b.ce, b.e);
            b.cl = clip(nodes, b.cl, b.l);
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

/// The inputs a cluster of effects moves, one entry per pin: how many.
fn moves_of(cluster: &[Effect], moves: &mut Vec<(u32, u8, u8)>) -> usize {
    moves.clear();
    for x in cluster {
        if !moves.iter().any(|m| m.0 == x.pin as u32) {
            moves.push((x.pin as u32, x.tr.before, x.tr.after));
        }
    }
    moves.len()
}

/// A node at time t, standing for n where a change's window is cut to the
/// part of it that reaches somewhere: n if that's its time.
fn clip(nodes: &mut Vec<Node>, n: u32, t: i64) -> u32 {
    if n == NONE || nodes[n as usize].t == t {
        return n;
    }
    let c = Node {
        t,
        ..nodes[n as usize]
    };
    nodes.push(c);
    (nodes.len() - 1) as u32
}

/// The earliest and latest times in [e, l] at which a condition over the
/// pins may be true (a pin changing then counted unknown), or None.
fn cond_hull(
    waves: &[&Wave],
    pins: &[u32],
    cond: &crate::input::Sop,
    e: i64,
    l: i64,
) -> Option<(i64, i64)> {
    let idx = |p: u32| pins.binary_search(&p).ok();
    let mut bp = vec![e, l + 1];
    for p in support(cond) {
        if let Some(i) = idx(p) {
            for t in &waves[i].tr {
                for x in [t.e, t.l + 1] {
                    if x > e && x <= l {
                        bp.push(x);
                    }
                }
            }
        }
    }
    bp.sort_unstable();
    bp.dedup();
    let mut hull: Option<(i64, i64)> = None;
    for w in bp.windows(2) {
        let (a, b) = (w[0], w[1]);
        let get = |q: u32| match idx(q) {
            Some(i) if waves[i].tr.iter().any(|t| t.e < b && t.l >= a) => X,
            Some(i) => waves[i].at(a),
            None => X,
        };
        if sop(cond, &get) != V0 {
            hull = Some(match hull {
                None => (a, b - 1),
                Some((s, _)) => (s, b - 1),
            });
        }
    }
    hull
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
