//! A fixed-step transient circuit simulator for signal integrity.
//!
//! It runs the circuits the backplane studies build: resistors, capacitors,
//! inductors and their couplings, lossless transmission lines (single, or
//! coupled through their modes), nodes held at a voltage, diodes, and the
//! behavioural current sources IBIS buffers are made of. infra/si/engine.py
//! turns the studies' SPICE netlists into a [`Netlist`].
//!
//! It differs from SPICE where that matters for sweeps:
//!
//! - **A fixed time step.** A run takes a known number of steps, so it
//!   can't stall the way an adaptive step can when it collapses on a
//!   table's kink. Newton's method gets a bounded number of iterations per
//!   step, and a step that doesn't converge is counted, not retried
//!   ([`Stats::nonconverged`]).
//! - **Nodal analysis only.** Voltage sources must be to ground; they make
//!   their node known ([`Fixed`]).
//! - **Lines by the method of characteristics.** A lossless line is a
//!   conductance and a source from the far end's past at each end, so it
//!   splits the circuit into pieces solved separately. Coupled lines are
//!   the same per mode.
//!
//! The integration is BDF2 (Gear, second order) throughout, from a DC
//! operating point at t = 0.

mod pwl;
mod sim;
mod sparse;

use serde::Deserialize;

pub use sim::run;

/// A circuit. Node 0 is ground; nodes are numbered from 0 to `nodes` − 1.
#[derive(Debug, Clone, Default, Deserialize)]
pub struct Netlist {
    pub nodes: usize,
    #[serde(default)]
    pub fixed: Vec<Fixed>,
    #[serde(default)]
    pub resistors: Vec<Resistor>,
    #[serde(default)]
    pub capacitors: Vec<Capacitor>,
    #[serde(default)]
    pub inductors: Vec<Inductor>,
    #[serde(default)]
    pub couplings: Vec<Coupling>,
    #[serde(default)]
    pub lines: Vec<Line>,
    #[serde(default)]
    pub tables: Vec<Table>,
    #[serde(default)]
    pub diodes: Vec<Diode>,
}

/// A node held at a voltage: piecewise linear in time, `(t, v)` points,
/// constant before the first and after the last.
#[derive(Debug, Clone, Deserialize)]
pub struct Fixed {
    pub node: usize,
    pub wave: Vec<(f64, f64)>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Resistor {
    pub a: usize,
    pub b: usize,
    pub r: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Capacitor {
    pub a: usize,
    pub b: usize,
    pub c: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Inductor {
    pub a: usize,
    pub b: usize,
    pub l: f64,
}

/// Mutual inductance between two inductors (indices into
/// [`Netlist::inductors`]), as a coupling coefficient.
#[derive(Debug, Clone, Deserialize)]
pub struct Coupling {
    pub l1: usize,
    pub l2: usize,
    pub k: f64,
}

/// A lossless line of n conductors between `end1` and `end2`, each end
/// with its reference node. The conductor voltages are v = Tv·vm, where
/// mode k has impedance `z[k]` and delay `delay[k]`; the currents are
/// i = Tv⁻ᵀ·im. A single line has `tv` = [[1]].
#[derive(Debug, Clone, Deserialize)]
pub struct Line {
    pub end1: Vec<usize>,
    pub ref1: usize,
    pub end2: Vec<usize>,
    pub ref2: usize,
    pub tv: Vec<Vec<f64>>,
    pub z: Vec<f64>,
    pub delay: Vec<f64>,
}

/// A behavioural current from `a` to `b`: coef(t) · table(V(x) − V(y)),
/// times `supply`'s factor if there is one.
/// The table is piecewise linear, extended along its end segments; the
/// coefficient is piecewise linear in time (1 if absent). An IBIS buffer
/// is four of these and a capacitor.
#[derive(Debug, Clone, Deserialize)]
pub struct Table {
    pub a: usize,
    pub b: usize,
    pub x: usize,
    pub y: usize,
    #[serde(default)]
    pub coef: Option<Vec<(f64, f64)>>,
    pub table: Vec<(f64, f64)>,
    /// A factor on the current from a voltage elsewhere: for a driver,
    /// how its strength follows its own rails (what IBIS's [ISSO] tables
    /// describe), so that ground bounce limits itself.
    #[serde(default)]
    pub supply: Option<Supply>,
}

/// The factor supply(V(p) − V(q)) on a [`Table`]'s current.
#[derive(Debug, Clone, Deserialize)]
pub struct Supply {
    pub p: usize,
    pub q: usize,
    pub table: Vec<(f64, f64)>,
}

/// A junction diode from `a` (anode) to `b`, as SPICE's: saturation
/// current, emission coefficient, and depletion capacitance (CJO, VJ, M,
/// FC). Series resistance is a separate resistor.
#[derive(Debug, Clone, Deserialize)]
pub struct Diode {
    pub a: usize,
    pub b: usize,
    pub is: f64,
    #[serde(default = "one")]
    pub n: f64,
    #[serde(default)]
    pub cjo: f64,
    #[serde(default = "one")]
    pub vj: f64,
    #[serde(default = "half")]
    pub m: f64,
    #[serde(default = "half")]
    pub fc: f64,
}

fn one() -> f64 {
    1.0
}

fn half() -> f64 {
    0.5
}

/// What to run, and what to record.
#[derive(Debug, Clone, Deserialize)]
pub struct Options {
    /// Time step (s).
    pub dt: f64,
    /// End time (s).
    pub tstop: f64,
    /// Voltages to record, as (node, reference node) pairs.
    pub probes: Vec<(usize, usize)>,
    /// Record every this many steps (and the first and last step).
    #[serde(default = "one_usize")]
    pub every: usize,
    /// Newton iterations allowed per time step.
    #[serde(default = "max_newton")]
    pub max_newton: usize,
    /// Newton has converged when no node moves more than this (V).
    #[serde(default = "vtol")]
    pub vtol: f64,
    /// Give up after this much wall-clock time (s).
    #[serde(default = "max_seconds")]
    pub max_seconds: f64,
}

fn one_usize() -> usize {
    1
}

fn max_newton() -> usize {
    50
}

fn vtol() -> f64 {
    1e-6
}

fn max_seconds() -> f64 {
    600.0
}

/// The recorded waveforms: `data[i * probes + p]` is probe p at `time[i]`.
#[derive(Debug, Clone)]
pub struct Output {
    pub time: Vec<f64>,
    pub data: Vec<f64>,
    pub stats: Stats,
}

#[derive(Debug, Clone, Default)]
pub struct Stats {
    /// Time steps taken.
    pub steps: usize,
    /// Newton iterations, over all steps and pieces of the circuit.
    pub newton: usize,
    /// The most Newton iterations any one step needed.
    pub newton_max: usize,
    /// Steps at which Newton hadn't converged within `max_newton`.
    pub nonconverged: usize,
    /// Newton iterations for the DC operating point.
    pub dc_iterations: usize,
    /// Pieces the circuit split into, and the unknowns in the largest.
    pub pieces: usize,
    pub largest_piece: usize,
    /// Wall-clock time (s).
    pub seconds: f64,
}

/// A netlist the simulator can't run, or a run that failed.
#[derive(Debug, Clone, PartialEq)]
pub struct Error(pub String);

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Error {}
