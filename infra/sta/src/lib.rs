//! The static timing engine (RFC 0048): waveforms over a cycle.
//!
//! A case fixes some nets' values and the registers' state at its start;
//! the rest is unknown. Phase A ([`values`]) simulates it edge by edge of
//! the reference clock with zero delay, in three values, to find what
//! every register loads at every edge, splitting the case where a register
//! it names would load X. Phase B ([`waves`]) computes every net's waveform
//! from those edges, with every chip's minimum and maximum delays, and the
//! checks ([`checks`]) read the waveforms: setup and hold with common path
//! pessimism removed, pulse widths and periods, strobes, glitches.
//!
//! A netlist comes as infra/hw/waves.py exports it ([`input`]); chips are
//! described in infra/hw/cells.py's terms, compiled in [`design`].

pub mod checks;
pub mod design;
pub mod input;
pub mod logic;
pub mod values;
pub mod waves;

pub use checks::{BranchOut, CheckOut, Step};
pub use design::Design;
pub use input::{Case, Netlist, Options};

/// A case's outcome as Python gets it: its branches, or why it couldn't
/// be analysed.
#[derive(serde::Serialize)]
#[serde(untagged)]
pub enum CaseOut {
    Branches(Vec<BranchOut>),
    Failed { error: String },
}

impl From<Result<Vec<BranchOut>, Error>> for CaseOut {
    fn from(r: Result<Vec<BranchOut>, Error>) -> CaseOut {
        match r {
            Ok(b) => CaseOut::Branches(b),
            Err(e) => CaseOut::Failed { error: e.0 },
        }
    }
}

/// A netlist or case the engine can't analyse.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Error {}

/// A case's branches: phase A splits it where a register it names would
/// load X, each branch with one value there.
pub fn analyse(d: &Design, case: &Case, o: &Options) -> Result<Vec<BranchOut>, Error> {
    let mut todo = vec![case.forced.clone()];
    let mut out = Vec::new();
    while let Some(forced) = todo.pop() {
        if out.len() + todo.len() >= o.branches {
            return Err(Error(format!(
                "{}: more than {} branches",
                case.label, o.branches
            )));
        }
        let mut c = case.clone();
        c.forced = forced;
        match values::run(d, &c)? {
            values::Outcome::Fork { net, event } => {
                for v in [1, 0] {
                    let mut f = c.forced.clone();
                    f.push((d.nets[net as usize].clone(), event, v));
                    todo.push(f);
                }
            }
            values::Outcome::Done(t) => {
                let mut w = waves::run(d, &t, o.fraction)?;
                out.push(checks::run(d, &t, &mut w, o, &c));
            }
        }
    }
    out.sort_by(|a, b| a.choices.cmp(&b.choices));
    Ok(out)
}

/// Every case, on `jobs` threads (0: as many as the machine has).
pub fn analyse_all(
    d: &Design,
    cases: &[Case],
    o: &Options,
    jobs: usize,
) -> Vec<Result<Vec<BranchOut>, Error>> {
    let jobs = if jobs == 0 {
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1)
    } else {
        jobs
    };
    let next = std::sync::atomic::AtomicUsize::new(0);
    let mut out: Vec<Option<Result<Vec<BranchOut>, Error>>> =
        (0..cases.len()).map(|_| None).collect();
    let slots = std::sync::Mutex::new(&mut out);
    std::thread::scope(|s| {
        for _ in 0..jobs.min(cases.len()).max(1) {
            s.spawn(|| {
                loop {
                    let i = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if i >= cases.len() {
                        break;
                    }
                    let r = analyse(d, &cases[i], o);
                    slots.lock().unwrap()[i] = Some(r);
                }
            });
        }
    });
    out.into_iter().map(|r| r.unwrap()).collect()
}
