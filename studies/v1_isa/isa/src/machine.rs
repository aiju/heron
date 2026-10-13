//! The draft 1 machine: 1 MB of RAM, the I/O page, sixteen registers, and
//! the instruction-level simulator that runs it (the Rust version of
//! studies/v1_isa/sim32.py).
//!
//! I/O page at 0xFFFFFF00 (32-bit registers, see isa-v1.md):
//!   +00  R: console input byte, or -1     W: console output (low byte)
//!   +04  R: bit 0 = input waiting, bit 1 = end of input
//!   +08  R/W: timer period in cycles (0 = off)
//!   +0C  R: timer flag                    W: acknowledge
//!   +10  R: cycle counter

use std::collections::HashMap;

use crate::insn::{Insn, Res, Stop, misaligned};
use crate::key::{Key, Kind};
use crate::timing::Config;
use crate::{v1a, v1b};

pub const RAM_SIZE: u32 = 0x10_0000;
pub const IO_BASE: u32 = 0xFFFF_FF00;

pub const RESET_VECTOR: u32 = 0x00;
pub const IRQ_VECTOR: u32 = 0x04;
pub const ILLEGAL_VECTOR: u32 = 0x08;
pub const SWI_VECTOR: u32 = 0x0C;
pub const DIV_VECTOR: u32 = 0x10;
pub const ADDR_VECTOR: u32 = 0x14;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Isa {
    V1a,
    V1b,
}

impl Isa {
    pub fn named(name: &str) -> Option<Isa> {
        match name {
            "v1a" => Some(Isa::V1a),
            "v1b" => Some(Isa::V1b),
            _ => None,
        }
    }
}

/// The console, the timer and the cycle counter.
#[derive(Default)]
pub struct Devices {
    pub out: Vec<u8>,
    pub inp: Vec<u8>,
    pub pos: usize,
    pub timer_period: u64,
    pub timer_next: u64,
    pub timer_flag: u32,
}

impl Devices {
    fn tick(&mut self, cycles: u64) {
        if self.timer_period != 0 {
            while cycles >= self.timer_next {
                self.timer_flag = 1;
                self.timer_next += self.timer_period;
            }
        }
    }

    fn read(&mut self, reg: u32, cycles: u64) -> u32 {
        match reg {
            0x00 => match self.inp.get(self.pos) {
                Some(&b) => {
                    self.pos += 1;
                    b as u32
                }
                None => 0xFFFF_FFFF,
            },
            0x04 => {
                if self.pos < self.inp.len() {
                    1
                } else {
                    2
                }
            }
            0x08 => self.timer_period as u32,
            0x0C => self.timer_flag,
            0x10 => cycles as u32,
            _ => 0,
        }
    }

    fn write(&mut self, reg: u32, value: u32, cycles: u64) {
        match reg {
            0x00 => self.out.push(value as u8),
            0x08 => {
                self.timer_period = value as u64;
                self.timer_next = cycles + value as u64;
                if value == 0 {
                    self.timer_flag = 0;
                }
            }
            0x0C => self.timer_flag = 0,
            _ => {}
        }
    }
}

/// What a decoded address holds: the instruction and its length.
#[derive(Clone, Copy)]
struct Decoded {
    insn: Insn,
    n: u32,
}

/// Executions of one (instruction address, timing key), with the key's
/// cycles in the reference configuration.
struct Count {
    key: Key,
    ref_cycles: u32,
    count: u64,
}

const NONE: u32 = u32::MAX;

pub struct Machine {
    pub isa: Isa,
    pub mem: Vec<u8>,
    pub dev: Devices,
    pub r: [u32; 16],
    pub hi: u32,
    pub pc: u32,
    pub n: u8,
    pub z: u8,
    pub c: u8,
    pub v: u8,
    pub i: u8,
    pub halted: bool,
    /// Cycles in the reference configuration (the timer and the cycle limit
    /// follow these).
    pub cycles: u64,
    pub instructions: u64,
    /// Traps taken (all but SWI): (pc, what).
    pub traps: Vec<(u32, String)>,
    /// A trap (SWI too) was taken, and no RTI since.
    pub in_trap: bool,
    pub irqs: u64,
    pub min_sp: u32,
    pub data_bytes: u64,
    reference: Config,
    ref_cache: HashMap<Key, u32>,
    /// Decoded instructions: decoded[slot[pc / 2]].
    slot: Vec<u32>,
    decoded: Vec<Decoded>,
    /// Parcels covered by decoded instructions: a store to one forgets them
    /// all (self-modifying code).
    code: Vec<bool>,
    /// Executions per (pc, key): counts[count_slot[pc / 2]].
    count_slot: Vec<u32>,
    counts: Vec<Vec<Count>>,
    irq_count: u64,
    /// The order the (pc, key) pairs first happened in: (counts index,
    /// index in it), or None for interrupt entries.
    order: Vec<Option<(u32, u32)>>,
}

impl Machine {
    /// A machine with `image` in RAM from address 0 and `inp` as console
    /// input.
    pub fn new(isa: Isa, image: &[u8], inp: &[u8], reference: Config) -> Machine {
        let mut mem = vec![0u8; RAM_SIZE as usize];
        let n = image.len().min(mem.len());
        mem[..n].copy_from_slice(&image[..n]);
        let half = (RAM_SIZE / 2) as usize;
        Machine {
            isa,
            mem,
            dev: Devices {
                inp: inp.to_vec(),
                ..Devices::default()
            },
            r: [0; 16],
            hi: 0,
            pc: RESET_VECTOR,
            n: 0,
            z: 0,
            c: 0,
            v: 0,
            i: 0,
            halted: false,
            cycles: 0,
            instructions: 0,
            traps: Vec::new(),
            in_trap: false,
            irqs: 0,
            min_sp: u32::MAX,
            data_bytes: 0,
            reference,
            ref_cache: HashMap::new(),
            slot: vec![NONE; half],
            decoded: Vec::new(),
            code: vec![false; half],
            count_slot: vec![NONE; half],
            counts: Vec::new(),
            irq_count: 0,
            order: Vec::new(),
        }
    }

    // ---- memory

    /// The 16-bit parcel at an address, for instruction fetch.
    pub fn parcel(&self, addr: u32) -> Res<u32> {
        if addr as u64 + 1 >= RAM_SIZE as u64 {
            return Err(Stop::Error(format!(
                "instruction fetch from {addr:08X}, outside RAM"
            )));
        }
        let a = addr as usize;
        Ok(self.mem[a] as u32 | (self.mem[a + 1] as u32) << 8)
    }

    fn io(&mut self, a: u32, size: u32, value: Option<u32>) -> u32 {
        let reg = (a - IO_BASE) & !3;
        let shift = 8 * (a & 3);
        match value {
            None => {
                let v = self.dev.read(reg, self.cycles) as u64;
                ((v >> shift) & ((1u64 << (8 * size)) - 1)) as u32
            }
            Some(v) => {
                self.dev.write(reg, v, self.cycles);
                0
            }
        }
    }

    fn bad<T>(&self, a: u32) -> Res<T> {
        Err(Stop::Error(format!(
            "access to unmapped address {a:08X} at pc {:08X}",
            self.pc
        )))
    }

    pub fn rd8(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 1;
        if a < RAM_SIZE {
            return Ok(self.mem[a as usize] as u32);
        }
        if a >= IO_BASE {
            return Ok(self.io(a, 1, None));
        }
        self.bad(a)
    }

    pub fn rd16(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 2;
        if a & 1 != 0 {
            return misaligned("half read", a);
        }
        if a < RAM_SIZE {
            let a = a as usize;
            return Ok(self.mem[a] as u32 | (self.mem[a + 1] as u32) << 8);
        }
        if a >= IO_BASE {
            return Ok(self.io(a, 2, None));
        }
        self.bad(a)
    }

    pub fn rd32(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 4;
        if a & 3 != 0 {
            return misaligned("word read", a);
        }
        if a < RAM_SIZE {
            let a = a as usize;
            return Ok(u32::from_le_bytes(self.mem[a..a + 4].try_into().unwrap()));
        }
        if a >= IO_BASE {
            return Ok(self.io(a, 4, None));
        }
        self.bad(a)
    }

    pub fn wr8(&mut self, a: u32, v: u32) -> Res<()> {
        self.data_bytes += 1;
        if a < RAM_SIZE {
            if self.code[(a >> 1) as usize] {
                self.flush();
            }
            self.mem[a as usize] = v as u8;
            return Ok(());
        }
        if a >= IO_BASE {
            self.io(a, 1, Some(v & 0xFF));
            return Ok(());
        }
        self.bad(a)
    }

    pub fn wr16(&mut self, a: u32, v: u32) -> Res<()> {
        self.data_bytes += 2;
        if a & 1 != 0 {
            return misaligned("half write", a);
        }
        if a < RAM_SIZE {
            if self.code[(a >> 1) as usize] {
                self.flush();
            }
            let a = a as usize;
            self.mem[a..a + 2].copy_from_slice(&(v as u16).to_le_bytes());
            return Ok(());
        }
        if a >= IO_BASE {
            self.io(a, 2, Some(v & 0xFFFF));
            return Ok(());
        }
        self.bad(a)
    }

    pub fn wr32(&mut self, a: u32, v: u32) -> Res<()> {
        self.data_bytes += 4;
        if a & 3 != 0 {
            return misaligned("word write", a);
        }
        if a < RAM_SIZE {
            let p = (a >> 1) as usize;
            if self.code[p] || self.code[p + 1] {
                self.flush();
            }
            let a = a as usize;
            self.mem[a..a + 4].copy_from_slice(&v.to_le_bytes());
            return Ok(());
        }
        if a >= IO_BASE {
            self.io(a, 4, Some(v));
            return Ok(());
        }
        self.bad(a)
    }

    /// A store hit decoded code: forget every decode.
    fn flush(&mut self) {
        self.slot.fill(NONE);
        self.decoded.clear();
        self.code.fill(false);
    }

    // ---- execution

    fn decode(&mut self, pc: u32) -> Res<Decoded> {
        let (insn, n) = match self.isa {
            Isa::V1a => v1a::decode(self, pc)?,
            Isa::V1b => v1b::decode(self, pc)?,
        };
        let d = Decoded { insn, n };
        self.slot[(pc >> 1) as usize] = self.decoded.len() as u32;
        self.decoded.push(d);
        let half = RAM_SIZE >> 1;
        for i in 0..n {
            self.code[(((pc >> 1) + i) & (half - 1)) as usize] = true;
        }
        Ok(d)
    }

    fn ref_cycles(&mut self, key: Key) -> u32 {
        let reference = self.reference;
        *self
            .ref_cache
            .entry(key)
            .or_insert_with(|| reference.cycles(key))
    }

    /// Count one execution of `key` at `pc`, and return its reference
    /// cycles.
    fn count(&mut self, pc: u32, key: Key) -> u32 {
        let s = (pc >> 1) as usize;
        if self.count_slot[s] == NONE {
            self.count_slot[s] = self.counts.len() as u32;
            self.counts.push(Vec::new());
        }
        let i = self.count_slot[s] as usize;
        if let Some(c) = self.counts[i].iter_mut().find(|c| c.key == key) {
            c.count += 1;
            return c.ref_cycles;
        }
        let ref_cycles = self.ref_cycles(key);
        self.order
            .push(Some((i as u32, self.counts[i].len() as u32)));
        self.counts[i].push(Count {
            key,
            ref_cycles,
            count: 1,
        });
        ref_cycles
    }

    /// Execute one instruction, and take an interrupt if one is due.
    pub fn step(&mut self) -> Result<(), String> {
        let pc = self.pc;
        let s = self.slot.get((pc >> 1) as usize).copied().unwrap_or(NONE);
        let d = if s != NONE && pc & 1 == 0 && pc < RAM_SIZE {
            self.decoded[s as usize]
        } else {
            if pc & 1 != 0 {
                return Err(format!("odd PC {pc:08X}"));
            }
            self.decode(pc).map_err(|e| match e {
                Stop::Error(e) => e,
                Stop::Trap(t) => t.why, // decoders don't trap
            })?
        };
        let mut i_before = self.i;
        let key = match self.exec(d.insn, pc, d.n) {
            Ok(key) => key,
            Err(Stop::Error(e)) => return Err(e),
            Err(Stop::Trap(t)) => {
                if t.vector != SWI_VECTOR {
                    let what = if t.why.is_empty() {
                        trap_name(t.vector).to_string()
                    } else {
                        t.why.clone()
                    };
                    self.traps.push((pc, what));
                }
                self.in_trap = true;
                let ret = if t.fault { pc } else { self.pc };
                self.enter(t.vector, ret)?;
                Key::new(d.n, pc, Kind::Trap)
            }
        };
        self.cycles += self.count(pc, key) as u64;
        self.instructions += 1;
        let sp = self.r[15];
        if sp < self.min_sp && sp != 0 {
            self.min_sp = sp;
        }
        if self.dev.timer_period != 0 {
            self.dev.tick(self.cycles);
        }
        if self.halted && self.i != 0 && (self.dev.timer_flag != 0 || self.dev.timer_period != 0) {
            if self.dev.timer_flag == 0 {
                self.cycles = self.cycles.max(self.dev.timer_next);
                self.dev.tick(self.cycles);
            }
            self.halted = false;
            i_before = 1;
        }
        let enabled = if key.kind == Kind::Rti {
            self.in_trap = false;
            self.i
        } else {
            i_before
        };
        if enabled != 0 && self.dev.timer_flag != 0 && !self.halted {
            self.irqs += 1;
            self.enter(IRQ_VECTOR, self.pc)?;
            if self.irq_count == 0 {
                self.order.push(None);
            }
            self.irq_count += 1;
            let k = Key {
                n: 1,
                p2: 0,
                kind: Kind::Irq,
            };
            self.cycles += self.ref_cycles(k) as u64;
            self.dev.tick(self.cycles);
        }
        Ok(())
    }

    /// Enter an interrupt or trap; failing to (an unmapped or misaligned
    /// stack) ends the simulation.
    fn enter(&mut self, vector: u32, ret: u32) -> Result<(), String> {
        self.enter_interrupt(vector, ret).map_err(|e| match e {
            Stop::Error(e) => e,
            Stop::Trap(t) => format!("{} while entering the {} vector", t.why, trap_name(vector)),
        })
    }

    /// Run until HALT, or until more than `max_cycles` cycles.
    pub fn run(&mut self, max_cycles: u64) -> Result<(), String> {
        while !self.run_for(max_cycles, u64::MAX)? {}
        Ok(())
    }

    /// Run as `run` does, but for at most `steps` instructions. Returns
    /// whether the machine halted.
    pub fn run_for(&mut self, max_cycles: u64, steps: u64) -> Result<bool, String> {
        for _ in 0..steps {
            if self.halted {
                break;
            }
            self.step()?;
            if self.cycles > max_cycles {
                return Err(format!(
                    "cycle limit of {max_cycles} reached at pc={:08X}",
                    self.pc
                ));
            }
        }
        Ok(self.halted)
    }

    // ---- results

    /// Executions per (instruction address, timing key), in the order
    /// each first happened; interrupt entries have no address.
    pub fn pc_keys(&self) -> Vec<(Option<u32>, Key, u64)> {
        let mut pcs = vec![0; self.counts.len()];
        for (s, &i) in self.count_slot.iter().enumerate() {
            if i != NONE {
                pcs[i as usize] = 2 * s as u32;
            }
        }
        let irq = Key {
            n: 1,
            p2: 0,
            kind: Kind::Irq,
        };
        self.order
            .iter()
            .map(|o| match *o {
                Some((i, j)) => {
                    let c = &self.counts[i as usize][j as usize];
                    (Some(pcs[i as usize]), c.key, c.count)
                }
                None => (None, irq, self.irq_count),
            })
            .collect()
    }

    /// Cycles in a configuration. `shifted` costs the program as if all its
    /// code sat one parcel further on (only the wide fetch cares).
    pub fn cycles_for(&self, config: Config, shifted: bool) -> u64 {
        let mut cache = HashMap::new();
        self.pc_keys()
            .into_iter()
            .map(|(_, mut k, count)| {
                if shifted {
                    k.p2 ^= 2;
                }
                count * *cache.entry(k).or_insert_with(|| config.cycles(k)) as u64
            })
            .sum()
    }
}

pub fn trap_name(vector: u32) -> &'static str {
    match vector {
        ILLEGAL_VECTOR => "illegal instruction",
        SWI_VECTOR => "SWI",
        DIV_VECTOR => "divide error",
        ADDR_VECTOR => "address error",
        IRQ_VECTOR => "IRQ",
        _ => "trap",
    }
}
