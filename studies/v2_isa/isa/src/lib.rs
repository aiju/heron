//! Draft 2 (reports/0028-rfc-draft-2-isa.md, studies/v2_isa/isa-v2.md): its
//! decoder and semantics, the instruction-level simulator, the timing
//! model, and the encoder the assembler core (infra/toolchain) uses.
//!
//! The machine and the timing model started as copies of draft 1's
//! (studies/v1_isa/isa), so that draft 2 can change them without touching
//! draft 1's numbers. Every executed instruction records a timing key
//! ([`key`]); the timing model ([`timing`]) turns a key into cycles for
//! each configuration, so one run gives the cycle counts for all of them.

pub mod asm;
pub mod decode;
pub mod insn;
pub mod key;
pub mod machine;
pub mod timing;

pub use machine::Machine;
