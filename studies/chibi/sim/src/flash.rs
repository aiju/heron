//! The boot flash: an SST39SF010A, 128K × 8, its byte n at 0xFFE0_0000 +
//! 2n (on MD7-0), writable with its command sequences:
//!
//! | Sequence (address/data, on A14-A0) | |
//! |---|---|
//! | 5555/AA 2AAA/55 5555/A0, then a/d | program byte a (bits can only go from 1 to 0): 20 µs |
//! | 5555/AA 2AAA/55 5555/80 5555/AA 2AAA/55, then a/30 | erase a's 4 KB sector: 25 ms |
//! | 5555/AA 2AAA/55 5555/80 5555/AA 2AAA/55 5555/10 | erase the chip: 100 ms |
//! | 5555/AA 2AAA/55 5555/90 | software ID: byte 0 reads BF (SST), byte 1 B5 (the 39SF010A) |
//! | 5555/AA 2AAA/55 5555/F0, or xxxx/F0 | back to reading |
//!
//! While it programs or erases, a read gives the byte's bit 7 inverted
//! (data# polling) and bit 6 toggling at each read; writes are ignored.
//! The times are the datasheet's maxima.

pub const SIZE: usize = 0x20000;
const SECTOR: usize = 0x1000;

#[derive(Clone, Debug)]
pub struct Flash {
    pub data: Vec<u8>,
    /// How far into a command sequence: 0 none, 1 after AA, 2 after 55,
    /// 3 a byte's program next, 4 erase's setup, 5 and 6 its AA and 55.
    step: u8,
    id: bool,
    busy_until: u64,
    toggle: bool,
    /// What the operation under way leaves (bit 7 for data# polling).
    target: u8,
    /// The ticks of 20 µs, 25 ms, 100 ms.
    t_program: u64,
    t_sector: u64,
    t_chip: u64,
}

impl Flash {
    /// A blank flash (every byte FF); `us` is the ticks of a microsecond.
    pub fn new(us: f64) -> Flash {
        Flash {
            data: vec![0xFF; SIZE],
            step: 0,
            id: false,
            busy_until: 0,
            toggle: false,
            target: 0xFF,
            t_program: (20.0 * us) as u64,
            t_sector: (25_000.0 * us) as u64,
            t_chip: (100_000.0 * us) as u64,
        }
    }

    pub fn busy(&self, now: u64) -> bool {
        now < self.busy_until
    }

    pub fn read(&mut self, n: u32, now: u64) -> u8 {
        let n = n as usize % SIZE;
        if self.busy(now) {
            self.toggle = !self.toggle;
            return (!self.target & 0x80) | (self.toggle as u8) << 6;
        }
        if self.id {
            return if n & 1 == 0 { 0xBF } else { 0xB5 };
        }
        self.data[n]
    }

    pub fn write(&mut self, n: u32, v: u8, now: u64) {
        if self.busy(now) {
            return;
        }
        let n = n as usize % SIZE;
        let a = n & 0x7FFF;
        self.step = match (self.step, a, v) {
            (3, _, _) => {
                self.data[n] &= v;
                self.target = v;
                self.busy_until = now + self.t_program;
                0
            }
            (6, _, 0x30) => {
                let s = n & !(SECTOR - 1);
                self.data[s..s + SECTOR].fill(0xFF);
                self.target = 0xFF;
                self.busy_until = now + self.t_sector;
                0
            }
            (6, 0x5555, 0x10) => {
                self.data.fill(0xFF);
                self.target = 0xFF;
                self.busy_until = now + self.t_chip;
                0
            }
            (_, _, 0xF0) if self.step != 2 || a == 0x5555 => {
                self.id = false;
                0
            }
            (0, 0x5555, 0xAA) | (4, 0x5555, 0xAA) => self.step + 1,
            (1, 0x2AAA, 0x55) | (5, 0x2AAA, 0x55) => self.step + 1,
            (2, 0x5555, 0xA0) => 3,
            (2, 0x5555, 0x80) => 4,
            (2, 0x5555, 0x90) => {
                self.id = true;
                0
            }
            _ => 0,
        };
    }
}
