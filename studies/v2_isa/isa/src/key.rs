//! Timing keys: what an executed instruction did, as the timing model
//! needs it. The simulator records one per instruction, so a single run
//! gives the cycle count for every hardware configuration.
//!
//! They are draft 1's (studies/v1_isa/isa/src/key.rs), with draft 2's
//! kinds of work added. In Python a key is a tuple (parcels, pc & 2, kind,
//! *params), as studies/v1_isa/timing32.py describes; [`Key::from_parts`]
//! and the accessors here convert.

/// How an instruction forms a memory address.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Ea {
    /// a register
    R,
    /// a register plus a 16-bit displacement
    Rd,
    /// an absolute address
    Abs,
    /// the PC plus a displacement
    Pc,
    /// a register plus a displacement plus a scaled index
    Idx,
    /// a register, incremented after
    Pi,
    /// a register, decremented before
    Pd,
    /// an absolute address plus a scaled index
    AbsX,
    /// the PC plus a displacement plus a scaled index
    PcX,
}

impl Ea {
    pub const ALL: [Ea; 9] = [
        Ea::R,
        Ea::Rd,
        Ea::Abs,
        Ea::Pc,
        Ea::Idx,
        Ea::Pi,
        Ea::Pd,
        Ea::AbsX,
        Ea::PcX,
    ];

    pub fn name(self) -> &'static str {
        match self {
            Ea::R => "r",
            Ea::Rd => "rd",
            Ea::Abs => "abs",
            Ea::Pc => "pc",
            Ea::Idx => "idx",
            Ea::Pi => "pi",
            Ea::Pd => "pd",
            Ea::AbsX => "absx",
            Ea::PcX => "pcx",
        }
    }

    pub fn from_name(s: &str) -> Option<Ea> {
        Ea::ALL.into_iter().find(|e| e.name() == s)
    }
}

/// Where a jump or call finds its target.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum How {
    Reg,
    Rel,
    Abs,
}

impl How {
    pub fn name(self) -> &'static str {
        match self {
            How::Reg => "reg",
            How::Rel => "rel",
            How::Abs => "abs",
        }
    }

    pub fn from_name(s: &str) -> Option<How> {
        [How::Reg, How::Rel, How::Abs]
            .into_iter()
            .find(|h| h.name() == s)
    }
}

/// The work an instruction does. `x` is 1 when an address computation
/// carries into the upper 16 bits (a second cycle on a 16-bit datapath);
/// `wb` is 1 when the result is written back.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    Alu {
        wb: u8,
    },
    Shift {
        steps: u32,
    },
    Mul {
        bits: u32,
        signed: u8,
    },
    Div {
        signed: u8,
    },
    Ld {
        ea: Ea,
        size: u8,
        x: u8,
    },
    Op {
        ea: Ea,
        size: u8,
        x: u8,
        wb: u8,
    },
    St {
        ea: Ea,
        size: u8,
        x: u8,
    },
    /// INC and DEC on memory: a read, an ALU operation, a write
    Rmw {
        ea: Ea,
        size: u8,
        x: u8,
    },
    Lea {
        ea: Ea,
        x: u8,
    },
    Br {
        taken: u8,
        x: u8,
    },
    /// DBNZ: a decrement, and a branch unless it reached zero
    Dbnz {
        taken: u8,
        x: u8,
    },
    Jmp {
        how: How,
        x: u8,
    },
    Jmpm {
        ea: Ea,
        x: u8,
    },
    Call {
        how: How,
        x: u8,
    },
    Callm {
        ea: Ea,
        x: u8,
    },
    Rti,
    Trap,
    Irq,
    Sys,
    Save {
        n: u8,
    },
    Restore {
        n: u8,
    },
    /// LDM and STM of n registers
    Ldm {
        n: u8,
    },
    Stm {
        n: u8,
    },
    /// BCOPY (tentative): n registers copied from one bank to another, a
    /// microcoded loop
    Bcopy {
        n: u8,
    },
}

/// One of a key's parameters, as Python sees it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Param<'a> {
    Int(i64),
    Str(&'a str),
}

/// A timing key: the instruction's length in parcels, whether it starts in
/// the second half of a 32-bit word (`p2` is pc & 2), and its kind.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Key {
    pub n: u8,
    pub p2: u8,
    pub kind: Kind,
}

impl Key {
    pub fn new(n: u32, pc: u32, kind: Kind) -> Key {
        Key {
            n: n as u8,
            p2: (pc & 2) as u8,
            kind,
        }
    }

    pub fn kind_name(&self) -> &'static str {
        match self.kind {
            Kind::Alu { .. } => "alu",
            Kind::Shift { .. } => "shift",
            Kind::Mul { .. } => "mul",
            Kind::Div { .. } => "div",
            Kind::Ld { .. } => "ld",
            Kind::Op { .. } => "op",
            Kind::St { .. } => "st",
            Kind::Rmw { .. } => "rmw",
            Kind::Lea { .. } => "lea",
            Kind::Br { .. } => "br",
            Kind::Dbnz { .. } => "dbnz",
            Kind::Jmp { .. } => "jmp",
            Kind::Jmpm { .. } => "jmpm",
            Kind::Call { .. } => "call",
            Kind::Callm { .. } => "callm",
            Kind::Rti => "rti",
            Kind::Trap => "trap",
            Kind::Irq => "irq",
            Kind::Sys => "sys",
            Kind::Save { .. } => "save",
            Kind::Restore { .. } => "restore",
            Kind::Ldm { .. } => "ldm",
            Kind::Stm { .. } => "stm",
            Kind::Bcopy { .. } => "bcopy",
        }
    }

    /// The parameters after the kind, as in the Python tuple.
    pub fn params(&self) -> Vec<Param<'static>> {
        use Param::{Int, Str};
        let i = |v: u8| Int(v as i64);
        match self.kind {
            Kind::Alu { wb } => vec![i(wb)],
            Kind::Shift { steps } => vec![Int(steps as i64)],
            Kind::Mul { bits, signed } => vec![Int(bits as i64), i(signed)],
            Kind::Div { signed } => vec![i(signed)],
            Kind::Ld { ea, size, x } | Kind::St { ea, size, x } | Kind::Rmw { ea, size, x } => {
                vec![Str(ea.name()), i(size), i(x)]
            }
            Kind::Op { ea, size, x, wb } => vec![Str(ea.name()), i(size), i(x), i(wb)],
            Kind::Lea { ea, x } | Kind::Jmpm { ea, x } | Kind::Callm { ea, x } => {
                vec![Str(ea.name()), i(x)]
            }
            Kind::Br { taken, x } | Kind::Dbnz { taken, x } => vec![i(taken), i(x)],
            Kind::Jmp { how, x } | Kind::Call { how, x } => vec![Str(how.name()), i(x)],
            Kind::Save { n }
            | Kind::Restore { n }
            | Kind::Ldm { n }
            | Kind::Stm { n }
            | Kind::Bcopy { n } => {
                vec![i(n)]
            }
            Kind::Rti | Kind::Trap | Kind::Irq | Kind::Sys => vec![],
        }
    }

    /// A key from the parts of a Python tuple, or None if it isn't one.
    pub fn from_parts(n: i64, p2: i64, kind: &str, p: &[Param<'_>]) -> Option<Key> {
        use Param::{Int, Str};
        let u8_ = |v: i64| u8::try_from(v).ok();
        let kind = match (kind, p) {
            ("alu", [Int(wb)]) => Kind::Alu { wb: u8_(*wb)? },
            ("shift", [Int(s)]) => Kind::Shift {
                steps: u32::try_from(*s).ok()?,
            },
            ("mul", [Int(b), Int(s)]) => Kind::Mul {
                bits: u32::try_from(*b).ok()?,
                signed: u8_(*s)?,
            },
            ("div", [Int(s)]) => Kind::Div { signed: u8_(*s)? },
            ("ld", [Str(e), Int(s), Int(x)]) => Kind::Ld {
                ea: Ea::from_name(e)?,
                size: u8_(*s)?,
                x: u8_(*x)?,
            },
            ("st", [Str(e), Int(s), Int(x)]) => Kind::St {
                ea: Ea::from_name(e)?,
                size: u8_(*s)?,
                x: u8_(*x)?,
            },
            ("rmw", [Str(e), Int(s), Int(x)]) => Kind::Rmw {
                ea: Ea::from_name(e)?,
                size: u8_(*s)?,
                x: u8_(*x)?,
            },
            ("op", [Str(e), Int(s), Int(x), Int(wb)]) => Kind::Op {
                ea: Ea::from_name(e)?,
                size: u8_(*s)?,
                x: u8_(*x)?,
                wb: u8_(*wb)?,
            },
            ("lea", [Str(e), Int(x)]) => Kind::Lea {
                ea: Ea::from_name(e)?,
                x: u8_(*x)?,
            },
            ("jmpm", [Str(e), Int(x)]) => Kind::Jmpm {
                ea: Ea::from_name(e)?,
                x: u8_(*x)?,
            },
            ("callm", [Str(e), Int(x)]) => Kind::Callm {
                ea: Ea::from_name(e)?,
                x: u8_(*x)?,
            },
            ("br", [Int(t), Int(x)]) => Kind::Br {
                taken: u8_(*t)?,
                x: u8_(*x)?,
            },
            ("dbnz", [Int(t), Int(x)]) => Kind::Dbnz {
                taken: u8_(*t)?,
                x: u8_(*x)?,
            },
            ("jmp", [Str(h), Int(x)]) => Kind::Jmp {
                how: How::from_name(h)?,
                x: u8_(*x)?,
            },
            ("call", [Str(h), Int(x)]) => Kind::Call {
                how: How::from_name(h)?,
                x: u8_(*x)?,
            },
            ("save", [Int(n)]) => Kind::Save { n: u8_(*n)? },
            ("restore", [Int(n)]) => Kind::Restore { n: u8_(*n)? },
            ("ldm", [Int(n)]) => Kind::Ldm { n: u8_(*n)? },
            ("stm", [Int(n)]) => Kind::Stm { n: u8_(*n)? },
            ("bcopy", [Int(n)]) => Kind::Bcopy { n: u8_(*n)? },
            ("rti", []) => Kind::Rti,
            ("trap", []) => Kind::Trap,
            ("irq", []) => Kind::Irq,
            ("sys", []) => Kind::Sys,
            _ => return None,
        };
        Some(Key {
            n: u8_(n)?,
            p2: u8_(p2)?,
            kind,
        })
    }
}
