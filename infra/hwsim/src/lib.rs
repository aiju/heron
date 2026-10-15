//! The event-driven chip-level timing simulator.
//!
//! A machine is a netlist of chips (infra/hw/netlist.py exports it), each
//! with a behavioural model and its datasheet delays ([`models`]). The
//! simulator propagates every change through the chips with those delays
//! ([`sim`]), checks setup, hold and write timing and bus contention as it
//! goes, and runs the machine from reset until its program halts
//! ([`machine`]), or runs a whole system of cards whose clocks are parts
//! of the netlist ([`system`]).

pub mod devices;
pub mod machine;
pub mod models;
pub mod rng;
pub mod sim;
pub mod system;

pub use machine::{Config, Netlist, Outcome, run};
pub use system::{SysConfig, SysOutcome, run_system};

/// A netlist or configuration the simulator can't run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Error {}
