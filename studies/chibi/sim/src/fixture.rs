//! The program suite's I/O page, a test fixture in slot 7 (0xFFFF_F000;
//! the console at 0xFFFF_FF00), as system.py's `Console` and the
//! chip-level simulator's `iodev32` have it. The board leaves the slot
//! free; the fixture is the simulation's.
//!
//! Its registers, a half at a time, by A7-A1:
//!   +00  R: console input byte (a read takes it), FFFF once none is left
//!        W: console output (the low byte)
//!   +02  R: FFFF after a read of +00 that found none
//!   +04  R: 1 input waiting, 2 the end of the input
//!   +08, +0A  the timer's period in CPU cycles (microinstructions), low
//!        and high half; its flag sets every period, and is the
//!        fixture's interrupt
//!   +0C  R: the timer's flag  W: (or +0E) clears it
//!   +10, +12  the cycle counter: the low half, and the high half as the
//!        low half's read left it

#[derive(Clone, Debug, Default)]
pub struct Fixture {
    pub inp: Vec<u8>,
    pub pos: usize,
    pub out: Vec<u8>,
    pub period: u32,
    pub count: u32,
    pub flag: bool,
    last_empty: bool,
    cycle_hi: u16,
}

impl Fixture {
    pub fn new(inp: &[u8]) -> Fixture {
        Fixture {
            inp: inp.to_vec(),
            ..Fixture::default()
        }
    }

    pub fn read(&self, a: u32, cycle: u64) -> u16 {
        let has = self.pos < self.inp.len();
        match a & 0xFE {
            0x00 if has => self.inp[self.pos] as u16,
            0x00 => 0xFFFF,
            0x02 if self.last_empty => 0xFFFF,
            0x04 if has => 1,
            0x04 => 2,
            0x08 => self.period as u16,
            0x0A => (self.period >> 16) as u16,
            0x0C => self.flag as u16,
            0x10 => cycle as u16,
            0x12 => self.cycle_hi,
            _ => 0,
        }
    }

    /// A read's side effects, at the clock edge that ends it.
    pub fn read_edge(&mut self, a: u32, cycle: u64) {
        match a & 0xFE {
            0x00 => {
                if self.pos < self.inp.len() {
                    self.pos += 1;
                    self.last_empty = false;
                } else {
                    self.last_empty = true;
                }
            }
            0x10 => self.cycle_hi = (cycle >> 16) as u16,
            _ => {}
        }
    }

    pub fn write(&mut self, a: u32, v: u16, lanes: u8) {
        match a & 0xFE {
            0x00 => {
                if lanes & 1 != 0 {
                    self.out.push(v as u8);
                }
            }
            0x08 => {
                self.period = v as u32;
                self.count = 0;
                if v == 0 {
                    self.flag = false;
                }
            }
            0x0A => {
                self.period = (self.period & 0xFFFF) | (v as u32) << 16;
                self.count = 0;
                if self.period == 0 {
                    self.flag = false;
                }
            }
            0x0C | 0x0E => self.flag = false,
            _ => {}
        }
    }

    /// A CPU cycle's end.
    #[inline]
    pub fn tick(&mut self) {
        if self.period > 0 {
            self.count += 1;
            if self.count >= self.period {
                self.flag = true;
                self.count = 0;
            }
        }
    }

    /// The cycles until the flag next sets by itself, if it's counting.
    pub fn cycles_to_flag(&self) -> Option<u64> {
        (self.period > 0).then(|| (self.period - self.count.min(self.period)) as u64)
    }

    /// `n` cycle ends at once.
    pub fn ticks(&mut self, n: u64) {
        if self.period > 0 && n > 0 {
            let total = self.count as u64 + n;
            if total >= self.period as u64 {
                self.flag = true;
            }
            self.count = (total % self.period as u64) as u32;
        }
    }
}
