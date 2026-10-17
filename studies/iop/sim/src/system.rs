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
//! The CPU card's registers, at RFC 0040's offsets (3; RFC 0037, 9 and
//! RFC 0027, 8.1 name them). They are words; the IOP, a 16-bit master,
//! reaches their low halves at +0 and their high halves at +2:
//!
//! | Offset | |
//! |---|---|
//! | `+0x0000` | control: W bit 0 RUN, bit 1 RESET (a warm reset, taken when RUN is next set), bit 2 STEP (one instruction while RUN is off), bit 3 NMI (not modelled: draft 2's model has none); R bit 0 running, bit 1 halted (HALT with interrupts off), bit 2 at an instruction boundary (always, at this level) |
//! | `+0x1000` | board information: +0 R the RAM's size, +4 R BCLK's period in ns, +8 R the region (the CPU's number), +C R boot flags; this study's: +0x10 W a byte to the simulator's debug log (not hardware), +0x14 R the CPU's clock in Hz |
//! | `+0x2000` | the request register (RFC 0040, 3.1): +0 W set the levels whose bits are 1, bit L - 1 for level L; +4 W clear them; +8 R the levels requested, the card's own sources' included |
//! | `+0x3000` | the message register (RFC 0040, 3.2): +0 R claim (0 if it was free and is now claimed, 1 if not); +4 W the message, which a 16-bit master writes low half, then high half; +8 W release; +C R its contents. Full, it requests level 7 |
//! | `+0x4000` | the timer (RFC 0040, 3.3): +0 R the count of BCLK since reset; +4 W bit 0 clears the tick, which each 0-1 edge of the count's bit `tick_bit` sets (if its jumper is fitted), and which requests level 6 |
//! | `+0x80_0000` + `0x2_0000` k | the control store's SRAM k, 64K x 16, k = 0-9, while RUN is off: draft 2's CPU (RFC 0031) has nine 16-bit lanes of microinstruction and the decode table. The CPU here runs at instruction level and doesn't use them; they're kept so that what the IOP loads can be checked |
//!
//! RESET (the control register's, or the system bus's) clears the request
//! register, frees the message register and clears the timer.
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
pub const CONTROL: u32 = 0x0000;
pub const INFO: u32 = 0x1000;
pub const IRQ: u32 = 0x2000;
pub const MSG: u32 = 0x3000;
pub const TIMER: u32 = 0x4000;
pub const CS: u32 = 0x80_0000;
pub const CS_LANE: u32 = 0x2_0000;
pub const CS_LANES: usize = 10;

pub const RUN: u32 = 1;
pub const RESET: u32 = 2;
pub const STEP: u32 = 4;

/// The timer's jumper as RFC 0040, 3.3 has it: its tick is each 0-1 edge
/// of this bit of the count, every 7.9 ms at 60 ns.
pub const TICK_BIT: u32 = 16;

/// The message register's states (RFC 0040, 3.2).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Msg {
    Free,
    Claimed,
    Full,
}

/// The CPU card, as the bus sees it. Its timer counts the IOP's bus clock.
pub struct CpuCard {
    pub ram_size: u32,
    pub clock_hz: f64,
    pub bclk_ns: u64,
    pub boot_flags: u32,
    pub run: bool,
    pub reset_pending: bool,
    pub step_pending: bool,
    /// The CPU stopped in HALT with interrupts off.
    pub halted: bool,
    /// The interrupt request register.
    pub irq: u8,
    pub msg: Msg,
    pub msg_value: u32,
    /// The bus clock at the last reset, and the count at the tick's last
    /// clearing.
    timer_reset: u64,
    tick_cleared: u64,
    /// The tick's jumper: the count's bit, or none fitted (no tick).
    pub tick_bit: Option<u32>,
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
    /// The timer's count at bus clock `now`.
    pub fn count(&self, now: u64) -> u64 {
        now.saturating_sub(self.timer_reset)
    }

    /// Ticks (0-1 edges of bit `b`) up to a count.
    fn edges(c: u64, b: u32) -> u64 {
        (c + (1 << b)) >> (b + 1)
    }

    pub fn tick(&self, now: u64) -> bool {
        self.tick_bit
            .is_some_and(|b| Self::edges(self.count(now), b) > Self::edges(self.tick_cleared, b))
    }

    /// The bus clock of the next tick after `now`, if there are ticks.
    pub fn next_tick(&self, now: u64) -> Option<u64> {
        let b = self.tick_bit?;
        let period = 1u64 << (b + 1);
        let c = self.count(now);
        let next = (Self::edges(c, b) * period) + (1 << b);
        Some(self.timer_reset + next.max(c + 1))
    }

    /// The levels requested: the register's, the timer's tick at 6 and
    /// a full message register at 7.
    pub fn levels(&self, now: u64) -> u8 {
        self.irq | (self.tick(now) as u8) << 5 | ((self.msg == Msg::Full) as u8) << 6
    }

    fn reset(&mut self, now: u64) {
        self.irq = 0;
        self.msg = Msg::Free;
        self.timer_reset = now;
        self.tick_cleared = 0;
        self.irq_changed = true;
    }

    fn reg_read(&mut self, off: u32, now: u64) -> Option<u32> {
        Some(match off & !3 {
            0x0000 => self.run as u32 | (self.halted as u32) << 1 | 4,
            0x1000 => self.ram_size,
            0x1004 => self.bclk_ns as u32,
            0x1008 => 0,
            0x100C => self.boot_flags,
            0x1014 => self.clock_hz as u32,
            0x2008 => self.levels(now) as u32,
            0x3000 => {
                if off & 2 != 0 {
                    return Some(0);
                }
                if self.msg == Msg::Free {
                    self.msg = Msg::Claimed;
                    0
                } else {
                    1
                }
            }
            0x300C => self.msg_value,
            0x4000 => self.count(now) as u32,
            o if (CS..CS + CS_LANE * CS_LANES as u32).contains(&o) => {
                let k = ((o - CS) / CS_LANE) as usize;
                self.lanes[k][(((off - CS) % CS_LANE) >> 1) as usize] as u32
            }
            _ => return None,
        })
    }

    fn reg_write(&mut self, off: u32, size: u32, v: u32, now: u64) -> bool {
        match off & !3 {
            0x1010 => self.debug.push(v as u8),
            0x1000..=0x101C => {}
            0x0000 => {
                if off & 2 == 0 {
                    if v & RESET != 0 {
                        self.reset_pending = true;
                        self.reset(now);
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
            0x2008 => {}
            0x3004 => {
                if self.msg == Msg::Claimed {
                    match (size, off & 2) {
                        (4, _) => {
                            self.msg_value = v;
                            self.msg = Msg::Full;
                        }
                        (_, 0) => self.msg_value = (self.msg_value & 0xFFFF_0000) | (v & 0xFFFF),
                        _ => {
                            self.msg_value = (self.msg_value & 0xFFFF) | (v & 0xFFFF) << 16;
                            self.msg = Msg::Full;
                        }
                    }
                    self.irq_changed = true;
                }
            }
            0x3008 => {
                self.msg = Msg::Free;
                self.irq_changed = true;
            }
            0x3000 | 0x300C => {}
            0x4004 => {
                if v & 1 != 0 {
                    self.tick_cleared = self.count(now);
                    self.irq_changed = true;
                }
            }
            0x4000 => {}
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

    /// The bus clock at a CPU cycle.
    fn clocks(&self, cycles: u64) -> u64 {
        self.ns(cycles) / self.card.bclk_ns
    }
}

impl Bus for CpuBoard {
    fn read(&mut self, pa: u32, size: u32, cycles: u64) -> Option<u32> {
        if pa >> 24 == CPU_REGS >> 24 {
            let now = self.clocks(cycles);
            return self.card.reg_read(pa & 0xFF_FFFF, now);
        }
        let t = self.ns(cycles);
        self.iop.lock().unwrap().slave_read(pa, size, t)
    }

    fn write(&mut self, pa: u32, size: u32, v: u32, cycles: u64) -> bool {
        if pa >> 24 == CPU_REGS >> 24 {
            let now = self.clocks(cycles);
            return self.card.reg_write(pa & 0xFF_FFFF, size, v, now);
        }
        let t = self.ns(cycles);
        self.iop.lock().unwrap().slave_write(pa, size, v, t)
    }

    fn irq(&mut self, cycles: u64) -> (u8, u64) {
        let now = self.clocks(cycles);
        let levels = self.card.levels(now);
        let next = match self.card.next_tick(now) {
            Some(t) if levels & 1 << 5 == 0 => {
                let t = t * self.card.bclk_ns;
                ((t as f64 * self.card.clock_hz / 1e9).ceil() as u64).max(cycles + 1)
            }
            _ => u64::MAX,
        };
        (levels, next)
    }
}

/// The IOP's master side on the bus: the CPU card's RAM through its slave
/// port, and its registers.
struct CpuSide<'a> {
    mem: &'a mut [u8],
    card: &'a mut CpuCard,
}

impl SystemBus for CpuSide<'_> {
    fn read(&mut self, addr: u32, size: u32, now: u64) -> Answer {
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
                    .reg_read(off & !1, now)
                    .map(|w| (w >> (8 * (off & 2))) as u16);
                Answer { data, clocks: 1 }
            }
            _ => Answer {
                data: None,
                clocks: 1,
            },
        }
    }

    fn write(&mut self, addr: u32, size: u32, data: u16, now: u64) -> Answer {
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
                self.card.reg_write(off, size, v, now);
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

    fn reset(&mut self, on: bool, now: u64) {
        if on {
            self.card.run = false;
            self.card.reset_pending = true;
            self.card.reset(now);
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
            bclk_ns: 60,
            boot_flags: 0,
            run: false,
            reset_pending: true,
            step_pending: false,
            halted: false,
            irq: 0,
            msg: Msg::Free,
            msg_value: 0,
            timer_reset: 0,
            tick_cleared: 0,
            tick_bit: None,
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
