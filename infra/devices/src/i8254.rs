//! An 82C54 programmable interval timer: three 16-bit down counters, each
//! with a CLK and a GATE input and an OUT output, programmed in one of six
//! modes, in binary or BCD.
//!
//! Time is counted in CLK pulses. A pulse is the whole clock cycle: the
//! GATE is sampled on its rising edge and the count changes on its falling
//! edge, so [`Timer::clock`] does both. A count written to a counter goes
//! to its count register (CR) and is loaded into the counting element (CE)
//! on a later pulse, as the mode says; reads see CE, or what was latched.
//!
//! [`Timer::clock_n`] runs many pulses at once: it steps only the pulses
//! where something other than the count changes, skips the rest, and skips
//! whole periods of modes 2 and 3, so its cost doesn't grow with `n`.

/// Status byte bits from the read-back command.
const STATUS_OUT: u8 = 0x80;
const STATUS_NULL: u8 = 0x40;

/// A count of pulses that never ends.
const FOREVER: u64 = u64::MAX;

/// One counter, with its control word, registers and latches.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Counter {
    /// The control word's RW, mode and BCD bits (bits 5:0), as written.
    ctrl: u8,
    /// The mode, 0..=5 (modes 6 and 7 are 2 and 3).
    mode: u8,
    /// Count register: the last count written.
    cr: u16,
    /// Counting element.
    ce: u16,
    /// The low byte of a two-byte count, until the high byte comes.
    lsb: u8,
    /// The next write is the high byte of a two-byte count.
    write_msb: bool,
    /// The next read is the high byte of a two-byte count.
    read_msb: bool,
    /// Output latch, from a counter latch or read-back command.
    latch: Option<u16>,
    /// Status latch, from a read-back command.
    status: Option<u8>,
    /// CR holds a count that hasn't been loaded into CE yet.
    null_count: bool,
    out: bool,
    gate: bool,
    /// A rising edge of GATE, not yet seen by a pulse (modes 1, 2, 3, 5).
    trigger: bool,
    /// Load CR into CE on the next pulse (modes 0, 2, 3, 4).
    load: bool,
    /// A count has been written since the control word.
    has_count: bool,
    /// CE holds a count and runs.
    counting: bool,
    /// Modes 4 and 5: the strobe for the current load is still to come.
    armed: bool,
    /// Mode 3, odd count: CE ran out in the high half, which lasts one
    /// pulse more.
    expired: bool,
    /// Mode 3: the count last loaded was odd.
    odd: bool,
}

impl Counter {
    /// A counter at power-on: the datasheet leaves its state undefined, so
    /// it's as if mode 0, binary, LSB then MSB had been programmed and no
    /// count written. GATE is high, as if tied to VCC.
    fn new() -> Counter {
        Counter {
            ctrl: 0x30,
            mode: 0,
            cr: 0,
            ce: 0,
            lsb: 0,
            write_msb: false,
            read_msb: false,
            latch: None,
            status: None,
            null_count: true,
            out: false,
            gate: true,
            trigger: false,
            load: false,
            has_count: false,
            counting: false,
            armed: false,
            expired: false,
            odd: false,
        }
    }

    fn bcd(&self) -> bool {
        self.ctrl & 1 != 0
    }

    fn rw(&self) -> u8 {
        (self.ctrl >> 4) & 3
    }

    /// The number of distinct counts: 65536 in binary, 10000 in BCD.
    fn modulus(&self) -> u64 {
        if self.bcd() { 10_000 } else { 65_536 }
    }

    /// A count as a number. BCD digits above 9 aren't defined; they're
    /// taken at face value, modulo 10000.
    fn num(&self, v: u16) -> u64 {
        if self.bcd() {
            let d = |i: u32| ((v >> (4 * i)) & 15) as u64;
            (d(3) * 1000 + d(2) * 100 + d(1) * 10 + d(0)) % 10_000
        } else {
            v as u64
        }
    }

    /// A number as a count.
    fn enc(&self, n: u64) -> u16 {
        if self.bcd() {
            let d = |p: u64| ((n / p) % 10) as u16;
            (d(1000) << 12) | (d(100) << 8) | (d(10) << 4) | d(1)
        } else {
            n as u16
        }
    }

    /// The pulses a count lasts: 0 is the largest count, one past 65535
    /// (or 9999).
    fn span(&self, v: u16) -> u64 {
        match self.num(v) {
            0 => self.modulus(),
            n => n,
        }
    }

    /// v counted down k times, wrapping around.
    fn dec(&self, v: u16, k: u64) -> u16 {
        let m = self.modulus();
        self.enc((self.num(v) + m - k % m) % m)
    }

    /// CR as CE takes it: mode 3 loads an odd count minus one.
    fn reload_value(&self) -> u16 {
        let v = self.enc(self.num(self.cr));
        if self.mode == 3 { v & !1 } else { v }
    }

    /// Transfer CR to CE.
    fn load_ce(&mut self) {
        self.ce = self.reload_value();
        self.odd = self.num(self.cr) & 1 != 0;
        self.expired = false;
        self.load = false;
        self.null_count = false;
        self.counting = true;
    }

    fn control(&mut self, v: u8) {
        self.ctrl = v & 0x3F;
        self.mode = match (v >> 1) & 7 {
            6 => 2,
            7 => 3,
            m => m,
        };
        self.out = self.mode != 0;
        self.null_count = true;
        self.write_msb = false;
        self.read_msb = false;
        self.latch = None;
        self.status = None;
        self.trigger = false;
        self.load = false;
        self.has_count = false;
        self.counting = false;
        self.armed = false;
        self.expired = false;
    }

    fn latch_count(&mut self) {
        // A second latch before the first is read is ignored.
        if self.latch.is_none() {
            self.latch = Some(self.ce);
        }
    }

    fn latch_status(&mut self) {
        if self.status.is_none() {
            let mut s = self.ctrl;
            if self.out {
                s |= STATUS_OUT;
            }
            if self.null_count {
                s |= STATUS_NULL;
            }
            self.status = Some(s);
        }
    }

    fn read(&mut self) -> u8 {
        // A latched status comes first, then the latched count.
        if let Some(s) = self.status.take() {
            return s;
        }
        let v = self.latch.unwrap_or(self.ce);
        let (byte, done) = match self.rw() {
            1 => (v as u8, true),
            2 => ((v >> 8) as u8, true),
            _ => {
                self.read_msb = !self.read_msb;
                if self.read_msb {
                    (v as u8, false)
                } else {
                    ((v >> 8) as u8, true)
                }
            }
        };
        if done {
            self.latch = None;
        }
        byte
    }

    fn write(&mut self, v: u8) {
        self.cr = match self.rw() {
            1 => v as u16,
            2 => (v as u16) << 8,
            _ if !self.write_msb => {
                self.lsb = v;
                self.write_msb = true;
                // Mode 0: the first byte stops the count and sets OUT low.
                if self.mode == 0 {
                    self.out = false;
                }
                return;
            }
            _ => {
                self.write_msb = false;
                ((v as u16) << 8) | self.lsb as u16
            }
        };
        self.null_count = true;
        match self.mode {
            0 => {
                self.out = false;
                self.load = true;
            }
            // A new count in modes 2 and 3 waits for the end of the
            // current period (or half period), or for a trigger.
            2 | 3 if !self.has_count => self.load = true,
            4 => self.load = true,
            // Modes 1 and 5 load on a trigger.
            _ => {}
        }
        self.has_count = true;
    }

    fn set_gate(&mut self, level: bool) {
        if level && !self.gate && matches!(self.mode, 1 | 2 | 3 | 5) {
            self.trigger = true;
        }
        // Modes 2 and 3: GATE low ends a low OUT at once.
        if !level && matches!(self.mode, 2 | 3) {
            self.out = true;
        }
        self.gate = level;
    }

    /// One CLK pulse. Returns whether OUT went high.
    fn pulse(&mut self) -> bool {
        let was = self.out;
        let trigger = std::mem::take(&mut self.trigger);
        match self.mode {
            // Interrupt on terminal count: OUT goes high when CE reaches 0
            // and stays high; GATE low pauses the count.
            0 => {
                if self.write_msb {
                    // half of a two-byte count: stopped
                } else if self.load {
                    self.load_ce();
                } else if self.counting && self.gate {
                    self.ce = self.dec(self.ce, 1);
                    if self.ce == 0 {
                        self.out = true;
                    }
                }
            }
            // Hardware-retriggerable one-shot: a trigger loads CE and sets
            // OUT low, which goes high again when CE reaches 0.
            1 => {
                if trigger && self.has_count {
                    self.load_ce();
                    self.out = false;
                } else if self.counting {
                    self.ce = self.dec(self.ce, 1);
                    if self.ce == 0 {
                        self.out = true;
                    }
                }
            }
            // Rate generator: OUT is low for the pulse where CE is 1, and
            // the next pulse reloads it.
            2 => {
                if (self.load || trigger) && self.has_count {
                    self.load_ce();
                    self.out = true;
                } else if self.counting && self.gate {
                    if self.ce == 1 {
                        self.load_ce();
                        self.out = true;
                    } else {
                        self.ce = self.dec(self.ce, 1);
                        if self.ce == 1 {
                            self.out = false;
                        }
                    }
                }
            }
            // Square wave: CE counts down by two from the even part of the
            // count, and OUT changes and CE reloads each time it runs out.
            // With an odd count, the high half lasts one pulse longer.
            3 => {
                if (self.load || trigger) && self.has_count {
                    self.load_ce();
                    self.out = true;
                } else if self.counting && self.gate {
                    if self.expired {
                        self.out = false;
                        self.load_ce();
                    } else {
                        self.ce = self.dec(self.ce, 2);
                        if self.ce == 0 {
                            if self.out && self.odd {
                                self.expired = true;
                            } else {
                                self.out = !self.out;
                                self.load_ce();
                            }
                        }
                    }
                }
            }
            // Software- (4) and hardware-triggered (5) strobe: OUT is low
            // for one pulse when CE first reaches 0 after a load, which is
            // a count written (4) or a trigger (5). GATE low pauses the
            // count in mode 4 but doesn't lengthen the strobe.
            _ => {
                self.out = true;
                let start = if self.mode == 4 {
                    self.load
                } else {
                    trigger && self.has_count
                };
                if start {
                    self.load_ce();
                    self.armed = true;
                } else if self.counting && (self.gate || self.mode == 5) {
                    self.ce = self.dec(self.ce, 1);
                    if self.ce == 0 && self.armed {
                        self.out = false;
                        self.armed = false;
                    }
                }
            }
        }
        !was && self.out
    }

    /// How many of the next pulses do nothing but count CE down, and by
    /// how much each (0 if it's stopped). Every other pulse is stepped.
    fn quiet(&self) -> (u64, u64) {
        if self.trigger || self.load {
            // (in mode 0, half a two-byte count holds the load back)
            return if self.mode == 0 && self.write_msb {
                (FOREVER, 0)
            } else {
                (0, 0)
            };
        }
        let gated = match self.mode {
            0 => self.write_msb || !self.gate,
            2..=4 => !self.gate,
            _ => false,
        };
        if matches!(self.mode, 4 | 5) && !self.out {
            return (0, 0);
        }
        if !self.counting || gated {
            return (FOREVER, 0);
        }
        let span = self.span(self.ce);
        match self.mode {
            0 | 1 if self.out => (FOREVER, 1),
            0 | 1 => (span - 1, 1),
            2 => (span.saturating_sub(2), 1),
            3 if self.expired => (0, 0),
            3 => (span / 2 - 1, 2),
            _ if self.armed => (span - 1, 1),
            _ => (FOREVER, 1),
        }
    }

    /// In modes 2 and 3, at the start of a period that will repeat as it
    /// is: its length in pulses, and how many times OUT rises in it.
    fn period(&self) -> Option<(u64, u64)> {
        let steady = self.counting
            && self.gate
            && self.out
            && !self.trigger
            && !self.load
            && !self.null_count
            && self.ce == self.reload_value();
        match self.mode {
            2 if steady => {
                let n = self.span(self.ce);
                Some((n, (n >= 2) as u64))
            }
            3 if steady && !self.expired && self.odd == (self.num(self.cr) & 1 != 0) => {
                Some((self.span(self.ce) + self.odd as u64, 1))
            }
            _ => None,
        }
    }

    fn pulses(&mut self, n: u64) -> u64 {
        let mut left = n;
        let mut rises = 0;
        while left > 0 {
            if let Some((len, r)) = self.period()
                && left >= len
            {
                rises += left / len * r;
                left %= len;
                continue;
            }
            match self.quiet() {
                (0, _) => {
                    rises += self.pulse() as u64;
                    left -= 1;
                }
                (q, by) => {
                    let k = q.min(left);
                    self.ce = self.dec(self.ce, (k % self.modulus()) * by);
                    left -= k;
                }
            }
        }
        rises
    }
}

/// An 82C54: three counters and a control register, at addresses 0..=2
/// and 3 (A1 A0).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Timer {
    counters: [Counter; 3],
}

impl Default for Timer {
    fn default() -> Timer {
        Timer::new()
    }
}

impl Timer {
    /// A timer at power-on. Each counter is as if programmed for mode 0,
    /// binary, LSB then MSB, with no count (OUT low), and with GATE high.
    pub fn new() -> Timer {
        Timer {
            counters: [Counter::new(), Counter::new(), Counter::new()],
        }
    }

    /// Read a counter (its latched status, its latched count, or CE, a
    /// byte at a time as its RW mode says). Reading the control register
    /// is a no-op on the chip: the bus floats, and this returns 0xFF.
    pub fn read(&mut self, addr: u8) -> u8 {
        match addr & 3 {
            3 => 0xFF,
            a => self.counters[a as usize].read(),
        }
    }

    /// Write a count byte to a counter, or a control word: a mode, a
    /// counter latch command (RW = 00) or a read-back command (SC = 11).
    pub fn write(&mut self, addr: u8, v: u8) {
        match addr & 3 {
            3 => self.control(v),
            a => self.counters[a as usize].write(v),
        }
    }

    fn control(&mut self, v: u8) {
        let sc = (v >> 6) as usize;
        if sc == 3 {
            // Read-back: bit 5 low latches the counts, bit 4 low the
            // status, of the counters selected by bits 1..=3.
            for (i, c) in self.counters.iter_mut().enumerate() {
                if v & (2 << i) != 0 {
                    if v & 0x20 == 0 {
                        c.latch_count();
                    }
                    if v & 0x10 == 0 {
                        c.latch_status();
                    }
                }
            }
        } else if v & 0x30 == 0 {
            self.counters[sc].latch_count();
        } else {
            self.counters[sc].control(v);
        }
    }

    /// Set a counter's GATE input. A rising edge is a trigger in modes 1,
    /// 2, 3 and 5, seen by the next pulse.
    pub fn set_gate(&mut self, counter: usize, level: bool) {
        self.counters[counter].set_gate(level);
    }

    /// One pulse on a counter's CLK input.
    pub fn clock(&mut self, counter: usize) {
        self.counters[counter].pulse();
    }

    /// `n` pulses on a counter's CLK input, in a time that doesn't depend
    /// on `n`. Returns how many times OUT went high during them.
    pub fn clock_n(&mut self, counter: usize, n: u64) -> u64 {
        self.counters[counter].pulses(n)
    }

    /// A counter's OUT output.
    pub fn out(&self, counter: usize) -> bool {
        self.counters[counter].out
    }
}
