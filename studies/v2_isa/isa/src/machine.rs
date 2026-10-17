//! The draft 2 machine: draft 1's (studies/v1_isa/isa/src/machine.rs), with
//! 1 MB of RAM, the I/O page and sixteen registers, all of them general,
//! and the instruction-level simulator that runs it.
//!
//! [`Machine::new_system`] makes it in system mode instead: RFC 0029's
//! supervisor, register banks, address space and exceptions ([`crate::sys`]),
//! with RAM of a given size at physical address 0 and a [`Bus`] for the
//! rest of the physical space. Decoded instructions are then kept by
//! physical address, and the PC's page is translated once until it
//! changes, as RFC 0029's PC page register does.
//!
//! I/O page at 0xFFFFFF00 (32-bit registers; RFC 0004, 26):
//!   +00  R: console input byte, or -1     W: console output (low byte)
//!   +04  R: bit 0 = input waiting, bit 1 = end of input
//!   +08  R/W: timer period in cycles (0 = off)
//!   +0C  R: timer flag                    W: acknowledge
//!   +10  R: cycle counter

use std::collections::HashMap;

use crate::decode;
use crate::insn::{Insn, Res, Stop, fault_at, misaligned};
use crate::key::{Key, Kind};
use crate::sys::{Access, Bus, Sys, VEC_BUS, VEC_PAGE, VEC_TRACE, irq_vector};
use crate::timing::Config;

pub const RAM_SIZE: u32 = 0x10_0000;
pub const IO_BASE: u32 = 0xFFFF_FF00;

pub const RESET_VECTOR: u32 = 0x00;
pub const IRQ_VECTOR: u32 = 0x04;
pub const ILLEGAL_VECTOR: u32 = 0x08;
pub const SWI_VECTOR: u32 = 0x0C;
pub const DIV_VECTOR: u32 = 0x10;
pub const ADDR_VECTOR: u32 = 0x14;
/// A tagged operation's check failed.
pub const TAG_VECTOR: u32 = 0x18;

/// The console, the timer and the cycle counter.
///
/// The console's input is all there from the start, as for a program's
/// run, unless its line is `open`: then more may come (`send`) until it's
/// closed (`close`), as at a terminal. A read of +00 with nothing waiting
/// on an open line waits for input: the instruction stops before it
/// happens (`Stop::Wait`), the machine is `waiting`, and the instruction
/// runs again at the next step. +04 reads 0 meanwhile.
#[derive(Default)]
pub struct Devices {
    pub out: Vec<u8>,
    pub inp: Vec<u8>,
    pub pos: usize,
    pub timer_period: u64,
    pub timer_next: u64,
    pub timer_flag: u32,
    pub open: bool,
    /// A read waited for input, and none has come since.
    pub waiting: bool,
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

    /// A register's value, or None for a read that waits for input.
    fn read(&mut self, reg: u32, cycles: u64) -> Option<u32> {
        Some(match reg {
            0x00 => match self.inp.get(self.pos) {
                Some(&b) => {
                    self.pos += 1;
                    b as u32
                }
                None if self.open => return None,
                None => 0xFFFF_FFFF,
            },
            0x04 => {
                if self.pos < self.inp.len() {
                    1
                } else if self.open {
                    0
                } else {
                    2
                }
            }
            0x08 => self.timer_period as u32,
            0x0C => self.timer_flag,
            0x10 => cycles as u32,
            _ => 0,
        })
    }

    /// More console input, on an open line.
    pub fn send(&mut self, bytes: &[u8]) {
        self.inp.extend_from_slice(bytes);
        self.waiting = false;
    }

    /// The end of the console's input: past what's there, reads read -1.
    pub fn close(&mut self) {
        self.open = false;
        self.waiting = false;
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

/// What a decoded address holds: the instruction and its length, and the
/// virtual address it was decoded at (its PC-relative operands depend on
/// it).
#[derive(Clone, Copy)]
struct Decoded {
    insn: Insn,
    n: u32,
    va: u32,
}

/// Why [`Machine::run_system`] returned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunStatus {
    /// HALT with interrupts off: stopped until reset.
    Halted,
    /// HALT with interrupts on, and nothing on the board will interrupt
    /// until something from outside (input) comes.
    Idle,
    /// The cycle count reached the limit.
    Limit,
    /// The step count ran out.
    Steps,
}

/// System mode has no console of the I/O page to wait for.
const SYSTEM_WAIT: &str = "a console wait in system mode";

/// Traps (all but SWI) kept for `traps` in system mode, where an operating
/// system takes them all the time.
const SYSTEM_TRAPS_KEPT: usize = 1000;

/// Executions of one (instruction address, timing key), with the key's
/// cycles in the reference configuration.
struct Count {
    key: Key,
    ref_cycles: u32,
    count: u64,
}

const NONE: u32 = u32::MAX;

pub struct Machine {
    pub mem: Vec<u8>,
    pub dev: Devices,
    pub r: [u32; 16],
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
    /// System mode (RFC 0029), or None for the machine around the
    /// instructions.
    pub sys: Option<Box<Sys>>,
    /// Cycles spent waiting in HALT, in system mode.
    pub idle_cycles: u64,
}

impl Machine {
    /// A machine with `image` in RAM from address 0 and `inp` as console
    /// input. Every register starts at zero.
    pub fn new(image: &[u8], inp: &[u8], reference: Config) -> Machine {
        let mut mem = vec![0u8; RAM_SIZE as usize];
        let n = image.len().min(mem.len());
        mem[..n].copy_from_slice(&image[..n]);
        let half = (RAM_SIZE / 2) as usize;
        Machine {
            mem,
            dev: Devices {
                inp: inp.to_vec(),
                ..Devices::default()
            },
            r: [0; 16],
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
            sys: None,
            idle_cycles: 0,
        }
    }

    /// A machine in system mode (RFC 0029): `ram_size` bytes of RAM at
    /// physical address 0, all zero, and `bus` for the rest of the
    /// physical space. It starts as reset leaves it: supervisor mode, bank
    /// 0, I and T clear, IPL, ctx and bank 0, at the reset vector,
    /// 0x8000_0000 (physical 0).
    pub fn new_system(ram_size: u32, bus: Box<dyn Bus>, reference: Config) -> Machine {
        let ram_size = ram_size.next_multiple_of(4096);
        let mut m = Machine::new(&[], b"", reference);
        let half = (ram_size / 2) as usize;
        m.mem = vec![0u8; ram_size as usize];
        m.slot = vec![NONE; half];
        m.code = vec![false; half];
        m.count_slot = vec![NONE; half];
        m.sys = Some(Box::new(Sys::new(ram_size, bus)));
        m.pc = crate::sys::VEC_BASE;
        m
    }

    /// The system state; panics on a machine without one.
    pub fn sys(&self) -> &Sys {
        self.sys.as_ref().expect("system mode")
    }

    pub fn sys_mut(&mut self) -> &mut Sys {
        self.sys.as_mut().expect("system mode")
    }

    // ---- memory

    /// The 16-bit parcel at an address, for instruction fetch. In system
    /// mode the address is virtual, and translated as a fetch.
    pub fn parcel(&self, addr: u32) -> Res<u32> {
        if let Some(s) = &self.sys {
            let pa = match s.translate(addr, Access::Fetch) {
                Ok(pa) => pa,
                Err(fsr) => return fault_at(VEC_PAGE, addr, fsr),
            };
            if pa as u64 + 1 >= s.ram_size as u64 {
                return Err(Stop::Error(format!(
                    "instruction fetch from {addr:08X} (physical {pa:08X}), outside RAM"
                )));
            }
            let a = pa as usize;
            return Ok(self.mem[a] as u32 | (self.mem[a + 1] as u32) << 8);
        }
        if addr as u64 + 1 >= RAM_SIZE as u64 {
            return Err(Stop::Error(format!(
                "instruction fetch from {addr:08X}, outside RAM"
            )));
        }
        let a = addr as usize;
        Ok(self.mem[a] as u32 | (self.mem[a + 1] as u32) << 8)
    }

    fn io_read(&mut self, a: u32, size: u32) -> Res<u32> {
        let reg = (a - IO_BASE) & !3;
        let shift = 8 * (a & 3);
        let Some(v) = self.dev.read(reg, self.cycles) else {
            return Err(Stop::Wait);
        };
        Ok(((v as u64 >> shift) & ((1u64 << (8 * size)) - 1)) as u32)
    }

    fn io_write(&mut self, a: u32, v: u32) {
        self.dev.write((a - IO_BASE) & !3, v, self.cycles);
    }

    fn bad<T>(&self, a: u32) -> Res<T> {
        Err(Stop::Error(format!(
            "access to unmapped address {a:08X} at pc {:08X}",
            self.pc
        )))
    }

    /// A translated read in system mode: RAM, or the bus.
    fn rd_system(&mut self, a: u32, size: u32) -> Res<u32> {
        let s = self.sys.as_mut().unwrap();
        let pa = match s.translate(a, Access::Load) {
            Ok(pa) => pa,
            Err(fsr) => return fault_at(VEC_PAGE, a, fsr),
        };
        if pa < s.ram_size {
            let p = pa as usize;
            return Ok(match size {
                1 => self.mem[p] as u32,
                2 => self.mem[p] as u32 | (self.mem[p + 1] as u32) << 8,
                _ => u32::from_le_bytes(self.mem[p..p + 4].try_into().unwrap()),
            });
        }
        s.touched();
        match s.bus.read(pa, size, self.cycles) {
            Some(v) => Ok(v),
            None => fault_at(VEC_BUS, a, 0),
        }
    }

    /// A translated write in system mode.
    fn wr_system(&mut self, a: u32, size: u32, v: u32) -> Res<()> {
        let s = self.sys.as_mut().unwrap();
        let pa = match s.translate(a, Access::Store) {
            Ok(pa) => pa,
            Err(fsr) => return fault_at(VEC_PAGE, a, fsr),
        };
        if pa < s.ram_size {
            let h = (pa >> 1) as usize;
            if self.code[h] || (size == 4 && self.code[h + 1]) {
                self.forget_code_page(pa);
            }
            let p = pa as usize;
            match size {
                1 => self.mem[p] = v as u8,
                2 => self.mem[p..p + 2].copy_from_slice(&(v as u16).to_le_bytes()),
                _ => self.mem[p..p + 4].copy_from_slice(&v.to_le_bytes()),
            }
            return Ok(());
        }
        s.touched();
        if s.bus.write(pa, size, v, self.cycles) {
            Ok(())
        } else {
            fault_at(VEC_BUS, a, 0)
        }
    }

    /// A store hit decoded code in system mode: forget the decodes in its
    /// page.
    fn forget_code_page(&mut self, pa: u32) {
        let first = ((pa & !0xFFF) >> 1) as usize;
        let last = (first + 2048).min(self.slot.len());
        self.slot[first..last].fill(NONE);
        self.code[first..last].fill(false);
    }

    pub fn rd8(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 1;
        if self.sys.is_some() {
            return self.rd_system(a, 1);
        }
        if a < RAM_SIZE {
            return Ok(self.mem[a as usize] as u32);
        }
        if a >= IO_BASE {
            return self.io_read(a, 1);
        }
        self.bad(a)
    }

    pub fn rd16(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 2;
        if a & 1 != 0 {
            return misaligned("half read", a);
        }
        if self.sys.is_some() {
            return self.rd_system(a, 2);
        }
        if a < RAM_SIZE {
            let a = a as usize;
            return Ok(self.mem[a] as u32 | (self.mem[a + 1] as u32) << 8);
        }
        if a >= IO_BASE {
            return self.io_read(a, 2);
        }
        self.bad(a)
    }

    pub fn rd32(&mut self, a: u32) -> Res<u32> {
        self.data_bytes += 4;
        if a & 3 != 0 {
            return misaligned("word read", a);
        }
        if self.sys.is_some() {
            return self.rd_system(a, 4);
        }
        if a < RAM_SIZE {
            let a = a as usize;
            return Ok(u32::from_le_bytes(self.mem[a..a + 4].try_into().unwrap()));
        }
        if a >= IO_BASE {
            return self.io_read(a, 4);
        }
        self.bad(a)
    }

    pub fn wr8(&mut self, a: u32, v: u32) -> Res<()> {
        self.data_bytes += 1;
        if self.sys.is_some() {
            return self.wr_system(a, 1, v & 0xFF);
        }
        if a < RAM_SIZE {
            if self.code[(a >> 1) as usize] {
                self.flush();
            }
            self.mem[a as usize] = v as u8;
            return Ok(());
        }
        if a >= IO_BASE {
            self.io_write(a, v & 0xFF);
            return Ok(());
        }
        self.bad(a)
    }

    pub fn wr16(&mut self, a: u32, v: u32) -> Res<()> {
        self.data_bytes += 2;
        if a & 1 != 0 {
            return misaligned("half write", a);
        }
        if self.sys.is_some() {
            return self.wr_system(a, 2, v & 0xFFFF);
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
            self.io_write(a, v & 0xFFFF);
            return Ok(());
        }
        self.bad(a)
    }

    pub fn wr32(&mut self, a: u32, v: u32) -> Res<()> {
        self.data_bytes += 4;
        if a & 3 != 0 {
            return misaligned("word write", a);
        }
        if self.sys.is_some() {
            return self.wr_system(a, 4, v);
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
            self.io_write(a, v);
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

    /// Decode the instruction at pc and remember it.
    fn decode(&mut self, pc: u32) -> Result<Decoded, String> {
        let (insn, n) = decode::decode(self, pc).map_err(|e| match e {
            Stop::Error(e) => e,
            Stop::Trap(t) => t.why,
            Stop::Wait => format!("a console wait decoding at {pc:08X}"),
        })?;
        let d = Decoded { insn, n, va: pc };
        let s = (pc >> 1) as usize;
        if self.slot[s] == NONE {
            self.slot[s] = self.decoded.len() as u32;
            self.decoded.push(d);
        } else {
            self.decoded[self.slot[s] as usize] = d;
        }
        let half = RAM_SIZE >> 1;
        for i in 0..n {
            self.code[(((pc >> 1) + i) & (half - 1)) as usize] = true;
        }
        Ok(d)
    }

    /// The instruction at pc.
    fn fetch(&mut self, pc: u32) -> Result<Decoded, String> {
        if pc & 1 != 0 {
            return Err(format!("odd PC {pc:08X}"));
        }
        if pc >= RAM_SIZE {
            return Err(format!("instruction fetch from {pc:08X}, outside RAM"));
        }
        match self.slot[(pc >> 1) as usize] {
            NONE => self.decode(pc),
            s => Ok(self.decoded[s as usize]),
        }
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

    /// The instruction at virtual address pc in system mode, and its
    /// physical address. A decode is kept by physical address unless the
    /// instruction runs into the next page, whose translation may change.
    fn fetch_system(&mut self, pc: u32) -> Res<(Decoded, u32)> {
        let s = self.sys.as_mut().unwrap();
        let pa = if s.pc_valid && s.pc_vpage == pc >> 12 {
            s.pc_ppage | (pc & 0xFFF)
        } else {
            let pa = match s.translate(pc, Access::Fetch) {
                Ok(pa) => pa,
                Err(fsr) => return fault_at(VEC_PAGE, pc, fsr),
            };
            if pa >= s.ram_size {
                return Err(Stop::Error(format!(
                    "instruction fetch from {pc:08X} (physical {pa:08X}), outside RAM"
                )));
            }
            (s.pc_vpage, s.pc_ppage, s.pc_valid) = (pc >> 12, pa & !0xFFF, true);
            pa
        };
        let h = (pa >> 1) as usize;
        if let Some(&i) = self.slot.get(h)
            && i != NONE
        {
            let d = self.decoded[i as usize];
            if d.va == pc {
                return Ok((d, pa));
            }
        }
        let (insn, n) = decode::decode(self, pc)?;
        let d = Decoded { insn, n, va: pc };
        if (pc & 0xFFF) + 2 * n <= 0x1000 {
            if self.decoded.len() >= 1 << 22 {
                self.flush();
            }
            if self.slot[h] == NONE {
                self.slot[h] = self.decoded.len() as u32;
                self.decoded.push(d);
            } else {
                self.decoded[self.slot[h] as usize] = d;
            }
            self.code[h..h + n as usize].fill(true);
        }
        Ok((d, pa))
    }

    /// Execute one instruction in system mode, then take a trace exception
    /// or an interrupt if one is due. A machine waiting in HALT doesn't
    /// come here (see run_system).
    fn step_system(&mut self) -> Result<(), String> {
        let pc = self.pc;
        let i_before = self.i;
        let t_before = self.sys().t;
        let (key, ppc, trapped) = match self.fetch_system(pc) {
            Ok((d, ppc)) => match self.exec(d.insn, pc, d.n) {
                Ok(key) => (key, ppc, false),
                Err(Stop::Error(e)) => return Err(e),
                Err(Stop::Wait) => return Err(SYSTEM_WAIT.into()),
                Err(Stop::Trap(t)) => {
                    self.take_trap_system(pc, t)?;
                    (Key::new(d.n, pc, Kind::Trap), ppc, true)
                }
            },
            Err(Stop::Error(e)) => return Err(e),
            Err(Stop::Wait) => return Err(SYSTEM_WAIT.into()),
            Err(Stop::Trap(t)) => {
                // a fault fetching the instruction: no physical address to
                // count it at, so it counts with the interrupts
                self.take_trap_system(pc, t)?;
                self.cycles += self.ref_cycles(Key::new(1, pc, Kind::Trap)) as u64;
                self.instructions += 1;
                return Ok(());
            }
        };
        self.cycles += self.count(ppc, key) as u64;
        self.instructions += 1;
        if t_before != 0 && !trapped {
            self.enter_system(VEC_TRACE, self.pc, None)?;
            self.cycles += self.ref_cycles(Key::new(1, pc, Kind::Trap)) as u64;
        }
        let enabled = if trapped {
            false
        } else if key.kind == Kind::Rti {
            self.i != 0
        } else {
            i_before != 0
        };
        if enabled {
            self.poll_irq();
            if let Some(l) = self.sys().pending() {
                self.interrupt(l)?;
            }
        }
        Ok(())
    }

    /// Ask the bus for the interrupt lines if they may have changed.
    fn poll_irq(&mut self) {
        let cycles = self.cycles;
        let s = self.sys.as_mut().unwrap();
        if cycles >= s.irq_next {
            (s.irq_mask, s.irq_next) = s.bus.irq(cycles);
        }
    }

    /// Take an interrupt at level l, 1-8 (RFC 0029, 7): its handler runs
    /// at IPL l.
    fn interrupt(&mut self, l: u32) -> Result<(), String> {
        let s = self.sys_mut();
        s.waiting = false;
        s.interrupts[l as usize - 1] += 1;
        self.irqs += 1;
        self.enter_system(irq_vector(l), self.pc, Some(l as u8))?;
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
        Ok(())
    }

    /// Take a trap raised by the instruction at pc, in system mode: `far`
    /// and `fsr` for a fault at an address, then the exception.
    fn take_trap_system(&mut self, pc: u32, t: crate::insn::Trap) -> Result<(), String> {
        if t.vector < crate::sys::VEC_SWI && self.traps.len() < SYSTEM_TRAPS_KEPT {
            let what = if t.why.is_empty() {
                trap_name_system(t.vector, t.fsr)
            } else {
                t.why.clone()
            };
            self.traps.push((pc, what));
        }
        if let Some(a) = t.far {
            let s = self.sys_mut();
            s.far = a;
            if t.vector == VEC_PAGE {
                s.fsr = t.fsr;
            }
        }
        let ret = if t.fault { pc } else { self.pc };
        self.enter_system(t.vector, ret, None)
    }

    /// Enter an exception in system mode; failing to (bank 0's sp outside
    /// the window, say) ends the simulation (RFC 0029, 6: open).
    fn enter_system(&mut self, offset: u32, ret: u32, ipl: Option<u8>) -> Result<(), String> {
        self.enter_exception(offset, ret, ipl).map_err(|e| match e {
            Stop::Error(e) => e,
            Stop::Wait => SYSTEM_WAIT.into(),
            Stop::Trap(t) => format!(
                "{} at {:08X} while entering the exception at vector offset {offset:#X}",
                trap_name_system(t.vector, t.fsr),
                t.far.unwrap_or(0)
            ),
        })
    }

    /// Run a machine in system mode until the cycle count reaches
    /// `until`, or for at most `steps` instructions, or until it halts or
    /// waits in HALT with nothing on the board to wake it. Waiting in HALT
    /// skips the cycles to the board's next event.
    pub fn run_system(&mut self, until: u64, steps: u64) -> Result<RunStatus, String> {
        let mut n = 0;
        loop {
            if self.halted {
                return Ok(RunStatus::Halted);
            }
            if self.sys().waiting {
                let cycles = self.cycles;
                let s = self.sys.as_mut().unwrap();
                (s.irq_mask, s.irq_next) = s.bus.irq(cycles);
                if let Some(l) = s.pending() {
                    self.interrupt(l)?;
                    continue;
                }
                let next = s.irq_next;
                if next == u64::MAX {
                    return Ok(RunStatus::Idle);
                }
                let to = next.max(cycles + 1).min(until.max(cycles));
                self.idle_cycles += to - cycles;
                self.cycles = to;
                if self.cycles >= until {
                    return Ok(RunStatus::Limit);
                }
                continue;
            }
            if self.cycles >= until {
                return Ok(RunStatus::Limit);
            }
            if n >= steps {
                return Ok(RunStatus::Steps);
            }
            self.step_system()?;
            n += 1;
        }
    }

    /// Execute one instruction, and take an interrupt if one is due.
    pub fn step(&mut self) -> Result<(), String> {
        if self.sys.is_some() {
            if self.sys().waiting {
                return Ok(());
            }
            return self.step_system();
        }
        let pc = self.pc;
        let mut i_before = self.i;
        let d = self.fetch(pc)?;
        let key = match self.exec(d.insn, pc, d.n) {
            Ok(key) => key,
            Err(Stop::Error(e)) => return Err(e),
            Err(Stop::Wait) => {
                self.dev.waiting = true;
                return Ok(());
            }
            Err(Stop::Trap(t)) => {
                self.take_trap(pc, t)?;
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

    /// Take a trap raised by the instruction at pc.
    fn take_trap(&mut self, pc: u32, t: crate::insn::Trap) -> Result<(), String> {
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
        self.enter(t.vector, ret)
    }

    /// Enter an interrupt or trap; failing to (an unmapped or misaligned
    /// stack) ends the simulation.
    fn enter(&mut self, vector: u32, ret: u32) -> Result<(), String> {
        self.enter_interrupt(vector, ret).map_err(|e| match e {
            Stop::Error(e) => e,
            Stop::Trap(t) => format!("{} while entering the {} vector", t.why, trap_name(vector)),
            Stop::Wait => format!(
                "a console wait while entering the {} vector",
                trap_name(vector)
            ),
        })
    }

    /// Run until HALT, or until more than `max_cycles` cycles, or until it
    /// waits for console input.
    pub fn run(&mut self, max_cycles: u64) -> Result<(), String> {
        while !self.run_for(max_cycles, u64::MAX)? && !self.dev.waiting {}
        Ok(())
    }

    /// Run as `run` does, but for at most `steps` instructions. Returns
    /// whether the machine halted.
    pub fn run_for(&mut self, max_cycles: u64, steps: u64) -> Result<bool, String> {
        for _ in 0..steps {
            if self.halted || self.dev.waiting {
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

/// What a trap in system mode was, by its vector offset (RFC 0029, 6).
pub fn trap_name_system(vector: u32, fsr: u32) -> String {
    use crate::sys::*;
    match vector {
        VEC_PAGE => {
            let what = if fsr & FSR_FETCH != 0 {
                "fetch"
            } else if fsr & FSR_STORE != 0 {
                "store"
            } else {
                "load"
            };
            let why = if fsr & FSR_INVALID != 0 {
                "invalid page"
            } else if fsr & FSR_NOWRITE != 0 {
                "page not writable"
            } else if fsr & FSR_NOEXEC != 0 {
                "page not executable"
            } else if fsr & FSR_RANGE != 0 {
                "address between 16 MB and 2 GB"
            } else {
                "user access to the window"
            };
            let mode = if fsr & FSR_SUPER != 0 {
                " in supervisor mode"
            } else {
                ""
            };
            format!("page fault: {what}, {why}{mode}")
        }
        VEC_BUS => "bus error".into(),
        VEC_PRIV => "privilege violation".into(),
        VEC_TRACE => "trace".into(),
        _ => trap_name(vector).into(),
    }
}

pub fn trap_name(vector: u32) -> &'static str {
    match vector {
        ILLEGAL_VECTOR => "illegal instruction",
        SWI_VECTOR => "SWI",
        DIV_VECTOR => "divide error",
        ADDR_VECTOR => "address error",
        IRQ_VECTOR => "IRQ",
        TAG_VECTOR => "tag check",
        _ => "trap",
    }
}
