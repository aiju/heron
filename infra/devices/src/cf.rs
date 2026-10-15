//! A CompactFlash card in True IDE mode: the ATA task file, PIO data
//! transfers of 16 or 8 bits, and the few commands a small operating
//! system needs (ATA-4 and the CF specification, kept small).
//!
//! Time is in nanoseconds, passed in with each access. The card is busy
//! (BSY) for a while after a command and after each sector, and moves on
//! when an access or [`CfCard::advance`] comes at or after the time that
//! ends it; [`CfCard::next_event_ns`] says when that is.
//!
//! Only device 0 is there. The task file registers are shared by both
//! devices on the cable, so writes reach them whatever DEV says, but with
//! DEV = 1 the status reads 0 and commands are ignored.

/// Bytes in a sector.
pub const SECTOR: usize = 512;

// Status
const BSY: u8 = 0x80;
const DRDY: u8 = 0x40;
const DSC: u8 = 0x10;
const DRQ: u8 = 0x08;
const ERR: u8 = 0x01;

// Error
const ABRT: u8 = 0x04;
const IDNF: u8 = 0x10;
/// The diagnostic code for "no error", left in the error register by a
/// reset and by EXECUTE DEVICE DIAGNOSTIC.
const DIAG_OK: u8 = 0x01;

// Drive/head
const LBA: u8 = 0x40;
const DEV: u8 = 0x10;

// Device control
const NIEN: u8 = 0x02;
const SRST: u8 = 0x04;

const HEADS: u32 = 16;

const MODEL: &str = "HERON SIMULATED CF";
const SERIAL: &str = "HERON-0001";
const FIRMWARE: &str = "1.0";

/// A command that moves data.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Cmd {
    Identify,
    Read,
    Write,
    Verify,
}

/// A data transfer in progress (DRQ is set).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Xfer {
    None,
    In,
    Out,
}

/// What happens when BSY ends.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Next {
    /// A reset is done: the diagnostic signature, no interrupt.
    Ready,
    /// The next sector of the command: DRQ, with an interrupt or not.
    Sector { irq: bool },
    /// The command is done.
    Done { irq: bool, err: bool },
}

/// A CompactFlash card and the sectors on it.
#[derive(Clone, Debug)]
pub struct CfCard {
    /// BSY after a command is written: 2 µs by default.
    pub t_cmd_ns: u64,
    /// BSY after each sector's data has moved: 1 µs by default.
    pub t_sector_ns: u64,
    /// BSY after a hardware reset, or after SRST goes low: 10 µs by
    /// default. (Real cards take milliseconds; these defaults keep
    /// simulations fast.)
    pub t_reset_ns: u64,
    image: Vec<u8>,
    /// The CHS geometry: cylinders and sectors per track, with 16 heads.
    cyls: u32,
    spt: u32,
    error: u8,
    features: u8,
    count: u8,
    /// Sector number / LBA 7:0, cylinder low / LBA 15:8, cylinder high /
    /// LBA 23:16.
    addr: [u8; 3],
    head: u8,
    status: u8,
    nien: bool,
    srst: bool,
    eight_bit: bool,
    /// An interrupt is pending (INTRQ, before nIEN).
    irq: bool,
    /// When BSY ends, and what happens then. None while SRST holds the
    /// card in reset, and when it isn't busy.
    busy_until: Option<u64>,
    next: Next,
    cmd: Cmd,
    /// Sectors still to go in the command.
    left: u32,
    /// The sector being transferred.
    lba: usize,
    xfer: Xfer,
    buf: [u8; SECTOR],
    pos: usize,
}

impl CfCard {
    /// A card holding `image`, padded with zeros to whole sectors. Its
    /// power-on reset is over: it's ready at time 0.
    pub fn new(image: Vec<u8>) -> CfCard {
        let mut image = image;
        image.resize(image.len().div_ceil(SECTOR) * SECTOR, 0);
        let sectors = (image.len() / SECTOR) as u32;
        // 32 sectors per track keeps a card of up to 256 MB within 1024
        // cylinders; bigger cards have 63.
        let spt = if sectors <= HEADS * 32 * 1024 { 32 } else { 63 };
        let mut card = CfCard {
            t_cmd_ns: 2000,
            t_sector_ns: 1000,
            t_reset_ns: 10_000,
            image,
            cyls: (sectors / (HEADS * spt)).clamp(1, 16383),
            spt,
            error: 0,
            features: 0,
            count: 0,
            addr: [0; 3],
            head: 0,
            status: DRDY | DSC,
            nien: false,
            srst: false,
            eight_bit: false,
            irq: false,
            busy_until: None,
            next: Next::Ready,
            cmd: Cmd::Read,
            left: 0,
            lba: 0,
            xfer: Xfer::None,
            buf: [0; SECTOR],
            pos: 0,
        };
        card.signature();
        card
    }

    /// A hardware reset (or the start of a software one): BSY for
    /// t_reset_ns from `now_ns`, then ready, with the command in progress
    /// dropped, 16-bit transfers and nIEN cleared.
    pub fn reset(&mut self, now_ns: u64) {
        self.begin_reset();
        self.nien = false;
        self.srst = false;
        self.busy(now_ns.saturating_add(self.t_reset_ns), Next::Ready);
    }

    /// Read a task file register (CS0) or a control block register (CS1).
    /// The data register is 16 bits wide, or 8 after SET FEATURES 0x01;
    /// the others are 8 bits, read with the upper byte high.
    pub fn read(&mut self, cs1: bool, reg: u8, now_ns: u64) -> u16 {
        self.advance(now_ns);
        let reg = reg & 7;
        let v = if cs1 {
            // alternate status, which doesn't clear the interrupt
            if reg == 6 { self.shown_status() } else { 0xFF }
        } else if self.status & BSY != 0 {
            if reg == 7 && !self.dev1() {
                self.irq = false;
            }
            self.status
        } else {
            match reg {
                0 => return self.read_data(now_ns),
                1 => self.error,
                2 => self.count,
                3..=5 => self.addr[reg as usize - 3],
                6 => self.head,
                _ => {
                    if !self.dev1() {
                        self.irq = false;
                    }
                    self.shown_status()
                }
            }
        };
        0xFF00 | v as u16
    }

    /// Write a task file register (CS0) or the device control register
    /// (CS1 6). While BSY only device control is written.
    pub fn write(&mut self, cs1: bool, reg: u8, v: u16, now_ns: u64) {
        self.advance(now_ns);
        let reg = reg & 7;
        if cs1 {
            if reg == 6 {
                self.device_control(v as u8, now_ns);
            }
            return;
        }
        if self.status & BSY != 0 {
            return;
        }
        let b = v as u8;
        match reg {
            0 => self.write_data(v, now_ns),
            1 => self.features = b,
            2 => self.count = b,
            3..=5 => self.addr[reg as usize - 3] = b,
            6 => self.head = b,
            _ => self.command(b, now_ns),
        }
    }

    /// Let time pass up to `now_ns`: a BSY period that has ended by then
    /// ends.
    pub fn advance(&mut self, now_ns: u64) {
        if let Some(t) = self.busy_until
            && t <= now_ns
        {
            self.busy_until = None;
            match self.next {
                Next::Ready => {
                    self.status = DRDY | DSC;
                    self.signature();
                }
                Next::Sector { irq } => self.start_sector(irq),
                Next::Done { irq, err } => {
                    self.status = DRDY | DSC | if err { ERR } else { 0 };
                    self.irq |= irq;
                }
            }
        }
    }

    /// The INTRQ output: an interrupt is pending and nIEN is clear. It's as
    /// of the last access or [`CfCard::advance`]: a caller waiting for it
    /// advances to [`CfCard::next_event_ns`].
    pub fn intrq(&self) -> bool {
        self.irq && !self.nien
    }

    /// When the card will next change on its own (BSY ending), if it will.
    pub fn next_event_ns(&self) -> Option<u64> {
        self.busy_until
    }

    /// Whether the data register moves 8 bits per access.
    pub fn eight_bit(&self) -> bool {
        self.eight_bit
    }

    /// The card's sectors, with what has been written to them.
    pub fn image(&self) -> &[u8] {
        &self.image
    }

    fn sectors(&self) -> u32 {
        (self.image.len() / SECTOR) as u32
    }

    fn dev1(&self) -> bool {
        self.head & DEV != 0
    }

    /// The status as the host sees it: device 1 isn't there.
    fn shown_status(&self) -> u8 {
        if self.status & BSY == 0 && self.dev1() {
            0
        } else {
            self.status
        }
    }

    fn busy(&mut self, until: u64, next: Next) {
        self.status = BSY;
        self.xfer = Xfer::None;
        self.busy_until = Some(until);
        self.next = next;
    }

    fn begin_reset(&mut self) {
        self.status = BSY;
        self.busy_until = None;
        self.xfer = Xfer::None;
        self.irq = false;
        self.eight_bit = false;
    }

    /// The task file after a reset or a diagnostic.
    fn signature(&mut self) {
        self.error = DIAG_OK;
        self.count = 1;
        self.addr = [1, 0, 0];
        self.head = 0;
    }

    /// Device control: nIEN, and SRST, which holds the card in reset while
    /// it's high, then BSY for t_reset_ns after it goes low.
    fn device_control(&mut self, v: u8, now: u64) {
        self.nien = v & NIEN != 0;
        let srst = v & SRST != 0;
        if srst && !self.srst {
            self.begin_reset();
        } else if !srst && self.srst {
            self.busy(now.saturating_add(self.t_reset_ns), Next::Ready);
        }
        self.srst = srst;
    }

    fn command(&mut self, c: u8, now: u64) {
        // EXECUTE DEVICE DIAGNOSTIC goes to both devices, so device 0 runs
        // it whatever DEV says.
        if self.dev1() && c != 0x90 {
            return;
        }
        self.irq = false;
        self.error = 0;
        let done = Next::Done {
            irq: true,
            err: false,
        };
        let count = if self.count == 0 {
            256
        } else {
            self.count as u32
        };
        let next = match c {
            0xEC => self.data_command(Cmd::Identify, 1, true),
            0x20 | 0x21 => self.data_command(Cmd::Read, count, true),
            // no interrupt before the first sector of a write
            0x30 | 0x31 => self.data_command(Cmd::Write, count, false),
            0x40 | 0x41 => self.data_command(Cmd::Verify, count, true),
            0xEF => {
                match self.features {
                    0x01 => self.eight_bit = true,
                    0x81 => self.eight_bit = false,
                    _ => {}
                }
                done
            }
            // INITIALIZE DEVICE PARAMETERS: accepted, but the geometry stays
            0x91 => done,
            0x90 => {
                self.signature();
                done
            }
            // CHECK POWER MODE: active
            0xE5 | 0x98 => {
                self.count = 0xFF;
                done
            }
            _ => {
                self.error = ABRT;
                Next::Done {
                    irq: true,
                    err: true,
                }
            }
        };
        self.busy(now.saturating_add(self.t_cmd_ns), next);
    }

    fn data_command(&mut self, cmd: Cmd, sectors: u32, irq: bool) -> Next {
        self.cmd = cmd;
        self.left = sectors;
        Next::Sector { irq }
    }

    /// The address in the task file as a sector number, if it's on the
    /// card: LBA, or CHS within the geometry.
    fn address(&self) -> Option<usize> {
        let [a0, a1, a2] = self.addr.map(|b| b as u32);
        let h = (self.head & 0x0F) as u32;
        let lba = if self.head & LBA != 0 {
            (h << 24) | (a2 << 16) | (a1 << 8) | a0
        } else {
            let c = (a2 << 8) | a1;
            if a0 == 0 || a0 > self.spt || c >= self.cyls {
                return None;
            }
            (c * HEADS + h) * self.spt + a0 - 1
        };
        (lba < self.sectors()).then_some(lba as usize)
    }

    /// Move the address in the task file on to the next sector.
    fn step_address(&mut self) {
        let [a0, a1, a2] = self.addr.map(|b| b as u32);
        let h = (self.head & 0x0F) as u32;
        let (a, h) = if self.head & LBA != 0 {
            let lba = ((h << 24) | (a2 << 16) | (a1 << 8) | a0) + 1;
            (lba & 0xFF_FFFF, (lba >> 24) & 0x0F)
        } else {
            let (mut s, mut h, mut c) = (a0 + 1, h, (a2 << 8) | a1);
            if s > self.spt {
                s = 1;
                h += 1;
                if h >= HEADS {
                    h = 0;
                    c += 1;
                }
            }
            ((c << 8) | s, h)
        };
        self.addr = [a as u8, (a >> 8) as u8, (a >> 16) as u8];
        self.head = (self.head & 0xF0) | h as u8;
    }

    fn fail(&mut self, error: u8) {
        self.error = error;
        self.status = DRDY | DSC | ERR;
        self.irq = true;
    }

    /// BSY has ended on the way to the command's next sector.
    fn start_sector(&mut self, irq: bool) {
        if self.cmd == Cmd::Identify {
            self.buf = self.identify();
        } else {
            let Some(lba) = self.address() else {
                return self.fail(IDNF);
            };
            self.lba = lba;
            match self.cmd {
                Cmd::Read => self
                    .buf
                    .copy_from_slice(&self.image[lba * SECTOR..(lba + 1) * SECTOR]),
                Cmd::Verify => return self.verify(),
                _ => {}
            }
        }
        self.xfer = if self.cmd == Cmd::Write {
            Xfer::Out
        } else {
            Xfer::In
        };
        self.pos = 0;
        self.status = DRDY | DSC | DRQ;
        self.irq |= irq;
    }

    /// READ VERIFY: check each sector is there, all at once.
    fn verify(&mut self) {
        loop {
            if self.address().is_none() {
                return self.fail(IDNF);
            }
            self.left -= 1;
            self.count = self.count.wrapping_sub(1);
            if self.left == 0 {
                break;
            }
            self.step_address();
        }
        self.status = DRDY | DSC;
        self.irq = true;
    }

    fn read_data(&mut self, now: u64) -> u16 {
        if self.xfer != Xfer::In {
            return 0xFFFF;
        }
        let v = if self.eight_bit {
            0xFF00 | self.buf[self.pos] as u16
        } else {
            u16::from_le_bytes([self.buf[self.pos], self.buf[self.pos + 1]])
        };
        self.moved(now);
        v
    }

    fn write_data(&mut self, v: u16, now: u64) {
        if self.xfer != Xfer::Out {
            return;
        }
        if self.eight_bit {
            self.buf[self.pos] = v as u8;
        } else {
            self.buf[self.pos..self.pos + 2].copy_from_slice(&v.to_le_bytes());
        }
        self.moved(now);
    }

    /// A data access has moved a byte or a word. After a sector's last,
    /// a written sector goes to the image, the sector count and address
    /// move on, and the card is busy before the next sector or the end.
    fn moved(&mut self, now: u64) {
        self.pos += if self.eight_bit { 1 } else { 2 };
        if self.pos < SECTOR {
            return;
        }
        let write = self.xfer == Xfer::Out;
        if write {
            let at = self.lba * SECTOR;
            self.image[at..at + SECTOR].copy_from_slice(&self.buf);
        }
        self.left -= 1;
        if self.cmd != Cmd::Identify {
            self.count = self.count.wrapping_sub(1);
        }
        let next = if self.left > 0 {
            self.step_address();
            Next::Sector { irq: true }
        } else {
            // the end of a read has no interrupt; the end of a write has
            Next::Done {
                irq: write,
                err: false,
            }
        };
        self.busy(now.saturating_add(self.t_sector_ns), next);
    }

    /// IDENTIFY DEVICE: 256 words, low byte first, with strings two
    /// characters to a word, the first in the high byte.
    fn identify(&self) -> [u8; SECTOR] {
        let mut w = [0u16; SECTOR / 2];
        let total = self.sectors();
        let chs = self.cyls * HEADS * self.spt;
        w[0] = 0x848A; // a CompactFlash card
        w[1] = self.cyls as u16;
        w[3] = HEADS as u16;
        w[6] = self.spt as u16;
        w[7] = (total >> 16) as u16; // sectors on the card, CF order
        w[8] = total as u16;
        put_string(&mut w[10..20], SERIAL);
        put_string(&mut w[23..27], FIRMWARE);
        put_string(&mut w[27..47], MODEL);
        w[47] = 0x8001; // READ/WRITE MULTIPLE: one sector
        w[49] = 0x0200; // LBA
        w[53] = 0x0001; // words 54-58 are valid
        w[54] = self.cyls as u16;
        w[55] = HEADS as u16;
        w[56] = self.spt as u16;
        w[57] = chs as u16;
        w[58] = (chs >> 16) as u16;
        w[60] = total as u16; // sectors addressable by LBA
        w[61] = (total >> 16) as u16;
        let mut out = [0; SECTOR];
        for (i, x) in w.iter().enumerate() {
            out[2 * i..2 * i + 2].copy_from_slice(&x.to_le_bytes());
        }
        out
    }
}

/// An ATA string, padded with spaces.
fn put_string(words: &mut [u16], s: &str) {
    let b = s.as_bytes();
    let c = |i: usize| *b.get(i).unwrap_or(&b' ') as u16;
    for (i, w) in words.iter_mut().enumerate() {
        *w = (c(2 * i) << 8) | c(2 * i + 1);
    }
}
