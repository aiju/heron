//! The draft 1 instruction sets, 1a and 1b (studies/v1_isa): decoders and
//! semantics, the instruction-level simulator, and the timing model of six
//! hardware configurations.
//!
//! The Python simulator they replace is studies/v1_isa/sim32.py, which now
//! runs on this crate through heron.native.v1. Every executed instruction
//! records a timing key ([`key`]); the timing model ([`timing`]) turns a
//! key into cycles for each configuration, so one run gives the cycle
//! counts for all of them.

pub mod insn;
pub mod key;
pub mod machine;
pub mod timing;
pub mod v1a;
pub mod v1b;

pub use machine::{Isa, Machine};
