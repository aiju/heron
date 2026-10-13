//! Cycle estimates for the draft 1 machines, from a model of six hardware
//! configurations (studies/v1_isa/timing32.py describes the model, and
//! timing-model-v1.md its rules).
//!
//! Each instruction is a few micro-operations, each using some of three
//! resources for a number of cycles: the ALU, the memory bus and the
//! register file port. A small list scheduler packs them, honouring
//! dependencies, the way a microcode writer would.

use crate::key::{Ea, How, Key, Kind};

/// Datapath width and fetch style.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Fetch {
    /// every instruction starts with its own fetch cycle; 16-bit bus
    Separate,
    /// the next opcode is fetched in the instruction's last cycle when the
    /// bus is free then; 16-bit bus
    Overlap,
    /// 32-bit bus and a two-parcel prefetch buffer
    Wide,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Config {
    /// 16 or 32
    pub dp: u32,
    pub fetch: Fetch,
}

/// The configurations, in the order the reports list them.
pub const CONFIGS: [(&str, Config); 6] = [
    (
        "D16-separate",
        Config {
            dp: 16,
            fetch: Fetch::Separate,
        },
    ),
    (
        "D16-overlap",
        Config {
            dp: 16,
            fetch: Fetch::Overlap,
        },
    ),
    (
        "D16-wide",
        Config {
            dp: 16,
            fetch: Fetch::Wide,
        },
    ),
    (
        "D32-separate",
        Config {
            dp: 32,
            fetch: Fetch::Separate,
        },
    ),
    (
        "D32-overlap",
        Config {
            dp: 32,
            fetch: Fetch::Overlap,
        },
    ),
    (
        "D32-wide",
        Config {
            dp: 32,
            fetch: Fetch::Wide,
        },
    ),
];

/// The configuration the simulator's own cycle count follows (for the timer
/// and the cycle limit).
pub const REFERENCE: &str = "D16-overlap";

impl Config {
    pub fn named(name: &str) -> Option<Config> {
        CONFIGS.iter().find(|(n, _)| *n == name).map(|&(_, c)| c)
    }
}

const A: u8 = 1;
const B: u8 = 2;
const R: u8 = 4;

/// A micro-operation: the resources it uses (A, B, R bits), for how long,
/// which earlier operations it waits for, and whether it sets the PC.
struct Op {
    res: u8,
    dur: u32,
    deps: Vec<usize>,
    sets_pc: bool,
}

fn op(res: u8, dur: u32, deps: &[usize]) -> Op {
    Op {
        res,
        dur,
        deps: deps.to_vec(),
        sets_pc: false,
    }
}

fn op_pc(res: u8, dur: u32, deps: &[usize]) -> Op {
    Op {
        res,
        dur,
        deps: deps.to_vec(),
        sets_pc: true,
    }
}

/// The cycles each resource is busy in.
#[derive(Default)]
struct Busy {
    cycles: [Vec<bool>; 3],
}

impl Busy {
    fn slot(res: u8) -> impl Iterator<Item = usize> {
        (0..3).filter(move |i| res & (1 << i) != 0)
    }

    fn get(&self, r: usize, c: u32) -> bool {
        self.cycles[r].get(c as usize).copied().unwrap_or(false)
    }

    fn free(&self, res: u8, t: u32, dur: u32) -> bool {
        Busy::slot(res).all(|r| (t..t + dur).all(|c| !self.get(r, c)))
    }

    fn take(&mut self, res: u8, t: u32, dur: u32) {
        for r in Busy::slot(res) {
            let v = &mut self.cycles[r];
            if v.len() < (t + dur) as usize {
                v.resize((t + dur) as usize, false);
            }
            for c in t..t + dur {
                v[c as usize] = true;
            }
        }
    }

    fn bus(&self, c: u32) -> bool {
        self.get(1, c)
    }
}

/// Place ops in order at the earliest cycle their dependencies and
/// resources allow. Returns each op's end and when the PC is ready.
fn schedule(ops: &[Op], start: u32, busy: &mut Busy) -> (Vec<u32>, Option<u32>) {
    let mut end: Vec<u32> = Vec::new();
    let mut pc_ready = None;
    for o in ops {
        let mut t = start;
        for &d in &o.deps {
            t = t.max(end[d]);
        }
        while !busy.free(o.res, t, o.dur) {
            t += 1;
        }
        busy.take(o.res, t, o.dur);
        end.push(t + o.dur);
        if o.sets_pc {
            pc_ready = Some(t + o.dur);
        }
    }
    (end, pc_ready)
}

/// The base-register write-back an addressing kind needs afterwards: for
/// post-increment and pre-decrement, a register write after op i (the
/// address op computes the new value too).
enum Update {
    None,
    Write(usize),
}

impl Config {
    fn bus(self) -> u32 {
        if self.fetch == Fetch::Wide { 32 } else { 16 }
    }

    /// A 32-bit ALU operation.
    fn aw(self) -> u32 {
        if self.dp == 32 { 1 } else { 2 }
    }

    /// Address arithmetic (base + small displacement, PC + offset). A 16-bit
    /// datapath adds the low halves and only needs a second cycle when the
    /// upper half changes.
    fn addr(self, x: u8) -> u32 {
        if self.dp == 32 { 1 } else { 1 + x as u32 }
    }

    fn mem(self, size: u8) -> u32 {
        if self.bus() == 32 || size <= 2 { 1 } else { 2 }
    }

    /// Append the ops that load MAR for an addressing kind. Returns the op
    /// that leaves the address in MAR, and the base update to follow.
    fn ea_ops(self, ops: &mut Vec<Op>, ea: Ea, x: u8, deps: &[usize]) -> (usize, Update) {
        let ar = A | R;
        match ea {
            Ea::R => ops.push(op(R, 1, deps)),
            Ea::Rd => ops.push(op(ar, self.addr(x), deps)),
            Ea::Rd32 => ops.push(op(ar, self.aw(), deps)),
            Ea::Abs => ops.push(op(0, 1, deps)),
            Ea::Pc => ops.push(op(A, self.addr(x), deps)),
            Ea::Idx => {
                ops.push(op(ar, self.addr(x), deps));
                // the index is a whole 32-bit register: a full add
                let i = ops.len() - 1;
                ops.push(op(ar, self.aw(), &[i]));
            }
            Ea::Pi | Ea::Pd => {
                // MAR <- R and T <- R +/- size in one cycle; R <- T later
                ops.push(op(ar, self.addr(x), deps));
                let i = ops.len() - 1;
                return (i, Update::Write(i));
            }
        }
        (ops.len() - 1, Update::None)
    }

    fn base_update(self, ops: &mut Vec<Op>, upd: Update) {
        match upd {
            Update::None => {}
            Update::Write(i) => ops.push(op(R, 1, &[i])),
        }
    }

    /// Micro-ops for one instruction, after its extension parcels are in.
    fn body(self, kind: Kind) -> Vec<Op> {
        let mut ops = Vec::new();
        let aw = self.aw();
        let ar = A | R;
        match kind {
            Kind::Alu { wb } => {
                ops.push(op(ar, aw, &[]));
                if wb != 0 {
                    ops.push(op(R, 1, &[0]));
                }
            }
            Kind::Shift { steps } => {
                ops.push(op(ar, steps.max(1) * aw, &[]));
                ops.push(op(R, 1, &[0]));
            }
            Kind::Mul { bits, signed } => {
                ops.push(op(ar, 1 + bits * aw + if signed != 0 { 2 } else { 0 }, &[]));
                ops.push(op(R, 1, &[0]));
            }
            Kind::Div { signed } => {
                ops.push(op(ar, 2 + 32 * aw + if signed != 0 { 2 } else { 0 }, &[]));
                ops.push(op(R, 1, &[0]));
            }
            Kind::Ld { ea, size, x } | Kind::Op { ea, size, x, .. } => {
                let (mar, upd) = self.ea_ops(&mut ops, ea, x, &[]);
                ops.push(op(B, self.mem(size), &[mar]));
                let m = ops.len() - 1;
                if let Kind::Op { wb, .. } = kind {
                    ops.push(op(ar, aw, &[m]));
                    if wb != 0 {
                        let i = ops.len() - 1;
                        ops.push(op(R, 1, &[i]));
                    }
                } else {
                    ops.push(op(R, 1, &[m]));
                }
                self.base_update(&mut ops, upd);
            }
            Kind::St { ea, size, x } => {
                let (mar, upd) = self.ea_ops(&mut ops, ea, x, &[]);
                ops.push(op(B, self.mem(size), &[mar]));
                self.base_update(&mut ops, upd);
            }
            Kind::Lea { ea, x } => {
                let (mar, _) = self.ea_ops(&mut ops, ea, x, &[]);
                ops.push(op(R, 1, &[mar]));
            }
            Kind::Br { taken, x } => {
                if taken != 0 {
                    ops.push(op_pc(A, self.addr(x), &[]));
                } else {
                    ops.push(op(0, 1, &[]));
                }
            }
            Kind::Jmp { how, x } => match how {
                How::Reg => ops.push(op_pc(R, 1, &[])),
                How::Rel => ops.push(op_pc(A, self.addr(x), &[])),
                How::Abs => ops.push(op_pc(0, 1, &[])),
            },
            Kind::Jmpm { ea, x } => {
                let (mar, upd) = self.ea_ops(&mut ops, ea, x, &[]);
                ops.push(op_pc(B, self.mem(4), &[mar]));
                self.base_update(&mut ops, upd);
            }
            Kind::Call { .. } | Kind::Callm { .. } => {
                let mut first = vec![];
                if let Kind::Callm { ea, x } = kind {
                    // read the target into T first
                    let (mar, upd) = self.ea_ops(&mut ops, ea, x, &[]);
                    ops.push(op(B, self.mem(4), &[mar]));
                    self.base_update(&mut ops, upd);
                    first = vec![ops.len() - 1];
                }
                ops.push(op(ar, self.addr(0), &first)); // MAR, T <- sp - 4
                let push = ops.len() - 1;
                ops.push(op(B, self.mem(4), &[push])); // [sp] <- return address
                ops.push(op(R, 1, &[push])); // sp <- T
                match kind {
                    Kind::Call { how: How::Rel, x } => ops.push(op_pc(A, self.addr(x), &[push])),
                    Kind::Call { how: How::Reg, .. } => ops.push(op_pc(R, 1, &[push])),
                    _ => ops.push(op_pc(0, 1, &[push])), // abs, or the target read from memory
                }
            }
            Kind::Ret => {
                ops.push(op(R, 1, &[])); // MAR, T <- sp
                ops.push(op_pc(B, self.mem(4), &[0]));
                ops.push(op(A, self.addr(0), &[0])); // T <- T + 4
                ops.push(op(R, 1, &[2])); // sp <- T
            }
            Kind::Rti => {
                ops.push(op(R, 1, &[]));
                ops.push(op(B, self.mem(4), &[0])); // flags
                ops.push(op_pc(B, self.mem(4), &[1]));
                ops.push(op(A, self.addr(0), &[0]));
                ops.push(op(R, 1, &[3]));
            }
            Kind::Trap | Kind::Irq => {
                // push PC and flags, jump to the vector
                ops.push(op(ar, self.addr(0), &[])); // MAR, T <- sp - 8
                ops.push(op(B, self.mem(4), &[0]));
                ops.push(op(B, self.mem(4), &[1]));
                ops.push(op(R, 1, &[0]));
                ops.push(op_pc(0, 1, &[0]));
            }
            Kind::Save { n } => {
                ops.push(op(ar, self.addr(0), &[])); // MAR <- sp - 4n; reads the first register too
                let (mut prev_mem, mut prev_read) = (None, 0);
                for i in 0..n {
                    if i > 0 {
                        ops.push(op(R, 1, &[prev_read]));
                        prev_read = ops.len() - 1;
                    }
                    let deps = match prev_mem {
                        None => vec![prev_read],
                        Some(m) => vec![prev_read, m],
                    };
                    ops.push(op(B, self.mem(4), &deps));
                    prev_mem = Some(ops.len() - 1);
                }
                ops.push(op(R, 1, &[0])); // sp <- sp - 4n
            }
            Kind::Restore { n } => {
                ops.push(op(R, 1, &[])); // MAR, T <- sp
                let mut prev = 0;
                for _ in 0..n {
                    ops.push(op(B, self.mem(4), &[prev]));
                    prev = ops.len() - 1;
                    ops.push(op(R, 1, &[prev]));
                }
                ops.push(op(A, self.addr(0), &[0]));
                let i = ops.len() - 1;
                ops.push(op(R, 1, &[i]));
            }
            Kind::Sys => ops.push(op(0, 1, &[])),
        }
        ops
    }

    /// The cycles an instruction takes in this configuration.
    pub fn cycles(self, key: Key) -> u32 {
        let (n, pc2) = (key.n as u32, key.p2 as u32);
        let n_ext = n.saturating_sub(1);
        let mut busy = Busy::default();
        let ext_fetches = if self.fetch == Fetch::Wide {
            // parcels at pc+2...; the opcode's 32-bit word also held pc+2 if
            // pc is aligned
            let need = if pc2 == 0 {
                n_ext.saturating_sub(1)
            } else {
                n_ext
            };
            need.div_ceil(2)
        } else {
            n_ext
        };
        busy.take(B, 0, ext_fetches);
        let ops = self.body(key.kind);
        let (end, pc_ready) = schedule(&ops, ext_fetches, &mut busy);
        let t = end
            .iter()
            .copied()
            .max()
            .unwrap_or(ext_fetches)
            .max(ext_fetches + 1);
        let nonseq = matches!(
            key.kind,
            Kind::Jmp { .. }
                | Kind::Jmpm { .. }
                | Kind::Call { .. }
                | Kind::Callm { .. }
                | Kind::Ret
                | Kind::Rti
                | Kind::Trap
                | Kind::Irq
                | Kind::Br { taken: 1.., .. }
        );
        match self.fetch {
            Fetch::Separate => 1 + t,
            Fetch::Overlap => {
                // the opcode fetch must fall in the last cycle (IR is reloaded then)
                let ready = pc_ready.unwrap_or(0);
                if !busy.bus(t - 1) && ready < t {
                    t
                } else {
                    t.max(ready) + 1
                }
            }
            Fetch::Wide => {
                // the next parcel already buffered?
                if !nonseq && (pc2 + 2 * n) % 4 == 2 {
                    return t;
                }
                let mut f = ext_fetches.max(pc_ready.unwrap_or(0));
                while busy.bus(f) {
                    f += 1;
                }
                t.max(f + 1)
            }
        }
    }
}
