//! The system of studies/v1b_system as the instruction-level simulator sees it:
//! the CPU card's RAM in slot 0, the memory card in slot 1, the I/O card in
//! slot 15, and nothing in the other slots. It's the reference the
//! chip-level system is checked against, so it decodes addresses as the
//! cards do (studies/v1b_system/memcard.py and iocard.py).
//!
//! Time comes from the machine's cycle count, at an assumed cycle time:
//! the UART, the timer and the CF card move on by the time that has passed.
//! Only results that don't depend on how long anything takes can be
//! compared with the hardware.

use devices::cf::CfCard;
use devices::i8254::Timer;
use devices::uart16550::Uart;
use v1_isa::machine::Bus;

pub const MEM_SLOT: u32 = 1;
pub const IO_SLOT: u32 = 15;
/// The memory card: 2 MB, its ID at A27.
pub const MEM_SIZE: usize = 2 << 20;
pub const MEM_ID: u16 = 0x0102;
pub const IO_ID: u8 = 0x10;

/// Settings of a run.
#[derive(Clone, Debug)]
pub struct Config {
    /// The time a cycle of the machine stands for.
    pub ns_per_cycle: f64,
    pub uart_hz: f64,
    pub timer_hz: f64,
    /// HALT with interrupts on gives up after this long without one.
    pub halt_limit_ns: f64,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            ns_per_cycle: 300.0,
            uart_hz: 14_745_600.0,
            timer_hz: 1_000_000.0,
            halt_limit_ns: 1e9,
        }
    }
}

/// The cards behind the CPU card.
pub struct System {
    pub cfg: Config,
    pub mem: Vec<u8>,
    pub uart: Uart,
    pub timer: Timer,
    pub cf: CfCard,
    /// The timer's interrupt flag (set by OUT0 rising, cleared by the
    /// acknowledge).
    pub tflag: bool,
    /// The time devices have been brought up to, and the fractions of their
    /// clocks not counted yet.
    now_ns: f64,
    uart_frac: f64,
    timer_frac: f64,
}

impl System {
    pub fn new(cfg: Config, uart_in: &[u8], cf_image: Vec<u8>) -> System {
        let mut uart = Uart::new();
        uart.rx_in.extend(uart_in.iter().copied());
        System {
            cfg,
            mem: vec![0; MEM_SIZE],
            uart,
            timer: Timer::new(),
            cf: CfCard::new(cf_image),
            tflag: false,
            now_ns: 0.0,
            uart_frac: 0.0,
            timer_frac: 0.0,
        }
    }

    /// Bring the devices up to a time.
    fn advance_to(&mut self, t: f64) {
        if t <= self.now_ns {
            return;
        }
        let dt = t - self.now_ns;
        self.now_ns = t;
        let u = dt * self.cfg.uart_hz / 1e9 + self.uart_frac;
        self.uart.clock(u.floor() as u64);
        self.uart_frac = u.fract();
        let k = dt * self.cfg.timer_hz / 1e9 + self.timer_frac;
        if self.timer.clock_n(0, k.floor() as u64) > 0 {
            self.tflag = true;
        }
        self.timer_frac = k.fract();
        self.cf.advance(t as u64);
    }

    fn advance(&mut self, cycles: u64) {
        self.advance_to(cycles as f64 * self.cfg.ns_per_cycle);
    }

    fn requested(&self) -> bool {
        self.uart.intr() || self.cf.intrq() || self.tflag
    }

    /// A transfer to the memory card.
    fn mem_card(&mut self, a: u32, write: bool, be: u8, data: u16) -> u16 {
        if a & (1 << 27) != 0 {
            return if a & 2 == 0 { MEM_ID } else { 0xFFFF };
        }
        let i = (a as usize) & (MEM_SIZE - 2);
        if write {
            if be & 1 != 0 {
                self.mem[i] = data as u8;
            }
            if be & 2 != 0 {
                self.mem[i + 1] = (data >> 8) as u8;
            }
            return 0;
        }
        self.mem[i] as u16 | (self.mem[i + 1] as u16) << 8
    }

    /// A transfer to the I/O card. It decodes A2-A8 only and ignores the
    /// byte enables, as a simple card does: its devices are on D0-D7, and
    /// any read has its ID on D8-D15.
    fn io_card(&mut self, a: u32, write: bool, data: u16) -> u16 {
        let reg = ((a >> 2) & 7) as u8;
        let (a5, a6, a7, a8) = ((a >> 5) & 1, (a >> 6) & 1, (a >> 7) & 1, (a >> 8) & 1);
        let now = self.now_ns as u64;
        let byte = data as u8;
        let mut out = 0xFFu8; // nothing drives D0-D7: the pull-ups
        if a7 == 1 && a6 == 1 && a5 == 0 {
            if write {
                self.uart.write(reg, byte);
            } else {
                out = self.uart.read(reg);
            }
        }
        if a6 == 0 || a7 == 0 {
            // CS0 (task file) is A6 low, CS1 (control block) A7 low
            let cs1 = a7 == 0;
            if write {
                self.cf.write(cs1, reg, data & 0xFF, now);
            } else {
                out = self.cf.read(cs1, reg, now) as u8;
            }
        }
        if a7 == 1 && a6 == 1 && a5 == 1 {
            if a8 == 1 {
                if write {
                    self.timer.write(reg & 3, byte);
                } else {
                    out = self.timer.read(reg & 3);
                }
            } else if write {
                self.tflag = false;
            }
        }
        out as u16 | (IO_ID as u16) << 8
    }
}

impl Bus for System {
    fn local(&self, a: u32) -> Option<u32> {
        (a >> 28 == 0).then_some(a & 0x000F_FFFF)
    }

    fn transfer(&mut self, a: u32, write: bool, be: u8, data: u16, cycles: u64) -> Option<u16> {
        self.advance(cycles);
        match a >> 28 {
            MEM_SLOT => Some(self.mem_card(a & 0x0FFF_FFFF, write, be, data)),
            IO_SLOT => Some(self.io_card(a, write, data)),
            _ => None,
        }
    }

    fn irq(&mut self, cycles: u64) -> bool {
        self.advance(cycles);
        self.requested()
    }

    fn wait_irq(&mut self, cycles: u64) -> Option<u64> {
        self.advance(cycles);
        let limit = self.now_ns + self.cfg.halt_limit_ns;
        let step = 1000.0; // 1 µs
        let mut c = cycles;
        while !self.requested() {
            if self.now_ns >= limit {
                return None;
            }
            c += (step / self.cfg.ns_per_cycle).ceil() as u64;
            self.advance(c);
        }
        Some(c)
    }

    fn dump(&self, what: &str) -> Option<Vec<u8>> {
        match what {
            "uart" => Some(self.uart.tx_out.clone()),
            "cf" => Some(self.cf.image().to_vec()),
            "mem" => Some(self.mem.clone()),
            _ => None,
        }
    }
}
