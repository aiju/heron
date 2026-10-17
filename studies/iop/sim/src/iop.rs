//! The IOP's core at microinstruction level (RFC 0027, 3), clocked by the
//! bus clock: what each microinstruction does, and how many bus clocks
//! it takes.
//!
//! **The microcycle** is two bus clocks, E0-E1-E2. In the first half R is
//! the source (a register, memory at X, K or T) and the ALU's A input, with
//! AC as B; F and the carry are latched at E1, unless HOLD. In the second
//! half R is F: written back to the SRAM if asked, taken into AB or a
//! device at E2, and loaded into AC, X, BANK, AH0, AH1, LC or CTRL at E2.
//! The SRAM's address is X when RS chooses memory, the register {BANK,
//! REG} otherwise, so a write-back goes to the register REG names unless
//! RS is memory.
//!
//! **Sequencing:** uIR holds the microinstruction being executed and uPC
//! the address of the next, fetched during it; at E2 uIR takes it and uPC
//! the next address. So the microinstruction after a branch always runs.
//! A condition is sampled in the second half: the carry and F's bit 15 are
//! this microinstruction's own (or held ones). COND 3 tests and counts LC,
//! a 4-bit counter: "not done" is LC != 15, and LC counts up at E2
//! whatever SEQ is, unless LC is loaded.
//!
//! **Stretching:** a microcycle takes longer when
//! - it makes a transfer on the system bus and the previous one hasn't
//!   ended, or the bus isn't granted yet: it waits at E1 (RFC 0027, 3.2);
//! - it reads BA before the last read's data is in it: BA onto R in the
//!   first half waits at E0, BA into AB or a device in the second half at
//!   E1. RFC 0027 doesn't say what happens here; this model interlocks;
//! - it loads AB while the last write's data phase hasn't ended: its
//!   second half lasts until the clock after that ends, so that the
//!   write's data holds (RFC 0027 doesn't say either; without it,
//!   back-to-back writes from registers would have to count the slave's
//!   clocks; the clock after is the netlist's, which registers the data
//!   phase rather than wait for WAIT, too late for E2);
//! - it accesses the I/O bus: the access starts when the last one's hold
//!   has ended, and the microcycle lasts until its strobe ends (RFC 0027,
//!   3.5), 1 + SETUP + STROBE clocks from the timing table, and a clock
//!   more; the hold, 1 + HOLD clocks, overlaps what follows. (So the I/O
//!   side holds A0-A7, WRITE and the data through the hold, whatever X
//!   does.) Its read data is latched at the strobe's end (RFC 0037, 16).
//!   The clock after it is the second half's last, or for a read onto R
//!   (RS = T) the first half's, for the bridge and the ALU. The netlist
//!   (`card.py`) registers the strobe's end, which is what costs that
//!   clock: the stall can't wait for the strobe's counter.
//!
//! **The system bus:** a transfer's address is R in the first half,
//! loaded into AL at E1, with AH0 or AH1 for A16-A31. Its address clock is
//! E1-E2, its data clocks follow from E2, as many as the slave takes. (If
//! an I/O bus access stretches the second half, the address clock is its
//! last, so that START is still one clock, and AB has the access's data
//! at E2.) Read
//! data lands in BA at the end. Write data comes from AB, which the
//! microinstruction making the transfer may load at its E2, the start of
//! the data phase; changing AB later in the data phase is a microcode
//! error here. REQ follows CTRL's SESSION bit; GNT comes 4 clocks after REQ
//! rises (an idle bus, RFC 0037, 6.2: the CPU's own transfers aren't
//! modelled), and a transfer without SESSION is a microcode error.
//!
//! **CTRL** is an addressable latch here (a 74x259), not RFC 0027's
//! 74ABT273: loading it from R sets bit R[2:0] to R[3], so that firmware
//! can change one bit without knowing the others. Its bits:
//! 0 SESSION (REQ), 1 WORK (native work is waiting: attention), 2 RESET
//! (the system bus's RESET), 3 IORESET.
//!
//! **Attention** is the tick, any doorbell, or WORK.
//!
//! **The devices on T** (REG bits 5-3, register bits 2-0):
//! - 0 the I/O bus at X (see [`crate::iobus`]);
//! - 1 the shared RAM at {page, X}: X is a byte address, its bit 0
//!   ignored, and the page register holds address bits 16-22, so that a
//!   CPU's physical address in region 4 splits into the two without a
//!   shift (RFC 0027 has X count halfwords, with a 4-bit page register
//!   for 2 MB);
//! - 2 the swap register: written from T, read with its bytes swapped;
//! - 3 the event ports: register 0 R the INT lines; 1 R ATN0-3 in bits
//!   0-3 and the tick in bit 15, W clears the tick; 2 R the doorbells, W
//!   clears doorbell X[3:0];
//! - 4 page registers, write-only: 0 the shared RAM's (7 bits, 64 KB
//!   pages), 1 the image flash's (11 bits);
//! - 5 the timing table, write-only, entry X[11:8];
//! - 6, 7 spare.
//!
//! Write-only and spare registers read as all ones.

use crate::iobus::{self, IoBus};
use crate::micro::*;

pub const CTRL_SESSION: u8 = 1;
pub const CTRL_WORK: u8 = 2;
pub const CTRL_RESET: u8 = 4;
pub const CTRL_IORESET: u8 = 8;

/// Clocks from REQ to the first address clock on an idle bus.
pub const GRANT_CLOCKS: u64 = 4;

#[derive(Clone, Debug)]
pub struct Config {
    /// The bus clock's period.
    pub bclk_ns: u64,
    /// The console UART's oscillator.
    pub uart_hz: f64,
    /// CLKB, the timer's clock.
    pub clkb_hz: f64,
    /// The shared RAM, in bytes: 2 MB fitted, up to 8 MB.
    pub shared_bytes: usize,
    /// Whether the watchdog is fitted: a COLD reset if the firmware
    /// doesn't kick it for 100 ms.
    pub watchdog: bool,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            bclk_ns: 60,
            uart_hz: 14_745_600.0,
            clkb_hz: 4e6,
            shared_bytes: 2 << 20,
            watchdog: false,
        }
    }
}

/// A slave's answer to the IOP's transfer: the data it drove (None if
/// nothing answered) and the data clocks the transfer took (at least 1).
#[derive(Clone, Copy, Debug)]
pub struct Answer {
    pub data: Option<u16>,
    pub clocks: u32,
}

/// The system bus, as the IOP's master side sees it. Addresses are byte
/// addresses; `size` is 1 or 2. Time is in bus clocks since power-up.
pub trait SystemBus {
    fn read(&mut self, addr: u32, size: u32, now: u64) -> Answer;
    fn write(&mut self, addr: u32, size: u32, data: u16, now: u64) -> Answer;
    /// ATN0-ATN3.
    fn atn(&mut self, _now: u64) -> u8 {
        0
    }
    /// RESET, the system reset, while CTRL's RESET bit is set.
    fn reset(&mut self, _on: bool, _now: u64) {}
}

/// A system bus with nothing else on it.
pub struct NoBus;

impl SystemBus for NoBus {
    fn read(&mut self, _addr: u32, _size: u32, _now: u64) -> Answer {
        Answer {
            data: None,
            clocks: 1,
        }
    }
    fn write(&mut self, _addr: u32, _size: u32, _data: u16, _now: u64) -> Answer {
        Answer {
            data: None,
            clocks: 1,
        }
    }
}

/// What the IOP did.
#[derive(Clone, Debug, Default)]
pub struct Stats {
    pub micro: u64,
    pub transfers: u64,
    /// Clocks lost waiting: at E1 for the system bus, for BA, and for the
    /// I/O bus beyond the microcycle's two clocks.
    pub stall_bus: u64,
    pub stall_ba: u64,
    pub stall_io: u64,
}

/// Why `run` returned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    /// The clock reached the limit.
    Limit,
    /// The microcode is in a loop of a jump to itself (and its delay
    /// slot): how microcode stops.
    Stopped,
    /// The microprogram counter reached a breakpoint.
    Break,
}

pub struct Iop {
    pub cfg: Config,
    pub words: Vec<u64>,
    rom: Vec<Micro>,
    /// The 64K x 16 SRAM: dictionary, stacks, the register banks.
    pub sram: Vec<u16>,
    /// The shared RAM, as halfwords.
    pub shared: Vec<u16>,
    pub upc: u16,
    uir: Micro,
    /// The address of the microinstruction in uIR (None after reset,
    /// when uIR holds the cleared word).
    pub cur: Option<u16>,
    prev: Option<u16>,
    pub f: u16,
    pub carry: bool,
    pub ac: u16,
    pub x: u16,
    pub bank: u8,
    pub ah: [u16; 2],
    pub lc: u8,
    pub ctrl: u8,
    pub ab: u16,
    pub ba: u16,
    pub swap: u16,
    pub sr_page: u16,
    pub io: IoBus,
    pub tick: bool,
    pub doorbells: u16,
    /// Bus clocks since power-up: E0 of the microinstruction in uIR.
    pub clock: u64,
    ba_ready: u64,
    bus_free: u64,
    write_end: u64,
    gnt_at: u64,
    /// When the I/O bus's last access, its hold included, ends.
    io_free: u64,
    /// D0-D15 on the system bus: what an unanswered read returns.
    d_hold: u16,
    next_dev: u64,
    pub stats: Stats,
    /// Executions by microaddress.
    pub counts: Vec<u64>,
    /// The last microaddresses executed, oldest first.
    pub trace: std::collections::VecDeque<(u64, u16)>,
    pub breakpoints: Vec<u16>,
    /// When on, every E2, the microaddress uIR takes there and AC after
    /// it: what the netlist (card.py) is checked against.
    pub log: Option<Vec<(u64, u16, u16)>>,
    pub stopped: bool,
    /// Cold resets the watchdog has caused.
    pub watchdog_resets: u64,
}

const TRACE: usize = 64;

impl Iop {
    /// An IOP with `words` as its microcode (missing words are zero) and
    /// `flash` in its image flash, at power-up.
    pub fn new(cfg: Config, words: &[u64], flash: &[u8]) -> Iop {
        let mut w = vec![0u64; WORDS];
        w[..words.len().min(WORDS)].copy_from_slice(&words[..words.len().min(WORDS)]);
        let rom = w.iter().map(|&x| Micro::decode(x)).collect();
        // The SRAMs power up holding anything: a fixed pseudo-random
        // pattern, so that firmware that reads before writing shows it.
        let mut seed = 0x2545_F491u32;
        let mut noise = || {
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            seed as u16
        };
        let sram = (0..0x10000).map(|_| noise()).collect();
        let shared = (0..cfg.shared_bytes / 2).map(|_| noise()).collect();
        let io = IoBus::new(flash, cfg.uart_hz, cfg.clkb_hz);
        Iop {
            cfg,
            words: w,
            rom,
            sram,
            shared,
            upc: 0,
            uir: Micro::default(),
            cur: None,
            prev: None,
            f: 0,
            carry: false,
            ac: 0,
            x: 0,
            bank: 0,
            ah: [0; 2],
            lc: 0,
            ctrl: 0,
            ab: 0,
            ba: 0,
            swap: 0,
            sr_page: 0,
            io,
            tick: false,
            doorbells: 0,
            clock: 0,
            ba_ready: 0,
            bus_free: 0,
            write_end: 0,
            gnt_at: 0,
            io_free: 0,
            d_hold: 0,
            next_dev: 0,
            stats: Stats::default(),
            counts: vec![0; WORDS],
            trace: std::collections::VecDeque::with_capacity(TRACE),
            breakpoints: Vec::new(),
            log: None,
            stopped: false,
            watchdog_resets: 0,
        }
    }

    /// An IOP from its microcode ROMs' contents as the microassembler
    /// writes them (six bytes a word, little-endian, from address 0).
    pub fn from_rom(cfg: Config, rom: &[u8], flash: &[u8]) -> Iop {
        let words: Vec<u64> = rom
            .chunks(6)
            .map(|c| {
                let mut b = [0u8; 8];
                b[..c.len()].copy_from_slice(c);
                u64::from_le_bytes(b)
            })
            .collect();
        Iop::new(cfg, &words, flash)
    }

    /// COLD: the core and the devices reset; the SRAMs, the flash and the
    /// timing table keep their contents.
    pub fn cold(&mut self) {
        self.upc = 0;
        self.uir = Micro::default();
        self.cur = None;
        self.prev = None;
        self.ctrl = 0;
        self.tick = false;
        self.doorbells = 0;
        self.stopped = false;
        self.io.reset();
        self.io.kicked_ns = self.now_ns();
    }

    pub fn now_ns(&self) -> u64 {
        self.clock * self.cfg.bclk_ns
    }

    pub fn attention(&self) -> bool {
        self.tick || self.doorbells != 0 || self.ctrl & CTRL_WORK != 0
    }

    /// The SRAM address of register `r` of bank `b`.
    pub fn reg_addr(bank: u8, r: u8) -> usize {
        0xC000 | (bank as usize) << 6 | r as usize
    }

    fn advance_devices(&mut self) {
        let now = self.now_ns();
        self.io.advance(now);
        if self.io.tick_edges > 0 {
            self.io.tick_edges = 0;
            self.tick = true;
        }
        // Look again within about a microsecond, or at the UART's next
        // change if that's sooner.
        let mut next = 16;
        if let Some(ns) = self.io.uart_next_ns() {
            next = next.min(ns / self.cfg.bclk_ns + 1);
        }
        self.next_dev = self.clock + next;
    }

    /// A device on T, read. Returns the value and the I/O bus clocks.
    fn dev_read(&mut self, reg: u8, bus: &mut dyn SystemBus) -> Result<(u16, u32), String> {
        let r = reg & 7;
        Ok(match reg >> 3 {
            DEV_IO => {
                let now = self.now_ns();
                self.io
                    .access(((self.x >> 8) & 15) as usize, self.x as u8, None, now)?
            }
            DEV_SR => (self.shared[self.sr_index()], 0),
            DEV_SWAP => (self.swap.rotate_left(8), 0),
            DEV_EVENTS => {
                self.advance_devices();
                let v = match r {
                    0 => self.io.int_lines(),
                    1 => (bus.atn(self.clock) & 15) as u16 | (self.tick as u16) << 15,
                    2 => self.doorbells,
                    _ => 0xFFFF,
                };
                (v, 0)
            }
            _ => (0xFFFF, 0),
        })
    }

    fn sr_index(&self) -> usize {
        ((self.sr_page as usize) << 15 | (self.x >> 1) as usize) % self.shared.len()
    }

    /// A device on T, written. Returns the I/O bus clocks.
    fn dev_write(&mut self, reg: u8, v: u16) -> Result<u32, String> {
        let r = reg & 7;
        match reg >> 3 {
            DEV_IO => {
                let now = self.now_ns();
                return Ok(self
                    .io
                    .access(((self.x >> 8) & 15) as usize, self.x as u8, Some(v), now)?
                    .1);
            }
            DEV_SR => {
                let i = self.sr_index();
                self.shared[i] = v;
            }
            DEV_SWAP => self.swap = v,
            DEV_EVENTS => match r {
                1 => self.tick = false,
                2 => self.doorbells &= !(1 << (self.x & 15)),
                _ => {}
            },
            DEV_PAGE => match r {
                0 => self.sr_page = v & 127,
                1 => self.io.flash_page = v & 0x7FF,
                _ => {}
            },
            DEV_TTAB => self.io.ttab[((self.x >> 8) & 15) as usize] = Some(v),
            _ => {}
        }
        Ok(0)
    }

    /// A microinstruction's access to the I/O bus, if it makes one: the
    /// clocks to the strobe's end, and the hold after it. Checks the
    /// timing table.
    fn io_timing(&self, u: &Micro) -> Result<Option<(u64, u64)>, String> {
        if u.uses_dev() && u.dev() == DEV_IO {
            let e = self.io.entry(((self.x >> 8) & 15) as usize)?;
            return Ok(Some((iobus::strobe_end(e) as u64, iobus::hold(e) as u64)));
        }
        Ok(None)
    }

    fn here(&self) -> String {
        match self.cur {
            Some(a) => format!("at {a:04X}"),
            None => "after reset".into(),
        }
    }

    /// Execute the microinstruction in uIR.
    pub fn step(&mut self, bus: &mut dyn SystemBus) -> Result<(), String> {
        if self.cfg.watchdog && self.now_ns().saturating_sub(self.io.kicked_ns) > iobus::WATCHDOG_NS
        {
            self.watchdog_resets += 1;
            self.cold();
        }
        self.step_inner(bus)
            .map_err(|e| format!("{e} ({}, clock {})", self.here(), self.clock))
    }

    fn step_inner(&mut self, bus: &mut dyn SystemBus) -> Result<(), String> {
        let u = self.uir;
        if self.clock >= self.next_dev {
            self.advance_devices();
        }
        if let Some(a) = self.cur {
            self.counts[a as usize] += 1;
            if self.trace.len() == TRACE {
                self.trace.pop_front();
            }
            self.trace.push_back((self.clock, a));
            if u.is_goto() && u.k == a && self.prev == Some(a.wrapping_add(1)) {
                self.stopped = true;
                return Ok(());
            }
        }
        self.stats.micro += 1;

        // E0: BA onto R must be there from the start.
        let mut start = self.clock;
        let ba_on_r = u.rs == RS_T && u.t != T_FROM_DEV;
        if ba_on_r && self.ba_ready > start {
            self.stats.stall_ba += self.ba_ready - start;
            start = self.ba_ready;
        }
        let mut len = 2;
        let mut io = false;
        if let Some((strobe_end, hold)) = self.io_timing(&u)? {
            let astart = start.max(self.io_free);
            len = len.max(astart - start + strobe_end);
            self.io_free = astart + strobe_end + hold;
            io = true;
        }
        let first_io = u.rs == RS_T && u.t == T_FROM_DEV;
        let mut e1 = start + if first_io && io { len + 1 } else { 1 };
        self.stats.stall_io += if first_io && io { len } else { len - 2 };
        if matches!(u.t, T_AB_BA | T_DEV_BA) && self.ba_ready > e1 {
            self.stats.stall_ba += self.ba_ready - e1;
            e1 = self.ba_ready;
        }
        let ab_load = matches!(u.t, T_AB_BA | T_AB_F | T_AB_DEV);
        if u.bus != BUS_NONE {
            if self.ctrl & CTRL_SESSION == 0 {
                return Err("a transfer without SESSION".into());
            }
            let ready = self.bus_free.max(self.gnt_at);
            if ready > e1 {
                self.stats.stall_bus += ready - e1;
                e1 = ready;
            }
        }
        // An access that stretches the second half ends it the clock after
        // its strobe (the netlist registers the strobe's end).
        let mut e2 = (e1 + 1).max(if first_io || !io { 0 } else { start + len + 1 });
        if !first_io && io {
            self.stats.stall_io += 1;
        }
        if ab_load && self.write_end + 1 > e2 {
            self.stats.stall_bus += self.write_end + 1 - e2;
            e2 = self.write_end + 1;
        }
        // A transfer's address clock is the second half's last, its data
        // clocks from E2.
        let (at, data_at) = (e2 - 1, e2);

        // The first half.
        let reg_addr = Self::reg_addr(self.bank, u.reg);
        let addr = if u.rs == RS_MEM {
            self.x as usize
        } else {
            reg_addr
        };
        let a = match u.rs {
            RS_REG | RS_MEM => self.sram[addr],
            RS_K => u.k,
            _ if u.t == T_FROM_DEV => self.dev_read(u.reg, bus)?.0,
            _ => self.ba,
        };
        if !u.hold {
            let (f, c) = alu(u.s, u.m, u.cin, a, self.ac);
            self.f = f;
            self.carry = c;
        }
        let f = self.f;

        // The second half.
        if u.wb {
            self.sram[addr] = f;
        }
        if ab_load && e2 < self.write_end {
            return Err("AB changed during a write's data phase".into());
        }
        let old_ba = self.ba;
        match u.t {
            T_AB_BA => self.ab = old_ba,
            T_AB_F => self.ab = f,
            T_AB_DEV => self.ab = self.dev_read(u.reg, bus)?.0,
            T_DEV_BA => {
                self.dev_write(u.reg, old_ba)?;
            }
            T_DEV_F => {
                self.dev_write(u.reg, f)?;
            }
            _ => {}
        }

        // The transfer: address clock E1-E2, data from E2.
        if u.bus != BUS_NONE {
            if u.sz == SZ_WORD {
                return Err("a word transfer, without the 32-bit path".into());
            }
            let size = if u.sz == SZ_HALF { 2 } else { 1 };
            let addr = (self.ah[u.seg as usize] as u32) << 16
                | (a & 0xFFFE) as u32
                | (u.sz == SZ_B1) as u32;
            self.stats.transfers += 1;
            if u.bus == BUS_WRITE {
                let ans = bus.write(addr, size, self.ab, at);
                let n = ans.clocks.max(1) as u64;
                self.d_hold = self.ab;
                self.write_end = data_at + n;
                self.bus_free = data_at + n;
            } else {
                let ans = bus.read(addr, size, at);
                let n = ans.clocks.max(1) as u64;
                let lanes: u16 = match u.sz {
                    SZ_B0 => 0x00FF,
                    SZ_B1 => 0xFF00,
                    _ => 0xFFFF,
                };
                let v = match ans.data {
                    Some(d) => (d & lanes) | (self.d_hold & !lanes),
                    None => self.d_hold,
                };
                self.d_hold = v;
                self.ba = v;
                self.ba_ready = data_at + n;
                self.bus_free = data_at + n;
            }
        }

        // The condition, in the second half.
        let cond = match u.cond {
            COND_ALWAYS => true,
            COND_CARRY => self.carry,
            COND_F15 => f & 0x8000 != 0,
            COND_LC => {
                let done = self.lc == 15;
                if u.ld != LD_LC {
                    self.lc = (self.lc + 1) & 15;
                }
                !done
            }
            COND_ATTN => self.attention(),
            COND_BELL => self.doorbells != 0,
            _ => false,
        };
        let next = match u.seq {
            SEQ_NEXT => self.upc.wrapping_add(1),
            SEQ_IF if cond => u.k,
            SEQ_UNLESS if !cond => u.k,
            SEQ_DISPATCH => {
                if cond {
                    f
                } else {
                    u.k
                }
            }
            _ => self.upc.wrapping_add(1),
        };

        // E2.
        match u.ld {
            LD_AC => self.ac = f,
            LD_X => self.x = f,
            LD_BANK => self.bank = f as u8,
            LD_AH0 => self.ah[0] = f,
            LD_AH1 => self.ah[1] = f,
            LD_LC => self.lc = (f & 15) as u8,
            LD_CTRL => {
                let bit = 1u8 << (f & 7);
                let was = self.ctrl;
                if f & 8 != 0 {
                    self.ctrl |= bit;
                } else {
                    self.ctrl &= !bit;
                }
                let rose = self.ctrl & !was;
                let fell = was & !self.ctrl;
                if rose & CTRL_SESSION != 0 {
                    self.gnt_at = e2 + GRANT_CLOCKS;
                }
                if (rose | fell) & CTRL_RESET != 0 {
                    bus.reset(self.ctrl & CTRL_RESET != 0, e2);
                }
                if rose & CTRL_IORESET != 0 {
                    self.io.reset();
                }
            }
            _ => {}
        }
        self.prev = self.cur;
        self.cur = Some(self.upc);
        if let Some(log) = &mut self.log {
            log.push((e2, self.upc, self.ac));
        }
        self.uir = self.rom[self.upc as usize];
        self.upc = next;
        self.clock = e2;
        Ok(())
    }

    /// Run until the clock reaches `until`, the microcode stops, or the
    /// microprogram counter is at a breakpoint.
    pub fn run(&mut self, until: u64, bus: &mut dyn SystemBus) -> Result<Status, String> {
        while self.clock < until {
            if self.stopped {
                return Ok(Status::Stopped);
            }
            self.step(bus)?;
            if !self.breakpoints.is_empty()
                && let Some(c) = self.cur
                && self.breakpoints.contains(&c)
            {
                return Ok(Status::Break);
            }
        }
        Ok(if self.stopped {
            Status::Stopped
        } else {
            Status::Limit
        })
    }

    // ---- the slave side (RFC 0027, 4.2), for the system bus's other masters

    /// A read by another master in the IOP's ranges: the shared RAM in
    /// region 4, the doorbells at 0x7400_0000 (which read stale data:
    /// here zero), the I/O bus's window at 0x7F00_0000. `size` is 1, 2 or
    /// 4; a word is two halfwords, as a 32-bit master makes it on a
    /// 16-bit card. None if the address isn't the IOP's.
    pub fn slave_read(&mut self, pa: u32, size: u32, now_ns: u64) -> Option<u32> {
        match pa >> 24 {
            0x40..=0x4F => {
                let mut v = 0u32;
                for i in 0..size {
                    let b = (pa + i) as usize % (self.shared.len() * 2);
                    let h = self.shared[b / 2];
                    v |= ((h >> (8 * (b & 1))) as u32 & 0xFF) << (8 * i);
                }
                Some(v)
            }
            0x74 => Some(0),
            0x7F => {
                if pa & 2 != 0 {
                    return Some(0);
                }
                let dev = ((pa >> 16) & 15) as usize;
                let reg = ((pa >> 2) & 0xFF) as u8;
                let (v, _) = self.io.window(dev, reg, None, now_ns.max(self.io.now_ns));
                Some(match size {
                    1 if pa & 1 != 0 => (v >> 8) as u32,
                    1 => (v & 0xFF) as u32,
                    _ => v as u32,
                })
            }
            _ => None,
        }
    }

    /// A write by another master; false if the address isn't the IOP's.
    pub fn slave_write(&mut self, pa: u32, size: u32, v: u32, now_ns: u64) -> bool {
        match pa >> 24 {
            0x40..=0x4F => {
                for i in 0..size {
                    let b = (pa + i) as usize % (self.shared.len() * 2);
                    let h = &mut self.shared[b / 2];
                    let sh = 8 * (b & 1);
                    *h = (*h & !(0xFF << sh)) | (((v >> (8 * i)) & 0xFF) as u16) << sh;
                }
                true
            }
            0x74 => {
                if pa & 0xFF_FFC0 == 0 {
                    self.doorbells |= 1 << ((pa >> 2) & 15);
                }
                true
            }
            0x7F => {
                if pa & 2 != 0 {
                    return true;
                }
                let dev = ((pa >> 16) & 15) as usize;
                let reg = ((pa >> 2) & 0xFF) as u8;
                let d = match size {
                    1 if pa & 1 != 0 => (v >> 8) as u16,
                    _ => v as u16,
                };
                self.io
                    .window(dev, reg, Some(d), now_ns.max(self.io.now_ns));
                true
            }
            _ => false,
        }
    }
}
