//! What the engine reads: a netlist as infra/hw/waves.py exports it, the
//! cases a study gives, and the options of a run.

use std::collections::HashMap;

use serde::Deserialize;

/// A sum of products over a chip's pins: each term a list of (pin, value);
/// no terms is 0, one empty term 1.
pub type Sop = Vec<Vec<(u32, u8)>>;

/// A delay as the data gives it: minimum (None where the data has none),
/// typical and maximum, in ps.
pub type DelaySpec = [Option<i64>; 3];

#[derive(Deserialize, Clone, Debug)]
pub struct Netlist {
    pub nets: Vec<String>,
    pub chips: Vec<ChipIn>,
    /// Nets with a pull-up resistor.
    #[serde(default)]
    pub pulled: Vec<u32>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct ChipIn {
    #[serde(rename = "ref")]
    pub reference: String,
    #[serde(rename = "type", default)]
    pub ctype: String,
    pub model: String,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub part: String,
    pub pins: Vec<String>,
    /// The net on each pin, -1 where it isn't connected.
    pub nets: Vec<i64>,
    #[serde(default)]
    pub params: HashMap<String, i64>,
    /// A synchroniser: its own setup and hold aren't reported.
    #[serde(default)]
    pub nocheck: bool,
    /// The chip's timing (infra/hw/cells.py), None for an untimed chip.
    #[serde(default)]
    pub desc: Option<Desc>,
    /// The wiring's delay on each pin, in pin order (empty: none).
    #[serde(default)]
    pub pin_delays: Vec<i64>,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct Desc {
    #[serde(default)]
    pub outputs: Vec<OutIn>,
    #[serde(default)]
    pub regs: Vec<RegIn>,
    #[serde(default)]
    pub checks: Vec<CheckIn>,
    /// Checks the description has but the part's data hasn't the figures for.
    #[serde(default)]
    pub unchecked: Vec<String>,
    #[serde(default)]
    pub sensitive: Vec<u32>,
    /// Outputs on a clock of the chip's own.
    #[serde(default)]
    pub asynchronous: Vec<u32>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct ArcIn {
    pub from: Vec<u32>,
    pub d: DelaySpec,
    pub name: String,
    #[serde(default)]
    pub when: Option<Sop>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct OutIn {
    pub pin: u32,
    /// None: an opaque function of the arcs' pins.
    #[serde(rename = "fn")]
    pub func: Option<Sop>,
    #[serde(default)]
    pub inv: bool,
    #[serde(default)]
    pub arcs: Vec<ArcIn>,
    #[serde(default)]
    pub enable: Option<Sop>,
    #[serde(default)]
    pub on: Vec<ArcIn>,
    #[serde(default)]
    pub off: Vec<ArcIn>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct RegIn {
    pub pin: u32,
    pub clock: u32,
    /// 1: rising edge, 0: falling.
    pub edge: u8,
    pub next: Sop,
    #[serde(default)]
    pub inv: bool,
    pub d: DelaySpec,
    pub name: String,
    #[serde(default)]
    pub clear: Option<Sop>,
    #[serde(default)]
    pub clear_value: u8,
    #[serde(default)]
    pub clear_arcs: Vec<ArcIn>,
    #[serde(default)]
    pub preset: Option<Sop>,
    #[serde(default)]
    pub preset_arcs: Vec<ArcIn>,
    #[serde(default)]
    pub enable: Option<Sop>,
    #[serde(default)]
    pub on: Vec<ArcIn>,
    #[serde(default)]
    pub off: Vec<ArcIn>,
    /// The state's delay into the chip's own functions; None: at once.
    #[serde(default)]
    pub feedback: Option<DelaySpec>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct StableIn {
    pub pins: Vec<u32>,
    pub start: Option<i64>,
    pub end: Option<i64>,
    pub after: Option<i64>,
    #[serde(default)]
    pub names: Vec<String>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct DataIn {
    pub pins: Vec<u32>,
    pub setup: Option<i64>,
    pub hold: Option<i64>,
    #[serde(default)]
    pub names: Vec<String>,
}

#[derive(Deserialize, Clone, Debug)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum CheckIn {
    Setup {
        pins: Vec<u32>,
        clock: u32,
        edge: u8,
        setup: i64,
        hold: i64,
        #[serde(default)]
        names: Vec<String>,
    },
    Width {
        pin: u32,
        level: u8,
        min: i64,
        #[serde(default)]
        names: Vec<String>,
    },
    Period {
        pin: u32,
        min: i64,
        #[serde(default)]
        names: Vec<String>,
    },
    Strobe {
        active: Sop,
        #[serde(default)]
        stable: Vec<StableIn>,
        #[serde(default)]
        data: Vec<DataIn>,
        width: Option<i64>,
        #[serde(default)]
        eq: String,
    },
}

/// When a case's window ends: at the first reference edge after 0 at
/// which `net` rises, within `events` edges.
#[derive(Deserialize, Clone, Debug)]
pub struct End {
    pub net: String,
    pub events: u32,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Case {
    #[serde(default)]
    pub label: String,
    /// The reference clock's net.
    pub clock: String,
    /// Nets pinned to a value once they first change.
    #[serde(default)]
    pub pins: HashMap<String, u8>,
    /// Nets held at a value throughout (a reset that isn't asserted).
    #[serde(default)]
    pub constant: HashMap<String, u8>,
    /// Registers' outputs before the edge at 0 and after it.
    #[serde(default)]
    pub start: HashMap<String, (u8, u8)>,
    /// Registers that split the case where they would load X.
    #[serde(default)]
    pub branch: Vec<String>,
    /// A branch's choices: (register's net, event, value).
    #[serde(default)]
    pub forced: Vec<(String, u32, u8)>,
    /// Chips whose checks this case doesn't count (their own cases time
    /// them), by reference.
    #[serde(default)]
    pub skip: Vec<String>,
    pub end: End,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Options {
    /// A delay's minimum where the data has none: this fraction of typical.
    #[serde(default = "default_fraction")]
    pub fraction: f64,
    /// The overlap two drivers of a bus may have at a handover, ps.
    #[serde(default = "default_tolerance")]
    pub tolerance: i64,
    /// Checks with less slack than this are reported as marginal, ps.
    #[serde(default = "default_marginal")]
    pub marginal: i64,
    /// How many of a branch's worst checks carry their paths.
    #[serde(default = "default_paths")]
    pub paths: usize,
    /// The most branches a case may split into.
    #[serde(default = "default_branches")]
    pub branches: usize,
    /// Nets whose waves the results carry.
    #[serde(default)]
    pub trace: Vec<String>,
}

fn default_fraction() -> f64 {
    0.3
}
fn default_tolerance() -> i64 {
    1000
}
fn default_marginal() -> i64 {
    2000
}
fn default_paths() -> usize {
    1
}
fn default_branches() -> usize {
    64
}

impl Default for Options {
    fn default() -> Options {
        Options {
            fraction: default_fraction(),
            tolerance: default_tolerance(),
            marginal: default_marginal(),
            paths: default_paths(),
            branches: default_branches(),
            trace: Vec::new(),
        }
    }
}
