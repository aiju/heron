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
//! | 15 | ports: 0 W the LEDs, R the panel's switches; 1 W bit 0 kicks the watchdog | D0-D7 |
//!
//! The time of day (a DS1302 on the ports) and the panel's shift chain
//! aren't modelled.
//!
//! **8-bit devices** drive D0-D7 only; D8-D15 keep what they last held, as
//! do all sixteen lines for a slot with no card, by the bus-hold of the
//! IOP's transceiver. So firmware masks what it reads from them.
//!
//! **An entry of the timing table** (RFC 0037, 17): bits 0-1 SETUP, 2-7
//! STROBE less one (1-64 clocks), 8-11 HOLD, 12 WAIT, 13 WINDOW. An access
//! takes (1 + SETUP) + STROBE + (1 + HOLD) bus clocks. The table is SRAM:
//! an access to a device whose entry hasn't been written since power-up
//! is an error here, since its timing would be whatever the SRAM held.

use crate::flash::Flash;
use devices::i8254::Timer;
use devices::uart16550::Uart;

pub const UART: usize = 12;
pub const FLASH: usize = 13;
pub const TIMER: usize = 14;
pub const PORTS: usize = 15;
pub const SLOTS: usize = 12;

pub const TT_WAIT: u16 = 1 << 12;
pub const TT_WINDOW: u16 = 1 << 13;

/// The watchdog's time: COLD if not kicked for this long (RFC 0027, 5).
pub const WATCHDOG_NS: u64 = 100_000_000;

/// An I/O card in a slot: its registers by A0-A7, and its INT line.
pub trait IoCard: Send {
    /// A read: the value, and the lines the card drives (0x00FF for an
    /// 8-bit device).
    fn read(&mut self, reg: u8, now_ns: u64) -> (u16, u16);
    fn write(&mut self, reg: u8, v: u16, now_ns: u64);
    fn int(&self) -> bool;
    fn advance(&mut self, now_ns: u64);
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
    pub switches: u8,
    /// The last kick of the watchdog.
    pub kicked_ns: u64,
    pub slots: Vec<Option<Box<dyn IoCard>>>,
    /// D0-D15's last value.
    pub hold: u16,
    pub now_ns: u64,
    uart_hz: f64,
    clkb_hz: f64,
    uart_frac: f64,
    clkb_frac: f64,
    /// Rising edges of the timer's OUT0 not yet taken as ticks.
    pub tick_edges: u64,
    pub accesses: u64,
}

impl IoBus {
    pub fn new(flash: &[u8], uart_hz: f64, clkb_hz: f64) -> IoBus {
        IoBus {
            ttab: [None; 16],
            uart: Uart::new(),
            flash: Flash::new(flash),
            flash_page: 0,
            timer: Timer::new(),
            leds: 0,
            led_log: Vec::new(),
            switches: 0,
            kicked_ns: 0,
            slots: (0..SLOTS).map(|_| None).collect(),
            hold: 0,
            now_ns: 0,
            uart_hz,
            clkb_hz,
            uart_frac: 0.0,
            clkb_frac: 0.0,
            tick_edges: 0,
            accesses: 0,
        }
    }

    /// IORESET: the devices on the bus to their reset state. The table
    /// and the page register are the IOP's and keep their contents.
    pub fn reset(&mut self) {
        self.uart.reset();
        self.timer = Timer::new();
        self.leds = 0;
    }

    /// Bring the devices up to `now_ns`.
    pub fn advance(&mut self, now_ns: u64) {
        if now_ns <= self.now_ns {
            return;
        }
        let dt = (now_ns - self.now_ns) as f64 / 1e9;
        let x = dt * self.uart_hz + self.uart_frac;
        self.uart.clock(x.floor() as u64);
        self.uart_frac = x.fract();
        let p = dt * self.clkb_hz + self.clkb_frac;
        let n = p.floor() as u64;
        self.clkb_frac = p.fract();
        if n > 0 {
            self.tick_edges += self.timer.clock_n(0, n);
            self.timer.clock_n(1, n);
            self.timer.clock_n(2, n);
        }
        for c in self.slots.iter_mut().flatten() {
            c.advance(now_ns);
        }
        self.now_ns = now_ns;
    }

    /// The UART's next change, in ns from now, if it has one coming.
    pub fn uart_next_ns(&self) -> Option<u64> {
        self.uart
            .next_change()
            .map(|x| ((x as f64 - self.uart_frac).max(0.0) * 1e9 / self.uart_hz).ceil() as u64)
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
        let e = self.entry(dev)?;
        self.advance(now_ns);
        self.accesses += 1;
        let v = match write {
            Some(v) => {
                self.write(dev, reg, v);
                v
            }
            None => self.read(dev, reg),
        };
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
                0 => (self.switches as u16, 0x00FF),
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
                        self.kicked_ns = t;
                    }
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
    /// devices without WINDOW in their entry ignore writes and read all
    /// ones. Returns the value, and the I/O bus clocks it took.
    pub fn window(&mut self, dev: usize, reg: u8, write: Option<u16>, now_ns: u64) -> (u16, u32) {
        match self.ttab[dev] {
            Some(e) if e & TT_WINDOW != 0 => {
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
        let mut b = IoBus::new(&[0x34, 0x12], 14_745_600.0, 4e6);
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
