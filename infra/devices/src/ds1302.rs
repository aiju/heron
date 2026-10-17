//! A DS1302 trickle-charge timekeeping chip: a clock and calendar in BCD
//! and 31 bytes of RAM behind a three-wire interface, CE, SCLK and a
//! bidirectional I/O line.
//!
//! A transfer starts when CE rises. The command byte comes first, LSB
//! first, each bit taken on SCLK's rising edge: bit 7 must be 1, bit 6
//! picks the RAM (1) or the clock (0), bits 5-1 the address, bit 0 reads
//! (1) or writes (0). A write's data follows, taken on rising edges too;
//! a read's is driven onto I/O from the falling edge after the command's
//! last bit, a bit on each falling edge. Address 31 is burst mode: the
//! clock's eight registers, or the whole RAM, one byte after another. CE
//! falling ends the transfer and lets go of I/O.
//!
//! The registers (clock address, its write command `0x80 + 2a`):
//!
//! | a | What |
//! |---|---|
//! | 0 | seconds, 00-59; bit 7 CH, the clock halted |
//! | 1 | minutes, 00-59 |
//! | 2 | hours: bit 7 12-hour mode, then bit 5 PM and 1-12; else 00-23 |
//! | 3 | date, 01-31 |
//! | 4 | month, 01-12 |
//! | 5 | day of the week, 1-7 |
//! | 6 | year, 00-99 |
//! | 7 | control: bit 7 WP, write protect: every other write is ignored |
//! | 8 | the trickle charger, kept but not used |
//!
//! Time is counted in nanoseconds, from the caller. The clock moves on a
//! second at a time; reading the clock copies all of it at the command's
//! end, so a burst read is consistent; writing the seconds restarts the
//! second. A clock burst write takes effect only once all eight bytes have
//! come. Beyond its byte, a single-byte read sends it again; a write
//! ignores more clocks.

const NS_PER_S: u64 = 1_000_000_000;

/// Where a transfer is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    /// CE low.
    Idle,
    /// Taking the command byte: its bits so far.
    Command,
    /// A read, sending; a write, taking: bits since the command.
    Data,
    /// The command's bit 7 was 0: nothing until CE falls.
    Ignore,
}

/// The chip.
#[derive(Clone, Debug)]
pub struct Ds1302 {
    /// Seconds, minutes, hours, date, month, day, year, control, trickle.
    pub regs: [u8; 9],
    pub ram: [u8; 31],
    /// When the current second started.
    second_ns: u64,
    ce: bool,
    sclk: bool,
    phase: Phase,
    shift: u8,
    nbits: u32,
    cmd: u8,
    /// What a read sends: one byte, or the burst's.
    out: Vec<u8>,
    /// What a clock burst write has taken so far.
    burst: Vec<u8>,
    /// The bit on I/O, or None when it isn't driving.
    drive: Option<bool>,
}

fn bcd(v: u8) -> u8 {
    (v / 10) << 4 | (v % 10)
}

fn bin(v: u8) -> u8 {
    (v >> 4) * 10 + (v & 15)
}

fn days_in(month: u8, year: u8) -> u8 {
    match month {
        2 if year.is_multiple_of(4) => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

impl Default for Ds1302 {
    fn default() -> Ds1302 {
        Ds1302::new(20_000_101_000_000)
    }
}

impl Ds1302 {
    /// A chip whose clock runs from `when`, yyyymmddhhmmss in decimal
    /// digits, in 24-hour mode, with write protect on: it has kept time on
    /// its battery, and nobody has written to it since. The day of the
    /// week starts at 1.
    pub fn new(when: u64) -> Ds1302 {
        let d = |k: u32| ((when / 10u64.pow(k)) % 100) as u8;
        Ds1302 {
            regs: [
                bcd(d(0)),
                bcd(d(2)),
                bcd(d(4)),
                bcd(d(6)),
                bcd(d(8)),
                1,
                bcd(d(10)),
                0x80,
                0,
            ],
            ram: [0; 31],
            second_ns: 0,
            ce: false,
            sclk: false,
            phase: Phase::Idle,
            shift: 0,
            nbits: 0,
            cmd: 0,
            out: Vec::new(),
            burst: Vec::new(),
            drive: None,
        }
    }

    /// What the chip drives onto I/O, None when it lets go.
    pub fn io(&self) -> Option<bool> {
        self.drive
    }

    /// The pins as they are now; `io` is the I/O line's level. Returns
    /// whether what the chip drives changed.
    pub fn set(&mut self, ce: bool, sclk: bool, io: bool, now_ns: u64) -> bool {
        let before = self.drive;
        self.advance(now_ns);
        if ce != self.ce {
            self.ce = ce;
            self.phase = if ce { Phase::Command } else { Phase::Idle };
            self.shift = 0;
            self.nbits = 0;
            self.burst.clear();
            self.drive = None;
        }
        if sclk != self.sclk {
            self.sclk = sclk;
            if self.ce {
                if sclk {
                    self.rise(io, now_ns);
                } else {
                    self.fall();
                }
            }
        }
        before != self.drive
    }

    fn read_cmd(&self) -> bool {
        self.cmd & 1 != 0
    }

    fn rise(&mut self, io: bool, now_ns: u64) {
        match self.phase {
            Phase::Command => {
                self.shift |= (io as u8) << self.nbits;
                self.nbits += 1;
                if self.nbits == 8 {
                    self.cmd = self.shift;
                    self.nbits = 0;
                    self.shift = 0;
                    self.phase = if self.cmd & 0x80 == 0 {
                        Phase::Ignore
                    } else {
                        Phase::Data
                    };
                    if self.phase == Phase::Data && self.read_cmd() {
                        self.out = self.snapshot();
                    }
                }
            }
            Phase::Data if !self.read_cmd() => {
                self.shift |= (io as u8) << (self.nbits % 8);
                self.nbits += 1;
                if self.nbits.is_multiple_of(8) {
                    let v = self.shift;
                    self.shift = 0;
                    self.write_byte((self.nbits / 8 - 1) as usize, v, now_ns);
                }
            }
            _ => {}
        }
    }

    fn fall(&mut self) {
        if self.phase == Phase::Data && self.read_cmd() {
            let k = self.nbits as usize;
            let byte = self.out[(k / 8) % self.out.len()];
            self.drive = Some((byte >> (k % 8)) & 1 != 0);
            self.nbits += 1;
        }
    }

    fn addr(&self) -> usize {
        ((self.cmd >> 1) & 31) as usize
    }

    fn ram_cmd(&self) -> bool {
        self.cmd & 0x40 != 0
    }

    /// What a read sends, taken at its command's end.
    fn snapshot(&self) -> Vec<u8> {
        let a = self.addr();
        match (self.ram_cmd(), a) {
            (true, 31) => self.ram.to_vec(),
            (true, a) => vec![self.ram[a]],
            (false, 31) => self.regs[..8].to_vec(),
            (false, a) if a < 9 => vec![self.regs[a]],
            _ => vec![0],
        }
    }

    /// Byte `i` of a write's data has come.
    fn write_byte(&mut self, i: usize, v: u8, now_ns: u64) {
        let a = self.addr();
        let burst = a == 31;
        if !burst && i > 0 {
            return;
        }
        let wp = self.regs[7] & 0x80 != 0;
        if self.ram_cmd() {
            if !wp && (burst && i < 31 || !burst) {
                self.ram[if burst { i } else { a }] = v;
            }
        } else if burst {
            if i < 8 {
                self.burst.push(v);
            }
            if i == 7 && !wp {
                let b = std::mem::take(&mut self.burst);
                for (k, &x) in b.iter().enumerate() {
                    self.write_reg(k, x, now_ns);
                }
            }
        } else if a < 9 && (!wp || a == 7) {
            self.write_reg(a, v, now_ns);
        }
    }

    fn write_reg(&mut self, a: usize, v: u8, now_ns: u64) {
        self.regs[a] = match a {
            7 => v & 0x80,
            _ => v,
        };
        if a == 0 {
            self.second_ns = now_ns;
        }
    }

    /// Move the clock on to `now_ns`, a second at a time.
    pub fn advance(&mut self, now_ns: u64) {
        if self.regs[0] & 0x80 != 0 {
            self.second_ns = now_ns;
            return;
        }
        while now_ns >= self.second_ns + NS_PER_S {
            self.second_ns += NS_PER_S;
            self.tick();
        }
    }

    fn tick(&mut self) {
        let r = &mut self.regs;
        let s = bin(r[0] & 0x7F) + 1;
        if s < 60 {
            r[0] = bcd(s);
            return;
        }
        r[0] = 0;
        let m = bin(r[1]) + 1;
        if m < 60 {
            r[1] = bcd(m);
            return;
        }
        r[1] = 0;
        let next_day = if r[2] & 0x80 != 0 {
            // 12-hour mode: 11 PM to 12 AM is the next day
            let pm = r[2] & 0x20 != 0;
            let h = bin(r[2] & 0x1F);
            let (h, pm, day) = match h {
                11 => (12, !pm, pm),
                12 => (1, pm, false),
                h => (h + 1, pm, false),
            };
            r[2] = 0x80 | (pm as u8) << 5 | bcd(h);
            day
        } else {
            let h = bin(r[2] & 0x3F) + 1;
            r[2] = bcd(h % 24);
            h == 24
        };
        if !next_day {
            return;
        }
        r[5] = r[5] % 7 + 1;
        let (year, month) = (bin(r[6]), bin(r[4]));
        let date = bin(r[3]) + 1;
        if date <= days_in(month, year) {
            r[3] = bcd(date);
            return;
        }
        r[3] = 1;
        if month < 12 {
            r[4] = bcd(month + 1);
            return;
        }
        r[4] = 1;
        r[6] = bcd((year + 1) % 100);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Clock a byte in, LSB first, starting at `t`; returns the time after.
    fn send(c: &mut Ds1302, v: u8, mut t: u64) -> u64 {
        for k in 0..8 {
            let b = (v >> k) & 1 != 0;
            c.set(true, false, b, t);
            c.set(true, true, b, t + 500);
            t += 1000;
        }
        t
    }

    fn receive(c: &mut Ds1302, mut t: u64) -> (u8, u64) {
        let mut v = 0;
        for k in 0..8 {
            c.set(true, false, true, t);
            v |= (c.io().unwrap_or(true) as u8) << k;
            c.set(true, true, true, t + 500);
            t += 1000;
        }
        (v, t)
    }

    fn read(c: &mut Ds1302, cmd: u8, t: u64) -> u8 {
        c.set(true, false, true, t);
        let t = send(c, cmd, t + 1000);
        let (v, t) = receive(c, t);
        c.set(false, false, true, t);
        assert_eq!(c.io(), None);
        v
    }

    fn write(c: &mut Ds1302, cmd: u8, v: u8, t: u64) {
        c.set(true, false, true, t);
        let t = send(c, cmd, t + 1000);
        let t = send(c, v, t);
        c.set(false, false, true, t);
    }

    #[test]
    fn reads_and_runs() {
        let mut c = Ds1302::new(20_261_017_235_958);
        assert_eq!(read(&mut c, 0x81, 0), 0x58);
        assert_eq!(read(&mut c, 0x85, 0), 0x23);
        assert_eq!(read(&mut c, 0x8D, 0), 0x26);
        // two seconds on: midnight, the 18th
        let t = 2 * NS_PER_S;
        assert_eq!(read(&mut c, 0x81, t), 0x00);
        assert_eq!(read(&mut c, 0x83, t), 0x00);
        assert_eq!(read(&mut c, 0x85, t), 0x00);
        assert_eq!(read(&mut c, 0x87, t), 0x18);
        assert_eq!(read(&mut c, 0x8B, t), 2);
    }

    #[test]
    fn write_protect() {
        let mut c = Ds1302::default();
        write(&mut c, 0xC0, 0x5A, 0);
        assert_eq!(read(&mut c, 0xC1, 0), 0);
        write(&mut c, 0x8E, 0x00, 0);
        write(&mut c, 0xC0, 0x5A, 0);
        assert_eq!(read(&mut c, 0xC1, 0), 0x5A);
        write(&mut c, 0x84, 0x92, 0); // 12-hour mode, 12 AM
        assert_eq!(read(&mut c, 0x85, 0), 0x92);
    }

    #[test]
    fn burst() {
        let mut c = Ds1302::new(20_240_228_235_959);
        let mut t = 0;
        c.set(true, false, true, t);
        t = send(&mut c, 0xBF, t + 1000);
        let mut got = Vec::new();
        for _ in 0..8 {
            let (v, t2) = receive(&mut c, t);
            got.push(v);
            t = t2;
        }
        c.set(false, false, true, t);
        assert_eq!(got, vec![0x59, 0x59, 0x23, 0x28, 0x02, 1, 0x24, 0x80]);
        // a leap year
        c.advance(NS_PER_S);
        assert_eq!(c.regs[3], 0x29);
    }

    #[test]
    fn halted_and_ignored() {
        let mut c = Ds1302::default();
        write(&mut c, 0x8E, 0x00, 0);
        write(&mut c, 0x80, 0x80 | 0x30, 0);
        c.advance(5 * NS_PER_S);
        assert_eq!(read(&mut c, 0x81, 5 * NS_PER_S), 0xB0);
        // bit 7 of the command 0: nothing
        assert_eq!(read(&mut c, 0x01, 0), 0xFF);
    }
}
