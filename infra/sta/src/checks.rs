//! The checks (RFC 0048 9) on one branch's waves, and its results.
//!
//! A capture counts if its clock's edge goes back to a reference event in
//! (0, end]: the edge at 0 is the end of the cycle before, which that
//! case's window checks. A pulse or a strobe counts if it starts at an
//! event in [0, end).

use serde::Serialize;

use crate::design::{Arc, CheckKind, Delay, Design, Kind, Source};
use crate::input::{Case, Options};
use crate::logic::{V0, V1, X, depends_exact, matters};
use crate::values::Trace;
use crate::waves::{NONE, STATE, Tr, Wave, Waves};

#[derive(Serialize, Clone, Debug)]
pub struct Step {
    pub t: i64,
    pub at: String,
    pub arc: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct CheckOut {
    pub chip: String,
    /// setup, hold, width, period, strobe, glitch
    pub check: String,
    /// The pin or pins checked, and the requirement's name.
    pub what: String,
    pub slack: i64,
    /// When: the clock edge's or the strobe's end's earliest time.
    pub at: i64,
    pub event: i32,
    /// The data's path (or the change's), and the clock's or the strobe's
    /// it's checked against.
    pub path: Vec<Step>,
    pub against: Vec<Step>,
    #[serde(skip)]
    pub node: u32,
    #[serde(skip)]
    pub other: u32,
}

#[derive(Serialize, Clone, Debug)]
pub struct BranchOut {
    pub label: String,
    /// The branch's choices: (register's net, event, value).
    pub choices: Vec<(String, u32, u8)>,
    pub end: u32,
    pub end_time: i64,
    pub checks: usize,
    /// Checks on the chips the case skips, not counted.
    pub skipped: usize,
    pub failing: usize,
    pub marginal: usize,
    pub min_slack: Option<i64>,
    /// The failing checks, then the marginal ones, then the worst, worst
    /// first.
    pub worst: Vec<CheckOut>,
    pub notes: Vec<String>,
    /// The waves of the nets the options name: (net, value before the
    /// window, its transitions).
    pub traces: Vec<NetTrace>,
}

pub type NetTrace = (String, u8, Vec<TrTrace>);
/// A transition: earliest, latest, before, after, clean, and its parts by
/// reference edge (event, earliest, latest).
pub type TrTrace = (i64, i64, u8, u8, bool, Vec<(i32, i64, i64)>);

struct Ctx<'a, 'b> {
    d: &'a Design,
    t: &'a Trace,
    w: &'b Waves<'a>,
    out: Vec<CheckOut>,
}

impl Ctx<'_, '_> {
    fn event(&self, n: u32) -> i32 {
        if n == NONE {
            -1
        } else {
            self.w.nodes[n as usize].event
        }
    }

    /// The path to a node from its reference edge, nodes first to last.
    fn chain(&self, mut n: u32) -> Vec<u32> {
        let mut out = Vec::new();
        while n != NONE {
            out.push(n);
            n = self.w.nodes[n as usize].parent;
        }
        out.reverse();
        out
    }

    /// Common path pessimism's credit between a late time (at node `late`)
    /// and an early one (`early`): where both paths go through the same
    /// nets from their reference edges, the last shared net's spread.
    fn credit(&self, late: u32, early: u32) -> i64 {
        if late == NONE || early == NONE {
            return 0;
        }
        let (a, b) = (self.chain(late), self.chain(early));
        let nodes = &self.w.nodes;
        let mut k = 0;
        while k < a.len() && k < b.len() && nodes[a[k] as usize].key == nodes[b[k] as usize].key {
            k += 1;
        }
        if k == 0 {
            return 0;
        }
        let (ra, rb) = (nodes[a[0] as usize], nodes[b[0] as usize]);
        if ra.parent != NONE || rb.parent != NONE || ra.event < 0 || rb.event < 0 {
            return 0;
        }
        let (x, y) = (nodes[a[k - 1] as usize], nodes[b[k - 1] as usize]);
        ((x.t - ra.t) - (y.t - rb.t)).max(0)
    }

    #[allow(clippy::too_many_arguments)] // a result's fields
    fn push(
        &mut self,
        chip: u32,
        check: &str,
        what: String,
        slack: i64,
        at: i64,
        event: i32,
        (node, other): (u32, u32),
    ) {
        self.out.push(CheckOut {
            chip: self.d.chips[chip as usize].reference.clone(),
            check: check.into(),
            what,
            slack,
            at,
            event,
            path: Vec::new(),
            against: Vec::new(),
            node,
            other,
        });
    }

    fn pin_name(&self, chip: u32, p: u32) -> String {
        self.d.chips[chip as usize].pins[p as usize].clone()
    }

    fn counts_capture(&self, ev: i32) -> bool {
        ev > 0 && ev <= self.t.end as i32
    }

    fn counts_start(&self, ev: i32) -> bool {
        ev >= 0 && ev < self.t.end as i32
    }

    #[allow(clippy::too_many_arguments)] // the check's fields
    fn setup(
        &mut self,
        chip: u32,
        pins: &[u32],
        clock: u32,
        rise: bool,
        setup: i64,
        hold: i64,
        names: &[String],
    ) {
        let d = self.d;
        let c = &d.chips[chip as usize];
        if c.nocheck {
            return;
        }
        let regs: Vec<&crate::input::Sop> = c
            .outs
            .iter()
            .filter_map(|&o| match &d.outs[o as usize].kind {
                Kind::Reg { clock: k, next, .. } if *k == clock => Some(next),
                _ => None,
            })
            .collect();
        let cw = self.w.pin_wave(chip, clock).clone();
        let (from, to) = if rise { (V0, V1) } else { (V1, V0) };
        for tr in &cw.tr {
            let possible = !tr.clean
                || (tr.before != tr.after || tr.before == X)
                    && (tr.before == from || tr.before == X)
                    && (tr.after == to || tr.after == X);
            let ev = self.event(tr.cl);
            if !possible || !self.counts_capture(ev) {
                continue;
            }
            let pre = &self.t.pre[ev as usize];
            let pre_state = &self.t.pre_state[ev as usize];
            let get = |p: u32| match c.source(p) {
                Source::Net(n) => pre[n as usize],
                Source::State(r) => pre_state[r as usize],
                Source::Open => X,
            };
            for &p in pins {
                let reads = regs
                    .iter()
                    .any(|f| f.iter().flatten().any(|&(q, _)| q == p));
                // (a pin no live term needs can't matter: the quick test first)
                let none = |_| false;
                if reads
                    && !regs
                        .iter()
                        .any(|f| matters(f, p, &get, &none) && depends_exact(f, p, &get, &none))
                {
                    continue;
                }
                let dw = self.w.pin_wave(chip, p);
                // the worst change on each side, each its own check (a
                // failing hold mustn't hide a failing setup)
                let mut worst: [Option<(i64, (u32, u32))>; 2] = [None, None];
                // a change before the edge is set up, one after it held;
                // one that overlaps the edge's window is late data if it
                // goes back to an earlier edge and may start before the
                // edge's earliest, else early data (it can't come before
                // the edge: a race with it)
                for dt in &dw.tr {
                    for part in self.w.parts_of(dt).iter() {
                        let s = tr.e - setup - part.l + self.credit(part.cl, tr.ce);
                        let h = part.e - (tr.l + hold) + self.credit(tr.cl, part.ce);
                        let setup_side = if s >= 0 || h >= 0 {
                            s >= h
                        } else {
                            part.event < ev && part.e < tr.e
                        };
                        let (side, slack, node) = if setup_side {
                            (0, s, (part.cl, tr.ce))
                        } else {
                            (1, h, (part.ce, tr.cl))
                        };
                        if worst[side].is_none_or(|w| slack < w.0) {
                            worst[side] = Some((slack, node));
                        }
                    }
                }
                for (side, kind) in [(0, "setup"), (1, "hold")] {
                    if let Some((slack, node)) = worst[side] {
                        let what = format!(
                            "{} ({})",
                            self.pin_name(chip, p),
                            names.get(side).map(|s| s.as_str()).unwrap_or(kind)
                        );
                        self.push(chip, kind, what, slack, tr.e, ev, node);
                    }
                }
            }
        }
    }

    fn width(&mut self, chip: u32, pin: u32, level: u8, min: i64, names: &[String]) {
        let w = self.w.pin_wave(chip, pin).clone();
        for k in 0..w.tr.len().saturating_sub(1) {
            let (a, b) = (w.tr[k], w.tr[k + 1]);
            if !(a.clean && b.clean && a.after == level && b.before == level && b.after != level) {
                continue;
            }
            let ev = self.event(a.cl);
            if !self.counts_start(ev) {
                continue;
            }
            let slack = b.e - a.l + self.credit(a.cl, b.ce) - min;
            let what = format!(
                "{} {} ({})",
                self.pin_name(chip, pin),
                if level == V1 { "high" } else { "low" },
                names.first().map(|s| s.as_str()).unwrap_or("width")
            );
            self.push(chip, "width", what, slack, a.l, ev, (b.ce, a.cl));
        }
    }

    fn period(&mut self, chip: u32, pin: u32, min: i64, names: &[String]) {
        let w = self.w.pin_wave(chip, pin).clone();
        let rises: Vec<Tr> =
            w.tr.iter()
                .filter(|t| t.clean && t.before == V0 && t.after == V1)
                .copied()
                .collect();
        for k in 0..rises.len().saturating_sub(1) {
            let (a, b) = (rises[k], rises[k + 1]);
            let ev = self.event(a.cl);
            if !self.counts_start(ev) {
                continue;
            }
            let slack = b.e - a.l + self.credit(a.cl, b.ce) - min;
            let what = format!(
                "{} ({})",
                self.pin_name(chip, pin),
                names.first().map(|s| s.as_str()).unwrap_or("period")
            );
            self.push(chip, "period", what, slack, a.l, ev, (b.ce, a.cl));
        }
    }

    fn strobe(
        &mut self,
        chip: u32,
        aw: &Wave,
        stable: &[crate::input::StableIn],
        data: &[crate::input::DataIn],
        width: Option<i64>,
        eq: &str,
    ) {
        let tr = &aw.tr;
        let mut k = 0;
        while k < tr.len() {
            let a = tr[k];
            if a.after == V0 {
                k += 1;
                continue;
            }
            // the strobe's end: the next transition to inactive
            let Some(m) = (k + 1..tr.len()).find(|&m| tr[m].after == V0) else {
                break;
            };
            let b = tr[m];
            let ev = self.event(a.cl);
            let glitchy = tr[k..=m].iter().any(|t| !t.clean);
            k = m + 1;
            if !self.counts_start(ev) {
                continue;
            }
            if glitchy {
                self.push(
                    chip,
                    "glitch",
                    format!("strobe {eq} may pulse"),
                    -1,
                    a.e,
                    ev,
                    (a.cl, NONE),
                );
            }
            if let Some(wd) = width {
                self.push(
                    chip,
                    "strobe",
                    format!("{eq} width"),
                    b.e - a.l - wd,
                    b.e,
                    ev,
                    (b.ce, a.cl),
                );
            }
            for s in stable {
                for &p in &s.pins {
                    let pw = self.w.pin_wave(chip, p);
                    let mut worst: Option<(i64, &str, (u32, u32))> = None;
                    for t in &pw.tr {
                        let mut before = a.e - s.start.unwrap_or(0) - t.l;
                        if let Some(end) = s.end {
                            before = before.min(b.e - end - t.l);
                        }
                        let after = t.e - (b.l + s.after.unwrap_or(0));
                        // the side after the strobe's end is a hold
                        let w = if before >= after {
                            (before, "strobe", (t.cl, a.ce))
                        } else {
                            (after, "hold", (t.ce, b.cl))
                        };
                        if worst.is_none_or(|x| w.0 < x.0) {
                            worst = Some(w);
                        }
                    }
                    if let Some((slack, kind, node)) = worst {
                        let what = format!(
                            "{eq}: {} stable ({})",
                            self.pin_name(chip, p),
                            s.names
                                .iter()
                                .filter(|n| n.as_str() != "None")
                                .cloned()
                                .collect::<Vec<_>>()
                                .join(", ")
                        );
                        self.push(chip, kind, what, slack, b.e, ev, node);
                    }
                }
            }
            for s in data {
                for &p in &s.pins {
                    let pw = self.w.pin_wave(chip, p);
                    let mut worst: Option<(i64, &str, (u32, u32))> = None;
                    for t in &pw.tr {
                        let su = b.e - s.setup.unwrap_or(0) - t.l;
                        let h = t.e - (b.l + s.hold.unwrap_or(0));
                        let w = if su >= h {
                            (su, "strobe", (t.cl, b.ce))
                        } else {
                            (h, "hold", (t.ce, b.cl))
                        };
                        if worst.is_none_or(|x| w.0 < x.0) {
                            worst = Some(w);
                        }
                    }
                    if let Some((slack, kind, node)) = worst {
                        let what = format!(
                            "{eq}: {} data ({})",
                            self.pin_name(chip, p),
                            s.names.join(", ")
                        );
                        self.push(chip, kind, what, slack, b.e, ev, node);
                    }
                }
            }
        }
    }

    /// Glitches on the pins that mustn't have them: clocks, clears and
    /// presets, the sensitive pins.
    fn glitches(&mut self) {
        let d = self.d;
        for (ci, c) in d.chips.iter().enumerate() {
            let mut pins: Vec<(u32, &str)> = Vec::new();
            for &o in &c.outs {
                if let Kind::Reg {
                    clock,
                    clear,
                    preset,
                    ..
                } = &d.outs[o as usize].kind
                {
                    pins.push((*clock, "clock"));
                    for f in [clear, preset].into_iter().flatten() {
                        for p in crate::logic::support(&f.f) {
                            pins.push((p, "clear or preset"));
                        }
                    }
                }
            }
            for &p in &c.sensitive {
                pins.push((p, "sensitive"));
            }
            pins.sort_unstable();
            pins.dedup_by_key(|x| x.0);
            for (p, why) in pins {
                let w = self.w.pin_wave(ci as u32, p);
                let bad: Vec<(i64, i32, u32)> =
                    w.tr.iter()
                        .filter(|t| !t.clean)
                        .map(|t| (t.e, self.event(t.cl), t.cl))
                        .filter(|x| self.counts_start(x.1))
                        .collect();
                for (at, ev, node) in bad {
                    let what = format!("{} ({why}) may glitch", self.pin_name(ci as u32, p));
                    self.push(ci as u32, "glitch", what, -1, at, ev, (node, NONE));
                }
            }
        }
    }

    fn path(&self, n: u32) -> Vec<Step> {
        let d = self.d;
        let nodes = &self.w.nodes;
        self.chain(n)
            .into_iter()
            .map(|i| {
                let x = nodes[i as usize];
                let at = if x.key & STATE != 0 && x.key & (1 << 30) != 0 {
                    "(a strobe)".to_string()
                } else if x.key & STATE != 0 {
                    format!("{} (state)", d.out_name(x.key & !STATE))
                } else {
                    d.nets.get(x.key as usize).cloned().unwrap_or_default()
                };
                let arc = if x.label == NONE {
                    if x.parent == NONE && x.event >= 0 {
                        format!("edge {}", x.event)
                    } else {
                        String::new()
                    }
                } else {
                    d.labels[x.label as usize].clone()
                };
                Step { t: x.t, at, arc }
            })
            .collect()
    }
}

/// Every check on one branch's waves.
pub fn run(d: &Design, t: &Trace, w: &mut Waves, o: &Options, case: &Case) -> BranchOut {
    // the strobes' active waves first: they add nodes to the waves
    let actives: Vec<Option<Wave>> = d
        .checks
        .iter()
        .enumerate()
        .map(|(k, ch)| match &ch.kind {
            CheckKind::Strobe { active, .. } => {
                let arcs = [Arc {
                    from: crate::logic::support(active),
                    d: Delay::zero(),
                    label: 0,
                    when: None,
                }];
                Some(w.eval(
                    ch.chip,
                    Some(active),
                    false,
                    &[&arcs],
                    STATE | (1 << 30) | k as u32,
                ))
            }
            _ => None,
        })
        .collect();
    let mut cx = Ctx {
        d,
        t,
        w: &*w,
        out: Vec::new(),
    };
    for (k, ch) in d.checks.iter().enumerate() {
        match &ch.kind {
            CheckKind::Setup {
                pins,
                clock,
                rise,
                setup,
                hold,
            } => cx.setup(ch.chip, pins, *clock, *rise, *setup, *hold, &ch.names),
            CheckKind::Width { pin, level, min } => {
                cx.width(ch.chip, *pin, *level, *min, &ch.names)
            }
            CheckKind::Period { pin, min } => cx.period(ch.chip, *pin, *min, &ch.names),
            CheckKind::Strobe {
                stable,
                data,
                width,
                eq,
                ..
            } => {
                if let Some(aw) = &actives[k] {
                    cx.strobe(ch.chip, aw, stable, data, *width, eq);
                }
            }
        }
    }
    cx.glitches();
    for &n in &w.unsettled {
        cx.out.push(CheckOut {
            chip: String::new(),
            check: "loop".into(),
            what: format!("{} doesn't settle", d.nets[n as usize]),
            slack: -1,
            at: 0,
            event: -1,
            path: Vec::new(),
            against: Vec::new(),
            node: NONE,
            other: NONE,
        });
    }
    let mut all = std::mem::take(&mut cx.out);
    let before = all.len();
    all.retain(|c| !case.skip.contains(&c.chip));
    let skipped = before - all.len();
    all.sort_by_key(|c| c.slack);
    let failing = all.iter().filter(|c| c.slack < 0).count();
    let marginal = all
        .iter()
        .filter(|c| c.slack >= 0 && c.slack < o.marginal)
        .count();
    let keep = (failing + marginal)
        .max(o.paths.max(1))
        .min(all.len())
        .min(200);
    let mut worst: Vec<CheckOut> = all[..keep].to_vec();
    for (i, c) in worst.iter_mut().enumerate() {
        if i < o.paths && c.path.is_empty() && c.node != NONE {
            c.path = cx.path(c.node);
            if c.other != NONE {
                c.against = cx.path(c.other);
            }
        }
    }
    BranchOut {
        label: case.label.clone(),
        choices: case.forced.clone(),
        end: t.end,
        end_time: crate::waves::event_time(t.end, t.period),
        checks: all.len(),
        skipped,
        failing,
        marginal,
        min_slack: all.first().map(|c| c.slack),
        worst,
        notes: w.notes.clone(),
        traces: traces(d, w, &o.trace),
    }
}

/// The waves the options trace: a net's, or "U_X.PIN" for an output's
/// value and "U_X.PIN/en" for its enable.
fn traces(d: &Design, w: &Waves, names: &[String]) -> Vec<NetTrace> {
    let one = |n: &str, wv: &Wave| -> NetTrace {
        let tr = wv
            .tr
            .iter()
            .map(|t| {
                let parts = w.parts_of(t).iter().map(|p| (p.event, p.e, p.l)).collect();
                (t.e, t.l, t.before, t.after, t.clean, parts)
            })
            .collect();
        (n.to_string(), wv.init, tr)
    };
    let mut out = Vec::new();
    for n in names {
        if let Some(&i) = d.net_index.get(n) {
            out.push(one(n, &w.net[i as usize]));
            continue;
        }
        let (name, en) = match n.strip_suffix("/en") {
            Some(x) => (x, true),
            None => (n.as_str(), false),
        };
        if let Some(oi) = (0..d.outs.len() as u32).find(|&o| d.out_name(o) == name) {
            let wv = if en {
                &w.en[oi as usize]
            } else {
                &w.val[oi as usize]
            };
            out.push(one(n, wv));
        }
    }
    out
}
