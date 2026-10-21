//! The checks (RFC 0048 9) on one branch's waves, and its results.
//!
//! A capture counts if its clock's edge goes back to a reference event in
//! (0, end]: the edge at 0 is the end of the cycle before, which that
//! case's window checks. A pulse or a strobe counts if it starts at an
//! event in [0, end).

use serde::Serialize;

use crate::design::{Arc, CheckKind, Delay, Design, Kind, Source};
use crate::input::{Case, Exception, Options};
use crate::logic::{V0, V1, X, depends_exact, matters};
use crate::values::Trace;
use crate::waves::{ENABLE, NONE, STATE, STROBE, Tr, Wave, Waves};

/// A step of a path: the time at a net (or a register's state), the arc
/// from the step before, and that arc's delay: its minimum and maximum
/// (the minimum from the fraction if `assumed`), and whether the side of
/// it the path takes rests on an estimate.
#[derive(Serialize, Clone, Debug)]
pub struct Step {
    pub t: i64,
    pub at: String,
    pub arc: String,
    pub min: Option<i64>,
    pub max: Option<i64>,
    pub assumed: bool,
    pub estimated: bool,
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
    /// The smallest fraction of typical (for the minimums the data hasn't)
    /// it passes with, by its early path's delays; None if it doesn't
    /// depend on one.
    pub min_fraction: Option<f64>,
    /// The values it rests on that the data marks as estimated: its limits'
    /// names, and its paths' arcs.
    pub estimated: Vec<String>,
    #[serde(skip)]
    pub node: u32,
    #[serde(skip)]
    pub other: u32,
    /// Which of node and other is the early time (the minimums').
    #[serde(skip)]
    pub early: u32,
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
    /// The checks (by Coverage::checks's index) this branch evaluated.
    pub evaluated: Vec<u32>,
    /// How many checks (or, for a false path, changes) each of the case's
    /// exceptions took.
    pub excepted: Vec<usize>,
    /// What the branch couldn't check because values it needs aren't known:
    /// drivers that may both be on, nets that may float.
    pub unresolved: Vec<String>,
    /// The captures of asynchronous nets at synchronisers (RFC 0048 9.7).
    pub crossings: Vec<Crossing>,
    /// The changes launched in the window still in flight past its end:
    /// (net, earliest, latest), ps from the end, for the next cycle's
    /// tails (RFC 0048 8).
    pub tails: Vec<(String, i64, i64)>,
    /// Where the branch came back to a state it had at this earlier rising
    /// edge, ending there.
    pub repeats: Option<u32>,
}

/// A synchroniser's capture of an asynchronous net: its source, and the
/// time its output has to settle before the next register's setup (the
/// tightest setup check whose path starts at the synchroniser).
#[derive(Serialize, Clone, Debug)]
pub struct Crossing {
    pub chip: String,
    pub pin: String,
    pub source: String,
    pub event: i32,
    pub settle: Option<i64>,
}

/// An overlap of two drivers: their chips, its start and end.
type Overlap = (u32, u32, i64, i64);
/// What the overlap found: its first net, how many nets, the slack, the
/// nodes (latest turn-off, earliest turn-on), the event.
type Handover = (u32, usize, i64, (u32, u32), i32);

/// A driver's enable in a stretch of time.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum En {
    Off,
    On,
    Maybe,
    Changing,
}

/// A wave's enable state in each stretch between `cuts`.
fn en_states(w: &Wave, cuts: &[i64]) -> Vec<En> {
    let (mut k, mut v) = (0, w.init);
    let mut out = Vec::with_capacity(cuts.len());
    for win in cuts.windows(2) {
        let (a, b) = (win[0], win[1]);
        while k < w.tr.len() && w.tr[k].l < a {
            v = w.tr[k].after;
            k += 1;
        }
        out.push(if k < w.tr.len() && w.tr[k].e < b {
            En::Changing
        } else {
            match v {
                V0 => En::Off,
                V1 => En::On,
                _ => En::Maybe,
            }
        });
    }
    out
}

pub type NetTrace = (String, u8, Vec<TrTrace>);
/// A transition: earliest, latest, before, after, clean, and its parts by
/// reference edge (event, earliest, latest).
pub type TrTrace = (i64, i64, u8, u8, bool, Vec<(i32, i64, i64)>);

/// A side's worst so far: its slack, and the nodes (path, against, early).
type Worst = (i64, (u32, u32, u32));

struct Ctx<'a, 'b> {
    d: &'a Design,
    t: &'a Trace,
    w: &'b Waves<'a>,
    out: Vec<CheckOut>,
    /// The limits of the check being evaluated that are estimated.
    est: Vec<String>,
    case: &'a Case,
    /// The case's false paths: (exception, net).
    through: Vec<(usize, u32)>,
    excepted: Vec<usize>,
    unresolved: Vec<(String, String, Vec<String>)>,
    /// Captures at synchronisers: (chip, pin, source, event).
    crossings: Vec<(u32, u32, u32, i32)>,
    /// Options::cppr_across_edges.
    across: bool,
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

    /// How far two paths share their nets from their reference edges: 0
    /// if they don't start at reference edges.
    fn shared(&self, a: &[u32], b: &[u32]) -> usize {
        let nodes = &self.w.nodes;
        let (Some(&a0), Some(&b0)) = (a.first(), b.first()) else {
            return 0;
        };
        let (ra, rb) = (nodes[a0 as usize], nodes[b0 as usize]);
        if ra.parent != NONE || rb.parent != NONE || ra.event < 0 || rb.event < 0 {
            return 0;
        }
        let mut k = 0;
        while k < a.len() && k < b.len() && nodes[a[k] as usize].key == nodes[b[k] as usize].key {
            k += 1;
        }
        k
    }

    /// Common path pessimism's credit between a late time (at node `late`)
    /// and an early one (`early`): where both paths go through the same
    /// nets from their reference edges, the last shared net's spread.
    fn credit(&self, late: u32, early: u32) -> i64 {
        if late == NONE || early == NONE {
            return 0;
        }
        let (a, b) = (self.chain(late), self.chain(early));
        let k = self.shared(&a, &b);
        if k == 0 {
            return 0;
        }
        let nodes = &self.w.nodes;
        let (ra, rb) = (nodes[a[0] as usize], nodes[b[0] as usize]);
        let (x, y) = (nodes[a[k - 1] as usize], nodes[b[k - 1] as usize]);
        if ra.event == rb.event {
            // one edge: its own jitter is common too
            (x.t - y.t).max(0)
        } else if self.across {
            ((x.t - ra.t) - (y.t - rb.t)).max(0)
        } else {
            0
        }
    }

    /// The smallest fraction a check passes with: its slack moves with the
    /// fraction by the typical delays of its early path's assumed
    /// minimums, past what it shares with the late path.
    fn min_fraction(&self, c: &CheckOut) -> Option<f64> {
        if c.early == NONE {
            return None;
        }
        let late = if c.early == c.node { c.other } else { c.node };
        let e = self.chain(c.early);
        let k = if late == NONE {
            0
        } else {
            self.shared(&self.chain(late), &e)
        };
        let per: i64 = e[k..]
            .iter()
            .filter_map(|&n| self.delay_of(n))
            .filter(|d| d.min.is_none())
            .map(|d| d.typ)
            .sum();
        if per == 0 {
            return None;
        }
        Some((self.w.fraction - c.slack as f64 / per as f64).max(0.0))
    }

    fn delay_of(&self, n: u32) -> Option<Delay> {
        let x = self.w.nodes[n as usize];
        if x.label == NONE {
            return None;
        }
        self.d.label_delays.get(x.label as usize).copied().flatten()
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
        early: u32,
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
            min_fraction: None,
            estimated: self.est.clone(),
            node,
            other,
            early,
        });
    }

    /// Whether an exception's chip, check, pin and values match.
    fn matches(&self, x: &Exception, chip: &str, check: &str, what: &str, ev: i32) -> bool {
        x.chip.as_ref().is_none_or(|c| c == chip)
            && x.check.as_ref().is_none_or(|c| c == check)
            && x.pin.as_ref().is_none_or(|p| {
                what.strip_prefix(p.as_str())
                    .is_some_and(|r| r.is_empty() || r.starts_with(' '))
            })
            && (x.when.is_empty()
                || ev >= 0
                    && (ev as usize) < self.t.pre.len()
                    && x.when.iter().all(|(n, &v)| {
                        self.d
                            .net_index
                            .get(n)
                            .is_some_and(|&i| self.t.pre[ev as usize][i as usize] == v)
                    }))
    }

    /// The false path that leaves out a change at a check, if one does: its
    /// path (to `node`) goes through the exception's net.
    fn false_path(&self, chip: u32, check: &str, what: &str, ev: i32, node: u32) -> Option<usize> {
        if self.through.is_empty() {
            return None;
        }
        let r = &self.d.chips[chip as usize].reference;
        let chain = self.chain(node);
        self.through.iter().find_map(|&(i, net)| {
            (self.matches(&self.case.exceptions[i], r, check, what, ev)
                && chain.iter().any(|&n| self.w.nodes[n as usize].key == net))
            .then_some(i)
        })
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
                let pname = self.pin_name(chip, p);
                // an asynchronous net: a crossing, which a synchroniser
                // (nocheck) takes; its timing isn't the window's (the
                // synchroniser's other inputs are checked as any)
                if let Some(tw) = dw.asynch
                    && tw.meets(tr.e - setup, tr.l + hold)
                {
                    self.crossing(chip, p, tw.src, tr.e, ev);
                    continue;
                }
                self.float(chip, p, tr.e - setup, tr.l + hold, tr.e, ev, tr.cl);
                // the worst change on each side, each its own check (a
                // failing hold mustn't hide a failing setup)
                let mut worst: [Option<Worst>; 2] = [None, None];
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
                            (0, s, (part.cl, tr.ce, tr.ce))
                        } else {
                            (1, h, (part.ce, tr.cl, part.ce))
                        };
                        let kind = if side == 0 { "setup" } else { "hold" };
                        if let Some(x) = self.false_path(chip, kind, &pname, ev, node.0) {
                            self.excepted[x] += 1;
                            continue;
                        }
                        if worst[side].is_none_or(|w| slack < w.0) {
                            worst[side] = Some((slack, node));
                        }
                    }
                }
                for (side, kind) in [(0, "setup"), (1, "hold")] {
                    if let Some((slack, (n, o, early))) = worst[side] {
                        let what = format!(
                            "{pname} ({})",
                            names.get(side).map(|s| s.as_str()).unwrap_or(kind)
                        );
                        self.push(chip, kind, what, slack, tr.e, ev, (n, o), early);
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
            self.push(chip, "width", what, slack, a.l, ev, (b.ce, a.cl), b.ce);
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
            self.push(chip, "period", what, slack, a.l, ev, (b.ce, a.cl), b.ce);
        }
    }

    /// A clear's or preset's release against the clock's edges, and its
    /// pulses' width.
    #[allow(clippy::too_many_arguments)] // the check's fields
    fn recovery(
        &mut self,
        chip: u32,
        clock: u32,
        rise: bool,
        recovery: Option<i64>,
        removal: Option<i64>,
        width: Option<i64>,
        names: &[String],
    ) {
        let d = self.d;
        let c = &d.chips[chip as usize];
        let cw = self.w.pin_wave(chip, clock).clone();
        let (from, to) = if rise { (V0, V1) } else { (V1, V0) };
        let name = |i: usize, dflt: &str| names.get(i).cloned().unwrap_or_else(|| dflt.into());
        let mut seen: Vec<(i64, i64)> = Vec::new();
        for &o in &c.outs {
            if !matches!(&d.outs[o as usize].kind, Kind::Reg { clock: k, .. } if *k == clock) {
                continue;
            }
            for fw in &self.w.forces[o as usize] {
                // one check for the registers that share a force
                let sig = fw.tr.first().map_or((0, 0), |t| (t.e, t.l));
                if fw.tr.is_empty() || seen.contains(&sig) {
                    continue;
                }
                seen.push(sig);
                let what = |n: String| format!("{} {n}", d.out_name(o));
                // its pulses
                if let Some(min) = width {
                    for k in 0..fw.tr.len().saturating_sub(1) {
                        let (a, b) = (fw.tr[k], fw.tr[k + 1]);
                        let ev = self.event(a.cl);
                        if a.after == V1 && b.before == V1 && b.after != V1 && self.counts_start(ev)
                        {
                            let slack = b.e - a.l + self.credit(a.cl, b.ce) - min;
                            let w = what(format!("force width ({})", name(2, "width")));
                            self.push(chip, "width", w, slack, a.l, ev, (b.ce, a.cl), b.ce);
                        }
                    }
                }
                // its releases against the edges
                let releases: Vec<Tr> = fw.tr.iter().filter(|t| t.after != V1).copied().collect();
                for tr in &cw.tr {
                    let possible = !tr.clean
                        || (tr.before != tr.after || tr.before == X)
                            && (tr.before == from || tr.before == X)
                            && (tr.after == to || tr.after == X);
                    let ev = self.event(tr.cl);
                    if !possible || !self.counts_capture(ev) {
                        continue;
                    }
                    let mut worst: [Option<Worst>; 2] = [None, None];
                    for r in &releases {
                        let s = tr.e - recovery.unwrap_or(0) - r.l + self.credit(r.cl, tr.ce);
                        let h = r.e - (tr.l + removal.unwrap_or(0)) + self.credit(tr.cl, r.ce);
                        let (side, slack, n) = if s >= h {
                            (0, s, (r.cl, tr.ce, tr.ce))
                        } else {
                            (1, h, (r.ce, tr.cl, r.ce))
                        };
                        if worst[side].is_none_or(|w| slack < w.0) {
                            worst[side] = Some((slack, n));
                        }
                    }
                    for (side, lim, kind) in [(0, recovery, "recovery"), (1, removal, "removal")] {
                        if let (Some((slack, (n, ot, e))), Some(_)) = (worst[side], lim) {
                            let w = what(format!("release ({})", name(side, kind)));
                            self.push(chip, kind, w, slack, tr.e, ev, (n, ot), e);
                        }
                    }
                }
            }
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
                    NONE,
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
                    b.ce,
                );
            }
            for s in stable {
                for &p in &s.pins {
                    let pw = self.w.pin_wave(chip, p);
                    let mut worst: Option<(i64, &str, (u32, u32), u32)> = None;
                    for t in &pw.tr {
                        let mut before = a.e - s.start.unwrap_or(0) - t.l;
                        if let Some(end) = s.end {
                            before = before.min(b.e - end - t.l);
                        }
                        let after = t.e - (b.l + s.after.unwrap_or(0));
                        // the side after the strobe's end is a hold
                        let w = if before >= after {
                            (before, "strobe", (t.cl, a.ce), a.ce)
                        } else {
                            (after, "hold", (t.ce, b.cl), t.ce)
                        };
                        if worst.is_none_or(|x| w.0 < x.0) {
                            worst = Some(w);
                        }
                    }
                    if let Some((slack, kind, node, early)) = worst {
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
                        self.push(chip, kind, what, slack, b.e, ev, node, early);
                    }
                }
            }
            for s in data {
                for &p in &s.pins {
                    let (su, h) = (s.setup.unwrap_or(0), s.hold.unwrap_or(0));
                    self.float(chip, p, b.e - su, b.l + h, b.e, ev, b.cl);
                    let pw = self.w.pin_wave(chip, p);
                    let mut worst: Option<(i64, &str, (u32, u32), u32)> = None;
                    for t in &pw.tr {
                        let su = b.e - s.setup.unwrap_or(0) - t.l;
                        let h = t.e - (b.l + s.hold.unwrap_or(0));
                        let w = if su >= h {
                            (su, "strobe", (t.cl, b.ce), b.ce)
                        } else {
                            (h, "hold", (t.ce, b.cl), t.ce)
                        };
                        if worst.is_none_or(|x| w.0 < x.0) {
                            worst = Some(w);
                        }
                    }
                    if let Some((slack, kind, node, early)) = worst {
                        let what = format!(
                            "{eq}: {} data ({})",
                            self.pin_name(chip, p),
                            s.names.join(", ")
                        );
                        self.push(chip, kind, what, slack, b.e, ev, node, early);
                    }
                }
            }
        }
    }

    /// A capture of a net that depends on an asynchronous source: at a
    /// synchroniser, noted for the report; else a failing check.
    fn crossing(&mut self, chip: u32, p: u32, src: u32, at: i64, ev: i32) {
        let d = self.d;
        let source = d.out_name(src);
        if d.chips[chip as usize].nocheck {
            if !self.crossings.iter().any(|x| (x.0, x.1) == (chip, p)) {
                self.crossings.push((chip, p, src, ev));
            }
        } else {
            let what = format!(
                "{} (from {source}, not at a synchroniser)",
                self.pin_name(chip, p)
            );
            self.push(chip, "crossing", what, -1, at, ev, (NONE, NONE), NONE);
        }
    }

    /// Whether a net may be undriven in [a, b] (and not pulled up): None if
    /// some driver is surely on throughout; else whether that's only for
    /// lack of values (a driver that may be on, its enable not known, and
    /// none changing), and for how long no driver surely is.
    fn floating(&self, net: u32, a: i64, b: i64) -> Option<(bool, i64)> {
        let d = self.d;
        let ni = net as usize;
        if d.pulled[ni] || d.rail[ni].is_some() || self.t.constant[ni].is_some() {
            return None;
        }
        let drv = &d.drivers[ni];
        if drv.iter().any(|&o| d.outs[o as usize].enable.is_none()) {
            return None;
        }
        let ens: Vec<&Wave> = drv.iter().map(|&o| &self.w.en[o as usize]).collect();
        let mut cuts = vec![a, b + 1];
        for w in &ens {
            for t in &w.tr {
                for x in [t.e, t.l + 1] {
                    if x > a && x <= b {
                        cuts.push(x);
                    }
                }
            }
        }
        cuts.sort_unstable();
        cuts.dedup();
        let st: Vec<Vec<En>> = ens.iter().map(|w| en_states(w, &cuts)).collect();
        // stretches where none is surely on: for lack of values if one may
        // be (stably), else for timing (drivers turning on or off)
        let (mut bare, mut timed) = (0, false);
        for (si, win) in cuts.windows(2).enumerate() {
            if st.iter().any(|s| s[si] == En::On) {
                continue;
            }
            bare += win[1] - win[0];
            if !st.iter().any(|s| s[si] == En::Maybe) {
                timed = true;
            }
        }
        (bare > 0).then_some((!timed, bare))
    }

    /// A sampled or strobed pin on a net no driver may surely hold, in
    /// [a, b] about an edge whose earliest is `e0`: before it a float
    /// (late data, which a length can fix), from it a hold.
    #[allow(clippy::too_many_arguments)] // the check's fields
    fn float(&mut self, chip: u32, p: u32, a: i64, b: i64, e0: i64, ev: i32, node: u32) {
        let Source::Net(n) = self.d.chips[chip as usize].source(p) else {
            return;
        };
        for (lo, hi, kind) in [(a, e0 - 1, "float"), (e0.max(a), b, "hold")] {
            if lo > hi {
                continue;
            }
            if let Some((unknown, bare)) = self.floating(n, lo, hi) {
                let pin = self.pin_name(chip, p);
                if unknown {
                    let c = self.d.chips[chip as usize].reference.clone();
                    self.note_unresolved(c, "may float: its drivers' enables aren't known", pin);
                } else {
                    let what = format!("{pin} (no driver surely on)");
                    self.push(chip, kind, what, -bare, e0, ev, (node, NONE), NONE);
                }
            }
        }
    }

    /// Every net more than one output drives: two drivers that may be on
    /// at once overlap by no more than the tolerance (RFC 0048 9.6).
    fn handovers(&mut self, tolerance: i64) {
        let d = self.d;
        let end_t = crate::waves::event_time(self.t.end, self.t.period);
        // by the two chips and the overlap: (net, nets, slack, nodes, event)
        let mut found: Vec<(Overlap, Handover)> = Vec::new();
        let mut unknown: Vec<(u32, u32, u32, i64)> = Vec::new();
        for (n, drv) in d.drivers.iter().enumerate() {
            if drv.len() < 2 || d.rail[n].is_some() || self.t.constant[n].is_some() {
                continue;
            }
            let ens: Vec<&Wave> = drv.iter().map(|&o| &self.w.en[o as usize]).collect();
            let mut cuts = vec![0, end_t];
            for w in &ens {
                for t in &w.tr {
                    for x in [t.e, t.l + 1] {
                        if x > 0 && x < end_t {
                            cuts.push(x);
                        }
                    }
                }
            }
            cuts.sort_unstable();
            cuts.dedup();
            let st: Vec<Vec<En>> = ens.iter().map(|w| en_states(w, &cuts)).collect();
            for i in 0..drv.len() {
                for j in i + 1..drv.len() {
                    let (oi, oj) = (drv[i] as usize, drv[j] as usize);
                    let (ci, cj) = (d.outs[oi].chip, d.outs[oj].chip);
                    let mut si = 0;
                    while si < cuts.len() - 1 {
                        if st[i][si] == En::Off || st[j][si] == En::Off {
                            si += 1;
                            continue;
                        }
                        // a run in which both may be on
                        let start = si;
                        let mut vague = false;
                        while si < cuts.len() - 1 && st[i][si] != En::Off && st[j][si] != En::Off {
                            let (a, b) = (st[i][si], st[j][si]);
                            if (a == En::Maybe || b == En::Maybe)
                                && a != En::Changing
                                && b != En::Changing
                            {
                                vague = true;
                            }
                            si += 1;
                        }
                        let (ra, rb) = (cuts[start], cuts[si] - 1);
                        let key = (ci.min(cj), ci.max(cj), ra, rb);
                        if vague {
                            if !unknown
                                .iter()
                                .any(|u| (u.0, u.1, u.2) == (key.0, key.1, n as u32))
                            {
                                unknown.push((key.0, key.1, n as u32, ra));
                            }
                            continue;
                        }
                        // the run's end is a driver's latest turn-off, its
                        // start the other's earliest turn-on
                        let late = ens[i]
                            .tr
                            .iter()
                            .chain(&ens[j].tr)
                            .find(|t| t.l == rb)
                            .map_or(NONE, |t| t.cl);
                        let early = ens[i]
                            .tr
                            .iter()
                            .chain(&ens[j].tr)
                            .find(|t| t.e == ra)
                            .map_or(NONE, |t| t.ce);
                        let slack = tolerance - (rb - ra + 1) + self.credit(late, early);
                        let ev = self.event(late);
                        match found.iter_mut().find(|f| f.0 == key) {
                            Some(f) => f.1.1 += 1,
                            None => found.push((key, (n as u32, 1, slack, (late, early), ev))),
                        }
                    }
                }
            }
        }
        for ((ci, cj, ra, _), (n, count, slack, nodes, ev)) in found {
            let (a, b) = (
                &d.chips[ci as usize].reference,
                &d.chips[cj as usize].reference,
            );
            let more = if count > 1 {
                format!(" and {} more", count - 1)
            } else {
                String::new()
            };
            let what = format!("{a} and {b} on {}{more}", d.nets[n as usize]);
            self.push(ci, "handover", what, slack, ra, ev, nodes, nodes.1);
        }
        for (ci, cj, n, ra) in unknown {
            let (a, b) = (
                &d.chips[ci as usize].reference,
                &d.chips[cj as usize].reference,
            );
            let why = if ra == 0 {
                "may both drive at the window's start: the cycle before isn't known".to_string()
            } else {
                format!(
                    "may both drive from {:.1} ns: their enables aren't known",
                    ra as f64 / 1000.0
                )
            };
            self.note_unresolved(format!("{a} and {b}"), &why, d.nets[n as usize].clone());
        }
    }

    /// Something the branch can't check for lack of values, grouped by who
    /// and why, its pins or nets listed together.
    fn note_unresolved(&mut self, who: String, why: &str, at: String) {
        match self
            .unresolved
            .iter_mut()
            .find(|u| u.0 == who && u.1 == why)
        {
            Some(u) => {
                if !u.2.contains(&at) {
                    u.2.push(at);
                }
            }
            None => self.unresolved.push((who, why.to_string(), vec![at])),
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
                    self.push(ci as u32, "glitch", what, -1, at, ev, (node, NONE), NONE);
                }
            }
        }
    }

    /// A node's path, `early` if it's the minimums'.
    fn path(&self, n: u32, early: bool) -> Vec<Step> {
        let d = self.d;
        let nodes = &self.w.nodes;
        let f = self.w.fraction;
        self.chain(n)
            .into_iter()
            .map(|i| {
                let x = nodes[i as usize];
                let at = if x.key & STATE != 0 && x.key & STROBE != 0 {
                    "(a strobe)".to_string()
                } else if x.key & STATE != 0 && x.key & ENABLE != 0 {
                    format!("{} (enable)", d.out_name(x.key & !(STATE | ENABLE)))
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
                let dl = self.delay_of(i);
                Step {
                    t: x.t,
                    at,
                    arc,
                    min: dl.map(|d| d.lo(f)),
                    max: dl.map(|d| d.hi()),
                    assumed: dl.is_some_and(|d| d.min.is_none()),
                    estimated: dl.is_some_and(|d| if early { d.lo_estimated() } else { d.est }),
                }
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
                    STATE | STROBE | k as u32,
                ))
            }
            _ => None,
        })
        .collect();
    let through = case
        .exceptions
        .iter()
        .enumerate()
        .filter_map(|(i, x)| {
            x.through
                .as_ref()
                .and_then(|n| d.net_index.get(n))
                .map(|&n| (i, n))
        })
        .collect();
    let mut cx = Ctx {
        d,
        t,
        w: &*w,
        out: Vec::new(),
        est: Vec::new(),
        case,
        through,
        excepted: vec![0; case.exceptions.len()],
        unresolved: Vec::new(),
        crossings: Vec::new(),
        across: o.cppr_across_edges,
    };
    let mut evaluated = Vec::new();
    for (k, ch) in d.checks.iter().enumerate() {
        cx.est = ch.estimated.clone();
        let before = cx.out.len();
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
            CheckKind::Recovery {
                clock,
                rise,
                recovery,
                removal,
                width,
            } => cx.recovery(
                ch.chip, *clock, *rise, *recovery, *removal, *width, &ch.names,
            ),
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
        if cx.out.len() > before {
            evaluated.push(k as u32);
        }
    }
    cx.est = Vec::new();
    cx.handovers(o.tolerance);
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
            min_fraction: None,
            estimated: Vec::new(),
            node: NONE,
            other: NONE,
            early: NONE,
        });
    }
    // each synchroniser's settle time: the tightest setup check whose path
    // goes through its outputs
    let mut crossings = Vec::new();
    for &(chip, p, src, ev) in &cx.crossings {
        let c = &d.chips[chip as usize];
        // the registers that capture the pin
        let keys: Vec<u32> = c
            .outs
            .iter()
            .filter(|&&o| match &d.outs[o as usize].kind {
                Kind::Reg { next, .. } => next.iter().flatten().any(|&(q, _)| q == p),
                _ => false,
            })
            .flat_map(|&o| [d.outs[o as usize].net.unwrap_or(NONE), STATE | o])
            .collect();
        let settle = cx
            .out
            .iter()
            .filter(|x| x.check == "setup" && x.node != NONE)
            .filter(|x| {
                cx.chain(x.node)
                    .iter()
                    .any(|&n| keys.contains(&cx.w.nodes[n as usize].key))
            })
            .map(|x| x.slack)
            .min();
        crossings.push(Crossing {
            chip: c.reference.clone(),
            pin: c.pins[p as usize].clone(),
            source: d.out_name(src),
            event: ev,
            settle,
        });
    }
    let mut all = std::mem::take(&mut cx.out);
    let before = all.len();
    all.retain(|c| !case.skip.contains(&c.chip));
    let skipped = before - all.len();
    // the exceptions that turn checks off (a false path has had its say)
    all.retain(|c| {
        let hit = case.exceptions.iter().position(|x| {
            x.through.is_none() && cx.matches(x, &c.chip, &c.check, &c.what, c.event)
        });
        if let Some(i) = hit {
            cx.excepted[i] += 1;
        }
        hit.is_none()
    });
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
        c.min_fraction = cx.min_fraction(c);
        if i < o.paths && c.path.is_empty() && c.node != NONE {
            c.path = cx.path(c.node, c.early == c.node);
            if c.other != NONE {
                c.against = cx.path(c.other, c.early == c.other);
            }
            for s in c.path.iter().chain(&c.against) {
                if s.estimated && !c.estimated.contains(&s.arc) {
                    c.estimated.push(s.arc.clone());
                }
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
        evaluated,
        excepted: cx.excepted,
        unresolved: cx
            .unresolved
            .into_iter()
            .map(|(who, why, at)| format!("{who} {}: {why}", at.join(" ")))
            .collect(),
        crossings,
        tails: tails(d, t, w),
        repeats: t.repeat,
    }
}

/// Each net's changes launched before the window's end and still in
/// flight past it: their earliest and latest, from the end.
fn tails(d: &Design, t: &Trace, w: &Waves) -> Vec<(String, i64, i64)> {
    let end = crate::waves::event_time(t.end, t.period);
    let mut out = Vec::new();
    for (n, wv) in w.net.iter().enumerate() {
        let mut span: Option<(i64, i64)> = None;
        for tr in &wv.tr {
            if tr.l <= end {
                continue;
            }
            for p in w.parts_of(tr).iter() {
                if p.event >= 0 && (p.event as u32) < t.end && p.l > end {
                    span = Some(match span {
                        None => (p.e, p.l),
                        Some((a, b)) => (a.min(p.e), b.max(p.l)),
                    });
                }
            }
        }
        if let Some((a, b)) = span {
            out.push((d.nets[n].clone(), a - end, b - end));
        }
    }
    out
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
