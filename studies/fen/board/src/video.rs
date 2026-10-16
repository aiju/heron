//! The video card: stage 1 of RFC 0016, a frame buffer. 2 MB of VRAM, a
//! canvas of 2048 lines of 1024 bytes, of which the screen shows a window:
//! 640 x 480 pixels (or 320 x 240, each pixel and line doubled) at 1, 2, 4
//! or 8 bits per pixel through a 256-entry palette of 5:6:5 colour, VGA
//! timing at 59.94 Hz, and an interrupt at the start of vertical blanking.
//!
//! Pixels are chunky, the first pixel of a byte in its low bits, as the
//! graphics study draws them (studies/graphics). There's no blitter
//! (RFC 0016's stage 2); everything is drawn by the CPU.
//!
//! In the slot's region (slot 1 is 0x1000_0000):
//!   +0x0000000  VRAM, 2 MB
//!   +0xFF00000  registers, 32 bits:
//!     +00  R: the card's ID, 0x0016_0001
//!     +04  R/W: mode: bits 1-0 log2 of the bits per pixel, bit 2 the
//!          320 x 240 modes, bit 3 display on (off shows palette entry 0)
//!     +08  R/W: start: the screen's first byte in VRAM, line * 1024 +
//!          byte; lines wrap at 2048, bytes at 1024. It takes effect at
//!          the next frame
//!     +0C  R/W: palette index (writing +10 moves it on)
//!     +10  R/W: the palette entry at the index, as 0xRRGGBB; the card
//!          keeps 5:6:5 of it
//!     +14  R: bit 0 a vertical blank began since cleared, bit 1 in
//!          vertical blanking now. W: 1 in bit 0 clears it
//!     +18  R/W: bit 0 interrupt at vertical blanking
//!     +1C  R: the line being scanned, 0-524 (480 and up are blanking)

pub const VRAM_SIZE: usize = 2 << 20;
pub const STRIDE: usize = 1024;
pub const WIDTH: usize = 640;
pub const HEIGHT: usize = 480;
pub const REGS: u32 = 0x0FF0_0000;
pub const ID: u32 = 0x0016_0001;
/// 800 clocks a line at 25.175 MHz, 525 lines a frame.
const LINE_NS: f64 = 800.0 / 25.175e6 * 1e9;
const LINES: u64 = 525;

pub struct Video {
    pub vram: Vec<u8>,
    pub mode: u32,
    pub start: u32,
    /// The start the current frame shows (latched at its top).
    shown_start: u32,
    pub pal_index: u32,
    /// 5:6:5 entries.
    pub palette: [u16; 256],
    pub vblank_flag: bool,
    pub irq_enable: bool,
    /// The frame counted up to, so a vertical blank is noticed once.
    frame: u64,
    /// VRAM, the mode or the palette changed since the screen was last
    /// rendered.
    pub dirty: bool,
}

impl Default for Video {
    fn default() -> Video {
        Video::new()
    }
}

fn to565(rgb: u32) -> u16 {
    (((rgb >> 19) & 0x1F) << 11 | ((rgb >> 10) & 0x3F) << 5 | ((rgb >> 3) & 0x1F)) as u16
}

fn from565(c: u16) -> u32 {
    let (r, g, b) = ((c >> 11) as u32, ((c >> 5) & 0x3F) as u32, (c & 0x1F) as u32);
    (r << 3 | r >> 2) << 16 | (g << 2 | g >> 4) << 8 | (b << 3 | b >> 2)
}

impl Video {
    pub fn new() -> Video {
        Video {
            vram: vec![0; VRAM_SIZE],
            mode: 0,
            start: 0,
            shown_start: 0,
            pal_index: 0,
            palette: [0; 256],
            vblank_flag: false,
            irq_enable: false,
            frame: 0,
            dirty: true,
        }
    }

    fn line_at(now_ns: u64) -> u64 {
        (now_ns as f64 / LINE_NS) as u64
    }

    /// Bring the card up to `now_ns`: each frame that reached its blanking
    /// sets the flag and latches the start.
    pub fn advance(&mut self, now_ns: u64) {
        let line = Self::line_at(now_ns);
        // the frame whose blanking (line 480) has been reached most recently
        let frame = (line + LINES - 480) / LINES;
        if frame > self.frame {
            self.frame = frame;
            self.vblank_flag = true;
            if self.shown_start != self.start {
                self.shown_start = self.start;
                self.dirty = true;
            }
        }
    }

    pub fn irq(&self) -> bool {
        self.irq_enable && self.vblank_flag
    }

    /// When the next vertical blank begins, if it would interrupt.
    pub fn next_ns(&self, _now_ns: u64) -> Option<u64> {
        if !self.irq_enable || self.vblank_flag {
            return None;
        }
        let line = (self.frame + 1) * LINES - (LINES - 480);
        Some((line as f64 * LINE_NS).ceil() as u64)
    }

    pub fn read_reg(&mut self, reg: u32, now_ns: u64) -> u32 {
        self.advance(now_ns);
        match reg {
            0x00 => ID,
            0x04 => self.mode,
            0x08 => self.start,
            0x0C => self.pal_index,
            0x10 => from565(self.palette[self.pal_index as usize]),
            0x14 => {
                let in_blank = Self::line_at(now_ns) % LINES >= 480;
                self.vblank_flag as u32 | (in_blank as u32) << 1
            }
            0x18 => self.irq_enable as u32,
            0x1C => (Self::line_at(now_ns) % LINES) as u32,
            _ => 0,
        }
    }

    pub fn write_reg(&mut self, reg: u32, v: u32, now_ns: u64) {
        self.advance(now_ns);
        match reg {
            0x04 => {
                self.mode = v & 0xF;
                self.dirty = true;
            }
            0x08 => self.start = v & (VRAM_SIZE as u32 - 1),
            0x0C => self.pal_index = v & 0xFF,
            0x10 => {
                self.palette[self.pal_index as usize] = to565(v);
                self.pal_index = (self.pal_index + 1) & 0xFF;
                self.dirty = true;
            }
            0x14 => {
                if v & 1 != 0 {
                    self.vblank_flag = false;
                }
            }
            0x18 => self.irq_enable = v & 1 != 0,
            _ => {}
        }
    }

    /// The screen as 0xRRGGBB pixels, 640 x 480, row by row.
    pub fn rgb_into(&self, out: &mut Vec<u32>) {
        out.clear();
        out.reserve(WIDTH * HEIGHT);
        let colours: Vec<u32> = self.palette.iter().map(|&c| from565(c)).collect();
        if self.mode & 8 == 0 {
            out.resize(WIDTH * HEIGHT, colours[0]);
            return;
        }
        let depth = self.mode & 3;
        let bpp = 1usize << depth;
        let mask = (1usize << bpp) - 1;
        let low = self.mode & 4 != 0;
        let (row0, col0) = ((self.shown_start as usize) >> 10, self.shown_start as usize & 1023);
        for y in 0..HEIGHT {
            let sy = if low { y / 2 } else { y };
            let line = ((row0 + sy) % 2048) * STRIDE;
            for x in 0..WIDTH {
                let sx = if low { x / 2 } else { x };
                let bit = sx * bpp;
                let byte = self.vram[line + (col0 + bit / 8) % STRIDE];
                let v = (byte as usize >> (bit % 8)) & mask;
                out.push(colours[v]);
            }
        }
    }
}
