//! The video: 640 × 480 × 4 at VGA's timing, through an IMS G171 RAMDAC,
//! as board2.py's U_VQ, U_VF, U_VH, U_VV, U_VS, U_VC and U_LINE build it.
//!
//! **Time.** A line is 200 words of 8 ticks (1600 ticks, 31.78 µs), a
//! frame 525 lines; both counters run from power-on and aren't reset. A
//! line here starts as HSYNC ends, when the line counter moves on: 12
//! words of back porch, 160 shown (pixel x at tick 96 + 2x), 4 of front
//! porch, 24 of HSYNC. Lines 0-479 are shown, 480-524 are the vertical
//! blank (VBL).
//!
//! **The scanline** (the interrupt controller's +6, and the copper's
//! compare) is U_LINE's count: the line, but 0-12 again for the blank's
//! last 13 lines (its 9 bits wrap at 512 and it's cleared at 13), so a
//! copper WAIT for a line under 13 matches twice a frame.
//!
//! **The frame interrupt** comes as line 481 starts (the blank's first
//! HSYNC with VBL set), if VIE is set and none is pending; a write of the
//! control register acknowledges it.
//!
//! **The buffer.** The video reads the frame buffer a word (four pixels)
//! at a time into a two-word buffer, in phase F's ticks 1-2; when the
//! buffer is empty as F starts, F is two ticks longer and reads a second
//! word in ticks 3-4 (VEXT). The fetch runs from the line's start to its
//! 160th word, and in HSYNC with its counter held at 0; the shifter takes
//! a word at each shown word's end. That's modelled as the netlist has
//! it, so a program's time with the display on is the board's, and a
//! word the shifter finds missing is counted (`underflows`): cycles too
//! long between phase Fs (the CF card at PIO mode 0) starve it.
//!
//! **The picture** is drawn as RFC 0047 specifies it (line y's pixel x
//! the nibble at base + 512y + x/2, the low nibble for even x), from RAM
//! as it is when the pixel is shown and through the palette as it is
//! then, so the copper's changes land where they would. The netlist's
//! buffer seems to show each line two words late (the words it fetches
//! in HSYNC stay in the buffer), which isn't drawn here.

pub const LINE_TICKS: u64 = 1600;
pub const LINES: u64 = 525;
pub const WIDTH: usize = 640;
pub const HEIGHT: usize = 480;
/// The frame buffers (the control register's bit 0).
pub const FB: [usize; 2] = [0x18_0000, 0x1C_0000];
const SHOWN: u64 = 96;
const HSYNC: u64 = 1408;
const WORDS: u16 = 160;

/// The IMS G171: 256 colours of 18 bits, by RS1-RS0: 0 the write address,
/// 1 the colour (red, green, blue, 6 bits each, then the address moves on),
/// 2 the pixel mask, 3 the read address. Its palette and mask are
/// undefined at power-on; here they're black and 0xFF.
#[derive(Clone, Debug)]
pub struct Palette {
    pub rgb: [[u8; 3]; 256],
    pub mask: u8,
    waddr: u8,
    raddr: u8,
    wstep: usize,
    rstep: usize,
    wbuf: [u8; 3],
}

impl Default for Palette {
    fn default() -> Palette {
        Palette {
            rgb: [[0; 3]; 256],
            mask: 0xFF,
            waddr: 0,
            raddr: 0,
            wstep: 0,
            rstep: 0,
            wbuf: [0; 3],
        }
    }
}

impl Palette {
    pub fn read(&mut self, rs: u32) -> u8 {
        match rs & 3 {
            0 => self.waddr,
            1 => {
                let v = self.rgb[self.raddr as usize][self.rstep];
                self.rstep += 1;
                if self.rstep == 3 {
                    self.rstep = 0;
                    self.raddr = self.raddr.wrapping_add(1);
                }
                v
            }
            2 => self.mask,
            _ => self.raddr,
        }
    }

    pub fn write(&mut self, rs: u32, v: u8) {
        match rs & 3 {
            0 => {
                self.waddr = v;
                self.wstep = 0;
            }
            1 => {
                self.wbuf[self.wstep] = v & 0x3F;
                self.wstep += 1;
                if self.wstep == 3 {
                    self.wstep = 0;
                    self.rgb[self.waddr as usize] = self.wbuf;
                    self.waddr = self.waddr.wrapping_add(1);
                }
            }
            2 => self.mask = v,
            _ => {
                self.raddr = v;
                self.rstep = 0;
            }
        }
    }

    /// A pixel value's colour, 0xRRGGBB.
    pub fn colour(&self, p: u8) -> u32 {
        let c = self.rgb[(p & self.mask) as usize];
        let e = |v: u8| ((v << 2) | (v >> 4)) as u32;
        e(c[0]) << 16 | e(c[1]) << 8 | e(c[2])
    }
}

#[derive(Clone, Debug)]
pub struct Video {
    /// The control register: the frame buffer shown, the display on, the
    /// frame interrupt enabled.
    pub fb: bool,
    pub den: bool,
    pub vie: bool,
    vset: bool,
    vack: bool,
    /// The palette bank (U_PB): the pixels' P7-P4.
    pub bank: u8,
    pub palette: Palette,
    /// The copper's target line and its enable (CEN).
    pub target: u16,
    pub cen: bool,
    /// Lines since power-on: the one under way.
    pub line: u64,
    fifo: u8,
    fc: u16,
    fdone: bool,
    /// The shown words the shifter has taken on this line.
    taken: u16,
    pub underflows: u64,
    /// Phase Fs made longer for the buffer.
    pub stretches: u64,
    /// Draw the picture (it costs the host time).
    pub render: bool,
    drawn: usize,
    lut: Vec<[u32; 2]>,
    lut_ok: bool,
    frame: Vec<u32>,
    /// The last whole frame drawn, 0xRRGGBB, and how many have been.
    pub shown: Vec<u32>,
    pub frames: u64,
    /// Frames ended since power-on, drawn or not.
    pub frame_count: u64,
}

impl Default for Video {
    fn default() -> Video {
        Video::new()
    }
}

impl Video {
    pub fn new() -> Video {
        Video {
            fb: false,
            den: false,
            vie: false,
            vset: false,
            vack: false,
            bank: 0,
            palette: Palette::default(),
            target: 0,
            cen: false,
            line: 0,
            fifo: 0,
            fc: 0,
            fdone: false,
            taken: 0,
            underflows: 0,
            stretches: 0,
            render: false,
            drawn: 0,
            lut: vec![[0; 2]; 256],
            lut_ok: false,
            frame: vec![0; WIDTH * HEIGHT],
            shown: vec![0; WIDTH * HEIGHT],
            frames: 0,
            frame_count: 0,
        }
    }

    /// Reset: the control register, the frame interrupt, the palette bank,
    /// the copper's enable and its line's bit 8 (U_VC, U_VS, U_PB,
    /// U_LREQ). The counters run on.
    pub fn reset(&mut self) {
        self.fb = false;
        self.den = false;
        self.vie = false;
        self.vset = false;
        self.vack = false;
        self.bank = 0;
        self.cen = false;
        self.target &= 0xFF;
        self.lut_ok = false;
    }

    /// The frame's line, 0-524.
    pub fn frame_line(&self) -> u32 {
        (self.line % LINES) as u32
    }

    /// The scanline as U_LINE counts it.
    pub fn scanline(&self) -> u16 {
        (self.frame_line() % 512) as u16
    }

    pub fn irq(&self) -> bool {
        self.vset != self.vack
    }

    pub fn copreq(&self) -> bool {
        self.cen && self.scanline() == self.target
    }

    fn base(&self) -> u64 {
        self.line * LINE_TICKS
    }

    fn visible(&self) -> bool {
        self.frame_line() < HEIGHT as u32
    }

    /// The next line's start.
    pub fn next_event(&self) -> u64 {
        self.base() + LINE_TICKS
    }

    /// Bring the line counters up to `t`.
    pub fn advance(&mut self, t: u64, ram: &[u8]) {
        while self.next_event() <= t {
            let end = self.next_event();
            self.take_upto(end - 1);
            self.draw_to(end, ram);
            if self.frame_line() == HEIGHT as u32 - 1 {
                self.frame_count += 1;
                if self.render {
                    std::mem::swap(&mut self.frame, &mut self.shown);
                    self.frames += 1;
                }
            }
            self.line += 1;
            self.fc = 0;
            self.fdone = false;
            self.taken = 0;
            self.drawn = 0;
            if self.frame_line() == HEIGHT as u32 + 1 && self.vie && !self.irq() {
                self.vset = !self.vset;
            }
        }
    }

    /// The control register written at `t` (bit 0 the frame buffer, 1
    /// the display, 2 the frame interrupt): the frame interrupt
    /// acknowledged.
    pub fn write_control(&mut self, v: u16, t: u64, ram: &[u8]) {
        self.draw_to(t, ram);
        self.take_upto(t);
        let den = v & 2 != 0;
        if den && !self.den {
            // the shifter takes the words shown from here on
            self.taken = self.word_at(t);
        }
        self.fb = v & 1 != 0;
        self.den = den;
        self.vie = v & 4 != 0;
        self.vack = self.vset;
    }

    pub fn write_bank(&mut self, v: u16, t: u64, ram: &[u8]) {
        self.draw_to(t, ram);
        self.bank = (v & 15) as u8;
        self.lut_ok = false;
    }

    pub fn write_palette(&mut self, rs: u32, v: u8, t: u64, ram: &[u8]) {
        self.draw_to(t, ram);
        self.palette.write(rs, v);
        self.lut_ok = false;
    }

    /// The copper's target line and CEN, from a write at the interrupt
    /// controller's +6.
    pub fn write_target(&mut self, v: u16) {
        self.target = v & 0x1FF;
        self.cen = v & 0x8000 != 0;
    }

    // ---- the buffer

    /// The first shown word whose end is at or after `t`.
    fn word_at(&self, t: u64) -> u16 {
        let dt = t.saturating_sub(self.base());
        if dt < SHOWN + 7 {
            return 0;
        }
        (((dt - SHOWN - 7) / 8 + 1) as u16).min(WORDS)
    }

    /// The shifter takes the words shown up to `t`.
    fn take_upto(&mut self, t: u64) {
        if !self.den || !self.visible() {
            return;
        }
        let k = self.word_at(t + 1);
        while self.taken < k {
            if self.fifo > 0 {
                self.fifo -= 1;
            } else {
                self.underflows += 1;
            }
            self.taken += 1;
        }
    }

    fn in_hsync(&self, t: u64) -> bool {
        t >= self.base() + HSYNC
    }

    fn fetching(&self, t: u64) -> bool {
        self.den && self.visible() && (!self.fdone || self.in_hsync(t))
    }

    fn load(&mut self, t: u64) {
        self.take_upto(t);
        if self.fetching(t) && self.fifo < 2 {
            self.fifo += 1;
            if !self.in_hsync(t) {
                self.fc += 1;
                self.fdone = self.fc >= WORDS;
            }
        }
    }

    /// Phase F starting at `t0`: the video's reads in it, and the ticks it
    /// is longer for them.
    #[inline]
    pub fn phase_f(&mut self, t0: u64) -> u64 {
        if !self.den || !self.visible() {
            return 0;
        }
        self.take_upto(t0.saturating_sub(1));
        let vext = self.fetching(t0) && self.fifo == 0;
        self.load(t0 + 1);
        if vext {
            self.load(t0 + 3);
            self.stretches += 1;
            2
        } else {
            0
        }
    }

    // ---- the picture

    fn make_lut(&mut self) {
        let hi = self.bank << 4;
        for b in 0..256usize {
            self.lut[b] = [
                self.palette.colour(hi | (b as u8 & 15)),
                self.palette.colour(hi | (b as u8 >> 4)),
            ];
        }
        self.lut_ok = true;
    }

    /// Draw this line's pixels shown before `t`.
    pub fn draw_to(&mut self, t: u64, ram: &[u8]) {
        if !self.render || !self.visible() {
            return;
        }
        let dt = t.saturating_sub(self.base());
        let upto = dt.saturating_sub(SHOWN).div_ceil(2).min(WIDTH as u64) as usize & !1;
        if upto <= self.drawn {
            return;
        }
        let y = self.frame_line() as usize;
        let row = &mut self.frame[y * WIDTH..(y + 1) * WIDTH];
        if !self.den {
            row[self.drawn..upto].fill(0);
        } else {
            if !self.lut_ok {
                self.make_lut();
            }
            let row = &mut self.frame[y * WIDTH..(y + 1) * WIDTH];
            let base = FB[self.fb as usize] + 512 * y;
            for x in (self.drawn..upto).step_by(2) {
                let px = self.lut[ram[base + x / 2] as usize];
                row[x] = px[0];
                row[x + 1] = px[1];
            }
        }
        self.drawn = upto;
    }
}
