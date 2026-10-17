//! The I/O bus (RFC 0037, Part II) as the IOP sees it: device 0 on T,
//! register `X`: device S = X bits 8-11, register = X bits 0-7. The
//! timing table gives each device's access its length; slots 0-11 take
//! I/O cards, and devices 12-15 are on the IOP's own card (RFC 0027, 5):
//!
//! | Device | What | Registers |
//! |---|---|---|
//! | 12 | the console, a 16C550 from a 14.7456 MHz oscillator | 0-7, A0-A2; D0-D7 |
//! | 13 | the image flash, 512K x 16, with its page register (device 4 register 1 on T) as A8-A18 | A0-A7 |
//! | 14 | an 82C54, all three counters from CLKB (4 MHz): OUT0 is the polling tick, OUT2 the device's INT | 0-3, A0-A1; D0-D7 |
//! | 15 | ports: 0 W the LEDs; 0 R the inputs; 1 W the outputs | D0-D7 |
//!
//! The ports (the study's choice; RFC 0027 lists what they carry): port
//! 0's inputs are bit 0 the clock chip's I/O, bit 1 the panel's shift
//! chain's data, bits 2-7 jumpers J2-J7 (1 open). Port 1's outputs are bit
//! 0 the watchdog's kick, as written (a 1 kicks it), bits 1-3 the clock
//! chip's CE, SCLK and I/O pulled low, bits 4-6 the panel's shift chain's
//! data, clock and latch. The clock chip is a DS1302 (devices::ds1302);
//! the panel isn't modelled, so its data reads 1.
//!
//! **8-bit devices** drive D0-D7 only; D8-D15 keep what they last held, as
//! do all sixteen lines for a slot with no card, by the bus-hold of the
//! IOP's transceiver. So firmware masks what it reads from them.
//!
//! **An entry of the timing table** (RFC 0037, 17): bits 0-1 SETUP, 2-7
//! STROBE less one (1-64 clocks), 8-11 HOLD, 12 WAIT. An access
//! takes (1 + SETUP) + STROBE + (1 + HOLD) bus clocks. The table is SRAM:
//! an access to a device whose entry hasn't been written since power-up
//! is an error here, since its timing would be whatever the SRAM held.
//!
//! **Time** is the card's ([`Edges`]): the UART is clocked on XIN's
//! rising edges and the timer on CLKB's falling edges where the card's
//! oscillators have them, and a device's outputs change its own delay
//! after, so that the core can see OUT0 and the INT lines at the clocks
//! the card does.

use std::collections::VecDeque;

use crate::flash::Flash;
use devices::ds1302::Ds1302;
use devices::i8254::Timer;
use devices::uart16550::Uart;

pub const UART: usize = 12;
pub const FLASH: usize = 13;
pub const TIMER: usize = 14;
pub const PORTS: usize = 15;
pub const SLOTS: usize = 12;

pub const TT_WAIT: u16 = 1 << 12;

/// The watchdog's time: COLD if not kicked for this long (RFC 0027, 5).
pub const WATCHDOG_NS: u64 = 100_000_000;

/// The card's oscillators as edges on its time line, in ps from power-up:
/// XIN rises at `xin_first_ps` + k `xin_period_ps`, CLKB falls (the
/// 82C54 counts on its fall) at `clkb_first_ps` + k `clkb_period_ps`.
/// `t0_ps` is the model's time 0 on that line. The delays are the parts'
/// at the slow corner: the 82C54's CLK and WR to OUT, the 16C550's XIN to
/// INTR, as the chip-level simulator has them.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Edges {
    pub t0_ps: i64,
    pub xin_first_ps: i64,
    pub xin_period_ps: i64,
    pub clkb_first_ps: i64,
    pub clkb_period_ps: i64,
    pub timer_out_ps: i64,
    pub timer_wr_out_ps: i64,
    pub uart_out_ps: i64,
}

impl Edges {
    /// The card's (card.py): oscillators that start low and rise half a
    /// period in.
    pub fn card(uart_hz: f64, clkb_hz: f64, t0_ps: i64) -> Edges {
        let xp = (1e12 / uart_hz).round() as i64;
        let bp = (1e12 / clkb_hz).round() as i64;
        Edges {
            t0_ps,
            xin_first_ps: xp / 2,
            xin_period_ps: xp,
            clkb_first_ps: bp / 2 + bp / 2,
            clkb_period_ps: bp,
            timer_out_ps: 100_000,
            timer_wr_out_ps: 240_000,
            uart_out_ps: 30_000,
        }
    }
}

/// A line's changes, in time order: what it was before the first, and
/// what it changed to when.
#[derive(Clone, Debug, Default)]
struct Line {
    base: bool,
    last: bool,
    changes: VecDeque<(i64, bool)>,
}

impl Line {
    fn note(&mut self, t: i64, v: bool) {
        if v == self.last {
            return;
        }
        self.last = v;
        let i = self
            .changes
            .iter()
            .rposition(|&(t2, _)| t2 <= t)
            .map_or(0, |i| i + 1);
        self.changes.insert(i, (t, v));
    }

    /// The line at time t; what came before is forgotten.
    fn at(&mut self, t: i64) -> bool {
        while let Some(&(t2, v)) = self.changes.front() {
            if t2 > t {
                break;
            }
            self.base = v;
            self.changes.pop_front();
        }
        self.base
    }

    fn reset(&mut self, v: bool) {
        self.base = v;
        self.last = v;
        self.changes.clear();
    }
}

/// An I/O card in a slot: its registers by A0-A7, and its INT line.
pub trait IoCard: Send {
    /// A read: the value, and the lines the card drives (0x00FF for an
    /// 8-bit device).
    fn read(&mut self, reg: u8, now_ns: u64) -> (u16, u16);
    fn write(&mut self, reg: u8, v: u16, now_ns: u64);
    fn int(&self) -> bool;
    fn advance(&mut self, now_ns: u64);
    /// IORESET (RFC 0037, 19): the card's devices to their reset state.
    fn reset(&mut self, _now_ns: u64) {}
    /// The I/O bus's WAIT (RFC 0037, 18): for an access whose SEL rises at
    /// `sel_ps` on the card's time line, when the card's letting go of WAIT
    /// reaches the IOP's synchroniser, or None if it never does. At
    /// `sel_ps` or before for a card that doesn't hold it.
    fn wait_release_ps(&self, sel_ps: i64, _edges: &Edges) -> Option<i64> {
        Some(sel_ps)
    }
    /// The card itself, for the host's side of it (a terminal, a disk image).
    fn as_any(&mut self) -> &mut dyn std::any::Any;
}

/// The number of bus clocks an access takes, by its device's timing
/// table entry: to the strobe's end, then the hold.
pub fn access_clocks(entry: u16) -> u32 {
    strobe_end(entry) + hold(entry)
}

/// Clocks from an access's start to its strobe's end: (1 + SETUP) + STROBE.
pub fn strobe_end(entry: u16) -> u32 {
    1 + (entry & 3) as u32 + ((entry >> 2) & 63) as u32 + 1
}

/// Clocks of hold after the strobe: 1 + HOLD.
pub fn hold(entry: u16) -> u32 {
    1 + ((entry >> 8) & 15) as u32
}

pub struct IoBus {
    /// The timing table, None until written.
    pub ttab: [Option<u16>; 16],
    pub uart: Uart,
    pub flash: Flash,
    /// The image flash's page register: A8-A18.
    pub flash_page: u16,
    pub timer: Timer,
    /// The LEDs, and what was written to them, with the time.
    pub leds: u8,
    pub led_log: Vec<(u64, u8)>,
    /// Port 1 as last written.
    pub port1: u8,
    /// Jumpers J2-J7 in bits 2-7: 1 open, 0 fitted.
    pub jumpers: u8,
    /// The time of day.
    pub rtc: Ds1302,
    /// The last kick of the watchdog, None since COLD until the first:
    /// that arms it.
    pub kicked_ns: Option<u64>,
    pub slots: Vec<Option<Box<dyn IoCard>>>,
    /// The device whose strobe WAIT's bound cut off (IOTO, event port
    /// register 1), until register 3 is written.
    pub wait_timeout: Option<u8>,
    /// D0-D15's last value.
    pub hold: u16,
    pub now_ns: u64,
    pub edges: Edges,
    /// The next XIN and CLKB edges not yet applied, on the card's time line.
    xin_next: i64,
    clkb_next: i64,
    /// When the timer's OUT0 rose (its delay after), not yet taken as ticks.
    pub out0_rises: VecDeque<i64>,
    intr: Line,
    out2: Line,
    pub accesses: u64,
}

impl IoBus {
    pub fn new(flash: &[u8], edges: Edges) -> IoBus {
        IoBus {
            ttab: [None; 16],
            uart: Uart::new(),
            flash: Flash::new(flash),
            flash_page: 0,
            timer: Timer::new(),
            leds: 0,
            led_log: Vec::new(),
            port1: 0,
            jumpers: 0xFC,
            rtc: Ds1302::default(),
            kicked_ns: None,
            slots: (0..SLOTS).map(|_| None).collect(),
            wait_timeout: None,
            hold: 0,
            now_ns: 0,
            edges,
            xin_next: edges.xin_first_ps,
            clkb_next: edges.clkb_first_ps,
            out0_rises: VecDeque::new(),
            intr: Line::default(),
            out2: Line::default(),
            accesses: 0,
        }
    }

    /// A time of the model's, in ns, on the card's time line.
    pub fn abs_ps(&self, ns: u64) -> i64 {
        self.edges.t0_ps + ns as i64 * 1000
    }

    /// IORESET: the devices on the bus to their reset state, the cards'
    /// too. The table and the page register are the IOP's and keep their
    /// contents.
    pub fn reset(&mut self) {
        let t = self.now_ns;
        for c in self.slots.iter_mut().flatten() {
            c.reset(t);
        }
        self.uart.reset();
        self.timer = Timer::new();
        self.leds = 0;
        self.out0_rises.clear();
        self.intr.reset(self.uart.intr());
        self.out2.reset(self.timer.out(2));
    }

    /// COLD: port 1 is cleared, letting go of the clock chip, and the
    /// watchdog disarmed.
    pub fn cold(&mut self) {
        self.port1 = 0;
        self.kicked_ns = None;
        self.wait_timeout = None;
        let t = self.now_ns;
        self.rtc.set(false, false, true, t);
    }

    /// The clock chip's I/O line: pulled up, low when port 1 pulls it
    /// low or the chip drives it low.
    fn rtc_io(&self) -> bool {
        self.port1 & 8 == 0 && self.rtc.io().unwrap_or(true)
    }

    /// Bring the devices up to `now_ns`.
    pub fn advance(&mut self, now_ns: u64) {
        let t = self.abs_ps(now_ns);
        self.advance_ps(t);
        for c in self.slots.iter_mut().flatten() {
            c.advance(now_ns);
        }
        self.now_ns = self.now_ns.max(now_ns);
    }

    /// Apply the oscillators' edges up to t on the card's time line: the
    /// UART's in steps to its next change, the timer's one by one, noting
    /// when OUT0 rises and the INT outputs change.
    pub fn advance_ps(&mut self, t: i64) {
        let (xp, bp) = (self.edges.xin_period_ps, self.edges.clkb_period_ps);
        while self.xin_next <= t {
            let avail = ((t - self.xin_next) / xp + 1) as u64;
            let step = match self.uart.next_change() {
                Some(n) if n >= 1 && n < avail => n,
                _ => avail,
            };
            self.uart.clock(step);
            let last = self.xin_next + (step as i64 - 1) * xp;
            self.xin_next += step as i64 * xp;
            let v = self.uart.intr();
            self.intr.note(last + self.edges.uart_out_ps, v);
        }
        while self.clkb_next <= t {
            let was = self.timer.out(0);
            for i in 0..3 {
                self.timer.clock(i);
            }
            let at = self.clkb_next + self.edges.timer_out_ps;
            if !was && self.timer.out(0) {
                self.out0_rises.push_back(at);
            }
            let v = self.timer.out(2);
            self.out2.note(at, v);
            self.clkb_next += bp;
        }
    }

    /// The UART's next change, in ns from now, if it has one coming.
    pub fn uart_next_ns(&self) -> Option<u64> {
        let now = self.abs_ps(self.now_ns);
        self.uart.next_change().map(|x| {
            let t = self.xin_next + (x as i64 - 1) * self.edges.xin_period_ps;
            ((t - now).max(0) / 1000) as u64 + 1
        })
    }

    /// The INT lines as the card's register takes them at time t on its
    /// time line.
    pub fn int_lines_at(&mut self, t: i64) -> u16 {
        self.advance_ps(t);
        let mut m = 0u16;
        for (i, c) in self.slots.iter().enumerate() {
            if let Some(c) = c
                && c.int()
            {
                m |= 1 << i;
            }
        }
        if self.intr.at(t) {
            m |= 1 << UART;
        }
        if self.out2.at(t) {
            m |= 1 << TIMER;
        }
        m
    }

    /// The INT lines: one per device.
    pub fn int_lines(&self) -> u16 {
        let mut m = 0u16;
        for (i, c) in self.slots.iter().enumerate() {
            if let Some(c) = c
                && c.int()
            {
                m |= 1 << i;
            }
        }
        if self.uart.intr() {
            m |= 1 << UART;
        }
        if self.timer.out(2) {
            m |= 1 << TIMER;
        }
        m
    }

    /// The timing table's entry for a device, or why there isn't one.
    pub fn entry(&self, dev: usize) -> Result<u16, String> {
        self.ttab[dev].ok_or_else(|| {
            format!("I/O bus device {dev} accessed before its timing table entry was written")
        })
    }

    /// An access by the IOP: a read if `write` is None. Returns the value
    /// read (or written) and the bus clocks it took.
    pub fn access(
        &mut self,
        dev: usize,
        reg: u8,
        write: Option<u16>,
        now_ns: u64,
    ) -> Result<(u16, u32), String> {
        let t = self.abs_ps(now_ns);
        self.access_at(dev, reg, write, t)
    }

    /// The same, at time t on the card's time line: a read when its strobe
    /// starts, a write when its strobe ends, as the card's devices see them.
    pub fn access_at(
        &mut self,
        dev: usize,
        reg: u8,
        write: Option<u16>,
        t: i64,
    ) -> Result<(u16, u32), String> {
        let e = self.entry(dev)?;
        let ns = ((t - self.edges.t0_ps).max(0) / 1000) as u64;
        self.advance(ns);
        self.advance_ps(t);
        self.accesses += 1;
        let out0_was = self.timer.out(0);
        let v = match write {
            Some(v) => {
                self.write(dev, reg, v);
                v
            }
            None => self.read(dev, reg),
        };
        match dev {
            UART => {
                let v = self.uart.intr();
                self.intr.note(t + self.edges.uart_out_ps, v);
            }
            TIMER if write.is_some() => {
                let at = t + self.edges.timer_wr_out_ps;
                if !out0_was && self.timer.out(0) {
                    self.out0_rises.push_back(at);
                }
                let v = self.timer.out(2);
                self.out2.note(at, v);
            }
            _ => {}
        }
        Ok((v, access_clocks(e)))
    }

    fn read(&mut self, dev: usize, reg: u8) -> u16 {
        let t = self.now_ns;
        let (v, lines) = match dev {
            UART => (self.uart.read(reg & 7) as u16, 0x00FF),
            FLASH => (
                self.flash
                    .read((self.flash_page as u32) << 8 | reg as u32, t),
                0xFFFF,
            ),
            TIMER => (self.timer.read(reg & 3) as u16, 0x00FF),
            PORTS => match reg & 1 {
                0 => {
                    let v = self.rtc_io() as u8 | 2 | (self.jumpers & 0xFC);
                    (v as u16, 0x00FF)
                }
                _ => (0, 0),
            },
            s if s < SLOTS => match &mut self.slots[s] {
                Some(c) => c.read(reg, t),
                None => (0, 0),
            },
            _ => (0, 0),
        };
        self.hold = (v & lines) | (self.hold & !lines);
        self.hold
    }

    fn write(&mut self, dev: usize, reg: u8, v: u16) {
        let t = self.now_ns;
        self.hold = v;
        match dev {
            UART => self.uart.write(reg & 7, v as u8),
            FLASH => self
                .flash
                .write((self.flash_page as u32) << 8 | reg as u32, v, t),
            TIMER => self.timer.write(reg & 3, v as u8),
            PORTS => match reg & 1 {
                0 => {
                    self.leds = v as u8;
                    self.led_log.push((t, v as u8));
                }
                _ => {
                    if v & 1 != 0 {
                        self.kicked_ns = Some(t);
                    }
                    self.port1 = v as u8;
                    let io = self.rtc_io();
                    self.rtc.set(v & 2 != 0, v & 4 != 0, io, t);
                }
            },
            s if s < SLOTS => {
                if let Some(c) = &mut self.slots[s] {
                    c.write(reg, v, t)
                }
            }
            _ => {}
        }
    }

    /// An access through the window from the system bus (RFC 0037, 20):
    /// it reaches every device (RFC 0040, 15). Writes are posted there,
    /// which this model doesn't time. A device whose timing table entry
    /// hasn't been written reads all ones and ignores writes. Returns the
    /// value, and the I/O bus clocks it took.
    pub fn window(&mut self, dev: usize, reg: u8, write: Option<u16>, now_ns: u64) -> (u16, u32) {
        match self.ttab[dev] {
            Some(e) => {
                self.advance(now_ns);
                self.accesses += 1;
                let v = match write {
                    Some(v) => {
                        self.write(dev, reg, v);
                        v
                    }
                    None => self.read(dev, reg),
                };
                (v, access_clocks(e))
            }
            _ => (0xFFFF, 0),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timing() {
        // RFC 0037, 17's examples: the UART 0/2/0 in 4, the CF card in
        // mode 0 1/6/1 in 10
        assert_eq!(access_clocks(1 << 2), 4);
        assert_eq!(access_clocks(1 | 5 << 2 | 1 << 8), 10);
    }

    #[test]
    fn hold_on_eight_bit_devices() {
        let mut b = IoBus::new(&[0x34, 0x12], Edges::card(14_745_600.0, 4e6, 0));
        assert!(b.access(FLASH, 0, None, 0).is_err());
        for d in 12..16 {
            b.ttab[d] = Some(1 << 2);
        }
        assert_eq!(b.access(FLASH, 0, None, 0).unwrap().0, 0x1234);
        b.access(UART, 7, Some(0x55), 0).unwrap();
        assert_eq!(b.access(UART, 7, None, 0).unwrap().0, 0x0055);
        assert_eq!(b.access(FLASH, 0, None, 0).unwrap().0, 0x1234);
        assert_eq!(b.access(UART, 7, None, 0).unwrap().0, 0x1255);
    }
}
