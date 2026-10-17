//! I/O cards for the I/O bus's slots (RFC 0037, 21's list of cards).
//!
//! - [`Cf`]: a CompactFlash card in True IDE mode on a connector and a
//!   74HCT132. A0-A2 pick the task file's register, A3 the second chip
//!   select (CS1, whose register 6 is the alternate status and the device
//!   control); the data register is 16 bits wide, the rest 8. Its INTRQ
//!   is the slot's INT.
//! - [`Serial`]: two serial lines, two 16C550s from CLKA (1.8432 MHz, up
//!   to 115,200 baud). A0-A2 pick the register, A3 the line. INT is
//!   either UART's interrupt.
//! - [`Gpio`]: general-purpose I/O, two latches and two buffers: register
//!   0 R the inputs, W the outputs; register 1 W the inputs that raise
//!   INT. Its inputs are the host's, so a test can raise INT.
//! - [`Waiter`]: the chip-level bench's WAIT cards (card.py's
//!   wait_cards), which hold the I/O bus's WAIT (RFC 0037, 18).

use crate::iobus::{Edges, IoCard};
use crate::iop::Iop;
use devices::cf::CfCard;
use devices::uart16550::Uart;
use std::any::Any;

pub const CLKA_HZ: f64 = 1_843_200.0;

/// The slots the study's firmware looks for its cards in (layout.py).
pub const DISK_SLOT: usize = 0;
pub const SERIAL_SLOT: usize = 1;

/// Cards into an IOP's slots: a CF card holding `disk`, the serial card,
/// GPIO cards, WAIT cards as (slot, value, CLKB rises) (Waiter).
pub fn fit(
    iop: &mut Iop,
    disk: Option<Vec<u8>>,
    serial: bool,
    gpio: &[usize],
    waiters: &[(usize, u8, Option<u32>)],
) {
    if let Some(image) = disk {
        iop.io.slots[DISK_SLOT] = Some(Box::new(Cf::new(image)));
    }
    if serial {
        iop.io.slots[SERIAL_SLOT] = Some(Box::new(Serial::new(iop.io.edges.t0_ps)));
    }
    for &(slot, value, clkb) in waiters {
        if slot < iop.io.slots.len() {
            iop.io.slots[slot] = Some(Box::new(Waiter { value, clkb }));
        }
    }
    for &slot in gpio {
        if slot < iop.io.slots.len() {
            iop.io.slots[slot] = Some(Box::new(Gpio {
                int_mask: 0xFFFF,
                ..Gpio::default()
            }));
        }
    }
}

/// The CF card's image, if the IOP has one.
pub fn disk_image(iop: &mut Iop) -> Option<Vec<u8>> {
    iop.io.slots[DISK_SLOT]
        .as_mut()
        .and_then(|c| c.as_any().downcast_mut::<Cf>())
        .map(|c| c.card.image().to_vec())
}

pub struct Cf {
    pub card: CfCard,
}

impl Cf {
    pub fn new(image: Vec<u8>) -> Cf {
        Cf {
            card: CfCard::new(image),
        }
    }
}

impl IoCard for Cf {
    /// The card drives all of D, an 8-bit register's upper byte high.
    fn read(&mut self, reg: u8, now_ns: u64) -> (u16, u16) {
        (self.card.read(reg & 8 != 0, reg & 7, now_ns), 0xFFFF)
    }

    fn write(&mut self, reg: u8, v: u16, now_ns: u64) {
        self.card.write(reg & 8 != 0, reg & 7, v, now_ns);
    }

    fn int(&self) -> bool {
        self.card.intrq()
    }

    fn advance(&mut self, now_ns: u64) {
        self.card.advance(now_ns);
    }

    fn reset(&mut self, now_ns: u64) {
        self.card.reset(now_ns);
    }

    fn as_any(&mut self) -> &mut dyn Any {
        self
    }
}

/// Its UARTs are clocked on CLKA's rising edges as the IOP's card has
/// them (card.py: an oscillator that starts low and rises half a period
/// in), on the card's time line, where the model's time 0 is `t0_ps`.
pub struct Serial {
    pub lines: [Uart; 2],
    t0_ps: i64,
    next_ps: i64,
    period_ps: i64,
}

impl Serial {
    pub fn new(t0_ps: i64) -> Serial {
        let period_ps = (1e12 / CLKA_HZ).round() as i64;
        Serial {
            lines: [Uart::new(), Uart::new()],
            t0_ps,
            next_ps: period_ps / 2,
            period_ps,
        }
    }
}

impl Default for Serial {
    fn default() -> Serial {
        Serial::new(0)
    }
}

impl IoCard for Serial {
    fn read(&mut self, reg: u8, now_ns: u64) -> (u16, u16) {
        self.advance(now_ns);
        let u = &mut self.lines[(reg >> 3) as usize & 1];
        (u.read(reg & 7) as u16, 0x00FF)
    }

    fn write(&mut self, reg: u8, v: u16, now_ns: u64) {
        self.advance(now_ns);
        self.lines[(reg >> 3) as usize & 1].write(reg & 7, v as u8);
    }

    fn int(&self) -> bool {
        self.lines.iter().any(|u| u.intr())
    }

    fn advance(&mut self, now_ns: u64) {
        let t = self.t0_ps + now_ns as i64 * 1000;
        if t < self.next_ps {
            return;
        }
        let n = (t - self.next_ps) / self.period_ps + 1;
        for u in &mut self.lines {
            u.clock(n as u64);
        }
        self.next_ps += n * self.period_ps;
    }

    fn reset(&mut self, now_ns: u64) {
        self.advance(now_ns);
        for u in &mut self.lines {
            u.reset();
        }
    }

    fn as_any(&mut self) -> &mut dyn Any {
        self
    }
}

#[derive(Default)]
pub struct Gpio {
    pub inputs: u16,
    pub outputs: u16,
    pub int_mask: u16,
}

impl IoCard for Gpio {
    fn read(&mut self, reg: u8, _now_ns: u64) -> (u16, u16) {
        match reg & 1 {
            0 => (self.inputs, 0xFFFF),
            _ => (0, 0),
        }
    }

    fn write(&mut self, reg: u8, v: u16, _now_ns: u64) {
        match reg & 1 {
            0 => self.outputs = v,
            _ => self.int_mask = v,
        }
    }

    fn int(&self) -> bool {
        self.inputs & self.int_mask != 0
    }

    fn advance(&mut self, _now_ns: u64) {}

    fn as_any(&mut self) -> &mut dyn Any {
        self
    }
}

/// A card that answers reads of any register with `value` and holds
/// WAIT from SEL's rise: until a 74HCT163 clocked by CLKB has counted
/// `clkb` rises with SEL high, or for as long as SEL is (None). CLKB rises
/// half a period in and every period after (card.py's oscillator); the
/// count's end reaches the IOP's synchroniser through the counter's RCO,
/// two 74F00s, a 74ABT125's turn-off and the IOP's 74F04, at the slow
/// corner.
pub struct Waiter {
    pub value: u8,
    pub clkb: Option<u32>,
}

const WAITER_RELEASE_PS: i64 = 61_000 + 6_000 + 6_000 + 6_200 + 6_000;

impl IoCard for Waiter {
    fn read(&mut self, _reg: u8, _now_ns: u64) -> (u16, u16) {
        (self.value as u16, 0x00FF)
    }

    fn write(&mut self, _reg: u8, _v: u16, _now_ns: u64) {}

    fn int(&self) -> bool {
        false
    }

    fn advance(&mut self, _now_ns: u64) {}

    fn wait_release_ps(&self, sel_ps: i64, edges: &Edges) -> Option<i64> {
        let n = self.clkb? as i64;
        let p = edges.clkb_period_ps;
        // the first rise after SEL's
        let k0 = (sel_ps - p / 2).div_euclid(p) + 1;
        Some(p / 2 + (k0 + n - 1) * p + WAITER_RELEASE_PS)
    }

    fn as_any(&mut self) -> &mut dyn Any {
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cf_registers() {
        let mut c = Cf::new(vec![0x11; 1024]);
        // device control through CS1 (A3): nIEN
        c.write(8 | 6, 2, 0);
        assert!(!c.int());
        // the status: ready
        assert_eq!(c.read(7, 0).0 & 0x40, 0x40);
    }

    #[test]
    fn serial_lines() {
        let mut s = Serial::default();
        s.write(3, 0x80, 0);
        s.write(0, 1, 0); // 115,200 baud from CLKA
        s.write(3, 3, 0);
        s.write(8 + 7, 0x5A, 0); // line 1's scratch register
        assert_eq!(s.read(8 + 7, 0).0, 0x5A);
        assert_eq!(s.read(7, 0).0 & 0xFF, 0);
        s.write(0, b'x' as u16, 0);
        s.advance(200_000);
        assert_eq!(s.lines[0].tx_out, b"x");
    }
}
