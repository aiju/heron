//! The CompactFlash model: the task file, PIO transfers in both widths,
//! addressing, errors, and the BSY/DRQ/INTRQ sequence.

use devices::cf::{CfCard, SECTOR};

const DATA: u8 = 0;
const ERROR: u8 = 1;
const FEATURES: u8 = 1;
const COUNT: u8 = 2;
const LBA0: u8 = 3;
const LBA1: u8 = 4;
const LBA2: u8 = 5;
const HEAD: u8 = 6;
const STATUS: u8 = 7;
const COMMAND: u8 = 7;
const CONTROL: u8 = 6; // CS1: alternate status / device control

/// A card of `n` sectors, each filled with its number and the offset.
fn card(n: usize) -> CfCard {
    let mut image = vec![0; n * SECTOR];
    for (i, b) in image.iter_mut().enumerate() {
        *b = ((i / SECTOR) as u8).wrapping_mul(7) ^ (i % SECTOR) as u8;
    }
    CfCard::new(image)
}

fn sector(c: &CfCard, n: usize) -> &[u8] {
    &c.image()[n * SECTOR..(n + 1) * SECTOR]
}

/// The host side, with its own clock.
struct Host {
    cf: CfCard,
    now: u64,
}

impl Host {
    fn new(cf: CfCard) -> Host {
        Host { cf, now: 0 }
    }

    fn rd(&mut self, reg: u8) -> u8 {
        let v = self.cf.read(false, reg, self.now);
        if reg != DATA {
            assert_eq!(v >> 8, 0xFF);
        }
        v as u8
    }

    fn wr(&mut self, reg: u8, v: u8) {
        self.cf.write(false, reg, v as u16, self.now);
    }

    fn alt(&mut self) -> u8 {
        self.cf.read(true, CONTROL, self.now) as u8
    }

    fn control(&mut self, v: u8) {
        self.cf.write(true, CONTROL, v as u16, self.now);
    }

    /// Wait until BSY ends; returns how long it took.
    fn wait(&mut self) -> u64 {
        let start = self.now;
        if let Some(t) = self.cf.next_event_ns() {
            self.now = self.now.max(t);
        }
        assert_eq!(self.alt() & 0x80, 0);
        self.now - start
    }

    /// Issue a command with an LBA address and sector count.
    fn lba_command(&mut self, cmd: u8, lba: u32, count: u8) {
        self.wr(COUNT, count);
        self.wr(LBA0, lba as u8);
        self.wr(LBA1, (lba >> 8) as u8);
        self.wr(LBA2, (lba >> 16) as u8);
        self.wr(HEAD, 0xE0 | ((lba >> 24) & 15) as u8);
        self.wr(COMMAND, cmd);
    }

    /// Read a sector's data in the current width.
    fn read_sector(&mut self) -> Vec<u8> {
        let mut out = Vec::new();
        while out.len() < SECTOR {
            let v = self.cf.read(false, DATA, self.now);
            if self.cf.eight_bit() {
                out.push(v as u8);
            } else {
                out.extend(v.to_le_bytes());
            }
        }
        out
    }

    fn write_sector(&mut self, data: &[u8]) {
        if self.cf.eight_bit() {
            for &b in data {
                self.cf.write(false, DATA, b as u16, self.now);
            }
        } else {
            for w in data.chunks(2) {
                let v = u16::from_le_bytes([w[0], w[1]]);
                self.cf.write(false, DATA, v, self.now);
            }
        }
    }

    fn address(&mut self) -> u32 {
        (((self.rd(HEAD) & 15) as u32) << 24)
            | ((self.rd(LBA2) as u32) << 16)
            | ((self.rd(LBA1) as u32) << 8)
            | self.rd(LBA0) as u32
    }
}

fn ata_string(id: &[u8], words: std::ops::Range<usize>) -> String {
    words
        .flat_map(|w| [id[2 * w + 1], id[2 * w]])
        .map(|b| b as char)
        .collect()
}

fn word(id: &[u8], w: usize) -> u16 {
    u16::from_le_bytes([id[2 * w], id[2 * w + 1]])
}

#[test]
fn identify_device() {
    let mut h = Host::new(card(2000));
    assert_eq!(h.rd(STATUS), 0x50);
    h.wr(HEAD, 0xA0);
    h.wr(COMMAND, 0xEC);
    // busy for t_cmd_ns, then DRQ and an interrupt
    assert_eq!(h.alt(), 0x80);
    assert_eq!(h.cf.next_event_ns(), Some(2000));
    h.now = 1999;
    assert_eq!(h.alt(), 0x80);
    assert!(!h.cf.intrq());
    // (INTRQ is as of the last access or advance)
    h.now = 2000;
    assert!(!h.cf.intrq());
    h.cf.advance(h.now);
    assert!(h.cf.intrq());
    assert_eq!(h.alt(), 0x58);
    assert!(h.cf.intrq());
    assert_eq!(h.rd(STATUS), 0x58);
    assert!(!h.cf.intrq());
    let id = h.read_sector();
    assert_eq!(word(&id, 0), 0x848A);
    assert_eq!(ata_string(&id, 27..47).trim_end(), "HERON SIMULATED CF");
    assert_eq!(ata_string(&id, 27..47).len(), 40);
    assert!(!ata_string(&id, 10..20).trim().is_empty());
    assert!(!ata_string(&id, 23..27).trim().is_empty());
    assert_eq!(word(&id, 47), 0x8001);
    assert_ne!(word(&id, 49) & 0x0200, 0);
    // 2000 sectors: 3 cylinders of 16 heads and 32 sectors
    assert_eq!([word(&id, 1), word(&id, 3), word(&id, 6)], [3, 16, 32]);
    assert_eq!([word(&id, 54), word(&id, 55), word(&id, 56)], [3, 16, 32]);
    assert_eq!((word(&id, 57), word(&id, 58)), (3 * 16 * 32, 0));
    assert_eq!((word(&id, 60), word(&id, 61)), (2000, 0));
    // then busy for t_sector_ns, and done without an interrupt
    assert_eq!(h.alt(), 0x80);
    assert_eq!(h.wait(), 1000);
    assert_eq!(h.rd(STATUS), 0x50);
    assert!(!h.cf.intrq());
}

#[test]
fn geometry_of_a_big_card() {
    // 512 MB: 63 sectors per track
    let mut h = Host::new(CfCard::new(vec![0; 1 << 29]));
    h.wr(COMMAND, 0xEC);
    h.wait();
    let id = h.read_sector();
    let sectors = (1u32 << 29) / 512;
    assert_eq!(word(&id, 6), 63);
    assert_eq!(word(&id, 1) as u32, sectors / (16 * 63));
    assert_eq!(
        (word(&id, 60), word(&id, 61)),
        (sectors as u16, (sectors >> 16) as u16)
    );
}

#[test]
fn eight_bit_mode() {
    let mut h = Host::new(card(4));
    assert!(!h.cf.eight_bit());
    h.wr(FEATURES, 0x01);
    h.wr(COMMAND, 0xEF);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
    assert!(h.cf.eight_bit());
    h.wr(COMMAND, 0xEC);
    h.wait();
    // one byte per access, low byte first, with the upper byte high
    assert_eq!(h.cf.read(false, DATA, h.now), 0xFF8A);
    assert_eq!(h.cf.read(false, DATA, h.now), 0xFF84);
    for _ in 2..SECTOR {
        h.cf.read(false, DATA, h.now);
    }
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
    // a write in 8-bit mode
    let data: Vec<u8> = (0..SECTOR).map(|i| (i * 3) as u8).collect();
    h.lba_command(0x30, 2, 1);
    h.wait();
    h.write_sector(&data);
    h.wait();
    assert_eq!(sector(&h.cf, 2), &data[..]);
    // and back to 16 bits
    h.wr(FEATURES, 0x81);
    h.wr(COMMAND, 0xEF);
    h.wait();
    assert!(!h.cf.eight_bit());
    h.lba_command(0x20, 2, 1);
    h.wait();
    assert_eq!(h.cf.read(false, DATA, h.now), 0x0300);
    // other SET FEATURES subcommands are accepted
    h.wr(FEATURES, 0x55);
    h.wr(COMMAND, 0xEF);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
}

#[test]
fn read_sectors_lba() {
    let mut h = Host::new(card(100));
    let want: Vec<Vec<u8>> = (0..100).map(|n| sector(&h.cf, n).to_vec()).collect();
    h.lba_command(0x20, 42, 1);
    assert_eq!(h.wait(), 2000);
    assert!(h.cf.intrq());
    assert_eq!(h.rd(STATUS), 0x58);
    assert_eq!(h.read_sector(), want[42]);
    assert_eq!(h.wait(), 1000);
    assert_eq!(h.rd(STATUS), 0x50);
    assert!(!h.cf.intrq());
    // three sectors: an interrupt and DRQ for each, BSY between
    h.lba_command(0x21, 97, 3);
    for n in 97..100 {
        h.wait();
        assert!(h.cf.intrq());
        assert_eq!(h.rd(STATUS), 0x58);
        assert_eq!(h.address(), n);
        assert_eq!(h.read_sector(), want[n as usize]);
        assert_eq!(h.alt(), 0x80);
    }
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
    // the address of the last sector, and a count of 0
    assert_eq!(h.address(), 99);
    assert_eq!(h.rd(COUNT), 0);
    // a count of 0 is 256 sectors
    let mut h = Host::new(card(300));
    h.lba_command(0x20, 10, 0);
    for n in 0..256 {
        h.wait();
        assert_eq!(h.rd(STATUS), 0x58, "sector {n}");
        h.read_sector();
    }
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
    assert_eq!(h.address(), 265);
}

#[test]
fn read_sectors_chs() {
    let mut h = Host::new(card(2000));
    // cylinder 1, head 2, sector 5: (1 * 16 + 2) * 32 + 4
    let lba = (16 + 2) * 32 + 4;
    let want: Vec<u8> = (lba..lba + 30)
        .flat_map(|n| sector(&h.cf, n).to_vec())
        .collect();
    h.wr(COUNT, 30);
    h.wr(LBA0, 5);
    h.wr(LBA1, 1);
    h.wr(LBA2, 0);
    h.wr(HEAD, 0xA2);
    h.wr(COMMAND, 0x20);
    let mut got = Vec::new();
    for _ in 0..30 {
        h.wait();
        assert_eq!(h.rd(STATUS), 0x58);
        got.extend(h.read_sector());
    }
    assert_eq!(got, want);
    // the last sector read: 5 + 29 = 34 is sector 2 of head 3
    h.wait();
    assert_eq!(
        [h.rd(LBA0), h.rd(LBA1), h.rd(LBA2), h.rd(HEAD)],
        [2, 1, 0, 0xA3]
    );
    // past the last head: on to the next cylinder
    h.wr(COUNT, 2);
    h.wr(LBA0, 32);
    h.wr(LBA1, 0);
    h.wr(HEAD, 0xAF);
    h.wr(COMMAND, 0x20);
    for n in [16 * 32 - 1, 16 * 32] {
        h.wait();
        assert_eq!(h.read_sector(), sector(&h.cf, n));
    }
    h.wait();
    assert_eq!([h.rd(LBA0), h.rd(LBA1), h.rd(HEAD)], [1, 1, 0xA0]);
}

#[test]
fn write_sectors() {
    let mut h = Host::new(card(50));
    let before = h.cf.image().to_vec();
    let data: Vec<u8> = (0..3 * SECTOR).map(|i| (i * 13 + 5) as u8).collect();
    h.lba_command(0x30, 20, 3);
    // DRQ after t_cmd_ns, with no interrupt for the first sector
    assert_eq!(h.wait(), 2000);
    assert!(!h.cf.intrq());
    for (i, chunk) in data.chunks(SECTOR).enumerate() {
        assert_eq!(h.rd(STATUS), 0x58);
        assert_eq!(h.address(), 20 + i as u32);
        h.write_sector(chunk);
        // busy while it's written, then an interrupt
        assert_eq!(h.alt(), 0x80);
        assert!(!h.cf.intrq());
        assert_eq!(h.wait(), 1000);
        assert!(h.cf.intrq());
    }
    assert_eq!(h.rd(STATUS), 0x50);
    assert!(!h.cf.intrq());
    assert_eq!(&h.cf.image()[20 * SECTOR..23 * SECTOR], &data[..]);
    assert_eq!(&h.cf.image()[..20 * SECTOR], &before[..20 * SECTOR]);
    assert_eq!(&h.cf.image()[23 * SECTOR..], &before[23 * SECTOR..]);
    // and it reads back
    h.lba_command(0x20, 21, 1);
    h.wait();
    assert_eq!(h.read_sector(), &data[SECTOR..2 * SECTOR]);
}

#[test]
fn partial_image_is_padded() {
    let cf = CfCard::new(vec![0xAA; 1000]);
    assert_eq!(cf.image().len(), 1024);
    assert_eq!(&cf.image()[1000..], &[0; 24]);
}

#[test]
fn idnf_past_the_end() {
    let mut h = Host::new(card(10));
    h.lba_command(0x20, 10, 1);
    h.wait();
    assert!(h.cf.intrq());
    assert_eq!(h.rd(STATUS), 0x51);
    assert_eq!(h.rd(ERROR), 0x10);
    // a multi-sector read stops at the first sector that isn't there
    h.lba_command(0x20, 8, 4);
    for _ in 0..2 {
        h.wait();
        assert_eq!(h.rd(STATUS), 0x58);
        h.read_sector();
    }
    h.wait();
    assert_eq!(h.rd(STATUS), 0x51);
    assert_eq!(h.rd(ERROR), 0x10);
    assert_eq!((h.address(), h.rd(COUNT)), (10, 2));
    // writes too, before taking any data
    h.lba_command(0x30, 12, 1);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x51);
    // a CHS sector of 0, or past the track
    h.wr(LBA0, 0);
    h.wr(LBA1, 0);
    h.wr(LBA2, 0);
    h.wr(HEAD, 0xA0);
    h.wr(COMMAND, 0x20);
    h.wait();
    assert_eq!(h.rd(ERROR), 0x10);
    h.wr(LBA0, 33);
    h.wr(COMMAND, 0x20);
    h.wait();
    assert_eq!(h.rd(ERROR), 0x10);
    // a successful command clears the error
    h.lba_command(0x40, 0, 10);
    h.wait();
    assert!(h.cf.intrq());
    assert_eq!(h.rd(STATUS), 0x50);
    assert_eq!(h.rd(ERROR), 0);
    assert_eq!((h.address(), h.rd(COUNT)), (9, 0));
    // read verify past the end
    h.lba_command(0x41, 5, 10);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x51);
    assert_eq!(h.rd(ERROR), 0x10);
    assert_eq!(h.address(), 10);
}

#[test]
fn abort_and_other_commands() {
    let mut h = Host::new(card(10));
    h.wr(COMMAND, 0x00);
    assert_eq!(h.alt(), 0x80);
    h.wait();
    assert!(h.cf.intrq());
    assert_eq!(h.rd(STATUS), 0x51);
    assert_eq!(h.rd(ERROR), 0x04);
    // CHECK POWER MODE: active
    h.wr(COUNT, 0);
    h.wr(COMMAND, 0xE5);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
    assert_eq!(h.rd(COUNT), 0xFF);
    // INITIALIZE DEVICE PARAMETERS is accepted
    h.wr(COMMAND, 0x91);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x50);
    // EXECUTE DEVICE DIAGNOSTIC: code 1 in the error register, not ERR
    h.wr(COMMAND, 0x90);
    h.wait();
    assert!(h.cf.intrq());
    assert_eq!(h.rd(STATUS), 0x50);
    assert_eq!(h.rd(ERROR), 0x01);
    assert_eq!(
        [h.rd(COUNT), h.rd(LBA0), h.rd(LBA1), h.rd(LBA2)],
        [1, 1, 0, 0]
    );
}

#[test]
fn busy_hides_the_task_file() {
    let mut h = Host::new(card(10));
    h.wr(COUNT, 5);
    h.wr(COMMAND, 0xEC);
    // reads return the status, writes are ignored
    for reg in 0..8 {
        assert_eq!(h.cf.read(false, reg, h.now), 0xFF80);
    }
    h.wr(COUNT, 9);
    h.wr(COMMAND, 0x00);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x58);
    assert_eq!(h.rd(COUNT), 5);
    // the data register reads high outside DRQ; other CS1 registers too
    h.read_sector();
    h.wait();
    assert_eq!(h.cf.read(false, DATA, h.now), 0xFFFF);
    assert_eq!(h.cf.read(true, 7, h.now), 0x00FF | 0xFF00);
}

#[test]
fn nien_masks_intrq() {
    let mut h = Host::new(card(10));
    h.control(0x02);
    h.wr(COMMAND, 0x91);
    h.wait();
    assert!(!h.cf.intrq());
    // the interrupt is still pending underneath
    h.control(0x00);
    assert!(h.cf.intrq());
    // alternate status doesn't clear it; status does
    h.alt();
    assert!(h.cf.intrq());
    h.rd(STATUS);
    assert!(!h.cf.intrq());
    // writing a command clears it too
    h.wr(COMMAND, 0x91);
    h.wait();
    assert!(h.cf.intrq());
    h.wr(COMMAND, 0x91);
    assert!(!h.cf.intrq());
}

#[test]
fn software_reset() {
    let mut h = Host::new(card(10));
    h.wr(FEATURES, 0x01);
    h.wr(COMMAND, 0xEF);
    h.wait();
    h.lba_command(0x20, 3, 2);
    h.wait();
    assert_eq!(h.rd(STATUS), 0x58);
    // SRST: busy as long as it's high, and t_reset_ns after
    h.control(0x06);
    assert_eq!(h.alt(), 0x80);
    assert_eq!(h.cf.next_event_ns(), None);
    h.now += 1_000_000;
    assert_eq!(h.alt(), 0x80);
    h.control(0x02);
    assert_eq!(h.cf.next_event_ns(), Some(h.now + 10_000));
    assert_eq!(h.wait(), 10_000);
    // ready, with the signature, 16-bit transfers, nIEN as written, and
    // the read abandoned
    assert_eq!(h.rd(STATUS), 0x50);
    assert_eq!(h.rd(ERROR), 0x01);
    assert_eq!(
        [h.rd(COUNT), h.rd(LBA0), h.rd(LBA1), h.rd(LBA2), h.rd(HEAD)],
        [1, 1, 0, 0, 0]
    );
    assert!(!h.cf.eight_bit());
    assert_eq!(h.cf.read(false, DATA, h.now), 0xFFFF);
    h.wr(COMMAND, 0x91);
    h.wait();
    assert!(!h.cf.intrq());
}

#[test]
fn hardware_reset() {
    let mut h = Host::new(card(10));
    h.control(0x02);
    h.wr(FEATURES, 0x01);
    h.wr(COMMAND, 0xEF);
    h.wait();
    h.cf.t_reset_ns = 5000;
    h.cf.reset(h.now);
    assert_eq!(h.alt(), 0x80);
    assert_eq!(h.wait(), 5000);
    assert_eq!(h.rd(STATUS), 0x50);
    assert!(!h.cf.eight_bit());
    // nIEN cleared
    h.wr(COMMAND, 0x91);
    h.wait();
    assert!(h.cf.intrq());
}

#[test]
fn device_1_is_absent() {
    let mut h = Host::new(card(10));
    h.wr(HEAD, 0xB0);
    assert_eq!(h.rd(STATUS), 0x00);
    assert_eq!(h.alt(), 0x00);
    // its commands are ignored, but the task file is shared
    h.wr(COUNT, 3);
    h.wr(COMMAND, 0xEC);
    assert_eq!(h.cf.next_event_ns(), None);
    assert_eq!(h.rd(COUNT), 3);
    h.wr(HEAD, 0xA0);
    assert_eq!(h.rd(STATUS), 0x50);
}

#[test]
fn timing_is_adjustable() {
    let mut h = Host::new(card(10));
    h.cf.t_cmd_ns = 50;
    h.cf.t_sector_ns = 7;
    h.lba_command(0x20, 0, 2);
    assert_eq!(h.wait(), 50);
    h.read_sector();
    assert_eq!(h.wait(), 7);
    // advance alone moves it on
    h.read_sector();
    h.cf.advance(h.now + 7);
    assert_eq!(h.cf.next_event_ns(), None);
    assert_eq!(h.cf.read(true, CONTROL, h.now + 7), 0xFF50);
}
