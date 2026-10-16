//! The machine Fen runs on: draft 2 in system mode (RFC 0029) with RAM on
//! the CPU board, a timer, a video card and an I/O card on the system bus
//! (RFC 0014). The board is the study's own: RFC 0029 leaves the physical
//! memory map open (its open question 2), and this is one answer.
//!
//! The physical address space, by the bus's slots (A31-A28, RFC 0014, 5.1;
//! only slots 0-7 are in the supervisor's window):
//!
//! | Physical | What |
//! |---|---|
//! | `0x0000_0000` | slot 0, the CPU board: RAM from 0 (4 MB by default) |
//! | `0x0F00_0000` | the CPU board's timer ([`timer`]) |
//! | `0x0F00_1000` | the board's information: +0 R the RAM's size in bytes, +4 R the clock in Hz, +C R boot flags the host sets; and the simulator's debug port, +8 W a byte to the host's log (not hardware) |
//! | `0x0F00_2000` | the interrupt mask: +0 R the levels requesting, +4 R/W the mask, a bit per level, 1 to let it through (0 after reset) |
//! | `0x1000_0000` | slot 1, the video card ([`video`]): VRAM, its registers at `0x1FF0_0000` |
//! | `0x2000_0000` | slot 2, the I/O card, a 4 KB page for each device: a 16C550 UART at +0x0000, a CompactFlash card in True IDE mode at +0x1000 (CS0, the task file) and +0x1020 (CS1, the control block), two PS/2 ports at +0x2000 (keyboard) and +0x2010 (mouse) ([`ps2`]), and a clock at +0x3000, with the card's ID at +0x3FFC |
//! | anything else | nothing answers: a bus error |
//!
//! The I/O card's devices are 8-bit, on D0-D7, their registers 4 bytes
//! apart, except the CF card's data register, which is 16 bits. The clock
//! is one register: seconds since 1970, as the host set them at power-on
//! and counted since.
//!
//! **A page for each device**, so that the page map can give each to its
//! own user-level driver: the file server the CF card, the window system
//! the PS/2 ports, and nothing else. On the card that is decoding A12-A13
//! instead of bits further down, which costs nothing.
//!
//! Interrupt levels (RFC 0029, 7), as the cards' jumpers would set them:
//! 6 the timer, 5 the UART, 4 the CF card, 3 the PS/2 ports, 2 the video
//! card's vertical blank.
//!
//! **The interrupt mask** isn't in RFC 0029, which has the eight lines go
//! straight to the priority encoder. A kernel that hands an interrupt to a
//! user-level driver needs it: the lines are level-sensitive, so the
//! request stays up until the driver has run, and without a mask the
//! kernel would take it again as soon as it returned. It is an 8-bit
//! register and eight AND gates on the board, about 2 chips (the 8259's
//! IMR).
//!
//! Time is the machine's cycle count (its reference configuration) at the
//! clock rate in [`Config`]: each device is brought up to that time when
//! it's accessed, or when the machine asks for the interrupt lines.

pub mod ps2;
pub mod timer;
pub mod video;

use devices::cf::CfCard;
use devices::uart16550::Uart;
use v2_isa::sys::Bus;
use v2_isa::timing::Config as Timing;
use v2_isa::{Machine, RunStatus};

pub const TIMER: u32 = 0x0F00_0000;
pub const INFO: u32 = 0x0F00_1000;
pub const IMASK: u32 = 0x0F00_2000;
pub const VIDEO_SLOT: u32 = 1;
pub const IO_SLOT: u32 = 2;
pub const IO_ID: u32 = 0x0009_0001;

pub const IRQ_TIMER: u8 = 6;
pub const IRQ_UART: u8 = 5;
pub const IRQ_CF: u8 = 4;
pub const IRQ_PS2: u8 = 3;
pub const IRQ_VIDEO: u8 = 2;

#[derive(Clone, Debug)]
pub struct Config {
    pub ram_size: u32,
    /// The CPU's clock, cycles a second.
    pub clock_hz: f64,
    /// The UART's XIN: 1.8432 MHz makes divisor 1 115,200 baud.
    pub uart_hz: f64,
    /// The clock's seconds since 1970 at power-on.
    pub epoch: u64,
    /// The timing configuration the cycle count follows.
    pub timing: Timing,
    /// Flags for the software, which it reads from the board: the host's
    /// way to pass it a choice at boot.
    pub boot_flags: u32,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            ram_size: 4 << 20,
            clock_hz: 6e6,
            uart_hz: 1_843_200.0,
            epoch: 1_792_108_800, // 2026-10-16
            timing: Timing::named(v2_isa::timing::REFERENCE).unwrap(),
            boot_flags: 0,
        }
    }
}

/// The devices behind the CPU.
pub struct Board {
    pub cfg: Config,
    pub timer: timer::Timer,
    pub video: video::Video,
    pub uart: Uart,
    pub cf: CfCard,
    pub kbd: ps2::Port,
    pub mouse: ps2::Port,
    /// What was written to the debug port.
    pub debug: Vec<u8>,
    /// The interrupt mask register.
    pub imask: u8,
    now_ns: u64,
    uart_frac: f64,
}

impl Board {
    pub fn new(cfg: Config, cf_image: Vec<u8>) -> Board {
        Board {
            cfg,
            timer: timer::Timer::default(),
            video: video::Video::new(),
            uart: Uart::new(),
            cf: CfCard::new(cf_image),
            kbd: ps2::Port::new(ps2::Kind::Keyboard),
            mouse: ps2::Port::new(ps2::Kind::Mouse),
            debug: Vec::new(),
            imask: 0,
            now_ns: 0,
            uart_frac: 0.0,
        }
    }

    fn ns(&self, cycles: u64) -> u64 {
        (cycles as f64 * 1e9 / self.cfg.clock_hz) as u64
    }

    fn cycles_at(&self, ns: u64) -> u64 {
        (ns as f64 * self.cfg.clock_hz / 1e9).ceil() as u64
    }

    /// The board's time.
    pub fn now_ns(&self) -> u64 {
        self.now_ns
    }

    /// Bring every device up to the time of `cycles`.
    pub fn advance(&mut self, cycles: u64) {
        let t = self.ns(cycles);
        if t > self.now_ns {
            let x = (t - self.now_ns) as f64 * self.cfg.uart_hz / 1e9 + self.uart_frac;
            self.uart.clock(x.floor() as u64);
            self.uart_frac = x.fract();
            self.now_ns = t;
        }
        let t = self.now_ns;
        self.timer.advance(t);
        self.video.advance(t);
        self.cf.advance(t);
        self.kbd.advance(t);
        self.mouse.advance(t);
    }

    /// The levels requesting, before the mask.
    fn requests(&self) -> u8 {
        let mut m = 0u8;
        let mut set = |on: bool, l: u8| {
            if on {
                m |= 1 << l
            }
        };
        set(self.timer.fired, IRQ_TIMER);
        set(self.uart.intr(), IRQ_UART);
        set(self.cf.intrq(), IRQ_CF);
        set(self.kbd.irq() || self.mouse.irq(), IRQ_PS2);
        set(self.video.irq(), IRQ_VIDEO);
        m
    }

    fn levels(&self) -> u8 {
        self.requests() & self.imask
    }

    /// When a device next changes by itself, in ns.
    fn next_ns(&self) -> Option<u64> {
        let t = self.now_ns;
        let uart = self.uart.next_change().map(|x| {
            t + ((x as f64 - self.uart_frac).max(0.0) * 1e9 / self.cfg.uart_hz).ceil() as u64
        });
        [
            self.timer.next_ns(t),
            uart,
            self.cf.next_event_ns(),
            self.kbd.next_ns(t),
            self.mouse.next_ns(t),
            self.video.next_ns(t),
        ]
        .into_iter()
        .flatten()
        .min()
    }

    fn io_read(&mut self, off: u32, size: u32) -> Option<u32> {
        let t = self.now_ns;
        let reg = ((off >> 2) & 7) as u8;
        let low = off & 0xFFF;
        Some(match off >> 12 {
            0 if low < 0x20 => self.uart.read(reg) as u32,
            1 if low < 0x40 => {
                let v = self.cf.read(low >= 0x20, reg, t) as u32;
                if reg == 0 && low < 0x20 && size >= 2 {
                    v & 0xFFFF
                } else {
                    v & 0xFF
                }
            }
            2 if low < 0x08 => self.kbd.read(low & 4, t),
            2 if (0x10..0x18).contains(&low) => self.mouse.read(low & 4, t),
            3 if low == 0 => (self.cfg.epoch + t / 1_000_000_000) as u32,
            3 if low == 0xFFC => IO_ID,
            _ => return None,
        })
    }

    fn io_write(&mut self, off: u32, v: u32) -> bool {
        let t = self.now_ns;
        let reg = ((off >> 2) & 7) as u8;
        let low = off & 0xFFF;
        match off >> 12 {
            0 if low < 0x20 => self.uart.write(reg, v as u8),
            1 if low < 0x40 => {
                let data = if reg == 0 && low < 0x20 {
                    v & 0xFFFF
                } else {
                    v & 0xFF
                };
                self.cf.write(low >= 0x20, reg, data as u16, t)
            }
            2 if low < 0x08 => self.kbd.write(low & 4, v, t),
            2 if (0x10..0x18).contains(&low) => self.mouse.write(low & 4, v, t),
            _ => return false,
        }
        true
    }
}

fn get(mem: &[u8], i: usize, size: u32) -> u32 {
    match size {
        1 => mem[i] as u32,
        2 => u16::from_le_bytes([mem[i], mem[i + 1]]) as u32,
        _ => u32::from_le_bytes(mem[i..i + 4].try_into().unwrap()),
    }
}

fn put(mem: &mut [u8], i: usize, size: u32, v: u32) {
    match size {
        1 => mem[i] = v as u8,
        2 => mem[i..i + 2].copy_from_slice(&(v as u16).to_le_bytes()),
        _ => mem[i..i + 4].copy_from_slice(&v.to_le_bytes()),
    }
}

impl Bus for Board {
    fn read(&mut self, pa: u32, size: u32, cycles: u64) -> Option<u32> {
        self.advance(cycles);
        let off = pa & 0x0FFF_FFFF;
        match pa >> 28 {
            0 if pa & !0xF == TIMER => Some(self.timer.read(pa & 0xF, self.now_ns)),
            0 if pa & !0xF == INFO => match pa & 0xF {
                0 => Some(self.cfg.ram_size),
                4 => Some(self.cfg.clock_hz as u32),
                0xC => Some(self.cfg.boot_flags),
                _ => Some(0),
            },
            0 if pa & !0xF == IMASK => match pa & 0xF {
                0 => Some(self.requests() as u32),
                4 => Some(self.imask as u32),
                _ => Some(0),
            },
            VIDEO_SLOT if (off as usize) < video::VRAM_SIZE => {
                Some(get(&self.video.vram, off as usize, size))
            }
            VIDEO_SLOT if off & !0xFF == video::REGS => {
                Some(self.video.read_reg(off & 0xFF, self.now_ns))
            }
            IO_SLOT if off < 0x4000 => self.io_read(off, size),
            _ => None,
        }
    }

    fn write(&mut self, pa: u32, size: u32, v: u32, cycles: u64) -> bool {
        self.advance(cycles);
        let off = pa & 0x0FFF_FFFF;
        match pa >> 28 {
            0 if pa & !0xF == TIMER => self.timer.write(pa & 0xF, v, self.now_ns),
            0 if pa == INFO + 8 => self.debug.push(v as u8),
            0 if pa & !0xF == INFO => {}
            0 if pa == IMASK + 4 => self.imask = v as u8,
            0 if pa & !0xF == IMASK => {}
            VIDEO_SLOT if (off as usize) < video::VRAM_SIZE => {
                put(&mut self.video.vram, off as usize, size, v);
                self.video.dirty = true;
            }
            VIDEO_SLOT if off & !0xFF == video::REGS => {
                self.video.write_reg(off & 0xFF, v, self.now_ns)
            }
            IO_SLOT if off < 0x4000 => return self.io_write(off, v),
            _ => return false,
        }
        true
    }

    fn irq(&mut self, cycles: u64) -> (u8, u64) {
        self.advance(cycles);
        let next = self
            .next_ns()
            .map_or(u64::MAX, |t| self.cycles_at(t).max(cycles + 1));
        (self.levels(), next)
    }
}

/// The machine and its board.
pub struct Computer {
    pub m: Machine,
}

impl Computer {
    pub fn new(cfg: Config, cf_image: Vec<u8>) -> Computer {
        let (ram, timing) = (cfg.ram_size, cfg.timing);
        let board = Board::new(cfg, cf_image);
        Computer {
            m: Machine::new_system(ram, Box::new(board), timing),
        }
    }

    pub fn board(&mut self) -> &mut Board {
        self.m.sys_mut().bus_as::<Board>().unwrap()
    }

    pub fn board_ref(&self) -> &Board {
        self.m.sys().bus_ref::<Board>().unwrap()
    }

    /// Put bytes in RAM at a physical address.
    pub fn load(&mut self, pa: u32, bytes: &[u8]) {
        let a = pa as usize;
        self.m.mem[a..a + bytes.len()].copy_from_slice(bytes);
    }

    /// Run until the cycle count reaches `until`, or `steps` instructions.
    pub fn run(&mut self, until: u64, steps: u64) -> Result<RunStatus, String> {
        self.m.run_system(until, steps)
    }

    /// The board's time.
    pub fn now_ns(&self) -> u64 {
        (self.m.cycles as f64 * 1e9 / self.board_ref().cfg.clock_hz) as u64
    }

    /// The cycle count at a time.
    pub fn cycles_at(&self, ns: u64) -> u64 {
        (ns as f64 * self.board_ref().cfg.clock_hz / 1e9) as u64
    }

    /// Something from outside changed a device: the machine asks the board
    /// about its interrupt lines again.
    fn poke(&mut self) {
        let c = self.m.cycles;
        self.board().advance(c);
        self.m.sys_mut().touched();
    }

    /// A key down or up, by its set 2 code.
    pub fn key(&mut self, code: u16, down: bool) {
        self.poke();
        self.board().kbd.key(code, down);
        self.poke();
    }

    /// The mouse moved by (dx, dy), y up, with `buttons` held.
    pub fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
        self.poke();
        self.board().mouse.mouse(dx, dy, buttons);
        self.poke();
    }

    /// Bytes typed at the terminal on the UART's line.
    pub fn uart_send(&mut self, bytes: &[u8]) {
        self.poke();
        self.board().uart.rx_in.extend(bytes.iter().copied());
        self.poke();
    }

    /// What the UART has sent since the last call.
    pub fn uart_take(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.board().uart.tx_out)
    }

    /// What the debug port has had since the last call.
    pub fn debug_take(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.board().debug)
    }

    /// The screen, 640 x 480 0xRRGGBB pixels, if it changed since the last
    /// call (or `always`).
    pub fn screen(&mut self, out: &mut Vec<u32>, always: bool) -> bool {
        let v = &mut self.board().video;
        if !v.dirty && !always {
            return false;
        }
        v.dirty = false;
        v.rgb_into(out);
        true
    }
}
