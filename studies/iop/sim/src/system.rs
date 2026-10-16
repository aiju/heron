//! A system on RFC 0037's bus: the IOP's card and a draft 2 CPU card, the
//! CPU at instruction level (studies/v2_isa in system mode).
//!
//! The physical map is RFC 0037's (5.1):
//!
//! | Physical | What |
//! |---|---|
//! | `0x0000_0000` | region 0, the CPU card: its RAM (4 MB by default), repeated through the region for other masters |
//! | `0x4000_0000` | region 4, the IOP's shared RAM, repeated |
//! | `0x7000_0000` | the CPU card's registers, below |
//! | `0x7400_0000` | the IOP's doorbells |
//! | `0x7F00_0000` | the I/O bus's window |
//!
//! The CPU card's registers (RFC 0037, 9 and RFC 0027, 8.1 name them;
//! where they are in the card's 16 MB is this study's choice). They are
//! words; the IOP, a 16-bit master, reaches their low halves at +0:
//!
//! | Offset | |
//! |---|---|
//! | `+0x0000` | board information: +0 R the RAM's size, +4 R the clock in Hz, +8 W a byte to the simulator's debug log (not hardware), +C R boot flags |
//! | `+0x1000` | control: W bit 0 RUN, bit 1 RESET (a warm reset, taken when RUN is next set), bit 2 STEP (one instruction while RUN is off), bit 3 NMI (not modelled: draft 2's model has none); R bit 0 running, bit 1 halted (HALT with interrupts off), bit 2 at an instruction boundary (always, at this level) |
//! | `+0x2000` | interrupt requests (RFC 0037, 8): +0 W set the levels whose bits are 1, bit L - 1 for level L; +4 W clear them; +0 R the requests |
//! | `+0x40_0000` + `0x2_0000` k | the control store's SRAM k, 64K x 16, k = 0-9, while RUN is off: draft 2's CPU (RFC 0031) has nine 16-bit lanes of microinstruction and the decode table. The CPU here runs at instruction level and doesn't use them; they're kept so that what the IOP loads can be checked |
//!
//! At power-up RUN is off: the CPU's control store would be SRAM. The
//! slave port into the RAM takes 2 data clocks for the IOP (one WAIT),
//! the registers 1.
//!
//! **Time:** the IOP and the CPU take turns, a slice of bus clocks each
//! (16 us by default): the IOP runs a slice, then the CPU catches up to
//! the IOP's time. What one does is seen by the other within a slice.

use crate::iop::{Answer, Iop, Status, SystemBus};
use std::sync::{Arc, Mutex};
use v2_isa::sys::Bus;
use v2_isa::timing::Config as Timing;
use v2_isa::{Machine, RunStatus};

pub const CPU_REGS: u32 = 0x7000_0000;
pub const INFO: u32 = 0x0000;
pub const CONTROL: u32 = 0x1000;
pub const IRQ: u32 = 0x2000;
pub const CS: u32 = 0x40_0000;
pub const CS_LANE: u32 = 0x2_0000;
pub const CS_LANES: usize = 10;

pub const RUN: u32 = 1;
pub const RESET: u32 = 2;
pub const STEP: u32 = 4;

/// The CPU card, as the bus sees it.
pub struct CpuCard {
    pub ram_size: u32,
    pub clock_hz: f64,
    pub boot_flags: u32,
    pub run: bool,
    pub reset_pending: bool,
    pub step_pending: bool,
    /// The CPU stopped in HALT with interrupts off.
    pub halted: bool,
    /// The interrupt request register.
    pub irq: u8,
    pub lanes: Vec<Vec<u16>>,
    /// Control store writes while RUN was on: lost.
    pub lane_errors: u64,
    pub debug: Vec<u8>,
    /// Since the last slice: RAM written by another master; the requests
    /// changed.
    ram_written: bool,
    irq_changed: bool,
}

impl CpuCard {
    fn reg_read(&mut self, off: u32) -> Option<u32> {
        Some(match off & !3 {
            0x0000 => self.ram_size,
            0x0004 => self.clock_hz as u32,
            0x000C => self.boot_flags,
            0x1000 => self.run as u32 | (self.halted as u32) << 1 | 4,
            0x2000 => self.irq as u32,
            o if (CS..CS + CS_LANE * CS_LANES as u32).contains(&o) => {
                let k = ((o - CS) / CS_LANE) as usize;
                self.lanes[k][(((off - CS) % CS_LANE) >> 1) as usize] as u32
            }
            _ => return None,
        })
    }

    fn reg_write(&mut self, off: u32, size: u32, v: u32) -> bool {
        match off & !3 {
            0x0008 => self.debug.push(v as u8),
            0x0000 | 0x0004 | 0x000C => {}
            0x1000 => {
                if off & 2 == 0 {
                    if v & RESET != 0 {
                        self.reset_pending = true;
                    }
                    if v & STEP != 0 {
                        self.step_pending = true;
                    }
                    self.run = v & RUN != 0;
                }
            }
            0x2000 => {
                if off & 2 == 0 {
                    self.irq |= v as u8;
                    self.irq_changed = true;
                }
            }
            0x2004 => {
                if off & 2 == 0 {
                    self.irq &= !(v as u8);
                    self.irq_changed = true;
                }
            }
            o if (CS..CS + CS_LANE * CS_LANES as u32).contains(&o) => {
                if self.run {
                    self.lane_errors += 1;
                    return true;
                }
                let k = ((o - CS) / CS_LANE) as usize;
                let i = (((off - CS) % CS_LANE) >> 1) as usize;
                let h = &mut self.lanes[k][i];
                *h = match (size, off & 1) {
                    (1, 0) => (*h & 0xFF00) | (v as u16 & 0xFF),
                    (1, _) => (*h & 0x00FF) | (v as u16) << 8,
                    _ => v as u16,
                };
            }
            _ => return false,
        }
        true
    }
}

/// The CPU's side of the bus: its card, and the IOP's ranges.
pub struct CpuBoard {
    pub card: CpuCard,
    iop: Arc<Mutex<Iop>>,
}

impl CpuBoard {
    fn ns(&self, cycles: u64) -> u64 {
        (cycles as f64 * 1e9 / self.card.clock_hz) as u64
    }
}

impl Bus for CpuBoard {
    fn read(&mut self, pa: u32, size: u32, cycles: u64) -> Option<u32> {
        if pa >> 24 == CPU_REGS >> 24 {
            return self.card.reg_read(pa & 0xFF_FFFF);
        }
        let t = self.ns(cycles);
        self.iop.lock().unwrap().slave_read(pa, size, t)
    }

    fn write(&mut self, pa: u32, size: u32, v: u32, cycles: u64) -> bool {
        if pa >> 24 == CPU_REGS >> 24 {
            return self.card.reg_write(pa & 0xFF_FFFF, size, v);
        }
        let t = self.ns(cycles);
        self.iop.lock().unwrap().slave_write(pa, size, v, t)
    }

    fn irq(&mut self, _cycles: u64) -> (u8, u64) {
        (self.card.irq, u64::MAX)
    }
}

/// The IOP's master side on the bus: the CPU card's RAM through its slave
/// port, and its registers.
struct CpuSide<'a> {
    mem: &'a mut [u8],
    card: &'a mut CpuCard,
}

impl SystemBus for CpuSide<'_> {
    fn read(&mut self, addr: u32, size: u32, _now: u64) -> Answer {
        match addr >> 28 {
            0 => {
                let a = (addr % self.card.ram_size) as usize & !1;
                let h = u16::from_le_bytes([self.mem[a], self.mem[a + 1]]);
                let _ = size;
                Answer {
                    data: Some(h),
                    clocks: 2,
                }
            }
            7 if addr >> 24 == CPU_REGS >> 24 => {
                let off = addr & 0xFF_FFFF;
                let data = self
                    .card
                    .reg_read(off & !1)
                    .map(|w| (w >> (8 * (off & 2))) as u16);
                Answer { data, clocks: 1 }
            }
            _ => Answer {
                data: None,
                clocks: 1,
            },
        }
    }

    fn write(&mut self, addr: u32, size: u32, data: u16, _now: u64) -> Answer {
        match addr >> 28 {
            0 => {
                let a = (addr % self.card.ram_size) as usize;
                if size == 1 {
                    self.mem[a] = (data >> (8 * (a & 1))) as u8;
                } else {
                    self.mem[a & !1..(a & !1) + 2].copy_from_slice(&data.to_le_bytes());
                }
                self.card.ram_written = true;
                Answer {
                    data: None,
                    clocks: 2,
                }
            }
            7 if addr >> 24 == CPU_REGS >> 24 => {
                let off = addr & 0xFF_FFFF;
                let v = if size == 1 && off & 1 != 0 {
                    (data >> 8) as u32
                } else {
                    data as u32
                };
                self.card.reg_write(off, size, v);
                Answer {
                    data: None,
                    clocks: 1,
                }
            }
            _ => Answer {
                data: None,
                clocks: 1,
            },
        }
    }

    fn reset(&mut self, on: bool) {
        if on {
            self.card.run = false;
            self.card.reset_pending = true;
            self.card.irq = 0;
            self.card.irq_changed = true;
        }
    }
}

pub struct System {
    pub iop: Arc<Mutex<Iop>>,
    pub cpu: Machine,
    /// Bus clocks a turn.
    pub slice: u64,
}

impl System {
    pub fn new(iop: Iop, ram_size: u32, clock_hz: f64, timing: Timing) -> System {
        let iop = Arc::new(Mutex::new(iop));
        let card = CpuCard {
            ram_size: ram_size.next_multiple_of(4096),
            clock_hz,
            boot_flags: 0,
            run: false,
            reset_pending: true,
            step_pending: false,
            halted: false,
            irq: 0,
            lanes: vec![vec![0; 0x10000]; CS_LANES],
            lane_errors: 0,
            debug: Vec::new(),
            ram_written: false,
            irq_changed: false,
        };
        let board = CpuBoard {
            card,
            iop: iop.clone(),
        };
        System {
            iop,
            cpu: Machine::new_system(ram_size, Box::new(board), timing),
            slice: 256,
        }
    }

    pub fn board(&mut self) -> &mut CpuBoard {
        self.cpu.sys_mut().bus_as::<CpuBoard>().unwrap()
    }

    pub fn card(&mut self) -> &mut CpuCard {
        &mut self.board().card
    }

    pub fn card_ref(&self) -> &CpuCard {
        &self.cpu.sys().bus_ref::<CpuBoard>().unwrap().card
    }

    fn cycles_at(&self, ns: u64) -> u64 {
        (ns as f64 * self.card_ref().clock_hz / 1e9) as u64
    }

    /// Run until the IOP's clock reaches `until` (bus clocks), or the
    /// IOP's microcode stops or reaches a breakpoint.
    pub fn run(&mut self, until: u64) -> Result<Status, String> {
        loop {
            let iop = self.iop.clone();
            let mut iop = iop.lock().unwrap();
            if iop.clock >= until {
                return Ok(Status::Limit);
            }
            let end = until.min(iop.clock + self.slice);
            let Machine { mem, sys, .. } = &mut self.cpu;
            let board = sys.as_mut().unwrap().bus_as::<CpuBoard>().unwrap();
            let mut side = CpuSide {
                mem,
                card: &mut board.card,
            };
            let st = iop.run(end, &mut side)?;
            let now_ns = iop.now_ns();
            drop(iop);
            self.cpu_catch_up(now_ns)?;
            if st != Status::Limit {
                return Ok(st);
            }
        }
    }

    /// The CPU's turn: what the IOP did to its card, then run it to the
    /// IOP's time.
    fn cpu_catch_up(&mut self, now_ns: u64) -> Result<(), String> {
        let target = self.cycles_at(now_ns);
        let card = self.card();
        let (written, irq_changed) = (card.ram_written, card.irq_changed);
        card.ram_written = false;
        card.irq_changed = false;
        if written {
            self.cpu.forget_code();
        }
        if irq_changed {
            self.cpu.sys_mut().touched();
        }
        let card = self.card();
        let reset = card.reset_pending && (card.run || card.step_pending);
        if reset {
            card.reset_pending = false;
            card.halted = false;
            self.cpu.reset_system();
        }
        let card = self.card();
        let (run, step) = (card.run, card.step_pending);
        card.step_pending = false;
        if self.cpu.cycles < target && (run || step) && !self.card_ref().halted {
            let st = self
                .cpu
                .run_system(target, if run { u64::MAX } else { 1 })?;
            match st {
                RunStatus::Halted => self.card().halted = true,
                RunStatus::Idle => {
                    self.cpu.idle_cycles += target - self.cpu.cycles;
                    self.cpu.cycles = target;
                }
                _ => {}
            }
        }
        if !run && self.cpu.cycles < target {
            self.cpu.cycles = target;
        }
        Ok(())
    }
}
