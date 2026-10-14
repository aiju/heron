//! The simulator: a DC operating point, then fixed BDF2 steps.
//!
//! Each element turns into conductances (the matrix) and currents (the
//! right-hand side). Capacitors and inductors carry their BDF2 history as
//! currents; a line end is its characteristic admittance and a current
//! from the far end's past. Lines therefore don't join the pieces of the
//! circuit they connect, and each piece is solved on its own: the linear
//! ones factorised once, the ones with tables or diodes by Newton's method
//! at every step.

// The numerics index several parallel arrays at once.
#![allow(clippy::needless_range_loop)]

use std::time::Instant;

use crate::pwl::Pwl;
use crate::sparse::Lu;
use crate::{Error, Netlist, Options, Output, Stats};

/// Conductance from every unknown node to ground.
const GMIN: f64 = 1e-12;
/// Inductors and lines at DC: 0.1 mΩ, at most tens of µV at bus currents,
/// and not so stiff that rounding hides convergence.
const R_SHORT: f64 = 1e-4;
/// kT/q at 27 °C, as SPICE.
const VT: f64 = 0.025865;
/// Newton iterations allowed for the DC operating point.
const DC_ITERATIONS: usize = 500;

/// A nonlinear element, by index, with the nodes it touches: [a, b, x, y]
/// (for a supply factor, [a, b, p, q]).
type Touch = (usize, [usize; 4]);
type Touches = Vec<Touch>;
/// Tables, their supply factors, and diodes.
type Nonlinear<'a> = (&'a [Touch], &'a [Touch], &'a [Touch]);

/// Where one entry of an element's stamp goes in a piece.
#[derive(Debug, Clone, Copy)]
enum Target {
    /// a slot of the matrix
    Slot(usize),
    /// row (local) times a known node's voltage, into the right-hand side
    Known(usize, usize),
    /// the row isn't in this piece (a known node)
    Skip,
}

#[derive(Debug, Clone)]
struct NonlinearRef {
    idx: usize,
    /// [row a, row b] × [column x, column y] (for a diode x = a, y = b)
    m: [[Target; 2]; 2],
    ra: Option<usize>,
    rb: Option<usize>,
}

/// One piece of the circuit: a set of unknown nodes solved together.
struct Piece {
    nodes: Vec<usize>,
    lu: Lu,
    base: Vec<f64>,
    known: Vec<(usize, usize, f64)>,
    tables: Vec<NonlinearRef>,
    /// the supply factors of tables that have one: rows a, b × columns p, q
    supplies: Vec<NonlinearRef>,
    diodes: Vec<NonlinearRef>,
    factored: bool,
    rhs0: Vec<f64>,
    rhs: Vec<f64>,
}

struct Ctx<'a> {
    loc: &'a [Option<(usize, usize)>],
}

impl Piece {
    /// A piece over `nodes`, with the static stamps `stamps` (row, column,
    /// conductance; only those whose row is in the piece are used) and the
    /// nonlinear elements whose rows are in it.
    fn new(
        id: usize,
        nodes: Vec<usize>,
        stamps: &[(usize, usize, f64)],
        (tables, supplies, diodes): Nonlinear,
        ctx: &Ctx,
    ) -> Piece {
        let local = |n: usize| match ctx.loc[n] {
            Some((p, l)) if p == id => Some(l),
            _ => None,
        };
        let mut entries: Vec<(usize, usize)> = (0..nodes.len()).map(|i| (i, i)).collect();
        for &(r, c, _) in stamps {
            if let (Some(i), Some(j)) = (local(r), local(c)) {
                entries.push((i, j));
            }
        }
        let mine = |list: &[(usize, [usize; 4])]| -> Vec<(usize, [usize; 4])> {
            list.iter()
                .filter(|(_, n)| local(n[0]).is_some() || local(n[1]).is_some())
                .copied()
                .collect()
        };
        let my_tables = mine(tables);
        let my_supplies = mine(supplies);
        let my_diodes = mine(diodes);
        for (_, n) in my_tables
            .iter()
            .chain(my_supplies.iter())
            .chain(my_diodes.iter())
        {
            for &r in &n[0..2] {
                for &c in &n[2..4] {
                    if let (Some(i), Some(j)) = (local(r), local(c)) {
                        entries.push((i, j));
                    }
                }
            }
        }
        let lu = Lu::new(nodes.len(), &entries);
        let mut base = vec![0.0; lu.len()];
        let mut known = Vec::new();
        for &(r, c, g) in stamps {
            let Some(i) = local(r) else { continue };
            match local(c) {
                Some(j) => base[lu.slot(i, j)] += g,
                None => {
                    if ctx.loc[c].is_none() {
                        known.push((i, c, g));
                    }
                }
            }
        }
        let refs = |list: &[(usize, [usize; 4])], lu: &Lu| -> Vec<NonlinearRef> {
            list.iter()
                .map(|&(idx, n)| {
                    let t = |r: usize, c: usize| match (local(r), local(c)) {
                        (None, _) => Target::Skip,
                        (Some(i), Some(j)) => Target::Slot(lu.slot(i, j)),
                        (Some(i), None) => Target::Known(i, c),
                    };
                    NonlinearRef {
                        idx,
                        m: [
                            [t(n[0], n[2]), t(n[0], n[3])],
                            [t(n[1], n[2]), t(n[1], n[3])],
                        ],
                        ra: local(n[0]),
                        rb: local(n[1]),
                    }
                })
                .collect()
        };
        let tables = refs(&my_tables, &lu);
        let supplies = refs(&my_supplies, &lu);
        let diodes = refs(&my_diodes, &lu);
        let n = nodes.len();
        Piece {
            nodes,
            lu,
            base,
            known,
            tables,
            supplies,
            diodes,
            factored: false,
            rhs0: vec![0.0; n],
            rhs: vec![0.0; n],
        }
    }

    fn linear(&self) -> bool {
        self.tables.is_empty() && self.supplies.is_empty() && self.diodes.is_empty()
    }

    /// The 2-norm of the KCL residual, A·v − rhs, of the assembled (not yet
    /// factorised) system.
    fn residual(&self, v: &[f64]) -> f64 {
        let mut r: Vec<f64> = self.rhs.iter().map(|x| -x).collect();
        for (s, &(i, j)) in self.lu.entries().iter().enumerate() {
            r[i] += self.lu.vals[s] * v[self.nodes[j]];
        }
        r.iter().map(|x| x * x).sum::<f64>().sqrt()
    }
}

/// Add conductance g between rows/columns a and b (a two-terminal stamp).
fn two(stamps: &mut Vec<(usize, usize, f64)>, a: usize, b: usize, g: f64) {
    stamps.push((a, a, g));
    stamps.push((b, b, g));
    stamps.push((a, b, -g));
    stamps.push((b, a, -g));
}

/// The inverse of a small dense matrix (Gauss–Jordan, partial pivoting).
fn invert(m: &[Vec<f64>]) -> Option<Vec<Vec<f64>>> {
    let n = m.len();
    let mut a: Vec<Vec<f64>> = m.to_vec();
    let mut inv: Vec<Vec<f64>> = (0..n)
        .map(|i| (0..n).map(|j| if i == j { 1.0 } else { 0.0 }).collect())
        .collect();
    for c in 0..n {
        let p = (c..n).max_by(|&i, &j| a[i][c].abs().total_cmp(&a[j][c].abs()))?;
        if a[p][c].abs() < 1e-300 {
            return None;
        }
        a.swap(c, p);
        inv.swap(c, p);
        let d = a[c][c];
        for j in 0..n {
            a[c][j] /= d;
            inv[c][j] /= d;
        }
        for r in 0..n {
            if r != c {
                let f = a[r][c];
                if f != 0.0 {
                    for j in 0..n {
                        a[r][j] -= f * a[c][j];
                        inv[r][j] -= f * inv[c][j];
                    }
                }
            }
        }
    }
    Some(inv)
}

fn matvec(m: &[Vec<f64>], x: &[f64], out: &mut [f64]) {
    for (o, row) in out.iter_mut().zip(m) {
        *o = row.iter().zip(x).map(|(a, b)| a * b).sum();
    }
}

/// Inductors that are coupled, solved together.
struct InductorGroup {
    members: Vec<usize>,
    /// (dt/1.5)·L⁻¹
    gamma: Vec<Vec<f64>>,
}

/// A line, ready to step.
struct LineState {
    n: usize,
    yc: Vec<Vec<f64>>,
    tv_inv: Vec<Vec<f64>>,
    tv_t: Vec<Vec<f64>>,
    tv_inv_t: Vec<Vec<f64>>,
    z: Vec<f64>,
    /// delay in steps
    m: Vec<f64>,
    len: usize,
    /// ring buffers, [end][mode][step % len]: modal voltage and current
    vm: [Vec<Vec<f64>>; 2],
    im: [Vec<Vec<f64>>; 2],
    /// the history currents of the step being solved (physical), per end
    h: [Vec<f64>; 2],
}

impl LineState {
    /// Modal value at (step − m) for one end and mode, interpolated.
    fn past(&self, buf: &[f64], step: usize, m: f64) -> f64 {
        let k = m.floor();
        let f = m - k;
        let k = k as usize;
        let at = |s: isize| {
            let s = s.max(0) as usize;
            buf[s % self.len]
        };
        let s = step as isize - k as isize;
        (1.0 - f) * at(s) + f * at(s - 1)
    }
}

struct Diodes {
    vlim: Vec<f64>,
    q: [Vec<f64>; 2],
}

fn diode_iv(d: &crate::Diode, v: f64) -> (f64, f64) {
    let nvt = d.n * VT;
    let e = (v / nvt).min(80.0).exp();
    (d.is * (e - 1.0) + GMIN * v, d.is * e / nvt + GMIN)
}

/// Depletion charge and capacitance, as SPICE's junction model.
fn diode_qc(d: &crate::Diode, v: f64) -> (f64, f64) {
    if d.cjo == 0.0 {
        return (0.0, 0.0);
    }
    let (vj, m, fc) = (d.vj, d.m, d.fc);
    if v < fc * vj {
        let a = 1.0 - v / vj;
        let q = d.cjo * vj * (1.0 - a.powf(1.0 - m)) / (1.0 - m);
        (q, d.cjo * a.powf(-m))
    } else {
        let f1 = vj * (1.0 - (1.0 - fc).powf(1.0 - m)) / (1.0 - m);
        let f2 = (1.0 - fc).powf(1.0 + m);
        let f3 = 1.0 - fc * (1.0 + m);
        let v0 = fc * vj;
        let q = d.cjo * (f1 + (f3 * (v - v0) + m / (2.0 * vj) * (v * v - v0 * v0)) / f2);
        (q, d.cjo / f2 * (f3 + m * v / vj))
    }
}

/// SPICE's junction voltage limiting (pnjlim).
fn pnjlim(d: &crate::Diode, vnew: f64, vold: f64) -> f64 {
    let nvt = d.n * VT;
    let vcrit = nvt * (nvt / (std::f64::consts::SQRT_2 * d.is)).ln();
    if vnew > vcrit && (vnew - vold).abs() > 2.0 * nvt {
        if vold > 0.0 {
            let arg = 1.0 + (vnew - vold) / nvt;
            if arg > 0.0 {
                vold + nvt * arg.ln()
            } else {
                vcrit
            }
        } else {
            nvt * (vnew / nvt).ln()
        }
    } else {
        vnew
    }
}

/// Union-find, for splitting the circuit into pieces.
struct Sets(Vec<usize>);

impl Sets {
    fn find(&mut self, mut a: usize) -> usize {
        while self.0[a] != a {
            self.0[a] = self.0[self.0[a]];
            a = self.0[a];
        }
        a
    }
    fn join(&mut self, a: usize, b: usize) {
        let (a, b) = (self.find(a), self.find(b));
        if a != b {
            self.0[a] = b;
        }
    }
}

struct Sim<'a> {
    net: &'a Netlist,
    opt: &'a Options,
    known: Vec<bool>,
    fixed: Vec<(usize, Pwl)>,
    /// each table, its coefficient and its supply factor
    tables: Vec<(Pwl, Option<Pwl>, Option<Pwl>)>,
    groups: Vec<InductorGroup>,
    lines: Vec<LineState>,
    v: Vec<f64>,
    v1: Vec<f64>,
    v2: Vec<f64>,
    il: [Vec<f64>; 2],
    diodes: Diodes,
    stats: Stats,
    /// the node that moved most in the last Newton iteration that didn't
    /// converge, and by how much
    last_miss: (usize, f64),
}

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Dc,
    Tran,
}

impl<'a> Sim<'a> {
    fn check(net: &Netlist, opt: &Options) -> Result<(), Error> {
        let bad = |what: &str| Err(Error(what.to_string()));
        if net.nodes == 0 {
            return bad("no nodes (node 0 is ground)");
        }
        if !(opt.dt > 0.0 && opt.tstop > 0.0 && opt.dt.is_finite() && opt.tstop.is_finite()) {
            return bad("the time step and end time must be positive");
        }
        let nodes = |list: &[usize]| list.iter().all(|&n| n < net.nodes);
        let ok = net
            .fixed
            .iter()
            .all(|f| f.node < net.nodes && f.node != 0 && !f.wave.is_empty())
            && net
                .resistors
                .iter()
                .all(|r| nodes(&[r.a, r.b]) && r.r > 0.0)
            && net
                .capacitors
                .iter()
                .all(|c| nodes(&[c.a, c.b]) && c.c >= 0.0)
            && net
                .inductors
                .iter()
                .all(|l| nodes(&[l.a, l.b]) && l.l > 0.0)
            && net.couplings.iter().all(|k| {
                k.l1 < net.inductors.len()
                    && k.l2 < net.inductors.len()
                    && k.l1 != k.l2
                    && k.k.abs() < 1.0
            })
            && net.tables.iter().all(|t| {
                nodes(&[t.a, t.b, t.x, t.y])
                    && t.supply.as_ref().is_none_or(|sp| nodes(&[sp.p, sp.q]))
            })
            && net
                .diodes
                .iter()
                .all(|d| nodes(&[d.a, d.b]) && d.is > 0.0 && d.n > 0.0)
            && opt
                .probes
                .iter()
                .all(|&(a, b)| a < net.nodes && b < net.nodes);
        if !ok {
            return bad(
                "an element refers to a node or inductor that doesn't exist, or has a bad value",
            );
        }
        for (i, l) in net.lines.iter().enumerate() {
            let n = l.end1.len();
            let shape = n > 0
                && l.end2.len() == n
                && l.z.len() == n
                && l.delay.len() == n
                && l.tv.len() == n
                && l.tv.iter().all(|r| r.len() == n);
            if !shape || !nodes(&l.end1) || !nodes(&l.end2) || !nodes(&[l.ref1, l.ref2]) {
                return Err(Error(format!("line {i}: inconsistent shape or nodes")));
            }
            if l.z.iter().any(|&z| z <= 0.0) {
                return Err(Error(format!("line {i}: impedances must be positive")));
            }
            if let Some(d) = l.delay.iter().find(|&&d| d < opt.dt) {
                return Err(Error(format!(
                    "line {i}: delay {d:e} s is shorter than the time step {:e} s",
                    opt.dt
                )));
            }
        }
        Ok(())
    }

    fn new(net: &'a Netlist, opt: &'a Options) -> Result<Sim<'a>, Error> {
        Self::check(net, opt)?;
        let mut known = vec![false; net.nodes];
        known[0] = true;
        let mut fixed = Vec::new();
        for f in &net.fixed {
            if known[f.node] {
                return Err(Error(format!("node {} is held twice", f.node)));
            }
            known[f.node] = true;
            fixed.push((
                f.node,
                Pwl::new(&f.wave).map_err(|e| Error(format!("fixed node {}: {e}", f.node)))?,
            ));
        }
        let mut tables = Vec::new();
        for (i, t) in net.tables.iter().enumerate() {
            let tab = Pwl::new(&t.table).map_err(|e| Error(format!("table {i}: {e}")))?;
            let coef = match &t.coef {
                Some(c) => {
                    Some(Pwl::new(c).map_err(|e| Error(format!("table {i} coefficient: {e}")))?)
                }
                None => None,
            };
            let supply = match &t.supply {
                Some(sp) => Some(
                    Pwl::new(&sp.table)
                        .map_err(|e| Error(format!("table {i} supply factor: {e}")))?,
                ),
                None => None,
            };
            tables.push((tab, coef, supply));
        }
        // coupled inductors: groups, and (dt/1.5)·L⁻¹ for each
        let ni = net.inductors.len();
        let mut sets = Sets((0..ni).collect());
        for k in &net.couplings {
            sets.join(k.l1, k.l2);
        }
        let mut by_root: std::collections::BTreeMap<usize, Vec<usize>> = Default::default();
        for i in 0..ni {
            let r = sets.find(i);
            by_root.entry(r).or_default().push(i);
        }
        let mut groups = Vec::new();
        for members in by_root.into_values() {
            let n = members.len();
            let mut lm = vec![vec![0.0; n]; n];
            for (p, &a) in members.iter().enumerate() {
                lm[p][p] = net.inductors[a].l;
            }
            for k in &net.couplings {
                if let (Some(p), Some(q)) = (
                    members.iter().position(|&m| m == k.l1),
                    members.iter().position(|&m| m == k.l2),
                ) {
                    let m = k.k * (net.inductors[k.l1].l * net.inductors[k.l2].l).sqrt();
                    lm[p][q] += m;
                    lm[q][p] += m;
                }
            }
            let inv = invert(&lm).ok_or_else(|| Error("coupled inductors are singular".into()))?;
            let gamma = inv
                .iter()
                .map(|row| row.iter().map(|x| x * opt.dt / 1.5).collect())
                .collect();
            groups.push(InductorGroup { members, gamma });
        }
        let mut lines = Vec::new();
        for (i, l) in net.lines.iter().enumerate() {
            let n = l.end1.len();
            let tv_inv =
                invert(&l.tv).ok_or_else(|| Error(format!("line {i}: singular modal matrix")))?;
            let tv_t: Vec<Vec<f64>> = (0..n)
                .map(|r| (0..n).map(|c| l.tv[c][r]).collect())
                .collect();
            let tv_inv_t: Vec<Vec<f64>> = (0..n)
                .map(|r| (0..n).map(|c| tv_inv[c][r]).collect())
                .collect();
            // Yc = Tv⁻ᵀ · diag(1/z) · Tv⁻¹
            let yc = (0..n)
                .map(|r| {
                    (0..n)
                        .map(|c| (0..n).map(|k| tv_inv_t[r][k] * tv_inv[k][c] / l.z[k]).sum())
                        .collect()
                })
                .collect();
            let m: Vec<f64> = l.delay.iter().map(|d| d / opt.dt).collect();
            let len = m.iter().fold(0.0f64, |a, &b| a.max(b)).ceil() as usize + 3;
            lines.push(LineState {
                n,
                yc,
                tv_inv,
                tv_t,
                tv_inv_t,
                z: l.z.clone(),
                m,
                len,
                vm: [vec![vec![0.0; len]; n], vec![vec![0.0; len]; n]],
                im: [vec![vec![0.0; len]; n], vec![vec![0.0; len]; n]],
                h: [vec![0.0; n], vec![0.0; n]],
            });
        }
        let nd = net.diodes.len();
        Ok(Sim {
            net,
            opt,
            known,
            fixed,
            tables,
            groups,
            lines,
            v: vec![0.0; net.nodes],
            v1: vec![0.0; net.nodes],
            v2: vec![0.0; net.nodes],
            il: [vec![0.0; ni], vec![0.0; ni]],
            diodes: Diodes {
                vlim: vec![0.0; nd],
                q: [vec![0.0; nd], vec![0.0; nd]],
            },
            stats: Stats::default(),
            last_miss: (0, 0.0),
        })
    }

    /// The static stamps for DC or for the transient.
    fn stamps(&self, mode: Mode) -> Vec<(usize, usize, f64)> {
        let net = self.net;
        let dt = self.opt.dt;
        let mut s = Vec::new();
        for n in 0..net.nodes {
            if !self.known[n] {
                s.push((n, n, GMIN));
            }
        }
        for r in &net.resistors {
            two(&mut s, r.a, r.b, 1.0 / r.r);
        }
        match mode {
            Mode::Dc => {
                for l in &net.inductors {
                    two(&mut s, l.a, l.b, 1.0 / R_SHORT);
                }
                for l in &net.lines {
                    for (&a, &b) in l.end1.iter().zip(&l.end2) {
                        two(&mut s, a, b, 1.0 / R_SHORT);
                    }
                    if l.ref1 != l.ref2 {
                        two(&mut s, l.ref1, l.ref2, 1.0 / R_SHORT);
                    }
                }
            }
            Mode::Tran => {
                for c in &net.capacitors {
                    two(&mut s, c.a, c.b, 1.5 * c.c / dt);
                }
                for g in &self.groups {
                    for (p, &lp) in g.members.iter().enumerate() {
                        for (q, &lq) in g.members.iter().enumerate() {
                            let x = g.gamma[p][q];
                            let (a, b) = (net.inductors[lp].a, net.inductors[lp].b);
                            let (c, d) = (net.inductors[lq].a, net.inductors[lq].b);
                            s.push((a, c, x));
                            s.push((a, d, -x));
                            s.push((b, c, -x));
                            s.push((b, d, x));
                        }
                    }
                }
                for (l, st) in net.lines.iter().zip(&self.lines) {
                    for (ends, r) in [(&l.end1, l.ref1), (&l.end2, l.ref2)] {
                        let mut total = 0.0;
                        for p in 0..st.n {
                            let mut col = 0.0;
                            for q in 0..st.n {
                                let y = st.yc[p][q];
                                s.push((ends[p], ends[q], y));
                                s.push((ends[p], r, -y));
                                col += y;
                            }
                            // the reference row: minus the column sums
                            s.push((r, ends[p], -col));
                            total += col;
                        }
                        s.push((r, r, total));
                    }
                }
            }
        }
        s
    }

    /// The nodes each nonlinear element touches: tables [a, b, x, y],
    /// their supply factors [a, b, p, q], diodes [a, b, a, b].
    fn nonlinear_nodes(&self) -> (Touches, Touches, Touches) {
        let t = self
            .net
            .tables
            .iter()
            .enumerate()
            .map(|(i, t)| (i, [t.a, t.b, t.x, t.y]))
            .collect();
        let s = self
            .net
            .tables
            .iter()
            .enumerate()
            .filter_map(|(i, t)| t.supply.as_ref().map(|sp| (i, [t.a, t.b, sp.p, sp.q])))
            .collect();
        let d = self
            .net
            .diodes
            .iter()
            .enumerate()
            .map(|(i, d)| (i, [d.a, d.b, d.a, d.b]))
            .collect();
        (t, s, d)
    }

    /// Split the unknown nodes into pieces: one piece (DC), or one per
    /// connected part of the transient's matrix.
    fn pieces(
        &self,
        mode: Mode,
        stamps: &[(usize, usize, f64)],
    ) -> (Vec<Piece>, Vec<Option<(usize, usize)>>) {
        let n = self.net.nodes;
        let (tables, supplies, diodes) = self.nonlinear_nodes();
        let mut sets = Sets((0..n).collect());
        if mode == Mode::Tran {
            for &(r, c, _) in stamps {
                if !self.known[r] && !self.known[c] {
                    sets.join(r, c);
                }
            }
            for (_, nn) in tables.iter().chain(supplies.iter()).chain(diodes.iter()) {
                let u: Vec<usize> = nn.iter().copied().filter(|&x| !self.known[x]).collect();
                for w in u.windows(2) {
                    sets.join(w[0], w[1]);
                }
            }
        }
        let mut loc: Vec<Option<(usize, usize)>> = vec![None; n];
        let mut members: Vec<Vec<usize>> = Vec::new();
        let mut root_piece: std::collections::HashMap<usize, usize> = Default::default();
        for node in 0..n {
            if self.known[node] {
                continue;
            }
            let r = if mode == Mode::Dc { 0 } else { sets.find(node) };
            let p = *root_piece.entry(r).or_insert_with(|| {
                members.push(Vec::new());
                members.len() - 1
            });
            loc[node] = Some((p, members[p].len()));
            members[p].push(node);
        }
        let ctx = Ctx { loc: &loc };
        let pieces = members
            .into_iter()
            .enumerate()
            .map(|(id, nodes)| Piece::new(id, nodes, stamps, (&tables, &supplies, &diodes), &ctx))
            .collect();
        (pieces, loc)
    }

    fn set_fixed(&mut self, t: f64) {
        for (node, w) in &self.fixed {
            self.v[*node] = w.at(t);
        }
    }

    /// The right-hand side from the histories (transient) into rhs (by node).
    fn history(&mut self, step: usize, rhs: &mut [f64]) {
        let net = self.net;
        let dt = self.opt.dt;
        for c in &net.capacitors {
            let v1 = self.v1[c.a] - self.v1[c.b];
            let v2 = self.v2[c.a] - self.v2[c.b];
            let ih = c.c / dt * (2.0 * v1 - 0.5 * v2);
            rhs[c.a] += ih;
            rhs[c.b] -= ih;
        }
        for (i, l) in net.inductors.iter().enumerate() {
            let ih = (2.0 * self.il[0][i] - 0.5 * self.il[1][i]) / 1.5;
            rhs[l.a] -= ih;
            rhs[l.b] += ih;
        }
        for (l, st) in net.lines.iter().zip(self.lines.iter_mut()) {
            let n = st.n;
            let mut hm = vec![0.0; n];
            for end in 0..2 {
                let far = 1 - end;
                for k in 0..n {
                    let vm = st.past(&st.vm[far][k], step, st.m[k]);
                    let im = st.past(&st.im[far][k], step, st.m[k]);
                    hm[k] = vm / st.z[k] + im;
                }
                let mut h = vec![0.0; n];
                matvec(&st.tv_inv_t, &hm, &mut h);
                let (ends, r) = if end == 0 {
                    (&l.end1, l.ref1)
                } else {
                    (&l.end2, l.ref2)
                };
                for p in 0..n {
                    rhs[ends[p]] += h[p];
                    rhs[r] -= h[p];
                }
                st.h[end] = h;
            }
        }
    }

    /// Solve one piece: once if it's linear, by Newton's method if not.
    /// Returns (iterations, converged).
    fn solve(
        &mut self,
        piece: &mut Piece,
        mode: Mode,
        t: f64,
        rhs: &[f64],
    ) -> Result<(usize, bool), Error> {
        let n = piece.nodes.len();
        for (i, &node) in piece.nodes.iter().enumerate() {
            piece.rhs0[i] = rhs[node];
        }
        for &(i, c, g) in &piece.known {
            piece.rhs0[i] -= g * self.v[c];
        }
        if piece.linear() {
            if !piece.factored {
                piece.lu.vals.copy_from_slice(&piece.base);
                piece
                    .lu
                    .factor()
                    .map_err(|node| Error(format!("singular matrix at node {node}")))?;
                piece.factored = true;
            }
            piece.rhs.copy_from_slice(&piece.rhs0);
            piece.lu.solve(&mut piece.rhs);
            for (i, &node) in piece.nodes.iter().enumerate() {
                self.v[node] = piece.rhs[i];
            }
            return Ok((1, true));
        }
        if mode == Mode::Dc {
            return self.newton_dc(piece);
        }
        let limit = self.opt.max_newton;
        let mut prev = vec![0.0; n];
        for it in 1..=limit {
            self.assemble(piece, mode, t, true);
            piece
                .lu
                .factor()
                .map_err(|node| Error(format!("singular matrix at node {node} (t = {t:e} s)")))?;
            piece.lu.solve(&mut piece.rhs);
            for (i, &node) in piece.nodes.iter().enumerate() {
                prev[i] = self.v[node];
            }
            let (dv, worst) = self.take(piece, &prev, 1.0, t)?;
            if dv < self.opt.vtol {
                return Ok((it, true));
            }
            self.last_miss = (worst, dv);
        }
        Ok((limit, false))
    }

    /// The DC operating point of a piece: Newton's method with a
    /// backtracking line search on the KCL residual. The tables have
    /// stretches of negative slope, where plain Newton bounces between
    /// segments; a Newton step always lowers the residual if it's short
    /// enough, so this can't cycle. Done when a full step is under vtol.
    fn newton_dc(&mut self, piece: &mut Piece) -> Result<(usize, bool), Error> {
        let n = piece.nodes.len();
        let mut x = vec![0.0; n];
        let mut step = vec![0.0; n];
        self.assemble(piece, Mode::Dc, 0.0, false);
        let mut norm = piece.residual(&self.v);
        for it in 1..=DC_ITERATIONS {
            piece
                .lu
                .factor()
                .map_err(|node| Error(format!("singular matrix at node {node} (DC)")))?;
            piece.lu.solve(&mut piece.rhs);
            for (i, &node) in piece.nodes.iter().enumerate() {
                x[i] = self.v[node];
                step[i] = piece.rhs[i] - x[i];
            }
            let full = step.iter().fold(0.0f64, |a, d| a.max(d.abs()));
            if !full.is_finite() {
                return Err(Error("the DC solution diverged".into()));
            }
            if full < self.opt.vtol {
                // there: the residual is down to rounding, which a line
                // search can't improve on
                for (i, &node) in piece.nodes.iter().enumerate() {
                    self.v[node] = x[i] + step[i];
                }
                return Ok((it, true));
            }
            let mut alpha = 1.0;
            loop {
                for (i, &node) in piece.nodes.iter().enumerate() {
                    self.v[node] = x[i] + alpha * step[i];
                }
                self.assemble(piece, Mode::Dc, 0.0, false);
                let trial = piece.residual(&self.v);
                if trial <= (1.0 - 1e-4 * alpha) * norm || alpha < 1e-4 {
                    norm = trial;
                    break;
                }
                alpha /= 2.0;
            }
            let worst = (0..n)
                .max_by(|&a, &b| step[a].abs().total_cmp(&step[b].abs()))
                .unwrap_or(0);
            self.last_miss = (piece.nodes.get(worst).copied().unwrap_or(0), alpha * full);
        }
        Ok((DC_ITERATIONS, false))
    }

    /// Fill the piece's matrix and right-hand side, linearised at the
    /// present voltages. `limit` applies junction limiting to the diodes.
    fn assemble(&mut self, piece: &mut Piece, mode: Mode, t: f64, limit: bool) {
        let dt = self.opt.dt;
        piece.lu.vals.copy_from_slice(&piece.base);
        piece.rhs.copy_from_slice(&piece.rhs0);
        let v = &self.v;
        let stamp = |vals: &mut [f64], rhs: &mut [f64], r: &NonlinearRef, g: f64, j: f64| {
            for (row, sign) in [(0, 1.0), (1, -1.0)] {
                for (col, s2) in [(0, 1.0), (1, -1.0)] {
                    match r.m[row][col] {
                        Target::Slot(s) => vals[s] += sign * s2 * g,
                        Target::Known(i, node) => rhs[i] -= sign * s2 * g * v[node],
                        Target::Skip => {}
                    }
                }
            }
            if let Some(i) = r.ra {
                rhs[i] -= j;
            }
            if let Some(i) = r.rb {
                rhs[i] += j;
            }
        };
        // with a supply factor, I = c·s(vs)·f(vx): the derivative in vx
        // goes in the table's own stamp, the one in vs in its supply stamp,
        // and the rest of the linearisation in the table's current
        let mut supply_g = 0;
        for r in &piece.tables {
            let el = &self.net.tables[r.idx];
            let (tab, coef, supply) = &self.tables[r.idx];
            let c = coef.as_ref().map_or(1.0, |p| p.at(t));
            let vx = v[el.x] - v[el.y];
            let (i, s) = tab.eval(vx);
            let (sv, sd, vs) = match (supply, &el.supply) {
                (Some(f), Some(sp)) => {
                    let vs = v[sp.p] - v[sp.q];
                    let (a, b) = f.eval(vs);
                    (a, b, vs)
                }
                _ => (1.0, 0.0, 0.0),
            };
            let g = c * sv * s;
            let gs = c * sd * i;
            stamp(
                &mut piece.lu.vals,
                &mut piece.rhs,
                r,
                g,
                c * sv * i - g * vx - gs * vs,
            );
            if supply.is_some() {
                let sr = &piece.supplies[supply_g];
                debug_assert_eq!(sr.idx, r.idx);
                stamp(&mut piece.lu.vals, &mut piece.rhs, sr, gs, 0.0);
                supply_g += 1;
            }
        }
        for r in &piece.diodes {
            let d = &self.net.diodes[r.idx];
            let vd = if limit {
                pnjlim(d, v[d.a] - v[d.b], self.diodes.vlim[r.idx])
            } else {
                v[d.a] - v[d.b]
            };
            self.diodes.vlim[r.idx] = vd;
            let (mut i, mut g) = diode_iv(d, vd);
            if mode == Mode::Tran {
                let (q, c) = diode_qc(d, vd);
                i += (1.5 * q - 2.0 * self.diodes.q[0][r.idx] + 0.5 * self.diodes.q[1][r.idx]) / dt;
                g += 1.5 * c / dt;
            }
            stamp(&mut piece.lu.vals, &mut piece.rhs, r, g, i - g * vd);
        }
    }

    /// Move the piece's nodes from `prev` a fraction `alpha` of the way to
    /// the solution in piece.rhs. Returns the largest move and its node.
    fn take(
        &mut self,
        piece: &Piece,
        prev: &[f64],
        alpha: f64,
        t: f64,
    ) -> Result<(f64, usize), Error> {
        let mut dv = 0.0f64;
        let mut worst = 0;
        for (i, &node) in piece.nodes.iter().enumerate() {
            let x = piece.rhs[i];
            if !x.is_finite() {
                return Err(Error(format!(
                    "the solution diverged at node {node} (t = {t:e} s)"
                )));
            }
            let d = alpha * (x - prev[i]);
            if d.abs() > dv {
                dv = d.abs();
                worst = node;
            }
            self.v[node] = prev[i] + d;
        }
        Ok((dv, worst))
    }

    /// Branch currents and line histories after a solved step (or DC).
    fn update(&mut self, mode: Mode, step: usize) {
        let net = self.net;
        let v = &self.v;
        match mode {
            Mode::Dc => {
                for (i, l) in net.inductors.iter().enumerate() {
                    let i0 = (v[l.a] - v[l.b]) / R_SHORT;
                    self.il[0][i] = i0;
                    self.il[1][i] = i0;
                }
            }
            Mode::Tran => {
                for g in &self.groups {
                    let vb: Vec<f64> = g
                        .members
                        .iter()
                        .map(|&m| v[net.inductors[m].a] - v[net.inductors[m].b])
                        .collect();
                    let new: Vec<f64> = g
                        .members
                        .iter()
                        .enumerate()
                        .map(|(p, &m)| {
                            let ih = (2.0 * self.il[0][m] - 0.5 * self.il[1][m]) / 1.5;
                            g.gamma[p].iter().zip(&vb).map(|(a, b)| a * b).sum::<f64>() + ih
                        })
                        .collect();
                    for (p, &m) in g.members.iter().enumerate() {
                        self.il[1][m] = self.il[0][m];
                        self.il[0][m] = new[p];
                    }
                }
            }
        }
        for (l, st) in net.lines.iter().zip(self.lines.iter_mut()) {
            let n = st.n;
            let mut vp = [vec![0.0; n], vec![0.0; n]];
            let mut ip = [vec![0.0; n], vec![0.0; n]];
            for p in 0..n {
                vp[0][p] = v[l.end1[p]] - v[l.ref1];
                vp[1][p] = v[l.end2[p]] - v[l.ref2];
            }
            match mode {
                Mode::Dc => {
                    for p in 0..n {
                        ip[0][p] = (v[l.end1[p]] - v[l.end2[p]]) / R_SHORT;
                        ip[1][p] = -ip[0][p];
                    }
                }
                Mode::Tran => {
                    for end in 0..2 {
                        matvec(&st.yc, &vp[end], &mut ip[end]);
                        for p in 0..n {
                            ip[end][p] -= st.h[end][p];
                        }
                    }
                }
            }
            let mut vm = vec![0.0; n];
            let mut im = vec![0.0; n];
            for end in 0..2 {
                matvec(&st.tv_inv, &vp[end], &mut vm);
                matvec(&st.tv_t, &ip[end], &mut im);
                for k in 0..n {
                    if mode == Mode::Dc {
                        st.vm[end][k].fill(vm[k]);
                        st.im[end][k].fill(im[k]);
                    } else {
                        st.vm[end][k][step % st.len] = vm[k];
                        st.im[end][k][step % st.len] = im[k];
                    }
                }
            }
        }
        for (i, d) in net.diodes.iter().enumerate() {
            let (q, _) = diode_qc(d, v[d.a] - v[d.b]);
            if mode == Mode::Dc {
                self.diodes.q[1][i] = q;
            } else {
                self.diodes.q[1][i] = self.diodes.q[0][i];
            }
            self.diodes.q[0][i] = q;
        }
        self.v2
            .copy_from_slice(if mode == Mode::Dc { &self.v } else { &self.v1 });
        self.v1.copy_from_slice(&self.v);
    }

    fn record(&self, time: &mut Vec<f64>, data: &mut Vec<f64>, t: f64) {
        time.push(t);
        for &(a, b) in &self.opt.probes {
            data.push(self.v[a] - self.v[b]);
        }
    }
}

/// Run a transient analysis from the DC operating point at t = 0.
/// `interrupt` is polled now and then; returning true stops the run.
pub fn run(
    net: &Netlist,
    opt: &Options,
    interrupt: &mut dyn FnMut() -> bool,
) -> Result<Output, Error> {
    let start = Instant::now();
    let mut sim = Sim::new(net, opt)?;
    // DC operating point
    sim.set_fixed(0.0);
    for d in 0..net.diodes.len() {
        sim.diodes.vlim[d] = 0.0;
    }
    let dc_stamps = sim.stamps(Mode::Dc);
    let (mut dc, _) = sim.pieces(Mode::Dc, &dc_stamps);
    let zero = vec![0.0; net.nodes];
    for piece in dc.iter_mut() {
        let (it, ok) = sim.solve(piece, Mode::Dc, 0.0, &zero)?;
        sim.stats.dc_iterations += it;
        if !ok {
            let (node, dv) = sim.last_miss;
            return Err(Error(format!(
                "no DC operating point: Newton's method didn't converge (node {node} still moving by {dv:.3e} V, at {:.4} V)",
                sim.v[node]
            )));
        }
    }
    drop(dc);
    sim.update(Mode::Dc, 0);
    // the transient
    let stamps = sim.stamps(Mode::Tran);
    let (mut pieces, _) = sim.pieces(Mode::Tran, &stamps);
    sim.stats.pieces = pieces.len();
    sim.stats.largest_piece = pieces.iter().map(|p| p.nodes.len()).max().unwrap_or(0);
    let steps = (opt.tstop / opt.dt - 1e-9).ceil().max(1.0) as usize;
    let every = opt.every.max(1);
    let mut time = Vec::with_capacity(steps / every + 2);
    let mut data = Vec::with_capacity((steps / every + 2) * opt.probes.len());
    sim.record(&mut time, &mut data, 0.0);
    let mut rhs = vec![0.0; net.nodes];
    for step in 1..=steps {
        if step % 256 == 0 {
            if interrupt() {
                return Err(Error("interrupted".into()));
            }
            let s = start.elapsed().as_secs_f64();
            if s > opt.max_seconds {
                return Err(Error(format!(
                    "gave up after {s:.0} s at t = {:.3} ns of {:.3} ns",
                    step as f64 * opt.dt * 1e9,
                    opt.tstop * 1e9
                )));
            }
        }
        let t = step as f64 * opt.dt;
        sim.set_fixed(t);
        rhs.fill(0.0);
        sim.history(step, &mut rhs);
        let mut worst = 0;
        for piece in pieces.iter_mut() {
            if !piece.linear() {
                // predict: carry on along the last step
                for &node in &piece.nodes {
                    sim.v[node] = 2.0 * sim.v1[node] - sim.v2[node];
                }
            }
            let (it, ok) = sim.solve(piece, Mode::Tran, t, &rhs)?;
            if !piece.linear() {
                sim.stats.newton += it;
                worst = worst.max(it);
                if !ok {
                    sim.stats.nonconverged += 1;
                }
            }
        }
        sim.stats.newton_max = sim.stats.newton_max.max(worst);
        sim.update(Mode::Tran, step);
        if step % every == 0 || step == steps {
            sim.record(&mut time, &mut data, t);
        }
    }
    sim.stats.steps = steps;
    sim.stats.seconds = start.elapsed().as_secs_f64();
    Ok(Output {
        time,
        data,
        stats: sim.stats,
    })
}
