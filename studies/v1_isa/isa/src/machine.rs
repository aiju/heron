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
use crate::pages::PageStats;
use crate::sys::{Acc, PAGE_VECTOR, PRIV_VECTOR, Sys};
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
/// v1bx only: a tagged operand's check failed (studies/lisp).
pub const TAG_VECTOR: u32 = 0x18;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Isa {
    V1a,
    V1b,
    /// 1b with the experimental extensions of the Lisp study
    /// (studies/lisp/isa.md): the reserved mode E is a tagged register.
    V1bx,
    /// 1b with the system extensions of the kernel study (sys.rs).
    V1bs,
}

impl Isa {
    pub fn named(name: &str) -> Option<Isa> {
        match name {
            "v1a" => Some(Isa::V1a),
            "v1b" => Some(Isa::V1b),
            "v1bx" => Some(Isa::V1bx),
            "v1bs" => Some(Isa::V1bs),
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

/// Everything outside the CPU's own RAM, for a machine on the system bus
/// (studies/system) instead of the simulator's I/O page. Accesses go to
/// it as the 16-bit CPU card makes them: transfers of a halfword, a word
/// being two (the low half first), with byte enables.
pub trait Bus: Send + Sync {
    /// Where an address is the CPU's own RAM: its offset in RAM, or None
    /// for an address on the bus.
    fn local(&self, a: u32) -> Option<u32>;
    /// One transfer at an even address: `be` bit 0 enables the low byte,
    /// bit 1 the high byte. A read returns the halfword, a write `data`'s
    /// enabled bytes; None is a bus error (an empty slot, a timeout).
    fn transfer(&mut self, a: u32, write: bool, be: u8, data: u16, cycles: u64) -> Option<u16>;
    /// Whether an interrupt is requested, `cycles` into the run.
    fn irq(&mut self, cycles: u64) -> bool;
    /// HALT with interrupts on: the cycle count at which one is next
    /// requested, or None if none ever will be.
    fn wait_irq(&mut self, cycles: u64) -> Option<u64>;
    /// What a device holds at the end, by name ("uart", "cf", "mem").
    fn dump(&self, what: &str) -> Option<Vec<u8>>;
}

/// Where a data address goes.
enum Place {
    Ram(u32),
    Bus,
}

/// What a decoded address holds: the instruction and its length. The
/// cache is by physical address; `vpc` is the address it was decoded at,
/// which relative targets were worked out from.
#[derive(Clone, Copy)]
struct Decoded {
    insn: Insn,
    n: u32,
    vpc: u32,
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
    /// v1bs's system state (sys.rs); None for the other ISAs.
    pub sys: Option<Box<Sys>>,
    /// Page reference statistics, when a tool has turned them on.
    pub pages: Option<Box<PageStats>>,
    /// The system bus, instead of the I/O page (see [`Bus`]).
    pub bus: Option<Box<dyn Bus>>,
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
            sys: (isa == Isa::V1bs).then(|| Box::new(Sys::new())),
            pages: None,
            bus: None,
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

    /// The 16-bit parcel at an address, for instruction fetch (through
    /// the map in v1bs user mode).
    pub fn parcel(&self, addr: u32) -> Res<u32> {
        let addr = self.fetch_phys(addr)?;
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

    /// Where a (physical) data address goes: without a bus, RAM as it is.
    fn place(&self, a: u32) -> Place {
        match &self.bus {
            None => Place::Ram(a),
            Some(b) => match b.local(a) {
                Some(l) => Place::Ram(l & (RAM_SIZE - 1)),
                None => Place::Bus,
            },
        }
    }

    fn bus_error<T>(a: u32) -> Res<T> {
        crate::insn::trap(ADDR_VECTOR, true, &format!("bus error at {a:08X}"))
    }

    /// A read of `size` bytes on the bus: halfword transfers.
    fn bus_read(&mut self, a: u32, size: u32) -> Res<u32> {
        let cycles = self.cycles;
        let bus = self.bus.as_mut().expect("a bus");
        let mut v = 0u32;
        for h in 0..size.div_ceil(2) {
            let be = if size == 1 { 1 << (a & 1) } else { 3 };
            match bus.transfer((a & !1) + 2 * h, false, be, 0, cycles) {
                Some(d) => v |= (d as u32) << (16 * h),
                None => return Self::bus_error(a),
            }
        }
        if size == 1 {
            v = (v >> (8 * (a & 1))) & 0xFF;
        }
        Ok(v)
    }

    /// A write of `size` bytes on the bus. A byte goes out on both lanes,
    /// as the CPU's store data does.
    fn bus_write(&mut self, a: u32, size: u32, v: u32) -> Res<()> {
        let cycles = self.cycles;
        let bus = self.bus.as_mut().expect("a bus");
        for h in 0..size.div_ceil(2) {
            let (be, d) = if size == 1 {
                (1 << (a & 1), (v & 0xFF) as u16 * 0x101)
            } else {
                (3, (v >> (16 * h)) as u16)
            };
            if bus
                .transfer((a & !1) + 2 * h, true, be, d, cycles)
                .is_none()
            {
                return Self::bus_error(a);
            }
        }
        Ok(())
    }

    fn bad<T>(&self, a: u32) -> Res<T> {
        Err(Stop::Error(format!(
            "access to unmapped address {a:08X} at pc {:08X}",
            self.pc
        )))
    }

    pub fn rd8(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 1;
        let a = self.data_phys(a, Acc::Load)?;
        let a = match self.place(a) {
            Place::Ram(l) => l,
            Place::Bus => return self.bus_read(a, 1),
        };
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
        let a = self.data_phys(a, Acc::Load)?;
        let a = match self.place(a) {
            Place::Ram(l) => l,
            Place::Bus => return self.bus_read(a, 2),
        };
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
        let a = self.data_phys(a, Acc::Load)?;
        let a = match self.place(a) {
            Place::Ram(l) => l,
            Place::Bus => return self.bus_read(a, 4),
        };
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
        let a = self.data_phys(a, Acc::Store)?;
        let a = match self.place(a) {
            Place::Ram(l) => l,
            Place::Bus => return self.bus_write(a, 1, v),
        };
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
        let a = self.data_phys(a, Acc::Store)?;
        let a = match self.place(a) {
            Place::Ram(l) => l,
            Place::Bus => return self.bus_write(a, 2, v),
        };
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
        let a = self.data_phys(a, Acc::Store)?;
        let a = match self.place(a) {
            Place::Ram(l) => l,
            Place::Bus => return self.bus_write(a, 4, v),
        };
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

    /// Decode the instruction at pc, whose first parcel is at physical
    /// address ppc, and remember it. In v1bs an instruction that straddles
    /// a page boundary isn't remembered: its pages may be mapped apart.
    fn decode(&mut self, pc: u32, ppc: u32) -> Res<Decoded> {
        let (insn, n) = match self.isa {
            Isa::V1a => v1a::decode(self, pc)?,
            Isa::V1b | Isa::V1bx | Isa::V1bs => v1b::decode(self, pc)?,
        };
        let d = Decoded { insn, n, vpc: pc };
        let last = pc.wrapping_add(2 * (n - 1));
        if self.sys.is_some() && (last ^ pc) >> crate::sys::PAGE_SHIFT != 0 {
            return Ok(d);
        }
        let s = (ppc >> 1) as usize;
        if self.slot[s] == NONE {
            self.slot[s] = self.decoded.len() as u32;
            self.decoded.push(d);
        } else {
            self.decoded[self.slot[s] as usize] = d;
        }
        let half = RAM_SIZE >> 1;
        for i in 0..n {
            self.code[(((ppc >> 1) + i) & (half - 1)) as usize] = true;
        }
        Ok(d)
    }

    /// The instruction at pc and the physical address of its first parcel.
    fn fetch(&mut self, pc: u32) -> Res<(Decoded, u32)> {
        if pc & 1 != 0 {
            return Err(Stop::Error(format!("odd PC {pc:08X}")));
        }
        let ppc = self.fetch_phys(pc)?;
        let s = self.slot.get((ppc >> 1) as usize).copied().unwrap_or(NONE);
        if s != NONE && ppc < RAM_SIZE {
            let d = self.decoded[s as usize];
            if d.vpc == pc {
                return Ok((d, ppc));
            }
        }
        Ok((self.decode(pc, ppc)?, ppc))
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
        if let Some(p) = self.pages.as_deref_mut() {
            p.fetch(pc);
        }
        let mut i_before = self.i;
        // the key, and the (physical) address its cycles are counted at; a
        // fetch that faults is counted at the page-fault vector
        let (key, at) = match self.fetch(pc) {
            Err(Stop::Error(e)) => return Err(e),
            Err(Stop::Trap(t)) => {
                self.take_trap(pc, t)?;
                (Key::new(1, pc, Kind::Trap), PAGE_VECTOR)
            }
            Ok((d, ppc)) => match self.exec(d.insn, pc, d.n) {
                Ok(key) => (key, ppc),
                Err(Stop::Error(e)) => return Err(e),
                Err(Stop::Trap(t)) => {
                    self.take_trap(pc, t)?;
                    (Key::new(d.n, pc, Kind::Trap), ppc)
                }
            },
        };
        self.cycles += self.count(at, key) as u64;
        self.instructions += 1;
        let sp = self.r[15];
        if sp < self.min_sp && sp != 0 {
            self.min_sp = sp;
        }
        if self.bus.is_some() {
            return self.bus_interrupts(key, i_before);
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

    /// After an instruction on a system bus machine: wait in HALT for an
    /// interrupt, and take one if it's due (the same rules as the I/O
    /// page's timer).
    fn bus_interrupts(&mut self, key: Key, mut i_before: u8) -> Result<(), String> {
        let bus = self.bus.as_mut().expect("a bus");
        if self.halted
            && self.i != 0
            && let Some(c) = bus.wait_irq(self.cycles)
        {
            self.cycles = self.cycles.max(c);
            self.halted = false;
            i_before = 1;
        }
        let enabled = if key.kind == Kind::Rti {
            self.in_trap = false;
            self.i
        } else {
            i_before
        };
        let bus = self.bus.as_mut().expect("a bus");
        if enabled != 0 && !self.halted && bus.irq(self.cycles) {
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
        }
        Ok(())
    }

    /// Take a trap raised by the instruction at pc.
    fn take_trap(&mut self, pc: u32, t: crate::insn::Trap) -> Result<(), String> {
        if let Some((far, fsr)) = t.page {
            let sys = self.sys.as_mut().unwrap();
            sys.far = far;
            sys.fsr = fsr;
            sys.page_faults += 1;
        } else if t.vector != SWI_VECTOR {
            let what = if t.why.is_empty() {
                trap_name(t.vector).to_string()
            } else {
                t.why.clone()
            };
            self.traps.push((pc, what));
        }
        self.in_trap = true;
        let ret = if t.fault { pc } else { self.pc };
        self.enter(t.vector, ret)
    }

    /// Turn on page reference statistics, with pages of 2^shift bytes.
    pub fn start_page_stats(&mut self, shift: u32) {
        self.pages = Some(Box::new(PageStats::new(shift)));
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
        PRIV_VECTOR => "privilege violation",
        PAGE_VECTOR => "page fault",
        _ => "trap",
    }
}
