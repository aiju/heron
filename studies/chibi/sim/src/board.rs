//! The board behind the CPU: the RAM, the I/O space and every device on
//! it, as board2.py's netlist has them (RFC 0047, 6 and 7).
//!
//! | Address | |
//! |---|---|
//! | A30 = 0 | RAM, 2 MB, repeated through the space |
//! | A30 = 1, A20 = 0 | the boot flash, its byte n at +2n ([`crate::flash`]) |
//! | A20 = 1, A16 = 0 | the expansion port: nothing yet |
//! | A20 = 1, A16 = 1 | the devices, a 4 KB slot each by A14-A12: 7 the suite's test fixture (the simulation's, [`crate::fixture`]), 6 UART 0, 5 the interrupt controller, 4 the video's control, 3 the PS/2 ports, 2 the slow devices, 1 UART 1 |
//!
//! The slow devices, by A6-A4: 000 the 82C54 (+2n its register n), 001 the
//! palette (+0x10 + 2n), 010 the PCM's sample (+0x20), 011 the CF card's
//! timing (+0x30, bit 0: PIO mode 4), 1xx the CF card (+0x40 + 2n its
//! command block's register n, +0x60 + 2n its control block's).
//!
//! **Time** is the master clock's ticks (19.86 ns). The CPU's cycle says
//! when each half starts; a device is brought up to the time when it's
//! accessed (the half's third tick, as the strobes start), and to the end
//! of a cycle once one of the devices has something due. Between those,
//! nothing outside the CPU looks at it. The UARTs and the timer count
//! their 1.8432 MHz clock's edges from power-on; the timer's outputs are
//! stepped to each change, so the interrupt, SREQ and the DAC's latch
//! change at the edge they would.
//!
//! **What the CPU reads where nothing drives the bus:** 0xFFFF for an
//! address no device answers; an 8-bit device's high byte 0 (the boot
//! flash's FF), as system2.py has them.

use devices::cf::CfCard;
use devices::i8254::Timer;
use devices::uart16550::Uart;

use crate::audio::Audio;
use crate::fixture::Fixture;
use crate::flash::Flash;
use crate::ps2::{Kind, Port};
use crate::video::Video;

pub const RAM_SIZE: usize = 0x20_0000;
/// The master clock's period, and the UARTs' and timer's, in ps.
pub const TICK_PS: u64 = 19_860;
pub const UCLK_PS: u64 = 542_535;
/// The ticks of a µs.
pub const US: f64 = 1e6 / TICK_PS as f64;
/// The tasks' words in RAM (RFC 0047, 7 and 9).
pub const COPPTR: u32 = 0x60;
pub const PCMPTR: u32 = 0x64;
pub const PCMEND: u32 = 0x68;
const PCM_LOG: usize = 4096;

/// The interrupt sources, in priority order (the controller's +0 bits).
pub const SOURCES: [&str; 8] = [
    "timer", "frame", "uart0", "uart1", "keyboard", "mouse", "cf", "button",
];

#[derive(Clone, Debug)]
pub struct Config {
    /// The suite's test fixture in slot 7.
    pub fixture: bool,
    /// Phase F as the clock generator gives it: a tick longer when a task
    /// starts or ends, two when the video's buffer is empty. Off, it's
    /// always three ticks, as rtl2.py counts it.
    pub stretch: bool,
    /// The mouse reports from power-on, as if a driver had enabled it.
    pub mouse_reporting: bool,
    /// When after power-on the keyboard and the mouse may first send (µs;
    /// system2.py's and the chip-level fixture's 50 and 70 µs, not a real
    /// device's self-test of half a second).
    pub kbd_ready_us: f64,
    pub mouse_ready_us: f64,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            fixture: true,
            stretch: true,
            mouse_reporting: false,
            kbd_ready_us: 50.0,
            mouse_ready_us: 70.0,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Region {
    Flash,
    Expansion,
    Slot(u32),
}

fn region(a: u32) -> Region {
    if a >> 20 & 1 == 0 {
        Region::Flash
    } else if a >> 16 & 1 == 0 {
        Region::Expansion
    } else {
        Region::Slot(a >> 12 & 7)
    }
}

/// UCLK's edges by tick `t`.
fn uclk_edges(t: u64) -> u64 {
    (t as u128 * TICK_PS as u128 / UCLK_PS as u128) as u64
}

/// The tick of UCLK's edge `e`.
fn tick_of_edge(e: u64) -> u64 {
    (e as u128 * UCLK_PS as u128).div_ceil(TICK_PS as u128) as u64
}

pub fn ns(t: u64) -> u64 {
    (t as u128 * TICK_PS as u128 / 1000) as u64
}

fn tick_of_ns(n: u64) -> u64 {
    (n as u128 * 1000).div_ceil(TICK_PS as u128) as u64
}

pub struct Board {
    pub cfg: Config,
    pub ram: Vec<u8>,
    pub flash: Flash,
    pub fixture: Fixture,
    pub uart: [Uart; 2],
    pub timer: Timer,
    pub cf: CfCard,
    /// The CF card at PIO mode 4 (U_SLOWD's CFFAST).
    pub cffast: bool,
    pub video: Video,
    pub ps2: [Port; 2],
    /// U_PCM, the sample the device task last wrote; SREQ, the PCM's
    /// request.
    pub pcm: u8,
    pub sreq: bool,
    /// The samples written to U_PCM, the first PCM_LOG of them (for tests).
    pub pcm_log: Vec<u8>,
    pub audio: Audio,
    /// The halt button's latch, TRACE (ODT's), the interrupt button's
    /// latch.
    pub hltq: bool,
    pub trace: bool,
    pub btnq: bool,
    /// UCLK's edges the UARTs and the timer have had.
    uclk: u64,
    now: u64,
    /// The next tick something on the board is due.
    pub next_event: u64,
    irq_line: bool,
    dreq_line: bool,
}

impl Board {
    pub fn new(cfg: Config) -> Board {
        let mut ps2 = [
            Port::new(Kind::Keyboard, US, cfg.kbd_ready_us),
            Port::new(Kind::Mouse, US, cfg.mouse_ready_us),
        ];
        ps2[1].reporting = cfg.mouse_reporting;
        let mut b = Board {
            cfg,
            ram: vec![0; RAM_SIZE],
            flash: Flash::new(US),
            fixture: Fixture::default(),
            uart: [Uart::new(), Uart::new()],
            timer: Timer::new(),
            cf: CfCard::new(Vec::new()),
            cffast: false,
            video: Video::new(),
            ps2,
            pcm: 0x80,
            sreq: false,
            pcm_log: Vec::new(),
            audio: Audio::new(),
            hltq: false,
            trace: false,
            btnq: false,
            uclk: 0,
            now: 0,
            next_event: 0,
            irq_line: false,
            dreq_line: false,
        };
        b.refresh();
        b
    }

    /// The board's time: as far as its devices have been brought.
    pub fn now(&self) -> u64 {
        self.now
    }

    /// The reset button (and power-on): the UARTs, the CF card, the
    /// video's control and the palette bank, the copper's enable, the PS/2
    /// ports' GALs, SREQ, the buttons' latches, TRACE and CFFAST. The
    /// timer, the palette, the flash and the RAM keep what they had.
    pub fn reset(&mut self, t: u64) {
        self.sync(t);
        for u in &mut self.uart {
            u.reset();
        }
        self.cf.reset(ns(t));
        self.video.reset();
        for p in &mut self.ps2 {
            p.reset(t);
        }
        self.sreq = false;
        self.hltq = false;
        self.trace = false;
        self.btnq = false;
        self.cffast = false;
        self.refresh();
    }

    // ---- the lines the CPU looks at

    /// IRQ: any source pending, or the fixture's interrupt.
    #[inline]
    pub fn irq(&self) -> bool {
        self.irq_line || (self.cfg.fixture && self.fixture.flag)
    }

    /// ODT asked for: the halt button's latch, or TRACE.
    #[inline]
    pub fn odt_req(&self) -> bool {
        self.hltq || self.trace
    }

    /// The device task's request: SREQ, or a PS/2 port's edge not taken.
    #[inline]
    pub fn dreq(&self) -> bool {
        self.dreq_line
    }

    /// The copper's request: CEN, and the scanline its target.
    #[inline]
    pub fn copreq(&self) -> bool {
        self.video.copreq()
    }

    /// The sources pending, a bit each in SOURCES's order.
    pub fn sources(&self) -> u8 {
        [
            self.timer.out(0),
            self.video.irq(),
            self.uart[0].intr(),
            self.uart[1].intr(),
            self.ps2[0].irq,
            self.ps2[1].irq,
            self.cf.intrq(),
            self.btnq,
        ]
        .iter()
        .enumerate()
        .fold(0, |m, (i, &on)| m | (on as u8) << i)
    }

    /// The vector the controller gives: 0x40 + 4k for the first source
    /// pending, 0x04 if none is.
    pub fn vector(&self) -> u16 {
        match self.sources() {
            0 => 0x04,
            s => 0x40 + 4 * s.trailing_zeros() as u16,
        }
    }

    /// Whether the video is fetching (phase F's length then varies).
    pub fn video_active(&self) -> bool {
        self.video.den && self.video.frame_line() < crate::video::HEIGHT as u32
    }

    /// Phase F starting at `t0`: the video's reads, and the ticks it's
    /// longer for them.
    #[inline]
    pub fn video_phase_f(&mut self, t0: u64) -> u64 {
        self.video.phase_f(t0)
    }

    // ---- time

    /// A CPU cycle's end, at `t`.
    #[inline]
    pub fn end_cycle(&mut self, t: u64) {
        if self.cfg.fixture {
            self.fixture.tick();
        }
        if t >= self.next_event {
            self.sync(t);
            self.refresh();
        }
    }

    /// Bring every device up to `t`.
    pub fn sync(&mut self, t: u64) {
        if t <= self.now {
            return;
        }
        let e = uclk_edges(t);
        if e > self.uclk {
            self.clock_uclk(e);
        }
        for p in &mut self.ps2 {
            p.advance(t);
        }
        self.cf.advance(ns(t));
        self.video.advance(t, &self.ram);
        self.now = t;
    }

    /// The timer's counters whose output changes are events: OUT0 the
    /// timer's interrupt, OUT1 the PCM's clock, OUT2 the speaker when the
    /// sound is recorded.
    fn watched(&self) -> usize {
        if self.audio.on { 3 } else { 2 }
    }

    fn clock_uclk(&mut self, e: u64) {
        let n = e - self.uclk;
        for u in &mut self.uart {
            u.clock(n);
        }
        let mut at = self.uclk;
        while at < e {
            let mut step = e - at;
            for k in 0..self.watched() {
                if let Some(c) = self.timer.next_change(k) {
                    step = step.min(c.max(1));
                }
            }
            let was = [self.timer.out(0), self.timer.out(1), self.timer.out(2)];
            for k in 0..3 {
                self.timer.clock_n(k, step);
            }
            at += step;
            self.timer_outputs(was, tick_of_edge(at));
        }
        self.uclk = e;
    }

    /// The timer's outputs may have changed at `t` from `was`.
    fn timer_outputs(&mut self, was: [bool; 3], t: u64) {
        let out1 = self.timer.out(1);
        if out1 && !was[1] {
            self.sreq = true;
        }
        if !out1 {
            // the DAC's latch follows U_PCM while OUT1 is low
            self.audio.set_dac(t, self.pcm);
        }
        self.audio.set_speaker(t, self.timer.out(2));
    }

    /// The cached lines and the next event, after anything changed.
    fn refresh(&mut self) {
        self.irq_line = self.sources() != 0;
        self.dreq_line = self.sreq || self.ps2[0].e || self.ps2[1].e;
        let mut n = self.video.next_event();
        for u in &self.uart {
            if let Some(x) = u.next_change() {
                n = n.min(tick_of_edge(self.uclk + x.max(1)));
            }
        }
        for k in 0..self.watched() {
            if let Some(x) = self.timer.next_change(k) {
                n = n.min(tick_of_edge(self.uclk + x.max(1)));
            }
        }
        for p in &self.ps2 {
            n = n.min(p.next_event());
        }
        if let Some(x) = self.cf.next_event_ns() {
            n = n.min(tick_of_ns(x));
        }
        self.next_event = n.max(self.now + 1);
    }

    // ---- the CPU's accesses

    /// A halfword read at `a` (the I/O space if `io`), in a half that
    /// starts at `t`, in CPU cycle `cycle` (for the fixture's counter).
    #[inline]
    pub fn read16(&mut self, a: u32, io: bool, t: u64, cycle: u64) -> u16 {
        if !io {
            let i = a as usize & (RAM_SIZE - 2);
            return u16::from_le_bytes([self.ram[i], self.ram[i + 1]]);
        }
        let t = t + 2;
        self.sync(t);
        let v = match region(a) {
            Region::Flash => self.flash.read(a >> 1 & 0x1FFFF, t) as u16 | 0xFF00,
            Region::Expansion => 0xFFFF,
            Region::Slot(7) if self.cfg.fixture => self.fixture.read(a, cycle),
            Region::Slot(6) => self.uart[0].read((a >> 1 & 7) as u8) as u16,
            Region::Slot(5) => match a >> 1 & 3 {
                0 => self.sources() as u16,
                1 => self.vector(),
                2 => {
                    if self.odt_req() {
                        0x9000
                    } else {
                        0
                    }
                }
                _ => self.video.scanline(),
            },
            Region::Slot(3) if a & 4 == 0 => {
                let k = (a >> 1 & 1) as usize;
                self.ps2[k].read() | if k == 1 { (self.sreq as u16) << 2 } else { 0 }
            }
            Region::Slot(2) => match a >> 4 & 7 {
                0 => self.timer.read((a >> 1 & 3) as u8) as u16,
                1 => self.video.palette.read(a >> 1 & 3) as u16,
                4..=7 => {
                    let cs1 = a >> 5 & 1 != 0;
                    let reg = (a >> 1 & 7) as u8;
                    let v = self.cf.read(cs1, reg, ns(t));
                    if !cs1 && reg == 0 { v } else { v & 0xFF }
                }
                _ => 0xFFFF,
            },
            Region::Slot(1) => self.uart[1].read((a >> 1 & 7) as u8) as u16,
            _ => 0xFFFF,
        };
        self.refresh();
        v
    }

    /// A read's side effects at the clock edge that ends it (the
    /// fixture's).
    pub fn read_edge(&mut self, a: u32, cycle: u64) {
        if self.cfg.fixture && region(a) == Region::Slot(7) {
            self.fixture.read_edge(a, cycle);
        }
    }

    /// A write of `v` at `a`: `lanes` 1 the low byte (an even address), 2
    /// the high, 3 both.
    #[inline]
    pub fn write(&mut self, a: u32, v: u16, lanes: u8, io: bool, t: u64) {
        if !io {
            let i = a as usize & (RAM_SIZE - 2);
            if lanes & 1 != 0 {
                self.ram[i] = v as u8;
            }
            if lanes & 2 != 0 {
                self.ram[i + 1] = (v >> 8) as u8;
            }
            return;
        }
        let t = t + 2;
        self.sync(t);
        let lo = lanes & 1 != 0;
        match region(a) {
            Region::Flash => {
                if lo {
                    self.flash.write(a >> 1 & 0x1FFFF, v as u8, t);
                }
            }
            Region::Expansion => {}
            Region::Slot(7) => {
                if self.cfg.fixture {
                    self.fixture.write(a, v, lanes);
                }
            }
            Region::Slot(6) => {
                if lo {
                    self.uart[0].write((a >> 1 & 7) as u8, v as u8);
                }
            }
            Region::Slot(5) => match a >> 1 & 3 {
                0 | 1 => self.btnq = false,
                2 => {
                    self.trace = v & 1 != 0;
                    self.hltq = false;
                }
                _ => self.video.write_target(v),
            },
            Region::Slot(4) => {
                if a & 2 == 0 {
                    self.video.write_control(v, t, &self.ram);
                } else {
                    self.video.write_bank(v, t, &self.ram);
                }
            }
            Region::Slot(3) => {
                let k = (a >> 1 & 1) as usize;
                if a & 4 == 0 {
                    self.ps2[k].take_edge();
                } else {
                    self.ps2[k].write_control(v, t);
                }
            }
            Region::Slot(2) => match a >> 4 & 7 {
                0 => {
                    let was = [self.timer.out(0), self.timer.out(1), self.timer.out(2)];
                    self.timer.write((a >> 1 & 3) as u8, v as u8);
                    self.timer_outputs(was, t);
                }
                1 => self.video.write_palette(a >> 1 & 3, v as u8, t, &self.ram),
                2 => {
                    self.pcm = v as u8;
                    if self.pcm_log.len() < PCM_LOG {
                        self.pcm_log.push(self.pcm);
                    }
                    self.sreq = false;
                    if !self.timer.out(1) {
                        self.audio.set_dac(t, self.pcm);
                    }
                }
                3 => self.cffast = v & 1 != 0,
                _ => {
                    let cs1 = a >> 5 & 1 != 0;
                    let reg = (a >> 1 & 7) as u8;
                    let v = if !cs1 && reg == 0 { v } else { v & 0xFF };
                    self.cf.write(cs1, reg, v, ns(t));
                }
            },
            Region::Slot(1) => {
                if lo {
                    self.uart[1].write((a >> 1 & 7) as u8, v as u8);
                }
            }
            Region::Slot(_) => {}
        }
        self.refresh();
    }

    /// The ticks of a half that accesses the I/O space at `a`: 6, or a slow
    /// device's (U_SLOW's count, plus two).
    #[inline]
    pub fn io_ticks(&self, a: u32) -> u64 {
        if region(a) == Region::Slot(2) {
            if a >> 6 & 1 != 0 {
                if self.cffast { 8 } else { 32 }
            } else {
                11
            }
        } else {
            6
        }
    }

    // ---- from outside

    /// The halt button: ODT at the next instruction's end.
    pub fn press_halt(&mut self) {
        self.hltq = true;
    }

    /// The interrupt button (its latch: the controller's source 7).
    pub fn press_interrupt(&mut self) {
        self.btnq = true;
        self.refresh();
    }

    /// A card with these contents in the slot, from `t`.
    pub fn set_cf(&mut self, image: Vec<u8>, t: u64) {
        self.sync(t);
        self.cf = CfCard::new(image);
        self.refresh();
    }

    /// Something from outside changed a device at `t`.
    pub fn poke(&mut self, t: u64) {
        self.sync(t);
        self.refresh();
    }
}
