//! The board behind the CPU: studies/mini/system.py's `System`, with the
//! video of RFC 0042 (video.rs) in place of its frame interrupt.

use crate::video::{Board, SUB, Video};

pub const RAM_SIZE: usize = 4 << 20;
const IO_BASE: u32 = 0x8000_0000;
const R_BOOT: u32 = 5;
const R_UART: u32 = 6;
const R_LOCAL: u32 = 7;
const L_STATUS: u32 = 0x800;

/// The store data: a word as it is, a half on both halves, a byte on all
/// four lanes.
fn replicate(size: u32, a: u32) -> u32 {
    match size {
        3 => a,
        2 => (a & 0xFFFF).wrapping_mul(0x10001),
        _ => (a & 0xFF).wrapping_mul(0x0101_0101),
    }
}

/// Byte lanes (bits 0-3) of an access.
fn lanes_of(size: u32, addr: u32) -> u32 {
    match size {
        3 => 0b1111,
        2 => 0b0011 << (addr & 2),
        _ => 1 << (addr & 3),
    }
}

/// Draft 1's I/O page, as system.py's `SuitePage`.
#[derive(Default)]
pub struct SuitePage {
    pub inp: Vec<u8>,
    pub pos: usize,
    pub out: Vec<u8>,
    period: u32,
    count: u32,
    flag: u32,
    cyc_hi: u32,
}

impl SuitePage {
    fn read(&mut self, off: u32, size: u32, cycle: u64) -> u32 {
        let w = off & 0xFC;
        let lanes = lanes_of(size, off);
        let (lo, hi) = (lanes & 3 != 0, lanes & 12 != 0);
        let empty = self.pos >= self.inp.len();
        let mut vals = [0u32; 2];
        for (h, v) in vals.iter_mut().enumerate() {
            *v = match w + 2 * h as u32 {
                0x00 => {
                    if empty {
                        0xFFFF
                    } else {
                        u32::from(self.inp[self.pos])
                    }
                }
                0x02 => {
                    if empty {
                        0xFFFF
                    } else {
                        0
                    }
                }
                0x04 => {
                    if empty {
                        2
                    } else {
                        1
                    }
                }
                0x08 => self.period & 0xFFFF,
                0x0A => self.period >> 16,
                0x0C => self.flag,
                0x10 => (cycle & 0xFFFF) as u32,
                0x12 => {
                    if lo && hi {
                        ((cycle >> 16) & 0xFFFF) as u32
                    } else {
                        self.cyc_hi
                    }
                }
                _ => 0,
            };
        }
        let value = if lo && hi {
            vals[0] | (vals[1] << 16)
        } else if lo {
            vals[0].wrapping_mul(0x10001)
        } else {
            vals[1].wrapping_mul(0x10001)
        };
        if lo && w == 0x00 && !empty {
            self.pos += 1;
        }
        if lo && w == 0x10 {
            self.cyc_hi = ((cycle >> 16) & 0xFFFF) as u32;
        }
        value
    }

    fn write(&mut self, off: u32, v: u32, size: u32) {
        let w = off & 0xFC;
        let lanes = lanes_of(size, off);
        for h in 0..2 {
            if lanes & (3 << (2 * h)) == 0 {
                continue;
            }
            let half = (v >> (16 * h)) & 0xFFFF;
            match w + 2 * h {
                0x00 if lanes & 1 != 0 => self.out.push(half as u8),
                0x08 => {
                    self.period = (self.period & 0xFFFF_0000) | half;
                    self.count = 0;
                    if self.period == 0 {
                        self.flag = 0;
                    }
                }
                0x0A => {
                    self.period = (self.period & 0xFFFF) | (half << 16);
                    self.count = 0;
                    if self.period == 0 {
                        self.flag = 0;
                    }
                }
                0x0C | 0x0E => self.flag = 0,
                _ => {}
            }
        }
    }

    fn tick(&mut self) {
        if self.period != 0 {
            self.count += 1;
            if self.count >= self.period {
                self.flag = 1;
                self.count = 0;
            }
        }
    }

    fn irq(&self) -> bool {
        self.flag != 0
    }
}

/// A 16C550, as system.py's `Uart`.
#[derive(Default)]
pub struct Uart {
    pub inp: Vec<u8>,
    pub pos: usize,
    pub out: Vec<u8>,
    ier: u32,
    lcr: u32,
    mcr: u32,
    scr: u32,
    dll: u32,
    dlm: u32,
}

impl Uart {
    fn read(&mut self, reg: u32) -> u32 {
        let dlab = self.lcr & 0x80 != 0;
        match reg {
            0 if dlab => self.dll,
            0 => {
                if self.pos < self.inp.len() {
                    self.pos += 1;
                    u32::from(self.inp[self.pos - 1])
                } else {
                    0
                }
            }
            1 if dlab => self.dlm,
            1 => self.ier,
            2 => {
                if self.irq() {
                    0xC4
                } else {
                    0xC1
                }
            }
            3 => self.lcr,
            4 => self.mcr,
            5 => 0x60 | u32::from(self.pos < self.inp.len()),
            6 => 0,
            _ => self.scr,
        }
    }

    fn write(&mut self, reg: u32, v: u32) {
        let dlab = self.lcr & 0x80 != 0;
        match reg {
            0 if dlab => self.dll = v,
            0 => self.out.push(v as u8),
            1 if dlab => self.dlm = v,
            1 => self.ier = v & 0x0F,
            3 => self.lcr = v,
            4 => self.mcr = v,
            7 => self.scr = v,
            _ => {}
        }
    }

    fn irq(&self) -> bool {
        self.ier & 1 != 0 && self.pos < self.inp.len()
    }
}

/// The board: the RAM, the I/O regions, the interrupt line, the video.
pub struct System {
    pub ram: Vec<u8>,
    mask: u32,
    pub page: SuitePage,
    pub uarts: [Uart; 2],
    pub video: Video,
    pub boot: Vec<u8>,
    /// Wait states by region, in ticks.
    pub io_hold: [u64; 8],
    pub ticks: u64,
    pub io_ticks: u64,
}

impl System {
    pub fn new(board: Board) -> System {
        System {
            ram: vec![0; RAM_SIZE],
            mask: (RAM_SIZE - 1) as u32,
            page: SuitePage::default(),
            uarts: [Uart::default(), Uart::default()],
            video: Video::new(board),
            boot: vec![0; 0x20000],
            io_hold: std::array::from_fn(|r| 16 - 2 * r as u64),
            ticks: 0,
            io_ticks: 0,
        }
    }

    pub fn is_io(pa: u32) -> bool {
        pa & IO_BASE != 0
    }

    pub fn ram_word(&self, pa: u32) -> u32 {
        let a = (pa & self.mask & !3) as usize;
        u32::from_le_bytes([
            self.ram[a],
            self.ram[a + 1],
            self.ram[a + 2],
            self.ram[a + 3],
        ])
    }

    pub fn fetch(&self, pa: u32) -> u32 {
        self.ram_word(pa)
    }

    /// A read of `size` (1 byte, 2 half, 3 word): the aligned word as the
    /// data bus carries it, and the ticks it holds the cycle.
    pub fn read(&mut self, pa: u32, size: u32, cycle: u64) -> (u32, u64) {
        if !System::is_io(pa) {
            return (self.ram_word(pa), 0);
        }
        let region = (pa >> 28) & 7;
        let hold = self.io_hold[region as usize];
        self.io_ticks += hold;
        (self.io_read(region, pa, size, cycle), hold)
    }

    /// A store of the A bus's value, replicated by size: the hold.
    pub fn write(&mut self, pa: u32, size: u32, value: u32, cycle: u64) -> u64 {
        let data = replicate(size, value);
        let lanes = lanes_of(size, pa);
        if !System::is_io(pa) {
            let a = (pa & self.mask & !3) as usize;
            for k in 0..4 {
                if (lanes >> k) & 1 != 0 {
                    self.ram[a + k] = (data >> (8 * k)) as u8;
                }
            }
            return 0;
        }
        let region = (pa >> 28) & 7;
        let hold = self.io_hold[region as usize];
        self.io_ticks += hold;
        self.io_write(region, pa, size, data, cycle);
        hold
    }

    fn suite_page(pa: u32) -> bool {
        pa & 0x0FFF_FF00 == 0x0FFF_FF00
    }

    fn io_read(&mut self, region: u32, pa: u32, size: u32, cycle: u64) -> u32 {
        if region == R_BOOT {
            return u32::from(self.boot[((pa >> 2) & 0x1FFFF) as usize]);
        }
        if region == R_UART {
            return self.uarts[((pa >> 5) & 1) as usize].read((pa >> 2) & 7);
        }
        if region == R_LOCAL && System::suite_page(pa) {
            return self.page.read(pa & 0xFF, size, cycle);
        }
        if region == R_LOCAL && pa & 0x20_0000 == 0 {
            if pa & 0xC00 == L_STATUS {
                return self.status().wrapping_mul(0x0101_0101);
            }
            if pa & 0xC00 < L_STATUS {
                return self.video.read(pa & 0x7FC, self.ticks * SUB);
            }
        }
        0
    }

    fn io_write(&mut self, region: u32, pa: u32, size: u32, data: u32, _cycle: u64) {
        if region == R_UART {
            self.uarts[((pa >> 5) & 1) as usize].write((pa >> 2) & 7, data & 0xFF);
        } else if region == R_LOCAL && System::suite_page(pa) {
            self.page.write(pa & 0xFF, data, size);
        } else if region == R_LOCAL && pa & 0x20_0000 == 0 && pa & 0xC00 < L_STATUS {
            self.video.write(pa & 0x7FC, data);
        }
    }

    /// The interrupt status register: the UARTs, the video, the expansion
    /// ports' lines (pulled up), the line.
    pub fn status(&self) -> u32 {
        let mut s = u32::from(self.uarts[0].irq())
            | (u32::from(self.uarts[1].irq()) << 1)
            | (u32::from(self.video.irq()) << 4);
        s |= 0x60;
        s | (u32::from(self.irq()) << 7)
    }

    pub fn irq(&self) -> bool {
        self.page.irq() || self.uarts.iter().any(Uart::irq) || self.video.irq()
    }

    /// Something could still raise the interrupt line on its own.
    pub fn can_interrupt(&self) -> bool {
        self.page.period != 0 || self.video.ctrl & 4 != 0
    }

    /// A CPU cycle of `ticks` master ticks, `hold` of them an I/O
    /// access's: the video through it, and the ticks it stole.
    pub fn cycle(&mut self, ticks: u64, hold: u64) -> u64 {
        let steal = self.video.cycle(&self.ram, self.ticks, ticks, hold);
        self.ticks += ticks + steal;
        self.page.tick();
        steal
    }
}
