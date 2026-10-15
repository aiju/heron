//! Instruction profiles of draft 1b programs (studies/v1b_profile).
//!
//! A [`Profile`] is an [`Observer`] of the instruction-level simulator. For
//! every instruction it executes it records:
//!
//! - the instruction itself: its address and parcels, once per distinct
//!   code found there (code that changes, as a JIT's does, gets a new
//!   entry);
//! - executions per timing key and per cost on the draft 1b hardware: the
//!   register-transfer model (v1b-rtl) follows the simulator as a shadow
//!   and times every instruction from its fetch to the next;
//! - control flow: the edges from each instruction to the next one, with
//!   interrupts and traps marked;
//! - def-use chains of the registers (with HI) and of the flags N, Z, C and
//!   V: which instruction's result each read found, how far back, and
//!   which results were never read;
//! - data addresses of the memory operands, and inclusive costs of the
//!   functions on a call stack kept from CALL and RET.
//!
//! The results are plain data for Python (heron/bindings) to store.

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::Arc;

use v1_isa::insn::{Insn, MemOp};
use v1_isa::key::{Ea, Key, Kind};
use v1_isa::machine::{IO_BASE, Isa, Machine, Observer, RAM_SIZE};
use v1_isa::timing::CONFIGS;
use v1_isa::v1b;
use v1b_rtl::Rom;
use v1b_rtl::shadow::{Arch, Shadow, Timed};

// ---------------------------------------------------------------- hashing

/// A small multiplicative hash for integer keys (FxHash's).
#[derive(Default)]
pub struct Fx(u64);

impl Fx {
    fn add(&mut self, x: u64) {
        self.0 = (self.0.rotate_left(5) ^ x).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
}

impl Hasher for Fx {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.add(b as u64);
        }
    }
    fn write_u8(&mut self, x: u8) {
        self.add(x as u64);
    }
    fn write_u16(&mut self, x: u16) {
        self.add(x as u64);
    }
    fn write_u32(&mut self, x: u32) {
        self.add(x as u64);
    }
    fn write_u64(&mut self, x: u64) {
        self.add(x);
    }
    fn write_usize(&mut self, x: usize) {
        self.add(x as u64);
    }
}

pub type FxMap<K, V> = HashMap<K, V, BuildHasherDefault<Fx>>;

// ---------------------------------------------------------------- uses

pub const NONE: u32 = u32::MAX;
/// The hardware cost of an instruction the shadow didn't time.
pub const HW_UNKNOWN: u16 = u16::MAX;
/// Register numbers 1-15, and HI as 16.
pub const HI: u32 = 16;
pub const REGS: usize = 17;
const SP: u8 = 15;

pub const FN: u8 = 1;
pub const FZ: u8 = 2;
pub const FC: u8 = 4;
pub const FV: u8 = 8;
const NZ: u8 = FN | FZ;
const NZCV: u8 = FN | FZ | FC | FV;

/// The flags a condition code tests (cond_true).
pub fn cc_flags(cc: u8) -> u8 {
    match cc >> 1 {
        0 => FZ,
        1 => FC,
        2 => FN,
        3 => FV,
        4 => FC | FZ,
        5 => FN | FV,
        6 => FZ | FN | FV,
        _ => 0,
    }
}

/// What an instruction reads and writes: registers as bit masks (bit r for
/// r1-r15, bit 16 for HI; r0 reads as 0 and isn't counted), flags as FN,
/// FZ, FC, FV.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Uses {
    pub reads: u32,
    pub writes: u32,
    pub freads: u8,
    pub fwrites: u8,
}

impl Uses {
    fn rd(&mut self, r: u8) {
        if r != 0 {
            self.reads |= 1 << r;
        }
    }
    fn wr(&mut self, r: u8) {
        if r != 0 {
            self.writes |= 1 << r;
        }
    }
    fn stack(&mut self) {
        self.rd(SP);
        self.wr(SP);
    }
    fn mem(&mut self, m: &MemOp) {
        match m.ea {
            Ea::Abs | Ea::Pc => {}
            Ea::Idx => {
                self.rd(m.base);
                self.rd(m.index);
            }
            Ea::Pi | Ea::Pd => {
                self.rd(m.base);
                self.wr(m.base);
            }
            _ => self.rd(m.base),
        }
    }
    /// ALU function f on rd (and rs, for the register forms).
    fn alu(&mut self, f: u8, d: u8, s: Option<u8>) {
        if let Some(s) = s {
            self.rd(s);
        }
        match f {
            // MOV
            8 => {
                self.wr(d);
                self.fwrites = NZ;
            }
            // CMP
            9 => {
                self.rd(d);
                self.fwrites = NZCV;
            }
            // TST
            10 => {
                self.rd(d);
                self.fwrites = NZ;
            }
            // ADD, SUB
            0 | 2 => {
                self.rd(d);
                self.wr(d);
                self.fwrites = NZCV;
            }
            // ADC, SBC: Z is sticky
            1 | 3 => {
                self.rd(d);
                self.wr(d);
                self.fwrites = NZCV;
                self.freads = FC | FZ;
            }
            // AND, OR, XOR, BIC
            4..=7 => {
                self.rd(d);
                self.wr(d);
                self.fwrites = NZ;
            }
            // MULU, MULS, DIVU, DIVS
            11..=14 => {
                self.rd(d);
                self.wr(d);
                self.writes |= 1 << HI;
                self.fwrites = NZCV;
            }
            // DIVUL
            _ => {
                self.rd(d);
                self.reads |= 1 << HI;
                self.wr(d);
                self.writes |= 1 << HI;
                self.fwrites = NZCV;
            }
        }
    }
}

/// What an instruction reads and writes when it completes (the
/// exceptions, which depend on the data, are in `Profile::after`).
pub fn uses(insn: &Insn) -> Uses {
    let mut u = Uses::default();
    match *insn {
        Insn::Illegal | Insn::Halt | Insn::Nop | Insn::SetI { .. } | Insn::Swi { .. } => {}
        Insn::JmpReg { b } => u.rd(b),
        Insn::CallReg { b } => {
            u.rd(b);
            u.stack();
        }
        Insn::Ret | Insn::Bsr { .. } | Insn::JeaImm { call: true, .. } => u.stack(),
        Insn::JeaImm { call: false, .. } => {}
        Insn::Save { a, cnt } => {
            for i in 0..cnt {
                u.rd(a + i);
            }
            u.stack();
        }
        Insn::Restore { a, cnt } => {
            u.rd(SP);
            for i in 0..cnt {
                u.wr(a + i);
            }
            u.wr(SP);
        }
        Insn::Rti => {
            u.stack();
            u.fwrites = NZCV;
        }
        Insn::Mfsr { a, b } => {
            match b {
                0 => u.freads = NZCV,
                1 => u.reads |= 1 << HI,
                _ => {}
            }
            u.wr(a);
        }
        Insn::Mtsr { a, b } => {
            u.rd(b);
            match a {
                0 => u.fwrites = NZCV,
                1 => u.writes |= 1 << HI,
                _ => {}
            }
        }
        Insn::Mfur { a, .. } => u.wr(a),
        Insn::Mtur { b, .. } => u.rd(b),
        Insn::Set { a, cc } => {
            u.freads = cc_flags(cc);
            u.wr(a);
        }
        Insn::Unary { d, s, f } => {
            u.rd(s);
            u.wr(d);
            // NEG, RLC and RRC set C and V; RLC and RRC shift C in
            u.fwrites = if matches!(f, 1 | 4 | 5) { NZCV } else { NZ };
            if matches!(f, 4 | 5) {
                u.freads = FC;
            }
        }
        Insn::ShiftImm { d, cnt, .. } => {
            u.rd(d);
            u.wr(d);
            u.fwrites = NZ | FV | if cnt != 0 { FC } else { 0 };
        }
        Insn::ShiftReg { d, s, .. } => {
            u.rd(d);
            u.rd(s);
            u.wr(d);
            u.fwrites = NZCV;
        }
        Insn::AluRR { f, d, s } => u.alu(f, d, Some(s)),
        Insn::AluReg { f, d, rn } | Insn::AluTag { f, d, rn } => u.alu(f, d, Some(rn)),
        Insn::AluImm { f, d, .. } => u.alu(f, d, None),
        Insn::Bcc { cc, .. } => u.freads = cc_flags(cc),
        Insn::Jcc { cc, .. } => match cc {
            15 => u.stack(),
            14 => {}
            _ => u.freads = cc_flags(cc),
        },
        Insn::JeaReg { call, rn } => {
            u.rd(rn);
            if call {
                u.stack();
            }
        }
        Insn::JeaMem { call, m } => {
            u.mem(&m);
            if call {
                u.stack();
            }
        }
        Insn::St { d, m } => {
            u.rd(d);
            u.mem(&m);
        }
        Insn::LeaMem { d, m } => {
            u.mem(&m);
            u.wr(d);
        }
        Insn::Load { d, m } => {
            u.mem(&m);
            u.wr(d);
            u.fwrites = NZ;
        }
        Insn::AluMem { f, d, m } => {
            u.mem(&m);
            u.alu(f, d, None);
        }
        // draft 1a: not profiled, but harmless
        Insn::AddI { d, .. } => {
            u.rd(d);
            u.wr(d);
            u.fwrites = NZ;
        }
        Insn::Access(acc) => {
            u.rd(acc.s);
            if acc.load {
                u.wr(acc.d);
                u.fwrites = NZ;
            } else {
                u.rd(acc.d);
            }
        }
        Insn::Lea { d, s, .. } => {
            u.rd(s);
            u.wr(d);
        }
        Insn::LeaConst { d, .. } => u.wr(d),
    }
    u
}

/// The memory operand of an instruction, if it has one.
fn mem_op(insn: &Insn) -> Option<&MemOp> {
    match insn {
        Insn::JeaMem { m, .. }
        | Insn::St { m, .. }
        | Insn::Load { m, .. }
        | Insn::AluMem { m, .. } => Some(m),
        _ => None,
    }
}

/// A memory operand's address, from the registers before the instruction
/// (Machine::address, which is private).
fn address(r: &[u32; 16], m: &MemOp) -> u32 {
    let g = |i: u8| r[i as usize];
    match m.ea {
        Ea::R | Ea::Pi => g(m.base),
        Ea::Rd | Ea::Rd32 => g(m.base).wrapping_add(m.disp),
        Ea::Abs | Ea::Pc => m.disp,
        Ea::Idx => g(m.base)
            .wrapping_add(m.disp)
            .wrapping_add(g(m.index).wrapping_mul(m.scale)),
        Ea::Pd => g(m.base).wrapping_sub(m.size as u32),
    }
}

// ---------------------------------------------------------------- results

/// Executions of one timing key with one hardware cost at an instruction,
/// with the key's cycles in each of the model's configurations.
#[derive(Clone, Debug)]
pub struct KeyCount {
    pub key: Key,
    pub hw: u16,
    pub count: u64,
    pub model: [u32; 6],
}

/// One instruction: an address and the code found there.
#[derive(Clone, Debug)]
pub struct InsnStat {
    pub pc: u32,
    pub phys: u32,
    pub parcels: [u16; 3],
    pub n: u8,
    /// 0 for the first code seen at this address, then 1, 2, ... as it
    /// changes.
    pub version: u32,
    pub insn: Insn,
    pub uses: Uses,
    /// The hardware decodes it as an illegal instruction (a v1bx or v1bs
    /// extension, which the hardware doesn't implement).
    pub hw_illegal: bool,
    pub count: u64,
    pub keys: Vec<KeyCount>,
    pub irqs: u64,
    pub traps: u64,
    pub reg_defs: u64,
    pub reg_defs_used: u64,
    pub flag_defs: [u64; 4],
    pub flag_defs_used: [u64; 4],
    pub mem: u64,
    pub mem_io: u64,
    /// Outside RAM and the I/O page (a frame buffer, say).
    pub mem_other: u64,
    pub mem_min: u32,
    pub mem_max: u32,
    /// The step it first ran at.
    pub first: u64,
    /// Executions after which the shadow's registers, flags or next fetch
    /// differed from the simulator's (it should never happen).
    pub mismatches: u64,
}

/// Running totals: instructions, hardware cycles, the model's cycles in
/// each configuration.
pub const TOTALS: usize = 8;
pub type Totals = [u64; TOTALS];

#[derive(Clone, Debug, Default)]
pub struct FuncStat {
    pub calls: u64,
    /// Inclusive costs, counting a recursive function's outermost
    /// activations only.
    pub incl: Totals,
}

#[derive(Clone, Copy, Debug)]
struct Frame {
    target: u32,
    /// Where the return address is.
    sp: u32,
    start: Totals,
}

/// Edge kinds.
pub const EDGE_NEXT: u8 = 0;
pub const EDGE_IRQ: u8 = 1;
pub const EDGE_TRAP: u8 = 2;

/// Def-use state: the instruction whose result each register and flag
/// holds, whether it has been read, and when it was written.
#[derive(Clone, Copy, Debug)]
struct Flow {
    reg: [u32; REGS],
    reg_used: [bool; REGS],
    reg_time: [u64; REGS],
    flag: [u32; 4],
    flag_used: [bool; 4],
}

impl Default for Flow {
    fn default() -> Flow {
        Flow {
            reg: [NONE; REGS],
            reg_used: [false; REGS],
            reg_time: [0; REGS],
            flag: [NONE; 4],
            flag_used: [false; 4],
        }
    }
}

/// Distances from a definition to a use, in instructions: bucket k holds
/// 2^k to 2^(k+1) - 1.
pub const DIST_BUCKETS: usize = 32;

/// What `before` found, for `after`.
#[derive(Clone, Copy, Debug)]
struct Pending {
    idx: u32,
    pre_sp: u32,
    hw: Option<Timed>,
    addr: Option<u32>,
    /// A register shift by 0: C isn't written.
    shift0: bool,
    /// DIVUL overflowing: only V is written.
    divul_ovf: bool,
    phys_off: u32,
}

pub struct Profile {
    isa: Isa,
    shadow: Option<Shadow>,
    check: bool,
    /// The current instruction at each physical parcel address.
    slot: Vec<u32>,
    /// Every (pc, parcels) seen: its instruction.
    seen: FxMap<(u32, u64), u32>,
    /// The next version number at each physical address.
    versions: FxMap<u32, u32>,
    pub insns: Vec<InsnStat>,
    pending: Option<Pending>,
    /// The last instruction and how it ended (an edge kind): its edge goes
    /// to wherever the next one starts.
    last: Option<(u32, u8)>,
    pub edges: FxMap<(u32, u32, u8), u64>,
    pub flag_pairs: FxMap<(u32, u32, u8), u64>,
    /// (writer, reader, register) -> (uses, sum of distances)
    pub reg_pairs: FxMap<(u32, u32, u8), (u64, u64)>,
    pub dist: [u64; DIST_BUCKETS],
    flow: Flow,
    /// Def-use state saved at interrupt entries, restored by RTI.
    saved: Vec<Flow>,
    stack: Vec<Frame>,
    active: FxMap<u32, u32>,
    pub funcs: FxMap<u32, FuncStat>,
    pub now: Totals,
    pub steps: u64,
    pub irqs: u64,
    pub irq_hw: u64,
    pub irq_model: [u64; 6],
    irq_cycles: [u32; 6],
    pub hw_unknown: u64,
    pub mismatches: u64,
    pub shadow_errors: u64,
    pub notes: Vec<String>,
    /// Instructions before which the fetch itself failed (v1bs page faults).
    pub fetch_faults: u64,
    model_cache: FxMap<Key, [u32; 6]>,
}

const MAX_NOTES: usize = 20;
const MAX_SAVED: usize = 64;

impl Profile {
    /// A profile of a machine running `isa`; with a ROM, the hardware
    /// shadow times every instruction (`check`: and compares its results
    /// with the simulator's).
    pub fn new(isa: Isa, rom: Option<Arc<Rom>>, check: bool) -> Result<Profile, String> {
        let shadow = rom.map(Shadow::new).transpose()?;
        let irq = Key {
            n: 1,
            p2: 0,
            kind: Kind::Irq,
        };
        Ok(Profile {
            isa,
            shadow,
            check,
            slot: vec![NONE; (RAM_SIZE / 2) as usize],
            seen: FxMap::default(),
            versions: FxMap::default(),
            insns: Vec::new(),
            pending: None,
            last: None,
            edges: FxMap::default(),
            flag_pairs: FxMap::default(),
            reg_pairs: FxMap::default(),
            dist: [0; DIST_BUCKETS],
            flow: Flow::default(),
            saved: Vec::new(),
            stack: Vec::new(),
            active: FxMap::default(),
            funcs: FxMap::default(),
            now: [0; TOTALS],
            steps: 0,
            irqs: 0,
            irq_hw: 0,
            irq_model: [0; 6],
            irq_cycles: CONFIGS.map(|(_, c)| c.cycles(irq)),
            hw_unknown: 0,
            mismatches: 0,
            shadow_errors: 0,
            notes: Vec::new(),
            fetch_faults: 0,
            model_cache: FxMap::default(),
        })
    }

    pub fn has_shadow(&self) -> bool {
        self.shadow.is_some()
    }

    fn note(&mut self, s: String) {
        if self.notes.len() < MAX_NOTES {
            self.notes.push(s);
        }
    }

    /// The instruction at pc (physical address phys), found or decoded.
    fn lookup(&mut self, m: &Machine, pc: u32, phys: u32) -> Option<u32> {
        let p = phys as usize;
        if p + 6 > m.mem.len() {
            return None;
        }
        let parcel = |i: usize| m.mem[p + 2 * i] as u16 | (m.mem[p + 2 * i + 1] as u16) << 8;
        let s = (phys >> 1) as usize;
        let cur = self.slot[s];
        if cur != NONE {
            let st = &self.insns[cur as usize];
            if st.pc == pc && (0..st.n as usize).all(|i| parcel(i) == st.parcels[i]) {
                return Some(cur);
            }
        }
        let (insn, n) = match self.isa {
            Isa::V1a => v1_isa::v1a::decode(m, pc).ok()?,
            _ => v1b::decode(m, pc).ok()?,
        };
        let n = n.min(3);
        let mut parcels = [0u16; 3];
        for (i, w) in parcels.iter_mut().enumerate().take(n as usize) {
            *w = parcel(i);
        }
        let packed = n as u64
            | (parcels[0] as u64) << 2
            | (parcels[1] as u64) << 18
            | (parcels[2] as u64) << 34;
        if let Some(&idx) = self.seen.get(&(pc, packed)) {
            self.slot[s] = idx;
            return Some(idx);
        }
        let next = self.versions.entry(phys).or_default();
        let version = *next;
        *next += 1;
        let hw_illegal = self
            .shadow
            .as_ref()
            .is_some_and(|sh| sh.illegal(parcels[0] as u32));
        let idx = self.insns.len() as u32;
        self.insns.push(InsnStat {
            pc,
            phys,
            parcels,
            n: n as u8,
            version,
            insn,
            uses: uses(&insn),
            hw_illegal,
            count: 0,
            keys: Vec::new(),
            irqs: 0,
            traps: 0,
            reg_defs: 0,
            reg_defs_used: 0,
            flag_defs: [0; 4],
            flag_defs_used: [0; 4],
            mem: 0,
            mem_io: 0,
            mem_other: 0,
            mem_min: u32::MAX,
            mem_max: 0,
            first: self.steps,
            mismatches: 0,
        });
        self.seen.insert((pc, packed), idx);
        self.slot[s] = idx;
        Some(idx)
    }

    fn model(&mut self, key: Key) -> [u32; 6] {
        *self
            .model_cache
            .entry(key)
            .or_insert_with(|| CONFIGS.map(|(_, c)| c.cycles(key)))
    }

    /// Reads and writes of one execution, in the def-use chains.
    fn flow(&mut self, idx: u32, u: Uses) {
        let now = self.steps;
        // flags first: a reader usually finds them all from one writer
        if u.freads != 0 {
            let mut from: [(u32, u8); 4] = [(NONE, 0); 4];
            for f in 0..4 {
                if u.freads & (1 << f) == 0 {
                    continue;
                }
                let w = self.flow.flag[f];
                if w == NONE {
                    continue;
                }
                if !self.flow.flag_used[f] {
                    self.flow.flag_used[f] = true;
                    self.insns[w as usize].flag_defs_used[f] += 1;
                }
                if let Some(e) = from.iter_mut().find(|e| e.0 == w || e.0 == NONE) {
                    e.0 = w;
                    e.1 |= 1 << f;
                }
            }
            for &(w, mask) in from.iter().filter(|e| e.0 != NONE) {
                *self.flag_pairs.entry((w, idx, mask)).or_default() += 1;
            }
        }
        let mut reads = u.reads;
        while reads != 0 {
            let r = reads.trailing_zeros() as usize;
            reads &= reads - 1;
            let w = self.flow.reg[r];
            if w == NONE {
                continue;
            }
            let d = now - self.flow.reg_time[r];
            if !self.flow.reg_used[r] {
                self.flow.reg_used[r] = true;
                self.insns[w as usize].reg_defs_used += 1;
            }
            let e = self.reg_pairs.entry((w, idx, r as u8)).or_default();
            e.0 += 1;
            e.1 += d;
            self.dist[((63 - d.max(1).leading_zeros()) as usize).min(DIST_BUCKETS - 1)] += 1;
        }
        let mut writes = u.writes;
        let st = &mut self.insns[idx as usize];
        while writes != 0 {
            let r = writes.trailing_zeros() as usize;
            writes &= writes - 1;
            self.flow.reg[r] = idx;
            self.flow.reg_used[r] = false;
            self.flow.reg_time[r] = now;
            st.reg_defs += 1;
        }
        for f in 0..4 {
            if u.fwrites & (1 << f) != 0 {
                self.flow.flag[f] = idx;
                self.flow.flag_used[f] = false;
                st.flag_defs[f] += 1;
            }
        }
    }

    /// Close a call frame: the function's calls and inclusive costs.
    fn close(&mut self, fr: Frame) {
        let a = self.active.entry(fr.target).or_default();
        *a = a.saturating_sub(1);
        let outermost = *a == 0;
        let f = self.funcs.entry(fr.target).or_default();
        f.calls += 1;
        if outermost {
            for (i, x) in f.incl.iter_mut().enumerate() {
                *x += self.now[i] - fr.start[i];
            }
        }
    }

    /// The functions with the frames still open closed as if they returned
    /// now (`main` and whatever was running when the program stopped).
    pub fn functions(&self) -> FxMap<u32, FuncStat> {
        let mut funcs = self.funcs.clone();
        let mut active = self.active.clone();
        for fr in self.stack.iter().rev() {
            let a = active.entry(fr.target).or_default();
            *a = a.saturating_sub(1);
            let f = funcs.entry(fr.target).or_default();
            f.calls += 1;
            if *a == 0 {
                for (i, x) in f.incl.iter_mut().enumerate() {
                    *x += self.now[i] - fr.start[i];
                }
            }
        }
        funcs
    }

    /// Compare the shadow's state after an instruction with the simulator's.
    fn compare(&mut self, m: &Machine, idx: u32) {
        let Some(sh) = self.shadow.as_ref() else {
            return;
        };
        let cpu = &sh.cpu;
        let mut diffs = Vec::new();
        for r in 1..16 {
            if cpu.rf[r] != m.r[r] {
                diffs.push(format!("r{r} {:08X} not {:08X}", cpu.rf[r], m.r[r]));
            }
        }
        if cpu.rf[v1b_rtl::HI] != m.hi {
            diffs.push(format!("HI {:08X} not {:08X}", cpu.rf[v1b_rtl::HI], m.hi));
        }
        let fl = (cpu.n, cpu.z, cpu.c, cpu.v, cpu.i);
        let ml = (m.n as u32, m.z as u32, m.c as u32, m.v as u32, m.i as u32);
        if fl != ml {
            diffs.push(format!("flags NZCVI {fl:?} not {ml:?}"));
        }
        match cpu.fetched {
            Some((a, _)) if a != m.pc => diffs.push(format!("fetch {a:08X} not {:08X}", m.pc)),
            None => diffs.push("no fetch".into()),
            _ => {}
        }
        if !diffs.is_empty() {
            self.mismatches += 1;
            let st = &mut self.insns[idx as usize];
            st.mismatches += 1;
            let pc = st.pc;
            self.note(format!(
                "shadow differs after {pc:08X}: {}",
                diffs.join(", ")
            ));
        }
    }
}

impl Observer for Profile {
    fn before(&mut self, m: &Machine) {
        let pc = m.pc;
        if let Some((from, kind)) = self.last.take() {
            *self.edges.entry((from, pc, kind)).or_default() += 1;
        }
        let phys = if m.sys.is_some() {
            m.fetch_phys(pc).ok()
        } else {
            Some(pc)
        };
        let Some(idx) = phys.and_then(|p| self.lookup(m, pc, p)) else {
            self.pending = None;
            return;
        };
        let phys = phys.unwrap_or(pc);
        let st = &self.insns[idx as usize];
        let insn = st.insn;
        let addr = mem_op(&insn).map(|mo| address(&m.r, mo));
        let shift0 = matches!(insn, Insn::ShiftReg { s, .. } if m.r[s as usize] & 31 == 0);
        let divul_ovf = matches!(insn, Insn::AluRR { f: 15, s, .. }
            if m.r[s as usize] != 0 && m.hi >= m.r[s as usize]);
        let mut hw = None;
        if let Some(sh) = self.shadow.as_mut() {
            let arch = Arch {
                r: m.r,
                hi: m.hi,
                n: m.n as u32,
                z: m.z as u32,
                c: m.c as u32,
                v: m.v as u32,
                i: m.i as u32,
                pc,
            };
            match sh.time(&arch, &m.mem, phys.wrapping_sub(pc)) {
                Ok(t) => hw = Some(t),
                Err(e) => {
                    self.shadow_errors += 1;
                    self.note(format!("shadow error at {pc:08X}: {e}"));
                }
            }
        }
        self.pending = Some(Pending {
            idx,
            pre_sp: m.r[15],
            hw,
            addr,
            shift0,
            divul_ovf,
            phys_off: phys.wrapping_sub(pc),
        });
    }

    fn after(&mut self, m: &Machine, key: Key, _at: u32, irq: bool) {
        let Some(p) = self.pending.take() else {
            self.fetch_faults += 1;
            self.steps += 1;
            return;
        };
        let idx = p.idx;
        let trap = key.kind == Kind::Trap;
        // an instruction the hardware doesn't implement costs what it
        // costs only when the simulator traps on it too
        let hw = match p.hw {
            Some(t) if trap || !self.insns[idx as usize].hw_illegal => {
                t.cycles.min(HW_UNKNOWN as u32 - 1) as u16
            }
            _ => HW_UNKNOWN,
        };
        let model = self.model(key);

        // counts and costs
        {
            let st = &mut self.insns[idx as usize];
            st.count += 1;
            if let Some(k) = st.keys.iter_mut().find(|k| k.key == key && k.hw == hw) {
                k.count += 1;
            } else {
                st.keys.push(KeyCount {
                    key,
                    hw,
                    count: 1,
                    model,
                });
            }
            if trap {
                st.traps += 1;
            }
            if let (Some(a), false) = (p.addr, trap) {
                st.mem += 1;
                if a >= IO_BASE {
                    st.mem_io += 1;
                } else if a >= RAM_SIZE {
                    st.mem_other += 1;
                } else {
                    st.mem_min = st.mem_min.min(a);
                    st.mem_max = st.mem_max.max(a);
                }
            }
        }
        self.now[0] += 1;
        if hw == HW_UNKNOWN {
            self.hw_unknown += 1;
        } else {
            self.now[1] += hw as u64;
        }
        for (t, &m) in self.now[2..].iter_mut().zip(&model) {
            *t += m as u64;
        }

        // the shadow against the simulator
        if self.check
            && !irq
            && self.isa != Isa::V1bs
            && let Some(t) = p.hw
        {
            let outside = p.addr.is_some_and(|a| (RAM_SIZE..IO_BASE).contains(&a));
            if !t.io && !t.halt && !self.insns[idx as usize].hw_illegal && !outside {
                self.compare(m, idx);
            }
        }

        // def-use chains
        let st = &self.insns[idx as usize];
        let mut u = st.uses;
        if trap {
            u.writes = 0;
            u.fwrites = 0;
        } else {
            if p.shift0 {
                u.fwrites &= !FC;
            }
            if p.divul_ovf {
                u.writes = 0;
                u.fwrites = FV;
            }
        }
        let rti = !trap && matches!(st.insn, Insn::Rti);
        if rti && !self.saved.is_empty() {
            // returning from an interrupt: the interrupted code's state
            u.writes = 0;
            u.fwrites = 0;
            self.flow(idx, u);
            self.flow = self.saved.pop().unwrap_or_default();
        } else {
            self.flow(idx, u);
        }

        // control flow
        let kind = if irq {
            EDGE_IRQ
        } else if trap {
            EDGE_TRAP
        } else {
            EDGE_NEXT
        };
        self.last = Some((idx, kind));

        // calls and returns
        if !trap {
            match key.kind {
                Kind::Call { .. } | Kind::Callm { .. } => {
                    // the target, and where the return address went
                    let target = if irq { NONE } else { m.pc };
                    let sp = if irq {
                        p.pre_sp.wrapping_sub(4)
                    } else {
                        m.r[15]
                    };
                    if target != NONE {
                        *self.active.entry(target).or_default() += 1;
                        self.stack.push(Frame {
                            target,
                            sp,
                            start: self.now,
                        });
                    }
                }
                Kind::Ret => {
                    while let Some(&fr) = self.stack.last() {
                        if fr.sp > p.pre_sp {
                            break;
                        }
                        self.stack.pop();
                        self.close(fr);
                    }
                }
                _ => {}
            }
        }

        // an interrupt taken after it
        if irq {
            self.irqs += 1;
            self.insns[idx as usize].irqs += 1;
            for i in 0..6 {
                self.irq_model[i] += self.irq_cycles[i] as u64;
                self.now[2 + i] += self.irq_cycles[i] as u64;
            }
            if let (Some(sh), Some(t)) = (self.shadow.as_mut(), p.hw) {
                match sh.irq_entry(&m.mem, p.phys_off, t.halt) {
                    Ok(c) => {
                        self.irq_hw += c as u64;
                        self.now[1] += c as u64;
                    }
                    Err(e) => {
                        self.shadow_errors += 1;
                        self.note(format!("shadow error entering an interrupt: {e}"));
                    }
                }
            }
            if self.saved.len() >= MAX_SAVED {
                self.saved.remove(0);
            }
            self.saved.push(self.flow);
            self.flow = Flow::default();
        }
        self.steps += 1;
    }
}
