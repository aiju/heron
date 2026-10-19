//! Heron Mini's register-transfer model (RFC 0041) and its board, with
//! the video options of RFC 0042: a port of studies/mini/rtl.py and
//! system.py, cycle for cycle and tick for tick, for speed.
//!
//! The control store comes from Python (studies/mini/sim.py builds it from
//! ucode.py): each distinct microword as its fields' values in [`FIELDS`]'s
//! order, and every address's word.

pub mod cpu;
pub mod system;
pub mod video;

pub use cpu::{Cpu, Rom};
pub use system::System;
pub use video::{Board, Video};

/// The microword's fields the model reads, in the order a word's values
/// come in: ucode.py's, with the flags field (FLG) as its seven logical
/// fields.
pub const FIELDS: [&str; 59] = [
    "NEXT", "SEQ", "COND", "ARF", "APC", "AR", "AR2", "PCK", "SINA", "BRF", "BR", "BL", "BX",
    "BS0", "BF1", "BF23", "RFA", "RFB", "RFW", "RFK", "RFKW", "RFWE", "LDSX", "LDEX", "S", "M",
    "CIN", "MQM", "MS", "RMS", "RZ", "SIN", "V8", "FSEL", "KONST", "LDSGN", "LDR", "LDMAR",
    "MARINC", "LDPC", "PCCOND", "CONSUME", "LDLC", "LCINC", "CCB", "MEM", "SIZE", "LDCL", "CLSRC",
    "LCL", "LL", "FNZ", "NSEL", "FC", "CZERO", "CSRC", "FV", "FI", "VAS",
];
