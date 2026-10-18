//! The video of RFC 0042: its two timing families, the modes, the pixel
//! layouts, the line descriptors or a frame base, the palette, the
//! cursor, the beam's position and the bandwidth options, as the
//! simulator models them (RFC 0042, 12).
//!
//! Time here is in sub-ticks, [`SUB`] to a master tick, so that both
//! pixel clocks are whole numbers of them: VGA's is two ticks, XGA's 65
//! MHz pixel 1007 sub-ticks (50.35 / 65 = 1007 / 1300).
//!
//! A line is rendered when it starts, from the memory and the registers
//! as they are then; its descriptor is read in the line before's
//! blanking. The shifters' loads and the slots that refill the holding
//! registers are followed through each CPU cycle, for the bandwidth: B0
//! counts the loads that found no word (the picture would glitch), B1
//! stretches the cycle by two ticks for each such load (the steal), B2
//! takes two words a slot.

/// Sub-ticks to a master tick.
pub const SUB: u64 = 1300;
/// RAM's bank 1, the video's, in bytes, and its size.
pub const BANK1: usize = 0x20_0000;
const BANK1_WORDS: u32 = 0x8_0000;

/// How the holding register's bits reach the shifters (RFC 0042, 4).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Layout {
    /// Chunky, as built: shifter k holds bit k of each nibble.
    L0,
    /// Planar: shifter k holds byte k.
    L1,
}

/// How the video gets its words (RFC 0042, 9).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Bandwidth {
    /// A slot a CPU cycle and through I/O holds, one holding register.
    B0,
    /// B0 with a second holding register and two-tick steals.
    B1,
    /// A 64-bit bank: two words a slot.
    B2,
}

/// The board's choices, which aren't registers.
#[derive(Clone, Copy, Debug)]
pub struct Board {
    pub layout: Layout,
    pub bandwidth: Bandwidth,
    /// XGA's pixel, in sub-ticks (1007: 65 MHz).
    pub xga_pixel: u64,
}

impl Default for Board {
    fn default() -> Board {
        Board {
            layout: Layout::L0,
            bandwidth: Bandwidth::B0,
            xga_pixel: 1007,
        }
    }
}

/// A timing family (RFC 0042, 2).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Family {
    pub width: usize,
    pub height: usize,
    /// Characters of 8 pixels a line, and the first of the sync.
    pub chars: u64,
    pub sync: u64,
    /// Lines a frame, and the picture's first.
    pub lines: u64,
    pub first: u64,
    /// The descriptor table's word for picture line 0.
    pub table: u32,
}

pub const VGA: Family = Family {
    width: 640,
    height: 480,
    chars: 100,
    sync: 82,
    lines: 525,
    first: 45,
    table: 44,
};

pub const XGA: Family = Family {
    width: 1024,
    height: 768,
    chars: 168,
    sync: 131,
    lines: 806,
    first: 38,
    table: 37,
};

/// A mode (RFC 0042, 3): its family, the bits a pixel, and whether a
/// pixel is two wide.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Mode {
    pub family: Family,
    pub bits: u32,
    pub double: bool,
}

impl Mode {
    /// Modes 0-6 (M0-M6); 7 shows nothing.
    pub fn of(n: u32) -> Option<Mode> {
        let (family, bits, double) = match n {
            0 => (VGA, 4, false),
            1 => (VGA, 8, true),
            2 => (VGA, 8, false),
            3 => (VGA, 2, false),
            4 => (VGA, 1, false),
            5 => (XGA, 2, false),
            6 => (XGA, 1, false),
            _ => return None,
        };
        Some(Mode {
            family,
            bits,
            double,
        })
    }

    /// The pixels a line holds in memory.
    pub fn pixels(&self) -> usize {
        if self.double {
            self.family.width / 2
        } else {
            self.family.width
        }
    }

    /// A line's words.
    pub fn words(&self) -> usize {
        self.pixels() * self.bits as usize / 32
    }
}

/// For each pixel of a word, its bits' positions in the word, low bit
/// first (RFC 0042, 4).
fn bit_table(bits: u32, layout: Layout, f1: bool) -> Vec<Vec<u32>> {
    let n = 32 / bits;
    (0..n)
        .map(|p| {
            (0..bits)
                .map(|i| match (layout, bits) {
                    (Layout::L0, 4) => 4 * p + i,
                    (Layout::L0, 8) => 8 * p + i,
                    (Layout::L0, 2) if f1 => 2 * p + i,
                    (Layout::L0, 2) => 4 * (p % 8) + p / 8 + 2 * i,
                    (Layout::L0, _) if f1 => p,
                    (Layout::L0, _) => 4 * (p % 8) + p / 8,
                    (Layout::L1, 4) => 8 * i + p,
                    (Layout::L1, 8) if i < 4 => 8 * i + 2 * p,
                    (Layout::L1, 8) => 8 * (i - 4) + 2 * p + 1,
                    (Layout::L1, 2) => 16 * i + p,
                    (Layout::L1, _) => p,
                })
                .collect()
        })
        .collect()
}

/// A decoder of words into pixels: for each of the word's four bytes,
/// what it adds to each pixel's value.
struct Decoder {
    per_word: usize,
    /// [byte][value][pixel]
    lut: Vec<u8>,
}

impl Decoder {
    fn new(bits: u32, layout: Layout, f1: bool) -> Decoder {
        let table = bit_table(bits, layout, f1);
        let per_word = table.len();
        let mut lut = vec![0u8; 4 * 256 * per_word];
        for (p, pos) in table.iter().enumerate() {
            for (i, &b) in pos.iter().enumerate() {
                let byte = (b / 8) as usize;
                for v in 0..256 {
                    if (v >> (b % 8)) & 1 != 0 {
                        lut[(byte * 256 + v) * per_word + p] |= 1 << i;
                    }
                }
            }
        }
        Decoder { per_word, lut }
    }

    fn decode(&self, w: u32, out: &mut [u8]) {
        let n = self.per_word;
        out[..n].fill(0);
        for byte in 0..4 {
            let v = ((w >> (8 * byte)) & 0xFF) as usize;
            let row = &self.lut[(byte * 256 + v) * n..(byte * 256 + v + 1) * n];
            for (o, r) in out.iter_mut().zip(row) {
                *o |= r;
            }
        }
    }
}

/// What the next event is.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Step {
    /// The line starts.
    Start,
    /// The next line's descriptor is read.
    Descriptor,
}

pub struct Video {
    pub board: Board,
    /// The control register (RFC 0042, 8).
    pub ctrl: u32,
    pub palette: [u16; 256],
    pub flag: bool,
    pub fbase: u32,
    pub cursor_x: i32,
    pub cursor_y: i32,
    pub cursor_base: u32,
    /// The frame's mode (None: mode 7), F1 and D1, latched as it starts.
    mode: Option<Mode>,
    f1: bool,
    d1: bool,
    family: Family,
    pixel: u64,
    frame_start: u64,
    line: u64,
    step: Step,
    next_event: u64,
    /// The next line's descriptor, as read.
    desc: u32,
    decoder: Decoder,
    decoder_key: (u32, Layout, bool),
    picture: Vec<u16>,
    /// The frames completed, and the last one.
    pub frames: u64,
    pub last: Vec<u16>,
    pub last_size: (usize, usize),
    // the bandwidth: the loads left in this line, the next's time, the
    // period, the units (words, or two in B2) in the holding registers,
    // the units fetched
    loads_left: u64,
    next_load: u64,
    load_period: u64,
    ahead: u64,
    fetched: u64,
    units: u64,
    pub underruns: u64,
    pub steals: u64,
    pub line_irqs: u64,
}

impl Video {
    pub fn new(board: Board) -> Video {
        let mut v = Video {
            board,
            ctrl: 0,
            palette: [0; 256],
            flag: false,
            fbase: 0,
            cursor_x: 0,
            cursor_y: 0,
            cursor_base: 0,
            mode: Mode::of(0),
            f1: false,
            d1: false,
            family: VGA,
            pixel: 2 * SUB,
            frame_start: 0,
            line: 0,
            step: Step::Start,
            next_event: 0,
            desc: 0,
            decoder: Decoder::new(4, board.layout, false),
            decoder_key: (4, board.layout, false),
            picture: vec![0; VGA.width * VGA.height],
            frames: 0,
            last: Vec::new(),
            last_size: (VGA.width, VGA.height),
            loads_left: 0,
            next_load: 0,
            load_period: 1,
            ahead: 0,
            fetched: 0,
            units: 0,
            underruns: 0,
            steals: 0,
            line_irqs: 0,
        };
        v.next_event = v.event_time();
        v
    }

    pub fn irq(&self) -> bool {
        self.flag && self.ctrl & 4 != 0
    }

    /// A write to the registers (offset: PA[10:0], a word's).
    pub fn write(&mut self, off: u32, v: u32) {
        if off >= 0x400 {
            self.palette[((off - 0x400) >> 2) as usize & 255] = v as u16;
            return;
        }
        match off & 0x1C {
            0x00 => self.ctrl = v & 0x3FF,
            0x04 => self.flag = false,
            0x0C => self.fbase = v & 0x7F_FFFF,
            0x10 => self.cursor_x = sign12(v),
            0x14 => self.cursor_y = sign12(v),
            0x18 => self.cursor_base = v & 0x7_FFFF,
            _ => {}
        }
    }

    /// A read of the registers: the beam's position at sub-tick `now`
    /// (P1), else 0.
    pub fn read(&self, off: u32, now: u64) -> u32 {
        if off < 0x400 && off & 0x1C == 0x08 {
            let (line, ch) = self.beam(now);
            return line as u32 | ((ch as u32) << 16);
        }
        0
    }

    /// The line and the character at sub-tick `now`.
    pub fn beam(&self, now: u64) -> (u64, u64) {
        let c = now.saturating_sub(self.frame_start) / (8 * self.pixel);
        let line = (c / self.family.chars).min(self.family.lines - 1);
        (line, c % self.family.chars)
    }

    fn line_time(&self) -> u64 {
        8 * self.pixel * self.family.chars
    }

    fn event_time(&self) -> u64 {
        let start = self.frame_start + self.line * self.line_time();
        match self.step {
            Step::Start => start,
            // the descriptor at the end of the sync's third character
            Step::Descriptor => start + 8 * self.pixel * (self.family.sync + 3),
        }
    }

    fn cap(&self) -> u64 {
        if self.board.bandwidth == Bandwidth::B1 {
            2
        } else {
            1
        }
    }

    /// A slot: the holding registers refilled, if the line still wants.
    fn slot(&mut self) {
        if self.loads_left > 0 && self.ahead < self.cap() && self.fetched < self.units {
            self.ahead += 1;
            self.fetched += 1;
        }
    }

    /// The video through a CPU cycle from tick t0, `k` ticks of which
    /// `hold` an I/O access's: the events, and the ticks it steals.
    pub fn cycle(&mut self, ram: &[u8], t0: u64, k: u64, hold: u64) -> u64 {
        let start = t0 * SUB;
        let mut end = (t0 + k) * SUB;
        let mut steal = 0;
        // an I/O hold's slots, every two ticks through it
        let (mut hs, nh) = (1, hold / 2);
        loop {
            let tl = if self.loads_left > 0 {
                self.next_load
            } else {
                u64::MAX
            };
            let te = self.next_event;
            if tl.min(te) > end {
                break;
            }
            if te <= tl {
                self.event(ram, te);
                continue;
            }
            while hs <= nh && start + 2 * hs * SUB <= tl {
                self.slot();
                hs += 1;
            }
            if self.ahead == 0 {
                if self.board.bandwidth == Bandwidth::B1 {
                    steal += 2;
                    end += 2 * SUB;
                    self.steals += 1;
                } else {
                    self.underruns += 1;
                }
                self.fetched += 1;
            } else {
                self.ahead -= 1;
            }
            self.loads_left -= 1;
            self.next_load += self.load_period;
        }
        while hs <= nh {
            self.slot();
            hs += 1;
        }
        // the cycle's tail
        self.slot();
        steal
    }

    fn event(&mut self, ram: &[u8], now: u64) {
        match self.step {
            Step::Start => {
                if self.line == self.family.lines {
                    self.end_frame(now);
                }
                let fam = self.family;
                if self.line >= fam.first {
                    self.start_line(ram, now, (self.line - fam.first) as usize);
                }
                self.step = Step::Descriptor;
            }
            Step::Descriptor => {
                let fam = self.family;
                if self.line + 1 >= fam.first && self.line + 1 < fam.lines {
                    self.read_descriptor(ram, (self.line + 1 - fam.first) as u32);
                }
                self.line += 1;
                self.step = Step::Start;
            }
        }
        self.next_event = self.event_time();
    }

    fn read_descriptor(&mut self, ram: &[u8], y: u32) {
        if self.d1 {
            let words = self.mode.map_or(0, |m| m.words() as u32);
            let base = (self.fbase & 0x7_FFFF).wrapping_add(y * words) & (BANK1_WORDS - 1);
            self.desc = base | (self.fbase & 0x78_0000);
            return;
        }
        let tsel = if self.ctrl & 2 != 0 { 1024 } else { 0 };
        self.desc = bank1_word(ram, tsel + self.family.table + y);
        if self.desc & (1 << 23) != 0 {
            self.flag = true;
            self.line_irqs += 1;
        }
    }

    /// The frame's end, as its last line ends: the interrupt, the picture
    /// kept, the next frame's mode.
    fn end_frame(&mut self, now: u64) {
        self.flag = true;
        self.frames += 1;
        self.last_size = (self.family.width, self.family.height);
        std::mem::swap(&mut self.last, &mut self.picture);
        self.mode = Mode::of((self.ctrl >> 4) & 7);
        self.f1 = self.ctrl & 0x80 != 0;
        self.d1 = self.ctrl & 0x200 != 0;
        if let Some(m) = self.mode {
            self.family = m.family;
        }
        self.pixel = if self.family == XGA {
            self.board.xga_pixel
        } else {
            2 * SUB
        };
        self.picture = vec![0; self.family.width * self.family.height];
        self.frame_start = now;
        self.line = 0;
    }

    /// Picture line y starts at sub-tick `now`: its pixels from the
    /// memory as it is, and its loads.
    fn start_line(&mut self, ram: &[u8], now: u64, y: usize) {
        let w = self.family.width;
        let on = self.ctrl & 1 != 0;
        let mode = match self.mode {
            Some(m) if on => m,
            _ => {
                self.picture[y * w..(y + 1) * w].fill(0);
                self.loads_left = 0;
                return;
            }
        };
        let words = mode.words();
        let unit = if self.board.bandwidth == Bandwidth::B2 {
            2
        } else {
            1
        };
        self.units = (words / unit) as u64;
        self.loads_left = self.units;
        self.load_period = w as u64 * self.pixel / self.units;
        self.next_load = now;
        self.ahead = self.cap().min(self.units);
        self.fetched = self.ahead;

        let f1 = self.f1 && self.board.layout == Layout::L0;
        let key = (mode.bits, self.board.layout, f1);
        if key != self.decoder_key {
            self.decoder = Decoder::new(mode.bits, self.board.layout, f1);
            self.decoder_key = key;
        }
        let base = self.desc & 0x7_FFFF;
        let bank = ((self.desc >> 19) & 15) as usize;
        let row = &mut self.picture[y * w..(y + 1) * w];
        let mut px = [0u8; 32];
        let mut x = 0;
        for j in 0..words as u32 {
            self.decoder
                .decode(bank1_word(ram, base.wrapping_add(j)), &mut px);
            for &p in &px[..self.decoder.per_word] {
                let c = if mode.bits == 8 {
                    self.palette[p as usize]
                } else {
                    self.palette[16 * bank + p as usize]
                };
                if mode.double {
                    row[x] = c;
                    row[x + 1] = c;
                    x += 2;
                } else {
                    row[x] = c;
                    x += 1;
                }
            }
        }
        if self.ctrl & 0x100 != 0 {
            self.cursor(ram, y);
        }
    }

    /// The cursor over picture line y (C1).
    fn cursor(&mut self, ram: &[u8], y: usize) {
        let r = y as i32 - self.cursor_y;
        if !(0..32).contains(&r) {
            return;
        }
        let w = self.family.width;
        let a = self.cursor_base.wrapping_add(2 * r as u32);
        let bits =
            u64::from(bank1_word(ram, a)) | (u64::from(bank1_word(ram, a.wrapping_add(1))) << 32);
        for p in 0..32 {
            let v = (bits >> (2 * p)) & 3;
            let x = self.cursor_x + p;
            if v != 0 && (0..w as i32).contains(&x) {
                self.picture[y * w + x as usize] = self.palette[252 + v as usize];
            }
        }
    }

    /// The picture the memory and the registers make now, every line
    /// rendered at once (the frame's mode, the descriptors as they are).
    pub fn snapshot(&self, ram: &[u8]) -> (usize, usize, Vec<u16>) {
        let mut v = Video::new(self.board);
        v.ctrl = self.ctrl;
        v.palette = self.palette;
        v.fbase = self.fbase;
        v.cursor_x = self.cursor_x;
        v.cursor_y = self.cursor_y;
        v.cursor_base = self.cursor_base;
        // as the next frame would latch them
        v.end_frame(0);
        for y in 0..v.family.height {
            v.read_descriptor(ram, y as u32);
            v.start_line(ram, 0, y);
        }
        (v.family.width, v.family.height, v.picture)
    }
}

fn sign12(v: u32) -> i32 {
    ((v << 20) as i32) >> 20
}

/// Bank 1's word at a word address.
fn bank1_word(ram: &[u8], a: u32) -> u32 {
    let i = BANK1 + 4 * (a & (BANK1_WORDS - 1)) as usize;
    u32::from_le_bytes([ram[i], ram[i + 1], ram[i + 2], ram[i + 3]])
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every bit of a word is in exactly one pixel, in every layout.
    #[test]
    fn layouts_cover_the_word() {
        for layout in [Layout::L0, Layout::L1] {
            for bits in [1, 2, 4, 8] {
                for f1 in [false, true] {
                    let mut seen = 0u64;
                    for pos in bit_table(bits, layout, f1) {
                        for b in pos {
                            assert_eq!(seen >> b & 1, 0);
                            seen |= 1 << b;
                        }
                    }
                    assert_eq!(seen, 0xFFFF_FFFF);
                }
            }
        }
    }

    #[test]
    fn chunky_nibbles() {
        let d = Decoder::new(4, Layout::L0, false);
        let mut px = [0u8; 32];
        d.decode(0x8765_4321, &mut px);
        assert_eq!(&px[..8], &[1, 2, 3, 4, 5, 6, 7, 8]);
        let d = Decoder::new(1, Layout::L0, false);
        d.decode(0x0000_0011, &mut px);
        // bits 0 and 4: pixels 0 and 1
        assert_eq!(&px[..4], &[1, 1, 0, 0]);
    }

    /// Cycles of k ticks until the next frame is complete; the ticks
    /// stolen.
    fn frame(v: &mut Video, ram: &[u8], t: &mut u64, k: u64) -> u64 {
        let (f, mut steal) = (v.frames, 0);
        while v.frames == f {
            let s = v.cycle(ram, *t, k, 0);
            *t += k + s;
            steal += s;
        }
        steal
    }

    fn put(ram: &mut [u8], word: u32, v: u32) {
        let i = BANK1 + 4 * word as usize;
        ram[i..i + 4].copy_from_slice(&v.to_le_bytes());
    }

    /// A video in `ctrl`'s mode from the next frame, the palette entry n
    /// being n.
    fn setup(board: Board, ctrl: u32) -> (Video, Vec<u8>, u64) {
        let ram = vec![0u8; 4 << 20];
        let mut v = Video::new(board);
        for n in 0..256 {
            v.palette[n] = n as u16;
        }
        v.ctrl = ctrl;
        let mut t = 0;
        frame(&mut v, &ram, &mut t, 5);
        (v, ram, t)
    }

    /// A VGA frame is 840,000 ticks; an XGA one 806 lines of 1344 pixels
    /// at 65 MHz.
    #[test]
    fn frame_times() {
        let ram = vec![0u8; 4 << 20];
        let mut v = Video::new(Board::default());
        let mut t = 0;
        frame(&mut v, &ram, &mut t, 5);
        assert_eq!(t, 840_000);
        // the mode changes at the next frame
        v.ctrl = 5 << 4;
        frame(&mut v, &ram, &mut t, 1);
        assert_eq!((t, v.last_size), (1_680_000, (640, 480)));
        frame(&mut v, &ram, &mut t, 1);
        assert_eq!(v.last_size, (1024, 768));
        assert_eq!(t - 1_680_000, (806 * 1344 * 1007_u64).div_ceil(SUB));
    }

    /// M1: bytes, two pixels wide, the palette by the byte alone; the
    /// descriptors' line and bank.
    #[test]
    fn m1_bytes() {
        let (mut v, mut ram, mut t) = setup(Board::default(), 1 | (1 << 4));
        put(&mut ram, VGA.table, 0x100 | (3 << 19));
        put(&mut ram, 0x100, 0x8070_6050);
        frame(&mut v, &ram, &mut t, 5);
        assert_eq!(
            &v.last[..8],
            &[0x50, 0x50, 0x60, 0x60, 0x70, 0x70, 0x80, 0x80]
        );
        // line 1's descriptor is 0: bank 1's word 0, the descriptor itself
        assert_eq!(v.last[640], (0x100 & 0xFF) as u16);
    }

    /// M3 in L0, with F1 and in L1; the palette bank.
    #[test]
    fn m3_layouts() {
        // bits 0, 3 and 4. L0: pixel 0 is bits 0 and 2, 1 bits 4 and 6, 2
        // bits 8 and 10; F1: 0 is bits 0 and 1, 1 bits 2 and 3, 2 bits 4
        // and 5; L1: pixel p bits p and 16 + p
        let w = 0b1_1001u32;
        for (board, ctrl, want) in [
            (Board::default(), 0, [1, 1, 0]),
            (Board::default(), 0x80, [1, 2, 1]),
            (
                Board {
                    layout: Layout::L1,
                    ..Board::default()
                },
                0,
                [1, 0, 0],
            ),
        ] {
            let (mut v, mut ram, mut t) = setup(board, 1 | (3 << 4) | ctrl);
            put(&mut ram, VGA.table, 0x100 | (2 << 19));
            put(&mut ram, 0x100, w);
            frame(&mut v, &ram, &mut t, 5);
            let got: Vec<u16> = v.last[..3].iter().map(|c| c - 32).collect();
            assert_eq!(got, want, "{board:?} {ctrl:x}");
        }
    }

    /// D1: lines one after another from the frame base; a descriptor's
    /// interrupt only with D0.
    #[test]
    fn frame_base() {
        let (mut v, mut ram, mut t) = setup(Board::default(), 1 | (4 << 4) | 0x200);
        v.fbase = 0x200 | (1 << 19);
        put(&mut ram, 0x200 + 20, 1);
        put(&mut ram, VGA.table + 2, 1 << 23);
        frame(&mut v, &ram, &mut t, 5);
        assert_eq!(v.last[640], 16 + 1);
        assert_eq!(v.last[641], 16);
        assert_eq!(v.line_irqs, 0);
        v.ctrl = 1 | (4 << 4);
        frame(&mut v, &ram, &mut t, 5);
        frame(&mut v, &ram, &mut t, 5);
        assert_eq!(v.line_irqs, 1);
    }

    /// The cursor, hanging off the left edge.
    #[test]
    fn cursor() {
        let (mut v, mut ram, mut t) = setup(Board::default(), 1 | 0x100);
        v.cursor_base = 0x300;
        v.cursor_x = -2;
        v.cursor_y = 10;
        // row 0: pixels 2 and 3 (on the screen's 0 and 1) colours 1 and 3
        put(&mut ram, 0x300, (1 << 4) | (3 << 6));
        frame(&mut v, &ram, &mut t, 5);
        assert_eq!(&v.last[640 * 10..640 * 10 + 3], &[253, 255, 0]);
        assert_eq!(v.last[640 * 9], 0);
    }

    /// The beam: line and character.
    #[test]
    fn beam() {
        let v = Video::new(Board::default());
        let now = (45 * 1600 + 3 * 16) * SUB;
        assert_eq!(v.read(0x08, now), 45 | (3 << 16));
    }

    /// M2 needs a word every 8 ticks: cycles of 9 leave B0 short, B1
    /// steals, B2 keeps up.
    #[test]
    fn bandwidth() {
        for (bw, under, stolen) in [
            (Bandwidth::B0, true, false),
            (Bandwidth::B1, false, true),
            (Bandwidth::B2, false, false),
        ] {
            let board = Board {
                bandwidth: bw,
                ..Board::default()
            };
            let (mut v, ram, mut t) = setup(board, 1 | (2 << 4));
            let steal = frame(&mut v, &ram, &mut t, 9);
            assert_eq!(v.underruns > 0, under, "{bw:?}");
            assert_eq!(steal > 0, stolen, "{bw:?}");
            assert_eq!(steal, 2 * v.steals);
        }
        // M0 at 9 ticks a cycle: no shortage anywhere
        let (mut v, ram, mut t) = setup(Board::default(), 1);
        frame(&mut v, &ram, &mut t, 9);
        assert_eq!(v.underruns, 0);
    }
}
