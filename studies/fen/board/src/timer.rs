//! The CPU board's timer: a free-running counter of microseconds and a
//! compare register that interrupts once, the timer report 0020 and RFC
//! 0009 recommend for a tickless kernel.
//!
//! Registers, 32 bits:
//!   +0  R: the counter, microseconds since reset (wraps in 71 minutes)
//!   +4  R/W: compare. Writing it arms the timer and clears FIRED; when
//!       the counter reaches it, FIRED is set and stays set
//!   +8  R: bit 0 FIRED, bit 1 ARMED
//!       W: bit 0 clears FIRED, bit 1 disarms

#[derive(Clone, Debug, Default)]
pub struct Timer {
    pub compare: u32,
    pub armed: bool,
    pub fired: bool,
}

impl Timer {
    /// The counter at a time.
    pub fn count(now_ns: u64) -> u32 {
        (now_ns / 1000) as u32
    }

    /// Bring the timer up to `now_ns`.
    pub fn advance(&mut self, now_ns: u64) {
        if self.armed && Self::count(now_ns).wrapping_sub(self.compare) as i32 >= 0 {
            self.fired = true;
            self.armed = false;
        }
    }

    /// When it will fire, if armed.
    pub fn next_ns(&self, now_ns: u64) -> Option<u64> {
        if !self.armed {
            return None;
        }
        let ahead = self.compare.wrapping_sub(Self::count(now_ns)) as u64;
        Some((now_ns / 1000 + ahead) * 1000)
    }

    pub fn read(&mut self, reg: u32, now_ns: u64) -> u32 {
        self.advance(now_ns);
        match reg {
            0 => Self::count(now_ns),
            4 => self.compare,
            8 => self.fired as u32 | (self.armed as u32) << 1,
            _ => 0,
        }
    }

    pub fn write(&mut self, reg: u32, v: u32, now_ns: u64) {
        match reg {
            4 => {
                self.compare = v;
                self.armed = true;
                self.fired = false;
                self.advance(now_ns);
            }
            8 => {
                if v & 1 != 0 {
                    self.fired = false;
                }
                if v & 2 != 0 {
                    self.armed = false;
                }
            }
            _ => {}
        }
    }
}
